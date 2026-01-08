"""
Converter for Smithsonian Global Volcanism Program data.

Creates:
- events.parquet: Individual eruption events with VEI, dates, locations
- global_volcanoes.parquet: Volcano locations for reference

Source: https://volcano.si.edu/
"""

import json
import sys
from pathlib import Path
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_converters.base import save_parquet

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/imported/smithsonian/volcano")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/global/smithsonian_volcanoes")
SOURCE_ID = "smithsonian_volcanoes"


def load_eruptions():
    """Load eruption GeoJSON data."""
    path = RAW_DATA_DIR / "gvp_eruptions.json"
    print(f"Loading eruptions from {path}...")

    with open(path, encoding='utf-8') as f:
        data = json.load(f)

    features = data.get('features', [])
    print(f"  Loaded {len(features)} eruption features")

    return features


def load_volcanoes():
    """Load volcano GeoJSON data for location reference."""
    path = RAW_DATA_DIR / "gvp_volcanoes.json"
    print(f"Loading volcanoes from {path}...")

    with open(path, encoding='utf-8') as f:
        data = json.load(f)

    features = data.get('features', [])
    print(f"  Loaded {len(features)} volcano features")

    # Build lookup by volcano number
    volcano_lookup = {}
    for f in features:
        props = f.get('properties', {})
        geom = f.get('geometry', {})
        coords = geom.get('coordinates', [None, None])

        volcano_lookup[props.get('Volcano_Number')] = {
            'volcano_name': props.get('Volcano_Name'),
            'country': props.get('Country'),
            'region': props.get('Region'),
            'subregion': props.get('Subregion'),
            'volcano_type': props.get('Primary_Volcano_Type'),
            'elevation_m': props.get('Elevation'),
            'latitude': coords[1] if len(coords) > 1 else props.get('Latitude'),
            'longitude': coords[0] if len(coords) > 0 else props.get('Longitude'),
        }

    return volcano_lookup


def process_eruptions(eruption_features, volcano_lookup):
    """Process eruption features into DataFrame."""
    print("\nProcessing eruptions...")

    records = []

    for f in eruption_features:
        props = f.get('properties', {})
        geom = f.get('geometry', {})
        coords = geom.get('coordinates', [None, None])

        volcano_num = props.get('Volcano_Number')
        volcano_info = volcano_lookup.get(volcano_num, {})

        # Get coordinates from eruption geometry or volcano lookup
        lat = coords[1] if coords and len(coords) > 1 and coords[1] else volcano_info.get('latitude')
        lon = coords[0] if coords and len(coords) > 0 and coords[0] else volcano_info.get('longitude')

        # Parse start date
        year = props.get('StartDateYear')
        month = props.get('StartDateMonth') or 1
        day = props.get('StartDateDay') or 1

        # Skip eruptions without valid year
        if year is None:
            continue

        # Build event date (handle negative years for BCE)
        if year >= 0:
            try:
                event_date = f"{year:04d}-{month:02d}-{day:02d}"
            except:
                event_date = f"{year}"
        else:
            event_date = f"{year} BCE"

        record = {
            'event_id': f"eruption_{props.get('Eruption_Number')}",
            'eruption_id': props.get('Eruption_Number'),
            'volcano_number': volcano_num,
            'volcano_name': props.get('Volcano_Name') or volcano_info.get('volcano_name'),
            'VEI': props.get('ExplosivityIndexMax'),
            'activity_type': props.get('Activity_Type'),
            'year': year,
            'start_date': event_date,
            'end_year': props.get('EndDateYear'),
            'latitude': lat,
            'longitude': lon,
            'country': volcano_info.get('country'),
            'region': volcano_info.get('region'),
            'volcano_type': volcano_info.get('volcano_type'),
            'elevation_m': volcano_info.get('elevation_m'),
        }

        records.append(record)

    df = pd.DataFrame(records)

    # Filter to valid coordinates
    df = df.dropna(subset=['latitude', 'longitude'])

    # Convert types
    df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
    df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
    df['VEI'] = pd.to_numeric(df['VEI'], errors='coerce')
    df['year'] = pd.to_numeric(df['year'], errors='coerce').astype('Int64')
    df['elevation_m'] = pd.to_numeric(df['elevation_m'], errors='coerce')

    print(f"  Processed {len(df)} eruptions with valid coordinates")
    print(f"  Year range: {df['year'].min()} to {df['year'].max()}")
    print(f"  VEI distribution:")
    print(df['VEI'].value_counts().sort_index().to_string())

    return df


def create_events_parquet(df):
    """Save events.parquet."""
    print("\nCreating events.parquet...")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "events.parquet"

    # Select and order columns
    cols = [
        'event_id', 'eruption_id', 'volcano_number', 'volcano_name',
        'VEI', 'activity_type', 'year', 'start_date', 'end_year',
        'latitude', 'longitude', 'country', 'region', 'volcano_type', 'elevation_m'
    ]

    df_out = df[cols].copy()
    save_parquet(df_out, output_path, description="volcano eruption events")

    file_size_mb = output_path.stat().st_size / 1e6
    print(f"  Output: {output_path}")
    print(f"  File size: {file_size_mb:.2f} MB")
    print(f"  Row count: {len(df_out)}")

    return df_out


def create_metadata(df):
    """Create metadata.json for the source."""
    print("\nCreating metadata.json...")

    # Calculate stats
    vei_stats = df['VEI'].dropna()
    year_min = int(df['year'].min()) if pd.notna(df['year'].min()) else None
    year_max = int(df['year'].max()) if pd.notna(df['year'].max()) else None

    # Filter to Holocene (last ~11,700 years) for practical display
    holocene_df = df[df['year'] >= -10000]

    metadata = {
        "source_id": SOURCE_ID,
        "source_name": "Smithsonian Global Volcanism Program",
        "source_url": "https://volcano.si.edu/",
        "license": "Public Domain",
        "description": "Global volcanic eruption history from the Smithsonian Institution Global Volcanism Program. Includes VEI (Volcanic Explosivity Index), eruption dates, and volcano locations.",
        "category": "hazard",
        "topic_tags": ["volcano", "eruption", "natural_hazard"],
        "keywords": ["volcano", "eruption", "VEI", "volcanic", "explosivity", "lava", "ash"],
        "last_updated": "2026-01-07",
        "geographic_level": "point",
        "geographic_coverage": {
            "type": "global",
            "countries": list(df['country'].dropna().unique())
        },
        "temporal_coverage": {
            "start": year_min,
            "end": year_max,
            "frequency": "event-based",
            "note": "Eruptions from Holocene epoch to present"
        },
        "row_count": len(df),
        "file_size_mb": round((OUTPUT_DIR / "events.parquet").stat().st_size / 1e6, 2),
        "data_completeness": round(df['VEI'].notna().mean(), 2),

        "metrics": {
            "VEI": {
                "name": "Volcanic Explosivity Index",
                "unit": "index (0-8)",
                "aggregation": "max",
                "description": "Logarithmic scale measuring eruption explosivity",
                "stats": {
                    "min": float(vei_stats.min()) if len(vei_stats) > 0 else None,
                    "max": float(vei_stats.max()) if len(vei_stats) > 0 else None,
                    "median": float(vei_stats.median()) if len(vei_stats) > 0 else None,
                },
                "density": round(df['VEI'].notna().mean(), 2),
                "years": [year_min, year_max],
            }
        },

        "files": {
            "events": {
                "filename": "events.parquet",
                "description": "Individual volcanic eruption events with VEI, dates, and locations",
                "record_type": "event",
                "record_count": len(df),
            }
        },

        "events_file": {
            "path": "events.parquet",
            "row_count": len(df),
            "file_size_mb": round((OUTPUT_DIR / "events.parquet").stat().st_size / 1e6, 2),
        },

        "llm_summary": f"{year_min}-{year_max}. VEI (Volcanic Explosivity Index) for {len(df)} eruptions globally."
    }

    meta_path = OUTPUT_DIR / "metadata.json"
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    print(f"  Output: {meta_path}")

    return metadata


def main():
    print("=" * 60)
    print("SMITHSONIAN VOLCANO CONVERTER")
    print("=" * 60)

    # Check raw data exists
    if not RAW_DATA_DIR.exists():
        print(f"ERROR: Raw data directory not found: {RAW_DATA_DIR}")
        return 1

    # Load data
    volcano_lookup = load_volcanoes()
    eruption_features = load_eruptions()

    # Process eruptions
    df = process_eruptions(eruption_features, volcano_lookup)

    # Create outputs
    create_events_parquet(df)
    create_metadata(df)

    print("\n" + "=" * 60)
    print("COMPLETE!")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
