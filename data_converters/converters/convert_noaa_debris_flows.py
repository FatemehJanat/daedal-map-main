"""
Convert NOAA Storm Events Database debris flows to parquet format.

Input: NOAA Storm Events CSV files (1996-2025)
Output:
  - noaa_debris_flows/events.parquet - Debris flow events with impact data
  - noaa_debris_flows/metadata.json - State coverage and statistics

Usage:
    python convert_noaa_debris_flows.py

Coverage:
- 2,502 debris flow events (1996-2025)
- United States only (including Puerto Rico)
- Detailed event narratives with impact data
- State and county-level precision
"""
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
import json
from datetime import datetime
import glob

# Configuration
INPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/noaa_storms")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/global/noaa_debris_flows")

# US State to ISO3 code mapping (for loc_id)
STATE_TO_ISO3 = {
    'ALABAMA': 'USA', 'ALASKA': 'USA', 'ARIZONA': 'USA', 'ARKANSAS': 'USA',
    'CALIFORNIA': 'USA', 'COLORADO': 'USA', 'CONNECTICUT': 'USA', 'DELAWARE': 'USA',
    'FLORIDA': 'USA', 'GEORGIA': 'USA', 'HAWAII': 'USA', 'IDAHO': 'USA',
    'ILLINOIS': 'USA', 'INDIANA': 'USA', 'IOWA': 'USA', 'KANSAS': 'USA',
    'KENTUCKY': 'USA', 'LOUISIANA': 'USA', 'MAINE': 'USA', 'MARYLAND': 'USA',
    'MASSACHUSETTS': 'USA', 'MICHIGAN': 'USA', 'MINNESOTA': 'USA', 'MISSISSIPPI': 'USA',
    'MISSOURI': 'USA', 'MONTANA': 'USA', 'NEBRASKA': 'USA', 'NEVADA': 'USA',
    'NEW HAMPSHIRE': 'USA', 'NEW JERSEY': 'USA', 'NEW MEXICO': 'USA', 'NEW YORK': 'USA',
    'NORTH CAROLINA': 'USA', 'NORTH DAKOTA': 'USA', 'OHIO': 'USA', 'OKLAHOMA': 'USA',
    'OREGON': 'USA', 'PENNSYLVANIA': 'USA', 'RHODE ISLAND': 'USA', 'SOUTH CAROLINA': 'USA',
    'SOUTH DAKOTA': 'USA', 'TENNESSEE': 'USA', 'TEXAS': 'USA', 'UTAH': 'USA',
    'VERMONT': 'USA', 'VIRGINIA': 'USA', 'WASHINGTON': 'USA', 'WEST VIRGINIA': 'USA',
    'WISCONSIN': 'USA', 'WYOMING': 'USA', 'DISTRICT OF COLUMBIA': 'USA',
    'PUERTO RICO': 'PRI', 'GUAM': 'GUM', 'VIRGIN ISLANDS': 'VIR', 'AMERICAN SAMOA': 'ASM',
}


def load_all_debris_flows():
    """Load all debris flow events from NOAA storm files."""
    print("Loading NOAA Storm Events debris flows...")

    # Find all detail files
    detail_files = sorted(INPUT_DIR.glob("StormEvents_details-ftp_v1.0_d*.csv"))

    if not detail_files:
        print(f"ERROR: No NOAA storm detail files found in {INPUT_DIR}")
        exit(1)

    print(f"  Found {len(detail_files)} storm event files")

    all_debris_flows = []

    for file_path in detail_files:
        try:
            # Read CSV
            df = pd.read_csv(file_path, encoding='latin1', low_memory=False)

            # Filter for debris flows only
            debris_flows = df[df['EVENT_TYPE'] == 'Debris Flow'].copy()

            if len(debris_flows) > 0:
                all_debris_flows.append(debris_flows)
                year = file_path.stem.split('_d')[1].split('_')[0]
                print(f"    {year}: {len(debris_flows)} debris flows")

        except Exception as e:
            print(f"    WARNING: Error reading {file_path.name}: {e}")
            continue

    if not all_debris_flows:
        print("ERROR: No debris flow events found")
        exit(1)

    # Combine all years
    combined_df = pd.concat(all_debris_flows, ignore_index=True)

    print(f"\n  Total debris flow events: {len(combined_df):,}")

    return combined_df


def process_events(df):
    """Process and standardize debris flow data."""
    print("\nProcessing events...")

    # Create timestamp from BEGIN_DATE_TIME
    df['timestamp'] = pd.to_datetime(df['BEGIN_DATE_TIME'], format='%d-%b-%y %H:%M:%S', errors='coerce')
    df['year'] = df['YEAR'].astype('Int64')

    # Parse damage amounts (stored as strings like "5.00K" or "2.5M")
    def parse_damage(damage_str):
        """Parse NOAA damage format (e.g., '5.00K' -> 5000)."""
        if pd.isna(damage_str) or damage_str == '':
            return None

        damage_str = str(damage_str).strip().upper()

        # Remove currency symbols
        damage_str = damage_str.replace('$', '')

        if damage_str.endswith('K'):
            return float(damage_str[:-1]) * 1_000
        elif damage_str.endswith('M'):
            return float(damage_str[:-1]) * 1_000_000
        elif damage_str.endswith('B'):
            return float(damage_str[:-1]) * 1_000_000_000
        else:
            try:
                return float(damage_str)
            except (ValueError, TypeError):
                return None

    df['damage_property_usd'] = df['DAMAGE_PROPERTY'].apply(parse_damage)
    df['damage_crops_usd'] = df['DAMAGE_CROPS'].apply(parse_damage)
    df['damage_total_usd'] = (df['damage_property_usd'].fillna(0) +
                               df['damage_crops_usd'].fillna(0))

    # Create loc_id (country code)
    df['loc_id'] = df['STATE'].map(STATE_TO_ISO3).fillna('USA')

    # Create output dataframe
    events = pd.DataFrame({
        'event_id': 'NOAA_DF_' + df['EVENT_ID'].astype(str),
        'timestamp': df['timestamp'],
        'year': df['year'],
        'month': df['MONTH_NAME'],
        'state': df['STATE'],
        'state_fips': df['STATE_FIPS'].astype('Int32'),
        'county_zone': df['CZ_NAME'],
        'county_fips': df['CZ_FIPS'].astype('Int32'),
        'loc_id': df['loc_id'],
        # Location
        'latitude_begin': pd.to_numeric(df['BEGIN_LAT'], errors='coerce'),
        'longitude_begin': pd.to_numeric(df['BEGIN_LON'], errors='coerce'),
        'latitude_end': pd.to_numeric(df['END_LAT'], errors='coerce'),
        'longitude_end': pd.to_numeric(df['END_LON'], errors='coerce'),
        'begin_location': df['BEGIN_LOCATION'],
        'end_location': df['END_LOCATION'],
        # Impact data
        'deaths_direct': pd.to_numeric(df['DEATHS_DIRECT'], errors='coerce').astype('Int32'),
        'deaths_indirect': pd.to_numeric(df['DEATHS_INDIRECT'], errors='coerce').astype('Int32'),
        'injuries_direct': pd.to_numeric(df['INJURIES_DIRECT'], errors='coerce').astype('Int32'),
        'injuries_indirect': pd.to_numeric(df['INJURIES_INDIRECT'], errors='coerce').astype('Int32'),
        'damage_property_usd': df['damage_property_usd'].astype('Float64'),
        'damage_crops_usd': df['damage_crops_usd'].astype('Float64'),
        'damage_total_usd': df['damage_total_usd'].astype('Float64'),
        # Event details
        'event_narrative': df['EVENT_NARRATIVE'],
        'episode_narrative': df['EPISODE_NARRATIVE'],
        'magnitude': pd.to_numeric(df['MAGNITUDE'], errors='coerce'),
        'magnitude_type': df['MAGNITUDE_TYPE'],
        'source': df['SOURCE'],
        'wfo': df['WFO'],
        'data_source': 'NOAA_STORMS',
    })

    # Calculate total deaths and injuries
    events['deaths'] = (events['deaths_direct'].fillna(0) +
                        events['deaths_indirect'].fillna(0)).astype('Int32')
    events['injuries'] = (events['injuries_direct'].fillna(0) +
                          events['injuries_indirect'].fillna(0)).astype('Int32')

    # Sort by date
    events = events.sort_values('timestamp', ascending=False)

    print(f"  Processed {len(events):,} debris flow events")
    print(f"  States: {events['state'].nunique()}")
    print(f"  Years: {events['year'].min()}-{events['year'].max()}")
    print(f"\n  Impact data:")
    print(f"    Events with deaths: {(events['deaths'] > 0).sum():,} ({(events['deaths'] > 0).sum()/len(events)*100:.1f}%)")
    print(f"    Events with injuries: {(events['injuries'] > 0).sum():,} ({(events['injuries'] > 0).sum()/len(events)*100:.1f}%)")
    print(f"    Total deaths: {events['deaths'].sum():,}")
    print(f"    Total injuries: {events['injuries'].sum():,}")
    print(f"    Events with damage: {(events['damage_total_usd'] > 0).sum():,}")
    print(f"    Total damage: ${events['damage_total_usd'].sum():,.0f}")

    return events


def create_metadata(events):
    """Create metadata including state coverage."""
    print("\nCreating metadata...")

    # State coverage
    state_stats = events.groupby('state').agg({
        'event_id': 'count',
        'deaths': 'sum',
        'injuries': 'sum',
        'damage_total_usd': 'sum',
        'year': ['min', 'max'],
    }).reset_index()

    state_stats.columns = ['state', 'event_count', 'total_deaths',
                           'total_injuries', 'total_damage', 'year_start', 'year_end']

    # Convert to dict for JSON
    states = {}
    for _, row in state_stats.iterrows():
        states[row['state']] = {
            'events': int(row['event_count']),
            'deaths': int(row['total_deaths']) if pd.notna(row['total_deaths']) else 0,
            'injuries': int(row['total_injuries']) if pd.notna(row['total_injuries']) else 0,
            'damage_usd': float(row['total_damage']) if pd.notna(row['total_damage']) else 0,
            'year_range': f"{int(row['year_start'])}-{int(row['year_end'])}"
        }

    metadata = {
        'source': 'NOAA Storm Events Database',
        'source_url': 'https://www.ncdc.noaa.gov/stormevents/',
        'coverage': 'United States (including Puerto Rico) - 1996-2025',
        'event_type': 'Debris Flow',
        'conversion_date': datetime.now().isoformat(),
        'total_events': len(events),
        'total_states': len(states),
        'date_range': {
            'start': int(events['year'].min()),
            'end': int(events['year'].max())
        },
        'impact_summary': {
            'events_with_deaths': int((events['deaths'] > 0).sum()),
            'events_with_injuries': int((events['injuries'] > 0).sum()),
            'total_deaths': int(events['deaths'].sum()),
            'total_injuries': int(events['injuries'].sum()),
            'total_damage_usd': float(events['damage_total_usd'].sum())
        },
        'states': states
    }

    return metadata


def save_parquet(df, output_path):
    """Save dataframe to parquet."""
    print(f"\nSaving to {output_path}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"  Size: {size_mb:.2f} MB, {len(df):,} rows")


def main():
    """Main conversion workflow."""
    print("=" * 70)
    print("NOAA Storm Events Debris Flow Converter")
    print("=" * 70)
    print()

    # Load all debris flows
    df = load_all_debris_flows()

    # Process events
    events = process_events(df)

    # Create metadata
    metadata = create_metadata(events)

    # Save outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    events_path = OUTPUT_DIR / "events.parquet"
    save_parquet(events, events_path)

    metadata_path = OUTPUT_DIR / "metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"\nMetadata saved: {metadata_path}")

    # Print summary
    print("\n" + "=" * 70)
    print("Conversion Summary")
    print("=" * 70)
    print(f"Total debris flows: {len(events):,}")
    print(f"States: {len(metadata['states'])}")
    print(f"Years: {metadata['date_range']['start']}-{metadata['date_range']['end']}")

    print(f"\nTop states by event count:")
    top_states = sorted(metadata['states'].items(),
                       key=lambda x: x[1]['events'], reverse=True)[:10]
    for state, info in top_states:
        print(f"  {state}: {info['events']} events, {info['deaths']} deaths")

    print("\n" + "=" * 70)
    print("COMPLETE!")
    print("=" * 70)

    return events, metadata


if __name__ == "__main__":
    main()
