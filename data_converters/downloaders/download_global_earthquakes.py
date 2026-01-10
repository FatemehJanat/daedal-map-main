"""
Download USGS global earthquake data.

Downloads historical earthquake events from USGS Earthquake Catalog API.
Includes ALL worldwide earthquakes (no geographic filter).

API Documentation: https://earthquake.usgs.gov/fdsnws/event/1/

Usage:
    python download_global_earthquakes.py              # Download 1970-present, magnitude 4.0+
    python download_global_earthquakes.py --start 1900 --end 2025 --minmag 5.0
    python download_global_earthquakes.py --year 2024  # Download single year
"""
import requests
import sys
from pathlib import Path
from datetime import datetime
import time
import argparse

# Configuration
API_BASE = "https://earthquake.usgs.gov/fdsnws/event/1/query"
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/usgs_earthquakes_global")
TIMEOUT = 300

# No geographic bounds - global coverage


def download_year_data(year, min_magnitude=4.0):
    """Download earthquake data for a single year."""

    start_date = f"{year}-01-01T00:00:00"
    end_date = f"{year + 1}-01-01T00:00:00"

    params = {
        'format': 'csv',
        'starttime': start_date,
        'endtime': end_date,
        'minmagnitude': min_magnitude,
        # No geographic bounds - worldwide
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
            print(f"    Year {year} may have more events. Consider raising min magnitude.")
        else:
            print(f"OK ({count:,} events)")

        return response.text, count

    except requests.exceptions.RequestException as e:
        print(f"ERROR: {e}")
        return None, 0


def download_month_data(year, month, min_magnitude=4.0):
    """Download earthquake data for a single month (for high-volume years)."""
    import calendar

    # Get last day of month
    _, last_day = calendar.monthrange(year, month)

    start_date = f"{year}-{month:02d}-01T00:00:00"
    if month == 12:
        end_date = f"{year + 1}-01-01T00:00:00"
    else:
        end_date = f"{year}-{month + 1:02d}-01T00:00:00"

    params = {
        'format': 'csv',
        'starttime': start_date,
        'endtime': end_date,
        'minmagnitude': min_magnitude,
        'orderby': 'time-asc',
        'limit': 20000
    }

    try:
        response = requests.get(API_BASE, params=params, timeout=TIMEOUT)
        response.raise_for_status()

        lines = response.text.strip().split('\n')
        count = len(lines) - 1

        return response.text, count

    except requests.exceptions.RequestException as e:
        return None, 0


def save_year_file(year, csv_data):
    """Save CSV data to file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"earthquakes_{year}.csv"

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(csv_data)

    size_kb = output_path.stat().st_size / 1024
    return output_path, size_kb


def download_year_by_month(year, min_magnitude=4.0):
    """Download a year month-by-month to avoid 20K limit."""
    all_lines = []
    header = None
    total_count = 0

    print(f"  Fetching {year} by month (mag {min_magnitude}+)...", flush=True)

    for month in range(1, 13):
        csv_data, count = download_month_data(year, month, min_magnitude)
        if csv_data:
            lines = csv_data.strip().split('\n')
            if header is None:
                header = lines[0]
                all_lines.append(header)
            # Add data lines (skip header)
            all_lines.extend(lines[1:])
            total_count += count
            print(f"    {year}-{month:02d}: {count:,} events")
        time.sleep(0.5)  # Rate limiting

    if all_lines:
        return '\n'.join(all_lines), total_count
    return None, 0


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Download USGS global earthquake data')

    parser.add_argument('--start', type=int, default=1970,
                        help='Start year (default: 1970)')
    parser.add_argument('--end', type=int, default=datetime.now().year,
                        help='End year (default: current year)')
    parser.add_argument('--year', type=int,
                        help='Download single year only')
    parser.add_argument('--minmag', type=float, default=4.0,
                        help='Minimum magnitude (default: 4.0)')
    parser.add_argument('--by-month', action='store_true',
                        help='Download each year month-by-month (slower but avoids 20K limit)')

    return parser.parse_args()


def main():
    """Main download logic."""
    args = parse_args()

    print("="*80)
    print("USGS Global Earthquake Data Downloader")
    print("="*80)

    # Determine year range
    if args.year:
        years = [args.year]
        print(f"\nDownloading year: {args.year}")
    else:
        years = list(range(args.start, args.end + 1))
        print(f"\nDownloading years: {args.start}-{args.end}")

    print(f"Minimum magnitude: {args.minmag}")
    print(f"Geographic bounds: WORLDWIDE (no filter)")
    print(f"Output directory: {OUTPUT_DIR}")
    if args.by_month:
        print("Mode: Month-by-month (slower, avoids 20K limit)")
    print()

    # Download data
    successful = []
    failed = []
    total_events = 0

    for year in years:
        if args.by_month:
            csv_data, count = download_year_by_month(year, args.minmag)
        else:
            csv_data, count = download_year_data(year, args.minmag)

        if csv_data:
            output_path, size_kb = save_year_file(year, csv_data)
            successful.append(year)
            total_events += count
            print(f"    Saved: {output_path.name} ({size_kb:.1f} KB, {count:,} events)")
        else:
            failed.append(year)

        # Rate limiting - be nice to USGS
        if year != years[-1]:
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
    print("  python data_converters/converters/convert_global_earthquakes.py")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
