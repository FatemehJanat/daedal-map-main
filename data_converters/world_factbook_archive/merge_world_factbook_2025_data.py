"""
Merge scraped CIA 2025 data into existing parquet files.

This script:
1. Reads the scraped JSON data
2. Pivots it to match parquet structure (metrics as columns)
3. Merges with existing parquet files
4. Saves updated parquet files
"""

import pandas as pd
import json
import os

# Define which metrics go into which parquet file
UNIQUE_METRICS = {
    'airports', 'area_sq_km', 'broadband_subscriptions', 'gini_index',
    'industrial_production_growth', 'labor_force', 'median_age',
    'merchant_marine', 'foreign_reserves', 'net_migration_rate',
    'taxes_revenue_pct_gdp', 'telephones_fixed', 'telephones_mobile',
    'unemployment_rate', 'youth_unemployment'
}

OVERLAP_METRICS = {
    'birth_rate', 'child_underweight', 'co2_emissions', 'current_account_balance',
    'death_rate', 'education_expenditure', 'exports', 'external_debt',
    'fertility_rate', 'gdp_growth_rate', 'gdp_per_capita_ppp', 'gdp_ppp',
    'imports', 'infant_mortality', 'inflation_rate', 'life_expectancy',
    'maternal_mortality', 'obesity_rate', 'pop_growth_rate', 'population',
    'public_debt_pct_gdp'
}

def load_scraped_data(json_path: str) -> pd.DataFrame:
    """Load scraped JSON and convert to DataFrame."""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    df = pd.DataFrame(data)
    print(f"Loaded {len(df)} records from {json_path}")
    return df

def pivot_to_wide_format(df: pd.DataFrame, metrics: set) -> pd.DataFrame:
    """Pivot long-format data to wide format (metrics as columns)."""
    # Filter to only requested metrics
    df_filtered = df[df['metric'].isin(metrics)].copy()

    if len(df_filtered) == 0:
        return pd.DataFrame()

    # Pivot: rows are (loc_id, year, factbook_edition), columns are metrics
    pivoted = df_filtered.pivot_table(
        index=['loc_id', 'year', 'factbook_edition'],
        columns='metric',
        values='value',
        aggfunc='first'  # If duplicates, take first
    ).reset_index()

    # Flatten column names
    pivoted.columns.name = None

    return pivoted

def merge_with_existing(new_df: pd.DataFrame, parquet_path: str) -> pd.DataFrame:
    """Merge new data with existing parquet file."""
    if os.path.exists(parquet_path):
        existing = pd.read_parquet(parquet_path)
        print(f"Existing data: {len(existing)} rows")

        # Combine new and existing
        combined = pd.concat([existing, new_df], ignore_index=True)

        # For duplicates on (loc_id, year), prefer newest factbook_edition
        combined = combined.sort_values('factbook_edition', ascending=False)

        # Get all metric columns
        metric_cols = [c for c in combined.columns if c not in ['loc_id', 'year', 'factbook_edition']]

        # Aggregate: for each (loc_id, year), take first non-null value per metric
        agg_dict = {col: 'first' for col in metric_cols}
        agg_dict['factbook_edition'] = 'first'

        combined = combined.groupby(['loc_id', 'year'], as_index=False).agg(agg_dict)
        combined = combined.sort_values(['loc_id', 'year']).reset_index(drop=True)

        print(f"After merge: {len(combined)} rows")
        return combined
    else:
        print(f"No existing file at {parquet_path}")
        return new_df

def main():
    print("=" * 60)
    print("Merge CIA 2025 Data into Parquet Files")
    print("=" * 60)

    # Paths
    json_path = 'world_factbook_2025_scraped.json'
    unique_parquet = 'c:/Users/Bryan/Desktop/county-map-data/data/world_factbook/all_countries.parquet'
    overlap_parquet = 'c:/Users/Bryan/Desktop/county-map-data/data/world_factbook_overlap/all_countries.parquet'

    # Load scraped data
    df = load_scraped_data(json_path)

    # Show what metrics we have
    scraped_metrics = set(df['metric'].unique())
    print(f"\nScraped metrics: {sorted(scraped_metrics)}")

    # Split into unique and overlap
    unique_in_scraped = scraped_metrics & UNIQUE_METRICS
    overlap_in_scraped = scraped_metrics & OVERLAP_METRICS
    unmapped = scraped_metrics - UNIQUE_METRICS - OVERLAP_METRICS

    print(f"\nUnique metrics to add: {sorted(unique_in_scraped)}")
    print(f"Overlap metrics to add: {sorted(overlap_in_scraped)}")
    if unmapped:
        print(f"Unmapped metrics (skipping): {sorted(unmapped)}")

    # Process unique metrics
    print("\n" + "=" * 60)
    print("Processing UNIQUE metrics")
    print("=" * 60)

    unique_new = pivot_to_wide_format(df, UNIQUE_METRICS)
    if len(unique_new) > 0:
        print(f"New unique data: {len(unique_new)} rows")
        unique_merged = merge_with_existing(unique_new, unique_parquet)
        unique_merged.to_parquet(unique_parquet, index=False)
        print(f"Saved to {unique_parquet}")

        # Show sample
        print("\nSample (unique):")
        print(unique_merged[unique_merged['factbook_edition'] == 2025].head())

    # Process overlap metrics
    print("\n" + "=" * 60)
    print("Processing OVERLAP metrics")
    print("=" * 60)

    overlap_new = pivot_to_wide_format(df, OVERLAP_METRICS)
    if len(overlap_new) > 0:
        print(f"New overlap data: {len(overlap_new)} rows")
        overlap_merged = merge_with_existing(overlap_new, overlap_parquet)
        overlap_merged.to_parquet(overlap_parquet, index=False)
        print(f"Saved to {overlap_parquet}")

        # Show sample
        print("\nSample (overlap):")
        print(overlap_merged[overlap_merged['factbook_edition'] == 2025].head())

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)

if __name__ == '__main__':
    main()
