"""
Optimize Geometry - Remove placeholder levels and add bounding boxes.

This script prepares parquet files for viewport-based loading by:
1. Removing placeholder admin levels (GADM creates empty child rows)
2. Computing bounding boxes for fast viewport filtering

Usage:
    python optimize_geometry.py CAN            # Process Canada
    python optimize_geometry.py CAN --dry-run  # Preview without saving
    python optimize_geometry.py --all          # Process all countries
"""

import pandas as pd
import json
from pathlib import Path
from shapely.geometry import shape
from shapely.validation import make_valid
import warnings

warnings.filterwarnings('ignore', category=RuntimeWarning)

GEOMETRY_PATH = Path(r"C:\Users\Bryan\Desktop\county-map-data\geometry")


def is_placeholder_level(df: pd.DataFrame, level: int) -> bool:
    """
    Check if a level is a placeholder (no real data).

    Placeholder levels have:
    - All empty/null names, OR
    - All rows have the same name (usually empty or 'Unknown')
    - OR row count matches parent level exactly (1:1 mapping)
    """
    level_df = df[df['admin_level'] == level]

    if len(level_df) == 0:
        return True

    # Check if all names are empty/null
    names = level_df['name'].fillna('')
    unique_names = names.unique()

    if len(unique_names) == 1 and unique_names[0] in ['', 'Unknown', None]:
        return True

    # Check if this level has same row count as previous level
    # (indicates 1:1 placeholder mapping)
    prev_level = level - 1
    if prev_level >= 0:
        prev_df = df[df['admin_level'] == prev_level]
        if len(level_df) == len(prev_df) and len(level_df) > 1:
            # Check if parent_ids match prev level loc_ids exactly
            prev_ids = set(prev_df['loc_id'].tolist())
            parent_ids = set(level_df['parent_id'].tolist())
            if prev_ids == parent_ids:
                return True

    return False


def compute_bbox(geom_str: str) -> tuple:
    """
    Extract bounding box from GeoJSON geometry string.
    Returns (min_lon, min_lat, max_lon, max_lat) or None if invalid.
    """
    if pd.isna(geom_str) or not geom_str:
        return None

    try:
        geom_data = json.loads(geom_str) if isinstance(geom_str, str) else geom_str
        geom = shape(geom_data)

        if not geom.is_valid:
            geom = make_valid(geom)

        bounds = geom.bounds  # (minx, miny, maxx, maxy)
        return bounds
    except Exception:
        return None


def optimize_country(iso3: str, dry_run: bool = False) -> dict:
    """
    Optimize a single country's parquet file.

    Returns dict with statistics about changes made.
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

    original_rows = len(df)
    original_levels = sorted(df['admin_level'].unique())

    # =====================
    # STEP 1: Remove placeholder levels
    # =====================
    placeholder_levels = []
    for level in sorted(df['admin_level'].unique(), reverse=True):
        if is_placeholder_level(df, level):
            placeholder_levels.append(level)

    # Remove placeholder levels
    df_clean = df[~df['admin_level'].isin(placeholder_levels)]

    rows_removed = original_rows - len(df_clean)

    # =====================
    # STEP 2: Add bounding boxes
    # =====================
    # Check if bbox columns already exist
    has_bbox = all(col in df_clean.columns for col in
                   ['bbox_min_lon', 'bbox_min_lat', 'bbox_max_lon', 'bbox_max_lat'])

    if not has_bbox:
        # Add empty columns
        df_clean = df_clean.copy()
        df_clean['bbox_min_lon'] = None
        df_clean['bbox_min_lat'] = None
        df_clean['bbox_max_lon'] = None
        df_clean['bbox_max_lat'] = None

    # Compute bboxes for rows with geometry but missing bbox
    bbox_computed = 0
    rows_with_geometry = df_clean['geometry'].notna()

    for idx in df_clean[rows_with_geometry].index:
        # Skip if bbox already computed
        if pd.notna(df_clean.at[idx, 'bbox_min_lon']):
            continue

        bbox = compute_bbox(df_clean.at[idx, 'geometry'])
        if bbox:
            df_clean.at[idx, 'bbox_min_lon'] = bbox[0]
            df_clean.at[idx, 'bbox_min_lat'] = bbox[1]
            df_clean.at[idx, 'bbox_max_lon'] = bbox[2]
            df_clean.at[idx, 'bbox_max_lat'] = bbox[3]
            bbox_computed += 1

    # =====================
    # STEP 3: Save results
    # =====================
    if not dry_run and (rows_removed > 0 or bbox_computed > 0):
        df_clean.to_parquet(parquet_path, index=False)

    final_levels = sorted(df_clean['admin_level'].unique())

    return {
        "status": "optimized",
        "original_rows": original_rows,
        "final_rows": len(df_clean),
        "rows_removed": rows_removed,
        "original_levels": original_levels,
        "final_levels": final_levels,
        "placeholder_levels_removed": placeholder_levels,
        "bbox_computed": bbox_computed,
        "dry_run": dry_run
    }


def optimize_all(dry_run: bool = False):
    """Optimize all countries."""
    parquet_files = list(GEOMETRY_PATH.glob("*.parquet"))

    results = {
        "optimized": [],
        "skipped": [],
        "errors": []
    }

    total_rows_removed = 0
    total_bbox_computed = 0

    for i, parquet_file in enumerate(parquet_files):
        iso3 = parquet_file.stem

        # Skip non-country files
        if len(iso3) != 3 or not iso3.isupper():
            continue

        result = optimize_country(iso3, dry_run=dry_run)

        if result["status"] == "optimized":
            results["optimized"].append(iso3)
            total_rows_removed += result["rows_removed"]
            total_bbox_computed += result["bbox_computed"]

            if result["rows_removed"] > 0 or result["bbox_computed"] > 0:
                print(f"[OPT] {iso3}: -{result['rows_removed']} rows, +{result['bbox_computed']} bboxes")
        elif result["status"] == "skip":
            results["skipped"].append((iso3, result["reason"]))
        else:
            results["errors"].append((iso3, result.get("reason", "unknown")))
            print(f"[ERR] {iso3}: {result.get('reason', 'unknown')}")

        if (i + 1) % 50 == 0:
            print(f"Processed {i + 1}/{len(parquet_files)} countries...")

    # Print summary
    print("\n=== Optimization Summary ===")
    print(f"Countries processed: {len(results['optimized'])}")
    print(f"Total rows removed: {total_rows_removed}")
    print(f"Total bboxes computed: {total_bbox_computed}")
    print(f"Skipped: {len(results['skipped'])}")
    print(f"Errors: {len(results['errors'])}")

    if dry_run:
        print("\n[DRY RUN - no files were modified]")

    return results


if __name__ == "__main__":
    import sys

    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    all_countries = "--all" in sys.argv or "-a" in sys.argv

    # Get country code if provided
    country_arg = None
    for arg in sys.argv[1:]:
        if arg not in ["--dry-run", "-n", "--all", "-a"]:
            country_arg = arg.upper()
            break

    if all_countries:
        print("Optimizing all countries...")
        if dry_run:
            print("[DRY RUN MODE - no files will be modified]")
        optimize_all(dry_run=dry_run)
    elif country_arg:
        print(f"Optimizing {country_arg}...")
        if dry_run:
            print("[DRY RUN MODE]")
        result = optimize_country(country_arg, dry_run=dry_run)
        print(json.dumps(result, indent=2, default=str))
    else:
        print("Usage:")
        print("  python optimize_geometry.py CAN            # Process Canada")
        print("  python optimize_geometry.py CAN --dry-run  # Preview without saving")
        print("  python optimize_geometry.py --all          # Process all countries")
