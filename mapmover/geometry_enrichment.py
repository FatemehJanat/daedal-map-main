"""
Geometry enrichment functions.
Handles loading geometry from Countries.csv and enriching data features with geometry.
"""

import json
import logging
import os
import pandas as pd
from pathlib import Path

from .geography import get_fallback_coordinates, load_conversions, CONVERSIONS_DATA

# Base directory for file paths
BASE_DIR = Path(__file__).resolve().parent.parent

logger = logging.getLogger("mapmover")

# Cache for geometry data to avoid repeated file reads
_geometry_cache = None


def get_geometry_lookup():
    """
    Load Countries.csv geometry data into a lookup dictionary.
    Returns dict mapping country_code (ISO3) -> geometry dict
    """
    global _geometry_cache
    if _geometry_cache is not None:
        return _geometry_cache

    countries_path = BASE_DIR / "data_pipeline" / "data_cleaned" / "Countries.csv"
    if not os.path.exists(countries_path):
        logger.warning(f"Countries.csv not found at {countries_path}")
        return {}

    try:
        df = pd.read_csv(countries_path)
        _geometry_cache = {}

        for _, row in df.iterrows():
            code = row.get('country_code')
            geom_str = row.get('geometry')

            if code and geom_str and pd.notna(geom_str):
                try:
                    geom = json.loads(geom_str) if isinstance(geom_str, str) else geom_str
                    _geometry_cache[code] = {
                        'geometry': geom,
                        'country_name': row.get('country_name', ''),
                        'latitude': row.get('latitude'),
                        'longitude': row.get('longitude'),
                        'continent': row.get('continent', ''),
                        'subregion': row.get('subregion', '')
                    }
                except (json.JSONDecodeError, TypeError):
                    continue

        logger.info(f"Loaded geometry for {len(_geometry_cache)} countries from Countries.csv")
        return _geometry_cache

    except Exception as e:
        logger.error(f"Error loading Countries.csv: {e}")
        return {}


def get_country_coordinates(country_name, country_code=None):
    """
    Get approximate coordinates for a country by name or code.
    First checks Countries.csv geometry lookup, then falls back to
    conversions.json for countries missing from the geometry CSV.

    Args:
        country_name: Name of the country
        country_code: Optional ISO 3-letter code for faster/more accurate lookup

    Returns:
        Tuple (lat, lon) or None if not found
    """
    # First try: Use country code with fallback coordinates (fastest for known missing countries)
    if country_code:
        fallback = get_fallback_coordinates(country_code)
        if fallback:
            return fallback

    # Second try: Look up in Countries.csv geometry lookup
    geometry_lookup = get_geometry_lookup()
    if geometry_lookup:
        name_lower = country_name.lower().strip()

        for code, data in geometry_lookup.items():
            stored_name = data.get('country_name', '').lower().strip()
            if stored_name == name_lower or code == country_code:
                lat = data.get('latitude')
                lon = data.get('longitude')
                if lat is not None and lon is not None and pd.notna(lat) and pd.notna(lon):
                    return (float(lat), float(lon))

    # Third try: Find code by name and check fallback coordinates
    if not country_code:
        # Try to find the country code from the name
        if not CONVERSIONS_DATA:
            load_conversions()
        iso_codes = CONVERSIONS_DATA.get('iso_country_codes', {})
        name_lower = country_name.lower().strip()
        for code, name in iso_codes.items():
            if name.lower() == name_lower:
                fallback = get_fallback_coordinates(code)
                if fallback:
                    return fallback
                break

    return None


# Country name aliases: data source name -> Countries.csv name
COUNTRY_NAME_ALIASES = {
    'cape verde': 'cabo verde',
    'central african republic': 'central african rep.',
    'democratic republic of congo': 'dem. rep. congo',
    'democratic republic of the congo': 'dem. rep. congo',
    'dr congo': 'dem. rep. congo',
    'drc': 'dem. rep. congo',
    'equatorial guinea': 'eq. guinea',
    'eswatini': 'eswatini',
    'south sudan': 's. sudan',
    'ivory coast': 'cote d\'ivoire',
    'cote d\'ivoire': 'cote d\'ivoire',
    'czechia': 'czech rep.',
    'czech republic': 'czech rep.',
    'north korea': 'north korea',
    'south korea': 'korea',
    'republic of korea': 'korea',
    'timor-leste': 'timor-leste',
    'east timor': 'timor-leste',
    'bosnia and herzegovina': 'bosnia and herz.',
    'united states': 'united states of america',
    'usa': 'united states of america',
    'uk': 'united kingdom',
    'britain': 'united kingdom',
}


def enrich_with_geometry(features, name_col='country_name', code_col='country_code'):
    """
    Enrich GeoJSON features with geometry from Countries.csv.

    For features missing geometry, looks up by country_code or country_name.
    Returns tuple: (enriched_features, missing_count, missing_names)
    """
    geometry_lookup = get_geometry_lookup()
    if not geometry_lookup:
        return features, len(features), []

    enriched = []
    missing_names = []

    for feature in features:
        props = feature.get('properties', {})
        geom = feature.get('geometry')

        # Already has geometry? Keep it
        if geom and geom.get('coordinates'):
            enriched.append(feature)
            continue

        # Try to find geometry by country code
        code = props.get(code_col) or props.get('country_code') or props.get('iso_code')
        if code and code in geometry_lookup:
            geo_data = geometry_lookup[code]
            feature['geometry'] = geo_data['geometry']
            enriched.append(feature)
            continue

        # Code exists but not in geometry_lookup - try fallback coordinates
        if code:
            fallback = get_fallback_coordinates(code)
            if fallback:
                lat, lon = fallback
                feature['geometry'] = {"type": "Point", "coordinates": [float(lon), float(lat)]}
                feature['properties']['_geometry_type'] = 'point'
                enriched.append(feature)
                continue

        # Try by country name (with alias support)
        name = props.get(name_col) or props.get('country_name') or props.get('country')
        if name:
            name_lower = name.lower().strip()
            # Apply alias if exists
            lookup_name = COUNTRY_NAME_ALIASES.get(name_lower, name_lower)

            # Direct lookup by iterating geometry cache
            found = False
            for geo_code, geo_data in geometry_lookup.items():
                geo_name = geo_data.get('country_name', '').lower()
                if geo_name == lookup_name or geo_name == name_lower:
                    feature['geometry'] = geo_data['geometry']
                    enriched.append(feature)
                    found = True
                    break

            if not found:
                # No polygon geometry found - try to create point marker
                lat = props.get('latitude') or props.get('lat')
                lon = props.get('longitude') or props.get('lon') or props.get('lng')

                # If no lat/lon in data, try to get coordinates from lookup or fallback
                if not (lat and lon):
                    coords = get_country_coordinates(name, country_code=code)
                    if coords:
                        lat, lon = coords

                if lat and lon:
                    try:
                        feature['geometry'] = {"type": "Point", "coordinates": [float(lon), float(lat)]}
                        feature['properties']['_geometry_type'] = 'point'  # Mark as point for UI
                        enriched.append(feature)
                    except (ValueError, TypeError):
                        if name not in missing_names:
                            missing_names.append(name)
                else:
                    if name not in missing_names:
                        missing_names.append(name)
        else:
            unknown_name = str(props.get(name_col, 'Unknown'))
            if unknown_name not in missing_names:
                missing_names.append(unknown_name)

    return enriched, len(missing_names), missing_names


def detect_missing_geometry(df):
    """
    Check if a DataFrame has a geometry column.

    Returns:
        bool: True if geometry column is missing, False if present
    """
    return 'geometry' not in df.columns


def get_geometry_source(geographic_level, data_catalog):
    """
    Select appropriate geometry dataset based on geographic level.

    Args:
        geographic_level: string - 'country', 'county', 'state', etc.
        data_catalog: list of catalog items

    Returns:
        dict: catalog item for the geometry source, or None if not found
    """
    # Map geographic levels to preferred geometry sources
    geometry_sources = {
        'country': 'Countries.csv',
        'county': 'usplaces.csv',
        'state': 'usplaces.csv',  # Can filter to state level
        'city': 'Populated Places.csv',
        'place': 'usplaces.csv'
    }

    preferred_file = geometry_sources.get(geographic_level.lower())
    if not preferred_file:
        print(f"Warning: No known geometry source for geographic level '{geographic_level}'")
        return None

    # Find the file in data catalog
    for item in data_catalog:
        if item['filename'] == preferred_file:
            return item

    print(f"Warning: Geometry source '{preferred_file}' not found in catalog")
    return None
