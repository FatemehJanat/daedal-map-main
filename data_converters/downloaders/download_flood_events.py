"""
Download flood event catalogs from multiple sources.

These event lists provide date/location triggers for downloading satellite imagery
only during known flood events (much more efficient than downloading everything).

Sources:
1. Global Flood Monitor (Twitter-derived): 2014-present, ~10,000+ events
   URL: https://globalfloodmonitor.org/events.xlsx

2. DFO/HDX Archive (news + satellite-derived): 1985-2019, ~4,800 events
   URL: https://data.humdata.org/dataset/global-active-archive-of-large-flood-events-dfo

3. Global Flood Database (Cloud to Street): 2000-2018, 913 events with polygons
   GitHub: https://github.com/cloudtostreet/MODIS_GlobalFloodDatabase

Usage:
    # Download all available flood event catalogs
    python download_flood_events.py --all

    # Download specific source
    python download_flood_events.py --source gfm
    python download_flood_events.py --source dfo
    python download_flood_events.py --source gfd

    # Merge all sources into unified event list
    python download_flood_events.py --merge

Output:
    Creates flood_events/ directory with:
    - gfm_events.xlsx (Global Flood Monitor)
    - dfo_events.shp (DFO shapefile from HDX)
    - gfd_events.csv (Global Flood Database)
    - merged_flood_events.csv (unified list for LANCE downloads)
"""
import requests
import sys
import os
from pathlib import Path
from datetime import datetime
import time
import argparse
import zipfile
import io

# Configuration
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/flood_events")
TIMEOUT = 120

# Data source URLs
SOURCES = {
    'gfm': {
        'name': 'Global Flood Monitor',
        'url': 'https://globalfloodmonitor.org/events.xlsx',
        'filename': 'gfm_events.xlsx',
        'coverage': '2014-present',
        'description': 'Twitter-derived flood events, ~10,000+ events globally'
    },
    'gfd': {
        'name': 'Global Flood Database QC',
        'url': 'https://raw.githubusercontent.com/cloudtostreet/MODIS_GlobalFloodDatabase/main/data/gfd_qcdatabase_2019_08_01.csv',
        'filename': 'gfd_events.csv',
        'coverage': '2000-2018',
        'description': 'Cloud to Street QC database, 913 validated events'
    },
    'gfd_mechanism': {
        'name': 'Global Flood Database Mechanism',
        'url': 'https://raw.githubusercontent.com/cloudtostreet/MODIS_GlobalFloodDatabase/main/data/gfd_floodmechanism.csv',
        'filename': 'gfd_mechanism.csv',
        'coverage': '2000-2018',
        'description': 'Flood mechanism classification data'
    },
    'gfd_popsummary': {
        'name': 'Global Flood Database Population',
        'url': 'https://raw.githubusercontent.com/cloudtostreet/MODIS_GlobalFloodDatabase/main/data/gfd_popsummary.csv',
        'filename': 'gfd_popsummary.csv',
        'coverage': '2000-2018',
        'description': 'Population exposure per country'
    }
}


def download_file(url, output_path, source_name):
    """Download a file with progress indication."""
    try:
        print(f"  Downloading {source_name}...", end=' ', flush=True)

        response = requests.get(url, timeout=TIMEOUT, stream=True)
        response.raise_for_status()

        # Get file size if available
        total_size = int(response.headers.get('content-length', 0))

        with open(output_path, 'wb') as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

        size_kb = output_path.stat().st_size / 1024
        print(f"OK ({size_kb:.1f} KB)")
        return True

    except requests.exceptions.RequestException as e:
        print(f"ERROR: {e}")
        return False


def download_source(source_key):
    """Download a specific flood event source."""
    if source_key not in SOURCES:
        print(f"ERROR: Unknown source '{source_key}'")
        print(f"Available sources: {', '.join(SOURCES.keys())}")
        return False

    source = SOURCES[source_key]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / source['filename']

    print(f"\n{source['name']}")
    print(f"  Coverage: {source['coverage']}")
    print(f"  Description: {source['description']}")

    success = download_file(source['url'], output_path, source['name'])

    # Handle zip files
    if success and output_path.suffix == '.zip':
        print(f"  Extracting...", end=' ', flush=True)
        extract_dir = OUTPUT_DIR / source_key
        extract_dir.mkdir(exist_ok=True)

        try:
            with zipfile.ZipFile(output_path, 'r') as zf:
                zf.extractall(extract_dir)

            # List extracted files
            extracted = list(extract_dir.glob('*'))
            print(f"OK ({len(extracted)} files)")
            for f in extracted[:5]:
                print(f"    - {f.name}")
            if len(extracted) > 5:
                print(f"    ... and {len(extracted) - 5} more")

        except zipfile.BadZipFile as e:
            print(f"ERROR extracting: {e}")

    return success


def download_all():
    """Download all available flood event sources."""
    print("="*80)
    print("FLOOD EVENT CATALOG DOWNLOADER")
    print("="*80)
    print(f"\nOutput directory: {OUTPUT_DIR}")

    results = {}
    for source_key in SOURCES:
        results[source_key] = download_source(source_key)
        time.sleep(1)  # Be nice to servers

    # Summary
    print("\n" + "="*80)
    print("DOWNLOAD SUMMARY")
    print("="*80)

    success_count = sum(1 for v in results.values() if v)
    print(f"\nSuccessful: {success_count}/{len(results)}")

    for key, success in results.items():
        status = "OK" if success else "FAILED"
        print(f"  {SOURCES[key]['name']}: {status}")

    print(f"\nFiles saved to: {OUTPUT_DIR}")
    print("\nNext steps:")
    print("  1. Inspect downloaded files to understand structure")
    print("  2. Run: python download_flood_events.py --merge")
    print("  3. Use merged list to trigger LANCE satellite downloads")

    return all(results.values())


def print_merge_instructions():
    """Print instructions for merging flood event sources."""
    print("\n" + "="*80)
    print("MERGE INSTRUCTIONS")
    print("="*80)
    print("""
After downloading flood event catalogs, you can merge them into a unified list.

Expected output columns:
  - event_id: Unique identifier
  - source: Origin database (gfm, dfo, gfd)
  - start_date: Flood start date
  - end_date: Flood end date (or peak date if duration unknown)
  - latitude: Event centroid latitude
  - longitude: Event centroid longitude
  - country: Country name
  - location_name: Specific location if available
  - severity: Normalized severity (1-5) if available

This merged list can then be used with download_lance_floods.py to:
  1. Filter to specific date ranges and regions
  2. Download only LANCE tiles that cover known flood events
  3. Process satellite data into flood extent polygons

To create the merge converter:
  python data_converters/converters/convert_flood_events.py
""")


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Download flood event catalogs for event-driven satellite downloads',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download all sources
  python download_flood_events.py --all

  # Download specific source
  python download_flood_events.py --source gfm

  # List available sources
  python download_flood_events.py --list

  # Show merge instructions
  python download_flood_events.py --merge
        """
    )

    parser.add_argument('--all', action='store_true',
                        help='Download all available flood event sources')
    parser.add_argument('--source', type=str,
                        choices=list(SOURCES.keys()),
                        help='Download specific source')
    parser.add_argument('--list', action='store_true',
                        help='List available sources')
    parser.add_argument('--merge', action='store_true',
                        help='Show instructions for merging sources')

    return parser.parse_args()


def list_sources():
    """List available flood event sources."""
    print("\n" + "="*80)
    print("AVAILABLE FLOOD EVENT SOURCES")
    print("="*80)

    for key, source in SOURCES.items():
        print(f"\n{key}:")
        print(f"  Name: {source['name']}")
        print(f"  Coverage: {source['coverage']}")
        print(f"  Description: {source['description']}")


def main():
    """Main entry point."""
    args = parse_args()

    if args.list:
        list_sources()
        return 0

    if args.merge:
        print_merge_instructions()
        return 0

    if args.source:
        success = download_source(args.source)
        return 0 if success else 1

    if args.all:
        success = download_all()
        return 0 if success else 1

    # Default: show help
    print("Flood Event Catalog Downloader")
    print("\nUse --all to download all sources, or --help for more options")
    list_sources()
    return 0


if __name__ == "__main__":
    sys.exit(main())
