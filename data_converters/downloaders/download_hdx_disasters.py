"""
HDX (Humanitarian Data Exchange) Disaster Data Downloader

Downloads disaster-related datasets from HDX/OCHA including:
- EM-DAT country profiles
- GDACS alerts
- ReliefWeb disasters
- Country-specific emergency data

Usage:
    python download_hdx_disasters.py

Output:
    Raw data saved to: county-map-data/Raw data/hdx/
    - emdat_country_profiles.xlsx
    - Various country and regional disaster files
    - hdx_metadata.json

Data Source:
    Humanitarian Data Exchange (HDX) - UN OCHA
    https://data.humdata.org/

Coverage:
    - 254 locations globally
    - Natural disasters, conflicts, humanitarian crises
    - Various temporal coverage depending on dataset
"""

import requests
from pathlib import Path
import json
from datetime import datetime
import sys
import time

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/hdx")
TIMEOUT = 120

# HDX API base URL
HDX_API_BASE = "https://data.humdata.org/api/3/action"

# Key datasets to download
DATASETS = {
    "emdat_profiles": {
        "package_id": "emdat-country-profiles",
        "description": "EM-DAT aggregated natural disaster statistics by country"
    },
    "reliefweb_disasters": {
        "package_id": "reliefweb-disasters",
        "description": "ReliefWeb disaster list since 1981"
    },
    "gdacs_events": {
        "package_id": "gdacs-events",
        "description": "GDACS global disaster alerts"
    }
}


def setup_output_dir():
    """Create output directory if it doesn't exist."""
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {RAW_DATA_DIR}")


def get_dataset_resources(package_id):
    """Get download URLs for a dataset from HDX API."""
    url = f"{HDX_API_BASE}/package_show?id={package_id}"

    try:
        response = requests.get(url, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()

        if data.get("success"):
            resources = data["result"].get("resources", [])
            return resources
        return []
    except Exception as e:
        print(f"  Error fetching dataset info: {e}")
        return []


def download_resource(resource, output_dir):
    """Download a resource file."""
    url = resource.get("url")
    name = resource.get("name", "unknown")
    format_type = resource.get("format", "").lower()

    if not url:
        return False, 0

    # Create filename
    ext = format_type if format_type else "dat"
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    filename = f"{safe_name}.{ext}"
    output_path = output_dir / filename

    print(f"    Downloading: {name} ({format_type})...", end=" ")

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; DisasterDataCollector/1.0)'
        }
        response = requests.get(url, timeout=TIMEOUT, headers=headers, allow_redirects=True)
        response.raise_for_status()

        with open(output_path, 'wb') as f:
            f.write(response.content)

        file_size = output_path.stat().st_size / 1024
        print(f"OK ({file_size:.1f} KB)")
        return True, file_size

    except Exception as e:
        print(f"FAILED: {e}")
        return False, 0


def download_all():
    """Download all HDX disaster datasets."""
    print("=" * 70)
    print("HDX (Humanitarian Data Exchange) Disaster Data Downloader")
    print("=" * 70)
    print()
    print("Source: UN OCHA - Humanitarian Data Exchange")
    print("Portal: https://data.humdata.org/")
    print()

    setup_output_dir()

    results = {}
    total_size = 0

    for key, info in DATASETS.items():
        print(f"\n{info['description']}...")
        print(f"  Package: {info['package_id']}")

        resources = get_dataset_resources(info["package_id"])

        if not resources:
            print("  No resources found")
            results[key] = {"success": False, "files": []}
            continue

        dataset_results = []
        for resource in resources:
            success, size = download_resource(resource, RAW_DATA_DIR)
            if success:
                total_size += size
                dataset_results.append({
                    "name": resource.get("name"),
                    "format": resource.get("format"),
                    "size_kb": size
                })

        results[key] = {
            "success": len(dataset_results) > 0,
            "files": dataset_results
        }

        time.sleep(1)  # Rate limiting

    # Also try to download EM-DAT directly with known URL pattern
    print("\nTrying direct EM-DAT download...")
    emdat_url = "https://data.humdata.org/dataset/emdat-country-profiles/resource_download/emdat-country-profiles"
    try:
        # Try with API to find current resource
        resources = get_dataset_resources("emdat-country-profiles")
        if resources:
            for r in resources:
                if r.get("format", "").lower() in ["xlsx", "csv"]:
                    success, size = download_resource(r, RAW_DATA_DIR)
                    if success:
                        total_size += size
    except Exception as e:
        print(f"  Direct download failed: {e}")

    # Save metadata
    metadata = {
        "download_date": datetime.now().isoformat(),
        "source": "Humanitarian Data Exchange (HDX) - UN OCHA",
        "source_url": "https://data.humdata.org/",
        "license": "Various - check individual datasets",
        "total_size_mb": round(total_size / 1024, 2),
        "datasets_attempted": len(DATASETS),
        "results": results,
        "notes": [
            "HDX hosts 18,000+ humanitarian datasets",
            "Data from UN agencies, NGOs, governments",
            "EM-DAT contains 27,000+ disaster records since 1900",
            "ReliefWeb provides disaster information since 1981"
        ]
    }

    metadata_path = RAW_DATA_DIR / "hdx_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"\nMetadata saved: {metadata_path}")

    # Summary
    print("\n" + "=" * 70)
    print("DOWNLOAD COMPLETE")
    print("=" * 70)
    success_count = sum(1 for r in results.values() if r.get("success"))
    print(f"Datasets downloaded: {success_count}/{len(DATASETS)}")
    print(f"Total size: {total_size/1024:.1f} MB")

    return success_count > 0


def main():
    success = download_all()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
