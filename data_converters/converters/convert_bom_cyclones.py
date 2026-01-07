"""
Convert Australian Bureau of Meteorology Tropical Cyclone Database to parquet format.

Input: CSV from BOM tropical cyclone database
Output:
  - events.parquet - Individual track observations (31K+ records)
  - AUS.parquet - Annual aggregates by cyclone season

Usage:
    python convert_bom_cyclones.py

Dataset contains tropical cyclone tracks in the Australian region (90E-160E, 0-40S)
from 1907 to present. Each row is a position observation at a point in time.
"""
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
import numpy as np
import sys

# Add build path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from build.catalog.finalize_source import finalize_source

# Configuration
INPUT_FILE = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/australia/IDCKMSTM0S.csv")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/AUS/bom_cyclones")

# Surface codes to Saffir-Simpson-like categories
# BOM uses a different scale but we can map roughly
SURFACE_CODE_MAP = {
    1: "tropical_low",      # Tropical Low
    2: "cat_1",             # Category 1 (64-82 kt)
    3: "cat_2",             # Category 2 (83-95 kt)
    4: "cat_3",             # Category 3 (96-113 kt)
    5: "cat_4",             # Category 4 (114-135 kt)
    6: "cat_5",             # Category 5 (>135 kt)
}


def load_raw_data():
    """Load raw CSV data, skipping the copyright header."""
    print("Loading BOM cyclone data...")

    # Skip the first 4 lines (copyright header)
    df = pd.read_csv(INPUT_FILE, skiprows=4, low_memory=False)
    print(f"  Loaded {len(df):,} track observations")

    return df


def process_events(df):
    """Process raw data into events format."""
    print("\nProcessing events...")

    # Parse timestamp
    df['timestamp'] = pd.to_datetime(df['TM'], errors='coerce')
    df['year'] = df['timestamp'].dt.year
    df['month'] = df['timestamp'].dt.month

    # Australian cyclone season spans Nov-Apr, so use season year
    # Season 2024 = Nov 2023 - Apr 2024
    df['season'] = df.apply(
        lambda r: r['year'] if r['month'] >= 7 else r['year'] - 1, axis=1
    )

    # Clean numeric columns
    df['lat'] = pd.to_numeric(df['LAT'], errors='coerce')
    df['lon'] = pd.to_numeric(df['LON'], errors='coerce')
    df['central_pressure_hpa'] = pd.to_numeric(df['CENTRAL_PRES'], errors='coerce')
    df['max_wind_kt'] = pd.to_numeric(df['MAX_WIND_SPD'], errors='coerce')
    df['surface_code'] = pd.to_numeric(df['SURFACE_CODE'], errors='coerce')

    # Map surface code to category name
    df['category'] = df['surface_code'].map(SURFACE_CODE_MAP).fillna('unknown')

    # Extract cyclone name and ID
    df['cyclone_name'] = df['NAME'].str.strip()
    df['cyclone_id'] = df['DISTURBANCE_ID'].str.strip()

    # Create output dataframe
    events = pd.DataFrame({
        'event_id': df['cyclone_id'] + '_' + df['timestamp'].dt.strftime('%Y%m%d%H%M'),
        'cyclone_id': df['cyclone_id'],
        'cyclone_name': df['cyclone_name'],
        'timestamp': df['timestamp'],
        'year': df['year'],
        'season': df['season'],
        'lat': df['lat'].round(4),
        'lon': df['lon'].round(4),
        'central_pressure_hpa': df['central_pressure_hpa'],
        'max_wind_kt': df['max_wind_kt'],
        'surface_code': df['surface_code'].astype('Int64'),
        'category': df['category'],
    })

    # Filter out rows with no valid position
    events = events.dropna(subset=['lat', 'lon', 'timestamp'])

    # Sort by cyclone and time
    events = events.sort_values(['cyclone_id', 'timestamp'])

    print(f"  Output: {len(events):,} valid track points")
    print(f"  Cyclones: {events['cyclone_id'].nunique():,}")
    print(f"  Seasons: {events['season'].min()}-{events['season'].max()}")

    return events


def create_aggregates(events):
    """Create annual/seasonal aggregates for country level."""
    print("\nCreating aggregates...")

    # Get unique cyclones per season with their max intensity
    cyclone_summary = events.groupby(['season', 'cyclone_id']).agg({
        'cyclone_name': 'first',
        'surface_code': 'max',
        'central_pressure_hpa': 'min',  # Lower pressure = stronger
        'max_wind_kt': 'max',
        'lat': ['min', 'max'],  # Track extent
        'lon': ['min', 'max'],
    }).reset_index()

    # Flatten column names
    cyclone_summary.columns = [
        'season', 'cyclone_id', 'name', 'max_category_code',
        'min_pressure_hpa', 'max_wind_kt',
        'lat_min', 'lat_max', 'lon_min', 'lon_max'
    ]

    # Aggregate by season
    agg = cyclone_summary.groupby('season').agg({
        'cyclone_id': 'count',
        'max_category_code': lambda x: (x >= 3).sum(),  # Cat 2+ severe
        'min_pressure_hpa': 'min',
        'max_wind_kt': 'max',
    }).reset_index()

    agg.columns = ['season', 'total_cyclones', 'severe_cyclones',
                   'min_pressure_hpa', 'max_wind_kt']

    # Add loc_id (country level for cyclones - they don't map to LGAs)
    agg['loc_id'] = 'AUS'

    # Add category counts per season
    for code, cat_name in SURFACE_CODE_MAP.items():
        cyclone_summary[f'is_{cat_name}'] = (cyclone_summary['max_category_code'] == code).fillna(False).astype(int)

    cat_counts = cyclone_summary.groupby('season')[[f'is_{cat}' for cat in SURFACE_CODE_MAP.values()]].sum()
    cat_counts.columns = [f'count_{cat}' for cat in SURFACE_CODE_MAP.values()]

    agg = agg.merge(cat_counts, on='season', how='left')

    # Reorder columns
    col_order = ['loc_id', 'season', 'total_cyclones', 'severe_cyclones',
                 'min_pressure_hpa', 'max_wind_kt'] + [f'count_{cat}' for cat in SURFACE_CODE_MAP.values()]
    agg = agg[col_order]

    print(f"  Output: {len(agg)} seasons")

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
    print("BOM Tropical Cyclone Converter")
    print("=" * 60)

    # Load and process
    df = load_raw_data()
    events = process_events(df)
    aggregates = create_aggregates(events)

    # Save outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    events_path = OUTPUT_DIR / "events.parquet"
    save_parquet(events, events_path, "event data")

    agg_path = OUTPUT_DIR / "AUS.parquet"
    save_parquet(aggregates, agg_path, "seasonal aggregates")

    # Print summary
    print("\n" + "=" * 60)
    print("Conversion Summary")
    print("=" * 60)
    print(f"Track points: {len(events):,}")
    print(f"Unique cyclones: {events['cyclone_id'].nunique():,}")
    print(f"Seasons: {aggregates['season'].min()}-{aggregates['season'].max()}")

    print("\nSample events:")
    print(events[['cyclone_id', 'cyclone_name', 'timestamp', 'lat', 'lon', 'category']].head(5).to_string())

    print("\nRecent seasons:")
    print(aggregates[aggregates['season'] >= 2020][['season', 'total_cyclones', 'severe_cyclones', 'max_wind_kt']].to_string())

    # Finalize
    print("\n" + "=" * 60)
    print("Finalizing source...")
    print("=" * 60)

    try:
        finalize_source(
            parquet_path=str(agg_path),
            source_id="bom_cyclones",
            events_parquet_path=str(events_path)
        )
    except ValueError as e:
        print(f"  Note: {e}")

    return events, aggregates


if __name__ == "__main__":
    main()
