"""
Convert IBTrACS (International Best Track Archive) to parquet format.

IBTrACS merges tropical cyclone data from all regional agencies:
- NHC (North Atlantic, East Pacific)
- JTWC (West Pacific, Indian Ocean)
- JMA (West Pacific)
- BOM (Australia)
- IMD (North Indian)
- RSMC Fiji (South Pacific)

Creates two output files:
1. storms.parquet - Storm metadata (one row per storm) with precalculated fields:
   - track_coords: JSON array of [lon, lat] for direct GeoJSON LineString generation
   - bbox: [minLon, minLat, maxLon, maxLat] for spatial queries
   - has_wind_radii: Boolean flag for UI display optimization
2. positions.parquet - 6-hourly track positions with wind radii (for animation drill-down)

Usage:
    python convert_ibtracs.py
    python convert_ibtracs.py --since1980    # Use smaller dataset
"""
import pandas as pd
import numpy as np
import json
import sys
from pathlib import Path
import argparse

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from data_converters.base import (
    get_water_body_loc_id,
    save_parquet,
)

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/ibtracs")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/global/tropical_storms")
SOURCE_ID = "ibtracs_storms"

# Basin codes and names
BASINS = {
    'NA': 'North Atlantic',
    'SA': 'South Atlantic',
    'EP': 'East Pacific',
    'WP': 'West Pacific',
    'SP': 'South Pacific',
    'SI': 'South Indian',
    'NI': 'North Indian',
}

# Agency priority for wind/pressure data
# Prefer USA data, then WMO, then regional agencies
AGENCY_PRIORITY = ['USA', 'WMO', 'TOKYO', 'CMA', 'REUNION', 'BOM', 'NEWDELHI']


def wind_to_category(wind_kt):
    """Convert max wind speed (knots) to Saffir-Simpson category."""
    if pd.isna(wind_kt) or wind_kt < 0:
        return None
    elif wind_kt < 34:
        return 'TD'  # Tropical Depression
    elif wind_kt < 64:
        return 'TS'  # Tropical Storm
    elif wind_kt < 83:
        return 'Cat1'
    elif wind_kt < 96:
        return 'Cat2'
    elif wind_kt < 113:
        return 'Cat3'
    elif wind_kt < 137:
        return 'Cat4'
    else:
        return 'Cat5'


def load_ibtracs_data(dataset='all'):
    """Load IBTrACS CSV data.

    Args:
        dataset: 'all' or 'since1980'

    Returns:
        DataFrame with track data
    """
    if dataset == 'since1980':
        csv_file = RAW_DATA_DIR / "ibtracs.since1980.list.v04r01.csv"
    else:
        csv_file = RAW_DATA_DIR / "ibtracs.ALL.list.v04r01.csv"

    if not csv_file.exists():
        print(f"ERROR: File not found: {csv_file}")
        return None

    print(f"\nLoading {csv_file.name}...")
    print(f"  Size: {csv_file.stat().st_size / 1024 / 1024:.1f} MB")

    # IBTrACS has a header row and a units row - skip the units row
    # keep_default_na=False prevents 'NA' basin code from being read as NaN
    df = pd.read_csv(csv_file, skiprows=[1], low_memory=False, keep_default_na=False, na_values=[''])

    print(f"  Rows: {len(df):,}")
    print(f"  Columns: {len(df.columns)}")

    # Convert numeric columns that might be strings
    numeric_cols = [
        'LAT', 'LON', 'WMO_WIND', 'WMO_PRES', 'DIST2LAND', 'LANDFALL',
        'USA_WIND', 'USA_PRES',
        'USA_R34_NE', 'USA_R34_SE', 'USA_R34_SW', 'USA_R34_NW',
        'USA_R50_NE', 'USA_R50_SE', 'USA_R50_SW', 'USA_R50_NW',
        'USA_R64_NE', 'USA_R64_SE', 'USA_R64_SW', 'USA_R64_NW',
        'TOKYO_WIND', 'TOKYO_PRES',
        'CMA_WIND', 'CMA_PRES',
        'REUNION_WIND', 'REUNION_PRES',
        'REUNION_R34_NE', 'REUNION_R34_SE', 'REUNION_R34_SW', 'REUNION_R34_NW',
        'REUNION_R50_NE', 'REUNION_R50_SE', 'REUNION_R50_SW', 'REUNION_R50_NW',
        'REUNION_R64_NE', 'REUNION_R64_SE', 'REUNION_R64_SW', 'REUNION_R64_NW',
        'BOM_WIND', 'BOM_PRES',
        'BOM_R34_NE', 'BOM_R34_SE', 'BOM_R34_SW', 'BOM_R34_NW',
        'BOM_R50_NE', 'BOM_R50_SE', 'BOM_R50_SW', 'BOM_R50_NW',
        'BOM_R64_NE', 'BOM_R64_SE', 'BOM_R64_SW', 'BOM_R64_NW',
        'NEWDELHI_WIND', 'NEWDELHI_PRES',
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    print(f"  Converted {len([c for c in numeric_cols if c in df.columns])} numeric columns")

    return df


def get_best_wind(row):
    """Get best available wind speed from multiple agencies."""
    # Try USA first
    if pd.notna(row.get('USA_WIND')) and row['USA_WIND'] > 0:
        return row['USA_WIND']
    # Then WMO
    if pd.notna(row.get('WMO_WIND')) and row['WMO_WIND'] > 0:
        return row['WMO_WIND']
    # Then regional agencies
    for prefix in ['TOKYO', 'CMA', 'REUNION', 'BOM', 'NEWDELHI']:
        col = f'{prefix}_WIND'
        if col in row and pd.notna(row[col]) and row[col] > 0:
            return row[col]
    return None


def get_best_pressure(row):
    """Get best available pressure from multiple agencies."""
    # Try USA first
    if pd.notna(row.get('USA_PRES')) and row['USA_PRES'] > 0:
        return row['USA_PRES']
    # Then WMO
    if pd.notna(row.get('WMO_PRES')) and row['WMO_PRES'] > 0:
        return row['WMO_PRES']
    # Then regional agencies
    for prefix in ['TOKYO', 'CMA', 'REUNION', 'BOM', 'NEWDELHI']:
        col = f'{prefix}_PRES'
        if col in row and pd.notna(row[col]) and row[col] > 0:
            return row[col]
    return None


def process_positions(df):
    """Process track positions from IBTrACS data.

    Returns:
        DataFrame with standardized position data
    """
    print("\nProcessing positions...")

    positions = []

    for idx, row in df.iterrows():
        if idx % 50000 == 0:
            print(f"  Processing row {idx:,}...")

        # Get best wind and pressure from available agencies
        wind_kt = get_best_wind(row)
        pressure_mb = get_best_pressure(row)

        # Parse timestamp
        try:
            timestamp = pd.to_datetime(row['ISO_TIME'])
        except:
            timestamp = None

        # Get wind radii (prefer USA data, then BOM, then Reunion)
        r34_ne = row.get('USA_R34_NE') or row.get('BOM_R34_NE') or row.get('REUNION_R34_NE')
        r34_se = row.get('USA_R34_SE') or row.get('BOM_R34_SE') or row.get('REUNION_R34_SE')
        r34_sw = row.get('USA_R34_SW') or row.get('BOM_R34_SW') or row.get('REUNION_R34_SW')
        r34_nw = row.get('USA_R34_NW') or row.get('BOM_R34_NW') or row.get('REUNION_R34_NW')

        r50_ne = row.get('USA_R50_NE') or row.get('BOM_R50_NE') or row.get('REUNION_R50_NE')
        r50_se = row.get('USA_R50_SE') or row.get('BOM_R50_SE') or row.get('REUNION_R50_SE')
        r50_sw = row.get('USA_R50_SW') or row.get('BOM_R50_SW') or row.get('REUNION_R50_SW')
        r50_nw = row.get('USA_R50_NW') or row.get('BOM_R50_NW') or row.get('REUNION_R50_NW')

        r64_ne = row.get('USA_R64_NE') or row.get('BOM_R64_NE') or row.get('REUNION_R64_NE')
        r64_se = row.get('USA_R64_SE') or row.get('BOM_R64_SE') or row.get('REUNION_R64_SE')
        r64_sw = row.get('USA_R64_SW') or row.get('BOM_R64_SW') or row.get('REUNION_R64_SW')
        r64_nw = row.get('USA_R64_NW') or row.get('BOM_R64_NW') or row.get('REUNION_R64_NW')

        # Clean up wind radii (replace invalid values)
        def clean_radius(val):
            if pd.isna(val) or val < 0:
                return None
            return int(val)

        pos = {
            'storm_id': row['SID'],
            'timestamp': timestamp,
            'latitude': row['LAT'],
            'longitude': row['LON'],
            'wind_kt': wind_kt,
            'pressure_mb': pressure_mb,
            'category': wind_to_category(wind_kt),
            'basin': row['BASIN'],
            'source_agency': row.get('WMO_AGENCY') or row.get('USA_AGENCY'),
            'status': row.get('USA_STATUS') or row.get('NATURE'),
            'dist_to_land_km': row.get('DIST2LAND'),
            'landfall_km': row.get('LANDFALL'),
            'r34_ne': clean_radius(r34_ne),
            'r34_se': clean_radius(r34_se),
            'r34_sw': clean_radius(r34_sw),
            'r34_nw': clean_radius(r34_nw),
            'r50_ne': clean_radius(r50_ne),
            'r50_se': clean_radius(r50_se),
            'r50_sw': clean_radius(r50_sw),
            'r50_nw': clean_radius(r50_nw),
            'r64_ne': clean_radius(r64_ne),
            'r64_se': clean_radius(r64_se),
            'r64_sw': clean_radius(r64_sw),
            'r64_nw': clean_radius(r64_nw),
        }
        positions.append(pos)

    positions_df = pd.DataFrame(positions)

    # Add event_id (storm_id + position index)
    positions_df['pos_idx'] = positions_df.groupby('storm_id').cumcount()
    positions_df['event_id'] = positions_df['storm_id'] + '_' + positions_df['pos_idx'].astype(str).str.zfill(3)
    positions_df = positions_df.drop(columns=['pos_idx'])

    # Assign water body loc_ids
    print("\nAssigning water body loc_ids...")
    positions_df['loc_id'] = positions_df.apply(
        lambda row: get_water_body_loc_id(row['latitude'], row['longitude'], region='global'),
        axis=1
    )

    print(f"  Positions: {len(positions_df):,}")
    print(f"  With wind radii: {positions_df['r34_ne'].notna().sum():,}")

    return positions_df


def process_storms(df, positions_df):
    """Aggregate positions into storm metadata with precalculated fields.

    Precalculated fields for faster API response:
    - track_coords: JSON array of [lon, lat] for direct GeoJSON LineString
    - bbox: [minLon, minLat, maxLon, maxLat] for spatial queries
    - has_wind_radii: Boolean flag for UI display optimization

    Returns:
        DataFrame with one row per storm
    """
    print("\nAggregating storm metadata...")

    storms = []
    total = len(df['SID'].unique())

    for idx, storm_id in enumerate(df['SID'].unique()):
        if idx % 1000 == 0:
            print(f"  Processing storm {idx:,}/{total:,}...")

        storm_positions = positions_df[positions_df['storm_id'] == storm_id].copy()
        raw_storm = df[df['SID'] == storm_id].iloc[0]

        # Sort positions by timestamp for track coordinates
        storm_positions = storm_positions.sort_values('timestamp')

        # Get storm time bounds
        start_time = storm_positions['timestamp'].min()
        end_time = storm_positions['timestamp'].max()

        # Find max intensity
        max_wind = storm_positions['wind_kt'].max()
        min_pres = storm_positions['pressure_mb'].min()
        if pd.isna(min_pres) or min_pres <= 0:
            min_pres = None

        # Check for landfall
        made_landfall = False
        if 'landfall_km' in storm_positions.columns:
            made_landfall = (storm_positions['landfall_km'] == 0).any()

        # === PRECALCULATED FIELDS ===

        # Build track coordinates as JSON array for direct GeoJSON generation
        # Format: [[lon1, lat1], [lon2, lat2], ...] for LineString
        valid_positions = storm_positions.dropna(subset=['longitude', 'latitude'])
        track_coords = [
            [round(row['longitude'], 2), round(row['latitude'], 2)]
            for _, row in valid_positions.iterrows()
        ]
        track_coords_json = json.dumps(track_coords) if len(track_coords) >= 2 else None

        # Calculate bounding box for spatial queries
        if len(valid_positions) > 0:
            min_lon = valid_positions['longitude'].min()
            max_lon = valid_positions['longitude'].max()
            min_lat = valid_positions['latitude'].min()
            max_lat = valid_positions['latitude'].max()
            bbox = json.dumps([round(min_lon, 2), round(min_lat, 2),
                               round(max_lon, 2), round(max_lat, 2)])
        else:
            bbox = None

        # Check if any position has wind radii data (for UI optimization)
        has_wind_radii = storm_positions['r34_ne'].notna().any()

        storm = {
            'storm_id': storm_id,
            'name': raw_storm.get('NAME') if pd.notna(raw_storm.get('NAME')) else None,
            'year': int(raw_storm['SEASON']),
            'basin': raw_storm['BASIN'],
            'subbasin': raw_storm.get('SUBBASIN') if pd.notna(raw_storm.get('SUBBASIN')) else None,
            'source_agency': raw_storm.get('WMO_AGENCY') if pd.notna(raw_storm.get('WMO_AGENCY')) else None,
            'start_date': start_time,
            'end_date': end_time,
            'max_wind_kt': max_wind if pd.notna(max_wind) else None,
            'min_pressure_mb': min_pres,
            'max_category': wind_to_category(max_wind),
            'num_positions': len(storm_positions),
            'made_landfall': made_landfall,
            # Precalculated fields
            'track_coords': track_coords_json,
            'bbox': bbox,
            'has_wind_radii': has_wind_radii,
        }
        storms.append(storm)

    storms_df = pd.DataFrame(storms)

    print(f"  Storms: {len(storms_df):,}")
    print(f"  Year range: {storms_df['year'].min()} - {storms_df['year'].max()}")
    print(f"  With wind radii: {storms_df['has_wind_radii'].sum():,}")
    print(f"  With track coords: {storms_df['track_coords'].notna().sum():,}")

    return storms_df


def print_statistics(storms_df, positions_df):
    """Print summary statistics."""
    print("\n" + "=" * 60)
    print("STATISTICS")
    print("=" * 60)

    print(f"\nTotal storms: {len(storms_df):,}")
    print(f"Total positions: {len(positions_df):,}")
    print(f"Year range: {storms_df['year'].min()} - {storms_df['year'].max()}")

    print("\nStorms by basin:")
    for basin_code, count in storms_df['basin'].value_counts().items():
        basin_name = BASINS.get(basin_code, basin_code)
        print(f"  {basin_code} ({basin_name}): {count:,}")

    print("\nCategory distribution:")
    for cat in ['TD', 'TS', 'Cat1', 'Cat2', 'Cat3', 'Cat4', 'Cat5']:
        count = (storms_df['max_category'] == cat).sum()
        if count > 0:
            print(f"  {cat}: {count:,}")

    print("\nWind radii coverage:")
    has_r34 = positions_df['r34_ne'].notna().sum()
    has_r50 = positions_df['r50_ne'].notna().sum()
    has_r64 = positions_df['r64_ne'].notna().sum()
    total = len(positions_df)
    print(f"  34kt radii: {has_r34:,} ({has_r34/total*100:.1f}%)")
    print(f"  50kt radii: {has_r50:,} ({has_r50/total*100:.1f}%)")
    print(f"  64kt radii: {has_r64:,} ({has_r64/total*100:.1f}%)")

    print("\nLoc_id distribution (top 10):")
    for loc_id, count in positions_df['loc_id'].value_counts().head(10).items():
        print(f"  {loc_id}: {count:,}")


def main():
    """Main conversion logic."""
    parser = argparse.ArgumentParser(description='Convert IBTrACS data to parquet')
    parser.add_argument('--since1980', action='store_true',
                        help='Use since1980 dataset instead of full history')
    args = parser.parse_args()

    print("=" * 60)
    print("IBTrACS Global Tropical Storm Converter")
    print("=" * 60)

    # Load data
    dataset = 'since1980' if args.since1980 else 'all'
    df = load_ibtracs_data(dataset)

    if df is None or df.empty:
        print("\nERROR: No data loaded")
        return 1

    # Process positions
    positions_df = process_positions(df)

    # Process storms
    storms_df = process_storms(df, positions_df)

    # Print statistics
    print_statistics(storms_df, positions_df)

    # Prepare output columns
    positions_out = positions_df[[
        'event_id', 'storm_id', 'timestamp', 'latitude', 'longitude',
        'wind_kt', 'pressure_mb', 'category', 'basin', 'source_agency',
        'status', 'loc_id',
        'r34_ne', 'r34_se', 'r34_sw', 'r34_nw',
        'r50_ne', 'r50_se', 'r50_sw', 'r50_nw',
        'r64_ne', 'r64_se', 'r64_sw', 'r64_nw',
    ]].copy()

    # Round coordinates
    positions_out['latitude'] = positions_out['latitude'].round(2)
    positions_out['longitude'] = positions_out['longitude'].round(2)

    # Save outputs
    print("\n" + "=" * 60)
    print("Saving outputs...")
    print("=" * 60)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    storms_path = OUTPUT_DIR / "storms.parquet"
    save_parquet(storms_df, storms_path, description="storm metadata")

    positions_path = OUTPUT_DIR / "positions.parquet"
    save_parquet(positions_out, positions_path, description="track positions")

    print("\n" + "=" * 60)
    print("COMPLETE!")
    print("=" * 60)
    print(f"\nOutput: {OUTPUT_DIR}")
    print(f"  storms.parquet: {len(storms_df):,} storms")
    print(f"  positions.parquet: {len(positions_out):,} positions")

    return 0


if __name__ == "__main__":
    sys.exit(main())
