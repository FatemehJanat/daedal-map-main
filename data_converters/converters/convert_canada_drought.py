"""
Convert Canada Drought Monitor GeoJSON files to snapshots.parquet

Reads monthly drought area polygons from Agriculture Canada and converts to
unified snapshot format for choropleth animation.

Input: Raw data/imported/canada/drought/{YEAR}/CDM_{YYMM}_D{0-4}_LR.geojson
Output: countries/CAN/drought/snapshots.parquet

Schema matches DISASTER_DISPLAY.md Drought Schema (Snapshots - Canada)
"""

import json
import pandas as pd
import geopandas as gpd
from pathlib import Path
from datetime import datetime, timedelta
from shapely.geometry import shape
import sys

# Severity mapping
SEVERITY_MAP = {
    0: {'name': 'Abnormally Dry', 'code': 'D0', 'color': '#FFFFE0'},
    1: {'name': 'Moderate Drought', 'code': 'D1', 'color': '#FCD37F'},
    2: {'name': 'Severe Drought', 'code': 'D2', 'color': '#FFAA00'},
    3: {'name': 'Extreme Drought', 'code': 'D3', 'color': '#E60000'},
    4: {'name': 'Exceptional Drought', 'code': 'D4', 'color': '#730000'}
}

ACRES_TO_KM2 = 0.00404686


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


def convert_geojson_to_snapshot(geojson_path):
    """Convert a single GeoJSON file to snapshot records."""
    year, month, severity = parse_filename(geojson_path)

    # Read GeoJSON
    with open(geojson_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Check if empty
    if not data.get('features'):
        print(f"  WARNING: No features in {geojson_path.name}")
        return None

    # Convert to GeoDataFrame - source coordinates are already WGS84 (no CRS in file but coords are lon/lat)
    gdf = gpd.GeoDataFrame.from_features(data['features'], crs='EPSG:4326')

    # Dissolve all polygons into one MultiPolygon per severity level
    # (There can be multiple polygons for the same month/severity)
    dissolved = gdf.dissolve()

    # Calculate area in km² from dissolved geometry
    # Re-project to equal-area projection for accurate area calculation
    dissolved_area = dissolved.to_crs('EPSG:6933')  # NSIDC EASE-Grid 2.0 Global (equal area)
    area_km2 = dissolved_area.geometry.iloc[0].area / 1_000_000  # m² to km²

    # Simplify geometry for web display (tolerance=0.01 ~1km precision for country level)
    # This drastically reduces file size while maintaining visual quality
    simplified_geom = dissolved.geometry.iloc[0].simplify(tolerance=0.01, preserve_topology=True)

    # Create snapshot record
    timestamp = datetime(year, month, 1)
    snapshot_id = f"CAN-{year:04d}{month:02d}-{SEVERITY_MAP[severity]['code']}"

    # Calculate end_timestamp (last day of month at 23:59:59)
    # Get first day of next month, then subtract 1 second
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
        'geometry': simplified_geom.wkt,  # Convert simplified geometry to WKT string
        'area_km2': area_km2,
        'iso3': 'CAN',
        'provinces_affected': None  # Could be extracted from geometry intersection with provinces
    }

    return record


def main():
    # Paths
    raw_data_dir = Path(r'C:\Users\Bryan\Desktop\county-map-data\Raw data\imported\canada\drought')
    output_dir = Path(r'C:\Users\Bryan\Desktop\county-map-data\countries\CAN\drought')
    output_file = output_dir / 'snapshots.parquet'

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find all GeoJSON files
    geojson_files = sorted(raw_data_dir.glob('*/CDM_*_D*_LR.geojson'))

    print(f"Found {len(geojson_files)} GeoJSON files")
    print(f"Converting to {output_file}...")

    # Process all files
    records = []
    for i, geojson_path in enumerate(geojson_files, 1):
        if i % 50 == 0:
            print(f"  Processed {i}/{len(geojson_files)}...")

        try:
            record = convert_geojson_to_snapshot(geojson_path)
            if record:
                records.append(record)
        except Exception as e:
            print(f"  ERROR processing {geojson_path.name}: {e}")
            continue

    # Create DataFrame
    df = pd.DataFrame(records)

    # Sort by timestamp and severity
    df = df.sort_values(['timestamp', 'severity_code'])

    # Convert timestamp to datetime64
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # Save to parquet
    df.to_parquet(output_file, index=False, compression='snappy')

    print(f"\nConversion complete!")
    print(f"  Total snapshots: {len(df)}")
    print(f"  Years: {df['year'].min()}-{df['year'].max()}")
    print(f"  Months: {df.groupby('year')['month'].nunique().to_dict()}")
    print(f"  Severity levels: {df['severity'].value_counts().to_dict()}")
    print(f"  Output file: {output_file}")
    print(f"  File size: {output_file.stat().st_size / 1_000_000:.2f} MB")

    # Create metadata file
    metadata = {
        'source': 'Agriculture and Agri-Food Canada',
        'source_url': 'https://agriculture.canada.ca/atlas/data_donnees/canadianDroughtMonitor/',
        'license': 'Open Government License - Canada',
        'download_date': datetime.now().isoformat(),
        'years': f"{df['year'].min()}-{df['year'].max()}",
        'total_snapshots': len(df),
        'severity_levels': SEVERITY_MAP,
        'crs_original': 'EPSG:4326',
        'crs_output': 'EPSG:4326',
        'geometry_simplification': {
            'tolerance': 0.01,
            'precision': '~1 kilometer',
            'level': 'Country (admin level 0)',
            'preserve_topology': True
        },
        'schema': {
            'snapshot_id': 'string - Unique identifier: CAN-{YYYYMM}-{severity}',
            'timestamp': 'datetime64 - First day of month (start time)',
            'end_timestamp': 'datetime64 - Last day of month at 23:59:59 (end time)',
            'duration_days': 'int32 - Duration in days (typically 28-31 depending on month)',
            'year': 'int32 - Year',
            'month': 'int32 - Month number (1-12)',
            'severity': 'string - Drought level: D0, D1, D2, D3, D4',
            'severity_code': 'int32 - Numeric code: 0-4',
            'severity_name': 'string - Full name',
            'geometry': 'string - WKT polygon(s) of drought area',
            'area_km2': 'float32 - Total affected area in km2',
            'iso3': 'string - Country code: CAN',
            'provinces_affected': 'string - Comma-separated province codes (future)'
        }
    }

    metadata_file = output_dir / 'metadata.json'
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"  Metadata: {metadata_file}")


if __name__ == '__main__':
    main()
