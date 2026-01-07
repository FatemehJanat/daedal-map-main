"""
Convert ReliefWeb Disasters List to parquet format.

Input: CSV from ReliefWeb API export
Output:
  - reliefweb_disasters/events.parquet - Individual disaster events
  - reliefweb_disasters/GLOBAL.parquet - Annual aggregates by country

Usage:
    python convert_reliefweb.py

Dataset contains global disaster events from OCHA ReliefWeb:
- 3,600+ disasters from 1981-2025
- Types: Floods, Cyclones, Earthquakes, Epidemics, Droughts, etc.
- Country-level with coordinates
- GLIDE numbers for cross-referencing
"""
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
import sys

# Add build path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from build.catalog.finalize_source import finalize_source

# Configuration
INPUT_FILE = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/reliefweb/reliefweb-disasters-list.csv")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/global/reliefweb_disasters")

# Disaster type code mapping (for standardization)
DISASTER_TYPE_MAP = {
    'FL': 'flood',
    'TC': 'tropical_cyclone',
    'EQ': 'earthquake',
    'EP': 'epidemic',
    'DR': 'drought',
    'ST': 'severe_storm',
    'FF': 'flash_flood',
    'VO': 'volcano',
    'CW': 'cold_wave',
    'LS': 'landslide',
    'WF': 'wildfire',
    'AC': 'technological',
    'MS': 'mudslide',
    'AV': 'avalanche',
    'TS': 'tsunami',
    'HT': 'heat_wave',
    'CE': 'complex_emergency',
    'IN': 'insect_infestation',
    'OT': 'other',
}


def load_raw_data():
    """Load ReliefWeb CSV data."""
    print("Loading ReliefWeb disasters data...")
    df = pd.read_csv(INPUT_FILE)
    print(f"  Loaded {len(df):,} disaster events")
    return df


def process_events(df):
    """Process raw data into events format."""
    print("\nProcessing events...")

    # Parse dates
    df['event_date'] = pd.to_datetime(df['date-event'], errors='coerce')
    df['year'] = df['event_date'].dt.year

    # Standardize ISO3 codes (uppercase)
    df['iso3'] = df['primary_country-iso3'].str.upper()

    # Create loc_id (country level)
    df['loc_id'] = df['iso3']

    # Extract disaster type
    df['disaster_type_code'] = df['primary_type-code']
    df['disaster_type'] = df['disaster_type_code'].map(DISASTER_TYPE_MAP).fillna('other')

    # Create output dataframe
    events = pd.DataFrame({
        'event_id': df['id'].astype(str),
        'loc_id': df['loc_id'],
        'name': df['name'],
        'disaster_type': df['disaster_type'],
        'disaster_type_code': df['disaster_type_code'],
        'glide': df['glide'],  # Global Disaster Identifier
        'country_name': df['primary_country-name'],
        'event_date': df['event_date'],
        'year': df['year'].astype('Int64'),
        'lat': df['primary_country-location-lat'],
        'lon': df['primary_country-location-lon'],
        'status': df['status'],
        'url': df['url'],
    })

    # Filter out rows with no valid country
    events = events[events['loc_id'].notna() & (events['loc_id'] != '')].copy()

    # Sort by date
    events = events.sort_values('event_date', ascending=False)

    print(f"  Output: {len(events):,} events")
    print(f"  Countries: {events['loc_id'].nunique()}")
    print(f"  Years: {events['year'].min()}-{events['year'].max()}")
    print(f"  Types: {events['disaster_type'].nunique()}")

    return events


def create_aggregates(events):
    """Create annual aggregates by country."""
    print("\nCreating aggregates...")

    # Count disasters by country and year
    agg = events.groupby(['loc_id', 'year']).agg({
        'event_id': 'count',
        'country_name': 'first',
    }).reset_index()

    agg.columns = ['loc_id', 'year', 'total_disasters', 'country_name']

    # Add disaster type counts
    type_counts = events.groupby(['loc_id', 'year', 'disaster_type']).size().unstack(fill_value=0)
    type_counts.columns = [f'count_{col}' for col in type_counts.columns]
    type_counts = type_counts.reset_index()

    agg = agg.merge(type_counts, on=['loc_id', 'year'], how='left')

    # Fill NaN counts with 0
    count_cols = [c for c in agg.columns if c.startswith('count_')]
    agg[count_cols] = agg[count_cols].fillna(0).astype('Int64')

    # Reorder columns
    base_cols = ['loc_id', 'country_name', 'year', 'total_disasters']
    other_cols = [c for c in agg.columns if c not in base_cols]
    agg = agg[base_cols + sorted(other_cols)]

    print(f"  Output: {len(agg):,} country-year records")

    return agg


def save_parquet(df, output_path, description):
    """Save dataframe to parquet."""
    print(f"\nSaving {description}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"  Saved: {output_path}")
    print(f"  Size: {size_mb:.2f} MB, {len(df):,} rows")
    return size_mb


def main():
    """Main conversion workflow."""
    print("=" * 60)
    print("ReliefWeb Disasters Converter")
    print("=" * 60)

    # Load and process
    df = load_raw_data()
    events = process_events(df)
    aggregates = create_aggregates(events)

    # Save outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    events_path = OUTPUT_DIR / "events.parquet"
    save_parquet(events, events_path, "event data")

    agg_path = OUTPUT_DIR / "GLOBAL.parquet"
    save_parquet(aggregates, agg_path, "country-year aggregates")

    # Print summary
    print("\n" + "=" * 60)
    print("Conversion Summary")
    print("=" * 60)
    print(f"Events: {len(events):,}")
    print(f"Countries: {events['loc_id'].nunique()}")
    print(f"Years: {events['year'].min()}-{events['year'].max()}")

    print("\nTop disaster types:")
    print(events['disaster_type'].value_counts().head(10).to_string())

    print("\nTop affected countries (all time):")
    top_countries = events.groupby('loc_id').size().nlargest(10)
    print(top_countries.to_string())

    # Finalize
    print("\n" + "=" * 60)
    print("Finalizing source...")
    print("=" * 60)

    try:
        finalize_source(
            parquet_path=str(agg_path),
            source_id="reliefweb_disasters",
            events_parquet_path=str(events_path)
        )
    except ValueError as e:
        print(f"  Note: {e}")
        print("  Add 'reliefweb_disasters' to source_registry.py to enable auto-finalization")

    return events, aggregates


if __name__ == "__main__":
    main()
