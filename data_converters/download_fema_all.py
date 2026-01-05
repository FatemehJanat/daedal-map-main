"""
FEMA Comprehensive Data Downloader

Downloads ALL available FEMA data before it disappears:
1. NRI Counties - ALL 467 fields, ALL 4 historical versions (2021-2025)
2. NRI Census Tracts - 85,154 records (finer granularity)
3. Disaster Declarations - 68,542 records (1953-2025)
4. Hazard Info metadata table

Usage:
    python download_fema_all.py                    # Download everything
    python download_fema_all.py --nri-only         # Just NRI data
    python download_fema_all.py --disasters-only   # Just disaster declarations
    python download_fema_all.py --list-versions    # Show available NRI versions

Output:
    Raw data saved to: county-map-data/Raw data/fema/
"""

import requests
import json
from pathlib import Path
import time
import sys
from datetime import datetime
import argparse

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/fema")
TIMEOUT = 120  # seconds (longer for big downloads)

# ArcGIS REST API base
ARCGIS_BASE = "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services"

# NRI Versions available
NRI_VERSIONS = {
    "v1.17": {
        "service": "NRI_Counties_v117",
        "release": "2021",
        "counties": 3142,
        "description": "Original release"
    },
    "v1.18.1": {
        "service": "NRI_Counties_Prod_v1181_view",
        "release": "November 2021",
        "counties": 3142,
        "description": "First update"
    },
    "v1.19.0": {
        "service": "National_Risk_Index_Counties_(March_2023)",
        "release": "March 2023",
        "counties": 3231,
        "description": "Major methodology update"
    },
    "v1.20.0": {
        "service": "National_Risk_Index_Counties",
        "release": "December 2025",
        "counties": 3232,
        "description": "Latest version"
    }
}

# Census tract service
NRI_CENSUS_TRACT_SERVICE = "National_Risk_Index_Census_Tracts"

# Hazard info table
NRI_HAZARD_INFO_SERVICE = "National_Risk_Index_Hazard_Info_Table"

# OpenFEMA API
OPENFEMA_BASE = "https://www.fema.gov/api/open/v2"


def setup_dirs():
    """Create output directories."""
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DATA_DIR / "nri_counties").mkdir(exist_ok=True)
    (RAW_DATA_DIR / "nri_tracts").mkdir(exist_ok=True)
    (RAW_DATA_DIR / "disasters").mkdir(exist_ok=True)
    print(f"Output directory: {RAW_DATA_DIR}")


def get_service_fields(service_name):
    """Get all field names from an ArcGIS service."""
    url = f"{ARCGIS_BASE}/{service_name}/FeatureServer/0"
    params = {"f": "json"}
    response = requests.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    data = response.json()

    fields = data.get("fields", [])
    # Exclude shape fields
    field_names = [f["name"] for f in fields if not f["name"].startswith("Shape")]
    return field_names


def get_record_count(service_name):
    """Get total number of records in an ArcGIS service."""
    url = f"{ARCGIS_BASE}/{service_name}/FeatureServer/0/query"
    params = {
        "where": "1=1",
        "returnCountOnly": "true",
        "f": "json"
    }
    response = requests.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    data = response.json()
    return data.get("count", 0)


def download_arcgis_batch(service_name, fields, offset, batch_size=1000):
    """Download a batch of records from ArcGIS using POST."""
    url = f"{ARCGIS_BASE}/{service_name}/FeatureServer/0/query"
    data = {
        "where": "1=1",
        "outFields": ",".join(fields),
        "returnGeometry": "false",
        "resultOffset": offset,
        "resultRecordCount": batch_size,
        "f": "json"
    }

    response = requests.post(url, data=data, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def download_nri_version(version_key, version_info):
    """Download a single NRI version with all fields."""
    service = version_info["service"]
    print(f"\n{'='*70}")
    print(f"Downloading NRI {version_key} ({version_info['release']})")
    print(f"Service: {service}")
    print(f"{'='*70}")

    # Get all fields
    print("Getting field list...")
    fields = get_service_fields(service)
    print(f"  {len(fields)} fields available")

    # Get count
    print("Getting record count...")
    total = get_record_count(service)
    print(f"  {total:,} records")

    if total == 0:
        print("  ERROR: No records found!")
        return None

    # Download in batches
    all_features = []
    batch_size = 1000
    offset = 0

    while offset < total:
        remaining = total - offset
        current_batch = min(batch_size, remaining)
        print(f"  Downloading records {offset+1:,}-{offset+current_batch:,} of {total:,}...")

        try:
            data = download_arcgis_batch(service, fields, offset, batch_size)
            features = data.get("features", [])

            if not features:
                print(f"    WARNING: No features returned at offset {offset}")
                break

            all_features.extend(features)
            offset += batch_size
            time.sleep(0.3)  # Be nice to server

        except requests.exceptions.Timeout:
            print(f"    TIMEOUT, retrying in 5s...")
            time.sleep(5)
            continue
        except Exception as e:
            print(f"    ERROR: {e}, retrying in 5s...")
            time.sleep(5)
            continue

    print(f"  Downloaded {len(all_features):,} total records")

    # Save
    output_file = RAW_DATA_DIR / "nri_counties" / f"nri_{version_key.replace('.', '_')}_raw.json"
    output = {
        "download_date": datetime.now().isoformat(),
        "source": f"{ARCGIS_BASE}/{service}/FeatureServer/0",
        "version": version_key,
        "release": version_info["release"],
        "total_records": len(all_features),
        "total_fields": len(fields),
        "fields": fields,
        "features": all_features
    }

    print(f"  Saving to: {output_file}")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f)

    file_size = output_file.stat().st_size / 1024 / 1024
    print(f"  File size: {file_size:.1f} MB")

    return output_file


def download_all_nri_versions():
    """Download all NRI county versions."""
    print("\n" + "="*70)
    print("DOWNLOADING ALL NRI COUNTY VERSIONS")
    print("="*70)

    results = {}
    for version_key, version_info in NRI_VERSIONS.items():
        try:
            output_file = download_nri_version(version_key, version_info)
            results[version_key] = str(output_file) if output_file else None
        except Exception as e:
            print(f"  FAILED: {e}")
            results[version_key] = None

    return results


def download_nri_census_tracts():
    """Download NRI Census Tract data (85K+ records)."""
    print("\n" + "="*70)
    print("DOWNLOADING NRI CENSUS TRACTS")
    print("="*70)

    service = NRI_CENSUS_TRACT_SERVICE
    print(f"Service: {service}")

    # Get fields
    print("Getting field list...")
    fields = get_service_fields(service)
    print(f"  {len(fields)} fields available")

    # Get count
    print("Getting record count...")
    total = get_record_count(service)
    print(f"  {total:,} records (this will take a while)")

    if total == 0:
        print("  ERROR: No records found!")
        return None

    # Download in batches
    all_features = []
    batch_size = 2000  # Census tracts can use larger batches
    offset = 0

    while offset < total:
        remaining = total - offset
        current_batch = min(batch_size, remaining)
        pct = (offset / total) * 100
        print(f"  [{pct:5.1f}%] Downloading records {offset+1:,}-{offset+current_batch:,} of {total:,}...")

        try:
            data = download_arcgis_batch(service, fields, offset, batch_size)
            features = data.get("features", [])

            if not features:
                print(f"    WARNING: No features returned at offset {offset}")
                break

            all_features.extend(features)
            offset += batch_size
            time.sleep(0.2)

        except Exception as e:
            print(f"    ERROR: {e}, retrying...")
            time.sleep(5)
            continue

    print(f"  Downloaded {len(all_features):,} total records")

    # Save
    output_file = RAW_DATA_DIR / "nri_tracts" / "nri_census_tracts_raw.json"
    output = {
        "download_date": datetime.now().isoformat(),
        "source": f"{ARCGIS_BASE}/{service}/FeatureServer/0",
        "total_records": len(all_features),
        "total_fields": len(fields),
        "fields": fields,
        "features": all_features
    }

    print(f"  Saving to: {output_file}")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f)

    file_size = output_file.stat().st_size / 1024 / 1024
    print(f"  File size: {file_size:.1f} MB")

    return output_file


def download_hazard_info():
    """Download NRI Hazard Info metadata table."""
    print("\n" + "="*70)
    print("DOWNLOADING NRI HAZARD INFO TABLE")
    print("="*70)

    service = NRI_HAZARD_INFO_SERVICE
    url = f"{ARCGIS_BASE}/{service}/FeatureServer/0/query"

    params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json"
    }

    response = requests.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    data = response.json()

    features = data.get("features", [])
    print(f"  {len(features)} hazard types")

    # Save
    output_file = RAW_DATA_DIR / "nri_hazard_info.json"
    output = {
        "download_date": datetime.now().isoformat(),
        "source": f"{ARCGIS_BASE}/{service}/FeatureServer/0",
        "total_records": len(features),
        "features": features
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"  Saved to: {output_file}")

    # Print hazard info
    print("\n  Hazard types and periods:")
    for feat in features:
        attrs = feat.get("attributes", {})
        hazard = attrs.get("Hazard", "?")
        prefix = attrs.get("Prefix", "?")
        start = attrs.get("Start", "?")
        end = attrs.get("End_", "?")
        print(f"    {prefix}: {hazard} ({start}-{end})")

    return output_file


def download_disaster_declarations():
    """Download all disaster declarations from OpenFEMA API."""
    print("\n" + "="*70)
    print("DOWNLOADING DISASTER DECLARATIONS (1953-present)")
    print("="*70)

    url = f"{OPENFEMA_BASE}/DisasterDeclarationsSummaries"

    # Get total count first
    count_url = f"{url}?$top=0&$inlinecount=allpages"
    response = requests.get(count_url, timeout=TIMEOUT)
    response.raise_for_status()
    data = response.json()
    total = data.get("metadata", {}).get("count", 0)
    print(f"  Total records: {total:,}")

    # Download in batches (OpenFEMA supports $skip and $top)
    all_records = []
    batch_size = 1000
    offset = 0

    while offset < total:
        remaining = total - offset
        current_batch = min(batch_size, remaining)
        pct = (offset / total) * 100
        print(f"  [{pct:5.1f}%] Downloading records {offset+1:,}-{offset+current_batch:,} of {total:,}...")

        try:
            batch_url = f"{url}?$skip={offset}&$top={batch_size}&$orderby=declarationDate"
            response = requests.get(batch_url, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()

            records = data.get("DisasterDeclarationsSummaries", [])
            if not records:
                print("    WARNING: No records returned")
                break

            all_records.extend(records)
            offset += batch_size
            time.sleep(0.2)

        except Exception as e:
            print(f"    ERROR: {e}, retrying...")
            time.sleep(5)
            continue

    print(f"  Downloaded {len(all_records):,} total records")

    # Save
    output_file = RAW_DATA_DIR / "disasters" / "disaster_declarations_raw.json"
    output = {
        "download_date": datetime.now().isoformat(),
        "source": url,
        "total_records": len(all_records),
        "records": all_records
    }

    print(f"  Saving to: {output_file}")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f)

    file_size = output_file.stat().st_size / 1024 / 1024
    print(f"  File size: {file_size:.1f} MB")

    # Summary stats
    print("\n  Summary by decade:")
    decades = {}
    for rec in all_records:
        date = rec.get("declarationDate", "")[:4]
        if date:
            decade = date[:3] + "0s"
            decades[decade] = decades.get(decade, 0) + 1

    for decade in sorted(decades.keys()):
        print(f"    {decade}: {decades[decade]:,} declarations")

    return output_file


def list_versions():
    """Print available NRI versions."""
    print("\nAvailable NRI Versions:")
    print("="*70)
    for version_key, version_info in NRI_VERSIONS.items():
        print(f"\n  {version_key}:")
        print(f"    Service: {version_info['service']}")
        print(f"    Release: {version_info['release']}")
        print(f"    Counties: {version_info['counties']}")
        print(f"    Description: {version_info['description']}")


def main():
    parser = argparse.ArgumentParser(description="Download all FEMA data")
    parser.add_argument("--nri-only", action="store_true", help="Download only NRI data")
    parser.add_argument("--disasters-only", action="store_true", help="Download only disaster declarations")
    parser.add_argument("--tracts-only", action="store_true", help="Download only census tract NRI")
    parser.add_argument("--list-versions", action="store_true", help="List available NRI versions")
    parser.add_argument("--version", type=str, help="Download specific NRI version (e.g., v1.17)")
    args = parser.parse_args()

    if args.list_versions:
        list_versions()
        return 0

    print("="*70)
    print("FEMA COMPREHENSIVE DATA DOWNLOADER")
    print("="*70)
    print(f"\nStarted: {datetime.now().isoformat()}")

    setup_dirs()

    results = {
        "download_date": datetime.now().isoformat(),
        "nri_versions": {},
        "census_tracts": None,
        "hazard_info": None,
        "disasters": None
    }

    if args.version:
        # Download specific version
        if args.version in NRI_VERSIONS:
            results["nri_versions"][args.version] = download_nri_version(
                args.version, NRI_VERSIONS[args.version]
            )
        else:
            print(f"ERROR: Unknown version {args.version}")
            list_versions()
            return 1

    elif args.nri_only:
        results["nri_versions"] = download_all_nri_versions()
        results["hazard_info"] = download_hazard_info()

    elif args.disasters_only:
        results["disasters"] = download_disaster_declarations()

    elif args.tracts_only:
        results["census_tracts"] = download_nri_census_tracts()

    else:
        # Download everything
        results["nri_versions"] = download_all_nri_versions()
        results["hazard_info"] = download_hazard_info()
        results["census_tracts"] = download_nri_census_tracts()
        results["disasters"] = download_disaster_declarations()

    # Save manifest
    manifest_file = RAW_DATA_DIR / "download_manifest.json"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    print("\n" + "="*70)
    print("DOWNLOAD COMPLETE!")
    print("="*70)
    print(f"\nManifest saved to: {manifest_file}")
    print(f"Finished: {datetime.now().isoformat()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
