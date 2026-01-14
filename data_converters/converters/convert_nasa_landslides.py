"""
Convert NASA Global Landslide Catalog to parquet format.

Input: Shapefile from HDX (1970-2019)
Output:
  - nasa_landslides/events.parquet - Landslide events with impact data
  - nasa_landslides/metadata.json - Country coverage and statistics

Usage:
    python convert_nasa_landslides.py
"""
import pandas as pd
import geopandas as gpd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
import json
from datetime import datetime

# Configuration
INPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/nasa_landslides")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/global/nasa_landslides")

# Landslide type mapping
LANDSLIDE_TYPE_MAP = {
    'landslide': 'landslide',
    'mudslide': 'mudslide',
    'rockfall': 'rockfall',
    'debris flow': 'debris_flow',
    'avalanche': 'avalanche',
    'complex': 'complex',
}

# Trigger type mapping
TRIGGER_MAP = {
    'rain': 'rain',
    'downpour': 'rain',
    'tropical cyclone': 'tropical_cyclone',
    'monsoon': 'monsoon',
    'snowmelt': 'snowmelt',
    'earthquake': 'earthquake',
    'construction': 'construction',
    'mining': 'mining',
    'unknown': 'unknown',
}


def load_shapefile():
    """Load NASA GLC shapefile."""
    print("Loading NASA Global Landslide Catalog...")

    shp_file = INPUT_DIR / "global_landslide_catalog_NASA.shp"

    if not shp_file.exists():
        print(f"ERROR: Shapefile not found: {shp_file}")
        exit(1)

    gdf = gpd.read_file(shp_file)
    print(f"  Loaded {len(gdf):,} landslide events")
    print(f"  Columns: {len(gdf.columns)}")

    return gdf


def process_events(gdf):
    """Process and standardize NASA GLC data."""
    print("\nProcessing events...")

    # Parse dates
    gdf['timestamp'] = pd.to_datetime(gdf['event_date'], errors='coerce')
    gdf['year'] = gdf['timestamp'].dt.year

    # Standardize country codes (already ISO2, need ISO3)
    # Common ISO2 to ISO3 mappings
    iso2_to_iso3 = {
        'CN': 'CHN', 'IN': 'IND', 'US': 'USA', 'ID': 'IDN', 'BR': 'BRA',
        'PK': 'PAK', 'NG': 'NGA', 'BD': 'BGD', 'RU': 'RUS', 'MX': 'MEX',
        'JP': 'JPN', 'ET': 'ETH', 'PH': 'PHL', 'EG': 'EGY', 'VN': 'VNM',
        'CD': 'COD', 'TR': 'TUR', 'IR': 'IRN', 'DE': 'DEU', 'TH': 'THA',
        'GB': 'GBR', 'FR': 'FRA', 'IT': 'ITA', 'ZA': 'ZAF', 'MM': 'MMR',
        'KR': 'KOR', 'CO': 'COL', 'ES': 'ESP', 'AR': 'ARG', 'DZ': 'DZA',
        'SD': 'SDN', 'UA': 'UKR', 'UG': 'UGA', 'IQ': 'IRQ', 'CA': 'CAN',
        'MA': 'MAR', 'PE': 'PER', 'NP': 'NPL', 'AF': 'AFG', 'MY': 'MYS',
        'VE': 'VEN', 'UZ': 'UZB', 'SA': 'SAU', 'KE': 'KEN', 'TZ': 'TZA',
        'GT': 'GTM', 'EC': 'ECU', 'NI': 'NIC', 'BO': 'BOL', 'HN': 'HND',
        'DO': 'DOM', 'CU': 'CUB', 'HT': 'HTI', 'GR': 'GRC', 'PT': 'PRT',
        'CZ': 'CZE', 'HU': 'HUN', 'BY': 'BLR', 'RS': 'SRB', 'AT': 'AUT',
        'CH': 'CHE', 'IL': 'ISR', 'JO': 'JOR', 'TJ': 'TJK', 'PG': 'PNG',
        'LA': 'LAO', 'LB': 'LBN', 'PR': 'PRI', 'JM': 'JAM', 'TT': 'TTO',
    }

    gdf['country_iso3'] = gdf['country_co'].map(iso2_to_iso3).fillna(gdf['country_co'])
    gdf['loc_id'] = gdf['country_iso3']

    # Standardize landslide category
    gdf['landslide_type'] = gdf['landslide_'].str.lower().map(LANDSLIDE_TYPE_MAP).fillna('landslide')

    # Standardize trigger
    gdf['trigger'] = gdf['landslid_1'].str.lower().map(TRIGGER_MAP).fillna('unknown')

    # Standardize size
    gdf['size_category'] = gdf['landslid_2'].str.lower()

    # Create output dataframe
    events = pd.DataFrame({
        'event_id': 'NASA_GLC_' + gdf['event_id'].astype(str),
        'timestamp': gdf['timestamp'],
        'year': gdf['year'].astype('Int64'),
        'latitude': gdf['latitude'],
        'longitude': gdf['longitude'],
        'loc_id': gdf['loc_id'],
        'country_name': gdf['country_na'],
        'country_code': gdf['country_iso3'],
        'admin_division': gdf['admin_divi'],
        'location_description': gdf['location_d'],
        'location_accuracy': gdf['location_a'],
        # Event details
        'event_title': gdf['event_titl'],
        'event_description': gdf['event_desc'],
        'landslide_type': gdf['landslide_type'],
        'trigger_type': gdf['trigger'],
        'size_category': gdf['size_category'],
        'landslide_setting': gdf['landslid_3'],
        # Impact data
        'deaths': pd.to_numeric(gdf['fatality_c'], errors='coerce').astype('Int32'),
        'injuries': pd.to_numeric(gdf['injury_cou'], errors='coerce').astype('Int32'),
        # Source
        'source_name': gdf['source_nam'],
        'source_link': gdf['source_lin'],
        'storm_name': gdf['storm_name'],
        'photo_link': gdf['photo_link'],
        # Metadata
        'submitted_date': pd.to_datetime(gdf['submitted_'], errors='coerce'),
        'created_date': pd.to_datetime(gdf['created_da'], errors='coerce'),
        'data_source': 'NASA_GLC',
    })

    # Sort by date
    events = events.sort_values('timestamp', ascending=False)

    print(f"  Processed {len(events):,} events")
    print(f"  Countries: {events['country_code'].nunique()}")
    print(f"  Years: {events['year'].min()}-{events['year'].max()}")
    print(f"\n  Impact data:")
    print(f"    Events with deaths: {events['deaths'].notna().sum():,} ({events['deaths'].notna().sum()/len(events)*100:.1f}%)")
    print(f"    Events with injuries: {events['injuries'].notna().sum():,} ({events['injuries'].notna().sum()/len(events)*100:.1f}%)")
    print(f"    Total deaths: {events['deaths'].sum():,}")
    print(f"    Total injuries: {events['injuries'].sum():,}")

    return events


def create_metadata(events):
    """Create metadata including country coverage."""
    print("\nCreating metadata...")

    # Country coverage
    country_stats = events.groupby('country_code').agg({
        'event_id': 'count',
        'deaths': 'sum',
        'injuries': 'sum',
        'year': ['min', 'max'],
        'country_name': 'first'
    }).reset_index()

    country_stats.columns = ['country_code', 'event_count', 'total_deaths',
                              'total_injuries', 'year_start', 'year_end', 'country_name']

    # Convert to dict for JSON
    countries = {}
    for _, row in country_stats.iterrows():
        countries[row['country_code']] = {
            'name': row['country_name'],
            'events': int(row['event_count']),
            'deaths': int(row['total_deaths']) if pd.notna(row['total_deaths']) else 0,
            'injuries': int(row['total_injuries']) if pd.notna(row['total_injuries']) else 0,
            'year_range': f"{int(row['year_start'])}-{int(row['year_end'])}"
        }

    metadata = {
        'source': 'NASA Global Landslide Catalog',
        'source_url': 'https://data.humdata.org/dataset/global-landslide-catalogue-nasa',
        'coverage': '1970-2019 (rainfall-triggered landslides)',
        'conversion_date': datetime.now().isoformat(),
        'total_events': len(events),
        'total_countries': len(countries),
        'date_range': {
            'start': int(events['year'].min()),
            'end': int(events['year'].max())
        },
        'impact_summary': {
            'events_with_deaths': int(events['deaths'].notna().sum()),
            'events_with_injuries': int(events['injuries'].notna().sum()),
            'total_deaths': int(events['deaths'].sum()),
            'total_injuries': int(events['injuries'].sum())
        },
        'trigger_types': events['trigger_type'].value_counts().to_dict(),
        'landslide_types': events['landslide_type'].value_counts().to_dict(),
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
    """Main conversion workflow."""
    print("=" * 70)
    print("NASA Global Landslide Catalog Converter")
    print("=" * 70)
    print()

    # Load shapefile
    gdf = load_shapefile()

    # Process events
    events = process_events(gdf)

    # Create metadata
    metadata = create_metadata(events)

    # Save outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    events_path = OUTPUT_DIR / "events.parquet"
    save_parquet(events, events_path)

    metadata_path = OUTPUT_DIR / "metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"\nMetadata saved: {metadata_path}")

    # Print summary
    print("\n" + "=" * 70)
    print("Conversion Summary")
    print("=" * 70)
    print(f"Total events: {len(events):,}")
    print(f"Countries: {len(metadata['countries'])}")
    print(f"Years: {metadata['date_range']['start']}-{metadata['date_range']['end']}")

    print(f"\nTop countries by event count:")
    top_countries = sorted(metadata['countries'].items(),
                          key=lambda x: x[1]['events'], reverse=True)[:10]
    for code, info in top_countries:
        print(f"  {code} ({info['name']}): {info['events']} events, {info['deaths']} deaths")

    print(f"\nTrigger types:")
    for trigger, count in sorted(metadata['trigger_types'].items(),
                                 key=lambda x: x[1], reverse=True)[:5]:
        print(f"  {trigger}: {count}")

    print("\n" + "=" * 70)
    print("COMPLETE!")
    print("=" * 70)

    return events, metadata


if __name__ == "__main__":
    main()
