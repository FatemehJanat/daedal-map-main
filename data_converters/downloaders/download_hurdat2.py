"""
Download NOAA HURDAT2 Hurricane Database.

Downloads both Atlantic (1851-2024) and Pacific (1949-2024) hurricane track databases
from the National Hurricane Center.

Data includes:
- 6-hourly storm positions (lat/lon)
- Maximum sustained winds
- Central pressure
- Storm status and category
- Wind radii (34kt, 50kt, 64kt) for recent storms

Output: Raw text files in county-map-data/Raw data/noaa/hurdat2/

Usage:
    python download_hurdat2.py
"""
import requests
from pathlib import Path
from datetime import datetime
import json

# Configuration
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/noaa/hurdat2")

# HURDAT2 URLs (updated April 2025)
HURDAT2_SOURCES = {
    "atlantic": {
        "url": "https://www.nhc.noaa.gov/data/hurdat/hurdat2-1851-2024-040425.txt",
        "filename": "hurdat2_atlantic.txt",
        "description": "Atlantic Basin hurricanes 1851-2024",
        "start_year": 1851,
        "end_year": 2024
    },
    "pacific": {
        "url": "https://www.nhc.noaa.gov/data/hurdat/hurdat2-nepac-1949-2024-031725.txt",
        "filename": "hurdat2_pacific.txt",
        "description": "Northeast/North Central Pacific hurricanes 1949-2024",
        "start_year": 1949,
        "end_year": 2024
    }
}


def download_file(url, output_path):
    """Download a file with progress indication."""
    print(f"  Downloading from {url}...")

    response = requests.get(url, stream=True, timeout=60)
    response.raise_for_status()

    total_size = int(response.headers.get('content-length', 0))

    with open(output_path, 'wb') as f:
        downloaded = 0
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            downloaded += len(chunk)
            if total_size > 0:
                pct = (downloaded / total_size) * 100
                print(f"\r  Downloaded: {downloaded:,} / {total_size:,} bytes ({pct:.1f}%)", end="")

    print()  # New line after progress
    return output_path


def count_storms(filepath):
    """Count storms in a HURDAT2 file."""
    storm_count = 0
    with open(filepath, 'r') as f:
        for line in f:
            # Header lines start with basin code (AL, EP, CP)
            if line.strip() and not line[0].isspace():
                parts = line.split(',')
                if len(parts) >= 4 and len(parts[0].strip()) <= 8:
                    storm_count += 1
    return storm_count


def main():
    """Download HURDAT2 databases."""
    print("=" * 70)
    print("HURDAT2 Hurricane Database Downloader")
    print("=" * 70)
    print(f"Started: {datetime.now().isoformat()}")

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\nOutput directory: {OUTPUT_DIR}")

    metadata = {
        "download_date": datetime.now().isoformat(),
        "source": "NOAA National Hurricane Center",
        "source_url": "https://www.nhc.noaa.gov/data/",
        "databases": {}
    }

    # Download each database
    for basin, info in HURDAT2_SOURCES.items():
        print(f"\n{'-' * 50}")
        print(f"Downloading {info['description']}...")

        output_path = OUTPUT_DIR / info['filename']

        try:
            download_file(info['url'], output_path)

            # Get file stats
            file_size = output_path.stat().st_size
            storm_count = count_storms(output_path)

            print(f"  Saved to: {output_path}")
            print(f"  File size: {file_size / 1024 / 1024:.2f} MB")
            print(f"  Storms found: {storm_count}")

            metadata["databases"][basin] = {
                "filename": info['filename'],
                "source_url": info['url'],
                "description": info['description'],
                "start_year": info['start_year'],
                "end_year": info['end_year'],
                "file_size_bytes": file_size,
                "storm_count": storm_count
            }

        except Exception as e:
            print(f"  ERROR: {e}")
            metadata["databases"][basin] = {"error": str(e)}

    # Save metadata
    metadata_path = OUTPUT_DIR / "hurdat2_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"\nMetadata saved to: {metadata_path}")

    # Summary
    print("\n" + "=" * 70)
    print("DOWNLOAD COMPLETE")
    print("=" * 70)

    total_storms = sum(
        db.get("storm_count", 0)
        for db in metadata["databases"].values()
        if isinstance(db, dict)
    )
    print(f"Total storms downloaded: {total_storms}")
    print(f"\nFiles created:")
    for f in OUTPUT_DIR.glob("*"):
        print(f"  {f.name} ({f.stat().st_size / 1024:.1f} KB)")

    print(f"\nNext step: Run convert_hurdat2.py to process into county-level data")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
