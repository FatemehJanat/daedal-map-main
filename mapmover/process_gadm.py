"""
Process GADM 3.6 GeoPackage into per-country parquet files.

GADM 3.6 stores all admin levels in a single flat 'gadm' table.
Each row represents one location at its deepest admin level.

Input: Raw data/gadm36.gpkg
Output:
  - geometry/global.csv (all countries, admin_0 only)
  - geometry/{ISO3}.parquet (all admin levels per country)
  - geometry/country_depth.json (metadata about admin levels per country)
  - geometry/country_coverage.json (coverage stats for each country)

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

# Paths
GADM_FILE = Path(r"C:\Users\Bryan\Desktop\county-map-data\Raw data\gadm36.gpkg")
OUTPUT_PATH = Path(r"C:\Users\Bryan\Desktop\county-map-data\geometry")
CENSUS_FILE = Path(r"C:\Users\Bryan\Desktop\county-map\data_pipeline\data_cleaned\cc-est2024-alldata.csv")

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
    """Determine admin level based on which GID columns are filled."""
    for level in range(5, -1, -1):
        if row.get(f'GID_{level}') is not None:
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


def geometry_to_geojson(geom_bytes, simplify_tolerance=0.001):
    """Convert GPKG geometry to GeoJSON string."""
    try:
        geom = parse_gpkg_geometry(geom_bytes)
        if geom is None or geom.is_empty:
            return None
        # Simplify for smaller file size
        if simplify_tolerance:
            geom = geom.simplify(simplify_tolerance, preserve_topology=True)
        return json.dumps(mapping(geom))
    except Exception as e:
        return None


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
    FROM gadm
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
                geometry_str = geometry_to_geojson(geom_bytes)
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
                'timezone': None,
                'iso_a3': iso3
            }

            locations[loc_id] = record

    return list(locations.values())


def process_all_countries():
    """Process all countries and create output files."""
    print("=" * 60)
    print("GADM 3.6 GeoPackage Processor")
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

    # Get list of all countries
    cursor = conn.execute("SELECT DISTINCT GID_0 FROM gadm ORDER BY GID_0")
    countries = [row[0] for row in cursor.fetchall()]
    print(f"Found {len(countries)} countries")

    # Track metadata
    country_depth = {}
    country_coverage = {}
    global_records = []

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

        # Convert types
        df['admin_level'] = df['admin_level'].astype('int8')
        df['has_polygon'] = df['has_polygon'].astype(bool)

        # Save country parquet
        output_file = OUTPUT_PATH / f"{iso3}.parquet"
        df.to_parquet(output_file, index=False)

        # Get stats
        level_counts = df.groupby('admin_level').size().to_dict()
        max_depth = df['admin_level'].max()

        country_depth[iso3] = {
            'max_depth': int(max_depth),
            'level_counts': {int(k): int(v) for k, v in level_counts.items()}
        }

        country_coverage[iso3] = {
            'actual_depth': int(max_depth),
            'expected_depth': int(max_depth),  # GADM is authoritative
            'coverage': 1.0,
            'level_counts': {int(k): int(v) for k, v in level_counts.items()}
        }

        # Add country-level record to global list
        country_record = df[df['admin_level'] == 0].to_dict('records')
        if country_record:
            global_records.append(country_record[0])

        print(f"  Saved {len(df)} records, max depth: {max_depth}")

    conn.close()

    # Save global.csv
    if global_records:
        global_df = pd.DataFrame(global_records)
        global_df = global_df.sort_values('loc_id')
        global_df.to_csv(OUTPUT_PATH / "global.csv", index=False)
        print(f"\nSaved {len(global_df)} countries to global.csv")

    # Save metadata files
    with open(OUTPUT_PATH / "country_depth.json", 'w', encoding='utf-8') as f:
        json.dump(country_depth, f, indent=2)
    print(f"Saved country_depth.json")

    with open(OUTPUT_PATH / "country_coverage.json", 'w', encoding='utf-8') as f:
        json.dump(country_coverage, f, indent=2)
    print(f"Saved country_coverage.json")

    print("\n" + "=" * 60)
    print("Processing complete!")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    process_all_countries()
