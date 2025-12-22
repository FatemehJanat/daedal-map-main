"""
Map state management for incremental data building.
Tracks the current state of the map display across requests.
"""

import logging
import pandas as pd

from .geometry_enrichment import get_geometry_lookup
from .geography import get_countries_in_region

logger = logging.getLogger("mapmover")

# Session state for incremental data building
_current_map_state = {
    "features": [],           # Current GeoJSON features on map
    "country_codes": [],      # List of country codes currently displayed
    "data_fields": [],        # List of data fields currently shown (e.g., ["gdp", "population"])
    "year": None,             # Current year filter
    "region": None,           # Current region filter (e.g., "Europe", "South America")
    "dataset": None,          # Primary dataset being used
    "sources": []             # List of sources: [{"name": "...", "url": "...", "fields": ["gdp"]}]
}


def get_map_state():
    """Get current map state for incremental updates."""
    return _current_map_state.copy()


def clear_map_state():
    """Clear the current map state."""
    global _current_map_state
    _current_map_state = {
        "features": [],
        "country_codes": [],
        "data_fields": [],
        "year": None,
        "region": None,
        "dataset": None,
        "sources": []
    }
    logger.info("Map state cleared")


def add_source_to_state(dataset_name, field_name, data_catalog=None):
    """Add or update a source in the map state."""
    global _current_map_state

    # Get metadata for this dataset
    metadata = None
    if data_catalog:
        for entry in data_catalog:
            if entry.get("filename") == dataset_name:
                metadata = entry.get("metadata", {})
                break

    source_name = metadata.get("source_name", dataset_name) if metadata else dataset_name
    source_url = metadata.get("source_url", "") if metadata else ""

    # Check if source already exists
    for source in _current_map_state["sources"]:
        if source["name"] == source_name:
            # Add field to existing source
            if field_name and field_name not in source["fields"]:
                source["fields"].append(field_name)
            return

    # Add new source
    _current_map_state["sources"].append({
        "name": source_name,
        "url": source_url,
        "fields": [field_name] if field_name else []
    })


def build_geometry_package(country_codes=None, country_names=None, region=None):
    """
    Build a GeoJSON FeatureCollection with geometry for specified places.
    This is the first step - geometry only, no data yet.

    Args:
        country_codes: List of ISO3 country codes (e.g., ["USA", "CAN", "MEX"])
        country_names: List of country names (alternative to codes)
        region: Region name to get all countries from (e.g., "Europe", "South America")

    Returns:
        dict with 'features' list and metadata about what was loaded
    """
    global _current_map_state

    geometry_lookup = get_geometry_lookup()
    if not geometry_lookup:
        return {"features": [], "loaded": 0, "missing": []}

    # If region specified, get country codes for that region
    if region:
        region_codes = get_countries_in_region(region)
        if region_codes:
            country_codes = region_codes
            logger.debug(f"Region '{region}' resolved to {len(country_codes)} countries")

    features = []
    missing = []
    codes_loaded = []

    # Build features from country codes
    if country_codes:
        for code in country_codes:
            if code in geometry_lookup:
                geo_data = geometry_lookup[code]
                feature = {
                    "type": "Feature",
                    "geometry": geo_data['geometry'],
                    "properties": {
                        "country_code": code,
                        "country_name": geo_data.get('country_name', ''),
                        "continent": geo_data.get('continent', ''),
                        "subregion": geo_data.get('subregion', '')
                    }
                }
                features.append(feature)
                codes_loaded.append(code)
            else:
                missing.append(code)

    # Build features from country names (if no codes provided)
    elif country_names:
        for name in country_names:
            found = False
            for code, geo_data in geometry_lookup.items():
                if geo_data.get('country_name', '').lower() == name.lower():
                    feature = {
                        "type": "Feature",
                        "geometry": geo_data['geometry'],
                        "properties": {
                            "country_code": code,
                            "country_name": geo_data.get('country_name', ''),
                            "continent": geo_data.get('continent', ''),
                            "subregion": geo_data.get('subregion', '')
                        }
                    }
                    features.append(feature)
                    codes_loaded.append(code)
                    found = True
                    break
            if not found:
                missing.append(name)

    logger.debug(f"Built geometry package: {len(features)} features, {len(missing)} missing")

    # Update map state
    _current_map_state["features"] = features
    _current_map_state["country_codes"] = codes_loaded
    _current_map_state["region"] = region
    _current_map_state["data_fields"] = []  # No data yet

    return {
        "features": features,
        "loaded": len(features),
        "missing": missing,
        "country_codes": codes_loaded
    }


def enrich_features_with_data(features, dataset_item, field_name, year=None, data_catalog=None):
    """
    Add data from a dataset to existing GeoJSON features.

    Args:
        features: List of GeoJSON features (with country_code in properties)
        dataset_item: Catalog item for the dataset
        field_name: Column name to extract (e.g., "gdp", "population", "co2")
        year: Optional year to filter to
        data_catalog: Optional data catalog for source tracking

    Returns:
        Updated features list with new data added to properties
    """
    global _current_map_state

    if not dataset_item:
        logger.warning(f"Dataset item not provided")
        return features

    # Load only the columns we need (identifier, year, and the target field)
    try:
        # First get headers to find the right columns
        header_df = pd.read_csv(dataset_item['path'], delimiter=dataset_item['delimiter'], nrows=0)
        all_cols = list(header_df.columns)

        # Find the matching data column (case-insensitive)
        actual_col = None
        for col in all_cols:
            if col.lower() == field_name.lower() or field_name.lower() in col.lower():
                actual_col = col
                break

        if not actual_col:
            logger.warning(f"Field '{field_name}' not found in {dataset_item['filename']}")
            return features

        # Find country code column
        code_col = None
        for col in ['country_code', 'iso_code', 'Code', 'ISO']:
            if col in all_cols:
                code_col = col
                break

        # Find year column
        year_col = None
        for col in ['year', 'data_year', 'Year']:
            if col in all_cols:
                year_col = col
                break

        # Build list of columns to load
        cols_to_load = [actual_col]
        if code_col:
            cols_to_load.append(code_col)
        if year_col:
            cols_to_load.append(year_col)

        # Load only needed columns
        df = pd.read_csv(dataset_item['path'], delimiter=dataset_item['delimiter'], usecols=cols_to_load, dtype=str)

    except Exception as e:
        logger.error(f"Error loading {dataset_item['filename']}: {e}")
        return features

    # Filter by year if specified
    if year and year_col:
        df = df[df[year_col].astype(str) == str(year)]
    elif year_col:
        # Get latest year for each country
        df[year_col] = pd.to_numeric(df[year_col], errors='coerce')
        df = df.sort_values(year_col, ascending=False).drop_duplicates(subset=[code_col], keep='first')

    # Build lookup from dataset
    data_lookup = {}
    if code_col:
        for _, row in df.iterrows():
            code = row.get(code_col)
            value = row.get(actual_col)
            row_year = row.get(year_col) if year_col else None
            if code and pd.notna(value):
                try:
                    data_lookup[code] = {
                        'value': float(value),
                        'year': int(float(row_year)) if row_year and pd.notna(row_year) else None
                    }
                except (ValueError, TypeError):
                    data_lookup[code] = {'value': value, 'year': row_year}

    # Enrich features
    enriched_count = 0
    for feature in features:
        code = feature['properties'].get('country_code')
        if code and code in data_lookup:
            feature['properties'][field_name] = data_lookup[code]['value']
            if data_lookup[code]['year']:
                feature['properties']['data_year'] = data_lookup[code]['year']
            enriched_count += 1

    logger.debug(f"Enriched {enriched_count}/{len(features)} features with '{field_name}'")

    # Update map state
    if field_name not in _current_map_state["data_fields"]:
        _current_map_state["data_fields"].append(field_name)
    _current_map_state["year"] = year
    _current_map_state["dataset"] = dataset_item['filename']

    # Track source for this field
    add_source_to_state(dataset_item['filename'], field_name, data_catalog)

    return features


def remove_field_from_features(features, field_name):
    """
    Remove a data field from all features.

    Args:
        features: List of GeoJSON features
        field_name: Field to remove from properties

    Returns:
        Updated features list
    """
    global _current_map_state

    for feature in features:
        if field_name in feature['properties']:
            del feature['properties'][field_name]

    # Update map state
    if field_name in _current_map_state["data_fields"]:
        _current_map_state["data_fields"].remove(field_name)

    logger.debug(f"Removed '{field_name}' from features")
    return features


def build_incremental_response(action, region=None, country_codes=None, field=None, dataset=None, year=None):
    """
    Build or modify the map data incrementally.

    Args:
        action: One of "new", "add_field", "remove_field", "change_region", "change_year"
        region: Region name for geographic filtering
        country_codes: Specific country codes to include
        field: Data field to add/remove (e.g., "gdp", "population")
        dataset: Dataset to pull field from
        year: Year filter

    Returns:
        dict with GeoJSON FeatureCollection and status info
    """
    global _current_map_state

    if action == "new":
        # Start fresh with new geometry
        clear_map_state()
        result = build_geometry_package(country_codes=country_codes, region=region)
        features = result["features"]

        # If field specified, add data
        if field and dataset:
            features = enrich_features_with_data(features, dataset, field, year)

        _current_map_state["features"] = features

    elif action == "add_field":
        # Add a new data field to existing features
        features = _current_map_state["features"]
        if not features:
            return {"error": "No features loaded. Start with a region or country selection first."}

        if field and dataset:
            features = enrich_features_with_data(features, dataset, field, year or _current_map_state["year"])
            _current_map_state["features"] = features

    elif action == "remove_field":
        # Remove a data field from existing features
        features = _current_map_state["features"]
        if field:
            features = remove_field_from_features(features, field)
            _current_map_state["features"] = features

    elif action == "change_region":
        # Keep data fields, change countries
        current_fields = _current_map_state["data_fields"].copy()
        current_dataset = _current_map_state["dataset"]
        current_year = year or _current_map_state["year"]

        # Build new geometry
        result = build_geometry_package(country_codes=country_codes, region=region)
        features = result["features"]

        # Re-apply all data fields
        for field_name in current_fields:
            features = enrich_features_with_data(features, current_dataset, field_name, current_year)

        _current_map_state["features"] = features

    elif action == "change_year":
        # Keep countries and fields, change year
        current_fields = _current_map_state["data_fields"].copy()
        current_dataset = _current_map_state["dataset"]
        features = _current_map_state["features"]

        # Clear existing data values
        for feature in features:
            for field_name in current_fields:
                if field_name in feature['properties']:
                    del feature['properties'][field_name]

        # Re-fetch with new year
        for field_name in current_fields:
            features = enrich_features_with_data(features, current_dataset, field_name, year)

        _current_map_state["features"] = features
        _current_map_state["year"] = year

    # Build response
    features = _current_map_state["features"]

    return {
        "geojson": {
            "type": "FeatureCollection",
            "features": features
        },
        "count": len(features),
        "data_fields": _current_map_state["data_fields"],
        "region": _current_map_state["region"],
        "year": _current_map_state["year"],
        "sources": _current_map_state["sources"],
        "message": []
    }
