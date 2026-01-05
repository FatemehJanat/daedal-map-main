"""
NOAA Storm Events Database Downloader

Downloads historical storm event data from NOAA's reliable FTP directory.
County-level storm data from 1950-2025.

Usage:
    python download_noaa_storms.py [year]

    year: Download specific year (e.g., 2024) or "recent" for last 3 years

Output:
    Saves raw CSV.gz files to: county_map_data/Raw data/noaa_storms/
"""

import requests
import os
from pathlib import Path
import sys
from bs4 import BeautifulSoup
import gzip
import shutil

# Configuration
RAW_DATA_DIR = Path("C:/Users/bryan/Desktop/county_map_data/Raw data/noaa_storms")
BASE_URL = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"
TIMEOUT = 120  # seconds

def setup_output_dir():
    """Create output directory if it doesn't exist."""
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {RAW_DATA_DIR}")

def list_available_files():
    """
    Fetch directory listing from NOAA FTP site.
    Returns list of (filename, size, date) tuples.
    """
    print(f"\nFetching file listing from: {BASE_URL}")

    try:
        response = requests.get(BASE_URL, timeout=TIMEOUT)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        files = []
        for link in soup.find_all('a'):
            href = link.get('href')
            if href and 'StormEvents_details' in href and href.endswith('.csv.gz'):
                # Extract year from filename: StormEvents_details-ftp_v1.0_d2024_c20251204.csv.gz
                if '_d' in href:
                    year_str = href.split('_d')[1][:4]
                    try:
                        year = int(year_str)
                        files.append({
                            'filename': href,
                            'year': year,
                            'url': BASE_URL + href
                        })
                    except ValueError:
                        continue

        # Sort by year descending
        files.sort(key=lambda x: x['year'], reverse=True)

        return files

    except Exception as e:
        print(f"Error fetching file list: {e}")
        return []

def download_file(url, output_path):
    """Download a file with progress indication."""
    try:
        print(f"\n  Downloading: {url}")

        response = requests.get(url, timeout=TIMEOUT, stream=True)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))

        with open(output_path, 'wb') as f:
            downloaded = 0
            chunk_size = 8192

            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

                    if total_size > 0:
                        pct = (downloaded / total_size) * 100
                        mb_down = downloaded / (1024 * 1024)
                        mb_total = total_size / (1024 * 1024)
                        print(f"\r  Progress: {pct:.1f}% ({mb_down:.1f} MB / {mb_total:.1f} MB)", end='')
                    else:
                        print(f"\r  Downloaded: {downloaded:,} bytes", end='')

        print(f"\n  Saved to: {output_path}")
        return True

    except Exception as e:
        print(f"\n  Error downloading: {e}")
        return False

def decompress_file(gz_path):
    """Decompress .gz file to .csv"""
    csv_path = gz_path.with_suffix('')  # Remove .gz extension

    print(f"\n  Decompressing to: {csv_path}")

    try:
        with gzip.open(gz_path, 'rb') as f_in:
            with open(csv_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)

        print(f"  Decompressed size: {csv_path.stat().st_size:,} bytes")

        # Remove .gz file to save space
        gz_path.unlink()
        print(f"  Removed compressed file: {gz_path}")

        return csv_path

    except Exception as e:
        print(f"  Error decompressing: {e}")
        return None

def main():
    """Main download logic."""
    print("=" * 70)
    print("NOAA Storm Events Database Downloader")
    print("=" * 70)

    setup_output_dir()

    # Get available files
    available_files = list_available_files()

    if not available_files:
        print("\nError: Could not fetch file list from NOAA")
        return 1

    print(f"\nFound {len(available_files)} available years")
    print(f"Range: {available_files[-1]['year']} - {available_files[0]['year']}")

    # Determine what to download
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()

        if arg == "recent":
            # Download last 3 years
            to_download = available_files[:3]
            print(f"\nDownloading recent 3 years: {', '.join(str(f['year']) for f in to_download)}")
        else:
            # Download specific year
            try:
                year = int(arg)
                to_download = [f for f in available_files if f['year'] == year]
                if not to_download:
                    print(f"\nError: Year {year} not found in available files")
                    print(f"Available years: {available_files[-1]['year']} - {available_files[0]['year']}")
                    return 1
                print(f"\nDownloading year: {year}")
            except ValueError:
                print(f"\nError: Invalid argument '{arg}'")
                print("Usage: python download_noaa_storms.py [year|recent]")
                return 1
    else:
        # Interactive mode - show recent years
        print("\n" + "=" * 70)
        print("Available recent years:")
        print("=" * 70)
        for i, file_info in enumerate(available_files[:10], 1):
            print(f"{i}. {file_info['year']} - {file_info['filename']}")

        print("\nOptions:")
        print("  Enter a number (1-10) to download that year")
        print("  Enter 'all' to download last 3 years")
        print("  Enter a specific year (e.g., 2020)")

        choice = input("\nChoice: ").strip()

        if choice.lower() == 'all':
            to_download = available_files[:3]
        elif choice.isdigit() and 1 <= int(choice) <= 10:
            to_download = [available_files[int(choice) - 1]]
        else:
            try:
                year = int(choice)
                to_download = [f for f in available_files if f['year'] == year]
                if not to_download:
                    print(f"Year {year} not found")
                    return 1
            except ValueError:
                print(f"Invalid choice: {choice}")
                return 1

    # Download files
    print("\n" + "=" * 70)
    print(f"Downloading {len(to_download)} file(s)...")
    print("=" * 70)

    successful = []
    failed = []

    for i, file_info in enumerate(to_download, 1):
        print(f"\n[{i}/{len(to_download)}] Year {file_info['year']}")

        output_path = RAW_DATA_DIR / file_info['filename']

        # Check if already exists
        csv_path = output_path.with_suffix('')  # Without .gz
        if csv_path.exists():
            print(f"  Already exists (decompressed): {csv_path}")
            print(f"  Size: {csv_path.stat().st_size:,} bytes")
            successful.append(file_info['year'])
            continue

        if output_path.exists():
            print(f"  Already exists (compressed): {output_path}")
            # Decompress it
            if decompress_file(output_path):
                successful.append(file_info['year'])
            else:
                failed.append(file_info['year'])
            continue

        # Download
        if download_file(file_info['url'], output_path):
            # Decompress
            if decompress_file(output_path):
                successful.append(file_info['year'])
            else:
                failed.append(file_info['year'])
        else:
            failed.append(file_info['year'])

    # Summary
    print("\n" + "=" * 70)
    print("DOWNLOAD COMPLETE")
    print("=" * 70)
    print(f"\nSuccessful: {len(successful)} files")
    if successful:
        print(f"  Years: {', '.join(map(str, successful))}")

    if failed:
        print(f"\nFailed: {len(failed)} files")
        print(f"  Years: {', '.join(map(str, failed))}")

    if successful:
        print(f"\nFiles saved to: {RAW_DATA_DIR}")
        print("\nNext steps:")
        print("1. Examine the CSV structure")
        print("2. Run: python data_converters/convert_noaa_storms.py")

    return 0 if not failed else 1

if __name__ == "__main__":
    sys.exit(main())
