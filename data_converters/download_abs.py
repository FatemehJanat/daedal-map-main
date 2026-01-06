"""
Download Australian Bureau of Statistics Regional Population Data.

Downloads annual population estimates by Local Government Area (LGA)
from the ABS Data API.

Output: Raw data/abs/regional_population_lga.csv

Usage:
    python download_abs.py
"""
import requests
from pathlib import Path
import time
import json

# Configuration
OUTPUT_DIR = Path("C:/Users/bryan/Desktop/county-map-data/Raw data/abs")
TIMEOUT = 180  # 3 minutes

# ABS API endpoint for regional population
# Using the SDMX 2.1 API
ABS_API_BASE = "https://api.data.abs.gov.au"

# Dataset IDs
DATASETS = [
    {
        "id": "ERP_LGA",
        "name": "Estimated Resident Population by LGA",
        "endpoint": "/data/ERP_LGA/1.LGA..A/all",
        "format": "csv",
        "description": "Annual population by Local Government Area (2001-2024)"
    },
]

# Alternative: Direct Excel data cube downloads
EXCEL_DOWNLOADS = [
    {
        "name": "Regional Population 2022-23",
        "url": "https://www.abs.gov.au/statistics/people/population/regional-population/2022-23/32180DS0001_2001-23.xlsx",
        "filename": "regional_population_2001_2023.xlsx"
    },
    {
        "name": "Regional Population by LGA 2024",
        "url": "https://www.abs.gov.au/statistics/people/population/regional-population/latest-release/32180DS0003_2023-24r.xlsx",
        "filename": "regional_population_lga_2024.xlsx"
    },
]


def download_abs():
    """Download ABS regional population datasets."""
    print("=" * 80)
    print("Australian Bureau of Statistics - Regional Population Downloader")
    print("=" * 80)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\nDownloading regional population data")
    print(f"Output directory: {OUTPUT_DIR}")

    success = 0
    failed = []
    skipped = 0

    # Try Excel data cubes (more reliable than API)
    print("\n--- Excel Data Cubes ---")
    for dataset in EXCEL_DOWNLOADS:
        name = dataset["name"]
        url = dataset["url"]
        filename = dataset["filename"]
        output_path = OUTPUT_DIR / filename

        # Skip if already exists
        if output_path.exists():
            size_kb = output_path.stat().st_size / 1024
            print(f"\n  {filename}: Already exists ({size_kb:.1f} KB), skipping")
            skipped += 1
            continue

        print(f"\n  {name}")
        print(f"    Downloading...", end=" ", flush=True)

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) county-map-project'
            }
            response = requests.get(url, timeout=TIMEOUT, stream=True, headers=headers)
            response.raise_for_status()

            # Get content length if available
            total_size = int(response.headers.get('content-length', 0))

            # Download with progress
            downloaded = 0
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = (downloaded / total_size) * 100
                        print(f"\r    Downloading... {pct:.1f}%", end="", flush=True)

            size_kb = output_path.stat().st_size / 1024
            print(f"\r    Downloaded: {size_kb:.1f} KB          ")

            success += 1

            # Rate limiting
            time.sleep(1)

        except requests.exceptions.HTTPError as e:
            print(f"HTTP ERROR: {e.response.status_code}")
            failed.append(filename)
        except requests.exceptions.RequestException as e:
            print(f"ERROR: {e}")
            failed.append(filename)

    # Try API for CSV format
    print("\n--- SDMX API (CSV) ---")
    for dataset in DATASETS:
        ds_id = dataset["id"]
        name = dataset["name"]
        endpoint = dataset["endpoint"]
        output_path = OUTPUT_DIR / f"{ds_id.lower()}.csv"

        # Skip if already exists
        if output_path.exists():
            size_kb = output_path.stat().st_size / 1024
            print(f"\n  {ds_id}: Already exists ({size_kb:.1f} KB), skipping")
            skipped += 1
            continue

        print(f"\n  {ds_id}: {name}")
        url = f"{ABS_API_BASE}{endpoint}?format=csv"
        print(f"    URL: {url[:80]}...")
        print(f"    Downloading...", end=" ", flush=True)

        try:
            headers = {
                'Accept': 'text/csv',
                'User-Agent': 'county-map-project'
            }
            response = requests.get(url, timeout=TIMEOUT, headers=headers)
            response.raise_for_status()

            with open(output_path, 'wb') as f:
                f.write(response.content)

            size_kb = output_path.stat().st_size / 1024
            print(f"OK ({size_kb:.1f} KB)")

            success += 1

        except requests.exceptions.HTTPError as e:
            print(f"HTTP ERROR: {e.response.status_code}")
            failed.append(ds_id)
        except requests.exceptions.RequestException as e:
            print(f"ERROR: {e}")
            failed.append(ds_id)

    # Summary
    print("\n" + "=" * 80)
    print("DOWNLOAD COMPLETE")
    print("=" * 80)
    print(f"  Successful: {success}")
    print(f"  Skipped (existing): {skipped}")
    print(f"  Failed: {len(failed)}")

    if failed:
        print(f"  Failed datasets: {failed}")
        print("\n  Note: ABS data may require manual download from:")
        print("  https://www.abs.gov.au/statistics/people/population/regional-population")

    # List files
    files = list(OUTPUT_DIR.glob("*.xlsx")) + list(OUTPUT_DIR.glob("*.csv"))
    if files:
        total_size = sum(f.stat().st_size for f in files)
        print(f"\nTotal files: {len(files)}")
        print(f"Total size: {total_size / (1024*1024):.2f} MB")

        for f in sorted(files):
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"  {f.name}: {size_mb:.2f} MB")

    print(f"\nSource: Australian Bureau of Statistics")
    print(f"Download date: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    return 0 if not failed else 1


if __name__ == "__main__":
    import sys
    sys.exit(download_abs())
