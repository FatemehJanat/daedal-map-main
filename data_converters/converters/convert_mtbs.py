"""
Convert MTBS (Monitoring Trends in Burn Severity) wildfire data to parquet format.

Creates two output files:
1. fires.parquet - Individual fire events with perimeter data
2. USA.parquet - County-year aggregated wildfire statistics

Input: MTBS shapefiles from USGS/USFS
Output: Two parquet files with wildfire data

MTBS covers fires >1000 acres (West) or >500 acres (East) from 1984-present.

Uses unified base utilities for spatial join and parquet saving.

Usage:
    python convert_mtbs.py
"""
import pandas as pd
import geopandas as gpd
from pathlib import Path
import json
import zipfile
import sys

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from data_converters.base import (
    USA_STATE_FIPS,
    load_geometry_parquet,
    save_parquet,
    TERRITORIAL_WATERS_DEG,
)
from build.catalog.finalize_source import finalize_source

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/imported/mtbs")
GEOMETRY_PATH = Path("C:/Users/Bryan/Desktop/county-map-data/geometry/USA.parquet")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA/wildfires")
SOURCE_ID = "mtbs_wildfires"

# Simplification tolerance for perimeter geometry (degrees)
# ~0.001 deg = ~100m at mid-latitudes, good balance of detail vs file size
SIMPLIFY_TOLERANCE = 0.001

# Incident types
INCIDENT_TYPES = {
    'WF': 'Wildfire',
    'RX': 'Prescribed Fire',
    'WFU': 'Wildfire Use (managed)',
    'UNK': 'Unknown'
}


# =============================================================================
# Data Loading
# =============================================================================

def load_counties():
    """Load county boundaries from geometry parquet using base utility."""
    return load_geometry_parquet(GEOMETRY_PATH, admin_level=2, geometry_format='geojson')


def load_mtbs_perimeters():
    """Load MTBS fire perimeter data from shapefile."""
    print("\nLoading MTBS perimeter data...")

    # Path to the zip file
    zip_path = RAW_DATA_DIR / "mtbs_perimeter_data.zip"

    if not zip_path.exists():
        print(f"  ERROR: {zip_path} not found")
        return gpd.GeoDataFrame()

    # geopandas can read shapefiles directly from zip
    # First, let's find the shapefile name inside the zip
    with zipfile.ZipFile(zip_path, 'r') as z:
        shp_files = [f for f in z.namelist() if f.endswith('.shp')]
        print(f"  Found shapefiles in zip: {shp_files}")

    if not shp_files:
        print("  ERROR: No shapefile found in zip")
        return gpd.GeoDataFrame()

    # Read the shapefile from the zip
    shp_name = shp_files[0]
    gdf = gpd.read_file(f"zip://{zip_path}!{shp_name}")

    print(f"  Loaded {len(gdf):,} fire perimeters")
    print(f"  Columns: {list(gdf.columns)}")

    return gdf


def load_mtbs_points():
    """Load MTBS fire occurrence points."""
    print("\nLoading MTBS fire occurrence points...")

    zip_path = RAW_DATA_DIR / "mtbs_fod_pts_data.zip"

    if not zip_path.exists():
        print(f"  ERROR: {zip_path} not found")
        return gpd.GeoDataFrame()

    with zipfile.ZipFile(zip_path, 'r') as z:
        shp_files = [f for f in z.namelist() if f.endswith('.shp')]
        print(f"  Found shapefiles in zip: {shp_files}")

    if not shp_files:
        print("  ERROR: No shapefile found in zip")
        return gpd.GeoDataFrame()

    shp_name = shp_files[0]
    gdf = gpd.read_file(f"zip://{zip_path}!{shp_name}")

    print(f"  Loaded {len(gdf):,} fire occurrence points")

    return gdf


def process_perimeters(perimeters_gdf):
    """Process fire perimeter data."""
    print("\nProcessing perimeter data...")

    # Common MTBS column names (may vary by version)
    # Event_ID, Incid_Name, Incid_Type, BurnBndAc, BurnBndLat, BurnBndLon, Ig_Date

    # Standardize column names (handle different versions)
    col_map = {}
    for col in perimeters_gdf.columns:
        col_lower = col.lower()
        if 'event' in col_lower and 'id' in col_lower:
            col_map[col] = 'event_id'
        elif 'incid' in col_lower and 'name' in col_lower:
            col_map[col] = 'fire_name'
        elif 'incid' in col_lower and 'type' in col_lower:
            col_map[col] = 'fire_type'
        elif 'burnbnd' in col_lower and 'ac' in col_lower:
            col_map[col] = 'burned_acres'
        elif 'burnbnd' in col_lower and 'lat' in col_lower:
            col_map[col] = 'centroid_lat'
        elif 'burnbnd' in col_lower and 'lon' in col_lower:
            col_map[col] = 'centroid_lon'
        elif 'ig_date' in col_lower or ('ignition' in col_lower and 'date' in col_lower):
            col_map[col] = 'ignition_date'
        elif col_lower == 'ig_year':
            col_map[col] = 'year'

    perimeters_gdf = perimeters_gdf.rename(columns=col_map)

    print(f"  Mapped columns: {col_map}")
    print(f"  Available columns: {list(perimeters_gdf.columns)}")

    # Parse ignition date if present
    if 'ignition_date' in perimeters_gdf.columns:
        # Try to parse dates - MTBS uses various formats
        perimeters_gdf['ignition_date'] = pd.to_datetime(
            perimeters_gdf['ignition_date'], errors='coerce', format='mixed'
        )
        perimeters_gdf['year'] = perimeters_gdf['ignition_date'].dt.year
        print(f"  Parsed ignition dates: {perimeters_gdf['ignition_date'].notna().sum():,}")

    # Extract year from event_id as fallback (format: CA3856811568220100818)
    # Apply this for any rows missing year data
    if 'event_id' in perimeters_gdf.columns and (
        'year' not in perimeters_gdf.columns or perimeters_gdf['year'].isna().any()
    ):
        # Try to extract year from event_id (varies by format)
        def extract_year(event_id):
            if not event_id or len(str(event_id)) < 4:
                return None
            # Try last 8 chars as YYYYMMDD
            try:
                year = int(str(event_id)[-8:-4])
                if 1984 <= year <= 2030:
                    return year
            except:
                pass
            return None

        # Only fill in where year is missing
        extracted_years = perimeters_gdf['event_id'].apply(extract_year)
        if 'year' in perimeters_gdf.columns:
            perimeters_gdf['year'] = perimeters_gdf['year'].fillna(extracted_years)
        else:
            perimeters_gdf['year'] = extracted_years
        print(f"  Years extracted from event_id (fallback): {extracted_years.notna().sum():,}")

    # Calculate centroid if not present
    if 'centroid_lat' not in perimeters_gdf.columns:
        centroids = perimeters_gdf.geometry.centroid
        perimeters_gdf['centroid_lat'] = centroids.y
        perimeters_gdf['centroid_lon'] = centroids.x

    # Simplify perimeter geometry for web display
    print(f"  Simplifying perimeter geometry (tolerance={SIMPLIFY_TOLERANCE} deg)...")
    original_size = perimeters_gdf.geometry.apply(lambda g: len(g.wkt) if g else 0).sum()
    perimeters_gdf['geometry'] = perimeters_gdf.geometry.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
    simplified_size = perimeters_gdf.geometry.apply(lambda g: len(g.wkt) if g else 0).sum()
    print(f"    Size reduction: {original_size/1e6:.1f}MB -> {simplified_size/1e6:.1f}MB ({100-simplified_size/original_size*100:.0f}% smaller)")

    print(f"  Year range: {perimeters_gdf['year'].min()}-{perimeters_gdf['year'].max()}")
    print(f"  Total acres burned: {perimeters_gdf['burned_acres'].sum():,.0f}")

    return perimeters_gdf


def geocode_fires_to_counties(fires_gdf, counties_gdf):
    """
    Assign fires to counties using 2-pass matching:
    1. Centroid-based 'within' spatial join
    2. Nearest county match for border fires (using base territorial waters constant)
    """
    print("\nGeocoding fires to counties...")

    # Ensure same CRS
    if fires_gdf.crs != counties_gdf.crs:
        print(f"  Reprojecting from {fires_gdf.crs} to {counties_gdf.crs}")
        fires_gdf = fires_gdf.to_crs(counties_gdf.crs)

    # === PASS 1: Centroid-based 'within' ===
    print("  Pass 1: Centroid-based county assignment...")

    # Create centroid points
    fires_gdf['centroid_geom'] = fires_gdf.geometry.centroid

    # Create a temporary GeoDataFrame with centroid geometry
    centroids_gdf = fires_gdf.copy()
    centroids_gdf = centroids_gdf.set_geometry('centroid_geom')

    # Spatial join with counties
    fires_with_county = gpd.sjoin(
        centroids_gdf,
        counties_gdf[['loc_id', 'name', 'geometry']].rename(columns={'name': 'county_name'}),
        how='left',
        predicate='within'
    )

    matched = fires_with_county['loc_id'].notna().sum()
    print(f"    Matched: {matched:,} ({matched/len(fires_with_county)*100:.1f}%)")

    # === PASS 2: Nearest county for unmatched border fires ===
    unmatched_mask = fires_with_county['loc_id'].isna()
    unmatched_count = unmatched_mask.sum()

    if unmatched_count > 0:
        print(f"  Pass 2: Nearest county matching for {unmatched_count} border fires...")

        unmatched_df = fires_with_county[unmatched_mask].copy()
        unmatched_df['_orig_idx'] = unmatched_df.index
        unmatched_df = unmatched_df.drop(columns=['loc_id', 'county_name', 'index_right'], errors='ignore')

        # Find nearest county
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # Suppress CRS warning
            nearest = gpd.sjoin_nearest(
                unmatched_df,
                counties_gdf[['loc_id', 'name', 'geometry']].rename(columns={'loc_id': 'nearest_loc_id', 'name': 'nearest_county'}),
                how='left',
                distance_col='dist_to_county'
            )

        # Filter to within threshold using base constant and dedupe
        within_threshold = nearest[nearest['dist_to_county'] <= TERRITORIAL_WATERS_DEG].copy()
        within_threshold = within_threshold.drop_duplicates(subset=['_orig_idx'])
        nearest_count = len(within_threshold)
        print(f"    Matched {nearest_count} fires to nearest county")

        # Build mapping and apply
        for _, row in within_threshold.iterrows():
            fires_with_county.loc[row['_orig_idx'], 'loc_id'] = row['nearest_loc_id']
            fires_with_county.loc[row['_orig_idx'], 'county_name'] = row['nearest_county']

    # Extract state FIPS from loc_id for statistics
    fires_with_county['state_fips'] = fires_with_county['loc_id'].apply(
        lambda x: x.split('-')[2][:2] if pd.notna(x) and '-' in str(x) else None
    )

    # Restore original geometry
    fires_with_county = fires_with_county.set_geometry('geometry')
    fires_with_county = fires_with_county.drop(columns=['centroid_geom'], errors='ignore')

    # Final count
    matched = fires_with_county['loc_id'].notna().sum()
    print(f"  Total matched: {matched:,} ({matched/len(fires_with_county)*100:.1f}%)")

    return fires_with_county


def geometry_to_geojson(geom):
    """Convert shapely geometry to GeoJSON string."""
    if geom is None or geom.is_empty:
        return None
    try:
        from shapely.geometry import mapping
        return json.dumps(mapping(geom))
    except Exception:
        return None


def create_fires_parquet(fires_gdf):
    """Create fires.parquet with individual fire events including perimeter geometry."""
    print("\nCreating fires.parquet with perimeter geometry...")

    # Convert perimeter geometry to GeoJSON strings
    print("  Converting perimeters to GeoJSON...")
    perimeter_geojson = fires_gdf.geometry.apply(geometry_to_geojson)
    valid_perimeters = perimeter_geojson.notna().sum()
    print(f"    Valid perimeters: {valid_perimeters:,} ({valid_perimeters/len(fires_gdf)*100:.1f}%)")

    # Select columns for output
    fires_out = pd.DataFrame({
        'event_id': fires_gdf.get('event_id', fires_gdf.index),
        'fire_name': fires_gdf.get('fire_name'),
        'fire_type': fires_gdf.get('fire_type'),
        'year': fires_gdf.get('year'),
        'ignition_date': fires_gdf.get('ignition_date'),
        'burned_acres': fires_gdf.get('burned_acres'),
        'centroid_lat': fires_gdf.get('centroid_lat'),
        'centroid_lon': fires_gdf.get('centroid_lon'),
        'perimeter': perimeter_geojson,  # GeoJSON string of simplified perimeter
        'loc_id': fires_gdf.get('loc_id'),
        'county_name': fires_gdf.get('county_name'),
        'state_fips': fires_gdf.get('state_fips')
    })

    # Convert coordinates to numeric and round
    if 'centroid_lat' in fires_out.columns:
        fires_out['centroid_lat'] = pd.to_numeric(fires_out['centroid_lat'], errors='coerce').round(4)
        fires_out['centroid_lon'] = pd.to_numeric(fires_out['centroid_lon'], errors='coerce').round(4)

    # Round acres
    if 'burned_acres' in fires_out.columns:
        fires_out['burned_acres'] = fires_out['burned_acres'].round(0)

    # Convert event_id to string
    fires_out['event_id'] = fires_out['event_id'].astype(str)

    # Save using base utility
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "fires.parquet"
    save_parquet(fires_out, output_path, description="fire events with perimeters")

    # Report file size
    file_size_mb = output_path.stat().st_size / 1e6
    print(f"  Output file size: {file_size_mb:.1f}MB")

    return fires_out


def create_county_aggregates(fires_df):
    """Create USA.parquet with county-year aggregates."""
    print("\nCreating county-year aggregates...")

    # Filter to fires with county match and valid year
    df_with_county = fires_df[
        (fires_df['loc_id'].notna()) &
        (fires_df['year'].notna())
    ].copy()

    if len(df_with_county) == 0:
        print("  No fires matched to counties!")
        return pd.DataFrame()

    # Group by county-year
    grouped = df_with_county.groupby(['loc_id', 'year'])

    aggregates = grouped.agg({
        'event_id': 'count',  # number of fires
        'burned_acres': ['sum', 'max', 'mean']
    }).reset_index()

    # Flatten column names
    aggregates.columns = ['loc_id', 'year', 'fire_count', 'total_burned_acres',
                          'max_fire_acres', 'avg_fire_acres']

    # Round values
    aggregates['total_burned_acres'] = aggregates['total_burned_acres'].round(0)
    aggregates['max_fire_acres'] = aggregates['max_fire_acres'].round(0)
    aggregates['avg_fire_acres'] = aggregates['avg_fire_acres'].round(0)

    # Convert year to int
    aggregates['year'] = aggregates['year'].astype(int)

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


def generate_metadata(fires_df, county_df):
    """Generate metadata.json for the dataset."""
    print("\nGenerating metadata.json...")

    min_year = int(fires_df['year'].min()) if fires_df['year'].notna().any() else 1984
    max_year = int(fires_df['year'].max()) if fires_df['year'].notna().any() else 2023

    metrics = {
        "fire_count": {
            "name": "Wildfire Count",
            "description": "Number of large wildfires (>1000 acres West, >500 acres East) in county during year",
            "unit": "count",
            "aggregation": "sum",
            "file": "USA.parquet"
        },
        "total_burned_acres": {
            "name": "Total Burned Acres",
            "description": "Total acres burned by large wildfires in county during year",
            "unit": "acres",
            "aggregation": "sum",
            "file": "USA.parquet"
        },
        "max_fire_acres": {
            "name": "Largest Fire",
            "description": "Size of largest wildfire in county during year",
            "unit": "acres",
            "aggregation": "max",
            "file": "USA.parquet"
        },
        "burned_acres": {
            "name": "Burned Acres",
            "description": "Total acres burned in fire perimeter",
            "unit": "acres",
            "file": "fires.parquet"
        }
    }

    metadata = {
        "source_id": "mtbs_wildfires",
        "source_name": "MTBS - Monitoring Trends in Burn Severity",
        "description": f"Large wildfire perimeters and burn severity data ({min_year}-{max_year})",

        "source": {
            "name": "USGS/USFS MTBS Project",
            "url": "https://www.mtbs.gov/",
            "license": "Public Domain (US Government)"
        },

        "geographic_level": "county",
        "geographic_coverage": {
            "type": "country",
            "countries": 1,
            "country_codes": ["USA"]
        },
        "coverage_description": "Continental USA (fires >1000 acres West, >500 acres East)",

        "temporal_coverage": {
            "start": min_year,
            "end": max_year,
            "frequency": "event-based"
        },

        "files": {
            "fires": {
                "filename": "fires.parquet",
                "description": "Individual large fire events with perimeter geometry, location, and burned acres",
                "record_type": "event",
                "record_count": len(fires_df),
                "has_geometry": True,
                "geometry_column": "perimeter",
                "geometry_type": "Polygon/MultiPolygon"
            },
            "county_aggregates": {
                "filename": "USA.parquet",
                "description": "County-year wildfire statistics",
                "record_type": "county-year",
                "record_count": len(county_df) if county_df is not None and not county_df.empty else 0
            }
        },

        "metrics": metrics,

        "llm_summary": f"MTBS wildfire data for USA, {min_year}-{max_year}. "
                      f"{len(fires_df):,} large fires. "
                      f"Covers fires >1000 acres (West) or >500 acres (East).",

        "processing": {
            "converter": "data_converters/convert_mtbs.py",
            "last_run": pd.Timestamp.now().strftime("%Y-%m-%d"),
            "geocoding_method": "2-pass: (1) centroid within polygon, (2) nearest county <22km for border fires",
            "size_threshold": ">1000 acres (West), >500 acres (East)"
        }
    }

    # Write metadata.json
    metadata_path = OUTPUT_DIR / "metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    print(f"  Saved: {metadata_path}")


def print_statistics(fires_df, county_df):
    """Print summary statistics."""
    print("\n" + "="*80)
    print("STATISTICS")
    print("="*80)

    print(f"\nTotal fires: {len(fires_df):,}")
    if fires_df['year'].notna().any():
        print(f"Year range: {int(fires_df['year'].min())}-{int(fires_df['year'].max())}")

    if 'burned_acres' in fires_df.columns:
        total_acres = fires_df['burned_acres'].sum()
        print(f"Total acres burned: {total_acres:,.0f}")
        print(f"Average fire size: {fires_df['burned_acres'].mean():,.0f} acres")
        print(f"Largest fire: {fires_df['burned_acres'].max():,.0f} acres")

    print("\nFires by Decade:")
    if fires_df['year'].notna().any():
        fires_df['decade'] = (fires_df['year'] // 10 * 10).astype(int)
        for decade, count in fires_df.groupby('decade').size().items():
            acres = fires_df[fires_df['decade'] == decade]['burned_acres'].sum()
            print(f"  {decade}s: {count:,} fires, {acres:,.0f} acres")

    print("\nMost Fire-Prone States (by acres burned):")
    if 'state_fips' in fires_df.columns:
        state_acres = fires_df.groupby('state_fips')['burned_acres'].sum().nlargest(10)
        for fips, acres in state_acres.items():
            state = USA_STATE_FIPS.get(str(fips).zfill(2), fips)
            count = len(fires_df[fires_df['state_fips'] == fips])
            print(f"  {state}: {acres:,.0f} acres ({count:,} fires)")

    print("\nLargest Fires:")
    if 'burned_acres' in fires_df.columns and 'fire_name' in fires_df.columns:
        largest = fires_df.nlargest(10, 'burned_acres')
        for _, row in largest.iterrows():
            name = row['fire_name'] if pd.notna(row['fire_name']) else 'Unknown'
            year = int(row['year']) if pd.notna(row['year']) else '?'
            print(f"  {name} ({year}): {row['burned_acres']:,.0f} acres")


def main():
    """Main conversion logic."""
    print("=" * 60)
    print("MTBS Wildfire Data Converter")
    print("=" * 60)

    # Load county boundaries using base utility
    counties_gdf = load_counties()

    # Load MTBS perimeter data
    perimeters_gdf = load_mtbs_perimeters()

    if perimeters_gdf.empty:
        print("\nERROR: No fire perimeter data loaded")
        return 1

    # Process perimeters
    fires_gdf = process_perimeters(perimeters_gdf)

    # Geocode fires to counties
    fires_with_county = geocode_fires_to_counties(fires_gdf, counties_gdf)

    # Create output files
    fires_out = create_fires_parquet(fires_with_county)

    # Create county aggregates
    county_df = create_county_aggregates(fires_out)
    agg_path = save_county_parquet(county_df)

    # Print statistics
    print_statistics(fires_out, county_df)

    # Generate metadata
    generate_metadata(fires_out, county_df)

    # Finalize (update index)
    print("\n" + "=" * 60)
    print("Finalizing source...")
    print("=" * 60)

    try:
        if agg_path:
            finalize_source(
                parquet_path=str(agg_path),
                source_id=SOURCE_ID,
                events_parquet_path=str(OUTPUT_DIR / "fires.parquet")
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
