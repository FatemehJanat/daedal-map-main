"""
Download PAGER-CAT earthquake impact database from USGS ScienceBase
Using JSON API to get file URLs
"""
import requests
from pathlib import Path
import json

OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/pager_cat")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ScienceBase item JSON API
ITEM_ID = "5bc730dde4b0fc368ebcad8a"
JSON_URL = f"https://www.sciencebase.gov/catalog/item/{ITEM_ID}?format=json"

print("=" * 70)
print("PAGER-CAT Earthquake Impact Database Downloader")
print("=" * 70)
print()
print("Source: USGS ScienceBase")
print(f"Output: {OUTPUT_DIR}")
print()

# Fetch JSON metadata
print("Fetching item metadata...")
response = requests.get(JSON_URL, timeout=30)

if response.status_code != 200:
    print(f"ERROR: Failed to fetch metadata (status {response.status_code})")
    exit(1)

metadata = response.json()

# Extract file information
files = metadata.get('files', [])
print(f"Found {len(files)} files")
print()

# Download priority files
priority_keywords = ['2008_06', 'readme', 'txt', 'pdf']

downloaded = []
for file_info in files:
    filename = file_info.get('name', '')
    file_url = file_info.get('url', '')
    size_bytes = file_info.get('size', 0)

    # Check if this is a priority file
    should_download = any(keyword in filename.lower() for keyword in priority_keywords)

    if should_download or len(files) <= 10:  # Download all if few files
        print(f"Downloading: {filename} ({size_bytes / 1024:.1f} KB)...", end=" ")
        try:
            file_response = requests.get(file_url, timeout=120)
            if file_response.status_code == 200:
                output_path = OUTPUT_DIR / filename
                with open(output_path, 'wb') as f:
                    f.write(file_response.content)
                print(f"OK")
                downloaded.append(filename)
            else:
                print(f"FAILED (status {file_response.status_code})")
        except Exception as e:
            print(f"ERROR: {e}")

# Save metadata
metadata_path = OUTPUT_DIR / "pagercat_metadata.json"
with open(metadata_path, 'w') as f:
    json.dump(metadata, f, indent=2)

print()
print("=" * 70)
print(f"Downloaded {len(downloaded)} files:")
for fname in downloaded:
    print(f"  - {fname}")
print(f"\nMetadata saved: {metadata_path}")
print("=" * 70)
