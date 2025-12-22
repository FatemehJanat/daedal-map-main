"""
Geometry endpoint handlers.
Handles loading geometry files and country hierarchy for drill-down navigation.

Data source:
  [backup_path]/geometry/global.csv      - All countries (admin_0)
  [backup_path]/geometry/{ISO3}.parquet  - All admin levels per country
  [backup_path]/geometry/country_depth.json - Metadata about admin levels

Schema (13 columns):
  loc_id, parent_id, admin_level, name, name_local, code, iso_3166_2,
  centroid_lon, centroid_lat, has_polygon, geometry, timezone, iso_a3
"""

import json
import logging
import pandas as pd
from pathlib import Path

from .settings import get_backup_path

logger = logging.getLogger("mapmover")

# Cache for country parquet data
_country_parquet_cache = {}  # iso3 -> DataFrame

# Cache for global countries data
_global_countries_cache = None

# Cache for country depth metadata
_country_depth_cache = None

# Cache for country coverage metadata
_country_coverage_cache = None


def get_geometry_path():
    """Get the geometry folder path from settings."""
    backup_path = get_backup_path()
    if not backup_path:
        return None
    return Path(backup_path) / "geometry"


def load_country_depth():
    """Load country depth metadata (max admin levels per country)."""
    global _country_depth_cache
    if _country_depth_cache is not None:
        return _country_depth_cache

    geom_path = get_geometry_path()
    if not geom_path:
        _country_depth_cache = {}
        return _country_depth_cache

    depth_file = geom_path / "country_depth.json"
    if depth_file.exists():
        try:
            with open(depth_file, 'r', encoding='utf-8') as f:
                _country_depth_cache = json.load(f)
            logger.info(f"Loaded country depth for {len(_country_depth_cache)} countries")
        except Exception as e:
            logger.error(f"Error loading country_depth.json: {e}")
            _country_depth_cache = {}
    else:
        _country_depth_cache = {}

    return _country_depth_cache


def load_country_coverage():
    """Load country coverage metadata (actual vs expected depth)."""
    global _country_coverage_cache
    if _country_coverage_cache is not None:
        return _country_coverage_cache

    geom_path = get_geometry_path()
    if not geom_path:
        _country_coverage_cache = {}
        return _country_coverage_cache

    coverage_file = geom_path / "country_coverage.json"
    if coverage_file.exists():
        try:
            with open(coverage_file, 'r', encoding='utf-8') as f:
                _country_coverage_cache = json.load(f)
            logger.info(f"Loaded coverage data for {len(_country_coverage_cache)} countries")
        except Exception as e:
            logger.error(f"Error loading country_coverage.json: {e}")
            _country_coverage_cache = {}
    else:
        _country_coverage_cache = {}

    return _country_coverage_cache


def load_global_countries():
    """
    Load global.csv (all countries, admin_0 only) from backup path.
    Returns DataFrame or None if file doesn't exist.
    """
    global _global_countries_cache
    if _global_countries_cache is not None:
        return _global_countries_cache

    geom_path = get_geometry_path()
    if not geom_path:
        logger.warning("No backup path configured")
        return None

    global_file = geom_path / "global.csv"
    if not global_file.exists():
        logger.warning(f"global.csv not found at {global_file}")
        return None

    try:
        _global_countries_cache = pd.read_csv(global_file)
        logger.info(f"Loaded {len(_global_countries_cache)} countries from global.csv")
        return _global_countries_cache
    except Exception as e:
        logger.error(f"Error loading global.csv: {e}")
        return None


def load_country_parquet(iso3: str):
    """
    Load country geometry parquet file into cache.
    Returns DataFrame or None if file doesn't exist.
    """
    if iso3 in _country_parquet_cache:
        return _country_parquet_cache[iso3]

    geom_path = get_geometry_path()
    if not geom_path:
        return None

    parquet_file = geom_path / f"{iso3}.parquet"
    if not parquet_file.exists():
        logger.debug(f"Parquet file not found: {parquet_file}")
        return None

    try:
        df = pd.read_parquet(parquet_file)
        _country_parquet_cache[iso3] = df
        logger.info(f"Loaded {len(df)} features for {iso3} from parquet")
        return df
    except Exception as e:
        logger.error(f"Error loading {iso3}.parquet: {e}")
        return None


def df_to_geojson(df, polygon_only=False):
    """
    Convert a DataFrame with geometry column to GeoJSON FeatureCollection.

    Args:
        df: DataFrame with geometry column (GeoJSON string)
        polygon_only: If True, skip Point geometries
    """
    features = []
    for _, row in df.iterrows():
        geom_str = row.get('geometry', '')
        if not geom_str or pd.isna(geom_str):
            continue

        try:
            geometry = json.loads(geom_str) if isinstance(geom_str, str) else geom_str
        except (json.JSONDecodeError, TypeError):
            continue

        # Skip Point geometries if polygon_only
        if polygon_only and geometry.get('type') == 'Point':
            continue

        # Build properties from all columns except geometry
        properties = {}
        for col in df.columns:
            if col != 'geometry':
                val = row.get(col)
                if pd.notna(val):
                    properties[col] = val

        features.append({
            "type": "Feature",
            "properties": properties,
            "geometry": geometry
        })

    return {"type": "FeatureCollection", "features": features}


def get_countries_geometry(debug: bool = False):
    """
    Get all country geometries for initial map display.
    Returns a GeoJSON FeatureCollection with polygon countries only.

    If debug=True, adds hierarchy_depth from country_depth.json.
    """
    df = load_global_countries()

    if df is None:
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0,
            "level": "country",
            "debug": debug,
            "error": "No geometry data available. Configure backup path in settings."
        }

    # Convert to GeoJSON (polygons only)
    geojson = df_to_geojson(df, polygon_only=True)

    # If debug mode, add coverage info for coloring
    if debug:
        country_coverage = load_country_coverage()
        for feature in geojson.get("features", []):
            loc_id = feature.get("properties", {}).get("loc_id")
            if loc_id and loc_id in country_coverage:
                cov_info = country_coverage[loc_id]
                feature["properties"]["actual_depth"] = cov_info.get("actual_depth", 0)
                feature["properties"]["expected_depth"] = cov_info.get("expected_depth", 1)
                feature["properties"]["coverage"] = cov_info.get("coverage", 0)
                feature["properties"]["level_counts"] = cov_info.get("level_counts", {})
            else:
                # No coverage data - assume no drill-down available
                feature["properties"]["actual_depth"] = 0
                feature["properties"]["expected_depth"] = 1
                feature["properties"]["coverage"] = 0

    return {
        "geojson": geojson,
        "count": len(geojson.get("features", [])),
        "level": "country",
        "debug": debug
    }


def get_location_children(loc_id: str):
    """
    Get child geometries for a location (drill-down).
    Uses parquet files with parent_id filtering.

    Examples:
    - loc_id="USA" -> Returns US states (admin_1)
    - loc_id="USA-CA" -> Returns California counties (admin_2)
    - loc_id="FRA" -> Returns French regions (admin_1)
    - loc_id="FRA-IDF" -> Returns Ile-de-France departments (admin_2)
    """
    # Extract country code from loc_id
    parts = loc_id.split("-")
    if not parts:
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0,
            "level": "none",
            "parent_loc_id": loc_id,
            "error": "Invalid loc_id format"
        }

    iso3 = parts[0]

    # Load country parquet
    df = load_country_parquet(iso3)
    if df is None:
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0,
            "level": "none",
            "parent_loc_id": loc_id,
            "error": f"No geometry data for {iso3}. Download GADM data first."
        }

    # Filter for children of this location
    children = df[df["parent_id"] == loc_id]

    if len(children) == 0:
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0,
            "level": "none",
            "parent_loc_id": loc_id,
            "message": f"No child locations for {loc_id}"
        }

    # Determine child level name
    child_level = int(children["admin_level"].iloc[0])
    level_names = {0: "country", 1: "state", 2: "county", 3: "place", 4: "locality", 5: "neighborhood"}
    level_name = level_names.get(child_level, f"admin_{child_level}")

    # Convert to GeoJSON
    geojson = df_to_geojson(children)

    return {
        "geojson": geojson,
        "count": len(geojson.get("features", [])),
        "level": level_name,
        "admin_level": child_level,
        "parent_loc_id": loc_id
    }


def get_location_places(loc_id: str):
    """
    Get places (cities/towns) for a location as a separate overlay layer.
    Used to display city markers on top of county boundaries.

    Returns the deepest admin level available for this location.
    """
    parts = loc_id.split("-")
    if not parts:
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0,
            "level": "none",
            "parent_loc_id": loc_id
        }

    iso3 = parts[0]

    # Load country parquet
    df = load_country_parquet(iso3)
    if df is None:
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0,
            "level": "none",
            "parent_loc_id": loc_id,
            "error": f"No geometry data for {iso3}"
        }

    # Find the deepest admin level that has this loc_id as ancestor
    # Get all features where parent_id starts with loc_id
    if len(parts) == 1:
        # Country level - find all places in country
        descendants = df[df["iso_a3"] == iso3]
    else:
        # Sub-national - find descendants
        # Match either exact parent_id or parent_id starting with loc_id-
        mask = (df["parent_id"] == loc_id) | (df["parent_id"].str.startswith(loc_id + "-", na=False))
        descendants = df[mask]

    if len(descendants) == 0:
        return {
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0,
            "level": "none",
            "parent_loc_id": loc_id
        }

    # Get the deepest level available
    max_level = descendants["admin_level"].max()
    places = descendants[descendants["admin_level"] == max_level]

    # Convert to GeoJSON
    geojson = df_to_geojson(places)

    level_names = {0: "country", 1: "state", 2: "county", 3: "place", 4: "locality", 5: "neighborhood"}
    level_name = level_names.get(int(max_level), f"admin_{max_level}")

    return {
        "geojson": geojson,
        "count": len(geojson.get("features", [])),
        "level": level_name,
        "admin_level": int(max_level),
        "parent_loc_id": loc_id
    }


def get_location_info(loc_id: str):
    """
    Get information about a specific location.
    Returns the feature for this loc_id and info about available children.
    """
    parts = loc_id.split("-")
    if not parts:
        return {"error": "Invalid loc_id"}

    iso3 = parts[0]

    # For country level, check global.csv first
    if len(parts) == 1:
        df = load_global_countries()
        if df is not None:
            location = df[df["loc_id"] == loc_id]
            if len(location) > 0:
                row = location.iloc[0].to_dict()

                # Check if we have children
                country_depth = load_country_depth()
                depth_info = country_depth.get(iso3, {})

                return {
                    "loc_id": loc_id,
                    "name": row.get("name"),
                    "admin_level": 0,
                    "max_depth": depth_info.get("max_depth", 0),
                    "has_children": depth_info.get("max_depth", 0) > 0
                }

    # For sub-national, check country parquet
    df = load_country_parquet(iso3)
    if df is None:
        return {"error": f"No data for {iso3}"}

    location = df[df["loc_id"] == loc_id]
    if len(location) == 0:
        return {"error": f"Location not found: {loc_id}"}

    row = location.iloc[0]
    admin_level = int(row.get("admin_level", 0))

    # Check for children
    children = df[df["parent_id"] == loc_id]
    has_children = len(children) > 0
    child_count = len(children) if has_children else 0

    return {
        "loc_id": loc_id,
        "name": row.get("name"),
        "admin_level": admin_level,
        "parent_id": row.get("parent_id"),
        "has_children": has_children,
        "child_count": child_count
    }


def clear_cache():
    """Clear all cached geometry data. Useful when data files are updated."""
    global _country_parquet_cache, _global_countries_cache, _country_depth_cache, _country_coverage_cache
    _country_parquet_cache = {}
    _global_countries_cache = None
    _country_depth_cache = None
    _country_coverage_cache = None
    logger.info("Geometry cache cleared")
