import json
from pathlib import Path

data_dir = Path("C:/Users/bryan/Desktop/county_map_data/data/noaa_storms")

# Load quick lookup
with open(data_dir / "storm_to_counties.json") as f:
    storms = json.load(f)

# Find Helene
helene_keys = [k for k in storms.keys() if 'Helene' in k]

print("HURRICANE HELENE REFERENCE DATA")
print("="*80)

for key in helene_keys:
    data = storms[key]
    print(f"\n{key}:")
    print(f"  Counties affected: {len(data['counties'])}")
    print(f"  Sample counties: {', '.join(data['counties'][:10])}")
    if len(data['counties']) > 10:
        print(f"                   ... and {len(data['counties']) - 10} more")
    print(f"  Episode IDs: {', '.join(map(str, data['episode_ids'][:5]))}...")
    print(f"  Total damage: ${data['damage']/1e9:.2f}B")
    print(f"  Total casualties (deaths + injuries): {data['casualties']}")

# Load full details for one
with open(data_dir / "named_storms.json") as f:
    named = json.load(f)

if helene_keys:
    key = [k for k in helene_keys if 'Hurricane' in k][0]
    full_data = named[key]
    print(f"\n\nFULL DETAILS: {key}")
    print("="*80)
    print(f"States affected: {', '.join(full_data['states_affected'][:10])}")
    print(f"Total deaths: {full_data['total_deaths']}")
    print(f"Total injuries: {full_data['total_injuries']}")
    print(f"Property damage: ${full_data['damage_property_usd']/1e9:.2f}B")
    print(f"Crop damage: ${full_data['damage_crops_usd']/1e9:.2f}B")
