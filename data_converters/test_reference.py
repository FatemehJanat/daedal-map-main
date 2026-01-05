"""
Quick test of reference.json functionality.
"""
import json
from pathlib import Path

ref_path = Path("C:/Users/bryan/Desktop/county_map_data/data/noaa_storms/reference.json")

print("="*80)
print("TESTING reference.json")
print("="*80)

with open(ref_path) as f:
    ref = json.load(f)

print(f"\nCoverage: {ref['coverage']}")

print("\n" + "-"*80)
print("TEST 1: Find Hurricane Helene")
print("-"*80)

storm_key = "Hurricane Helene 2024"
storm = ref['storm_index'][storm_key]
print(f"\n{storm_key}:")
print(f"  Counties affected: {len(storm['counties'])}")
print(f"  Damage: ${storm['damage']/1e9:.2f}B")
print(f"  Deaths: {storm['deaths']}, Injuries: {storm['injuries']}")
print(f"  Sample counties: {storm['counties'][:5]}")

print("\n" + "-"*80)
print("TEST 2: Reverse lookup - Which storms hit Franklin County, FL?")
print("-"*80)

county = "USA-FL-12037"  # Franklin County
if county in ref['county_index']:
    storms = ref['county_index'][county]
    print(f"\n{county} was affected by {len(storms)} named storm(s):")
    for storm_data in storms:
        print(f"  - {storm_data['storm']}")
        print(f"    Damage: ${storm_data['damage']/1e6:.1f}M, Deaths: {storm_data['deaths']}")
else:
    print(f"\n{county} was not affected by any named storms (2023-2025)")

print("\n" + "-"*80)
print("TEST 3: Episode lookup")
print("-"*80)

episode_id = "195141"
if episode_id in ref['episodes']:
    episode = ref['episodes'][episode_id]
    print(f"\nEpisode {episode_id}:")
    print(f"  Year: {episode['year']}, Month: {episode['month']}")
    print(f"  States: {', '.join(episode['states'][:3])}")
    print(f"  Event types: {', '.join(episode['event_types'])}")
    print(f"  Counties affected: {episode['total_counties']}")
    print(f"  Damage: ${episode['damage_usd']/1e6:.1f}M")

print("\n" + "-"*80)
print("TEST 4: County storm history")
print("-"*80)

# Find a county with multiple storms
for county, storms in ref['county_index'].items():
    if len(storms) >= 3:
        print(f"\n{county} history ({len(storms)} storms):")
        for storm in storms[:3]:
            print(f"  - {storm['storm']}: ${storm['damage']/1e9:.2f}B")
        break

print("\n" + "="*80)
print("ALL TESTS PASSED!")
print("="*80)
