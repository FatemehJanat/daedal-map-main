"""
Centralized path configuration for the county-map project.

This module provides all file system paths used across the application.
Supports both local development and deployed environments via environment variables.

Folder Structure:
    global map/
        county-map/         - Public app (this repo)
        county-map-private/ - Protected converters and build scripts
        county-map-data/    - Processed parquet files and catalog
        county-map-raw/     - Raw downloaded source files (never shared)
"""

import os
from pathlib import Path

# =============================================================================
# Base Path Detection
# =============================================================================

def _get_project_root() -> Path:
    """
    Determine the project root directory.

    Priority:
    1. COUNTY_MAP_ROOT environment variable (for deployment)
    2. Parent of this file's directory (local development)
    """
    env_root = os.environ.get("COUNTY_MAP_ROOT")
    if env_root:
        return Path(env_root)

    # Local development: this file is in county-map/mapmover/paths.py
    # So project root is county-map/
    return Path(__file__).resolve().parent.parent


def _get_global_root() -> Path:
    """
    Get the 'global map' folder that contains all 4 project folders.

    Priority:
    1. GLOBAL_MAP_ROOT environment variable
    2. Parent of county-map folder (local development)
    """
    env_root = os.environ.get("GLOBAL_MAP_ROOT")
    if env_root:
        return Path(env_root)

    # Local development: global map is parent of county-map
    return _get_project_root().parent


# =============================================================================
# Core Path Definitions
# =============================================================================

# Project root (county-map folder)
PROJECT_ROOT = _get_project_root()

# Global map root (contains all 4 folders)
GLOBAL_ROOT = _get_global_root()

# The 4 main folders
APP_ROOT = PROJECT_ROOT  # county-map (public app)
PRIVATE_ROOT = GLOBAL_ROOT / "county-map-private"  # Protected converters
DATA_ROOT = GLOBAL_ROOT / "county-map-data"  # Processed data
RAW_ROOT = GLOBAL_ROOT / "county-map-raw"  # Raw downloads

# =============================================================================
# Data Paths (county-map-data)
# =============================================================================

# Main data directories
COUNTRIES_DIR = DATA_ROOT / "countries"
GLOBAL_DIR = DATA_ROOT / "global"
GEOMETRY_DIR = DATA_ROOT / "geometry"

# Catalog files
CATALOG_PATH = DATA_ROOT / "catalog.json"
INDEX_PATH = DATA_ROOT / "index.json"

# =============================================================================
# App Paths (county-map)
# =============================================================================

# Static assets
STATIC_DIR = APP_ROOT / "static"
TEMPLATES_DIR = APP_ROOT / "templates"
LOGS_DIR = APP_ROOT / "logs"

# Config files
CONFIG_PATH = APP_ROOT / "config.json"
SETTINGS_PATH = APP_ROOT / "settings.json"

# =============================================================================
# Private Paths (county-map-private)
# =============================================================================

# Build and converter directories
BUILD_DIR = PRIVATE_ROOT / "build"
CONVERTERS_DIR = PRIVATE_ROOT / "data_converters"
DOWNLOADERS_DIR = PRIVATE_ROOT / "data_converters" / "downloaders"

# =============================================================================
# Raw Data Paths (county-map-raw)
# =============================================================================

RAW_DATA_DIR = RAW_ROOT / "Raw data"
SOURCE_DATA_DIR = RAW_ROOT / "source_data"
BACKUPS_DIR = RAW_ROOT / "backups"

# =============================================================================
# Helper Functions
# =============================================================================

def get_country_dir(iso3: str) -> Path:
    """Get the data directory for a specific country."""
    return COUNTRIES_DIR / iso3.upper()


def get_country_index(iso3: str) -> Path:
    """Get the index.json path for a specific country."""
    return get_country_dir(iso3) / "index.json"


def get_dataset_path(scope: str, dataset: str, filename: str = "events.parquet") -> Path:
    """
    Get the path to a dataset file.

    Args:
        scope: 'global' or country ISO3 code (e.g., 'USA', 'CAN')
        dataset: Dataset name (e.g., 'earthquakes', 'hurricanes')
        filename: File name (default: 'events.parquet')

    Returns:
        Path to the dataset file
    """
    if scope.lower() == "global":
        return GLOBAL_DIR / dataset / filename
    else:
        return COUNTRIES_DIR / scope.upper() / dataset / filename


def get_geometry_path(geometry_type: str) -> Path:
    """Get path to a geometry file."""
    return GEOMETRY_DIR / f"{geometry_type}.parquet"


def ensure_dir(path: Path) -> Path:
    """Create directory if it doesn't exist, return the path."""
    path.mkdir(parents=True, exist_ok=True)
    return path


# =============================================================================
# Validation
# =============================================================================

def validate_paths(verbose: bool = False) -> dict:
    """
    Check which paths exist. Useful for debugging path issues.

    Returns:
        Dict with path names and their existence status
    """
    paths_to_check = {
        "PROJECT_ROOT": PROJECT_ROOT,
        "GLOBAL_ROOT": GLOBAL_ROOT,
        "DATA_ROOT": DATA_ROOT,
        "PRIVATE_ROOT": PRIVATE_ROOT,
        "RAW_ROOT": RAW_ROOT,
        "GEOMETRY_DIR": GEOMETRY_DIR,
        "CATALOG_PATH": CATALOG_PATH,
    }

    results = {}
    for name, path in paths_to_check.items():
        exists = path.exists()
        results[name] = {"path": str(path), "exists": exists}
        if verbose:
            status = "OK" if exists else "MISSING"
            print(f"{status}: {name} = {path}")

    return results


if __name__ == "__main__":
    # Quick validation when run directly
    print("Path Configuration:")
    print("=" * 60)
    validate_paths(verbose=True)
