"""
Download NOAA NCEI Significant Earthquake Database.

Downloads historical significant earthquakes from NOAA's National Centers for
Environmental Information (NCEI) hazard database. Goes back to 2150 BC.

Source: https://www.ngdc.noaa.gov/hazel/view/hazards/earthquake/search
API: https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/earthquakes

A "significant" earthquake is one that meets at least one of:
- Caused deaths
- Caused moderate damage (~$1 million or more)
- Magnitude 7.5 or greater
- Modified Mercalli Intensity X or greater
- Generated a tsunami

Usage:
    python download_noaa_significant_earthquakes.py
"""

import requests
import json
from pathlib import Path
from datetime import datetime
import sys

# Output directory
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/noaa/significant_earthquakes")

# NOAA NCEI Hazard Service API
BASE_URL = "https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1"


def fetch_all_earthquakes():
    """Fetch all significant earthquake events using pagination."""
    print("\nFetching all significant earthquake events...")

    all_events = []
    page = 1

    # First, get the total count
    url = f"{BASE_URL}/earthquakes"
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
        url = f"{BASE_URL}/earthquakes?page={page}"

        try:
            response = requests.get(url, timeout=120)
            response.raise_for_status()
            data = response.json()

            items = data.get('items', [])
            all_events.extend(items)

            if page % 5 == 0 or page == total_pages:
                print(f"  Page {page}/{total_pages}: {len(all_events)} events so far")

            page += 1

        except requests.exceptions.RequestException as e:
            print(f"  ERROR on page {page}: {e}")
            break

    return all_events


def main():
    """Download all significant earthquake data."""
    print("=" * 70)
    print("NOAA NCEI Significant Earthquake Database Downloader")
    print("=" * 70)
    print(f"Started: {datetime.now().isoformat()}")
    print(f"Source: https://www.ngdc.noaa.gov/hazel/view/hazards/earthquake/search")

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\nOutput directory: {OUTPUT_DIR}")

    # Fetch earthquake events
    events = fetch_all_earthquakes()

    if not events:
        print("ERROR: No events downloaded")
        return 1

    # Save events
    events_path = OUTPUT_DIR / "significant_earthquakes.json"
    with open(events_path, 'w', encoding='utf-8') as f:
        json.dump({"events": events, "count": len(events)}, f, indent=2)
    print(f"\nSaved to: {events_path}")

    # Analyze the data
    print("\n" + "=" * 70)
    print("DATA ANALYSIS")
    print("=" * 70)

    # Year range
    years = [e.get('year') for e in events if e.get('year') is not None]
    if years:
        print(f"Year range: {min(years)} to {max(years)}")

    # Magnitude range
    mags = [e.get('eqMagnitude') for e in events if e.get('eqMagnitude') is not None]
    if mags:
        print(f"Magnitude range: {min(mags):.1f} to {max(mags):.1f}")

    # Deaths
    deaths = [e.get('deaths') for e in events if e.get('deaths') is not None]
    if deaths:
        print(f"Events with deaths: {len(deaths)}")
        print(f"Total deaths recorded: {sum(deaths):,}")

    # Tsunami-linked
    tsunami_linked = [e for e in events if e.get('tsunamiEventId')]
    print(f"Linked to tsunamis: {len(tsunami_linked)}")

    # Volcano-linked
    volcano_linked = [e for e in events if e.get('volcanoEventId')]
    print(f"Linked to volcanoes: {len(volcano_linked)}")

    # Pre-1900 events (historical)
    historical = [e for e in events if e.get('year') and e.get('year') < 1900]
    print(f"Pre-1900 (historical): {len(historical)}")

    # Save metadata
    metadata = {
        "download_date": datetime.now().isoformat(),
        "source": "NOAA NCEI Global Significant Earthquake Database",
        "source_url": "https://www.ngdc.noaa.gov/hazel/view/hazards/earthquake/search",
        "api_url": BASE_URL,
        "doi": "10.7289/V5TD9V7K",
        "record_count": len(events),
        "year_range": [min(years), max(years)] if years else None,
        "magnitude_range": [min(mags), max(mags)] if mags else None,
        "pre_1900_count": len(historical),
        "tsunami_linked_count": len(tsunami_linked),
        "volcano_linked_count": len(volcano_linked),
        "criteria": [
            "Caused deaths",
            "Caused moderate damage (~$1 million or more)",
            "Magnitude 7.5 or greater",
            "Modified Mercalli Intensity X or greater",
            "Generated a tsunami"
        ]
    }

    metadata_path = OUTPUT_DIR / "metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)
    print(f"\nMetadata saved to: {metadata_path}")

    # Summary
    print("\n" + "=" * 70)
    print("DOWNLOAD COMPLETE")
    print("=" * 70)
    print(f"Total significant earthquakes: {len(events)}")
    print(f"Historical (pre-1900): {len(historical)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
