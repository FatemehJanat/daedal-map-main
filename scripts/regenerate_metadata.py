"""
Regenerate metadata.json for all data sources.

Usage:
    python scripts/regenerate_metadata.py              # All sources
    python scripts/regenerate_metadata.py owid_co2     # Single source
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from mapmover.metadata_generator import generate_metadata

DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/data")

# Source configurations (manual info that can't be auto-detected)
SOURCES = {
    "owid_co2": {
        "source_name": "Our World in Data",
        "source_url": "https://github.com/owid/co2-data",
        "license": "CC-BY",
        "description": "CO2 and greenhouse gas emissions, energy, and economic data",
        "category": "environmental",
        "topic_tags": ["climate", "emissions", "environment", "energy", "economics"],
        "keywords": ["carbon", "pollution", "greenhouse", "global warming", "climate change"],
        "update_schedule": "annual",
        "expected_next_update": "2025-06"
    },
    "who_health": {
        "source_name": "World Health Organization",
        "source_url": "https://www.who.int/data/gho",
        "license": "CC BY-NC-SA 3.0 IGO",
        "description": "WHO Global Health Observatory indicators",
        "category": "health",
        "topic_tags": ["health", "mortality", "disease", "healthcare"],
        "keywords": ["life expectancy", "mortality", "disease", "medical", "health"],
        "update_schedule": "annual",
        "expected_next_update": "2025-06"
    },
    "imf_bop": {
        "source_name": "International Monetary Fund",
        "source_url": "https://data.imf.org",
        "license": "IMF Data Terms",
        "description": "Balance of payments and trade data",
        "category": "economic",
        "topic_tags": ["economics", "trade", "finance"],
        "keywords": ["trade", "exports", "imports", "balance of payments", "finance"],
        "update_schedule": "annual",
        "expected_next_update": "2025-04"
    },
    "census_population": {
        "source_name": "US Census Bureau",
        "source_url": "https://www.census.gov",
        "license": "Public Domain",
        "description": "US county-level population estimates",
        "category": "demographic",
        "topic_tags": ["demographics", "population"],
        "keywords": ["population", "people", "residents", "census"],
        "update_schedule": "annual",
        "expected_next_update": "2025-03"
    },
    "census_agesex": {
        "source_name": "US Census Bureau",
        "source_url": "https://www.census.gov",
        "license": "Public Domain",
        "description": "US county-level age and sex demographics",
        "category": "demographic",
        "topic_tags": ["demographics", "age", "population"],
        "keywords": ["age", "median age", "demographics", "census"],
        "update_schedule": "annual",
        "expected_next_update": "2025-03"
    },
    "census_demographics": {
        "source_name": "US Census Bureau",
        "source_url": "https://www.census.gov",
        "license": "Public Domain",
        "description": "US county-level race and ethnicity demographics",
        "category": "demographic",
        "topic_tags": ["demographics", "race", "ethnicity"],
        "keywords": ["race", "ethnicity", "demographics", "census"],
        "update_schedule": "annual",
        "expected_next_update": "2025-03"
    }
}


def regenerate_source(source_id: str):
    """Regenerate metadata for a single source."""
    source_dir = DATA_DIR / source_id

    if not source_dir.exists():
        print(f"ERROR: {source_dir} not found")
        return

    # Find parquet file
    parquets = list(source_dir.glob("*.parquet"))
    if not parquets:
        print(f"ERROR: No parquet files in {source_dir}")
        return

    parquet_path = parquets[0]
    for name in ["all_countries.parquet", "USA.parquet"]:
        if (source_dir / name).exists():
            parquet_path = source_dir / name
            break

    # Get source config
    source_info = SOURCES.get(source_id, {}).copy()
    source_info["source_id"] = source_id
    if "source_name" not in source_info:
        source_info["source_name"] = source_id.replace("_", " ").title()

    print(f"Processing {source_id}...")
    print(f"  Parquet: {parquet_path.name}")

    # Generate metadata
    metadata = generate_metadata(str(parquet_path), source_info)

    # Save
    meta_path = source_dir / "metadata.json"
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    print(f"  Saved: {meta_path}")
    print(f"  Rows: {metadata['row_count']}, Years: {metadata['temporal_coverage']}")


def main():
    sources = sys.argv[1:] if len(sys.argv) > 1 else list(SOURCES.keys())

    for source_id in sources:
        regenerate_source(source_id)

    print("\nDone!")


if __name__ == "__main__":
    main()
