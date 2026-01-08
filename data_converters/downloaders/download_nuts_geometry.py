"""
Download NUTS boundaries from Eurostat GISCO service.

Downloads NUTS 2024 boundaries and converts to parquet files with loc_ids
matching Eurostat data format (e.g., FRA-FR1, DEU-DE3).

Source: https://gisco-services.ec.europa.eu/distribution/v2/nuts/download/

Output: countries/{ISO3}/geometry.parquet for each European country

Usage:
    python download_nuts_geometry.py
    python download_nuts_geometry.py --scale 10m  # Default
    python download_nuts_geometry.py --scale 1m   # Higher detail
"""

import json
import requests
import zipfile
import io
import sys
from pathlib import Path
import geopandas as gpd
import pandas as pd

# Configuration
OUTPUT_BASE = Path(r"C:\Users\Bryan\Desktop\county-map-data\countries")
TEMP_DIR = Path(r"C:\Users\Bryan\Desktop\county-map-data\Raw data\nuts_geometry")

# NUTS 2-letter country code to ISO3 mapping
NUTS_TO_ISO3 = {
    "AL": "ALB",  # Albania
    "AT": "AUT",  # Austria
    "BE": "BEL",  # Belgium
    "BG": "BGR",  # Bulgaria
    "CH": "CHE",  # Switzerland
    "CY": "CYP",  # Cyprus
    "CZ": "CZE",  # Czechia
    "DE": "DEU",  # Germany
    "DK": "DNK",  # Denmark
    "EE": "EST",  # Estonia
    "EL": "GRC",  # Greece (EL in NUTS, not GR)
    "ES": "ESP",  # Spain
    "FI": "FIN",  # Finland
    "FR": "FRA",  # France
    "HR": "HRV",  # Croatia
    "HU": "HUN",  # Hungary
    "IE": "IRL",  # Ireland
    "IS": "ISL",  # Iceland
    "IT": "ITA",  # Italy
    "LI": "LIE",  # Liechtenstein
    "LT": "LTU",  # Lithuania
    "LU": "LUX",  # Luxembourg
    "LV": "LVA",  # Latvia
    "ME": "MNE",  # Montenegro
    "MK": "MKD",  # North Macedonia
    "MT": "MLT",  # Malta
    "NL": "NLD",  # Netherlands
    "NO": "NOR",  # Norway
    "PL": "POL",  # Poland
    "PT": "PRT",  # Portugal
    "RO": "ROU",  # Romania
    "RS": "SRB",  # Serbia
    "SE": "SWE",  # Sweden
    "SI": "SVN",  # Slovenia
    "SK": "SVK",  # Slovakia
    "TR": "TUR",  # Turkey
    "UK": "GBR",  # United Kingdom
}

# Countries with Eurostat data (from scan)
EUROSTAT_COUNTRIES = [
    "ALB", "AUT", "BEL", "BGR", "CHE", "CYP", "CZE", "DEU", "DNK", "ESP",
    "EST", "FIN", "FRA", "GBR", "GRC", "HRV", "HUN", "IRL", "ISL", "ITA",
    "LIE", "LTU", "LUX", "LVA", "MKD", "MLT", "MNE", "NLD", "NOR", "POL",
    "PRT", "ROU", "SRB", "SVK", "SVN", "SWE", "TUR"
]


def download_nuts_geojson(scale="10m", year="2024"):
    """
    Download NUTS boundaries from GISCO.

    Args:
        scale: Map scale - "1m", "3m", "10m", "20m", "60m"
        year: NUTS version year - "2024", "2021", "2016", etc.

    Returns:
        Path to downloaded/extracted GeoJSON file
    """
    url = f"https://gisco-services.ec.europa.eu/distribution/v2/nuts/download/ref-nuts-{year}-{scale}.geojson.zip"

    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    geojson_path = TEMP_DIR / f"nuts_{year}_{scale}.geojson"

    # Check if already downloaded
    if geojson_path.exists():
        print(f"Using cached: {geojson_path}")
        return geojson_path

    print(f"Downloading NUTS {year} at {scale} scale...")
    print(f"  URL: {url}")

    response = requests.get(url, timeout=300)
    response.raise_for_status()

    # Extract from zip
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        # Find the GeoJSON file in the zip
        geojson_files = [f for f in zf.namelist() if f.endswith('.geojson') or f.endswith('.json')]
        if not geojson_files:
            raise ValueError(f"No GeoJSON file found in zip. Contents: {zf.namelist()}")

        # Extract the largest one (main boundaries file)
        main_file = max(geojson_files, key=lambda f: zf.getinfo(f).file_size)
        print(f"  Extracting: {main_file}")

        with zf.open(main_file) as src, open(geojson_path, 'wb') as dst:
            dst.write(src.read())

    size_mb = geojson_path.stat().st_size / (1024 * 1024)
    print(f"  Downloaded: {size_mb:.1f} MB")

    return geojson_path


def load_nuts_data(geojson_path):
    """Load NUTS GeoJSON into GeoDataFrame."""
    print(f"\nLoading NUTS boundaries...")
    gdf = gpd.read_file(geojson_path)
    print(f"  Total features: {len(gdf)}")
    print(f"  Columns: {gdf.columns.tolist()}")

    # Show sample of NUTS IDs
    if 'NUTS_ID' in gdf.columns:
        sample_ids = gdf['NUTS_ID'].head(10).tolist()
        print(f"  Sample NUTS_IDs: {sample_ids}")

    return gdf


def convert_to_loc_id(nuts_id, nuts_to_iso3):
    """
    Convert NUTS ID to loc_id format.

    NUTS IDs: FR, FR1, FR10, FRB, DE3, DE30
    loc_ids:  FRA, FRA-FR1, FRA-FR10, FRA-FRB, DEU-DE3, DEU-DE30

    Note: NUTS 0 (country level, 2 chars) becomes just ISO3 (e.g., FR -> FRA)
    """
    if not nuts_id or len(nuts_id) < 2:
        return None

    # First 2 characters are country code
    nuts_country = nuts_id[:2]
    iso3 = nuts_to_iso3.get(nuts_country)

    if not iso3:
        return None

    # NUTS 0 (country level) = just ISO3
    if len(nuts_id) == 2:
        return iso3

    # All other levels = ISO3 + "-" + full NUTS code
    return f"{iso3}-{nuts_id}"


def get_nuts_level(nuts_id):
    """
    Determine NUTS level from ID length.

    NUTS 0: 2 chars (FR, DE) -> admin_level 0
    NUTS 1: 3 chars (FR1, DE3) -> admin_level 1
    NUTS 2: 4 chars (FR10, DE30) -> admin_level 2
    NUTS 3: 5 chars (FR101, DE300) -> admin_level 3
    """
    if not nuts_id:
        return None
    length = len(nuts_id)
    if length == 2:
        return 0  # Country
    elif length == 3:
        return 1  # NUTS 1
    elif length == 4:
        return 2  # NUTS 2
    elif length >= 5:
        return 3  # NUTS 3
    return None


def get_parent_loc_id(loc_id):
    """
    Get parent loc_id by removing last NUTS level.

    FRA-FR101 -> FRA-FR10 -> FRA-FR1 -> FRA -> None
    """
    if not loc_id:
        return None

    # Country level (no hyphen, just ISO3) has no parent
    if '-' not in loc_id:
        return None

    parts = loc_id.split('-')
    iso3 = parts[0]
    nuts_code = parts[1] if len(parts) > 1 else ""

    # Remove last character from NUTS code to get parent
    parent_nuts = nuts_code[:-1]

    # If parent is just country code (2 chars), return ISO3
    if len(parent_nuts) == 2:
        return iso3

    return f"{iso3}-{parent_nuts}"


def process_country(gdf, iso3, nuts_country_code):
    """
    Extract and process geometry for a single country.

    Args:
        gdf: Full NUTS GeoDataFrame
        iso3: ISO3 country code (e.g., "FRA")
        nuts_country_code: NUTS 2-letter code (e.g., "FR")

    Returns:
        GeoDataFrame with country's geometry in standard format
    """
    # Filter to this country
    country_gdf = gdf[gdf['NUTS_ID'].str.startswith(nuts_country_code)].copy()

    if len(country_gdf) == 0:
        return None

    # Create standardized columns
    records = []
    for _, row in country_gdf.iterrows():
        nuts_id = row['NUTS_ID']
        loc_id = convert_to_loc_id(nuts_id, NUTS_TO_ISO3)

        if not loc_id:
            continue

        admin_level = get_nuts_level(nuts_id)
        parent_id = get_parent_loc_id(loc_id)

        # Get name - try multiple possible columns
        name = None
        for name_col in ['NUTS_NAME', 'NAME_LATN', 'name', 'NAME']:
            if name_col in row and pd.notna(row[name_col]):
                name = row[name_col]
                break

        if not name:
            name = nuts_id

        # Get geometry
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue

        # Calculate centroid
        centroid = geom.centroid

        # Calculate bbox
        bounds = geom.bounds  # (minx, miny, maxx, maxy)

        records.append({
            'loc_id': loc_id,
            'parent_id': parent_id,
            'admin_level': admin_level,
            'name': name,
            'name_local': row.get('NAME_LATN', name),
            'code': nuts_id,
            'centroid_lon': centroid.x,
            'centroid_lat': centroid.y,
            'has_polygon': True,
            'geometry': geom,
            'bbox_min_lon': bounds[0],
            'bbox_min_lat': bounds[1],
            'bbox_max_lon': bounds[2],
            'bbox_max_lat': bounds[3],
        })

    if not records:
        return None

    result_gdf = gpd.GeoDataFrame(records, crs=country_gdf.crs)
    return result_gdf


def save_country_geometry(gdf, iso3):
    """Save country geometry to parquet."""
    output_dir = OUTPUT_BASE / iso3
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "geometry.parquet"

    # Convert geometry to GeoJSON strings for storage
    gdf_copy = gdf.copy()
    gdf_copy['geometry'] = gdf_copy['geometry'].apply(
        lambda g: json.dumps(g.__geo_interface__) if g else None
    )

    # Save as parquet
    gdf_copy.to_parquet(output_path, index=False)

    return output_path


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Download NUTS geometry from Eurostat GISCO")
    parser.add_argument("--scale", default="10m", choices=["1m", "3m", "10m", "20m", "60m"],
                       help="Map scale (default: 10m)")
    parser.add_argument("--year", default="2024", help="NUTS version year (default: 2024)")
    parser.add_argument("--countries", nargs="*", help="Specific countries to process (ISO3 codes)")
    args = parser.parse_args()

    print("=" * 70)
    print("NUTS Geometry Downloader")
    print("=" * 70)
    print(f"Scale: {args.scale}")
    print(f"Year: {args.year}")
    print(f"Source: Eurostat GISCO")
    print()

    # Download NUTS data
    geojson_path = download_nuts_geojson(scale=args.scale, year=args.year)

    # Load into GeoDataFrame
    gdf = load_nuts_data(geojson_path)

    # Determine which countries to process
    if args.countries:
        countries_to_process = [c.upper() for c in args.countries]
    else:
        countries_to_process = EUROSTAT_COUNTRIES

    print(f"\nProcessing {len(countries_to_process)} countries...")

    # Build reverse mapping (ISO3 -> NUTS code)
    iso3_to_nuts = {v: k for k, v in NUTS_TO_ISO3.items()}

    # Process each country
    success = 0
    failed = []

    for iso3 in countries_to_process:
        nuts_code = iso3_to_nuts.get(iso3)

        if not nuts_code:
            print(f"  {iso3}: No NUTS mapping found")
            failed.append(iso3)
            continue

        country_gdf = process_country(gdf, iso3, nuts_code)

        if country_gdf is None or len(country_gdf) == 0:
            print(f"  {iso3}: No features found")
            failed.append(iso3)
            continue

        # Save to parquet
        output_path = save_country_geometry(country_gdf, iso3)

        # Stats
        level_counts = country_gdf.groupby('admin_level').size().to_dict()
        print(f"  {iso3}: {len(country_gdf)} features - {level_counts}")

        success += 1

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Successful: {success}")
    print(f"Failed: {len(failed)}")

    if failed:
        print(f"Failed countries: {failed}")

    print(f"\nOutput: {OUTPUT_BASE}/{{ISO3}}/geometry.parquet")
    print("\nNOTE: These geometry files use NUTS-based loc_ids that match Eurostat data.")
    print("      Eurostat data will now join directly without crosswalk.")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
