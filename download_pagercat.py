"""
Download PAGER-CAT earthquake impact database from USGS ScienceBase
"""
import requests
from pathlib import Path
from bs4 import BeautifulSoup

OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/pager_cat")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ScienceBase item page
ITEM_URL = "https://www.sciencebase.gov/catalog/item/5bc730dde4b0fc368ebcad8a"

print("=" * 70)
print("PAGER-CAT Earthquake Impact Database Downloader")
print("=" * 70)
print()
print("Source: USGS ScienceBase")
print(f"Item: {ITEM_URL}")
print(f"Output: {OUTPUT_DIR}")
print()

# Fetch the item page to get download links
print("Fetching ScienceBase item page...")
response = requests.get(ITEM_URL, timeout=30)

if response.status_code != 200:
    print(f"ERROR: Failed to fetch page (status {response.status_code})")
    exit(1)

soup = BeautifulSoup(response.content, 'html.parser')

# Find all file download links
download_links = []
for link in soup.find_all('a', href=True):
    href = link['href']
    # Look for direct file download links
    if '/catalog/file/get/' in href:
        filename = href.split('/')[-1]
        download_links.append({
            'url': href if href.startswith('http') else f"https://www.sciencebase.gov{href}",
            'filename': filename
        })

print(f"Found {len(download_links)} files")
print()

# Download priority files
priority_files = [
    'pagercat_2008_06.zip',  # Latest version compressed
    'pagercat_v2.zip',        # Version 2 compressed
    'README'                   # Documentation
]

downloaded = []
for file_info in download_links:
    filename = file_info['filename']

    # Check if this is a priority file or matches patterns
    should_download = False
    if filename in priority_files:
        should_download = True
    elif 'readme' in filename.lower() or 'txt' in filename.lower():
        should_download = True
    elif '2008_06' in filename:
        should_download = True

    if should_download:
        print(f"Downloading: {filename}...", end=" ")
        try:
            file_response = requests.get(file_info['url'], timeout=120)
            if file_response.status_code == 200:
                output_path = OUTPUT_DIR / filename
                with open(output_path, 'wb') as f:
                    f.write(file_response.content)
                size_kb = len(file_response.content) / 1024
                print(f"OK ({size_kb:.1f} KB)")
                downloaded.append(filename)
            else:
                print(f"FAILED (status {file_response.status_code})")
        except Exception as e:
            print(f"ERROR: {e}")

print()
print("=" * 70)
print(f"Downloaded {len(downloaded)} files:")
for fname in downloaded:
    print(f"  - {fname}")
print("=" * 70)
