"""
Convert IMF Balance of Payments data to parquet format.

Input: IMF_BOPAGG_WIDEF.csv (years as columns, indicators as rows)
Output: imf_bop/all_countries.parquet (years as rows, indicators as columns)

The IMF data has two unit types:
- USD (millions) - primary
- Percentage of GDP - secondary

We keep USD values and rename indicators to clean column names.
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
INPUT_FILE = r"C:\Users\Bryan\Desktop\county-map\data_pipeline\data_cleaned\IMF_BOPAGG_WIDEF.csv"
OUTPUT_DIR = r"C:\Users\Bryan\Desktop\county-map-data\data\imf_bop"

# Source info for metadata generation
SOURCE_INFO = {
    "source_id": "imf_bop",
    "source_name": "International Monetary Fund",
    "source_url": "https://data.imf.org",
    "license": "IMF Data Terms",
    "description": "Balance of payments and trade data",
    "category": "economic",
    "topic_tags": ["economics", "trade", "finance"],
    "keywords": ["trade", "exports", "imports", "balance of payments", "finance"],
    "update_schedule": "annual",
    "expected_next_update": "2025-04"
}

# Year columns in the data
YEAR_COLS = [str(y) for y in range(2005, 2023)]

# Indicator name mapping (only USD indicators)
INDICATOR_NAMES = {
    "IMF_BOPAGG_BCA_BP6": "current_account_pct_gdp",  # This one is % of GDP
    "IMF_BOPAGG_BG_BP6_USD": "goods_balance",
    "IMF_BOPAGG_BMS_BP6_USD": "services_imports",
    "IMF_BOPAGG_BMG_BP6_USD": "goods_imports",
    "IMF_BOPAGG_BMCA_BP6_USD": "current_account_debit",
    "IMF_BOPAGG_BXCA_BP6_USD": "current_account_credit",
    "IMF_BOPAGG_BXS_BP6_USD": "services_exports",
    "IMF_BOPAGG_BXG_BP6_USD": "goods_exports",
    "IMF_BOPAGG_BS_BP6_USD": "services_balance",
    "IMF_BOPAGG_BGS_BP6_USD": "goods_services_balance",
    "IMF_BOPAGG_BIP_BP6_USD": "primary_income_balance",
    "IMF_BOPAGG_BIS_BP6_USD": "secondary_income_balance",
    "IMF_BOPAGG_BK_BP6_USD": "capital_account_balance",
    "IMF_BOPAGG_BFD_BP6_USD": "direct_investment_balance",
    "IMF_BOPAGG_BFP_BP6_USD": "portfolio_investment_balance",
    "IMF_BOPAGG_BFF_BP6_USD": "financial_derivatives_balance",
    "IMF_BOPAGG_BFRAFR_BP6_USD": "reserve_assets",
}


def convert_imf_data():
    """Convert IMF CSV to parquet format."""
    print("Loading IMF BOP data...")
    df = pd.read_csv(INPUT_FILE)
    print(f"Loaded {len(df):,} rows")

    # Filter to USD values only (most useful for comparisons)
    df_usd = df[df['UNIT_MEASURE'] == 'USD'].copy()
    print(f"USD rows: {len(df_usd):,}")

    # Also get the current account % GDP (useful metric)
    df_pct = df[(df['INDICATOR'] == 'IMF_BOPAGG_BCA_BP6') & (df['UNIT_MEASURE'] == 'PT_GDP')].copy()
    df_pct['INDICATOR'] = 'IMF_BOPAGG_BCA_BP6_PCT'  # Rename to distinguish
    print(f"Adding current account % GDP: {len(df_pct):,} rows")

    df_combined = pd.concat([df_usd, df_pct], ignore_index=True)

    # Melt year columns to rows
    print("Melting years to rows...")
    df_melted = df_combined.melt(
        id_vars=['country_code', 'INDICATOR'],
        value_vars=YEAR_COLS,
        var_name='year',
        value_name='value'
    )

    # Convert year to int
    df_melted['year'] = df_melted['year'].astype(int)

    # Drop null values
    df_melted = df_melted.dropna(subset=['value'])
    print(f"After dropping nulls: {len(df_melted):,} rows")

    # Create clean indicator names
    def clean_indicator(ind):
        # Use mapping if available
        if ind in INDICATOR_NAMES:
            return INDICATOR_NAMES[ind]
        # Otherwise create from code
        name = ind.replace('IMF_BOPAGG_', '').replace('_BP6_USD', '').replace('_BP6', '')
        return name.lower()

    df_melted['indicator'] = df_melted['INDICATOR'].apply(clean_indicator)

    # Pivot to wide format
    print("Pivoting indicators to columns...")
    pivot_df = df_melted.pivot_table(
        index=['country_code', 'year'],
        columns='indicator',
        values='value',
        aggfunc='first'
    ).reset_index()

    # Rename country_code to loc_id
    pivot_df = pivot_df.rename(columns={'country_code': 'loc_id'})

    # Flatten column names
    pivot_df.columns.name = None

    print(f"Result: {len(pivot_df):,} rows x {len(pivot_df.columns)} columns")

    # Verify country codes match geometry
    print("\nVerifying country codes...")
    geom = pd.read_csv(r"C:\Users\Bryan\Desktop\county-map-data\geometry\global.csv")
    geom_codes = set(geom['loc_id'])
    imf_codes = set(pivot_df['loc_id'])

    matched = imf_codes & geom_codes
    unmatched = imf_codes - geom_codes

    print(f"Matched: {len(matched)}")
    if unmatched:
        print(f"Unmatched ({len(unmatched)}): {sorted(unmatched)[:10]}...")

    # Save parquet
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "all_countries.parquet")
    pivot_df.to_parquet(out_path, index=False)
    print(f"\nSaved: {out_path}")
    print(f"Size: {os.path.getsize(out_path) / 1024:.1f} KB")

    # Show sample
    print("\n=== Sample (USA) ===")
    usa = pivot_df[pivot_df['loc_id'] == 'USA'].tail(5)
    cols_to_show = ['loc_id', 'year', 'goods_balance', 'services_balance', 'current_account_pct_gdp']
    cols_avail = [c for c in cols_to_show if c in pivot_df.columns]
    print(usa[cols_avail].to_string(index=False))

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
    parquet_path = convert_imf_data()
    create_metadata(parquet_path)
    print("\nDone!")
