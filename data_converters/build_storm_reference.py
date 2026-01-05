"""
Build comprehensive storm reference files for NOAA Storm Events.

Creates three reference files:
1. named_storms.json - Named storm metadata with county lists
2. episodes.json - All episode metadata (named and unnamed)
3. storm_to_counties.json - Quick lookup: storm name -> counties

This enables queries like "show me Hurricane Helene" to map to specific counties.
"""
import pandas as pd
import json
from pathlib import Path
from collections import defaultdict
import re

RAW_DIR = Path("C:/Users/bryan/Desktop/county_map_data/Raw data/noaa_storms")
OUTPUT_DIR = Path("C:/Users/bryan/Desktop/county_map_data/data/noaa_storms")


def parse_damage_value(damage_str):
    """Convert NOAA damage string to numeric USD value."""
    if pd.isna(damage_str) or damage_str == '':
        return 0.0

    damage_str = str(damage_str).strip().upper().replace('$', '')

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


def extract_storm_names(narrative):
    """Extract storm names from episode narrative."""
    if pd.isna(narrative):
        return []

    # Patterns for named storms
    patterns = [
        (r'Hurricane\s+([A-Z][a-z]+)', 'Hurricane'),
        (r'Tropical Storm\s+([A-Z][a-z]+)', 'Tropical Storm'),
        (r'Winter Storm\s+([A-Z][a-z]+)', 'Winter Storm'),
    ]

    storms = []
    for pattern, storm_type in patterns:
        matches = re.findall(pattern, narrative)
        for name in matches:
            # Filter out common false positives
            if name not in ['Force', 'Criteria', 'Warning', 'Warnings', 'Watch', 'Wind', 'Season', 'Severity', 'Center']:
                storms.append({'name': name, 'type': storm_type})

    # Deduplicate
    seen = set()
    unique_storms = []
    for storm in storms:
        key = (storm['name'], storm['type'])
        if key not in seen:
            seen.add(key)
            unique_storms.append(storm)

    return unique_storms


def build_episode_data():
    """Process all CSV files and build episode database."""
    print("="*80)
    print("BUILDING STORM REFERENCE DATABASE")
    print("="*80)

    all_episodes = []

    for csv_file in sorted(RAW_DIR.glob("StormEvents_details*.csv")):
        # Extract year from filename: StormEvents_details-ftp_v1.0_d2023_c20251216.csv
        # Need to find '_d' followed by 4 digits
        import re
        year_match = re.search(r'_d(\d{4})_', csv_file.name)
        if year_match:
            year = year_match.group(1)
        else:
            year = "unknown"
        print(f"\nProcessing {year}...")

        df = pd.read_csv(csv_file)
        print(f"  Loaded {len(df):,} events")

        # Parse damage for aggregation
        df['damage_property_numeric'] = df['DAMAGE_PROPERTY'].apply(parse_damage_value)
        df['damage_crops_numeric'] = df['DAMAGE_CROPS'].apply(parse_damage_value)

        # Create loc_id for county mapping
        from convert_noaa_storms import create_loc_id
        df['loc_id'] = df.apply(
            lambda row: create_loc_id(
                row['STATE'],
                row['STATE_FIPS'],
                row['CZ_TYPE'],
                row['CZ_FIPS']
            ),
            axis=1
        )

        # Group by EPISODE_ID
        episodes = df.groupby('EPISODE_ID').agg({
            'YEAR': 'first',
            'MONTH_NAME': 'first',
            'BEGIN_YEARMONTH': 'first',
            'STATE': lambda x: sorted(x.unique()),
            'EVENT_TYPE': lambda x: sorted(x.unique()),
            'CZ_NAME': 'count',  # Number of zones affected
            'loc_id': lambda x: sorted([lid for lid in x.dropna().unique()]),  # County loc_ids
            'EPISODE_NARRATIVE': 'first',
            'EVENT_NARRATIVE': lambda x: ' | '.join(x.dropna().unique()[:3]),  # Sample event narratives
            'DEATHS_DIRECT': 'sum',
            'DEATHS_INDIRECT': 'sum',
            'INJURIES_DIRECT': 'sum',
            'INJURIES_INDIRECT': 'sum',
            'damage_property_numeric': 'sum',
            'damage_crops_numeric': 'sum',
        }).reset_index()

        episodes['year'] = year
        all_episodes.append(episodes)
        print(f"  Extracted {len(episodes):,} unique episodes")

    combined = pd.concat(all_episodes, ignore_index=True)
    print(f"\n  Total episodes across all years: {len(combined):,}")

    return combined


def build_named_storms_reference(episodes_df):
    """Extract named storms and build reference structure."""
    print("\n" + "="*80)
    print("EXTRACTING NAMED STORMS")
    print("="*80)

    # Extract storm names from narratives
    episodes_df['storms'] = episodes_df['EPISODE_NARRATIVE'].apply(extract_storm_names)
    episodes_df['has_named_storm'] = episodes_df['storms'].apply(lambda x: len(x) > 0)

    named_episodes = episodes_df[episodes_df['has_named_storm']].copy()
    print(f"\nFound {len(named_episodes)} episodes with named storms")

    # Build storm catalog
    storm_catalog = {}
    storm_to_episodes = defaultdict(list)

    for _, episode in named_episodes.iterrows():
        for storm_info in episode['storms']:
            storm_name = storm_info['name']
            storm_type = storm_info['type']
            storm_key = f"{storm_type} {storm_name} {episode['year']}"

            # Add episode to this storm's list
            storm_to_episodes[storm_key].append({
                'episode_id': int(episode['EPISODE_ID']),
                'year': episode['year'],
                'month': episode['MONTH_NAME'],
                'states': episode['STATE'],
                'counties': episode['loc_id'],
                'deaths': int(episode['DEATHS_DIRECT'] + episode['DEATHS_INDIRECT']),
                'injuries': int(episode['INJURIES_DIRECT'] + episode['INJURIES_INDIRECT']),
                'damage_property_usd': float(episode['damage_property_numeric']),
                'damage_crops_usd': float(episode['damage_crops_numeric']),
                'event_types': episode['EVENT_TYPE']
            })

    # Consolidate episodes into storms
    for storm_key, episodes_list in storm_to_episodes.items():
        # Aggregate across all episodes for this storm
        all_counties = set()
        all_states = set()
        total_deaths = 0
        total_injuries = 0
        total_damage_property = 0
        total_damage_crops = 0
        episode_ids = []

        for ep in episodes_list:
            all_counties.update(ep['counties'])
            all_states.update(ep['states'])
            total_deaths += ep['deaths']
            total_injuries += ep['injuries']
            total_damage_property += ep['damage_property_usd']
            total_damage_crops += ep['damage_crops_usd']
            episode_ids.append(ep['episode_id'])

        storm_catalog[storm_key] = {
            'name': storm_key.split()[2],  # Extract name
            'type': ' '.join(storm_key.split()[:2]),  # "Hurricane" or "Tropical Storm"
            'year': episodes_list[0]['year'],
            'month': episodes_list[0]['month'],
            'episode_ids': sorted(episode_ids),
            'states_affected': sorted(all_states),
            'counties_affected': sorted(all_counties),
            'total_counties': len(all_counties),
            'total_deaths': total_deaths,
            'total_injuries': total_injuries,
            'damage_property_usd': total_damage_property,
            'damage_crops_usd': total_damage_crops,
            'total_damage_usd': total_damage_property + total_damage_crops
        }

    print(f"Cataloged {len(storm_catalog)} unique named storms")

    return storm_catalog


def save_references(episodes_df, storm_catalog):
    """Save all reference files."""
    print("\n" + "="*80)
    print("SAVING REFERENCE FILES")
    print("="*80)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Named storms catalog
    named_storms_path = OUTPUT_DIR / "named_storms.json"
    with open(named_storms_path, 'w') as f:
        json.dump(storm_catalog, f, indent=2)
    print(f"\n1. Named storms catalog: {named_storms_path}")
    print(f"   {len(storm_catalog)} storms")
    print(f"   Size: {named_storms_path.stat().st_size / 1024:.1f} KB")

    # 2. All episodes (including unnamed) - simplified for lookup
    episodes_dict = {}
    for _, ep in episodes_df.iterrows():
        episodes_dict[int(ep['EPISODE_ID'])] = {
            'year': ep['year'],
            'month': ep['MONTH_NAME'],
            'states': ep['STATE'],
            'event_types': ep['EVENT_TYPE'],
            'counties': ep['loc_id'],
            'total_counties': len(ep['loc_id']),
            'deaths': int(ep['DEATHS_DIRECT'] + ep['DEATHS_INDIRECT']),
            'injuries': int(ep['INJURIES_DIRECT'] + ep['INJURIES_INDIRECT']),
            'damage_usd': float(ep['damage_property_numeric'] + ep['damage_crops_numeric'])
        }

    episodes_path = OUTPUT_DIR / "episodes.json"
    with open(episodes_path, 'w') as f:
        json.dump(episodes_dict, f, indent=2)
    print(f"\n2. All episodes: {episodes_path}")
    print(f"   {len(episodes_dict)} episodes")
    print(f"   Size: {episodes_path.stat().st_size / 1024:.1f} KB")

    # 3. Quick lookup: storm name -> counties (simplified for fast queries)
    quick_lookup = {}
    for storm_key, storm_data in storm_catalog.items():
        quick_lookup[storm_key] = {
            'counties': storm_data['counties_affected'],
            'episode_ids': storm_data['episode_ids'],
            'damage': storm_data['total_damage_usd'],
            'casualties': storm_data['total_deaths'] + storm_data['total_injuries']
        }

    lookup_path = OUTPUT_DIR / "storm_to_counties.json"
    with open(lookup_path, 'w') as f:
        json.dump(quick_lookup, f, indent=2)
    print(f"\n3. Quick lookup table: {lookup_path}")
    print(f"   {len(quick_lookup)} storms")
    print(f"   Size: {lookup_path.stat().st_size / 1024:.1f} KB")

    return named_storms_path, episodes_path, lookup_path


def print_summary(storm_catalog):
    """Print summary of major storms."""
    print("\n" + "="*80)
    print("MAJOR NAMED STORMS (Top 10 by Damage)")
    print("="*80)

    storms_by_damage = sorted(storm_catalog.items(), key=lambda x: x[1]['total_damage_usd'], reverse=True)

    for i, (storm_key, data) in enumerate(storms_by_damage[:10], 1):
        damage_b = data['total_damage_usd'] / 1_000_000_000
        print(f"\n{i}. {storm_key}")
        print(f"   Damage: ${damage_b:.2f}B")
        print(f"   Deaths: {data['total_deaths']}, Injuries: {data['total_injuries']}")
        print(f"   States: {', '.join(data['states_affected'][:5])}{'...' if len(data['states_affected']) > 5 else ''}")
        print(f"   Counties affected: {data['total_counties']}")

    print("\n" + "="*80)
    print("DEADLIEST NAMED STORMS (Top 10 by Deaths)")
    print("="*80)

    storms_by_deaths = sorted(storm_catalog.items(), key=lambda x: x[1]['total_deaths'], reverse=True)

    for i, (storm_key, data) in enumerate(storms_by_deaths[:10], 1):
        print(f"\n{i}. {storm_key}")
        print(f"   Deaths: {data['total_deaths']}, Injuries: {data['total_injuries']}")
        print(f"   Damage: ${data['total_damage_usd'] / 1_000_000_000:.2f}B")
        print(f"   States: {', '.join(data['states_affected'][:5])}")
        print(f"   Counties: {data['total_counties']}")


def main():
    """Main execution."""
    # Build episode database
    episodes_df = build_episode_data()

    # Extract named storms
    storm_catalog = build_named_storms_reference(episodes_df)

    # Save all references
    save_references(episodes_df, storm_catalog)

    # Print summary
    print_summary(storm_catalog)

    print("\n" + "="*80)
    print("REFERENCE BUILD COMPLETE!")
    print("="*80)
    print("\nUsage:")
    print("  - named_storms.json: Full storm metadata with county lists")
    print("  - episodes.json: All episode data (named and unnamed)")
    print("  - storm_to_counties.json: Quick lookup for queries")
    print("\nExample query: 'Hurricane Helene 2024' -> counties_affected")


if __name__ == "__main__":
    main()
