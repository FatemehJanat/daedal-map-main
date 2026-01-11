"""
Convert Global Fire Atlas day_of_burn rasters to daily fire progression parquet.

Creates daily polygon snapshots for each fire, enabling fire spread animation.
Processes year-by-year (most recent first) for resume capability.

Input:
  - SHP_perimeters: Fire perimeter shapefiles with fire_ID, start/end dates
  - day_of_burn: Rasters with day-of-year burned for each pixel

Output:
  - fire_progression_{year}.parquet: Daily cumulative burn polygons per fire

Schema:
  - event_id (str): Fire ID matching fires.parquet
  - date (date): Date of this snapshot
  - day_num (int): Day number within fire (1 = ignition day)
  - area_km2 (float): Cumulative burned area as of this day
  - perimeter (str): GeoJSON polygon of cumulative burn area

Usage:
  # Process all years >= 10 km2 (default), most recent first
  python convert_fire_progression.py --all

  # Process with different size threshold
  python convert_fire_progression.py --all --min-size 25

  # Process specific year
  python convert_fire_progression.py --year 2024

  # Force reprocess
  python convert_fire_progression.py --year 2024 --force

Size thresholds (global, ~23 years):
  >= 10 km2:  ~1.3M fires, ~12 hours
  >= 25 km2:  ~473K fires, ~4.4 hours
  >= 50 km2:  ~196K fires, ~1.8 hours
  >= 100 km2: ~75K fires,  ~42 minutes
"""

import argparse
import geopandas as gpd
import pandas as pd
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.warp import transform_bounds
from rasterio.features import shapes, rasterize
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime, timedelta
import json
import warnings
import traceback
import time
warnings.filterwarnings('ignore')


def doy_to_date(doy: int, year: int) -> datetime:
    """Convert day-of-year to datetime."""
    return datetime(year, 1, 1) + timedelta(days=doy - 1)


def process_fire(fire, tif_current_path, tif_prev_path, current_year, simplify_tolerance=0.005):
    """
    Process a single fire to extract daily progression polygons.
    Returns list of dicts with daily snapshots.
    """
    fire_id = str(fire.fire_ID)
    start_doy = int(fire.start_DOY)
    end_doy = int(fire.end_DOY)
    duration = int(fire.duration)

    # Skip single-day fires (no progression to show)
    if duration < 2:
        return []

    # Determine if fire spans year boundary (Dec -> Jan)
    spans_year = start_doy > end_doy

    bounds = fire.geometry.bounds
    results = []

    try:
        with rasterio.open(tif_current_path) as src:
            # Transform bounds to raster CRS
            minx, miny, maxx, maxy = transform_bounds('EPSG:4326', src.crs, *bounds)

            # Add buffer
            buffer = 2000  # 2km buffer
            minx -= buffer
            miny -= buffer
            maxx += buffer
            maxy += buffer

            window = from_bounds(minx, miny, maxx, maxy, src.transform)

            # Handle window edge cases
            col_off = max(0, int(window.col_off))
            row_off = max(0, int(window.row_off))
            width = min(int(window.width), src.width - col_off)
            height = min(int(window.height), src.height - row_off)

            if width <= 0 or height <= 0:
                return []

            from rasterio.windows import Window
            safe_window = Window(col_off, row_off, width, height)

            data_current = src.read(1, window=safe_window)
            win_transform = src.window_transform(safe_window)
            raster_crs = src.crs

            # Load previous year data if fire spans year boundary
            data_prev = None
            if spans_year and tif_prev_path and Path(tif_prev_path).exists():
                try:
                    with rasterio.open(tif_prev_path) as src_prev:
                        window_prev = from_bounds(minx, miny, maxx, maxy, src_prev.transform)
                        col_off_p = max(0, int(window_prev.col_off))
                        row_off_p = max(0, int(window_prev.row_off))
                        width_p = min(int(window_prev.width), src_prev.width - col_off_p)
                        height_p = min(int(window_prev.height), src_prev.height - row_off_p)

                        if width_p > 0 and height_p > 0:
                            safe_window_prev = Window(col_off_p, row_off_p, width_p, height_p)
                            data_prev = src_prev.read(1, window=safe_window_prev)
                except Exception:
                    data_prev = None

            # Rasterize fire perimeter as mask
            fire_gdf = gpd.GeoDataFrame([fire], crs='EPSG:4326').to_crs(raster_crs)
            fire_geom = fire_gdf.geometry.iloc[0]

            mask = rasterize(
                [(fire_geom, 1)],
                out_shape=data_current.shape,
                transform=win_transform,
                fill=0,
                dtype=np.uint8
            )

            # Build day-by-day progression
            prev_year = current_year - 1

            if spans_year:
                # Fire spans Dec prev_year -> Jan/Feb current_year
                days_in_prev_year = 366 if (prev_year % 4 == 0 and (prev_year % 100 != 0 or prev_year % 400 == 0)) else 365

                # Days from previous year (Dec)
                days_prev = list(range(start_doy, days_in_prev_year + 1)) if data_prev is not None else []

                # Days in current year
                days_current = list(range(1, end_doy + 1))

                day_num = 1
                cumulative_mask = np.zeros_like(data_current, dtype=bool)

                # Process previous year days
                for doy in days_prev:
                    if data_prev is not None and data_prev.shape == data_current.shape:
                        new_burn = (data_prev == doy) & (mask == 1)
                        cumulative_mask = cumulative_mask | new_burn

                    if cumulative_mask.sum() > 0:
                        poly = extract_polygon(cumulative_mask, win_transform, raster_crs, simplify_tolerance)
                        if poly:
                            date = doy_to_date(doy, prev_year)
                            results.append({
                                'event_id': fire_id,
                                'date': date.date(),
                                'day_num': day_num,
                                'area_km2': poly.area * 12321,
                                'perimeter': json.dumps(mapping(poly))
                            })
                    day_num += 1

                # Process current year days
                for doy in days_current:
                    new_burn = (data_current == doy) & (mask == 1)
                    cumulative_mask = cumulative_mask | new_burn

                    if cumulative_mask.sum() > 0:
                        poly = extract_polygon(cumulative_mask, win_transform, raster_crs, simplify_tolerance)
                        if poly:
                            date = doy_to_date(doy, current_year)
                            results.append({
                                'event_id': fire_id,
                                'date': date.date(),
                                'day_num': day_num,
                                'area_km2': poly.area * 12321,
                                'perimeter': json.dumps(mapping(poly))
                            })
                    day_num += 1

            else:
                # Fire entirely within current year
                cumulative_mask = np.zeros_like(data_current, dtype=bool)

                for day_num, doy in enumerate(range(start_doy, end_doy + 1), 1):
                    new_burn = (data_current == doy) & (mask == 1)
                    cumulative_mask = cumulative_mask | new_burn

                    if cumulative_mask.sum() > 0:
                        poly = extract_polygon(cumulative_mask, win_transform, raster_crs, simplify_tolerance)
                        if poly:
                            date = doy_to_date(doy, current_year)
                            results.append({
                                'event_id': fire_id,
                                'date': date.date(),
                                'day_num': day_num,
                                'area_km2': poly.area * 12321,
                                'perimeter': json.dumps(mapping(poly))
                            })

    except Exception as e:
        # Log but don't fail - continue with other fires
        print(f"    Warning: Error processing fire {fire_id}: {str(e)[:100]}")
        return []

    return results


def extract_polygon(mask, transform, src_crs, simplify_tolerance):
    """Extract and simplify polygon from binary mask."""
    try:
        polys = []
        for geom, val in shapes(mask.astype(np.uint8), transform=transform):
            if val == 1:
                polys.append(shape(geom))

        if not polys:
            return None

        merged = unary_union(polys)

        # Transform to WGS84
        result_gdf = gpd.GeoDataFrame(geometry=[merged], crs=src_crs).to_crs('EPSG:4326')
        result_geom = result_gdf.geometry.iloc[0]

        # Simplify
        if simplify_tolerance > 0:
            result_geom = result_geom.simplify(simplify_tolerance, preserve_topology=True)

        return result_geom

    except Exception:
        return None


def process_year(year, raw_path, output_path, min_size_km2=10, simplify_tolerance=0.005, force=False):
    """Process a single year of fire data."""

    output_file = output_path / f'fire_progression_{year}.parquet'

    if output_file.exists() and not force:
        print(f"  Year {year}: Already processed (use --force to reprocess)")
        return True

    perimeter_shp = raw_path / f'SHP_perimeters/GFA_v20240409_perimeters_{year}.shp'
    tif_current = raw_path / f'day_of_burn/GFA_v20240409_day_of_burn_{year}.tif'
    tif_prev = raw_path / f'day_of_burn/GFA_v20240409_day_of_burn_{year - 1}.tif'

    if not perimeter_shp.exists():
        print(f"  Year {year}: No perimeter file found")
        return False

    if not tif_current.exists():
        print(f"  Year {year}: No day_of_burn raster found")
        return False

    print(f"\n=== Processing year {year} ===")

    # Load perimeters
    print(f"  Loading fire perimeters...")
    perims = gpd.read_file(perimeter_shp)

    # Filter to multi-day fires with minimum size
    filtered = perims[(perims['duration'] >= 2) & (perims['size'] >= min_size_km2)]
    print(f"  Total fires: {len(perims):,}")
    print(f"  Multi-day (duration >= 2): {len(perims[perims['duration'] >= 2]):,}")
    print(f"  After size filter (>= {min_size_km2} km2): {len(filtered):,}")

    if len(filtered) == 0:
        print(f"  No fires to process after filtering")
        return True

    # Process each fire
    all_results = []
    errors = 0
    start_time = time.time()

    for idx, (_, fire) in enumerate(filtered.iterrows()):
        if idx % 100 == 0:
            elapsed = time.time() - start_time
            rate = (idx + 1) / elapsed if elapsed > 0 else 0
            remaining = (len(filtered) - idx) / rate if rate > 0 else 0
            print(f"  Processing {idx + 1:,}/{len(filtered):,} ({rate:.1f}/sec, ~{remaining/60:.1f} min left)")

        try:
            results = process_fire(fire, tif_current, tif_prev, year, simplify_tolerance)
            all_results.extend(results)
        except Exception as e:
            errors += 1
            if errors <= 10:
                print(f"    Error on fire {fire.fire_ID}: {str(e)[:80]}")

    elapsed = time.time() - start_time
    print(f"  Completed in {elapsed/60:.1f} minutes")
    print(f"  Total daily snapshots: {len(all_results):,}, Errors: {errors}")

    if not all_results:
        print(f"  No results to save for year {year}")
        return True

    # Convert to DataFrame and save
    df = pd.DataFrame(all_results)
    df['date'] = pd.to_datetime(df['date'])

    output_path.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df)
    pq.write_table(table, output_file, compression='snappy')

    print(f"  Saved: {output_file.name}")
    print(f"  File size: {output_file.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"  Unique fires: {df['event_id'].nunique():,}")
    print(f"  Total snapshots: {len(df):,}")
    print(f"  Avg days per fire: {len(df) / df['event_id'].nunique():.1f}")

    return True


def main():
    parser = argparse.ArgumentParser(description='Convert fire day_of_burn to progression parquet')
    parser.add_argument('--year', type=int, help='Single year to process')
    parser.add_argument('--all', action='store_true', help='Process all available years (most recent first)')
    parser.add_argument('--force', action='store_true', help='Reprocess even if output exists')
    parser.add_argument('--min-size', type=float, default=10, help='Minimum fire size in km2 (default: 10)')
    parser.add_argument('--simplify', type=float, default=0.005, help='Simplification tolerance in degrees')
    args = parser.parse_args()

    # Paths
    raw_path = Path('C:/Users/Bryan/Desktop/county-map-data/Raw data/global_fire_atlas')
    output_path = Path('C:/Users/Bryan/Desktop/county-map-data/global/wildfires')

    if args.year:
        # Process single year
        process_year(args.year, raw_path, output_path, args.min_size, args.simplify, args.force)
    elif args.all:
        # Find all available years from perimeter shapefiles
        shp_path = raw_path / 'SHP_perimeters'
        years = sorted([
            int(f.stem.split('_')[-1])
            for f in shp_path.glob('GFA_v*_perimeters_*.shp')
        ], reverse=True)  # Most recent first

        print(f"Found {len(years)} years: {years[0]} to {years[-1]} (processing newest first)")
        print(f"Output: {output_path}")
        print(f"Minimum size: {args.min_size} km2")
        print(f"Simplification: {args.simplify} degrees")

        total_start = time.time()
        for year in years:
            try:
                process_year(year, raw_path, output_path, args.min_size, args.simplify, args.force)
            except Exception as e:
                print(f"  ERROR processing year {year}: {e}")
                traceback.print_exc()
                continue

        total_elapsed = time.time() - total_start
        print(f"\n=== All years complete in {total_elapsed/3600:.1f} hours ===")
    else:
        print("Convert Global Fire Atlas to daily fire progression parquet")
        print()
        print("Usage:")
        print("  python convert_fire_progression.py --all                  # All years, >= 10 km2")
        print("  python convert_fire_progression.py --all --min-size 25    # All years, >= 25 km2")
        print("  python convert_fire_progression.py --year 2024            # Single year")
        print()
        print("Options:")
        print("  --min-size N   Minimum fire size in km2 (default: 10)")
        print("  --force        Reprocess even if output exists")
        print("  --simplify N   Simplification tolerance in degrees (default: 0.005)")
        print()
        print("Size thresholds (global, ~23 years):")
        print("  >= 10 km2:  ~1.3M fires, ~12 hours")
        print("  >= 25 km2:  ~473K fires, ~4.4 hours")
        print("  >= 50 km2:  ~196K fires, ~1.8 hours")
        print("  >= 100 km2: ~75K fires,  ~42 minutes")


if __name__ == '__main__':
    main()
