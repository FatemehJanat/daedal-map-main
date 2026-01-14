"""
Merge NOAA Significant Volcanic Eruptions impact data into Smithsonian volcanoes.

This script:
1. Loads NOAA significant volcano data (200 events with impact data)
2. Loads Smithsonian Global Volcanism Program data (11K+ eruptions)
3. Matches on volcano_number and year
4. Adds impact columns (deaths, injuries, damage, houses destroyed)
5. Saves enriched parquet file

Match strategy:
- Primary: volcano_number (NOAA volcanoLocationNewNum = Smithsonian volcano_number)
- Secondary: year (exact match)
"""

import argparse
import json
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np


def load_noaa_data(noaa_path: Path) -> pd.DataFrame:
    """Load NOAA significant volcano events."""
    print(f"Loading NOAA data from {noaa_path}...")

    with open(noaa_path) as f:
        data = json.load(f)

    events = data['events']
    print(f"  Loaded {len(events)} NOAA significant volcanic eruptions")

    # Convert to DataFrame
    df = pd.DataFrame(events)

    # Select and rename columns in one step
    column_mapping = {
        'id': 'id',
        'volcanoLocationNewNum': 'volcano_number',
        'year': 'year',
        'deathsTotal': 'deaths',
        'injuriesTotal': 'injuries',
        'missingTotal': 'missing',
        'damageMillionsDollarsTotal': 'damage_millions',
        'housesDestroyedTotal': 'houses_destroyed',
        'agent': 'eruption_agent',
        'tsunamiEventId': 'tsunamiEventId',
        'earthquakeEventId': 'earthquakeEventId'
    }

    # Only keep columns that exist in the data
    df = df[[col for col in column_mapping.keys() if col in df.columns]]
    df = df.rename(columns=column_mapping)

    # Convert to proper types (only for columns that exist)
    numeric_cols = ['volcano_number', 'year', 'deaths', 'injuries', 'missing',
                    'damage_millions', 'houses_destroyed']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # Drop rows with no volcano_number or year
    df = df.dropna(subset=['volcano_number', 'year'])

    print(f"  {len(df)} events with valid volcano_number and year")
    if 'deaths' in df.columns:
        print(f"  {(df['deaths'] > 0).sum()} with deaths")
    if 'damage_millions' in df.columns:
        print(f"  {(df['damage_millions'] > 0).sum()} with damage data")

    return df


def load_smithsonian_data(smith_path: Path) -> pd.DataFrame:
    """Load Smithsonian volcano events."""
    print(f"\nLoading Smithsonian data from {smith_path}...")

    df = pd.read_parquet(smith_path)
    print(f"  Loaded {len(df):,} Smithsonian eruption events")
    print(f"  Unique volcanoes: {df['volcano_number'].nunique():,}")
    print(f"  Year range: {df['year'].min():.0f} - {df['year'].max():.0f}")

    return df


def merge_impact_data(smith_df: pd.DataFrame, noaa_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge NOAA impact data into Smithsonian events.

    Match on volcano_number + year.
    """
    print("\nMerging NOAA impact data...")

    # Prepare NOAA data for merge (group by volcano+year to handle duplicates)
    noaa_grouped = noaa_df.groupby(['volcano_number', 'year']).agg({
        'deaths': 'max',  # Take max across any duplicates
        'injuries': 'max',
        'missing': 'max',
        'damage_millions': 'max',
        'houses_destroyed': 'max',
        'eruption_agent': 'first',
        'id': 'first'  # NOAA event ID
    }).reset_index()

    noaa_grouped = noaa_grouped.rename(columns={'id': 'noaa_id'})

    print(f"  NOAA events grouped: {len(noaa_grouped)} unique volcano+year combinations")

    # Merge on volcano_number + year
    result_df = smith_df.merge(
        noaa_grouped,
        on=['volcano_number', 'year'],
        how='left',
        suffixes=('', '_noaa')
    )

    # Convert damage from millions to USD
    result_df['damage_usd'] = result_df['damage_millions'] * 1_000_000
    result_df = result_df.drop(columns=['damage_millions'])

    # Convert to proper dtypes
    result_df['deaths'] = result_df['deaths'].astype('Int32')  # Nullable int
    result_df['injuries'] = result_df['injuries'].astype('Int32')
    result_df['missing'] = result_df['missing'].astype('Int32')
    result_df['damage_usd'] = result_df['damage_usd'].astype('Float64')
    result_df['houses_destroyed'] = result_df['houses_destroyed'].astype('Int32')
    result_df['noaa_id'] = result_df['noaa_id'].astype('Int32')

    # Stats
    matched = result_df['noaa_id'].notna().sum()
    with_deaths = (result_df['deaths'] > 0).sum()
    with_injuries = (result_df['injuries'] > 0).sum()
    with_damage = (result_df['damage_usd'] > 0).sum()

    print(f"\nMerge results:")
    print(f"  Matched events: {matched:,} ({100*matched/len(result_df):.1f}%)")
    print(f"  Events with deaths: {with_deaths:,}")
    print(f"  Events with injuries: {with_injuries:,}")
    print(f"  Events with damage: {with_damage:,}")
    print(f"  Total deaths recorded: {result_df['deaths'].sum():,}")

    return result_df


def update_metadata(metadata_path: Path, stats: dict):
    """Update metadata.json with merge information."""
    print(f"\nUpdating metadata at {metadata_path}...")

    if metadata_path.exists():
        with open(metadata_path) as f:
            metadata = json.load(f)
    else:
        metadata = {}

    # Update source info
    metadata['source_name'] = 'Smithsonian Global Volcanism Program + NOAA Significant Eruptions'
    metadata['secondary_source_url'] = 'https://www.ngdc.noaa.gov/hazel/view/hazards/volcano/search'

    # Add new columns to schema
    if 'columns' not in metadata:
        metadata['columns'] = {}

    metadata['columns'].update({
        'deaths': 'Number of deaths (significant eruptions only)',
        'injuries': 'Number of injuries (significant eruptions only)',
        'missing': 'Number of missing persons (significant eruptions only)',
        'damage_usd': 'Damage in USD (significant eruptions only)',
        'houses_destroyed': 'Houses destroyed (significant eruptions only)',
        'eruption_agent': 'Eruption agent (T=Tephra, L=Lava, P=Pyroclastic, etc.)',
        'noaa_id': 'NOAA significant eruption event ID (if matched)'
    })

    # Add statistics
    metadata['statistics'] = stats
    metadata['generated'] = datetime.now().isoformat()

    # Write back
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    print("  Metadata updated")


def main():
    parser = argparse.ArgumentParser(
        description="Merge NOAA volcano impact data into Smithsonian volcanoes",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("--noaa",
        default="C:/Users/Bryan/Desktop/county-map-data/Raw data/noaa/significant_volcanoes/significant_volcanoes.json",
        help="Path to NOAA significant volcanoes JSON")
    parser.add_argument("--smithsonian",
        default="C:/Users/Bryan/Desktop/county-map-data/global/smithsonian_volcanoes/events.parquet",
        help="Path to Smithsonian volcanoes parquet")
    parser.add_argument("--output",
        help="Output path (default: overwrites smithsonian file)")
    parser.add_argument("--dry-run", action='store_true',
        help="Show merge preview without saving")

    args = parser.parse_args()

    # Load data
    noaa_df = load_noaa_data(Path(args.noaa))
    smith_df = load_smithsonian_data(Path(args.smithsonian))

    # Merge
    result_df = merge_impact_data(smith_df, noaa_df)

    if args.dry_run:
        print("\n=== DRY RUN - No files modified ===")
        print("\nSample merged events with impact data:")
        sample = result_df[result_df['deaths'] > 0][['event_id', 'volcano_name', 'year', 'deaths', 'injuries', 'damage_usd']].head(10)
        print(sample.to_string(index=False))
        return

    # Save
    output_path = Path(args.output) if args.output else Path(args.smithsonian)
    print(f"\nSaving to {output_path}...")
    result_df.to_parquet(output_path, index=False, compression='snappy')

    file_size = output_path.stat().st_size / (1024 * 1024)
    print(f"  Saved {len(result_df):,} events ({file_size:.1f} MB)")

    # Update metadata
    metadata_path = output_path.parent / 'metadata.json'
    stats = {
        'total_events': len(result_df),
        'noaa_matched': int(result_df['noaa_id'].notna().sum()),
        'with_deaths': int((result_df['deaths'] > 0).sum()),
        'with_injuries': int((result_df['injuries'] > 0).sum()),
        'with_damage': int((result_df['damage_usd'] > 0).sum()),
        'total_deaths_recorded': int(result_df['deaths'].sum())
    }
    update_metadata(metadata_path, stats)

    print("\n=== Merge complete! ===")


if __name__ == '__main__':
    main()
