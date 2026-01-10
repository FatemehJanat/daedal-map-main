"""
Download USGS earthquake data - GLOBAL coverage.

Downloads historical earthquake events from USGS Earthquake Catalog API.
Data includes location, magnitude, depth, time, and other event properties.

API Documentation: https://earthquake.usgs.gov/fdsnws/event/1/

Usage:
    python download_usgs_earthquakes.py                    # Download 1900-present, M2.5+ global
    python download_usgs_earthquakes.py --start 2000 --end 2025 --minmag 4.0
    python download_usgs_earthquakes.py --year 2024        # Download single year
    python download_usgs_earthquakes.py --region us        # US territory only
    python download_usgs_earthquakes.py --minmag 2.5       # Lower threshold (more data)
"""
import requests
import sys
from pathlib import Path
from datetime import datetime, timedelta
import time
import argparse

# Configuration
API_BASE = "https://earthquake.usgs.gov/fdsnws/event/1/query"
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/usgs_earthquakes")
TIMEOUT = 300

# Regional boundaries
REGIONS = {
    'global': None,  # No bounds = global
    'us': {
        'minlatitude': 15.0,
        'maxlatitude': 72.0,
        'minlongitude': -180.0,
        'maxlongitude': -60.0
    }
}


def download_period_data(start_date, end_date, min_magnitude=2.5, max_magnitude=None, region='global', label=''):
    """Download earthquake data for a date range."""

    params = {
        'format': 'csv',
        'starttime': start_date,
        'endtime': end_date,
        'minmagnitude': min_magnitude,
        'orderby': 'time-asc',
        'limit': 20000  # API maximum
    }

    if max_magnitude is not None:
        params['maxmagnitude'] = max_magnitude

    # Add regional bounds if specified
    bounds = REGIONS.get(region)
    if bounds:
        params.update(bounds)

    try:
        print(f"  Fetching {label} (mag {min_magnitude}+)...", end=' ', flush=True)
        response = requests.get(API_BASE, params=params, timeout=TIMEOUT)
        response.raise_for_status()

        # Check if we hit the 20,000 limit
        lines = response.text.strip().split('\n')
        count = len(lines) - 1  # Subtract header

        if count >= 19999:
            print(f"WARNING: Hit 20K limit ({count} events)")
            return response.text, count, True  # True = needs finer granularity
        else:
            print(f"OK ({count:,} events)")

        return response.text, count, False

    except requests.exceptions.RequestException as e:
        print(f"ERROR: {e}")
        return None, 0, False


def download_year_data(year, min_magnitude=2.5, max_magnitude=None, region='global'):
    """Download earthquake data for a single year, splitting into months if needed."""

    start_date = f"{year}-01-01T00:00:00"
    end_date = f"{year + 1}-01-01T00:00:00"

    # Try full year first
    csv_data, count, hit_limit = download_period_data(
        start_date, end_date, min_magnitude, max_magnitude, region, str(year)
    )

    if not hit_limit or csv_data is None:
        return csv_data, count

    # Hit limit - download by month
    print(f"    Splitting {year} into months...")
    all_lines = []
    header = None
    total_count = 0

    for month in range(1, 13):
        m_start = f"{year}-{month:02d}-01T00:00:00"
        if month == 12:
            m_end = f"{year + 1}-01-01T00:00:00"
        else:
            m_end = f"{year}-{month + 1:02d}-01T00:00:00"

        csv_data, count, _ = download_period_data(
            m_start, m_end, min_magnitude, max_magnitude, region, f"{year}-{month:02d}"
        )

        if csv_data:
            lines = csv_data.strip().split('\n')
            if header is None:
                header = lines[0]
                all_lines.append(header)
            all_lines.extend(lines[1:])  # Skip header for subsequent months
            total_count += count

        time.sleep(0.5)  # Rate limiting

    return '\n'.join(all_lines), total_count


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
    parser = argparse.ArgumentParser(description='Download USGS earthquake data - global or regional')

    parser.add_argument('--start', type=int, default=1900,
                        help='Start year (default: 1900)')
    parser.add_argument('--end', type=int, default=datetime.now().year,
                        help='End year (default: current year)')
    parser.add_argument('--year', type=int,
                        help='Download single year only')
    parser.add_argument('--minmag', type=float, default=2.5,
                        help='Minimum magnitude (default: 2.5)')
    parser.add_argument('--maxmag', type=float, default=None,
                        help='Maximum magnitude (default: None = no limit)')
    parser.add_argument('--region', type=str, default='global', choices=['global', 'us'],
                        help='Region to download (default: global)')
    parser.add_argument('--output', type=str, default=None,
                        help='Output directory (default: usgs_earthquakes)')

    return parser.parse_args()


def main():
    """Main download logic."""
    global OUTPUT_DIR
    args = parse_args()

    # Override output directory if specified
    if args.output:
        OUTPUT_DIR = Path(args.output)

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

    mag_range = f"M{args.minmag}+"
    if args.maxmag:
        mag_range = f"M{args.minmag}-{args.maxmag}"
    print(f"Magnitude range: {mag_range}")
    bounds = REGIONS.get(args.region)
    if bounds:
        print(f"Region: {args.region} (lat {bounds['minlatitude']}-{bounds['maxlatitude']}, lon {bounds['minlongitude']}-{bounds['maxlongitude']})")
    else:
        print(f"Region: GLOBAL (no geographic bounds)")
    print(f"Output directory: {OUTPUT_DIR}")
    print()

    # Download data
    successful = []
    failed = []
    total_events = 0

    for year in years:
        csv_data, count = download_year_data(year, args.minmag, args.maxmag, args.region)

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
