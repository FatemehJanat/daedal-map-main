"""
Download MTBS (Monitoring Trends in Burn Severity) wildfire data.

Downloads burned area boundaries from MTBS direct download page.
MTBS provides fire perimeters for all large fires (>1000 acres West, >500 acres East)
from 1984-present at 30m resolution.

Source: https://www.mtbs.gov/direct-download
Data: Burned area boundaries shapefile (~500 MB zipped)

Usage:
    python download_mtbs.py
"""

import requests
import json
from pathlib import Path
from datetime import datetime
import sys

# Output directory
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/mtbs")

# MTBS Direct Download URLs
# These are the current URLs from mtbs.gov/direct-download
MTBS_SOURCES = {
    "burned_areas_conus": {
        "url": "https://edcintl.cr.usgs.gov/downloads/sciweb1/shared/MTBS_Fire/data/composite_data/burned_area_extent_shapefile/mtbs_perimeter_data.zip",
        "filename": "mtbs_perimeter_data.zip",
        "description": "CONUS fire perimeters 1984-2023",
        "format": "Shapefile (zipped)",
        "coverage": "Continental US"
    },
    "burned_areas_alaska": {
        "url": "https://edcintl.cr.usgs.gov/downloads/sciweb1/shared/MTBS_Fire/data/composite_data/burned_area_extent_shapefile/mtbs_perimeter_data_AK.zip",
        "filename": "mtbs_perimeter_data_AK.zip",
        "description": "Alaska fire perimeters 1984-2023",
        "format": "Shapefile (zipped)",
        "coverage": "Alaska"
    },
    "fire_occurrence_points": {
        "url": "https://edcintl.cr.usgs.gov/downloads/sciweb1/shared/MTBS_Fire/data/composite_data/fod_pt_shapefile/mtbs_fod_pts_data.zip",
        "filename": "mtbs_fod_pts_data.zip",
        "description": "Fire occurrence points (ignition locations)",
        "format": "Shapefile (zipped)",
        "coverage": "All US"
    }
}


def download_file(url, output_path, description):
    """Download a file with progress indication."""
    print(f"\nDownloading {description}...")
    print(f"  URL: {url}")
    print(f"  Target: {output_path}")

    try:
        # Stream download for large files
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()

        # Get file size if available
        total_size = int(response.headers.get('content-length', 0))

        # Download with progress
        downloaded = 0
        chunk_size = 1024 * 1024  # 1 MB chunks

        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = (downloaded / total_size) * 100
                        print(f"  Progress: {downloaded / (1024*1024):.1f} MB / {total_size / (1024*1024):.1f} MB ({pct:.1f}%)", end='\r')
                    else:
                        print(f"  Downloaded: {downloaded / (1024*1024):.1f} MB", end='\r')

        print()  # New line after progress

        actual_size = output_path.stat().st_size
        print(f"  Complete: {actual_size / (1024*1024):.1f} MB")

        return {
            "success": True,
            "file_size_bytes": actual_size,
            "url": url
        }

    except requests.exceptions.RequestException as e:
        print(f"  ERROR: {e}")
        return {
            "success": False,
            "error": str(e),
            "url": url
        }


def main():
    """Download all MTBS data files."""
    print("=" * 70)
    print("MTBS Wildfire Data Downloader")
    print("=" * 70)
    print(f"Started: {datetime.now().isoformat()}")
    print(f"Source: https://www.mtbs.gov/direct-download")

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\nOutput directory: {OUTPUT_DIR}")

    # Download metadata
    metadata = {
        "download_date": datetime.now().isoformat(),
        "source": "MTBS - Monitoring Trends in Burn Severity",
        "source_url": "https://www.mtbs.gov/direct-download",
        "description": "Fire perimeters for large fires (>1000 acres West, >500 acres East) 1984-present",
        "files": {}
    }

    # Download each file
    success_count = 0
    for key, source in MTBS_SOURCES.items():
        output_path = OUTPUT_DIR / source["filename"]

        result = download_file(
            source["url"],
            output_path,
            source["description"]
        )

        metadata["files"][key] = {
            "filename": source["filename"],
            "description": source["description"],
            "format": source["format"],
            "coverage": source["coverage"],
            "source_url": source["url"],
            **result
        }

        if result["success"]:
            success_count += 1

    # Save metadata
    metadata_path = OUTPUT_DIR / "mtbs_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"\nMetadata saved to: {metadata_path}")

    # Summary
    print("\n" + "=" * 70)
    print("DOWNLOAD SUMMARY")
    print("=" * 70)
    print(f"Successful: {success_count}/{len(MTBS_SOURCES)}")

    total_size = sum(
        f.get("file_size_bytes", 0)
        for f in metadata["files"].values()
        if f.get("success")
    )
    print(f"Total size: {total_size / (1024*1024):.1f} MB")

    if success_count < len(MTBS_SOURCES):
        print("\nFailed downloads:")
        for key, info in metadata["files"].items():
            if not info.get("success"):
                print(f"  - {key}: {info.get('error', 'Unknown error')}")
        return 1

    print("\nAll files downloaded successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
