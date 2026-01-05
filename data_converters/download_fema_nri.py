"""
FEMA National Risk Index Data Downloader

Downloads FEMA NRI county-level data using multiple fallback methods.
Handles the unreliable FEMA infrastructure with retries and alternatives.

Usage:
    python download_fema_nri.py

Output:
    Saves raw CSV to: county_map_data/Raw data/fema_nri/
"""

import requests
import os
from pathlib import Path
import time
import sys

# Configuration
RAW_DATA_DIR = Path("C:/Users/bryan/Desktop/county_map_data/Raw data/fema_nri")
TIMEOUT = 60  # seconds

# Known download URLs (try in order)
DOWNLOAD_URLS = [
    # Direct download links (try these first)
    {
        "url": "https://hazards.fema.gov/nri/Content/StaticDocuments/DataDownload/NRI_Table_Counties/NRI_Table_Counties.csv",
        "filename": "NRI_Table_Counties.csv",
        "description": "Direct county CSV download"
    },
    {
        "url": "https://hazards.fema.gov/nri/Content/StaticDocuments/DataDownload/NRI_Table_Counties.zip",
        "filename": "NRI_Table_Counties.zip",
        "description": "Direct county ZIP download"
    },
    # Archive versions (v1.19 from 2023, v1.18 from 2021)
    {
        "url": "https://hazards.fema.gov/nri/Content/StaticDocuments/DataDownload/Archive/v119_0/NRI_Table_Counties/NRI_Table_Counties.csv",
        "filename": "NRI_Table_Counties_v119.csv",
        "description": "Archive v1.19 county CSV"
    },
    {
        "url": "https://hazards.fema.gov/nri/Content/StaticDocuments/DataDownload/Archive/v118_1/NRI_Table_Counties/NRI_Table_Counties.csv",
        "filename": "NRI_Table_Counties_v118.csv",
        "description": "Archive v1.18 county CSV"
    },
]

def setup_output_dir():
    """Create output directory if it doesn't exist."""
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {RAW_DATA_DIR}")

def download_with_retry(url, output_path, max_retries=3):
    """
    Download file with retries and progress indication.

    Args:
        url: URL to download from
        output_path: Local path to save file
        max_retries: Number of retry attempts

    Returns:
        True if successful, False otherwise
    """
    for attempt in range(max_retries):
        try:
            print(f"\n  Attempt {attempt + 1}/{max_retries}...")
            print(f"  URL: {url}")

            # Try to download with streaming
            response = requests.get(
                url,
                timeout=TIMEOUT,
                stream=True,
                verify=False,  # Skip SSL verification due to FEMA cert issues
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            )

            response.raise_for_status()

            # Get file size if available
            total_size = int(response.headers.get('content-length', 0))

            # Download with progress
            with open(output_path, 'wb') as f:
                downloaded = 0
                chunk_size = 8192

                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        # Show progress
                        if total_size > 0:
                            pct = (downloaded / total_size) * 100
                            print(f"\r  Progress: {pct:.1f}% ({downloaded:,} / {total_size:,} bytes)", end='')
                        else:
                            print(f"\r  Downloaded: {downloaded:,} bytes", end='')

            print(f"\n  ✓ Success! Saved to: {output_path}")
            print(f"  File size: {output_path.stat().st_size:,} bytes")
            return True

        except requests.exceptions.SSLError as e:
            print(f"  ✗ SSL Error: {e}")
            if attempt < max_retries - 1:
                print(f"  Retrying in 5 seconds...")
                time.sleep(5)

        except requests.exceptions.Timeout:
            print(f"  ✗ Timeout after {TIMEOUT} seconds")
            if attempt < max_retries - 1:
                print(f"  Retrying in 5 seconds...")
                time.sleep(5)

        except requests.exceptions.RequestException as e:
            print(f"  ✗ Request failed: {e}")
            if attempt < max_retries - 1:
                print(f"  Retrying in 5 seconds...")
                time.sleep(5)

        except Exception as e:
            print(f"  ✗ Unexpected error: {e}")
            return False

    return False

def main():
    """Try to download FEMA NRI data using multiple sources."""
    print("=" * 70)
    print("FEMA National Risk Index Downloader")
    print("=" * 70)

    # Disable SSL warnings due to FEMA certificate issues
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    setup_output_dir()

    print(f"\nAttempting to download from {len(DOWNLOAD_URLS)} sources...")

    for i, source in enumerate(DOWNLOAD_URLS, 1):
        print(f"\n[{i}/{len(DOWNLOAD_URLS)}] Trying: {source['description']}")

        output_path = RAW_DATA_DIR / source['filename']

        # Skip if already downloaded
        if output_path.exists():
            print(f"  ⚠ File already exists: {output_path}")
            response = input("  Overwrite? (y/N): ").strip().lower()
            if response != 'y':
                print("  Skipping...")
                continue

        # Try download
        success = download_with_retry(source['url'], output_path)

        if success:
            print("\n" + "=" * 70)
            print("✓ DOWNLOAD SUCCESSFUL!")
            print("=" * 70)
            print(f"\nFile saved to: {output_path}")
            print(f"File size: {output_path.stat().st_size:,} bytes")
            print("\nNext steps:")
            print("1. Examine the CSV structure")
            print("2. Run: python data_converters/convert_fema_nri.py")
            return 0

    # All attempts failed
    print("\n" + "=" * 70)
    print("✗ ALL DOWNLOAD ATTEMPTS FAILED")
    print("=" * 70)
    print("\nFEMA's infrastructure appears to be down.")
    print("\nManual alternatives:")
    print("1. Try downloading directly in your browser:")
    print("   https://hazards.fema.gov/nri/data-resources")
    print("\n2. Or try the data archive:")
    print("   https://hazards.fema.gov/nri/data-archive")
    print("\n3. Save the file to:")
    print(f"   {RAW_DATA_DIR}")
    print("\n4. Then run the converter:")
    print("   python data_converters/convert_fema_nri.py")

    return 1

if __name__ == "__main__":
    sys.exit(main())
