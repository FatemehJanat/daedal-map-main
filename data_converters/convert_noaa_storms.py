"""
Convert NOAA Storm Events data to parquet format.

Input: StormEvents_details CSV files (one per year)
Output: noaa_storms/USA.parquet

Aggregates storm events by county, year, and event type.
Converts CZ_FIPS codes to loc_id format (USA-{state}-{fips}).

Metrics extracted:
- Event counts by type
- Total deaths/injuries
- Total property/crop damage
"""

import pandas as pd
import numpy as np
import os
import json
import sys
from pathlib import Path
from collections import defaultdict

# Add parent dir to path for mapmover imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from mapmover.constants import state_abbreviations

# Configuration
RAW_DATA_DIR = Path("C:/Users/bryan/Desktop/county_map_data/Raw data/noaa_storms")
OUTPUT_DIR = Path("C:/Users/bryan/Desktop/county_map_data/data/noaa_storms")

# Source info for metadata generation
SOURCE_INFO = {
    "source_id": "noaa_storms",
    "source_name": "NOAA Storm Events Database",
    "source_url": "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/",
    "license": "Public Domain (US Government)",
    "description": "Historical storm event data for US counties (1950-2025)",
    "category": "weather",
    "topic_tags": ["weather", "hazards", "climate", "storms"],
    "keywords": ["tornado", "hurricane", "flood", "hail", "thunderstorm", "wildfire", "winter storm"],
    "update_schedule": "monthly",
    "expected_next_update": "ongoing"
}

# State name to abbreviation (inverse of state_abbreviations)
# NOAA data has state names in ALL CAPS, so uppercase the keys
STATE_NAME_TO_ABBREV = {v.upper(): k for k, v in state_abbreviations.items()}
# Add special cases
STATE_NAME_TO_ABBREV.update({
    'DISTRICT OF COLUMBIA': 'DC',
    'PUERTO RICO': 'PR',
    'VIRGIN ISLANDS': 'VI',
    'GUAM': 'GU',
    'AMERICAN SAMOA': 'AS',
})


def state_name_to_abbrev(state_name):
    """Convert state name to abbreviation."""
    if not state_name or pd.isna(state_name):
        return None
    state_upper = str(state_name).upper().strip()
    return STATE_NAME_TO_ABBREV.get(state_upper)


def create_loc_id(state, state_fips, cz_type, cz_fips):
    """
    Create loc_id from NOAA storm event data.

    CZ_TYPE indicates zone type:
    - C = County
    - Z = NWS Public Forecast Zone
    - M = Marine zone

    We only process County (C) type for now.

    NOAA CZ_FIPS is the county FIPS (last 3 digits), not the full 5-digit.
    We need to combine state_fips + cz_fips to get the full FIPS.
    """
    if cz_type != 'C':
        return None  # Skip non-county zones for now

    if pd.isna(state) or pd.isna(cz_fips) or pd.isna(state_fips):
        return None

    state_abbrev = state_name_to_abbrev(state)
    if not state_abbrev:
        return None

    try:
        # Build full FIPS code: state_fips (2 digits) + county_fips (3 digits)
        state_fips_str = str(int(state_fips)).zfill(2)
        county_fips_str = str(int(cz_fips)).zfill(3)
        full_fips_str = state_fips_str + county_fips_str
        full_fips = int(full_fips_str)

        return f'USA-{state_abbrev}-{full_fips}'
    except (ValueError, TypeError):
        return None


def parse_damage(damage_str):
    """
    Parse damage strings like '10.00K', '5.00M' to numeric values.
    K = thousands, M = millions, B = billions
    """
    if pd.isna(damage_str) or damage_str == '':
        return 0.0

    damage_str = str(damage_str).strip().upper()

    # Remove $ if present
    damage_str = damage_str.replace('$', '')

    multiplier = 1
    if damage_str.endswith('K'):
        multiplier = 1_000
        damage_str = damage_str[:-1]
    elif damage_str.endswith('M'):
        multiplier = 1_000_000
        damage_str = damage_str[:-1]
    elif damage_str.endswith('B'):
        multiplier = 1_000_000_000
        damage_str = damage_str[:-1]

    try:
        return float(damage_str) * multiplier
    except ValueError:
        return 0.0


def load_and_process_year(csv_path):
    """Load and process a single year's CSV file."""
    print(f"\nProcessing: {csv_path.name}")

    try:
        df = pd.read_csv(csv_path, low_memory=False)
        print(f"  Loaded {len(df):,} events")

        # Create loc_id
        df['loc_id'] = df.apply(
            lambda row: create_loc_id(
                row['STATE'],
                row['STATE_FIPS'],
                row['CZ_TYPE'],
                row['CZ_FIPS']
            ),
            axis=1
        )

        # Filter to valid county-level records
        df = df[df['loc_id'].notna()].copy()
        print(f"  Valid county records: {len(df):,}")
        print(f"  Unique counties: {df['loc_id'].nunique():,}")

        if len(df) == 0:
            return pd.DataFrame()

        # Parse damage columns
        df['damage_property_usd'] = df['DAMAGE_PROPERTY'].apply(parse_damage)
        df['damage_crops_usd'] = df['DAMAGE_CROPS'].apply(parse_damage)

        # Ensure numeric columns
        for col in ['INJURIES_DIRECT', 'INJURIES_INDIRECT', 'DEATHS_DIRECT', 'DEATHS_INDIRECT']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        # Get year
        df['year'] = df['YEAR']

        # Aggregate by loc_id, year, and event_type
        agg_dict = {
            'EVENT_ID': 'count',  # Count of events
            'INJURIES_DIRECT': 'sum',
            'INJURIES_INDIRECT': 'sum',
            'DEATHS_DIRECT': 'sum',
            'DEATHS_INDIRECT': 'sum',
            'damage_property_usd': 'sum',
            'damage_crops_usd': 'sum',
        }

        # Group by loc_id, year, event_type
        event_type_data = df.groupby(['loc_id', 'year', 'EVENT_TYPE']).agg(agg_dict).reset_index()
        event_type_data.rename(columns={'EVENT_ID': 'event_count'}, inplace=True)

        # Pivot to wide format: one column per event type
        wide_df = event_type_data.pivot_table(
            index=['loc_id', 'year'],
            columns='EVENT_TYPE',
            values='event_count',
            fill_value=0,
            aggfunc='sum'
        )

        # Flatten column names
        wide_df.columns = [f'events_{col.lower().replace(" ", "_").replace("/", "_")}'
                          for col in wide_df.columns]
        wide_df.reset_index(inplace=True)

        # Add total metrics (across all event types)
        total_metrics = df.groupby(['loc_id', 'year']).agg(agg_dict).reset_index()
        total_metrics.rename(columns={
            'EVENT_ID': 'total_events',
            'INJURIES_DIRECT': 'injuries_direct',
            'INJURIES_INDIRECT': 'injuries_indirect',
            'DEATHS_DIRECT': 'deaths_direct',
            'DEATHS_INDIRECT': 'deaths_indirect',
        }, inplace=True)

        # Merge wide format with totals
        result = wide_df.merge(total_metrics, on=['loc_id', 'year'], how='left')

        print(f"  Aggregated to {len(result):,} county-year records")
        print(f"  Event type columns: {len([c for c in result.columns if c.startswith('events_')])}")

        return result

    except Exception as e:
        print(f"  Error: {e}")
        return pd.DataFrame()


def generate_metadata(output_dir, all_columns, year_range):
    """Generate metadata.json for the dataset."""

    # Event type columns
    event_cols = [c for c in all_columns if c.startswith('events_')]

    # Build metrics dict (standard format matching metadata_generator.py)
    metrics = {
        "total_events": {
            "name": "Total Storm Events",
            "description": "Total number of storm events across all types",
            "unit": "count",
            "aggregation": "sum"
        },
        "deaths_direct": {
            "name": "Direct Deaths",
            "description": "Deaths directly caused by storm events",
            "unit": "count",
            "aggregation": "sum"
        },
        "deaths_indirect": {
            "name": "Indirect Deaths",
            "description": "Deaths indirectly caused by storm events",
            "unit": "count",
            "aggregation": "sum"
        },
        "injuries_direct": {
            "name": "Direct Injuries",
            "description": "Injuries directly caused by storm events",
            "unit": "count",
            "aggregation": "sum"
        },
        "injuries_indirect": {
            "name": "Indirect Injuries",
            "description": "Injuries indirectly caused by storm events",
            "unit": "count",
            "aggregation": "sum"
        },
        "damage_property_usd": {
            "name": "Property Damage",
            "description": "Total property damage in USD",
            "unit": "USD",
            "aggregation": "sum"
        },
        "damage_crops_usd": {
            "name": "Crop Damage",
            "description": "Total crop damage in USD",
            "unit": "USD",
            "aggregation": "sum"
        },
    }

    # Add event type metrics
    for col in sorted(event_cols):
        event_name = col.replace('events_', '').replace('_', ' ').title()
        metrics[col] = {
            "name": f"{event_name} Events",
            "description": f"Number of {event_name.lower()} events",
            "unit": "count",
            "aggregation": "sum"
        }

    metadata = {
        "source_id": SOURCE_INFO["source_id"],
        "source_name": SOURCE_INFO["source_name"],
        "description": SOURCE_INFO["description"],

        "source": {
            "name": SOURCE_INFO["source_name"],
            "url": SOURCE_INFO["source_url"],
            "license": SOURCE_INFO["license"],
        },

        "geographic_level": "county",
        "geographic_coverage": {
            "type": "country",
            "countries": 1,
            "country_codes": ["USA"]
        },
        "coverage_description": "USA",

        "temporal_coverage": {
            "start": year_range[0],
            "end": year_range[1],
            "frequency": "annual"
        },

        "metrics": metrics,

        "llm_summary": f"NOAA Storm Events for USA counties, {year_range[0]}-{year_range[1]}. "
                      f"{len(event_cols)} event types with deaths, injuries, damage estimates.",

        "processing": {
            "converter": "data_converters/convert_noaa_storms.py",
            "last_run": pd.Timestamp.now().strftime("%Y-%m-%d"),
            "source_files": "StormEvents_details CSV files"
        }
    }

    # Write metadata.json
    metadata_path = output_dir / "metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    print(f"\nMetadata saved to: {metadata_path}")


def main():
    """Main conversion logic."""
    print("=" * 70)
    print("NOAA Storm Events Converter")
    print("=" * 70)

    # Find all CSV files
    csv_files = sorted(RAW_DATA_DIR.glob("StormEvents_details*.csv"))

    if not csv_files:
        print(f"\nNo CSV files found in: {RAW_DATA_DIR}")
        print("Please download files first using:")
        print("  python data_converters/download_noaa_storms.py")
        return 1

    print(f"\nFound {len(csv_files)} CSV files")

    # Process each year
    all_data = []
    for csv_file in csv_files:
        year_data = load_and_process_year(csv_file)
        if len(year_data) > 0:
            all_data.append(year_data)

    if not all_data:
        print("\nNo data processed!")
        return 1

    # Combine all years
    print("\n" + "=" * 70)
    print("Combining all years...")
    combined = pd.concat(all_data, ignore_index=True)

    # Fill NaN values with 0 for event counts
    event_cols = [c for c in combined.columns if c.startswith('events_')]
    combined[event_cols] = combined[event_cols].fillna(0)

    # Sort by loc_id and year
    combined = combined.sort_values(['loc_id', 'year'])

    print(f"Total records: {len(combined):,}")
    print(f"Counties: {combined['loc_id'].nunique():,}")
    print(f"Years: {combined['year'].min()}-{combined['year'].max()}")
    print(f"Total columns: {len(combined.columns)}")

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Save to parquet
    output_file = OUTPUT_DIR / "USA.parquet"
    combined.to_parquet(output_file, index=False, compression='snappy')

    print(f"\nData saved to: {output_file}")
    print(f"File size: {output_file.stat().st_size / 1024 / 1024:.1f} MB")

    # Generate metadata
    year_range = (int(combined['year'].min()), int(combined['year'].max()))
    generate_metadata(OUTPUT_DIR, combined.columns, year_range)

    # Sample preview
    print("\n" + "=" * 70)
    print("Sample data (first 5 rows):")
    print("=" * 70)
    sample_cols = ['loc_id', 'year', 'total_events', 'deaths_direct', 'injuries_direct',
                   'damage_property_usd'] + event_cols[:3]
    print(combined[sample_cols].head().to_string())

    print("\n" + "=" * 70)
    print("CONVERSION COMPLETE!")
    print("=" * 70)
    print("\nNext steps:")
    print("1. Run catalog builder to add to catalog.json:")
    print("   python build/catalog/catalog_builder.py")
    print("\n2. Test querying in chat interface")

    return 0


if __name__ == "__main__":
    sys.exit(main())
