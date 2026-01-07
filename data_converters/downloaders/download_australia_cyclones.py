"""
Australian Tropical Cyclone Database Downloader

Downloads tropical cyclone track data from the Australian Bureau of Meteorology.
Includes all recorded cyclones in the Australian region since 1909.

Usage:
    python download_australia_cyclones.py

Output:
    Raw data saved to: county-map-data/Raw data/australia/
    - IDCKMSTM0S.csv (best track database)
    - OTCR_database.csv (reanalysis 1981-2016)
    - australia_cyclones_metadata.json

Data Source:
    Bureau of Meteorology - Australian Government
    https://www.bom.gov.au/cyclone/tropical-cyclone-knowledge-centre/databases/

Coverage:
    - Tropical cyclone tracks from 1909 to present
    - Australian region (90E-160E, 0-40S)
    - Position, intensity, pressure, wind speed
"""

import requests
from pathlib import Path
import json
from datetime import datetime
import sys

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/australia")
TIMEOUT = 120

# Download URLs
URLS = {
    "best_track": {
        "url": "http://www.bom.gov.au/clim_data/IDCKMSTM0S.csv",
        "filename": "IDCKMSTM0S.csv",
        "description": "Best Track Database (1909-present)"
    },
    "otcr": {
        "url": "http://www.bom.gov.au/cyclone/history/database/OTCR_alldata.csv",
        "filename": "OTCR_database.csv",
        "description": "Objective Tropical Cyclone Reanalysis (1981-2016)"
    }
}


def setup_output_dir():
    """Create output directory if it doesn't exist."""
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {RAW_DATA_DIR}")


def download_file(url, output_path, description):
    """Download a file from URL."""
    print(f"\nDownloading {description}...")
    print(f"  URL: {url}")

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; DisasterDataCollector/1.0)'
        }
        response = requests.get(url, timeout=TIMEOUT, allow_redirects=True, headers=headers)
        response.raise_for_status()

        with open(output_path, 'wb') as f:
            f.write(response.content)

        file_size = output_path.stat().st_size / 1024
        print(f"  Saved: {output_path.name} ({file_size:.1f} KB)")
        return True

    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def count_csv_records(csv_path):
    """Count records in CSV."""
    try:
        with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        return max(0, len(lines) - 1)
    except Exception as e:
        return 0


def download_all():
    """Download all Australian cyclone database files."""
    print("=" * 70)
    print("Australian Tropical Cyclone Database Downloader")
    print("=" * 70)
    print()
    print("Source: Bureau of Meteorology - Australian Government")
    print("Portal: https://www.bom.gov.au/cyclone/tropical-cyclone-knowledge-centre/databases/")
    print()

    setup_output_dir()

    results = {}

    # Download each file
    for key, info in URLS.items():
        output_path = RAW_DATA_DIR / info["filename"]
        success = download_file(info["url"], output_path, info["description"])
        record_count = count_csv_records(output_path) if success else 0
        results[key] = {
            "success": success,
            "records": record_count,
            "file": info["filename"] if success else None
        }

    # Save metadata
    metadata = {
        "download_date": datetime.now().isoformat(),
        "source": "Bureau of Meteorology - Australian Government",
        "source_url": "https://www.bom.gov.au/cyclone/tropical-cyclone-knowledge-centre/databases/",
        "license": "Creative Commons Attribution (CC BY 4.0)",
        "files_downloaded": results,
        "coverage": {
            "best_track": {
                "start_year": 1909,
                "end_year": "present",
                "region": "Australian region (90E-160E, 0-40S)"
            },
            "otcr": {
                "start_year": 1981,
                "end_year": 2016,
                "description": "Objective reanalysis with improved intensity estimates"
            }
        },
        "data_fields": [
            "Cyclone ID",
            "Name",
            "Date/Time",
            "Latitude",
            "Longitude",
            "Central Pressure (hPa)",
            "Maximum Wind Speed (knots)",
            "Category"
        ],
        "notes": [
            "Best track data updated regularly",
            "OTCR provides improved historical intensity estimates",
            "Position data available at 6-hourly intervals",
            "Pre-satellite era (before 1970s) data has higher uncertainty"
        ]
    }

    metadata_path = RAW_DATA_DIR / "australia_cyclones_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"\nMetadata saved: {metadata_path}")

    # Summary
    print("\n" + "=" * 70)
    print("DOWNLOAD COMPLETE")
    print("=" * 70)
    success = sum(1 for v in results.values() if v.get("success"))
    print(f"Files downloaded: {success}/{len(results)}")

    for key, result in results.items():
        if result.get("success"):
            print(f"  {key}: {result['records']} records")

    return any(v.get("success") for v in results.values())


def main():
    success = download_all()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
