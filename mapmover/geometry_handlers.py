"""
Geometry endpoint handlers.
Handles loading geometry files and country hierarchy for drill-down navigation.

Data source (resolved via paths.py DATA_ROOT):
  geometry/global.csv      - All countries (admin_0)
  geometry/{ISO3}.parquet  - All admin levels per country

Schema (13 columns):
  loc_id, parent_id, admin_level, name, name_local, code, iso_3166_2,
  centroid_lon, centroid_lat, has_polygon, geometry, timezone, iso_a3
"""

import json
import logging
import threading
import pandas as pd
from pathlib import Path

# Try orjson for faster JSON parsing (3-10x faster than stdlib json)
try:
    import orjson
    def fast_json_loads(s):
        return orjson.loads(s)
except ImportError:
    def fast_json_loads(s):
        return json.loads(s)

from .paths import GEOMETRY_DIR, DATA_ROOT, COUNTRIES_DIR
from .duckdb_helpers import is_cloud_mode, parquet_columns, select_rows
from .foundation_helpers import (
    load_country_crosswalk,
    load_global_countries_frame,
    load_reference_json,
    load_world_factbook_static_frame,
)

logger = logging.getLogger("mapmover")

# Cache for country parquet data - keyed by (iso3, admin_level) or just iso3 for full
_country_parquet_cache = {}
_country_parquet_cache_lock = threading.Lock()
_country_parquet_inflight = set()  # keys currently being fetched from R2
_country_parquet_waiters = {}  # key -> Event for concurrent waiters

# Cache for country bounding boxes (for viewport filtering)
_country_bounds_cache = None

def _parquet_accessible(path: Path) -> bool:
    """Returns True if a parquet file exists locally or is accessible via S3/DuckDB."""
    if not is_cloud_mode():
        return path.exists()
    try:
        cols = parquet_columns(path)
        return bool(cols)
    except Exception:
        return False


def _load_crosswalk(iso3: str) -> dict | None:
    """Compatibility shim over the shared foundation helper layer."""
    return load_country_crosswalk(iso3)


def canonicalize_loc_id(loc_id: str) -> str:
    """Return runtime loc_ids in canonical form. Legacy formats are not normalized here."""
    return loc_id


def translate_loc_id_to_geometry_id(loc_id: str) -> str:
    """
    Translate a dataset loc_id into the geometry join id used by runtime geometry rows.

    - admin_1 local ids can map to geoBoundaries G-IDs via `mappings`
    - admin_2 USA FIPS bridge ids can map via `admin_2_fips`
    - admin_3+ local ids stay local after canonicalization
    """
    canonical = canonicalize_loc_id(loc_id)
    if not isinstance(canonical, str) or "-" not in canonical:
        return canonical

    iso3 = canonical.split("-", 1)[0]
    crosswalk = _load_crosswalk(iso3)
    local_to_geo, _ = _build_crosswalk_maps(crosswalk)
    return local_to_geo.get(canonical, canonical)


def translate_geometry_id_to_local_id(loc_id: str) -> str:
    """
    Translate a geometry-side loc_id back to its preferred local/canonical id.

    This is the reverse of translate_loc_id_to_geometry_id() and is especially
    important for multi-level USA flows where an admin_2 geometry id (GeoBoundaries
    county id) needs to scope deeper admin_3+ rows that are stored under the
    canonical local county bridge id.
    """
    canonical = canonicalize_loc_id(loc_id)
    if not isinstance(canonical, str) or "-" not in canonical:
        return canonical

    iso3 = canonical.split("-", 1)[0]
    crosswalk = _load_crosswalk(iso3)
    _, geo_to_local = _build_crosswalk_maps(crosswalk)
    return geo_to_local.get(canonical, canonical)


def _build_crosswalk_maps(crosswalk_data: dict | None) -> tuple[dict, dict]:
    """
    Build local->geo and geo->preferred-local maps from crosswalk data.

    Includes:
    - admin_1 `mappings`
    - admin_2 FIPS bridge `admin_2_fips`
    """
    local_to_geo: dict[str, str] = {}
    geo_to_local: dict[str, str] = {}
    if not crosswalk_data:
        return local_to_geo, geo_to_local

    for local_loc_id, geo_loc_id in (crosswalk_data.get("mappings") or {}).items():
        local_norm = canonicalize_loc_id(local_loc_id)
        local_to_geo[local_norm] = geo_loc_id
        geo_to_local.setdefault(geo_loc_id, local_norm)

    for local_loc_id, geo_loc_id in (crosswalk_data.get("admin_2_fips") or {}).items():
        local_norm = canonicalize_loc_id(local_loc_id)
        local_to_geo[local_norm] = geo_loc_id
        geo_to_local.setdefault(geo_loc_id, local_norm)

    return local_to_geo, geo_to_local


def get_geometry_path():
    """Get the geometry folder path using centralized path resolution."""
    if GEOMETRY_DIR.exists():
        return GEOMETRY_DIR
    return None


def load_global_countries():
    """
    Load global.csv (all countries, admin_0 only) from backup path.
    Returns DataFrame or None if file doesn't exist.
    """
    return load_global_countries_frame()


def load_world_factbook_static():
    """
    Load world_factbook_static/all_countries.parquet for lightweight country popup enrichment.
    Returns DataFrame or None if unavailable.
    """
    return load_world_factbook_static_frame()


def load_country_parquet(iso3: str, admin_level: int = None):
    """
    Load country geometry parquet file into cache.
    Returns DataFrame or None if file doesn't exist.

    Priority order (3-tier fallback):
    1. countries/{ISO3}/geometry.parquet - Country-specific geometry (NUTS, ABS LGA, etc.)
    2. countries/{ISO3}/crosswalk.json + geometry/{ISO3}.parquet - Crosswalk translation to geoBoundaries
    3. geometry/{ISO3}.parquet - Global geoBoundaries geometry (fallback)

    If admin_level is specified, uses predicate pushdown for efficiency.
    """
    # Check cache - if admin_level specified, cache by (iso3, level)
    cache_key = (iso3, admin_level) if admin_level is not None else iso3
    wait_event = None
    owns_fetch = False

    with _country_parquet_cache_lock:
        if cache_key in _country_parquet_cache:
            return _country_parquet_cache[cache_key]

        # If we have the full dataframe cached, filter from it
        if admin_level is not None and iso3 in _country_parquet_cache:
            full_df = _country_parquet_cache[iso3]
            filtered = full_df[full_df['admin_level'] == admin_level]
            _country_parquet_cache[cache_key] = filtered
            return filtered

        # If another thread is already fetching this key, wait for it to finish
        # so repeated hot geometry requests reuse the same cold-load work.
        if cache_key in _country_parquet_inflight:
            wait_event = _country_parquet_waiters.get(cache_key)
        else:
            _country_parquet_inflight.add(cache_key)
            wait_event = threading.Event()
            _country_parquet_waiters[cache_key] = wait_event
            owns_fetch = True

    if not owns_fetch:
        if wait_event is not None:
            wait_event.wait(timeout=15.0)
        with _country_parquet_cache_lock:
            if cache_key in _country_parquet_cache:
                return _country_parquet_cache[cache_key]
            if admin_level is not None and iso3 in _country_parquet_cache:
                full_df = _country_parquet_cache[iso3]
                filtered = full_df[full_df['admin_level'] == admin_level]
                _country_parquet_cache[cache_key] = filtered
                return filtered
        return None

    # Priority 1: Country-specific geometry (matches data loc_ids like NUTS)
    country_geom_file = DATA_ROOT / "countries" / iso3 / "geometry.parquet"
    # Priority 2: Crosswalk file (for translating loc_ids)
    crosswalk_file = DATA_ROOT / "countries" / iso3 / "crosswalk.json"
    # Priority 3: Global geometry folder (GADM fallback)
    global_geom_file = GEOMETRY_DIR / f"{iso3}.parquet"

    # Try country-specific first
    parquet_file = None
    crosswalk_data = None

    if _parquet_accessible(country_geom_file):
        parquet_file = country_geom_file
        logger.debug(f"Using country-specific geometry: {country_geom_file}")
    elif crosswalk_file.exists() and _parquet_accessible(global_geom_file):
        crosswalk_data = _load_crosswalk(iso3)
        parquet_file = global_geom_file
        logger.debug(f"Using crosswalk + geoBoundaries geometry: {crosswalk_file}")
    elif _parquet_accessible(global_geom_file):
        parquet_file = global_geom_file
        logger.debug(f"Using global geometry fallback: {global_geom_file}")
    else:
        logger.debug(f"No geometry file found for {iso3}")
        with _country_parquet_cache_lock:
            _country_parquet_inflight.discard(cache_key)
            waiter = _country_parquet_waiters.pop(cache_key, None)
        if waiter is not None:
            waiter.set()
        return None

    try:
        # Use predicate pushdown if admin_level specified
        if admin_level is not None:
            df = select_rows(
                parquet_file,
                exact_filters={"admin_level": admin_level},
            )
            if df.empty and not is_cloud_mode():
                df = pd.read_parquet(
                    parquet_file,
                    filters=[('admin_level', '==', admin_level)]
                )
        else:
            if is_cloud_mode():
                df = select_rows(parquet_file)
            else:
                df = pd.read_parquet(parquet_file)

        # If crosswalk exists, add reverse mapping for lookup
        # This allows data with local loc_ids to find GADM geometry
        if crosswalk_data:
            _, reverse_map = _build_crosswalk_maps(crosswalk_data)
            # Add local_loc_id column for joining
            df['local_loc_id'] = df['loc_id'].map(reverse_map)
            logger.debug(f"Applied crosswalk: {len(reverse_map)} mappings")

        # In S3 mode, do not cache empty DataFrames - an empty result from a cold
        # DuckDB/R2 fetch is likely a transient failure, not "this country has no data".
        # Caching empty would poison the cache and serve 0 features for the rest of
        # the container's lifetime. Local mode is fine to cache empty (data truly absent).
        if df.empty and is_cloud_mode():
            logger.warning(f"Empty geometry result for {iso3} (level={admin_level}) in S3 mode - not caching")
            with _country_parquet_cache_lock:
                _country_parquet_inflight.discard(cache_key)
                waiter = _country_parquet_waiters.pop(cache_key, None)
            if waiter is not None:
                waiter.set()
            return df  # Return empty but do NOT cache, so next request retries

        with _country_parquet_cache_lock:
            _country_parquet_cache[cache_key] = df
            _country_parquet_inflight.discard(cache_key)
            waiter = _country_parquet_waiters.pop(cache_key, None)
        if waiter is not None:
            waiter.set()
        logger.debug(f"Loaded {len(df)} features for {iso3} (level={admin_level}) from {parquet_file.name}")
        return df
    except Exception as e:
        logger.error(f"Error loading geometry for {iso3}: {e}")
        with _country_parquet_cache_lock:
            _country_parquet_inflight.discard(cache_key)
            waiter = _country_parquet_waiters.pop(cache_key, None)
        if waiter is not None:
            waiter.set()
        return None


def load_country_parquet_viewport(iso3: str, admin_level: int, bbox: tuple):
    """
    Load only the geometry rows for one country/admin level that intersect a viewport bbox.

    This is stricter than load_country_parquet(): it pushes bbox filtering into DuckDB so
    large countries like USA admin_2 do not need to load the whole level slice first.
    """
    min_lon, min_lat, max_lon, max_lat = bbox

    country_geom_file = DATA_ROOT / "countries" / iso3 / "geometry.parquet"
    crosswalk_file = DATA_ROOT / "countries" / iso3 / "crosswalk.json"
    global_geom_file = GEOMETRY_DIR / f"{iso3}.parquet"

    parquet_file = None
    crosswalk_data = None

    if _parquet_accessible(country_geom_file):
        parquet_file = country_geom_file
    elif crosswalk_file.exists() and _parquet_accessible(global_geom_file):
        crosswalk_data = _load_crosswalk(iso3)
        parquet_file = global_geom_file
    elif _parquet_accessible(global_geom_file):
        parquet_file = global_geom_file
    else:
        return None

    try:
        available_cols = parquet_columns(parquet_file)
        has_bbox = all(
            col in available_cols
            for col in ("bbox_min_lon", "bbox_max_lon", "bbox_min_lat", "bbox_max_lat")
        )
        has_centroid = "centroid_lon" in available_cols and "centroid_lat" in available_cols

        compare_filters = []
        if has_bbox:
            compare_filters = [
                ("bbox_max_lon", ">=", min_lon),
                ("bbox_min_lon", "<=", max_lon),
                ("bbox_max_lat", ">=", min_lat),
                ("bbox_min_lat", "<=", max_lat),
            ]
        elif has_centroid:
            compare_filters = [
                ("centroid_lon", ">=", min_lon),
                ("centroid_lon", "<=", max_lon),
                ("centroid_lat", ">=", min_lat),
                ("centroid_lat", "<=", max_lat),
            ]

        df = select_rows(
            parquet_file,
            exact_filters={"admin_level": admin_level},
            compare_filters=compare_filters,
        )

        if df.empty and not is_cloud_mode():
            filters = [("admin_level", "==", admin_level)]
            if has_bbox:
                filters.extend([
                    ("bbox_max_lon", ">=", min_lon),
                    ("bbox_min_lon", "<=", max_lon),
                    ("bbox_max_lat", ">=", min_lat),
                    ("bbox_min_lat", "<=", max_lat),
                ])
            elif has_centroid:
                filters.extend([
                    ("centroid_lon", ">=", min_lon),
                    ("centroid_lon", "<=", max_lon),
                    ("centroid_lat", ">=", min_lat),
                    ("centroid_lat", "<=", max_lat),
                ])
            df = pd.read_parquet(parquet_file, filters=filters)

        if crosswalk_data and not df.empty:
            _, reverse_map = _build_crosswalk_maps(crosswalk_data)
            df['local_loc_id'] = df['loc_id'].map(reverse_map)

        return df
    except Exception as e:
        logger.error(f"Error loading viewport geometry for {iso3} level={admin_level}: {e}")
        return None


def _resolve_geometry_source(iso3: str):
    """Resolve the parquet source and optional crosswalk for a country geometry lookup."""
    country_geom_file = DATA_ROOT / "countries" / iso3 / "geometry.parquet"
    crosswalk_file = DATA_ROOT / "countries" / iso3 / "crosswalk.json"
    global_geom_file = GEOMETRY_DIR / f"{iso3}.parquet"

    if _parquet_accessible(country_geom_file):
        return country_geom_file, None

    if crosswalk_file.exists() and _parquet_accessible(global_geom_file):
        crosswalk_data = _load_crosswalk(iso3)
        return global_geom_file, crosswalk_data

    if _parquet_accessible(global_geom_file):
        return global_geom_file, None

    return None, None


def load_geometry_rows_by_loc_ids(iso3: str, loc_ids: list[str]):
    """
    Load exact geometry rows for a country by loc_id list.

    This is the robust exact-fetch path used by diff loading:
    - no full country parquet load
    - loc_id exact-match pushdown in DuckDB / parquet filters
    """
    requested_ids = [canonicalize_loc_id(loc_id) for loc_id in loc_ids if loc_id]
    if not requested_ids:
        return pd.DataFrame()

    parquet_file, crosswalk_data = _resolve_geometry_source(iso3)
    if parquet_file is None:
        return pd.DataFrame()

    requested_set = set(requested_ids)
    query_ids = requested_ids
    reverse_map = None

    if crosswalk_data:
        local_to_geo, reverse_map = _build_crosswalk_maps(crosswalk_data)
        query_ids = [local_to_geo.get(loc_id, loc_id) for loc_id in requested_ids]

    try:
        df = select_rows(
            parquet_file,
            in_filters={"loc_id": query_ids},
        )

        if df.empty and not is_cloud_mode():
            df = pd.read_parquet(
                parquet_file,
                filters=[("loc_id", "in", query_ids)],
            )

        if df.empty:
            return df

        if reverse_map:
            df["source_loc_id"] = df["loc_id"]
            df["local_loc_id"] = df["loc_id"].map(lambda value: reverse_map.get(value, value))

            # Preserve the caller's id space. If the request asked for local ids,
            # return local ids; if it asked for source geometry ids, keep those.
            def resolve_requested_id(source_value):
                local_value = reverse_map.get(source_value)
                if local_value in requested_set:
                    return local_value
                return source_value

            df["loc_id"] = df["source_loc_id"].map(resolve_requested_id)
            df = df[
                df["loc_id"].isin(requested_set) |
                df["source_loc_id"].isin(requested_set)
            ]
        else:
            df = df[df["loc_id"].isin(requested_set)]
        return df
    except Exception as e:
        logger.error(f"Error loading exact geometry rows for {iso3}: {e}")
        return pd.DataFrame()


def _load_subcounty_rows_by_loc_ids(iso3: str, loc_ids: list[str]):
    """
    Load exact deep-admin geometry rows for canonical local loc_ids.

    Reuses the established subcounty geometry system documented in crosswalk
    `sub_admin_levels` instead of falling back to the country-level geometry bank.
    """
    requested_ids = [canonicalize_loc_id(loc_id) for loc_id in loc_ids if loc_id]
    if not requested_ids:
        return pd.DataFrame()

    crosswalk = _load_crosswalk(iso3) or {}
    sub_admin_levels = crosswalk.get("sub_admin_levels") or {}
    if not sub_admin_levels:
        return pd.DataFrame()

    grouped: dict[tuple[int, str | None], list[str]] = {}
    for loc_id in requested_ids:
        parts = str(loc_id).split("-")
        if not parts or parts[0] != iso3:
            continue
        segment_count = len(parts)
        if segment_count < 4:
            continue
        admin_level = segment_count - 1
        if f"admin_{admin_level}" not in sub_admin_levels:
            continue
        state_abbrev = parts[1] if len(parts) >= 2 else None
        grouped.setdefault((admin_level, state_abbrev), []).append(loc_id)

    frames = []
    for (admin_level, state_abbrev), group_ids in grouped.items():
        df = load_subcounty_geometry(iso3, admin_level=admin_level, state_abbrev=state_abbrev)
        if df is None or df.empty:
            continue
        filtered = df[df["loc_id"].isin(group_ids)]
        if not filtered.empty:
            frames.append(filtered)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _load_deep_geometry_index_rows(
    iso3: str,
    admin_level: int,
    parent_loc_id: str | None = None,
    bbox: tuple | None = None,
):
    """
    Load lightweight index rows for canonical deep admin levels.

    This keeps admin_3/admin_4/admin_5 on the same path as the working
    subcounty geometry loaders instead of falling back to country parquet files
    that stop at admin_2 for countries like USA.
    """
    frames = []

    if parent_loc_id:
        parts = parent_loc_id.split("-")
        state_abbrev = parts[1] if len(parts) >= 2 else None
        df = load_subcounty_geometry(iso3, admin_level=admin_level, state_abbrev=state_abbrev)
        if df is None or df.empty:
            return pd.DataFrame()
        if "parent_id" in df.columns:
            df = df[df["parent_id"] == parent_loc_id]
        return df

    if bbox is None:
        return pd.DataFrame()

    regions = get_regions_in_bbox(iso3, *bbox)
    for region_code in regions:
        df = load_subcounty_geometry(iso3, admin_level=admin_level, state_abbrev=region_code)
        if df is None or df.empty:
            continue
        df = _filter_df_by_bbox(df, bbox)
        if df is not None and not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def load_country_bounds():
    """
    Load country bounding boxes from global.csv for fast viewport filtering.
    Returns dict of iso3 -> (min_lon, min_lat, max_lon, max_lat).
    """
    global _country_bounds_cache
    if _country_bounds_cache is not None:
        return _country_bounds_cache

    _country_bounds_cache = {}

    df = load_global_countries()
    if df is None:
        return _country_bounds_cache

    try:
        from shapely.geometry import shape

        for _, row in df.iterrows():
            loc_id = row.get('loc_id')
            geom_str = row.get('geometry')

            if not loc_id or pd.isna(geom_str) or not geom_str:
                continue

            try:
                geom_data = json.loads(geom_str) if isinstance(geom_str, str) else geom_str
                geom = shape(geom_data)
                bounds = geom.bounds  # (minx, miny, maxx, maxy)
                _country_bounds_cache[loc_id] = bounds
            except Exception:
                continue

        logger.info(f"Loaded bounds for {len(_country_bounds_cache)} countries")
    except ImportError:
        logger.warning("shapely not available for country bounds computation")

    return _country_bounds_cache


def get_geometry_index(parent_loc_id: str | None = None, admin_level: int | None = None, bbox: tuple | None = None):
    """
    Return lightweight geometry index rows without polygon payloads.

    Intended for client-side diff loading. Returns loc_id hierarchy + bbox/centroid
    metadata so the browser can compute which loc_ids are visible and still missing.
    """
    if parent_loc_id:
        parts = parent_loc_id.split("-")
        iso3 = parts[0]
        if parent_loc_id == iso3:
            target_level = admin_level if admin_level is not None else 1
        else:
            target_level = admin_level if admin_level is not None else len(parts)

        if target_level >= 3:
            df = _load_deep_geometry_index_rows(
                iso3,
                admin_level=target_level,
                parent_loc_id=parent_loc_id,
            )
        else:
            df = load_country_parquet(iso3, admin_level=target_level)
        if df is None or df.empty:
            return {"rows": [], "count": 0, "parent_loc_id": parent_loc_id, "admin_level": target_level}

        if target_level < 3 and "parent_id" in df.columns:
            df = df[df["parent_id"] == parent_loc_id]
    else:
        target_level = admin_level if admin_level is not None else 0
        if target_level == 0:
            df = load_global_countries()
        elif target_level >= 3 and bbox is not None:
            countries = get_countries_in_bbox(*bbox)
            frames = []
            for iso3 in countries:
                deep_df = _load_deep_geometry_index_rows(
                    iso3,
                    admin_level=target_level,
                    bbox=bbox,
                )
                if deep_df is not None and not deep_df.empty:
                    frames.append(deep_df)
            df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        elif bbox is not None:
            countries = get_countries_in_bbox(*bbox)
            frames = []
            for iso3 in countries:
                viewport_df = load_country_parquet_viewport(iso3, target_level, bbox)
                if viewport_df is not None and not viewport_df.empty:
                    frames.append(viewport_df)
            df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        else:
            return {
                "rows": [],
                "count": 0,
                "parent_loc_id": None,
                "admin_level": target_level,
                "error": "parent_loc_id required for sub-country index queries",
            }
        if df is None or df.empty:
            return {"rows": [], "count": 0, "parent_loc_id": parent_loc_id, "admin_level": target_level}

    if bbox is not None and df is not None and not df.empty:
        min_lon, min_lat, max_lon, max_lat = bbox
        if all(col in df.columns for col in ["bbox_min_lon", "bbox_max_lon", "bbox_min_lat", "bbox_max_lat"]):
            mask = (
                (df["bbox_max_lon"] >= min_lon) &
                (df["bbox_min_lon"] <= max_lon) &
                (df["bbox_max_lat"] >= min_lat) &
                (df["bbox_min_lat"] <= max_lat)
            )
            df = df[mask]
        elif "centroid_lon" in df.columns and "centroid_lat" in df.columns:
            mask = (
                (df["centroid_lon"] >= min_lon) &
                (df["centroid_lon"] <= max_lon) &
                (df["centroid_lat"] >= min_lat) &
                (df["centroid_lat"] <= max_lat)
            )
            df = df[mask]

    index_columns = [
        "loc_id",
        "parent_id",
        "admin_level",
        "name",
        "code",
        "bbox_min_lon",
        "bbox_min_lat",
        "bbox_max_lon",
        "bbox_max_lat",
        "centroid_lon",
        "centroid_lat",
    ]
    available = [col for col in index_columns if col in df.columns]
    rows = df[available].to_dict("records") if df is not None and not df.empty else []

    return {
        "rows": rows,
        "count": len(rows),
        "parent_loc_id": parent_loc_id,
        "admin_level": target_level,
    }


def get_countries_in_bbox(min_lon: float, min_lat: float, max_lon: float, max_lat: float):
    """
    Return ISO3 codes whose bounds intersect the query bbox.
    """
    bounds = load_country_bounds()
    result = []

    for iso3, (c_min_lon, c_min_lat, c_max_lon, c_max_lat) in bounds.items():
        # Check bbox intersection
        if (c_max_lon >= min_lon and c_min_lon <= max_lon and
            c_max_lat >= min_lat and c_min_lat <= max_lat):
            result.append(iso3)

    return result


def _filter_df_for_point(df, lon: float, lat: float):
    """Filter candidate rows that could contain a point using bbox columns."""
    if df is None or len(df) == 0:
        return pd.DataFrame()

    result = df
    if all(col in result.columns for col in ("bbox_min_lon", "bbox_max_lon", "bbox_min_lat", "bbox_max_lat")):
        result = result[
            (result["bbox_max_lon"] >= lon) &
            (result["bbox_min_lon"] <= lon) &
            (result["bbox_max_lat"] >= lat) &
            (result["bbox_min_lat"] <= lat)
        ]
    return result


def _find_containing_row(df, lon: float, lat: float):
    """Return the first candidate row whose polygon covers the point."""
    if df is None or len(df) == 0:
        return None

    try:
        from shapely.geometry import Point, shape
    except Exception:
        logger.warning("shapely not available for point resolution")
        return None

    point = Point(float(lon), float(lat))
    candidates = _filter_df_for_point(df, lon, lat)
    if candidates.empty:
        return None

    if "admin_level" in candidates.columns:
        candidates = candidates.sort_values(["admin_level"], ascending=[False])

    for _, row in candidates.iterrows():
        geom_value = row.get("geometry")
        if not geom_value:
            continue
        try:
            geometry = fast_json_loads(geom_value) if isinstance(geom_value, str) else geom_value
            if not geometry or geometry.get("type") == "Point":
                continue
            if shape(geometry).covers(point):
                return row
        except Exception:
            continue
    return None


def _resolve_deepest_point_match(iso3: str, lon: float, lat: float, admin1_row=None, admin2_row=None):
    """Attempt admin_3+ point resolution where country-specific deep geometry exists."""
    crosswalk = _load_crosswalk(iso3) or {}
    sub_admin_levels = crosswalk.get("sub_admin_levels", {})
    if not sub_admin_levels:
        return None

    deep_levels = []
    for key in sub_admin_levels.keys():
        if not key.startswith("admin_"):
            continue
        try:
            level_value = int(key.split("_", 1)[1])
        except ValueError:
            continue
        if level_value >= 3:
            deep_levels.append(level_value)
    deep_levels.sort()
    if not deep_levels:
        return None

    admin1_local = translate_geometry_id_to_local_id(admin1_row.get("loc_id")) if admin1_row is not None else None
    admin2_local = translate_geometry_id_to_local_id(admin2_row.get("loc_id")) if admin2_row is not None else None

    state_abbrev = None
    if isinstance(admin1_local, str):
        parts = admin1_local.split("-")
        if len(parts) >= 2:
            state_abbrev = parts[1]

    deepest_match = None
    parent_scope = admin2_local or admin1_local

    for admin_level in deep_levels:
        df = load_subcounty_geometry(iso3, admin_level=admin_level, state_abbrev=state_abbrev)
        if df is None or df.empty:
            continue

        candidates = _filter_df_for_point(df, lon, lat)
        if candidates.empty:
            continue

        if parent_scope and "parent_id" in candidates.columns:
            parent_mask = (
                (candidates["parent_id"] == parent_scope) |
                candidates["parent_id"].astype(str).str.startswith(parent_scope + "-", na=False)
            )
            scoped = candidates[parent_mask]
            if not scoped.empty:
                candidates = scoped

        match_row = _find_containing_row(candidates, lon, lat)
        if match_row is not None:
            deepest_match = match_row
            parent_scope = canonicalize_loc_id(match_row.get("loc_id"))

    return deepest_match


def resolve_point_to_location(lon: float, lat: float, include_geometry: bool = True):
    """Resolve a point to the deepest available location."""
    lon = float(lon)
    lat = float(lat)

    country_df = load_global_countries()
    if country_df is None or country_df.empty:
        return {"error": "No global geometry available"}

    country_match = _find_containing_row(country_df, lon, lat)
    if country_match is None:
        return {"error": "No containing country found", "point": {"lon": lon, "lat": lat}}

    iso3 = country_match.get("loc_id")
    country_name = country_match.get("name") or iso3

    admin1_df = load_country_parquet_viewport(iso3, 1, (lon, lat, lon, lat))
    if admin1_df is None or admin1_df.empty:
        admin1_df = load_country_parquet(iso3, admin_level=1)
    admin1_match = _find_containing_row(admin1_df, lon, lat)

    admin2_df = load_country_parquet_viewport(iso3, 2, (lon, lat, lon, lat))
    if admin2_df is None or admin2_df.empty:
        admin2_df = load_country_parquet(iso3, admin_level=2)
    admin2_match = _find_containing_row(admin2_df, lon, lat)

    deepest_row = admin2_match or admin1_match or country_match
    deep_match = _resolve_deepest_point_match(iso3, lon, lat, admin1_row=admin1_match, admin2_row=admin2_match)
    if deep_match is not None:
        deepest_row = deep_match

    deepest_loc_id = deepest_row.get("loc_id") if deepest_row is not None else iso3
    deepest_name = deepest_row.get("name") if deepest_row is not None else country_name
    deepest_level = int(deepest_row.get("admin_level", 0)) if deepest_row is not None else 0

    stack = []
    for row in (country_match, admin1_match, admin2_match):
        if row is None:
            continue
        stack.append({
            "loc_id": row.get("loc_id"),
            "name": row.get("name"),
            "admin_level": int(row.get("admin_level", 0)),
        })
    if deepest_level >= 3 and deepest_row is not None:
        stack.append({
            "loc_id": deepest_loc_id,
            "name": deepest_name,
            "admin_level": deepest_level,
        })

    result = {
        "point": {"lon": lon, "lat": lat},
        "country": {"loc_id": iso3, "name": country_name},
        "matched": {
            "loc_id": deepest_loc_id,
            "name": deepest_name,
            "admin_level": deepest_level,
            "country_name": country_name,
            "iso3": iso3,
        },
        "stack": stack,
    }
    if include_geometry:
        result["geojson"] = get_selection_geometries([deepest_loc_id])
    return result


def calculate_coverage_from_parquet(iso3: str, from_level: int = 1):
    """
    Calculate coverage stats on-the-fly from actual parquet data.

    Args:
        iso3: Country ISO3 code
        from_level: Start counting from this level (default 1, excludes country level)

    Returns:
        dict with level_counts, geometry_counts, coverage, actual_depth, drillable_depth
    """
    # Load full parquet for the country
    df = load_country_parquet(iso3)
    if df is None or len(df) == 0:
        return {
            "level_counts": {},
            "geometry_counts": {},
            "coverage": 0,
            "actual_depth": 0,
            "drillable_depth": 0
        }

    # Calculate stats from actual data
    level_counts = {}
    geometry_counts = {}

    for level in df['admin_level'].unique():
        level = int(level)
        if level < from_level:
            continue
        level_df = df[df['admin_level'] == level]
        level_counts[str(level)] = len(level_df)
        # Count rows with actual geometry (not null/empty)
        has_geom = level_df['geometry'].notna() & (level_df['geometry'] != '')
        geometry_counts[str(level)] = int(has_geom.sum())

    # Calculate coverage
    total = sum(level_counts.values())
    with_geom = sum(geometry_counts.values())
    coverage = with_geom / total if total > 0 else 0

    # Calculate depth
    if level_counts:
        max_level = max(int(k) for k in level_counts.keys())
        min_level = min(int(k) for k in level_counts.keys())
        actual_depth = max_level - min_level + 1
        # Drillable depth = deepest level with geometry
        levels_with_geom = [int(k) for k, v in geometry_counts.items() if v > 0]
        drillable_depth = max(levels_with_geom) if levels_with_geom else min_level
    else:
        actual_depth = 0
        drillable_depth = 0

    return {
        "level_counts": level_counts,
        "geometry_counts": geometry_counts,
        "coverage": coverage,
        "actual_depth": actual_depth,
        "drillable_depth": drillable_depth
    }


def df_to_geojson(df, polygon_only=False):
    """
    Convert a DataFrame with geometry column to GeoJSON FeatureCollection.

    Args:
        df: DataFrame with geometry column (GeoJSON string)
        polygon_only: If True, skip Point geometries

    Performance notes:
        - Uses to_dict('records') instead of iterrows() (10-100x faster)
        - Uses orjson for JSON parsing when available (3-10x faster)
        - Pre-computes column list to avoid repeated lookups
    """
    if df is None or len(df) == 0:
        return {"type": "FeatureCollection", "features": []}

    # Get property columns once (all except geometry)
    prop_cols = [c for c in df.columns if c != 'geometry']

    # Convert to list of dicts - MUCH faster than iterrows()
    records = df.to_dict('records')

    features = []
    for row in records:
        geom_str = row.get('geometry')
        if not geom_str or (isinstance(geom_str, float) and pd.isna(geom_str)):
            continue

        try:
            geometry = fast_json_loads(geom_str) if isinstance(geom_str, str) else geom_str
        except (ValueError, TypeError):
            continue

        # Skip Point geometries if polygon_only
        if polygon_only and geometry.get('type') == 'Point':
            continue

        # Build properties - only include non-null values
        properties = {col: row[col] for col in prop_cols
                      if row.get(col) is not None and not (isinstance(row[col], float) and pd.isna(row[col]))}

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

    If debug=True, calculates coverage info on-the-fly from parquet files.
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

    # If debug mode, calculate coverage info on-the-fly from parquet
    if debug:
        for feature in geojson.get("features", []):
            loc_id = feature.get("properties", {}).get("loc_id")
            if loc_id:
                # Calculate from actual parquet data, starting from level 1
                cov_info = calculate_coverage_from_parquet(loc_id, from_level=1)
                feature["properties"]["actual_depth"] = cov_info.get("actual_depth", 0)
                feature["properties"]["expected_depth"] = cov_info.get("actual_depth", 0)
                feature["properties"]["coverage"] = cov_info.get("coverage", 0)
                feature["properties"]["level_counts"] = cov_info.get("level_counts", {})
                feature["properties"]["geometry_counts"] = cov_info.get("geometry_counts", {})
                feature["properties"]["drillable_depth"] = cov_info.get("drillable_depth", 0)
            else:
                feature["properties"]["actual_depth"] = 0
                feature["properties"]["expected_depth"] = 0
                feature["properties"]["coverage"] = 0
                feature["properties"]["level_counts"] = {}
                feature["properties"]["geometry_counts"] = {}
                feature["properties"]["drillable_depth"] = 0

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

    If direct children have no geometry (hierarchy-only levels),
    recursively finds the first descendant level with geometry.

    Examples:
    - loc_id="USA" -> Returns US counties (skips admin_1 which has no geometry)
    - loc_id="USA-CA" -> Returns California counties (admin_2)
    - loc_id="FRA" -> Returns French communes (skips intermediate levels)
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

    # Find children with geometry, drilling through hierarchy-only levels
    current_parents = {loc_id}
    children = pd.DataFrame()
    max_depth = 10  # Safety limit

    for _ in range(max_depth):
        # Get all direct children of current parent set
        children = df[df["parent_id"].isin(current_parents)]

        if len(children) == 0:
            return {
                "geojson": {"type": "FeatureCollection", "features": []},
                "count": 0,
                "level": "none",
                "parent_loc_id": loc_id,
                "message": f"No child locations for {loc_id}"
            }

        # Check if these children have geometry
        children_with_geom = children[children["geometry"].notna()]

        if len(children_with_geom) > 0:
            # Found children with geometry
            children = children_with_geom
            break

        # No geometry at this level - drill down further
        # Use these children as the new parent set
        current_parents = set(children["loc_id"].tolist())
        logger.debug(f"Level has no geometry, drilling to {len(current_parents)} children")

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
    Get detailed information about a specific location for popup display.

    Returns:
        - Basic info: loc_id, name, admin_level, parent_id
        - Children counts: children_count, children_by_level, descendants_count, descendants_by_level
        - Memberships: regional groupings (G20, BRICS, etc.) for countries
        - Dataset count: number of datasets available for this location

    Uses pre-computed children counts from parquet when available.
    """
    parts = loc_id.split("-")
    if not parts:
        return {"error": "Invalid loc_id"}

    iso3 = parts[0]
    result = {
        "loc_id": loc_id,
        "admin_level": len(parts) - 1,  # USA=0, USA-CA=1, USA-CA-037=2
        "memberships": [],
        "dataset_count": 0
    }

    # For country level, check global.csv first
    if len(parts) == 1:
        df = load_global_countries()
        if df is not None:
            location = df[df["loc_id"] == loc_id]
            if len(location) > 0:
                row = location.iloc[0]
                result["name"] = row.get("name")
                result["admin_level"] = 0

                # Get children info from country parquet
                country_df = load_country_parquet(iso3)
                if country_df is not None and len(country_df) > 0:
                    country_row = country_df[country_df["loc_id"] == loc_id]
                    if len(country_row) > 0:
                        cr = country_row.iloc[0]
                        result["children_count"] = int(cr.get("children_count", 0)) if pd.notna(cr.get("children_count")) else 0
                        result["children_by_level"] = cr.get("children_by_level", "{}")
                        result["descendants_count"] = int(cr.get("descendants_count", 0)) if pd.notna(cr.get("descendants_count")) else 0
                        result["descendants_by_level"] = cr.get("descendants_by_level", "{}")
                    else:
                        # Calculate from parquet if not in parquet (country-only entry)
                        children = country_df[country_df["parent_id"] == loc_id]
                        result["children_count"] = len(children)
                        result["descendants_count"] = len(country_df) - 1  # Exclude country itself
                    result["max_depth"] = int(country_df['admin_level'].max())
                    result["has_children"] = result.get("children_count", 0) > 0 or result["max_depth"] > 0
                else:
                    result["children_count"] = 0
                    result["descendants_count"] = 0
                    result["max_depth"] = 0
                    result["has_children"] = False

                # Get memberships from conversions.json
                result["memberships"] = _get_country_memberships(iso3)

                # Add a few lightweight static country facts for navigation popups
                static_df = load_world_factbook_static()
                if static_df is not None:
                    static_row = static_df[static_df["loc_id"] == loc_id]
                    if len(static_row) > 0:
                        sr = static_row.iloc[0]
                        result["capital_name"] = sr.get("capital_name")
                        area_total = sr.get("area_total_sq_km")
                        coastline = sr.get("coastline_km")
                        if pd.notna(area_total):
                            result["area_total_sq_km"] = float(area_total)
                        if pd.notna(coastline):
                            result["coastline_km"] = float(coastline)

                # Get dataset counts by level
                result["dataset_counts"] = _get_dataset_counts_by_level(loc_id)
                result["dataset_count"] = sum(result["dataset_counts"].values())

                # Get country-specific level names
                result["level_names"] = _get_level_names(iso3)

                return result

    # For sub-national, check country parquet
    df = load_country_parquet(iso3)
    if df is None:
        return {"error": f"No data for {iso3}"}

    location = df[df["loc_id"] == loc_id]
    if len(location) == 0:
        return {"error": f"Location not found: {loc_id}"}

    row = location.iloc[0]
    result["name"] = row.get("name")
    result["admin_level"] = int(row.get("admin_level", 0))
    result["parent_id"] = row.get("parent_id")

    # Get parent name for "Part of" display
    parent_id = row.get("parent_id")
    if parent_id:
        parent_names = _get_parent_hierarchy(df, parent_id, iso3)
        result["memberships"] = [f"Part of: {', '.join(parent_names)}"] if parent_names else []
    else:
        result["memberships"] = []

    # Use pre-computed children counts if available
    result["children_count"] = int(row.get("children_count", 0)) if pd.notna(row.get("children_count")) else 0
    result["children_by_level"] = row.get("children_by_level", "{}")
    result["descendants_count"] = int(row.get("descendants_count", 0)) if pd.notna(row.get("descendants_count")) else 0
    result["descendants_by_level"] = row.get("descendants_by_level", "{}")
    result["has_children"] = result["children_count"] > 0

    # Get dataset counts by level
    result["dataset_counts"] = _get_dataset_counts_by_level(loc_id)
    result["dataset_count"] = sum(result["dataset_counts"].values())

    # Get country-specific level names
    result["level_names"] = _get_level_names(iso3)

    return result


def _get_country_memberships(iso3: str) -> list:
    """
    Get regional grouping memberships for a country from conversions.json.
    Returns list of group names this country belongs to.

    Regional groupings are stored as {group_name: {code, countries}} in conversions.json.
    """
    try:
        from .geography import get_conversions_data
        conversions = get_conversions_data()
        if not conversions:
            return []

        regional_groupings = conversions.get("regional_groupings", {})
        memberships = []

        # Priority groups to show first (most recognizable)
        priority_groups = ['G7', 'G20', 'European_Union', 'NATO', 'BRICS', 'OECD', 'OPEC', 'ASEAN']

        for group_name, group_data in regional_groupings.items():
            # Handle both dict format {code, countries} and list format
            if isinstance(group_data, dict):
                countries = group_data.get("countries", [])
            else:
                countries = group_data if isinstance(group_data, list) else []

            if iso3 in countries:
                # Use code if available, otherwise format group_name
                if isinstance(group_data, dict) and group_data.get("code"):
                    display_name = group_data["code"]
                else:
                    display_name = group_name.replace("_", " ")
                memberships.append((group_name, display_name))

        # Sort: priority groups first, then alphabetically
        def sort_key(item):
            group_name, display_name = item
            if group_name in priority_groups:
                return (0, priority_groups.index(group_name))
            return (1, display_name)

        memberships.sort(key=sort_key)
        return [display_name for _, display_name in memberships]
    except Exception:
        return []


def _get_dataset_counts_by_level(loc_id: str) -> dict:
    """
    Count datasets by geographic level for this location.
    Returns dict like {"country": 20, "state": 0, "county": 3}
    """
    try:
        from .data_loading import get_data_catalog
        catalog = get_data_catalog()
        if not catalog:
            return {}

        # Extract country code from loc_id
        iso3 = loc_id.split("-")[0] if "-" in loc_id else loc_id

        counts = {}
        for source in catalog.get("sources", []):
            geo_coverage = source.get("geographic_coverage", {})
            country_codes = geo_coverage.get("country_codes_all", [])
            geo_level = source.get("geographic_level", "country")

            if iso3 in country_codes:
                counts[geo_level] = counts.get(geo_level, 0) + 1

        return counts
    except Exception:
        return {}


def _get_dataset_count(loc_id: str) -> int:
    """
    Count how many datasets in the catalog cover this location.
    Uses geographic_coverage.country_codes_all field from catalog.json.
    """
    counts = _get_dataset_counts_by_level(loc_id)
    return sum(counts.values())


# Default level names (fallback if conversions.json unavailable)
DEFAULT_LEVEL_NAMES = {
    1: "first-level divisions",
    2: "second-level divisions",
    3: "third-level divisions",
    4: "localities",
    5: "neighborhoods",
    6: "blocks"
}

# Cache for canonical deep admin geometry files (admin_3+ such as tracts,
# block groups, and blocks). Parallel geometry tracks like ZCTA or tribal
# should not be routed through this admin hierarchy.
_subcounty_geometry_cache = {}


def load_subcounty_geometry(iso3: str, admin_level: int, state_abbrev: str = None):
    """
    Load canonical deep-admin geometry for admin_3+.

    Supports tiered geometry files stored in:
    - geometry_{type}.parquet (national files when a country stores deep
      admin geometry in one file)
    - geometry_{type}/{ISO3}-{region}.parquet (regional files)

    For USA, the structure is:
    - Level 3 (admin_3): tract
    - Level 4 (admin_4): block group
    - Level 5 (admin_5): block

    Parallel geometry tracks such as ZCTA, tribal, watersheds, or parks are
    handled elsewhere and are not part of the admin_0..admin_5 path.

    Args:
        iso3: Country code
        admin_level: Canonical admin level (3+)
        state_abbrev: Region/state code (required for state-partitioned levels)

    Returns:
        DataFrame or None
    """
    countries_dir = DATA_ROOT / "countries" / iso3

    crosswalk = _load_crosswalk(iso3)
    sub_admin_levels = (crosswalk or {}).get("sub_admin_levels", {})
    level_config = sub_admin_levels.get(f"admin_{admin_level}")

    if not level_config:
        return None

    geom_type = level_config.get("folder") or level_config.get("name")
    is_partitioned = bool(state_abbrev or iso3 == "USA")

    if not is_partitioned:
        # National file
        cache_key = f"{iso3}_{geom_type}"
        if cache_key in _subcounty_geometry_cache:
            return _subcounty_geometry_cache[cache_key]

        file_path = countries_dir / "geometry" / f"{geom_type}.parquet"
        if not is_cloud_mode() and not file_path.exists():
            logger.debug(f"Sub-county geometry not found: {file_path}")
            return None

        try:
            df = select_rows(file_path)
            if df.empty:
                df = pd.read_parquet(file_path)
            _subcounty_geometry_cache[cache_key] = df
            logger.debug(f"Loaded {len(df)} features from {file_path}")
            return df
        except Exception as e:
            logger.error(f"Error loading sub-county geometry: {e}")
            return None

    else:
        # Partitioned by region/state
        if not state_abbrev:
            logger.warning(f"Region/state code required for {iso3} admin level {admin_level}")
            return None

        subdir = geom_type  # e.g., "tract", "blockgroup", "block"
        cache_key = f"{iso3}_geometry_{subdir}_{state_abbrev}"

        if cache_key in _subcounty_geometry_cache:
            return _subcounty_geometry_cache[cache_key]

        file_path = countries_dir / "geometry" / subdir / f"{iso3}-{state_abbrev}.parquet"
        if not is_cloud_mode() and not file_path.exists():
            logger.debug(f"Sub-county geometry not found: {file_path}")
            return None

        try:
            df = select_rows(file_path)
            if df.empty:
                df = pd.read_parquet(file_path)
            _subcounty_geometry_cache[cache_key] = df
            logger.debug(f"Loaded {len(df)} features for {state_abbrev} level {admin_level}")
            return df
        except Exception as e:
            logger.error(f"Error loading sub-county geometry: {e}")
            return None


def get_states_in_bbox(min_lon: float, min_lat: float, max_lon: float, max_lat: float):
    """
    Return state abbreviations whose bounds intersect the query bbox.
    Uses the USA geometry.parquet to find states (admin_level=1).
    """
    df = load_country_parquet("USA", admin_level=1)
    if df is None or len(df) == 0:
        return []

    result = []
    for _, row in df.iterrows():
        # Check bbox intersection
        if 'bbox_min_lon' in df.columns:
            c_min_lon = row.get('bbox_min_lon')
            c_min_lat = row.get('bbox_min_lat')
            c_max_lon = row.get('bbox_max_lon')
            c_max_lat = row.get('bbox_max_lat')

            if pd.notna(c_min_lon) and pd.notna(c_max_lon):
                if (c_max_lon >= min_lon and c_min_lon <= max_lon and
                    c_max_lat >= min_lat and c_min_lat <= max_lat):
                    # Extract state abbrev from loc_id (e.g., "USA-CA" -> "CA")
                    loc_id = row.get('loc_id', '')
                    if '-' in loc_id:
                        state_abbrev = loc_id.split('-')[1]
                        result.append(state_abbrev)

    return result


def _extract_display_name(value):
    """Extract display name from level name value (handles both string and array formats)."""
    if isinstance(value, list) and len(value) > 0:
        return value[0]  # First element is display name
    return value  # Already a string


def _load_admin_levels():
    """Load admin level names from reference/admin_levels.json."""
    data = load_reference_json("admin_levels.json")
    if isinstance(data, dict):
        return data
    return {}


def _get_level_names(iso3: str) -> dict:
    """
    Get country-specific level names from reference/admin_levels.json.
    Returns dict like {1: "states", 2: "counties", 3: "places"} for USA.

    Format in admin_levels.json is array: [display_name, synonym1, synonym2, ...]
    This function extracts only the display name (first element).

    Falls back to DEFAULT_LEVEL_NAMES if country not found.
    """
    try:
        admin_levels = _load_admin_levels()
        if not admin_levels:
            return DEFAULT_LEVEL_NAMES

        # Get country-specific names
        country_names = admin_levels.get(iso3)
        if country_names:
            # Convert string keys to int keys, extract display name from arrays
            return {int(k): _extract_display_name(v) for k, v in country_names.items() if not k.startswith("_")}

        # Use _default from admin_levels.json if available
        default_names = admin_levels.get("_default")
        if default_names:
            return {int(k): _extract_display_name(v) for k, v in default_names.items() if not k.startswith("_")}

        return DEFAULT_LEVEL_NAMES
    except Exception as e:
        logger.debug(f"Error loading level names for {iso3}: {e}")
        return DEFAULT_LEVEL_NAMES


def _get_parent_hierarchy(df, parent_id: str, iso3: str) -> list:
    """
    Get list of parent names from immediate parent up to country.
    Returns list like ["California", "United States of America"].
    """
    names = []
    current_id = parent_id
    max_depth = 5  # Safety limit

    for _ in range(max_depth):
        if not current_id:
            break

        # Check if it's the country level
        if current_id == iso3:
            # Get country name from global.csv
            global_df = load_global_countries()
            if global_df is not None:
                country_row = global_df[global_df["loc_id"] == iso3]
                if len(country_row) > 0:
                    names.append(country_row.iloc[0].get("name", iso3))
            else:
                names.append(iso3)
            break

        # Find in country parquet
        parent_row = df[df["loc_id"] == current_id]
        if len(parent_row) == 0:
            break

        parent_name = parent_row.iloc[0].get("name", current_id)
        names.append(parent_name)

        # Move up to next parent
        current_id = parent_row.iloc[0].get("parent_id")

    return names


def _load_subcounty_for_viewport(iso3: str, admin_level: int, buffered_bbox: tuple, debug: bool = False):
    """
    Load sub-county geometry (levels 3+) from tiered files for a specific country.

    Args:
        iso3: Country code
        admin_level: Target admin level (3+)
        buffered_bbox: (min_lon, min_lat, max_lon, max_lat) with buffer
        debug: If True, add debug properties

    Returns:
        List of GeoJSON features
    """
    all_features = []
    logger.info(f"Loading subcounty geometry for {iso3} level {admin_level}, bbox={buffered_bbox}")

    # Check if this country has sub-county geometry at this level
    # First try non-partitioned (national file)
    df = load_subcounty_geometry(iso3, admin_level=admin_level)

    if df is not None and len(df) > 0:
        # National file exists - filter by bbox
        logger.info(f"Found national file with {len(df)} features for {iso3} level {admin_level}")
        df_filtered = _filter_df_by_bbox(df, buffered_bbox)
        logger.info(f"After bbox filter: {len(df_filtered)} features")
        geojson = df_to_geojson(df_filtered, polygon_only=True)
        if debug:
            for feature in geojson.get("features", []):
                feature["properties"]["current_admin_level"] = admin_level
        all_features.extend(geojson.get("features", []))

    else:
        # Try partitioned files (by state/region)
        # Get regions that intersect the bbox
        logger.info(f"No national file for {iso3} level {admin_level}, trying partitioned files")
        regions = get_regions_in_bbox(iso3, *buffered_bbox)
        logger.info(f"Regions in bbox: {regions}")

        if regions:
            for region_code in regions:
                df = load_subcounty_geometry(iso3, admin_level=admin_level, state_abbrev=region_code)
                if df is None or len(df) == 0:
                    logger.debug(f"No data for {iso3}-{region_code} level {admin_level}")
                    continue

                logger.info(f"Loaded {len(df)} features for {iso3}-{region_code} level {admin_level}")
                df_filtered = _filter_df_by_bbox(df, buffered_bbox)
                logger.info(f"After bbox filter: {len(df_filtered)} features")
                geojson = df_to_geojson(df_filtered, polygon_only=True)
                if debug:
                    for feature in geojson.get("features", []):
                        feature["properties"]["current_admin_level"] = admin_level
                all_features.extend(geojson.get("features", []))
        else:
            logger.warning(f"No regions found in bbox for {iso3}")

    logger.info(f"Total subcounty features for {iso3} level {admin_level}: {len(all_features)}")
    return all_features


def _filter_df_by_bbox(df, buffered_bbox):
    """Filter DataFrame by bounding box using bbox or centroid columns."""
    if 'bbox_min_lon' in df.columns:
        mask = (
            (df['bbox_max_lon'] >= buffered_bbox[0]) &
            (df['bbox_min_lon'] <= buffered_bbox[2]) &
            (df['bbox_max_lat'] >= buffered_bbox[1]) &
            (df['bbox_min_lat'] <= buffered_bbox[3])
        )
        return df[mask]
    elif 'centroid_lon' in df.columns:
        mask = (
            (df['centroid_lon'] >= buffered_bbox[0]) &
            (df['centroid_lon'] <= buffered_bbox[2]) &
            (df['centroid_lat'] >= buffered_bbox[1]) &
            (df['centroid_lat'] <= buffered_bbox[3])
        )
        return df[mask]
    return df


_crosswalk_reverse_cache: dict = {}


def _get_crosswalk_reverse(iso3: str) -> dict:
    """
    Load crosswalk.json for iso3 and return a reverse map:
      geo_loc_id -> local_abbrev  (e.g. "USA-G109436" -> "NY")

    Result is cached in memory. Returns empty dict if no crosswalk exists.
    """
    if iso3 in _crosswalk_reverse_cache:
        return _crosswalk_reverse_cache[iso3]

    cw = _load_crosswalk(iso3)
    if not cw:
        _crosswalk_reverse_cache[iso3] = {}
        return {}

    try:
        mappings = cw.get("mappings", {})
        # mappings: "USA-NY" -> "USA-G109436"
        # reverse:  "USA-G109436" -> "NY"
        reverse = {}
        for local_loc_id, geo_loc_id in mappings.items():
            # Extract the local abbreviation from "USA-NY" -> "NY"
            parts = local_loc_id.split("-", 1)
            if len(parts) == 2:
                reverse[geo_loc_id] = parts[1]
        _crosswalk_reverse_cache[iso3] = reverse
        return reverse
    except Exception as e:
        logger.warning(f"Failed to load crosswalk for {iso3}: {e}")
        _crosswalk_reverse_cache[iso3] = {}
        return {}


def get_regions_in_bbox(iso3: str, min_lon: float, min_lat: float, max_lon: float, max_lat: float):
    """
    Return local region/state codes whose bounds intersect the query bbox.
    Uses the country's geometry.parquet to find admin_level=1 regions, then
    resolves geo loc_ids back to local codes via the crosswalk reverse map.
    """
    df = load_country_parquet(iso3, admin_level=1)
    if df is None or len(df) == 0:
        logger.debug(f"No admin_level=1 data found for {iso3}")
        return []

    crosswalk_reverse = _get_crosswalk_reverse(iso3)

    def resolve_region_code(loc_id: str) -> str:
        """Convert a geo loc_id to a local region code via crosswalk, or fall back to raw segment."""
        if loc_id in crosswalk_reverse:
            return crosswalk_reverse[loc_id]
        # No crosswalk entry - extract second segment as-is
        parts = loc_id.split("-", 1)
        return parts[1] if len(parts) == 2 else loc_id

    result = []
    has_bbox = 'bbox_min_lon' in df.columns
    has_centroid = 'centroid_lon' in df.columns

    if not has_bbox and not has_centroid:
        logger.warning(f"No bbox or centroid columns in {iso3} admin_level=1 parquet")
        for _, row in df.iterrows():
            loc_id = row.get('loc_id', '')
            if loc_id:
                result.append(resolve_region_code(loc_id))
        logger.debug(f"Returning all {len(result)} regions for {iso3} (no spatial filter)")
        return result

    for _, row in df.iterrows():
        intersects = False

        if has_bbox:
            c_min_lon = row.get('bbox_min_lon')
            c_min_lat = row.get('bbox_min_lat')
            c_max_lon = row.get('bbox_max_lon')
            c_max_lat = row.get('bbox_max_lat')

            if pd.notna(c_min_lon) and pd.notna(c_max_lon):
                intersects = (c_max_lon >= min_lon and c_min_lon <= max_lon and
                              c_max_lat >= min_lat and c_min_lat <= max_lat)
        elif has_centroid:
            c_lon = row.get('centroid_lon')
            c_lat = row.get('centroid_lat')
            if pd.notna(c_lon) and pd.notna(c_lat):
                intersects = (c_lon >= min_lon and c_lon <= max_lon and
                              c_lat >= min_lat and c_lat <= max_lat)

        if intersects:
            loc_id = row.get('loc_id', '')
            if loc_id:
                result.append(resolve_region_code(loc_id))

    logger.debug(f"Found {len(result)} regions in bbox for {iso3}: {result}")
    return result


def get_viewport_geometry(admin_level: int, bbox: tuple, debug: bool = False):
    """
    Load features at admin_level within bounding box.

    Args:
        admin_level: Target admin level (0=countries, 1=states, 2=counties, 3=ZCTAs,
                     4=census tracts, 5=block groups, 6=blocks)
        bbox: (min_lon, min_lat, max_lon, max_lat)
        debug: If True, add coverage info for level 0 features

    Returns:
        GeoJSON FeatureCollection with features in viewport
    """
    min_lon, min_lat, max_lon, max_lat = bbox

    # Buffer for smooth panning - proportional to viewport size.
    # Cloud/S3 mode: all levels at 1% to keep feature caps focused on visible area.
    # Local mode (restore when switching back): smart scaling by level:
    #   level 0-1: 0.50  (world/country - few large shapes, prefetch aggressively)
    #   level 2:   0.30  (county/district view)
    #   level 3+:  0.15  (tracts/blocks - many small shapes, tight budget)
    if admin_level >= 3:
        buffer_factor = 0.01
    elif admin_level == 2:
        buffer_factor = 0.01
    else:
        buffer_factor = 0.01
    viewport_width = max_lon - min_lon
    viewport_height = max_lat - min_lat
    buffer_lon = viewport_width * buffer_factor
    buffer_lat = viewport_height * buffer_factor
    buffered_bbox = (
        min_lon - buffer_lon,
        min_lat - buffer_lat,
        max_lon + buffer_lon,
        max_lat + buffer_lat
    )

    # For level 0 (countries), just return from global.csv
    if admin_level == 0:
        df = load_global_countries()
        if df is None:
            return {"type": "FeatureCollection", "features": []}

        # Filter by bbox if bbox columns exist
        if 'bbox_min_lon' in df.columns:
            mask = (
                (df['bbox_max_lon'] >= buffered_bbox[0]) &
                (df['bbox_min_lon'] <= buffered_bbox[2]) &
                (df['bbox_max_lat'] >= buffered_bbox[1]) &
                (df['bbox_min_lat'] <= buffered_bbox[3])
            )
            df = df[mask]

        geojson = df_to_geojson(df, polygon_only=True)

        # Add coverage info for debug mode (calculate on-the-fly from parquet)
        if debug:
            for feature in geojson.get("features", []):
                loc_id = feature.get("properties", {}).get("loc_id")
                feature["properties"]["current_admin_level"] = admin_level

                if loc_id:
                    # Calculate from actual parquet data, starting from level 1
                    cov_info = calculate_coverage_from_parquet(loc_id, from_level=1)
                    feature["properties"]["actual_depth"] = cov_info.get("actual_depth", 0)
                    feature["properties"]["expected_depth"] = cov_info.get("actual_depth", 0)
                    feature["properties"]["coverage"] = cov_info.get("coverage", 0)
                    feature["properties"]["level_counts"] = cov_info.get("level_counts", {})
                    feature["properties"]["geometry_counts"] = cov_info.get("geometry_counts", {})
                    feature["properties"]["drillable_depth"] = cov_info.get("drillable_depth", 0)
                else:
                    feature["properties"]["actual_depth"] = 0
                    feature["properties"]["expected_depth"] = 0
                    feature["properties"]["coverage"] = 0
                    feature["properties"]["level_counts"] = {}
                    feature["properties"]["geometry_counts"] = {}
                    feature["properties"]["drillable_depth"] = 0

        return geojson

    # Find countries that intersect the viewport
    countries = get_countries_in_bbox(*buffered_bbox)

    if not countries:
        return {"type": "FeatureCollection", "features": []}

    all_features = []

    # For admin levels 3+, try sub-county geometry files for each country
    countries_with_subcounty = []
    if admin_level >= 3:
        for iso3 in countries:
            subcounty_features = _load_subcounty_for_viewport(iso3, admin_level, buffered_bbox, debug)
            if subcounty_features:
                all_features.extend(subcounty_features)
                countries_with_subcounty.append(iso3)
        # Remove countries that were handled via subcounty geometry
        countries = [c for c in countries if c not in countries_with_subcounty]

    for iso3 in countries:
        # Load only the visible slice for this level from parquet (bbox pushdown).
        df = load_country_parquet_viewport(iso3, admin_level, buffered_bbox)

        if df is None or len(df) == 0:
            # Fallback: try one level up if no data at this level
            if admin_level > 0:
                df = load_country_parquet_viewport(iso3, admin_level - 1, buffered_bbox)
            if df is None or len(df) == 0:
                continue

        # Convert to features
        geojson = df_to_geojson(df, polygon_only=True)

        # Add debug info for sub-country levels (calculate on-the-fly from parquet)
        if debug:
            # Calculate from actual parquet data, starting from current admin_level
            cov_info = calculate_coverage_from_parquet(iso3, from_level=admin_level)

            for feature in geojson.get("features", []):
                feature["properties"]["current_admin_level"] = admin_level
                feature["properties"]["actual_depth"] = cov_info.get("actual_depth", 0)
                feature["properties"]["expected_depth"] = cov_info.get("actual_depth", 0)
                feature["properties"]["coverage"] = cov_info.get("coverage", 0)
                feature["properties"]["level_counts"] = cov_info.get("level_counts", {})
                feature["properties"]["geometry_counts"] = cov_info.get("geometry_counts", {})
                feature["properties"]["drillable_depth"] = cov_info.get("drillable_depth", 0)

        all_features.extend(geojson.get("features", []))

    # Per-level feature cap to limit browser memory and S3 transfer volume.
    # Tighter caps at deep zoom where shapes are small and viewport covers fewer.
    MAX_FEATURES_BY_LEVEL = {
        0: 300,   # Countries - global.csv is local anyway
        1: 500,   # States / provinces
        2: 1000,  # Counties / districts
        3: 500,   # Tracts / ZCTAs
        4: 300,   # Block groups
        5: 200,   # Blocks
    }
    MAX_FEATURES = MAX_FEATURES_BY_LEVEL.get(admin_level, 200)
    truncated = False
    if len(all_features) > MAX_FEATURES:
        logger.warning(f"Truncating {len(all_features)} features to {MAX_FEATURES} for admin level {admin_level}")

        # Calculate viewport center
        center_lon = (min_lon + max_lon) / 2
        center_lat = (min_lat + max_lat) / 2

        # Pre-compute distances once (O(n)) instead of during sort (O(n log n) function calls)
        distances = []
        for f in all_features:
            props = f.get("properties", {})
            f_lon = props.get("centroid_lon")
            f_lat = props.get("centroid_lat")
            if f_lon is None or f_lat is None:
                # Fallback to bbox center
                b1, b2 = props.get("bbox_min_lon"), props.get("bbox_max_lon")
                b3, b4 = props.get("bbox_min_lat"), props.get("bbox_max_lat")
                if b1 is not None and b2 is not None:
                    f_lon, f_lat = (b1 + b2) / 2, (b3 + b4) / 2
                else:
                    distances.append(float('inf'))
                    continue
            distances.append((f_lon - center_lon) ** 2 + (f_lat - center_lat) ** 2)

        # Sort indices by distance, take first N
        sorted_indices = sorted(range(len(all_features)), key=lambda i: distances[i])
        all_features = [all_features[i] for i in sorted_indices[:MAX_FEATURES]]
        truncated = True

    return {
        "type": "FeatureCollection",
        "features": all_features,
        "metadata": {
            "admin_level": admin_level,
            "countries_searched": len(countries),
            "feature_count": len(all_features),
            "truncated": truncated
        }
    }


def clear_cache():
    """Clear all cached geometry data. Useful when data files are updated."""
    global _country_parquet_cache, _global_countries_cache, _country_bounds_cache, _subcounty_geometry_cache, _country_parquet_waiters
    with _country_parquet_cache_lock:
        _country_parquet_cache = {}
        _country_parquet_inflight.clear()
        for waiter in _country_parquet_waiters.values():
            waiter.set()
        _country_parquet_waiters = {}
    _global_countries_cache = None
    _country_bounds_cache = None
    _subcounty_geometry_cache = {}
    logger.info("Geometry cache cleared")


def prewarm_geometry() -> None:
    """Pre-warm the global countries CSV into memory.

    All deeper geometry (country level 1/2/3) is loaded on demand as users zoom.
    Only the global CSV (country outlines at admin level 0) is pre-warmed since
    it is needed on every page load.
    """
    import time as _time

    if not is_cloud_mode():
        return

    t0 = _time.monotonic()
    try:
        df = load_global_countries()
        elapsed = _time.monotonic() - t0
        if df is not None and not df.empty:
            logger.info("prewarm geometry global CSV: %d rows in %.1fs", len(df), elapsed)
        else:
            logger.warning("prewarm geometry global CSV: empty result in %.1fs", elapsed)
    except Exception as exc:
        logger.warning("prewarm geometry global CSV failed: %s", exc)

    logger.info("Geometry pre-warmer complete")


def get_selection_geometries(loc_ids: list):
    """
    Get geometries for specific loc_ids for disambiguation selection mode.

    Args:
        loc_ids: List of location IDs to fetch geometries for

    Returns:
        GeoJSON FeatureCollection with requested geometries
    """
    if not loc_ids:
        return {"type": "FeatureCollection", "features": []}

    features = []

    # Group by country (first part of loc_id) for efficient loading
    by_country = {}
    for loc_id in loc_ids:
        parts = loc_id.split("-")
        iso3 = parts[0]
        if iso3 not in by_country:
            by_country[iso3] = []
        by_country[iso3].append(loc_id)

    # For each country, load parquet and filter to requested loc_ids
    for iso3, country_loc_ids in by_country.items():
        # Check if any are country-level (just the ISO3 code)
        country_level_ids = [lid for lid in country_loc_ids if lid == iso3]
        sub_level_ids = [lid for lid in country_loc_ids if lid != iso3]
        deep_level_ids = []
        regular_sub_level_ids = []
        crosswalk = _load_crosswalk(iso3) or {}
        sub_admin_levels = crosswalk.get("sub_admin_levels") or {}
        for lid in sub_level_ids:
            parts = str(lid).split("-")
            segment_count = len(parts)
            admin_level = segment_count - 1
            if segment_count >= 4 and f"admin_{admin_level}" in sub_admin_levels:
                deep_level_ids.append(lid)
            else:
                regular_sub_level_ids.append(lid)

        # Fetch country-level from global.csv
        if country_level_ids:
            global_df = load_global_countries()
            if global_df is not None:
                country_rows = global_df[global_df["loc_id"].isin(country_level_ids)]
                if len(country_rows) > 0:
                    country_geojson = df_to_geojson(country_rows, polygon_only=True)
                    features.extend(country_geojson.get("features", []))

        # Fetch canonical deep sub-country levels from the existing subcounty geometry system.
        if deep_level_ids:
            deep_df = _load_subcounty_rows_by_loc_ids(iso3, deep_level_ids)
            if deep_df is not None and len(deep_df) > 0:
                deep_geojson = df_to_geojson(deep_df, polygon_only=True)
                features.extend(deep_geojson.get("features", []))

        # Fetch remaining sub-country levels from the standard country/crosswalk path.
        if regular_sub_level_ids:
            country_df = load_geometry_rows_by_loc_ids(iso3, regular_sub_level_ids)
            if country_df is not None and len(country_df) > 0:
                sub_geojson = df_to_geojson(country_df, polygon_only=True)
                features.extend(sub_geojson.get("features", []))

    logger.debug(f"Loaded {len(features)} geometries for selection from {len(loc_ids)} loc_ids")

    return {"type": "FeatureCollection", "features": features}
