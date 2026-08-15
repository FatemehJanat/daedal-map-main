"""
Shared runtime-owned helper/foundation loaders.

This module centralizes access to small always-available helper assets that should
not be modeled as pack-owned data. Explore is the first lane to formalize onto this
surface, but the intent is that Research and Ops can reuse the same helpers with
their own access patterns later.
"""

from __future__ import annotations

import json
import logging
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from .duckdb_helpers import is_cloud_mode, parquet_columns
from .orchestrator_specs import list_orchestrator_specs
from .paths import COUNTRIES_DIR, DATA_ROOT, GEOMETRY_DIR
from .runtime.explainer_response import build_explainer_response, looks_like_explainer_question
from .runtime.read_posture import prefer_local_geometry_reads
from .runtime.result_cap import (
    apply_runtime_feature_cap_to_payload,
    apply_runtime_result_cap,
    merge_cap_info,
)
from .runtime.published_artifacts import read_artifact_bytes, read_artifact_json

logger = logging.getLogger("mapmover")

REFERENCE_DIR = Path(__file__).parent / "reference"

FOUNDATION_HELPER_REGISTRY = {
    "reference_json": [
        "admin_levels.json",
        "country_aliases.json",
        "disaster_links.json",
        "disasters.json",
        "iso_codes.json",
        "query_synonyms.json",
        "stopwords.json",
        "unit_conversions.json",
        "water_body_codes.json",
        "usa/usa_admin.json",
    ],
    "country_crosswalks": "geometry/countries/{ISO3}/crosswalk.json",
    "country_json_assets": "countries/{ISO3}/{filename}",
    "global_country_geometry": "geometry/global.csv",
    "world_factbook_static": "global/world_factbook_static/all_countries.parquet",
    "orchestrator_specs": "mapmover/orchestrator_specs.py",
    "runtime_result_cap": "mapmover/runtime/result_cap.py",
    "runtime_explainer_response": "mapmover/runtime/explainer_response.py",
    "mode_profiles": {
        "explore": [
            "reference_json",
            "country_crosswalks",
            "global_country_geometry",
            "world_factbook_static",
            "orchestrator_specs",
            "runtime_result_cap",
            "runtime_explainer_response",
        ],
        "research": [
            "country_crosswalks",
            "orchestrator_specs",
            "runtime_result_cap",
            "runtime_explainer_response",
        ],
        "ops": [
            "orchestrator_specs",
            "runtime_result_cap",
            "runtime_explainer_response",
        ],
    },
}

_REFERENCE_JSON_CACHE: dict[str, Any] = {}
_COUNTRY_CROSSWALK_CACHE: dict[tuple[str, str], dict | None] = {}
_COUNTRY_JSON_ASSET_CACHE: dict[tuple[str, str, str], Any] = {}
_GLOBAL_COUNTRIES_CACHE = None
_WORLD_FACTBOOK_STATIC_CACHE = None

def _parquet_accessible(path: Path) -> bool:
    """Returns True if a parquet file exists locally or is accessible via S3/DuckDB."""
    if not is_cloud_mode():
        return path.exists()
    try:
        cols = parquet_columns(path)
        return bool(cols)
    except Exception:
        return False


def load_reference_json(relative_path: str | Path) -> Any:
    """
    Load a JSON helper asset from the shared runtime reference directory.

    `relative_path` may be a simple filename like `iso_codes.json`, a nested path such as
    `usa/usa_admin.json`, or an absolute Path for compatibility with older callers.
    """
    path = relative_path if isinstance(relative_path, Path) else Path(relative_path)
    if not path.is_absolute():
        path = REFERENCE_DIR / path
    cache_key = str(path.resolve()) if path.exists() else str(path)
    if cache_key in _REFERENCE_JSON_CACHE:
        return _REFERENCE_JSON_CACHE[cache_key]
    if not path.exists():
        _REFERENCE_JSON_CACHE[cache_key] = None
        return None
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        _REFERENCE_JSON_CACHE[cache_key] = data
        return data
    except Exception as e:
        logger.warning(f"Failed to load reference helper {path}: {e}")
        _REFERENCE_JSON_CACHE[cache_key] = None
        return None


def load_reference_dict(relative_path: str | Path) -> dict | None:
    """Load a reference helper asset and return it only when it is a dict."""
    data = load_reference_json(relative_path)
    return data if isinstance(data, dict) else None


def get_foundation_helper_registry() -> dict[str, Any]:
    """Return the declared runtime-owned helper assets."""
    return FOUNDATION_HELPER_REGISTRY


def load_orchestrator_specs() -> dict[str, Any]:
    """Return the shared orchestrator spec registry."""
    return list_orchestrator_specs()


def load_runtime_result_cap_helpers() -> dict[str, Any]:
    """Return the shared runtime cap helpers."""
    return {
        "apply_runtime_result_cap": apply_runtime_result_cap,
        "apply_runtime_feature_cap_to_payload": apply_runtime_feature_cap_to_payload,
        "merge_cap_info": merge_cap_info,
    }


def load_runtime_explainer_helpers() -> dict[str, Any]:
    """Return the shared explainer helpers."""
    return {
        "looks_like_explainer_question": looks_like_explainer_question,
        "build_explainer_response": build_explainer_response,
    }


def _reference_country_codes() -> set[str]:
    data = load_reference_dict("iso_codes.json") or {}
    codes: set[str] = set()
    for section in ("common_countries", "commonly_missing"):
        values = (data.get(section) or {}).get("codes") or []
        codes.update(str(value).strip().upper() for value in values if str(value).strip())
    return codes


def _load_supplemental_admin0_frame(existing_columns: list[str], existing_loc_ids: set[str]) -> pd.DataFrame:
    """Load approved supplemental Admin0 candidates for point containment.

    A supplemental territory may intentionally share a loc_id with the shallow
    global bank when its reviewed polygon corrects a coastal coverage gap. Keep
    both candidates; the point matcher selects the smallest covering polygon.
    """
    path = GEOMETRY_DIR / "supplemental" / "admin0_territories.parquet"
    index_path = GEOMETRY_DIR / "supplemental" / "admin0_territories_index.json"
    if not is_cloud_mode() and (not path.exists() or not index_path.exists()):
        return pd.DataFrame(columns=existing_columns)

    try:
        index = (
            read_artifact_json("geometry/supplemental/admin0_territories_index.json", lane="published")
            if is_cloud_mode()
            else json.loads(index_path.read_text(encoding="utf-8"))
        )
    except Exception as e:
        logger.warning("Failed to load supplemental Admin0 index: %s", e)
        return pd.DataFrame(columns=existing_columns)

    if str(index.get("license_review_status") or "").strip().lower() != "approved" or not index.get("usable_for_derivation"):
        return pd.DataFrame(columns=existing_columns)

    reference_codes = _reference_country_codes()
    try:
        supplemental = (
            pd.read_parquet(BytesIO(read_artifact_bytes("geometry/supplemental/admin0_territories.parquet", lane="published")))
            if is_cloud_mode()
            else pd.read_parquet(path)
        )
    except Exception as e:
        logger.warning("Failed to load supplemental Admin0 geometry: %s", e)
        return pd.DataFrame(columns=existing_columns)

    if supplemental.empty or "loc_id" not in supplemental.columns:
        return pd.DataFrame(columns=existing_columns)

    supplemental = supplemental.copy()
    supplemental["loc_id"] = supplemental["loc_id"].astype(str).str.strip().str.upper()
    overlap_overrides = {
        str(value).strip().upper()
        for value in index.get("overlap_override_loc_ids") or []
        if str(value).strip()
    }
    supplemental = supplemental[
        supplemental["loc_id"].isin(reference_codes)
        & (
            ~supplemental["loc_id"].isin(existing_loc_ids)
            | supplemental["loc_id"].isin(overlap_overrides)
        )
    ]
    if supplemental.empty:
        return pd.DataFrame(columns=existing_columns)

    rows: list[dict[str, Any]] = []
    for record in supplemental.to_dict(orient="records"):
        loc_id = str(record.get("loc_id") or "").strip().upper()
        geometry = record.get("geometry")
        row = {
            "loc_id": loc_id,
            "parent_id": "WORLD",
            "admin_level": 0,
            "type": "admin",
            "name": record.get("name") or loc_id,
            "name_local": "",
            "code": loc_id,
            "iso_3166_2": "",
            "centroid_lon": None,
            "centroid_lat": None,
            "has_polygon": True,
            "geometry": geometry,
            "timezone": "",
            "iso_a3": loc_id,
            "land_area": None,
            "water_area": None,
            "bbox_min_lon": None,
            "bbox_min_lat": None,
            "bbox_max_lon": None,
            "bbox_max_lat": None,
            "children_count": 0,
            "children_by_level": "{}",
            "descendants_count": 0,
            "descendants_by_level": "{}",
            "source_system": record.get("source_system") or "supplemental_admin0",
            "source_shape_id": "",
            "source_shape_type": "SUPPLEMENTAL_ADM0",
            "direct_children_count": 0,
            "direct_children_by_level": "{}",
        }
        try:
            from shapely.geometry import shape

            geom_data = json.loads(geometry) if isinstance(geometry, str) else geometry
            geom = shape(geom_data)
            centroid = geom.centroid
            row.update({
                "centroid_lon": centroid.x,
                "centroid_lat": centroid.y,
                "bbox_min_lon": geom.bounds[0],
                "bbox_min_lat": geom.bounds[1],
                "bbox_max_lon": geom.bounds[2],
                "bbox_max_lat": geom.bounds[3],
            })
        except Exception:
            pass
        rows.append(row)

    frame = pd.DataFrame(rows)
    for column in existing_columns:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame[existing_columns]


def load_country_crosswalk(iso3: str) -> dict | None:
    """Load a country crosswalk from the shared runtime helper layer."""
    iso3 = (iso3 or "").upper()
    if not iso3:
        return None
    read_mode = "local" if prefer_local_geometry_reads() else "runtime"
    cache_key = (iso3, read_mode)
    if cache_key in _COUNTRY_CROSSWALK_CACHE:
        return _COUNTRY_CROSSWALK_CACHE[cache_key]

    crosswalk_path = GEOMETRY_DIR / "geometry" / "countries" / iso3 / "crosswalk.json"
    if crosswalk_path.exists():
        try:
            with open(crosswalk_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            _COUNTRY_CROSSWALK_CACHE[cache_key] = data
            return data
        except Exception as e:
            logger.warning(f"Failed to load crosswalk for {iso3}: {e}")
            _COUNTRY_CROSSWALK_CACHE[cache_key] = None
            return None

    if prefer_local_geometry_reads():
        _COUNTRY_CROSSWALK_CACHE[cache_key] = None
        return None

    if not crosswalk_path.exists():
        if is_cloud_mode():
            try:
                data = read_artifact_json(f"geometry/countries/{iso3}/crosswalk.json", lane="published")
                _COUNTRY_CROSSWALK_CACHE[cache_key] = data
                return data
            except Exception as e:
                logger.warning(f"Failed to load crosswalk for {iso3} from cloud storage: {e}")
        _COUNTRY_CROSSWALK_CACHE[cache_key] = None
        return None
    _COUNTRY_CROSSWALK_CACHE[cache_key] = None
    return None


def load_country_json_asset(iso3: str, filename: str) -> Any:
    """Load a country-owned JSON asset from `countries/{ISO3}/`."""
    iso3 = (iso3 or "").upper()
    filename = str(filename or "").strip()
    if not iso3 or not filename:
        return None

    read_mode = "local" if prefer_local_geometry_reads() else "runtime"
    cache_key = (iso3, filename, read_mode)
    if cache_key in _COUNTRY_JSON_ASSET_CACHE:
        return _COUNTRY_JSON_ASSET_CACHE[cache_key]

    asset_path = COUNTRIES_DIR / iso3 / filename
    if asset_path.exists():
        try:
            with open(asset_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            _COUNTRY_JSON_ASSET_CACHE[cache_key] = data
            return data
        except Exception as e:
            logger.warning("Failed to load country asset %s/%s: %s", iso3, filename, e)
            _COUNTRY_JSON_ASSET_CACHE[cache_key] = None
            return None

    if prefer_local_geometry_reads():
        _COUNTRY_JSON_ASSET_CACHE[cache_key] = None
        return None

    if not asset_path.exists():
        if is_cloud_mode():
            try:
                data = read_artifact_json(f"countries/{iso3}/{filename}", lane="published")
                _COUNTRY_JSON_ASSET_CACHE[cache_key] = data
                return data
            except Exception as e:
                logger.warning("Failed to load country asset %s/%s from cloud storage: %s", iso3, filename, e)
        _COUNTRY_JSON_ASSET_CACHE[cache_key] = None
        return None
    _COUNTRY_JSON_ASSET_CACHE[cache_key] = None
    return None


def load_global_countries_frame():
    """Load the shared global country geometry helper file."""
    global _GLOBAL_COUNTRIES_CACHE
    if _GLOBAL_COUNTRIES_CACHE is not None:
        return _GLOBAL_COUNTRIES_CACHE

    global_file = GEOMETRY_DIR / "global.csv"
    if global_file.exists():
        try:
            base = pd.read_csv(global_file)
            existing_loc_ids = set(base["loc_id"].dropna().astype(str).str.strip().str.upper()) if "loc_id" in base.columns else set()
            supplemental = _load_supplemental_admin0_frame(list(base.columns), existing_loc_ids)
            _GLOBAL_COUNTRIES_CACHE = pd.concat([base, supplemental], ignore_index=True) if not supplemental.empty else base
            logger.info(
                "Loaded %d countries from global.csv plus %d supplemental Admin0 rows",
                len(_GLOBAL_COUNTRIES_CACHE),
                len(supplemental),
            )
            return _GLOBAL_COUNTRIES_CACHE
        except Exception as e:
            logger.error(f"Error loading global.csv: {e}")
            return None

    if is_cloud_mode():
        try:
            raw = read_artifact_bytes("geometry/global.csv", lane="published").decode("utf-8-sig")
            base = pd.read_csv(StringIO(raw))
            existing_loc_ids = set(base["loc_id"].dropna().astype(str).str.strip().str.upper()) if "loc_id" in base.columns else set()
            supplemental = _load_supplemental_admin0_frame(list(base.columns), existing_loc_ids)
            _GLOBAL_COUNTRIES_CACHE = pd.concat([base, supplemental], ignore_index=True) if not supplemental.empty else base
            logger.info(
                "Loaded %d countries from published geometry/global.csv plus %d supplemental Admin0 rows",
                len(_GLOBAL_COUNTRIES_CACHE),
                len(supplemental),
            )
            return _GLOBAL_COUNTRIES_CACHE
        except Exception as e:
            logger.warning("Failed to load global.csv from object storage: %s", e)

    logger.warning(f"global.csv not found at {global_file}")
    return None


def load_world_factbook_static_frame():
    """Load the shared static country-context helper parquet."""
    global _WORLD_FACTBOOK_STATIC_CACHE
    if _WORLD_FACTBOOK_STATIC_CACHE is not None:
        return _WORLD_FACTBOOK_STATIC_CACHE

    factbook_file = DATA_ROOT / "global" / "world_factbook_static" / "all_countries.parquet"
    if not _parquet_accessible(factbook_file):
        logger.warning("world_factbook_static parquet not accessible at %s", factbook_file)
        return None

    try:
        _WORLD_FACTBOOK_STATIC_CACHE = pd.read_parquet(factbook_file)
        logger.info("Loaded %d rows from world_factbook_static", len(_WORLD_FACTBOOK_STATIC_CACHE))
        return _WORLD_FACTBOOK_STATIC_CACHE
    except Exception as e:
        logger.warning("Error loading world_factbook_static parquet: %s", e)
        return None


def bridge_loc_id_family(loc_id: str, target_family: str = "geometry") -> str:
    """
    Translate between a local/canonical loc_id family and the geometry/global family.

    `target_family="geometry"` maps local ids toward geometry/global ids.
    `target_family="local"` maps geometry/global ids back toward preferred local ids.
    """
    canonical = str(loc_id or "").strip()
    if "-" not in canonical:
        return canonical

    iso3 = canonical.split("-", 1)[0].upper()
    crosswalk = load_country_crosswalk(iso3) or {}
    local_to_geo: dict[str, str] = {}
    geo_to_local: dict[str, str] = {}

    for source_map in (crosswalk.get("mappings") or {}, crosswalk.get("admin_2_fips") or {}):
        for local_loc_id, geo_loc_id in source_map.items():
            local_norm = str(local_loc_id or "").strip()
            geo_norm = str(geo_loc_id or "").strip()
            if not local_norm or not geo_norm:
                continue
            local_to_geo[local_norm] = geo_norm
            geo_to_local.setdefault(geo_norm, local_norm)

    if target_family == "local":
        return geo_to_local.get(canonical, canonical)
    return local_to_geo.get(canonical, canonical)
