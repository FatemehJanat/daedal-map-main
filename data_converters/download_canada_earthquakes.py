"""
Canadian Earthquake Database Downloader

Downloads earthquake event data from Natural Resources Canada (NRCan).
Contains historical earthquakes from 1985 onward with magnitude, location, depth.

Usage:
    python download_canada_earthquakes.py

Output:
    Raw data saved to: county-map-data/Raw data/canada/
    - eqarchive-en.csv (main earthquake catalog)
    - earthquakes_en.gdb.zip (geodatabase format)
    - canada_earthquakes_metadata.json (download info)

Data Source:
    Natural Resources Canada - Earthquakes Canada
    https://www.earthquakescanada.nrcan.gc.ca/
    Open Data Portal: https://open.canada.ca/data/en/dataset/4cedd37e-0023-41fe-8eff-bea45385e469

Coverage:
    - Earthquakes from 1985 onward (some records back to 1600s)
    - Magnitude, depth, location coordinates
    - Includes both felt and instrumental earthquakes
"""

import requests
from pathlib import Path
import json
from datetime import datetime
import sys

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/canada")
TIMEOUT = 180

# Download URLs from Open Government Portal
URLS = {
    "csv": {
        "url": "https://ftp.maps.canada.ca/pub/nrcan_rncan/Earthquakes_Tremblement-de-terre/canadian-earthquakes_tremblements-de-terre-canadien/eqarchive-en.csv",
        "filename": "eqarchive-en.csv",
        "description": "Earthquake catalog CSV (English)"
    },
    "gdb": {
        "url": "https://ftp.maps.canada.ca/pub/nrcan_rncan/Earthquakes_Tremblement-de-terre/canadian-earthquakes_tremblements-de-terre-canadien/earthquakes_en.gdb.zip",
        "filename": "earthquakes_en.gdb.zip",
        "description": "Earthquake geodatabase (English)"
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
        response = requests.get(url, timeout=TIMEOUT, allow_redirects=True, stream=True)
        response.raise_for_status()

        # Get content length if available
        total_size = int(response.headers.get('content-length', 0))

        with open(output_path, 'wb') as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = (downloaded / total_size) * 100
                        print(f"\r  Progress: {downloaded/1024:.0f} KB / {total_size/1024:.0f} KB ({pct:.1f}%)", end='')

        file_size = output_path.stat().st_size / 1024
        print(f"\n  Saved: {output_path.name} ({file_size:.1f} KB)")
        return True

    except Exception as e:
        print(f"\n  ERROR: {e}")
        return False


def count_csv_records(csv_path):
    """Count records and get sample of CSV."""
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            lines = f.readlines()

        # Get header
        header = lines[0].strip() if lines else ""

        # Count non-empty data lines
        record_count = sum(1 for line in lines[1:] if line.strip())

        return record_count, header
    except Exception as e:
        print(f"  Error counting records: {e}")
        return 0, ""


def download_all():
    """Download all Canadian Earthquake Database files."""
    print("=" * 70)
    print("Canadian Earthquake Database Downloader")
    print("=" * 70)
    print()
    print("Source: Natural Resources Canada - Earthquakes Canada")
    print("Portal: https://open.canada.ca/data/en/dataset/4cedd37e-0023-41fe-8eff-bea45385e469")
    print()

    setup_output_dir()

    results = {}

    # Download each file
    for key, info in URLS.items():
        output_path = RAW_DATA_DIR / info["filename"]
        results[key] = download_file(info["url"], output_path, info["description"])

    # Get record count from CSV
    csv_path = RAW_DATA_DIR / URLS["csv"]["filename"]
    record_count = 0
    csv_header = ""
    if csv_path.exists():
        record_count, csv_header = count_csv_records(csv_path)
        print(f"\nCSV contains {record_count:,} earthquake records")

    # Save metadata
    metadata = {
        "download_date": datetime.now().isoformat(),
        "source": "Natural Resources Canada - Earthquakes Canada",
        "source_url": "https://www.earthquakescanada.nrcan.gc.ca/",
        "open_data_portal": "https://open.canada.ca/data/en/dataset/4cedd37e-0023-41fe-8eff-bea45385e469",
        "license": "Open Government License - Canada",
        "files_downloaded": results,
        "record_count": record_count,
        "csv_columns": csv_header.split(",") if csv_header else [],
        "coverage": {
            "start_year": 1985,
            "end_year": "present",
            "historical_records": "Some events back to 1600s"
        },
        "data_fields": [
            "Date/Time (UTC)",
            "Latitude",
            "Longitude",
            "Depth (km)",
            "Magnitude",
            "Magnitude Type",
            "Location Description"
        ],
        "notes": [
            "Instrumental records from 1985 onward",
            "Historical felt earthquakes back to 1600s",
            "Coordinates in decimal degrees (WGS84)",
            "GDB file contains same data with geometry"
        ]
    }

    metadata_path = RAW_DATA_DIR / "canada_earthquakes_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"\nMetadata saved: {metadata_path}")

    # Summary
    print("\n" + "=" * 70)
    print("DOWNLOAD COMPLETE")
    print("=" * 70)
    success = sum(1 for v in results.values() if v)
    print(f"Files downloaded: {success}/{len(results)}")

    if csv_path.exists():
        # Quick preview of CSV
        print("\nCSV Preview (first 5 lines):")
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            for i, line in enumerate(f):
                if i >= 5:
                    break
                print(f"  {line.strip()[:100]}...")

    return all(results.values())


def main():
    success = download_all()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
