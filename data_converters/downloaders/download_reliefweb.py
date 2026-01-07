"""
Download ReliefWeb Global Disasters data from HDX.

Downloads the ReliefWeb disasters list from the Humanitarian Data Exchange.
Covers natural disasters with humanitarian impact from 1981 to present.
Includes GLIDE numbers for cross-referencing with EM-DAT.

Output: Raw data/reliefweb/reliefweb-disasters-list.csv

Usage:
    python download_reliefweb.py
"""
import requests
from pathlib import Path
import time

# Configuration
OUTPUT_DIR = Path("C:/Users/bryan/Desktop/county-map-data/Raw data/reliefweb")
# HDX mirror of ReliefWeb disasters - direct CSV download
HDX_URL = "https://data.humdata.org/dataset/7117aece-abc5-47b8-b5a1-6308db53e7f8/resource/7303ffbd-c0a9-47f7-9664-2d728a25288b/download/reliefweb-disasters-list.csv"
TIMEOUT = 120


def download_disasters():
    """Download ReliefWeb disasters from HDX."""
    print("=" * 80)
    print("ReliefWeb Disasters Downloader (via HDX)")
    print("=" * 80)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_path = OUTPUT_DIR / "reliefweb-disasters-list.csv"

    # Skip if already exists
    if output_path.exists():
        size_kb = output_path.stat().st_size / 1024
        print(f"\nFile already exists: {output_path}")
        print(f"Size: {size_kb:.1f} KB")
        print("Delete the file to re-download.")
        return 0

    print(f"\nDownloading from HDX...")
    print(f"URL: {HDX_URL}")

    try:
        response = requests.get(HDX_URL, timeout=TIMEOUT, stream=True)
        response.raise_for_status()

        # Get content length if available
        total_size = int(response.headers.get('content-length', 0))

        # Download with progress
        downloaded = 0
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    pct = (downloaded / total_size) * 100
                    print(f"\r  Downloading... {pct:.1f}%", end="", flush=True)

        size_kb = output_path.stat().st_size / 1024
        print(f"\r  Downloaded: {size_kb:.1f} KB          ")

        # Quick stats from CSV
        print("\n" + "=" * 80)
        print("DOWNLOAD COMPLETE")
        print("=" * 80)
        print(f"  Output file: {output_path}")
        print(f"  File size: {size_kb:.1f} KB")

        # Count rows
        with open(output_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            # Skip header rows (first 2 lines: header + HXL tags)
            data_rows = len(lines) - 2 if len(lines) > 2 else 0
            print(f"  Total disasters: {data_rows}")

            # Show header to understand structure
            if lines:
                print(f"\n  Columns: {lines[0].strip()[:100]}...")

        print(f"\n  Source: Humanitarian Data Exchange (HDX)")
        print(f"  Original data: ReliefWeb / UN OCHA")
        print(f"  Download date: {time.strftime('%Y-%m-%d %H:%M:%S')}")

        return 0

    except requests.exceptions.HTTPError as e:
        print(f"\nHTTP ERROR: {e.response.status_code}")
        return 1
    except requests.exceptions.RequestException as e:
        print(f"\nERROR: {e}")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(download_disasters())
