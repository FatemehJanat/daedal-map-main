"""
Download and extract NOAA Storm Events data.

Downloads StormEvents_details CSV files from NOAA's FTP directory,
extracts them, and cleans up compressed files.

Usage:
    python download_and_extract_noaa.py              # Interactive menu
    python download_and_extract_noaa.py 2020         # Download specific year
    python download_and_extract_noaa.py 2020-2022    # Download year range
    python download_and_extract_noaa.py recent       # Download last 3 years
    python download_and_extract_noaa.py all          # Download ALL years

Downloads to: C:/Users/bryan/Desktop/county_map_data/Raw data/noaa_storms/
"""
import requests
import gzip
import shutil
import sys
from pathlib import Path
from bs4 import BeautifulSoup
import re

# Configuration
NOAA_BASE_URL = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"
RAW_DATA_DIR = Path("C:/Users/bryan/Desktop/county_map_data/Raw data/noaa_storms")
DOWNLOADS_DIR = Path.home() / "Downloads"
TIMEOUT = 120

def setup_output_dir():
    """Create output directory if needed."""
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {RAW_DATA_DIR}")


def fetch_available_files():
    """Fetch list of available files from NOAA."""
    print(f"\nFetching file listing from NOAA...")

    try:
        response = requests.get(NOAA_BASE_URL, timeout=TIMEOUT)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        # Collect all three file types
        file_types = ['StormEvents_details', 'StormEvents_fatalities', 'StormEvents_locations']
        files_by_year = {}

        for link in soup.find_all('a'):
            href = link.get('href')
            if href and href.endswith('.csv.gz'):
                # Check if it's one of our file types
                for file_type in file_types:
                    if file_type in href:
                        # Extract year from filename
                        year_match = re.search(r'_d(\d{4})_', href)
                        if year_match:
                            year = int(year_match.group(1))

                            # Group files by year
                            if year not in files_by_year:
                                files_by_year[year] = []

                            files_by_year[year].append({
                                'filename': href,
                                'type': file_type,
                                'url': NOAA_BASE_URL + href
                            })
                        break

        # Convert to list of year groups
        year_groups = []
        for year in sorted(files_by_year.keys()):
            year_groups.append({
                'year': year,
                'files': files_by_year[year]
            })

        return year_groups

    except Exception as e:
        print(f"Error fetching file list: {e}")
        return []


def download_file(url, output_path):
    """Download file with progress indication."""
    try:
        print(f"\n  Downloading: {url.split('/')[-1]}")

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

        print(f"\n  Downloaded: {output_path}")
        return True

    except Exception as e:
        print(f"\n  Error downloading: {e}")
        return False


def extract_file(gz_path):
    """Extract .gz file to .csv and delete compressed version."""
    csv_path = gz_path.with_suffix('')  # Remove .gz extension

    print(f"  Extracting to: {csv_path.name}")

    try:
        with gzip.open(gz_path, 'rb') as f_in:
            with open(csv_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)

        # Get file sizes
        csv_size_mb = csv_path.stat().st_size / (1024 * 1024)
        gz_size_mb = gz_path.stat().st_size / (1024 * 1024)

        print(f"  Extracted: {csv_size_mb:.1f} MB (was {gz_size_mb:.1f} MB compressed)")

        # Delete compressed file
        gz_path.unlink()
        print(f"  Removed: {gz_path.name}")

        return csv_path

    except Exception as e:
        print(f"  Error extracting: {e}")
        return None


def move_from_downloads(filename):
    """Move file from Downloads folder to RAW_DATA_DIR."""
    downloads_path = DOWNLOADS_DIR / filename
    target_path = RAW_DATA_DIR / filename

    if downloads_path.exists():
        print(f"  Moving from Downloads: {filename}")
        shutil.move(str(downloads_path), str(target_path))
        return target_path

    return None


def check_year_complete(year_group):
    """Check if all files for a year are already extracted."""
    for file_info in year_group['files']:
        filename = file_info['filename']
        csv_path = RAW_DATA_DIR / filename.replace('.gz', '')
        if not csv_path.exists():
            return False
    return True


def process_year_group(year_group):
    """Download, extract, and clean up all files for a single year."""
    year = year_group['year']
    files = year_group['files']

    print(f"\n  Found {len(files)} files for {year}:")
    for f in files:
        print(f"    - {f['type'].replace('StormEvents_', '')}")

    success_count = 0
    for file_info in files:
        filename = file_info['filename']
        file_type = file_info['type']
        url = file_info['url']

        # Check if already extracted (CSV exists)
        csv_path = RAW_DATA_DIR / filename.replace('.gz', '')
        if csv_path.exists():
            csv_size_mb = csv_path.stat().st_size / (1024 * 1024)
            print(f"    OK {file_type.replace('StormEvents_', '')}: {csv_size_mb:.1f} MB (already extracted)")
            success_count += 1
            continue

        # Check if compressed file exists in RAW_DATA_DIR
        gz_path = RAW_DATA_DIR / filename
        if gz_path.exists():
            print(f"    -> {file_type.replace('StormEvents_', '')}: extracting...")
            if extract_file(gz_path):
                success_count += 1
            continue

        # Check if file is in Downloads folder
        moved_path = move_from_downloads(filename)
        if moved_path:
            print(f"    -> {file_type.replace('StormEvents_', '')}: moved from Downloads, extracting...")
            if extract_file(moved_path):
                success_count += 1
            continue

        # Download file
        print(f"    -> {file_type.replace('StormEvents_', '')}: downloading...")
        download_path = RAW_DATA_DIR / filename
        if download_file(url, download_path):
            if extract_file(download_path):
                success_count += 1

    return success_count == len(files)


def select_files_to_download(available_files):
    """Interactive or command-line file selection."""
    # Scan for already complete years
    print("\nScanning for existing files...")
    complete_years = []
    incomplete_years = []

    for year_group in available_files:
        if check_year_complete(year_group):
            complete_years.append(year_group['year'])
        else:
            incomplete_years.append(year_group)

    if complete_years:
        print(f"Already complete: {len(complete_years)} year(s) - {', '.join(map(str, sorted(complete_years)))}")
    if incomplete_years:
        print(f"Need download: {len(incomplete_years)} year(s)")
    else:
        print("\nAll files already downloaded and extracted!")
        return []

    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()

        # Recent: last 3 years
        if arg == 'recent':
            # Get last 3 years from incomplete list
            to_download = [yg for yg in available_files[-3:] if yg in incomplete_years]
            if to_download:
                print(f"\nDownloading recent years (skipping complete): {', '.join(str(f['year']) for f in to_download)}")
            else:
                print(f"\nRecent 3 years already complete!")
            return to_download

        # All years
        elif arg == 'all':
            if not incomplete_years:
                print("\nAll years already complete!")
                return []
            print(f"\nDownloading {len(incomplete_years)} incomplete year(s): {incomplete_years[0]['year']}-{incomplete_years[-1]['year']}")
            print(f"Skipping {len(complete_years)} already complete year(s)")
            confirm = input("Continue? (y/N): ").strip().lower()
            if confirm == 'y':
                return incomplete_years
            else:
                print("Cancelled.")
                return []

        # Year range: 2020-2022
        elif '-' in arg:
            try:
                start_year, end_year = map(int, arg.split('-'))
                # Filter to incomplete years in range
                to_download = [yg for yg in incomplete_years if start_year <= yg['year'] <= end_year]
                if not to_download:
                    # Check if years exist but are complete
                    complete_in_range = [y for y in complete_years if start_year <= y <= end_year]
                    if complete_in_range:
                        print(f"\nAll years in range {start_year}-{end_year} already complete!")
                    else:
                        print(f"\nError: No files found for years {start_year}-{end_year}")
                    return []
                print(f"\nDownloading years {start_year}-{end_year}: {len(to_download)} year(s) (skipping complete)")
                return to_download
            except ValueError:
                print(f"\nError: Invalid year range '{arg}'. Use format: 2020-2022")
                return []

        # Specific year
        else:
            try:
                year = int(arg)
                # Check if year is complete
                if year in complete_years:
                    print(f"\nYear {year} already complete (all 3 files extracted)!")
                    return []
                # Find year in incomplete list
                to_download = [yg for yg in incomplete_years if yg['year'] == year]
                if not to_download:
                    print(f"\nError: Year {year} not found")
                    print(f"Available years: {available_files[0]['year']}-{available_files[-1]['year']}")
                    return []
                print(f"\nDownloading year: {year}")
                return to_download
            except ValueError:
                print(f"\nError: Invalid argument '{arg}'")
                print("Usage: python download_and_extract_noaa.py [year|recent|all|2020-2022]")
                return []

    # Interactive mode
    print("\n" + "="*80)
    print("INTERACTIVE MODE")
    print("="*80)
    total_incomplete = sum(len(yg['files']) for yg in incomplete_years)
    print(f"\nIncomplete years: {len(incomplete_years)} ({total_incomplete} files needed)")
    print("\nOptions:")
    print("  1. Download recent 3 years")
    print("  2. Download specific year")
    print("  3. Download year range")
    print("  4. Download ALL incomplete years")

    choice = input("\nChoice (1-4): ").strip()

    if choice == '1':
        to_download = [yg for yg in available_files[-3:] if yg in incomplete_years]
        return to_download

    elif choice == '2':
        year = input("Enter year: ").strip()
        try:
            year = int(year)
            if year in complete_years:
                print(f"Year {year} already complete!")
                return []
            to_download = [yg for yg in incomplete_years if yg['year'] == year]
            if not to_download:
                print(f"Year {year} not found")
                return []
            return to_download
        except ValueError:
            print("Invalid year")
            return []

    elif choice == '3':
        range_input = input("Enter year range (e.g., 2020-2022): ").strip()
        try:
            start_year, end_year = map(int, range_input.split('-'))
            to_download = [yg for yg in incomplete_years if start_year <= yg['year'] <= end_year]
            if not to_download:
                print(f"No incomplete years found in range {start_year}-{end_year}")
                return []
            print(f"Found {len(to_download)} incomplete year(s)")
            return to_download
        except ValueError:
            print("Invalid range format")
            return []

    elif choice == '4':
        if not incomplete_years:
            print("All years already complete!")
            return []
        confirm = input(f"Download {len(incomplete_years)} incomplete year(s)? (y/N): ").strip().lower()
        if confirm == 'y':
            return incomplete_years
        else:
            return []

    else:
        print("Invalid choice")
        return []


def main():
    """Main download and extraction logic."""
    print("="*80)
    print("NOAA Storm Events - Download & Extract")
    print("="*80)

    setup_output_dir()

    # Fetch available files
    available_files = fetch_available_files()
    if not available_files:
        print("\nError: Could not fetch file list from NOAA")
        return 1

    total_files = sum(len(yg['files']) for yg in available_files)
    print(f"Found {len(available_files)} years ({total_files} total files)")
    print(f"Years: {available_files[0]['year']} - {available_files[-1]['year']}")

    # Select files to download
    to_download = select_files_to_download(available_files)
    if not to_download:
        print("\nNo files selected.")
        return 0

    # Process files
    total_to_download = sum(len(yg['files']) for yg in to_download)
    print("\n" + "="*80)
    print(f"Processing {len(to_download)} year(s) ({total_to_download} total files)")
    print("="*80)

    successful = []
    failed = []

    for i, year_group in enumerate(to_download, 1):
        print(f"\n[{i}/{len(to_download)}] Year {year_group['year']}")

        if process_year_group(year_group):
            successful.append(year_group['year'])
        else:
            failed.append(year_group['year'])

    # Summary
    print("\n" + "="*80)
    print("COMPLETE!")
    print("="*80)

    print(f"\nSuccessful: {len(successful)} year(s)")
    if successful:
        print(f"  Years: {', '.join(map(str, successful))}")

    if failed:
        print(f"\nFailed: {len(failed)} year(s)")
        print(f"  Years: {', '.join(map(str, failed))}")

    if successful:
        print(f"\nFiles location: {RAW_DATA_DIR}")
        print("\nNext steps:")
        print("  1. Run converter: python data_converters/convert_noaa_storms.py")
        print("  2. Build references: python data_converters/build_storm_reference.py")
        print("  3. Create reference.json: python data_converters/create_reference_json.py")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
