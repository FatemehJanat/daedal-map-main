"""
Download NASA Global Landslide Catalog from Humanitarian Data Exchange

The Global Landslide Catalog (GLC) was developed to identify rainfall-triggered
landslide events around the world. Data compiled since 2007 at NASA GSFC.

Source: Humanitarian Data Exchange (HDX)
Coverage: 1970-2019
Format: Shapefile (SHP)

Usage:
    python download_nasa_landslides.py
"""
import requests
from pathlib import Path
import zipfile

# Configuration
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/nasa_landslides")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# HDX Download URL (direct link to resource)
# Note: HDX URLs typically follow pattern: https://data.humdata.org/dataset/{id}/resource/{resource_id}
# We'll need to get the actual download URL from the HDX API

HDX_DATASET_ID = "global-landslide-catalogue-nasa"
HDX_API_URL = f"https://data.humdata.org/api/3/action/package_show?id={HDX_DATASET_ID}"

print("=" * 70)
print("NASA Global Landslide Catalog Downloader")
print("=" * 70)
print()
print("Source: Humanitarian Data Exchange (HDX)")
print(f"Dataset: {HDX_DATASET_ID}")
print(f"Output: {OUTPUT_DIR}")
print()

# Fetch dataset metadata to get download URL
print("Fetching dataset metadata from HDX API...")
response = requests.get(HDX_API_URL, timeout=30)

if response.status_code != 200:
    print(f"ERROR: Failed to fetch dataset metadata (status {response.status_code})")
    exit(1)

data = response.json()

if not data.get('success'):
    print("ERROR: API request failed")
    exit(1)

# Extract resources (download files)
resources = data['result']['resources']
print(f"Found {len(resources)} resources")
print()

# Find the shapefile resource
shapefile_resource = None
for resource in resources:
    if resource['format'].upper() in ['SHP', 'ZIP', 'ZIPPED SHAPEFILE']:
        shapefile_resource = resource
        break

if not shapefile_resource:
    print("ERROR: Could not find shapefile resource")
    print("Available resources:")
    for r in resources:
        print(f"  - {r['name']} ({r['format']})")
    exit(1)

download_url = shapefile_resource['url']
filename = shapefile_resource['name']
file_format = shapefile_resource['format']
file_size = shapefile_resource.get('size', 'unknown')

print(f"Resource: {filename}")
print(f"Format: {file_format}")
print(f"Size: {file_size}")
print(f"URL: {download_url}")
print()

# Download the file
output_file = OUTPUT_DIR / filename
print(f"Downloading to: {output_file}")

try:
    response = requests.get(download_url, timeout=120, stream=True)
    response.raise_for_status()

    with open(output_file, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    downloaded_size = output_file.stat().st_size / (1024 * 1024)
    print(f"Download complete: {downloaded_size:.2f} MB")

except Exception as e:
    print(f"ERROR downloading file: {e}")
    exit(1)

# If it's a ZIP file, extract it
if output_file.suffix.lower() == '.zip':
    print()
    print("Extracting ZIP file...")
    try:
        with zipfile.ZipFile(output_file, 'r') as zip_ref:
            zip_ref.extractall(OUTPUT_DIR)

        extracted_files = list(OUTPUT_DIR.glob('*'))
        print(f"Extracted {len(extracted_files)} files:")
        for f in extracted_files:
            if f != output_file:
                print(f"  - {f.name}")
    except Exception as e:
        print(f"ERROR extracting ZIP: {e}")

print()
print("=" * 70)
print("DOWNLOAD COMPLETE")
print("=" * 70)
print()
print("Next steps:")
print("  1. Run convert_nasa_landslides.py to convert shapefile to parquet")
print("  2. Cross-reference with DesInventar landslides")
print("  3. Merge unique events into global landslide catalog")
