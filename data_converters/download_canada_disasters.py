"""
Canadian Disaster Database (CDD) Downloader

Downloads disaster event data from Public Safety Canada.
Contains 1000+ natural and technological disasters since 1900.

Usage:
    python download_canada_disasters.py

Output:
    Raw data saved to: county-map-data/Raw data/canada/
    - cdd_disasters.csv (main data)
    - cdd_disasters.kml (geographic data)
    - cdd_metadata.json (download info)

Data Source:
    Public Safety Canada - Canadian Disaster Database
    https://cdd.publicsafety.gc.ca/
    Open Government Portal: https://open.canada.ca/data/en/dataset/1c3d15f9-9cfa-4010-8462-0d67e493d9b9

Coverage:
    - 1000+ disaster events since 1900
    - Natural disasters: floods, storms, wildfires, earthquakes, etc.
    - Technological disasters: industrial accidents, transportation
    - Includes fatalities, injuries, evacuations, and cost estimates
"""

import requests
from pathlib import Path
import json
from datetime import datetime
import sys

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/canada")
TIMEOUT = 120

# Download URLs from Open Government Portal
URLS = {
    "csv": "https://cdd.publicsafety.gc.ca/dl-eng.aspx?cultureCode=en-Ca&normalizedCostYear=1",
    "kml": "http://cdd.publicsafety.gc.ca/CDDService/kml/EventMapLayer?cultureCode=en-Ca&normalizedCostYear=1",
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
        response = requests.get(url, timeout=TIMEOUT, allow_redirects=True)
        response.raise_for_status()

        with open(output_path, 'wb') as f:
            f.write(response.content)

        file_size = output_path.stat().st_size / 1024
        print(f"  Saved: {output_path.name} ({file_size:.1f} KB)")
        return True

    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def download_all():
    """Download all Canadian Disaster Database files."""
    print("=" * 70)
    print("Canadian Disaster Database (CDD) Downloader")
    print("=" * 70)
    print()
    print("Source: Public Safety Canada")
    print("Portal: https://cdd.publicsafety.gc.ca/")
    print()

    setup_output_dir()

    results = {}

    # Download CSV (main data)
    csv_path = RAW_DATA_DIR / "cdd_disasters.csv"
    results["csv"] = download_file(URLS["csv"], csv_path, "CSV data")

    # Download KML (geographic data)
    kml_path = RAW_DATA_DIR / "cdd_disasters.kml"
    results["kml"] = download_file(URLS["kml"], kml_path, "KML geographic data")

    # Save metadata
    metadata = {
        "download_date": datetime.now().isoformat(),
        "source": "Public Safety Canada - Canadian Disaster Database",
        "source_url": "https://cdd.publicsafety.gc.ca/",
        "open_data_portal": "https://open.canada.ca/data/en/dataset/1c3d15f9-9cfa-4010-8462-0d67e493d9b9",
        "license": "Open Government License - Canada",
        "files_downloaded": results,
        "coverage": {
            "start_year": 1900,
            "end_year": "present",
            "events": "1000+ disasters"
        },
        "disaster_types": [
            "Flood",
            "Storm (winter, hurricane, tornado)",
            "Wildfire",
            "Earthquake",
            "Drought",
            "Avalanche",
            "Landslide",
            "Heat wave",
            "Cold wave",
            "Industrial accident",
            "Transportation accident"
        ],
        "notes": [
            "Data includes fatalities, injuries, evacuations, and cost estimates",
            "Costs normalized to current year dollars",
            "KML file contains geographic coordinates for mapping",
            "CSV contains full event details"
        ]
    }

    metadata_path = RAW_DATA_DIR / "cdd_metadata.json"
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
