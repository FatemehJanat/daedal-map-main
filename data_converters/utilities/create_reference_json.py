"""
Create reference.json file for NOAA storms data.

Consolidates named_storms.json and episodes.json into a single reference file
with proper structure for the county-map system.
"""
import json
from pathlib import Path

DATA_DIR = Path("C:/Users/bryan/Desktop/county_map_data/data/noaa_storms")

def create_reference():
    """Create consolidated reference.json file."""

    # Load source files
    with open(DATA_DIR / "named_storms.json") as f:
        named_storms = json.load(f)

    with open(DATA_DIR / "episodes.json") as f:
        episodes = json.load(f)

    # Build reference structure
    reference = {
        "description": "Reference data for NOAA Storm Events Database",
        "coverage": {
            "years": "2023-2025",
            "total_episodes": len(episodes),
            "total_named_storms": len(named_storms)
        },

        # Named storms with county lists
        "named_storms": named_storms,

        # All episodes (for EPISODE_ID lookups)
        "episodes": episodes,

        # Index: storm name -> quick lookup
        "storm_index": {},

        # Index: county -> storms that affected it
        "county_index": {}
    }

    # Build storm index (simplified for quick lookups)
    for storm_key, storm_data in named_storms.items():
        reference["storm_index"][storm_key] = {
            "counties": storm_data["counties_affected"],
            "episode_ids": storm_data["episode_ids"],
            "damage": storm_data["total_damage_usd"],
            "deaths": storm_data["total_deaths"],
            "injuries": storm_data["total_injuries"]
        }

    # Build county index (which storms affected each county)
    county_to_storms = {}
    for storm_key, storm_data in named_storms.items():
        for county in storm_data["counties_affected"]:
            if county not in county_to_storms:
                county_to_storms[county] = []
            county_to_storms[county].append({
                "storm": storm_key,
                "damage": storm_data["total_damage_usd"],
                "deaths": storm_data["total_deaths"]
            })

    # Sort storms by damage for each county
    for county in county_to_storms:
        county_to_storms[county].sort(key=lambda x: x["damage"], reverse=True)

    reference["county_index"] = county_to_storms

    # Add metadata
    reference["metadata"] = {
        "source": "NOAA Storm Events Database",
        "url": "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/",
        "generated": "2026-01-05",
        "coverage_years": [2023, 2024, 2025],
        "notes": [
            "named_storms: Full metadata for all named storms",
            "episodes: All episode data (named and unnamed)",
            "storm_index: Quick lookup by storm name",
            "county_index: Find which storms affected a given county"
        ]
    }

    return reference


def main():
    print("="*80)
    print("Creating reference.json for NOAA Storm Events")
    print("="*80)

    reference = create_reference()

    # Save to reference.json
    output_path = DATA_DIR / "reference.json"
    with open(output_path, 'w') as f:
        json.dump(reference, f, indent=2)

    print(f"\nCreated: {output_path}")
    print(f"Size: {output_path.stat().st_size / 1024 / 1024:.2f} MB")

    print(f"\nContents:")
    print(f"  - {reference['coverage']['total_named_storms']} named storms")
    print(f"  - {reference['coverage']['total_episodes']} total episodes")
    print(f"  - {len(reference['county_index'])} counties in storm index")

    # Sample county lookup
    print(f"\nSample county lookup (USA-FL-12001):")
    if "USA-FL-12001" in reference["county_index"]:
        storms = reference["county_index"]["USA-FL-12001"]
        print(f"  Affected by {len(storms)} named storms:")
        for storm in storms[:3]:
            print(f"    - {storm['storm']}: ${storm['damage']/1e9:.2f}B damage, {storm['deaths']} deaths")

    # Remove redundant files
    print("\n" + "="*80)
    print("Cleaning up redundant files...")
    print("="*80)

    redundant = [
        DATA_DIR / "episode_reference.csv",
        DATA_DIR / "storm_to_counties.json"  # Now in reference.json as storm_index
    ]

    for file_path in redundant:
        if file_path.exists():
            file_path.unlink()
            print(f"  Removed: {file_path.name}")

    print("\nKeeping:")
    print("  - reference.json (consolidated)")
    print("  - named_storms.json (detailed storm data)")
    print("  - episodes.json (all episode data)")

    print("\n" + "="*80)
    print("COMPLETE!")
    print("="*80)


if __name__ == "__main__":
    main()
