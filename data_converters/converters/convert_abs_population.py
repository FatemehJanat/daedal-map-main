"""
Convert Australian Bureau of Statistics Regional Population data to parquet format.

Input: GeoPackage from ABS Regional Population release
Output:
  - abs_population/AUS.parquet - Population time series (2001-2024) with demographics
  - geometry.parquet - LGA boundaries from ABS (in country folder, overrides GADM fallback)

Usage:
    python convert_abs_population.py

Dataset contains 547 Local Government Areas with:
- 24 years of population estimates (ERP 2001-2024)
- Birth/death/migration components
- Area and density metrics
- Official ABS geometry (more current than GADM)

Geometry strategy:
  - Local geometry in countries/AUS/geometry.parquet (preferred, from ABS)
  - GADM fallback in geometry/AUS.parquet (if country folder doesn't exist)
"""
import pandas as pd
import geopandas as gpd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
import json
import sys

# Add build path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from build.catalog.finalize_source import finalize_source

# Configuration
INPUT_FILE = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/imported/abs/ERP_2024_LGA/32180_ERP_2024_LGA_GDA2020.gpkg")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/AUS/abs_population")
COUNTRY_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/AUS")

# State code to abbreviation mapping (ABS state_code_2021)
AUS_STATE_TO_ABBR = {
    1: "NSW",  # New South Wales
    2: "VIC",  # Victoria
    3: "QLD",  # Queensland
    4: "SA",   # South Australia
    5: "WA",   # Western Australia
    6: "TAS",  # Tasmania
    7: "NT",   # Northern Territory
    8: "ACT",  # Australian Capital Territory
    9: "OT"    # Other Territories
}

# State names for admin_1 geometry
AUS_STATE_NAMES = {
    "AUS-NSW": "New South Wales",
    "AUS-VIC": "Victoria",
    "AUS-QLD": "Queensland",
    "AUS-SA": "South Australia",
    "AUS-WA": "Western Australia",
    "AUS-TAS": "Tasmania",
    "AUS-NT": "Northern Territory",
    "AUS-ACT": "Australian Capital Territory",
    "AUS-OT": "Other Territories",
}


def load_geopackage():
    """Load GeoPackage with population data and geometry."""
    print("Loading ABS GeoPackage...")
    gdf = gpd.read_file(INPUT_FILE)
    print(f"  Loaded {len(gdf)} LGAs with {len(gdf.columns)} columns")
    print(f"  CRS: {gdf.crs}")
    return gdf


def create_loc_id(row):
    """Create loc_id in format AUS-{state_abbr}-{lga_code}."""
    state_abbr = AUS_STATE_TO_ABBR.get(row['state_code_2021'], 'XX')
    return f"AUS-{state_abbr}-{row['lga_code_2024']}"


def process_data(gdf):
    """Process GeoDataFrame into LONG FORMAT output (one row per location-year).

    Long format is required for consistent time slider functionality.
    See data_import.md for format specification.

    Includes:
    - total_pop: ERP (Estimated Resident Population) for all years 2001-2024
    - Demographic components for 2022-2024 only (fiscal years 2021_22, 2022_23, 2023_24):
      births, deaths, natural_increase, net_internal_migration, net_overseas_migration,
      internal_arrivals, internal_departures, overseas_arrivals, overseas_departures
    """
    print("\nProcessing data to long format...")

    # Create loc_id
    gdf['loc_id'] = gdf.apply(create_loc_id, axis=1)

    # Fiscal year suffix to calendar year mapping (fiscal year ends June, use ending year)
    FISCAL_TO_YEAR = {
        '2021_22': 2022,
        '2022_23': 2023,
        '2023_24': 2024,
    }

    # Demographic column prefixes (only available for 2021_22, 2022_23, 2023_24)
    DEMOGRAPHIC_COLS = [
        'births',
        'deaths',
        'natural_increase',
        'net_internal_migration',
        'net_overseas_migration',
        'internal_arrivals',
        'internal_departures',
        'overseas_arrivals',
        'overseas_departures',
    ]

    # Build long format records (one row per LGA-year)
    records = []

    for _, row in gdf.iterrows():
        loc_id = row['loc_id']

        # Create one record per year (2001-2024)
        for year in range(2001, 2025):
            erp_col = f'erp_{year}'
            if erp_col not in gdf.columns or pd.isna(row[erp_col]):
                continue

            record = {
                'loc_id': loc_id,
                'year': year,
                'total_pop': int(row[erp_col]),
            }

            # Add demographic columns for years that have them (2022-2024)
            for fiscal_suffix, cal_year in FISCAL_TO_YEAR.items():
                if year == cal_year:
                    for col_prefix in DEMOGRAPHIC_COLS:
                        src_col = f'{col_prefix}_{fiscal_suffix}'
                        if src_col in gdf.columns and pd.notna(row[src_col]):
                            record[col_prefix] = int(row[src_col])

            records.append(record)

    df = pd.DataFrame(records)

    # Sort by loc_id, year for consistent ordering
    df = df.sort_values(['loc_id', 'year']).reset_index(drop=True)

    # Count how many rows have demographic data
    demo_cols = [c for c in DEMOGRAPHIC_COLS if c in df.columns]
    rows_with_demo = df[demo_cols].notna().any(axis=1).sum() if demo_cols else 0

    print(f"  Output: {len(df):,} rows (long format)")
    print(f"  Locations: {df['loc_id'].nunique()}")
    print(f"  Years: {df['year'].min()}-{df['year'].max()}")
    print(f"  Demographic data: {rows_with_demo:,} rows (2022-2024 only)")
    print(f"  Columns: {list(df.columns)}")
    return df


def extract_geometry_gdf(gdf, simplify_tolerance=0.001):
    """Extract geometry as GeoDataFrame for aggregation.

    Args:
        gdf: GeoDataFrame with geometry
        simplify_tolerance: Tolerance for simplification (0.001 = ~100m for counties)

    Returns:
        GeoDataFrame with geometry objects (not GeoJSON strings)

    Includes area_km2 which aggregates cleanly (sum for parent polygons).
    """
    print("\nExtracting geometry...")

    # Create geometry dataframe
    geom_df = gdf[['geometry']].copy()
    geom_df['loc_id'] = gdf.apply(create_loc_id, axis=1)
    geom_df['name'] = gdf['lga_name_2024']
    geom_df['admin_level'] = 2  # LGA = admin level 2
    geom_df['parent_id'] = gdf['state_code_2021'].map(
        lambda x: f"AUS-{AUS_STATE_TO_ABBR.get(x, 'XX')}"
    )
    # Add area from source (static metric, aggregates via sum)
    geom_df['area_km2'] = gdf['area_km2']

    # Reproject to WGS84 (EPSG:4326) for consistency with GADM
    if gdf.crs and str(gdf.crs) != "EPSG:4326":
        print(f"  Reprojecting from {gdf.crs} to EPSG:4326...")
        geom_gdf = gpd.GeoDataFrame(geom_df, geometry='geometry', crs=gdf.crs)
        geom_gdf = geom_gdf.to_crs("EPSG:4326")
    else:
        geom_gdf = gpd.GeoDataFrame(geom_df, geometry='geometry', crs=gdf.crs)

    # Simplify geometry for web display (0.001 = ~100m precision for county level)
    print(f"  Simplifying geometry (tolerance={simplify_tolerance})...")
    geom_gdf['geometry'] = geom_gdf['geometry'].simplify(simplify_tolerance, preserve_topology=True)

    print(f"  Geometry: {len(geom_gdf)} polygons (admin_level 2)")
    return geom_gdf


def save_parquet(df, output_path, description):
    """Save dataframe to parquet with appropriate schema."""
    print(f"\nSaving {description}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"  Saved: {output_path}")
    print(f"  Size: {size_mb:.2f} MB, {len(df):,} rows")
    return size_mb


def aggregate_to_parent_levels(df, geometry_df):
    """
    Aggregate admin_2 data up to admin_1 and admin_0 levels.

    Args:
        df: DataFrame with loc_id, year, and metric columns (admin_2)
        geometry_df: DataFrame with loc_id, parent_id, admin_level

    Returns:
        Combined DataFrame with all admin levels
    """
    print("\nAggregating data to parent levels...")

    all_levels = [df.copy()]  # Start with original admin_2 data

    # Build parent lookup from geometry
    parent_lookup = geometry_df.set_index('loc_id')['parent_id'].to_dict()

    # Identify numeric columns to aggregate (exclude loc_id, year)
    metric_cols = [c for c in df.columns if c not in ['loc_id', 'year']]

    # Aggregate to admin_1 (states)
    df_with_parent = df.copy()
    df_with_parent['parent_id'] = df_with_parent['loc_id'].map(parent_lookup)

    # Remove rows where parent_id is None (shouldn't happen, but safety check)
    df_with_parent = df_with_parent.dropna(subset=['parent_id'])

    # Use min_count=1 so sum of all NaN = NaN (not 0.0)
    admin1 = df_with_parent.groupby(['parent_id', 'year'])[metric_cols].sum(min_count=1).reset_index()
    admin1 = admin1.rename(columns={'parent_id': 'loc_id'})
    print(f"  Admin 1 (states): {admin1['loc_id'].nunique()} locations, {len(admin1)} rows")
    all_levels.append(admin1)

    # Aggregate to admin_0 (country)
    admin1_copy = admin1.copy()
    admin1_copy['country'] = admin1_copy['loc_id'].str.split('-').str[0]
    admin0 = admin1_copy.groupby(['country', 'year'])[metric_cols].sum(min_count=1).reset_index()
    admin0 = admin0.rename(columns={'country': 'loc_id'})
    print(f"  Admin 0 (country): {admin0['loc_id'].nunique()} locations, {len(admin0)} rows")
    all_levels.append(admin0)

    result = pd.concat(all_levels, ignore_index=True)
    print(f"  Total: {result['loc_id'].nunique()} unique locations, {len(result)} rows")
    return result


def create_parent_geometry(geometry_gdf):
    """
    Dissolve admin_2 polygons into admin_1 and admin_0.

    Args:
        geometry_gdf: GeoDataFrame with geometry, loc_id, parent_id, admin_level, area_km2

    Returns:
        Combined GeoDataFrame with all admin levels

    Aggregates area_km2 by summing child areas for parent polygons.
    """
    from shapely.ops import unary_union
    from shapely.geometry import mapping

    print("\nCreating parent-level geometry...")

    # Keep only admin_2 for dissolving (geometry_gdf may already be admin_2 only)
    admin2_gdf = geometry_gdf[geometry_gdf['admin_level'] == 2].copy()

    all_levels = [admin2_gdf.copy()]

    # Dissolve to admin_1 (group by parent_id), aggregate area_km2
    admin1_groups = admin2_gdf.groupby('parent_id')
    admin1_records = []
    for parent_id, group in admin1_groups:
        dissolved = unary_union(group.geometry.tolist())
        area_sum = group['area_km2'].sum() if 'area_km2' in group.columns else None
        admin1_records.append({
            'loc_id': parent_id,
            'name': AUS_STATE_NAMES.get(parent_id, parent_id),
            'admin_level': 1,
            'parent_id': 'AUS',
            'geometry': dissolved,
            'area_km2': area_sum,
        })
    admin1_gdf = gpd.GeoDataFrame(admin1_records, crs=admin2_gdf.crs)
    print(f"  Admin 1 (states): {len(admin1_gdf)} polygons")
    all_levels.append(admin1_gdf)

    # Dissolve to admin_0 (whole country), aggregate area_km2
    country_geom = unary_union(admin2_gdf.geometry.tolist())
    country_area = admin2_gdf['area_km2'].sum() if 'area_km2' in admin2_gdf.columns else None
    admin0_gdf = gpd.GeoDataFrame([{
        'loc_id': 'AUS',
        'name': 'Australia',
        'admin_level': 0,
        'parent_id': None,
        'geometry': country_geom,
        'area_km2': country_area,
    }], crs=admin2_gdf.crs)
    print(f"  Admin 0 (country): 1 polygon (area: {country_area:,.0f} km2)")
    all_levels.append(admin0_gdf)

    # Combine all levels
    combined = pd.concat(all_levels, ignore_index=True)

    # Convert geometry to GeoJSON strings for parquet storage
    combined['geometry'] = combined['geometry'].apply(
        lambda g: json.dumps(mapping(g)) if g else None
    )

    # Convert to regular DataFrame (drop shapely geometry column type)
    result = pd.DataFrame(combined)
    print(f"  Total: {len(result)} polygons across all levels")

    return result


def main():
    """Main conversion workflow."""
    print("=" * 60)
    print("ABS Regional Population Converter")
    print("=" * 60)

    # Load data
    gdf = load_geopackage()

    # Process population data (admin_2 only initially)
    df = process_data(gdf)

    # Extract geometry as GeoDataFrame (for aggregation)
    geom_gdf = extract_geometry_gdf(gdf)

    # === Aggregate to parent levels ===
    # This creates admin_1 (states) and admin_0 (country) from admin_2 (LGAs)
    df = aggregate_to_parent_levels(df, geom_gdf)
    geom_df = create_parent_geometry(geom_gdf)

    # Save outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Save main data file
    data_path = OUTPUT_DIR / "AUS.parquet"
    save_parquet(df, data_path, "population data")

    # Save geometry file in country folder (overrides GADM fallback)
    geom_path = COUNTRY_DIR / "geometry.parquet"
    save_parquet(geom_df, geom_path, "ABS geometry")

    # Print summary
    print("\n" + "=" * 60)
    print("Conversion Summary")
    print("=" * 60)
    print(f"Total rows: {len(df):,} (long format)")
    print(f"Locations: {df['loc_id'].nunique()}")

    # Show breakdown by admin level
    df['_level'] = df['loc_id'].str.count('-')
    level_counts = df.groupby('_level')['loc_id'].nunique()
    print(f"\nLocations by admin level:")
    print(f"  Admin 0 (country): {level_counts.get(0, 0)}")
    print(f"  Admin 1 (states): {level_counts.get(1, 0)}")
    print(f"  Admin 2 (LGAs): {level_counts.get(2, 0)}")
    df = df.drop(columns=['_level'])

    print(f"\nYears: {df['year'].min()}-{df['year'].max()} ({df['year'].nunique()} years)")
    print(f"Columns: {list(df.columns)}")
    print(f"\nOutputs:")
    print(f"  Data: {data_path}")
    print(f"  Geometry: {geom_path}")

    # Sample output - show aggregated state data
    print("\nSample data (NSW state - first 5 years):")
    sample = df[df['loc_id'] == 'AUS-NSW'].head(5)
    if len(sample) == 0:
        sample = df.head(5)
    print(sample.to_string(index=False))

    # Finalize source (generate metadata, update index)
    print("\n" + "=" * 60)
    print("Finalizing source...")
    print("=" * 60)

    try:
        finalize_source(
            parquet_path=str(data_path),
            source_id="abs_population"
        )
    except ValueError as e:
        print(f"  Note: {e}")
        print("  Add 'abs_population' to source_registry.py to enable auto-finalization")

    return df, geom_df


if __name__ == "__main__":
    main()
