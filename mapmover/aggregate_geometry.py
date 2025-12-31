"""
Aggregate Geometry - Creates parent boundaries by dissolving child polygons.

GADM data only has geometry at the deepest admin level for most countries.
This script aggregates (unions/dissolves) child geometries to create parent boundaries.

Example: For USA, level 2 (counties) have geometry but level 1 (states) don't.
We dissolve all counties in Alabama to create Alabama's state boundary.
"""

import pandas as pd
import json
from pathlib import Path
from shapely import wkt
from shapely.ops import unary_union
from shapely.validation import make_valid
from shapely.geometry import mapping
import warnings

# Suppress shapely warnings about invalid geometries
warnings.filterwarnings('ignore', category=RuntimeWarning)

GEOMETRY_PATH = Path(r"C:\Users\Bryan\Desktop\county-map-data\geometry")


def get_simplify_tolerance(admin_level):
    """Get simplification tolerance based on admin level (per GEOMETRY.md)."""
    if admin_level == 0:
        return 0.01      # Countries: ~1 km precision
    elif admin_level <= 2:
        return 0.001     # States/Counties: ~100 m precision
    else:
        return 0.0001    # Cities/Districts: ~10 m precision


def aggregate_country(iso3: str, dry_run: bool = False) -> dict:
    """
    Aggregate geometry for a single country.

    Returns dict with stats about what was done.
    """
    parquet_path = GEOMETRY_PATH / f"{iso3}.parquet"

    if not parquet_path.exists():
        return {"status": "skip", "reason": "no parquet file"}

    try:
        df = pd.read_parquet(parquet_path)
    except Exception as e:
        return {"status": "error", "reason": str(e)}

    if len(df) == 0:
        return {"status": "skip", "reason": "empty parquet"}

    # Find which levels have geometry and which don't
    level_stats = {}
    for level in df['admin_level'].unique():
        level_df = df[df['admin_level'] == level]
        with_geom = level_df['geometry'].notna().sum()
        total = len(level_df)
        level_stats[int(level)] = {
            'total': total,
            'with_geometry': with_geom,
            'missing': total - with_geom
        }

    # Sort levels
    sorted_levels = sorted(level_stats.keys())

    # Find levels that need aggregation (have rows but no geometry)
    levels_needing_agg = []
    for level in sorted_levels:
        stats = level_stats[level]
        if stats['total'] > 0 and stats['with_geometry'] == 0:
            levels_needing_agg.append(level)

    if not levels_needing_agg:
        return {
            "status": "ok",
            "reason": "all levels have geometry",
            "level_stats": level_stats
        }

    # Find the first level that has geometry (our source for aggregation)
    source_level = None
    for level in sorted_levels:
        if level_stats[level]['with_geometry'] > 0:
            source_level = level
            break

    if source_level is None:
        return {
            "status": "error",
            "reason": "no level has geometry to aggregate from",
            "level_stats": level_stats
        }

    # Work backwards from source level, aggregating to parent levels
    aggregated_count = 0

    # Create a working copy of the dataframe
    df_work = df.copy()

    # For each level that needs aggregation (starting from deepest)
    for target_level in sorted(levels_needing_agg, reverse=True):
        # Find the level with geometry that's deeper than target
        child_level = None
        for level in sorted_levels:
            if level > target_level and level_stats[level]['with_geometry'] > 0:
                child_level = level
                break
            # Or use already-aggregated level
            if level > target_level and level in levels_needing_agg:
                # Check if we already aggregated this level
                agg_check = df_work[(df_work['admin_level'] == level) & df_work['geometry'].notna()]
                if len(agg_check) > 0:
                    child_level = level
                    break

        if child_level is None:
            continue

        # Get all rows at target level that need geometry
        target_rows = df_work[(df_work['admin_level'] == target_level) & df_work['geometry'].isna()]

        for idx, target_row in target_rows.iterrows():
            target_loc_id = target_row['loc_id']

            # Find all children whose parent_id matches
            children = df_work[
                (df_work['parent_id'] == target_loc_id) &
                df_work['geometry'].notna()
            ]

            if len(children) == 0:
                # Try to find grandchildren if direct children don't have geometry
                continue

            # Parse and union all child geometries
            child_geoms = []
            for _, child_row in children.iterrows():
                geom_str = child_row['geometry']
                if pd.isna(geom_str) or not geom_str:
                    continue
                try:
                    # Parse geometry (stored as GeoJSON string)
                    geom_data = json.loads(geom_str) if isinstance(geom_str, str) else geom_str

                    # Convert GeoJSON to Shapely
                    from shapely.geometry import shape
                    geom = shape(geom_data)

                    # Validate geometry
                    if not geom.is_valid:
                        geom = make_valid(geom)

                    child_geoms.append(geom)
                except Exception as e:
                    continue

            if not child_geoms:
                continue

            # Union all child geometries
            try:
                if len(child_geoms) == 1:
                    merged = child_geoms[0]
                else:
                    merged = unary_union(child_geoms)

                # Validate result
                if not merged.is_valid:
                    merged = make_valid(merged)

                # Simplify based on target level (per GEOMETRY.md)
                tolerance = get_simplify_tolerance(target_level)
                merged = merged.simplify(tolerance, preserve_topology=True)

                # Convert back to GeoJSON string
                geom_json = json.dumps(mapping(merged))

                # Calculate centroid from merged geometry
                centroid = merged.centroid
                centroid_lon = centroid.x
                centroid_lat = centroid.y

                # Update the row with geometry AND centroid
                df_work.at[idx, 'geometry'] = geom_json
                df_work.at[idx, 'centroid_lon'] = centroid_lon
                df_work.at[idx, 'centroid_lat'] = centroid_lat
                aggregated_count += 1

            except Exception as e:
                continue

    if aggregated_count == 0:
        return {
            "status": "ok",
            "reason": "no aggregation possible",
            "levels_needing_agg": levels_needing_agg,
            "level_stats": level_stats
        }

    # Save updated parquet
    if not dry_run:
        df_work.to_parquet(parquet_path, index=False)

    return {
        "status": "aggregated",
        "count": aggregated_count,
        "levels_needing_agg": levels_needing_agg,
        "source_level": source_level,
        "dry_run": dry_run
    }


def backfill_centroids(iso3: str, dry_run: bool = False) -> dict:
    """
    Backfill missing centroids for rows that have geometry but no centroid.

    This fixes data from previous aggregation runs that didn't calculate centroids.
    """
    parquet_path = GEOMETRY_PATH / f"{iso3}.parquet"

    if not parquet_path.exists():
        return {"status": "skip", "reason": "no parquet file"}

    try:
        df = pd.read_parquet(parquet_path)
    except Exception as e:
        return {"status": "error", "reason": str(e)}

    if len(df) == 0:
        return {"status": "skip", "reason": "empty parquet"}

    # Find rows with geometry but missing centroid
    needs_centroid = df[
        df['geometry'].notna() &
        (df['centroid_lon'].isna() | df['centroid_lat'].isna())
    ]

    if len(needs_centroid) == 0:
        return {"status": "ok", "reason": "all centroids present"}

    from shapely.geometry import shape

    df_work = df.copy()
    fixed_count = 0

    for idx, row in needs_centroid.iterrows():
        geom_str = row['geometry']
        if pd.isna(geom_str) or not geom_str:
            continue

        try:
            # Parse geometry
            geom_data = json.loads(geom_str) if isinstance(geom_str, str) else geom_str
            geom = shape(geom_data)

            # Validate if needed
            if not geom.is_valid:
                geom = make_valid(geom)

            # Calculate centroid
            centroid = geom.centroid
            df_work.at[idx, 'centroid_lon'] = centroid.x
            df_work.at[idx, 'centroid_lat'] = centroid.y
            fixed_count += 1

        except Exception as e:
            continue

    if fixed_count == 0:
        return {"status": "ok", "reason": "no centroids to fix"}

    # Save updated parquet
    if not dry_run:
        df_work.to_parquet(parquet_path, index=False)

    return {
        "status": "fixed",
        "count": fixed_count,
        "dry_run": dry_run
    }


def backfill_all_centroids(dry_run: bool = False):
    """Backfill centroids for all countries."""

    parquet_files = list(GEOMETRY_PATH.glob("*.parquet"))

    results = {
        "fixed": [],
        "ok": [],
        "skipped": [],
        "errors": []
    }

    for i, parquet_file in enumerate(parquet_files):
        iso3 = parquet_file.stem

        # Skip non-country files
        if len(iso3) != 3 or not iso3.isupper():
            continue

        result = backfill_centroids(iso3, dry_run=dry_run)

        if result["status"] == "fixed":
            results["fixed"].append((iso3, result["count"]))
            print(f"[FIX] {iso3}: Fixed {result['count']} centroids")
        elif result["status"] == "ok":
            results["ok"].append(iso3)
        elif result["status"] == "skip":
            results["skipped"].append((iso3, result["reason"]))
        else:
            results["errors"].append((iso3, result.get("reason", "unknown")))
            print(f"[ERR] {iso3}: {result.get('reason', 'unknown')}")

        if (i + 1) % 50 == 0:
            print(f"Processed {i + 1}/{len(parquet_files)} countries...")

    # Print summary
    print("\n=== Centroid Backfill Summary ===")
    print(f"Countries with fixed centroids: {len(results['fixed'])}")
    total_fixed = sum(count for _, count in results['fixed'])
    print(f"Total centroids fixed: {total_fixed}")
    print(f"Countries already complete: {len(results['ok'])}")
    print(f"Skipped: {len(results['skipped'])}")
    print(f"Errors: {len(results['errors'])}")

    if dry_run:
        print("\n[DRY RUN - no files were modified]")

    return results


def aggregate_all(dry_run: bool = False):
    """Aggregate geometry for all countries."""

    parquet_files = list(GEOMETRY_PATH.glob("*.parquet"))

    results = {
        "aggregated": [],
        "ok": [],
        "skipped": [],
        "errors": []
    }

    for i, parquet_file in enumerate(parquet_files):
        iso3 = parquet_file.stem

        # Skip non-country files
        if len(iso3) != 3 or not iso3.isupper():
            continue

        result = aggregate_country(iso3, dry_run=dry_run)

        if result["status"] == "aggregated":
            results["aggregated"].append((iso3, result["count"]))
            print(f"[AGG] {iso3}: Created {result['count']} parent geometries")
        elif result["status"] == "ok":
            results["ok"].append(iso3)
        elif result["status"] == "skip":
            results["skipped"].append((iso3, result["reason"]))
        else:
            results["errors"].append((iso3, result.get("reason", "unknown")))
            print(f"[ERR] {iso3}: {result.get('reason', 'unknown')}")

        if (i + 1) % 50 == 0:
            print(f"Processed {i + 1}/{len(parquet_files)} countries...")

    # Print summary
    print("\n=== Aggregation Summary ===")
    print(f"Countries with new geometry: {len(results['aggregated'])}")
    total_agg = sum(count for _, count in results['aggregated'])
    print(f"Total parent geometries created: {total_agg}")
    print(f"Countries already complete: {len(results['ok'])}")
    print(f"Skipped: {len(results['skipped'])}")
    print(f"Errors: {len(results['errors'])}")

    if dry_run:
        print("\n[DRY RUN - no files were modified]")

    return results


if __name__ == "__main__":
    import sys

    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    backfill_mode = "--backfill" in sys.argv or "-b" in sys.argv

    # Get country code if provided (skip flags)
    country_arg = None
    for arg in sys.argv[1:]:
        if arg not in ["--dry-run", "-n", "--backfill", "-b"]:
            country_arg = arg.upper()
            break

    if backfill_mode:
        # Backfill centroids mode
        if country_arg:
            print(f"Backfilling centroids for {country_arg}...")
            result = backfill_centroids(country_arg, dry_run=dry_run)
            print(json.dumps(result, indent=2, default=str))
        else:
            print("Backfilling centroids for all countries...")
            if dry_run:
                print("[DRY RUN MODE - no files will be modified]")
            backfill_all_centroids(dry_run=dry_run)
    elif country_arg:
        # Single country aggregation
        print(f"Aggregating geometry for {country_arg}...")
        result = aggregate_country(country_arg, dry_run=dry_run)
        print(json.dumps(result, indent=2, default=str))
    else:
        # All countries aggregation
        print("Aggregating geometry for all countries...")
        if dry_run:
            print("[DRY RUN MODE - no files will be modified]")
        aggregate_all(dry_run=dry_run)
