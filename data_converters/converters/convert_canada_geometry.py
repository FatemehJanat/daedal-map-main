"""
Convert Statistics Canada Census boundary files to parquet format.

Input: GDB files from Statistics Canada 2021 Census
  - lpr_000a21f_e.gdb - Provinces/Territories (13)
  - lcd_000a21f_e.gdb - Census Divisions (293)
  - lcsd000a21f_e.gdb - Census Subdivisions (5,161)

Output:
  - countries/CAN/geometry.parquet - Combined admin levels 1, 2, 3 geometry

Usage:
    python convert_canada_geometry.py

Geometry strategy:
  - Admin level 1: Provinces/Territories (13 regions)
  - Admin level 2: Census Divisions (293 regions, similar to US counties)
  - Admin level 3: Census Subdivisions (5,161 municipalities)
  - loc_id format: CAN-{prov_abbr}, CAN-{prov_abbr}-{cduid}, CAN-{prov_abbr}-{csduid}
"""
import pandas as pd
import geopandas as gpd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
import sys
import json
from shapely.geometry import mapping

# Add build path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Configuration
INPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data")
PROVINCES_GDB = INPUT_DIR / "lpr_000a21f_e.gdb"
CENSUS_DIV_GDB = INPUT_DIR / "lcd_000a21f_e.gdb"
CENSUS_SUBDIV_GDB = INPUT_DIR / "lcsd000a21f_e.gdb"
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/CAN")

# Province/Territory codes to standard abbreviations
# Using 2-letter codes that match common usage
CAN_PROVINCE_ABBR = {
    "10": "NL",   # Newfoundland and Labrador
    "11": "PE",   # Prince Edward Island
    "12": "NS",   # Nova Scotia
    "13": "NB",   # New Brunswick
    "24": "QC",   # Quebec
    "35": "ON",   # Ontario
    "46": "MB",   # Manitoba
    "47": "SK",   # Saskatchewan
    "48": "AB",   # Alberta
    "59": "BC",   # British Columbia
    "60": "YT",   # Yukon
    "61": "NT",   # Northwest Territories
    "62": "NU",   # Nunavut
}

# Reverse mapping for lookups
CAN_ABBR_TO_PRUID = {v: k for k, v in CAN_PROVINCE_ABBR.items()}


def load_provinces():
    """Load provinces/territories from GDB."""
    print("Loading provinces/territories...")
    gdf = gpd.read_file(PROVINCES_GDB)
    print(f"  Loaded {len(gdf)} provinces/territories")
    print(f"  CRS: {gdf.crs}")
    return gdf


def load_census_divisions():
    """Load census divisions from GDB."""
    print("Loading census divisions...")
    gdf = gpd.read_file(CENSUS_DIV_GDB)
    print(f"  Loaded {len(gdf)} census divisions")
    print(f"  CRS: {gdf.crs}")
    return gdf


def load_census_subdivisions():
    """Load census subdivisions from GDB."""
    print("Loading census subdivisions...")
    gdf = gpd.read_file(CENSUS_SUBDIV_GDB)
    print(f"  Loaded {len(gdf)} census subdivisions")
    print(f"  CRS: {gdf.crs}")
    return gdf


def process_provinces(gdf, simplify_tolerance=0.01):
    """Process provinces into standard geometry format.

    Args:
        gdf: GeoDataFrame with province geometry
        simplify_tolerance: Tolerance for simplification (0.01 = ~1km for provinces)
    """
    print("\nProcessing provinces...")

    # Reproject to WGS84
    if gdf.crs and str(gdf.crs) != "EPSG:4326":
        print(f"  Reprojecting from {gdf.crs} to EPSG:4326...")
        gdf = gdf.to_crs("EPSG:4326")

    # Simplify geometry
    print(f"  Simplifying geometry (tolerance={simplify_tolerance})...")
    gdf['geometry'] = gdf['geometry'].simplify(simplify_tolerance, preserve_topology=True)

    # Build output
    records = []
    for _, row in gdf.iterrows():
        pruid = str(row['PRUID'])
        abbr = CAN_PROVINCE_ABBR.get(pruid, pruid)

        records.append({
            'loc_id': f"CAN-{abbr}",
            'name': row['PRENAME'],
            'admin_level': 1,
            'parent_id': 'CAN',
            'pruid': pruid,
            'geometry': json.dumps(mapping(row['geometry'])) if row['geometry'] else None
        })

    df = pd.DataFrame(records)
    print(f"  Output: {len(df)} provinces")
    return df


def process_census_divisions(gdf, simplify_tolerance=0.001):
    """Process census divisions into standard geometry format.

    Args:
        gdf: GeoDataFrame with census division geometry
        simplify_tolerance: Tolerance for simplification (0.001 = ~100m for divisions)
    """
    print("\nProcessing census divisions...")

    # Reproject to WGS84
    if gdf.crs and str(gdf.crs) != "EPSG:4326":
        print(f"  Reprojecting from {gdf.crs} to EPSG:4326...")
        gdf = gdf.to_crs("EPSG:4326")

    # Simplify geometry
    print(f"  Simplifying geometry (tolerance={simplify_tolerance})...")
    gdf['geometry'] = gdf['geometry'].simplify(simplify_tolerance, preserve_topology=True)

    # Build output
    records = []
    for _, row in gdf.iterrows():
        pruid = str(row['PRUID'])
        cduid = str(row['CDUID'])
        abbr = CAN_PROVINCE_ABBR.get(pruid, pruid)

        records.append({
            'loc_id': f"CAN-{abbr}-{cduid}",
            'name': row['CDNAME'],
            'admin_level': 2,
            'parent_id': f"CAN-{abbr}",
            'pruid': pruid,
            'cduid': cduid,
            'geometry': json.dumps(mapping(row['geometry'])) if row['geometry'] else None
        })

    df = pd.DataFrame(records)
    print(f"  Output: {len(df)} census divisions")
    return df


def process_census_subdivisions(gdf, simplify_tolerance=0.0005):
    """Process census subdivisions into standard geometry format.

    Args:
        gdf: GeoDataFrame with census subdivision geometry
        simplify_tolerance: Tolerance for simplification (0.0005 = ~50m for subdivisions)
    """
    print("\nProcessing census subdivisions...")

    # Reproject to WGS84
    if gdf.crs and str(gdf.crs) != "EPSG:4326":
        print(f"  Reprojecting from {gdf.crs} to EPSG:4326...")
        gdf = gdf.to_crs("EPSG:4326")

    # Simplify geometry
    print(f"  Simplifying geometry (tolerance={simplify_tolerance})...")
    gdf['geometry'] = gdf['geometry'].simplify(simplify_tolerance, preserve_topology=True)

    # Build output
    records = []
    for _, row in gdf.iterrows():
        pruid = str(row['PRUID'])
        csduid = str(row['CSDUID'])
        # CDUID is first 4 digits of CSDUID
        cduid = csduid[:4]
        abbr = CAN_PROVINCE_ABBR.get(pruid, pruid)

        records.append({
            'loc_id': f"CAN-{abbr}-{csduid}",
            'name': row['CSDNAME'],
            'admin_level': 3,
            'parent_id': f"CAN-{abbr}-{cduid}",
            'pruid': pruid,
            'cduid': cduid,
            'csduid': csduid,
            'csdtype': row.get('CSDTYPE', ''),
            'geometry': json.dumps(mapping(row['geometry'])) if row['geometry'] else None
        })

    df = pd.DataFrame(records)
    print(f"  Output: {len(df)} census subdivisions")
    return df


def save_geometry(df, output_path):
    """Save geometry dataframe to parquet."""
    print(f"\nSaving geometry...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"  Saved: {output_path}")
    print(f"  Size: {size_mb:.2f} MB, {len(df):,} rows")
    return size_mb


def create_index_json(prov_df, cd_df, csd_df, output_path):
    """Create index.json for Canada folder."""
    import json

    index = {
        "country": "CAN",
        "country_name": "Canada",
        "admin_levels": {
            "1": len(prov_df),
            "2": len(cd_df),
            "3": len(csd_df)
        },
        "admin_level_names": {
            "1": "Province/Territory",
            "2": "Census Division",
            "3": "Census Subdivision"
        },
        "geometry": {
            "file": "geometry.parquet",
            "source": "Statistics Canada - 2021 Census Boundary Files",
            "source_url": "https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/index-eng.cfm",
            "total_features": len(prov_df) + len(cd_df) + len(csd_df),
            "note": "Digital Boundary Files (DBF) for provinces/territories, census divisions, and census subdivisions."
        },
        "datasets": {},
        "categories": {}
    }

    print(f"\nSaving index.json...")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, indent=2)
    print(f"  Saved: {output_path}")


def main():
    """Main conversion workflow."""
    print("=" * 60)
    print("Canada Census Geometry Converter")
    print("=" * 60)

    # Load data
    prov_gdf = load_provinces()
    cd_gdf = load_census_divisions()
    csd_gdf = load_census_subdivisions()

    # Process geometry
    prov_df = process_provinces(prov_gdf)
    cd_df = process_census_divisions(cd_gdf)
    csd_df = process_census_subdivisions(csd_gdf)

    # Combine into single dataframe
    print("\nCombining geometry...")
    combined_df = pd.concat([prov_df, cd_df, csd_df], ignore_index=True)
    print(f"  Total: {len(combined_df)} features")

    # Reorder columns
    col_order = ['loc_id', 'name', 'admin_level', 'parent_id', 'pruid', 'cduid', 'csduid', 'csdtype', 'geometry']
    combined_df = combined_df[[c for c in col_order if c in combined_df.columns]]

    # Save outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    geom_path = OUTPUT_DIR / "geometry.parquet"
    save_geometry(combined_df, geom_path)

    # Create index.json
    index_path = OUTPUT_DIR / "index.json"
    create_index_json(prov_df, cd_df, csd_df, index_path)

    # Print summary
    print("\n" + "=" * 60)
    print("Conversion Summary")
    print("=" * 60)
    print(f"Provinces/Territories: {len(prov_df)}")
    print(f"Census Divisions: {len(cd_df)}")
    print(f"Census Subdivisions: {len(csd_df)}")
    print(f"Total Features: {len(combined_df)}")

    print("\nProvinces:")
    print(prov_df[['loc_id', 'name']].to_string())

    print("\nSample Census Divisions (first 10):")
    print(cd_df[['loc_id', 'name', 'parent_id']].head(10).to_string())

    print("\nSample Census Subdivisions (first 10):")
    print(csd_df[['loc_id', 'name', 'parent_id']].head(10).to_string())

    print("\n" + "=" * 60)
    print("Outputs:")
    print(f"  Geometry: {geom_path}")
    print(f"  Index: {index_path}")

    return combined_df


if __name__ == "__main__":
    main()
