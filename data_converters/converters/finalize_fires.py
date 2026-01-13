"""
Finalize fire data by adding loc_id columns to progression files.

This script:
1. Finds years where both enriched fires AND progression files exist
2. Joins loc_id columns from enriched fires to progression via event_id
3. Saves updated progression files with location data

The 5 columns added to progression:
- loc_id: Unique location identifier for filtering
- parent_loc_id: Parent admin unit (state/region)
- sibling_level: Admin level where fire becomes a sibling
- iso3: Country code
- loc_confidence: Confidence score of location assignment
"""

import argparse
from pathlib import Path
import pandas as pd
import time


# Columns to join from enriched fires to progression
LOC_COLUMNS = ['loc_id', 'parent_loc_id', 'sibling_level', 'iso3', 'loc_confidence']


def find_available_years(enriched_dir: Path, progression_dir: Path) -> list:
    """
    Find years where both enriched and progression files exist.

    Returns list of (year, enriched_path, progression_path) tuples.
    """
    available = []

    # Find all enriched files
    enriched_files = {
        int(f.stem.split('_')[1]): f
        for f in enriched_dir.glob('fires_*_enriched.parquet')
    }

    # Find all progression files (fire_progression_YYYY.parquet)
    progression_files = {
        int(f.stem.split('_')[2]): f
        for f in progression_dir.glob('fire_progression_*.parquet')
    }

    # Find intersection
    common_years = set(enriched_files.keys()) & set(progression_files.keys())

    for year in sorted(common_years):
        available.append((
            year,
            enriched_files[year],
            progression_files[year]
        ))

    return available


def analyze_files(enriched_path: Path, progression_path: Path, year: int):
    """Analyze and compare enriched and progression files."""
    print(f"\n=== Year {year} ===")

    # Load files
    enriched_df = pd.read_parquet(enriched_path)
    progression_df = pd.read_parquet(progression_path)

    print(f"  Enriched fires:    {len(enriched_df):,} rows")
    print(f"  Progression:       {len(progression_df):,} rows")

    # Check unique event_ids
    enriched_events = set(enriched_df['event_id'].unique())
    progression_events = set(progression_df['event_id'].unique())

    print(f"  Unique fires (enriched):    {len(enriched_events):,}")
    print(f"  Unique fires (progression): {len(progression_events):,}")

    # Check overlap
    common = enriched_events & progression_events
    only_enriched = enriched_events - progression_events
    only_progression = progression_events - enriched_events

    print(f"  Common event_ids:           {len(common):,}")
    if only_enriched:
        print(f"  Only in enriched:           {len(only_enriched):,}")
    if only_progression:
        print(f"  Only in progression:        {len(only_progression):,}")

    # Check if progression already has loc columns
    has_loc = 'loc_id' in progression_df.columns
    print(f"  Progression has loc_id:     {has_loc}")

    # Check enriched has all required columns
    missing_cols = [c for c in LOC_COLUMNS if c not in enriched_df.columns]
    if missing_cols:
        print(f"  WARNING: Enriched missing:  {missing_cols}")

    return {
        'year': year,
        'enriched_rows': len(enriched_df),
        'progression_rows': len(progression_df),
        'common_events': len(common),
        'has_loc': has_loc,
        'can_process': len(common) > 0 and not missing_cols
    }


def add_loc_to_progression(
    enriched_path: Path,
    progression_path: Path,
    output_path: Path,
    year: int,
    force: bool = False
) -> bool:
    """
    Add loc_id columns to progression file via event_id join.

    Returns True if successful.
    """
    print(f"\n=== Processing year {year} ===")

    # Check if output already exists and has loc columns
    if output_path.exists() and not force:
        # Read just the schema to check columns
        import pyarrow.parquet as pq
        schema = pq.read_schema(output_path)
        if 'loc_id' in schema.names:
            print(f"  Output already has loc_id, skipping (use --force to reprocess)")
            return True

    start = time.time()

    # Load enriched (only need event_id + loc columns)
    print(f"  Loading enriched fires...", flush=True)
    enriched_df = pd.read_parquet(enriched_path, columns=['event_id'] + LOC_COLUMNS)

    # Deduplicate enriched by event_id (should already be unique, but just in case)
    enriched_df = enriched_df.drop_duplicates(subset=['event_id'])
    print(f"    {len(enriched_df):,} unique fires with loc data")

    # Load progression
    print(f"  Loading progression...", flush=True)
    progression_df = pd.read_parquet(progression_path)
    original_rows = len(progression_df)
    print(f"    {original_rows:,} daily snapshots")

    # Drop existing loc columns if present (for reprocessing)
    existing_loc_cols = [c for c in LOC_COLUMNS if c in progression_df.columns]
    if existing_loc_cols:
        print(f"  Dropping existing loc columns: {existing_loc_cols}")
        progression_df = progression_df.drop(columns=existing_loc_cols)

    # Join loc columns
    print(f"  Joining on event_id...", flush=True)
    result_df = progression_df.merge(
        enriched_df,
        on='event_id',
        how='left'
    )

    # Verify row count unchanged
    if len(result_df) != original_rows:
        print(f"  WARNING: Row count changed! {original_rows:,} -> {len(result_df):,}")
        return False

    # Check join success
    matched = result_df['loc_id'].notna().sum()
    unmatched = result_df['loc_id'].isna().sum()
    print(f"  Matched:   {matched:,} rows ({100*matched/len(result_df):.1f}%)")
    if unmatched > 0:
        print(f"  Unmatched: {unmatched:,} rows (no loc data)")

    # Save
    print(f"  Saving to {output_path.name}...", flush=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result_df.to_parquet(output_path, index=False, compression='snappy')

    elapsed = time.time() - start
    file_size = output_path.stat().st_size / (1024 * 1024)
    print(f"  Done in {elapsed:.1f}s ({file_size:.1f} MB)")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Add loc_id columns to fire progression files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze available files (dry run)
  python finalize_fires.py --analyze

  # Process all available years
  python finalize_fires.py --all

  # Process specific year
  python finalize_fires.py --year 2022

  # Force reprocess (overwrite existing)
  python finalize_fires.py --all --force
        """
    )

    parser.add_argument("--enriched-dir",
        default="C:/Users/Bryan/Desktop/county-map-data/global/wildfires/by_year_enriched",
        help="Directory with enriched fire files")
    parser.add_argument("--progression-dir",
        default="C:/Users/Bryan/Desktop/county-map-data/global/wildfires",
        help="Directory with progression files")
    parser.add_argument("--output-dir",
        help="Output directory (default: same as progression-dir)")
    parser.add_argument("--analyze", action='store_true',
        help="Analyze files without processing")
    parser.add_argument("--all", action='store_true',
        help="Process all available years")
    parser.add_argument("--year", type=int,
        help="Process specific year")
    parser.add_argument("--force", action='store_true',
        help="Reprocess even if output exists")

    args = parser.parse_args()

    enriched_dir = Path(args.enriched_dir)
    progression_dir = Path(args.progression_dir)
    output_dir = Path(args.output_dir) if args.output_dir else progression_dir

    # Find available years
    available = find_available_years(enriched_dir, progression_dir)

    if not available:
        print("No years found with both enriched and progression files!")
        print(f"  Enriched dir:    {enriched_dir}")
        print(f"  Progression dir: {progression_dir}")
        return

    print(f"Found {len(available)} years with both files: {[y[0] for y in available]}")

    if args.analyze:
        # Analyze mode - just report on files
        print("\n" + "="*60)
        print("ANALYSIS MODE")
        print("="*60)

        results = []
        for year, enriched_path, progression_path in available:
            result = analyze_files(enriched_path, progression_path, year)
            results.append(result)

        print("\n" + "="*60)
        print("SUMMARY")
        print("="*60)
        for r in results:
            status = "Ready" if r['can_process'] else "Issues"
            loc_status = "(has loc)" if r['has_loc'] else "(needs loc)"
            print(f"  {r['year']}: {r['progression_rows']:,} rows, "
                  f"{r['common_events']:,} fires matched - {status} {loc_status}")

    elif args.year:
        # Process specific year
        year_data = [(y, e, p) for y, e, p in available if y == args.year]
        if not year_data:
            print(f"Year {args.year} not found in available years!")
            return

        year, enriched_path, progression_path = year_data[0]
        output_path = output_dir / f"fire_progression_{year}.parquet"

        add_loc_to_progression(
            enriched_path, progression_path, output_path, year, args.force
        )

    elif args.all:
        # Process all years
        print(f"\nProcessing {len(available)} years...")
        print(f"Output: {output_dir}")

        total_start = time.time()
        success = 0

        for year, enriched_path, progression_path in available:
            output_path = output_dir / f"fire_progression_{year}.parquet"

            if add_loc_to_progression(
                enriched_path, progression_path, output_path, year, args.force
            ):
                success += 1

        total_elapsed = time.time() - total_start
        print(f"\n{'='*60}")
        print(f"Completed {success}/{len(available)} years in {total_elapsed:.1f}s")

    else:
        parser.print_help()
        print("\n" + "="*60)
        print("Available years:", [y[0] for y in available])
        print("Use --analyze to see details, --all to process")


if __name__ == '__main__':
    main()
