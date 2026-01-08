"""
Remove redundant metadata columns from data parquets.

The data format should be: loc_id, year, [numeric metrics only]

Redundant columns to remove:
- state, STATE, state_abbr, STATEABBRV, STATEFIPS - derivable from loc_id
- county, COUNTY, county_name, COUNTYFIPS - derivable from loc_id
- country, location, region - derivable from loc_id
- STCOFIPS, GEOID, fips - redundant with loc_id
- name - stored in geometry, not data

Usage:
    # Dry run - preview changes
    python data_converters/scripts/cleanup_redundant_columns.py --dry-run

    # Process specific source
    python data_converters/scripts/cleanup_redundant_columns.py --source epa_aqs

    # Process all sources
    python data_converters/scripts/cleanup_redundant_columns.py --all
"""

import argparse
import pandas as pd
from pathlib import Path
import sys

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mapmover.settings import get_backup_path

# Columns that should be removed (case-insensitive matching)
REDUNDANT_COLUMNS = {
    # State identifiers
    'state', 'state_abbr', 'stateabbrv', 'statefips', 'state_fips',
    # County identifiers
    'county', 'county_name', 'countyfips', 'county_fips',
    # Combined FIPS
    'stcofips', 'geoid', 'fips',
    # Location names (should be in geometry)
    'name', 'location', 'region', 'country',
    # NRI-specific redundant columns
    'nri_version',
}

# Event-based sources - these have different schema requirements
EVENT_SOURCES = {
    'hurricanes', 'tsunamis', 'volcanoes', 'wildfires',
    'usgs_earthquakes', 'nrcan_earthquakes', 'noaa_storms',
    'bom_cyclones',
}


def cleanup_source(source_path: Path, dry_run: bool = False) -> dict:
    """
    Remove redundant columns from a source's parquet file.

    Args:
        source_path: Path to source directory
        dry_run: If True, don't write changes

    Returns:
        dict with cleanup results
    """
    source_id = source_path.name
    country = source_path.parent.name

    result = {
        'source': f'{country}/{source_id}',
        'status': 'unknown',
        'removed_columns': [],
        'kept_columns': [],
    }

    # Skip event-based sources
    if source_id in EVENT_SOURCES:
        result['status'] = 'skipped (event source)'
        return result

    # Find main parquet file
    parquets = [p for p in source_path.glob('*.parquet')
                if 'events' not in p.name.lower()]
    if not parquets:
        result['status'] = 'skipped (no parquet)'
        return result

    parquet_path = parquets[0]
    df = pd.read_parquet(parquet_path)

    original_cols = list(df.columns)

    # Find columns to remove (case-insensitive)
    cols_to_remove = []
    for col in df.columns:
        if col.lower() in REDUNDANT_COLUMNS:
            cols_to_remove.append(col)

    if not cols_to_remove:
        result['status'] = 'clean (no redundant columns)'
        result['kept_columns'] = original_cols
        return result

    # Remove columns
    df_clean = df.drop(columns=cols_to_remove)

    result['removed_columns'] = cols_to_remove
    result['kept_columns'] = list(df_clean.columns)

    # Save
    if not dry_run:
        df_clean.to_parquet(parquet_path, index=False)
        result['status'] = 'cleaned'
    else:
        result['status'] = 'would clean (dry-run)'

    return result


def find_all_sources(backup_path: Path) -> list:
    """Find all source directories."""
    sources = []
    countries_dir = backup_path / 'countries'

    for country_dir in sorted(countries_dir.iterdir()):
        if not country_dir.is_dir():
            continue

        for source_dir in sorted(country_dir.iterdir()):
            if source_dir.is_dir():
                sources.append(source_dir)

    return sources


def main():
    parser = argparse.ArgumentParser(description='Remove redundant metadata columns')
    parser.add_argument('--source', help='Specific source_id to process')
    parser.add_argument('--all', action='store_true', help='Process all sources')
    parser.add_argument('--dry-run', action='store_true', help='Preview without saving')

    args = parser.parse_args()

    if not (args.source or args.all):
        parser.print_help()
        print("\nError: Must specify --source or --all")
        sys.exit(1)

    backup_path = Path(get_backup_path())
    print(f"Backup path: {backup_path}")
    print(f"Dry run: {args.dry_run}")
    print("=" * 60)

    # Find sources
    if args.source:
        sources = []
        for country_dir in (backup_path / 'countries').iterdir():
            source_path = country_dir / args.source
            if source_path.exists():
                sources.append(source_path)
        if not sources:
            print(f"Error: Source '{args.source}' not found")
            sys.exit(1)
    else:
        sources = find_all_sources(backup_path)

    print(f"Found {len(sources)} source(s) to check\n")

    # Process
    results = []
    for source_path in sources:
        print(f"Processing {source_path.parent.name}/{source_path.name}...")
        result = cleanup_source(source_path, args.dry_run)
        results.append(result)

        if result['removed_columns']:
            print(f"  Removed: {result['removed_columns']}")
            print(f"  Kept: {result['kept_columns']}")
        print(f"  Status: {result['status']}\n")

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    cleaned = [r for r in results if 'clean' in r['status'] and r['removed_columns']]
    skipped = [r for r in results if r['status'].startswith('skipped')]
    already_clean = [r for r in results if r['status'] == 'clean (no redundant columns)']

    print(f"Cleaned: {len(cleaned)}")
    for r in cleaned:
        print(f"  {r['source']}: removed {r['removed_columns']}")

    print(f"\nAlready clean: {len(already_clean)}")
    print(f"Skipped (event sources): {len([r for r in skipped if 'event' in r['status']])}")


if __name__ == '__main__':
    main()
