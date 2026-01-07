"""
Download Statistics Canada Census Population Data.

Downloads population and dwelling counts by census subdivision (municipality)
for census years 2001-2021.

Output: Raw data/statcan/population_[YEAR].csv

Usage:
    python download_statcan.py
"""
import requests
from pathlib import Path
import time
import zipfile
import io

# Configuration
OUTPUT_DIR = Path("C:/Users/bryan/Desktop/county-map-data/Raw data/statcan")
TIMEOUT = 180  # 3 minutes

# Statistics Canada census profile downloads
# These are population and dwelling count tables by geography
# Source: https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/index.cfm
DATASETS = [
    {
        "year": 2021,
        "name": "2021 Census - Population and Dwelling Counts",
        "url": "https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/details/download-telecharger/comp/GetFile.cfm?Lang=E&FILETYPE=CSV&GEONO=044",
        "filename": "population_2021.csv"
    },
    {
        "year": 2016,
        "name": "2016 Census - Population and Dwelling Counts",
        "url": "https://www12.statcan.gc.ca/census-recensement/2016/dp-pd/prof/details/download-telecharger/comp/GetFile.cfm?Lang=E&FILETYPE=CSV&GEONO=044",
        "filename": "population_2016.csv"
    },
    {
        "year": 2011,
        "name": "2011 Census - Population and Dwelling Counts",
        "url": "https://www12.statcan.gc.ca/census-recensement/2011/dp-pd/prof/details/download-telecharger/comp/GetFile.cfm?Lang=E&FILETYPE=CSV&GEONO=044",
        "filename": "population_2011.csv"
    },
]

# Alternative: Open Data Portal bulk downloads
ALT_DATASETS = [
    {
        "year": 2021,
        "name": "Census Profile 2021 - Canada, provinces, territories, CDs, CSDs",
        "url": "https://www150.statcan.gc.ca/n1/tbl/csv/98100001-eng.zip",
        "filename": "census_profile_2021.zip"
    },
]


def download_statcan():
    """Download Statistics Canada population datasets."""
    print("=" * 80)
    print("Statistics Canada Census Population Downloader")
    print("=" * 80)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\nAttempting to download census population data")
    print(f"Output directory: {OUTPUT_DIR}")

    success = 0
    failed = []
    skipped = 0

    # Try primary datasets first
    all_datasets = DATASETS + ALT_DATASETS

    for dataset in all_datasets:
        year = dataset.get("year", "")
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

        print(f"\n  {year}: {name}")
        print(f"    URL: {url[:80]}...")
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
            content = b''
            for chunk in response.iter_content(chunk_size=8192):
                content += chunk
                downloaded += len(chunk)
                if total_size > 0:
                    pct = (downloaded / total_size) * 100
                    print(f"\r    Downloading... {pct:.1f}%", end="", flush=True)

            # Handle ZIP files
            if filename.endswith('.zip'):
                with open(output_path, 'wb') as f:
                    f.write(content)
            else:
                with open(output_path, 'wb') as f:
                    f.write(content)

            size_kb = output_path.stat().st_size / 1024
            print(f"\r    Downloaded: {size_kb:.1f} KB          ")

            success += 1

            # Rate limiting
            time.sleep(2)

        except requests.exceptions.HTTPError as e:
            print(f"HTTP ERROR: {e.response.status_code}")
            failed.append(filename)
        except requests.exceptions.RequestException as e:
            print(f"ERROR: {e}")
            failed.append(filename)

    # Summary
    print("\n" + "=" * 80)
    print("DOWNLOAD COMPLETE")
    print("=" * 80)
    print(f"  Successful: {success}")
    print(f"  Skipped (existing): {skipped}")
    print(f"  Failed: {len(failed)}")

    if failed:
        print(f"  Failed datasets: {failed}")
        print("\n  Note: Statistics Canada downloads may require browser access.")
        print("  Manual download available at:")
        print("  https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/index.cfm")

    # List files
    files = list(OUTPUT_DIR.glob("*.csv")) + list(OUTPUT_DIR.glob("*.zip"))
    if files:
        total_size = sum(f.stat().st_size for f in files)
        print(f"\nTotal files: {len(files)}")
        print(f"Total size: {total_size / (1024*1024):.2f} MB")

        for f in sorted(files):
            size_kb = f.stat().st_size / 1024
            print(f"  {f.name}: {size_kb:.1f} KB")

    print(f"\nSource: Statistics Canada")
    print(f"Download date: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    return 0 if not failed else 1


if __name__ == "__main__":
    import sys
    sys.exit(download_statcan())
