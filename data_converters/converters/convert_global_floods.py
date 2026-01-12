"""
Convert Global Flood Database and Dartmouth Flood Observatory data to parquet format.

Creates:
1. events.parquet - Flood events with metadata
2. geometries/ - GeoJSON files for flood extents (when available)

Sources:
- Global Flood Database (GFD): 913 events 2000-2018, MODIS-derived flood extents
  - Download: gsutil -m cp -r gs://gfd_v1_4 <local_dir>
  - Metadata: https://github.com/cloudtostreet/MODIS_GlobalFloodDatabase

- Dartmouth Flood Observatory (DFO): ~4500 events 1985-present, polygons
  - Download: dfo_polys_20191203.shp from GitHub repo

Usage:
    python convert_global_floods.py
"""
import pandas as pd
import numpy as np
import json
import sys
from pathlib import Path
from datetime import datetime

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from data_converters.base import save_parquet

# Try to import geopandas for shapefile reading
try:
    import geopandas as gpd
    HAS_GEOPANDAS = True
except ImportError:
    HAS_GEOPANDAS = False
    print("Warning: geopandas not available, shapefile processing disabled")

# Try to import rasterio for GeoTIFF reading
try:
    import rasterio
    from rasterio import features
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False
    print("Warning: rasterio not available, GeoTIFF processing disabled")

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/gfd")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/global/floods")
GEOMETRY_DIR = OUTPUT_DIR / "geometries"
SOURCE_ID = "global_floods"

# DFO Masterlist from Zenodo (has dates for 4,968 events 1985-2020)
# Source: https://zenodo.org/record/4139180
DFO_MASTERLIST_PATH = RAW_DATA_DIR / "DFO_masterlist.xlsx"

# GFD metadata CSV columns (from GitHub repo)
GFD_METADATA_COLS = {
    'DFO_ID': 'dfo_id',
    'GLIDE': 'glide_index',
    'DFO_COUNTRY': 'country',
    'DFO_CENTROID_X': 'longitude',
    'DFO_CENTROID_Y': 'latitude',
    'DFO_BEGAN': 'start_date',
    'DFO_ENDED': 'end_date',
    'DFO_DEAD': 'deaths',
    'DFO_DISPLACED': 'displaced',
    'DFO_SEVERITY': 'severity',
    'DFO_AREA': 'area_km2',
}


def load_dfo_shapefile():
    """Load DFO flood polygon shapefile."""
    if not HAS_GEOPANDAS:
        print("  Skipping shapefile - geopandas not available")
        return None

    shp_path = RAW_DATA_DIR / "dfo_polys_20191203.shp"
    if not shp_path.exists():
        print(f"  DFO shapefile not found: {shp_path}")
        return None

    print(f"  Loading DFO shapefile: {shp_path}")
    gdf = gpd.read_file(shp_path)
    print(f"  Loaded {len(gdf):,} flood polygons")

    return gdf


def load_gfd_metadata():
    """Load GFD metadata CSV with event details."""
    csv_path = RAW_DATA_DIR / "gfd_qcdatabase.csv"
    if not csv_path.exists():
        # Try alternate names
        csv_path = RAW_DATA_DIR / "gfd_qcdatabase_2019_08_01.csv"
    if not csv_path.exists():
        csv_path = RAW_DATA_DIR / "gfd_metadata.csv"

    if not csv_path.exists():
        print(f"  GFD metadata CSV not found in {RAW_DATA_DIR}")
        return None

    print(f"  Loading GFD metadata: {csv_path}")
    df = pd.read_csv(csv_path)
    print(f"  Loaded {len(df):,} event records")

    return df


def load_dfo_masterlist():
    """Load DFO masterlist from Zenodo with complete date coverage.

    This Excel file contains 4,968 flood events (1985-2020) with dates
    that can be used to fill in missing dates from the DFO shapefile.

    Returns dict mapping DFO ID to (start_date, end_date, country, deaths, displaced, severity)
    """
    if not DFO_MASTERLIST_PATH.exists():
        print(f"  DFO masterlist not found: {DFO_MASTERLIST_PATH}")
        print("    Download from: https://zenodo.org/record/4139180")
        return {}

    try:
        print(f"  Loading DFO masterlist: {DFO_MASTERLIST_PATH}")
        df = pd.read_excel(DFO_MASTERLIST_PATH, engine='openpyxl')
        print(f"  Loaded {len(df):,} events from Zenodo masterlist")

        # Create lookup dictionary by ID
        lookup = {}
        for _, row in df.iterrows():
            dfo_id = row.get('ID')
            if pd.isna(dfo_id):
                continue

            dfo_id = int(dfo_id)
            lookup[dfo_id] = {
                'start_date': parse_dfo_date(row.get('Began')),
                'end_date': parse_dfo_date(row.get('Ended')),
                'country': row.get('Country'),
                'deaths': row.get('Dead'),
                'displaced': row.get('Displaced'),
                'severity': row.get('Severity'),
                'area': row.get('Area'),
                'lat': row.get('lat'),
                'lon': row.get('long'),
            }

        # Count events with dates
        with_dates = sum(1 for v in lookup.values() if pd.notna(v['start_date']))
        print(f"  Masterlist events with dates: {with_dates:,}")

        return lookup

    except ImportError:
        print("  Warning: openpyxl not available for Excel reading")
        print("    Install with: pip install openpyxl")
        return {}
    except Exception as e:
        print(f"  Error loading masterlist: {e}")
        return {}


def load_gfd_geotiffs():
    """List available GFD GeoTIFF files."""
    geotiff_dir = RAW_DATA_DIR / "gfd_v1_4"
    if not geotiff_dir.exists():
        # Try alternate location
        geotiff_dir = RAW_DATA_DIR / "geotiffs"

    if not geotiff_dir.exists():
        print(f"  GeoTIFF directory not found: {geotiff_dir}")
        return {}

    # Find all .tif files and map by DFO ID
    geotiff_map = {}
    tif_files = list(geotiff_dir.glob("**/*.tif"))

    for tif_path in tif_files:
        # Extract DFO ID from filename (format varies)
        # Examples: DFO_1234_*.tif or similar
        name = tif_path.stem
        parts = name.split('_')
        for part in parts:
            if part.isdigit():
                dfo_id = int(part)
                geotiff_map[dfo_id] = tif_path
                break

    print(f"  Found {len(geotiff_map):,} GeoTIFF files")
    return geotiff_map


def parse_dfo_date(date_str):
    """Parse DFO date string to datetime."""
    if pd.isna(date_str):
        return pd.NaT

    date_str = str(date_str).strip()

    # Try various formats
    formats = [
        '%Y-%m-%d',
        '%m/%d/%Y',
        '%d-%b-%y',
        '%d-%b-%Y',
        '%Y%m%d',
    ]

    for fmt in formats:
        try:
            return pd.to_datetime(date_str, format=fmt)
        except:
            pass

    # Last resort - let pandas try
    try:
        return pd.to_datetime(date_str)
    except:
        return pd.NaT


def extract_flood_polygon_from_geotiff(tif_path, output_geojson_path):
    """Extract flood extent polygon from GeoTIFF and save as GeoJSON."""
    if not HAS_RASTERIO:
        return None

    try:
        with rasterio.open(tif_path) as src:
            # Read the 'flooded' band (band 1)
            flooded = src.read(1)

            # Create binary mask (flooded pixels = 1)
            mask = (flooded == 1).astype(np.uint8)

            # Skip if no flood pixels
            if mask.sum() == 0:
                return None

            # Vectorize to polygons
            shapes = list(features.shapes(mask, transform=src.transform))

            # Filter to flooded areas (value == 1)
            flood_shapes = [shape for shape, value in shapes if value == 1]

            if not flood_shapes:
                return None

            # Create GeoJSON
            geojson = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": shape,
                        "properties": {}
                    }
                    for shape in flood_shapes
                ]
            }

            # Save to file
            with open(output_geojson_path, 'w') as f:
                json.dump(geojson, f)

            return output_geojson_path

    except Exception as e:
        print(f"    Error processing {tif_path}: {e}")
        return None


def extract_duration_bands_from_geotiff(tif_path):
    """Extract duration band statistics from GeoTIFF."""
    if not HAS_RASTERIO:
        return None

    try:
        with rasterio.open(tif_path) as src:
            # Read duration band (band 2)
            duration = src.read(2)

            # Get pixel area in km2 (approximate)
            pixel_area_km2 = abs(src.transform.a * src.transform.e) * (111.32 ** 2) / 1e6

            # Calculate area by duration
            bands = []
            duration_ranges = [
                (1, 3),
                (4, 7),
                (8, 14),
                (15, None)  # 15+ days
            ]

            for days_min, days_max in duration_ranges:
                if days_max:
                    mask = (duration >= days_min) & (duration <= days_max)
                else:
                    mask = (duration >= days_min)

                area = mask.sum() * pixel_area_km2

                if area > 0:
                    bands.append({
                        "days_min": days_min,
                        "days_max": days_max,
                        "area_km2": round(area, 2)
                    })

            return bands if bands else None

    except Exception as e:
        print(f"    Error extracting duration bands: {e}")
        return None


def process_gfd_events(gfd_df, geotiff_map):
    """Process GFD metadata into events dataframe."""
    print("\nProcessing GFD events...")

    # Debug: show actual columns
    print(f"  CSV columns: {list(gfd_df.columns)}")

    events = []

    for idx, row in gfd_df.iterrows():
        # Column name is 'ID' in the actual CSV
        dfo_id = row.get('ID')
        if pd.isna(dfo_id):
            continue

        dfo_id = int(dfo_id)
        event_id = f"GFD-{dfo_id}"

        # Parse dates - actual column names are 'Began' and 'Ended'
        start_date = parse_dfo_date(row.get('Began'))
        end_date = parse_dfo_date(row.get('Ended'))

        # Calculate duration
        duration_days = None
        if pd.notna(start_date) and pd.notna(end_date):
            duration_days = (end_date - start_date).days
            if duration_days < 0:
                duration_days = None

        # Get coordinates - actual column names are 'lat' and 'long'
        lat = row.get('lat')
        lon = row.get('long')

        # Get country - actual column name is 'Country'
        country = row.get('Country')

        # Get impact metrics - actual column names
        deaths = row.get('Dead')
        displaced = row.get('Displaced')
        severity = row.get('Severity')
        area = row.get('Area')

        # Check for GeoTIFF
        has_geotiff = dfo_id in geotiff_map

        # Check for embedded geometry in CSV
        has_csv_geom = pd.notna(row.get('geometry'))

        event = {
            'event_id': event_id,
            'timestamp': start_date,
            'end_timestamp': end_date,
            'year': start_date.year if pd.notna(start_date) else None,
            'latitude': float(lat) if pd.notna(lat) else None,
            'longitude': float(lon) if pd.notna(lon) else None,
            'country': str(country) if pd.notna(country) else None,
            'loc_id': None,  # Will be assigned later via spatial join
            'area_km2': float(area) if pd.notna(area) else None,
            'duration_days': int(duration_days) if pd.notna(duration_days) else None,
            'severity': int(severity) if pd.notna(severity) else None,
            'deaths': int(deaths) if pd.notna(deaths) else None,
            'displaced': int(displaced) if pd.notna(displaced) else None,
            'damage_usd': None,  # Not in GFD metadata
            'source': 'GFD',
            'dfo_id': dfo_id,
            'glide_index': row.get('GlideNumber'),
            'has_geometry': has_geotiff or has_csv_geom,
            'has_progression': has_geotiff,  # Only GeoTIFFs have duration bands
        }

        events.append(event)

    print(f"  Processed {len(events):,} GFD events")
    return pd.DataFrame(events)


def process_dfo_polygons(dfo_gdf, gfd_events_df, masterlist_lookup=None):
    """Process DFO shapefile polygons, adding events not in GFD.

    Args:
        dfo_gdf: GeoDataFrame of DFO polygons
        gfd_events_df: DataFrame of GFD events (to avoid duplicates)
        masterlist_lookup: Dict of DFO ID -> metadata from Zenodo masterlist
    """
    if dfo_gdf is None:
        return pd.DataFrame()

    if masterlist_lookup is None:
        masterlist_lookup = {}

    print("\nProcessing DFO polygon events...")

    # Get DFO IDs already in GFD (handle empty dataframe)
    if not gfd_events_df.empty and 'dfo_id' in gfd_events_df.columns:
        gfd_dfo_ids = set(gfd_events_df['dfo_id'].dropna().astype(int).tolist())
    else:
        gfd_dfo_ids = set()

    print(f"  GFD has {len(gfd_dfo_ids):,} DFO IDs, checking {len(dfo_gdf):,} DFO polygons")
    print(f"  Masterlist has {len(masterlist_lookup):,} events for date lookup")

    events = []
    dates_from_masterlist = 0

    for idx, row in dfo_gdf.iterrows():
        # Column name is 'ID' in shapefile
        dfo_id = row.get('ID')
        if pd.isna(dfo_id):
            continue

        dfo_id = int(dfo_id)

        # Skip if already in GFD
        if dfo_id in gfd_dfo_ids:
            continue

        event_id = f"DFO-{dfo_id}"

        # Parse dates - columns are 'Began' and 'Ended'
        start_date = parse_dfo_date(row.get('Began'))
        end_date = parse_dfo_date(row.get('Ended'))

        # If dates are missing, try to get from masterlist
        if pd.isna(start_date) and dfo_id in masterlist_lookup:
            ml_data = masterlist_lookup[dfo_id]
            start_date = ml_data['start_date']
            end_date = ml_data['end_date']
            if pd.notna(start_date):
                dates_from_masterlist += 1

        # Calculate duration
        duration_days = None
        if pd.notna(start_date) and pd.notna(end_date):
            duration_days = (end_date - start_date).days
            if duration_days < 0:
                duration_days = None

        # Get centroid from geometry or use lat/long columns
        geom = row.geometry
        if geom is not None and not geom.is_empty:
            centroid = geom.centroid
            lat = centroid.y
            lon = centroid.x
        else:
            lat = row.get('lat')
            lon = row.get('long')

        # Get country
        country = row.get('Country')

        # Get impact metrics
        deaths = row.get('Dead')
        displaced = row.get('Displaced')
        severity = row.get('Severity')
        area = row.get('Area')

        event = {
            'event_id': event_id,
            'timestamp': start_date,
            'end_timestamp': end_date,
            'year': start_date.year if pd.notna(start_date) else None,
            'latitude': float(lat) if pd.notna(lat) else None,
            'longitude': float(lon) if pd.notna(lon) else None,
            'country': str(country) if pd.notna(country) else None,
            'loc_id': None,
            'area_km2': float(area) if pd.notna(area) else None,
            'duration_days': int(duration_days) if pd.notna(duration_days) else None,
            'severity': int(severity) if pd.notna(severity) else None,
            'deaths': int(deaths) if pd.notna(deaths) else None,
            'displaced': int(displaced) if pd.notna(displaced) else None,
            'damage_usd': None,
            'source': 'DFO',
            'dfo_id': dfo_id,
            'glide_index': row.get('GlideNumbe'),  # Truncated column name in shapefile
            'has_geometry': True,  # DFO has polygons
            'has_progression': False,  # DFO doesn't have duration bands
        }

        events.append(event)

    print(f"  Added {len(events):,} DFO-only events (not in GFD)")
    print(f"  Dates filled from Zenodo masterlist: {dates_from_masterlist:,}")
    return pd.DataFrame(events)


def export_geometries(dfo_gdf, geotiff_map, events_df):
    """Export flood extent geometries to GeoJSON files."""
    print("\nExporting geometries...")

    GEOMETRY_DIR.mkdir(parents=True, exist_ok=True)

    exported_count = 0
    duration_count = 0

    # Get set of GFD IDs from events
    gfd_ids = set()
    if not events_df.empty and 'dfo_id' in events_df.columns:
        gfd_events = events_df[events_df['source'] == 'GFD']
        if not gfd_events.empty:
            gfd_ids = set(gfd_events['dfo_id'].dropna().astype(int).tolist())

    # Export DFO polygons
    if dfo_gdf is not None and HAS_GEOPANDAS:
        for idx, row in dfo_gdf.iterrows():
            dfo_id = row.get('ID')
            if pd.isna(dfo_id):
                continue

            dfo_id = int(dfo_id)
            geom = row.geometry

            if geom is None or geom.is_empty:
                continue

            # Determine event_id (GFD or DFO prefix)
            if dfo_id in gfd_ids:
                event_id = f"GFD-{dfo_id}"
            else:
                event_id = f"DFO-{dfo_id}"

            # Export polygon
            geojson_path = GEOMETRY_DIR / f"flood_{event_id}.geojson"

            geojson = {
                "type": "Feature",
                "properties": {
                    "event_id": event_id,
                    "dfo_id": dfo_id
                },
                "geometry": geom.__geo_interface__
            }

            with open(geojson_path, 'w') as f:
                json.dump(geojson, f)

            exported_count += 1

    # Export GFD duration bands (if rasterio available)
    if HAS_RASTERIO and geotiff_map:
        print("  Extracting duration bands from GeoTIFFs...")
        for dfo_id, tif_path in geotiff_map.items():
            event_id = f"GFD-{dfo_id}"

            bands = extract_duration_bands_from_geotiff(tif_path)

            if bands:
                duration_path = GEOMETRY_DIR / f"flood_{event_id}_duration.json"

                duration_data = {
                    "event_id": event_id,
                    "bands": bands
                }

                with open(duration_path, 'w') as f:
                    json.dump(duration_data, f)

                duration_count += 1

    print(f"  Exported {exported_count:,} geometry files")
    print(f"  Exported {duration_count:,} duration band files")


def print_statistics(events_df):
    """Print summary statistics."""
    print("\n" + "=" * 60)
    print("STATISTICS")
    print("=" * 60)

    print(f"\nTotal events: {len(events_df):,}")

    # By source
    print("\nBy source:")
    for source, count in events_df['source'].value_counts().items():
        print(f"  {source}: {count:,}")

    # Year range
    year_valid = events_df['year'].dropna()
    if len(year_valid) > 0:
        print(f"\nYear range: {int(year_valid.min())} to {int(year_valid.max())}")

    # Top countries
    print("\nTop 10 countries:")
    for country, count in events_df['country'].value_counts().head(10).items():
        print(f"  {country}: {count:,}")

    # Severity distribution
    print("\nSeverity distribution:")
    severity_counts = events_df['severity'].value_counts().sort_index()
    for sev, count in severity_counts.items():
        if pd.notna(sev):
            label = "Large" if sev == 1 else "Very Large" if sev == 2 else f"Level {int(sev)}"
            print(f"  {label}: {count:,}")

    # Geometry coverage
    has_geom = events_df['has_geometry'].sum()
    has_prog = events_df['has_progression'].sum()
    print(f"\nGeometry coverage:")
    print(f"  Events with geometry: {has_geom:,} ({100*has_geom/len(events_df):.1f}%)")
    print(f"  Events with duration bands: {has_prog:,} ({100*has_prog/len(events_df):.1f}%)")

    # Impact totals
    total_deaths = events_df['deaths'].sum()
    total_displaced = events_df['displaced'].sum()
    print(f"\nTotal impact:")
    print(f"  Deaths: {int(total_deaths):,}" if pd.notna(total_deaths) else "  Deaths: N/A")
    print(f"  Displaced: {int(total_displaced):,}" if pd.notna(total_displaced) else "  Displaced: N/A")


def generate_metadata(events_df):
    """Generate metadata.json for the dataset."""
    print("\nGenerating metadata.json...")

    year_valid = events_df['year'].dropna()
    min_year = int(year_valid.min()) if len(year_valid) > 0 else 1985
    max_year = int(year_valid.max()) if len(year_valid) > 0 else 2018

    # Convert counts to native Python ints
    event_count = int(len(events_df))
    geom_count = int(events_df['has_geometry'].sum())

    metadata = {
        "source_id": SOURCE_ID,
        "source_name": "Global Flood Database + Dartmouth Flood Observatory",
        "source_urls": [
            "https://global-flood-database.cloudtostreet.ai/",
            "https://floodobservatory.colorado.edu/"
        ],
        "license": "Academic/Research use",
        "description": f"Global flood events {min_year}-{max_year} with satellite-derived flood extents",

        "geographic_level": "global",
        "geographic_coverage": {
            "type": "global",
            "description": "Major flood events worldwide"
        },

        "temporal_coverage": {
            "start": min_year,
            "end": max_year,
            "frequency": "event-based"
        },

        "files": {
            "events": {
                "filename": "events.parquet",
                "description": "Flood events with metadata and impact data",
                "record_type": "event",
                "record_count": event_count
            },
            "geometries": {
                "directory": "geometries/",
                "description": "GeoJSON flood extent polygons and duration band data",
                "file_count": geom_count
            }
        },

        "metrics": {
            "area_km2": {
                "name": "Flood Area",
                "description": "Maximum flooded area in square kilometers",
                "unit": "km2"
            },
            "duration_days": {
                "name": "Duration",
                "description": "Flood event duration in days",
                "unit": "days"
            },
            "severity": {
                "name": "DFO Severity",
                "description": "1=Large event, 2=Very large event",
                "unit": "category"
            },
            "deaths": {
                "name": "Deaths",
                "description": "Estimated fatalities",
                "unit": "count"
            },
            "displaced": {
                "name": "Displaced",
                "description": "Estimated displaced persons",
                "unit": "count"
            }
        },

        "llm_summary": f"Global Flood Database, {min_year}-{max_year}. "
                      f"{event_count:,} flood events with satellite-derived flood extents. "
                      f"Includes duration bands for animation of flood progression.",

        "processing": {
            "converter": "data_converters/converters/convert_global_floods.py",
            "last_run": pd.Timestamp.now().strftime("%Y-%m-%d")
        }
    }

    metadata_path = OUTPUT_DIR / "metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    print(f"  Saved: {metadata_path}")


def main():
    """Main conversion logic."""
    print("=" * 60)
    print("Global Flood Database Converter")
    print("=" * 60)

    # Check for source data
    if not RAW_DATA_DIR.exists():
        print(f"\nERROR: Source directory not found: {RAW_DATA_DIR}")
        print("\nTo download the data:")
        print("  1. GFD GeoTIFFs: gsutil -m cp -r gs://gfd_v1_4 " + str(RAW_DATA_DIR / "gfd_v1_4"))
        print("  2. DFO Shapefile: Download from https://github.com/cloudtostreet/MODIS_GlobalFloodDatabase")
        print("     - dfo_polys_20191203.shp")
        print("     - gfd_qcdatabase_2019_08_01.csv")
        return 1

    print(f"\nSource directory: {RAW_DATA_DIR}")

    # Load data sources
    print("\nLoading data sources...")

    # Load GFD metadata
    gfd_df = load_gfd_metadata()

    # Load DFO shapefile
    dfo_gdf = load_dfo_shapefile()

    # Load DFO masterlist from Zenodo (for filling missing dates)
    dfo_masterlist = load_dfo_masterlist()

    # List GeoTIFF files
    geotiff_map = load_gfd_geotiffs()

    if gfd_df is None and dfo_gdf is None:
        print("\nERROR: No data sources found")
        return 1

    # Process events
    events_list = []

    if gfd_df is not None:
        gfd_events = process_gfd_events(gfd_df, geotiff_map)
        events_list.append(gfd_events)
    else:
        gfd_events = pd.DataFrame()

    if dfo_gdf is not None:
        dfo_events = process_dfo_polygons(dfo_gdf, gfd_events, dfo_masterlist)
        if not dfo_events.empty:
            events_list.append(dfo_events)

    # Combine all events
    if not events_list:
        print("\nERROR: No events processed")
        return 1

    events_df = pd.concat(events_list, ignore_index=True)
    events_df = events_df.sort_values('timestamp').reset_index(drop=True)

    # Print statistics
    print_statistics(events_df)

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Export geometries
    export_geometries(dfo_gdf, geotiff_map, events_df)

    # Save events parquet
    print("\n" + "=" * 60)
    print("Saving outputs...")
    print("=" * 60)

    # Convert types for parquet
    events_df['timestamp'] = pd.to_datetime(events_df['timestamp'])
    events_df['end_timestamp'] = pd.to_datetime(events_df['end_timestamp'])
    events_df['year'] = events_df['year'].astype('Int32')
    events_df['latitude'] = events_df['latitude'].astype('float32')
    events_df['longitude'] = events_df['longitude'].astype('float32')
    events_df['area_km2'] = events_df['area_km2'].astype('float32')
    events_df['duration_days'] = events_df['duration_days'].astype('Int16')
    events_df['severity'] = events_df['severity'].astype('Int8')
    events_df['deaths'] = events_df['deaths'].astype('Int32')
    events_df['displaced'] = events_df['displaced'].astype('Int64')
    events_df['dfo_id'] = events_df['dfo_id'].astype('Int32')

    events_path = OUTPUT_DIR / "events.parquet"
    save_parquet(events_df, events_path, description="global flood events")

    # Generate metadata
    generate_metadata(events_df)

    print("\n" + "=" * 60)
    print("COMPLETE!")
    print("=" * 60)
    print(f"\nOutput: {OUTPUT_DIR}")
    print(f"  events.parquet: {len(events_df):,} events")
    print(f"  geometries/: flood extent polygons and duration bands")

    return 0


if __name__ == "__main__":
    sys.exit(main())
