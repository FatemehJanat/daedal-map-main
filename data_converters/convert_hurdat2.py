"""
Convert NOAA HURDAT2 Hurricane Database to parquet format.

Creates three output files:
1. storms.parquet - Storm metadata (one row per storm)
2. positions.parquet - Storm track positions (6-hourly)
3. USA.parquet - County-year aggregated hurricane statistics

Input: HURDAT2 text files from NOAA NHC
Output: Three parquet files with hurricane data

HURDAT2 Format:
- Header line: AL011851, UNNAMED, 14,
- Position lines: 18510625, 0000, , HU, 28.0N, 94.8W, 80, -999, ...

Status codes:
- TD = Tropical Depression (<34 kt)
- TS = Tropical Storm (34-63 kt)
- HU = Hurricane (>= 64 kt)
- EX = Extratropical
- SD = Subtropical Depression
- SS = Subtropical Storm
- LO = Low
- WV = Wave
- DB = Disturbance

Usage:
    python convert_hurdat2.py
"""
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import geopandas as gpd
from pathlib import Path
from shapely.geometry import Point, LineString, shape
import re
import json

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/noaa/hurdat2")
GEOMETRY_PATH = Path("C:/Users/Bryan/Desktop/county-map-data/geometry/USA.parquet")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA/hurricanes")

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

# Saffir-Simpson Hurricane Wind Scale (kt to category)
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


def parse_coordinate(coord_str):
    """Parse HURDAT2 coordinate string (e.g., '28.0N' or '94.8W')."""
    coord_str = coord_str.strip()
    if not coord_str:
        return None

    direction = coord_str[-1].upper()
    value = float(coord_str[:-1])

    if direction in ['S', 'W']:
        value = -value

    return value


def fips_to_loc_id(fips_code):
    """Convert 5-digit FIPS code to loc_id format."""
    fips_str = str(fips_code).zfill(5)
    state_fips = fips_str[:2]
    state_abbr = STATE_FIPS.get(state_fips)

    if not state_abbr:
        return None

    return f"USA-{state_abbr}-{int(fips_str)}"


def get_water_body_loc_id(lat, lon):
    """
    Determine water body loc_id based on coordinates.

    Uses simplified bounding boxes to assign ocean/sea codes.
    Water body codes follow ISO 3166-1 X-prefix convention:
      XOA = Atlantic Ocean
      XOP = Pacific Ocean
      XSG = Gulf of Mexico
      XSC = Caribbean Sea
    """
    if pd.isna(lat) or pd.isna(lon):
        return None

    # Gulf of Mexico (roughly bounded)
    # lat: 18-31, lon: -98 to -80
    if 18 <= lat <= 31 and -98 <= lon <= -80:
        return "XSG-0"

    # Caribbean Sea
    # lat: 9-22, lon: -89 to -59
    if 9 <= lat <= 22 and -89 <= lon <= -59:
        return "XSC-0"

    # Eastern Pacific (west of Americas)
    # lon < -100 (west of Mexico) or Pacific basin storms
    if lon < -100:
        return "XOP-0"

    # Atlantic Ocean (default for Atlantic basin)
    # Everything else in the western Atlantic
    if -100 <= lon <= 0:
        return "XOA-0"

    # Fallback for any other location
    return "XOA-0"


def load_counties():
    """Load county boundaries from geometry parquet."""
    print("Loading county boundaries...")

    # Read geometry parquet
    df = pd.read_parquet(GEOMETRY_PATH)

    # Filter to counties (admin_level 2)
    counties = df[df['admin_level'] == 2].copy()

    # Parse GeoJSON geometry
    counties['geom'] = counties['geometry'].apply(
        lambda x: shape(json.loads(x)) if pd.notna(x) else None
    )

    # Create GeoDataFrame
    gdf = gpd.GeoDataFrame(counties, geometry='geom', crs='EPSG:4326')

    print(f"  Loaded {len(gdf)} counties")
    return gdf


def parse_hurdat2_file(file_path, basin):
    """Parse a HURDAT2 format file into storms and positions dataframes."""
    storms = []
    positions = []

    with open(file_path, 'r') as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Check if this is a header line (starts with basin ID like AL, EP, CP)
        if line and (line.startswith('AL') or line.startswith('EP') or line.startswith('CP')):
            parts = [p.strip() for p in line.split(',')]

            storm_id = parts[0]
            storm_name = parts[1] if len(parts) > 1 else 'UNNAMED'
            num_entries = int(parts[2]) if len(parts) > 2 else 0

            # Extract year from storm ID (e.g., AL011851 -> 1851)
            year = int(storm_id[4:8])

            # Initialize storm data
            storm_data = {
                'storm_id': storm_id,
                'basin': basin,
                'name': storm_name if storm_name != 'UNNAMED' else None,
                'year': year,
                'max_wind_kt': 0,
                'min_pressure_mb': 9999,
                'max_category': None,
                'num_positions': num_entries,
                'start_date': None,
                'end_date': None,
                'made_landfall': False,
                'us_landfall': False
            }

            # Process position entries
            for j in range(num_entries):
                i += 1
                if i >= len(lines):
                    break

                pos_line = lines[i].strip()
                pos_parts = [p.strip() for p in pos_line.split(',')]

                if len(pos_parts) < 8:
                    continue

                # Parse position data
                date_str = pos_parts[0]  # YYYYMMDD
                time_str = pos_parts[1]  # HHMM
                record_id = pos_parts[2]  # L=landfall, etc.
                status = pos_parts[3]  # HU, TS, TD, etc.
                lat_str = pos_parts[4]
                lon_str = pos_parts[5]
                wind_kt = int(pos_parts[6]) if pos_parts[6] != '-999' else None
                pressure = int(pos_parts[7]) if pos_parts[7] != '-999' else None

                # Parse coordinates
                lat = parse_coordinate(lat_str)
                lon = parse_coordinate(lon_str)

                # Parse datetime
                try:
                    year_pos = int(date_str[:4])
                    month = int(date_str[4:6])
                    day = int(date_str[6:8])
                    hour = int(time_str[:2])
                    minute = int(time_str[2:4]) if len(time_str) > 2 else 0
                    timestamp = pd.Timestamp(year=year_pos, month=month, day=day,
                                            hour=hour, minute=minute)
                except:
                    timestamp = None

                # Update storm statistics
                if wind_kt and wind_kt > storm_data['max_wind_kt']:
                    storm_data['max_wind_kt'] = wind_kt
                    storm_data['max_category'] = wind_to_category(wind_kt)

                if pressure and pressure > 0 and pressure < storm_data['min_pressure_mb']:
                    storm_data['min_pressure_mb'] = pressure

                if timestamp:
                    if not storm_data['start_date']:
                        storm_data['start_date'] = timestamp
                    storm_data['end_date'] = timestamp

                # Check for landfall
                if record_id == 'L':
                    storm_data['made_landfall'] = True
                    # Check if US landfall (rough bounding box)
                    if lat and lon:
                        # Continental US + PR + HI rough bounds
                        if (24 <= lat <= 50 and -125 <= lon <= -65) or \
                           (17 <= lat <= 19 and -68 <= lon <= -64) or \
                           (18 <= lat <= 23 and -161 <= lon <= -154):
                            storm_data['us_landfall'] = True

                # Parse wind radii if available (positions 8-19)
                wind_radii = {}
                if len(pos_parts) > 8:
                    # 34 kt radii: NE, SE, SW, NW
                    try:
                        wind_radii['r34_ne'] = int(pos_parts[8]) if pos_parts[8] != '-999' else None
                        wind_radii['r34_se'] = int(pos_parts[9]) if pos_parts[9] != '-999' else None
                        wind_radii['r34_sw'] = int(pos_parts[10]) if pos_parts[10] != '-999' else None
                        wind_radii['r34_nw'] = int(pos_parts[11]) if pos_parts[11] != '-999' else None
                    except (IndexError, ValueError):
                        pass

                if len(pos_parts) > 12:
                    # 50 kt radii
                    try:
                        wind_radii['r50_ne'] = int(pos_parts[12]) if pos_parts[12] != '-999' else None
                        wind_radii['r50_se'] = int(pos_parts[13]) if pos_parts[13] != '-999' else None
                        wind_radii['r50_sw'] = int(pos_parts[14]) if pos_parts[14] != '-999' else None
                        wind_radii['r50_nw'] = int(pos_parts[15]) if pos_parts[15] != '-999' else None
                    except (IndexError, ValueError):
                        pass

                if len(pos_parts) > 16:
                    # 64 kt radii (hurricane force)
                    try:
                        wind_radii['r64_ne'] = int(pos_parts[16]) if pos_parts[16] != '-999' else None
                        wind_radii['r64_se'] = int(pos_parts[17]) if pos_parts[17] != '-999' else None
                        wind_radii['r64_sw'] = int(pos_parts[18]) if pos_parts[18] != '-999' else None
                        wind_radii['r64_nw'] = int(pos_parts[19]) if pos_parts[19] != '-999' else None
                    except (IndexError, ValueError):
                        pass

                positions.append({
                    'storm_id': storm_id,
                    'timestamp': timestamp,
                    'record_id': record_id if record_id else None,
                    'status': status,
                    'latitude': lat,
                    'longitude': lon,
                    'wind_kt': wind_kt,
                    'pressure_mb': pressure,
                    'category': wind_to_category(wind_kt),
                    **wind_radii
                })

            # Fix min_pressure if no valid readings
            if storm_data['min_pressure_mb'] == 9999:
                storm_data['min_pressure_mb'] = None

            storms.append(storm_data)

        i += 1

    return storms, positions


def load_hurdat2_data():
    """Load all HURDAT2 files."""
    print("\nLoading HURDAT2 data...")

    all_storms = []
    all_positions = []

    # Atlantic basin
    atlantic_file = RAW_DATA_DIR / "hurdat2_atlantic.txt"
    if atlantic_file.exists():
        print(f"  Processing Atlantic basin...")
        storms, positions = parse_hurdat2_file(atlantic_file, 'Atlantic')
        all_storms.extend(storms)
        all_positions.extend(positions)
        print(f"    Storms: {len(storms):,}, Positions: {len(positions):,}")

    # Pacific basin (Eastern Pacific)
    pacific_file = RAW_DATA_DIR / "hurdat2_pacific.txt"
    if pacific_file.exists():
        print(f"  Processing Pacific basin...")
        storms, positions = parse_hurdat2_file(pacific_file, 'Pacific')
        all_storms.extend(storms)
        all_positions.extend(positions)
        print(f"    Storms: {len(storms):,}, Positions: {len(positions):,}")

    storms_df = pd.DataFrame(all_storms)
    positions_df = pd.DataFrame(all_positions)

    print(f"\n  Total storms: {len(storms_df):,}")
    print(f"  Total positions: {len(positions_df):,}")

    return storms_df, positions_df


def filter_us_affecting_storms(storms_df, positions_df):
    """Filter to storms that affected US territory."""
    print("\nFiltering to US-affecting storms...")

    # US bounding box (generous to catch nearby storms)
    us_bbox = {
        'min_lat': 15,   # Below PR/VI
        'max_lat': 55,   # Above Maine
        'min_lon': -170, # Hawaii
        'max_lon': -60   # East of Maine
    }

    # Find storms with positions in/near US
    us_storm_ids = set()

    for storm_id in positions_df['storm_id'].unique():
        storm_positions = positions_df[positions_df['storm_id'] == storm_id]

        # Check if any position is within US region
        in_us = (
            (storm_positions['latitude'] >= us_bbox['min_lat']) &
            (storm_positions['latitude'] <= us_bbox['max_lat']) &
            (storm_positions['longitude'] >= us_bbox['min_lon']) &
            (storm_positions['longitude'] <= us_bbox['max_lon'])
        )

        if in_us.any():
            us_storm_ids.add(storm_id)

    # Also include all storms with US landfall
    landfall_ids = storms_df[storms_df['us_landfall']]['storm_id'].tolist()
    us_storm_ids.update(landfall_ids)

    # Filter dataframes
    us_storms = storms_df[storms_df['storm_id'].isin(us_storm_ids)].copy()
    us_positions = positions_df[positions_df['storm_id'].isin(us_storm_ids)].copy()

    print(f"  US-affecting storms: {len(us_storms):,}")
    print(f"  US-affecting positions: {len(us_positions):,}")
    print(f"  Storms with US landfall: {us_storms['us_landfall'].sum():,}")

    return us_storms, us_positions


def geocode_positions(positions_df, counties_gdf):
    """Geocode storm positions to counties."""
    print("\nGeocoding positions to counties...")

    # Filter to positions with coordinates
    positions_with_coords = positions_df.dropna(subset=['latitude', 'longitude']).copy()
    print(f"  Positions with coordinates: {len(positions_with_coords):,}")

    if len(positions_with_coords) == 0:
        return positions_df

    # Create geometry
    geometry = [Point(xy) for xy in zip(positions_with_coords['longitude'],
                                         positions_with_coords['latitude'])]
    gdf = gpd.GeoDataFrame(positions_with_coords, geometry=geometry, crs="EPSG:4326")

    # Spatial join with counties (geometry parquet already has loc_id)
    gdf_with_counties = gpd.sjoin(gdf, counties_gdf[['loc_id', 'geom']].set_geometry('geom'),
                                   how='left', predicate='within')

    matched_land = gdf_with_counties['loc_id'].notna().sum()
    print(f"  Matched to counties (land): {matched_land:,} ({matched_land/len(gdf_with_counties)*100:.1f}%)")

    # For positions over water (no county match), assign water body loc_id
    water_mask = gdf_with_counties['loc_id'].isna()
    gdf_with_counties.loc[water_mask, 'loc_id'] = gdf_with_counties.loc[water_mask].apply(
        lambda row: get_water_body_loc_id(row['latitude'], row['longitude']),
        axis=1
    )

    matched_water = water_mask.sum()
    print(f"  Assigned to water bodies: {matched_water:,} ({matched_water/len(gdf_with_counties)*100:.1f}%)")

    # Count by water body
    water_counts = gdf_with_counties[water_mask]['loc_id'].value_counts()
    for loc_id, count in water_counts.head(5).items():
        print(f"    {loc_id}: {count:,}")

    return gdf_with_counties


def create_storms_parquet(storms_df):
    """Create storms.parquet with storm metadata."""
    print("\nCreating storms.parquet...")

    # Prepare storms dataframe
    storms_out = pd.DataFrame({
        'storm_id': storms_df['storm_id'],
        'basin': storms_df['basin'],
        'name': storms_df['name'],
        'year': storms_df['year'],
        'start_date': storms_df['start_date'],
        'end_date': storms_df['end_date'],
        'max_wind_kt': storms_df['max_wind_kt'],
        'min_pressure_mb': storms_df['min_pressure_mb'],
        'max_category': storms_df['max_category'],
        'num_positions': storms_df['num_positions'],
        'made_landfall': storms_df['made_landfall'],
        'us_landfall': storms_df['us_landfall']
    })

    # Define schema
    schema = pa.schema([
        ('storm_id', pa.string()),
        ('basin', pa.string()),
        ('name', pa.string()),
        ('year', pa.int32()),
        ('start_date', pa.timestamp('us')),
        ('end_date', pa.timestamp('us')),
        ('max_wind_kt', pa.int32()),
        ('min_pressure_mb', pa.int32()),
        ('max_category', pa.string()),
        ('num_positions', pa.int32()),
        ('made_landfall', pa.bool_()),
        ('us_landfall', pa.bool_())
    ])

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "storms.parquet"

    table = pa.Table.from_pandas(storms_out, schema=schema, preserve_index=False)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Saved: {size_mb:.2f} MB")
    print(f"  Storms: {len(storms_out):,}")

    return storms_out


def create_positions_parquet(positions_df):
    """Create positions.parquet with track positions."""
    print("\nCreating positions.parquet...")

    # Select columns
    cols = ['storm_id', 'timestamp', 'record_id', 'status', 'latitude', 'longitude',
            'wind_kt', 'pressure_mb', 'category']

    # Add wind radii columns if present
    radii_cols = ['r34_ne', 'r34_se', 'r34_sw', 'r34_nw',
                  'r50_ne', 'r50_se', 'r50_sw', 'r50_nw',
                  'r64_ne', 'r64_se', 'r64_sw', 'r64_nw']

    for col in radii_cols:
        if col in positions_df.columns:
            cols.append(col)

    if 'loc_id' in positions_df.columns:
        cols.append('loc_id')

    positions_out = positions_df[cols].copy()

    # Round coordinates
    positions_out['latitude'] = positions_out['latitude'].round(2)
    positions_out['longitude'] = positions_out['longitude'].round(2)

    # Build schema dynamically
    schema_fields = [
        ('storm_id', pa.string()),
        ('timestamp', pa.timestamp('us')),
        ('record_id', pa.string()),
        ('status', pa.string()),
        ('latitude', pa.float32()),
        ('longitude', pa.float32()),
        ('wind_kt', pa.int32()),
        ('pressure_mb', pa.int32()),
        ('category', pa.string())
    ]

    for col in radii_cols:
        if col in positions_out.columns:
            schema_fields.append((col, pa.int32()))

    if 'loc_id' in positions_out.columns:
        schema_fields.append(('loc_id', pa.string()))

    schema = pa.schema(schema_fields)

    # Save
    output_path = OUTPUT_DIR / "positions.parquet"

    table = pa.Table.from_pandas(positions_out, schema=schema, preserve_index=False)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Saved: {size_mb:.2f} MB")
    print(f"  Positions: {len(positions_out):,}")

    return positions_out


def create_county_aggregates(storms_df, positions_df):
    """Create USA.parquet with county-year aggregates."""
    print("\nCreating county-year aggregates...")

    # Filter to positions with county match
    if 'loc_id' not in positions_df.columns:
        print("  No loc_id column in positions!")
        return pd.DataFrame()

    df_with_county = positions_df[positions_df['loc_id'].notna()].copy()

    if len(df_with_county) == 0:
        print("  No positions matched to counties!")
        return pd.DataFrame()

    df_with_county['year'] = df_with_county['timestamp'].dt.year

    # Group by county-year
    grouped = df_with_county.groupby(['loc_id', 'year'])

    aggregates = grouped.agg({
        'storm_id': 'nunique',  # distinct storms
        'wind_kt': 'max',  # max wind observed
    }).reset_index()

    aggregates.columns = ['loc_id', 'year', 'storm_count', 'max_wind_kt']

    # Add category for max wind
    aggregates['max_category'] = aggregates['max_wind_kt'].apply(wind_to_category)

    print(f"  County-year records: {len(aggregates):,}")
    print(f"  Unique counties: {aggregates['loc_id'].nunique():,}")

    return aggregates


def save_county_parquet(df):
    """Save county aggregates to USA.parquet."""
    if df.empty:
        print("\n  Skipping USA.parquet (no data)")
        return None

    print("\nSaving USA.parquet...")

    # Define schema
    schema = pa.schema([
        ('loc_id', pa.string()),
        ('year', pa.int32()),
        ('storm_count', pa.int32()),
        ('max_wind_kt', pa.int32()),
        ('max_category', pa.string())
    ])

    # Save
    output_path = OUTPUT_DIR / "USA.parquet"

    table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Saved: {size_mb:.2f} MB")

    return output_path


def generate_metadata(storms_df, positions_df, county_df):
    """Generate metadata.json for the dataset."""
    print("\nGenerating metadata.json...")

    min_year = int(storms_df['year'].min())
    max_year = int(storms_df['year'].max())

    metrics = {
        "storm_count": {
            "name": "Hurricane/Storm Count",
            "description": "Number of tropical storms/hurricanes affecting county during year",
            "unit": "count",
            "aggregation": "sum",
            "file": "USA.parquet"
        },
        "max_wind_kt": {
            "name": "Maximum Wind Speed",
            "description": "Maximum sustained wind speed observed in county during year",
            "unit": "knots",
            "aggregation": "max",
            "file": "USA.parquet"
        },
        "max_category": {
            "name": "Maximum Category",
            "description": "Highest Saffir-Simpson category (TD, TS, Cat1-5) in county during year",
            "unit": "category",
            "file": "USA.parquet"
        },
        "wind_kt": {
            "name": "Wind Speed",
            "description": "Maximum sustained wind speed at 6-hourly track position",
            "unit": "knots",
            "file": "positions.parquet"
        },
        "pressure_mb": {
            "name": "Central Pressure",
            "description": "Minimum central pressure at track position",
            "unit": "millibars",
            "file": "positions.parquet"
        }
    }

    metadata = {
        "source_id": "noaa_hurricanes",
        "source_name": "NOAA NHC HURDAT2 Hurricane Database",
        "description": f"Atlantic and Pacific hurricane tracks and statistics ({min_year}-{max_year})",

        "source": {
            "name": "NOAA National Hurricane Center",
            "url": "https://www.nhc.noaa.gov/data/hurdat/",
            "license": "Public Domain (US Government)"
        },

        "geographic_level": "county",
        "geographic_coverage": {
            "type": "country",
            "countries": 1,
            "country_codes": ["USA"]
        },
        "coverage_description": "USA (Atlantic and Gulf Coast, Hawaii, Puerto Rico)",

        "temporal_coverage": {
            "start": min_year,
            "end": max_year,
            "frequency": "event-based (6-hourly positions)"
        },

        "files": {
            "storms": {
                "filename": "storms.parquet",
                "description": "Storm metadata with max intensity and landfall info",
                "record_type": "storm",
                "record_count": len(storms_df)
            },
            "positions": {
                "filename": "positions.parquet",
                "description": "6-hourly track positions with wind radii",
                "record_type": "position",
                "record_count": len(positions_df)
            },
            "county_aggregates": {
                "filename": "USA.parquet",
                "description": "County-year hurricane statistics",
                "record_type": "county-year",
                "record_count": len(county_df) if county_df is not None and not county_df.empty else 0
            }
        },

        "metrics": metrics,

        "llm_summary": f"HURDAT2 hurricane data for USA, {min_year}-{max_year}. "
                      f"{len(storms_df):,} storms, {len(positions_df):,} track positions. "
                      f"Includes Atlantic and Eastern Pacific basins.",

        "processing": {
            "converter": "data_converters/convert_hurdat2.py",
            "last_run": pd.Timestamp.now().strftime("%Y-%m-%d"),
            "geocoding_method": "Spatial join with Census TIGER/Line 2024 county boundaries"
        }
    }

    # Write metadata.json
    metadata_path = OUTPUT_DIR / "metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    print(f"  Saved: {metadata_path}")


def print_statistics(storms_df, positions_df):
    """Print summary statistics."""
    print("\n" + "="*80)
    print("STATISTICS")
    print("="*80)

    print(f"\nTotal storms: {len(storms_df):,}")
    print(f"Year range: {storms_df['year'].min()}-{storms_df['year'].max()}")
    print(f"Storms with US landfall: {storms_df['us_landfall'].sum():,}")

    print("\nCategory Distribution:")
    for cat in ['TD', 'TS', 'Cat1', 'Cat2', 'Cat3', 'Cat4', 'Cat5']:
        count = (storms_df['max_category'] == cat).sum()
        print(f"  {cat}: {count:,}")

    print("\nMost Active Years:")
    year_counts = storms_df.groupby('year').size().nlargest(10)
    for year, count in year_counts.items():
        print(f"  {year}: {count:,} storms")

    print("\nDeadliest Hurricanes (by category):")
    cat5 = storms_df[storms_df['max_category'] == 'Cat5'].nlargest(10, 'max_wind_kt')
    for _, row in cat5.head(10).iterrows():
        name = row['name'] if row['name'] else 'UNNAMED'
        print(f"  {name} ({row['year']}) - {row['max_wind_kt']} kt, {row['min_pressure_mb']} mb")


def main():
    """Main conversion logic."""
    print("="*80)
    print("NOAA HURDAT2 Hurricane Database - Text to Parquet Converter")
    print("="*80)

    # Load county boundaries
    counties_gdf = load_counties()

    # Load HURDAT2 data
    storms_df, positions_df = load_hurdat2_data()

    if storms_df.empty:
        print("\nERROR: No hurricane data loaded")
        return 1

    # Filter to US-affecting storms
    us_storms, us_positions = filter_us_affecting_storms(storms_df, positions_df)

    # Geocode positions to counties
    us_positions_geocoded = geocode_positions(us_positions, counties_gdf)

    # Create output files
    storms_out = create_storms_parquet(us_storms)
    positions_out = create_positions_parquet(us_positions_geocoded)

    # Create county aggregates
    county_df = create_county_aggregates(us_storms, us_positions_geocoded)
    save_county_parquet(county_df)

    # Print statistics
    print_statistics(storms_out, positions_out)

    # Generate metadata
    generate_metadata(storms_out, positions_out, county_df)

    print("\n" + "="*80)
    print("COMPLETE!")
    print("="*80)
    print("\nOutput files:")
    print("  storms.parquet: Storm metadata with max intensity")
    print("  positions.parquet: 6-hourly track positions")
    print("  USA.parquet: County-year aggregated statistics")
    print("  metadata.json: Standard metadata format")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
