"""
Data loading, catalog management, and metadata functions.

Handles loading the unified catalog.json and source metadata from the parquet-based
data structure.

Data Structure (layered):
    county-map-data/
        catalog.json              # Unified catalog with 'path' field per source

        global/                   # Country-level datasets
            geometry.csv          # Country outlines
            {source_id}/          # e.g., owid_co2/, imf_bop/
                metadata.json
                *.parquet
            un_sdg/               # Nested folder for SDGs
                01/ ... 17/

        countries/                # Sub-national data
            USA/
                geometry.parquet  # States + counties
                index.json        # Country-level metadata
                {source_id}/      # e.g., noaa_storms/, census_agesex/
                    metadata.json
                    *.parquet

        geometry/                 # Bank of all country geometries (fallback)
            {ISO3}.parquet

Path resolution uses catalog.json 'path' field:
    source_id='usgs_earthquakes' -> path='countries/USA/usgs_earthquakes'
"""

import json
import logging
from pathlib import Path

from .settings import get_backup_path

logger = logging.getLogger("mapmover")

# Global data catalog
data_catalog = {}

# Cache for source metadata
_metadata_cache = {}


def get_data_folder():
    """Get the data folder path from settings backup path."""
    backup_path = get_backup_path()
    if backup_path:
        return Path(backup_path) / "data"
    return None


def get_catalog_path():
    """Get the catalog.json path from settings backup path."""
    backup_path = get_backup_path()
    if backup_path:
        return Path(backup_path) / "catalog.json"
    return None


def load_catalog():
    """
    Load the unified catalog.json file.

    Returns:
        dict: Catalog with sources, or empty dict if not found
    """
    catalog_path = get_catalog_path()
    if not catalog_path or not catalog_path.exists():
        logger.warning(f"Catalog not found at {catalog_path}")
        return {"sources": [], "total_sources": 0}

    try:
        with open(catalog_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading catalog.json: {e}")
        return {"sources": [], "total_sources": 0}


def get_source_path(source_id: str):
    """
    Get the path to a source folder using the path field from catalog.

    Args:
        source_id: Source identifier (e.g., 'owid_co2', 'usgs_earthquakes')

    Returns:
        Path: Full path to source folder, or None if not found
    """
    backup_path = get_backup_path()
    if not backup_path:
        return None

    catalog = load_catalog()
    for source in catalog.get("sources", []):
        if source.get("source_id") == source_id:
            # Use path field if present, otherwise fall back to old structure
            source_path = source.get("path", f"data/{source_id}")
            return Path(backup_path) / source_path

    # Source not in catalog - try old path as fallback
    return Path(backup_path) / "data" / source_id


def load_source_metadata(source_id: str):
    """
    Load metadata.json for a specific source.

    Args:
        source_id: Source identifier (e.g., 'owid_co2', 'census_population')

    Returns:
        dict: Source metadata or None if not found
    """
    if source_id in _metadata_cache:
        return _metadata_cache[source_id]

    source_folder = get_source_path(source_id)
    if not source_folder or not source_folder.exists():
        return None

    metadata_path = source_folder / "metadata.json"
    if not metadata_path.exists():
        return None

    try:
        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
            _metadata_cache[source_id] = metadata
            return metadata
    except Exception as e:
        logger.error(f"Error loading metadata for {source_id}: {e}")
        return None


def get_source_by_topic(topic: str):
    """
    Find sources that match a topic keyword.

    Args:
        topic: Topic to search for (e.g., 'co2', 'population', 'health')

    Returns:
        list: Matching source entries from catalog
    """
    global data_catalog
    topic_lower = topic.lower()

    matches = []
    for source in data_catalog.get("sources", []):
        # Check topic_tags
        if any(topic_lower in tag.lower() for tag in source.get("topic_tags", [])):
            matches.append(source)
            continue
        # Check keywords
        if any(topic_lower in kw.lower() for kw in source.get("keywords", [])):
            matches.append(source)
            continue
        # Check source_id
        if topic_lower in source.get("source_id", "").lower():
            matches.append(source)

    return matches


def initialize_catalog():
    """
    Initialize the data catalog by loading catalog.json.
    Called at server startup.
    """
    global data_catalog

    data_catalog = load_catalog()

    if data_catalog.get("total_sources", 0) > 0:
        logger.info(f"Data catalog loaded: {data_catalog['total_sources']} sources")
        for source in data_catalog.get("sources", [])[:5]:
            logger.info(f"  - {source.get('source_id')}: {source.get('geographic_level')}")
        if data_catalog['total_sources'] > 5:
            logger.info(f"  ... and {data_catalog['total_sources'] - 5} more")
    else:
        logger.warning("Data catalog is empty or not found")


def get_data_catalog():
    """Get the current data catalog."""
    return data_catalog


def clear_metadata_cache():
    """Clear the metadata cache."""
    global _metadata_cache
    _metadata_cache = {}
    logger.info("Metadata cache cleared")


def get_geometry_folder():
    """Get the geometry folder path from settings backup path."""
    backup_path = get_backup_path()
    if backup_path:
        return Path(backup_path) / "geometry"
    return None


def get_countries_folder():
    """Get the countries folder path from settings backup path."""
    backup_path = get_backup_path()
    if backup_path:
        return Path(backup_path) / "countries"
    return None


def load_geometry_for_country(iso3: str):
    """
    Load geometry for a country using 3-tier fallback:
    1. countries/{ISO3}/geometry.parquet (local/official source like NUTS)
    2. countries/{ISO3}/crosswalk.json -> geometry/{ISO3}.parquet (translated)
    3. geometry/{ISO3}.parquet (GADM fallback)

    Returns:
        tuple: (GeoDataFrame, crosswalk_dict or None)
    """
    import pandas as pd

    countries_folder = get_countries_folder()
    geometry_folder = get_geometry_folder()

    # Tier 1: Country-specific geometry (NUTS, ABS LGA, etc.)
    if countries_folder:
        country_geom_path = countries_folder / iso3 / "geometry.parquet"
        if country_geom_path.exists():
            try:
                gdf = pd.read_parquet(country_geom_path)
                logger.debug(f"Loaded {len(gdf)} features from {country_geom_path}")
                return gdf, None
            except Exception as e:
                logger.warning(f"Error loading {country_geom_path}: {e}")

    # Tier 2: Load crosswalk if exists (for translating loc_ids)
    crosswalk = None
    if countries_folder:
        crosswalk_path = countries_folder / iso3 / "crosswalk.json"
        if crosswalk_path.exists():
            try:
                import json
                with open(crosswalk_path, 'r') as f:
                    crosswalk = json.load(f)
                logger.debug(f"Loaded crosswalk for {iso3}: {len(crosswalk.get('mappings', {}))} mappings")
            except Exception as e:
                logger.warning(f"Error loading crosswalk {crosswalk_path}: {e}")

    # Tier 3: GADM fallback geometry
    if geometry_folder:
        gadm_path = geometry_folder / f"{iso3}.parquet"
        if gadm_path.exists():
            try:
                gdf = pd.read_parquet(gadm_path)
                logger.debug(f"Loaded {len(gdf)} features from GADM {gadm_path}")
                return gdf, crosswalk
            except Exception as e:
                logger.warning(f"Error loading {gadm_path}: {e}")

    logger.warning(f"No geometry found for {iso3}")
    return None, crosswalk


def fetch_geometries_by_loc_ids(loc_ids: list) -> dict:
    """
    Fetch geometries from parquet files for a list of loc_ids.
    Uses 3-tier geometry fallback: country folder -> crosswalk -> GADM.
    Used for "show borders" functionality.

    Args:
        loc_ids: List of location IDs (e.g., ["USA-WA-53073", "USA-OR-41067"])

    Returns:
        GeoJSON FeatureCollection with geometries
    """
    import pandas as pd
    import json as json_module

    if not loc_ids:
        return {"type": "FeatureCollection", "features": []}

    # Group loc_ids by country (first part before dash, or whole ID for country-level)
    country_loc_ids = {}
    for loc_id in loc_ids:
        parts = loc_id.split("-")
        country = parts[0] if parts else loc_id
        if country not in country_loc_ids:
            country_loc_ids[country] = []
        country_loc_ids[country].append(loc_id)

    all_features = []

    for country, lids in country_loc_ids.items():
        # Load geometry using 3-tier fallback
        gdf, crosswalk = load_geometry_for_country(country)

        if gdf is None:
            logger.warning(f"No geometry found for {country}")
            continue

        # Build lookup set for requested loc_ids
        remaining_lids = set(lids)
        found_lids = set()

        try:
            # First try direct match
            filtered = gdf[gdf['loc_id'].isin(remaining_lids)]

            if len(filtered) > 0:
                for _, row in filtered.iterrows():
                    # Handle geometry - could be string or shapely geometry
                    geom = row.get('geometry')
                    if geom is None:
                        continue

                    # Convert to dict if needed
                    if hasattr(geom, '__geo_interface__'):
                        geom_dict = geom.__geo_interface__
                    elif isinstance(geom, str):
                        geom_dict = json_module.loads(geom)
                    else:
                        continue

                    feature = {
                        "type": "Feature",
                        "geometry": geom_dict,
                        "properties": {
                            "loc_id": row.get("loc_id"),
                            "name": row.get("name"),
                            "admin_level": row.get("admin_level"),
                            "parent_id": row.get("parent_id"),
                        }
                    }
                    all_features.append(feature)
                    found_lids.add(row.get("loc_id"))

            remaining_lids -= found_lids

            # If crosswalk exists and we still have unmatched loc_ids, try translation
            if crosswalk and remaining_lids:
                mappings = crosswalk.get('mappings', {})
                for loc_id in list(remaining_lids):
                    gadm_id = mappings.get(loc_id)
                    if gadm_id:
                        match = gdf[gdf['loc_id'] == gadm_id]
                        if len(match) > 0:
                            row = match.iloc[0]
                            geom = row.get('geometry')
                            if geom is None:
                                continue

                            if hasattr(geom, '__geo_interface__'):
                                geom_dict = geom.__geo_interface__
                            elif isinstance(geom, str):
                                geom_dict = json_module.loads(geom)
                            else:
                                continue

                            feature = {
                                "type": "Feature",
                                "geometry": geom_dict,
                                "properties": {
                                    "loc_id": loc_id,  # Use original loc_id
                                    "name": row.get("name"),
                                    "admin_level": row.get("admin_level"),
                                    "parent_id": row.get("parent_id"),
                                    "_crosswalk_from": gadm_id,  # Track translation
                                }
                            }
                            all_features.append(feature)
                            remaining_lids.discard(loc_id)

            if remaining_lids:
                logger.debug(f"No geometry found for {len(remaining_lids)} loc_ids in {country}: {list(remaining_lids)[:5]}")

        except Exception as e:
            logger.error(f"Error processing geometry for {country}: {e}")

    logger.info(f"Fetched {len(all_features)} geometries for {len(loc_ids)} loc_ids")

    return {
        "type": "FeatureCollection",
        "features": all_features
    }
