"""
Data loading, catalog management, and metadata functions.

Handles loading the unified catalog.json and source metadata from the parquet-based
data structure.

Data Structure:
    county-map-data/
        catalog.json              # Unified catalog of all sources
        data/
            {source_id}/
                metadata.json     # Source metadata
                *.parquet         # Data files
        geometry/
            global.csv            # Country geometry
            {ISO3}.parquet        # Country sub-divisions
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

    data_folder = get_data_folder()
    if not data_folder:
        return None

    metadata_path = data_folder / source_id / "metadata.json"
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
