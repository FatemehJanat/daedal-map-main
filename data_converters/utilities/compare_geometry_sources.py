"""
Compare geometry from different sources to assess compatibility.

Compares:
1. Australia: ABS LGA boundaries vs GADM admin_2
2. Canada: StatsCan CSD boundaries vs GADM admin_2 (requires separate boundary download)
3. Europe: Eurostat GISCO NUTS vs GADM regions

This helps decide whether to:
- Use GADM as baseline and build crosswalks to source IDs
- Replace GADM geometry with source geometry for better data alignment

Usage:
    python compare_geometry_sources.py --australia
    python compare_geometry_sources.py --canada
    python compare_geometry_sources.py --europe
    python compare_geometry_sources.py --all
"""

import argparse
import json
import sqlite3
from pathlib import Path
from collections import defaultdict

try:
    from shapely.geometry import shape, mapping
    from shapely.ops import unary_union
    from shapely import wkt
    import geopandas as gpd
    HAS_GEO = True
except ImportError:
    HAS_GEO = False
    print("WARNING: shapely/geopandas not installed. Some comparisons limited.")

# Paths - adjust as needed
GADM_PATH = Path("C:/Users/bryan/Desktop/county-map-data/Raw data/gadm_410.gpkg")
GEOMETRY_DIR = Path("C:/Users/bryan/Desktop/county-map-data/geometry")
RAW_DATA_DIR = Path("C:/Users/bryan/Desktop/county-map-data/Raw data")

# Australia paths
ABS_LGA_GPKG = RAW_DATA_DIR / "abs/ERP_2024_LGA/32180_ERP_2024_LGA_GDA2020.gpkg"

# State mappings
AUS_STATE_CODE_TO_NAME = {
    1: "New South Wales",
    2: "Victoria",
    3: "Queensland",
    4: "South Australia",
    5: "Western Australia",
    6: "Tasmania",
    7: "Northern Territory",
    8: "Australian Capital Territory",
    9: "Other Territories"
}


def compare_australia():
    """Compare ABS LGA geometry with GADM Australia admin_2."""
    print("=" * 80)
    print("AUSTRALIA: ABS LGA vs GADM admin_2")
    print("=" * 80)

    # Load ABS LGA data
    if not ABS_LGA_GPKG.exists():
        print(f"ERROR: ABS file not found: {ABS_LGA_GPKG}")
        return

    print(f"\n1. Loading ABS LGA data from {ABS_LGA_GPKG.name}...")

    abs_conn = sqlite3.connect(str(ABS_LGA_GPKG))
    abs_cursor = abs_conn.cursor()

    # Get ABS LGA info
    abs_cursor.execute("""
        SELECT state_code_2021, state_name_2021, lga_code_2024, lga_name_2024
        FROM ERP_LGA_GDA2020
        ORDER BY state_code_2021, lga_name_2024
    """)
    abs_lgas = abs_cursor.fetchall()

    print(f"   ABS LGAs: {len(abs_lgas)} total")

    # Group by state
    abs_by_state = defaultdict(list)
    for state_code, state_name, lga_code, lga_name in abs_lgas:
        abs_by_state[state_name].append((lga_code, lga_name))

    print("\n   ABS LGAs by State:")
    for state, lgas in sorted(abs_by_state.items()):
        print(f"     {state:35} {len(lgas):4} LGAs")

    abs_conn.close()

    # Load GADM Australia
    print(f"\n2. Loading GADM Australia data...")

    gadm_aus_path = GEOMETRY_DIR / "AUS.parquet"
    if not gadm_aus_path.exists():
        print(f"   ERROR: GADM file not found: {gadm_aus_path}")
        print("   Trying raw GADM gpkg...")

        if not GADM_PATH.exists():
            print(f"   ERROR: GADM gpkg not found: {GADM_PATH}")
            return

        # Try to read from raw GADM
        gadm_conn = sqlite3.connect(str(GADM_PATH))
        gadm_cursor = gadm_conn.cursor()

        # Check for Australia in different possible table names
        gadm_cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [t[0] for t in gadm_cursor.fetchall()]

        # Find admin_2 table
        admin2_table = None
        for t in tables:
            if 'adm' in t.lower() and '2' in t:
                admin2_table = t
                break

        if not admin2_table:
            print(f"   No admin_2 table found. Tables: {tables[:10]}...")
            gadm_conn.close()
            return

        gadm_cursor.execute(f"""
            SELECT NAME_1, NAME_2, GID_2
            FROM {admin2_table}
            WHERE GID_0 = 'AUS'
            ORDER BY NAME_1, NAME_2
        """)
        gadm_regions = gadm_cursor.fetchall()
        gadm_conn.close()

    else:
        # Read from processed parquet
        if HAS_GEO:
            import pandas as pd
            gadm_df = pd.read_parquet(gadm_aus_path)
            gadm_admin2 = gadm_df[gadm_df['admin_level'] == 2]
            print(f"   GADM admin_2: {len(gadm_admin2)} regions")

            # Extract state and region names
            gadm_regions = []
            for _, row in gadm_admin2.iterrows():
                loc_id = row['loc_id']
                name = row.get('name', '')
                # Parse parent from loc_id: AUS-NSW-xxx -> NSW
                parts = loc_id.split('-')
                state = parts[1] if len(parts) > 1 else ''
                gadm_regions.append((state, name, loc_id))
        else:
            print("   Cannot read parquet without pandas")
            return

    print(f"   GADM regions: {len(gadm_regions)} total")

    # Group GADM by state
    gadm_by_state = defaultdict(list)
    for state, name, gid in gadm_regions:
        gadm_by_state[state].append((gid, name))

    print("\n   GADM regions by State:")
    for state, regions in sorted(gadm_by_state.items()):
        print(f"     {state:35} {len(regions):4} regions")

    # Compare counts
    print("\n3. Comparison Summary:")
    print("-" * 60)
    print(f"   {'Source':<20} {'Count':>10}")
    print("-" * 60)
    print(f"   {'ABS LGAs':<20} {len(abs_lgas):>10}")
    print(f"   {'GADM admin_2':<20} {len(gadm_regions):>10}")
    print(f"   {'Difference':<20} {len(abs_lgas) - len(gadm_regions):>10}")

    # Try name matching
    print("\n4. Name Matching Analysis:")

    abs_names = {lga_name.lower().strip() for _, _, _, lga_name in abs_lgas}
    gadm_names = {name.lower().strip() for _, name, _ in gadm_regions}

    matched = abs_names & gadm_names
    abs_only = abs_names - gadm_names
    gadm_only = gadm_names - abs_names

    print(f"   Exact name matches: {len(matched)}")
    print(f"   ABS-only names: {len(abs_only)}")
    print(f"   GADM-only names: {len(gadm_only)}")

    if abs_only:
        print(f"\n   Sample ABS-only (first 10):")
        for name in sorted(abs_only)[:10]:
            print(f"     - {name}")

    if gadm_only:
        print(f"\n   Sample GADM-only (first 10):")
        for name in sorted(gadm_only)[:10]:
            print(f"     - {name}")

    # Geometry comparison (if geopandas available)
    if HAS_GEO:
        print("\n5. Geometry Comparison (sample):")
        compare_australia_geometry()


def compare_australia_geometry():
    """Compare actual geometry boundaries for Australia."""
    import pandas as pd

    # Load ABS with geometry
    abs_gdf = gpd.read_file(str(ABS_LGA_GPKG))
    print(f"   ABS geometry CRS: {abs_gdf.crs}")
    print(f"   ABS total area: {abs_gdf.geometry.area.sum():,.0f} sq units")

    # Load GADM
    gadm_path = GEOMETRY_DIR / "AUS.parquet"
    if gadm_path.exists():
        gadm_df = pd.read_parquet(gadm_path)
        gadm_admin2 = gadm_df[gadm_df['admin_level'] == 2].copy()

        # Parse geometry from GeoJSON string
        if 'geometry' in gadm_admin2.columns:
            sample_geom = gadm_admin2.iloc[0]['geometry']
            if isinstance(sample_geom, str):
                print(f"   GADM geometry format: GeoJSON string")
                # Would need to convert to compare
            else:
                print(f"   GADM geometry format: {type(sample_geom)}")

    print("\n   For detailed geometry comparison, both sources need")
    print("   to be in the same CRS and format.")


def compare_canada():
    """Compare StatsCan CSD boundaries with GADM Canada admin_2."""
    print("=" * 80)
    print("CANADA: Statistics Canada CSD vs GADM admin_2")
    print("=" * 80)

    # StatsCan census data doesn't include geometry
    # Need separate boundary file download
    print("\nNOTE: StatsCan Census Profile data does not include geometry.")
    print("Need to download boundary files separately from:")
    print("  https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/index2021-eng.cfm")
    print("\nAlternatively, compare using GADM geometry with name matching.")

    # Check if we have census data to at least list CSDs
    census_path = RAW_DATA_DIR / "statcan/census_2021"
    if census_path.exists():
        print(f"\nCensus data found at: {census_path}")

        # Count CSDs from geo index files
        total_csds = 0
        for region in ['Atlantic', 'BritishColumbia', 'Ontario', 'Prairies', 'Quebec', 'Territories']:
            geo_file = census_path / f"98-401-X2021006_Geo_starting_row_{region}.CSV"
            if geo_file.exists():
                import csv
                with open(geo_file, 'r', encoding='latin-1') as f:
                    reader = csv.DictReader(f)
                    csds = sum(1 for row in reader if len(row['Geo Code']) == 16)
                    total_csds += csds
                    print(f"  {region}: {csds} CSDs")

        print(f"\nTotal CSDs in census data: {total_csds}")


def compare_europe():
    """Compare Eurostat NUTS boundaries with GADM European regions."""
    print("=" * 80)
    print("EUROPE: Eurostat NUTS vs GADM regions")
    print("=" * 80)

    # Check Eurostat data
    eurostat_path = RAW_DATA_DIR / "eurostat"
    if not eurostat_path.exists():
        print(f"ERROR: Eurostat data not found at {eurostat_path}")
        return

    # Read population TSV to get NUTS codes
    pop_file = eurostat_path / "demo_r_gind3/demo_r_gind3.tsv"
    if pop_file.exists():
        print(f"\nReading Eurostat NUTS codes from {pop_file.name}...")

        # Parse TSV
        with open(pop_file, 'r', encoding='utf-8') as f:
            header = f.readline().strip()

            # Collect unique geo codes
            geo_codes = set()
            nuts3_codes = set()

            for line in f:
                parts = line.split('\t')
                if parts:
                    # First field format: freq,indic_de,geo\time
                    first = parts[0]
                    geo = first.split(',')[-1] if ',' in first else first
                    geo_codes.add(geo)

                    # NUTS 3 codes are typically 5 characters (2 country + 3 region)
                    if len(geo) == 5 and geo[:2].isalpha():
                        nuts3_codes.add(geo)

        print(f"   Total unique geo codes: {len(geo_codes)}")
        print(f"   NUTS 3 codes (5 char): {len(nuts3_codes)}")

        # Group by country
        by_country = defaultdict(list)
        for code in nuts3_codes:
            country = code[:2]
            by_country[country].append(code)

        print(f"\n   NUTS 3 regions by country:")
        for country in sorted(by_country.keys()):
            print(f"     {country}: {len(by_country[country])} regions")

    print("\nNOTE: For geometry comparison, need to download GISCO boundaries:")
    print("  https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/territorial-units-statistics")


def main():
    parser = argparse.ArgumentParser(description="Compare geometry sources")
    parser.add_argument('--australia', action='store_true', help='Compare Australia ABS vs GADM')
    parser.add_argument('--canada', action='store_true', help='Compare Canada StatsCan vs GADM')
    parser.add_argument('--europe', action='store_true', help='Compare Europe Eurostat vs GADM')
    parser.add_argument('--all', action='store_true', help='Run all comparisons')

    args = parser.parse_args()

    if args.all or (not args.australia and not args.canada and not args.europe):
        compare_australia()
        print("\n")
        compare_canada()
        print("\n")
        compare_europe()
    else:
        if args.australia:
            compare_australia()
        if args.canada:
            compare_canada()
        if args.europe:
            compare_europe()


if __name__ == "__main__":
    main()
