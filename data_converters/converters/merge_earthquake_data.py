"""
Merge multiple earthquake CSV sources into one unified raw data folder.

Combines:
- usgs_earthquakes_global (M4.5+)
- usgs_earthquakes (M2.5-3.5)
- usgs_earthquakes_m35_45 (M3.5-4.5)

Deduplicates by USGS event ID, keeping highest magnitude version.
Output goes to usgs_earthquakes_merged for convert_global_earthquakes.py

Usage:
    python merge_earthquake_data.py
"""
import pandas as pd
from pathlib import Path
import glob

# Source directories
RAW_BASE = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data")
SOURCES = [
    RAW_BASE / "usgs_earthquakes_global",   # M4.5+
    RAW_BASE / "usgs_earthquakes",          # M2.5-3.5
    RAW_BASE / "usgs_earthquakes_m35_45",   # M3.5-4.5 (filling gap)
]
OUTPUT_DIR = RAW_BASE / "usgs_earthquakes_merged"


def merge_sources():
    """Merge all earthquake sources, deduplicate by event ID."""
    print("=" * 60)
    print("Merging Earthquake Data Sources")
    print("=" * 60)

    all_events = []

    for source_dir in SOURCES:
        if not source_dir.exists():
            print(f"\nSkipping {source_dir.name} (not found)")
            continue

        csv_files = list(source_dir.glob("earthquakes_*.csv"))
        print(f"\n{source_dir.name}: {len(csv_files)} files")

        source_events = []
        for csv_path in csv_files:
            try:
                df = pd.read_csv(csv_path)
                source_events.append(df)
            except Exception as e:
                print(f"  Error reading {csv_path.name}: {e}")

        if source_events:
            combined = pd.concat(source_events, ignore_index=True)
            print(f"  Total: {len(combined):,} events, M{combined['mag'].min():.1f}-{combined['mag'].max():.1f}")
            all_events.append(combined)

    if not all_events:
        print("\nNo data found!")
        return

    # Combine all sources
    print("\n" + "=" * 60)
    print("Combining all sources...")
    merged = pd.concat(all_events, ignore_index=True)
    print(f"Total before dedup: {len(merged):,}")

    # Deduplicate by USGS event ID, keeping highest magnitude
    merged = merged.sort_values('mag', ascending=False)
    merged = merged.drop_duplicates(subset=['id'], keep='first')
    merged = merged.sort_values('time')
    print(f"Total after dedup: {len(merged):,}")
    print(f"Magnitude range: M{merged['mag'].min():.1f} to M{merged['mag'].max():.1f}")

    # Split by year and save
    print("\n" + "=" * 60)
    print("Saving merged data by year...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    merged['time'] = pd.to_datetime(merged['time'])
    merged['year'] = merged['time'].dt.year

    for year, group in merged.groupby('year'):
        out_path = OUTPUT_DIR / f"earthquakes_{year}.csv"
        group.drop(columns=['year']).to_csv(out_path, index=False)
        print(f"  {year}: {len(group):,} events")

    print("\n" + "=" * 60)
    print(f"Done! Merged data saved to: {OUTPUT_DIR}")
    print("Run convert_global_earthquakes.py with this folder to rebuild events.parquet")


if __name__ == "__main__":
    merge_sources()
