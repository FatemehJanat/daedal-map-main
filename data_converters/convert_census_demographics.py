"""
Convert US Census race/ethnicity demographics to parquet format.

Input: cc-est2024-alldata.csv (race/ethnicity data with AGEGRP rows)
Output: census_demographics/USA.parquet

Extracts race/ethnicity population by sex from AGEGRP=0 (all ages) rows.
Converts FIPS codes to loc_id format (USA-{state}-{fips}).
"""

import pandas as pd
import os
import json

# Configuration
INPUT_FILE = r"C:\Users\Bryan\Desktop\county-map\data_pipeline\Raw data\cc-est2024-alldata.csv"
OUTPUT_DIR = r"C:\Users\Bryan\Desktop\county-map-data\data\census_demographics"

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


def convert_census_demographics():
    """Convert Census demographics CSV to parquet format."""
    print("Loading Census demographics data...")
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

    # Race/ethnicity columns we want (for each year)
    # Format: {prefix}_{year} where year is 2020-2024
    race_prefixes = {
        'WA': 'white',           # White alone
        'BA': 'black',           # Black alone
        'IA': 'native',          # American Indian/Alaska Native alone
        'AA': 'asian',           # Asian alone
        'NA': 'pacific',         # Native Hawaiian/Pacific Islander alone
        'TOM': 'multiracial',    # Two or more races
        'H': 'hispanic',         # Hispanic or Latino
    }

    # Build records in long format
    records = []
    for _, row in df.iterrows():
        loc_id = row['loc_id']

        for year in range(2020, 2025):
            record = {'loc_id': loc_id, 'year': year}

            for prefix, name in race_prefixes.items():
                # Male column
                male_col = f'{prefix}_MALE{year}'
                if male_col in df.columns:
                    record[f'{name}_male'] = row.get(male_col)

                # Female column
                female_col = f'{prefix}_FEMALE{year}'
                if female_col in df.columns:
                    record[f'{name}_female'] = row.get(female_col)

            records.append(record)

    result = pd.DataFrame(records)

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
    print("\n=== Sample (Los Angeles County 2024) ===")
    la = result[(result['loc_id'] == 'USA-CA-6037') & (result['year'] == 2024)]
    print(la.to_string(index=False))

    return result


def create_metadata(df):
    """Create metadata.json for the dataset."""
    metadata = {
        "source_id": "census_demographics",
        "source_name": "US Census Bureau",
        "description": "County-level race and ethnicity demographics by sex",
        "source_url": "https://www.census.gov/programs-surveys/popest.html",
        "last_updated": "2024-12-21",
        "license": "Public Domain",
        "geographic_level": "county",
        "year_range": {
            "start": int(df['year'].min()),
            "end": int(df['year'].max())
        },
        "countries_covered": ["USA"],
        "metrics": {
            "white_male": {"name": "White Male", "unit": "count", "aggregation": "sum"},
            "white_female": {"name": "White Female", "unit": "count", "aggregation": "sum"},
            "black_male": {"name": "Black Male", "unit": "count", "aggregation": "sum"},
            "black_female": {"name": "Black Female", "unit": "count", "aggregation": "sum"},
            "asian_male": {"name": "Asian Male", "unit": "count", "aggregation": "sum"},
            "asian_female": {"name": "Asian Female", "unit": "count", "aggregation": "sum"},
            "hispanic_male": {"name": "Hispanic Male", "unit": "count", "aggregation": "sum"},
            "hispanic_female": {"name": "Hispanic Female", "unit": "count", "aggregation": "sum"},
            "native_male": {"name": "Native American Male", "unit": "count", "aggregation": "sum"},
            "native_female": {"name": "Native American Female", "unit": "count", "aggregation": "sum"},
            "pacific_male": {"name": "Pacific Islander Male", "unit": "count", "aggregation": "sum"},
            "pacific_female": {"name": "Pacific Islander Female", "unit": "count", "aggregation": "sum"},
            "multiracial_male": {"name": "Multiracial Male", "unit": "count", "aggregation": "sum"},
            "multiracial_female": {"name": "Multiracial Female", "unit": "count", "aggregation": "sum"},
        },
        "topic_tags": ["demographics", "race", "ethnicity", "population"],
        "llm_summary": f"US county race/ethnicity demographics for {df['loc_id'].nunique()} counties ({df['year'].min()}-{df['year'].max()})"
    }

    meta_path = os.path.join(OUTPUT_DIR, "metadata.json")
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved: {meta_path}")

    return metadata


if __name__ == "__main__":
    df = convert_census_demographics()
    create_metadata(df)
    print("\nDone!")
