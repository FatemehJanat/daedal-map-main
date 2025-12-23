"""
Migration script: Add 'type' column to all geometry files.

Sets type='admin' for all existing records since they are all
administrative divisions (countries, states, counties).

Run from county-map folder:
    python scripts/add_type_column.py
"""

import pandas as pd
from pathlib import Path
import sys

# Paths
GEOMETRY_DIR = Path(__file__).parent.parent.parent / "county-map-data" / "geometry"

def add_type_to_parquet(filepath):
    """Add type='admin' column to a parquet file."""
    try:
        df = pd.read_parquet(filepath)

        # Skip if type column already exists
        if 'type' in df.columns:
            print(f"  SKIP (already has type): {filepath.name}")
            return False

        # Add type column - all existing data is administrative
        df['type'] = 'admin'

        # Reorder columns to put type after level/admin_level
        cols = df.columns.tolist()
        # Find the level column (might be 'level' or 'admin_level')
        level_col = 'admin_level' if 'admin_level' in cols else 'level'
        if level_col in cols:
            level_idx = cols.index(level_col)
            cols.remove('type')
            cols.insert(level_idx + 1, 'type')
            df = df[cols]

        # Save back
        df.to_parquet(filepath, index=False)
        print(f"  OK: {filepath.name}")
        return True
    except Exception as e:
        print(f"  ERROR: {filepath.name} - {e}")
        return False

def add_type_to_csv(filepath):
    """Add type='admin' column to global.csv."""
    try:
        df = pd.read_csv(filepath)

        # Skip if type column already exists
        if 'type' in df.columns:
            print(f"  SKIP (already has type): {filepath.name}")
            return False

        # Add type column
        df['type'] = 'admin'

        # Reorder columns to put type after admin_level
        cols = df.columns.tolist()
        if 'admin_level' in cols:
            level_idx = cols.index('admin_level')
            cols.remove('type')
            cols.insert(level_idx + 1, 'type')
            df = df[cols]

        # Save back
        df.to_csv(filepath, index=False)
        print(f"  OK: {filepath.name}")
        return True
    except Exception as e:
        print(f"  ERROR: {filepath.name} - {e}")
        return False

def main():
    if not GEOMETRY_DIR.exists():
        print(f"ERROR: Geometry directory not found: {GEOMETRY_DIR}")
        sys.exit(1)

    print(f"Geometry directory: {GEOMETRY_DIR}")
    print()

    # Process global.csv
    print("Processing global.csv...")
    global_csv = GEOMETRY_DIR / "global.csv"
    if global_csv.exists():
        add_type_to_csv(global_csv)
    else:
        print("  NOT FOUND: global.csv")
    print()

    # Process all parquet files
    parquet_files = list(GEOMETRY_DIR.glob("*.parquet"))
    print(f"Processing {len(parquet_files)} parquet files...")

    updated = 0
    skipped = 0
    errors = 0

    for filepath in sorted(parquet_files):
        result = add_type_to_parquet(filepath)
        if result:
            updated += 1
        elif result is False:
            skipped += 1
        else:
            errors += 1

    print()
    print(f"Done! Updated: {updated}, Skipped: {skipped}, Errors: {errors}")

if __name__ == "__main__":
    main()
