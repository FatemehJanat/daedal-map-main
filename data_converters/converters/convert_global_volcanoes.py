"""
Convert Smithsonian Global Volcanism Program data to global parquet format.

Creates output files:
1. events.parquet - Global eruption events with standard schema
2. GLOBAL.parquet - Country-year aggregated eruption statistics

Input: GeoJSON files from Smithsonian GVP
Output: Parquet files in global/smithsonian_volcanoes/

Uses unified base utilities for water body assignment.

Usage:
    python convert_global_volcanoes.py
"""
import pandas as pd
import geopandas as gpd
from pathlib import Path
import json
import sys

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from data_converters.base import (
    get_water_body_loc_id,
    save_parquet,
)
from build.catalog.finalize_source import finalize_source

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/smithsonian/volcano")
IMPORTED_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/imported/smithsonian/volcano")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/global/smithsonian_volcanoes")
SOURCE_ID = "smithsonian_volcanoes_global"

# Country name to ISO3 mapping for common names in Smithsonian data
COUNTRY_TO_ISO3 = {
    'United States': 'USA',
    'Russia': 'RUS',
    'Japan': 'JPN',
    'Indonesia': 'IDN',
    'Chile': 'CHL',
    'Papua New Guinea': 'PNG',
    'Philippines': 'PHL',
    'New Zealand': 'NZL',
    'Ecuador': 'ECU',
    'Mexico': 'MEX',
    'Italy': 'ITA',
    'Iceland': 'ISL',
    'Vanuatu': 'VUT',
    'Guatemala': 'GTM',
    'Costa Rica': 'CRI',
    'Colombia': 'COL',
    'Peru': 'PER',
    'Nicaragua': 'NIC',
    'El Salvador': 'SLV',
    'Argentina': 'ARG',
    'Canada': 'CAN',
    'Ethiopia': 'ETH',
    'DR Congo': 'COD',
    'Tanzania': 'TZA',
    'Kenya': 'KEN',
    'Cameroon': 'CMR',
    'Greece': 'GRC',
    'Turkey': 'TUR',
    'Turkiye': 'TUR',
    'Spain': 'ESP',
    'Portugal': 'PRT',
    'France': 'FRA',
    'Germany': 'DEU',
    'China': 'CHN',
    'Taiwan': 'TWN',
    'South Korea': 'KOR',
    'North Korea': 'PRK',
    'India': 'IND',
    'Australia': 'AUS',
    'Tonga': 'TON',
    'Fiji': 'FJI',
    'Samoa': 'WSM',
    'Solomon Islands': 'SLB',
    'Antarctica': 'ATA',
    'Eritrea': 'ERI',
    'Yemen': 'YEM',
    'Saudi Arabia': 'SAU',
    'Iran': 'IRN',
    'Georgia': 'GEO',
    'Armenia': 'ARM',
    'Azerbaijan': 'AZE',
    'Uganda': 'UGA',
    'Rwanda': 'RWA',
    'Burundi': 'BDI',
    'Equatorial Guinea': 'GNQ',
    'Cabo Verde': 'CPV',
    'Comoros': 'COM',
    'Union of the Comoros': 'COM',
    'Reunion': 'REU',
    'Martinique': 'MTQ',
    'Guadeloupe': 'GLP',
    'Dominica': 'DMA',
    'Saint Lucia': 'LCA',
    'Saint Vincent and the Grenadines': 'VCT',
    'Grenada': 'GRD',
    'Montserrat': 'MSR',
    'Saint Kitts and Nevis': 'KNA',
    'Honduras': 'HND',
    'Panama': 'PAN',
    'Bolivia': 'BOL',
    'Norway': 'NOR',
    'United Kingdom': 'GBR',
    'Netherlands': 'NLD',
    'Mongolia': 'MNG',
    'Vietnam': 'VNM',
    'Burma (Myanmar)': 'MMR',
    'Myanmar': 'MMR',
    'Syria': 'SYR',
    'Jordan': 'JOR',
    'Djibouti': 'DJI',
    'South Africa': 'ZAF',
    # Multi-country entries - assign to first country
    'Chile-Argentina': 'CHL',
    'Chile-Bolivia': 'CHL',
    'Colombia-Ecuador': 'COL',
    'DR Congo-Rwanda': 'COD',
    'Ethiopia-Djibouti': 'ETH',
    'China-North Korea': 'CHN',
    'Mexico-Guatemala': 'MEX',
    'Armenia-Azerbaijan': 'ARM',
    'Syria-Jordan-Saudi Arabia': 'SYR',
    'Japan - administered by Russia': 'RUS',
    'France - claimed by Vanuatu': 'FRA',
    'Ethiopia-Eritrea': 'ETH',
    'Ethiopia-Eritrea-Djibouti': 'ETH',
    'Eritrea-Djibouti': 'ERI',
    'Guatemala-El Salvador': 'GTM',
    # African countries
    'Niger': 'NER',
    'Algeria': 'DZA',
    'Chad': 'TCD',
    'Sudan': 'SDN',
    'Libya': 'LBY',
    'Egypt': 'EGY',
    'Morocco': 'MAR',
    'Tunisia': 'TUN',
    'Mali': 'MLI',
    'Mauritania': 'MRT',
    # Special cases
    'Undersea Features': None,  # Will use water body code
}


# =============================================================================
# Eruption Radius Calculations
# =============================================================================

def calculate_felt_radius_km(vei):
    """
    Calculate eruption "felt" radius in km based on VEI.

    VEI is logarithmic (each step = 10x ejecta volume).
    Radius scales as cube root of volume: R ~ 10^(VEI/3)

    Formula: felt_radius = 5 * 10^(VEI * 0.33)
    """
    if pd.isna(vei):
        return 10.0  # Default for unknown VEI
    vei = max(0, int(vei))
    return round(5 * (10 ** (vei * 0.33)), 1)


def calculate_damage_radius_km(vei):
    """
    Calculate eruption "damage" radius in km based on VEI.

    Damage zone (pyroclastic flows, lahars, heavy ashfall)
    is much smaller than felt radius.

    Formula: damage_radius = 1 * 10^(VEI * 0.3)
    """
    if pd.isna(vei):
        return 3.0  # Default for unknown VEI
    vei = max(0, int(vei))
    return round(1 * (10 ** (vei * 0.3)), 1)


def get_source_dir():
    """Get source directory - check raw first, then imported."""
    if RAW_DATA_DIR.exists() and (RAW_DATA_DIR / "gvp_volcanoes.json").exists():
        return RAW_DATA_DIR
    elif IMPORTED_DIR.exists() and (IMPORTED_DIR / "gvp_volcanoes.json").exists():
        print(f"  Note: Using imported data from {IMPORTED_DIR}")
        return IMPORTED_DIR
    return RAW_DATA_DIR


def country_to_loc_id(country, latitude=None, longitude=None):
    """
    Convert country name to loc_id.

    Returns ISO3 code for countries, or water body code for undersea features.
    """
    if country is None or pd.isna(country):
        # Use water body based on coordinates
        if latitude is not None and longitude is not None:
            return get_water_body_loc_id(latitude, longitude, region='global')
        return 'XOP'  # Default Pacific

    iso3 = COUNTRY_TO_ISO3.get(country)

    if iso3 is None:
        # Check for undersea/oceanic features
        if 'Undersea' in str(country) or 'Ocean' in str(country):
            if latitude is not None and longitude is not None:
                return get_water_body_loc_id(latitude, longitude, region='global')
            return 'XOP'
        # Unknown country - log and use coordinates
        print(f"  Warning: Unknown country '{country}' - using water body code")
        if latitude is not None and longitude is not None:
            return get_water_body_loc_id(latitude, longitude, region='global')
        return 'XOP'

    return iso3


# =============================================================================
# Data Loading
# =============================================================================

def load_volcano_data():
    """Load volcanoes and eruptions from GeoJSON files."""
    print("\nLoading volcano data...")

    source_dir = get_source_dir()

    # Load volcanoes
    volcanoes_path = source_dir / "gvp_volcanoes.json"
    with open(volcanoes_path, 'r', encoding='utf-8') as f:
        volcanoes_geojson = json.load(f)

    # Extract features to dataframe
    volcanoes_list = []
    for feature in volcanoes_geojson['features']:
        props = feature['properties']
        coords = feature['geometry']['coordinates']
        volcanoes_list.append({
            'volcano_number': props.get('Volcano_Number'),
            'volcano_name': props.get('Volcano_Name'),
            'country': props.get('Country'),
            'region': props.get('Region'),
            'subregion': props.get('Subregion'),
            'latitude': props.get('Latitude'),
            'longitude': props.get('Longitude'),
            'elevation_m': props.get('Elevation'),
            'volcano_type': props.get('Primary_Volcano_Type'),
            'last_eruption_year': props.get('Last_Eruption_Year'),
        })

    volcanoes_df = pd.DataFrame(volcanoes_list)
    print(f"  Total volcanoes: {len(volcanoes_df):,}")

    # Load eruptions
    eruptions_path = source_dir / "gvp_eruptions.json"
    with open(eruptions_path, 'r', encoding='utf-8') as f:
        eruptions_geojson = json.load(f)

    # Extract features to dataframe
    eruptions_list = []
    for feature in eruptions_geojson['features']:
        props = feature['properties']
        coords = feature['geometry']['coordinates']
        eruptions_list.append({
            'volcano_number': props.get('Volcano_Number'),
            'volcano_name': props.get('Volcano_Name'),
            'eruption_number': props.get('Eruption_Number'),
            'activity_type': props.get('Activity_Type'),
            'vei': props.get('ExplosivityIndexMax'),
            'start_year': props.get('StartDateYear'),
            'start_month': props.get('StartDateMonth'),
            'start_day': props.get('StartDateDay'),
            'end_year': props.get('EndDateYear'),
            'end_month': props.get('EndDateMonth'),
            'end_day': props.get('EndDateDay'),
            'activity_area': props.get('ActivityArea'),  # e.g., "East rift zone (Puu O'o)"
            'latitude': coords[1] if coords else None,
            'longitude': coords[0] if coords else None
        })

    eruptions_df = pd.DataFrame(eruptions_list)
    print(f"  Total eruptions: {len(eruptions_df):,}")

    return volcanoes_df, eruptions_df


def assign_loc_ids(volcanoes_df):
    """Assign loc_id to each volcano based on country."""
    print("\nAssigning loc_ids...")

    volcanoes_df = volcanoes_df.copy()
    volcanoes_df['loc_id'] = volcanoes_df.apply(
        lambda row: country_to_loc_id(
            row['country'],
            row.get('latitude'),
            row.get('longitude')
        ),
        axis=1
    )

    # Show breakdown
    loc_id_counts = volcanoes_df['loc_id'].value_counts()
    print(f"  Unique loc_ids: {len(loc_id_counts)}")
    print(f"  Top 10 countries:")
    for loc_id, count in loc_id_counts.head(10).items():
        print(f"    {loc_id}: {count}")

    # Show water body assignments
    water_body = volcanoes_df[volcanoes_df['loc_id'].str.startswith('X', na=False)]
    if len(water_body) > 0:
        print(f"\n  Water body assignments: {len(water_body)}")
        for code in water_body['loc_id'].unique():
            print(f"    {code}: {len(water_body[water_body['loc_id'] == code])}")

    return volcanoes_df


def create_events_parquet(eruptions_df, volcanoes_df):
    """Create events.parquet with standard event schema."""
    print("\nCreating events.parquet...")

    # Join eruptions with volcano loc_id and country
    volcano_info = volcanoes_df[['volcano_number', 'loc_id', 'country', 'region']].drop_duplicates()
    eruptions_with_loc = eruptions_df.merge(volcano_info, on='volcano_number', how='left')

    # Build timestamp from year/month/day fields
    def build_timestamp(year, month, day):
        try:
            year = int(year) if pd.notna(year) else None
            if year and year > 0:
                month = int(month) if pd.notna(month) and month > 0 else 1
                day = int(day) if pd.notna(day) and day > 0 else 1
                month = max(1, min(12, month))
                day = max(1, min(28, day))
                return pd.Timestamp(year=year, month=month, day=day)
        except:
            pass
        return pd.NaT

    eruptions_with_loc = eruptions_with_loc.copy()

    # Build start and end timestamps
    eruptions_with_loc['timestamp'] = eruptions_with_loc.apply(
        lambda row: build_timestamp(row['start_year'], row.get('start_month'), row.get('start_day')),
        axis=1
    )
    eruptions_with_loc['end_timestamp'] = eruptions_with_loc.apply(
        lambda row: build_timestamp(row['end_year'], row.get('end_month'), row.get('end_day')),
        axis=1
    )

    # Extract year (works for negative/prehistoric years too)
    eruptions_with_loc['year'] = eruptions_with_loc['start_year'].apply(
        lambda x: int(x) if pd.notna(x) else None
    )
    eruptions_with_loc['end_year_int'] = eruptions_with_loc['end_year'].apply(
        lambda x: int(x) if pd.notna(x) else None
    )

    # Calculate duration in days (for eruptions with both start and end)
    def calc_duration(row):
        if pd.notna(row['timestamp']) and pd.notna(row['end_timestamp']):
            delta = row['end_timestamp'] - row['timestamp']
            return max(0, delta.days)
        return None
    eruptions_with_loc['duration_days'] = eruptions_with_loc.apply(calc_duration, axis=1)

    # Determine if eruption is ongoing (no end date, or ended in current year)
    current_year = pd.Timestamp.now().year
    def is_ongoing(row):
        if pd.isna(row['end_year']):
            return True  # No end date = ongoing
        return int(row['end_year']) >= current_year
    eruptions_with_loc['is_ongoing'] = eruptions_with_loc.apply(is_ongoing, axis=1)

    # Calculate impact radii from VEI
    print("  Calculating impact radii from VEI...")
    eruptions_with_loc['felt_radius_km'] = eruptions_with_loc['vei'].apply(calculate_felt_radius_km)
    eruptions_with_loc['damage_radius_km'] = eruptions_with_loc['vei'].apply(calculate_damage_radius_km)

    # Prepare events dataframe with UNIFIED EVENT SCHEMA
    events_out = pd.DataFrame({
        'event_id': eruptions_with_loc['eruption_number'].apply(lambda x: f"VE{x:06d}" if pd.notna(x) else None),
        'eruption_id': eruptions_with_loc['eruption_number'],  # For grouping continuous eruptions
        'event_type': 'volcano',  # Standard event type column
        'year': eruptions_with_loc['year'],
        'timestamp': eruptions_with_loc['timestamp'],
        'end_year': eruptions_with_loc['end_year_int'],
        'end_timestamp': eruptions_with_loc['end_timestamp'],
        'duration_days': eruptions_with_loc['duration_days'],
        'is_ongoing': eruptions_with_loc['is_ongoing'],
        'latitude': eruptions_with_loc['latitude'].round(4) if eruptions_with_loc['latitude'].notna().any() else pd.NA,
        'longitude': eruptions_with_loc['longitude'].round(4) if eruptions_with_loc['longitude'].notna().any() else pd.NA,
        'loc_id': eruptions_with_loc['loc_id'],
        'felt_radius_km': eruptions_with_loc['felt_radius_km'],
        'damage_radius_km': eruptions_with_loc['damage_radius_km'],
        'volcano_number': eruptions_with_loc['volcano_number'],
        'volcano_name': eruptions_with_loc['volcano_name'],
        'activity_type': eruptions_with_loc['activity_type'],
        'activity_area': eruptions_with_loc.get('activity_area'),  # e.g., "East rift zone"
        'VEI': eruptions_with_loc['vei'],  # Frontend expects uppercase VEI
        'country': eruptions_with_loc['country'],
        'region': eruptions_with_loc['region'],
    })

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "events.parquet"
    save_parquet(events_out, output_path, description="global eruption events")

    # Print stats
    print(f"  Total events: {len(events_out):,}")
    print(f"  Year range: {events_out['year'].min()} to {events_out['year'].max()}")
    print(f"  Countries: {events_out['loc_id'].nunique()}")
    print(f"  Radii: felt {events_out['felt_radius_km'].min()}-{events_out['felt_radius_km'].max()} km, "
          f"damage {events_out['damage_radius_km'].min()}-{events_out['damage_radius_km'].max()} km")

    # Duration stats
    with_duration = events_out[events_out['duration_days'].notna()]
    if len(with_duration) > 0:
        print(f"\n  Duration stats ({len(with_duration):,} eruptions with end dates):")
        print(f"    Mean duration: {with_duration['duration_days'].mean():.0f} days")
        print(f"    Max duration: {with_duration['duration_days'].max():.0f} days")
        long_eruptions = with_duration[with_duration['duration_days'] > 365]
        print(f"    Long eruptions (>1 year): {len(long_eruptions):,}")

    ongoing = events_out[events_out['is_ongoing'] == True]
    print(f"    Ongoing eruptions: {len(ongoing):,}")

    return events_out


def create_country_aggregates(events_df):
    """Create GLOBAL.parquet with country-year aggregates."""
    print("\nCreating country-year aggregates...")

    # Filter to events with valid year (excluding prehistoric for aggregates)
    df = events_df[events_df['year'].notna() & (events_df['year'] >= 1800)].copy()
    df['year'] = df['year'].astype(int)

    if len(df) == 0:
        print("  No events with valid modern years!")
        return pd.DataFrame()

    # Group by country-year
    grouped = df.groupby(['loc_id', 'year'])

    aggregates = grouped.agg({
        'event_id': 'count',
        'volcano_number': 'nunique',
        'VEI': ['max', 'mean']
    }).reset_index()

    # Flatten column names
    aggregates.columns = ['loc_id', 'year', 'eruption_count', 'volcano_count', 'max_vei', 'avg_vei']
    aggregates['avg_vei'] = aggregates['avg_vei'].round(1)

    print(f"  Country-year records: {len(aggregates):,}")
    print(f"  Unique countries: {aggregates['loc_id'].nunique():,}")

    # Save
    output_path = OUTPUT_DIR / "GLOBAL.parquet"
    save_parquet(aggregates, output_path, description="country-year aggregates")

    return aggregates


def print_statistics(events_df):
    """Print summary statistics."""
    print("\n" + "=" * 60)
    print("STATISTICS")
    print("=" * 60)

    print(f"\nTotal eruptions: {len(events_df):,}")
    print(f"Year range: {events_df['year'].min()} to {events_df['year'].max()}")

    print("\nTop 10 Countries by Eruption Count:")
    country_counts = events_df.groupby('loc_id').size().nlargest(10)
    for loc_id, count in country_counts.items():
        print(f"  {loc_id}: {count:,}")

    print("\nVEI Distribution:")
    if 'VEI' in events_df.columns:
        for vei, count in events_df['VEI'].value_counts().sort_index().items():
            if pd.notna(vei):
                print(f"  VEI {int(vei)}: {count:,}")
        unknown = events_df['VEI'].isna().sum()
        print(f"  Unknown: {unknown:,}")

    print("\nMost Active Volcanoes:")
    volcano_counts = events_df.groupby('volcano_name').size().nlargest(10)
    for volcano, count in volcano_counts.items():
        print(f"  {volcano}: {count:,}")

    print("\nRecent Eruptions (2020+):")
    recent = events_df[events_df['year'] >= 2020].sort_values('year', ascending=False)
    for _, row in recent.head(10).iterrows():
        vei_str = f"VEI {int(row['VEI'])}" if pd.notna(row['VEI']) else "VEI ?"
        print(f"  {row['volcano_name']} ({row['loc_id']}, {int(row['year'])}) - {vei_str}")


def main():
    """Main conversion logic."""
    print("=" * 60)
    print("Global Volcano Database Converter")
    print("=" * 60)

    # Load volcano data
    volcanoes_df, eruptions_df = load_volcano_data()

    if volcanoes_df.empty:
        print("\nERROR: No volcano data found")
        return 1

    # Assign loc_ids to volcanoes
    volcanoes_with_loc = assign_loc_ids(volcanoes_df)

    # Create output files
    events_out = create_events_parquet(eruptions_df, volcanoes_with_loc)
    aggregates = create_country_aggregates(events_out)

    # Print statistics
    print_statistics(events_out)

    # Generate metadata
    print("\n" + "=" * 60)
    print("Finalizing source...")
    print("=" * 60)

    try:
        agg_path = OUTPUT_DIR / "GLOBAL.parquet"
        if agg_path.exists():
            finalize_source(
                parquet_path=str(agg_path),
                source_id=SOURCE_ID,
                events_parquet_path=str(OUTPUT_DIR / "events.parquet")
            )
    except ValueError as e:
        print(f"  Note: {e}")
        print(f"  Add '{SOURCE_ID}' to source_registry.py to enable auto-finalization")

    print("\n" + "=" * 60)
    print("COMPLETE!")
    print(f"Output: {OUTPUT_DIR}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
