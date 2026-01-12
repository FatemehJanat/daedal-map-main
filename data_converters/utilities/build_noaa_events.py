"""
Build NOAA Storm Events events.parquet file.

Creates events.parquet with individual storm events including location data
for map visualization alongside the existing USA.parquet county aggregates.

Uses 3-pass geocoding:
1. FIPS-based loc_id from source data
2. Nearest county match within 12nm (territorial waters) for coastal events
3. Water body codes for marine events beyond 12nm

Input: Raw NOAA storm CSV files
Output: events.parquet with individual storm events

Usage:
    python build_noaa_events.py
"""
import pandas as pd
import geopandas as gpd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
from datetime import datetime
from shapely.geometry import Point, shape
import json

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/noaa_storms")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA/noaa_storms")
GEOMETRY_PATH = Path("C:/Users/Bryan/Desktop/county-map-data/geometry/USA.parquet")

# Territorial waters threshold: 12 nautical miles = ~0.2 degrees
TERRITORIAL_WATERS_DEG = 0.2

# State FIPS to abbreviation mapping
STATE_FIPS = {
    '01': 'AL', '02': 'AK', '04': 'AZ', '05': 'AR', '06': 'CA',
    '08': 'CO', '09': 'CT', '10': 'DE', '11': 'DC', '12': 'FL',
    '13': 'GA', '15': 'HI', '16': 'ID', '17': 'IL', '18': 'IN',
    '19': 'IA', '20': 'KS', '21': 'KY', '22': 'LA', '23': 'ME',
    '24': 'MD', '25': 'MA', '26': 'MI', '27': 'MN', '28': 'MS',
    '29': 'MO', '30': 'MT', '31': 'NE', '32': 'NV', '33': 'NH',
    '34': 'NJ', '35': 'NM', '36': 'NY', '37': 'NC', '38': 'ND',
    '39': 'OH', '40': 'OK', '41': 'OR', '42': 'PA', '44': 'RI',
    '45': 'SC', '46': 'SD', '47': 'TN', '48': 'TX', '49': 'UT',
    '50': 'VT', '51': 'VA', '53': 'WA', '54': 'WV', '55': 'WI',
    '56': 'WY', '72': 'PR', '78': 'VI'
}


def get_water_body_loc_id(lat, lon):
    """
    Assign water body loc_id for points in international waters.
    Uses ISO 3166-1 X-prefix codes for water bodies.
    """
    # Great Lakes
    if 41 < lat < 49 and -93 < lon < -76:
        return "XLG"  # Great Lakes

    # Gulf of Mexico
    if 18 < lat < 31 and -98 < lon < -80:
        return "XSG"  # Gulf of Mexico

    # Caribbean Sea
    if 8 < lat < 22 and -90 < lon < -60:
        return "XSC"  # Caribbean Sea

    # Atlantic Ocean (East Coast)
    if lon > -82 and lat > 24 and lat < 50:
        return "XOA"  # Atlantic Ocean

    # Pacific Ocean (West Coast, Hawaii, Alaska)
    if lon < -100 or lon > 150:
        return "XOP"  # Pacific Ocean

    # Bering Sea
    if lon < -160 and lat > 50:
        return "XSB"  # Bering Sea

    # Default to generic ocean
    return "XOO"  # Unknown ocean


def load_counties():
    """Load county geometry from parquet for spatial joins."""
    print("Loading county geometry...")

    df = pd.read_parquet(GEOMETRY_PATH)
    df = df[df['admin_level'] == 2].copy()

    # Convert GeoJSON to shapely geometry
    def parse_geometry(g):
        if g is None:
            return None
        if isinstance(g, str):
            return shape(json.loads(g))
        return shape(g)

    df['geometry'] = df['geometry'].apply(parse_geometry)
    df = df[df['geometry'].notna()].copy()

    gdf = gpd.GeoDataFrame(df, geometry='geometry', crs="EPSG:4326")
    print(f"  Loaded {len(gdf)} counties")
    return gdf


def fips_to_loc_id(state_fips, cz_fips):
    """Convert state and county zone FIPS to loc_id format."""
    if pd.isna(state_fips) or pd.isna(cz_fips):
        return None

    state_fips_str = str(int(state_fips)).zfill(2)
    state_abbr = STATE_FIPS.get(state_fips_str)

    if not state_abbr:
        return None

    # CZ_FIPS is county code (last 3 digits)
    county_fips = str(int(cz_fips)).zfill(3)
    full_fips = int(state_fips_str + county_fips)

    return f"USA-{state_abbr}-{full_fips}"


def calculate_tornado_radii(tor_length, tor_width, ef_scale):
    """
    Calculate dual radii for tornado visualization (matches earthquake/volcano pattern).

    Returns:
        tuple: (felt_radius_km, damage_radius_km)
        - felt_radius_km: Broader impact zone based on track length
        - damage_radius_km: Actual tornado damage width
    """
    # Default EF scale radii in meters (from Fujita-Pearson data)
    EF_RADII_M = {
        0: 8,     # EF0: ~16m wide path
        1: 25,    # EF1: ~50m wide path
        2: 80,    # EF2: ~160m wide path
        3: 200,   # EF3: ~400m wide path
        4: 500,   # EF4: ~1km wide path
        5: 1200   # EF5: ~2.4km wide path
    }

    # Calculate damage_radius_km from tornado_width_yd
    if pd.notna(tor_width) and tor_width > 0:
        # yards to km: yards * 0.0009144, then half for radius
        damage_radius_km = (tor_width * 0.0009144) / 2
    else:
        # Fall back to EF scale default
        scale_num = 0
        if pd.notna(ef_scale):
            scale_str = str(ef_scale).upper()
            for i in range(6):
                if str(i) in scale_str:
                    scale_num = i
                    break
        damage_radius_km = EF_RADII_M.get(scale_num, 8) / 1000  # meters to km

    # Calculate felt_radius_km from track length
    if pd.notna(tor_length) and tor_length > 0:
        # miles to km, then half for radius
        felt_radius_km = (tor_length * 1.60934) / 2
    else:
        felt_radius_km = 5.0  # Default 5 km

    # Ensure felt >= damage (impact zone should be larger than damage zone)
    if felt_radius_km < damage_radius_km:
        felt_radius_km = damage_radius_km * 2

    return felt_radius_km, damage_radius_km


def calculate_event_radius_km(event_type, magnitude, tor_length, tor_width):
    """
    Calculate approximate event radius in km for visualization.

    Different event types have different spatial extents.
    Note: For tornadoes, use calculate_tornado_radii() for dual radii.
    """
    event_type_upper = str(event_type).upper() if pd.notna(event_type) else ""

    # Tornado - handled separately by calculate_tornado_radii
    if 'TORNADO' in event_type_upper:
        # Return felt_radius for backwards compatibility
        felt, _ = calculate_tornado_radii(tor_length, tor_width, None)
        return felt

    # Hail - magnitude is hail size in inches, convert to damage radius
    if 'HAIL' in event_type_upper:
        if pd.notna(magnitude):
            # Larger hail -> wider damage swath
            # 1 inch hail ~2 km, 4 inch hail ~10 km (rough estimate)
            return min(2.0 + (magnitude * 2.0), 15.0)
        return 2.0

    # Hurricane/Tropical Storm - large radius events
    if 'HURRICANE' in event_type_upper or 'TROPICAL STORM' in event_type_upper:
        return 150.0  # ~150 km typical hurricane force wind radius

    # Flood events - typically affect river basins/watersheds
    if 'FLOOD' in event_type_upper:
        return 20.0  # 20 km typical flood extent

    # Wildfire - can be massive
    if 'FIRE' in event_type_upper or 'WILDFIRE' in event_type_upper:
        return 30.0  # 30 km typical wildfire radius

    # High winds, thunderstorms - moderate extent
    if any(x in event_type_upper for x in ['WIND', 'THUNDERSTORM', 'TSTM']):
        if pd.notna(magnitude):
            # Wind speed in knots -> radius (higher winds, wider area)
            return min(5.0 + (magnitude / 10.0), 25.0)
        return 10.0

    # Winter weather - can cover large areas
    if any(x in event_type_upper for x in ['SNOW', 'ICE', 'WINTER', 'BLIZZARD']):
        return 50.0

    # Default for other events
    return 10.0


def process_storm_details():
    """Load and process storm details CSV files."""
    print("\nProcessing storm details CSV files...")

    csv_files = sorted(RAW_DATA_DIR.glob("StormEvents_details-ftp_v1.0_d*.csv"))
    print(f"  Found {len(csv_files)} files")

    all_events = []
    total_loaded = 0
    total_with_location = 0

    for csv_path in csv_files:
        year = csv_path.stem.split('_d')[1].split('_')[0]
        print(f"  Processing {year}...", end=' ', flush=True)

        try:
            df = pd.read_csv(csv_path)
            total_loaded += len(df)

            # Filter to events with location data (either BEGIN or END coords)
            has_location = (
                (df['BEGIN_LAT'].notna() & df['BEGIN_LON'].notna()) |
                (df['END_LAT'].notna() & df['END_LON'].notna())
            )

            df_with_loc = df[has_location].copy()
            count_with_loc = len(df_with_loc)
            total_with_location += count_with_loc

            if count_with_loc == 0:
                print(f"{len(df)} events, 0 with location")
                continue

            # Use BEGIN coords if available, otherwise END coords
            df_with_loc['latitude'] = df_with_loc['BEGIN_LAT'].fillna(df_with_loc['END_LAT'])
            df_with_loc['longitude'] = df_with_loc['BEGIN_LON'].fillna(df_with_loc['END_LON'])

            # Preserve END coords for track display (especially tornadoes)
            df_with_loc['end_latitude'] = df_with_loc['END_LAT']
            df_with_loc['end_longitude'] = df_with_loc['END_LON']

            # Parse datetime
            # Note: %y (2-digit year) defaults to 2000-2068 pivot, but NOAA data
            # starts from 1950. Dates parsed as 2050-2068 need to be fixed to 1950-1968.
            df_with_loc['event_time'] = pd.to_datetime(
                df_with_loc['BEGIN_DATE_TIME'],
                format='%d-%b-%y %H:%M:%S',
                errors='coerce'
            )
            # Fix century parsing: any date > 2025 should be shifted back 100 years
            future_mask = df_with_loc['event_time'].dt.year > 2025
            df_with_loc.loc[future_mask, 'event_time'] = (
                df_with_loc.loc[future_mask, 'event_time'] - pd.DateOffset(years=100)
            )

            # Calculate dual radii for tornadoes (felt + damage)
            def calc_radii(row):
                event_type = str(row['EVENT_TYPE']).upper() if pd.notna(row['EVENT_TYPE']) else ""
                if 'TORNADO' in event_type:
                    felt, damage = calculate_tornado_radii(
                        row.get('TOR_LENGTH'),
                        row.get('TOR_WIDTH'),
                        row.get('TOR_F_SCALE')
                    )
                    return pd.Series({'felt_radius_km': felt, 'damage_radius_km': damage})
                else:
                    # Non-tornado: use single radius for both
                    radius = calculate_event_radius_km(
                        row['EVENT_TYPE'],
                        row.get('MAGNITUDE'),
                        row.get('TOR_LENGTH'),
                        row.get('TOR_WIDTH')
                    )
                    return pd.Series({'felt_radius_km': radius, 'damage_radius_km': radius})

            radii = df_with_loc.apply(calc_radii, axis=1)
            df_with_loc['felt_radius_km'] = radii['felt_radius_km']
            df_with_loc['damage_radius_km'] = radii['damage_radius_km']

            # Create loc_id
            df_with_loc['loc_id'] = df_with_loc.apply(
                lambda row: fips_to_loc_id(row['STATE_FIPS'], row['CZ_FIPS']),
                axis=1
            )

            # Select columns for events file
            events = df_with_loc[[
                'EVENT_ID', 'event_time', 'EVENT_TYPE',
                'latitude', 'longitude', 'end_latitude', 'end_longitude',
                'felt_radius_km', 'damage_radius_km',
                'MAGNITUDE', 'MAGNITUDE_TYPE',
                'TOR_F_SCALE', 'TOR_LENGTH', 'TOR_WIDTH',
                'DEATHS_DIRECT', 'DEATHS_INDIRECT',
                'INJURIES_DIRECT', 'INJURIES_INDIRECT',
                'DAMAGE_PROPERTY', 'DAMAGE_CROPS',
                'BEGIN_LOCATION', 'loc_id'
            ]].copy()

            # Rename columns to match unified event schema (DISASTER_DISPLAY.md)
            events.columns = [
                'event_id', 'timestamp', 'event_type',
                'latitude', 'longitude', 'end_latitude', 'end_longitude',
                'felt_radius_km', 'damage_radius_km',
                'magnitude', 'magnitude_type',
                'tornado_scale', 'tornado_length_mi', 'tornado_width_yd',
                'deaths_direct', 'deaths_indirect',
                'injuries_direct', 'injuries_indirect',
                'damage_property', 'damage_crops',
                'location', 'loc_id'
            ]

            all_events.append(events)

            print(f"{len(df)} events, {count_with_loc} with location ({count_with_loc/len(df)*100:.1f}%)")

        except Exception as e:
            print(f"ERROR: {e}")
            continue

    print(f"\nCombining all events...")
    combined = pd.concat(all_events, ignore_index=True)

    print(f"  Total events loaded: {total_loaded:,}")
    print(f"  Events with location data: {total_with_location:,} ({total_with_location/total_loaded*100:.1f}%)")
    print(f"  Final events.parquet size: {len(combined):,}")

    return combined


def geocode_missing_events(df, counties_gdf):
    """
    Apply 3-pass geocoding to fill missing loc_ids.

    Pass 1: Already done - FIPS-based loc_id from source data
    Pass 2: Nearest county match within 12nm (territorial waters)
    Pass 3: Water body codes for marine events beyond 12nm
    """
    missing_mask = df['loc_id'].isna()
    missing_count = missing_mask.sum()

    if missing_count == 0:
        print("\nAll events have loc_id from FIPS codes")
        return df

    print(f"\nGeocoding {missing_count:,} events missing loc_id...")

    # Create GeoDataFrame for spatial operations - use original index
    missing_df = df[missing_mask].copy()
    missing_df['_orig_idx'] = missing_df.index
    geometry = [Point(xy) for xy in zip(missing_df['longitude'], missing_df['latitude'])]
    missing_gdf = gpd.GeoDataFrame(missing_df, geometry=geometry, crs="EPSG:4326")

    # === PASS 2: Nearest county within territorial waters ===
    print("  Pass 2: Nearest county matching (< 12nm)...")
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # Suppress CRS warning
        nearest = gpd.sjoin_nearest(
            missing_gdf,
            counties_gdf[['loc_id', 'geometry']].rename(columns={'loc_id': 'county_loc_id'}),
            how='left',
            distance_col='dist_to_county'
        )

    # Filter to within territorial waters and dedupe by original index
    within_territorial = nearest[nearest['dist_to_county'] <= TERRITORIAL_WATERS_DEG].copy()
    within_territorial = within_territorial.drop_duplicates(subset=['_orig_idx'])
    nearest_count = len(within_territorial)
    print(f"    Matched {nearest_count:,} events to nearest county")

    # Build mapping and apply
    loc_id_map = within_territorial.set_index('_orig_idx')['county_loc_id'].to_dict()
    for orig_idx, loc_id in loc_id_map.items():
        df.loc[orig_idx, 'loc_id'] = loc_id

    # === PASS 3: Water body codes for remaining events ===
    still_missing_mask = df['loc_id'].isna()
    still_missing_count = still_missing_mask.sum()

    if still_missing_count > 0:
        print(f"  Pass 3: Assigning water body codes to {still_missing_count:,} marine events...")
        df.loc[still_missing_mask, 'loc_id'] = df.loc[still_missing_mask].apply(
            lambda row: get_water_body_loc_id(row['latitude'], row['longitude']),
            axis=1
        )

    # Summary
    county_match = df['loc_id'].str.startswith('USA-', na=False).sum()
    water_body = df['loc_id'].str.startswith('X', na=False).sum()
    total = len(df)

    print(f"\nGeocoding complete:")
    print(f"  County matches: {county_match:,} ({county_match/total*100:.1f}%)")
    print(f"  Water body codes: {water_body:,} ({water_body/total*100:.1f}%)")

    return df


def haversine_km(lon1, lat1, lon2, lat2):
    """Calculate distance in km between two points using haversine formula."""
    from math import radians, cos, sin, asin, sqrt
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    return 2 * 6371 * asin(sqrt(a))


def link_tornado_sequences(df, time_window_hours=1, distance_km=10):
    """
    Link tornadoes into sequences (same storm system).

    Algorithm:
    - Tornadoes within time_window_hours of each other are candidates
    - If tornado A's end point is within distance_km of tornado B's start point
      AND B starts after A, they are linked
    - Chains are built by walking forward/backward through links
    - Each sequence gets a unique sequence_id based on the earliest tornado

    Official NWS Standard (for reference - we use looser values for storm system tracking):
    - NWS considers same tornado segment if: lifts < 4 minutes AND < 2 miles (3.2 km)
    - NWS considers separate tornado if: lifts >= 4 minutes OR >= 2 miles
    - Source: https://www.ncei.noaa.gov/stormevents/faq.jsp

    Current defaults (1 hr, 10 km) are looser to capture same supercell/storm system,
    not just official tornado segments. Adjust as needed:
    - Stricter (NWS-like): time_window_hours=0.1, distance_km=3.2
    - Looser (outbreak tracking): time_window_hours=3, distance_km=50

    Adds columns:
    - sequence_id: ID of the sequence (event_id of earliest tornado in chain)
    - sequence_position: Position in sequence (1 = first, 2 = second, etc.)
    - sequence_count: Total tornadoes in this sequence
    """
    print("\nLinking tornado sequences...")

    # Filter to tornadoes only
    tornado_mask = df['event_type'] == 'Tornado'
    tornado_count = tornado_mask.sum()
    print(f"  Total tornadoes: {tornado_count:,}")

    # Initialize new columns
    df['sequence_id'] = None
    df['sequence_position'] = None
    df['sequence_count'] = None

    if tornado_count == 0:
        return df

    # Get tornado subset with valid coordinates
    tornadoes = df[tornado_mask & df['timestamp'].notna()].copy()
    tornadoes = tornadoes[
        tornadoes['latitude'].notna() &
        tornadoes['longitude'].notna() &
        tornadoes['end_latitude'].notna() &
        tornadoes['end_longitude'].notna()
    ].copy()

    print(f"  Tornadoes with full track data: {len(tornadoes):,}")

    if len(tornadoes) < 2:
        return df

    # Sort by timestamp
    tornadoes = tornadoes.sort_values('timestamp').reset_index(drop=False)
    tornadoes.rename(columns={'index': 'orig_idx'}, inplace=True)

    # Build links: for each tornado, find what follows it
    # links[event_id_a] = event_id_b means A -> B (B follows A)
    links = {}
    time_delta = pd.Timedelta(hours=time_window_hours)

    print(f"  Building link graph (window={time_window_hours}h, distance={distance_km}km)...")

    for i, row_a in tornadoes.iterrows():
        # Only check tornadoes that come after this one (within time window)
        candidates = tornadoes[
            (tornadoes['timestamp'] > row_a['timestamp']) &
            (tornadoes['timestamp'] <= row_a['timestamp'] + time_delta)
        ]

        if len(candidates) == 0:
            continue

        # Check if A's end point is near any candidate's start point
        for j, row_b in candidates.iterrows():
            dist = haversine_km(
                row_a['end_longitude'], row_a['end_latitude'],
                row_b['longitude'], row_b['latitude']
            )

            if dist <= distance_km:
                # A -> B link found
                # Only keep closest link if multiple candidates
                if row_a['event_id'] not in links:
                    links[row_a['event_id']] = row_b['event_id']
                break  # First match wins (closest in time)

    print(f"  Found {len(links):,} direct links")

    if len(links) == 0:
        return df

    # Build reverse lookup
    reverse_links = {v: k for k, v in links.items()}

    # Build sequences by walking chains
    visited = set()
    sequences = []  # List of (sequence_id, [event_ids in order])

    # Create event_id -> row lookup
    event_lookup = tornadoes.set_index('event_id').to_dict('index')

    for event_id in tornadoes['event_id']:
        if event_id in visited:
            continue

        # Walk backwards to find sequence start
        current = event_id
        while current in reverse_links:
            current = reverse_links[current]

        # Now walk forward to build full sequence
        sequence = [current]
        visited.add(current)

        while current in links:
            next_id = links[current]
            sequence.append(next_id)
            visited.add(next_id)
            current = next_id

        # Only keep sequences with 2+ tornadoes
        if len(sequence) >= 2:
            # Use earliest event_id as sequence_id
            seq_id = str(sequence[0])
            sequences.append((seq_id, sequence))

    print(f"  Found {len(sequences):,} sequences with 2+ tornadoes")

    # Count total linked tornadoes
    total_linked = sum(len(s[1]) for s in sequences)
    print(f"  Total linked tornadoes: {total_linked:,}")

    # Apply sequence info to dataframe
    for seq_id, event_ids in sequences:
        seq_count = len(event_ids)
        for position, eid in enumerate(event_ids, 1):
            if eid in event_lookup:
                orig_idx = event_lookup[eid]['orig_idx']
                df.loc[orig_idx, 'sequence_id'] = seq_id
                df.loc[orig_idx, 'sequence_position'] = position
                df.loc[orig_idx, 'sequence_count'] = seq_count

    # Summary
    linked_count = df['sequence_id'].notna().sum()
    print(f"\nTornado sequence linking complete:")
    print(f"  Sequences: {len(sequences):,}")
    print(f"  Linked tornadoes: {linked_count:,} ({linked_count/tornado_count*100:.1f}% of all tornadoes)")

    # Show some example sequences
    if len(sequences) > 0:
        print(f"\n  Example sequences:")
        for seq_id, event_ids in sequences[:3]:
            print(f"    Sequence {seq_id}: {len(event_ids)} tornadoes")

    return df


def save_events_parquet(df):
    """Save events to parquet."""
    print("\nSaving events.parquet...")

    # Round numeric columns for better compression
    df['latitude'] = df['latitude'].round(4)
    df['longitude'] = df['longitude'].round(4)
    df['end_latitude'] = df['end_latitude'].round(4)
    df['end_longitude'] = df['end_longitude'].round(4)
    df['felt_radius_km'] = df['felt_radius_km'].round(2)
    df['damage_radius_km'] = df['damage_radius_km'].round(4)  # More precision for small tornado widths

    # Handle tornado columns (may be NaN)
    df['tornado_length_mi'] = df['tornado_length_mi'].fillna(0).round(1)
    df['tornado_width_yd'] = df['tornado_width_yd'].fillna(0).round(0).astype('Int32')

    # Convert damage columns from string (e.g., "10K", "1.5M") to numeric
    def parse_damage(value):
        if pd.isna(value) or value == 0:
            return 0
        value_str = str(value).upper().strip()
        if not value_str or value_str == '':
            return 0
        if 'K' in value_str:
            num_str = value_str.replace('K', '').strip()
            return float(num_str) * 1000 if num_str else 0
        elif 'M' in value_str:
            num_str = value_str.replace('M', '').strip()
            return float(num_str) * 1000000 if num_str else 0
        elif 'B' in value_str:
            num_str = value_str.replace('B', '').strip()
            return float(num_str) * 1000000000 if num_str else 0
        try:
            return float(value_str)
        except:
            return 0

    df['damage_property'] = df['damage_property'].apply(parse_damage).round(0).astype('Int64')
    df['damage_crops'] = df['damage_crops'].apply(parse_damage).round(0).astype('Int64')

    # Convert casualty columns to int
    df['deaths_direct'] = df['deaths_direct'].fillna(0).astype('Int32')
    df['deaths_indirect'] = df['deaths_indirect'].fillna(0).astype('Int32')
    df['injuries_direct'] = df['injuries_direct'].fillna(0).astype('Int32')
    df['injuries_indirect'] = df['injuries_indirect'].fillna(0).astype('Int32')

    # Handle sequence columns (may be None for non-tornadoes)
    # Convert to string type for parquet compatibility
    df['sequence_id'] = df['sequence_id'].astype('string')
    df['sequence_position'] = df['sequence_position'].astype('Int32')
    df['sequence_count'] = df['sequence_count'].astype('Int32')

    # Define schema (follows unified event schema from DISASTER_DISPLAY.md)
    schema = pa.schema([
        ('event_id', pa.int64()),
        ('timestamp', pa.timestamp('us')),  # Use 'timestamp' per unified schema
        ('event_type', pa.string()),
        ('latitude', pa.float32()),
        ('longitude', pa.float32()),
        ('end_latitude', pa.float32()),      # Tornado track end point
        ('end_longitude', pa.float32()),     # Tornado track end point
        ('felt_radius_km', pa.float32()),    # Broader impact zone
        ('damage_radius_km', pa.float32()),  # Actual damage width
        ('magnitude', pa.float32()),
        ('magnitude_type', pa.string()),
        ('tornado_scale', pa.string()),      # EF0-EF5 or F0-F5
        ('tornado_length_mi', pa.float32()), # Track length in miles
        ('tornado_width_yd', pa.int32()),    # Width in yards
        ('deaths_direct', pa.int32()),
        ('deaths_indirect', pa.int32()),
        ('injuries_direct', pa.int32()),
        ('injuries_indirect', pa.int32()),
        ('damage_property', pa.int64()),
        ('damage_crops', pa.int64()),
        ('location', pa.string()),
        ('loc_id', pa.string()),
        # Tornado sequence columns (linked storm systems)
        ('sequence_id', pa.string()),        # ID of sequence (event_id of first tornado)
        ('sequence_position', pa.int32()),   # Position in sequence (1, 2, 3...)
        ('sequence_count', pa.int32())       # Total tornadoes in sequence
    ])

    # Save
    output_path = OUTPUT_DIR / "events.parquet"
    table = pa.Table.from_pandas(df, schema=schema)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Saved: {size_mb:.2f} MB")
    print(f"  Events: {len(df):,}")

    return output_path


def print_statistics(df):
    """Print summary statistics."""
    print("\n" + "="*80)
    print("STATISTICS")
    print("="*80)

    print(f"\nTotal events with location data: {len(df):,}")
    print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")

    print("\nTop 10 Event Types (by count):")
    top_types = df['event_type'].value_counts().head(10)
    for event_type, count in top_types.items():
        print(f"  {event_type}: {count:,}")

    print("\nCasualties:")
    print(f"  Total deaths (direct): {df['deaths_direct'].sum():,}")
    print(f"  Total deaths (indirect): {df['deaths_indirect'].sum():,}")
    print(f"  Total injuries (direct): {df['injuries_direct'].sum():,}")
    print(f"  Total injuries (indirect): {df['injuries_indirect'].sum():,}")

    print("\nDamage:")
    total_damage = df['damage_property'].sum() + df['damage_crops'].sum()
    print(f"  Total property damage: ${df['damage_property'].sum()/1e9:.2f}B")
    print(f"  Total crop damage: ${df['damage_crops'].sum()/1e9:.2f}B")
    print(f"  Combined total: ${total_damage/1e9:.2f}B")

    print("\nFelt Radius Distribution:")
    print(f"  Min: {df['felt_radius_km'].min():.2f} km")
    print(f"  Max: {df['felt_radius_km'].max():.2f} km")
    print(f"  Mean: {df['felt_radius_km'].mean():.2f} km")
    print(f"  Median: {df['felt_radius_km'].median():.2f} km")

    print("\nDamage Radius Distribution:")
    print(f"  Min: {df['damage_radius_km'].min():.4f} km")
    print(f"  Max: {df['damage_radius_km'].max():.4f} km")
    print(f"  Mean: {df['damage_radius_km'].mean():.4f} km")
    print(f"  Median: {df['damage_radius_km'].median():.4f} km")


def main():
    """Main processing logic."""
    print("="*80)
    print("NOAA Storm Events - Build events.parquet")
    print("="*80)

    # Load county geometry for geocoding
    counties_gdf = load_counties()

    # Process storm details
    events_df = process_storm_details()

    if events_df.empty:
        print("\nERROR: No events with location data found")
        return 1

    # Geocode missing loc_ids (3-pass approach)
    events_df = geocode_missing_events(events_df, counties_gdf)

    # Link tornado sequences (same storm system)
    events_df = link_tornado_sequences(events_df)

    # Save events.parquet
    save_events_parquet(events_df)

    # Print statistics
    print_statistics(events_df)

    print("\n" + "="*80)
    print("COMPLETE!")
    print("="*80)
    print("\nOutput:")
    print("  events.parquet: Individual storm events with location and radius")
    print("\nNext steps:")
    print("  1. Update metadata.json to document events.parquet")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
