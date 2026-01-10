"""
Convert USGS earthquake data to parquet format.

Creates two output files:
1. events.parquet - Individual earthquake events with location and radius data
2. USA.parquet - County-year aggregated statistics

Input: CSV files from download_usgs_earthquakes.py
Output: Two parquet files with earthquake data

Uses unified base utilities for spatial join and water body assignment.

Usage:
    python convert_usgs_earthquakes.py
"""
import pandas as pd
import geopandas as gpd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
import json
import sys

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from data_converters.base import (
    USA_STATE_FIPS,
    load_geometry_parquet,
    spatial_join_3pass,
    create_point_gdf,
    save_parquet,
)
from build.catalog.finalize_source import finalize_source

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/usgs_earthquakes")
IMPORTED_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/imported/usgs_earthquakes")
GEOMETRY_PATH = Path("C:/Users/Bryan/Desktop/county-map-data/geometry/USA.parquet")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA/usgs_earthquakes")
SOURCE_ID = "usgs_earthquakes"


# =============================================================================
# Earthquake-Specific Calculations
# =============================================================================

def calculate_felt_radius(magnitude, depth_km=None):
    """
    Calculate felt radius in km (MMI II-III, people notice shaking).

    Based on empirical seismological attenuation models.
    Formula: R = 10^(0.44 * M - 0.29) with depth correction.

    Shallow earthquakes (< 70km) are felt over wider areas.
    Deep earthquakes have smaller felt radii.

    Approximate felt radii by magnitude (shallow):
    - M4.0: ~30 km
    - M5.0: ~80 km
    - M6.0: ~220 km
    - M7.0: ~620 km
    - M8.0: ~1700 km
    """
    if pd.isna(magnitude):
        return None

    # Base formula: empirical MMI attenuation
    radius = 10 ** (0.44 * magnitude - 0.29)

    # Depth correction: deeper quakes have smaller felt areas
    if depth_km is not None and not pd.isna(depth_km):
        if depth_km > 300:
            radius *= 0.5  # Deep focus - 50% reduction
        elif depth_km > 70:
            radius *= 0.7  # Intermediate - 30% reduction
        # Shallow (< 70km) - full radius

    return radius


def calculate_damage_radius(magnitude, depth_km=None):
    """
    Calculate damage radius in km (MMI VI+, potential structural damage).

    Based on empirical attenuation for damaging ground motion.
    Formula: R = 10^(0.32 * M - 0.78) with depth correction.

    Damage radii are much smaller than felt radii - concentrated near epicenter.

    Approximate damage radii by magnitude (shallow):
    - M5.0: ~7 km
    - M6.0: ~14 km
    - M7.0: ~29 km
    - M8.0: ~60 km
    """
    if pd.isna(magnitude):
        return None

    # Only earthquakes M5+ typically cause structural damage
    if magnitude < 5.0:
        return 0.0

    # Base formula: empirical MMI attenuation for damaging intensity
    radius = 10 ** (0.32 * magnitude - 0.78)

    # Depth correction: deeper quakes cause less surface damage
    if depth_km is not None and not pd.isna(depth_km):
        if depth_km > 300:
            radius *= 0.3  # Deep focus - 70% reduction
        elif depth_km > 70:
            radius *= 0.5  # Intermediate - 50% reduction
        # Shallow (< 70km) - full radius

    return radius


# =============================================================================
# Data Processing
# =============================================================================

def get_source_dir():
    """Get source directory - check raw first, then imported."""
    if RAW_DATA_DIR.exists() and list(RAW_DATA_DIR.glob("earthquakes_*.csv")):
        return RAW_DATA_DIR
    elif IMPORTED_DIR.exists() and list(IMPORTED_DIR.glob("earthquakes_*.csv")):
        print(f"  Note: Using imported data from {IMPORTED_DIR}")
        return IMPORTED_DIR
    return RAW_DATA_DIR  # Default, will show 0 files message


def move_to_imported():
    """Move processed raw files to imported folder."""
    if RAW_DATA_DIR.exists() and RAW_DATA_DIR != IMPORTED_DIR:
        csv_files = list(RAW_DATA_DIR.glob("earthquakes_*.csv"))
        if csv_files:
            import shutil
            IMPORTED_DIR.mkdir(parents=True, exist_ok=True)
            for f in csv_files:
                dest = IMPORTED_DIR / f.name
                shutil.move(str(f), str(dest))
            print(f"  Moved {len(csv_files)} files to {IMPORTED_DIR}")


def load_raw_data():
    """Load all earthquake CSV files."""
    print("Loading earthquake CSV files...")

    source_dir = get_source_dir()
    csv_files = sorted(source_dir.glob("earthquakes_*.csv"))
    print(f"  Found {len(csv_files)} CSV files")

    all_events = []
    for csv_path in csv_files:
        year = csv_path.stem.split('_')[1]
        print(f"  Loading {year}...", end=' ', flush=True)

        try:
            df = pd.read_csv(csv_path)

            # Drop events with missing coordinates
            df = df.dropna(subset=['latitude', 'longitude', 'mag'])

            # Parse dates
            df['time'] = pd.to_datetime(df['time'])
            df['year'] = df['time'].dt.year

            all_events.append(df)
            print(f"{len(df):,} events")

        except Exception as e:
            print(f"ERROR: {e}")
            continue

    # Combine all years
    print("\nCombining all years...")
    combined = pd.concat(all_events, ignore_index=True)
    print(f"  Total: {len(combined):,} events")

    return combined


def process_events(df, counties_gdf):
    """Process events with spatial join and radius calculations."""
    print("\nProcessing events...")

    # Calculate radii (using magnitude and depth for realistic values)
    df['felt_radius_km'] = df.apply(
        lambda row: calculate_felt_radius(row['mag'], row.get('depth')),
        axis=1
    )
    df['damage_radius_km'] = df.apply(
        lambda row: calculate_damage_radius(row['mag'], row.get('depth')),
        axis=1
    )

    # Create point geometries
    print("  Creating point geometries...")
    gdf = create_point_gdf(df, lat_col='latitude', lon_col='longitude')

    # 3-pass spatial join
    gdf = spatial_join_3pass(
        gdf,
        counties_gdf,
        loc_id_col='loc_id',
        water_body_region='usa'
    )

    return gdf


def create_events_dataframe(gdf):
    """Create standardized events DataFrame.

    Standard event schema columns:
    - event_id: unique identifier
    - timestamp: event datetime (ISO format)
    - latitude, longitude: event location
    - loc_id: assigned county/water body code
    """
    events = pd.DataFrame({
        'event_id': [f"EQ{i:08d}" for i in range(len(gdf))],
        'timestamp': gdf['time'],  # Standard column name
        'latitude': gdf['latitude'].round(4),  # Standard column name
        'longitude': gdf['longitude'].round(4),  # Standard column name
        'magnitude': gdf['mag'].round(2),
        'depth_km': gdf['depth'].round(1),
        'felt_radius_km': gdf['felt_radius_km'].round(1),
        'damage_radius_km': gdf['damage_radius_km'].round(1),
        'place': gdf['place'],
        'loc_id': gdf['loc_id'],
    })

    return events.sort_values('timestamp', ascending=False)


def create_aggregates(events):
    """Create county-year aggregates."""
    print("\nCreating county-year aggregates...")

    # Filter to events with county match (exclude water body codes)
    df = events[events['loc_id'].str.startswith('USA-', na=False)].copy()

    # Extract year from timestamp
    df['year'] = pd.to_datetime(df['timestamp']).dt.year

    # Group by county-year
    agg = df.groupby(['loc_id', 'year']).agg({
        'event_id': 'count',
        'magnitude': ['min', 'max', 'mean'],
        'depth_km': 'mean'
    }).reset_index()

    # Flatten column names
    agg.columns = ['loc_id', 'year', 'earthquake_count',
                   'min_magnitude', 'max_magnitude', 'avg_magnitude', 'avg_depth_km']

    # Round values
    agg['min_magnitude'] = agg['min_magnitude'].round(2)
    agg['max_magnitude'] = agg['max_magnitude'].round(2)
    agg['avg_magnitude'] = agg['avg_magnitude'].round(2)
    agg['avg_depth_km'] = agg['avg_depth_km'].round(1)

    # Add magnitude category counts
    for mag_threshold, col_name in [(5.0, 'count_mag_5plus'), (6.0, 'count_mag_6plus')]:
        mag_counts = df[df['magnitude'] >= mag_threshold].groupby(
            ['loc_id', 'year']
        ).size().reset_index(name=col_name)
        agg = agg.merge(mag_counts, on=['loc_id', 'year'], how='left')
        agg[col_name] = agg[col_name].fillna(0).astype('Int64')

    print(f"  County-year records: {len(agg):,}")
    print(f"  Unique counties: {agg['loc_id'].nunique():,}")

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
    years = pd.to_datetime(events['timestamp']).dt.year
    print(f"Year range: {years.min()}-{years.max()}")

    # Matching summary
    county_match = events['loc_id'].str.startswith('USA-', na=False).sum()
    water_body = events['loc_id'].str.startswith('X', na=False).sum()
    print(f"\nGeocoding:")
    print(f"  Counties: {county_match:,} ({county_match/len(events)*100:.1f}%)")
    print(f"  Water bodies: {water_body:,} ({water_body/len(events)*100:.1f}%)")

    print("\nMagnitude distribution:")
    print(f"  Min: {events['magnitude'].min():.2f}")
    print(f"  Max: {events['magnitude'].max():.2f}")
    print(f"  Mean: {events['magnitude'].mean():.2f}")
    print(f"  M5.0+: {(events['magnitude'] >= 5.0).sum():,}")
    print(f"  M6.0+: {(events['magnitude'] >= 6.0).sum():,}")
    print(f"  M7.0+: {(events['magnitude'] >= 7.0).sum():,}")

    print("\nTop 10 counties by event count:")
    top = aggregates.groupby('loc_id')['earthquake_count'].sum().nlargest(10)
    for loc_id, count in top.items():
        print(f"  {loc_id}: {int(count):,}")

    print("\nLargest earthquakes:")
    largest = events.nlargest(10, 'magnitude')[['timestamp', 'magnitude', 'place', 'loc_id']]
    print(largest.to_string())


# =============================================================================
# Main
# =============================================================================

def main():
    """Main conversion logic."""
    print("=" * 60)
    print("USGS Earthquake Converter")
    print("=" * 60)

    # Load county geometry using base utility
    counties_gdf = load_geometry_parquet(GEOMETRY_PATH, admin_level=2, geometry_format='geojson')

    # Load raw data
    df = load_raw_data()
    if df.empty:
        print("\nERROR: No earthquake data found")
        return 1

    # Process with spatial join
    gdf = process_events(df, counties_gdf)

    # Create output dataframes
    events = create_events_dataframe(gdf)
    aggregates = create_aggregates(events)

    # Save outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    events_path = OUTPUT_DIR / "events.parquet"
    save_parquet(events, events_path, description="earthquake events")

    agg_path = OUTPUT_DIR / "USA.parquet"
    save_parquet(aggregates, agg_path, description="county-year aggregates")

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

    # Move raw files to imported folder
    move_to_imported()

    print("\n" + "=" * 60)
    print("COMPLETE!")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
