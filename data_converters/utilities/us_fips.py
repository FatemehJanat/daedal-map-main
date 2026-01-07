"""
US FIPS Code Utilities

Provides mappings and functions for working with US Federal Information Processing
Standards (FIPS) codes for states and counties.

Usage:
    from data_converters.utilities.us_fips import (
        STATE_FIPS_TO_ABBR,
        STATE_ABBR_TO_FIPS,
        STATE_NAME_TO_FIPS,
        normalize_county_name,
        load_county_fips_mapping,
        build_usa_loc_id,
    )

    # Build loc_id from FIPS
    loc_id = build_usa_loc_id(6037)  # "USA-CA-6037" (Los Angeles County)

    # Or from state/county names
    fips_map = load_county_fips_mapping()
    fips = fips_map.get(('06', 'losangeles'))  # 6037
"""
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

# =============================================================================
# STATE FIPS MAPPINGS
# =============================================================================

# State FIPS code to 2-letter abbreviation
STATE_FIPS_TO_ABBR = {
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
    '56': 'WY',
    # Territories
    '60': 'AS',  # American Samoa
    '66': 'GU',  # Guam
    '69': 'MP',  # Northern Mariana Islands
    '72': 'PR',  # Puerto Rico
    '78': 'VI',  # Virgin Islands
}

# Reverse: abbreviation to FIPS
STATE_ABBR_TO_FIPS = {v: k for k, v in STATE_FIPS_TO_ABBR.items()}

# State name to FIPS (for datasets that use full names)
STATE_NAME_TO_FIPS = {
    'Alabama': '01', 'Alaska': '02', 'Arizona': '04', 'Arkansas': '05',
    'California': '06', 'Colorado': '08', 'Connecticut': '09', 'Delaware': '10',
    'District of Columbia': '11', 'Florida': '12', 'Georgia': '13', 'Hawaii': '15',
    'Idaho': '16', 'Illinois': '17', 'Indiana': '18', 'Iowa': '19',
    'Kansas': '20', 'Kentucky': '21', 'Louisiana': '22', 'Maine': '23',
    'Maryland': '24', 'Massachusetts': '25', 'Michigan': '26', 'Minnesota': '27',
    'Mississippi': '28', 'Missouri': '29', 'Montana': '30', 'Nebraska': '31',
    'Nevada': '32', 'New Hampshire': '33', 'New Jersey': '34', 'New Mexico': '35',
    'New York': '36', 'North Carolina': '37', 'North Dakota': '38', 'Ohio': '39',
    'Oklahoma': '40', 'Oregon': '41', 'Pennsylvania': '42', 'Rhode Island': '44',
    'South Carolina': '45', 'South Dakota': '46', 'Tennessee': '47', 'Texas': '48',
    'Utah': '49', 'Vermont': '50', 'Virginia': '51', 'Washington': '53',
    'West Virginia': '54', 'Wisconsin': '55', 'Wyoming': '56',
    # Territories
    'American Samoa': '60', 'Guam': '66', 'Northern Mariana Islands': '69',
    'Puerto Rico': '72', 'Virgin Islands': '78',
}

# Reverse: FIPS to state name
STATE_FIPS_TO_NAME = {v: k for k, v in STATE_NAME_TO_FIPS.items()}


# =============================================================================
# MANUAL COUNTY FIPS MAPPINGS (Edge Cases)
# =============================================================================

# Counties that changed names or were reorganized - map old/variant names to current FIPS
# Format: (normalized_state, normalized_county) -> FIPS code
MANUAL_FIPS_MAPPING = {
    # Alaska reorganizations (GADM uses old 2010-era names)
    ('alaska', 'wadehampton'): 2158,  # Renamed to Kusilvak Census Area (2015)
    ('alaska', 'princeofwalesouterketchi'): 2198,  # Prince of Wales-Hyder
    ('alaska', 'skagwayyakutatangoon'): 2232,  # Split - using Skagway
    ('alaska', 'valdezcordova'): 2261,  # Split into Chugach + Copper River (2019)
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

# Entries to skip (water bodies, defunct entities)
SKIP_ENTRIES = {
    # Great Lakes water bodies (sometimes included in geometry sources)
    ('illinois', 'lakemichigan'),
    ('indiana', 'lakemichigan'),
    ('michigan', 'lakemichigan'),
    ('wisconsin', 'lakemichigan'),
    ('michigan', 'lakehuron'),
    ('michigan', 'lakehurron'),  # Typo in some sources
    ('michigan', 'lakestclair'),
    ('michigan', 'lakesuperior'),
    ('minnesota', 'lakesuperior'),
    ('wisconsin', 'lakesuperior'),
    ('ohio', 'lakeerie'),
    ('michigan', 'lakeerie'),
    ('newyork', 'lakeerie'),
    ('newyork', 'lakeontario'),

    # Defunct independent cities (merged into counties)
    ('virginia', 'cliftonforge'),  # Merged into Alleghany County (2001)
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def normalize_county_name(name: str) -> str:
    """
    Normalize county name for matching.

    Removes common suffixes (County, Parish, Borough, etc.), normalizes
    saint/st variations, and strips non-alphanumeric characters.

    Args:
        name: Raw county name

    Returns:
        Normalized lowercase alphanumeric string
    """
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

    # Remove all non-alphanumeric
    name = re.sub(r'[^a-z0-9]', '', name)
    return name


def normalize_state_name(name: str) -> str:
    """
    Normalize state name for matching.

    Args:
        name: Raw state name

    Returns:
        Normalized lowercase alphanumeric string
    """
    if not name:
        return ""
    name = str(name).lower().strip()
    name = re.sub(r'[^a-z0-9]', '', name)
    return name


def load_county_fips_mapping(census_file: Optional[Path] = None) -> Dict[Tuple[str, str], int]:
    """
    Load county name to FIPS mapping from Census data.

    Args:
        census_file: Path to Census population estimates CSV.
                     Defaults to standard location.

    Returns:
        Dict mapping (state_fips, normalized_county) -> full_fips_code
    """
    import pandas as pd

    if census_file is None:
        census_file = Path("C:/Users/Bryan/Desktop/county-map/data_pipeline/data_cleaned/cc-est2024-alldata.csv")

    if not census_file.exists():
        print(f"WARNING: Census file not found: {census_file}")
        print("  County name-to-FIPS mapping will only use manual mappings.")
        return dict(MANUAL_FIPS_MAPPING)

    df = pd.read_csv(census_file, usecols=['county_code', 'county_name', 'state_name'])
    df = df.drop_duplicates(subset=['county_code'])

    mapping = {}
    for _, row in df.iterrows():
        state_fips = str(row['county_code'])[:2].zfill(2)
        county_norm = normalize_county_name(row['county_name'])
        fips = int(row['county_code'])
        mapping[(state_fips, county_norm)] = fips

    # Add manual mappings (overrides for edge cases)
    mapping.update(MANUAL_FIPS_MAPPING)

    print(f"Loaded {len(mapping)} county FIPS codes")
    return mapping


def build_usa_loc_id(fips_code: int) -> str:
    """
    Build a USA loc_id from a full 5-digit FIPS code.

    Args:
        fips_code: Full 5-digit FIPS code (e.g., 6037 for Los Angeles County)

    Returns:
        loc_id string (e.g., "USA-CA-6037")
    """
    fips_str = str(fips_code).zfill(5)
    state_fips = fips_str[:2]
    state_abbr = STATE_FIPS_TO_ABBR.get(state_fips, 'XX')
    return f"USA-{state_abbr}-{fips_code}"


def build_usa_loc_id_from_parts(state_fips: str, county_fips: str) -> str:
    """
    Build a USA loc_id from separate state and county FIPS.

    Args:
        state_fips: 2-digit state FIPS (e.g., "06")
        county_fips: 3-digit county FIPS (e.g., "037")

    Returns:
        loc_id string (e.g., "USA-CA-6037")
    """
    state_abbr = STATE_FIPS_TO_ABBR.get(state_fips, 'XX')
    full_fips = int(state_fips + county_fips)
    return f"USA-{state_abbr}-{full_fips}"


def get_state_loc_id(state_fips: str) -> str:
    """
    Get state-level loc_id from state FIPS.

    Args:
        state_fips: 2-digit state FIPS (e.g., "06")

    Returns:
        State loc_id (e.g., "USA-CA")
    """
    state_abbr = STATE_FIPS_TO_ABBR.get(state_fips, 'XX')
    return f"USA-{state_abbr}"


def should_skip_entry(state_name: str, county_name: str) -> bool:
    """
    Check if a state/county combination should be skipped (water bodies, etc.).

    Args:
        state_name: State name
        county_name: County name

    Returns:
        True if entry should be skipped
    """
    state_norm = normalize_state_name(state_name)
    county_norm = normalize_county_name(county_name)
    return (state_norm, county_norm) in SKIP_ENTRIES


# =============================================================================
# MAIN (for testing)
# =============================================================================

if __name__ == "__main__":
    print("US FIPS Utilities")
    print("=" * 60)

    print(f"\nState mappings: {len(STATE_FIPS_TO_ABBR)} states/territories")
    print(f"Manual county mappings: {len(MANUAL_FIPS_MAPPING)} edge cases")
    print(f"Skip entries: {len(SKIP_ENTRIES)} water bodies/defunct")

    # Test build_usa_loc_id
    test_cases = [
        (6037, "USA-CA-6037"),      # Los Angeles County, CA
        (36061, "USA-NY-36061"),    # New York County (Manhattan), NY
        (48201, "USA-TX-48201"),    # Harris County (Houston), TX
        (72001, "USA-PR-72001"),    # Adjuntas, PR
    ]

    print("\nTest build_usa_loc_id:")
    for fips, expected in test_cases:
        result = build_usa_loc_id(fips)
        status = "OK" if result == expected else "FAIL"
        print(f"  {fips} -> {result} [{status}]")

    # Test normalization
    print("\nTest normalize_county_name:")
    test_names = [
        ("Los Angeles County", "losangeles"),
        ("St. Louis City", "stlouiscity"),
        ("Prince George's County", "princegeorges"),
        ("Dona Ana County", "donaana"),
    ]
    for raw, expected in test_names:
        result = normalize_county_name(raw)
        status = "OK" if result == expected else "FAIL"
        print(f"  '{raw}' -> '{result}' [{status}]")
