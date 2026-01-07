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
INPUT_FILE = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/abs/ERP_2024_LGA/32180_ERP_2024_LGA_GDA2020.gpkg")
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
    """
    print("\nProcessing data to long format...")

    # Create loc_id
    gdf['loc_id'] = gdf.apply(create_loc_id, axis=1)

    # Build long format records (one row per LGA-year)
    records = []

    for _, row in gdf.iterrows():
        loc_id = row['loc_id']

        # Create one record per year (2001-2024)
        for year in range(2001, 2025):
            erp_col = f'erp_{year}'
            if erp_col in gdf.columns and pd.notna(row[erp_col]):
                records.append({
                    'loc_id': loc_id,
                    'year': year,
                    'total_pop': int(row[erp_col]) if pd.notna(row[erp_col]) else None,
                })

    df = pd.DataFrame(records)

    # Sort by loc_id, year for consistent ordering
    df = df.sort_values(['loc_id', 'year']).reset_index(drop=True)

    print(f"  Output: {len(df):,} rows (long format)")
    print(f"  Locations: {df['loc_id'].nunique()}")
    print(f"  Years: {df['year'].min()}-{df['year'].max()}")
    return df


def extract_geometry(gdf, simplify_tolerance=0.001):
    """Extract and convert geometry to parquet format for geometry folder.

    Args:
        gdf: GeoDataFrame with geometry
        simplify_tolerance: Tolerance for simplification (0.001 = ~100m for counties)
    """
    print("\nExtracting geometry...")

    # Create geometry dataframe
    geom_df = gdf[['geometry']].copy()
    geom_df['loc_id'] = gdf.apply(create_loc_id, axis=1)
    geom_df['name'] = gdf['lga_name_2024']
    geom_df['admin_level'] = 2  # LGA = admin level 2
    geom_df['parent_loc_id'] = gdf['state_code_2021'].map(
        lambda x: f"AUS-{AUS_STATE_TO_ABBR.get(x, 'XX')}"
    )

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

    # Convert to WKB for parquet storage
    geom_gdf['geometry_wkb'] = geom_gdf['geometry'].apply(lambda g: g.wkb if g else None)

    # Create output dataframe (without shapely geometry)
    output_df = pd.DataFrame({
        'loc_id': geom_gdf['loc_id'],
        'name': geom_gdf['name'],
        'admin_level': geom_gdf['admin_level'],
        'parent_loc_id': geom_gdf['parent_loc_id'],
        'geometry': geom_gdf['geometry_wkb']
    })

    print(f"  Geometry: {len(output_df)} polygons")
    return output_df


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


def main():
    """Main conversion workflow."""
    print("=" * 60)
    print("ABS Regional Population Converter")
    print("=" * 60)

    # Load data
    gdf = load_geopackage()

    # Process population data
    df = process_data(gdf)

    # Extract geometry
    geom_df = extract_geometry(gdf)

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
    print(f"Years: {df['year'].min()}-{df['year'].max()} ({df['year'].nunique()} years)")
    print(f"Columns: {list(df.columns)}")
    print(f"\nOutputs:")
    print(f"  Data: {data_path}")
    print(f"  Geometry: {geom_path}")

    # Sample output - show one location across years
    print("\nSample data (Sydney - first 5 years):")
    sample = df[df['loc_id'].str.contains('17200')].head(5)  # Sydney LGA
    if len(sample) == 0:
        sample = df.head(5)
    print(sample.to_string(index=False))

    # Finalize source (generate metadata, update index)
    # Note: Need to add abs_population to source_registry first
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
