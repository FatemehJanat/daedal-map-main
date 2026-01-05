"""
Download USGS earthquake data for the United States.

Downloads historical earthquake events from USGS Earthquake Catalog API.
Data includes location, magnitude, depth, time, and other event properties.

API Documentation: https://earthquake.usgs.gov/fdsnws/event/1/

Usage:
    python download_usgs_earthquakes.py              # Download 1970-present, magnitude 3.0+
    python download_usgs_earthquakes.py --start 2000 --end 2025 --minmag 4.0
    python download_usgs_earthquakes.py --year 2024  # Download single year
"""
import requests
import sys
from pathlib import Path
from datetime import datetime, timedelta
import time
import argparse

# Configuration
API_BASE = "https://earthquake.usgs.gov/fdsnws/event/1/query"
OUTPUT_DIR = Path("C:/Users/bryan/Desktop/county_map_data/Raw data/usgs_earthquakes")
TIMEOUT = 300

# US territory boundaries (approximate)
# Includes Alaska, Hawaii, Puerto Rico, and territories
US_BOUNDS = {
    'minlatitude': 15.0,   # Puerto Rico and territories
    'maxlatitude': 72.0,   # Alaska
    'minlongitude': -180.0,  # Alaska (crosses dateline)
    'maxlongitude': -60.0    # Eastern seaboard
}


def download_year_data(year, min_magnitude=3.0):
    """Download earthquake data for a single year."""

    start_date = f"{year}-01-01T00:00:00"
    end_date = f"{year + 1}-01-01T00:00:00"

    params = {
        'format': 'csv',
        'starttime': start_date,
        'endtime': end_date,
        'minmagnitude': min_magnitude,
        'minlatitude': US_BOUNDS['minlatitude'],
        'maxlatitude': US_BOUNDS['maxlatitude'],
        'minlongitude': US_BOUNDS['minlongitude'],
        'maxlongitude': US_BOUNDS['maxlongitude'],
        'orderby': 'time-asc',
        'limit': 20000  # API maximum
    }

    try:
        print(f"  Fetching {year} (mag {min_magnitude}+)...", end=' ', flush=True)
        response = requests.get(API_BASE, params=params, timeout=TIMEOUT)
        response.raise_for_status()

        # Check if we hit the 20,000 limit
        lines = response.text.strip().split('\n')
        count = len(lines) - 1  # Subtract header

        if count >= 20000:
            print(f"WARNING: Hit 20K limit ({count} events)")
            print(f"    Year {year} may have more events. Consider lowering date range or raising min magnitude.")
        else:
            print(f"SUCCESS ({count} events)")

        return response.text, count

    except requests.exceptions.RequestException as e:
        print(f"ERROR: {e}")
        return None, 0


def save_year_file(year, csv_data):
    """Save CSV data to file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"earthquakes_{year}.csv"

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(csv_data)

    size_kb = output_path.stat().st_size / 1024
    return output_path, size_kb


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Download USGS earthquake data for the United States')

    parser.add_argument('--start', type=int, default=1970,
                        help='Start year (default: 1970)')
    parser.add_argument('--end', type=int, default=datetime.now().year,
                        help='End year (default: current year)')
    parser.add_argument('--year', type=int,
                        help='Download single year only')
    parser.add_argument('--minmag', type=float, default=3.0,
                        help='Minimum magnitude (default: 3.0)')

    return parser.parse_args()


def main():
    """Main download logic."""
    args = parse_args()

    print("="*80)
    print("USGS Earthquake Data Downloader")
    print("="*80)

    # Determine year range
    if args.year:
        years = [args.year]
        print(f"\nDownloading year: {args.year}")
    else:
        years = range(args.start, args.end + 1)
        print(f"\nDownloading years: {args.start}-{args.end}")

    print(f"Minimum magnitude: {args.minmag}")
    print(f"Geographic bounds: US territory (lat {US_BOUNDS['minlatitude']}-{US_BOUNDS['maxlatitude']}, lon {US_BOUNDS['minlongitude']}-{US_BOUNDS['maxlongitude']})")
    print(f"Output directory: {OUTPUT_DIR}")
    print()

    # Download data
    successful = []
    failed = []
    total_events = 0

    for year in years:
        csv_data, count = download_year_data(year, args.minmag)

        if csv_data:
            output_path, size_kb = save_year_file(year, csv_data)
            successful.append(year)
            total_events += count
            print(f"    Saved: {output_path.name} ({size_kb:.1f} KB)")
        else:
            failed.append(year)

        # Rate limiting - be nice to USGS
        if year != years[-1]:  # Don't sleep after last year
            time.sleep(1)

    # Summary
    print("\n" + "="*80)
    print("DOWNLOAD COMPLETE")
    print("="*80)
    print(f"\nSuccessful years: {len(successful)}/{len(years)}")
    print(f"Total events downloaded: {total_events:,}")

    if failed:
        print(f"\nFailed years ({len(failed)}): {failed}")

    print(f"\nOutput directory: {OUTPUT_DIR}")
    print("\nNext steps:")
    print("  1. Download Census TIGER/Line county shapefile")
    print("  2. Create converter to geocode earthquakes to counties")
    print("  3. Aggregate events by county-year")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
