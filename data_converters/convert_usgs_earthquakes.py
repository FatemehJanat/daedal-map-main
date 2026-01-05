"""
Convert USGS earthquake data to parquet format.

Creates two output files:
1. events.parquet - Individual earthquake events with location and radius data
2. USA.parquet - County-year aggregated statistics

Input: CSV files from download_usgs_earthquakes.py
Output: Two parquet files with earthquake data

Usage:
    python convert_usgs_earthquakes.py
"""
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import geopandas as gpd
from pathlib import Path
from shapely.geometry import Point
import numpy as np

# Configuration
RAW_DATA_DIR = Path("C:/Users/bryan/Desktop/county_map_data/Raw data/usgs_earthquakes")
SHAPEFILE_PATH = Path("C:/Users/bryan/Desktop/county_map_data/shapefiles/counties/tl_2024_us_county.shp")
OUTPUT_DIR = Path("C:/Users/bryan/Desktop/county_map_data/data/usgs_earthquakes")

# State FIPS to abbreviation mapping
STATE_FIPS = {
    '01': 'AL', '02': 'AK', '04': 'AZ', '05': 'AR', '06': 'CA',
    '08': 'CO', '09': 'CT', '10': 'DE', '11': 'DC', '12': 'FL',
    '13': 'GA', '15': 'HI', '16': 'ID', '17': 'IL', '18': 'IN',
    '19': 'IA', '20': 'KS', '21': 'KY', '22': 'LA', '23': 'ME',
    '24': 'MD', '25': 'MA', '26': 'MI', '27': 'MN', '28': 'MS',
    '29': 'MO', '30': 'MT', '31': 'NE', '32': 'NV', '33': 'NH',
    '34': 'NJ', '35': 'NM', '36': 'NY', '37': 'NC', '38': 'ND',
    '39': 'OH', '40': 'OK', '41': 'OR', '42': 'PA', '44': 'RI',
    '45': 'SC', '46': 'SD', '47': 'TN', '48': 'TX', '49': 'UT',
    '50': 'VT', '51': 'VA', '53': 'WA', '54': 'WV', '55': 'WI',
    '56': 'WY', '72': 'PR'
}


def calculate_felt_radius(magnitude):
    """
    Calculate felt radius in km (people notice shaking).

    Based on Modified Mercalli Intensity attenuation.
    Formula: R = 10^(0.5 * M - 1.0)
    """
    return 10 ** (0.5 * magnitude - 1.0)


def calculate_damage_radius(magnitude):
    """
    Calculate damage radius in km (potential structural damage, MMI VI+).

    Based on Modified Mercalli Intensity attenuation.
    Formula: R = 10^(0.5 * M - 1.5)
    """
    return 10 ** (0.5 * magnitude - 1.5)


def fips_to_loc_id(fips_code):
    """Convert 5-digit FIPS code to loc_id format."""
    fips_str = str(fips_code).zfill(5)
    state_fips = fips_str[:2]
    state_abbr = STATE_FIPS.get(state_fips)

    if not state_abbr:
        return None

    return f"USA-{state_abbr}-{int(fips_str)}"


def load_shapefile():
    """Load Census county shapefile."""
    print("Loading county shapefile...")
    counties = gpd.read_file(SHAPEFILE_PATH)
    print(f"  Loaded {len(counties)} counties")
    return counties


def process_earthquake_csvs(counties_gdf):
    """Load and geocode all earthquake CSV files."""
    print("\nProcessing earthquake CSV files...")

    csv_files = sorted(RAW_DATA_DIR.glob("earthquakes_*.csv"))
    print(f"  Found {len(csv_files)} CSV files")

    all_events = []

    for csv_path in csv_files:
        year = csv_path.stem.split('_')[1]
        print(f"  Loading {year}...", end=' ', flush=True)

        try:
            df = pd.read_csv(csv_path)

            # Drop events with missing coordinates
            df = df.dropna(subset=['latitude', 'longitude', 'mag'])

            # Extract year from time
            df['time'] = pd.to_datetime(df['time'])
            df['year'] = df['time'].dt.year

            # Calculate radii
            df['felt_radius_km'] = df['mag'].apply(calculate_felt_radius)
            df['damage_radius_km'] = df['mag'].apply(calculate_damage_radius)

            # Create geometry for spatial join
            geometry = [Point(xy) for xy in zip(df['longitude'], df['latitude'])]
            gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")

            # Spatial join with counties
            gdf_with_counties = gpd.sjoin(gdf, counties_gdf[['GEOID', 'geometry']],
                                          how='left', predicate='within')

            # Convert GEOID to loc_id
            gdf_with_counties['loc_id'] = gdf_with_counties['GEOID'].apply(
                lambda x: fips_to_loc_id(x) if pd.notna(x) else None
            )

            # Select columns for events file
            events = gdf_with_counties[[
                'time', 'latitude', 'longitude', 'depth', 'mag',
                'felt_radius_km', 'damage_radius_km', 'place', 'loc_id'
            ]].copy()

            all_events.append(events)

            print(f"{len(events)} events")

        except Exception as e:
            print(f"ERROR: {e}")
            continue

    # Combine all years
    print("\nCombining all events...")
    combined = pd.concat(all_events, ignore_index=True)
    print(f"  Total events: {len(combined):,}")

    # Count events with/without county match
    matched = combined['loc_id'].notna().sum()
    unmatched = combined['loc_id'].isna().sum()
    print(f"  Matched to counties: {matched:,} ({matched/len(combined)*100:.1f}%)")
    print(f"  No county match: {unmatched:,} ({unmatched/len(combined)*100:.1f}%)")

    return combined


def create_events_parquet(df):
    """Create events.parquet with individual earthquake data."""
    print("\nCreating events.parquet...")

    # Round values for compression
    events_df = pd.DataFrame({
        'time': df['time'],
        'latitude': df['latitude'].round(4),
        'longitude': df['longitude'].round(4),
        'magnitude': df['mag'].round(2),
        'depth_km': df['depth'].round(1),
        'felt_radius_km': df['felt_radius_km'].round(1),
        'damage_radius_km': df['damage_radius_km'].round(1),
        'place': df['place'],
        'loc_id': df['loc_id']
    })

    # Define schema
    schema = pa.schema([
        ('time', pa.timestamp('us')),
        ('latitude', pa.float32()),
        ('longitude', pa.float32()),
        ('magnitude', pa.float32()),
        ('depth_km', pa.float32()),
        ('felt_radius_km', pa.float32()),
        ('damage_radius_km', pa.float32()),
        ('place', pa.string()),
        ('loc_id', pa.string())
    ])

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "events.parquet"

    table = pa.Table.from_pandas(events_df, schema=schema)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Saved: {size_mb:.2f} MB")
    print(f"  Events: {len(events_df):,}")

    return output_path


def create_county_aggregates(df):
    """Create USA.parquet with county-year aggregates."""
    print("\nCreating county-year aggregates...")

    # Filter to events with county match
    df_with_county = df[df['loc_id'].notna()].copy()
    df_with_county['year'] = df_with_county['time'].dt.year

    # Group by county-year
    grouped = df_with_county.groupby(['loc_id', 'year'])

    aggregates = grouped.agg({
        'mag': ['count', 'min', 'max', 'mean'],
        'depth': 'mean'
    }).reset_index()

    # Flatten column names
    aggregates.columns = ['loc_id', 'year', 'earthquake_count',
                          'min_magnitude', 'max_magnitude', 'avg_magnitude', 'avg_depth_km']

    # Round values
    aggregates['min_magnitude'] = aggregates['min_magnitude'].round(2)
    aggregates['max_magnitude'] = aggregates['max_magnitude'].round(2)
    aggregates['avg_magnitude'] = aggregates['avg_magnitude'].round(2)
    aggregates['avg_depth_km'] = aggregates['avg_depth_km'].round(1)

    print(f"  County-year records: {len(aggregates):,}")
    print(f"  Unique counties: {aggregates['loc_id'].nunique():,}")
    print(f"  Year range: {aggregates['year'].min()}-{aggregates['year'].max()}")

    return aggregates


def save_county_parquet(df):
    """Save county aggregates to USA.parquet."""
    print("\nSaving USA.parquet...")

    # Define schema
    schema = pa.schema([
        ('loc_id', pa.string()),
        ('year', pa.int32()),
        ('earthquake_count', pa.int32()),
        ('min_magnitude', pa.float32()),
        ('max_magnitude', pa.float32()),
        ('avg_magnitude', pa.float32()),
        ('avg_depth_km', pa.float32())
    ])

    # Save
    output_path = OUTPUT_DIR / "USA.parquet"

    table = pa.Table.from_pandas(df, schema=schema)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Saved: {size_mb:.2f} MB")

    return output_path


def print_statistics(events_df, county_df):
    """Print summary statistics."""
    print("\n" + "="*80)
    print("STATISTICS")
    print("="*80)

    print(f"\nTotal earthquake events: {len(events_df):,}")
    print(f"Date range: {events_df['time'].min()} to {events_df['time'].max()}")

    print("\nMagnitude Distribution:")
    print(f"  Min: {events_df['magnitude'].min():.2f}")
    print(f"  Max: {events_df['magnitude'].max():.2f}")
    print(f"  Mean: {events_df['magnitude'].mean():.2f}")
    print(f"  Mag 5.0+: {(events_df['magnitude'] >= 5.0).sum():,}")
    print(f"  Mag 6.0+: {(events_df['magnitude'] >= 6.0).sum():,}")
    print(f"  Mag 7.0+: {(events_df['magnitude'] >= 7.0).sum():,}")

    print("\nTop 10 Most Seismically Active Counties (by event count):")
    top_counties = county_df.groupby('loc_id')['earthquake_count'].sum().nlargest(10)
    for loc_id, count in top_counties.items():
        avg_mag = county_df[county_df['loc_id'] == loc_id]['avg_magnitude'].mean()
        print(f"  {loc_id}: {int(count):,} events (avg mag {avg_mag:.2f})")

    print("\nLargest Earthquakes (Top 10):")
    top_quakes = events_df.nlargest(10, 'magnitude')[['time', 'magnitude', 'place', 'damage_radius_km']]
    for _, row in top_quakes.iterrows():
        print(f"  Mag {row['magnitude']:.2f} ({row['time'].year}) - {row['place']} (damage radius: {row['damage_radius_km']:.0f} km)")


def main():
    """Main conversion logic."""
    print("="*80)
    print("USGS Earthquake Data - CSV to Parquet Converter")
    print("="*80)

    # Load county shapefile
    counties_gdf = load_shapefile()

    # Process earthquake CSVs
    events_df = process_earthquake_csvs(counties_gdf)

    if events_df.empty:
        print("\nERROR: No earthquake data processed")
        return 1

    # Create events.parquet
    create_events_parquet(events_df)

    # Create county aggregates
    county_df = create_county_aggregates(events_df)
    save_county_parquet(county_df)

    # Print statistics
    print_statistics(events_df, county_df)

    print("\n" + "="*80)
    print("COMPLETE!")
    print("="*80)
    print("\nOutput files:")
    print(f"  events.parquet: Individual earthquakes with location and radii")
    print(f"  USA.parquet: County-year aggregated statistics")
    print("\nNext steps:")
    print("  1. Create metadata.json for earthquake metrics")
    print("  2. Update DATA_SOURCES_EXPLORATION.md")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
