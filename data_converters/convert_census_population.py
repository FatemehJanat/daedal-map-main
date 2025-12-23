"""
Convert US Census county population estimates to parquet format.

Input: cc-est2024-alldata.csv (race/ethnicity data with AGEGRP rows)
Output: census_population/USA.parquet

Extracts total population by sex from AGEGRP=0 (all ages) rows.
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
INPUT_FILE = r"C:\Users\Bryan\Desktop\county-map\data_pipeline\Raw data\cc-est2024-alldata.csv"
OUTPUT_DIR = r"C:\Users\Bryan\Desktop\county-map-data\data\census_population"

# Source info for metadata generation
SOURCE_INFO = {
    "source_id": "census_population",
    "source_name": "US Census Bureau",
    "source_url": "https://www.census.gov",
    "license": "Public Domain",
    "description": "US county-level population estimates",
    "category": "demographic",
    "topic_tags": ["demographics", "population"],
    "keywords": ["population", "people", "residents", "census"],
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


def fips_to_loc_id(state_fips, county_fips):
    """Convert FIPS codes to loc_id format."""
    state_str = str(state_fips).zfill(2)
    county_str = str(county_fips).zfill(3)
    abbrev = STATE_FIPS.get(state_str)
    if not abbrev:
        return None
    full_fips = int(state_str + county_str)
    return f'USA-{abbrev}-{full_fips}'


def convert_census_population():
    """Convert Census population CSV to parquet format."""
    print("Loading Census population data...")
    df = pd.read_csv(INPUT_FILE, encoding='latin-1')
    print(f"Loaded {len(df):,} rows")

    # Filter to AGEGRP=0 (all ages combined)
    df = df[df['AGEGRP'] == 0].copy()
    print(f"After filtering AGEGRP=0: {len(df):,} rows")

    # Create loc_id
    df['loc_id'] = df.apply(
        lambda row: fips_to_loc_id(row['STATE'], row['COUNTY']),
        axis=1
    )

    # Drop rows without valid loc_id
    df = df[df['loc_id'].notna()]
    print(f"After loc_id conversion: {len(df):,} rows")

    # Year columns mapping (POPESTIMATE2020, etc.)
    year_cols = {
        'POPESTIMATE2020': 2020,
        'POPESTIMATE2021': 2021,
        'POPESTIMATE2022': 2022,
        'POPESTIMATE2023': 2023,
        'POPESTIMATE2024': 2024,
    }

    # Melt to long format
    records = []
    for _, row in df.iterrows():
        loc_id = row['loc_id']
        for col, year in year_cols.items():
            if col in df.columns:
                # Get total, male, female for this year
                total_col = col
                male_col = col.replace('POPESTIMATE', 'POPEST_MALE')
                female_col = col.replace('POPESTIMATE', 'POPEST_FEM')

                records.append({
                    'loc_id': loc_id,
                    'year': year,
                    'total_pop': row.get(total_col),
                    'male': row.get(male_col),
                    'female': row.get(female_col),
                })

    result = pd.DataFrame(records)

    # Remove duplicates (keep last - July estimate over April census)
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
    print(la.to_string(index=False))

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
    parquet_path = convert_census_population()
    create_metadata(parquet_path)
    print("\nDone!")
