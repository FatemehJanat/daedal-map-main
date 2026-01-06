"""
Convert Smithsonian Global Volcanism Program data to parquet format.

Creates two output files:
1. volcanoes.parquet - Volcano locations with metadata
2. eruptions.parquet - Historical eruption events
3. USA.parquet - County-year aggregated eruption statistics

Input: GeoJSON files from Smithsonian GVP
Output: Three parquet files with volcano/eruption data

Usage:
    python convert_volcano.py
"""
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import geopandas as gpd
from pathlib import Path
from shapely.geometry import Point, shape
import json

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/smithsonian/volcano")
GEOMETRY_PATH = Path("C:/Users/Bryan/Desktop/county-map-data/geometry/USA.parquet")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA/volcanoes")

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

# US regions/countries in Smithsonian data
US_REGIONS = [
    'United States',
    'Northern Mariana Islands',
    'Guam',
    'American Samoa'
]


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
    Water body codes follow ISO 3166-1 X-prefix convention:
      XOP = Pacific Ocean
      XOA = Atlantic Ocean
      XOI = Indian Ocean

    Used for submarine volcanoes that don't fall within county boundaries.
    """
    if pd.isna(lat) or pd.isna(lon):
        return None

    # Pacific Ocean (most US submarine volcanoes are here - Hawaii, Mariana, etc.)
    if lon < -100 or lon > 100:
        return "XOP-0"

    # Atlantic Ocean
    if -100 <= lon <= 0 and lat > 0:
        return "XOA-0"

    # Default to Pacific for US territories
    return "XOP-0"


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


def load_volcano_data():
    """Load volcanoes and eruptions from GeoJSON files."""
    print("\nLoading volcano data...")

    # Load volcanoes
    volcanoes_path = RAW_DATA_DIR / "gvp_volcanoes.json"
    with open(volcanoes_path, 'r', encoding='utf-8') as f:
        volcanoes_geojson = json.load(f)

    # Extract features to dataframe
    volcanoes_list = []
    for feature in volcanoes_geojson['features']:
        props = feature['properties']
        coords = feature['geometry']['coordinates']
        volcanoes_list.append({
            'volcano_number': props.get('Volcano_Number'),
            'volcano_name': props.get('Volcano_Name'),
            'country': props.get('Country'),
            'region': props.get('Region'),
            'subregion': props.get('Subregion'),
            'latitude': props.get('Latitude'),
            'longitude': props.get('Longitude'),
            'elevation_m': props.get('Elevation'),
            'volcano_type': props.get('Primary_Volcano_Type'),
            'last_eruption_year': props.get('Last_Eruption_Year'),
            'tectonic_setting': props.get('Tectonic_Setting'),
            'rock_type': props.get('Major_Rock_Type'),
            'geologic_epoch': props.get('Geologic_Epoch')
        })

    volcanoes_df = pd.DataFrame(volcanoes_list)
    print(f"  Total volcanoes: {len(volcanoes_df):,}")

    # Load eruptions
    eruptions_path = RAW_DATA_DIR / "gvp_eruptions.json"
    with open(eruptions_path, 'r', encoding='utf-8') as f:
        eruptions_geojson = json.load(f)

    # Extract features to dataframe
    eruptions_list = []
    for feature in eruptions_geojson['features']:
        props = feature['properties']
        coords = feature['geometry']['coordinates']
        eruptions_list.append({
            'volcano_number': props.get('Volcano_Number'),
            'volcano_name': props.get('Volcano_Name'),
            'eruption_number': props.get('Eruption_Number'),
            'activity_type': props.get('Activity_Type'),
            'vei': props.get('ExplosivityIndexMax'),  # Volcanic Explosivity Index
            'start_year': props.get('StartDateYear'),
            'start_month': props.get('StartDateMonth'),
            'start_day': props.get('StartDateDay'),
            'end_year': props.get('EndDateYear'),
            'end_month': props.get('EndDateMonth'),
            'end_day': props.get('EndDateDay'),
            'latitude': coords[1] if coords else None,
            'longitude': coords[0] if coords else None
        })

    eruptions_df = pd.DataFrame(eruptions_list)
    print(f"  Total eruptions: {len(eruptions_df):,}")

    return volcanoes_df, eruptions_df


def filter_us_data(volcanoes_df, eruptions_df):
    """Filter to US volcanoes and their eruptions."""
    print("\nFiltering to US data...")

    # Filter volcanoes to US
    us_volcanoes = volcanoes_df[volcanoes_df['country'].isin(US_REGIONS)].copy()
    us_volcano_numbers = set(us_volcanoes['volcano_number'].tolist())

    # Filter eruptions to US volcanoes
    us_eruptions = eruptions_df[eruptions_df['volcano_number'].isin(us_volcano_numbers)].copy()

    print(f"  US volcanoes: {len(us_volcanoes):,}")
    print(f"  US eruptions: {len(us_eruptions):,}")

    # Show region breakdown
    print("\n  By region:")
    for region, count in us_volcanoes['region'].value_counts().items():
        print(f"    {region}: {count}")

    return us_volcanoes, us_eruptions


def geocode_volcanoes(volcanoes_df, counties_gdf):
    """Geocode volcano locations to counties."""
    print("\nGeocoding volcanoes to counties...")

    # Filter to volcanoes with coordinates
    volcanoes_with_coords = volcanoes_df.dropna(subset=['latitude', 'longitude']).copy()
    print(f"  Volcanoes with coordinates: {len(volcanoes_with_coords):,}")

    if len(volcanoes_with_coords) == 0:
        return volcanoes_df

    # Create geometry
    geometry = [Point(xy) for xy in zip(volcanoes_with_coords['longitude'],
                                         volcanoes_with_coords['latitude'])]
    gdf = gpd.GeoDataFrame(volcanoes_with_coords, geometry=geometry, crs="EPSG:4326")

    # Spatial join with counties (geometry parquet already has loc_id)
    gdf_with_counties = gpd.sjoin(gdf, counties_gdf[['loc_id', 'geom']].set_geometry('geom'),
                                   how='left', predicate='within')

    matched = gdf_with_counties['loc_id'].notna().sum()
    print(f"  Matched to counties: {matched:,} ({matched/len(gdf_with_counties)*100:.1f}%)")

    # For volcanoes not matched to counties (submarine, remote territories), assign water body loc_id
    water_mask = gdf_with_counties['loc_id'].isna()
    if water_mask.any():
        gdf_with_counties.loc[water_mask, 'loc_id'] = gdf_with_counties.loc[water_mask].apply(
            lambda row: get_water_body_loc_id(row['latitude'], row['longitude']),
            axis=1
        )
        water_count = water_mask.sum()
        print(f"  Assigned water body loc_id: {water_count:,} (submarine/remote volcanoes)")

        # Show breakdown by loc_id
        loc_id_counts = gdf_with_counties['loc_id'].value_counts()
        water_body_counts = loc_id_counts[loc_id_counts.index.str.startswith('X', na=False)]
        if not water_body_counts.empty:
            print(f"  Water body breakdown: {dict(water_body_counts)}")

    return gdf_with_counties


def create_volcanoes_parquet(volcanoes_df):
    """Create volcanoes.parquet with volcano locations."""
    print("\nCreating volcanoes.parquet...")

    # Prepare volcanoes dataframe
    volcanoes_out = pd.DataFrame({
        'volcano_number': volcanoes_df['volcano_number'],
        'volcano_name': volcanoes_df['volcano_name'],
        'country': volcanoes_df['country'],
        'region': volcanoes_df['region'],
        'subregion': volcanoes_df['subregion'],
        'latitude': volcanoes_df['latitude'].round(4),
        'longitude': volcanoes_df['longitude'].round(4),
        'elevation_m': volcanoes_df['elevation_m'],
        'volcano_type': volcanoes_df['volcano_type'],
        'last_eruption_year': volcanoes_df['last_eruption_year'],
        'tectonic_setting': volcanoes_df['tectonic_setting'],
        'rock_type': volcanoes_df['rock_type'],
        'loc_id': volcanoes_df.get('loc_id', pd.NA)
    })

    # Define schema
    schema = pa.schema([
        ('volcano_number', pa.int64()),
        ('volcano_name', pa.string()),
        ('country', pa.string()),
        ('region', pa.string()),
        ('subregion', pa.string()),
        ('latitude', pa.float32()),
        ('longitude', pa.float32()),
        ('elevation_m', pa.int32()),
        ('volcano_type', pa.string()),
        ('last_eruption_year', pa.int32()),
        ('tectonic_setting', pa.string()),
        ('rock_type', pa.string()),
        ('loc_id', pa.string())
    ])

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "volcanoes.parquet"

    table = pa.Table.from_pandas(volcanoes_out, schema=schema, preserve_index=False)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Saved: {size_mb:.2f} MB")
    print(f"  Volcanoes: {len(volcanoes_out):,}")

    return volcanoes_out


def create_eruptions_parquet(eruptions_df, volcanoes_df):
    """Create eruptions.parquet with eruption events."""
    print("\nCreating eruptions.parquet...")

    # Join eruptions with volcano loc_id
    volcano_loc_ids = volcanoes_df[['volcano_number', 'loc_id']].drop_duplicates()
    eruptions_with_loc = eruptions_df.merge(volcano_loc_ids, on='volcano_number', how='left')

    # Prepare eruptions dataframe
    eruptions_out = pd.DataFrame({
        'eruption_number': eruptions_with_loc['eruption_number'],
        'volcano_number': eruptions_with_loc['volcano_number'],
        'volcano_name': eruptions_with_loc['volcano_name'],
        'activity_type': eruptions_with_loc['activity_type'],
        'vei': eruptions_with_loc['vei'],
        'start_year': eruptions_with_loc['start_year'],
        'start_month': eruptions_with_loc['start_month'],
        'start_day': eruptions_with_loc['start_day'],
        'end_year': eruptions_with_loc['end_year'],
        'latitude': eruptions_with_loc['latitude'].round(4) if pd.notna(eruptions_with_loc['latitude']).any() else pd.NA,
        'longitude': eruptions_with_loc['longitude'].round(4) if pd.notna(eruptions_with_loc['longitude']).any() else pd.NA,
        'loc_id': eruptions_with_loc.get('loc_id', pd.NA)
    })

    # Define schema
    schema = pa.schema([
        ('eruption_number', pa.int64()),
        ('volcano_number', pa.int64()),
        ('volcano_name', pa.string()),
        ('activity_type', pa.string()),
        ('vei', pa.int32()),
        ('start_year', pa.int32()),
        ('start_month', pa.int32()),
        ('start_day', pa.int32()),
        ('end_year', pa.int32()),
        ('latitude', pa.float32()),
        ('longitude', pa.float32()),
        ('loc_id', pa.string())
    ])

    # Save
    output_path = OUTPUT_DIR / "eruptions.parquet"

    table = pa.Table.from_pandas(eruptions_out, schema=schema, preserve_index=False)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Saved: {size_mb:.2f} MB")
    print(f"  Eruptions: {len(eruptions_out):,}")

    return eruptions_out


def create_county_aggregates(eruptions_df):
    """Create USA.parquet with county-year aggregates based on eruptions."""
    print("\nCreating county-year aggregates...")

    # Filter to eruptions with county match and valid year
    df_with_county = eruptions_df[
        (eruptions_df['loc_id'].notna()) &
        (eruptions_df['start_year'].notna()) &
        (eruptions_df['start_year'] > 0)  # Filter out prehistoric
    ].copy()

    if len(df_with_county) == 0:
        print("  No eruptions matched to counties with valid years!")
        return pd.DataFrame()

    df_with_county['year'] = df_with_county['start_year'].astype(int)

    # Group by county-year
    grouped = df_with_county.groupby(['loc_id', 'year'])

    aggregates = grouped.agg({
        'eruption_number': 'count',  # number of eruptions
        'volcano_number': 'nunique',  # distinct volcanoes
        'vei': ['max', 'mean']  # max and average VEI
    }).reset_index()

    # Flatten column names
    aggregates.columns = ['loc_id', 'year', 'eruption_count', 'volcano_count', 'max_vei', 'avg_vei']
    aggregates['avg_vei'] = aggregates['avg_vei'].round(1)

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
        ('eruption_count', pa.int32()),
        ('volcano_count', pa.int32()),
        ('max_vei', pa.int32()),
        ('avg_vei', pa.float32())
    ])

    # Save
    output_path = OUTPUT_DIR / "USA.parquet"

    table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Saved: {size_mb:.2f} MB")

    return output_path


def generate_metadata(volcanoes_df, eruptions_df, county_df):
    """Generate metadata.json for the dataset."""
    print("\nGenerating metadata.json...")

    # Year range (filter out prehistoric years < 0)
    valid_years = eruptions_df[eruptions_df['start_year'] > 0]['start_year']
    min_year = int(valid_years.min()) if not valid_years.empty else 0
    max_year = int(valid_years.max()) if not valid_years.empty else 0

    metrics = {
        "eruption_count": {
            "name": "Eruption Count",
            "description": "Number of volcanic eruptions in county during year",
            "unit": "count",
            "aggregation": "sum",
            "file": "USA.parquet"
        },
        "volcano_count": {
            "name": "Active Volcano Count",
            "description": "Number of distinct volcanoes that erupted in county during year",
            "unit": "count",
            "aggregation": "sum",
            "file": "USA.parquet"
        },
        "max_vei": {
            "name": "Maximum VEI",
            "description": "Maximum Volcanic Explosivity Index for eruptions in county during year",
            "unit": "VEI scale (0-8)",
            "aggregation": "max",
            "file": "USA.parquet"
        },
        "vei": {
            "name": "Volcanic Explosivity Index",
            "description": "VEI measures eruption magnitude (0=gentle effusive, 8=mega-colossal)",
            "unit": "VEI scale (0-8)",
            "file": "eruptions.parquet"
        }
    }

    metadata = {
        "source_id": "smithsonian_volcanoes",
        "source_name": "Smithsonian Global Volcanism Program",
        "description": f"Holocene volcano locations and eruption history for US territory ({min_year}-{max_year})",

        "source": {
            "name": "Smithsonian Institution Global Volcanism Program",
            "url": "https://volcano.si.edu/",
            "license": "Public Domain / Creative Commons"
        },

        "geographic_level": "county",
        "geographic_coverage": {
            "type": "country",
            "countries": 1,
            "country_codes": ["USA"]
        },
        "coverage_description": "USA (primarily Alaska, Hawaii, Cascades, Yellowstone)",

        "temporal_coverage": {
            "start": min_year,
            "end": max_year,
            "frequency": "event-based"
        },

        "files": {
            "volcanoes": {
                "filename": "volcanoes.parquet",
                "description": "Holocene volcano locations with metadata",
                "record_type": "location",
                "record_count": len(volcanoes_df)
            },
            "eruptions": {
                "filename": "eruptions.parquet",
                "description": "Historical eruption events with VEI and dates",
                "record_type": "event",
                "record_count": len(eruptions_df)
            },
            "county_aggregates": {
                "filename": "USA.parquet",
                "description": "County-year eruption statistics",
                "record_type": "county-year",
                "record_count": len(county_df) if county_df is not None and not county_df.empty else 0
            }
        },

        "metrics": metrics,

        "llm_summary": f"Smithsonian GVP volcano data for USA, {min_year}-{max_year}. "
                      f"{len(volcanoes_df):,} volcanoes, {len(eruptions_df):,} eruptions. "
                      f"Primarily in Alaska (Aleutians), Hawaii, and Cascades (WA/OR).",

        "processing": {
            "converter": "data_converters/convert_volcano.py",
            "last_run": pd.Timestamp.now().strftime("%Y-%m-%d"),
            "geocoding_method": "Spatial join with Census TIGER/Line 2024 county boundaries"
        }
    }

    # Write metadata.json
    metadata_path = OUTPUT_DIR / "metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    print(f"  Saved: {metadata_path}")


def print_statistics(volcanoes_df, eruptions_df):
    """Print summary statistics."""
    print("\n" + "="*80)
    print("STATISTICS")
    print("="*80)

    print(f"\nTotal US volcanoes: {len(volcanoes_df):,}")
    print(f"Total US eruptions: {len(eruptions_df):,}")

    print("\nVolcano Types:")
    for vtype, count in volcanoes_df['volcano_type'].value_counts().head(10).items():
        print(f"  {vtype}: {count:,}")

    print("\nVEI Distribution (eruptions):")
    if 'vei' in eruptions_df.columns:
        for vei, count in eruptions_df['vei'].value_counts().sort_index().items():
            if pd.notna(vei):
                print(f"  VEI {int(vei)}: {count:,}")

    print("\nMost Active Volcanoes:")
    eruption_counts = eruptions_df.groupby('volcano_name').size().nlargest(10)
    for volcano, count in eruption_counts.items():
        print(f"  {volcano}: {count:,} eruptions")

    print("\nRecent Eruptions (2000+):")
    recent = eruptions_df[eruptions_df['start_year'] >= 2000].sort_values('start_year', ascending=False)
    for _, row in recent.head(10).iterrows():
        vei_str = f"VEI {int(row['vei'])}" if pd.notna(row['vei']) else "VEI ?"
        print(f"  {row['volcano_name']} ({int(row['start_year'])}) - {vei_str}")


def main():
    """Main conversion logic."""
    print("="*80)
    print("Smithsonian Volcano Database - GeoJSON to Parquet Converter")
    print("="*80)

    # Load county boundaries
    counties_gdf = load_counties()

    # Load volcano data
    volcanoes_df, eruptions_df = load_volcano_data()

    # Filter to US data
    us_volcanoes, us_eruptions = filter_us_data(volcanoes_df, eruptions_df)

    if us_volcanoes.empty:
        print("\nERROR: No US volcanoes found")
        return 1

    # Geocode volcanoes to counties
    us_volcanoes_geocoded = geocode_volcanoes(us_volcanoes, counties_gdf)

    # Create output files
    volcanoes_out = create_volcanoes_parquet(us_volcanoes_geocoded)
    eruptions_out = create_eruptions_parquet(us_eruptions, us_volcanoes_geocoded)

    # Create county aggregates
    county_df = create_county_aggregates(eruptions_out)
    save_county_parquet(county_df)

    # Print statistics
    print_statistics(volcanoes_out, eruptions_out)

    # Generate metadata
    generate_metadata(volcanoes_out, eruptions_out, county_df)

    print("\n" + "="*80)
    print("COMPLETE!")
    print("="*80)
    print("\nOutput files:")
    print("  volcanoes.parquet: Volcano locations with metadata")
    print("  eruptions.parquet: Historical eruption events")
    print("  USA.parquet: County-year aggregated statistics")
    print("  metadata.json: Standard metadata format")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
