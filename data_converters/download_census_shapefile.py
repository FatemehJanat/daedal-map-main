"""
Download Census TIGER/Line county shapefile for geocoding.

Downloads the national county shapefile used for reverse geocoding
lat/long coordinates to county FIPS codes.

Usage:
    python download_census_shapefile.py
"""
import requests
import zipfile
from pathlib import Path
import sys

# Configuration
SHAPEFILE_URL = "https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip"
OUTPUT_DIR = Path("C:/Users/bryan/Desktop/county_map_data/shapefiles/counties")
TIMEOUT = 300

def download_shapefile():
    """Download and extract county shapefile."""
    print("="*80)
    print("Census TIGER/Line County Shapefile Downloader")
    print("="*80)
    print(f"\nDownloading from: {SHAPEFILE_URL}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = OUTPUT_DIR / "tl_2024_us_county.zip"

    try:
        # Download
        print("Downloading...", end=' ', flush=True)
        response = requests.get(SHAPEFILE_URL, timeout=TIMEOUT, stream=True)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0

        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    pct = (downloaded / total_size) * 100
                    print(f"\rDownloading... {pct:.1f}%", end='', flush=True)

        print(f"\rDownloaded: {downloaded / (1024*1024):.1f} MB")

        # Extract
        print("Extracting...", end=' ', flush=True)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(OUTPUT_DIR)
        print("DONE")

        # List extracted files
        files = list(OUTPUT_DIR.glob("*"))
        print(f"\nExtracted {len(files)} files to: {OUTPUT_DIR}")

        # Remove zip file
        zip_path.unlink()
        print("Cleaned up zip file")

        print("\n" + "="*80)
        print("COMPLETE")
        print("="*80)
        print(f"\nShapefile ready: {OUTPUT_DIR / 'tl_2024_us_county.shp'}")

        return 0

    except requests.exceptions.RequestException as e:
        print(f"\nERROR downloading: {e}")
        return 1
    except zipfile.BadZipFile as e:
        print(f"\nERROR extracting: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(download_shapefile())
