"""
Download Global Fire Atlas data from NASA/ORNL DAAC via Zenodo.

The Global Fire Atlas contains 13.3 million tracked fire events (2002-2024)
derived from MODIS burned area data, with ignition points, perimeters,
daily progression, spread speed, and direction.

Data Source: https://zenodo.org/records/11400062
Reference: Andela et al. (2019) "The Global Fire Atlas of individual fire size,
           duration, speed and direction", Earth System Science Data

Available Files:
- SHP_ignitions.zip (801.9 MB) - Fire ignition points with metadata
- SHP_perimeters.zip (2.8 GB) - Fire perimeters with summary statistics

Optional Raster Files (GeoTIFF):
- GeoTIFF_day_of_burn.zip (822.6 MB) - Daily burn progression
- GeoTIFF_direction.zip (506.3 MB) - Fire spread direction
- GeoTIFF_speed.zip (1.5 GB) - Fire spread speed
- GeoTIFF_fire_line.zip (737.0 MB) - Fire line density
- GeoTIFF_monthly_summaries.zip (149.7 MB) - Monthly aggregates

Usage:
    python download_global_fire_atlas.py                # Download shapefiles only
    python download_global_fire_atlas.py --all          # Download all files
    python download_global_fire_atlas.py --rasters      # Download raster files too
"""
import requests
import sys
from pathlib import Path
from datetime import datetime
import argparse
import zipfile

# Configuration
ZENODO_RECORD = "11400062"
BASE_URL = f"https://zenodo.org/records/{ZENODO_RECORD}/files"
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/global_fire_atlas")
TIMEOUT = 600  # 10 min timeout for large files

# Available files
SHAPEFILE_DATASETS = {
    'ignitions': {
        'filename': 'SHP_ignitions.zip',
        'size_mb': 802,
        'description': 'Fire ignition points with fire_id, date, location'
    },
    'perimeters': {
        'filename': 'SHP_perimeters.zip',
        'size_mb': 2800,
        'description': 'Fire perimeters with area, duration, spread stats'
    },
}

RASTER_DATASETS = {
    'day_of_burn': {
        'filename': 'GeoTIFF_day_of_burn.zip',
        'size_mb': 823,
        'description': 'Daily burn progression (500m resolution)'
    },
    'direction': {
        'filename': 'GeoTIFF_direction.zip',
        'size_mb': 506,
        'description': 'Fire spread direction'
    },
    'speed': {
        'filename': 'GeoTIFF_speed.zip',
        'size_mb': 1500,
        'description': 'Fire spread speed'
    },
    'fire_line': {
        'filename': 'GeoTIFF_fire_line.zip',
        'size_mb': 737,
        'description': 'Fire line density'
    },
    'monthly': {
        'filename': 'GeoTIFF_monthly_summaries.zip',
        'size_mb': 150,
        'description': 'Monthly aggregates (0.25 degree resolution)'
    },
}


def download_file(filename, force=False):
    """Download a single file from Zenodo."""
    url = f"{BASE_URL}/{filename}?download=1"
    output_path = OUTPUT_DIR / filename

    # Check if already exists
    if output_path.exists() and not force:
        existing_size = output_path.stat().st_size / 1024 / 1024
        print(f"  {filename} already exists ({existing_size:.1f} MB)")
        return output_path

    print(f"  Downloading {filename}...")
    print(f"    URL: {url}")

    try:
        response = requests.get(url, timeout=TIMEOUT, stream=True)
        response.raise_for_status()

        # Get file size
        total_size = int(response.headers.get('content-length', 0))

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # Download with progress
        downloaded = 0
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=65536):  # 64KB chunks
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size:
                        pct = downloaded / total_size * 100
                        mb_done = downloaded / 1024 / 1024
                        mb_total = total_size / 1024 / 1024
                        print(f"\r    Progress: {pct:.1f}% ({mb_done:.1f}/{mb_total:.1f} MB)", end='', flush=True)

        print(f"\n    Saved: {output_path.name} ({output_path.stat().st_size / 1024 / 1024:.1f} MB)")
        return output_path

    except requests.exceptions.RequestException as e:
        print(f"\n    ERROR: {e}")
        return None


def extract_zip(zip_path, extract_dir=None):
    """Extract a zip file."""
    if extract_dir is None:
        extract_dir = zip_path.parent / zip_path.stem

    print(f"  Extracting {zip_path.name}...")

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # List contents
            file_list = zf.namelist()
            print(f"    Contains {len(file_list)} files")

            # Extract
            zf.extractall(extract_dir)
            print(f"    Extracted to: {extract_dir}")

        return extract_dir

    except zipfile.BadZipFile as e:
        print(f"    ERROR: Bad zip file - {e}")
        return None


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Download Global Fire Atlas data from Zenodo',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download shapefile datasets only (ignitions + perimeters)
  python download_global_fire_atlas.py

  # Download all datasets including rasters
  python download_global_fire_atlas.py --all

  # Download specific dataset
  python download_global_fire_atlas.py --dataset ignitions

  # Download and extract
  python download_global_fire_atlas.py --extract

  # Force re-download
  python download_global_fire_atlas.py --force
        """
    )

    parser.add_argument('--all', action='store_true',
                        help='Download all files including rasters (~7.4 GB total)')
    parser.add_argument('--rasters', action='store_true',
                        help='Include raster (GeoTIFF) datasets')
    parser.add_argument('--dataset', type=str,
                        choices=list(SHAPEFILE_DATASETS.keys()) + list(RASTER_DATASETS.keys()),
                        help='Download specific dataset only')
    parser.add_argument('--extract', action='store_true',
                        help='Extract downloaded zip files')
    parser.add_argument('--force', action='store_true',
                        help='Force re-download even if files exist')
    parser.add_argument('--list', action='store_true',
                        help='List available datasets and exit')

    return parser.parse_args()


def main():
    """Main download logic."""
    args = parse_args()

    print("=" * 80)
    print("Global Fire Atlas Downloader")
    print("=" * 80)
    print(f"\nSource: https://zenodo.org/records/{ZENODO_RECORD}")
    print(f"Output: {OUTPUT_DIR}")

    # List mode
    if args.list:
        print("\nShapefile Datasets (for disaster events):")
        for key, info in SHAPEFILE_DATASETS.items():
            print(f"  {key}: {info['filename']} ({info['size_mb']} MB)")
            print(f"         {info['description']}")

        print("\nRaster Datasets (optional, for analysis):")
        for key, info in RASTER_DATASETS.items():
            print(f"  {key}: {info['filename']} ({info['size_mb']} MB)")
            print(f"         {info['description']}")

        total_shp = sum(d['size_mb'] for d in SHAPEFILE_DATASETS.values())
        total_raster = sum(d['size_mb'] for d in RASTER_DATASETS.values())
        print(f"\nTotal shapefile size: ~{total_shp / 1024:.1f} GB")
        print(f"Total raster size: ~{total_raster / 1024:.1f} GB")
        print(f"Grand total: ~{(total_shp + total_raster) / 1024:.1f} GB")
        return 0

    # Determine what to download
    datasets_to_download = {}

    if args.dataset:
        # Single dataset
        if args.dataset in SHAPEFILE_DATASETS:
            datasets_to_download[args.dataset] = SHAPEFILE_DATASETS[args.dataset]
        else:
            datasets_to_download[args.dataset] = RASTER_DATASETS[args.dataset]
    else:
        # Default: shapefiles
        datasets_to_download.update(SHAPEFILE_DATASETS)

        if args.all or args.rasters:
            datasets_to_download.update(RASTER_DATASETS)

    # Calculate total size
    total_mb = sum(d['size_mb'] for d in datasets_to_download.values())
    print(f"\nDatasets to download: {len(datasets_to_download)}")
    print(f"Estimated size: ~{total_mb / 1024:.1f} GB")

    # Confirm large download
    if total_mb > 3000 and not args.force:
        print("\nWARNING: Large download. Use --force to proceed or download specific datasets.")
        print("Proceeding with download...")

    print()

    # Download
    successful = []
    failed = []

    for key, info in datasets_to_download.items():
        filename = info['filename']
        print(f"\n[{key}] {info['description']}")

        result = download_file(filename, force=args.force)

        if result:
            successful.append(key)

            # Extract if requested
            if args.extract:
                extract_zip(result)
        else:
            failed.append(key)

    # Summary
    print("\n" + "=" * 80)
    print("DOWNLOAD COMPLETE")
    print("=" * 80)
    print(f"\nSuccessful: {len(successful)}/{len(datasets_to_download)}")

    if failed:
        print(f"Failed: {failed}")

    print(f"\nOutput directory: {OUTPUT_DIR}")

    # List downloaded files
    if OUTPUT_DIR.exists():
        files = list(OUTPUT_DIR.glob("*.zip"))
        if files:
            print(f"\nDownloaded files ({len(files)}):")
            for f in files:
                size_mb = f.stat().st_size / 1024 / 1024
                print(f"  {f.name} ({size_mb:.1f} MB)")

    print("\nNext steps:")
    print("  python data_converters/converters/convert_global_fire_atlas.py")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
