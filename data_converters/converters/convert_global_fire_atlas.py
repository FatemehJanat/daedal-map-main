"""
Convert Global Fire Atlas data to parquet format for global wildfire display.

Creates output file:
- fires.parquet - Individual fire events with perimeter data (global)

Input: Global Fire Atlas data from Zenodo (https://zenodo.org/records/11400062)
- SHP_ignitions/ folder - Ignition points with fire metadata (primary data source)
- SHP_perimeters/ folder or .zip - Fire boundary polygons (optional, joins by fire_ID)

Data structure (annual shapefiles):
- GFA_v20240409_ignitions_YYYY.shp - Fire events with lat/lon, size, dates, etc.
- GFA_v20240409_perimeters_YYYY.shp - Fire boundary polygons

Output: Parquet file with worldwide wildfire data (2002-2024)

The Global Fire Atlas is derived from MODIS Collection 6.1 burned area product
and tracks individual fires globally with perimeters, ignition points, and
fire behavior metrics.

FUTURE: Fire Progression Animation
----------------------------------
The GeoTIFF_day_of_burn files contain daily burn progression data that could
be used to animate fire expansion over time. Each pixel has the day it burned,
allowing reconstruction of the fire's spread from ignition to final extent.
This would enable Mode D (Animated Perimeter) display with daily timesteps.

Usage:
    python convert_global_fire_atlas.py
"""
import pandas as pd
import geopandas as gpd
from pathlib import Path
import json
import zipfile
import sys

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from data_converters.base import save_parquet

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/global_fire_atlas")
IMPORTED_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/imported/global_fire_atlas")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/global/wildfires")
SOURCE_ID = "global_fire_atlas"

# Conversion constants
KM2_TO_ACRES = 247.105  # 1 km^2 = 247.105 acres

# Simplification tolerance for perimeter geometry (degrees)
# Fire perimeters don't need precise boundaries - using aggressive tolerance
# ~0.01 deg = ~1km at equator (matches "Countries" level in tolerance table)
SIMPLIFY_TOLERANCE = 0.01

# Minimum fire size to include (km^2) - 0 = keep all fires
# Frontend will filter by zoom level, so we store everything
MIN_FIRE_SIZE_KM2 = 0.0  # Keep all fires


def get_source_dir():
    """Get source directory - check raw first, then imported."""
    if RAW_DATA_DIR.exists():
        return RAW_DATA_DIR
    elif IMPORTED_DIR.exists():
        print(f"  Note: Using imported data from {IMPORTED_DIR}")
        return IMPORTED_DIR
    return RAW_DATA_DIR


def find_shapefiles_in_folder(folder_path):
    """Find all shapefiles in a folder."""
    if not folder_path.exists():
        return []
    return sorted(folder_path.glob("*.shp"))


def find_shapefile_in_zip(zip_path, pattern=""):
    """Find shapefile name inside a zip archive."""
    with zipfile.ZipFile(zip_path, 'r') as z:
        shp_files = [f for f in z.namelist() if f.endswith('.shp')]
        if pattern:
            shp_files = [f for f in shp_files if pattern.lower() in f.lower()]
        return sorted(shp_files)


def load_perimeters():
    """Load fire perimeter polygons from shapefile (optional - joins to ignitions)."""
    print("\nLoading perimeter polygons (optional)...")

    source_dir = get_source_dir()

    # Check for extracted folder first
    folder_candidates = [
        source_dir / "SHP_perimeters",
        source_dir / "perimeters",
    ]

    folder_path = None
    for candidate in folder_candidates:
        if candidate.exists() and any(candidate.glob("*.shp")):
            folder_path = candidate
            break

    if folder_path:
        # Load from extracted folder
        print(f"  Found: {folder_path.name}/ (extracted folder)")
        shp_files = find_shapefiles_in_folder(folder_path)
        print(f"  Shapefiles: {len(shp_files)} annual files")

        all_gdfs = []
        for shp_file in shp_files:
            try:
                year = shp_file.stem.split('_')[-1]
                print(f"    Loading {year}...", end=" ", flush=True)
                gdf = gpd.read_file(shp_file)
                gdf['file_year'] = int(year)
                all_gdfs.append(gdf)
                print(f"{len(gdf):,} perimeters")
            except Exception as e:
                print(f"Error: {e}")

    else:
        # Try zip file
        zip_candidates = ["SHP_perimeters.zip", "perimeters.zip"]
        zip_path = None
        for candidate in zip_candidates:
            test_path = source_dir / candidate
            if test_path.exists():
                zip_path = test_path
                break

        if not zip_path:
            for f in source_dir.glob("*perimeter*.zip"):
                zip_path = f
                break

        if not zip_path or not zip_path.exists():
            print("  Perimeters not available yet (still downloading?)")
            print("  Will create point-only output from ignitions data")
            return gpd.GeoDataFrame()

        print(f"  Found: {zip_path.name} (zip file)")
        shp_files = find_shapefile_in_zip(zip_path)
        print(f"  Shapefiles: {len(shp_files)} annual files")

        all_gdfs = []
        for shp_name in shp_files:
            try:
                year = shp_name.split('_')[-1].replace('.shp', '')
                print(f"    Loading {year}...", end=" ", flush=True)
                gdf = gpd.read_file(f"zip://{zip_path}!{shp_name}")
                gdf['file_year'] = int(year)
                all_gdfs.append(gdf)
                print(f"{len(gdf):,} perimeters")
            except Exception as e:
                print(f"Error: {e}")

    if not all_gdfs:
        return gpd.GeoDataFrame()

    combined = pd.concat(all_gdfs, ignore_index=True)
    combined = gpd.GeoDataFrame(combined, geometry='geometry', crs=all_gdfs[0].crs)

    print(f"  Total loaded: {len(combined):,} fire perimeters")
    print(f"  Columns: {list(combined.columns)}")

    return combined


def load_ignitions():
    """Load fire ignition points - the PRIMARY data source with all fire metadata."""
    print("\nLoading ignition points (primary data source)...")

    source_dir = get_source_dir()

    # Check for extracted folder first
    folder_candidates = [
        source_dir / "SHP_ignitions",
        source_dir / "ignitions",
    ]

    folder_path = None
    for candidate in folder_candidates:
        if candidate.exists() and any(candidate.glob("*.shp")):
            folder_path = candidate
            break

    if folder_path:
        # Load from extracted folder
        print(f"  Found: {folder_path.name}/ (extracted folder)")
        shp_files = find_shapefiles_in_folder(folder_path)
        print(f"  Shapefiles: {len(shp_files)} annual files")

        all_gdfs = []
        for shp_file in shp_files:
            try:
                year = shp_file.stem.split('_')[-1]  # Extract year from filename
                print(f"    Loading {year}...", end=" ", flush=True)
                gdf = gpd.read_file(shp_file)
                gdf['file_year'] = int(year)
                all_gdfs.append(gdf)
                print(f"{len(gdf):,} fires")
            except Exception as e:
                print(f"Error: {e}")

    else:
        # Fall back to zip file
        zip_candidates = ["SHP_ignitions.zip", "ignitions.zip"]
        zip_path = None
        for candidate in zip_candidates:
            test_path = source_dir / candidate
            if test_path.exists():
                zip_path = test_path
                break

        if not zip_path:
            for f in source_dir.glob("*ignition*.zip"):
                zip_path = f
                break

        if not zip_path or not zip_path.exists():
            print("  ERROR: Ignitions data not found!")
            return gpd.GeoDataFrame()

        print(f"  Found: {zip_path.name} (zip file)")
        shp_files = find_shapefile_in_zip(zip_path)

        all_gdfs = []
        for shp_name in shp_files:
            try:
                year = shp_name.split('_')[-1].replace('.shp', '')
                gdf = gpd.read_file(f"zip://{zip_path}!{shp_name}")
                gdf['file_year'] = int(year)
                all_gdfs.append(gdf)
            except Exception:
                pass

    if not all_gdfs:
        print("  ERROR: No data loaded from ignitions!")
        return gpd.GeoDataFrame()

    combined = pd.concat(all_gdfs, ignore_index=True)
    combined = gpd.GeoDataFrame(combined, geometry='geometry', crs=all_gdfs[0].crs)

    print(f"  Total loaded: {len(combined):,} fire events")
    print(f"  Columns: {list(combined.columns)}")

    return combined


def process_fires(ignitions_gdf, perimeters_gdf=None):
    """Process ignitions as primary data source, optionally join perimeter polygons."""
    print("\nProcessing fire data...")
    print(f"  Ignitions: {len(ignitions_gdf):,} fire events")

    # The ignitions file has these columns (from data inspection):
    # fire_ID, lat, lon, size, perimeter, start_date, start_DOY, end_date, end_DOY,
    # duration, fire_line, spread, speed, direction, direc_frac, MODIS_tile,
    # landcover, landc_frac, GFED_regio, geometry

    fires_gdf = ignitions_gdf.copy()

    # Rename columns to standard schema
    col_map = {
        'fire_ID': 'fire_id',
        'size': 'area_km2',  # size is in km^2
        'perimeter': 'perimeter_km',  # perimeter length, not geometry
        'duration': 'duration_days',
        'landcover': 'land_cover',
    }
    fires_gdf = fires_gdf.rename(columns=col_map)

    # Use ignition point coordinates directly
    fires_gdf['latitude'] = fires_gdf['lat']
    fires_gdf['longitude'] = fires_gdf['lon']

    # Convert area from km^2 to acres
    fires_gdf['burned_acres'] = fires_gdf['area_km2'] * KM2_TO_ACRES
    print(f"  Total area: {fires_gdf['burned_acres'].sum():,.0f} acres")

    # Filter by minimum size
    original_count = len(fires_gdf)
    fires_gdf = fires_gdf[fires_gdf['area_km2'] >= MIN_FIRE_SIZE_KM2].copy()
    print(f"  Filtered by min size ({MIN_FIRE_SIZE_KM2} km^2): {original_count:,} -> {len(fires_gdf):,}")

    # Parse dates and create timestamp
    fires_gdf['timestamp'] = pd.to_datetime(fires_gdf['start_date'], errors='coerce')

    # Extract year
    fires_gdf['year'] = fires_gdf['timestamp'].dt.year

    print(f"  Year range: {fires_gdf['year'].min()}-{fires_gdf['year'].max()}")

    # Join perimeter polygons if available
    if perimeters_gdf is not None and not perimeters_gdf.empty:
        print(f"\n  Joining perimeter polygons...")
        print(f"    Perimeters available: {len(perimeters_gdf):,}")

        # The perimeters should have fire_ID to match ignitions
        # Check what ID column exists in perimeters
        perim_id_col = None
        for col in ['fire_ID', 'fire_id', 'id', 'ID', 'FID']:
            if col in perimeters_gdf.columns:
                perim_id_col = col
                break

        if perim_id_col:
            # Simplify perimeter geometry for web display
            print(f"    Simplifying geometry (tolerance={SIMPLIFY_TOLERANCE} deg)...")
            perimeters_gdf['geometry'] = perimeters_gdf.geometry.simplify(
                SIMPLIFY_TOLERANCE, preserve_topology=True
            )

            # Create a lookup dict: fire_id -> geometry
            perim_lookup = dict(zip(
                perimeters_gdf[perim_id_col].astype(str),
                perimeters_gdf['geometry']
            ))

            # Match perimeters to fires
            fires_gdf['perimeter_geom'] = fires_gdf['fire_id'].astype(str).map(perim_lookup)
            matched = fires_gdf['perimeter_geom'].notna().sum()
            print(f"    Matched: {matched:,} / {len(fires_gdf):,} ({matched/len(fires_gdf)*100:.1f}%)")
        else:
            print(f"    WARNING: No ID column found in perimeters to match")
            fires_gdf['perimeter_geom'] = None
    else:
        print("\n  No perimeters available - fires will display as circles based on size")
        fires_gdf['perimeter_geom'] = None

    print(f"\n  Final fire count: {len(fires_gdf):,}")

    return fires_gdf


def geometry_to_geojson(geom):
    """Convert shapely geometry to GeoJSON string."""
    if geom is None or geom.is_empty:
        return None
    try:
        from shapely.geometry import mapping
        return json.dumps(mapping(geom))
    except Exception:
        return None


def create_fires_parquet(fires_gdf):
    """Create fires.parquet with individual fire events including perimeter geometry."""
    print("\nCreating fires.parquet...")

    # Convert perimeter geometry to GeoJSON strings (if available)
    print("  Converting perimeters to GeoJSON...")
    if 'perimeter_geom' in fires_gdf.columns:
        perimeter_geojson = fires_gdf['perimeter_geom'].apply(geometry_to_geojson)
    else:
        perimeter_geojson = pd.Series([None] * len(fires_gdf))

    valid_perimeters = perimeter_geojson.notna().sum()
    print(f"    Valid perimeters: {valid_perimeters:,} ({valid_perimeters/len(fires_gdf)*100:.1f}%)")

    # Build output dataframe with standard schema
    fires_out = pd.DataFrame({
        'event_id': fires_gdf['fire_id'].astype(str),
        'timestamp': fires_gdf['timestamp'],
        'latitude': fires_gdf['latitude'],
        'longitude': fires_gdf['longitude'],
        'burned_acres': fires_gdf['burned_acres'],
        'area_km2': fires_gdf['area_km2'],
        'duration_days': fires_gdf.get('duration_days'),
        'land_cover': fires_gdf.get('land_cover'),
        'perimeter': perimeter_geojson,
        'source': 'global_fire_atlas',  # Data source identifier
        'has_progression': True,  # GFA has day_of_burn GeoTIFFs for animation
    })

    # Round coordinates
    fires_out['latitude'] = pd.to_numeric(fires_out['latitude'], errors='coerce').round(4)
    fires_out['longitude'] = pd.to_numeric(fires_out['longitude'], errors='coerce').round(4)

    # Round acres
    fires_out['burned_acres'] = fires_out['burned_acres'].round(0)

    # Round area_km2
    fires_out['area_km2'] = fires_out['area_km2'].round(2)

    # Save using base utility
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "fires.parquet"
    save_parquet(fires_out, output_path, description="global fire events")

    # Report file size
    file_size_mb = output_path.stat().st_size / 1e6
    print(f"  Output file size: {file_size_mb:.1f}MB")

    return fires_out


def generate_metadata(fires_df):
    """Generate metadata.json for the dataset."""
    print("\nGenerating metadata.json...")

    years = pd.to_datetime(fires_df['timestamp'], errors='coerce').dt.year
    min_year = int(years.min()) if years.notna().any() else 2002
    max_year = int(years.max()) if years.notna().any() else 2024

    metadata = {
        "source_id": SOURCE_ID,
        "source_name": "Global Fire Atlas",
        "description": f"Global individual fire perimeters and characteristics ({min_year}-{max_year})",

        "source": {
            "name": "Global Fire Atlas (Andela et al.)",
            "url": "https://zenodo.org/records/11400062",
            "paper": "https://essd.copernicus.org/articles/11/529/2019/",
            "license": "CC BY 4.0"
        },

        "geographic_level": "global",
        "geographic_coverage": {
            "type": "global",
            "description": "Worldwide fire perimeters from MODIS burned area product"
        },

        "temporal_coverage": {
            "start": min_year,
            "end": max_year,
            "frequency": "event-based"
        },

        "files": {
            "fires": {
                "filename": "fires.parquet",
                "description": "Individual fire events with perimeter geometry",
                "record_type": "event",
                "record_count": len(fires_df),
                "has_geometry": True,
                "geometry_column": "perimeter",
                "geometry_type": "Polygon/MultiPolygon"
            }
        },

        "metrics": {
            "burned_acres": {
                "name": "Burned Area",
                "description": "Total area burned by fire",
                "unit": "acres",
                "file": "fires.parquet"
            },
            "area_km2": {
                "name": "Burned Area (km^2)",
                "description": "Total area burned by fire in square kilometers",
                "unit": "km^2",
                "file": "fires.parquet"
            },
            "duration_days": {
                "name": "Fire Duration",
                "description": "Number of days fire was active",
                "unit": "days",
                "file": "fires.parquet"
            }
        },

        "llm_summary": f"Global Fire Atlas wildfire data, {min_year}-{max_year}. "
                      f"{len(fires_df):,} fires >1 km^2. "
                      f"Derived from MODIS Collection 6.1 burned area product.",

        "processing": {
            "converter": "data_converters/converters/convert_global_fire_atlas.py",
            "last_run": pd.Timestamp.now().strftime("%Y-%m-%d"),
            "min_fire_size": f"{MIN_FIRE_SIZE_KM2} km^2 (~{MIN_FIRE_SIZE_KM2 * KM2_TO_ACRES:.0f} acres)",
            "simplification": f"{SIMPLIFY_TOLERANCE} degrees (~200m)"
        }
    }

    metadata_path = OUTPUT_DIR / "metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    print(f"  Saved: {metadata_path}")


def print_statistics(fires_df):
    """Print summary statistics."""
    print("\n" + "=" * 80)
    print("STATISTICS - Global Fire Atlas")
    print("=" * 80)

    fires_df = fires_df.copy()
    fires_df['year'] = pd.to_datetime(fires_df['timestamp'], errors='coerce').dt.year

    print(f"\nTotal fires: {len(fires_df):,}")
    if fires_df['year'].notna().any():
        print(f"Year range: {int(fires_df['year'].min())}-{int(fires_df['year'].max())}")

    if 'burned_acres' in fires_df.columns:
        total_acres = fires_df['burned_acres'].sum()
        print(f"Total acres burned: {total_acres:,.0f}")
        print(f"Average fire size: {fires_df['burned_acres'].mean():,.0f} acres")
        print(f"Median fire size: {fires_df['burned_acres'].median():,.0f} acres")
        print(f"Largest fire: {fires_df['burned_acres'].max():,.0f} acres")

    if 'area_km2' in fires_df.columns:
        print(f"Total km^2 burned: {fires_df['area_km2'].sum():,.0f}")

    print("\nFires by Year (sample):")
    if fires_df['year'].notna().any():
        yearly = fires_df.groupby('year').agg({
            'event_id': 'count',
            'burned_acres': 'sum'
        }).rename(columns={'event_id': 'count'})

        # Show first 5, last 5
        for year in list(yearly.index[:5]) + ['...'] + list(yearly.index[-5:]):
            if year == '...':
                print("  ...")
            else:
                row = yearly.loc[year]
                print(f"  {int(year)}: {int(row['count']):,} fires, {row['burned_acres']:,.0f} acres")

    print("\nLargest Fires:")
    if 'burned_acres' in fires_df.columns:
        largest = fires_df.nlargest(10, 'burned_acres')
        for _, row in largest.iterrows():
            year = int(row['year']) if pd.notna(row.get('year')) else '?'
            lat = row.get('latitude', '?')
            lon = row.get('longitude', '?')
            print(f"  {year}: {row['burned_acres']:,.0f} acres at ({lat}, {lon})")

    if 'land_cover' in fires_df.columns and fires_df['land_cover'].notna().any():
        print("\nFires by Land Cover:")
        lc_counts = fires_df['land_cover'].value_counts().head(10)
        for lc, count in lc_counts.items():
            print(f"  {lc}: {count:,}")


def process_year(year, ignitions_path, perimeters_path=None):
    """Process a single year's data with memory efficiency."""
    print(f"\n  Processing {year}...")

    # Load ignitions for this year
    ign_gdf = gpd.read_file(ignitions_path)
    print(f"    Loaded {len(ign_gdf):,} ignitions")

    # Rename columns
    col_map = {
        'fire_ID': 'fire_id',
        'size': 'area_km2',
        'perimeter': 'perimeter_km',
        'duration': 'duration_days',
        'landcover': 'land_cover',
    }
    ign_gdf = ign_gdf.rename(columns=col_map)

    # Filter by minimum size BEFORE any other processing
    original = len(ign_gdf)
    ign_gdf = ign_gdf[ign_gdf['area_km2'] >= MIN_FIRE_SIZE_KM2]
    print(f"    Filtered: {original:,} -> {len(ign_gdf):,} (>={MIN_FIRE_SIZE_KM2} km^2)")

    if len(ign_gdf) == 0:
        return pd.DataFrame()

    # Extract needed columns
    fires_df = pd.DataFrame({
        'event_id': ign_gdf['fire_id'].astype(str),
        'timestamp': pd.to_datetime(ign_gdf['start_date'], errors='coerce'),
        'latitude': ign_gdf['lat'].round(4),
        'longitude': ign_gdf['lon'].round(4),
        'burned_acres': (ign_gdf['area_km2'] * KM2_TO_ACRES).round(0),
        'area_km2': ign_gdf['area_km2'].round(2),
        'duration_days': ign_gdf.get('duration_days'),
        'land_cover': ign_gdf.get('land_cover'),
        'source': 'global_fire_atlas',
        'has_progression': True,
    })

    # Load and join perimeters if available
    perimeter_geojson = [None] * len(fires_df)

    if perimeters_path and perimeters_path.exists():
        try:
            perim_gdf = gpd.read_file(perimeters_path)
            print(f"    Loaded {len(perim_gdf):,} perimeters")

            # Get fire_ID column
            perim_id_col = 'fire_ID' if 'fire_ID' in perim_gdf.columns else 'fire_id'

            # Filter perimeters to only fires we're keeping (>= MIN_SIZE)
            fire_ids_kept = set(fires_df['event_id'].values)
            perim_gdf = perim_gdf[perim_gdf[perim_id_col].astype(str).isin(fire_ids_kept)]
            print(f"    Matched perimeters: {len(perim_gdf):,}")

            # Simplify geometry
            perim_gdf['geometry'] = perim_gdf.geometry.simplify(
                SIMPLIFY_TOLERANCE, preserve_topology=True
            )

            # Create lookup: fire_id -> GeoJSON string
            perim_lookup = {}
            for _, row in perim_gdf.iterrows():
                fid = str(row[perim_id_col])
                geom = row.geometry
                if geom and not geom.is_empty:
                    try:
                        from shapely.geometry import mapping
                        perim_lookup[fid] = json.dumps(mapping(geom))
                    except:
                        pass

            # Apply to fires
            perimeter_geojson = fires_df['event_id'].map(lambda x: perim_lookup.get(x))
            matched = perimeter_geojson.notna().sum()
            print(f"    Perimeters matched: {matched:,} ({matched/len(fires_df)*100:.1f}%)")

        except Exception as e:
            print(f"    Perimeter error: {e}")

    fires_df['perimeter'] = perimeter_geojson

    print(f"    Output rows: {len(fires_df):,}")
    return fires_df


def main():
    """Main conversion logic - processes year by year with incremental saves."""
    print("=" * 60)
    print("Global Fire Atlas Converter (Incremental Mode)")
    print("=" * 60)

    source_dir = get_source_dir()
    ign_folder = source_dir / "SHP_ignitions"
    perim_folder = source_dir / "SHP_perimeters"

    if not ign_folder.exists():
        print(f"\nERROR: Ignitions folder not found: {ign_folder}")
        return 1

    # Find all ignition shapefiles (newest first for priority)
    ign_files = sorted(ign_folder.glob("*.shp"), reverse=True)
    if not ign_files:
        print(f"\nERROR: No shapefiles found in {ign_folder}")
        return 1

    print(f"\nFound {len(ign_files)} annual datasets")
    print(f"Perimeters available: {perim_folder.exists()}")

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Check which years already processed (for resumability)
    years_dir = OUTPUT_DIR / "by_year"
    years_dir.mkdir(exist_ok=True)
    already_done = set()
    for f in years_dir.glob("*.parquet"):
        year = f.stem.replace("fires_", "")
        already_done.add(year)

    if already_done:
        print(f"Resuming: {len(already_done)} years already processed")

    # Process year by year with incremental saves
    total_fires = 0
    processed_years = []

    for ign_path in ign_files:
        # Extract year from filename
        year = ign_path.stem.split('_')[-1]

        # Skip if already done
        if year in already_done:
            # Load count from existing file
            existing = pd.read_parquet(years_dir / f"fires_{year}.parquet", columns=['event_id'])
            total_fires += len(existing)
            processed_years.append(year)
            print(f"\n  Skipping {year} (already done, {len(existing):,} fires)")
            continue

        # Find matching perimeter file
        perim_path = None
        if perim_folder.exists():
            perim_candidates = list(perim_folder.glob(f"*{year}.shp"))
            if perim_candidates:
                perim_path = perim_candidates[0]

        # Process this year
        year_df = process_year(year, ign_path, perim_path)

        if not year_df.empty:
            # Save this year's data immediately
            year_output = years_dir / f"fires_{year}.parquet"
            year_df.to_parquet(year_output, index=False)
            print(f"    Saved: {year_output.name} ({year_output.stat().st_size/1e6:.1f}MB)")

            total_fires += len(year_df)
            processed_years.append(year)

    print(f"\n{'='*60}")
    print(f"All years processed: {len(processed_years)} files")
    print(f"Total fires: {total_fires:,}")

    # Merge all year files into one
    print(f"\nMerging year files into fires.parquet...")
    all_dfs = []
    for year in sorted(processed_years):
        df = pd.read_parquet(years_dir / f"fires_{year}.parquet")
        all_dfs.append(df)

    fires_out = pd.concat(all_dfs, ignore_index=True)
    output_path = OUTPUT_DIR / "fires.parquet"
    fires_out.to_parquet(output_path, index=False)

    file_size_mb = output_path.stat().st_size / 1e6
    print(f"Output file size: {file_size_mb:.1f}MB")

    # Print statistics
    print_statistics(fires_out)

    # Generate metadata
    generate_metadata(fires_out)

    print("\n" + "=" * 60)
    print("COMPLETE!")
    print("=" * 60)
    print(f"\nOutput: {OUTPUT_DIR}")
    print(f"Files: fires.parquet, metadata.json")
    print(f"Year files: {years_dir}/ (can be deleted after verification)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
