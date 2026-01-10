"""
Download IBTrACS (International Best Track Archive for Climate Stewardship) data.

IBTrACS merges tropical cyclone data from all regional agencies:
- NHC (Atlantic, East Pacific)
- JTWC (West Pacific, Indian Ocean)
- JMA (West Pacific)
- BOM (Australia)
- IMD (North Indian)
- RSMC Fiji (South Pacific)

Data is provided in CSV format, updated weekly.

Source: https://www.ncei.noaa.gov/products/international-best-track-archive
API: https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/

Usage:
    python download_ibtracs.py                    # Download all data
    python download_ibtracs.py --since 2000       # Download 2000-present
    python download_ibtracs.py --active           # Download only active storms
"""
import requests
import sys
from pathlib import Path
from datetime import datetime
import argparse

# Configuration
BASE_URL = "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv"
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/ibtracs")
TIMEOUT = 300

# Available datasets
DATASETS = {
    'all': 'ibtracs.ALL.list.v04r01.csv',           # All basins, all time (~50MB)
    'since1980': 'ibtracs.since1980.list.v04r01.csv',  # 1980-present (~20MB)
    'last3years': 'ibtracs.last3years.list.v04r01.csv', # Recent 3 years (~3MB)
    'active': 'ibtracs.ACTIVE.list.v04r01.csv',      # Currently active storms
}

# Basin codes
BASINS = {
    'NA': 'North Atlantic',
    'SA': 'South Atlantic',
    'EP': 'East Pacific',
    'WP': 'West Pacific',
    'SP': 'South Pacific',
    'SI': 'South Indian',
    'NI': 'North Indian',
}


def download_dataset(dataset_key='all', force=False):
    """Download IBTrACS dataset."""

    if dataset_key not in DATASETS:
        print(f"Unknown dataset: {dataset_key}")
        print(f"Available: {list(DATASETS.keys())}")
        return None

    filename = DATASETS[dataset_key]
    url = f"{BASE_URL}/{filename}"
    output_path = OUTPUT_DIR / filename

    # Check if already exists
    if output_path.exists() and not force:
        age_hours = (datetime.now().timestamp() - output_path.stat().st_mtime) / 3600
        if age_hours < 24:
            print(f"Using cached {filename} ({age_hours:.1f} hours old)")
            return output_path
        print(f"Cached file is {age_hours:.1f} hours old, re-downloading...")

    print(f"Downloading {filename}...")
    print(f"  URL: {url}")

    try:
        response = requests.get(url, timeout=TIMEOUT, stream=True)
        response.raise_for_status()

        # Get file size
        total_size = int(response.headers.get('content-length', 0))

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # Download with progress
        downloaded = 0
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size:
                        pct = downloaded / total_size * 100
                        print(f"\r  Progress: {pct:.1f}% ({downloaded / 1024 / 1024:.1f} MB)", end='')

        print(f"\n  Saved: {output_path}")
        print(f"  Size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")

        return output_path

    except requests.exceptions.RequestException as e:
        print(f"  ERROR: {e}")
        return None


def show_dataset_info(csv_path):
    """Display info about downloaded dataset."""
    import pandas as pd

    print(f"\nLoading {csv_path.name}...")

    # IBTrACS has a header row and a units row - skip the units row
    df = pd.read_csv(csv_path, skiprows=[1], low_memory=False)

    print(f"\nDataset Info:")
    print(f"  Total rows: {len(df):,}")
    print(f"  Columns: {len(df.columns)}")

    # Count unique storms
    if 'SID' in df.columns:
        storms = df['SID'].nunique()
        print(f"  Unique storms: {storms:,}")

    # Year range
    if 'SEASON' in df.columns:
        print(f"  Year range: {df['SEASON'].min()} - {df['SEASON'].max()}")

    # Basin breakdown
    if 'BASIN' in df.columns:
        print(f"\n  Storms by basin:")
        for basin, count in df.groupby('BASIN')['SID'].nunique().items():
            basin_name = BASINS.get(basin, basin)
            print(f"    {basin} ({basin_name}): {count:,}")

    # Check for wind radii data
    wind_cols = [c for c in df.columns if c.startswith('USA_R') or c.startswith('BOM_R')]
    if wind_cols:
        non_null = df[wind_cols[0]].notna().sum()
        print(f"\n  Wind radii data: {non_null:,} rows ({non_null/len(df)*100:.1f}%)")

    print(f"\nKey columns available:")
    key_cols = ['SID', 'SEASON', 'BASIN', 'NAME', 'ISO_TIME', 'LAT', 'LON',
                'WMO_WIND', 'WMO_PRES', 'USA_WIND', 'USA_PRES', 'USA_SSHS',
                'USA_R34_NE', 'USA_R50_NE', 'USA_R64_NE']
    for col in key_cols:
        if col in df.columns:
            print(f"  {col}")


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Download IBTrACS global tropical cyclone data')

    parser.add_argument('--dataset', type=str, default='all',
                        choices=list(DATASETS.keys()),
                        help='Dataset to download (default: all)')
    parser.add_argument('--since', type=int,
                        help='Only download data since this year (uses since1980 or last3years)')
    parser.add_argument('--active', action='store_true',
                        help='Download only active storms')
    parser.add_argument('--force', action='store_true',
                        help='Force re-download even if cached')
    parser.add_argument('--info', action='store_true',
                        help='Show dataset info after download')

    return parser.parse_args()


def main():
    """Main download logic."""
    args = parse_args()

    print("=" * 60)
    print("IBTrACS Global Tropical Cyclone Downloader")
    print("=" * 60)

    # Determine which dataset to download
    dataset = args.dataset
    if args.active:
        dataset = 'active'
    elif args.since:
        if args.since >= datetime.now().year - 3:
            dataset = 'last3years'
        elif args.since >= 1980:
            dataset = 'since1980'
        else:
            dataset = 'all'

    print(f"\nDataset: {dataset}")
    print(f"Output: {OUTPUT_DIR}")

    # Download
    csv_path = download_dataset(dataset, force=args.force)

    if csv_path and args.info:
        show_dataset_info(csv_path)

    if csv_path:
        print("\n" + "=" * 60)
        print("DOWNLOAD COMPLETE")
        print("=" * 60)
        print(f"\nNext steps:")
        print(f"  1. Run convert_ibtracs.py to process into parquet")
        print(f"  2. Data will be saved to global/tropical_storms/")
    else:
        print("\nDownload failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
