"""
Convert NASA FIRMS active fire data to parquet format.

NASA FIRMS (Fire Information for Resource Management System) provides
near-real-time satellite fire detection globally.

Creates output file:
- events.parquet - Individual fire detections with lat/lon/FRP

Data Sources:
- MODIS: 1km resolution, 2000-present
- VIIRS S-NPP: 375m resolution, 2012-present
- VIIRS NOAA-20: 375m resolution, 2018-present
- VIIRS NOAA-21: 375m resolution, 2024-present

Uses water body assignment for ocean fires (oil rigs, ships, etc.)

Usage:
    python convert_nasa_firms.py
"""
import pandas as pd
import numpy as np
import sys
from pathlib import Path
from datetime import datetime
import json

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from data_converters.base import (
    get_water_body_loc_id,
    save_parquet,
)

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/nasa_firms")
NASA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/nasa")  # Existing data location
ARCHIVE_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/nasa_firms/archive")
IMPORTED_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/imported/nasa_firms")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/global/nasa_firms")
SOURCE_ID = "nasa_firms"

# Confidence level mapping
CONFIDENCE_MAP = {
    'l': 'low',
    'n': 'nominal',
    'h': 'high',
    'low': 'low',
    'nominal': 'nominal',
    'high': 'high'
}


def get_source_files():
    """Get all CSV files from raw and archive directories."""
    files = []

    # Check raw directory for NRT files
    if RAW_DATA_DIR.exists():
        files.extend(RAW_DATA_DIR.glob("firms_*.csv"))

    # Check archive directory
    if ARCHIVE_DIR.exists():
        files.extend(ARCHIVE_DIR.glob("*.csv"))

    # Check imported directory
    if IMPORTED_DIR.exists():
        files.extend(IMPORTED_DIR.glob("*.csv"))

    return list(files)


def load_firms_data(files):
    """Load and combine all FIRMS CSV files."""
    print("\nLoading FIRMS data...")

    all_dfs = []

    for file_path in files:
        try:
            df = pd.read_csv(file_path, low_memory=False)
            df['source_file'] = file_path.name
            all_dfs.append(df)
            print(f"  {file_path.name}: {len(df):,} rows")
        except Exception as e:
            print(f"  ERROR loading {file_path.name}: {e}")

    if not all_dfs:
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    print(f"\nTotal fire detections: {len(combined):,}")

    return combined


def normalize_columns(df):
    """Normalize column names across different FIRMS formats."""
    # FIRMS column names vary slightly between sensors
    # Standardize to lowercase
    df.columns = df.columns.str.lower()

    # Common mappings
    col_map = {
        'lat': 'latitude',
        'lon': 'longitude',
        'long': 'longitude',
        'bright_ti4': 'brightness_ti4',
        'bright_ti5': 'brightness_ti5',
        'acq_date': 'date',
        'acq_time': 'time',
    }

    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    return df


def parse_timestamps(df):
    """Parse date and time columns into timestamp."""
    print("\nParsing timestamps...")

    # FIRMS typically has acq_date (YYYY-MM-DD) and acq_time (HHMM)
    if 'date' in df.columns and 'time' in df.columns:
        # Combine date and time
        df['time_str'] = df['time'].apply(
            lambda x: f"{int(x):04d}" if pd.notna(x) else "0000"
        )
        df['timestamp'] = pd.to_datetime(
            df['date'].astype(str) + ' ' + df['time_str'],
            format='%Y-%m-%d %H%M',
            errors='coerce'
        )
        df = df.drop(columns=['time_str'])
    elif 'date' in df.columns:
        df['timestamp'] = pd.to_datetime(df['date'], errors='coerce')
    else:
        print("  WARNING: No date column found")
        df['timestamp'] = pd.NaT

    # Extract year for filtering
    df['year'] = df['timestamp'].dt.year

    valid_timestamps = df['timestamp'].notna().sum()
    print(f"  Valid timestamps: {valid_timestamps:,} ({valid_timestamps/len(df)*100:.1f}%)")

    return df


def process_fires(df):
    """Process fire detections into standard event format."""
    print("\nProcessing fire detections...")

    df = normalize_columns(df)
    df = parse_timestamps(df)

    # Filter to valid coordinates
    df = df.dropna(subset=['latitude', 'longitude'])
    print(f"  With valid coordinates: {len(df):,}")

    # Generate unique event IDs
    # Format: F{YYYYMMDD}{HHMM}{lat*100}{lon*100}
    def make_event_id(row):
        try:
            date_part = row['timestamp'].strftime('%Y%m%d%H%M') if pd.notna(row['timestamp']) else '0'
            lat_part = f"{abs(row['latitude']*100):.0f}"
            lon_part = f"{abs(row['longitude']*100):.0f}"
            return f"F{date_part}_{lat_part}_{lon_part}"
        except:
            return f"F{np.random.randint(1e9)}"

    df['event_id'] = df.apply(make_event_id, axis=1)

    # Determine sensor type
    if 'satellite' in df.columns:
        df['sensor'] = df['satellite'].map({
            'N': 'VIIRS_SNPP',
            'N20': 'VIIRS_NOAA20',
            'N21': 'VIIRS_NOAA21',
            'T': 'MODIS_TERRA',
            'A': 'MODIS_AQUA'
        }).fillna('UNKNOWN')
    else:
        df['sensor'] = 'UNKNOWN'

    # Normalize confidence
    if 'confidence' in df.columns:
        df['confidence'] = df['confidence'].astype(str).str.lower().map(CONFIDENCE_MAP).fillna('nominal')
    else:
        df['confidence'] = 'nominal'

    # Round coordinates
    df['latitude'] = df['latitude'].round(4)
    df['longitude'] = df['longitude'].round(4)

    # Assign water body loc_id for ocean detections
    print("  Assigning loc_ids (water bodies for ocean fires)...")

    def get_loc_id(row):
        # Simple check - if lat/lon is far from land, assign water body
        # For now, just assign water body codes for obvious ocean areas
        return get_water_body_loc_id(row['latitude'], row['longitude'], region='global')

    # Apply to a sample first to check
    sample = df.head(1000).copy()
    sample['loc_id'] = sample.apply(get_loc_id, axis=1)

    # Full assignment
    df['loc_id'] = df.apply(get_loc_id, axis=1)

    land_count = (df['loc_id'].isna() | ~df['loc_id'].str.startswith('X')).sum()
    water_count = df['loc_id'].str.startswith('X', na=False).sum()
    print(f"  Land detections: {land_count:,}")
    print(f"  Water/ocean detections: {water_count:,}")

    return df


def create_events_dataframe(df):
    """Create standardized events DataFrame."""
    print("\nCreating events parquet...")

    # Select and order columns per unified event schema
    events = pd.DataFrame({
        'event_id': df['event_id'],
        'timestamp': df['timestamp'],
        'year': df['year'],
        'latitude': df['latitude'],
        'longitude': df['longitude'],
        'event_type': 'fire',
        'loc_id': df['loc_id'],
        'frp': df.get('frp'),  # Fire Radiative Power (MW)
        'brightness': df.get('brightness') if 'brightness' in df.columns else df.get('brightness_ti4'),
        'confidence': df['confidence'],
        'sensor': df['sensor'],
        'daynight': df.get('daynight'),
    })

    # Round FRP
    if 'frp' in events.columns:
        events['frp'] = events['frp'].round(1)

    print(f"  Event records: {len(events):,}")

    # Print sensor breakdown
    if 'sensor' in events.columns:
        print("\n  Detections by sensor:")
        for sensor, count in events['sensor'].value_counts().items():
            print(f"    {sensor}: {count:,}")

    return events


def print_statistics(events_df):
    """Print summary statistics."""
    print("\n" + "="*60)
    print("STATISTICS")
    print("="*60)

    print(f"\nTotal fire detections: {len(events_df):,}")

    if 'year' in events_df.columns:
        year_counts = events_df['year'].value_counts().sort_index()
        print(f"Year range: {year_counts.index.min()}-{year_counts.index.max()}")

        print("\nDetections by year (last 10):")
        for year, count in year_counts.tail(10).items():
            print(f"  {int(year)}: {count:,}")

    if 'frp' in events_df.columns and events_df['frp'].notna().sum() > 0:
        print(f"\nFire Radiative Power (MW):")
        print(f"  Mean: {events_df['frp'].mean():.1f}")
        print(f"  Max: {events_df['frp'].max():.1f}")
        print(f"  With FRP data: {events_df['frp'].notna().sum():,}")

    if 'confidence' in events_df.columns:
        print("\nBy confidence level:")
        for conf, count in events_df['confidence'].value_counts().items():
            print(f"  {conf}: {count:,}")

    if 'daynight' in events_df.columns:
        print("\nBy time of day:")
        for dn, count in events_df['daynight'].value_counts().items():
            label = 'Day' if dn == 'D' else 'Night' if dn == 'N' else dn
            print(f"  {label}: {count:,}")


def generate_metadata(events_df):
    """Generate metadata.json for the dataset."""
    print("\nGenerating metadata.json...")

    # Year range
    if 'year' in events_df.columns:
        year_valid = events_df['year'].dropna()
        min_year = int(year_valid.min()) if len(year_valid) > 0 else 2000
        max_year = int(year_valid.max()) if len(year_valid) > 0 else datetime.now().year
    else:
        min_year = 2000
        max_year = datetime.now().year

    metadata = {
        "source_id": SOURCE_ID,
        "source_name": "NASA FIRMS - Fire Information for Resource Management System",
        "source_url": "https://firms.modaps.eosdis.nasa.gov/",
        "license": "Public Domain (U.S. Government / NASA)",
        "description": f"Global satellite fire detections from MODIS/VIIRS sensors ({min_year}-{max_year})",

        "geographic_level": "global",
        "geographic_coverage": {
            "type": "global",
            "description": "Worldwide fire detections from polar-orbiting satellites"
        },

        "temporal_coverage": {
            "start": min_year,
            "end": max_year,
            "frequency": "sub-daily (multiple satellite passes per day)"
        },

        "files": {
            "events": {
                "filename": "events.parquet",
                "description": "Individual fire detections with coordinates and intensity",
                "record_type": "event",
                "record_count": len(events_df)
            }
        },

        "metrics": {
            "frp": {
                "name": "Fire Radiative Power",
                "description": "Measure of fire intensity in megawatts",
                "unit": "MW",
                "file": "events.parquet"
            },
            "brightness": {
                "name": "Brightness Temperature",
                "description": "Thermal brightness in Kelvin",
                "unit": "K",
                "file": "events.parquet"
            },
            "confidence": {
                "name": "Detection Confidence",
                "description": "Detection confidence level: low, nominal, high",
                "unit": "category",
                "file": "events.parquet"
            }
        },

        "sensors": {
            "MODIS": {
                "resolution": "1km",
                "satellites": ["Terra", "Aqua"],
                "start_year": 2000
            },
            "VIIRS": {
                "resolution": "375m",
                "satellites": ["S-NPP", "NOAA-20", "NOAA-21"],
                "start_year": 2012
            }
        },

        "llm_summary": f"NASA FIRMS global active fire data, {min_year}-{max_year}. "
                      f"{len(events_df):,} fire detections from MODIS/VIIRS satellites. "
                      f"375m (VIIRS) and 1km (MODIS) resolution. "
                      f"Near real-time updates available.",

        "processing": {
            "converter": "data_converters/converters/convert_nasa_firms.py",
            "last_run": pd.Timestamp.now().strftime("%Y-%m-%d")
        }
    }

    # Write metadata.json
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    metadata_path = OUTPUT_DIR / "metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    print(f"  Saved: {metadata_path}")


def main():
    """Main conversion logic."""
    print("="*60)
    print("NASA FIRMS Active Fire Data Converter")
    print("="*60)

    # Find source files
    files = get_source_files()

    if not files:
        print("\nNo FIRMS data files found!")
        print(f"\nLooked in:")
        print(f"  {RAW_DATA_DIR}")
        print(f"  {ARCHIVE_DIR}")
        print(f"  {IMPORTED_DIR}")
        print("\nTo download data, run:")
        print("  python data_converters/downloaders/download_nasa_firms.py --nrt --days 7 --key YOUR_KEY")
        print("\nFor historical data (archive), visit:")
        print("  https://firms.modaps.eosdis.nasa.gov/download/")
        return 1

    print(f"\nFound {len(files)} source file(s)")

    # Load data
    df = load_firms_data(files)

    if df.empty:
        print("\nERROR: No data loaded from files")
        return 1

    # Process fires
    fires_df = process_fires(df)

    # Create events DataFrame
    events_df = create_events_dataframe(fires_df)

    # Print statistics
    print_statistics(events_df)

    # Save outputs
    print("\n" + "="*60)
    print("Saving outputs...")
    print("="*60)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    events_path = OUTPUT_DIR / "events.parquet"
    save_parquet(events_df, events_path, description="fire detections")

    # Generate metadata
    generate_metadata(events_df)

    print("\n" + "="*60)
    print("COMPLETE!")
    print("="*60)
    print(f"\nOutput: {OUTPUT_DIR}")
    print(f"  events.parquet: {len(events_df):,} fire detections")

    return 0


if __name__ == "__main__":
    sys.exit(main())
