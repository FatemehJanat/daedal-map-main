"""
FEMA National Risk Index Data Downloader

Downloads FEMA NRI county-level data via ArcGIS REST API.
This is a workaround while hazards.fema.gov is experiencing outages.

Usage:
    python download_fema_nri.py

Output:
    Saves raw JSON to: county-map-data/Raw data/fema_nri_counties_raw.json
"""

import requests
import json
from pathlib import Path
import time
import sys
from datetime import datetime

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA/fema_nri")
TIMEOUT = 60  # seconds

# ArcGIS REST API endpoints for different NRI versions
# All available via services.arcgis.com as workaround for hazards.fema.gov outage
NRI_VERSIONS = {
    "v1.17": {
        "service": "NRI_Counties_v117",
        "release": "2021",
        "counties": 3142
    },
    "v1.18.1": {
        "service": "NRI_Counties_Prod_v1181_view",
        "release": "November 2021",
        "counties": 3142
    },
    "v1.19.0": {
        "service": "National_Risk_Index_Counties_(March_2023)",
        "release": "March 2023",
        "counties": 3231
    },
    "v1.20.0": {
        "service": "National_Risk_Index_Counties",
        "release": "December 2025",
        "counties": 3232
    }
}

# Default to latest version
DEFAULT_VERSION = "v1.20.0"
ARCGIS_BASE = "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services"
ARCGIS_BASE_URL = f"{ARCGIS_BASE}/{NRI_VERSIONS[DEFAULT_VERSION]['service']}/FeatureServer/0"

# Key fields to download (subset of 467 available fields)
# Field names verified against ArcGIS service 2026-01-05
KEY_FIELDS = [
    # Identifiers
    "OBJECTID", "NRI_ID", "STATE", "STATEABBRV", "STATEFIPS", "COUNTY", "COUNTYTYPE", "COUNTYFIPS", "STCOFIPS",

    # Demographics
    "POPULATION", "BUILDVALUE", "AGRIVALUE", "AREA",

    # Composite Risk Scores
    "RISK_VALUE", "RISK_SCORE", "RISK_RATNG", "RISK_SPCTL",

    # Expected Annual Loss (Composite)
    "EAL_SCORE", "EAL_RATNG", "EAL_SPCTL", "EAL_VALT", "EAL_VALB", "EAL_VALP", "EAL_VALPE", "EAL_VALA",

    # Annual Loss Rate (Composite)
    "ALR_VALB", "ALR_VALP", "ALR_VALA", "ALR_NPCTL", "ALR_VRA_NPCTL",

    # Social Vulnerability
    "SOVI_SCORE", "SOVI_RATNG", "SOVI_SPCTL",

    # Community Resilience
    "RESL_SCORE", "RESL_RATNG", "RESL_SPCTL", "RESL_VALUE",

    # Community Risk Factor
    "CRF_VALUE",

    # NRI Version
    "NRI_VER",

    # Avalanche (AVLN)
    "AVLN_EVNTS", "AVLN_AFREQ", "AVLN_EALT", "AVLN_EALS", "AVLN_EALR", "AVLN_RISKV", "AVLN_RISKS", "AVLN_RISKR",
    # Coastal Flooding (CFLD)
    "CFLD_EVNTS", "CFLD_AFREQ", "CFLD_EALT", "CFLD_EALS", "CFLD_EALR", "CFLD_RISKV", "CFLD_RISKS", "CFLD_RISKR",
    # Cold Wave (CWAV)
    "CWAV_EVNTS", "CWAV_AFREQ", "CWAV_EALT", "CWAV_EALS", "CWAV_EALR", "CWAV_RISKV", "CWAV_RISKS", "CWAV_RISKR",
    # Drought (DRGT)
    "DRGT_EVNTS", "DRGT_AFREQ", "DRGT_EALT", "DRGT_EALS", "DRGT_EALR", "DRGT_RISKV", "DRGT_RISKS", "DRGT_RISKR",
    # Earthquake (ERQK)
    "ERQK_EVNTS", "ERQK_AFREQ", "ERQK_EALT", "ERQK_EALS", "ERQK_EALR", "ERQK_RISKV", "ERQK_RISKS", "ERQK_RISKR",
    # Hail (HAIL)
    "HAIL_EVNTS", "HAIL_AFREQ", "HAIL_EALT", "HAIL_EALS", "HAIL_EALR", "HAIL_RISKV", "HAIL_RISKS", "HAIL_RISKR",
    # Heat Wave (HWAV)
    "HWAV_EVNTS", "HWAV_AFREQ", "HWAV_EALT", "HWAV_EALS", "HWAV_EALR", "HWAV_RISKV", "HWAV_RISKS", "HWAV_RISKR",
    # Hurricane (HRCN)
    "HRCN_EVNTS", "HRCN_AFREQ", "HRCN_EALT", "HRCN_EALS", "HRCN_EALR", "HRCN_RISKV", "HRCN_RISKS", "HRCN_RISKR",
    # Ice Storm (ISTM)
    "ISTM_EVNTS", "ISTM_AFREQ", "ISTM_EALT", "ISTM_EALS", "ISTM_EALR", "ISTM_RISKV", "ISTM_RISKS", "ISTM_RISKR",
    # Landslide (LNDS)
    "LNDS_EVNTS", "LNDS_AFREQ", "LNDS_EALT", "LNDS_EALS", "LNDS_EALR", "LNDS_RISKV", "LNDS_RISKS", "LNDS_RISKR",
    # Lightning (LTNG)
    "LTNG_EVNTS", "LTNG_AFREQ", "LTNG_EALT", "LTNG_EALS", "LTNG_EALR", "LTNG_RISKV", "LTNG_RISKS", "LTNG_RISKR",
    # Inland (Riverine) Flooding (IFLD) - note: not RFLD
    "IFLD_EVNTS", "IFLD_AFREQ", "IFLD_EALT", "IFLD_EALS", "IFLD_EALR", "IFLD_RISKV", "IFLD_RISKS", "IFLD_RISKR",
    # Strong Wind (SWND)
    "SWND_EVNTS", "SWND_AFREQ", "SWND_EALT", "SWND_EALS", "SWND_EALR", "SWND_RISKV", "SWND_RISKS", "SWND_RISKR",
    # Tornado (TRND)
    "TRND_EVNTS", "TRND_AFREQ", "TRND_EALT", "TRND_EALS", "TRND_EALR", "TRND_RISKV", "TRND_RISKS", "TRND_RISKR",
    # Tsunami (TSUN)
    "TSUN_EVNTS", "TSUN_AFREQ", "TSUN_EALT", "TSUN_EALS", "TSUN_EALR", "TSUN_RISKV", "TSUN_RISKS", "TSUN_RISKR",
    # Volcanic Activity (VLCN)
    "VLCN_EVNTS", "VLCN_AFREQ", "VLCN_EALT", "VLCN_EALS", "VLCN_EALR", "VLCN_RISKV", "VLCN_RISKS", "VLCN_RISKR",
    # Wildfire (WFIR)
    "WFIR_EVNTS", "WFIR_AFREQ", "WFIR_EALT", "WFIR_EALS", "WFIR_EALR", "WFIR_RISKV", "WFIR_RISKS", "WFIR_RISKR",
    # Winter Weather (WNTW)
    "WNTW_EVNTS", "WNTW_AFREQ", "WNTW_EALT", "WNTW_EALS", "WNTW_EALR", "WNTW_RISKV", "WNTW_RISKS", "WNTW_RISKR",
]

def setup_output_dir():
    """Create output directory if it doesn't exist."""
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Raw data directory: {RAW_DATA_DIR}")
    print(f"Output directory: {OUTPUT_DIR}")


def get_record_count():
    """Get total number of records in the dataset."""
    url = f"{ARCGIS_BASE_URL}/query"
    params = {
        "where": "1=1",
        "returnCountOnly": "true",
        "f": "json"
    }
    response = requests.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    data = response.json()
    return data.get("count", 0)


def download_batch(offset, batch_size=1000):
    """Download a batch of records starting at offset using POST to avoid URL length limits."""
    url = f"{ARCGIS_BASE_URL}/query"
    # Use POST with form data to avoid URL length limits (188 fields = very long URL)
    data = {
        "where": "1=1",
        "outFields": ",".join(KEY_FIELDS),
        "returnGeometry": "false",
        "resultOffset": offset,
        "resultRecordCount": batch_size,
        "f": "json"
    }

    response = requests.post(url, data=data, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def download_all_data():
    """Download all NRI county data in batches via ArcGIS API."""
    print("=" * 70)
    print("FEMA National Risk Index Downloader")
    print("=" * 70)
    print()
    print("NOTE: Using ArcGIS REST API as workaround for hazards.fema.gov outage")
    print(f"Endpoint: {ARCGIS_BASE_URL}")
    print()

    setup_output_dir()

    # Get total count
    print("Getting record count...")
    total = get_record_count()
    print(f"Total records available: {total}")

    if total == 0:
        print("ERROR: No records found. API may be down.")
        return None

    # Download in batches
    all_features = []
    batch_size = 1000
    offset = 0

    while offset < total:
        remaining = total - offset
        current_batch = min(batch_size, remaining)
        print(f"Downloading records {offset+1}-{offset+current_batch} of {total}...")

        try:
            data = download_batch(offset, batch_size)
            features = data.get("features", [])

            if not features:
                print(f"  WARNING: No features returned at offset {offset}")
                break

            all_features.extend(features)
            print(f"  Got {len(features)} records")
            offset += batch_size

            # Be nice to the server
            time.sleep(0.3)

        except requests.exceptions.Timeout:
            print(f"  TIMEOUT at offset {offset}, retrying in 5 seconds...")
            time.sleep(5)
            continue

        except Exception as e:
            print(f"  ERROR at offset {offset}: {e}")
            print("  Retrying in 5 seconds...")
            time.sleep(5)
            continue

    print()
    print(f"Downloaded {len(all_features)} total records")

    # Save raw data
    raw_path = RAW_DATA_DIR / "fema_nri_counties_raw.json"

    output = {
        "download_date": datetime.now().isoformat(),
        "source": ARCGIS_BASE_URL,
        "source_note": "ArcGIS REST API workaround - hazards.fema.gov was down",
        "total_records": len(all_features),
        "fields": KEY_FIELDS,
        "features": all_features
    }

    print(f"Saving raw data to: {raw_path}")
    with open(raw_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)

    file_size = raw_path.stat().st_size / 1024 / 1024
    print(f"File size: {file_size:.1f} MB")

    return all_features


def main():
    """Download FEMA NRI data via ArcGIS API."""
    features = download_all_data()

    if features:
        print()
        print("=" * 70)
        print("SUCCESS! Raw data downloaded.")
        print("=" * 70)
        print()
        print("Next step: Run the converter to create parquet:")
        print("  python data_converters/convert_fema_nri.py")
        return 0
    else:
        print()
        print("=" * 70)
        print("DOWNLOAD FAILED")
        print("=" * 70)
        print()
        print("The ArcGIS API may also be experiencing issues.")
        print("Try again later or check:")
        print("  https://gis-fema.hub.arcgis.com/")
        return 1


if __name__ == "__main__":
    sys.exit(main())
