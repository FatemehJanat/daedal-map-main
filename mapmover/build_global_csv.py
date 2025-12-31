"""
Build global.csv from Natural Earth country GeoJSON.

This script is COMPLETELY SEPARATE from GADM imports.
It creates the country-level geometry file from Natural Earth data.

Usage:
    python build_global_csv.py              # Build global.csv
    python build_global_csv.py --dry-run    # Preview without saving
"""

import json
import pandas as pd
from pathlib import Path
from shapely.geometry import shape, mapping
from shapely.validation import make_valid

# Paths
RAW_DATA_PATH = Path(r"C:\Users\Bryan\Desktop\county-map-data\Raw data")
GEOMETRY_PATH = Path(r"C:\Users\Bryan\Desktop\county-map-data\geometry")

# Input file
COUNTRIES_GEOJSON = RAW_DATA_PATH / "all countries.json"

# Output file
GLOBAL_CSV = GEOMETRY_PATH / "global.csv"


def build_global_csv(dry_run=False):
    """Convert Natural Earth GeoJSON to global.csv format."""

    print(f"Reading {COUNTRIES_GEOJSON}...")
    with open(COUNTRIES_GEOJSON, 'r', encoding='utf-8') as f:
        data = json.load(f)

    features = data.get('features', [])
    print(f"Found {len(features)} country features")

    records = []
    skipped = []

    for feat in features:
        props = feat.get('properties', {})
        geom = feat.get('geometry')

        # Get ISO3 code - try multiple fields
        iso3 = props.get('iso_a3') or props.get('adm0_a3') or props.get('sov_a3')

        # Skip invalid ISO codes
        if not iso3 or iso3 == '-99' or len(iso3) != 3:
            skipped.append(props.get('admin', 'Unknown'))
            continue

        # Get country name
        name = props.get('admin') or props.get('name') or props.get('name_long', '')

        # Get geometry as JSON string
        geometry_str = None
        centroid_lon = None
        centroid_lat = None
        bbox_min_lon = None
        bbox_min_lat = None
        bbox_max_lon = None
        bbox_max_lat = None

        if geom:
            try:
                geom_obj = shape(geom)
                if not geom_obj.is_valid:
                    geom_obj = make_valid(geom_obj)

                # Simplify for faster loading (country level doesn't need high detail)
                geom_obj = geom_obj.simplify(0.01, preserve_topology=True)

                geometry_str = json.dumps(mapping(geom_obj))

                # Compute centroid
                centroid = geom_obj.centroid
                centroid_lon = round(centroid.x, 6)
                centroid_lat = round(centroid.y, 6)

                # Compute bbox
                bounds = geom_obj.bounds  # (minx, miny, maxx, maxy)
                bbox_min_lon = round(bounds[0], 6)
                bbox_min_lat = round(bounds[1], 6)
                bbox_max_lon = round(bounds[2], 6)
                bbox_max_lat = round(bounds[3], 6)

            except Exception as e:
                print(f"  Warning: Failed to process geometry for {iso3}: {e}")

        # Use Natural Earth's label coordinates as fallback for centroid
        if centroid_lon is None and 'label_x' in props:
            centroid_lon = props.get('label_x')
            centroid_lat = props.get('label_y')

        record = {
            'loc_id': iso3,
            'name': name,
            'admin_level': 0,
            'parent_id': 'WORLD',
            'geometry': geometry_str,
            'centroid_lon': centroid_lon,
            'centroid_lat': centroid_lat,
            'has_polygon': geometry_str is not None,
            'bbox_min_lon': bbox_min_lon,
            'bbox_min_lat': bbox_min_lat,
            'bbox_max_lon': bbox_max_lon,
            'bbox_max_lat': bbox_max_lat,
        }
        records.append(record)

    print(f"Processed {len(records)} countries")
    if skipped:
        print(f"Skipped {len(skipped)} entries without valid ISO3: {skipped[:5]}{'...' if len(skipped) > 5 else ''}")

    # Create DataFrame
    df = pd.DataFrame(records)
    df = df.sort_values('loc_id')

    # Show stats
    with_geom = df['geometry'].notna().sum()
    print(f"Countries with geometry: {with_geom}/{len(df)}")

    # Show sample
    print("\nSample records:")
    sample_cols = ['loc_id', 'name', 'centroid_lon', 'centroid_lat', 'has_polygon']
    print(df[sample_cols].head(10).to_string(index=False))

    if dry_run:
        print(f"\n[DRY RUN] Would save {len(df)} countries to {GLOBAL_CSV}")
    else:
        df.to_csv(GLOBAL_CSV, index=False)
        print(f"\nSaved {len(df)} countries to {GLOBAL_CSV}")

    return df


if __name__ == "__main__":
    import sys

    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv

    build_global_csv(dry_run=dry_run)
