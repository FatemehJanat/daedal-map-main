"""
Convert NOAA Tsunami Database to parquet format.

Creates two output files:
1. events.parquet - Individual tsunami events with source location
2. USA.parquet - County-year aggregated statistics (based on runup locations)

Input: JSON files from NOAA NCEI tsunami database
Output: Two parquet files with tsunami data

Uses unified base utilities for spatial join and water body assignment.

Usage:
    python convert_tsunami.py
"""
import pandas as pd
import geopandas as gpd
from pathlib import Path
import json
import sys

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from data_converters.base import (
    USA_STATE_FIPS,
    load_geometry_parquet,
    get_water_body_loc_id,
    create_point_gdf,
    save_parquet,
    TERRITORIAL_WATERS_DEG,
)
from build.catalog.finalize_source import finalize_source

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/noaa/tsunami")
IMPORTED_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/imported/noaa/tsunami")
GEOMETRY_PATH = Path("C:/Users/Bryan/Desktop/county-map-data/geometry/USA.parquet")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA/tsunamis")
SOURCE_ID = "noaa_tsunamis"


def get_source_dir():
    """Get source directory - check raw first, then imported."""
    if RAW_DATA_DIR.exists() and (RAW_DATA_DIR / "tsunami_events.json").exists():
        return RAW_DATA_DIR
    elif IMPORTED_DIR.exists() and (IMPORTED_DIR / "tsunami_events.json").exists():
        print(f"  Note: Using imported data from {IMPORTED_DIR}")
        return IMPORTED_DIR
    return RAW_DATA_DIR


def move_to_imported():
    """Move processed raw files to imported folder."""
    import shutil
    if RAW_DATA_DIR.exists() and (RAW_DATA_DIR / "tsunami_events.json").exists():
        IMPORTED_DIR.mkdir(parents=True, exist_ok=True)
        for f in RAW_DATA_DIR.glob("*.json"):
            shutil.move(str(f), str(IMPORTED_DIR / f.name))
        print(f"  Moved files to {IMPORTED_DIR}")

# Cause codes from NOAA documentation
CAUSE_CODES = {
    0: 'Unknown',
    1: 'Earthquake',
    2: 'Questionable Earthquake',
    3: 'Earthquake and Landslide',
    4: 'Volcano and Earthquake',
    5: 'Volcano, Earthquake, and Landslide',
    6: 'Volcano',
    7: 'Volcano and Landslide',
    8: 'Landslide',
    9: 'Meteorological',
    10: 'Explosion',
    11: 'Astronomical Tide'
}


# =============================================================================
# Data Loading
# =============================================================================

def load_counties():
    """Load county boundaries from geometry parquet using base utility."""
    return load_geometry_parquet(GEOMETRY_PATH, admin_level=2, geometry_format='geojson')


def load_tsunami_data():
    """Load tsunami events and runups from JSON files."""
    print("\nLoading tsunami data...")

    source_dir = get_source_dir()

    # Load events
    events_path = source_dir / "tsunami_events.json"
    with open(events_path, 'r', encoding='utf-8') as f:
        events_data = json.load(f)

    events_df = pd.DataFrame(events_data['events'])
    print(f"  Total events: {len(events_df):,}")

    # Load runups
    runups_path = source_dir / "tsunami_runups.json"
    with open(runups_path, 'r', encoding='utf-8') as f:
        runups_data = json.load(f)

    runups_df = pd.DataFrame(runups_data['runups'])
    print(f"  Total runups: {len(runups_df):,}")

    return events_df, runups_df


def filter_us_data(events_df, runups_df):
    """Filter to US-related events and runups."""
    print("\nFiltering to US data...")

    # US states/territories in the data
    us_regions = ['USA', 'UNITED STATES', 'ALASKA', 'HAWAII', 'PUERTO RICO',
                  'VIRGIN ISLANDS', 'GUAM', 'AMERICAN SAMOA']

    # Filter events where source is in US or affects US
    us_event_ids = set()

    # Events with US source location
    us_source_events = events_df[events_df['country'].str.upper().isin(us_regions)]
    us_event_ids.update(us_source_events['id'].tolist())

    # US runups
    us_runups = runups_df[runups_df['country'].str.upper().isin(us_regions)]
    us_event_ids.update(us_runups['tsunamiEventId'].dropna().tolist())

    # Filter events to those affecting US
    us_events = events_df[events_df['id'].isin(us_event_ids)].copy()

    print(f"  US source events: {len(us_source_events):,}")
    print(f"  US runup locations: {len(us_runups):,}")
    print(f"  Total US-related events: {len(us_events):,}")

    return us_events, us_runups


def geocode_runups(runups_df, counties_gdf):
    """
    Geocode runup locations to counties using base utilities.

    Uses three-pass matching:
    1. Strict 'within' for points inside county polygons
    2. Nearest neighbor for coastal points within 12 nautical miles (territorial waters)
    3. Water body codes for offshore points
    """
    print("\nGeocoding runups to counties...")

    # Filter to runups with coordinates
    runups_with_coords = runups_df.dropna(subset=['latitude', 'longitude']).copy()
    print(f"  Runups with coordinates: {len(runups_with_coords):,}")

    if len(runups_with_coords) == 0:
        return runups_df

    # Create point geometries using base utility
    gdf = create_point_gdf(runups_with_coords, lat_col='latitude', lon_col='longitude')

    # Pass 1: Strict 'within' spatial join
    gdf_with_counties = gpd.sjoin(gdf, counties_gdf[['loc_id', 'geometry']],
                                   how='left', predicate='within')

    strict_matched = gdf_with_counties['loc_id'].notna().sum()
    print(f"  Pass 1 (within): {strict_matched:,} matched")

    # Pass 2: Nearest neighbor for unmatched coastal points
    unmatched_mask = gdf_with_counties['loc_id'].isna()
    if unmatched_mask.any():
        unmatched_indices = gdf_with_counties[unmatched_mask].index
        unmatched_gdf = gdf_with_counties.loc[unmatched_indices].copy()
        unmatched_gdf = unmatched_gdf.drop(columns=['loc_id', 'index_right'], errors='ignore')

        # Use sjoin_nearest to find closest county
        nearest = gpd.sjoin_nearest(
            unmatched_gdf,
            counties_gdf[['loc_id', 'geometry']],
            how='left',
            distance_col='dist_to_county'
        )

        # Only assign if within territorial waters (12 nm) using base constant
        within_territorial = nearest['dist_to_county'] <= TERRITORIAL_WATERS_DEG
        nearest_matched = within_territorial.sum()

        # Update loc_id for points within territorial waters
        updates = nearest[within_territorial][['loc_id']].to_dict()['loc_id']
        for idx, loc_id_val in updates.items():
            gdf_with_counties.at[idx, 'loc_id'] = loc_id_val

        print(f"  Pass 2 (nearest, <12nm): {nearest_matched:,} matched")

        # Pass 3: Assign water body codes using base utility
        still_unmatched_mask = gdf_with_counties['loc_id'].isna()
        if still_unmatched_mask.any():
            gdf_with_counties.loc[still_unmatched_mask, 'loc_id'] = \
                gdf_with_counties.loc[still_unmatched_mask].apply(
                    lambda row: get_water_body_loc_id(row['latitude'], row['longitude'], region='usa'),
                    axis=1
                )
            water_assigned = still_unmatched_mask.sum()
            print(f"  Pass 3 (water body, >12nm): {water_assigned:,} assigned")

    total_matched = gdf_with_counties['loc_id'].notna().sum()
    print(f"  Total assigned: {total_matched:,} ({total_matched/len(gdf_with_counties)*100:.1f}%)")

    # Clean up join artifacts
    gdf_with_counties = gdf_with_counties.drop(columns=['index_right'], errors='ignore')

    return gdf_with_counties


def create_events_parquet(events_df, runups_df):
    """Create events.parquet with tsunami source events.

    Standard event schema columns:
    - event_id: unique identifier
    - timestamp: event datetime (ISO format)
    - latitude, longitude: event location
    - loc_id: assigned county/water body code
    """
    # Build timestamp from year/month/day
    def build_timestamp(row):
        try:
            year = int(row['year']) if pd.notna(row['year']) else None
            month = int(row.get('month', 1)) if pd.notna(row.get('month')) else 1
            day = int(row.get('day', 1)) if pd.notna(row.get('day')) else 1
            if year:
                return pd.Timestamp(year=year, month=month, day=day)
        except:
            pass
        return pd.NaT

    events_df = events_df.copy()
    events_df['timestamp'] = events_df.apply(build_timestamp, axis=1)

    # Prepare events dataframe with standard schema
    events_out = pd.DataFrame({
        'event_id': events_df['id'].apply(lambda x: f"TS{x:06d}" if pd.notna(x) else None),
        'timestamp': events_df['timestamp'],  # Standard column name
        'latitude': events_df['latitude'].round(4),
        'longitude': events_df['longitude'].round(4),
        'country': events_df['country'],
        'location': events_df['locationName'],
        'cause_code': events_df['causeCode'],
        'cause': events_df['causeCode'].map(CAUSE_CODES),
        'intensity': events_df.get('tsIntensity', pd.NA),
        'max_water_height_m': events_df.get('maxWaterHeight', pd.NA),
        'num_runups': events_df.get('numRunups', 0),
        'deaths_order': events_df.get('deathsAmountOrder', pd.NA),
        'damage_order': events_df.get('damageAmountOrder', pd.NA),
        'eq_magnitude': events_df.get('eqMagnitude', pd.NA)
    })

    # Filter to events with valid coordinates
    events_out = events_out.dropna(subset=['latitude', 'longitude'])

    # Assign water body loc_id for source events using base utility (most are in ocean)
    events_out['loc_id'] = events_out.apply(
        lambda row: get_water_body_loc_id(row['latitude'], row['longitude'], region='usa'),
        axis=1
    )

    # Count by water body
    water_counts = events_out['loc_id'].value_counts()
    print(f"  Source events by water body:")
    for loc_id, count in water_counts.head(5).items():
        print(f"    {loc_id}: {count:,}")

    # Save using base utility
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "events.parquet"
    save_parquet(events_out, output_path, description="tsunami source events")

    return events_out


def create_runups_parquet(runups_df):
    """Create runups.parquet with coastal impact locations."""
    # Prepare runups dataframe
    runups_out = pd.DataFrame({
        'runup_id': runups_df['id'],
        'event_id': runups_df['tsunamiEventId'],
        'year': runups_df['year'],
        'month': runups_df.get('month', pd.NA),
        'latitude': runups_df['latitude'].round(4) if 'latitude' in runups_df else pd.NA,
        'longitude': runups_df['longitude'].round(4) if 'longitude' in runups_df else pd.NA,
        'country': runups_df['country'],
        'location': runups_df['locationName'],
        'water_height_m': runups_df.get('waterHeight', pd.NA),
        'horizontal_inundation_m': runups_df.get('horizontalInundation', pd.NA),
        'dist_from_source_km': runups_df.get('distFromSource', pd.NA),
        'deaths_order': runups_df.get('deathsAmountOrder', pd.NA),
        'damage_order': runups_df.get('damageAmountOrder', pd.NA),
        'loc_id': runups_df.get('loc_id', pd.NA)
    })

    # Save using base utility
    output_path = OUTPUT_DIR / "runups.parquet"
    save_parquet(runups_out, output_path, description="runup observations")

    return runups_out


def create_county_aggregates(runups_df):
    """Create USA.parquet with county-year aggregates based on runups."""
    print("\nCreating county-year aggregates...")

    # Filter to runups with county match
    df_with_county = runups_df[runups_df['loc_id'].notna()].copy()

    if len(df_with_county) == 0:
        print("  No runups matched to counties!")
        return pd.DataFrame()

    # Group by county-year
    grouped = df_with_county.groupby(['loc_id', 'year'])

    aggregates = grouped.agg({
        'id': 'count',  # number of runups
        'tsunamiEventId': 'nunique',  # distinct events
    }).reset_index()

    aggregates.columns = ['loc_id', 'year', 'runup_count', 'event_count']

    print(f"  County-year records: {len(aggregates):,}")
    print(f"  Unique counties: {aggregates['loc_id'].nunique():,}")

    return aggregates


def save_county_parquet(df):
    """Save county aggregates to USA.parquet using base utility."""
    if df.empty:
        print("\n  Skipping USA.parquet (no data)")
        return None

    output_path = OUTPUT_DIR / "USA.parquet"
    save_parquet(df, output_path, description="county-year aggregates")

    return output_path


def generate_metadata(events_df, runups_df, county_df):
    """Generate metadata.json for the dataset."""
    print("\nGenerating metadata.json...")

    # Year range - extract from timestamp
    if not events_df.empty and 'timestamp' in events_df.columns:
        years = pd.to_datetime(events_df['timestamp'], errors='coerce').dt.year
        min_year = int(years.min()) if years.notna().any() else 0
        max_year = int(years.max()) if years.notna().any() else 0
    else:
        min_year = 0
        max_year = 0

    metrics = {
        "runup_count": {
            "name": "Tsunami Runup Count",
            "description": "Number of recorded tsunami runup observations in county during year",
            "unit": "count",
            "aggregation": "sum",
            "file": "USA.parquet"
        },
        "event_count": {
            "name": "Tsunami Event Count",
            "description": "Number of distinct tsunami events affecting county during year",
            "unit": "count",
            "aggregation": "sum",
            "file": "USA.parquet"
        },
        "intensity": {
            "name": "Tsunami Intensity",
            "description": "Soloviev-Imamura tsunami intensity scale",
            "unit": "scale",
            "file": "events.parquet"
        },
        "max_water_height_m": {
            "name": "Maximum Water Height",
            "description": "Maximum observed water height above normal sea level",
            "unit": "meters",
            "file": "events.parquet"
        }
    }

    metadata = {
        "source_id": "noaa_tsunamis",
        "source_name": "NOAA National Centers for Environmental Information - Tsunami Database",
        "description": f"Historical tsunami events and runup observations for US territory ({min_year}-{max_year})",

        "source": {
            "name": "NOAA NCEI Global Historical Tsunami Database",
            "url": "https://www.ngdc.noaa.gov/hazel/view/hazards/tsunami/event-search",
            "license": "Public Domain (US Government)"
        },

        "geographic_level": "county",
        "geographic_coverage": {
            "type": "country",
            "countries": 1,
            "country_codes": ["USA"]
        },
        "coverage_description": "USA (primarily coastal states: HI, CA, AK, WA, OR)",

        "temporal_coverage": {
            "start": min_year,
            "end": max_year,
            "frequency": "event-based"
        },

        "files": {
            "events": {
                "filename": "events.parquet",
                "description": "Tsunami source events with location and impact metrics",
                "record_type": "event",
                "record_count": len(events_df)
            },
            "runups": {
                "filename": "runups.parquet",
                "description": "Coastal runup/impact observations linked to source events",
                "record_type": "observation",
                "record_count": len(runups_df)
            },
            "county_aggregates": {
                "filename": "USA.parquet",
                "description": "County-year tsunami statistics based on runup locations",
                "record_type": "county-year",
                "record_count": len(county_df) if county_df is not None else 0
            }
        },

        "metrics": metrics,

        "llm_summary": f"NOAA Tsunami Database for USA, {min_year}-{max_year}. "
                      f"{len(events_df):,} events, {len(runups_df):,} runup observations. "
                      f"Primarily affects Hawaii, California, Alaska, Washington, Oregon.",

        "processing": {
            "converter": "data_converters/convert_tsunami.py",
            "last_run": pd.Timestamp.now().strftime("%Y-%m-%d"),
            "geocoding_method": "Spatial join with Census TIGER/Line 2024 county boundaries"
        }
    }

    # Write metadata.json
    metadata_path = OUTPUT_DIR / "metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    print(f"  Saved: {metadata_path}")


def print_statistics(events_df, runups_df, county_df):
    """Print summary statistics."""
    print("\n" + "="*80)
    print("STATISTICS")
    print("="*80)

    print(f"\nTotal tsunami events: {len(events_df):,}")
    if not events_df.empty and 'timestamp' in events_df.columns:
        years = pd.to_datetime(events_df['timestamp'], errors='coerce').dt.year
        if years.notna().any():
            print(f"Year range: {int(years.min())} to {int(years.max())}")

    print(f"\nTotal runup observations: {len(runups_df):,}")

    if 'loc_id' in runups_df.columns:
        matched = runups_df['loc_id'].notna().sum()
        print(f"Runups matched to US counties: {matched:,}")

    print("\nCause Distribution (events):")
    if 'cause' in events_df.columns:
        for cause, count in events_df['cause'].value_counts().head(10).items():
            print(f"  {cause}: {count:,}")

    print("\nUS State Distribution (runups):")
    if 'country' in runups_df.columns:
        # Map area field to states where available
        state_counts = runups_df.groupby('country').size().sort_values(ascending=False).head(10)
        for state, count in state_counts.items():
            print(f"  {state}: {count:,}")


def main():
    """Main conversion logic."""
    print("=" * 60)
    print("NOAA Tsunami Database Converter")
    print("=" * 60)

    # Load county boundaries using base utility
    counties_gdf = load_counties()

    # Load tsunami data
    events_df, runups_df = load_tsunami_data()

    # Filter to US data
    us_events, us_runups = filter_us_data(events_df, runups_df)

    if us_events.empty:
        print("\nERROR: No US-related tsunami events found")
        return 1

    # Geocode runups to counties
    us_runups_geocoded = geocode_runups(us_runups, counties_gdf)

    # Create output files
    events_out = create_events_parquet(us_events, us_runups_geocoded)
    runups_out = create_runups_parquet(us_runups_geocoded)

    # Create county aggregates
    county_df = create_county_aggregates(us_runups_geocoded)
    agg_path = save_county_parquet(county_df)

    # Print statistics
    print_statistics(events_out, runups_out, county_df)

    # Generate metadata (custom for tsunamis - 3 files)
    generate_metadata(events_out, runups_out, county_df)

    # Finalize (update index)
    print("\n" + "=" * 60)
    print("Finalizing source...")
    print("=" * 60)

    try:
        if agg_path:
            finalize_source(
                parquet_path=str(agg_path),
                source_id=SOURCE_ID,
                events_parquet_path=str(OUTPUT_DIR / "events.parquet")
            )
    except ValueError as e:
        print(f"  Note: {e}")
        print(f"  Add '{SOURCE_ID}' to source_registry.py to enable auto-finalization")

    # Move raw files to imported folder
    move_to_imported()

    print("\n" + "=" * 60)
    print("COMPLETE!")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
