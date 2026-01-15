"""
Fix USA FIPS leading zeros in loc_id columns.

The correct format is USA-CA-6037 (no leading zeros), not USA-CA-06037.
This script strips leading zeros from the FIPS portion of USA loc_ids.

Files to fix (per LOC_ID_INCONSISTENCIES.md analysis):
- geometry/USA.parquet
- countries/USA/geometry.parquet
- countries/USA/census_population/USA.parquet
- countries/USA/census_demographics/USA.parquet
- countries/USA/fema_nri/USA.parquet
- countries/USA/fema_disasters/USA.parquet

Usage:
    python fix_usa_fips_leading_zeros.py          # Dry run (preview changes)
    python fix_usa_fips_leading_zeros.py --apply  # Apply changes
"""

import pandas as pd
from pathlib import Path
import re
import sys

DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data")

FILES_TO_FIX = [
    DATA_DIR / "geometry" / "USA.parquet",
    DATA_DIR / "countries" / "USA" / "geometry.parquet",
    DATA_DIR / "countries" / "USA" / "census_population" / "USA.parquet",
    DATA_DIR / "countries" / "USA" / "census_demographics" / "USA.parquet",
    DATA_DIR / "countries" / "USA" / "fema_nri" / "USA.parquet",
    DATA_DIR / "countries" / "USA" / "fema_disasters" / "USA.parquet",
]


def fix_loc_id(loc_id):
    """
    Fix a loc_id by stripping leading zeros from the FIPS portion.

    USA-CA-06037 -> USA-CA-6037
    USA-CA-6037 -> USA-CA-6037 (unchanged)
    USA-CA -> USA-CA (unchanged, no FIPS)
    USA -> USA (unchanged, country level)
    """
    if not isinstance(loc_id, str):
        return loc_id

    if not loc_id.startswith('USA-'):
        return loc_id

    parts = loc_id.split('-')
    if len(parts) != 3:
        # Not a county-level loc_id
        return loc_id

    # parts = ['USA', 'CA', '06037']
    country, state, fips = parts

    # Strip leading zeros from FIPS
    try:
        fips_int = int(fips)
        return f"{country}-{state}-{fips_int}"
    except ValueError:
        # Not a numeric FIPS (maybe a ZCTA like Z90210)
        return loc_id


def has_leading_zeros(loc_id):
    """Check if a loc_id has leading zeros in FIPS."""
    if not isinstance(loc_id, str):
        return False

    if not loc_id.startswith('USA-'):
        return False

    parts = loc_id.split('-')
    if len(parts) != 3:
        return False

    fips = parts[2]
    # Has leading zeros if starts with 0 and is numeric
    return fips.startswith('0') and fips.isdigit()


def process_file(filepath, apply=False):
    """Process a single parquet file."""
    if not filepath.exists():
        print(f"  SKIP: File not found: {filepath}")
        return 0

    print(f"\n  Processing: {filepath.relative_to(DATA_DIR)}")

    # Read parquet
    df = pd.read_parquet(filepath)

    if 'loc_id' not in df.columns:
        print(f"    No loc_id column found")
        return 0

    # Count records with leading zeros
    mask = df['loc_id'].apply(has_leading_zeros)
    count_with_zeros = mask.sum()

    if count_with_zeros == 0:
        print(f"    OK: No leading zeros found in {len(df)} records")
        return 0

    print(f"    Found {count_with_zeros} records with leading zeros (out of {len(df)})")

    # Show some examples
    examples = df[mask]['loc_id'].head(5).tolist()
    fixed_examples = [fix_loc_id(x) for x in examples]
    print(f"    Examples:")
    for orig, fixed in zip(examples, fixed_examples):
        print(f"      {orig} -> {fixed}")

    if apply:
        # Apply fix
        df['loc_id'] = df['loc_id'].apply(fix_loc_id)

        # Also fix parent_id if it exists (geometry files)
        if 'parent_id' in df.columns:
            df['parent_id'] = df['parent_id'].apply(fix_loc_id)
            print(f"    Also fixed parent_id column")

        # Save back
        df.to_parquet(filepath, index=False)
        print(f"    FIXED: Saved {len(df)} records")
    else:
        print(f"    DRY RUN: Would fix {count_with_zeros} records")

    return count_with_zeros


def main():
    apply = '--apply' in sys.argv

    print("=" * 60)
    print("USA FIPS Leading Zeros Fix")
    print("=" * 60)

    if apply:
        print("\nMode: APPLY (changes will be saved)")
    else:
        print("\nMode: DRY RUN (preview only, use --apply to save)")

    total_fixed = 0

    for filepath in FILES_TO_FIX:
        count = process_file(filepath, apply=apply)
        total_fixed += count

    print("\n" + "=" * 60)
    if apply:
        print(f"COMPLETE: Fixed {total_fixed} total records with leading zeros")
    else:
        print(f"DRY RUN COMPLETE: Would fix {total_fixed} total records")
        print("\nRun with --apply to save changes:")
        print("  python fix_usa_fips_leading_zeros.py --apply")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
