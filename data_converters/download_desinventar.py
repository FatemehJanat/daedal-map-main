"""
DesInventar Global Disaster Database Downloader

Downloads disaster event data from DesInventar (UN UNDRR initiative).
Contains historical disaster records for 82+ countries since various years.

Usage:
    python download_desinventar.py
    python download_desinventar.py --countries col,per,mex

Output:
    Raw data saved to: county-map-data/Raw data/desinventar/
    - {country_code}_desinventar.xml per country
    - desinventar_metadata.json

Data Source:
    DesInventar - UN Office for Disaster Risk Reduction (UNDRR)
    https://www.desinventar.net/

Coverage:
    - 82+ countries across all continents
    - Geological and weather-related disasters
    - Various temporal coverage per country (some back to 1900s)
"""

import requests
from pathlib import Path
import json
from datetime import datetime
import sys
import time
import argparse

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/desinventar")
TIMEOUT = 120

# Base URL for DesInventar downloads
BASE_URL = "https://www.desinventar.net/DesInventar/download_base.jsp"

# Available countries with their codes (subset - most active databases)
COUNTRIES = {
    # Latin America & Caribbean
    "arg": "Argentina",
    "bol": "Bolivia",
    "chl": "Chile",
    "col": "Colombia",
    "cri": "Costa Rica",
    "ecu": "Ecuador",
    "slv": "El Salvador",
    "gtm": "Guatemala",
    "hnd": "Honduras",
    "mex": "Mexico",
    "nic": "Nicaragua",
    "pan": "Panama",
    "per": "Peru",
    "ven": "Venezuela",
    "dom": "Dominican Republic",
    "jam": "Jamaica",
    "tto": "Trinidad and Tobago",
    "guy": "Guyana",

    # Asia
    "afg": "Afghanistan",
    "ind": "India",
    "idn": "Indonesia",
    "irn": "Iran",
    "jor": "Jordan",
    "lbn": "Lebanon",
    "npL": "Nepal",
    "pak": "Pakistan",
    "phl": "Philippines",
    "lka": "Sri Lanka",
    "vnm": "Vietnam",
    "khm": "Cambodia",
    "lao": "Laos",
    "mmr": "Myanmar",
    "tls": "Timor-Leste",
    "yem": "Yemen",

    # Africa
    "dza": "Algeria",
    "ago": "Angola",
    "ben": "Benin",
    "bfa": "Burkina Faso",
    "bdi": "Burundi",
    "cmr": "Cameroon",
    "tcd": "Chad",
    "com": "Comoros",
    "civ": "Cote d'Ivoire",
    "cod": "DR Congo",
    "eth": "Ethiopia",
    "gha": "Ghana",
    "gin": "Guinea",
    "ken": "Kenya",
    "mdg": "Madagascar",
    "mwi": "Malawi",
    "mli": "Mali",
    "mar": "Morocco",
    "moz": "Mozambique",
    "ner": "Niger",
    "nga": "Nigeria",
    "rwa": "Rwanda",
    "sen": "Senegal",
    "tza": "Tanzania",
    "tgo": "Togo",
    "uga": "Uganda",
    "zmb": "Zambia",
    "zwe": "Zimbabwe",

    # Europe & Central Asia
    "alb": "Albania",
    "mne": "Montenegro",
    "srb": "Serbia",
    "esp": "Spain",
    "tur": "Turkey",
    "kgz": "Kyrgyzstan",
    "tjk": "Tajikistan",

    # Pacific
    "fji": "Fiji",
    "png": "Papua New Guinea",
    "vut": "Vanuatu",
    "slb": "Solomon Islands"
}

# Priority countries (larger, more complete databases)
PRIORITY_COUNTRIES = [
    "col", "per", "mex", "ind", "idn", "phl", "pak", "vnm",
    "eth", "ken", "tza", "moz", "nga", "dza", "mar",
    "arg", "chl", "ecu", "bol", "gtm", "slv", "hnd", "nic"
]


def setup_output_dir():
    """Create output directory if it doesn't exist."""
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {RAW_DATA_DIR}")


def download_country(country_code, country_name):
    """Download disaster database for a country."""
    url = f"{BASE_URL}?countrycode={country_code}"
    output_path = RAW_DATA_DIR / f"{country_code}_desinventar.xml"

    print(f"  {country_name} ({country_code})...", end=" ")

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; DisasterDataCollector/1.0)'
        }
        response = requests.get(url, timeout=TIMEOUT, allow_redirects=True, headers=headers)

        if response.status_code == 200 and len(response.content) > 1000:
            # Check if it's actually XML data (not HTML error page)
            content_start = response.content[:500].decode('utf-8', errors='ignore').lower()
            if '<?xml' in content_start or '<desinventar' in content_start:
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                file_size = output_path.stat().st_size / 1024
                print(f"OK ({file_size:.0f} KB)")
                return True, file_size
            else:
                print("NO DATA (HTML response)")
                return False, 0
        else:
            print(f"FAILED (status {response.status_code})")
            return False, 0

    except Exception as e:
        print(f"ERROR: {e}")
        return False, 0


def download_all(selected_countries=None):
    """Download all or selected DesInventar country databases."""
    print("=" * 70)
    print("DesInventar Global Disaster Database Downloader")
    print("=" * 70)
    print()
    print("Source: UN Office for Disaster Risk Reduction (UNDRR)")
    print("Portal: https://www.desinventar.net/")
    print()

    setup_output_dir()

    # Determine which countries to download
    if selected_countries:
        countries_to_download = {k: v for k, v in COUNTRIES.items() if k in selected_countries}
    else:
        # Default: download priority countries first
        countries_to_download = {k: COUNTRIES[k] for k in PRIORITY_COUNTRIES if k in COUNTRIES}

    print(f"Downloading {len(countries_to_download)} countries...")
    print()

    results = {}
    total_size = 0

    for code, name in countries_to_download.items():
        success, size = download_country(code, name)
        results[code] = {
            "name": name,
            "success": success,
            "size_kb": size
        }
        if success:
            total_size += size
        time.sleep(1)  # Rate limiting

    # Save metadata
    metadata = {
        "download_date": datetime.now().isoformat(),
        "source": "DesInventar - UN Office for Disaster Risk Reduction",
        "source_url": "https://www.desinventar.net/",
        "license": "Apache 2.0-like (free for commercial and non-commercial use)",
        "countries_attempted": len(countries_to_download),
        "countries_successful": sum(1 for r in results.values() if r["success"]),
        "total_size_mb": round(total_size / 1024, 2),
        "results": results,
        "available_countries": COUNTRIES,
        "data_fields": [
            "Event ID",
            "Date",
            "Location (Admin levels)",
            "Event Type",
            "Cause",
            "Deaths",
            "Missing",
            "Injured",
            "Affected",
            "Houses Destroyed",
            "Houses Damaged",
            "Economic Losses"
        ],
        "notes": [
            "Data quality varies by country",
            "Temporal coverage varies (some countries back to 1900s)",
            "XML format contains full disaster event records",
            "GAR datasets use standardized subset with quality criteria"
        ]
    }

    metadata_path = RAW_DATA_DIR / "desinventar_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"\nMetadata saved: {metadata_path}")

    # Summary
    print("\n" + "=" * 70)
    print("DOWNLOAD COMPLETE")
    print("=" * 70)
    success_count = sum(1 for r in results.values() if r["success"])
    print(f"Countries downloaded: {success_count}/{len(countries_to_download)}")
    print(f"Total size: {total_size/1024:.1f} MB")

    # List successful downloads
    print("\nSuccessful downloads:")
    for code, result in results.items():
        if result["success"]:
            print(f"  {result['name']}: {result['size_kb']:.0f} KB")

    return success_count > 0


def main():
    parser = argparse.ArgumentParser(description='Download DesInventar disaster databases')
    parser.add_argument('--countries', type=str, help='Comma-separated country codes (e.g., col,per,mex)')
    parser.add_argument('--all', action='store_true', help='Download all available countries')
    args = parser.parse_args()

    selected = None
    if args.countries:
        selected = [c.strip().lower() for c in args.countries.split(',')]
    elif args.all:
        selected = list(COUNTRIES.keys())

    success = download_all(selected)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
