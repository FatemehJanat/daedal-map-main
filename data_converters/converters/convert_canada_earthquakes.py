"""
Convert Natural Resources Canada Earthquakes to parquet format.

Creates two output files:
1. events.parquet - Individual earthquake events with location and radius data
2. CAN.parquet - Census Division-year aggregated statistics

Input: CSV from Earthquakes Canada
Output: Two parquet files with earthquake data

Uses unified base utilities for spatial join and water body assignment.

Usage:
    python convert_canada_earthquakes.py
"""
import pandas as pd
import geopandas as gpd
from pathlib import Path
import sys

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from data_converters.base import (
    CAN_PROVINCE_ABBR,
    load_geometry_parquet,
    spatial_join_3pass,
    create_point_gdf,
    save_parquet,
)
from build.catalog.finalize_source import finalize_source

# Configuration
INPUT_FILE = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/canada/eqarchive-en.csv")
GEOMETRY_PATH = Path("C:/Users/Bryan/Desktop/county-map-data/countries/CAN/geometry.parquet")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/CAN/nrcan_earthquakes")
SOURCE_ID = "nrcan_earthquakes"


# =============================================================================
# Earthquake-Specific Calculations
# =============================================================================

def calculate_felt_radius(magnitude):
    """
    Calculate felt radius in km (people notice shaking).

    Based on Modified Mercalli Intensity attenuation.
    Formula: R = 10^(0.6 * M - 1.0) - slightly different for Canadian geology
    """
    if pd.isna(magnitude) or magnitude < 1.0:
        return None
    radius = 10 ** (0.6 * magnitude - 1.0)
    return min(radius, 2000)  # Cap at 2000km


def calculate_damage_radius(magnitude):
    """
    Calculate damage radius in km (potential structural damage, MMI VI+).
    """
    if pd.isna(magnitude) or magnitude < 3.0:
        return None
    return 10 ** (0.6 * magnitude - 1.5)


# =============================================================================
# Data Processing
# =============================================================================

def load_raw_data():
    """Load earthquake CSV data."""
    print("Loading Canada earthquakes data...")
    df = pd.read_csv(INPUT_FILE)

    # Clean up column names
    df.columns = ['date', 'latitude', 'longitude', 'depth', 'magnitude',
                  'magnitude_type', 'place', 'province_code', 'extra']

    # Drop empty column and rows with missing coordinates
    df = df.drop(columns=['extra'])
    df = df.dropna(subset=['latitude', 'longitude'])

    # Parse dates
    df['time'] = pd.to_datetime(df['date'], errors='coerce', utc=True)
    df['year'] = df['time'].dt.year

    print(f"  Loaded {len(df):,} earthquakes")
    return df


def process_events(df, cd_gdf):
    """Process events with spatial join and radius calculations."""
    print("\nProcessing events...")

    # Calculate radii
    df['felt_radius_km'] = df['magnitude'].apply(calculate_felt_radius)
    df['damage_radius_km'] = df['magnitude'].apply(calculate_damage_radius)

    # Create point geometries
    print("  Creating point geometries...")
    gdf = create_point_gdf(df, lat_col='latitude', lon_col='longitude')

    # 3-pass spatial join with Canada water body region
    gdf = spatial_join_3pass(
        gdf,
        cd_gdf,
        loc_id_col='loc_id',
        water_body_region='canada'
    )

    return gdf


def create_events_dataframe(gdf):
    """Create standardized events DataFrame."""
    events = pd.DataFrame({
        'event_id': range(len(gdf)),
        'loc_id': gdf['loc_id'],
        'event_date': gdf['time'],
        'year': gdf['year'].astype('Int64'),
        'lat': gdf['latitude'].round(4),
        'lon': gdf['longitude'].round(4),
        'depth_km': gdf['depth'].round(1),
        'magnitude': gdf['magnitude'].round(2),
        'magnitude_type': gdf['magnitude_type'],
        'felt_radius_km': gdf['felt_radius_km'].round(1),
        'damage_radius_km': gdf['damage_radius_km'].round(1),
        'place': gdf['place'],
    })

    return events.sort_values('event_date', ascending=False)


def create_aggregates(events):
    """Create census division-year aggregates."""
    print("\nCreating aggregates...")

    # Filter to events with census division match (exclude water body codes)
    df = events[events['loc_id'].str.startswith('CAN-', na=False)].copy()

    # Group by census division-year
    agg = df.groupby(['loc_id', 'year']).agg({
        'event_id': 'count',
        'magnitude': ['max', 'mean', 'median'],
        'depth_km': 'mean'
    }).reset_index()

    # Flatten column names
    agg.columns = ['loc_id', 'year', 'earthquake_count',
                   'max_magnitude', 'mean_magnitude', 'median_magnitude', 'mean_depth_km']

    # Round values
    agg['mean_magnitude'] = agg['mean_magnitude'].round(2)
    agg['median_magnitude'] = agg['median_magnitude'].round(2)
    agg['mean_depth_km'] = agg['mean_depth_km'].round(1)

    # Add magnitude category counts
    for mag_threshold, col_name in [(3.0, 'count_mag_3plus'), (4.0, 'count_mag_4plus'),
                                    (5.0, 'count_mag_5plus'), (6.0, 'count_mag_6plus')]:
        mag_counts = df[df['magnitude'] >= mag_threshold].groupby(
            ['loc_id', 'year']
        ).size().reset_index(name=col_name)
        agg = agg.merge(mag_counts, on=['loc_id', 'year'], how='left')
        agg[col_name] = agg[col_name].fillna(0).astype('Int64')

    print(f"  Census division-year records: {len(agg):,}")
    print(f"  Unique census divisions: {agg['loc_id'].nunique():,}")

    return agg


# =============================================================================
# Statistics & Reporting
# =============================================================================

def print_statistics(events, aggregates):
    """Print summary statistics."""
    print("\n" + "=" * 60)
    print("Statistics")
    print("=" * 60)

    print(f"\nTotal events: {len(events):,}")
    print(f"Year range: {events['year'].min()}-{events['year'].max()}")

    # Matching summary
    cd_match = events['loc_id'].str.startswith('CAN-', na=False).sum()
    water_body = events['loc_id'].str.startswith('X', na=False).sum()
    print(f"\nGeocoding:")
    print(f"  Census divisions: {cd_match:,} ({cd_match/len(events)*100:.1f}%)")
    print(f"  Water bodies: {water_body:,} ({water_body/len(events)*100:.1f}%)")

    print("\nMagnitude distribution:")
    print(f"  Min: {events['magnitude'].min():.2f}")
    print(f"  Max: {events['magnitude'].max():.2f}")
    print(f"  Mean: {events['magnitude'].mean():.2f}")
    print(f"  M5.0+: {(events['magnitude'] >= 5.0).sum():,}")
    print(f"  M6.0+: {(events['magnitude'] >= 6.0).sum():,}")
    print(f"  M7.0+: {(events['magnitude'] >= 7.0).sum():,}")

    print("\nTop 10 census divisions by event count:")
    top = events[events['loc_id'].str.startswith('CAN-', na=False)].groupby('loc_id').size().nlargest(10)
    for loc_id, count in top.items():
        print(f"  {loc_id}: {int(count):,}")

    print("\nWater body distribution:")
    water = events[events['loc_id'].str.startswith('X', na=False)].groupby('loc_id').size()
    for loc_id, count in water.items():
        print(f"  {loc_id}: {int(count):,}")

    print("\nLargest earthquakes:")
    largest = events.nlargest(10, 'magnitude')[['event_date', 'magnitude', 'place', 'loc_id']]
    print(largest.to_string())


# =============================================================================
# Main
# =============================================================================

def main():
    """Main conversion logic."""
    print("=" * 60)
    print("Canada Earthquakes Converter (NRCAN)")
    print("=" * 60)

    # Load census division geometry using base utility
    cd_gdf = load_geometry_parquet(GEOMETRY_PATH, admin_level=2, geometry_format='wkb')

    # Load raw data
    df = load_raw_data()
    if df.empty:
        print("\nERROR: No earthquake data found")
        return 1

    # Process with spatial join
    gdf = process_events(df, cd_gdf)

    # Create output dataframes
    events = create_events_dataframe(gdf)
    aggregates = create_aggregates(events)

    # Save outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    events_path = OUTPUT_DIR / "events.parquet"
    save_parquet(events, events_path, description="earthquake events")

    agg_path = OUTPUT_DIR / "CAN.parquet"
    save_parquet(aggregates, agg_path, description="census division-year aggregates")

    # Print statistics
    print_statistics(events, aggregates)

    # Finalize (generate metadata, update index)
    print("\n" + "=" * 60)
    print("Finalizing source...")
    print("=" * 60)

    try:
        finalize_source(
            parquet_path=str(agg_path),
            source_id=SOURCE_ID,
            events_parquet_path=str(events_path)
        )
    except ValueError as e:
        print(f"  Note: {e}")
        print(f"  Add '{SOURCE_ID}' to source_registry.py to enable auto-finalization")

    print("\n" + "=" * 60)
    print("COMPLETE!")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
