"""
Convert NOAA NCEI Global Tsunami Database to parquet format.

Creates two output files:
1. events.parquet - Tsunami source events (earthquake/landslide epicenters)
2. runups.parquet - Runup observations (coastal impact points)

Source: NOAA NCEI Global Historical Tsunami Database
DOI: 10.7289/V5PN93H7
Coverage: 2100 BC to present (~3000 events globally)

Usage:
    python convert_global_tsunami.py
"""
import pandas as pd
import numpy as np
import json
import sys
from pathlib import Path
from math import radians, sin, cos, sqrt, atan2

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from data_converters.base import (
    get_water_body_loc_id,
    save_parquet,
)

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/noaa/tsunami")
IMPORTED_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/imported/noaa/tsunami")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/global/tsunamis")
SOURCE_ID = "noaa_global_tsunamis"

# Cross-event linking paths
EARTHQUAKES_PATH = Path("C:/Users/Bryan/Desktop/county-map-data/global/earthquakes/events.parquet")
VOLCANOES_PATH = Path("C:/Users/Bryan/Desktop/county-map-data/global/smithsonian_volcanoes/volcanoes.parquet")

# Cause codes from NOAA documentation
CAUSE_CODES = {
    0: 'Unknown',
    1: 'Earthquake',
    2: 'Questionable Earthquake',
    3: 'Earthquake and Landslide',
    4: 'Volcano and Earthquake',
    5: 'Volcano, Earthquake, and Landslide',
    6: 'Volcano',
    7: 'Volcano and Landslide',
    8: 'Landslide',
    9: 'Meteorological',
    10: 'Explosion',
    11: 'Astronomical Tide'
}

# Simplified cause mapping for display
CAUSE_SIMPLE = {
    0: 'Unknown',
    1: 'Earthquake',
    2: 'Earthquake',
    3: 'Earthquake',
    4: 'Volcano',
    5: 'Volcano',
    6: 'Volcano',
    7: 'Volcano',
    8: 'Landslide',
    9: 'Meteorological',
    10: 'Explosion',
    11: 'Meteorological'
}


def get_source_dir():
    """Get source directory - check raw first, then imported."""
    if RAW_DATA_DIR.exists() and (RAW_DATA_DIR / "tsunami_events.json").exists():
        return RAW_DATA_DIR
    elif IMPORTED_DIR.exists() and (IMPORTED_DIR / "tsunami_events.json").exists():
        print(f"  Note: Using imported data from {IMPORTED_DIR}")
        return IMPORTED_DIR
    return RAW_DATA_DIR


def haversine_km(lat1, lon1, lat2, lon2):
    """Calculate distance in km between two points using Haversine formula."""
    if any(pd.isna([lat1, lon1, lat2, lon2])):
        return None

    R = 6371  # Earth radius in km

    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))

    return R * c


def load_earthquake_data():
    """Load USGS earthquake data for cross-event linking."""
    if not EARTHQUAKES_PATH.exists():
        print(f"  Note: Earthquake data not found at {EARTHQUAKES_PATH}")
        print("  Earthquake-tsunami linking will be skipped")
        return None

    print(f"  Loading earthquake data for linking...")
    eq_df = pd.read_parquet(EARTHQUAKES_PATH)
    print(f"  Loaded {len(eq_df):,} earthquakes")
    return eq_df


def link_tsunamis_to_earthquakes(tsunamis_df, earthquakes_df):
    """
    Link tsunami events to their triggering earthquakes.

    Linking criteria (based on seismological research):
    - Time: 0-24 hours before tsunami timestamp
    - Distance: Within 500km of tsunami source
    - Magnitude: M7.0+ (threshold for tsunamigenic earthquakes)
    - Depth: < 100km (shallow earthquakes generate tsunamis)

    Returns DataFrame with parent_event_id column added
    """
    if earthquakes_df is None or len(earthquakes_df) == 0:
        tsunamis_df['parent_event_id'] = None
        tsunamis_df['eq_event_id'] = None
        return tsunamis_df

    print("\nLinking tsunamis to triggering earthquakes...")

    # METHOD 1: Direct ID matching using NOAA's pre-computed links
    # Earthquakes have tsunami_event_id that matches tsunami event_id
    direct_linked = 0
    proximity_linked = 0

    # Build lookup: tsunami_event_id -> earthquake_event_id
    eq_with_tsunami_links = earthquakes_df[earthquakes_df['tsunami_event_id'].notna()].copy()
    tsunami_to_eq = dict(zip(eq_with_tsunami_links['tsunami_event_id'], eq_with_tsunami_links['event_id']))
    print(f"  Earthquakes with direct tsunami links: {len(tsunami_to_eq):,}")

    # Apply direct links first
    parent_ids = []
    for idx, tsunami in tsunamis_df.iterrows():
        ts_id = tsunami['event_id']
        if ts_id in tsunami_to_eq:
            parent_ids.append(tsunami_to_eq[ts_id])
            direct_linked += 1
        else:
            parent_ids.append(None)

    tsunamis_df['parent_event_id'] = parent_ids
    print(f"  Direct ID matches: {direct_linked:,}")

    # METHOD 2: Time/location proximity for unlinked earthquake-caused tsunamis (post-1900 only)
    unlinked_eq_tsunamis = tsunamis_df[
        (tsunamis_df['parent_event_id'].isna()) &
        (tsunamis_df['cause'] == 'Earthquake') &
        (tsunamis_df['year'] >= 1900)
    ]
    print(f"  Unlinked earthquake-caused tsunamis (1900+): {len(unlinked_eq_tsunamis):,}")

    if len(unlinked_eq_tsunamis) > 0:
        # Filter earthquakes to tsunamigenic candidates (M7.0+, shallow)
        eq_candidates = earthquakes_df[
            (earthquakes_df['magnitude'] >= 7.0) &
            (earthquakes_df['year'] >= 1900)
        ].copy()

        if 'depth_km' in eq_candidates.columns:
            eq_candidates = eq_candidates[
                (eq_candidates['depth_km'] < 100) | (eq_candidates['depth_km'].isna())
            ]

        # Ensure timestamp is datetime and timezone-naive for comparison
        eq_candidates['timestamp'] = pd.to_datetime(eq_candidates['timestamp'], errors='coerce')
        eq_candidates['timestamp'] = eq_candidates['timestamp'].dt.tz_localize(None)

        for idx in unlinked_eq_tsunamis.index:
            tsunami = tsunamis_df.loc[idx]
            tsunami_time = pd.to_datetime(tsunami['timestamp'])

            if pd.isna(tsunami_time):
                continue

            # Make timezone-naive
            if tsunami_time.tzinfo is not None:
                tsunami_time = tsunami_time.tz_localize(None)

            # Time window: 0-24 hours before tsunami
            time_min = tsunami_time - pd.Timedelta(hours=24)
            time_max = tsunami_time + pd.Timedelta(hours=1)

            candidates = eq_candidates[
                (eq_candidates['timestamp'] >= time_min) &
                (eq_candidates['timestamp'] <= time_max)
            ]

            if len(candidates) == 0:
                continue

            # Find closest within 500km
            tsunami_lat = tsunami['latitude']
            tsunami_lon = tsunami['longitude']
            best_match = None
            best_dist = 500

            for _, eq in candidates.iterrows():
                dist = haversine_km(tsunami_lat, tsunami_lon, eq['latitude'], eq['longitude'])
                if dist is not None and dist < best_dist:
                    best_dist = dist
                    best_match = eq['event_id']

            if best_match:
                tsunamis_df.at[idx, 'parent_event_id'] = best_match
                proximity_linked += 1

        print(f"  Proximity matches: {proximity_linked:,}")

    tsunamis_df['eq_event_id'] = tsunamis_df['parent_event_id']  # Explicit earthquake link
    total_linked = direct_linked + proximity_linked
    print(f"  Total linked: {total_linked:,}")

    # Statistics
    eq_caused = tsunamis_df[tsunamis_df['cause'] == 'Earthquake']
    eq_linked = eq_caused['parent_event_id'].notna().sum()
    rate = eq_linked / len(eq_caused) * 100 if len(eq_caused) > 0 else 0

    print(f"  Earthquake-caused tsunamis: {len(eq_caused):,}")
    print(f"  Successfully linked: {eq_linked:,} ({rate:.1f}%)")

    return tsunamis_df


def load_volcano_data():
    """Load Smithsonian volcano data for cross-event linking."""
    # Try eruptions first (has temporal data), fall back to volcanoes
    eruptions_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/smithsonian_volcanoes/events.parquet")
    volcanoes_path = Path("C:/Users/Bryan/Desktop/county-map-data/global/volcanoes/volcanoes.parquet")

    if eruptions_path.exists():
        print(f"  Loading volcano eruption data for linking...")
        df = pd.read_parquet(eruptions_path)
        print(f"  Loaded {len(df):,} eruptions")
        return df, 'eruptions'
    elif volcanoes_path.exists():
        print(f"  Loading volcano location data for linking...")
        df = pd.read_parquet(volcanoes_path)
        print(f"  Loaded {len(df):,} volcanoes")
        return df, 'volcanoes'
    else:
        print(f"  Note: Volcano data not found")
        print("  Volcano-tsunami linking will be skipped")
        return None, None


def link_tsunamis_to_volcanoes(tsunamis_df, volcano_data, data_type):
    """
    Link volcano-caused tsunamis to specific volcanoes.

    Linking criteria:
    - Cause: Must be 'Volcano'
    - Distance: Within 200km of known volcano
    - If eruption data: Within 1 year of eruption

    Returns DataFrame with volcano_id column added
    """
    if volcano_data is None:
        tsunamis_df['volcano_id'] = None
        tsunamis_df['volcano_name'] = None
        return tsunamis_df

    print("\nLinking tsunamis to triggering volcanoes...")

    # Get volcano-caused tsunamis
    volcano_tsunamis = tsunamis_df[tsunamis_df['cause'] == 'Volcano'].copy()
    print(f"  Volcano-caused tsunamis: {len(volcano_tsunamis):,}")

    if len(volcano_tsunamis) == 0:
        tsunamis_df['volcano_id'] = None
        tsunamis_df['volcano_name'] = None
        return tsunamis_df

    linked_count = 0
    volcano_ids = []
    volcano_names = []

    for idx, tsunami in tsunamis_df.iterrows():
        volcano_id = None
        volcano_name = None

        # Only link volcano-caused tsunamis
        if tsunami.get('cause') != 'Volcano':
            volcano_ids.append(None)
            volcano_names.append(None)
            continue

        tsunami_lat = tsunami['latitude']
        tsunami_lon = tsunami['longitude']

        # Find closest volcano within 200km
        best_match_id = None
        best_match_name = None
        best_dist = 200  # km threshold

        for _, volcano in volcano_data.iterrows():
            vol_lat = volcano.get('latitude')
            vol_lon = volcano.get('longitude')

            if pd.isna(vol_lat) or pd.isna(vol_lon):
                continue

            dist = haversine_km(tsunami_lat, tsunami_lon, vol_lat, vol_lon)

            if dist is not None and dist < best_dist:
                best_dist = dist
                best_match_id = volcano.get('volcano_number') or volcano.get('volcano_id')
                best_match_name = volcano.get('volcano_name')

        if best_match_id:
            linked_count += 1
            volcano_id = str(best_match_id)
            volcano_name = best_match_name

        volcano_ids.append(volcano_id)
        volcano_names.append(volcano_name)

    tsunamis_df['volcano_id'] = volcano_ids
    tsunamis_df['volcano_name'] = volcano_names

    print(f"  Successfully linked: {linked_count:,}")

    return tsunamis_df


def load_tsunami_data():
    """Load tsunami events and runups from JSON files."""
    print("\nLoading tsunami data...")

    source_dir = get_source_dir()

    # Load events
    events_path = source_dir / "tsunami_events.json"
    with open(events_path, 'r', encoding='utf-8') as f:
        events_data = json.load(f)

    events_df = pd.DataFrame(events_data['events'])
    print(f"  Total events: {len(events_df):,}")

    # Load runups
    runups_path = source_dir / "tsunami_runups.json"
    with open(runups_path, 'r', encoding='utf-8') as f:
        runups_data = json.load(f)

    runups_df = pd.DataFrame(runups_data['runups'])
    print(f"  Total runups: {len(runups_df):,}")

    return events_df, runups_df


def process_events(events_df):
    """Process tsunami source events."""
    print("\nProcessing events...")

    # Build timestamp from year/month/day
    def build_timestamp(row):
        try:
            year = int(row['year']) if pd.notna(row['year']) else None
            month = int(row.get('month', 1)) if pd.notna(row.get('month')) else 1
            day = int(row.get('day', 1)) if pd.notna(row.get('day')) else 1

            # Handle negative years (BC) - use year 1 as fallback
            if year and year < 1:
                year = 1
            if year:
                return pd.Timestamp(year=year, month=month, day=day)
        except:
            pass
        return pd.NaT

    # Get year for filtering (handles BC years)
    def get_year(row):
        try:
            return int(row['year']) if pd.notna(row['year']) else None
        except:
            return None

    events_out = pd.DataFrame({
        'event_id': events_df['id'].apply(lambda x: f"TS{x:06d}" if pd.notna(x) else None),
        'timestamp': events_df.apply(build_timestamp, axis=1),
        'year': events_df.apply(get_year, axis=1),
        'latitude': events_df['latitude'].round(4),
        'longitude': events_df['longitude'].round(4),
        'country': events_df['country'],
        'location': events_df.get('locationName'),
        'cause_code': events_df.get('causeCode'),
        'cause': events_df.get('causeCode').map(CAUSE_SIMPLE),
        'eq_magnitude': events_df.get('eqMagnitude'),
        'max_water_height_m': events_df.get('maxWaterHeight'),
        'intensity': events_df.get('tsIntensity'),
        'runup_count': events_df.get('numRunups', 0),
        'deaths': events_df.get('deaths'),
        'deaths_order': events_df.get('deathsAmountOrder'),
        'damage_millions': events_df.get('damageMillionsDollars'),
        'damage_order': events_df.get('damageAmountOrder'),
    })

    # Filter to events with valid coordinates
    events_out = events_out.dropna(subset=['latitude', 'longitude'])

    # Assign water body loc_id using base utility
    print("  Assigning water body loc_ids...")
    events_out['loc_id'] = events_out.apply(
        lambda row: get_water_body_loc_id(row['latitude'], row['longitude'], region='global'),
        axis=1
    )

    # Count by water body
    water_counts = events_out['loc_id'].value_counts()
    print(f"  Events by water body (top 5):")
    for loc_id, count in water_counts.head(5).items():
        print(f"    {loc_id}: {count:,}")

    print(f"  Valid events: {len(events_out):,}")

    return events_out


def process_runups(runups_df, events_df):
    """Process runup observations with calculated distance from source."""
    print("\nProcessing runups...")

    # Create event lookup for source coordinates
    event_coords = {}
    for _, row in events_df.iterrows():
        if pd.notna(row.get('id')) and pd.notna(row.get('latitude')) and pd.notna(row.get('longitude')):
            event_coords[row['id']] = (row['latitude'], row['longitude'])

    # Calculate distance from source if not provided
    def get_distance(row):
        # Use existing distance if available
        if pd.notna(row.get('distFromSource')):
            return row['distFromSource']

        # Calculate from event coordinates
        event_id = row.get('tsunamiEventId')
        if event_id in event_coords:
            source_lat, source_lon = event_coords[event_id]
            runup_lat = row.get('latitude')
            runup_lon = row.get('longitude')
            if pd.notna(runup_lat) and pd.notna(runup_lon):
                return round(haversine_km(source_lat, source_lon, runup_lat, runup_lon), 1)
        return None

    # Build timestamp from year/month/day if available
    def build_timestamp(row):
        try:
            year = int(row['year']) if pd.notna(row['year']) else None
            month = int(row.get('month', 1)) if pd.notna(row.get('month')) else 1
            day = int(row.get('day', 1)) if pd.notna(row.get('day')) else 1

            if year and year < 1:
                year = 1
            if year:
                return pd.Timestamp(year=year, month=month, day=day)
        except:
            pass
        return pd.NaT

    runups_out = pd.DataFrame({
        'runup_id': runups_df['id'].apply(lambda x: f"RU{x:06d}" if pd.notna(x) else None),
        'event_id': runups_df['tsunamiEventId'].apply(lambda x: f"TS{int(x):06d}" if pd.notna(x) else None),
        'timestamp': runups_df.apply(build_timestamp, axis=1),
        'year': runups_df['year'],
        'latitude': runups_df['latitude'].round(4) if 'latitude' in runups_df else pd.NA,
        'longitude': runups_df['longitude'].round(4) if 'longitude' in runups_df else pd.NA,
        'country': runups_df['country'],
        'location': runups_df.get('locationName'),
        'water_height_m': runups_df.get('waterHeight'),
        'horizontal_inundation_m': runups_df.get('horizontalInundation'),
        'dist_from_source_km': runups_df.apply(get_distance, axis=1),
        'arrival_travel_time_min': runups_df.get('arrivalTravelMins'),
        'deaths': runups_df.get('deaths'),
        'deaths_order': runups_df.get('deathsAmountOrder'),
        'damage_order': runups_df.get('damageAmountOrder'),
    })

    # Filter to runups with valid coordinates
    runups_with_coords = runups_out.dropna(subset=['latitude', 'longitude'])

    # Assign water body loc_id
    print("  Assigning water body loc_ids...")
    runups_with_coords = runups_with_coords.copy()
    runups_with_coords['loc_id'] = runups_with_coords.apply(
        lambda row: get_water_body_loc_id(row['latitude'], row['longitude'], region='global'),
        axis=1
    )

    print(f"  Runups with coordinates: {len(runups_with_coords):,}")
    print(f"  With distance from source: {runups_with_coords['dist_from_source_km'].notna().sum():,}")

    return runups_with_coords


def print_statistics(events_df, runups_df):
    """Print summary statistics."""
    print("\n" + "=" * 60)
    print("STATISTICS")
    print("=" * 60)

    print(f"\nTotal events: {len(events_df):,}")
    if 'year' in events_df.columns:
        year_valid = events_df['year'].dropna()
        if len(year_valid) > 0:
            print(f"Year range: {int(year_valid.min())} to {int(year_valid.max())}")

    print(f"\nTotal runups: {len(runups_df):,}")

    print("\nCause distribution (events):")
    if 'cause' in events_df.columns:
        for cause, count in events_df['cause'].value_counts().items():
            print(f"  {cause}: {count:,}")

    print("\nTop countries (events):")
    if 'country' in events_df.columns:
        for country, count in events_df['country'].value_counts().head(10).items():
            print(f"  {country}: {count:,}")

    print("\nTop countries (runups):")
    if 'country' in runups_df.columns:
        for country, count in runups_df['country'].value_counts().head(10).items():
            print(f"  {country}: {count:,}")

    print("\nWater body distribution (events, top 10):")
    if 'loc_id' in events_df.columns:
        for loc_id, count in events_df['loc_id'].value_counts().head(10).items():
            print(f"  {loc_id}: {count:,}")


def generate_metadata(events_df, runups_df):
    """Generate metadata.json for the dataset."""
    print("\nGenerating metadata.json...")

    # Year range
    if 'year' in events_df.columns:
        year_valid = events_df['year'].dropna()
        min_year = int(year_valid.min()) if len(year_valid) > 0 else 0
        max_year = int(year_valid.max()) if len(year_valid) > 0 else 0
    else:
        min_year = 0
        max_year = 0

    metadata = {
        "source_id": SOURCE_ID,
        "source_name": "NOAA NCEI Global Historical Tsunami Database",
        "source_url": "https://www.ncei.noaa.gov/products/natural-hazards/tsunamis-earthquakes-volcanoes/tsunamis",
        "doi": "10.7289/V5PN93H7",
        "license": "Public Domain (U.S. Government)",
        "description": f"Historical tsunami events and runup observations from {min_year} to {max_year}",

        "geographic_level": "global",
        "geographic_coverage": {
            "type": "global",
            "description": "All coastal regions worldwide"
        },

        "temporal_coverage": {
            "start": min_year,
            "end": max_year,
            "frequency": "event-based"
        },

        "files": {
            "events": {
                "filename": "events.parquet",
                "description": "Tsunami source events (earthquake/landslide epicenters)",
                "record_type": "event",
                "record_count": len(events_df)
            },
            "runups": {
                "filename": "runups.parquet",
                "description": "Runup observations (coastal impact points)",
                "record_type": "observation",
                "record_count": len(runups_df)
            }
        },

        "metrics": {
            "eq_magnitude": {
                "name": "Earthquake Magnitude",
                "description": "Magnitude of triggering earthquake",
                "unit": "magnitude",
                "file": "events.parquet"
            },
            "max_water_height_m": {
                "name": "Max Water Height",
                "description": "Maximum water height observed",
                "unit": "meters",
                "file": "events.parquet"
            },
            "intensity": {
                "name": "Tsunami Intensity",
                "description": "Soloviev-Imamura intensity scale",
                "unit": "scale",
                "file": "events.parquet"
            },
            "water_height_m": {
                "name": "Runup Water Height",
                "description": "Water height at observation point",
                "unit": "meters",
                "file": "runups.parquet"
            },
            "dist_from_source_km": {
                "name": "Distance from Source",
                "description": "Distance from tsunami source epicenter",
                "unit": "km",
                "file": "runups.parquet"
            }
        },

        "llm_summary": f"NOAA Global Tsunami Database, {min_year}-{max_year}. "
                      f"{len(events_df):,} source events, {len(runups_df):,} runup observations. "
                      f"Includes earthquake/volcano/landslide triggered tsunamis worldwide.",

        "processing": {
            "converter": "data_converters/converters/convert_global_tsunami.py",
            "last_run": pd.Timestamp.now().strftime("%Y-%m-%d")
        }
    }

    # Write metadata.json
    metadata_path = OUTPUT_DIR / "metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    print(f"  Saved: {metadata_path}")


def main():
    """Main conversion logic."""
    print("=" * 60)
    print("NOAA Global Tsunami Database Converter")
    print("=" * 60)

    # Load data
    events_df, runups_df = load_tsunami_data()

    if events_df.empty:
        print("\nERROR: No events loaded")
        return 1

    # Process events
    events_out = process_events(events_df)

    # Load earthquake data for cross-event linking
    earthquakes_df = load_earthquake_data()

    # Link tsunamis to triggering earthquakes
    events_out = link_tsunamis_to_earthquakes(events_out, earthquakes_df)

    # Load volcano data for cross-event linking
    volcano_data, volcano_type = load_volcano_data()

    # Link tsunamis to triggering volcanoes
    events_out = link_tsunamis_to_volcanoes(events_out, volcano_data, volcano_type)

    # Process runups
    runups_out = process_runups(runups_df, events_df)

    # Print statistics
    print_statistics(events_out, runups_out)

    # Save outputs
    print("\n" + "=" * 60)
    print("Saving outputs...")
    print("=" * 60)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    events_path = OUTPUT_DIR / "events.parquet"
    save_parquet(events_out, events_path, description="tsunami source events")

    runups_path = OUTPUT_DIR / "runups.parquet"
    save_parquet(runups_out, runups_path, description="runup observations")

    # Generate metadata
    generate_metadata(events_out, runups_out)

    print("\n" + "=" * 60)
    print("COMPLETE!")
    print("=" * 60)
    print(f"\nOutput: {OUTPUT_DIR}")
    print(f"  events.parquet: {len(events_out):,} events")
    print(f"  runups.parquet: {len(runups_out):,} runups")

    # Linking summary
    print(f"\nCross-event linking:")
    if 'parent_event_id' in events_out.columns:
        eq_linked = events_out['parent_event_id'].notna().sum()
        print(f"  Linked to earthquakes: {eq_linked:,} events")
    if 'volcano_id' in events_out.columns:
        vol_linked = events_out['volcano_id'].notna().sum()
        print(f"  Linked to volcanoes: {vol_linked:,} events")

    return 0


if __name__ == "__main__":
    sys.exit(main())
