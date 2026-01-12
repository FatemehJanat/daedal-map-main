"""
Convert NOAA Significant Earthquake Database and merge with USGS data.

Creates a unified earthquake dataset combining:
1. NOAA Significant Earthquakes (2150 BC - present, ~6,600 major events)
2. USGS Earthquakes (1900 - present, ~1M events with detailed aftershock analysis)

The merger:
- Uses NOAA for pre-1900 historical earthquakes
- Uses USGS for 1900+ events (more complete, aftershock detection)
- Adds cross-event linking to tsunamis and volcanoes

Output: global/earthquakes/events.parquet (unified)

Usage:
    python convert_noaa_significant_earthquakes.py
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
import json
from datetime import datetime

# Add base utilities
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_converters.base import (
    get_water_body_loc_id,
    save_parquet,
)

# Paths
NOAA_RAW_PATH = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/noaa/significant_earthquakes/significant_earthquakes.json")
USGS_EVENTS_PATH = Path("C:/Users/Bryan/Desktop/county-map-data/global/usgs_earthquakes/events.parquet")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/global/earthquakes")

# Tsunami data for linking verification
TSUNAMI_PATH = Path("C:/Users/Bryan/Desktop/county-map-data/global/tsunamis/events.parquet")
VOLCANO_PATH = Path("C:/Users/Bryan/Desktop/county-map-data/global/smithsonian_volcanoes/events.parquet")


def load_noaa_earthquakes():
    """Load NOAA significant earthquakes from JSON."""
    print("\nLoading NOAA Significant Earthquakes...")

    with open(NOAA_RAW_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    events = data['events']
    print(f"  Loaded {len(events):,} events")

    return pd.DataFrame(events)


def load_usgs_earthquakes():
    """Load existing USGS earthquake events."""
    print("\nLoading USGS Earthquakes...")

    if not USGS_EVENTS_PATH.exists():
        print(f"  WARNING: USGS data not found at {USGS_EVENTS_PATH}")
        return None

    df = pd.read_parquet(USGS_EVENTS_PATH)
    print(f"  Loaded {len(df):,} events")
    print(f"  Year range: {df['year'].min()} to {df['year'].max()}")

    return df


def process_noaa_events(df):
    """Convert NOAA events to standard schema."""
    print("\nProcessing NOAA events...")

    # Build timestamp from year/month/day/hour/minute/second
    def build_timestamp(row):
        try:
            year = int(row.get('year', 0))
            # Handle negative years (BC)
            if year < 0:
                # Use a placeholder since pandas can't handle BC dates
                return None
            month = int(row.get('month', 1) or 1)
            day = int(row.get('day', 1) or 1)
            hour = int(row.get('hour', 0) or 0)
            minute = int(row.get('minute', 0) or 0)
            second = int(row.get('second', 0) or 0)

            # Clamp values to valid ranges
            month = max(1, min(12, month))
            day = max(1, min(28, day))  # Safe for all months
            hour = max(0, min(23, hour))
            minute = max(0, min(59, minute))
            second = max(0, min(59, second))

            return pd.Timestamp(year=year, month=month, day=day,
                              hour=hour, minute=minute, second=second)
        except:
            return None

    # Create output DataFrame
    out = pd.DataFrame({
        'event_id': df['id'].apply(lambda x: f"NOAA-SIG-{x}"),
        'timestamp': df.apply(build_timestamp, axis=1),
        'year': df['year'].astype(int),
        'latitude': df['latitude'].astype(float),
        'longitude': df['longitude'].astype(float),
        'magnitude': df['eqMagnitude'].astype(float),
        'depth_km': df['eqDepth'].astype(float),
        'place': df['locationName'],
        'country': df['country'],
        # Impact data
        'deaths': df['deaths'],
        'injuries': df['injuries'],
        'damage_millions': df['damageMillionsDollars'],
        'houses_destroyed': df['housesDestroyed'],
        # NOAA cross-links (internal IDs)
        'noaa_tsunami_id': df['tsunamiEventId'],
        'noaa_volcano_id': df['volcanoEventId'],
        # Intensity
        'intensity': df['intensity'],
        # Source tracking
        'source': 'noaa_significant'
    })

    # Assign water body loc_ids for offshore earthquakes
    print("  Assigning loc_ids...")
    loc_ids = []
    for _, row in out.iterrows():
        lat, lon = row['latitude'], row['longitude']
        if pd.notna(lat) and pd.notna(lon):
            # For now, just use water body assignment
            # Full spatial join would require geometry data
            loc_id = get_water_body_loc_id(lat, lon, region='global')
            loc_ids.append(loc_id)
        else:
            loc_ids.append(None)
    out['loc_id'] = loc_ids

    # Calculate felt and damage radii (same formulas as USGS converter)
    def calc_felt_radius(mag):
        if pd.isna(mag) or mag < 2.5:
            return None
        return 10 ** (0.5 * mag - 0.15)  # ~30km for M5, ~100km for M6

    def calc_damage_radius(mag):
        if pd.isna(mag) or mag < 5.0:
            return None
        return 10 ** (0.4 * mag - 1.0)  # ~10km for M6, ~25km for M7

    out['felt_radius_km'] = out['magnitude'].apply(calc_felt_radius)
    out['damage_radius_km'] = out['magnitude'].apply(calc_damage_radius)

    print(f"  Processed {len(out):,} events")
    print(f"  Year range: {out['year'].min()} to {out['year'].max()}")
    print(f"  Pre-1900 (historical): {(out['year'] < 1900).sum():,}")

    return out


def merge_datasets(noaa_df, usgs_df):
    """Merge NOAA historical with USGS modern data."""
    print("\nMerging datasets...")

    if usgs_df is None:
        print("  No USGS data - using NOAA only")
        return noaa_df

    # Strategy:
    # - Use NOAA for pre-1900 events (USGS doesn't have)
    # - Use USGS for 1900+ events (better coverage, aftershock detection)
    # - Keep NOAA 1900+ significant events that USGS might miss

    noaa_historical = noaa_df[noaa_df['year'] < 1900].copy()
    noaa_modern = noaa_df[noaa_df['year'] >= 1900].copy()

    print(f"  NOAA historical (pre-1900): {len(noaa_historical):,}")
    print(f"  NOAA modern (1900+): {len(noaa_modern):,}")
    print(f"  USGS: {len(usgs_df):,}")

    # Add source column to USGS if missing
    if 'source' not in usgs_df.columns:
        usgs_df = usgs_df.copy()
        usgs_df['source'] = 'usgs'

    # For 1900+ events, we primarily use USGS
    # But we'll add NOAA cross-linking info to matching events

    # First, add NOAA impact data and cross-links to USGS events where they match
    # Match by: similar time (within 1 day), similar location (within 100km), similar magnitude (within 0.5)

    print("\n  Enriching USGS events with NOAA data...")

    # Add columns for NOAA data
    usgs_df['deaths'] = None
    usgs_df['injuries'] = None
    usgs_df['damage_millions'] = None
    usgs_df['houses_destroyed'] = None
    usgs_df['noaa_tsunami_id'] = None
    usgs_df['noaa_volcano_id'] = None
    usgs_df['intensity'] = None

    matches_found = 0

    # For efficiency, group NOAA events by year
    noaa_by_year = noaa_modern.groupby('year')
    years_to_process = list(noaa_by_year.groups.keys())
    total_years = len(years_to_process)

    print(f"  Processing {total_years} years of NOAA data...")

    for i, (year, noaa_year_events) in enumerate(noaa_by_year):
        if year not in usgs_df['year'].values:
            continue

        usgs_year = usgs_df[usgs_df['year'] == year]

        year_matches = 0
        for _, noaa_event in noaa_year_events.iterrows():
            noaa_lat = noaa_event['latitude']
            noaa_lon = noaa_event['longitude']
            noaa_mag = noaa_event['magnitude']

            if pd.isna(noaa_lat) or pd.isna(noaa_lon):
                continue

            # Find potential matches - use vectorized filtering first
            candidates = usgs_year[
                (usgs_year['latitude'].between(noaa_lat - 1, noaa_lat + 1)) &
                (usgs_year['longitude'].between(noaa_lon - 1, noaa_lon + 1))
            ]

            if pd.notna(noaa_mag):
                candidates = candidates[
                    candidates['magnitude'].between(noaa_mag - 0.5, noaa_mag + 0.5)
                ]

            if len(candidates) > 0:
                idx = candidates.index[0]
                # Match found - enrich USGS event with NOAA data
                usgs_df.at[idx, 'deaths'] = noaa_event['deaths']
                usgs_df.at[idx, 'injuries'] = noaa_event['injuries']
                usgs_df.at[idx, 'damage_millions'] = noaa_event['damage_millions']
                usgs_df.at[idx, 'houses_destroyed'] = noaa_event['houses_destroyed']
                usgs_df.at[idx, 'noaa_tsunami_id'] = noaa_event['noaa_tsunami_id']
                usgs_df.at[idx, 'noaa_volcano_id'] = noaa_event['noaa_volcano_id']
                usgs_df.at[idx, 'intensity'] = noaa_event['intensity']
                matches_found += 1
                year_matches += 1

        # Progress update every 10 years
        if (i + 1) % 10 == 0 or (i + 1) == total_years:
            print(f"    Year {i+1}/{total_years}: {year} ({year_matches} matches, {matches_found:,} total)")

    print(f"  Enriched {matches_found:,} USGS events with NOAA data")

    # Normalize timestamps before combining (mixing tz-aware and tz-naive causes errors)
    def normalize_timestamp(ts):
        """Remove timezone info from timestamp."""
        if pd.isna(ts):
            return pd.NaT
        try:
            ts = pd.to_datetime(ts)
            if ts.tzinfo is not None:
                # Convert to UTC then remove timezone
                return ts.tz_convert('UTC').tz_localize(None)
            return ts
        except:
            return pd.NaT

    noaa_historical['timestamp'] = noaa_historical['timestamp'].apply(normalize_timestamp)
    usgs_df['timestamp'] = usgs_df['timestamp'].apply(normalize_timestamp)

    # Combine: NOAA historical + enriched USGS
    combined = pd.concat([noaa_historical, usgs_df], ignore_index=True)

    # Sort by year, then timestamp
    combined = combined.sort_values(['year', 'timestamp']).reset_index(drop=True)

    print(f"  Combined dataset: {len(combined):,} events")
    print(f"  Year range: {combined['year'].min()} to {combined['year'].max()}")

    return combined


def link_to_tsunamis(eq_df):
    """Link earthquakes to tsunamis using NOAA IDs."""
    print("\nLinking to tsunamis...")

    if not TSUNAMI_PATH.exists():
        print(f"  Tsunami data not found at {TSUNAMI_PATH}")
        eq_df['tsunami_event_id'] = None
        return eq_df

    # Load tsunamis
    tsunamis = pd.read_parquet(TSUNAMI_PATH)
    print(f"  Loaded {len(tsunamis):,} tsunamis")

    # Check if tsunamis have their original NOAA IDs
    # The tsunami event_id format is like "TS000123" but NOAA uses numeric IDs

    # Extract NOAA ID from tsunami event_id (TS prefix + number)
    def extract_noaa_id(event_id):
        if pd.isna(event_id):
            return None
        # TS000123 -> 123
        try:
            return int(event_id.replace('TS', '').lstrip('0') or '0')
        except:
            return None

    tsunami_noaa_ids = tsunamis['event_id'].apply(extract_noaa_id)
    tsunamis['noaa_id'] = tsunami_noaa_ids

    # Create mapping from NOAA tsunami ID to our event_id
    noaa_to_event = tsunamis.set_index('noaa_id')['event_id'].to_dict()

    # Link earthquakes that have noaa_tsunami_id
    def get_tsunami_event_id(noaa_id):
        if pd.isna(noaa_id):
            return None
        try:
            return noaa_to_event.get(int(noaa_id))
        except:
            return None

    eq_df['tsunami_event_id'] = eq_df['noaa_tsunami_id'].apply(get_tsunami_event_id)

    linked = eq_df['tsunami_event_id'].notna().sum()
    print(f"  Linked {linked:,} earthquakes to tsunamis")

    return eq_df


def link_to_volcanoes(eq_df):
    """Link earthquakes to volcanoes using NOAA->Smithsonian crosswalk."""
    import json

    print("\nLinking to volcanoes...")

    if not VOLCANO_PATH.exists():
        print(f"  Volcano data not found at {VOLCANO_PATH}")
        eq_df['volcano_event_id'] = None
        return eq_df

    # Load volcanoes
    volcanoes = pd.read_parquet(VOLCANO_PATH)
    print(f"  Loaded {len(volcanoes):,} eruptions")

    # Load NOAA->Smithsonian crosswalk
    crosswalk_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/noaa_volcano_crosswalk.json")
    if crosswalk_path.exists():
        with open(crosswalk_path) as f:
            crosswalk = json.load(f)
        print(f"  Loaded crosswalk with {len(crosswalk):,} mappings")
    else:
        print(f"  WARNING: Crosswalk not found at {crosswalk_path}")
        crosswalk = {}

    # Convert NOAA IDs to Smithsonian volcano numbers
    def noaa_to_smithsonian(noaa_id):
        if pd.isna(noaa_id):
            return None
        smithsonian = crosswalk.get(str(int(noaa_id)))
        return str(smithsonian) if smithsonian else None

    eq_df['volcano_event_id'] = eq_df['noaa_volcano_id'].apply(noaa_to_smithsonian)

    linked = eq_df['volcano_event_id'].notna().sum()
    print(f"  Linked {linked:,} earthquakes to volcanoes (Smithsonian numbers)")

    return eq_df


def generate_metadata(df):
    """Generate metadata.json for the dataset."""
    print("\nGenerating metadata...")

    metadata = {
        "source_id": "global_earthquakes",
        "source_name": "Global Earthquakes (USGS + NOAA Significant)",
        "source_url": "https://earthquake.usgs.gov/",
        "secondary_source_url": "https://www.ngdc.noaa.gov/hazel/view/hazards/earthquake/search",
        "description": "Global earthquake events combining USGS real-time catalog (1900+) with NOAA Significant Earthquakes (2150 BC - present)",
        "license": "Public Domain (U.S. Government)",
        "event_type": "earthquake",
        "record_count": len(df),
        "year_range": [int(df['year'].min()), int(df['year'].max())],
        "coverage": "Global",
        "columns": {
            "event_id": "Unique identifier (NOAA-SIG-* for historical, usgs* for modern)",
            "timestamp": "Event datetime (UTC)",
            "year": "Event year",
            "latitude": "Epicenter latitude",
            "longitude": "Epicenter longitude",
            "magnitude": "Earthquake magnitude",
            "depth_km": "Focal depth in kilometers",
            "felt_radius_km": "Approximate felt radius",
            "damage_radius_km": "Approximate damage radius",
            "place": "Location description",
            "loc_id": "Assigned location or water body code",
            "deaths": "Number of deaths (significant events only)",
            "injuries": "Number of injuries (significant events only)",
            "damage_millions": "Damage in millions USD (significant events only)",
            "tsunami_event_id": "Linked tsunami event ID",
            "volcano_event_id": "Linked volcano event ID",
            "mainshock_id": "Mainshock event ID (aftershocks only)",
            "sequence_id": "Earthquake sequence ID",
            "source": "Data source (usgs or noaa_significant)"
        },
        "statistics": {
            "pre_1900_count": int((df['year'] < 1900).sum()),
            "post_1900_count": int((df['year'] >= 1900).sum()),
            "with_deaths": int(df['deaths'].notna().sum()),
            "tsunami_linked": int(df['tsunami_event_id'].notna().sum()),
            "volcano_linked": int(df['volcano_event_id'].notna().sum()),
            "total_deaths_recorded": int(df['deaths'].sum()) if df['deaths'].notna().any() else 0
        },
        "generated": datetime.now().isoformat()
    }

    metadata_path = OUTPUT_DIR / "metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    print(f"  Saved: {metadata_path}")


def main():
    """Main conversion logic."""
    print("=" * 70)
    print("NOAA Significant Earthquakes + USGS Merger")
    print("=" * 70)

    # Load NOAA data
    noaa_raw = load_noaa_earthquakes()
    noaa_processed = process_noaa_events(noaa_raw)

    # Load USGS data
    usgs_df = load_usgs_earthquakes()

    # Merge datasets
    combined = merge_datasets(noaa_processed, usgs_df)

    # Link to tsunamis
    combined = link_to_tsunamis(combined)

    # Link to volcanoes
    combined = link_to_volcanoes(combined)

    # Select final columns
    final_columns = [
        'event_id', 'timestamp', 'year', 'latitude', 'longitude',
        'magnitude', 'depth_km', 'felt_radius_km', 'damage_radius_km',
        'place', 'loc_id', 'country',
        'deaths', 'injuries', 'damage_millions', 'houses_destroyed',
        'intensity',
        'mainshock_id', 'sequence_id', 'is_mainshock', 'aftershock_count',
        'tsunami_event_id', 'volcano_event_id',
        'source'
    ]

    # Only keep columns that exist
    final_columns = [c for c in final_columns if c in combined.columns]
    combined = combined[final_columns]

    # Save
    print("\n" + "=" * 70)
    print("Saving output...")
    print("=" * 70)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    events_path = OUTPUT_DIR / "events.parquet"
    save_parquet(combined, events_path, description="unified earthquake events")

    # Generate metadata
    generate_metadata(combined)

    # Statistics
    print("\n" + "=" * 70)
    print("FINAL STATISTICS")
    print("=" * 70)

    print(f"Total events: {len(combined):,}")
    print(f"Year range: {combined['year'].min()} to {combined['year'].max()}")
    print(f"Pre-1900 (historical): {(combined['year'] < 1900).sum():,}")
    print(f"Linked to tsunamis: {combined['tsunami_event_id'].notna().sum():,}")
    print(f"Linked to volcanoes: {combined['volcano_event_id'].notna().sum():,}")

    if 'deaths' in combined.columns:
        print(f"With death records: {combined['deaths'].notna().sum():,}")

    if 'mainshock_id' in combined.columns:
        print(f"Aftershocks: {combined['mainshock_id'].notna().sum():,}")

    print("\n" + "=" * 70)
    print("COMPLETE!")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
