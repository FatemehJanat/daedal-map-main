"""
Download NOAA NGDC Tsunami Database.

Downloads historical tsunami events from NOAA's National Centers for
Environmental Information (NCEI, formerly NGDC) hazard database.

Source: https://www.ngdc.noaa.gov/hazel/view/hazards/tsunami/search
API: https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/tsunamis

Data includes:
- Tsunami source events (earthquakes, volcanoes, landslides)
- Runup locations (coastal impact points)
- Lat/Long coordinates for all events

Usage:
    python download_tsunami.py
"""

import requests
import json
from pathlib import Path
from datetime import datetime
import sys

# Output directory
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/noaa/tsunami")

# NOAA NCEI Hazard Service API endpoints
# Working endpoint pattern found through testing
BASE_URL = "https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1"

ENDPOINTS = {
    "tsunami_events": {
        "url": f"{BASE_URL}/tsunamis/events",
        "filename": "tsunami_events.json",
        "description": "Tsunami source events (earthquakes causing tsunamis)"
    },
    "tsunami_runups": {
        "url": f"{BASE_URL}/tsunamis/runups",
        "filename": "tsunami_runups.json",
        "description": "Tsunami runup locations (coastal impact points)"
    }
}

# Additional filter for US-relevant tsunamis
US_REGIONS = {
    "pacific_us": {
        "minLatitude": 20,
        "maxLatitude": 75,
        "minLongitude": -180,
        "maxLongitude": -100
    },
    "atlantic_us": {
        "minLatitude": 20,
        "maxLatitude": 50,
        "minLongitude": -100,
        "maxLongitude": -60
    }
}


def download_api_data(url, description, params=None):
    """Download data from NOAA API."""
    print(f"\nDownloading {description}...")
    print(f"  URL: {url}")
    if params:
        print(f"  Params: {params}")

    try:
        response = requests.get(url, params=params, timeout=120)
        response.raise_for_status()

        data = response.json()

        # Handle different response formats
        if isinstance(data, dict):
            if 'items' in data:
                records = data['items']
            elif 'features' in data:
                records = data['features']
            else:
                records = [data]
        elif isinstance(data, list):
            records = data
        else:
            records = [data]

        print(f"  Retrieved: {len(records)} records")
        return {
            "success": True,
            "data": data,
            "record_count": len(records)
        }

    except requests.exceptions.RequestException as e:
        print(f"  ERROR: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def fetch_all_tsunamis():
    """Fetch all tsunami events using pagination."""
    print("\nFetching all tsunami source events...")

    all_events = []
    page = 1

    # First, get the total count
    url = f"{BASE_URL}/tsunamis/events"
    try:
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        data = response.json()
        total_pages = data.get('totalPages', 1)
        total_items = data.get('totalItems', 0)
        print(f"  Total events: {total_items} across {total_pages} pages")
    except Exception as e:
        print(f"  ERROR getting initial data: {e}")
        return []

    # Fetch all pages
    while page <= total_pages:
        url = f"{BASE_URL}/tsunamis/events?page={page}"

        try:
            response = requests.get(url, timeout=120)
            response.raise_for_status()
            data = response.json()

            items = data.get('items', [])
            all_events.extend(items)
            print(f"  Page {page}/{total_pages}: {len(items)} events (total: {len(all_events)})")

            page += 1

        except requests.exceptions.RequestException as e:
            print(f"  ERROR on page {page}: {e}")
            break

    return all_events


def fetch_all_runups():
    """Fetch all tsunami runup records."""
    print("\nFetching all tsunami runup locations...")

    all_runups = []
    page = 1

    # First, get the total count
    url = f"{BASE_URL}/tsunamis/runups"
    try:
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        data = response.json()
        total_pages = data.get('totalPages', 1)
        total_items = data.get('totalItems', 0)
        print(f"  Total runups: {total_items} across {total_pages} pages")
    except Exception as e:
        print(f"  ERROR getting initial data: {e}")
        return []

    # Fetch all pages
    while page <= total_pages:
        url = f"{BASE_URL}/tsunamis/runups?page={page}"

        try:
            response = requests.get(url, timeout=120)
            response.raise_for_status()
            data = response.json()

            items = data.get('items', [])
            all_runups.extend(items)

            # Print progress less frequently for large datasets
            if page % 10 == 0 or page == total_pages:
                print(f"  Page {page}/{total_pages}: {len(all_runups)} runups so far")

            page += 1

        except requests.exceptions.RequestException as e:
            print(f"  ERROR on page {page}: {e}")
            break

    return all_runups


def main():
    """Download all tsunami data."""
    print("=" * 70)
    print("NOAA NCEI Tsunami Database Downloader")
    print("=" * 70)
    print(f"Started: {datetime.now().isoformat()}")
    print(f"Source: https://www.ngdc.noaa.gov/hazel/view/hazards/tsunami/search")

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\nOutput directory: {OUTPUT_DIR}")

    # Metadata
    metadata = {
        "download_date": datetime.now().isoformat(),
        "source": "NOAA NCEI (National Centers for Environmental Information)",
        "source_url": "https://www.ngdc.noaa.gov/hazel/view/hazards/tsunami/search",
        "api_url": BASE_URL,
        "files": {}
    }

    # Fetch tsunami events
    events = fetch_all_tsunamis()
    if events:
        events_path = OUTPUT_DIR / "tsunami_events.json"
        with open(events_path, 'w', encoding='utf-8') as f:
            json.dump({"events": events, "count": len(events)}, f, indent=2)
        print(f"  Saved to: {events_path}")

        # Extract US-relevant events
        us_events = [
            e for e in events
            if e.get('country') in ['USA', 'UNITED STATES', 'U.S.', 'US']
            or (e.get('latitude') and e.get('longitude') and
                20 <= e.get('latitude', 0) <= 75 and
                -180 <= e.get('longitude', 0) <= -60)
        ]
        print(f"  US-relevant events: {len(us_events)}")

        metadata["files"]["tsunami_events"] = {
            "filename": "tsunami_events.json",
            "record_count": len(events),
            "us_relevant_count": len(us_events)
        }

    # Fetch runup locations
    runups = fetch_all_runups()
    if runups:
        runups_path = OUTPUT_DIR / "tsunami_runups.json"
        with open(runups_path, 'w', encoding='utf-8') as f:
            json.dump({"runups": runups, "count": len(runups)}, f, indent=2)
        print(f"  Saved to: {runups_path}")

        # Extract US runups
        us_runups = [
            r for r in runups
            if r.get('country') in ['USA', 'UNITED STATES', 'U.S.', 'US']
        ]
        print(f"  US runup locations: {len(us_runups)}")

        metadata["files"]["tsunami_runups"] = {
            "filename": "tsunami_runups.json",
            "record_count": len(runups),
            "us_count": len(us_runups)
        }

    # Save metadata
    metadata_path = OUTPUT_DIR / "tsunami_metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)
    print(f"\nMetadata saved to: {metadata_path}")

    # Summary
    print("\n" + "=" * 70)
    print("DOWNLOAD SUMMARY")
    print("=" * 70)
    print(f"Tsunami source events: {len(events)}")
    print(f"Tsunami runup locations: {len(runups)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
