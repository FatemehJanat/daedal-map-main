"""
Convert US Census age/sex demographics to parquet format.

Input: cc-est2024-agesex-all.csv (pre-aggregated age brackets)
Output: census_agesex/USA.parquet

Extracts age bracket totals and median age by county.
Converts FIPS codes to loc_id format (USA-{state}-{fips}).
"""

import pandas as pd
import os
import json
import sys
from pathlib import Path

# Add parent dir to path for mapmover imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from mapmover.metadata_generator import generate_metadata

# Configuration
INPUT_FILE = r"C:\Users\Bryan\Desktop\county-map\data_pipeline\Raw data\cc-est2024-agesex-all.csv"
OUTPUT_DIR = r"C:\Users\Bryan\Desktop\county-map-data\data\census_agesex"

# Source info for metadata generation
SOURCE_INFO = {
    "source_id": "census_agesex",
    "source_name": "US Census Bureau",
    "source_url": "https://www.census.gov",
    "license": "Public Domain",
    "description": "US county-level age and sex demographics",
    "category": "demographic",
    "topic_tags": ["demographics", "age", "population"],
    "keywords": ["age", "median age", "demographics", "census"],
    "update_schedule": "annual",
    "expected_next_update": "2025-03"
}

# State FIPS to abbreviation mapping
STATE_FIPS = {
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
}

# Year mapping from YEAR column
YEAR_MAP = {
    1: 2019,  # April 2020 estimates base (use 2019)
    2: 2020,
    3: 2021,
    4: 2022,
    5: 2023,
    6: 2024,
}


def fips_to_loc_id(state_fips, county_fips):
    """Convert FIPS codes to loc_id format."""
    state_str = str(state_fips).zfill(2)
    county_str = str(county_fips).zfill(3)
    abbrev = STATE_FIPS.get(state_str)
    if not abbrev:
        return None
    full_fips = int(state_str + county_str)
    return f'USA-{abbrev}-{full_fips}'


def convert_census_agesex():
    """Convert Census age/sex CSV to parquet format."""
    print("Loading Census age/sex data...")
    df = pd.read_csv(INPUT_FILE, encoding='latin-1')
    print(f"Loaded {len(df):,} rows")

    # Create loc_id
    df['loc_id'] = df.apply(
        lambda row: fips_to_loc_id(row['STATE'], row['COUNTY']),
        axis=1
    )

    # Drop rows without valid loc_id
    df = df[df['loc_id'].notna()]

    # Map YEAR to actual year
    df['year'] = df['YEAR'].map(YEAR_MAP)
    df = df[df['year'].notna()]

    print(f"After loc_id and year conversion: {len(df):,} rows")

    # Select columns to keep
    keep_cols = ['loc_id', 'year']

    # Age bracket columns (these exist in the agesex file)
    age_cols = [
        'UNDER5_TOT', 'AGE513_TOT', 'AGE1417_TOT', 'AGE1824_TOT',
        'AGE2544_TOT', 'AGE4564_TOT', 'AGE65PLUS_TOT',
        'UNDER5_MALE', 'UNDER5_FEM',
        'AGE18PLUS_TOT', 'AGE18PLUS_MALE', 'AGE18PLUS_FEM',
        'MEDIAN_AGE_TOT', 'MEDIAN_AGE_MALE', 'MEDIAN_AGE_FEM',
    ]

    # Add columns that exist
    for col in age_cols:
        if col in df.columns:
            keep_cols.append(col)

    result = df[keep_cols].copy()

    # Rename columns to cleaner names
    rename_map = {
        'UNDER5_TOT': 'under_5',
        'AGE513_TOT': 'age_5_13',
        'AGE1417_TOT': 'age_14_17',
        'AGE1824_TOT': 'age_18_24',
        'AGE2544_TOT': 'age_25_44',
        'AGE4564_TOT': 'age_45_64',
        'AGE65PLUS_TOT': 'age_65_plus',
        'UNDER5_MALE': 'under_5_male',
        'UNDER5_FEM': 'under_5_female',
        'AGE18PLUS_TOT': 'age_18_plus',
        'AGE18PLUS_MALE': 'age_18_plus_male',
        'AGE18PLUS_FEM': 'age_18_plus_female',
        'MEDIAN_AGE_TOT': 'median_age',
        'MEDIAN_AGE_MALE': 'median_age_male',
        'MEDIAN_AGE_FEM': 'median_age_female',
    }
    result = result.rename(columns=rename_map)

    # Remove duplicates
    result = result.drop_duplicates(subset=['loc_id', 'year'], keep='last')

    print(f"Result: {len(result):,} rows x {len(result.columns)} columns")

    # Save parquet
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "USA.parquet")
    result.to_parquet(out_path, index=False)
    print(f"\nSaved: {out_path}")
    print(f"Size: {os.path.getsize(out_path) / 1024:.1f} KB")

    # Show sample
    print("\n=== Sample (Los Angeles County) ===")
    la = result[result['loc_id'] == 'USA-CA-6037']
    print(la[['loc_id', 'year', 'median_age', 'under_5', 'age_18_plus', 'age_65_plus']].to_string(index=False))

    return out_path


def create_metadata(parquet_path):
    """Create metadata.json using the shared generator."""
    metadata = generate_metadata(parquet_path, SOURCE_INFO)

    meta_path = os.path.join(OUTPUT_DIR, "metadata.json")
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved: {meta_path}")

    return metadata


if __name__ == "__main__":
    parquet_path = convert_census_agesex()
    create_metadata(parquet_path)
    print("\nDone!")
