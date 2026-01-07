"""
Aggregate Eurostat NUTS-3 data to parent levels (NUTS-2, NUTS-1, Country).

NUTS Hierarchy (by code length):
- NUTS-3: 5 chars (e.g., DE111, UKJ28) - most detailed
- NUTS-2: 4 chars (e.g., DE11, UKJ2) - truncate 1 char
- NUTS-1: 3 chars (e.g., DE1, UKJ) - truncate 2 chars
- Country: 2 chars (e.g., DE, UK) - but we use ISO3 code (DEU, GBR)

loc_id format: {ISO3}-{NUTS_CODE}
Example hierarchy: GBR-UKJ28 -> GBR-UKJ2 -> GBR-UKJ -> GBR

Aggregation rules:
- SUM columns: births, deaths, gdp_mio_eur, natural_growth, net_migration, pop_change, population
- RECALCULATE per-capita columns from totals after aggregation

Usage:
    python aggregate_eurostat_to_country.py
    python aggregate_eurostat_to_country.py --country DEU  # Single country
    python aggregate_eurostat_to_country.py --dry-run      # Preview only
"""

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
import argparse

# Configuration
COUNTRIES_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries")

# Columns that should be summed (counts/totals)
SUM_COLUMNS = [
    'births', 'deaths', 'gdp_mio_eur', 'natural_growth',
    'net_migration', 'pop_change', 'population'
]

# Per-capita columns that need recalculation after aggregation
PER_CAPITA_COLUMNS = {
    'gdp_per_capita_eur': ('gdp_mio_eur', 'population', 1_000_000),  # GDP in millions, need to convert
    'gdp_per_capita_pps': ('gdp_mio_eur', 'population', 1_000_000),  # Approximate - use same ratio
}


def derive_parent_loc_id(loc_id: str, target_nuts_level: int) -> str:
    """
    Derive parent loc_id by truncating NUTS code.

    Args:
        loc_id: Full loc_id (e.g., 'DEU-DE111')
        target_nuts_level: 0=country, 1=NUTS-1, 2=NUTS-2

    Returns:
        Parent loc_id (e.g., 'DEU-DE11' for NUTS-2, 'DEU' for country)
    """
    parts = loc_id.split('-')
    iso3 = parts[0]
    nuts_code = parts[1] if len(parts) > 1 else ''

    if target_nuts_level == 0:
        # Country level - just ISO3
        return iso3
    elif target_nuts_level == 1:
        # NUTS-1: truncate to 3 chars
        return f"{iso3}-{nuts_code[:3]}"
    elif target_nuts_level == 2:
        # NUTS-2: truncate to 4 chars
        return f"{iso3}-{nuts_code[:4]}"
    else:
        return loc_id


def get_nuts_level(loc_id: str) -> int:
    """
    Determine NUTS level from loc_id.

    Returns:
        0 = country (no dash or 2-char NUTS)
        1 = NUTS-1 (3-char NUTS code)
        2 = NUTS-2 (4-char NUTS code)
        3 = NUTS-3 (5-char NUTS code)
    """
    if '-' not in loc_id:
        return 0

    nuts_code = loc_id.split('-')[1]
    code_len = len(nuts_code)

    if code_len <= 2:
        return 0
    elif code_len == 3:
        return 1
    elif code_len == 4:
        return 2
    else:
        return 3


def aggregate_to_level(df: pd.DataFrame, target_level: int) -> pd.DataFrame:
    """
    Aggregate data to a target NUTS level.

    Args:
        df: DataFrame with loc_id, year, and metric columns
        target_level: Target NUTS level (0, 1, or 2)

    Returns:
        Aggregated DataFrame
    """
    # Derive parent loc_id for each row
    df = df.copy()
    df['parent_loc_id'] = df['loc_id'].apply(lambda x: derive_parent_loc_id(x, target_level))

    # Identify columns to sum (only those that exist in the dataframe)
    sum_cols = [c for c in SUM_COLUMNS if c in df.columns]

    # Group and sum
    agg_df = df.groupby(['parent_loc_id', 'year'])[sum_cols].sum().reset_index()
    agg_df = agg_df.rename(columns={'parent_loc_id': 'loc_id'})

    # Recalculate per-capita columns
    for col, (numerator, denominator, multiplier) in PER_CAPITA_COLUMNS.items():
        if col in df.columns and numerator in agg_df.columns and denominator in agg_df.columns:
            # GDP per capita = (GDP in millions * 1M) / population
            agg_df[col] = (agg_df[numerator] * multiplier) / agg_df[denominator]
            # Handle division by zero
            agg_df[col] = agg_df[col].replace([float('inf'), float('-inf')], None)

    return agg_df


def process_country(iso3: str, dry_run: bool = False) -> dict:
    """
    Process a single country's Eurostat data.

    Returns dict with stats about the aggregation.
    """
    parquet_path = COUNTRIES_DIR / iso3 / 'eurostat' / f'{iso3}.parquet'

    if not parquet_path.exists():
        return {'status': 'skipped', 'reason': 'file not found'}

    # Load data
    df = pd.read_parquet(parquet_path)
    original_rows = len(df)
    original_locs = df['loc_id'].nunique()

    # Check if already has multiple levels
    levels = df['loc_id'].apply(get_nuts_level).unique()
    if len(levels) > 1:
        return {
            'status': 'skipped',
            'reason': f'already has multiple levels: {sorted(levels)}',
            'locations': original_locs
        }

    # Aggregate to each parent level
    all_levels = [df.copy()]  # Keep original NUTS-3 data

    # NUTS-2 aggregation
    nuts2 = aggregate_to_level(df, 2)
    nuts2_locs = nuts2['loc_id'].nunique()
    all_levels.append(nuts2)

    # NUTS-1 aggregation
    nuts1 = aggregate_to_level(df, 1)
    nuts1_locs = nuts1['loc_id'].nunique()
    all_levels.append(nuts1)

    # Country level aggregation
    country = aggregate_to_level(df, 0)
    country_locs = country['loc_id'].nunique()
    all_levels.append(country)

    # Combine all levels
    combined = pd.concat(all_levels, ignore_index=True)
    combined = combined.sort_values(['loc_id', 'year']).reset_index(drop=True)

    final_rows = len(combined)
    final_locs = combined['loc_id'].nunique()

    stats = {
        'status': 'success',
        'nuts3': original_locs,
        'nuts2': nuts2_locs,
        'nuts1': nuts1_locs,
        'country': country_locs,
        'total_locations': final_locs,
        'original_rows': original_rows,
        'final_rows': final_rows,
    }

    if not dry_run:
        # Save updated parquet
        table = pa.Table.from_pandas(combined, preserve_index=False)
        pq.write_table(table, parquet_path, compression='snappy')
        stats['saved'] = True
    else:
        stats['saved'] = False

    return stats


def main():
    parser = argparse.ArgumentParser(description='Aggregate Eurostat NUTS-3 data to parent levels')
    parser.add_argument('--country', type=str, help='Process single country (ISO3 code)')
    parser.add_argument('--dry-run', action='store_true', help='Preview without saving')
    args = parser.parse_args()

    print("=" * 70)
    print("Eurostat NUTS Aggregation")
    print("=" * 70)

    if args.dry_run:
        print("DRY RUN - No files will be modified\n")

    # Find all Eurostat countries
    eurostat_files = list(COUNTRIES_DIR.glob("*/eurostat/*.parquet"))
    countries = sorted(set(p.parent.parent.name for p in eurostat_files))

    if args.country:
        if args.country not in countries:
            print(f"Error: {args.country} not found in Eurostat data")
            return
        countries = [args.country]

    print(f"Processing {len(countries)} countries...\n")

    # Process each country
    results = {}
    for iso3 in countries:
        stats = process_country(iso3, dry_run=args.dry_run)
        results[iso3] = stats

        if stats['status'] == 'success':
            print(f"{iso3}: NUTS-3={stats['nuts3']} -> NUTS-2={stats['nuts2']} -> "
                  f"NUTS-1={stats['nuts1']} -> Country={stats['country']} "
                  f"| Total: {stats['total_locations']} locations, {stats['final_rows']} rows")
        else:
            print(f"{iso3}: {stats['status']} - {stats.get('reason', '')}")

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)

    success = [k for k, v in results.items() if v['status'] == 'success']
    skipped = [k for k, v in results.items() if v['status'] == 'skipped']

    print(f"Processed: {len(success)} countries")
    print(f"Skipped: {len(skipped)} countries")

    if success:
        total_locs = sum(results[k]['total_locations'] for k in success)
        total_rows = sum(results[k]['final_rows'] for k in success)
        print(f"Total locations: {total_locs}")
        print(f"Total rows: {total_rows}")

    if args.dry_run:
        print("\nTo apply changes, run without --dry-run")


if __name__ == "__main__":
    main()
