"""
Download EPA AQS Annual AQI by County data (1980-2025).

Downloads pre-generated annual AQI summary files from EPA's Air Quality System.
46 years of county-level air quality data.

Output: Raw data/epa_aqs/annual_aqi_by_county_[YEAR].csv

Usage:
    python download_epa_aqs.py
"""
import requests
from pathlib import Path
import zipfile
import io
import time

# Configuration
OUTPUT_DIR = Path("C:/Users/bryan/Desktop/county-map-data/Raw data/epa_aqs")
BASE_URL = "https://aqs.epa.gov/aqsweb/airdata"
START_YEAR = 1980
END_YEAR = 2025
TIMEOUT = 60

def download_aqi_files():
    """Download annual AQI by county files for all years."""
    print("=" * 80)
    print("EPA AQS - Annual AQI by County Downloader")
    print("=" * 80)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    years = list(range(START_YEAR, END_YEAR + 1))
    print(f"\nDownloading {len(years)} years: {START_YEAR}-{END_YEAR}")
    print(f"Output directory: {OUTPUT_DIR}")

    success = 0
    failed = []
    skipped = 0

    for year in years:
        filename = f"annual_aqi_by_county_{year}.zip"
        url = f"{BASE_URL}/{filename}"
        csv_path = OUTPUT_DIR / f"annual_aqi_by_county_{year}.csv"

        # Skip if already downloaded
        if csv_path.exists():
            print(f"  {year}: Already exists, skipping")
            skipped += 1
            continue

        print(f"  {year}: Downloading...", end=" ", flush=True)

        try:
            response = requests.get(url, timeout=TIMEOUT)
            response.raise_for_status()

            # Extract CSV from zip
            with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
                # Get the CSV file inside
                csv_names = [n for n in zf.namelist() if n.endswith('.csv')]
                if csv_names:
                    csv_content = zf.read(csv_names[0])
                    with open(csv_path, 'wb') as f:
                        f.write(csv_content)

                    size_kb = len(csv_content) / 1024
                    print(f"OK ({size_kb:.1f} KB)")
                    success += 1
                else:
                    print("ERROR: No CSV in zip")
                    failed.append(year)

            # Rate limiting - be nice to EPA servers
            time.sleep(0.5)

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                print(f"NOT FOUND (year may not exist)")
            else:
                print(f"HTTP ERROR: {e.response.status_code}")
            failed.append(year)
        except requests.exceptions.RequestException as e:
            print(f"ERROR: {e}")
            failed.append(year)
        except zipfile.BadZipFile:
            print("ERROR: Invalid zip file")
            failed.append(year)

    # Summary
    print("\n" + "=" * 80)
    print("DOWNLOAD COMPLETE")
    print("=" * 80)
    print(f"  Successful: {success}")
    print(f"  Skipped (existing): {skipped}")
    print(f"  Failed: {len(failed)}")

    if failed:
        print(f"  Failed years: {failed}")

    # List files
    files = sorted(OUTPUT_DIR.glob("*.csv"))
    total_size = sum(f.stat().st_size for f in files)
    print(f"\nTotal files: {len(files)}")
    print(f"Total size: {total_size / (1024*1024):.2f} MB")

    return 0 if not failed else 1


if __name__ == "__main__":
    import sys
    sys.exit(download_aqi_files())
