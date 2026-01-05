"""
Download U.S. Drought Monitor county-level statistics.

Downloads comprehensive drought statistics for all U.S. counties from 2000-present.
Data includes drought severity percentages (D0-D4) by area and population.

API Documentation: https://droughtmonitor.unl.edu/DmData/DataDownload/WebServiceInfo.aspx

Usage:
    python download_usdm_drought.py              # Download all counties, full history
    python download_usdm_drought.py 2020-2024    # Download specific date range
    python download_usdm_drought.py recent       # Download last 2 years
"""
import requests
import sys
from pathlib import Path
from datetime import datetime, timedelta
import time

# Configuration
API_BASE = "https://usdmdataservices.unl.edu/api/CountyStatistics"
OUTPUT_DIR = Path("C:/Users/bryan/Desktop/county_map_data/Raw data/usdm_drought")
TIMEOUT = 120

# U.S. state abbreviations
US_STATES = [
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
    'DC', 'PR', 'VI', 'GU', 'AS', 'MP'
]


def setup_output_dir():
    """Create output directory if needed."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {OUTPUT_DIR}")


def download_state_data(state, start_date, end_date, stat_type="GetDroughtSeverityStatisticsByAreaPercent"):
    """
    Download drought statistics for all counties in a state.

    Args:
        state: Two-letter state abbreviation
        start_date: Start date as M/D/YYYY string
        end_date: End date as M/D/YYYY string
        stat_type: Statistics type (default: area percent)

    Returns:
        str: CSV content if successful, None otherwise
    """
    url = f"{API_BASE}/{stat_type}"
    params = {
        'aoi': state,
        'startdate': start_date,
        'enddate': end_date,
        'statisticsType': '2'  # Categorical format
    }

    headers = {
        'Accept': 'text/csv'
    }

    try:
        print(f"  Requesting {state}: {start_date} to {end_date}")
        response = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        response.raise_for_status()

        # Check if we got data
        if len(response.text) < 100:
            print(f"  WARNING: {state} returned very little data")
            return None

        return response.text

    except requests.exceptions.Timeout:
        print(f"  ERROR: {state} request timed out")
        return None
    except requests.exceptions.RequestException as e:
        print(f"  ERROR: {state} request failed: {e}")
        return None


def save_csv(content, filename):
    """Save CSV content to file."""
    output_path = OUTPUT_DIR / filename

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)

    size_kb = output_path.stat().st_size / 1024
    print(f"  Saved: {filename} ({size_kb:.1f} KB)")
    return output_path


def parse_date_range(arg):
    """Parse command line date range argument."""
    if arg == 'recent':
        # Last 2 years
        end_date = datetime.now()
        start_date = end_date - timedelta(days=730)
        return start_date, end_date

    elif '-' in arg:
        # Year range like "2020-2024"
        try:
            start_year, end_year = map(int, arg.split('-'))
            start_date = datetime(start_year, 1, 1)
            end_date = datetime(end_year, 12, 31)
            return start_date, end_date
        except ValueError:
            print(f"Error: Invalid date range '{arg}'. Use format: 2020-2024")
            return None, None

    else:
        print(f"Error: Unknown argument '{arg}'")
        return None, None


def main():
    """Main download logic."""
    print("="*80)
    print("U.S. Drought Monitor - County Statistics Downloader")
    print("="*80)

    setup_output_dir()

    # Determine date range
    if len(sys.argv) > 1:
        start_date, end_date = parse_date_range(sys.argv[1])
        if not start_date:
            return 1
    else:
        # Default: full history (USDM started in 2000)
        start_date = datetime(2000, 1, 1)
        end_date = datetime.now()

    # Format dates for API (M/D/YYYY without leading zeros)
    start_str = f"{start_date.month}/{start_date.day}/{start_date.year}"
    end_str = f"{end_date.month}/{end_date.day}/{end_date.year}"

    print(f"\nDate range: {start_str} to {end_str}")
    print(f"Downloading data for {len(US_STATES)} states/territories\n")

    # Download data for each state
    successful = []
    failed = []

    for i, state in enumerate(US_STATES, 1):
        print(f"[{i}/{len(US_STATES)}] {state}")

        # Download area percent statistics
        csv_data = download_state_data(state, start_str, end_str)

        if csv_data:
            # Save to file
            filename = f"usdm_{state}_{start_date.year}-{end_date.year}_area_percent.csv"
            save_csv(csv_data, filename)
            successful.append(state)
        else:
            failed.append(state)

        # Rate limiting - be nice to the API
        if i < len(US_STATES):
            time.sleep(1)

    # Summary
    print("\n" + "="*80)
    print("COMPLETE!")
    print("="*80)

    print(f"\nSuccessful: {len(successful)} states")
    if successful:
        print(f"  States: {', '.join(successful)}")

    if failed:
        print(f"\nFailed: {len(failed)} states")
        print(f"  States: {', '.join(failed)}")

    print(f"\nFiles location: {OUTPUT_DIR}")
    print("\nNext steps:")
    print("  1. Run converter: python data_converters/convert_usdm_drought.py")
    print("  2. Add to catalog.json")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
