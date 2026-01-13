"""
Download NASA LANCE Global Flood Product (MCDWD/VCDWD) data.

NASA LANCE provides near-real-time and archived flood detection from MODIS/VIIRS.

Data Sources:
- MCDWD_L3_NRT (MODIS): 250m resolution, 2003-present (reprocessed archive)
- VCDWD_L3_NRT (VIIRS): 375m resolution, 2012-present

Product Details:
- 1-day, 2-day, 3-day composites (cloud filtering)
- Flood classes: 1=open water, 2=flood, 3=recurring flood (new Dec 2025)
- HDF4 format with 12 raster layers per file
- Sinusoidal tile grid (h##v## format, ~10x10 degree tiles)

Data Access:
- Archive: https://nrt3.modaps.eosdis.nasa.gov/archive/allData/61/MCDWD_L3_NRT/
- Requires NASA Earthdata login: https://urs.earthdata.nasa.gov/

Usage:
    # Download 2-day composites for 2015-present (all tiles)
    python download_lance_floods.py --start 2015-01-01 --end 2025-12-31

    # Download specific date range
    python download_lance_floods.py --start 2024-01-01 --end 2024-01-31

    # Download only specific tiles (e.g., USA coverage)
    python download_lance_floods.py --start 2024-01-01 --tiles h08v05,h09v05,h10v04

    # List available tiles for a region
    python download_lance_floods.py --list-tiles --region usa

Documentation:
    https://www.earthdata.nasa.gov/data/instruments/viirs/near-real-time-data/nrt-global-flood-products
"""
import requests
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
import time
import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import netrc

# Configuration
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/lance_floods")
ARCHIVE_URL = "https://nrt3.modaps.eosdis.nasa.gov/archive/allData/61/MCDWD_L3_NRT"
VIIRS_ARCHIVE_URL = "https://nrt3.modaps.eosdis.nasa.gov/archive/allData/5200/VCDWD_L3_NRT"

# Earthdata authentication
EARTHDATA_URL = "https://urs.earthdata.nasa.gov"

# Timeout for requests
TIMEOUT = 60

# MODIS sinusoidal tile grid
# Tiles that cover land (approximate - not all contain flood-prone areas)
# Format: h##v## where h=horizontal (0-35), v=vertical (0-17)
LAND_TILES = [
    # North America
    'h08v04', 'h09v04', 'h10v04', 'h11v04', 'h12v04', 'h13v04',  # Canada
    'h08v05', 'h09v05', 'h10v05', 'h11v05', 'h12v05',  # USA North
    'h08v06', 'h09v06', 'h10v06', 'h11v06',  # USA South/Mexico
    'h07v06', 'h07v07', 'h08v07', 'h09v07',  # Central America

    # South America
    'h10v07', 'h11v07', 'h12v07', 'h13v07', 'h14v07',
    'h10v08', 'h11v08', 'h12v08', 'h13v08', 'h14v08',
    'h10v09', 'h11v09', 'h12v09', 'h13v09', 'h14v09',
    'h10v10', 'h11v10', 'h12v10', 'h13v10', 'h14v10',
    'h11v11', 'h12v11', 'h13v11', 'h14v11',
    'h12v12', 'h13v12', 'h14v12',
    'h13v13', 'h14v13',

    # Europe
    'h17v03', 'h18v03', 'h19v03', 'h20v03',
    'h17v04', 'h18v04', 'h19v04', 'h20v04', 'h21v04',
    'h18v05', 'h19v05', 'h20v05',

    # Africa
    'h16v05', 'h17v05', 'h18v05', 'h19v05', 'h20v05', 'h21v05',
    'h16v06', 'h17v06', 'h18v06', 'h19v06', 'h20v06', 'h21v06',
    'h16v07', 'h17v07', 'h18v07', 'h19v07', 'h20v07', 'h21v07', 'h22v07',
    'h17v08', 'h18v08', 'h19v08', 'h20v08', 'h21v08', 'h22v08',
    'h19v09', 'h20v09', 'h21v09',
    'h19v10', 'h20v10', 'h21v10',
    'h20v11', 'h21v11',
    'h20v12',

    # Asia
    'h22v03', 'h23v03', 'h24v03', 'h25v03', 'h26v03', 'h27v03',
    'h22v04', 'h23v04', 'h24v04', 'h25v04', 'h26v04', 'h27v04', 'h28v04', 'h29v04',
    'h23v05', 'h24v05', 'h25v05', 'h26v05', 'h27v05', 'h28v05', 'h29v05',
    'h24v06', 'h25v06', 'h26v06', 'h27v06', 'h28v06', 'h29v06',
    'h25v07', 'h26v07', 'h27v07', 'h28v07', 'h29v07',
    'h26v08', 'h27v08', 'h28v08', 'h29v08',
    'h27v09', 'h28v09', 'h29v09',
    'h28v10', 'h29v10',

    # Australia/Oceania
    'h29v10', 'h30v10', 'h31v10', 'h32v10',
    'h29v11', 'h30v11', 'h31v11', 'h32v11',
    'h30v12', 'h31v12', 'h32v12',
]

# Regional tile subsets
REGION_TILES = {
    'usa': ['h08v04', 'h09v04', 'h10v04', 'h11v04', 'h12v04',
            'h08v05', 'h09v05', 'h10v05', 'h11v05', 'h12v05',
            'h08v06', 'h09v06', 'h10v06', 'h11v06'],
    'europe': ['h17v03', 'h18v03', 'h19v03', 'h20v03',
               'h17v04', 'h18v04', 'h19v04', 'h20v04', 'h21v04',
               'h18v05', 'h19v05', 'h20v05'],
    'asia': ['h23v04', 'h24v04', 'h25v04', 'h26v04', 'h27v04', 'h28v04',
             'h23v05', 'h24v05', 'h25v05', 'h26v05', 'h27v05', 'h28v05'],
    'australia': ['h29v10', 'h30v10', 'h31v10', 'h32v10',
                  'h29v11', 'h30v11', 'h31v11', 'h32v11'],
    'global': LAND_TILES,
}


def get_earthdata_session():
    """Create authenticated session for NASA Earthdata."""
    session = requests.Session()

    # Try to get credentials from environment
    username = os.environ.get('EARTHDATA_USERNAME')
    password = os.environ.get('EARTHDATA_PASSWORD')

    # Try netrc file
    if not username or not password:
        try:
            netrc_file = netrc.netrc()
            auth = netrc_file.authenticators('urs.earthdata.nasa.gov')
            if auth:
                username, _, password = auth
        except (FileNotFoundError, netrc.NetrcParseError):
            pass

    # Try config file
    if not username or not password:
        config_path = OUTPUT_DIR / "earthdata_config.json"
        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)
                username = config.get('username')
                password = config.get('password')

    if not username or not password:
        return None, "No Earthdata credentials found"

    # Configure session for Earthdata authentication
    session.auth = (username, password)

    # Earthdata requires redirect handling
    session.headers.update({
        'User-Agent': 'county-map-data-downloader/1.0'
    })

    return session, None


def save_earthdata_config(username, password):
    """Save Earthdata credentials to config file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config_path = OUTPUT_DIR / "earthdata_config.json"

    with open(config_path, 'w') as f:
        json.dump({'username': username, 'password': password}, f, indent=2)

    # Set restrictive permissions
    os.chmod(config_path, 0o600)
    print(f"  Credentials saved to {config_path}")


def date_to_doy(date):
    """Convert date to year and day of year."""
    year = date.year
    doy = date.timetuple().tm_yday
    return year, doy


def list_available_files(session, year, doy):
    """List available HDF files for a given date."""
    url = f"{ARCHIVE_URL}/{year}/{doy:03d}/"

    try:
        response = session.get(url, timeout=TIMEOUT)
        if response.status_code == 404:
            return []
        response.raise_for_status()

        # Parse HTML for HDF file links
        # Pattern: MCDWD_L3_NRT.A{YYYY}{DOY}.h{HH}v{VV}.061.{timestamp}.hdf
        pattern = r'MCDWD_L3_NRT\.A\d{7}\.h\d{2}v\d{2}\.061\.\d+\.hdf'
        files = re.findall(pattern, response.text)

        return list(set(files))  # Remove duplicates

    except requests.exceptions.RequestException as e:
        print(f"  Error listing files for {year}/{doy:03d}: {e}")
        return []


def download_file(session, year, doy, filename, output_dir):
    """Download a single HDF file."""
    url = f"{ARCHIVE_URL}/{year}/{doy:03d}/{filename}"
    output_path = output_dir / str(year) / f"{doy:03d}" / filename

    # Skip if already downloaded
    if output_path.exists():
        return output_path, 0, True  # Already exists

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        response = session.get(url, timeout=TIMEOUT, stream=True)
        response.raise_for_status()

        # Write to file
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        size_mb = output_path.stat().st_size / (1024 * 1024)
        return output_path, size_mb, False  # Newly downloaded

    except requests.exceptions.RequestException as e:
        print(f"  Error downloading {filename}: {e}")
        return None, 0, False


def download_date_range(session, start_date, end_date, tiles, output_dir, max_workers=4):
    """Download flood data for a date range."""

    total_downloaded = 0
    total_skipped = 0
    total_size_mb = 0
    failed = []

    current = start_date
    while current <= end_date:
        year, doy = date_to_doy(current)
        date_str = current.strftime('%Y-%m-%d')

        print(f"\n{date_str} (DOY {doy}):")

        # List available files
        available = list_available_files(session, year, doy)

        if not available:
            print(f"  No data available")
            current += timedelta(days=1)
            continue

        # Filter to requested tiles
        if tiles:
            tile_set = set(tiles)
            available = [f for f in available if any(t in f for t in tile_set)]

        if not available:
            print(f"  No matching tiles")
            current += timedelta(days=1)
            continue

        print(f"  Found {len(available)} files")

        # Download files in parallel
        day_downloaded = 0
        day_skipped = 0
        day_size = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(download_file, session, year, doy, f, output_dir): f
                for f in available
            }

            for future in as_completed(futures):
                filename = futures[future]
                try:
                    result_path, size_mb, existed = future.result()
                    if result_path:
                        if existed:
                            day_skipped += 1
                        else:
                            day_downloaded += 1
                            day_size += size_mb
                    else:
                        failed.append(filename)
                except Exception as e:
                    print(f"  Error: {e}")
                    failed.append(futures[future])

        print(f"  Downloaded: {day_downloaded}, Skipped: {day_skipped}, Size: {day_size:.1f} MB")

        total_downloaded += day_downloaded
        total_skipped += day_skipped
        total_size_mb += day_size

        current += timedelta(days=1)

        # Brief pause to avoid rate limiting
        time.sleep(0.5)

    return total_downloaded, total_skipped, total_size_mb, failed


def estimate_download_size(start_date, end_date, tiles):
    """Estimate total download size."""
    days = (end_date - start_date).days + 1
    tiles_per_day = len(tiles) if tiles else len(LAND_TILES)

    # Approximate: 2-5 MB per tile per day
    avg_mb_per_tile = 3.5
    total_gb = (days * tiles_per_day * avg_mb_per_tile) / 1024

    return days, tiles_per_day, total_gb


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Download NASA LANCE Global Flood Product data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download 2015-present for global coverage
  python download_lance_floods.py --start 2015-01-01 --end 2025-12-31

  # Download only USA tiles for 2024
  python download_lance_floods.py --start 2024-01-01 --end 2024-12-31 --region usa

  # Download specific tiles
  python download_lance_floods.py --start 2024-01-01 --tiles h08v05,h09v05

  # Save Earthdata credentials
  python download_lance_floods.py --save-credentials

Before running:
  1. Register at https://urs.earthdata.nasa.gov/
  2. Set environment variables:
     EARTHDATA_USERNAME=your_username
     EARTHDATA_PASSWORD=your_password
  Or use --save-credentials to store locally
        """
    )

    # Date range
    parser.add_argument('--start', type=str, required=False,
                        help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, required=False,
                        help='End date (YYYY-MM-DD)')

    # Tile selection
    parser.add_argument('--tiles', type=str,
                        help='Comma-separated list of tiles (e.g., h08v05,h09v05)')
    parser.add_argument('--region', type=str, choices=list(REGION_TILES.keys()),
                        help='Download tiles for a region')

    # Options
    parser.add_argument('--list-tiles', action='store_true',
                        help='List available tiles for region')
    parser.add_argument('--estimate', action='store_true',
                        help='Estimate download size without downloading')
    parser.add_argument('--workers', type=int, default=4,
                        help='Number of parallel download workers (default: 4)')

    # Credentials
    parser.add_argument('--save-credentials', action='store_true',
                        help='Save Earthdata credentials to config file')
    parser.add_argument('--username', type=str,
                        help='Earthdata username')
    parser.add_argument('--password', type=str,
                        help='Earthdata password')

    return parser.parse_args()


def main():
    """Main download logic."""
    args = parse_args()

    print("="*80)
    print("NASA LANCE Global Flood Product Downloader")
    print("="*80)

    # Handle credential saving
    if args.save_credentials:
        username = args.username or input("Earthdata username: ")
        password = args.password or input("Earthdata password: ")
        save_earthdata_config(username, password)
        print("\nCredentials saved. You can now run downloads.")
        return 0

    # List tiles mode
    if args.list_tiles:
        region = args.region or 'global'
        tiles = REGION_TILES.get(region, LAND_TILES)
        print(f"\nTiles for {region} ({len(tiles)} tiles):")
        for tile in sorted(tiles):
            print(f"  {tile}")
        return 0

    # Require date range for download
    if not args.start or not args.end:
        print("\nERROR: --start and --end dates required for download")
        print("Use --help for usage information")
        return 1

    # Parse dates
    try:
        start_date = datetime.strptime(args.start, '%Y-%m-%d')
        end_date = datetime.strptime(args.end, '%Y-%m-%d')
    except ValueError as e:
        print(f"ERROR: Invalid date format: {e}")
        return 1

    # Determine tiles
    if args.tiles:
        tiles = [t.strip() for t in args.tiles.split(',')]
    elif args.region:
        tiles = REGION_TILES.get(args.region, LAND_TILES)
    else:
        tiles = LAND_TILES

    # Estimate mode
    if args.estimate:
        days, tile_count, est_gb = estimate_download_size(start_date, end_date, tiles)
        print(f"\nDownload Estimate:")
        print(f"  Date range: {args.start} to {args.end} ({days} days)")
        print(f"  Tiles: {tile_count}")
        print(f"  Estimated size: {est_gb:.1f} GB")
        print(f"\nNote: Actual size varies based on cloud cover and flood extent.")
        return 0

    # Get authenticated session
    session, error = get_earthdata_session()
    if error:
        print(f"\nERROR: {error}")
        print("\nTo set up authentication:")
        print("  1. Register at https://urs.earthdata.nasa.gov/")
        print("  2. Set environment variables:")
        print("     EARTHDATA_USERNAME=your_username")
        print("     EARTHDATA_PASSWORD=your_password")
        print("  Or: python download_lance_floods.py --save-credentials")
        return 1

    # Print summary
    days = (end_date - start_date).days + 1
    print(f"\nDownload Configuration:")
    print(f"  Date range: {args.start} to {args.end} ({days} days)")
    print(f"  Tiles: {len(tiles)}")
    print(f"  Output: {OUTPUT_DIR}")
    print(f"  Workers: {args.workers}")

    # Estimate size
    _, _, est_gb = estimate_download_size(start_date, end_date, tiles)
    print(f"  Estimated size: {est_gb:.1f} GB")

    print("\nStarting download...")

    # Download
    start_time = time.time()
    downloaded, skipped, size_mb, failed = download_date_range(
        session, start_date, end_date, tiles, OUTPUT_DIR, args.workers
    )
    elapsed = time.time() - start_time

    # Summary
    print("\n" + "="*80)
    print("DOWNLOAD COMPLETE")
    print("="*80)
    print(f"\nFiles downloaded: {downloaded:,}")
    print(f"Files skipped (existing): {skipped:,}")
    print(f"Total size: {size_mb/1024:.2f} GB")
    print(f"Time elapsed: {elapsed/60:.1f} minutes")

    if failed:
        print(f"\nFailed downloads: {len(failed)}")
        for f in failed[:10]:
            print(f"  {f}")
        if len(failed) > 10:
            print(f"  ... and {len(failed) - 10} more")

    print(f"\nOutput directory: {OUTPUT_DIR}")
    print("\nNext steps:")
    print("  python data_converters/converters/process_lance_floods.py")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
