"""
Convert Canada Drought Monitor GeoJSON files to snapshots.parquet

Reads monthly drought area polygons from Agriculture Canada and converts to
unified snapshot format for choropleth animation.

Input: Raw data/imported/canada/drought/{YEAR}/CDM_{YYMM}_D{0-4}_LR.geojson
Output: countries/CAN/drought/snapshots.parquet

Schema matches DISASTER_DISPLAY.md Drought Schema (Snapshots - Canada)

Optimizations for web delivery:
- Aggressive geometry simplification (0.05 degrees ~5km)
- Coordinate precision reduction (4 decimal places)
- Geometry validation and repair
- Efficient parquet compression
"""

import json
import pandas as pd
import geopandas as gpd
from pathlib import Path
from datetime import datetime, timedelta
from shapely.geometry import shape, mapping
from shapely.validation import make_valid
from shapely import wkt
import warnings

# Suppress shapely warnings during processing
warnings.filterwarnings('ignore', category=RuntimeWarning)

# Severity mapping
SEVERITY_MAP = {
    0: {'name': 'Abnormally Dry', 'code': 'D0', 'color': '#FFFFE0'},
    1: {'name': 'Moderate Drought', 'code': 'D1', 'color': '#FCD37F'},
    2: {'name': 'Severe Drought', 'code': 'D2', 'color': '#FFAA00'},
    3: {'name': 'Extreme Drought', 'code': 'D3', 'color': '#E60000'},
    4: {'name': 'Exceptional Drought', 'code': 'D4', 'color': '#730000'}
}

# Simplification tolerance in degrees
# Higher = more simplification = smaller file size
# Use MUCH higher tolerance for D0/D1 which follow detailed coastlines
SIMPLIFY_TOLERANCE = {
    0: 0.25,  # D0: 28km - massive areas covering coastlines, aggressive simplification
    1: 0.20,  # D1: 22km - still very large areas
    2: 0.12,  # D2: 13km - moderate areas
    3: 0.06,  # D3: 7km - smaller, keep more detail
    4: 0.03,  # D4: 3km - smallest, preserve most detail
}
SIMPLIFY_TOLERANCE_DEFAULT = 0.15

# Coordinate precision (decimal places)
# 3 decimals = ~111m precision, sufficient for country-level display
COORD_PRECISION = 3


def parse_filename(filename):
    """Extract year, month, and severity from filename.

    Format: CDM_YYMM_D{0-4}_LR.geojson
    Example: CDM_2407_D2_LR.geojson -> (2024, 7, 2)
    """
    parts = filename.stem.split('_')
    yymm = parts[1]  # '2407'
    severity_str = parts[2]  # 'D2'

    year = 2000 + int(yymm[:2])
    month = int(yymm[2:])
    severity = int(severity_str[1])

    return year, month, severity


def round_coordinates(geom, precision=COORD_PRECISION):
    """Round coordinates to reduce WKT string size.

    Args:
        geom: Shapely geometry
        precision: Number of decimal places

    Returns:
        Geometry with rounded coordinates
    """
    if geom is None or geom.is_empty:
        return geom

    # Convert to GeoJSON, round coords, convert back
    geojson = mapping(geom)

    def round_coords(coords):
        """Recursively round coordinate arrays."""
        if isinstance(coords[0], (int, float)):
            # Base case: coordinate pair/triple
            return tuple(round(c, precision) for c in coords)
        else:
            # Recursive case: nested arrays
            return [round_coords(c) for c in coords]

    if 'coordinates' in geojson:
        geojson['coordinates'] = round_coords(geojson['coordinates'])

    return shape(geojson)


def calculate_area_safe(geom):
    """Calculate area in km2 safely, handling projection errors.

    Uses EPSG:3347 (NAD83 / Statistics Canada Lambert) for accurate area
    calculation in Canada.

    Args:
        geom: Shapely geometry in WGS84

    Returns:
        Area in km2, or 0 if calculation fails
    """
    if geom is None or geom.is_empty:
        return 0.0

    try:
        # Create single-feature GeoDataFrame
        gdf = gpd.GeoDataFrame({'geometry': [geom]}, crs='EPSG:4326')

        # Project to Canada Lambert for accurate area
        # EPSG:3347 is the standard for Statistics Canada
        gdf_proj = gdf.to_crs('EPSG:3347')

        # Calculate area in m2, convert to km2
        area_m2 = gdf_proj.geometry.iloc[0].area
        return area_m2 / 1_000_000

    except Exception as e:
        # Fallback: estimate from WGS84 coordinates
        # At 50N latitude, 1 degree lat = ~111km, 1 degree lon = ~71km
        # Area in deg2 * ~7900 km2/deg2 (rough estimate)
        try:
            return geom.area * 7900
        except:
            return 0.0


def convert_geojson_to_snapshot(geojson_path, verbose=False):
    """Convert a single GeoJSON file to snapshot record.

    Args:
        geojson_path: Path to GeoJSON file
        verbose: Print debug info

    Returns:
        Record dict or None if conversion fails
    """
    year, month, severity = parse_filename(geojson_path)

    # Read GeoJSON
    with open(geojson_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Check if empty
    if not data.get('features'):
        if verbose:
            print(f"  WARNING: No features in {geojson_path.name}")
        return None

    # Convert features to geometries
    geometries = []
    for feature in data['features']:
        try:
            geom = shape(feature['geometry'])
            if geom.is_valid and not geom.is_empty:
                geometries.append(geom)
            else:
                # Try to repair invalid geometry
                repaired = make_valid(geom)
                if not repaired.is_empty:
                    geometries.append(repaired)
        except Exception as e:
            if verbose:
                print(f"  WARNING: Invalid geometry in {geojson_path.name}: {e}")
            continue

    if not geometries:
        if verbose:
            print(f"  WARNING: No valid geometries in {geojson_path.name}")
        return None

    # Create GeoDataFrame and dissolve to single MultiPolygon
    gdf = gpd.GeoDataFrame({'geometry': geometries}, crs='EPSG:4326')
    dissolved = gdf.dissolve()
    merged_geom = dissolved.geometry.iloc[0]

    # Validate and repair merged geometry
    if not merged_geom.is_valid:
        merged_geom = make_valid(merged_geom)

    if merged_geom.is_empty:
        if verbose:
            print(f"  WARNING: Empty geometry after merge in {geojson_path.name}")
        return None

    # Calculate area BEFORE simplification (more accurate)
    area_km2 = calculate_area_safe(merged_geom)

    # Get severity-specific simplification tolerance
    # Lower severity (D0/D1) = larger areas = more aggressive simplification
    # Higher severity (D3/D4) = smaller areas = preserve more detail
    tolerance = SIMPLIFY_TOLERANCE.get(severity, SIMPLIFY_TOLERANCE_DEFAULT)

    # Simplify geometry for web display
    simplified = merged_geom.simplify(tolerance=tolerance, preserve_topology=True)

    # Validate simplified geometry
    if not simplified.is_valid:
        simplified = make_valid(simplified)

    if simplified.is_empty:
        # Simplification removed everything - use buffer(0) trick instead
        simplified = merged_geom.buffer(0)
        if simplified.is_empty:
            if verbose:
                print(f"  WARNING: Geometry lost after simplification in {geojson_path.name}")
            return None

    # Round coordinates to reduce WKT size
    simplified = round_coordinates(simplified, COORD_PRECISION)

    # Create snapshot record
    timestamp = datetime(year, month, 1)
    snapshot_id = f"CAN-{year:04d}{month:02d}-{SEVERITY_MAP[severity]['code']}"

    # Calculate end_timestamp (last day of month at 23:59:59)
    if month == 12:
        end_timestamp = datetime(year + 1, 1, 1, 0, 0, 0) - timedelta(seconds=1)
    else:
        end_timestamp = datetime(year, month + 1, 1, 0, 0, 0) - timedelta(seconds=1)

    # Calculate duration in days
    duration_days = (end_timestamp - timestamp).days + 1

    record = {
        'snapshot_id': snapshot_id,
        'timestamp': timestamp,
        'end_timestamp': end_timestamp,
        'duration_days': duration_days,
        'year': year,
        'month': month,
        'severity': SEVERITY_MAP[severity]['code'],
        'severity_code': severity,
        'severity_name': SEVERITY_MAP[severity]['name'],
        'geometry': simplified.wkt,
        'area_km2': area_km2,
        'iso3': 'CAN',
        'provinces_affected': None
    }

    return record


def main():
    print("=" * 80)
    print("Canada Drought Monitor - GeoJSON to Parquet Converter")
    print("=" * 80)

    # Paths
    raw_data_dir = Path(r'C:\Users\Bryan\Desktop\county-map-data\Raw data\imported\canada\drought')
    output_dir = Path(r'C:\Users\Bryan\Desktop\county-map-data\countries\CAN\drought')
    output_file = output_dir / 'snapshots.parquet'

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find all GeoJSON files
    geojson_files = sorted(raw_data_dir.glob('*/CDM_*_D*_LR.geojson'))

    print(f"\nFound {len(geojson_files)} GeoJSON files")
    print(f"Simplification tolerances by severity:")
    for sev, tol in SIMPLIFY_TOLERANCE.items():
        print(f"  D{sev}: {tol} degrees (~{tol * 111:.0f}km)")
    print(f"Coordinate precision: {COORD_PRECISION} decimal places")
    print(f"Converting to {output_file}...")
    print()

    # Process all files
    records = []
    errors = 0
    empty_count = 0

    for i, geojson_path in enumerate(geojson_files, 1):
        if i % 25 == 0 or i == len(geojson_files):
            print(f"  Processed {i}/{len(geojson_files)} files ({len(records)} records, {errors} errors)")

        try:
            record = convert_geojson_to_snapshot(geojson_path)
            if record:
                records.append(record)
            else:
                empty_count += 1
        except Exception as e:
            print(f"  ERROR processing {geojson_path.name}: {e}")
            errors += 1
            continue

    if not records:
        print("\nERROR: No records generated")
        return 1

    # Create DataFrame
    df = pd.DataFrame(records)

    # Sort by timestamp and severity
    df = df.sort_values(['timestamp', 'severity_code'])

    # Convert timestamp columns to datetime64
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['end_timestamp'] = pd.to_datetime(df['end_timestamp'])

    # Save to parquet with snappy compression
    df.to_parquet(output_file, index=False, compression='snappy')

    # Calculate file size
    file_size_mb = output_file.stat().st_size / (1024 * 1024)

    print()
    print("=" * 80)
    print("CONVERSION COMPLETE")
    print("=" * 80)
    print(f"\nTotal snapshots: {len(df)}")
    print(f"Empty/skipped files: {empty_count}")
    print(f"Errors: {errors}")
    print(f"Years: {df['year'].min()}-{df['year'].max()}")
    print(f"Months per year: ~{df.groupby('year')['month'].nunique().mean():.1f}")
    print(f"Severity levels: {sorted(df['severity'].unique().tolist())}")
    print(f"\nOutput file: {output_file}")
    print(f"File size: {file_size_mb:.2f} MB")

    # Check geometry string sizes
    geom_sizes = df['geometry'].str.len()
    print(f"\nGeometry WKT sizes:")
    print(f"  Min: {geom_sizes.min():,} chars")
    print(f"  Max: {geom_sizes.max():,} chars")
    print(f"  Mean: {geom_sizes.mean():,.0f} chars")
    print(f"  Total: {geom_sizes.sum() / 1024 / 1024:.2f} MB")

    # Create/update metadata file
    metadata = {
        'source': 'Agriculture and Agri-Food Canada',
        'source_url': 'https://agriculture.canada.ca/atlas/data_donnees/canadianDroughtMonitor/',
        'license': 'Open Government License - Canada',
        'download_date': datetime.now().isoformat(),
        'conversion_date': datetime.now().isoformat(),
        'years': f"{df['year'].min()}-{df['year'].max()}",
        'total_snapshots': len(df),
        'severity_levels': SEVERITY_MAP,
        'crs': 'EPSG:4326 (WGS84)',
        'geometry_simplification': {
            'tolerance_by_severity': {f'D{k}': f'{v} deg (~{v*111:.0f}km)' for k, v in SIMPLIFY_TOLERANCE.items()},
            'coordinate_precision': COORD_PRECISION,
            'level': 'Country (admin level 0)',
            'preserve_topology': True
        },
        'file_size_mb': round(file_size_mb, 2),
        'schema': {
            'snapshot_id': 'string - Unique identifier: CAN-{YYYYMM}-{severity}',
            'timestamp': 'datetime64 - First day of month (start time)',
            'end_timestamp': 'datetime64 - Last day of month at 23:59:59 (end time)',
            'duration_days': 'int32 - Duration in days (typically 28-31)',
            'year': 'int32 - Year',
            'month': 'int32 - Month number (1-12)',
            'severity': 'string - Drought level: D0, D1, D2, D3, D4',
            'severity_code': 'int32 - Numeric code: 0-4',
            'severity_name': 'string - Full name',
            'geometry': 'string - WKT polygon(s) of drought area (simplified)',
            'area_km2': 'float64 - Total affected area in km2 (calculated before simplification)',
            'iso3': 'string - Country code: CAN',
            'provinces_affected': 'string - Comma-separated province codes (future)'
        }
    }

    metadata_file = output_dir / 'metadata.json'
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"Metadata: {metadata_file}")

    # Size recommendation
    if file_size_mb > 50:
        print(f"\n[WARNING] File size ({file_size_mb:.1f} MB) is large for web delivery.")
        print("Consider increasing SIMPLIFY_TOLERANCE or reducing COORD_PRECISION.")
    elif file_size_mb < 25:
        print(f"\n[OK] File size ({file_size_mb:.1f} MB) is good for web delivery.")

    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
