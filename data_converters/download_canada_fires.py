"""
Canadian National Fire Database (CNFDB) Downloader

Downloads wildfire data from Natural Resources Canada.
Contains fire locations and perimeters from all Canadian provinces/territories.

Usage:
    python download_canada_fires.py

Output:
    Raw data saved to: county-map-data/Raw data/canada/cnfdb/
    - NFDB_point.zip (all fire points shapefile)
    - NFDB_point_large_fires.zip (fires >= 200 hectares)
    - NFDB_point_stats.zip (summary statistics)
    - cnfdb_metadata.json (download info)

Data Source:
    Canadian Wildland Fire Information System (CWFIS)
    Natural Resources Canada - Canadian Forest Service
    https://cwfis.cfs.nrcan.gc.ca/datamart
"""

import requests
from pathlib import Path
import json
from datetime import datetime
import sys

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/canada/cnfdb")
TIMEOUT = 300  # 5 minutes - shapefiles can be large

# Direct download URLs from CWFIS Datamart
URLS = {
    "fire_points": {
        "url": "https://cwfis.cfs.nrcan.gc.ca/downloads/nfdb/fire_pnt/current_version/NFDB_point.zip",
        "description": "All fire point data (shapefile)",
        "filename": "NFDB_point.zip"
    },
    "fire_points_txt": {
        "url": "https://cwfis.cfs.nrcan.gc.ca/downloads/nfdb/fire_pnt/current_version/NFDB_point_txt.zip",
        "description": "All fire point data (text format)",
        "filename": "NFDB_point_txt.zip"
    },
    "large_fires": {
        "url": "https://cwfis.cfs.nrcan.gc.ca/downloads/nfdb/fire_pnt/current_version/NFDB_point_large_fires.zip",
        "description": "Large fires >= 200 hectares (shapefile)",
        "filename": "NFDB_point_large_fires.zip"
    },
    "statistics": {
        "url": "https://cwfis.cfs.nrcan.gc.ca/downloads/nfdb/fire_pnt/current_version/NFDB_point_stats.zip",
        "description": "Summary statistics (Excel)",
        "filename": "NFDB_point_stats.zip"
    }
}

# Also available - fire polygon data (perimeters)
POLYGON_URLS = {
    "fire_polygons": {
        "url": "https://cwfis.cfs.nrcan.gc.ca/downloads/nfdb/fire_poly/current_version/NFDB_poly.zip",
        "description": "Fire perimeter polygons (shapefile)",
        "filename": "NFDB_poly.zip"
    }
}


def setup_output_dir():
    """Create output directory if it doesn't exist."""
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {RAW_DATA_DIR}")


def download_file(url, output_path, description):
    """Download a file from URL with progress."""
    print(f"\nDownloading {description}...")
    print(f"  URL: {url}")

    try:
        response = requests.get(url, timeout=TIMEOUT, stream=True)
        response.raise_for_status()

        # Get file size if available
        total_size = int(response.headers.get('content-length', 0))

        with open(output_path, 'wb') as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    pct = (downloaded / total_size) * 100
                    print(f"\r  Progress: {pct:.1f}% ({downloaded/1024/1024:.1f} MB)", end="")

        print()  # New line after progress
        file_size = output_path.stat().st_size / 1024 / 1024
        print(f"  Saved: {output_path.name} ({file_size:.1f} MB)")
        return True

    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def download_all():
    """Download all Canadian Fire Database files."""
    print("=" * 70)
    print("Canadian National Fire Database (CNFDB) Downloader")
    print("=" * 70)
    print()
    print("Source: Natural Resources Canada - Canadian Forest Service")
    print("Portal: https://cwfis.cfs.nrcan.gc.ca/datamart")
    print()

    setup_output_dir()

    results = {}

    # Download point data files
    print("\n--- Fire Point Data ---")
    for key, info in URLS.items():
        output_path = RAW_DATA_DIR / info["filename"]
        results[key] = download_file(info["url"], output_path, info["description"])

    # Download polygon data
    print("\n--- Fire Polygon Data ---")
    for key, info in POLYGON_URLS.items():
        output_path = RAW_DATA_DIR / info["filename"]
        results[key] = download_file(info["url"], output_path, info["description"])

    # Save metadata
    metadata = {
        "download_date": datetime.now().isoformat(),
        "source": "Natural Resources Canada - Canadian Forest Service",
        "source_url": "https://cwfis.cfs.nrcan.gc.ca/datamart",
        "database_info": "https://cwfis.cfs.nrcan.gc.ca/ha/nfdb",
        "license": "Open Government License - Canada",
        "files_downloaded": {k: {"success": v, **URLS.get(k, POLYGON_URLS.get(k, {}))}
                            for k, v in results.items()},
        "coverage": {
            "spatial": "Canada (all provinces and territories)",
            "temporal": "Historical fire records (varies by province)",
            "contributing_agencies": [
                "Provincial fire management agencies",
                "Territorial fire management agencies",
                "Parks Canada"
            ]
        },
        "data_notes": [
            "Fire point data includes lat/lon, date, cause, size",
            "Large fires >= 200 hectares have polygon perimeters",
            "Data completeness varies by province and year",
            "Not all fires have been mapped - see metadata for gaps",
            "Citation: Canadian Forest Service, Northern Forestry Centre"
        ]
    }

    metadata_path = RAW_DATA_DIR / "cnfdb_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"\nMetadata saved: {metadata_path}")

    # Summary
    print("\n" + "=" * 70)
    print("DOWNLOAD COMPLETE")
    print("=" * 70)
    success = sum(1 for v in results.values() if v)
    print(f"Files downloaded: {success}/{len(results)}")

    # List downloaded files with sizes
    print("\nFiles:")
    for f in RAW_DATA_DIR.glob("*.zip"):
        size = f.stat().st_size / 1024 / 1024
        print(f"  {f.name}: {size:.1f} MB")

    return all(results.values())


def main():
    success = download_all()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
