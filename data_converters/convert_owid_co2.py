"""
Convert OWID CO2 data to parquet format.

Input: owid-co2-data.csv (already in wide format)
Output: owid_co2/all_countries.parquet

This is a simple conversion - the data is already in the right format.
We just need to:
1. Rename country_code -> loc_id
2. Rename data_year -> year
3. Drop country_name (redundant)
"""

import pandas as pd
import os
import json

# Configuration
INPUT_FILE = r"C:\Users\Bryan\Desktop\county-map\data_pipeline\data_cleaned\owid-co2-data.csv"
OUTPUT_DIR = r"C:\Users\Bryan\Desktop\county-map-data\data\owid_co2"


def convert_owid_data():
    """Convert OWID CSV to parquet format."""
    print("Loading OWID CO2 data...")
    df = pd.read_csv(INPUT_FILE)
    print(f"Loaded {len(df):,} rows")

    # Add loc_id (country_code IS the loc_id for country-level data)
    df['loc_id'] = df['country_code']

    # Rename data_year to year
    df = df.rename(columns={'data_year': 'year'})

    # Drop redundant columns
    drop_cols = ['country_code', 'country_name']
    df = df.drop(columns=drop_cols)

    # Reorder columns: loc_id, year first
    id_cols = ['loc_id', 'year']
    metric_cols = [c for c in df.columns if c not in id_cols]
    df = df[id_cols + metric_cols]

    print(f"Result: {len(df):,} rows x {len(df.columns)} columns")
    print(f"Dropped: {drop_cols}")

    # Verify country codes match geometry
    print("\nVerifying country codes...")
    geom = pd.read_csv(r"C:\Users\Bryan\Desktop\county-map-data\geometry\global.csv")
    geom_codes = set(geom['loc_id'])
    owid_codes = set(df['loc_id'])

    matched = owid_codes & geom_codes
    unmatched = owid_codes - geom_codes

    print(f"Matched: {len(matched)}")
    if unmatched:
        print(f"Unmatched: {unmatched}")

    # Save parquet
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "all_countries.parquet")
    df.to_parquet(out_path, index=False)
    print(f"\nSaved: {out_path}")
    print(f"Size: {os.path.getsize(out_path) / 1024 / 1024:.1f} MB")

    # Show sample
    print("\n=== Sample (USA last 5 years) ===")
    usa = df[df['loc_id'] == 'USA'].sort_values('year').tail(5)
    print(usa[['loc_id', 'year', 'population', 'gdp', 'co2', 'co2_per_capita']].to_string(index=False))

    return df


def create_metadata(df):
    """Create metadata.json for the dataset."""
    metric_cols = [c for c in df.columns if c not in ['loc_id', 'year']]

    metadata = {
        "source_id": "owid_co2",
        "source_name": "Our World in Data",
        "description": "CO2 and greenhouse gas emissions, energy, and economic data",
        "source_url": "https://github.com/owid/co2-data",
        "last_updated": "2024-12-21",
        "license": "CC-BY",
        "geographic_level": "country",
        "year_range": {
            "start": int(df['year'].min()),
            "end": int(df['year'].max())
        },
        "countries_covered": df['loc_id'].nunique(),
        "metrics": {
            "population": {"name": "Population", "unit": "count", "aggregation": "sum"},
            "gdp": {"name": "GDP", "unit": "USD", "aggregation": "sum"},
            "co2": {"name": "Annual CO2 emissions", "unit": "million tonnes", "aggregation": "sum"},
            "co2_per_capita": {"name": "CO2 per capita", "unit": "tonnes/person", "aggregation": "avg"},
            "cement_co2": {"name": "CO2 from cement", "unit": "million tonnes", "aggregation": "sum"},
            "coal_co2": {"name": "CO2 from coal", "unit": "million tonnes", "aggregation": "sum"},
            "oil_co2": {"name": "CO2 from oil", "unit": "million tonnes", "aggregation": "sum"},
            "gas_co2": {"name": "CO2 from gas", "unit": "million tonnes", "aggregation": "sum"},
            "flaring_co2": {"name": "CO2 from flaring", "unit": "million tonnes", "aggregation": "sum"},
            "methane": {"name": "Methane emissions", "unit": "million tonnes CO2eq", "aggregation": "sum"},
            "nitrous_oxide": {"name": "Nitrous oxide emissions", "unit": "million tonnes CO2eq", "aggregation": "sum"},
            "total_ghg": {"name": "Total GHG emissions", "unit": "million tonnes CO2eq", "aggregation": "sum"},
            "primary_energy_consumption": {"name": "Primary energy consumption", "unit": "TWh", "aggregation": "sum"},
            "energy_per_capita": {"name": "Energy per capita", "unit": "kWh/person", "aggregation": "avg"},
        },
        "topic_tags": ["climate", "emissions", "environment", "energy", "economics"],
        "llm_summary": f"Comprehensive CO2 and greenhouse gas emissions data for {df['loc_id'].nunique()} countries ({df['year'].min()}-{df['year'].max()})"
    }

    meta_path = os.path.join(OUTPUT_DIR, "metadata.json")
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved: {meta_path}")

    return metadata


if __name__ == "__main__":
    df = convert_owid_data()
    create_metadata(df)
    print("\nDone!")
