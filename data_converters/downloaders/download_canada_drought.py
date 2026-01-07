"""
Canadian Drought Monitor (CDM) Downloader

Downloads drought area GeoJSON data from Agriculture Canada.
Monthly drought polygons at 5 severity levels (D0-D4), similar to US Drought Monitor.

Usage:
    python download_canada_drought.py              # Download all years
    python download_canada_drought.py --year 2024  # Download single year
    python download_canada_drought.py --test       # Test with one month

Output:
    Raw data saved to: county-map-data/Raw data/canada/drought/
    - {year}/CDM_{YYMM}_D{0-4}_LR.geojson
    - cdm_metadata.json

Data Source:
    Agriculture and Agri-Food Canada
    https://agriculture.canada.ca/atlas/data_donnees/canadianDroughtMonitor/

Drought Severity Levels:
    D0 = Abnormally Dry
    D1 = Moderate Drought
    D2 = Severe Drought
    D3 = Extreme Drought
    D4 = Exceptional Drought
"""

import requests
from pathlib import Path
import json
from datetime import datetime
import sys
import argparse
import time

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/canada/drought")
TIMEOUT = 60
BASE_URL = "https://agriculture.canada.ca/atlas/data_donnees/canadianDroughtMonitor/data_donnees/geoJSON/areasofDrought"

# Available years
YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
MONTHS = list(range(1, 13))  # 1-12
SEVERITY_LEVELS = [0, 1, 2, 3, 4]  # D0-D4


def setup_output_dir():
    """Create output directory if it doesn't exist."""
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {RAW_DATA_DIR}")


def download_month(year, month):
    """Download all severity levels for a given month."""
    yy = str(year)[2:]  # Last 2 digits of year
    mm = str(month).zfill(2)
    folder_name = f"cdm_{yy}{mm}_drought_areas"

    results = {}

    for d in SEVERITY_LEVELS:
        filename = f"CDM_{yy}{mm}_D{d}_LR.geojson"
        url = f"{BASE_URL}/{year}/{folder_name}/{filename}"

        output_dir = RAW_DATA_DIR / str(year)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename

        try:
            response = requests.get(url, timeout=TIMEOUT)
            if response.status_code == 200:
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                size = len(response.content) / 1024
                results[f"D{d}"] = {"success": True, "size_kb": size}
            elif response.status_code == 404:
                results[f"D{d}"] = {"success": False, "error": "not found"}
            else:
                results[f"D{d}"] = {"success": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            results[f"D{d}"] = {"success": False, "error": str(e)}

    return results


def download_year(year):
    """Download all months for a given year."""
    print(f"\n--- Year {year} ---")
    year_results = {}

    for month in MONTHS:
        month_name = datetime(year, month, 1).strftime("%b")
        print(f"  {month_name} {year}...", end=" ")

        results = download_month(year, month)
        success_count = sum(1 for r in results.values() if r.get("success"))
        print(f"D0-D4: {success_count}/5 files")

        year_results[f"{year}-{str(month).zfill(2)}"] = results
        time.sleep(0.2)  # Be nice to server

    return year_results


def download_all(years=None):
    """Download all Canadian Drought Monitor data."""
    print("=" * 70)
    print("Canadian Drought Monitor (CDM) Downloader")
    print("=" * 70)
    print()
    print("Source: Agriculture and Agri-Food Canada")
    print(f"URL: {BASE_URL}")
    print()

    setup_output_dir()

    if years is None:
        years = YEARS

    all_results = {}
    total_files = 0

    for year in years:
        year_results = download_year(year)
        all_results[str(year)] = year_results

        # Count successful downloads
        for month_results in year_results.values():
            total_files += sum(1 for r in month_results.values() if r.get("success"))

    # Save metadata
    metadata = {
        "download_date": datetime.now().isoformat(),
        "source": "Agriculture and Agri-Food Canada",
        "source_url": "https://agriculture.canada.ca/atlas/data_donnees/canadianDroughtMonitor/",
        "license": "Open Government License - Canada",
        "years_downloaded": years,
        "total_files": total_files,
        "severity_levels": {
            "D0": "Abnormally Dry",
            "D1": "Moderate Drought",
            "D2": "Severe Drought",
            "D3": "Extreme Drought",
            "D4": "Exceptional Drought"
        },
        "file_pattern": "CDM_{YYMM}_D{0-4}_LR.geojson",
        "notes": [
            "Monthly drought area polygons for Canada",
            "Similar to US Drought Monitor (USDM) severity scale",
            "GeoJSON format with polygon geometries",
            "Some months may not have all severity levels (no drought at that level)"
        ],
        "results_by_year": all_results
    }

    metadata_path = RAW_DATA_DIR / "cdm_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    # Summary
    print("\n" + "=" * 70)
    print("DOWNLOAD COMPLETE")
    print("=" * 70)
    print(f"Years: {years}")
    print(f"Total files downloaded: {total_files}")
    print(f"Metadata saved: {metadata_path}")

    # Calculate total size
    total_size = 0
    for year_dir in RAW_DATA_DIR.iterdir():
        if year_dir.is_dir():
            for f in year_dir.glob("*.geojson"):
                total_size += f.stat().st_size
    print(f"Total size: {total_size / 1024 / 1024:.1f} MB")

    return total_files > 0


def main():
    parser = argparse.ArgumentParser(description="Download Canadian Drought Monitor data")
    parser.add_argument("--year", type=int, help="Download single year")
    parser.add_argument("--test", action="store_true", help="Test with Jan 2024 only")
    args = parser.parse_args()

    setup_output_dir()

    if args.test:
        print("Test mode: Downloading January 2024")
        results = download_month(2024, 1)
        for level, result in results.items():
            status = "OK" if result.get("success") else f"FAIL: {result.get('error')}"
            print(f"  {level}: {status}")
        return 0 if any(r.get("success") for r in results.values()) else 1
    elif args.year:
        success = download_all([args.year])
        return 0 if success else 1
    else:
        success = download_all()
        return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
