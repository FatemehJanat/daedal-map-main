"""
Find named storms across all NOAA years.
Extracts EPISODE_ID groupings for hurricanes and major events.
"""
import pandas as pd
from pathlib import Path
import re

RAW_DIR = Path("C:/Users/bryan/Desktop/county_map_data/Raw data/noaa_storms")

def extract_storm_names(narrative):
    """Extract potential storm names from narrative text."""
    if pd.isna(narrative):
        return []

    # Common patterns for named storms
    patterns = [
        r'Hurricane\s+([A-Z][a-z]+)',
        r'Tropical Storm\s+([A-Z][a-z]+)',
        r'Winter Storm\s+([A-Z][a-z]+)',
    ]

    names = []
    for pattern in patterns:
        matches = re.findall(pattern, narrative)
        names.extend(matches)

    return list(set(names))

all_episodes = []

for csv_file in sorted(RAW_DIR.glob("StormEvents_details*.csv")):
    year = csv_file.stem.split('_d')[1][:4]
    print(f"\nProcessing {year}...")

    df = pd.read_csv(csv_file)

    # Group by EPISODE_ID to get unique episodes
    episodes = df.groupby('EPISODE_ID').agg({
        'STATE': lambda x: ', '.join(sorted(x.unique())),
        'CZ_NAME': 'count',  # Number of zones affected
        'EVENT_TYPE': lambda x: ', '.join(sorted(x.unique())),
        'EPISODE_NARRATIVE': 'first',
        'YEAR': 'first',
        'MONTH_NAME': 'first',
        'DEATHS_DIRECT': 'sum',
        'INJURIES_DIRECT': 'sum',
        'DAMAGE_PROPERTY': lambda x: x.apply(lambda v: pd.to_numeric(v.replace('K', 'e3').replace('M', 'e6').replace('B', 'e9') if isinstance(v, str) else 0, errors='coerce')).sum()
    }).reset_index()

    episodes['year'] = year
    all_episodes.append(episodes)

combined = pd.concat(all_episodes, ignore_index=True)

# Extract storm names
combined['storm_names'] = combined['EPISODE_NARRATIVE'].apply(extract_storm_names)
combined['has_name'] = combined['storm_names'].apply(lambda x: len(x) > 0)

print("\n" + "="*80)
print("NAMED STORMS FOUND")
print("="*80)

named = combined[combined['has_name']].copy()
named['names_str'] = named['storm_names'].apply(lambda x: ', '.join(x))

print(f"\nTotal named storm episodes: {len(named)}")
print(f"\nUnique storm names: {sorted(set([n for names in named['storm_names'] for n in names]))}")

print("\n" + "-"*80)
print("Major Named Storms (by damage):")
print("-"*80)
top_damage = named.nlargest(10, 'DAMAGE_PROPERTY')[
    ['EPISODE_ID', 'year', 'MONTH_NAME', 'names_str', 'STATE', 'DEATHS_DIRECT', 'DAMAGE_PROPERTY']
]
print(top_damage.to_string(index=False))

print("\n" + "-"*80)
print("Major Named Storms (by casualties):")
print("-"*80)
top_deaths = named[named['DEATHS_DIRECT'] > 0].nlargest(10, 'DEATHS_DIRECT')[
    ['EPISODE_ID', 'year', 'MONTH_NAME', 'names_str', 'STATE', 'DEATHS_DIRECT', 'INJURIES_DIRECT']
]
print(top_deaths.to_string(index=False))

# Save episode reference
print("\n" + "="*80)
print("Saving episode reference...")
print("="*80)

# Create reference table
reference = combined[['EPISODE_ID', 'year', 'MONTH_NAME', 'STATE', 'CZ_NAME', 'EVENT_TYPE',
                      'DEATHS_DIRECT', 'INJURIES_DIRECT', 'DAMAGE_PROPERTY']].copy()
reference['storm_names'] = combined['storm_names'].apply(lambda x: ', '.join(x) if x else '')

output_path = Path("C:/Users/bryan/Desktop/county_map_data/data/noaa_storms/episode_reference.csv")
reference.to_csv(output_path, index=False)
print(f"\nSaved {len(reference)} episodes to: {output_path}")
print(f"File size: {output_path.stat().st_size / 1024:.1f} KB")
