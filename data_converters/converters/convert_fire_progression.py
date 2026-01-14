"""
Convert Global Fire Atlas day_of_burn rasters to daily fire progression parquet.

Creates daily polygon snapshots for each fire, enabling fire spread animation.
Processes year-by-year (most recent first) for resume capability.

OPTIMIZED VERSION (2026-01-11):
  - Multiprocessing: 4-8 workers process fires in parallel (4-8x speedup)
  - Incremental saves: Saves every 500 fires for crash recovery
  - Smart resume: Detects partial years and continues from where it left off

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

  # Force reprocess (ignores existing files)
  python convert_fire_progression.py --year 2024 --force

  # Control worker count (default: CPU count - 1)
  python convert_fire_progression.py --all --workers 4

Size thresholds (global, ~23 years, with multiprocessing):
  >= 10 km2:  ~1.3M fires, ~2-3 hours (was ~12 hours)
  >= 15 km2:  ~982K fires, ~1.5-2.5 hours
  >= 25 km2:  ~473K fires, ~1 hour
  >= 50 km2:  ~196K fires, ~25 minutes
  >= 100 km2: ~75K fires,  ~10 minutes
"""

import argparse
import geopandas as gpd
import pandas as pd
import numpy as np
import rasterio
from rasterio.windows import from_bounds, Window
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
import multiprocessing as mp
from functools import partial
import os
warnings.filterwarnings('ignore')

# Incremental save interval (fires processed before saving)
SAVE_INTERVAL = 500


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

            # Transform fire perimeter to raster CRS (using pyproj directly)
            from pyproj import Transformer
            from shapely.ops import transform as shapely_transform

            to_raster = Transformer.from_crs('EPSG:4326', raster_crs, always_xy=True)
            to_wgs84 = Transformer.from_crs(raster_crs, 'EPSG:4326', always_xy=True)
            fire_geom = shapely_transform(to_raster.transform, fire.geometry)

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
                last_pixel_count = 0
                for doy in days_prev:
                    if data_prev is not None and data_prev.shape == data_current.shape:
                        new_burn = (data_prev == doy) & (mask == 1)
                        cumulative_mask = cumulative_mask | new_burn

                    pixel_count = cumulative_mask.sum()
                    # Only extract polygon if mask changed (new pixels burned)
                    if pixel_count > 0 and pixel_count != last_pixel_count:
                        poly = extract_polygon(cumulative_mask, win_transform, raster_crs, simplify_tolerance, to_wgs84)
                        if poly:
                            date = doy_to_date(doy, prev_year)
                            results.append({
                                'event_id': fire_id,
                                'date': date.date(),
                                'day_num': day_num,
                                'area_km2': poly.area * 12321,
                                'perimeter': json.dumps(mapping(poly))
                            })
                        last_pixel_count = pixel_count
                    day_num += 1

                # Process current year days
                for doy in days_current:
                    new_burn = (data_current == doy) & (mask == 1)
                    cumulative_mask = cumulative_mask | new_burn

                    pixel_count = cumulative_mask.sum()
                    # Only extract polygon if mask changed (new pixels burned)
                    if pixel_count > 0 and pixel_count != last_pixel_count:
                        poly = extract_polygon(cumulative_mask, win_transform, raster_crs, simplify_tolerance, to_wgs84)
                        if poly:
                            date = doy_to_date(doy, current_year)
                            results.append({
                                'event_id': fire_id,
                                'date': date.date(),
                                'day_num': day_num,
                                'area_km2': poly.area * 12321,
                                'perimeter': json.dumps(mapping(poly))
                            })
                        last_pixel_count = pixel_count
                    day_num += 1

            else:
                # Fire entirely within current year
                cumulative_mask = np.zeros_like(data_current, dtype=bool)
                last_pixel_count = 0

                for day_num, doy in enumerate(range(start_doy, end_doy + 1), 1):
                    new_burn = (data_current == doy) & (mask == 1)
                    cumulative_mask = cumulative_mask | new_burn

                    pixel_count = cumulative_mask.sum()
                    # Only extract polygon if mask changed (new pixels burned)
                    if pixel_count > 0 and pixel_count != last_pixel_count:
                        poly = extract_polygon(cumulative_mask, win_transform, raster_crs, simplify_tolerance, to_wgs84)
                        if poly:
                            date = doy_to_date(doy, current_year)
                            results.append({
                                'event_id': fire_id,
                                'date': date.date(),
                                'day_num': day_num,
                                'area_km2': poly.area * 12321,
                                'perimeter': json.dumps(mapping(poly))
                            })
                        last_pixel_count = pixel_count

    except Exception as e:
        # Log but don't fail - continue with other fires
        print(f"    Warning: Error processing fire {fire_id}: {str(e)[:100]}")
        return []

    return results


def extract_polygon(mask, transform, src_crs, simplify_tolerance, transformer=None):
    """
    Extract and simplify polygon from binary mask.
    Uses pyproj transformer directly instead of GeoDataFrame for speed.
    """
    try:
        polys = []
        for geom, val in shapes(mask.astype(np.uint8), transform=transform):
            if val == 1:
                polys.append(shape(geom))

        if not polys:
            return None

        merged = unary_union(polys)

        # Transform to WGS84 using pyproj (faster than GeoDataFrame)
        if transformer is None:
            from pyproj import Transformer
            transformer = Transformer.from_crs(src_crs, 'EPSG:4326', always_xy=True)

        from shapely.ops import transform as shapely_transform
        result_geom = shapely_transform(transformer.transform, merged)

        # Simplify
        if simplify_tolerance > 0:
            result_geom = result_geom.simplify(simplify_tolerance, preserve_topology=True)

        return result_geom

    except Exception:
        return None


def process_fire_worker(fire_data, tif_current_path, tif_prev_path, current_year, simplify_tolerance):
    """
    Worker function for multiprocessing.
    Takes fire data as dict (not GeoDataFrame row) for pickling.
    """
    try:
        # Reconstruct geometry from WKT
        from shapely import wkt

        fire_id = fire_data['fire_ID']
        start_doy = fire_data['start_DOY']
        end_doy = fire_data['end_DOY']
        duration = fire_data['duration']
        geometry = wkt.loads(fire_data['geometry_wkt'])

        # Create a simple namespace object to pass to process_fire
        class FireRecord:
            pass

        fire = FireRecord()
        fire.fire_ID = fire_id
        fire.start_DOY = start_doy
        fire.end_DOY = end_doy
        fire.duration = duration
        fire.geometry = geometry

        return process_fire(fire, tif_current_path, tif_prev_path, current_year, simplify_tolerance)
    except Exception as e:
        return []


def load_existing_progress(output_file):
    """
    Load existing partial progress from output file.
    Returns set of already-processed event_ids.
    """
    if not output_file.exists():
        return set()

    try:
        df = pd.read_parquet(output_file)
        processed_ids = set(df['event_id'].unique())
        print(f"  Resuming: Found {len(processed_ids):,} fires already processed")
        return processed_ids
    except Exception as e:
        print(f"  Warning: Could not read existing file: {e}")
        return set()


def save_incremental(output_file, all_results, mode='overwrite'):
    """Save results to parquet file."""
    if not all_results:
        return

    df = pd.DataFrame(all_results)
    df['date'] = pd.to_datetime(df['date'])

    output_file.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df)
    pq.write_table(table, output_file, compression='snappy')


def process_year(year, raw_path, output_path, min_size_km2=10, simplify_tolerance=0.005,
                 force=False, num_workers=None):
    """
    Process a single year of fire data with multiprocessing and incremental saves.

    Features:
    - Multiprocessing: Uses Pool to process fires in parallel
    - Incremental saves: Saves every SAVE_INTERVAL fires
    - Resume capability: Detects partial files and continues from where left off
    """
    output_file = output_path / f'fire_progression_{year}.parquet'

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
    filtered = perims[(perims['duration'] >= 2) & (perims['size'] >= min_size_km2)].copy()
    total_fires = len(filtered)

    print(f"  Total fires: {len(perims):,}")
    print(f"  Multi-day (duration >= 2): {len(perims[perims['duration'] >= 2]):,}")
    print(f"  After size filter (>= {min_size_km2} km2): {total_fires:,}")

    if total_fires == 0:
        print(f"  No fires to process after filtering")
        return True

    # Check for existing progress (resume capability)
    existing_results = []
    processed_ids = set()

    if output_file.exists() and not force:
        processed_ids = load_existing_progress(output_file)
        if processed_ids:
            # Load existing data to merge with new results
            existing_df = pd.read_parquet(output_file)
            existing_results = existing_df.to_dict('records')

            # Filter out already-processed fires
            filtered = filtered[~filtered['fire_ID'].astype(str).isin(processed_ids)]

            if len(filtered) == 0:
                print(f"  Year {year}: All fires already processed")
                return True

            print(f"  Remaining fires to process: {len(filtered):,}")

    # Set up multiprocessing
    if num_workers is None:
        num_workers = max(1, mp.cpu_count() - 1)

    print(f"  Using {num_workers} worker processes")

    # Prepare fire data for workers (convert to dicts for pickling)
    fire_data_list = []
    for _, fire in filtered.iterrows():
        fire_data_list.append({
            'fire_ID': str(fire.fire_ID),
            'start_DOY': int(fire.start_DOY),
            'end_DOY': int(fire.end_DOY),
            'duration': int(fire.duration),
            'geometry_wkt': fire.geometry.wkt
        })

    # Convert paths to strings for pickling
    tif_current_str = str(tif_current)
    tif_prev_str = str(tif_prev) if tif_prev.exists() else None

    # Process fires with multiprocessing
    all_results = list(existing_results)  # Start with existing results
    new_results = []
    errors = 0
    start_time = time.time()
    fires_since_save = 0

    # Create worker function with fixed parameters
    worker_func = partial(
        process_fire_worker,
        tif_current_path=tif_current_str,
        tif_prev_path=tif_prev_str,
        current_year=year,
        simplify_tolerance=simplify_tolerance
    )

    # Process in batches for incremental saves
    batch_size = SAVE_INTERVAL
    total_to_process = len(fire_data_list)

    with mp.Pool(processes=num_workers) as pool:
        for batch_start in range(0, total_to_process, batch_size):
            batch_end = min(batch_start + batch_size, total_to_process)
            batch = fire_data_list[batch_start:batch_end]

            # Process batch
            batch_results = pool.map(worker_func, batch)

            # Collect results
            for result_list in batch_results:
                if result_list:
                    new_results.extend(result_list)
                else:
                    errors += 1

            fires_processed = batch_end
            elapsed = time.time() - start_time
            rate = fires_processed / elapsed if elapsed > 0 else 0
            remaining = (total_to_process - fires_processed) / rate if rate > 0 else 0

            print(f"  Processed {fires_processed:,}/{total_to_process:,} "
                  f"({rate:.1f}/sec, ~{remaining/60:.1f} min left, {len(new_results):,} snapshots)")

            # Incremental save
            if new_results:
                combined_results = all_results + new_results
                save_incremental(output_file, combined_results)
                print(f"    [Saved checkpoint: {len(combined_results):,} total snapshots]")

    # Final results
    all_results = all_results + new_results
    elapsed = time.time() - start_time

    print(f"  Completed in {elapsed/60:.1f} minutes")
    print(f"  Total daily snapshots: {len(all_results):,}, Errors: {errors}")

    if not all_results:
        print(f"  No results to save for year {year}")
        return True

    # Final save
    save_incremental(output_file, all_results)

    print(f"  Saved: {output_file.name}")
    print(f"  File size: {output_file.stat().st_size / 1024 / 1024:.2f} MB")

    # Calculate stats
    df = pd.DataFrame(all_results)
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
    parser.add_argument('--workers', type=int, default=None, help='Number of worker processes (default: CPU count - 1)')
    args = parser.parse_args()

    # Paths
    raw_path = Path('C:/Users/Bryan/Desktop/county-map-data/Raw data/global_fire_atlas')
    output_path = Path('C:/Users/Bryan/Desktop/county-map-data/global/wildfires')

    # Determine worker count
    num_workers = args.workers if args.workers else max(1, mp.cpu_count() - 1)

    if args.year:
        # Process single year
        process_year(args.year, raw_path, output_path, args.min_size, args.simplify, args.force, num_workers)
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
        print(f"Workers: {num_workers} (multiprocessing enabled)")
        print(f"Incremental saves: Every {SAVE_INTERVAL} fires")

        total_start = time.time()
        for year in years:
            try:
                process_year(year, raw_path, output_path, args.min_size, args.simplify, args.force, num_workers)
            except Exception as e:
                print(f"  ERROR processing year {year}: {e}")
                traceback.print_exc()
                continue

        total_elapsed = time.time() - total_start
        print(f"\n=== All years complete in {total_elapsed/3600:.1f} hours ===")
    else:
        num_cpus = mp.cpu_count()
        print("Convert Global Fire Atlas to daily fire progression parquet")
        print()
        print("OPTIMIZED VERSION - Features:")
        print(f"  - Multiprocessing: {num_cpus - 1} workers (your system has {num_cpus} CPUs)")
        print(f"  - Incremental saves: Every {SAVE_INTERVAL} fires for crash recovery")
        print("  - Smart resume: Continues from partial files if interrupted")
        print()
        print("Usage:")
        print("  python convert_fire_progression.py --all                  # All years, >= 10 km2")
        print("  python convert_fire_progression.py --all --min-size 15    # All years, >= 15 km2 (recommended)")
        print("  python convert_fire_progression.py --all --workers 4      # Limit to 4 workers")
        print("  python convert_fire_progression.py --year 2024            # Single year")
        print()
        print("Options:")
        print("  --min-size N   Minimum fire size in km2 (default: 10)")
        print("  --workers N    Number of parallel workers (default: CPU count - 1)")
        print("  --force        Reprocess even if output exists (ignores partial progress)")
        print("  --simplify N   Simplification tolerance in degrees (default: 0.005)")
        print()
        print("Estimated times (with multiprocessing):")
        print("  >= 10 km2:  ~1.3M fires, ~2-3 hours")
        print("  >= 15 km2:  ~982K fires, ~1.5-2.5 hours")
        print("  >= 25 km2:  ~473K fires, ~1 hour")
        print("  >= 50 km2:  ~196K fires, ~25 minutes")
        print("  >= 100 km2: ~75K fires,  ~10 minutes")


if __name__ == '__main__':
    # Required for Windows multiprocessing
    mp.freeze_support()
    main()