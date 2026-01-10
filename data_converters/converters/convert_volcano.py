"""
Convert Smithsonian Global Volcanism Program data to parquet format.

Creates three output files:
1. volcanoes.parquet - Volcano locations with metadata
2. eruptions.parquet - Historical eruption events
3. USA.parquet - County-year aggregated eruption statistics

Input: GeoJSON files from Smithsonian GVP
Output: Three parquet files with volcano/eruption data

Uses unified base utilities for spatial join and water body assignment.

Usage:
    python convert_volcano.py
"""
import pandas as pd
import geopandas as gpd
from pathlib import Path
import json
import sys

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from data_converters.base import (
    USA_STATE_FIPS,
    load_geometry_parquet,
    get_water_body_loc_id,
    create_point_gdf,
    save_parquet,
    VEI_SCALE,
)
from build.catalog.finalize_source import finalize_source

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/smithsonian/volcano")
IMPORTED_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/imported/smithsonian/volcano")
GEOMETRY_PATH = Path("C:/Users/Bryan/Desktop/county-map-data/geometry/USA.parquet")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA/volcanoes")
SOURCE_ID = "smithsonian_volcanoes"


# =============================================================================
# Eruption Radius Calculations
# =============================================================================

def calculate_felt_radius_km(vei):
    """
    Calculate eruption "felt" radius in km based on VEI.

    VEI is logarithmic (each step = 10x ejecta volume).
    Radius scales as cube root of volume: R ~ 10^(VEI/3)

    Formula: felt_radius = 5 * 10^(VEI * 0.33)

    This gives approximately:
    - VEI 0: ~5 km (local effects)
    - VEI 2: ~11 km (regional ash fall)
    - VEI 4: ~23 km (significant ash)
    - VEI 5: ~50 km (Mt St Helens scale)
    - VEI 6: ~108 km (Pinatubo scale)
    - VEI 7: ~232 km (major caldera)

    Calibrated against Tambora VEI 7 which had ash 600 km.
    """
    if pd.isna(vei):
        return 10.0  # Default for unknown VEI
    vei = max(0, int(vei))
    # Formula: 5 * 10^(VEI * 0.33)
    return round(5 * (10 ** (vei * 0.33)), 1)


def calculate_damage_radius_km(vei):
    """
    Calculate eruption "damage" radius in km based on VEI.

    Damage zone (pyroclastic flows, lahars, heavy ashfall)
    is much smaller than felt radius.

    Formula: damage_radius = 1 * 10^(VEI * 0.3)

    This gives approximately:
    - VEI 0: ~1 km (immediate vicinity)
    - VEI 2: ~4 km
    - VEI 4: ~16 km
    - VEI 5: ~32 km
    - VEI 6: ~63 km
    - VEI 7: ~126 km
    """
    if pd.isna(vei):
        return 3.0  # Default for unknown VEI
    vei = max(0, int(vei))
    # Formula: 1 * 10^(VEI * 0.3)
    return round(1 * (10 ** (vei * 0.3)), 1)


def get_source_dir():
    """Get source directory - check raw first, then imported."""
    if RAW_DATA_DIR.exists() and (RAW_DATA_DIR / "gvp_volcanoes.json").exists():
        return RAW_DATA_DIR
    elif IMPORTED_DIR.exists() and (IMPORTED_DIR / "gvp_volcanoes.json").exists():
        print(f"  Note: Using imported data from {IMPORTED_DIR}")
        return IMPORTED_DIR
    return RAW_DATA_DIR


def move_to_imported():
    """Move processed raw files to imported folder."""
    import shutil
    if RAW_DATA_DIR.exists() and (RAW_DATA_DIR / "gvp_volcanoes.json").exists():
        IMPORTED_DIR.mkdir(parents=True, exist_ok=True)
        for f in RAW_DATA_DIR.glob("*.json"):
            shutil.move(str(f), str(IMPORTED_DIR / f.name))
        print(f"  Moved files to {IMPORTED_DIR}")

# US regions/countries in Smithsonian data
US_REGIONS = [
    'United States',
    'Northern Mariana Islands',
    'Guam',
    'American Samoa'
]


# =============================================================================
# Data Loading
# =============================================================================

def load_counties():
    """Load county boundaries from geometry parquet using base utility."""
    return load_geometry_parquet(GEOMETRY_PATH, admin_level=2, geometry_format='geojson')


def load_volcano_data():
    """Load volcanoes and eruptions from GeoJSON files."""
    print("\nLoading volcano data...")

    source_dir = get_source_dir()

    # Load volcanoes
    volcanoes_path = source_dir / "gvp_volcanoes.json"
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
    eruptions_path = source_dir / "gvp_eruptions.json"
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
    """Geocode volcano locations to counties using base utilities."""
    print("\nGeocoding volcanoes to counties...")

    # Filter to volcanoes with coordinates
    volcanoes_with_coords = volcanoes_df.dropna(subset=['latitude', 'longitude']).copy()
    print(f"  Volcanoes with coordinates: {len(volcanoes_with_coords):,}")

    if len(volcanoes_with_coords) == 0:
        return volcanoes_df

    # Create point geometries using base utility
    gdf = create_point_gdf(volcanoes_with_coords, lat_col='latitude', lon_col='longitude')

    # Spatial join with counties
    gdf_with_counties = gpd.sjoin(gdf, counties_gdf[['loc_id', 'geometry']],
                                   how='left', predicate='within')

    matched = gdf_with_counties['loc_id'].notna().sum()
    print(f"  Matched to counties: {matched:,} ({matched/len(gdf_with_counties)*100:.1f}%)")

    # For volcanoes not matched to counties (submarine, remote territories), assign water body loc_id
    water_mask = gdf_with_counties['loc_id'].isna()
    if water_mask.any():
        gdf_with_counties.loc[water_mask, 'loc_id'] = gdf_with_counties.loc[water_mask].apply(
            lambda row: get_water_body_loc_id(row['latitude'], row['longitude'], region='usa'),
            axis=1
        )
        water_count = water_mask.sum()
        print(f"  Assigned water body loc_id: {water_count:,} (submarine/remote volcanoes)")

        # Show breakdown by loc_id
        loc_id_counts = gdf_with_counties['loc_id'].value_counts()
        water_body_counts = loc_id_counts[loc_id_counts.index.str.startswith('X', na=False)]
        if not water_body_counts.empty:
            print(f"  Water body breakdown: {dict(water_body_counts)}")

    # Clean up join artifacts
    gdf_with_counties = gdf_with_counties.drop(columns=['index_right'], errors='ignore')

    return gdf_with_counties


def create_volcanoes_parquet(volcanoes_df):
    """Create volcanoes.parquet with volcano locations."""
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

    # Save using base utility
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "volcanoes.parquet"
    save_parquet(volcanoes_out, output_path, description="volcano locations")

    return volcanoes_out


def create_eruptions_parquet(eruptions_df, volcanoes_df):
    """Create eruptions.parquet with eruption events.

    Standard Point+Radius Event Schema (for frontend display):
    - event_id: unique identifier
    - timestamp: event datetime (ISO format)
    - latitude, longitude: event location
    - loc_id: assigned county/water body code
    - felt_radius_km: outer impact radius (lighter display)
    - damage_radius_km: inner damage radius (bolder display)
    - [source-specific fields]: magnitude/VEI/intensity etc for coloring
    """
    # Join eruptions with volcano loc_id
    volcano_loc_ids = volcanoes_df[['volcano_number', 'loc_id']].drop_duplicates()
    eruptions_with_loc = eruptions_df.merge(volcano_loc_ids, on='volcano_number', how='left')

    # Build timestamp from start_year/start_month/start_day
    # Note: Timestamps only work for positive years (CE). Prehistoric eruptions get null timestamp.
    def build_timestamp(row):
        try:
            year = int(row['start_year']) if pd.notna(row['start_year']) else None
            if year and year > 0:
                # Default month/day to 1 if 0 or missing
                month = int(row.get('start_month', 1)) if pd.notna(row.get('start_month')) and row.get('start_month') > 0 else 1
                day = int(row.get('start_day', 1)) if pd.notna(row.get('start_day')) and row.get('start_day') > 0 else 1
                # Clamp to valid ranges
                month = max(1, min(12, month))
                day = max(1, min(28, day))  # Use 28 to avoid month-end issues
                return pd.Timestamp(year=year, month=month, day=day)
        except:
            pass
        return pd.NaT

    eruptions_with_loc = eruptions_with_loc.copy()
    eruptions_with_loc['timestamp'] = eruptions_with_loc.apply(build_timestamp, axis=1)

    # Extract year directly from start_year (works for negative/prehistoric years too)
    eruptions_with_loc['year'] = eruptions_with_loc['start_year'].apply(
        lambda x: int(x) if pd.notna(x) else None
    )

    # Calculate impact radii from VEI
    print("  Calculating impact radii from VEI...")
    eruptions_with_loc['felt_radius_km'] = eruptions_with_loc['vei'].apply(calculate_felt_radius_km)
    eruptions_with_loc['damage_radius_km'] = eruptions_with_loc['vei'].apply(calculate_damage_radius_km)

    # Prepare eruptions dataframe with standard schema
    eruptions_out = pd.DataFrame({
        'event_id': eruptions_with_loc['eruption_number'].apply(lambda x: f"VE{x:06d}" if pd.notna(x) else None),
        'year': eruptions_with_loc['year'],  # Integer year (including negative for prehistoric)
        'timestamp': eruptions_with_loc['timestamp'],  # Full datetime (null for prehistoric)
        'latitude': eruptions_with_loc['latitude'].round(4) if pd.notna(eruptions_with_loc['latitude']).any() else pd.NA,
        'longitude': eruptions_with_loc['longitude'].round(4) if pd.notna(eruptions_with_loc['longitude']).any() else pd.NA,
        'felt_radius_km': eruptions_with_loc['felt_radius_km'],  # Standard: outer impact radius
        'damage_radius_km': eruptions_with_loc['damage_radius_km'],  # Standard: inner damage radius
        'volcano_number': eruptions_with_loc['volcano_number'],
        'volcano_name': eruptions_with_loc['volcano_name'],
        'activity_type': eruptions_with_loc['activity_type'],
        'vei': eruptions_with_loc['vei'],  # Source-specific: used for coloring
        'loc_id': eruptions_with_loc.get('loc_id', pd.NA)
    })

    # Save using base utility
    output_path = OUTPUT_DIR / "eruptions.parquet"
    save_parquet(eruptions_out, output_path, description="eruption events")

    # Print radius stats
    print(f"  Radii calculated: felt_radius range {eruptions_out['felt_radius_km'].min()}-{eruptions_out['felt_radius_km'].max()} km")
    print(f"                    damage_radius range {eruptions_out['damage_radius_km'].min()}-{eruptions_out['damage_radius_km'].max()} km")

    return eruptions_out


def create_county_aggregates(eruptions_df):
    """Create USA.parquet with county-year aggregates based on eruptions."""
    print("\nCreating county-year aggregates...")

    # Filter to eruptions with county match and valid timestamp
    df_with_county = eruptions_df[
        (eruptions_df['loc_id'].notna()) &
        (eruptions_df['timestamp'].notna())
    ].copy()

    if len(df_with_county) == 0:
        print("  No eruptions matched to counties with valid timestamps!")
        return pd.DataFrame()

    # Extract year from timestamp - filter to valid pandas datetime range (1677+)
    # Some eruptions have prehistoric dates that overflow pandas nanosecond bounds
    df_with_county['year'] = df_with_county['timestamp'].apply(
        lambda t: t.year if pd.notna(t) and hasattr(t, 'year') and t.year >= 1677 else None
    )
    df_with_county = df_with_county[df_with_county['year'].notna()].copy()
    df_with_county['year'] = df_with_county['year'].astype(int)

    if len(df_with_county) == 0:
        print("  No eruptions with valid modern timestamps!")
        return pd.DataFrame()

    # Group by county-year
    grouped = df_with_county.groupby(['loc_id', 'year'])

    aggregates = grouped.agg({
        'event_id': 'count',  # number of eruptions
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
    """Save county aggregates to USA.parquet using base utility."""
    if df.empty:
        print("\n  Skipping USA.parquet (no data)")
        return None

    output_path = OUTPUT_DIR / "USA.parquet"
    save_parquet(df, output_path, description="county-year aggregates")

    return output_path


def generate_metadata(volcanoes_df, eruptions_df, county_df):
    """Generate metadata.json for the dataset."""
    print("\nGenerating metadata.json...")

    # Year range from timestamp - extract safely to avoid overflow on prehistoric dates
    valid_timestamps = eruptions_df['timestamp'].dropna()
    valid_years = valid_timestamps.apply(
        lambda t: t.year if pd.notna(t) and hasattr(t, 'year') and t.year >= 1677 else None
    ).dropna()
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
    eruptions_df = eruptions_df.copy()
    # Extract year safely to avoid overflow on prehistoric dates
    eruptions_df['year'] = eruptions_df['timestamp'].apply(
        lambda t: t.year if pd.notna(t) and hasattr(t, 'year') and t.year >= 1677 else None
    )
    recent = eruptions_df[eruptions_df['year'] >= 2000].sort_values('timestamp', ascending=False)
    for _, row in recent.head(10).iterrows():
        vei_str = f"VEI {int(row['vei'])}" if pd.notna(row['vei']) else "VEI ?"
        print(f"  {row['volcano_name']} ({int(row['year'])}) - {vei_str}")


def main():
    """Main conversion logic."""
    print("=" * 60)
    print("Smithsonian Volcano Database Converter")
    print("=" * 60)

    # Load county boundaries using base utility
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
    agg_path = save_county_parquet(county_df)

    # Print statistics
    print_statistics(volcanoes_out, eruptions_out)

    # Generate metadata (custom for volcanoes - 3 files)
    generate_metadata(volcanoes_out, eruptions_out, county_df)

    # Finalize (update index)
    print("\n" + "=" * 60)
    print("Finalizing source...")
    print("=" * 60)

    try:
        if agg_path:
            finalize_source(
                parquet_path=str(agg_path),
                source_id=SOURCE_ID,
                events_parquet_path=str(OUTPUT_DIR / "eruptions.parquet")
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
