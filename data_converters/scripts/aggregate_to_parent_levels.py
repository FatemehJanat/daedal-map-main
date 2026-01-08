"""
Aggregate single-level data to parent admin levels.

This script adds aggregated parent rows (admin_1, admin_0) to sources that
only have detailed data (admin_2). Uses geometry parquet to determine
parent relationships.

Usage:
    # Dry run - preview changes
    python data_converters/scripts/aggregate_to_parent_levels.py --dry-run

    # Process specific source
    python data_converters/scripts/aggregate_to_parent_levels.py --source census_population

    # Process specific country
    python data_converters/scripts/aggregate_to_parent_levels.py --country USA

    # Process all single-level sources
    python data_converters/scripts/aggregate_to_parent_levels.py --all

    # Force re-aggregation (even if already multi-level)
    python data_converters/scripts/aggregate_to_parent_levels.py --source census_population --force
"""

import argparse
import pandas as pd
from pathlib import Path
import sys

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mapmover.settings import get_backup_path

# Sources that should NOT be aggregated (indices, point data, event-only)
SKIP_SOURCES = {
    'fema_nri',           # Composite risk index - internal weights
    'wildfire_risk',      # Risk index
    'noaa_storms',        # Event-based (aggregates are storm counts, already done)
    'usgs_earthquakes',   # Event-based
    'nrcan_earthquakes',  # Event-based
    'bom_cyclones',       # Event-based
    'volcanoes',          # Point data
}


def load_geometry_parent_lookup(iso3: str, backup_path: Path) -> dict:
    """
    Load geometry parquet and build loc_id -> parent_id lookup.

    Returns:
        dict: {loc_id: parent_id}
    """
    # Try country-specific geometry first, then GADM fallback
    geom_paths = [
        backup_path / 'countries' / iso3 / 'geometry.parquet',
        backup_path / 'geometry' / f'{iso3}.parquet',
    ]

    for geom_path in geom_paths:
        if geom_path.exists():
            df = pd.read_parquet(geom_path)
            if 'parent_id' in df.columns:
                return df.set_index('loc_id')['parent_id'].to_dict()
            elif 'parent_loc_id' in df.columns:
                return df.set_index('loc_id')['parent_loc_id'].to_dict()

    return {}


def derive_parent_from_loc_id(loc_id: str) -> str:
    """
    Derive parent loc_id by removing the last segment.

    Examples:
        USA-NC-001 -> USA-NC
        USA-NC -> USA
        USA -> None
    """
    if not loc_id or '-' not in loc_id:
        return None

    parts = loc_id.rsplit('-', 1)
    return parts[0] if len(parts) > 1 else None


def get_admin_level(loc_id: str) -> int:
    """Get admin level from loc_id based on dash count."""
    if not loc_id:
        return 0
    return loc_id.count('-')


def aggregate_source(source_path: Path, dry_run: bool = False, force: bool = False) -> dict:
    """
    Aggregate a single source to parent levels.

    Args:
        source_path: Path to source directory containing parquet files
        dry_run: If True, don't write changes
        force: If True, re-aggregate even if already multi-level

    Returns:
        dict with status info
    """
    source_id = source_path.name
    country = source_path.parent.name

    result = {
        'source': f'{country}/{source_id}',
        'status': 'unknown',
        'original_rows': 0,
        'new_rows': 0,
        'levels_before': {},
        'levels_after': {},
    }

    # Skip blacklisted sources
    if source_id in SKIP_SOURCES:
        result['status'] = 'skipped (not aggregatable)'
        return result

    # Find main parquet file
    parquets = [p for p in source_path.glob('*.parquet')
                if 'events' not in p.name.lower()]
    if not parquets:
        result['status'] = 'skipped (no parquet)'
        return result

    parquet_path = parquets[0]
    df = pd.read_parquet(parquet_path)

    if 'loc_id' not in df.columns:
        result['status'] = 'skipped (no loc_id)'
        return result

    result['original_rows'] = len(df)

    # Check current levels
    df['_admin_level'] = df['loc_id'].apply(get_admin_level)
    levels_before = df.groupby('_admin_level')['loc_id'].nunique().to_dict()
    result['levels_before'] = levels_before

    # Skip if already multi-level (unless forced)
    if len(levels_before) > 1 and not force:
        result['status'] = 'skipped (already multi-level)'
        df = df.drop(columns=['_admin_level'])
        return result

    # Get the deepest level present
    max_level = max(levels_before.keys())
    if max_level == 0:
        result['status'] = 'skipped (only country-level)'
        df = df.drop(columns=['_admin_level'])
        return result

    # Load geometry for parent lookup
    backup_path = Path(get_backup_path())
    parent_lookup = load_geometry_parent_lookup(country, backup_path)

    # Check if geometry lookup has matches for our data
    unique_locs = df['loc_id'].unique()
    matched_count = sum(1 for loc in unique_locs if loc in parent_lookup)

    # If no/few geometry matches, derive parents from loc_id structure
    if matched_count < len(unique_locs) * 0.5:  # Less than 50% match
        if parent_lookup:
            print(f"  Warning: Only {matched_count}/{len(unique_locs)} loc_ids match geometry, deriving from loc_id")
        else:
            print(f"  Warning: No geometry parent lookup for {country}, deriving from loc_id")
        parent_lookup = {loc: derive_parent_from_loc_id(loc) for loc in unique_locs}

    # Identify columns to aggregate
    # Exclude: loc_id, year, and any string/object columns
    exclude_cols = {'loc_id', 'year', '_admin_level'}
    numeric_cols = df.select_dtypes(include=['number']).columns
    agg_cols = [c for c in numeric_cols if c not in exclude_cols]

    if not agg_cols:
        result['status'] = 'skipped (no numeric columns)'
        df = df.drop(columns=['_admin_level'])
        return result

    has_year = 'year' in df.columns

    # Start with original data (deepest level only if force re-aggregating)
    if force:
        df = df[df['_admin_level'] == max_level].copy()

    all_levels = [df.drop(columns=['_admin_level'])]

    # Aggregate up through each level
    current_df = df.copy()
    for target_level in range(max_level - 1, -1, -1):
        # Add parent column
        current_df['_parent'] = current_df['loc_id'].map(parent_lookup)

        # Remove rows without parents (shouldn't happen for valid data)
        current_df = current_df.dropna(subset=['_parent'])

        if current_df.empty:
            break

        # Aggregate
        if has_year:
            group_cols = ['_parent', 'year']
        else:
            group_cols = ['_parent']

        agg_df = current_df.groupby(group_cols)[agg_cols].sum().reset_index()
        agg_df = agg_df.rename(columns={'_parent': 'loc_id'})

        # Update parent lookup for next iteration
        parent_lookup = {loc: derive_parent_from_loc_id(loc)
                        for loc in agg_df['loc_id'].unique()}

        all_levels.append(agg_df)
        current_df = agg_df.copy()
        current_df['_admin_level'] = target_level

        print(f"    Level {target_level}: {agg_df['loc_id'].nunique()} locations")

    # Combine all levels
    combined = pd.concat(all_levels, ignore_index=True)

    # Check new levels
    combined['_check_level'] = combined['loc_id'].apply(get_admin_level)
    levels_after = combined.groupby('_check_level')['loc_id'].nunique().to_dict()
    result['levels_after'] = levels_after
    combined = combined.drop(columns=['_check_level'])

    result['new_rows'] = len(combined) - result['original_rows']

    # Save
    if not dry_run:
        combined.to_parquet(parquet_path, index=False)
        result['status'] = 'aggregated'
    else:
        result['status'] = 'would aggregate (dry-run)'

    return result


def find_sources_to_aggregate(backup_path: Path, country_filter: str = None) -> list:
    """Find all source directories that might need aggregation."""
    sources = []
    countries_dir = backup_path / 'countries'

    for country_dir in sorted(countries_dir.iterdir()):
        if not country_dir.is_dir():
            continue

        if country_filter and country_dir.name != country_filter:
            continue

        for source_dir in sorted(country_dir.iterdir()):
            if source_dir.is_dir():
                sources.append(source_dir)

    return sources


def main():
    parser = argparse.ArgumentParser(description='Aggregate single-level data to parent levels')
    parser.add_argument('--source', help='Specific source_id to process')
    parser.add_argument('--country', help='Process all sources for a country (ISO3)')
    parser.add_argument('--all', action='store_true', help='Process all sources')
    parser.add_argument('--dry-run', action='store_true', help='Preview without saving')
    parser.add_argument('--force', action='store_true', help='Re-aggregate even if multi-level')

    args = parser.parse_args()

    if not (args.source or args.country or args.all):
        parser.print_help()
        print("\nError: Must specify --source, --country, or --all")
        sys.exit(1)

    backup_path = Path(get_backup_path())
    print(f"Backup path: {backup_path}")
    print(f"Dry run: {args.dry_run}")
    print(f"Force: {args.force}")
    print("=" * 60)

    # Find sources to process
    if args.source:
        # Find specific source
        sources = []
        for country_dir in (backup_path / 'countries').iterdir():
            source_path = country_dir / args.source
            if source_path.exists():
                sources.append(source_path)
        if not sources:
            print(f"Error: Source '{args.source}' not found")
            sys.exit(1)
    else:
        sources = find_sources_to_aggregate(backup_path, args.country)

    print(f"Found {len(sources)} source(s) to check\n")

    # Process each source
    results = []
    for source_path in sources:
        print(f"Processing {source_path.parent.name}/{source_path.name}...")
        result = aggregate_source(source_path, args.dry_run, args.force)
        results.append(result)

        if result['status'].startswith('skipped'):
            print(f"  {result['status']}")
        else:
            before = result['levels_before']
            after = result['levels_after']
            print(f"  Before: {before}")
            print(f"  After: {after}")
            print(f"  New rows: +{result['new_rows']}")
            print(f"  Status: {result['status']}")
        print()

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    aggregated = [r for r in results if 'aggregat' in r['status']]
    skipped = [r for r in results if r['status'].startswith('skipped')]

    print(f"Aggregated: {len(aggregated)}")
    for r in aggregated:
        print(f"  {r['source']}: +{r['new_rows']} rows")

    print(f"\nSkipped: {len(skipped)}")
    for r in skipped:
        print(f"  {r['source']}: {r['status']}")


if __name__ == '__main__':
    main()
