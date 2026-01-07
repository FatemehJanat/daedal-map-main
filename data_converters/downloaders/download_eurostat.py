"""
Download Eurostat Regional Population Data (NUTS 3 level).

Downloads population data at NUTS 3 level (small regions) for EU countries.
Covers 1,165+ regions from 1990 to present.

Output: Raw data/eurostat/demo_r_gind3.tsv.gz (population by NUTS 3)

Usage:
    python download_eurostat.py
"""
import requests
from pathlib import Path
import time
import gzip

# Configuration
OUTPUT_DIR = Path("C:/Users/bryan/Desktop/county-map-data/Raw data/eurostat")
TIMEOUT = 300  # 5 minutes for large files

# Eurostat bulk download URLs
# Format: TSV.GZ files from the bulk download listing
DATASETS = [
    # Population datasets
    {
        "code": "demo_r_gind3",
        "name": "Population change - NUTS 3 regions",
        "url": "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/demo_r_gind3/?format=TSV&compressed=true"
    },
    {
        "code": "demo_r_d3avg",
        "name": "Average population - NUTS 3 regions",
        "url": "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/demo_r_d3avg/?format=TSV&compressed=true"
    },
    # GDP datasets (smaller, for reference)
    {
        "code": "nama_10r_3gdp",
        "name": "GDP at NUTS 3 level",
        "url": "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/nama_10r_3gdp/?format=TSV&compressed=true"
    },
]


def download_eurostat():
    """Download Eurostat regional datasets."""
    print("=" * 80)
    print("Eurostat Regional Statistics Downloader")
    print("=" * 80)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\nDownloading {len(DATASETS)} datasets")
    print(f"Output directory: {OUTPUT_DIR}")

    success = 0
    failed = []
    skipped = 0

    for dataset in DATASETS:
        code = dataset["code"]
        name = dataset["name"]
        url = dataset["url"]
        output_path = OUTPUT_DIR / f"{code}.tsv.gz"

        # Skip if already exists
        if output_path.exists():
            size_kb = output_path.stat().st_size / 1024
            print(f"\n  {code}: Already exists ({size_kb:.1f} KB), skipping")
            skipped += 1
            continue

        print(f"\n  {code}: {name}")
        print(f"    Downloading...", end=" ", flush=True)

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

            size_kb = output_path.stat().st_size / 1024
            print(f"\r    Downloaded: {size_kb:.1f} KB          ")

            # Quick preview of data
            try:
                with gzip.open(output_path, 'rt', encoding='utf-8') as f:
                    header = f.readline().strip()
                    # Count columns (years)
                    cols = header.split('\t')
                    year_cols = [c for c in cols if c.strip().isdigit()]
                    print(f"    Years available: {min(year_cols) if year_cols else 'N/A'}-{max(year_cols) if year_cols else 'N/A'}")

                    # Count regions (lines)
                    line_count = sum(1 for _ in f)
                    print(f"    Regions: ~{line_count:,}")
            except Exception as e:
                print(f"    (Could not preview: {e})")

            success += 1

            # Rate limiting
            time.sleep(1)

        except requests.exceptions.HTTPError as e:
            print(f"HTTP ERROR: {e.response.status_code}")
            failed.append(code)
        except requests.exceptions.RequestException as e:
            print(f"ERROR: {e}")
            failed.append(code)

    # Summary
    print("\n" + "=" * 80)
    print("DOWNLOAD COMPLETE")
    print("=" * 80)
    print(f"  Successful: {success}")
    print(f"  Skipped (existing): {skipped}")
    print(f"  Failed: {len(failed)}")

    if failed:
        print(f"  Failed datasets: {failed}")

    # List files
    files = sorted(OUTPUT_DIR.glob("*.tsv.gz"))
    total_size = sum(f.stat().st_size for f in files)
    print(f"\nTotal files: {len(files)}")
    print(f"Total size: {total_size / 1024:.1f} KB")

    for f in files:
        size_kb = f.stat().st_size / 1024
        print(f"  {f.name}: {size_kb:.1f} KB")

    print(f"\nSource: Eurostat (European Commission)")
    print(f"Download date: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    return 0 if not failed else 1


if __name__ == "__main__":
    import sys
    sys.exit(download_eurostat())
