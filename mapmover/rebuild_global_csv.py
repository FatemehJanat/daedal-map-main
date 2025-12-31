"""
Rebuild global.csv from individual country parquet files.

This extracts admin_level=0 rows from each country parquet
to create a complete global.csv with all countries.

Usage:
    python rebuild_global_csv.py              # Rebuild global.csv
    python rebuild_global_csv.py --dry-run    # Preview without saving
"""

import os
import pandas as pd
from pathlib import Path

# Paths
GEOMETRY_PATH = Path(r"C:\Users\Bryan\Desktop\county-map-data\geometry")
GLOBAL_CSV = GEOMETRY_PATH / "global.csv"


def rebuild_global_csv(dry_run=False):
    """Extract admin_level=0 from all country parquets to build global.csv."""

    # Find all 3-letter ISO parquet files
    parquet_files = sorted([
        f for f in os.listdir(GEOMETRY_PATH)
        if f.endswith('.parquet')
        and len(f.replace('.parquet', '')) == 3
        and f[0].isupper()
    ])

    print(f"Found {len(parquet_files)} country parquet files")

    records = []
    missing_country_level = []
    errors = []

    for pf in parquet_files:
        iso3 = pf.replace('.parquet', '')
        parquet_path = GEOMETRY_PATH / pf

        try:
            df = pd.read_parquet(parquet_path)

            # Find admin_level=0 (country level)
            country_rows = df[df['admin_level'] == 0]

            if len(country_rows) == 0:
                missing_country_level.append(iso3)
                continue

            # Take the first country-level row
            row = country_rows.iloc[0]

            # Extract columns for global.csv
            record = {
                'loc_id': row.get('loc_id', iso3),
                'name': row.get('name', ''),
                'admin_level': 0,
                'parent_id': row.get('parent_id', 'WORLD'),
                'geometry': row.get('geometry', None),
                'centroid_lon': row.get('centroid_lon', None),
                'centroid_lat': row.get('centroid_lat', None),
                'has_polygon': row.get('has_polygon', False),
                'bbox_min_lon': row.get('bbox_min_lon', None),
                'bbox_min_lat': row.get('bbox_min_lat', None),
                'bbox_max_lon': row.get('bbox_max_lon', None),
                'bbox_max_lat': row.get('bbox_max_lat', None),
            }
            records.append(record)

        except Exception as e:
            errors.append((iso3, str(e)))

    print(f"Extracted {len(records)} country-level records")

    if missing_country_level:
        print(f"Warning: {len(missing_country_level)} files have no admin_level=0:")
        print(f"  {missing_country_level}")

    if errors:
        print(f"Errors reading {len(errors)} files:")
        for iso, err in errors[:5]:
            print(f"  {iso}: {err}")

    # Create DataFrame
    result_df = pd.DataFrame(records)
    result_df = result_df.sort_values('loc_id').reset_index(drop=True)

    # Compare with existing
    if GLOBAL_CSV.exists():
        old_df = pd.read_csv(GLOBAL_CSV)
        old_ids = set(old_df['loc_id'])
        new_ids = set(result_df['loc_id'])

        added = new_ids - old_ids
        removed = old_ids - new_ids

        print(f"\nComparison with existing global.csv:")
        print(f"  Old: {len(old_ids)} countries")
        print(f"  New: {len(new_ids)} countries")
        if added:
            print(f"  Added ({len(added)}): {sorted(added)}")
        if removed:
            print(f"  Removed ({len(removed)}): {sorted(removed)}")

    # Show sample
    print("\nSample records:")
    sample_cols = ['loc_id', 'name', 'centroid_lon', 'centroid_lat', 'has_polygon']
    available_cols = [c for c in sample_cols if c in result_df.columns]
    print(result_df[available_cols].head(10).to_string(index=False))

    if dry_run:
        print(f"\n[DRY RUN] Would save {len(result_df)} countries to {GLOBAL_CSV}")
    else:
        # Backup existing
        if GLOBAL_CSV.exists():
            backup_path = GLOBAL_CSV.with_suffix('.csv.bak2')
            os.rename(GLOBAL_CSV, backup_path)
            print(f"Backed up existing to {backup_path}")

        result_df.to_csv(GLOBAL_CSV, index=False)
        print(f"\nSaved {len(result_df)} countries to {GLOBAL_CSV}")

    return result_df


if __name__ == "__main__":
    import sys

    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv

    rebuild_global_csv(dry_run=dry_run)
