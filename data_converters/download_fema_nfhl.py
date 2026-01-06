"""
FEMA National Flood Hazard Layer (NFHL) Downloader

Downloads flood zone polygon data from various sources.
Flood zones are cross-boundary entities (sibling level) - they don't align with county boundaries.

STATUS (2026-01-05):
    - hazards.fema.gov: DOWN (certificate/connectivity issues)
    - ArcGIS Online sample layer: Only 66 records (demo data, not full dataset)
    - State GIS portals: WORKING - use as primary source
    - FEMA MSC: Requires interactive search (no bulk API)

Usage:
    python download_fema_nfhl.py              # Download from state GIS portals
    python download_fema_nfhl.py --state MA   # Download single state
    python download_fema_nfhl.py --list       # List available state sources

Output:
    Raw data saved to: county-map-data/Raw data/fema/nfhl/
    - nfhl_{state}.zip (shapefiles) per state
    - nfhl_metadata.json with download info

Data Sources (by priority):
    1. State GIS portals (direct download links)
    2. FEMA Map Service Center (manual download when available)
    3. hazards.fema.gov ArcGIS (when infrastructure recovers)
"""

import requests
import json
from pathlib import Path
import time
import sys
from datetime import datetime
import argparse

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/fema/nfhl")
TIMEOUT = 120  # seconds - flood polygons can be large

# ArcGIS FeatureServer endpoint
# This is the public FEMA NFHL layer hosted on ArcGIS Online
NFHL_FEATURE_SERVER = "https://services.arcgis.com/2gdL2gxYNFY2TOUb/arcgis/rest/services/FEMA_National_Flood_Hazard_Layer/FeatureServer/0"

# State bounding boxes (approximate, in WGS84)
# Format: [minX, minY, maxX, maxY] = [west, south, east, north]
STATE_BOUNDS = {
    "AL": [-88.5, 30.1, -84.9, 35.0],
    "AK": [-180.0, 51.0, -130.0, 71.5],  # Large state
    "AZ": [-115.0, 31.3, -109.0, 37.0],
    "AR": [-94.6, 33.0, -89.6, 36.5],
    "CA": [-124.5, 32.5, -114.1, 42.0],
    "CO": [-109.1, 36.9, -102.0, 41.0],
    "CT": [-73.7, 40.9, -71.8, 42.1],
    "DE": [-75.8, 38.4, -75.0, 39.8],
    "DC": [-77.1, 38.8, -76.9, 39.0],
    "FL": [-87.6, 24.5, -80.0, 31.0],
    "GA": [-85.6, 30.4, -80.8, 35.0],
    "HI": [-160.3, 18.9, -154.8, 22.2],
    "ID": [-117.2, 42.0, -111.0, 49.0],
    "IL": [-91.5, 36.9, -87.5, 42.5],
    "IN": [-88.1, 37.8, -84.8, 41.8],
    "IA": [-96.6, 40.4, -90.1, 43.5],
    "KS": [-102.1, 37.0, -94.6, 40.0],
    "KY": [-89.6, 36.5, -81.9, 39.1],
    "LA": [-94.0, 28.9, -89.0, 33.0],
    "ME": [-71.1, 43.0, -66.9, 47.5],
    "MD": [-79.5, 37.9, -75.0, 39.7],
    "MA": [-73.5, 41.2, -69.9, 42.9],
    "MI": [-90.4, 41.7, -82.4, 48.2],
    "MN": [-97.2, 43.5, -89.5, 49.4],
    "MS": [-91.7, 30.2, -88.1, 35.0],
    "MO": [-95.8, 36.0, -89.1, 40.6],
    "MT": [-116.0, 44.4, -104.0, 49.0],
    "NE": [-104.1, 40.0, -95.3, 43.0],
    "NV": [-120.0, 35.0, -114.0, 42.0],
    "NH": [-72.6, 42.7, -70.6, 45.3],
    "NJ": [-75.6, 38.9, -73.9, 41.4],
    "NM": [-109.1, 31.3, -103.0, 37.0],
    "NY": [-79.8, 40.5, -71.9, 45.0],
    "NC": [-84.3, 33.8, -75.5, 36.6],
    "ND": [-104.1, 45.9, -96.6, 49.0],
    "OH": [-84.8, 38.4, -80.5, 42.0],
    "OK": [-103.0, 33.6, -94.4, 37.0],
    "OR": [-124.6, 41.9, -116.5, 46.3],
    "PA": [-80.5, 39.7, -74.7, 42.3],
    "RI": [-71.9, 41.1, -71.1, 42.0],
    "SC": [-83.4, 32.0, -78.5, 35.2],
    "SD": [-104.1, 42.5, -96.4, 45.9],
    "TN": [-90.3, 35.0, -81.6, 36.7],
    "TX": [-106.6, 25.8, -93.5, 36.5],
    "UT": [-114.1, 37.0, -109.0, 42.0],
    "VT": [-73.4, 42.7, -71.5, 45.0],
    "VA": [-83.7, 36.5, -75.2, 39.5],
    "WA": [-124.8, 45.5, -116.9, 49.0],
    "WV": [-82.6, 37.2, -77.7, 40.6],
    "WI": [-92.9, 42.5, -86.8, 47.1],
    "WY": [-111.1, 41.0, -104.1, 45.0],
    "PR": [-67.3, 17.9, -65.6, 18.5],
}

# Key fields to download
NFHL_FIELDS = [
    "OBJECTID",
    "DFIRM_ID",       # Digital Flood Insurance Rate Map ID
    "FLD_ZONE",       # Flood zone designation (A, AE, V, VE, X, etc.)
    "ZONE_SUBTY",     # Zone subtype
    "SFHA_TF",        # Special Flood Hazard Area (T/F)
    "STATIC_BFE",     # Base Flood Elevation
    "DEPTH",          # Flood depth
    "VELOCITY",       # Flow velocity
    "SOURCE_CIT",     # Source citation
]


def setup_output_dir():
    """Create output directory if it doesn't exist."""
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {RAW_DATA_DIR}")


def get_record_count(bbox=None):
    """Get total number of records, optionally within a bounding box."""
    url = f"{NFHL_FEATURE_SERVER}/query"
    params = {
        "where": "1=1",
        "returnCountOnly": "true",
        "f": "json"
    }
    if bbox:
        params["geometry"] = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
        params["geometryType"] = "esriGeometryEnvelope"
        params["spatialRel"] = "esriSpatialRelIntersects"
        params["inSR"] = "4326"

    try:
        response = requests.get(url, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
        return data.get("count", 0)
    except Exception as e:
        print(f"  Error getting count: {e}")
        return 0


def download_state_batch(bbox, offset, batch_size=2000):
    """Download a batch of flood zone polygons within a bounding box."""
    url = f"{NFHL_FEATURE_SERVER}/query"
    params = {
        "where": "1=1",
        "outFields": ",".join(NFHL_FIELDS),
        "returnGeometry": "true",
        "geometry": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "inSR": "4326",
        "outSR": "4326",
        "resultOffset": offset,
        "resultRecordCount": batch_size,
        "f": "geojson"  # Get GeoJSON directly
    }

    response = requests.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def download_state(state_abbr):
    """Download all flood zone data for a single state."""
    if state_abbr not in STATE_BOUNDS:
        print(f"ERROR: Unknown state: {state_abbr}")
        return None

    bbox = STATE_BOUNDS[state_abbr]
    print(f"\nDownloading {state_abbr}...")
    print(f"  Bounding box: {bbox}")

    # Get count for this state
    count = get_record_count(bbox)
    print(f"  Records in area: {count:,}")

    if count == 0:
        print(f"  No flood zones found for {state_abbr}")
        return None

    # Download in batches
    all_features = []
    batch_size = 2000  # Max allowed by service
    offset = 0

    while offset < count:
        remaining = count - offset
        current_batch = min(batch_size, remaining)
        print(f"  Downloading {offset+1:,}-{offset+current_batch:,} of {count:,}...")

        try:
            data = download_state_batch(bbox, offset, batch_size)
            features = data.get("features", [])

            if not features:
                print(f"    No features returned at offset {offset}")
                break

            all_features.extend(features)
            offset += len(features)

            # If we got fewer than requested, we're done
            if len(features) < batch_size:
                break

            # Be nice to the server
            time.sleep(0.5)

        except requests.exceptions.Timeout:
            print(f"    TIMEOUT at offset {offset}, retrying in 10 seconds...")
            time.sleep(10)
            continue

        except Exception as e:
            print(f"    ERROR at offset {offset}: {e}")
            print("    Retrying in 10 seconds...")
            time.sleep(10)
            continue

    print(f"  Downloaded {len(all_features):,} features for {state_abbr}")

    # Create GeoJSON structure
    geojson = {
        "type": "FeatureCollection",
        "features": all_features,
        "metadata": {
            "state": state_abbr,
            "download_date": datetime.now().isoformat(),
            "feature_count": len(all_features),
            "bbox": bbox,
            "source": NFHL_FEATURE_SERVER
        }
    }

    # Save to file
    output_path = RAW_DATA_DIR / f"nfhl_{state_abbr}.geojson"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(geojson, f)

    file_size = output_path.stat().st_size / 1024 / 1024
    print(f"  Saved to {output_path.name} ({file_size:.1f} MB)")

    return len(all_features)


def download_test_sample():
    """Download a small test sample (Rhode Island - smallest state)."""
    print("Test mode: Downloading Rhode Island (smallest state)")
    return download_state("RI")


def download_all_states():
    """Download flood zone data for all states."""
    print("=" * 70)
    print("FEMA National Flood Hazard Layer (NFHL) Downloader")
    print("=" * 70)
    print()
    print(f"Source: {NFHL_FEATURE_SERVER}")
    print(f"Output: {RAW_DATA_DIR}")
    print()

    setup_output_dir()

    results = {}
    total_features = 0

    # Sort states by estimated size (smaller states first)
    small_states = ["RI", "DE", "DC", "CT", "NJ", "NH", "VT", "MA", "MD", "HI"]
    medium_states = ["WV", "SC", "ME", "IN", "KY", "TN", "VA", "NC", "OH", "PA", "NY", "GA", "AL", "MS", "LA", "AR"]
    large_states = [s for s in STATE_BOUNDS.keys() if s not in small_states + medium_states]

    all_states = small_states + medium_states + large_states

    for i, state in enumerate(all_states):
        print(f"\n[{i+1}/{len(all_states)}] Processing {state}...")

        # Skip if already downloaded
        output_path = RAW_DATA_DIR / f"nfhl_{state}.geojson"
        if output_path.exists():
            print(f"  Already exists, skipping. Delete file to re-download.")
            # Read existing count
            try:
                with open(output_path) as f:
                    existing = json.load(f)
                    existing_count = existing.get("metadata", {}).get("feature_count", 0)
                    results[state] = existing_count
                    total_features += existing_count
            except:
                results[state] = "exists"
            continue

        count = download_state(state)
        if count:
            results[state] = count
            total_features += count
        else:
            results[state] = 0

        # Longer pause between states
        time.sleep(2)

    # Save metadata summary
    metadata = {
        "download_date": datetime.now().isoformat(),
        "source": NFHL_FEATURE_SERVER,
        "total_features": total_features,
        "states_downloaded": len([s for s in results if results[s] > 0]),
        "results": results,
        "fields": NFHL_FIELDS,
        "notes": [
            "Flood zones are polygon features that cross county boundaries",
            "FLD_ZONE values: A, AE, AH, AO, V, VE, X (shaded), X (unshaded)",
            "SFHA_TF = 'T' indicates Special Flood Hazard Area (high risk)",
            "Data will be stored as sibling entities in geometry parquet"
        ]
    }

    metadata_path = RAW_DATA_DIR / "nfhl_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    print("\n" + "=" * 70)
    print("DOWNLOAD COMPLETE")
    print("=" * 70)
    print(f"Total features: {total_features:,}")
    print(f"States with data: {len([s for s in results if results[s] and results[s] > 0])}")
    print(f"Metadata saved: {metadata_path}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Download FEMA NFHL flood zone data")
    parser.add_argument("--state", type=str, help="Download single state (e.g., CA)")
    parser.add_argument("--test", action="store_true", help="Test with Rhode Island only")
    args = parser.parse_args()

    setup_output_dir()

    if args.test:
        result = download_test_sample()
        return 0 if result else 1
    elif args.state:
        result = download_state(args.state.upper())
        return 0 if result else 1
    else:
        results = download_all_states()
        return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
