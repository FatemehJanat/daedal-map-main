"""
NOAA Climate at a Glance Downloader

Downloads historical climate time series data from NOAA NCEI.
Includes temperature, precipitation, and drought indices at national/state/county level.

Usage:
    python download_noaa_climate.py

Output:
    Raw data saved to: county-map-data/Raw data/noaa/climate_at_a_glance/
    - CSV files per state/parameter combination
    - noaa_climate_metadata.json (download info)

Data Source:
    NOAA National Centers for Environmental Information (NCEI)
    https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/

Coverage:
    - Monthly data from 1895 to present
    - All 48 contiguous US states + national
    - Temperature (avg, max, min), precipitation, drought indices
"""

import requests
from pathlib import Path
import json
from datetime import datetime
import sys
import time

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/noaa/climate_at_a_glance")
TIMEOUT = 60

# Base URL pattern for Climate at a Glance CSV downloads
# Format: /national/time-series/{location}/{parameter}/{timescale}/{month}/{startyear}-{endyear}.csv
BASE_URL = "https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance"

# US State FIPS codes for statewide data
US_STATES = {
    "01": "Alabama", "02": "Alaska", "04": "Arizona", "05": "Arkansas",
    "06": "California", "08": "Colorado", "09": "Connecticut", "10": "Delaware",
    "11": "District of Columbia", "12": "Florida", "13": "Georgia", "15": "Hawaii",
    "16": "Idaho", "17": "Illinois", "18": "Indiana", "19": "Iowa",
    "20": "Kansas", "21": "Kentucky", "22": "Louisiana", "23": "Maine",
    "24": "Maryland", "25": "Massachusetts", "26": "Michigan", "27": "Minnesota",
    "28": "Mississippi", "29": "Missouri", "30": "Montana", "31": "Nebraska",
    "32": "Nevada", "33": "New Hampshire", "34": "New Jersey", "35": "New Mexico",
    "36": "New York", "37": "North Carolina", "38": "North Dakota", "39": "Ohio",
    "40": "Oklahoma", "41": "Oregon", "42": "Pennsylvania", "44": "Rhode Island",
    "45": "South Carolina", "46": "South Dakota", "47": "Tennessee", "48": "Texas",
    "49": "Utah", "50": "Vermont", "51": "Virginia", "53": "Washington",
    "54": "West Virginia", "55": "Wisconsin", "56": "Wyoming"
}

# Parameters to download
PARAMETERS = {
    "tavg": "Average Temperature",
    "tmax": "Maximum Temperature",
    "tmin": "Minimum Temperature",
    "pcp": "Precipitation",
    "pdsi": "Palmer Drought Severity Index",
    "phdi": "Palmer Hydrological Drought Index",
    "zndx": "Palmer Z-Index",
    "cdd": "Cooling Degree Days",
    "hdd": "Heating Degree Days"
}

# Time range
START_YEAR = 1895
END_YEAR = 2025


def setup_output_dir():
    """Create output directories if they don't exist."""
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DATA_DIR / "national").mkdir(exist_ok=True)
    (RAW_DATA_DIR / "state").mkdir(exist_ok=True)
    print(f"Output directory: {RAW_DATA_DIR}")


def download_csv(url, output_path, description, retries=3):
    """Download a CSV file from URL with retries."""
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=TIMEOUT, allow_redirects=True)

            # Check if we got actual CSV data
            content_type = response.headers.get('content-type', '')
            if 'text/csv' in content_type or response.text.startswith('Date,'):
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(response.text)
                return True, len(response.text.split('\n')) - 1
            elif response.status_code == 200:
                # Might still be valid CSV without proper content-type
                if ',' in response.text and len(response.text) > 50:
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write(response.text)
                    return True, len(response.text.split('\n')) - 1

            if attempt < retries - 1:
                time.sleep(1)

        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                return False, 0

    return False, 0


def download_national_data():
    """Download national-level climate data for all parameters."""
    print("\n" + "-" * 50)
    print("Downloading NATIONAL level data...")
    print("-" * 50)

    results = {}
    national_dir = RAW_DATA_DIR / "national"

    for param_code, param_name in PARAMETERS.items():
        # URL pattern: /national/time-series/110/{param}/all/1/{start}-{end}.csv
        # 110 = contiguous US, all = all months, 1 = include all data
        url = f"{BASE_URL}/national/time-series/110/{param_code}/all/1/{START_YEAR}-{END_YEAR}.csv"
        output_path = national_dir / f"national_{param_code}_{START_YEAR}-{END_YEAR}.csv"

        success, records = download_csv(url, output_path, f"National {param_name}")
        results[f"national_{param_code}"] = {
            "success": success,
            "records": records,
            "file": output_path.name if success else None
        }

        status = "OK" if success else "FAILED"
        print(f"  {param_name}: {status} ({records} records)")

        time.sleep(0.5)  # Rate limiting

    return results


def download_state_data():
    """Download state-level climate data."""
    print("\n" + "-" * 50)
    print("Downloading STATE level data...")
    print("-" * 50)

    results = {}
    state_dir = RAW_DATA_DIR / "state"

    # Download temperature and precipitation for each state
    key_params = ["tavg", "tmax", "tmin", "pcp", "pdsi"]

    for state_fips, state_name in US_STATES.items():
        print(f"\n  {state_name} ({state_fips}):")
        state_results = {}

        for param_code in key_params:
            # URL pattern: /statewide/time-series/{state_fips}/{param}/all/1/{start}-{end}.csv
            url = f"{BASE_URL}/statewide/time-series/{state_fips}/{param_code}/all/1/{START_YEAR}-{END_YEAR}.csv"
            output_path = state_dir / f"state_{state_fips}_{param_code}_{START_YEAR}-{END_YEAR}.csv"

            success, records = download_csv(url, output_path, f"{state_name} {param_code}")
            state_results[param_code] = {
                "success": success,
                "records": records
            }

            status = "OK" if success else "FAIL"
            print(f"    {param_code}: {status}", end=" | ")

            time.sleep(0.3)  # Rate limiting

        print()
        results[state_fips] = state_results

    return results


def download_all():
    """Download all Climate at a Glance data."""
    print("=" * 70)
    print("NOAA Climate at a Glance Downloader")
    print("=" * 70)
    print()
    print("Source: NOAA National Centers for Environmental Information (NCEI)")
    print("Portal: https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/")
    print()
    print(f"Time range: {START_YEAR} - {END_YEAR}")
    print(f"Parameters: {', '.join(PARAMETERS.keys())}")
    print()

    setup_output_dir()

    # Download national data
    national_results = download_national_data()

    # Download state data
    state_results = download_state_data()

    # Save metadata
    metadata = {
        "download_date": datetime.now().isoformat(),
        "source": "NOAA National Centers for Environmental Information (NCEI)",
        "source_url": "https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/",
        "license": "Public Domain (US Government)",
        "time_range": {
            "start_year": START_YEAR,
            "end_year": END_YEAR
        },
        "parameters": PARAMETERS,
        "geographic_coverage": {
            "national": "Contiguous 48 states",
            "states": len(US_STATES)
        },
        "national_results": national_results,
        "state_download_summary": {
            "total_states": len(state_results),
            "parameters_per_state": ["tavg", "tmax", "tmin", "pcp", "pdsi"]
        },
        "notes": [
            "Monthly climate data since 1895",
            "Temperature in degrees Fahrenheit",
            "Precipitation in inches",
            "PDSI ranges from -10 (extreme drought) to +10 (extreme wet)",
            "State data limited to key parameters to reduce download time"
        ]
    }

    metadata_path = RAW_DATA_DIR / "noaa_climate_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"\nMetadata saved: {metadata_path}")

    # Summary
    print("\n" + "=" * 70)
    print("DOWNLOAD COMPLETE")
    print("=" * 70)

    national_success = sum(1 for r in national_results.values() if r.get("success"))
    print(f"National files: {national_success}/{len(national_results)}")

    state_success = sum(
        1 for state in state_results.values()
        for param in state.values()
        if param.get("success")
    )
    total_state_files = len(state_results) * 5  # 5 params per state
    print(f"State files: {state_success}/{total_state_files}")

    return True


def main():
    success = download_all()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
