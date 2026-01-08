"""
Convert Census sub-county geometry to parquet format.

Creates tiered geometry files:
- geometry_zcta.parquet      - All ZCTAs national (type="postal")
- geometry_tract/{state}.parquet    - Tracts by state (type="census")
- geometry_blockgroup/{state}.parquet - Block groups by state (type="census")
- geometry_block/{state}.parquet    - Blocks by state (type="census", optional)

Follows loc_id format:
- ZCTA: USA-Z-{zcta}
- Tract: USA-{state}-T{tract}
- Block Group: USA-{state}-T{tract}-{bg}
- Block: USA-{state}-T{tract}-{block}

Usage:
    python convert_census_geometry.py --level zcta
    python convert_census_geometry.py --level tract
    python convert_census_geometry.py --level blockgroup
    python convert_census_geometry.py --level block --states CA NY
    python convert_census_geometry.py --all
"""

import sys
import json
import argparse
from pathlib import Path
from typing import Optional, List
import geopandas as gpd
import pandas as pd
from shapely.geometry import mapping

# Paths
RAW_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/census/geometry")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA")
REFERENCE_DIR = Path("C:/Users/Bryan/Desktop/county-map/mapmover/reference/usa")

# State FIPS to abbreviation mapping
FIPS_TO_ABBREV = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA",
    "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
    "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN",
    "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
    "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS",
    "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
    "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
    "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI",
    "56": "WY", "60": "AS", "66": "GU", "69": "MP", "72": "PR", "78": "VI"
}


def load_zcta_crosswalk():
    """Load ZCTA to county crosswalk for parent_id mapping."""
    crosswalk_path = REFERENCE_DIR / "zcta_crosswalk.parquet"
    if crosswalk_path.exists():
        return pd.read_parquet(crosswalk_path).set_index('zcta')
    return None


def geometry_to_geojson(geom) -> str:
    """Convert shapely geometry to GeoJSON string."""
    if geom is None or geom.is_empty:
        return None
    return json.dumps(mapping(geom))


def create_geometry_row(loc_id: str, parent_id: str, admin_level: int,
                        geo_type: str, name: str, geom, land_area: float,
                        water_area: float) -> dict:
    """Create a geometry row matching the existing schema."""
    centroid = geom.centroid if geom and not geom.is_empty else None
    bounds = geom.bounds if geom and not geom.is_empty else (None, None, None, None)

    return {
        'loc_id': loc_id,
        'parent_id': parent_id,
        'admin_level': admin_level,
        'type': geo_type,
        'name': name,
        'name_local': None,
        'code': '',
        'iso_3166_2': None,
        'centroid_lon': centroid.x if centroid else None,
        'centroid_lat': centroid.y if centroid else None,
        'has_polygon': True,
        'geometry': geometry_to_geojson(geom),
        'timezone': None,
        'iso_a3': 'USA',
        'land_area': land_area,
        'water_area': water_area,
        'bbox_min_lon': bounds[0],
        'bbox_min_lat': bounds[1],
        'bbox_max_lon': bounds[2],
        'bbox_max_lat': bounds[3],
        'children_count': 0,
        'children_by_level': '{}',
        'descendants_count': 0,
        'descendants_by_level': '{}'
    }


def convert_zcta():
    """Convert ZCTA shapefile to parquet."""
    print("\n" + "=" * 60)
    print("Converting ZCTA Geometry")
    print("=" * 60)

    # Find shapefile
    shp_dir = RAW_DIR / "zcta_extracted"
    if not shp_dir.exists():
        # Extract if needed
        import zipfile
        zip_path = RAW_DIR / "tl_2024_us_zcta520.zip"
        print(f"Extracting {zip_path}...")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(shp_dir)

    shp_path = shp_dir / "tl_2024_us_zcta520.shp"
    print(f"Loading {shp_path}...")

    # Load in chunks to manage memory
    gdf = gpd.read_file(shp_path)
    print(f"  Loaded {len(gdf):,} ZCTAs")

    # Load crosswalk for parent_id
    crosswalk = load_zcta_crosswalk()

    # Process each ZCTA
    print("Processing ZCTAs...")
    rows = []
    for idx, row in gdf.iterrows():
        zcta = row['ZCTA5CE20']
        loc_id = f"USA-Z-{zcta}"

        # Get parent county from crosswalk
        parent_id = None
        if crosswalk is not None and zcta in crosswalk.index:
            parent_id = crosswalk.loc[zcta, 'primary_county_loc_id']

        # If no crosswalk match, use state from centroid (fallback)
        if parent_id is None:
            parent_id = "USA"

        name = f"ZCTA {zcta}"

        geometry_row = create_geometry_row(
            loc_id=loc_id,
            parent_id=parent_id,
            admin_level=3,  # Same level as townships/subdivisions
            geo_type='postal',
            name=name,
            geom=row.geometry,
            land_area=float(row['ALAND20']) if pd.notna(row['ALAND20']) else 0,
            water_area=float(row['AWATER20']) if pd.notna(row['AWATER20']) else 0
        )
        rows.append(geometry_row)

        if (idx + 1) % 5000 == 0:
            print(f"    Processed {idx + 1:,} / {len(gdf):,}")

    # Create DataFrame and save
    result_df = pd.DataFrame(rows)

    output_path = OUTPUT_DIR / "geometry_zcta.parquet"
    result_df.to_parquet(output_path, index=False)

    print(f"\nSaved: {output_path}")
    print(f"  Size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"  Rows: {len(result_df):,}")

    return result_df


def convert_tract():
    """Convert Census Tract shapefile to parquet (by state)."""
    print("\n" + "=" * 60)
    print("Converting Census Tract Geometry (by state)")
    print("=" * 60)

    # Extract if needed
    shp_dir = RAW_DIR / "tract_extracted"
    if not shp_dir.exists():
        import zipfile
        zip_path = RAW_DIR / "cb_2024_us_tract_500k.zip"
        print(f"Extracting {zip_path}...")
        shp_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(shp_dir)

    shp_path = list(shp_dir.glob("*.shp"))[0]
    print(f"Loading {shp_path}...")

    gdf = gpd.read_file(shp_path)
    print(f"  Loaded {len(gdf):,} tracts")
    print(f"  Columns: {list(gdf.columns)}")

    # Create output directory
    output_subdir = OUTPUT_DIR / "geometry_tract"
    output_subdir.mkdir(exist_ok=True)

    # Group by state
    gdf['state_fips'] = gdf['STATEFP'].astype(str).str.zfill(2)

    total_saved = 0
    for state_fips, state_gdf in gdf.groupby('state_fips'):
        if state_fips not in FIPS_TO_ABBREV:
            print(f"  Skipping unknown state FIPS: {state_fips}")
            continue

        state_abbrev = FIPS_TO_ABBREV[state_fips]
        print(f"  Processing {state_abbrev} ({len(state_gdf):,} tracts)...")

        rows = []
        for _, row in state_gdf.iterrows():
            # Build tract ID: state FIPS (2) + county FIPS (3) + tract (6)
            tract_geoid = row['GEOID']  # Full GEOID like "01001020100"
            county_fips = tract_geoid[:5]  # State + County
            tract_code = tract_geoid[5:]  # 6-digit tract code

            # loc_id format: USA-{state}-T{tract_geoid}
            loc_id = f"USA-{state_abbrev}-T{tract_geoid}"

            # Parent is the county
            county_fips_int = int(county_fips)
            parent_id = f"USA-{state_abbrev}-{county_fips_int}"

            name = row.get('NAMELSAD', f"Tract {tract_code}")

            geometry_row = create_geometry_row(
                loc_id=loc_id,
                parent_id=parent_id,
                admin_level=4,  # Below county (level 2) and township (level 3)
                geo_type='census',
                name=name,
                geom=row.geometry,
                land_area=float(row['ALAND']) if 'ALAND' in row and pd.notna(row['ALAND']) else 0,
                water_area=float(row['AWATER']) if 'AWATER' in row and pd.notna(row['AWATER']) else 0
            )
            rows.append(geometry_row)

        # Save state file
        state_df = pd.DataFrame(rows)
        output_path = output_subdir / f"USA-{state_abbrev}.parquet"
        state_df.to_parquet(output_path, index=False)
        total_saved += len(state_df)

    print(f"\nTotal tracts saved: {total_saved:,}")
    print(f"Output directory: {output_subdir}")


def convert_blockgroup():
    """Convert Census Block Group shapefile to parquet (by state)."""
    print("\n" + "=" * 60)
    print("Converting Census Block Group Geometry (by state)")
    print("=" * 60)

    # Extract if needed
    shp_dir = RAW_DIR / "bg_extracted"
    if not shp_dir.exists():
        import zipfile
        zip_path = RAW_DIR / "cb_2024_us_bg_500k.zip"
        print(f"Extracting {zip_path}...")
        shp_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(shp_dir)

    shp_path = list(shp_dir.glob("*.shp"))[0]
    print(f"Loading {shp_path}...")

    gdf = gpd.read_file(shp_path)
    print(f"  Loaded {len(gdf):,} block groups")
    print(f"  Columns: {list(gdf.columns)}")

    # Create output directory
    output_subdir = OUTPUT_DIR / "geometry_blockgroup"
    output_subdir.mkdir(exist_ok=True)

    # Group by state
    gdf['state_fips'] = gdf['STATEFP'].astype(str).str.zfill(2)

    total_saved = 0
    for state_fips, state_gdf in gdf.groupby('state_fips'):
        if state_fips not in FIPS_TO_ABBREV:
            print(f"  Skipping unknown state FIPS: {state_fips}")
            continue

        state_abbrev = FIPS_TO_ABBREV[state_fips]
        print(f"  Processing {state_abbrev} ({len(state_gdf):,} block groups)...")

        rows = []
        for _, row in state_gdf.iterrows():
            # GEOID format: state (2) + county (3) + tract (6) + block group (1)
            bg_geoid = row['GEOID']  # e.g., "010010201001"
            tract_geoid = bg_geoid[:11]  # First 11 chars = tract
            bg_code = bg_geoid[11:]  # Last char = block group

            # loc_id: USA-{state}-T{tract}-{bg}
            loc_id = f"USA-{state_abbrev}-T{tract_geoid}-{bg_code}"

            # Parent is the tract
            parent_id = f"USA-{state_abbrev}-T{tract_geoid}"

            name = row.get('NAMELSAD', f"Block Group {bg_code}")

            geometry_row = create_geometry_row(
                loc_id=loc_id,
                parent_id=parent_id,
                admin_level=5,  # Below tract (level 4)
                geo_type='census',
                name=name,
                geom=row.geometry,
                land_area=float(row['ALAND']) if 'ALAND' in row and pd.notna(row['ALAND']) else 0,
                water_area=float(row['AWATER']) if 'AWATER' in row and pd.notna(row['AWATER']) else 0
            )
            rows.append(geometry_row)

        # Save state file
        state_df = pd.DataFrame(rows)
        output_path = output_subdir / f"USA-{state_abbrev}.parquet"
        state_df.to_parquet(output_path, index=False)
        total_saved += len(state_df)

    print(f"\nTotal block groups saved: {total_saved:,}")
    print(f"Output directory: {output_subdir}")


def convert_block(states: Optional[List[str]] = None):
    """Convert Census Block shapefile to parquet (by state)."""
    print("\n" + "=" * 60)
    print("Converting Census Block Geometry (by state)")
    print("=" * 60)

    # Create output directory
    output_subdir = OUTPUT_DIR / "geometry_block"
    output_subdir.mkdir(exist_ok=True)

    # Map state abbreviations to FIPS
    abbrev_to_fips = {v: k for k, v in FIPS_TO_ABBREV.items()}

    if states:
        state_list = [abbrev_to_fips.get(s.upper(), s) for s in states]
    else:
        # Default to states with downloaded files
        state_list = []
        for zip_file in RAW_DIR.glob("tl_2024_*_tabblock20.zip"):
            fips = zip_file.stem.split('_')[2]
            state_list.append(fips)

    if not state_list:
        print("No block files found. Download from:")
        print("https://www2.census.gov/geo/tiger/TIGER2024/TABBLOCK20/")
        return

    print(f"Processing states: {state_list}")

    total_saved = 0
    for state_fips in state_list:
        state_fips = str(state_fips).zfill(2)
        if state_fips not in FIPS_TO_ABBREV:
            print(f"  Skipping unknown state FIPS: {state_fips}")
            continue

        state_abbrev = FIPS_TO_ABBREV[state_fips]

        # Find and extract zip
        zip_path = RAW_DIR / f"tl_2024_{state_fips}_tabblock20.zip"
        if not zip_path.exists():
            print(f"  {state_abbrev}: No file found at {zip_path}")
            continue

        shp_dir = RAW_DIR / f"block_extracted_{state_fips}"
        if not shp_dir.exists():
            import zipfile
            print(f"  Extracting {zip_path}...")
            shp_dir.mkdir(exist_ok=True)
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(shp_dir)

        shp_path = list(shp_dir.glob("*.shp"))[0]
        print(f"  Loading {state_abbrev} blocks from {shp_path.name}...")

        gdf = gpd.read_file(shp_path)
        print(f"    Loaded {len(gdf):,} blocks")

        rows = []
        for idx, row in gdf.iterrows():
            # GEOID20 format: state (2) + county (3) + tract (6) + block (4)
            block_geoid = row['GEOID20']
            tract_geoid = block_geoid[:11]
            block_code = block_geoid[11:]

            # loc_id: USA-{state}-T{tract}-{block}
            loc_id = f"USA-{state_abbrev}-T{tract_geoid}-{block_code}"

            # Parent is the block group (first digit of block = block group)
            bg_code = block_code[0]
            parent_id = f"USA-{state_abbrev}-T{tract_geoid}-{bg_code}"

            name = f"Block {block_code}"

            geometry_row = create_geometry_row(
                loc_id=loc_id,
                parent_id=parent_id,
                admin_level=6,  # Below block group (level 5)
                geo_type='census',
                name=name,
                geom=row.geometry,
                land_area=float(row['ALAND20']) if pd.notna(row['ALAND20']) else 0,
                water_area=float(row['AWATER20']) if pd.notna(row['AWATER20']) else 0
            )
            rows.append(geometry_row)

            if (idx + 1) % 100000 == 0:
                print(f"      Processed {idx + 1:,} / {len(gdf):,}")

        # Save state file
        state_df = pd.DataFrame(rows)
        output_path = output_subdir / f"USA-{state_abbrev}.parquet"
        state_df.to_parquet(output_path, index=False)
        print(f"    Saved: {output_path} ({output_path.stat().st_size / 1024 / 1024:.1f} MB)")
        total_saved += len(state_df)

    print(f"\nTotal blocks saved: {total_saved:,}")
    print(f"Output directory: {output_subdir}")


def main():
    parser = argparse.ArgumentParser(description="Convert Census geometry to parquet")
    parser.add_argument('--level', choices=['zcta', 'tract', 'blockgroup', 'block', 'all'],
                        default='all', help='Geographic level to convert')
    parser.add_argument('--states', nargs='+', help='States to process (for block level)')

    args = parser.parse_args()

    print("=" * 60)
    print("Census Geometry Converter")
    print("=" * 60)

    if args.level == 'zcta' or args.level == 'all':
        convert_zcta()

    if args.level == 'tract' or args.level == 'all':
        convert_tract()

    if args.level == 'blockgroup' or args.level == 'all':
        convert_blockgroup()

    if args.level == 'block':
        convert_block(args.states)
    elif args.level == 'all':
        # Only convert blocks if files exist
        if any(RAW_DIR.glob("tl_2024_*_tabblock20.zip")):
            convert_block()

    print("\n" + "=" * 60)
    print("COMPLETE!")
    print("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
