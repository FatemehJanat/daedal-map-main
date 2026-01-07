"""
Parquet column extraction and combination utilities.

Usage examples:
    # Extract specific columns to new file
    python parquet_tools.py extract source.parquet output.parquet col1 col2 col3

    # Merge columns from source into target (matching on loc_id, year)
    python parquet_tools.py merge target.parquet source.parquet col1 col2

    # List columns in a parquet file
    python parquet_tools.py info file.parquet
"""

import pandas as pd
import sys
from pathlib import Path


def info(parquet_path: str):
    """Show info about a parquet file."""
    df = pd.read_parquet(parquet_path)
    print(f"File: {parquet_path}")
    print(f"Shape: {df.shape[0]} rows x {df.shape[1]} columns")
    print(f"\nColumns:")
    for col in df.columns:
        non_null = df[col].notna().sum()
        dtype = df[col].dtype
        print(f"  {col}: {non_null} values ({dtype})")

    if 'loc_id' in df.columns:
        print(f"\nCountries: {df['loc_id'].nunique()}")
    if 'year' in df.columns:
        years = sorted(df['year'].dropna().unique())
        print(f"Years: {min(years)}-{max(years)} ({len(years)} years)")


def extract(source_path: str, output_path: str, columns: list, key_cols: list = None):
    """Extract specific columns from source to new file."""
    if key_cols is None:
        key_cols = ['loc_id', 'year']

    df = pd.read_parquet(source_path)

    # Always include key columns
    cols_to_extract = []
    for k in key_cols:
        if k in df.columns and k not in cols_to_extract:
            cols_to_extract.append(k)

    # Add requested columns
    for col in columns:
        if col in df.columns and col not in cols_to_extract:
            cols_to_extract.append(col)
        elif col not in df.columns:
            print(f"Warning: Column '{col}' not found in source")

    result = df[cols_to_extract].copy()

    # Drop rows where all metric columns are null
    metric_cols = [c for c in cols_to_extract if c not in key_cols]
    if metric_cols:
        result = result.dropna(subset=metric_cols, how='all')

    result.to_parquet(output_path, index=False)
    print(f"Extracted {len(result)} rows with columns {cols_to_extract}")
    print(f"Saved to: {output_path}")
    return result


def merge(target_path: str, source_path: str, columns: list, output_path: str = None, key_cols: list = None):
    """Merge columns from source into target, matching on key columns."""
    if key_cols is None:
        key_cols = ['loc_id', 'year']
    if output_path is None:
        output_path = target_path

    target = pd.read_parquet(target_path)
    source = pd.read_parquet(source_path)

    # Get columns to merge
    cols_to_merge = [c for c in columns if c in source.columns]
    if not cols_to_merge:
        print("Error: No valid columns to merge")
        return None

    # Extract key + requested columns from source
    source_subset = source[key_cols + cols_to_merge].copy()

    # Merge into target
    result = target.merge(source_subset, on=key_cols, how='left', suffixes=('', '_new'))

    # Handle column conflicts (prefer new values where they exist)
    for col in cols_to_merge:
        if f'{col}_new' in result.columns:
            result[col] = result[f'{col}_new'].combine_first(result[col])
            result = result.drop(columns=[f'{col}_new'])

    result.to_parquet(output_path, index=False)
    print(f"Merged {len(cols_to_merge)} columns: {cols_to_merge}")
    print(f"Result: {len(result)} rows")
    print(f"Saved to: {output_path}")
    return result


def create_static_data(source_path: str, output_path: str, static_columns: list):
    """
    Create a static data file (one row per location, no year dimension).
    Useful for things like area_sq_km that don't change over time.
    """
    df = pd.read_parquet(source_path)

    # Get the columns we want
    cols = ['loc_id'] + [c for c in static_columns if c in df.columns]

    # Take first non-null value per loc_id
    result = df[cols].groupby('loc_id', as_index=False).first()

    # Drop rows with all nulls
    metric_cols = [c for c in cols if c != 'loc_id']
    result = result.dropna(subset=metric_cols, how='all')

    result.to_parquet(output_path, index=False)
    print(f"Created static data file with {len(result)} locations")
    print(f"Columns: {list(result.columns)}")
    print(f"Saved to: {output_path}")
    return result


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'info' and len(sys.argv) >= 3:
        info(sys.argv[2])

    elif cmd == 'extract' and len(sys.argv) >= 5:
        extract(sys.argv[2], sys.argv[3], sys.argv[4:])

    elif cmd == 'merge' and len(sys.argv) >= 5:
        merge(sys.argv[2], sys.argv[3], sys.argv[4:])

    elif cmd == 'static' and len(sys.argv) >= 5:
        create_static_data(sys.argv[2], sys.argv[3], sys.argv[4:])

    else:
        print(__doc__)
        print("\nCommands:")
        print("  info <file>                      - Show file info")
        print("  extract <src> <out> <cols...>    - Extract columns to new file")
        print("  merge <target> <src> <cols...>   - Merge columns into target")
        print("  static <src> <out> <cols...>     - Create static (no year) file")
