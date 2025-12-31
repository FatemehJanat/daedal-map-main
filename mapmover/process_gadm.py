"""
Process GADM GeoPackage into per-country parquet files.

GADM stores all admin levels in a single flat table.
Each row represents one location at its deepest admin level.

NOTE: This script does NOT touch global.csv.
      Country-level geometry comes from Natural Earth data via build_global_csv.py.
      GADM only provides sub-country admin levels (states, counties, etc.)

Input: Raw data/gadm_410.gpkg (GADM 4.1) or gadm36.gpkg (GADM 3.6)
Output: geometry/{ISO3}.parquet (all admin levels per country)

Schema (13 columns):
  loc_id, parent_id, admin_level, name, name_local, code, iso_3166_2,
  centroid_lon, centroid_lat, has_polygon, geometry, timezone, iso_a3
"""

import sqlite3
import pandas as pd
import json
from pathlib import Path
from datetime import datetime
from shapely import wkb
from shapely.geometry import mapping
import re

# Paths - GADM 4.1 (use gadm36.gpkg for older version)
GADM_FILE = Path(r"C:\Users\Bryan\Desktop\county-map-data\Raw data\gadm_410.gpkg")
GADM_TABLE = "gadm_410"  # Table name: "gadm" for 3.6, "gadm_410" for 4.1
OUTPUT_PATH = Path(r"C:\Users\Bryan\Desktop\county-map-data\geometry")
CENSUS_FILE = Path(r"C:\Users\Bryan\Desktop\county-map\data_pipeline\data_cleaned\cc-est2024-alldata.csv")

# Countries with partial geometry from other sources (merge, don't overwrite)
# These countries have some admin levels with better geometry (e.g., USA has Census counties)
# GADM will fill in missing levels but preserve existing geometry
MERGE_COUNTRIES = {'USA'}  # USA has Census-derived county geometry at level 2

# Large countries to process last (by record count from GADM 4.1)
# These take longest, so process them at the end
LARGE_COUNTRIES = ['IDN', 'PHL', 'FRA', 'DEU', 'VNM']  # 162k, 127k, 41k, 28k, 27k records

# Ensure output folder exists
OUTPUT_PATH.mkdir(parents=True, exist_ok=True)

# State FIPS to abbreviation mapping (for US loc_id format)
STATE_FIPS_TO_ABBREV = {
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
    '56': 'WY', '60': 'AS', '66': 'GU', '69': 'MP', '72': 'PR',
    '78': 'VI',
}

# Reverse mapping
ABBREV_TO_STATE_FIPS = {v: k for k, v in STATE_FIPS_TO_ABBREV.items()}

# Manual FIPS mapping for GADM names that don't match Census
# Format: (normalized_state, normalized_county) -> FIPS code
# These are mostly Alaska boroughs with old/reorganized names
MANUAL_FIPS_MAPPING = {
    # Alaska reorganizations (GADM uses old 2010-era names)
    ('alaska', 'wadehampton'): 2158,  # Renamed to Kusilvak Census Area
    ('alaska', 'princeofwalesouterketchi'): 2198,  # Truncated name -> Prince of Wales-Hyder
    ('alaska', 'skagwayyakutatangoon'): 2232,  # Split - using Skagway
    ('alaska', 'valdezcordova'): 2261,  # Split into Chugach + Copper River
    ('alaska', 'wrangellpetersburg'): 2275,  # Split - using Wrangell
    # Connecticut abolished counties in 2022 - use planning region equivalents
    ('connecticut', 'fairfield'): 9001,
    ('connecticut', 'hartford'): 9003,
    ('connecticut', 'litchfield'): 9005,
    ('connecticut', 'middlesex'): 9007,
    ('connecticut', 'newhaven'): 9009,
    ('connecticut', 'newlondon'): 9011,
    ('connecticut', 'tolland'): 9013,
    ('connecticut', 'windham'): 9015,
    # Name changes and special cases
    ('newmexico', 'donaana'): 35013,  # Accent stripped: Dona Ana
    ('southdakota', 'shannon'): 46102,  # Renamed to Oglala Lakota County (2015)
}

# Skip these GADM entries (not real counties - water bodies and defunct entities)
SKIP_GADM_ENTRIES = {
    # Great Lakes water bodies
    ('illinois', 'lakemichigan'),
    ('indiana', 'lakemichigan'),
    ('michigan', 'lakemichigan'),
    ('wisconsin', 'lakemichigan'),
    ('michigan', 'lakehuron'),
    ('michigan', 'lakehurron'),  # Typo in GADM
    ('michigan', 'lakestclair'),
    ('michigan', 'lakesuperior'),
    ('minnesota', 'lakesuperior'),
    ('wisconsin', 'lakesuperior'),
    ('ohio', 'lakeerie'),
    ('michigan', 'lakeerie'),
    ('newyork', 'lakeerie'),
    ('newyork', 'lakeontario'),
    # Defunct independent cities merged into counties
    ('virginia', 'cliftonforge'),  # Merged into Alleghany County (2001)
}


def load_us_fips_mapping():
    """
    Load US county name-to-FIPS mapping from Census data.
    Returns dict: {(state_name_lower, county_name_lower): fips_code}
    """
    if not CENSUS_FILE.exists():
        print(f"WARNING: Census file not found: {CENSUS_FILE}")
        return {}

    df = pd.read_csv(CENSUS_FILE, usecols=['county_code', 'county_name', 'state_name'])
    df = df.drop_duplicates(subset=['county_code'])

    mapping = {}
    for _, row in df.iterrows():
        state = normalize_name(row['state_name'])
        county = normalize_name(row['county_name'])
        fips = int(row['county_code'])
        mapping[(state, county)] = fips

    # Add manual mappings
    mapping.update(MANUAL_FIPS_MAPPING)

    print(f"Loaded {len(mapping)} US county FIPS codes from Census data")
    return mapping


def normalize_name(name):
    """Normalize name for matching."""
    if not name:
        return ""
    name = str(name).lower().strip()

    # Remove common suffixes
    for suffix in [' county', ' parish', ' borough', ' census area',
                   ' municipality', ' city and borough', ' city and', ' city']:
        name = name.replace(suffix, '')

    # Normalize saint/st variations
    name = name.replace('saint ', 'st ')
    name = name.replace('sainte ', 'ste ')

    # Normalize spacing and punctuation
    name = re.sub(r'[^a-z0-9]', '', name)  # Remove all non-alphanumeric
    return name


def get_admin_level(row):
    """
    Determine admin level based on which NAME columns are filled.

    Note: GADM fills GID columns even when there's no actual data at that level.
    The NAME columns are more reliable - they're only filled when real data exists.
    We check NAME columns from deepest to shallowest to find actual admin level.
    """
    for level in range(5, -1, -1):
        name = row.get(f'NAME_{level}')
        # Check for actual non-empty name
        if name is not None and str(name).strip() != '':
            return level
    return 0


def parse_gpkg_geometry(gpkg_bytes):
    """
    Parse GeoPackage Binary (GPB) format to Shapely geometry.

    GPKG Binary format:
    - 2 bytes: 'GP' magic number
    - 1 byte: version
    - 1 byte: flags
    - 4 bytes: srs_id
    - envelope (variable size based on flags)
    - WKB geometry
    """
    if gpkg_bytes is None or len(gpkg_bytes) < 8:
        return None

    # Check magic number
    magic = gpkg_bytes[:2]
    if magic != b'GP':
        # Not GPKG format, try standard WKB
        try:
            return wkb.loads(gpkg_bytes)
        except Exception:
            return None

    # Parse flags
    flags = gpkg_bytes[3]

    # Envelope type (bits 1-3 of flags)
    envelope_type = (flags >> 1) & 0x07

    # Calculate envelope size based on type
    envelope_sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    envelope_size = envelope_sizes.get(envelope_type, 0)

    # WKB starts after 8-byte header + envelope
    wkb_start = 8 + envelope_size
    wkb_bytes = gpkg_bytes[wkb_start:]

    try:
        return wkb.loads(wkb_bytes)
    except Exception:
        return None


def get_centroid(geom_bytes):
    """Get centroid from GPKG geometry bytes."""
    try:
        geom = parse_gpkg_geometry(geom_bytes)
        if geom is None or geom.is_empty:
            return None, None
        centroid = geom.centroid
        return round(centroid.x, 6), round(centroid.y, 6)
    except Exception as e:
        return None, None


def get_simplify_tolerance(admin_level):
    """Get simplification tolerance based on admin level (per GEOMETRY.md)."""
    if admin_level == 0:
        return 0.01      # Countries: ~1 km precision
    elif admin_level <= 2:
        return 0.001     # States/Counties: ~100 m precision
    else:
        return 0.0001    # Cities/Districts: ~10 m precision


def geometry_to_geojson(geom_bytes, admin_level=2):
    """Convert GPKG geometry to GeoJSON string with level-appropriate simplification."""
    try:
        geom = parse_gpkg_geometry(geom_bytes)
        if geom is None or geom.is_empty:
            return None
        # Simplify for smaller file size using level-appropriate tolerance
        tolerance = get_simplify_tolerance(admin_level)
        geom = geom.simplify(tolerance, preserve_topology=True)
        return json.dumps(mapping(geom))
    except Exception as e:
        return None


def get_bbox_from_geometry(geometry_str):
    """
    Extract bounding box from GeoJSON geometry string.
    Returns (min_lon, min_lat, max_lon, max_lat) or (None, None, None, None).
    """
    if not geometry_str:
        return None, None, None, None

    try:
        from shapely.geometry import shape
        geom_data = json.loads(geometry_str)
        geom = shape(geom_data)
        bounds = geom.bounds  # (minx, miny, maxx, maxy)
        return round(bounds[0], 6), round(bounds[1], 6), round(bounds[2], 6), round(bounds[3], 6)
    except Exception:
        return None, None, None, None


def is_placeholder_level(df, level):
    """
    Check if a level is a placeholder (all names are empty/null).

    GADM creates placeholder rows at levels 4-5 even when real data
    only exists at level 3. These placeholders have empty names and
    just copy the parent name.
    """
    level_df = df[df['admin_level'] == level]
    if len(level_df) == 0:
        return False

    # Check names - if all are empty/null/Unknown, it's a placeholder
    names = level_df['name'].fillna('')
    unique_names = names.unique()

    # Placeholder indicators:
    # 1. All names are empty
    # 2. All names are "Unknown"
    # 3. Only one unique name that matches parent pattern
    if len(unique_names) == 1:
        if unique_names[0] in ['', 'Unknown', None]:
            return True

    # Also check if > 90% of names are empty
    empty_count = (names == '').sum() + level_df['name'].isna().sum()
    if empty_count / len(level_df) > 0.9:
        return True

    return False


def remove_placeholder_levels(df):
    """
    Remove placeholder admin levels from the DataFrame.
    Returns cleaned DataFrame and list of removed levels.
    """
    levels = sorted(df['admin_level'].unique())
    removed_levels = []

    # Check from deepest level upward
    for level in reversed(levels):
        if level == 0:
            continue  # Never remove country level

        if is_placeholder_level(df, level):
            removed_levels.append(level)
            df = df[df['admin_level'] != level]
        else:
            # Stop at first non-placeholder level
            # (don't remove middle levels, only trailing placeholders)
            break

    return df, removed_levels


def merge_with_existing(new_df, existing_df):
    """
    Merge new GADM data with existing parquet, preserving existing geometry.

    Logic:
    - For loc_ids that exist in both: keep existing row if it has geometry,
      otherwise use new row (to fill in missing geometry)
    - For loc_ids only in new: add them
    - For loc_ids only in existing: keep them (e.g., Census county data)

    Returns merged DataFrame and stats dict.
    """
    if existing_df is None or len(existing_df) == 0:
        return new_df, {"preserved": 0, "added": len(new_df), "filled": 0}

    # Index by loc_id for fast lookup
    existing_by_id = existing_df.set_index('loc_id')
    new_by_id = new_df.set_index('loc_id')

    existing_ids = set(existing_by_id.index)
    new_ids = set(new_by_id.index)

    # Categories
    only_existing = existing_ids - new_ids  # Keep these (e.g., Census counties)
    only_new = new_ids - existing_ids        # Add these
    both = existing_ids & new_ids            # Merge logic

    result_rows = []
    stats = {"preserved": 0, "added": 0, "filled": 0}

    # Keep rows only in existing (preserve Census data, etc.)
    for loc_id in only_existing:
        result_rows.append(existing_by_id.loc[loc_id])
        stats["preserved"] += 1

    # Add rows only in new (new GADM data)
    for loc_id in only_new:
        result_rows.append(new_by_id.loc[loc_id])
        stats["added"] += 1

    # For rows in both: prefer existing if it has geometry, else use new
    for loc_id in both:
        existing_row = existing_by_id.loc[loc_id]
        new_row = new_by_id.loc[loc_id]

        existing_has_geom = pd.notna(existing_row.get('geometry')) and existing_row.get('geometry')

        if existing_has_geom:
            result_rows.append(existing_row)
            stats["preserved"] += 1
        else:
            result_rows.append(new_row)
            stats["filled"] += 1

    # Build result DataFrame
    result_df = pd.DataFrame(result_rows)
    result_df = result_df.reset_index()  # loc_id back to column

    # Ensure loc_id is named correctly (reset_index may name it 'index')
    if 'index' in result_df.columns and 'loc_id' not in result_df.columns:
        result_df = result_df.rename(columns={'index': 'loc_id'})

    return result_df, stats


def build_loc_id(row, admin_level, us_fips_map=None):
    """
    Build loc_id from GADM row data.

    Format: {ISO3}[-{admin1_code}[-{admin2_code}[...]]]

    For US: Use state abbreviations and FIPS codes
    For others: Use HASC codes where available, else GID suffix
    """
    iso3 = row.get('GID_0', '')

    if admin_level == 0:
        return iso3

    # Build hierarchically
    parts = [iso3]

    for level in range(1, admin_level + 1):
        if iso3 == 'USA':
            # US-specific handling
            if level == 1:
                # Use state abbreviation from HASC
                hasc = row.get('HASC_1', '')
                if hasc and '.' in hasc:
                    parts.append(hasc.split('.')[-1])
                else:
                    parts.append(str(level))
            elif level == 2:
                # Use FIPS code for counties
                if us_fips_map:
                    state_name = normalize_name(row.get('NAME_1', ''))
                    county_name = normalize_name(row.get('NAME_2', ''))
                    fips = us_fips_map.get((state_name, county_name))
                    if fips:
                        parts.append(str(fips))
                    else:
                        # Fallback: use GID suffix
                        gid = row.get(f'GID_{level}', '')
                        suffix = gid.split('.')[-1].split('_')[0] if gid else str(level)
                        parts.append(suffix)
                else:
                    gid = row.get(f'GID_{level}', '')
                    suffix = gid.split('.')[-1].split('_')[0] if gid else str(level)
                    parts.append(suffix)
            else:
                gid = row.get(f'GID_{level}', '')
                suffix = gid.split('.')[-1].split('_')[0] if gid else str(level)
                parts.append(suffix)
        else:
            # Non-US countries
            hasc = row.get(f'HASC_{level}', '')
            cc = row.get(f'CC_{level}', '')

            if hasc and '.' in hasc:
                # Use HASC code (last part after dot)
                parts.append(hasc.split('.')[-1])
            elif cc:
                # Use country code (CC_X)
                parts.append(str(cc))
            else:
                # Fallback to GID suffix
                gid = row.get(f'GID_{level}', '')
                if gid:
                    suffix = gid.split('.')[-1].split('_')[0]
                    parts.append(suffix)
                else:
                    parts.append(str(level))

    return '-'.join(parts)


def build_parent_id(loc_id):
    """Get parent_id by removing last component."""
    if '-' not in loc_id:
        return None  # Country level has no parent
    parts = loc_id.rsplit('-', 1)
    return parts[0]


def process_country(conn, iso3, us_fips_map=None):
    """
    Process all admin levels for a single country.
    Returns list of records for all unique locations.
    """
    # Get all rows for this country
    query = f"""
    SELECT *
    FROM {GADM_TABLE}
    WHERE GID_0 = ?
    """

    cursor = conn.execute(query, (iso3,))
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()

    if not rows:
        return []

    # Track unique locations by loc_id
    locations = {}

    for row_data in rows:
        row = dict(zip(columns, row_data))
        admin_level = get_admin_level(row)

        # For USA, check if this entry should be skipped (water bodies)
        if iso3 == 'USA' and admin_level == 2:
            state_name = normalize_name(row.get('NAME_1', ''))
            county_name = normalize_name(row.get('NAME_2', ''))
            if (state_name, county_name) in SKIP_GADM_ENTRIES:
                continue  # Skip water bodies like Lake Michigan

        # Process this row and all its parent levels
        for level in range(admin_level, -1, -1):
            loc_id = build_loc_id(row, level, us_fips_map)

            if loc_id in locations:
                continue  # Already processed

            # Get geometry from deepest level row
            geom_bytes = row.get('geom')

            # For parent levels, we don't have their own geometry in this row
            # We'll aggregate later or use the deepest available
            if level < admin_level:
                # Parent level - no geometry in this row
                lon, lat = None, None
                geometry_str = None
                has_polygon = False
            else:
                # Deepest level - has geometry
                lon, lat = get_centroid(geom_bytes)
                geometry_str = geometry_to_geojson(geom_bytes, level)
                has_polygon = geometry_str is not None

            # Get name for this level
            name_col = f'NAME_{level}'
            name = row.get(name_col, row.get('NAME_0', ''))

            # Get local/variant name
            varname_col = f'VARNAME_{level}' if level > 0 else None
            nlname_col = f'NL_NAME_{level}' if level > 0 else None
            name_local = row.get(varname_col) or row.get(nlname_col)
            if name_local == name:
                name_local = None

            # Get code
            if level == 0:
                code = iso3
            else:
                cc_col = f'CC_{level}'
                code = row.get(cc_col, '')

            # Get ISO 3166-2 (only for admin_1)
            iso_3166_2 = None
            if level == 1:
                hasc = row.get('HASC_1', '')
                if hasc:
                    iso_3166_2 = hasc.replace('.', '-')

            # Compute bounding box from geometry
            bbox_min_lon, bbox_min_lat, bbox_max_lon, bbox_max_lat = get_bbox_from_geometry(geometry_str)

            record = {
                'loc_id': loc_id,
                'parent_id': build_parent_id(loc_id),
                'admin_level': level,
                'name': name,
                'name_local': name_local,
                'code': str(code) if code else '',
                'iso_3166_2': iso_3166_2,
                'centroid_lon': lon,
                'centroid_lat': lat,
                'has_polygon': has_polygon,
                'geometry': geometry_str,
                'bbox_min_lon': bbox_min_lon,
                'bbox_min_lat': bbox_min_lat,
                'bbox_max_lon': bbox_max_lon,
                'bbox_max_lat': bbox_max_lat,
                'timezone': None,
                'iso_a3': iso3
            }

            locations[loc_id] = record

    return list(locations.values())


def process_all_countries(country_list=None):
    """
    Process countries and create output files.

    Args:
        country_list: Optional list of ISO3 codes to process. If None, process all.
    """
    print("=" * 60)
    print(f"GADM GeoPackage Processor ({GADM_TABLE})")
    print("=" * 60)
    print(f"Input: {GADM_FILE}")
    print(f"Output: {OUTPUT_PATH}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    if not GADM_FILE.exists():
        print(f"ERROR: GADM file not found: {GADM_FILE}")
        return

    # Load US FIPS mapping
    us_fips_map = load_us_fips_mapping()

    # Connect to GADM
    conn = sqlite3.connect(GADM_FILE)

    # Get list of countries to process
    if country_list:
        # Validate that requested countries exist in GADM
        cursor = conn.execute(f"SELECT DISTINCT GID_0 FROM {GADM_TABLE}")
        valid_countries = {row[0] for row in cursor.fetchall()}
        countries = [c.upper() for c in country_list if c.upper() in valid_countries]
        invalid = [c for c in country_list if c.upper() not in valid_countries]
        if invalid:
            print(f"Warning: Countries not found in GADM: {invalid}")
    else:
        # Get all countries
        cursor = conn.execute(f"SELECT DISTINCT GID_0 FROM {GADM_TABLE} ORDER BY GID_0")
        all_countries = [row[0] for row in cursor.fetchall()]
        # Reorder: put large countries at the end (they take longest)
        small_countries = [c for c in all_countries if c not in LARGE_COUNTRIES]
        countries = small_countries + [c for c in LARGE_COUNTRIES if c in all_countries]
        print(f"Large countries moved to end: {[c for c in LARGE_COUNTRIES if c in all_countries]}")

    print(f"Processing {len(countries)} countries")

    # Process each country
    for i, iso3 in enumerate(countries):
        print(f"\n[{i+1}/{len(countries)}] Processing {iso3}...")

        records = process_country(conn, iso3, us_fips_map)

        if not records:
            print(f"  No records for {iso3}")
            continue

        # Create DataFrame
        df = pd.DataFrame(records)

        # Sort by admin_level then loc_id
        df = df.sort_values(['admin_level', 'loc_id'])

        # Remove placeholder levels (GADM creates empty levels 4-5 for many countries)
        original_count = len(df)
        df, removed_levels = remove_placeholder_levels(df)
        if removed_levels:
            print(f"  Removed placeholder levels: {removed_levels} ({original_count - len(df)} rows)")

        # For MERGE_COUNTRIES: merge with existing data, preserving existing geometry
        output_file = OUTPUT_PATH / f"{iso3}.parquet"
        if iso3 in MERGE_COUNTRIES and output_file.exists():
            try:
                existing_df = pd.read_parquet(output_file)
                df, merge_stats = merge_with_existing(df, existing_df)
                print(f"  Merged: {merge_stats['preserved']} preserved, {merge_stats['added']} added, {merge_stats['filled']} filled")
            except Exception as e:
                print(f"  Warning: Could not merge with existing ({e}), overwriting")

        # Convert types
        df['admin_level'] = df['admin_level'].astype('int8')
        df['has_polygon'] = df['has_polygon'].astype(bool)

        # Save country parquet
        df.to_parquet(output_file, index=False)

        # Print stats
        max_depth = df['admin_level'].max()
        print(f"  Saved {len(df)} records, max depth: {max_depth}")

    conn.close()

    print("\n" + "=" * 60)
    print("Processing complete!")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    import sys

    # Parse command-line arguments
    # Usage: python process_gadm.py [COUNTRY1] [COUNTRY2] ...
    # Examples:
    #   python process_gadm.py           # Process all countries
    #   python process_gadm.py BRA ARG   # Process Brazil and Argentina only

    country_args = [arg.upper() for arg in sys.argv[1:] if not arg.startswith('-')]

    if country_args:
        print(f"Processing specific countries: {country_args}")
        process_all_countries(country_list=country_args)
    else:
        process_all_countries()
