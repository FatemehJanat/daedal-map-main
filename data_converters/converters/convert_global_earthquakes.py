"""
Convert USGS global earthquake data to parquet format.

Creates output files:
1. events.parquet - Global earthquake events with standard schema
2. GLOBAL.parquet - Country-year aggregated statistics

USGS provides global earthquake data - this converter processes all worldwide
earthquakes, not just USA.

Includes aftershock sequence detection using Gardner-Knopoff windows.

Input: CSV files from USGS earthquake search (worldwide, M4.0+)
Output: Parquet files in global/usgs_earthquakes/

Usage:
    python convert_global_earthquakes.py
"""
import pandas as pd
import numpy as np
from pathlib import Path
import json
import sys
from math import radians, cos, sin, asin, sqrt

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from data_converters.base import (
    get_water_body_loc_id,
    save_parquet,
)
from build.catalog.finalize_source import finalize_source

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/usgs_earthquakes_merged")
IMPORTED_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/imported/usgs_earthquakes_merged")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/global/usgs_earthquakes")
SOURCE_ID = "usgs_earthquakes_global"


# =============================================================================
# Haversine Distance
# =============================================================================

def haversine_km(lon1, lat1, lon2, lat2):
    """
    Calculate the great circle distance in kilometers between two points.
    """
    # Convert to radians
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])

    # Haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))

    # Earth radius in km
    r = 6371
    return c * r


# =============================================================================
# Gardner-Knopoff Aftershock Windows
# =============================================================================

def gardner_knopoff_window(magnitude):
    """
    Calculate aftershock time and distance windows using Gardner-Knopoff (1974).

    These are empirically-derived windows that capture ~90% of aftershocks.

    Time window (days): 10^(0.5 * M - 1.5)
    Distance window (km): 10^(0.5 * M - 0.5)

    Returns: (time_days, distance_km)
    """
    if pd.isna(magnitude) or magnitude < 5.0:
        return (0, 0)  # Only compute for M5.0+

    time_days = 10 ** (0.5 * magnitude - 1.5)
    distance_km = 10 ** (0.5 * magnitude - 0.5)

    return (time_days, distance_km)


def detect_aftershock_sequences(df, min_mainshock_mag=5.5):
    """
    Detect aftershock sequences using Gardner-Knopoff windows.

    Algorithm:
    1. Sort events by time
    2. For each potential mainshock (M >= min_mainshock_mag):
       - Calculate time/distance window
       - Find subsequent events within window
       - Tag them as aftershocks (if not already tagged to a larger mainshock)
    3. Largest earthquake in a cluster becomes the mainshock

    Returns DataFrame with added columns:
    - mainshock_id: ID of the mainshock this event is an aftershock of (None if mainshock)
    - aftershock_count: Number of aftershocks (for mainshocks only)
    - sequence_id: Shared ID for all events in a sequence
    """
    print("\nDetecting aftershock sequences...")
    print(f"  Minimum mainshock magnitude: M{min_mainshock_mag}")

    # Sort by time
    df = df.sort_values('time').reset_index(drop=True)

    # Initialize columns
    df['mainshock_id'] = None
    df['sequence_id'] = None
    df['is_mainshock'] = False

    # Get potential mainshocks (M >= threshold, sorted by magnitude desc)
    mainshocks = df[df['mag'] >= min_mainshock_mag].sort_values('mag', ascending=False)
    print(f"  Potential mainshocks: {len(mainshocks):,}")

    sequence_count = 0
    total_aftershocks = 0

    # Process each potential mainshock
    for idx, mainshock in mainshocks.iterrows():
        # Skip if already assigned as aftershock of a larger event
        if df.loc[idx, 'mainshock_id'] is not None:
            continue

        # Calculate window
        time_window, dist_window = gardner_knopoff_window(mainshock['mag'])

        # Time bounds
        start_time = mainshock['time']
        end_time = start_time + pd.Timedelta(days=time_window)

        # Find events within time window (after mainshock)
        time_mask = (df['time'] > start_time) & (df['time'] <= end_time)
        candidates = df[time_mask]

        if len(candidates) == 0:
            continue

        # Check distance for each candidate
        aftershock_indices = []
        for cand_idx, candidate in candidates.iterrows():
            # Skip if already assigned
            if df.loc[cand_idx, 'mainshock_id'] is not None:
                continue

            dist = haversine_km(
                mainshock['longitude'], mainshock['latitude'],
                candidate['longitude'], candidate['latitude']
            )

            if dist <= dist_window:
                aftershock_indices.append(cand_idx)

        # Tag aftershocks
        if aftershock_indices:
            sequence_count += 1
            seq_id = f"SEQ{sequence_count:06d}"

            # Tag mainshock
            df.loc[idx, 'is_mainshock'] = True
            df.loc[idx, 'sequence_id'] = seq_id

            # Tag aftershocks
            for as_idx in aftershock_indices:
                df.loc[as_idx, 'mainshock_id'] = mainshock['id']
                df.loc[as_idx, 'sequence_id'] = seq_id

            total_aftershocks += len(aftershock_indices)

    # Count aftershocks per mainshock
    aftershock_counts = df[df['mainshock_id'].notna()].groupby('mainshock_id').size()
    df['aftershock_count'] = df['id'].map(aftershock_counts).fillna(0).astype(int)

    # Statistics
    mainshock_count = df['is_mainshock'].sum()
    print(f"  Sequences detected: {sequence_count:,}")
    print(f"  Mainshocks: {mainshock_count:,}")
    print(f"  Aftershocks tagged: {total_aftershocks:,}")

    # Top sequences
    if mainshock_count > 0:
        print("\n  Largest aftershock sequences:")
        top_sequences = df[df['is_mainshock']].nlargest(10, 'aftershock_count')
        for _, row in top_sequences.iterrows():
            if row['aftershock_count'] > 0:
                date_str = row['time'].strftime('%Y-%m-%d') if pd.notna(row['time']) else '?'
                print(f"    M{row['mag']:.1f} {date_str} - {row['aftershock_count']:,} aftershocks - {row.get('place', 'Unknown')}")

    return df


# =============================================================================
# Earthquake-Specific Calculations
# =============================================================================

def calculate_felt_radius(magnitude, depth_km=None):
    """
    Calculate felt radius in km (MMI II-III, people notice shaking).

    Based on empirical seismological attenuation models.
    Formula: R = 10^(0.44 * M - 0.29) with depth correction.

    Shallow earthquakes (< 70km) are felt over wider areas.
    Deep earthquakes have smaller felt radii.

    Approximate felt radii by magnitude (shallow):
    - M4.0: ~30 km
    - M5.0: ~80 km
    - M6.0: ~220 km
    - M7.0: ~620 km
    - M8.0: ~1700 km
    """
    if pd.isna(magnitude):
        return None

    # Base formula: empirical MMI attenuation
    radius = 10 ** (0.44 * magnitude - 0.29)

    # Depth correction: deeper quakes have smaller felt areas
    if depth_km is not None and not pd.isna(depth_km):
        if depth_km > 300:
            radius *= 0.5  # Deep focus - 50% reduction
        elif depth_km > 70:
            radius *= 0.7  # Intermediate - 30% reduction
        # Shallow (< 70km) - full radius

    return round(radius, 1)


def calculate_damage_radius(magnitude, depth_km=None):
    """
    Calculate damage radius in km (MMI VI+, potential structural damage).

    Based on empirical attenuation for damaging ground motion.
    Formula: R = 10^(0.32 * M - 0.78) with depth correction.

    Damage radii are much smaller than felt radii - concentrated near epicenter.

    Approximate damage radii by magnitude (shallow):
    - M5.0: ~7 km
    - M6.0: ~14 km
    - M7.0: ~29 km
    - M8.0: ~60 km
    """
    if pd.isna(magnitude):
        return None

    # Only earthquakes M5+ typically cause structural damage
    if magnitude < 5.0:
        return 0.0

    # Base formula: empirical MMI attenuation for damaging intensity
    radius = 10 ** (0.32 * magnitude - 0.78)

    # Depth correction: deeper quakes cause less surface damage
    if depth_km is not None and not pd.isna(depth_km):
        if depth_km > 300:
            radius *= 0.3  # Deep focus - 70% reduction
        elif depth_km > 70:
            radius *= 0.5  # Intermediate - 50% reduction
        # Shallow (< 70km) - full radius

    return round(radius, 1)


# =============================================================================
# Country Assignment
# =============================================================================

# Bounding boxes for major countries (approximate, for quick lookup)
# Format: (min_lon, min_lat, max_lon, max_lat)
COUNTRY_BOUNDS = {
    'USA': (-180, 17, -65, 72),  # Includes Alaska and Hawaii
    'CAN': (-141, 41, -52, 84),
    'MEX': (-118, 14, -86, 33),
    'JPN': (122, 24, 154, 46),
    'IDN': (95, -11, 141, 6),
    'PHL': (116, 5, 127, 21),
    'CHL': (-76, -56, -66, -17),
    'PER': (-82, -18, -68, 0),
    'NZL': (165, -48, 179, -34),
    'PNG': (140, -12, 157, -1),
    'TUR': (26, 36, 45, 42),
    'GRC': (19, 35, 30, 42),
    'ITA': (6, 36, 19, 47),
    'IRN': (44, 25, 64, 40),
    'AFG': (60, 29, 75, 39),
    'PAK': (61, 23, 77, 37),
    'IND': (68, 6, 97, 36),
    'CHN': (73, 18, 135, 54),
    'RUS': (27, 41, 180, 82),
    'AUS': (112, -45, 155, -10),
    'ARG': (-74, -56, -53, -21),
    'COL': (-82, -5, -66, 14),
    'ECU': (-92, -5, -75, 2),
    'VEN': (-73, 1, -60, 12),
    'BRA': (-74, -34, -34, 6),
    'BOL': (-70, -23, -57, -9),
}


def point_in_bounds(lon, lat, bounds):
    """Check if point is within bounding box."""
    min_lon, min_lat, max_lon, max_lat = bounds
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def assign_loc_id(latitude, longitude):
    """
    Assign loc_id based on coordinates.

    Uses bounding boxes for quick country assignment.
    Falls back to water body code for ocean locations.
    """
    if pd.isna(latitude) or pd.isna(longitude):
        return None

    # Try bounding box match
    for country, bounds in COUNTRY_BOUNDS.items():
        if point_in_bounds(longitude, latitude, bounds):
            return country

    # Default to water body based on coordinates
    return get_water_body_loc_id(latitude, longitude, region='global')


# =============================================================================
# Data Processing
# =============================================================================

def get_source_dir():
    """Get source directory - check raw first, then imported."""
    if RAW_DATA_DIR.exists() and list(RAW_DATA_DIR.glob("earthquakes*.csv")):
        return RAW_DATA_DIR
    elif IMPORTED_DIR.exists() and list(IMPORTED_DIR.glob("earthquakes*.csv")):
        print(f"  Note: Using imported data from {IMPORTED_DIR}")
        return IMPORTED_DIR
    return RAW_DATA_DIR


def load_raw_data():
    """Load all earthquake CSV files."""
    print("Loading earthquake CSV files...")

    source_dir = get_source_dir()
    csv_files = sorted(source_dir.glob("earthquakes*.csv"))
    print(f"  Found {len(csv_files)} CSV files in {source_dir}")

    if len(csv_files) == 0:
        print("  No CSV files found!")
        return pd.DataFrame()

    all_events = []
    for csv_path in csv_files:
        print(f"  Loading {csv_path.name}...", end=' ', flush=True)

        try:
            df = pd.read_csv(csv_path)

            # Drop events with missing coordinates
            df = df.dropna(subset=['latitude', 'longitude', 'mag'])

            # Parse dates (use mixed format for inconsistent timestamp formats)
            df['time'] = pd.to_datetime(df['time'], format='mixed', utc=True)
            df['year'] = df['time'].dt.year

            all_events.append(df)
            print(f"{len(df):,} events")

        except Exception as e:
            print(f"ERROR: {e}")
            continue

    if not all_events:
        return pd.DataFrame()

    # Combine all files
    print("\nCombining all data...")
    combined = pd.concat(all_events, ignore_index=True)
    print(f"  Total: {len(combined):,} events")

    return combined


def process_events(df):
    """Process events with radius calculations, loc_id assignment, and aftershock detection."""
    print("\nProcessing events...")

    # Calculate radii
    print("  Calculating felt/damage radii...")
    df['felt_radius_km'] = df.apply(
        lambda row: calculate_felt_radius(row['mag'], row.get('depth')),
        axis=1
    )
    df['damage_radius_km'] = df.apply(
        lambda row: calculate_damage_radius(row['mag'], row.get('depth')),
        axis=1
    )

    # Assign loc_ids based on coordinates
    print("  Assigning loc_ids...")
    df['loc_id'] = df.apply(
        lambda row: assign_loc_id(row['latitude'], row['longitude']),
        axis=1
    )

    # Show breakdown
    loc_id_counts = df['loc_id'].value_counts()
    print(f"  Unique loc_ids: {len(loc_id_counts)}")
    print(f"  Top 10:")
    for loc_id, count in loc_id_counts.head(10).items():
        print(f"    {loc_id}: {count:,}")

    # Detect aftershock sequences
    df = detect_aftershock_sequences(df, min_mainshock_mag=5.5)

    return df


def create_events_dataframe(df):
    """Create standardized events DataFrame with unified schema."""
    print("\nCreating events parquet...")

    # Use USGS id as event_id for linking
    events = pd.DataFrame({
        'event_id': df['id'],  # Use USGS ID for aftershock linking
        'event_type': 'earthquake',  # Standard event type column
        'timestamp': df['time'],
        'year': df['year'],
        'latitude': df['latitude'].round(4),
        'longitude': df['longitude'].round(4),
        'loc_id': df['loc_id'],
        'magnitude': df['mag'].round(2),
        'depth_km': df['depth'].round(1),
        'felt_radius_km': df['felt_radius_km'],
        'damage_radius_km': df['damage_radius_km'],
        'place': df['place'],
        # Aftershock sequence columns
        'mainshock_id': df['mainshock_id'],  # ID of mainshock (None if this IS mainshock)
        'sequence_id': df['sequence_id'],    # Shared ID for all events in sequence
        'is_mainshock': df['is_mainshock'],  # True if this event has aftershocks
        'aftershock_count': df['aftershock_count'],  # Number of aftershocks (mainshocks only)
    })

    # Sort by time descending
    events = events.sort_values('timestamp', ascending=False)

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "events.parquet"
    save_parquet(events, output_path, description="global earthquake events")

    print(f"  Total events: {len(events):,}")
    print(f"  Year range: {events['year'].min()} to {events['year'].max()}")
    print(f"  Magnitude range: {events['magnitude'].min():.1f} to {events['magnitude'].max():.1f}")

    return events


def create_aggregates(events):
    """Create country-year aggregates."""
    print("\nCreating country-year aggregates...")

    # Filter to events with loc_id
    df = events[events['loc_id'].notna()].copy()

    # Group by country-year
    agg = df.groupby(['loc_id', 'year']).agg({
        'event_id': 'count',
        'magnitude': ['min', 'max', 'mean'],
        'depth_km': 'mean'
    }).reset_index()

    # Flatten column names
    agg.columns = ['loc_id', 'year', 'earthquake_count',
                   'min_magnitude', 'max_magnitude', 'avg_magnitude', 'avg_depth_km']

    # Round values
    agg['min_magnitude'] = agg['min_magnitude'].round(2)
    agg['max_magnitude'] = agg['max_magnitude'].round(2)
    agg['avg_magnitude'] = agg['avg_magnitude'].round(2)
    agg['avg_depth_km'] = agg['avg_depth_km'].round(1)

    # Add magnitude category counts
    for mag_threshold, col_name in [(5.0, 'count_mag_5plus'), (6.0, 'count_mag_6plus'), (7.0, 'count_mag_7plus')]:
        mag_counts = df[df['magnitude'] >= mag_threshold].groupby(
            ['loc_id', 'year']
        ).size().reset_index(name=col_name)
        agg = agg.merge(mag_counts, on=['loc_id', 'year'], how='left')
        agg[col_name] = agg[col_name].fillna(0).astype('Int64')

    print(f"  Country-year records: {len(agg):,}")
    print(f"  Unique countries: {agg['loc_id'].nunique():,}")

    # Save
    output_path = OUTPUT_DIR / "GLOBAL.parquet"
    save_parquet(agg, output_path, description="country-year aggregates")

    return agg


# =============================================================================
# Statistics & Reporting
# =============================================================================

def print_statistics(events, aggregates):
    """Print summary statistics."""
    print("\n" + "=" * 60)
    print("Statistics")
    print("=" * 60)

    print(f"\nTotal events: {len(events):,}")
    print(f"Year range: {events['year'].min()}-{events['year'].max()}")

    # Location summary
    land_count = events[~events['loc_id'].str.startswith('X', na=False)].shape[0]
    water_count = events[events['loc_id'].str.startswith('X', na=False)].shape[0]
    print(f"\nLocation:")
    print(f"  Land: {land_count:,} ({land_count/len(events)*100:.1f}%)")
    print(f"  Water: {water_count:,} ({water_count/len(events)*100:.1f}%)")

    print("\nMagnitude distribution:")
    print(f"  Min: {events['magnitude'].min():.2f}")
    print(f"  Max: {events['magnitude'].max():.2f}")
    print(f"  Mean: {events['magnitude'].mean():.2f}")
    print(f"  M5.0+: {(events['magnitude'] >= 5.0).sum():,}")
    print(f"  M6.0+: {(events['magnitude'] >= 6.0).sum():,}")
    print(f"  M7.0+: {(events['magnitude'] >= 7.0).sum():,}")
    print(f"  M8.0+: {(events['magnitude'] >= 8.0).sum():,}")

    print("\nTop 10 countries by event count:")
    top = aggregates.groupby('loc_id')['earthquake_count'].sum().nlargest(10)
    for loc_id, count in top.items():
        print(f"  {loc_id}: {int(count):,}")

    print("\nLargest earthquakes:")
    largest = events.nlargest(10, 'magnitude')[['timestamp', 'magnitude', 'place', 'loc_id']]
    for _, row in largest.iterrows():
        date_str = row['timestamp'].strftime('%Y-%m-%d') if pd.notna(row['timestamp']) else '?'
        print(f"  M{row['magnitude']:.1f} {date_str} - {row['place']} ({row['loc_id']})")


# =============================================================================
# Main
# =============================================================================

def main():
    """Main conversion logic."""
    print("=" * 60)
    print("Global USGS Earthquake Converter")
    print("=" * 60)

    # Load raw data
    df = load_raw_data()
    if df.empty:
        print("\nERROR: No earthquake data found")
        print(f"Expected CSV files in: {RAW_DATA_DIR}")
        print("\nTo download global earthquake data from USGS:")
        print("  1. Go to https://earthquake.usgs.gov/earthquakes/search/")
        print("  2. Set magnitude minimum to 4.0")
        print("  3. Set date range (e.g., 1900-present)")
        print("  4. Select 'CSV' output format")
        print("  5. Download and save to Raw data/usgs_earthquakes_global/")
        return 1

    # Process events
    df = process_events(df)

    # Create output dataframes
    events = create_events_dataframe(df)
    aggregates = create_aggregates(events)

    # Print statistics
    print_statistics(events, aggregates)

    # Finalize
    print("\n" + "=" * 60)
    print("Finalizing source...")
    print("=" * 60)

    try:
        finalize_source(
            parquet_path=str(OUTPUT_DIR / "GLOBAL.parquet"),
            source_id=SOURCE_ID,
            events_parquet_path=str(OUTPUT_DIR / "events.parquet")
        )
    except ValueError as e:
        print(f"  Note: {e}")
        print(f"  Add '{SOURCE_ID}' to source_registry.py to enable auto-finalization")

    print("\n" + "=" * 60)
    print("COMPLETE!")
    print(f"Output: {OUTPUT_DIR}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
