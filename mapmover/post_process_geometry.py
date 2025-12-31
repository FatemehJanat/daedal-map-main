"""
Post-process geometry parquet files.

This script enhances raw imported geometry with:
1. Aggregation - Create parent geometry by merging child polygons
2. Bounding boxes - Compute bbox columns for viewport filtering
3. Centroids - Backfill missing centroid coordinates
4. Children counts - Compute children_count and descendants_count for popups

Run after any geometry import (GADM, Census, etc.) to ensure complete data.

Usage:
    python post_process_geometry.py              # Process all countries
    python post_process_geometry.py USA          # Process single country
    python post_process_geometry.py --dry-run    # Preview without saving
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# Import shapely for geometry operations
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from shapely.validation import make_valid

# Path to geometry files
GEOMETRY_PATH = Path(r"C:\Users\Bryan\Desktop\county-map-data\geometry")

# Simplification tolerances by admin level (in degrees)
# Higher levels = more detail needed
SIMPLIFY_TOLERANCE = {
    0: 0.01,   # Country level - moderate simplification
    1: 0.005,  # State level - less simplification
    2: 0.001,  # County level - minimal simplification
}


def get_simplify_tolerance(level):
    """Get simplification tolerance for admin level."""
    return SIMPLIFY_TOLERANCE.get(level, 0.001)


def aggregate_geometry(df):
    """
    Aggregate child geometry to create missing parent geometry.

    For each level missing geometry, merge children's polygons.
    Returns updated DataFrame and count of aggregated rows.
    """
    if len(df) == 0:
        return df, 0

    df_work = df.copy()
    aggregated_count = 0

    # Find levels that need aggregation (have rows but no geometry)
    # Process from deepest to shallowest so children are aggregated before parents
    levels = sorted(df_work['admin_level'].unique(), reverse=True)

    # For each level, check if any rows are missing geometry
    for level in levels:
        level_df = df_work[df_work['admin_level'] == level]
        missing_geom = level_df[level_df['geometry'].isna()]

        if len(missing_geom) == 0:
            continue

        # Find source level (immediate child level with geometry)
        # Search in ascending order to find the closest level above
        source_level = None
        for check_level in sorted(df_work['admin_level'].unique()):
            if check_level > level:
                check_df = df_work[df_work['admin_level'] == check_level]
                if check_df['geometry'].notna().any():
                    source_level = check_level
                    break

        if source_level is None:
            continue

        # Aggregate from source level
        for idx, row in missing_geom.iterrows():
            loc_id = row['loc_id']

            # Find children at source level
            children = df_work[
                (df_work['admin_level'] == source_level) &
                (df_work['parent_id'] == loc_id) &
                (df_work['geometry'].notna())
            ]

            if len(children) == 0:
                # Try finding by loc_id prefix
                children = df_work[
                    (df_work['admin_level'] == source_level) &
                    (df_work['loc_id'].str.startswith(loc_id + '-')) &
                    (df_work['geometry'].notna())
                ]

            if len(children) == 0:
                continue

            try:
                # Parse child geometries
                child_geoms = []
                for _, child in children.iterrows():
                    geom_str = child['geometry']
                    if pd.isna(geom_str) or not geom_str:
                        continue
                    geom_data = json.loads(geom_str) if isinstance(geom_str, str) else geom_str
                    geom = shape(geom_data)
                    if not geom.is_valid:
                        geom = make_valid(geom)
                    child_geoms.append(geom)

                if not child_geoms:
                    continue

                # Merge geometries
                merged = unary_union(child_geoms)

                # Simplify based on target level
                tolerance = get_simplify_tolerance(level)
                merged = merged.simplify(tolerance, preserve_topology=True)

                # Convert back to GeoJSON string
                geom_json = json.dumps(mapping(merged))

                # Calculate centroid
                centroid = merged.centroid

                # Calculate bbox
                bounds = merged.bounds  # (minx, miny, maxx, maxy)

                # Update the row
                df_work.at[idx, 'geometry'] = geom_json
                df_work.at[idx, 'centroid_lon'] = centroid.x
                df_work.at[idx, 'centroid_lat'] = centroid.y
                df_work.at[idx, 'bbox_min_lon'] = bounds[0]
                df_work.at[idx, 'bbox_min_lat'] = bounds[1]
                df_work.at[idx, 'bbox_max_lon'] = bounds[2]
                df_work.at[idx, 'bbox_max_lat'] = bounds[3]
                df_work.at[idx, 'has_polygon'] = True
                aggregated_count += 1

            except Exception as e:
                continue

    return df_work, aggregated_count


def compute_bboxes(df):
    """
    Compute bounding boxes for all rows with geometry but missing bbox.
    Returns updated DataFrame and count of computed bboxes.
    """
    if len(df) == 0:
        return df, 0

    df_work = df.copy()

    # Ensure bbox columns exist
    for col in ['bbox_min_lon', 'bbox_min_lat', 'bbox_max_lon', 'bbox_max_lat']:
        if col not in df_work.columns:
            df_work[col] = None

    # Find rows with geometry but missing bbox
    needs_bbox = df_work[
        df_work['geometry'].notna() &
        (df_work['bbox_min_lon'].isna() | df_work['bbox_min_lat'].isna() |
         df_work['bbox_max_lon'].isna() | df_work['bbox_max_lat'].isna())
    ]

    if len(needs_bbox) == 0:
        return df_work, 0

    computed_count = 0

    for idx, row in needs_bbox.iterrows():
        geom_str = row['geometry']
        if pd.isna(geom_str) or not geom_str:
            continue

        try:
            geom_data = json.loads(geom_str) if isinstance(geom_str, str) else geom_str
            geom = shape(geom_data)
            bounds = geom.bounds  # (minx, miny, maxx, maxy)

            df_work.at[idx, 'bbox_min_lon'] = bounds[0]
            df_work.at[idx, 'bbox_min_lat'] = bounds[1]
            df_work.at[idx, 'bbox_max_lon'] = bounds[2]
            df_work.at[idx, 'bbox_max_lat'] = bounds[3]
            computed_count += 1

        except Exception:
            continue

    return df_work, computed_count


def backfill_centroids(df):
    """
    Backfill missing centroids for rows with geometry.
    Returns updated DataFrame and count of backfilled centroids.
    """
    if len(df) == 0:
        return df, 0

    df_work = df.copy()

    # Ensure centroid columns exist
    if 'centroid_lon' not in df_work.columns:
        df_work['centroid_lon'] = None
    if 'centroid_lat' not in df_work.columns:
        df_work['centroid_lat'] = None

    # Find rows with geometry but missing centroid
    needs_centroid = df_work[
        df_work['geometry'].notna() &
        (df_work['centroid_lon'].isna() | df_work['centroid_lat'].isna())
    ]

    if len(needs_centroid) == 0:
        return df_work, 0

    fixed_count = 0

    for idx, row in needs_centroid.iterrows():
        geom_str = row['geometry']
        if pd.isna(geom_str) or not geom_str:
            continue

        try:
            geom_data = json.loads(geom_str) if isinstance(geom_str, str) else geom_str
            geom = shape(geom_data)

            if not geom.is_valid:
                geom = make_valid(geom)

            centroid = geom.centroid
            df_work.at[idx, 'centroid_lon'] = centroid.x
            df_work.at[idx, 'centroid_lat'] = centroid.y
            fixed_count += 1

        except Exception:
            continue

    return df_work, fixed_count


def compute_children_counts(df):
    """
    Compute direct children counts for each row.

    Returns updated DataFrame with:
    - children_count: int - total direct children
    - children_by_level: str - JSON dict of counts by admin level
    """
    if len(df) == 0:
        return df, 0

    df_work = df.copy()

    # Initialize columns
    df_work['children_count'] = 0
    df_work['children_by_level'] = '{}'

    updated_count = 0

    # Build parent-to-children mapping using parent_id
    children_by_parent = defaultdict(list)

    for idx, row in df_work.iterrows():
        loc_id = row['loc_id']
        parent_id = row.get('parent_id', '')
        admin_level = row['admin_level']

        if parent_id and pd.notna(parent_id):
            children_by_parent[parent_id].append({
                'loc_id': loc_id,
                'admin_level': admin_level
            })

    # Compute counts for each row
    for idx, row in df_work.iterrows():
        loc_id = row['loc_id']
        direct_children = children_by_parent.get(loc_id, [])

        if not direct_children:
            continue

        total_count = len(direct_children)
        by_level = defaultdict(int)

        for child in direct_children:
            level = child['admin_level']
            by_level[level] += 1

        by_level_json = json.dumps({str(k): v for k, v in sorted(by_level.items())})

        df_work.at[idx, 'children_count'] = total_count
        df_work.at[idx, 'children_by_level'] = by_level_json
        updated_count += 1

    return df_work, updated_count


def compute_descendant_counts(df):
    """
    Compute total descendant counts (all levels below, not just direct children).

    Example: Brazil level 0 gets descendants_count=5599 (27 states + 5572 municipalities)

    Returns updated DataFrame with:
    - descendants_count: int - total descendants at all levels below
    - descendants_by_level: str - JSON dict of counts by admin level
    """
    if len(df) == 0:
        return df, 0

    df_work = df.copy()

    # Initialize columns
    if 'descendants_count' not in df_work.columns:
        df_work['descendants_count'] = 0
    if 'descendants_by_level' not in df_work.columns:
        df_work['descendants_by_level'] = '{}'

    updated_count = 0

    # For each row, count all rows at deeper levels that are descendants
    for idx, row in df_work.iterrows():
        loc_id = row['loc_id']
        current_level = row['admin_level']

        # Find all descendants (rows at deeper levels whose loc_id starts with this one)
        descendants = df_work[
            (df_work['admin_level'] > current_level) &
            (df_work['loc_id'].str.startswith(loc_id + '-'))
        ]

        if len(descendants) == 0:
            continue

        by_level = descendants.groupby('admin_level').size().to_dict()
        total_count = len(descendants)

        by_level_json = json.dumps({str(k): v for k, v in sorted(by_level.items())})

        df_work.at[idx, 'descendants_count'] = total_count
        df_work.at[idx, 'descendants_by_level'] = by_level_json
        updated_count += 1

    return df_work, updated_count


def post_process_country(iso3: str, dry_run: bool = False) -> dict:
    """
    Run all post-processing steps on a single country.

    Steps:
    1. Aggregate missing geometry from children
    2. Compute bounding boxes
    3. Backfill centroids
    4. Compute children and descendant counts

    Returns dict with stats.
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

    original_len = len(df)
    stats = {
        "total_rows": original_len,
        "aggregated": 0,
        "bboxes_computed": 0,
        "centroids_fixed": 0,
        "children_computed": 0,
        "descendants_computed": 0,
    }

    # Step 1: Aggregate missing geometry
    df, agg_count = aggregate_geometry(df)
    stats["aggregated"] = agg_count

    # Step 2: Compute bounding boxes
    df, bbox_count = compute_bboxes(df)
    stats["bboxes_computed"] = bbox_count

    # Step 3: Backfill centroids
    df, centroid_count = backfill_centroids(df)
    stats["centroids_fixed"] = centroid_count

    # Step 4: Compute children counts
    df, children_count = compute_children_counts(df)
    stats["children_computed"] = children_count

    # Step 5: Compute descendant counts
    df, descendants_count = compute_descendant_counts(df)
    stats["descendants_computed"] = descendants_count

    # Check if anything changed
    total_changes = agg_count + bbox_count + centroid_count + children_count + descendants_count
    if total_changes == 0:
        return {"status": "ok", "reason": "no changes needed", **stats}

    # Save updated parquet
    if not dry_run:
        df.to_parquet(parquet_path, index=False)

    stats["status"] = "updated"
    stats["dry_run"] = dry_run
    return stats


def post_process_all(dry_run: bool = False):
    """Run post-processing on all country parquet files."""

    parquet_files = list(GEOMETRY_PATH.glob("*.parquet"))

    results = {
        "updated": [],
        "ok": [],
        "skipped": [],
        "errors": []
    }

    totals = {
        "aggregated": 0,
        "bboxes_computed": 0,
        "centroids_fixed": 0,
        "children_computed": 0,
        "descendants_computed": 0,
    }

    print(f"Post-processing {len(parquet_files)} parquet files...")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if dry_run:
        print("[DRY RUN MODE - no files will be modified]")
    print()

    for i, parquet_file in enumerate(parquet_files):
        iso3 = parquet_file.stem

        # Skip non-country files (global.csv backup, etc.)
        if len(iso3) != 3 or not iso3.isupper():
            continue

        result = post_process_country(iso3, dry_run=dry_run)

        if result["status"] == "updated":
            results["updated"].append(iso3)
            totals["aggregated"] += result.get("aggregated", 0)
            totals["bboxes_computed"] += result.get("bboxes_computed", 0)
            totals["centroids_fixed"] += result.get("centroids_fixed", 0)
            totals["children_computed"] += result.get("children_computed", 0)
            totals["descendants_computed"] += result.get("descendants_computed", 0)

            # Print details for updated countries
            details = []
            if result.get("aggregated", 0) > 0:
                details.append(f"{result['aggregated']} aggregated")
            if result.get("bboxes_computed", 0) > 0:
                details.append(f"{result['bboxes_computed']} bboxes")
            if result.get("centroids_fixed", 0) > 0:
                details.append(f"{result['centroids_fixed']} centroids")
            if result.get("children_computed", 0) > 0:
                details.append(f"{result['children_computed']} children")
            if result.get("descendants_computed", 0) > 0:
                details.append(f"{result['descendants_computed']} descendants")
            print(f"  [{iso3}] Updated: {', '.join(details)}")

        elif result["status"] == "ok":
            results["ok"].append(iso3)
        elif result["status"] == "skip":
            results["skipped"].append((iso3, result.get("reason", "unknown")))
        else:
            results["errors"].append((iso3, result.get("reason", "unknown")))
            print(f"  [{iso3}] ERROR: {result.get('reason', 'unknown')}")

        # Progress update
        if (i + 1) % 50 == 0:
            print(f"  Processed {i + 1}/{len(parquet_files)} files...")

    # Print summary
    print()
    print("=" * 60)
    print("POST-PROCESSING SUMMARY")
    print("=" * 60)
    print(f"Countries updated: {len(results['updated'])}")
    print(f"Countries already complete: {len(results['ok'])}")
    print(f"Skipped: {len(results['skipped'])}")
    print(f"Errors: {len(results['errors'])}")
    print()
    print("Total changes:")
    print(f"  Geometry aggregated: {totals['aggregated']}")
    print(f"  Bboxes computed: {totals['bboxes_computed']}")
    print(f"  Centroids fixed: {totals['centroids_fixed']}")
    print(f"  Children counts: {totals['children_computed']}")
    print(f"  Descendant counts: {totals['descendants_computed']}")
    print()
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if dry_run:
        print("\n[DRY RUN - no files were modified]")

    return results


if __name__ == "__main__":
    import sys

    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv

    # Get country code if provided (skip flags)
    country_arg = None
    for arg in sys.argv[1:]:
        if arg not in ["--dry-run", "-n"]:
            country_arg = arg.upper()
            break

    if country_arg:
        # Single country
        print(f"Post-processing {country_arg}...")
        if dry_run:
            print("[DRY RUN MODE]")
        result = post_process_country(country_arg, dry_run=dry_run)
        print(json.dumps(result, indent=2, default=str))
    else:
        # All countries
        post_process_all(dry_run=dry_run)
