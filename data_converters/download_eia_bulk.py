"""
Download EIA Bulk Data files.

Downloads bulk data files from the Energy Information Administration.
Includes SEDS (State Energy Data System), Electricity, Natural Gas, etc.

Output: Raw data/eia/[dataset].zip

Usage:
    python download_eia_bulk.py
"""
import requests
from pathlib import Path
import time

# Configuration
OUTPUT_DIR = Path("C:/Users/bryan/Desktop/county-map-data/Raw data/eia")
BASE_URL = "https://api.eia.gov/bulk"
TIMEOUT = 300  # 5 minutes for large files

# Priority datasets (most useful for state-level analysis)
DATASETS = [
    ("SEDS", "State Energy Data System - consumption, production, prices"),
    ("ELEC", "Electricity - generation, capacity, sales"),
    ("NG", "Natural Gas - production, consumption, prices"),
    ("PET", "Petroleum - production, imports, exports"),
    ("COAL", "Coal - production, consumption, prices"),
    ("EMISS", "CO2 Emissions by state and sector"),
    ("TOTAL", "Total Energy - monthly/annual summaries"),
]

def download_eia_bulk():
    """Download EIA bulk data files."""
    print("=" * 80)
    print("EIA Bulk Data Downloader")
    print("=" * 80)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\nDownloading {len(DATASETS)} datasets")
    print(f"Output directory: {OUTPUT_DIR}")
    print("\nNote: These files can be large (100+ MB each)")

    success = 0
    failed = []
    skipped = 0

    for dataset_id, description in DATASETS:
        filename = f"{dataset_id}.zip"
        url = f"{BASE_URL}/{filename}"
        output_path = OUTPUT_DIR / filename

        # Skip if already exists
        if output_path.exists():
            size_mb = output_path.stat().st_size / (1024 * 1024)
            print(f"\n  {dataset_id}: Already exists ({size_mb:.1f} MB), skipping")
            skipped += 1
            continue

        print(f"\n  {dataset_id}: {description}")
        print(f"    Downloading from {url}...", end=" ", flush=True)

        try:
            response = requests.get(url, timeout=TIMEOUT, stream=True)
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

            size_mb = output_path.stat().st_size / (1024 * 1024)
            print(f"\r    Downloaded: {size_mb:.1f} MB          ")
            success += 1

            # Rate limiting
            time.sleep(1)

        except requests.exceptions.HTTPError as e:
            print(f"HTTP ERROR: {e.response.status_code}")
            failed.append(dataset_id)
        except requests.exceptions.RequestException as e:
            print(f"ERROR: {e}")
            failed.append(dataset_id)

    # Summary
    print("\n" + "=" * 80)
    print("DOWNLOAD COMPLETE")
    print("=" * 80)
    print(f"  Successful: {success}")
    print(f"  Skipped (existing): {skipped}")
    print(f"  Failed: {len(failed)}")

    if failed:
        print(f"  Failed datasets: {failed}")

    # List files and total size
    files = sorted(OUTPUT_DIR.glob("*.zip"))
    total_size = sum(f.stat().st_size for f in files)
    print(f"\nTotal files: {len(files)}")
    print(f"Total size: {total_size / (1024*1024):.2f} MB")

    for f in files:
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"  {f.name}: {size_mb:.1f} MB")

    return 0 if not failed else 1


if __name__ == "__main__":
    import sys
    sys.exit(download_eia_bulk())
