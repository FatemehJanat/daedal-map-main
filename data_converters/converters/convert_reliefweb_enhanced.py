"""
Convert ReliefWeb Disasters List to parquet format WITH IMPACT DATA EXTRACTION.

This enhanced version extracts impact numbers (deaths, injuries, displaced, damage)
from the description field using pattern matching.

Input: CSV from ReliefWeb API export
Output:
  - reliefweb_disasters/events.parquet - Individual disaster events with impact data
  - reliefweb_disasters/GLOBAL.parquet - Annual aggregates by country

Usage:
    python convert_reliefweb_enhanced.py

Dataset contains global disaster events from OCHA ReliefWeb:
- 18,000+ disasters from 1981-2025
- Types: Floods, Cyclones, Earthquakes, Epidemics, Droughts, etc.
- Country-level with coordinates
- GLIDE numbers for cross-referencing
- Impact data extracted from descriptions
"""
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
import sys
import re

# Add build path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from build.catalog.finalize_source import finalize_source

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/reliefweb")
IMPORTED_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/imported/reliefweb")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/global/reliefweb_disasters")


def get_input_file():
    """Get input file - check raw first, then imported."""
    raw_file = RAW_DATA_DIR / "reliefweb-disasters-list.csv"
    imported_file = IMPORTED_DIR / "reliefweb-disasters-list.csv"
    if raw_file.exists():
        return raw_file
    elif imported_file.exists():
        print(f"  Note: Using imported data from {IMPORTED_DIR}")
        return imported_file
    return raw_file


def move_to_imported():
    """Move processed raw files to imported folder."""
    import shutil
    raw_file = RAW_DATA_DIR / "reliefweb-disasters-list.csv"
    if raw_file.exists():
        IMPORTED_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(raw_file), str(IMPORTED_DIR / raw_file.name))
        print(f"  Moved files to {IMPORTED_DIR}")

# Disaster type code mapping (for standardization)
DISASTER_TYPE_MAP = {
    'FL': 'flood',
    'TC': 'tropical_cyclone',
    'EQ': 'earthquake',
    'EP': 'epidemic',
    'DR': 'drought',
    'ST': 'severe_storm',
    'FF': 'flash_flood',
    'VO': 'volcano',
    'CW': 'cold_wave',
    'LS': 'landslide',
    'WF': 'wildfire',
    'AC': 'technological',
    'MS': 'mudslide',
    'AV': 'avalanche',
    'TS': 'tsunami',
    'HT': 'heat_wave',
    'CE': 'complex_emergency',
    'IN': 'insect_infestation',
    'OT': 'other',
}


def extract_number(text, patterns):
    """Extract a number from text using multiple regex patterns."""
    if pd.isna(text):
        return None

    text = str(text).lower()

    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            # Get all numbers found
            numbers = []
            for match in matches:
                # Extract the numeric part
                if isinstance(match, tuple):
                    num_str = match[0]  # First capture group
                else:
                    num_str = match

                # Remove commas and convert to int
                num_str = num_str.replace(',', '').replace('.', '')
                try:
                    numbers.append(int(num_str))
                except ValueError:
                    continue

            # Return the maximum number found (often most comprehensive total)
            if numbers:
                return max(numbers)

    return None


def extract_impact_data(description):
    """Extract impact numbers from ReliefWeb description text.

    Returns dict with: deaths, injuries, missing, displaced, affected, houses_destroyed, damage_usd
    """
    if pd.isna(description):
        return {}

    impact = {}

    # Deaths patterns
    death_patterns = [
        r'(\d+[\d,]*)\s+(?:people\s+)?(?:have\s+)?died',
        r'(\d+[\d,]*)\s+deaths?',
        r'(\d+[\d,]*)\s+(?:people\s+)?(?:have\s+been\s+)?killed',
        r'(\d+[\d,]*)\s+fatalities',
        r'(\d+[\d,]*)\s+dead',
        r'death\s+toll\s+(?:of\s+)?(\d+[\d,]*)',
        r'killed\s+(\d+[\d,]*)',
        r'at\s+least\s+(\d+[\d,]*)\s+(?:people\s+)?died',
    ]
    deaths = extract_number(description, death_patterns)
    if deaths is not None:
        impact['deaths'] = deaths

    # Injuries patterns
    injury_patterns = [
        r'(\d+[\d,]*)\s+(?:people\s+)?injured',
        r'(\d+[\d,]*)\s+(?:people\s+)?wounded',
        r'(\d+[\d,]*)\s+injuries',
    ]
    injuries = extract_number(description, injury_patterns)
    if injuries is not None:
        impact['injuries'] = injuries

    # Missing patterns
    missing_patterns = [
        r'(\d+[\d,]*)\s+missing',
        r'(\d+[\d,]*)\s+(?:people\s+)?unaccounted',
        r'(\d+[\d,]*)\s+(?:remain\s+)?disappeared',
    ]
    missing = extract_number(description, missing_patterns)
    if missing is not None:
        impact['missing'] = missing

    # Displaced/Evacuated patterns
    displaced_patterns = [
        r'(\d+[\d,]*)\s+(?:people\s+)?displaced',
        r'(\d+[\d,]*)\s+(?:people\s+)?evacuated',
        r'(\d+[\d,]*)\s+(?:people\s+)?homeless',
        r'(\d+[\d,]*)\s+(?:people\s+)?(?:left\s+)?without\s+shelter',
    ]
    displaced = extract_number(description, displaced_patterns)
    if displaced is not None:
        impact['displaced'] = displaced

    # Affected patterns (broad category)
    affected_patterns = [
        r'(\d+[\d,]*)\s+(?:people\s+)?affected',
        r'(\d+[\d,]*)\s+(?:people\s+)?impacted',
        r'(\d+[\d,]*)\s+families\s+affected',  # multiply by 5 for people
        r'(\d+[\d,]*)\s+households\s+affected',  # multiply by 4 for people
    ]
    affected = extract_number(description, affected_patterns)
    if affected is not None:
        # Check if it was families or households
        if 'families' in description.lower():
            affected = affected * 5  # Average family size
        elif 'households' in description.lower():
            affected = affected * 4  # Average household size
        impact['affected'] = affected

    # Houses destroyed
    houses_patterns = [
        r'(\d+[\d,]*)\s+houses?\s+destroyed',
        r'(\d+[\d,]*)\s+homes?\s+destroyed',
        r'(\d+[\d,]*)\s+houses?\s+damaged',
        r'(\d+[\d,]*)\s+homes?\s+damaged',
    ]
    houses = extract_number(description, houses_patterns)
    if houses is not None:
        impact['houses_destroyed'] = houses

    # Damage (USD, millions, billions)
    damage_patterns = [
        r'(?:usd|us\$|\$)\s*(\d+[\d,]*)\s*(?:million|mn|m)',
        r'(\d+[\d,]*)\s*(?:million|mn|m)\s+(?:usd|us\$|\$|dollars)',
        r'(?:usd|us\$|\$)\s*(\d+[\d,]*)\s*(?:billion|bn|b)',
        r'(\d+[\d,]*)\s*(?:billion|bn|b)\s+(?:usd|us\$|\$|dollars)',
        r'(\d+[\d,]*)\s+million\s+dollars',
        r'(\d+[\d,]*)\s+billion\s+dollars',
        r'php\s+(\d+[\d,.]*)\s+billion',  # Philippine Peso
        r'chf\s+(\d+[\d,.]*)\s+million',  # Swiss Franc
    ]

    # Extract damage and convert to USD
    damage_text = description.lower()
    for pattern in damage_patterns:
        matches = re.findall(pattern, damage_text)
        if matches:
            for match in matches:
                num_str = match.replace(',', '').replace('.', '') if isinstance(match, str) else str(match)
                try:
                    value = float(num_str)

                    # Convert to USD if needed
                    if 'billion' in damage_text or 'bn' in damage_text or 'b)' in damage_text:
                        value = value * 1_000_000_000
                    elif 'million' in damage_text or 'mn' in damage_text:
                        value = value * 1_000_000

                    # Currency conversions (rough estimates to USD)
                    if 'php' in damage_text:  # Philippine Peso
                        value = value / 50  # ~50 PHP = 1 USD
                    elif 'chf' in damage_text:  # Swiss Franc
                        value = value * 1.1  # ~1 CHF = 1.1 USD

                    impact['damage_usd'] = int(value)
                    break
                except ValueError:
                    continue
            if 'damage_usd' in impact:
                break

    return impact


def load_raw_data():
    """Load ReliefWeb CSV data."""
    print("Loading ReliefWeb disasters data...")
    input_file = get_input_file()
    df = pd.read_csv(input_file)
    print(f"  Loaded {len(df):,} disaster events")
    return df


def process_events(df):
    """Process raw data into events format with impact data extraction.

    Standard event schema columns:
    - event_id: unique identifier
    - timestamp: event datetime (ISO format)
    - latitude, longitude: event location
    - loc_id: assigned county/water body code
    - deaths, injuries, missing, displaced, affected, houses_destroyed, damage_usd: impact data
    """
    print("\nProcessing events...")

    # Parse dates
    df['timestamp'] = pd.to_datetime(df['date-event'], errors='coerce')
    df['year'] = df['timestamp'].dt.year

    # Standardize ISO3 codes (uppercase)
    df['iso3'] = df['primary_country-iso3'].str.upper()

    # Create loc_id (country level)
    df['loc_id'] = df['iso3']

    # Extract disaster type
    df['disaster_type_code'] = df['primary_type-code']
    df['disaster_type'] = df['disaster_type_code'].map(DISASTER_TYPE_MAP).fillna('other')

    # Extract impact data from descriptions
    print("  Extracting impact data from descriptions...")
    impact_data = df['description'].apply(extract_impact_data)
    impact_df = pd.DataFrame(impact_data.tolist())

    print(f"    Deaths extracted: {impact_df['deaths'].notna().sum():,}")
    print(f"    Injuries extracted: {impact_df['injuries'].notna().sum():,}")
    print(f"    Missing extracted: {impact_df['missing'].notna().sum():,}")
    print(f"    Displaced extracted: {impact_df['displaced'].notna().sum():,}")
    print(f"    Affected extracted: {impact_df['affected'].notna().sum():,}")
    print(f"    Damage (USD) extracted: {impact_df['damage_usd'].notna().sum():,}")

    # Create output dataframe with standard schema + impact data
    events = pd.DataFrame({
        'event_id': df['id'].astype(str),
        'timestamp': df['timestamp'],
        'latitude': df['primary_country-location-lat'],
        'longitude': df['primary_country-location-lon'],
        'loc_id': df['loc_id'],
        'name': df['name'],
        'disaster_type': df['disaster_type'],
        'disaster_type_code': df['disaster_type_code'],
        'glide': df['glide'],  # Global Disaster Identifier
        'country_name': df['primary_country-name'],
        'year': df['year'].astype('Int64'),
        'status': df['status'],
        'url': df['url'],
        # Impact data
        'deaths': impact_df['deaths'].astype('Int32'),
        'injuries': impact_df['injuries'].astype('Int32'),
        'missing': impact_df['missing'].astype('Int32'),
        'displaced': impact_df['displaced'].astype('Int32'),
        'affected': impact_df['affected'].astype('Int32'),
        'houses_destroyed': impact_df['houses_destroyed'].astype('Int32'),
        'damage_usd': impact_df['damage_usd'].astype('Int64'),
    })

    # Filter out rows with no valid country
    events = events[events['loc_id'].notna() & (events['loc_id'] != '')].copy()

    # Sort by date
    events = events.sort_values('timestamp', ascending=False)

    print(f"\n  Output: {len(events):,} events")
    print(f"  Countries: {events['loc_id'].nunique()}")
    print(f"  Years: {events['year'].min()}-{events['year'].max()}")
    print(f"  Types: {events['disaster_type'].nunique()}")
    print(f"  Events with deaths: {events['deaths'].notna().sum():,} ({events['deaths'].notna().sum()/len(events)*100:.1f}%)")
    print(f"  Total deaths: {events['deaths'].sum():,}")

    return events


def create_aggregates(events):
    """Create annual aggregates by country with impact sums."""
    print("\nCreating aggregates...")

    # Count disasters by country and year
    agg = events.groupby(['loc_id', 'year']).agg({
        'event_id': 'count',
        'country_name': 'first',
        'deaths': 'sum',
        'injuries': 'sum',
        'displaced': 'sum',
        'affected': 'sum',
        'damage_usd': 'sum',
    }).reset_index()

    agg.columns = ['loc_id', 'year', 'total_disasters', 'country_name',
                   'total_deaths', 'total_injuries', 'total_displaced', 'total_affected', 'total_damage_usd']

    # Add disaster type counts
    type_counts = events.groupby(['loc_id', 'year', 'disaster_type']).size().unstack(fill_value=0)
    type_counts.columns = [f'count_{col}' for col in type_counts.columns]
    type_counts = type_counts.reset_index()

    agg = agg.merge(type_counts, on=['loc_id', 'year'], how='left')

    # Fill NaN counts with 0
    count_cols = [c for c in agg.columns if c.startswith('count_')]
    agg[count_cols] = agg[count_cols].fillna(0).astype('Int64')

    # Reorder columns
    base_cols = ['loc_id', 'country_name', 'year', 'total_disasters',
                 'total_deaths', 'total_injuries', 'total_displaced', 'total_affected', 'total_damage_usd']
    other_cols = [c for c in agg.columns if c not in base_cols]
    agg = agg[base_cols + sorted(other_cols)]

    print(f"  Output: {len(agg):,} country-year records")

    return agg


def save_parquet(df, output_path, description):
    """Save dataframe to parquet."""
    print(f"\nSaving {description}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"  Saved: {output_path}")
    print(f"  Size: {size_mb:.2f} MB, {len(df):,} rows")
    return size_mb


def main():
    """Main conversion workflow."""
    print("=" * 60)
    print("ReliefWeb Disasters Converter (Enhanced)")
    print("=" * 60)

    # Load and process
    df = load_raw_data()
    events = process_events(df)
    aggregates = create_aggregates(events)

    # Save outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    events_path = OUTPUT_DIR / "events.parquet"
    save_parquet(events, events_path, "event data")

    agg_path = OUTPUT_DIR / "GLOBAL.parquet"
    save_parquet(aggregates, agg_path, "country-year aggregates")

    # Print summary
    print("\n" + "=" * 60)
    print("Conversion Summary")
    print("=" * 60)
    print(f"Events: {len(events):,}")
    print(f"Countries: {events['loc_id'].nunique()}")
    print(f"Years: {events['year'].min()}-{events['year'].max()}")

    print("\nImpact Data Coverage:")
    print(f"  Events with deaths: {events['deaths'].notna().sum():,} ({events['deaths'].notna().sum()/len(events)*100:.1f}%)")
    print(f"  Events with injuries: {events['injuries'].notna().sum():,} ({events['injuries'].notna().sum()/len(events)*100:.1f}%)")
    print(f"  Events with displaced: {events['displaced'].notna().sum():,} ({events['displaced'].notna().sum()/len(events)*100:.1f}%)")
    print(f"  Events with damage: {events['damage_usd'].notna().sum():,} ({events['damage_usd'].notna().sum()/len(events)*100:.1f}%)")

    print("\nTotal Impact:")
    print(f"  Deaths: {events['deaths'].sum():,}")
    print(f"  Injuries: {events['injuries'].sum():,}")
    print(f"  Displaced: {events['displaced'].sum():,}")
    print(f"  Damage: ${events['damage_usd'].sum():,}")

    print("\nTop disaster types:")
    print(events['disaster_type'].value_counts().head(10).to_string())

    print("\nTop affected countries (by deaths, all time):")
    top_deaths = events.groupby('loc_id')['deaths'].sum().nlargest(10)
    print(top_deaths.to_string())

    # Finalize
    print("\n" + "=" * 60)
    print("Finalizing source...")
    print("=" * 60)

    try:
        finalize_source(
            parquet_path=str(agg_path),
            source_id="reliefweb_disasters",
            events_parquet_path=str(events_path)
        )
    except ValueError as e:
        print(f"  Note: {e}")
        print("  Add 'reliefweb_disasters' to source_registry.py to enable auto-finalization")

    # Move raw files to imported folder
    move_to_imported()

    print("\n" + "=" * 60)
    print("COMPLETE!")
    print("=" * 60)

    return events, aggregates


if __name__ == "__main__":
    main()
