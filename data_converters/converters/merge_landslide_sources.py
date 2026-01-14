"""
Merge all landslide sources into unified global catalog.

Sources:
  - DesInventar: 32,044 landslides (33 countries, 1700-2104)
  - NASA GLC: 11,033 landslides (140 countries, 1988-2017)
  - NOAA Debris Flows: 2,502 events (39 US states, 1996-2025)

Output:
  - landslides/events.parquet - Unified landslide catalog
  - landslides/metadata.json - Combined country coverage

Strategy:
  - Deduplicate on date (±7 days), location (±50km), country
  - Prefer DesInventar (most structured), then NASA GLC, then NOAA
  - Track source attribution
"""
import pandas as pd
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
import json
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2

# Configuration
DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/global")
OUTPUT_DIR = DATA_DIR / "landslides"

# Deduplication parameters
DATE_TOLERANCE_DAYS = 7
LOCATION_TOLERANCE_KM = 50


def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two points in kilometers."""
    if pd.isna(lat1) or pd.isna(lon1) or pd.isna(lat2) or pd.isna(lon2):
        return float('inf')

    R = 6371  # Earth radius in km

    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))

    return R * c


def load_desinventar():
    """Load DesInventar landslides."""
    print("Loading DesInventar landslides...")

    df = pd.read_parquet(DATA_DIR / "desinventar" / "events.parquet")

    # Filter for landslides only
    landslides = df[df['disaster_type'] == 'landslide'].copy()

    # Standardize schema
    landslides['source'] = 'DesInventar'
    landslides['source_id'] = landslides['event_id']

    # Add event_name column (use location_name)
    landslides['event_name'] = landslides['location_name']

    # Select and rename columns - use country_code as loc_id
    result = landslides[['event_id', 'timestamp', 'year', 'country_code', 'latitude', 'longitude',
                        'deaths', 'injuries', 'missing', 'affected', 'houses_destroyed',
                        'damage_usd', 'event_name', 'source', 'source_id']].copy()

    result = result.rename(columns={'country_code': 'loc_id'})

    print(f"  Loaded {len(result):,} DesInventar landslides")
    print(f"  Countries: {result['loc_id'].nunique()}")

    return result


def load_nasa_glc():
    """Load NASA Global Landslide Catalog."""
    print("\nLoading NASA GLC landslides...")

    df = pd.read_parquet(DATA_DIR / "nasa_landslides" / "events.parquet")

    df['source'] = 'NASA_GLC'
    df['source_id'] = df['event_id']

    # Add missing columns
    df['missing'] = pd.NA
    df['affected'] = pd.NA
    df['houses_destroyed'] = pd.NA
    df['damage_usd'] = pd.NA
    df['event_name'] = df['event_title']

    # Select columns and rename
    result = df[['event_id', 'timestamp', 'year', 'country_code', 'latitude', 'longitude',
                'deaths', 'injuries', 'missing', 'affected', 'houses_destroyed',
                'damage_usd', 'event_name', 'source', 'source_id']].copy()

    result = result.rename(columns={'country_code': 'loc_id'})

    print(f"  Loaded {len(result):,} NASA GLC landslides")
    print(f"  Countries: {result['loc_id'].nunique()}")

    return result


def load_noaa():
    """Load NOAA debris flows."""
    print("\nLoading NOAA debris flows...")

    df = pd.read_parquet(DATA_DIR / "noaa_debris_flows" / "events.parquet")

    df['source'] = 'NOAA'
    df['source_id'] = df['event_id']

    # Calculate centroid for location matching
    df['latitude_calc'] = df[['latitude_begin', 'latitude_end']].mean(axis=1)
    df['longitude_calc'] = df[['longitude_begin', 'longitude_end']].mean(axis=1)

    # Add missing columns
    df['missing'] = pd.NA
    df['affected'] = pd.NA
    df['houses_destroyed'] = pd.NA
    df['event_name'] = df['begin_location']

    result = df[['event_id', 'timestamp', 'year', 'loc_id', 'latitude_calc', 'longitude_calc',
                'deaths', 'injuries', 'missing', 'affected', 'houses_destroyed',
                'damage_total_usd', 'event_name', 'source', 'source_id']].copy()

    result = result.rename(columns={
        'latitude_calc': 'latitude',
        'longitude_calc': 'longitude',
        'damage_total_usd': 'damage_usd'
    })

    print(f"  Loaded {len(result):,} NOAA debris flows")
    print(f"  States: {result['loc_id'].nunique()}")

    return result


def find_duplicates(primary_df, secondary_df, source_name):
    """Find duplicate events between two datasets."""
    print(f"\nFinding duplicates: {source_name}...")

    duplicates = []
    matched_secondary = set()

    # Convert to records for faster iteration
    for idx in range(len(primary_df)):
        primary = primary_df.iloc[idx]

        # Skip if missing critical data
        if pd.isna(primary['timestamp']):
            continue
        if pd.isna(primary['loc_id']) or primary['loc_id'] == '':
            continue

        # Filter secondary by country
        country_match = secondary_df[secondary_df['loc_id'] == primary['loc_id']]

        if len(country_match) == 0:
            continue

        # Filter by date range (±7 days)
        date_min = primary['timestamp'] - timedelta(days=DATE_TOLERANCE_DAYS)
        date_max = primary['timestamp'] + timedelta(days=DATE_TOLERANCE_DAYS)

        date_match = country_match[
            (country_match['timestamp'] >= date_min) &
            (country_match['timestamp'] <= date_max)
        ]

        if len(date_match) == 0:
            continue

        # Check location distance
        for sec_idx, secondary in date_match.iterrows():
            if sec_idx in matched_secondary:
                continue

            distance = haversine_distance(
                primary['latitude'], primary['longitude'],
                secondary['latitude'], secondary['longitude']
            )

            if distance <= LOCATION_TOLERANCE_KM:
                duplicates.append({
                    'primary_id': primary['event_id'],
                    'secondary_id': secondary['event_id'],
                    'date_diff_days': abs((primary['timestamp'] - secondary['timestamp']).days),
                    'distance_km': distance
                })
                matched_secondary.add(sec_idx)
                break

    print(f"  Found {len(duplicates)} duplicates")
    print(f"  {len(matched_secondary)} {source_name} events matched")

    return duplicates, matched_secondary


def merge_sources():
    """Merge all landslide sources with deduplication."""
    print("=" * 70)
    print("Unified Landslide Catalog - Merging Sources")
    print("=" * 70)
    print()

    # Load all sources
    desinventar = load_desinventar()
    nasa_glc = load_nasa_glc()
    noaa = load_noaa()

    print("\n" + "=" * 70)
    print("Deduplication")
    print("=" * 70)

    # Start with DesInventar as base (highest priority)
    unified = desinventar.copy()
    unified['sources'] = 'DesInventar'

    print(f"\nBase catalog: {len(unified):,} DesInventar events")

    # Deduplicate NASA GLC against DesInventar
    nasa_dupes, nasa_matched = find_duplicates(desinventar, nasa_glc, 'NASA GLC')

    # Add non-duplicate NASA GLC events
    nasa_unmatched = nasa_glc[~nasa_glc.index.isin(nasa_matched)].copy()
    nasa_unmatched['sources'] = 'NASA_GLC'

    unified = pd.concat([unified, nasa_unmatched], ignore_index=True)
    print(f"  Added {len(nasa_unmatched):,} unique NASA GLC events")
    print(f"  Running total: {len(unified):,} events")

    # Update sources for matched DesInventar events
    if len(nasa_dupes) > 0:
        nasa_dupe_df = pd.DataFrame(nasa_dupes)
        matched_primary_ids = set(nasa_dupe_df['primary_id'])
        unified.loc[unified['event_id'].isin(matched_primary_ids), 'sources'] = 'DesInventar+NASA_GLC'

    # Deduplicate NOAA against combined (DesInventar + NASA GLC)
    noaa_dupes, noaa_matched = find_duplicates(unified, noaa, 'NOAA')

    # Add non-duplicate NOAA events
    noaa_unmatched = noaa[~noaa.index.isin(noaa_matched)].copy()
    noaa_unmatched['sources'] = 'NOAA'

    unified = pd.concat([unified, noaa_unmatched], ignore_index=True)
    print(f"  Added {len(noaa_unmatched):,} unique NOAA events")
    print(f"  Final total: {len(unified):,} unique landslide events")

    # Update sources for matched events
    if len(noaa_dupes) > 0:
        noaa_dupe_df = pd.DataFrame(noaa_dupes)
        matched_primary_ids = set(noaa_dupe_df['primary_id'])
        for event_id in matched_primary_ids:
            current_sources = unified.loc[unified['event_id'] == event_id, 'sources'].values[0]
            if current_sources == 'DesInventar':
                unified.loc[unified['event_id'] == event_id, 'sources'] = 'DesInventar+NOAA'
            elif current_sources == 'NASA_GLC':
                unified.loc[unified['event_id'] == event_id, 'sources'] = 'NASA_GLC+NOAA'
            elif current_sources == 'DesInventar+NASA_GLC':
                unified.loc[unified['event_id'] == event_id, 'sources'] = 'All_Sources'

    # Sort by date
    unified = unified.sort_values('timestamp', ascending=False)

    # Print deduplication summary
    print("\n" + "=" * 70)
    print("Deduplication Summary")
    print("=" * 70)
    print(f"DesInventar:        32,044 landslides")
    print(f"NASA GLC:           11,033 landslides")
    print(f"NOAA:                2,502 debris flows")
    print(f"Total before:       45,579 events")
    print(f"Duplicates removed:  {45579 - len(unified):,}")
    print(f"Final unified:      {len(unified):,} unique events")
    print(f"Deduplication rate: {(45579 - len(unified)) / 45579 * 100:.1f}%")

    return unified, nasa_dupes, noaa_dupes


def create_metadata(unified):
    """Create metadata with country coverage."""
    print("\nCreating metadata...")

    # Country coverage
    country_stats = unified.groupby('loc_id').agg({
        'event_id': 'count',
        'deaths': 'sum',
        'injuries': 'sum',
        'damage_usd': 'sum',
        'year': ['min', 'max'],
        'sources': lambda x: list(x.unique())
    }).reset_index()

    country_stats.columns = ['loc_id', 'events', 'deaths', 'injuries',
                             'damage_usd', 'year_start', 'year_end', 'sources']

    # Convert to dict
    countries = {}
    for _, row in country_stats.iterrows():
        countries[row['loc_id']] = {
            'events': int(row['events']),
            'deaths': int(row['deaths']) if pd.notna(row['deaths']) else 0,
            'injuries': int(row['injuries']) if pd.notna(row['injuries']) else 0,
            'damage_usd': float(row['damage_usd']) if pd.notna(row['damage_usd']) else 0,
            'year_range': f"{int(row['year_start'])}-{int(row['year_end'])}",
            'sources': row['sources']
        }

    # Source breakdown
    source_counts = unified['sources'].value_counts().to_dict()

    metadata = {
        'source': 'Unified Global Landslide Catalog',
        'sources_merged': [
            'DesInventar (UNDRR)',
            'NASA Global Landslide Catalog (HDX)',
            'NOAA Storm Events Database'
        ],
        'conversion_date': datetime.now().isoformat(),
        'total_events': len(unified),
        'total_countries': len(countries),
        'date_range': {
            'start': int(unified['year'].min()),
            'end': int(unified['year'].max())
        },
        'impact_summary': {
            'events_with_deaths': int((unified['deaths'] > 0).sum()),
            'events_with_injuries': int((unified['injuries'] > 0).sum()),
            'total_deaths': int(unified['deaths'].sum()),
            'total_injuries': int(unified['injuries'].sum()),
            'total_damage_usd': float(unified['damage_usd'].sum())
        },
        'source_breakdown': source_counts,
        'countries': countries
    }

    return metadata


def save_parquet(df, output_path):
    """Save dataframe to parquet."""
    print(f"\nSaving to {output_path}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"  Size: {size_mb:.2f} MB, {len(df):,} rows")


def main():
    """Main merge workflow."""
    # Merge sources
    unified, nasa_dupes, noaa_dupes = merge_sources()

    # Create metadata
    metadata = create_metadata(unified)

    # Save outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    events_path = OUTPUT_DIR / "events.parquet"
    save_parquet(unified, events_path)

    metadata_path = OUTPUT_DIR / "metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"\nMetadata saved: {metadata_path}")

    # Print final summary
    print("\n" + "=" * 70)
    print("Unified Catalog Summary")
    print("=" * 70)
    print(f"Total unique events: {len(unified):,}")
    print(f"Countries: {len(metadata['countries'])}")
    print(f"Years: {metadata['date_range']['start']}-{metadata['date_range']['end']}")

    print(f"\nSource breakdown:")
    for source, count in sorted(metadata['source_breakdown'].items(),
                                key=lambda x: x[1], reverse=True):
        print(f"  {source}: {count:,}")

    print(f"\nImpact totals:")
    print(f"  Events with deaths: {metadata['impact_summary']['events_with_deaths']:,}")
    print(f"  Total deaths: {metadata['impact_summary']['total_deaths']:,}")
    print(f"  Total injuries: {metadata['impact_summary']['total_injuries']:,}")
    print(f"  Total damage: ${metadata['impact_summary']['total_damage_usd']:,.0f}")

    print(f"\nTop 10 countries by events:")
    top_countries = sorted(metadata['countries'].items(),
                          key=lambda x: x[1]['events'], reverse=True)[:10]
    for code, info in top_countries:
        sources_str = ', '.join(info['sources'])
        print(f"  {code}: {info['events']:,} events ({sources_str})")

    print("\n" + "=" * 70)
    print("COMPLETE!")
    print("=" * 70)

    return unified, metadata


if __name__ == "__main__":
    main()
