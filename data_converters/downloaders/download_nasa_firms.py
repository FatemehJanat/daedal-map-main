"""
Download NASA FIRMS (Fire Information for Resource Management System) active fire data.

NASA FIRMS provides near-real-time satellite fire detection globally.

Data Sources:
- MODIS (Aqua/Terra): 1km resolution, 2000-present
- VIIRS S-NPP: 375m resolution, 2012-present
- VIIRS NOAA-20: 375m resolution, 2018-present
- VIIRS NOAA-21: 375m resolution, 2024-present

API Documentation: https://firms.modaps.eosdis.nasa.gov/api/
Archive Download: https://firms.modaps.eosdis.nasa.gov/download/

IMPORTANT:
- NRT (Near Real-Time) API limited to last 10 days
- For historical data, use --archive mode or download from FIRMS portal
- Free MAP_KEY required: https://firms.modaps.eosdis.nasa.gov/api/area/

Usage:
    # Download recent NRT data (requires MAP_KEY in environment or --key)
    python download_nasa_firms.py --nrt --days 7 --key YOUR_MAP_KEY

    # Download archive data for date range (from pre-downloaded archive files)
    python download_nasa_firms.py --archive --start 2020-01-01 --end 2020-12-31

    # Download by region
    python download_nasa_firms.py --nrt --days 3 --region usa --key YOUR_MAP_KEY
"""
import requests
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
import time
import argparse
import json

# Configuration
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/nasa_firms")
ARCHIVE_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/nasa_firms/archive")

# API endpoints
API_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
ARCHIVE_BASE = "https://firms.modaps.eosdis.nasa.gov/data/active_fire"

# Sensor configurations
SENSORS = {
    'VIIRS_NOAA20_NRT': {
        'name': 'VIIRS NOAA-20',
        'resolution': '375m',
        'start_year': 2018,
        'description': 'VIIRS sensor on NOAA-20 satellite'
    },
    'VIIRS_NOAA21_NRT': {
        'name': 'VIIRS NOAA-21',
        'resolution': '375m',
        'start_year': 2024,
        'description': 'VIIRS sensor on NOAA-21 satellite'
    },
    'VIIRS_SNPP_NRT': {
        'name': 'VIIRS S-NPP',
        'resolution': '375m',
        'start_year': 2012,
        'description': 'VIIRS sensor on Suomi NPP satellite'
    },
    'MODIS_NRT': {
        'name': 'MODIS',
        'resolution': '1km',
        'start_year': 2000,
        'description': 'MODIS sensors on Terra/Aqua satellites'
    }
}

# Region bounding boxes (minX, minY, maxX, maxY)
REGIONS = {
    'world': (-180, -90, 180, 90),
    'usa': (-125, 24, -66, 50),
    'canada': (-141, 41, -52, 84),
    'australia': (112, -45, 155, -10),
    'europe': (-25, 35, 45, 72),
    'california': (-125, 32, -114, 42),
    'amazon': (-80, -20, -40, 5),
}

TIMEOUT = 120


def download_nrt_data(map_key, sensor, region, days):
    """Download near-real-time fire data from FIRMS API."""

    if region in REGIONS:
        bounds = REGIONS[region]
        coords = f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}"
    else:
        # Assume world if region not found
        coords = "world"

    url = f"{API_BASE}/{map_key}/{sensor}/{coords}/{days}"

    try:
        print(f"  Fetching {sensor} data ({days} days, {region})...", end=' ', flush=True)
        response = requests.get(url, timeout=TIMEOUT)

        if response.status_code == 401:
            print("ERROR: Invalid MAP_KEY")
            return None, 0
        elif response.status_code == 429:
            print("ERROR: Rate limit exceeded (5000 requests/10 min)")
            return None, 0

        response.raise_for_status()

        # Count records
        lines = response.text.strip().split('\n')
        count = len(lines) - 1  # Subtract header

        print(f"OK ({count:,} fire detections)")

        return response.text, count

    except requests.exceptions.RequestException as e:
        print(f"ERROR: {e}")
        return None, 0


def save_nrt_file(sensor, region, days, csv_data):
    """Save NRT data to file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y%m%d")
    filename = f"firms_{sensor}_{region}_{days}d_{today}.csv"
    output_path = OUTPUT_DIR / filename

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(csv_data)

    size_kb = output_path.stat().st_size / 1024
    return output_path, size_kb


def download_archive_info():
    """Print information about downloading archive data."""
    print("\n" + "="*80)
    print("NASA FIRMS ARCHIVE DOWNLOAD")
    print("="*80)
    print("""
Historical fire data (beyond 10 days) must be downloaded from the FIRMS portal:

1. Go to: https://firms.modaps.eosdis.nasa.gov/download/

2. Select parameters:
   - Sensor: VIIRS-NOAA20 (recommended) or MODIS
   - Date Range: Your desired range
   - Area: Global or specific region
   - Format: CSV

3. Download and extract to:
   {archive_dir}

4. Run converter:
   python data_converters/converters/convert_nasa_firms.py

Archive Data Availability:
- MODIS: 2000-11 to present
- VIIRS S-NPP: 2012-01 to present
- VIIRS NOAA-20: 2018-04 to present
- VIIRS NOAA-21: 2024-01 to present

Note: Each year of global data is ~500MB-1GB (VIIRS) or ~200MB (MODIS)
""".format(archive_dir=ARCHIVE_DIR))


def check_archive_files():
    """Check for existing archive files."""
    if not ARCHIVE_DIR.exists():
        return []

    archive_files = list(ARCHIVE_DIR.glob("*.csv"))
    return archive_files


def get_map_key(args):
    """Get MAP_KEY from args or environment."""
    if args.key:
        return args.key

    # Check environment variable
    key = os.environ.get('NASA_FIRMS_KEY') or os.environ.get('FIRMS_MAP_KEY')
    if key:
        return key

    # Check config file
    config_path = OUTPUT_DIR / "config.json"
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
            if 'map_key' in config:
                return config['map_key']

    return None


def save_map_key(map_key):
    """Save MAP_KEY to config file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config_path = OUTPUT_DIR / "config.json"

    config = {}
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)

    config['map_key'] = map_key

    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    print(f"  MAP_KEY saved to {config_path}")


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Download NASA FIRMS active fire data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download last 7 days of VIIRS data for USA
  python download_nasa_firms.py --nrt --days 7 --region usa --key YOUR_KEY

  # Download all available sensors for last 3 days
  python download_nasa_firms.py --nrt --days 3 --all-sensors --key YOUR_KEY

  # Get archive download instructions
  python download_nasa_firms.py --archive
        """
    )

    # Mode
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--nrt', action='store_true',
                      help='Download near-real-time data (last 10 days max)')
    mode.add_argument('--archive', action='store_true',
                      help='Show archive download instructions')

    # NRT options
    parser.add_argument('--days', type=int, default=7,
                        help='Number of days of NRT data (1-10, default: 7)')
    parser.add_argument('--region', type=str, default='world',
                        choices=list(REGIONS.keys()),
                        help='Region to download (default: world)')
    parser.add_argument('--sensor', type=str, default='VIIRS_NOAA20_NRT',
                        choices=list(SENSORS.keys()),
                        help='Sensor type (default: VIIRS_NOAA20_NRT)')
    parser.add_argument('--all-sensors', action='store_true',
                        help='Download from all sensors')

    # API key
    parser.add_argument('--key', type=str,
                        help='NASA FIRMS MAP_KEY (or set NASA_FIRMS_KEY env var)')
    parser.add_argument('--save-key', action='store_true',
                        help='Save MAP_KEY to config file for future use')

    return parser.parse_args()


def main():
    """Main download logic."""
    args = parse_args()

    print("="*80)
    print("NASA FIRMS Active Fire Data Downloader")
    print("="*80)

    # Archive mode - just show instructions
    if args.archive:
        download_archive_info()

        # Check for existing archive files
        archive_files = check_archive_files()
        if archive_files:
            print(f"\nExisting archive files found ({len(archive_files)}):")
            for f in archive_files[:10]:
                print(f"  {f.name}")
            if len(archive_files) > 10:
                print(f"  ... and {len(archive_files) - 10} more")

        return 0

    # NRT mode
    map_key = get_map_key(args)
    if not map_key:
        print("\nERROR: No MAP_KEY provided!")
        print("\nTo get a free MAP_KEY:")
        print("  1. Go to: https://firms.modaps.eosdis.nasa.gov/api/area/")
        print("  2. Register for a free account")
        print("  3. Use: python download_nasa_firms.py --nrt --key YOUR_MAP_KEY")
        print("  4. Optionally save key: --save-key")
        return 1

    if args.save_key:
        save_map_key(map_key)

    # Validate days
    if args.days < 1 or args.days > 10:
        print("ERROR: --days must be between 1 and 10 for NRT data")
        return 1

    # Determine sensors to download
    if args.all_sensors:
        sensors = list(SENSORS.keys())
    else:
        sensors = [args.sensor]

    print(f"\nMode: Near Real-Time (NRT)")
    print(f"Days: {args.days}")
    print(f"Region: {args.region}")
    print(f"Sensors: {', '.join(sensors)}")
    print(f"Output: {OUTPUT_DIR}")
    print()

    # Download data
    successful = []
    failed = []
    total_fires = 0

    for sensor in sensors:
        csv_data, count = download_nrt_data(map_key, sensor, args.region, args.days)

        if csv_data and count > 0:
            output_path, size_kb = save_nrt_file(sensor, args.region, args.days, csv_data)
            successful.append(sensor)
            total_fires += count
            print(f"    Saved: {output_path.name} ({size_kb:.1f} KB)")
        elif csv_data and count == 0:
            print(f"    No fire detections for {sensor}")
        else:
            failed.append(sensor)

        # Rate limiting
        if sensor != sensors[-1]:
            time.sleep(1)

    # Summary
    print("\n" + "="*80)
    print("DOWNLOAD COMPLETE")
    print("="*80)
    print(f"\nSuccessful sensors: {len(successful)}/{len(sensors)}")
    print(f"Total fire detections: {total_fires:,}")

    if failed:
        print(f"\nFailed sensors: {failed}")

    print(f"\nOutput directory: {OUTPUT_DIR}")
    print("\nNext steps:")
    print("  python data_converters/converters/convert_nasa_firms.py")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
