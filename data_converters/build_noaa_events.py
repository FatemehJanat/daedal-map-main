"""
Build NOAA Storm Events events.parquet file.

Creates events.parquet with individual storm events including location data
for map visualization alongside the existing USA.parquet county aggregates.

Input: Raw NOAA storm CSV files
Output: events.parquet with individual storm events

Usage:
    python build_noaa_events.py
"""
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
from datetime import datetime

# Configuration
RAW_DATA_DIR = Path("C:/Users/bryan/Desktop/county_map_data/Raw data/noaa_storms")
OUTPUT_DIR = Path("C:/Users/bryan/Desktop/county_map_data/data/noaa_storms")

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
    '56': 'WY', '72': 'PR'
}


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


def calculate_event_radius_km(event_type, magnitude, tor_length, tor_width):
    """
    Calculate approximate event radius in km for visualization.

    Different event types have different spatial extents.
    """
    event_type_upper = str(event_type).upper() if pd.notna(event_type) else ""

    # Tornado - use reported length/width
    if 'TORNADO' in event_type_upper:
        if pd.notna(tor_length) and pd.notna(tor_width):
            # Radius as average of length and width (converted from miles to km)
            return ((tor_length + tor_width) / 2) * 1.60934
        return 5.0  # Default 5 km for tornadoes without size data

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

    csv_files = sorted(RAW_DATA_DIR.glob("StormEvents_details-*.csv"))
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

            # Parse datetime
            df_with_loc['event_time'] = pd.to_datetime(
                df_with_loc['BEGIN_DATE_TIME'],
                format='%d-%b-%y %H:%M:%S',
                errors='coerce'
            )

            # Calculate event radius
            df_with_loc['event_radius_km'] = df_with_loc.apply(
                lambda row: calculate_event_radius_km(
                    row['EVENT_TYPE'],
                    row.get('MAGNITUDE'),
                    row.get('TOR_LENGTH'),
                    row.get('TOR_WIDTH')
                ),
                axis=1
            )

            # Create loc_id
            df_with_loc['loc_id'] = df_with_loc.apply(
                lambda row: fips_to_loc_id(row['STATE_FIPS'], row['CZ_FIPS']),
                axis=1
            )

            # Select columns for events file
            events = df_with_loc[[
                'EVENT_ID', 'event_time', 'EVENT_TYPE',
                'latitude', 'longitude', 'event_radius_km',
                'MAGNITUDE', 'MAGNITUDE_TYPE',
                'TOR_F_SCALE', 'TOR_LENGTH', 'TOR_WIDTH',
                'DEATHS_DIRECT', 'DEATHS_INDIRECT',
                'INJURIES_DIRECT', 'INJURIES_INDIRECT',
                'DAMAGE_PROPERTY', 'DAMAGE_CROPS',
                'BEGIN_LOCATION', 'loc_id'
            ]].copy()

            # Rename columns
            events.columns = [
                'event_id', 'time', 'event_type',
                'latitude', 'longitude', 'event_radius_km',
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


def save_events_parquet(df):
    """Save events to parquet."""
    print("\nSaving events.parquet...")

    # Round numeric columns for better compression
    df['latitude'] = df['latitude'].round(4)
    df['longitude'] = df['longitude'].round(4)
    df['event_radius_km'] = df['event_radius_km'].round(1)

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

    # Define schema
    schema = pa.schema([
        ('event_id', pa.int64()),
        ('time', pa.timestamp('us')),
        ('event_type', pa.string()),
        ('latitude', pa.float32()),
        ('longitude', pa.float32()),
        ('event_radius_km', pa.float32()),
        ('magnitude', pa.float32()),
        ('magnitude_type', pa.string()),
        ('tornado_scale', pa.string()),
        ('tornado_length_mi', pa.float32()),
        ('tornado_width_yd', pa.int32()),
        ('deaths_direct', pa.int32()),
        ('deaths_indirect', pa.int32()),
        ('injuries_direct', pa.int32()),
        ('injuries_indirect', pa.int32()),
        ('damage_property', pa.int64()),
        ('damage_crops', pa.int64()),
        ('location', pa.string()),
        ('loc_id', pa.string())
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
    print(f"Date range: {df['time'].min()} to {df['time'].max()}")

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

    print("\nEvent Radius Distribution:")
    print(f"  Min: {df['event_radius_km'].min():.1f} km")
    print(f"  Max: {df['event_radius_km'].max():.1f} km")
    print(f"  Mean: {df['event_radius_km'].mean():.1f} km")
    print(f"  Median: {df['event_radius_km'].median():.1f} km")


def main():
    """Main processing logic."""
    print("="*80)
    print("NOAA Storm Events - Build events.parquet")
    print("="*80)

    # Process storm details
    events_df = process_storm_details()

    if events_df.empty:
        print("\nERROR: No events with location data found")
        return 1

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
