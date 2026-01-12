"""
Convert Canadian Tornado Data to parquet format matching USA schema.

Combines two data sources:
1. CNTD (Canadian National Tornado Database) - Environment Canada 1980-2009
2. NTP (Northern Tornadoes Project) - Western University 2017-present

Output files:
1. events.parquet - Individual tornado events matching USA NOAA schema
2. CAN.parquet - Province-year aggregated statistics

Schema matches USA NOAA storms events.parquet for unified visualization.

Usage:
    python convert_canada_tornadoes.py
"""
import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime
import sys

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from data_converters.base import save_parquet
from build.catalog.finalize_source import finalize_source

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/canada_tornadoes")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/CAN/tornadoes")
SOURCE_ID = "canada_tornadoes"

# Province code mappings
# CNTD uses 2-letter abbreviations, NTP uses full names
PROVINCE_TO_LOCID = {
    # CNTD abbreviations
    'AB': 'CAN-AB',
    'BC': 'CAN-BC',
    'MB': 'CAN-MB',
    'NB': 'CAN-NB',
    'NL': 'CAN-NL',
    'NS': 'CAN-NS',
    'NT': 'CAN-NT',
    'NU': 'CAN-NU',
    'ON': 'CAN-ON',
    'PE': 'CAN-PE',
    'QC': 'CAN-QC',
    'SK': 'CAN-SK',
    'YT': 'CAN-YT',
    # NTP full names
    'Alberta': 'CAN-AB',
    'British Columbia': 'CAN-BC',
    'Manitoba': 'CAN-MB',
    'New Brunswick': 'CAN-NB',
    'Newfoundland and Labrador': 'CAN-NL',
    'Nova Scotia': 'CAN-NS',
    'Northwest Territories': 'CAN-NT',
    'Nunavut': 'CAN-NU',
    'Ontario': 'CAN-ON',
    'Prince Edward Island': 'CAN-PE',
    'Quebec': 'CAN-QC',
    'Saskatchewan': 'CAN-SK',
    'Yukon': 'CAN-YT',
}

# EF/F scale mapping for NTP damage field
NTP_DAMAGE_TO_SCALE = {
    'ef0': 'EF0',
    'default_ef0': 'EF0',
    'ef1': 'EF1',
    'ef2': 'EF2',
    'ef3': 'EF3',
    'ef4': 'EF4',
    'ef5': 'EF5',
}


def load_cntd_data():
    """
    Load CNTD (Canadian National Tornado Database) 1980-2009.
    Source: Environment and Climate Change Canada
    """
    print("Loading CNTD data (1980-2009)...")

    csv_path = RAW_DATA_DIR / "GIS_CAN_VerifiedTornadoes_1980-2009.csv"
    if not csv_path.exists():
        print(f"  Warning: CNTD file not found: {csv_path}")
        return pd.DataFrame()

    df = pd.read_csv(csv_path, encoding='latin-1')
    print(f"  Loaded {len(df):,} CNTD records")

    # Parse columns (see earlier analysis for field names)
    # YYYYMMDDHH format: '19800407 0020' = 1980-04-07 00:20
    def parse_cntd_datetime(row):
        try:
            dt_str = str(row.get('YYYYMMDDHH', '')).strip()
            if not dt_str or dt_str == 'nan':
                return None
            # Format: 'YYYYMMDD HHMM'
            parts = dt_str.split()
            date_part = parts[0]
            time_part = parts[1] if len(parts) > 1 else '0000'
            year = int(date_part[:4])
            month = int(date_part[4:6])
            day = int(date_part[6:8])
            hour = int(time_part[:2]) if len(time_part) >= 2 else 0
            minute = int(time_part[2:4]) if len(time_part) >= 4 else 0
            return datetime(year, month, day, hour, minute)
        except:
            return None

    records = []
    for idx, row in df.iterrows():
        # Parse timestamp
        ts = parse_cntd_datetime(row)
        if ts is None:
            continue

        # Get coordinates
        lat = float(row.get('START_LAT_', 0))
        lon = float(row.get('START_LON_', 0))
        if lat == 0 or lon == 0:
            continue

        # End coordinates (-999 means missing)
        end_lat = float(row.get('END_LAT_N', -999))
        end_lon = float(row.get('END_LON_W', -999))
        if end_lat == -999 or end_lat <= 0:
            end_lat = None
            end_lon = None

        # Fujita scale
        fujita = str(row.get('FUJITA', '')).strip()
        tornado_scale = f"F{fujita}" if fujita.isdigit() else None

        # Track length (meters to miles, -999 = missing)
        length_m = float(row.get('LENGTH_M', -999))
        tornado_length_mi = length_m / 1609.34 if length_m > 0 else None

        # Track width (meters to yards, -999 = missing)
        width_m = float(row.get('WIDTH_MAX_', -999))
        tornado_width_yd = int(width_m * 1.09361) if width_m > 0 else None

        # Casualties (-999 = missing)
        deaths = int(row.get('HUMAN_FATA', -999))
        injuries = int(row.get('HUMAN_INJ', -999))
        deaths = deaths if deaths >= 0 else 0
        injuries = injuries if injuries >= 0 else 0

        # Damage (thousands USD, -999 = missing)
        damage_thous = float(row.get('DMG_THOUS', -999))
        damage_property = int(damage_thous * 1000) if damage_thous > 0 else 0

        # Province
        province = str(row.get('PROVINCE', '')).strip()
        loc_id = PROVINCE_TO_LOCID.get(province, f'CAN-{province}')

        # Location description
        location = str(row.get('NEAR_CMMTY', '')).strip()
        if location == 'nan':
            location = None

        records.append({
            'source': 'CNTD',
            'timestamp': ts,
            'latitude': lat,
            'longitude': lon,
            'end_latitude': end_lat,
            'end_longitude': end_lon,
            'tornado_scale': tornado_scale,
            'tornado_length_mi': tornado_length_mi,
            'tornado_width_yd': tornado_width_yd,
            'deaths_direct': deaths,
            'injuries_direct': injuries,
            'damage_property': damage_property,
            'loc_id': loc_id,
            'location': location,
        })

    result = pd.DataFrame(records)
    print(f"  Parsed {len(result):,} valid CNTD tornadoes")
    return result


def load_ntp_data():
    """
    Load NTP (Northern Tornadoes Project) 2017-present.
    Source: Western University / Environment Canada
    """
    print("\nLoading NTP data (2017-present)...")

    geojson_path = RAW_DATA_DIR / "NTP_Events_2017-present.geojson"
    if not geojson_path.exists():
        print(f"  Warning: NTP file not found: {geojson_path}")
        return pd.DataFrame()

    with open(geojson_path, 'r') as f:
        data = json.load(f)

    features = data['features']
    print(f"  Loaded {len(features):,} NTP features")

    # Filter to tornadoes only (tornado_over_land + tornado_over_water)
    tornado_types = ['tornado_over_land', 'tornado_over_water']

    records = []
    for feat in features:
        props = feat['properties']
        geom = feat.get('geometry', {})

        # Filter to tornado types
        event_type = props.get('event_type', '')
        if event_type not in tornado_types:
            continue

        # Get coordinates from geometry (Point)
        coords = geom.get('coordinates', [None, None])
        lon = coords[0]
        lat = coords[1]
        if lat is None or lon is None:
            continue

        # Build timestamp from year/month/day/time fields
        year = props.get('Year')
        month = props.get('month')
        day = props.get('day')
        time_local = props.get('time')  # HHMM format

        try:
            hour = int(time_local) // 100 if time_local else 12
            minute = int(time_local) % 100 if time_local else 0
            ts = datetime(int(year), int(month), int(day), hour, minute)
        except:
            ts = datetime(int(year), 1, 1, 12, 0)  # Fallback

        # EF scale from damage field
        damage = str(props.get('damage', '')).lower()
        tornado_scale = NTP_DAMAGE_TO_SCALE.get(damage, None)

        # Track length (km to miles)
        track_km = props.get('track_length')
        tornado_length_mi = float(track_km) * 0.621371 if track_km else None

        # Track width (meters to yards)
        width_m = props.get('max_path_width')
        tornado_width_yd = int(float(width_m) * 1.09361) if width_m else None

        # Casualties - NTP uses text fields
        fatalities_text = str(props.get('fatalities_text', '')).strip()
        injuries = props.get('injuries')

        # Parse fatalities (might be "0", "1", or descriptive text)
        try:
            deaths = int(fatalities_text) if fatalities_text and fatalities_text.isdigit() else 0
        except:
            deaths = 0

        try:
            injuries_count = int(injuries) if injuries is not None else 0
        except:
            injuries_count = 0

        # Damage cost
        damage_text = str(props.get('damage_cost_text', '')).strip()
        # Parse damage if numeric, otherwise 0
        try:
            if damage_text and damage_text.replace('.', '').isdigit():
                damage_property = int(float(damage_text))
            else:
                damage_property = 0
        except:
            damage_property = 0

        # Province
        province = props.get('province', '')
        loc_id = PROVINCE_TO_LOCID.get(province, 'CAN')

        # Location
        location = props.get('event_name', '')

        records.append({
            'source': 'NTP',
            'timestamp': ts,
            'latitude': lat,
            'longitude': lon,
            'end_latitude': None,  # NTP has point data only
            'end_longitude': None,
            'tornado_scale': tornado_scale,
            'tornado_length_mi': tornado_length_mi,
            'tornado_width_yd': tornado_width_yd,
            'deaths_direct': deaths,
            'injuries_direct': injuries_count,
            'damage_property': damage_property,
            'loc_id': loc_id,
            'location': location,
        })

    result = pd.DataFrame(records)
    print(f"  Parsed {len(result):,} valid NTP tornadoes")
    return result


def create_events_dataframe(cntd_df, ntp_df):
    """
    Combine CNTD and NTP data into unified events DataFrame.
    Schema matches USA NOAA storms events.parquet.
    """
    print("\nCreating unified events DataFrame...")

    # Combine both sources
    combined = pd.concat([cntd_df, ntp_df], ignore_index=True)
    combined = combined.sort_values('timestamp').reset_index(drop=True)

    # Generate unique event IDs (CAN- prefix to distinguish from USA)
    # Use string format to avoid collision with USA integer IDs
    combined['event_id'] = [f"CAN-{100000 + i}" for i in range(len(combined))]

    # Calculate event radius from width (similar to USA logic)
    # tornado_width_yd / 2 converted to km
    def calc_radius(width_yd):
        if pd.isna(width_yd) or width_yd <= 0:
            return 0.5  # Default 500m
        return (width_yd * 0.9144 / 2) / 1000  # yards to km

    combined['event_radius_km'] = combined['tornado_width_yd'].apply(calc_radius)

    # Extract year
    combined['year'] = combined['timestamp'].dt.year

    # Build final events DataFrame matching USA schema exactly
    events = pd.DataFrame({
        'event_id': combined['event_id'],  # String IDs with CAN- prefix
        'timestamp': pd.to_datetime(combined['timestamp']),
        'event_type': 'Tornado',
        'latitude': combined['latitude'].astype('float32'),
        'longitude': combined['longitude'].astype('float32'),
        'end_latitude': combined['end_latitude'].astype('float32'),
        'end_longitude': combined['end_longitude'].astype('float32'),
        'event_radius_km': combined['event_radius_km'].astype('float32'),
        'magnitude': np.float32(0.0),  # Not applicable for tornadoes
        'magnitude_type': None,
        'tornado_scale': combined['tornado_scale'],
        'tornado_length_mi': combined['tornado_length_mi'].astype('float32'),
        'tornado_width_yd': combined['tornado_width_yd'].astype('Int32'),
        'deaths_direct': combined['deaths_direct'].astype('Int32'),
        'deaths_indirect': pd.array([0] * len(combined), dtype='Int32'),
        'injuries_direct': combined['injuries_direct'].astype('Int32'),
        'injuries_indirect': pd.array([0] * len(combined), dtype='Int32'),
        'damage_property': combined['damage_property'].astype('Int64'),
        'damage_crops': pd.array([0] * len(combined), dtype='Int64'),
        'location': combined['location'],
        'loc_id': combined['loc_id'],
        # Sequence fields - would need linking algorithm like USA
        'sequence_id': pd.array([None] * len(combined), dtype='string'),
        'sequence_position': pd.array([None] * len(combined), dtype='Int32'),
        'sequence_count': pd.array([None] * len(combined), dtype='Int32'),
    })

    # Sort by timestamp descending (newest first)
    events = events.sort_values('timestamp', ascending=False).reset_index(drop=True)

    print(f"  Total events: {len(events):,}")
    print(f"  Year range: {events['timestamp'].dt.year.min()}-{events['timestamp'].dt.year.max()}")
    print(f"  With tornado scale: {events['tornado_scale'].notna().sum():,}")

    return events


def create_aggregates(events):
    """Create province-year aggregated statistics."""
    print("\nCreating province-year aggregates...")

    # Add year column for aggregation
    df = events.copy()
    df['year'] = df['timestamp'].dt.year

    # Group by province (loc_id) and year
    agg = df.groupby(['loc_id', 'year']).agg({
        'event_id': 'count',
        'tornado_length_mi': 'sum',
        'deaths_direct': 'sum',
        'injuries_direct': 'sum',
        'damage_property': 'sum',
    }).reset_index()

    agg.columns = ['loc_id', 'year', 'tornado_count', 'total_track_miles',
                   'deaths', 'injuries', 'damage_usd']

    # Round numeric columns
    agg['total_track_miles'] = agg['total_track_miles'].round(1)

    print(f"  Created {len(agg):,} province-year records")
    print(f"  Provinces: {agg['loc_id'].nunique()}")

    return agg


def print_summary(events):
    """Print summary statistics."""
    print("\n" + "=" * 60)
    print("DATA SUMMARY")
    print("=" * 60)

    print(f"\nTotal tornadoes: {len(events):,}")
    print(f"Year range: {events['timestamp'].dt.year.min()}-{events['timestamp'].dt.year.max()}")

    print("\nTornadoes by scale:")
    scale_counts = events['tornado_scale'].value_counts().sort_index()
    for scale, count in scale_counts.items():
        pct = count / len(events) * 100
        print(f"  {scale}: {count:,} ({pct:.1f}%)")

    print("\nTornadoes by province:")
    prov_counts = events['loc_id'].value_counts().head(10)
    for prov, count in prov_counts.items():
        print(f"  {prov}: {count:,}")

    print("\nCasualties:")
    print(f"  Total deaths: {events['deaths_direct'].sum():,}")
    print(f"  Total injuries: {events['injuries_direct'].sum():,}")

    print("\nData quality:")
    print(f"  Has scale: {events['tornado_scale'].notna().sum():,} ({events['tornado_scale'].notna().mean()*100:.1f}%)")
    print(f"  Has track length: {events['tornado_length_mi'].notna().sum():,} ({events['tornado_length_mi'].notna().mean()*100:.1f}%)")
    print(f"  Has end coords: {events['end_latitude'].notna().sum():,} ({events['end_latitude'].notna().mean()*100:.1f}%)")


def main():
    print("=" * 60)
    print("Canadian Tornado Data Converter")
    print("=" * 60)
    print(f"Input: {RAW_DATA_DIR}")
    print(f"Output: {OUTPUT_DIR}")

    # Load both data sources
    cntd_df = load_cntd_data()
    ntp_df = load_ntp_data()

    if len(cntd_df) == 0 and len(ntp_df) == 0:
        print("\nERROR: No data loaded!")
        return 1

    # Create unified events
    events = create_events_dataframe(cntd_df, ntp_df)

    # Create aggregates
    aggregates = create_aggregates(events)

    # Print summary
    print_summary(events)

    # Save outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    events_path = OUTPUT_DIR / "events.parquet"
    save_parquet(events, events_path, description="tornado events")

    agg_path = OUTPUT_DIR / "CAN.parquet"
    save_parquet(aggregates, agg_path, description="province-year aggregates")

    # Finalize
    print("\n" + "=" * 60)
    print("Finalizing source...")
    print("=" * 60)

    try:
        finalize_source(
            parquet_path=str(agg_path),
            source_id=SOURCE_ID,
            events_parquet_path=str(events_path)
        )
    except ValueError as e:
        print(f"  Note: {e}")
        print(f"  Add '{SOURCE_ID}' to source_registry.py to enable auto-finalization")

    print("\n" + "=" * 60)
    print("COMPLETE!")
    print("=" * 60)
    print(f"  Events: {events_path}")
    print(f"  Aggregates: {agg_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
