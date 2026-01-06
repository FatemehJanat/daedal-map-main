"""
Convert NOAA Tsunami Database to parquet format.

Creates two output files:
1. events.parquet - Individual tsunami events with source location
2. USA.parquet - County-year aggregated statistics (based on runup locations)

Input: JSON files from NOAA NCEI tsunami database
Output: Two parquet files with tsunami data

Usage:
    python convert_tsunami.py
"""
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import geopandas as gpd
from pathlib import Path
from shapely.geometry import Point
import json
from shapely.geometry import shape

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/noaa/tsunami")
GEOMETRY_PATH = Path("C:/Users/Bryan/Desktop/county-map-data/geometry/USA.parquet")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA/tsunamis")

# State FIPS to abbreviation mapping
STATE_FIPS = {
    '01': 'AL', '02': 'AK', '04': 'AZ', '05': 'AR', '06': 'CA',
    '08': 'CO', '09': 'CT', '10': 'DE', '11': 'DC', '12': 'FL',
    '13': 'GA', '15': 'HI', '16': 'ID', '17': 'IL', '18': 'IN',
    '19': 'IA', '20': 'KS', '21': 'KY', '22': 'LA', '23': 'ME',
    '24': 'MD', '25': 'MA', '26': 'MI', '27': 'MN', '28': 'MS',
    '29': 'MO', '30': 'MT', '31': 'NE', '32': 'NV', '33': 'NH',
    '34': 'NJ', '35': 'NM', '36': 'NY', '37': 'NC', '38': 'ND',
    '39': 'OH', '40': 'OK', '41': 'OR', '42': 'PA', '44': 'RI',
    '45': 'SC', '46': 'SD', '47': 'TN', '48': 'TX', '49': 'UT',
    '50': 'VT', '51': 'VA', '53': 'WA', '54': 'WV', '55': 'WI',
    '56': 'WY', '72': 'PR'
}

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


def fips_to_loc_id(fips_code):
    """Convert 5-digit FIPS code to loc_id format."""
    fips_str = str(fips_code).zfill(5)
    state_fips = fips_str[:2]
    state_abbr = STATE_FIPS.get(state_fips)

    if not state_abbr:
        return None

    return f"USA-{state_abbr}-{int(fips_str)}"


def get_water_body_loc_id(lat, lon):
    """
    Determine water body loc_id based on coordinates.

    Uses simplified bounding boxes to assign ocean/sea codes.
    Water body codes follow ISO 3166-1 X-prefix convention.
    """
    if pd.isna(lat) or pd.isna(lon):
        return None

    # Pacific Ocean (west of Americas, or far west Pacific)
    if lon < -100 or lon > 100:
        return "XOP-0"

    # Gulf of Mexico
    if 18 <= lat <= 31 and -98 <= lon <= -80:
        return "XSG-0"

    # Caribbean Sea
    if 9 <= lat <= 22 and -89 <= lon <= -59:
        return "XSC-0"

    # Atlantic Ocean (default for western Atlantic)
    if -100 <= lon <= 0:
        return "XOA-0"

    # Indian Ocean
    if 30 <= lon <= 100 and lat < 30:
        return "XOI-0"

    # Fallback
    return "XOA-0"


def load_counties():
    """Load county boundaries from geometry parquet."""
    print("Loading county boundaries...")

    # Read geometry parquet
    df = pd.read_parquet(GEOMETRY_PATH)

    # Filter to counties (admin_level 2)
    counties = df[df['admin_level'] == 2].copy()

    # Parse GeoJSON geometry
    counties['geom'] = counties['geometry'].apply(
        lambda x: shape(json.loads(x)) if pd.notna(x) else None
    )

    # Create GeoDataFrame
    gdf = gpd.GeoDataFrame(counties, geometry='geom', crs='EPSG:4326')

    print(f"  Loaded {len(gdf)} counties")
    return gdf


def load_tsunami_data():
    """Load tsunami events and runups from JSON files."""
    print("\nLoading tsunami data...")

    # Load events
    events_path = RAW_DATA_DIR / "tsunami_events.json"
    with open(events_path, 'r', encoding='utf-8') as f:
        events_data = json.load(f)

    events_df = pd.DataFrame(events_data['events'])
    print(f"  Total events: {len(events_df):,}")

    # Load runups
    runups_path = RAW_DATA_DIR / "tsunami_runups.json"
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
    Geocode runup locations to counties.

    Uses two-pass matching:
    1. Strict 'within' for points inside county polygons
    2. Nearest neighbor for coastal points within 12 nautical miles (territorial waters)
    """
    print("\nGeocoding runups to counties...")

    # Territorial waters threshold: 12 nautical miles = 22.2 km = ~0.2 degrees
    TERRITORIAL_WATERS_DEG = 0.2

    # Filter to runups with coordinates
    runups_with_coords = runups_df.dropna(subset=['latitude', 'longitude']).copy()
    print(f"  Runups with coordinates: {len(runups_with_coords):,}")

    if len(runups_with_coords) == 0:
        return runups_df

    # Create geometry
    geometry = [Point(xy) for xy in zip(runups_with_coords['longitude'],
                                         runups_with_coords['latitude'])]
    gdf = gpd.GeoDataFrame(runups_with_coords, geometry=geometry, crs="EPSG:4326")

    # Pass 1: Strict 'within' spatial join
    gdf_with_counties = gpd.sjoin(gdf, counties_gdf[['loc_id', 'geom']].set_geometry('geom'),
                                   how='left', predicate='within')

    strict_matched = gdf_with_counties['loc_id'].notna().sum()
    print(f"  Pass 1 (within): {strict_matched:,} matched")

    # Pass 2: Nearest neighbor for unmatched coastal points
    unmatched_mask = gdf_with_counties['loc_id'].isna()
    if unmatched_mask.any():
        unmatched_indices = gdf_with_counties[unmatched_mask].index
        unmatched_gdf = gdf_with_counties.loc[unmatched_indices].copy()

        # Use sjoin_nearest to find closest county
        nearest = gpd.sjoin_nearest(
            unmatched_gdf[['geometry']],
            counties_gdf[['loc_id', 'geom']].set_geometry('geom'),
            how='left',
            distance_col='dist_to_county'
        )

        # Only assign if within territorial waters (12 nm)
        within_territorial = nearest['dist_to_county'] <= TERRITORIAL_WATERS_DEG
        nearest_matched = within_territorial.sum()

        # Update loc_id for points within territorial waters using index alignment
        for idx in nearest[within_territorial].index:
            gdf_with_counties.loc[idx, 'loc_id'] = nearest.loc[idx, 'loc_id']

        print(f"  Pass 2 (nearest, <12nm): {nearest_matched:,} matched")

        # Pass 3: Assign water body codes for points beyond territorial waters
        still_unmatched_mask = gdf_with_counties['loc_id'].isna()
        if still_unmatched_mask.any():
            gdf_with_counties.loc[still_unmatched_mask, 'loc_id'] = \
                gdf_with_counties.loc[still_unmatched_mask].apply(
                    lambda row: get_water_body_loc_id(row['latitude'], row['longitude']),
                    axis=1
                )
            water_assigned = still_unmatched_mask.sum()
            print(f"  Pass 3 (water body, >12nm): {water_assigned:,} assigned")

    total_matched = gdf_with_counties['loc_id'].notna().sum()
    print(f"  Total assigned: {total_matched:,} ({total_matched/len(gdf_with_counties)*100:.1f}%)")

    return gdf_with_counties


def create_events_parquet(events_df, runups_df):
    """Create events.parquet with tsunami source events."""
    print("\nCreating events.parquet...")

    # Prepare events dataframe
    events_out = pd.DataFrame({
        'event_id': events_df['id'],
        'year': events_df['year'],
        'month': events_df.get('month', pd.NA),
        'day': events_df.get('day', pd.NA),
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

    # Assign water body loc_id for source events (most are in ocean)
    events_out['loc_id'] = events_out.apply(
        lambda row: get_water_body_loc_id(row['latitude'], row['longitude']),
        axis=1
    )

    # Count by water body
    water_counts = events_out['loc_id'].value_counts()
    print(f"  Source events by water body:")
    for loc_id, count in water_counts.head(5).items():
        print(f"    {loc_id}: {count:,}")

    # Define schema
    schema = pa.schema([
        ('event_id', pa.int64()),
        ('year', pa.int32()),
        ('month', pa.int32()),
        ('day', pa.int32()),
        ('latitude', pa.float32()),
        ('longitude', pa.float32()),
        ('country', pa.string()),
        ('location', pa.string()),
        ('cause_code', pa.int32()),
        ('cause', pa.string()),
        ('intensity', pa.float32()),
        ('max_water_height_m', pa.float32()),
        ('num_runups', pa.int32()),
        ('deaths_order', pa.int32()),
        ('damage_order', pa.int32()),
        ('eq_magnitude', pa.float32()),
        ('loc_id', pa.string())
    ])

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "events.parquet"

    table = pa.Table.from_pandas(events_out, schema=schema, preserve_index=False)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Saved: {size_mb:.2f} MB")
    print(f"  Events: {len(events_out):,}")

    return events_out


def create_runups_parquet(runups_df):
    """Create runups.parquet with coastal impact locations."""
    print("\nCreating runups.parquet...")

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

    # Define schema
    schema = pa.schema([
        ('runup_id', pa.int64()),
        ('event_id', pa.int64()),
        ('year', pa.int32()),
        ('month', pa.int32()),
        ('latitude', pa.float32()),
        ('longitude', pa.float32()),
        ('country', pa.string()),
        ('location', pa.string()),
        ('water_height_m', pa.float32()),
        ('horizontal_inundation_m', pa.float32()),
        ('dist_from_source_km', pa.float32()),
        ('deaths_order', pa.int32()),
        ('damage_order', pa.int32()),
        ('loc_id', pa.string())
    ])

    # Save
    output_path = OUTPUT_DIR / "runups.parquet"

    table = pa.Table.from_pandas(runups_out, schema=schema, preserve_index=False)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Saved: {size_mb:.2f} MB")
    print(f"  Runups: {len(runups_out):,}")

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
    """Save county aggregates to USA.parquet."""
    if df.empty:
        print("\n  Skipping USA.parquet (no data)")
        return None

    print("\nSaving USA.parquet...")

    # Define schema
    schema = pa.schema([
        ('loc_id', pa.string()),
        ('year', pa.int32()),
        ('runup_count', pa.int32()),
        ('event_count', pa.int32())
    ])

    # Save
    output_path = OUTPUT_DIR / "USA.parquet"

    table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Saved: {size_mb:.2f} MB")

    return output_path


def generate_metadata(events_df, runups_df, county_df):
    """Generate metadata.json for the dataset."""
    print("\nGenerating metadata.json...")

    # Year range
    min_year = int(events_df['year'].min()) if not events_df.empty else 0
    max_year = int(events_df['year'].max()) if not events_df.empty else 0

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
    if not events_df.empty:
        print(f"Year range: {events_df['year'].min()} to {events_df['year'].max()}")

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
    print("="*80)
    print("NOAA Tsunami Database - JSON to Parquet Converter")
    print("="*80)

    # Load county boundaries
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
    save_county_parquet(county_df)

    # Print statistics
    print_statistics(events_out, runups_out, county_df)

    # Generate metadata
    generate_metadata(events_out, runups_out, county_df)

    print("\n" + "="*80)
    print("COMPLETE!")
    print("="*80)
    print("\nOutput files:")
    print("  events.parquet: Tsunami source events with location")
    print("  runups.parquet: Coastal impact observations")
    print("  USA.parquet: County-year aggregated statistics")
    print("  metadata.json: Standard metadata format")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
