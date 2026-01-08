"""
Build ZCTA to County/State crosswalk reference file.

Creates a lookup table that maps ZIP codes (ZCTAs) to:
- Primary county (by land area)
- State
- All overlapping counties (for ZCTAs that span multiple counties)

This enables address-based lookups: User enters ZIP -> get county/state loc_ids
-> pull data from whatever geographic level is available.

Input: Census Bureau ZCTA to County Relationship File
Output: mapmover/reference/usa/zcta_crosswalk.parquet

Usage:
    python build_zcta_crosswalk.py
"""

import sys
from pathlib import Path
import pandas as pd
import json

# Paths
RAW_FILE = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/census/crosswalks/zcta_county_rel_10.txt")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map/mapmover/reference/usa")
USA_ADMIN = OUTPUT_DIR / "usa_admin.json"


def load_fips_mapping():
    """Load FIPS to state abbreviation mapping."""
    with open(USA_ADMIN, 'r') as f:
        admin = json.load(f)
    return admin['fips_to_abbrev']


def load_relationship_file():
    """Load Census ZCTA-County relationship file."""
    print(f"Loading {RAW_FILE}...")

    # Read pipe-delimited file
    df = pd.read_csv(RAW_FILE, sep='|', dtype=str, encoding='utf-8-sig')

    print(f"  Loaded {len(df):,} relationship records")
    print(f"  Columns: {list(df.columns)}")

    return df


def build_crosswalk(df, fips_to_abbrev):
    """
    Build ZCTA crosswalk with primary county assignment.

    For ZCTAs spanning multiple counties, assigns primary county
    based on largest land area overlap.
    """
    print("\nBuilding crosswalk...")

    # Filter to records with valid ZCTA codes
    df = df[df['GEOID_ZCTA5_20'].notna() & (df['GEOID_ZCTA5_20'] != '')].copy()
    print(f"  {len(df):,} records with valid ZCTAs")

    # Convert area to numeric
    df['AREALAND_PART'] = pd.to_numeric(df['AREALAND_PART'], errors='coerce').fillna(0)

    # Extract state FIPS from county FIPS (first 2 digits)
    df['state_fips'] = df['GEOID_COUNTY_20'].str[:2]
    df['county_fips'] = df['GEOID_COUNTY_20']

    # Map to state abbreviation
    df['state_abbrev'] = df['state_fips'].map(fips_to_abbrev)

    # Build loc_id for county
    def make_county_loc_id(row):
        if pd.isna(row['state_abbrev']) or pd.isna(row['county_fips']):
            return None
        # Convert FIPS to integer to remove leading zeros, then back to string
        try:
            fips_int = int(row['county_fips'])
            return f"USA-{row['state_abbrev']}-{fips_int}"
        except:
            return None

    df['county_loc_id'] = df.apply(make_county_loc_id, axis=1)

    # Filter out records with missing mappings
    df = df[df['county_loc_id'].notna()].copy()
    print(f"  {len(df):,} records after filtering invalid mappings")

    # Group by ZCTA and find primary county (largest land area overlap)
    print("  Assigning primary counties by land area...")

    # Sort by ZCTA and land area (descending)
    df_sorted = df.sort_values(['GEOID_ZCTA5_20', 'AREALAND_PART'], ascending=[True, False])

    # Get primary county (first in sorted order = largest area)
    primary = df_sorted.groupby('GEOID_ZCTA5_20').first().reset_index()

    # Get all counties for each ZCTA (for multi-county lookups)
    all_counties = df.groupby('GEOID_ZCTA5_20').agg({
        'county_loc_id': lambda x: list(x.unique()),
        'AREALAND_PART': 'sum'
    }).reset_index()
    all_counties.columns = ['zcta', 'all_counties', 'total_land_area']

    # Count counties per ZCTA
    all_counties['county_count'] = all_counties['all_counties'].apply(len)

    # Build final crosswalk
    crosswalk = pd.DataFrame({
        'zcta': primary['GEOID_ZCTA5_20'],
        'zcta_loc_id': 'USA-Z-' + primary['GEOID_ZCTA5_20'],
        'primary_county_loc_id': primary['county_loc_id'],
        'primary_county_name': primary['NAMELSAD_COUNTY_20'],
        'state_abbrev': primary['state_abbrev'],
        'state_loc_id': 'USA-' + primary['state_abbrev'],
    })

    # Merge in multi-county info
    crosswalk = crosswalk.merge(all_counties[['zcta', 'all_counties', 'county_count']], on='zcta')

    # Convert all_counties list to JSON string for parquet storage
    crosswalk['all_counties_json'] = crosswalk['all_counties'].apply(json.dumps)
    crosswalk = crosswalk.drop('all_counties', axis=1)

    print(f"  Created crosswalk with {len(crosswalk):,} ZCTAs")

    return crosswalk


def print_stats(crosswalk):
    """Print crosswalk statistics."""
    print("\n" + "=" * 60)
    print("ZCTA CROSSWALK STATISTICS")
    print("=" * 60)

    print(f"\nTotal ZCTAs: {len(crosswalk):,}")

    # State distribution
    state_counts = crosswalk['state_abbrev'].value_counts()
    print(f"\nZCTAs by state (top 10):")
    for state, count in state_counts.head(10).items():
        print(f"  {state}: {count:,}")

    # Multi-county ZCTAs
    multi_county = crosswalk[crosswalk['county_count'] > 1]
    print(f"\nMulti-county ZCTAs: {len(multi_county):,} ({100*len(multi_county)/len(crosswalk):.1f}%)")

    max_counties = crosswalk['county_count'].max()
    print(f"Max counties per ZCTA: {max_counties}")

    # Example lookups
    print("\nExample lookups:")
    examples = ['90210', '10001', '60601', '33139', '98101']
    for zcta in examples:
        row = crosswalk[crosswalk['zcta'] == zcta]
        if len(row) > 0:
            r = row.iloc[0]
            print(f"  {zcta}: {r['primary_county_name']}, {r['state_abbrev']} -> {r['primary_county_loc_id']}")


def main():
    print("=" * 60)
    print("ZCTA to County Crosswalk Builder")
    print("=" * 60)

    # Load mappings
    fips_to_abbrev = load_fips_mapping()
    print(f"Loaded {len(fips_to_abbrev)} state FIPS mappings")

    # Load relationship file
    df = load_relationship_file()

    # Build crosswalk
    crosswalk = build_crosswalk(df, fips_to_abbrev)

    # Print statistics
    print_stats(crosswalk)

    # Save to parquet
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "zcta_crosswalk.parquet"

    crosswalk.to_parquet(output_path, index=False)
    print(f"\nSaved to: {output_path}")
    print(f"File size: {output_path.stat().st_size / 1024:.1f} KB")

    # Also save a sample as JSON for inspection
    sample_path = OUTPUT_DIR / "zcta_crosswalk_sample.json"
    sample = crosswalk.head(100).to_dict(orient='records')
    with open(sample_path, 'w') as f:
        json.dump(sample, f, indent=2)
    print(f"Sample saved to: {sample_path}")

    print("\n" + "=" * 60)
    print("COMPLETE!")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
