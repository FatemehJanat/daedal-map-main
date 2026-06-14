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
import os
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from .duckdb_helpers import is_cloud_mode, parquet_columns
from .orchestrator_specs import list_orchestrator_specs
from .paths import COUNTRIES_DIR, DATA_ROOT, GEOMETRY_DIR
from .runtime.explainer_response import build_explainer_response, looks_like_explainer_question
from .runtime.result_cap import (
    apply_runtime_feature_cap_to_payload,
    apply_runtime_result_cap,
    merge_cap_info,
)

logger = logging.getLogger("mapmover")

REFERENCE_DIR = Path(__file__).parent / "reference"

FOUNDATION_HELPER_REGISTRY = {
    "reference_json": [
        "admin_levels.json",
        "country_aliases.json",
        "disasters.json",
        "iso_codes.json",
        "query_synonyms.json",
        "stopwords.json",
        "unit_conversions.json",
        "water_body_codes.json",
        "usa/usa_admin.json",
    ],
    "country_crosswalks": "countries/{ISO3}/crosswalk.json",
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
_COUNTRY_CROSSWALK_CACHE: dict[str, dict | None] = {}
_COUNTRY_JSON_ASSET_CACHE: dict[tuple[str, str], Any] = {}
_GLOBAL_COUNTRIES_CACHE = None
_WORLD_FACTBOOK_STATIC_CACHE = None

try:
    import boto3
except ImportError:
    boto3 = None


def _parquet_accessible(path: Path) -> bool:
    """Returns True if a parquet file exists locally or is accessible via S3/DuckDB."""
    if not is_cloud_mode():
        return path.exists()
    try:
        cols = parquet_columns(path)
        return bool(cols)
    except Exception:
        return False


def _object_store_client():
    if boto3 is None:
        return None
    endpoint_url = os.environ.get("S3_ENDPOINT_URL", "").strip() or None
    region = (
        os.environ.get("AWS_DEFAULT_REGION", "").strip()
        or os.environ.get("AWS_REGION", "").strip()
        or "auto"
    )
    return boto3.client("s3", endpoint_url=endpoint_url, region_name=region)


def _object_store_bucket_and_key(relative_path: str) -> tuple[str, str] | None:
    cloud_cfg = {}
    try:
        from .runtime_config import get_runtime_config
        cloud_cfg = get_runtime_config().get("cloud", {}) or {}
    except Exception:
        cloud_cfg = {}
    bucket = os.environ.get("S3_BUCKET", "").strip() or str(cloud_cfg.get("bucket", "")).strip()
    if not bucket:
        return None
    prefix = (
        os.environ.get("S3_PUBLISHED_PREFIX", "").strip()
        or os.environ.get("S3_PREFIX", "").strip()
        or str(cloud_cfg.get("prefix", "")).strip()
        or "published"
    ).strip("/")
    key = f"{prefix}/{relative_path}".strip("/")
    return bucket, key


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


def load_country_crosswalk(iso3: str) -> dict | None:
    """Load a country crosswalk from the shared runtime helper layer."""
    iso3 = (iso3 or "").upper()
    if not iso3:
        return None
    if iso3 in _COUNTRY_CROSSWALK_CACHE:
        return _COUNTRY_CROSSWALK_CACHE[iso3]

    crosswalk_path = COUNTRIES_DIR / iso3 / "crosswalk.json"
    if not crosswalk_path.exists():
        if is_cloud_mode():
            try:
                from .data_loading import _fetch_json_from_s3

                data = _fetch_json_from_s3(f"countries/{iso3}/crosswalk.json")
                _COUNTRY_CROSSWALK_CACHE[iso3] = data
                return data
            except Exception as e:
                logger.warning(f"Failed to load crosswalk for {iso3} from cloud storage: {e}")
        _COUNTRY_CROSSWALK_CACHE[iso3] = None
        return None

    try:
        with open(crosswalk_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        _COUNTRY_CROSSWALK_CACHE[iso3] = data
        return data
    except Exception as e:
        logger.warning(f"Failed to load crosswalk for {iso3}: {e}")
        _COUNTRY_CROSSWALK_CACHE[iso3] = None
        return None


def load_country_json_asset(iso3: str, filename: str) -> Any:
    """Load a country-owned JSON asset from `countries/{ISO3}/`."""
    iso3 = (iso3 or "").upper()
    filename = str(filename or "").strip()
    if not iso3 or not filename:
        return None

    cache_key = (iso3, filename)
    if cache_key in _COUNTRY_JSON_ASSET_CACHE:
        return _COUNTRY_JSON_ASSET_CACHE[cache_key]

    asset_path = COUNTRIES_DIR / iso3 / filename
    if not asset_path.exists():
        if is_cloud_mode():
            try:
                from .data_loading import _fetch_json_from_s3

                data = _fetch_json_from_s3(f"countries/{iso3}/{filename}")
                _COUNTRY_JSON_ASSET_CACHE[cache_key] = data
                return data
            except Exception as e:
                logger.warning("Failed to load country asset %s/%s from cloud storage: %s", iso3, filename, e)
        _COUNTRY_JSON_ASSET_CACHE[cache_key] = None
        return None

    try:
        with open(asset_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        _COUNTRY_JSON_ASSET_CACHE[cache_key] = data
        return data
    except Exception as e:
        logger.warning("Failed to load country asset %s/%s: %s", iso3, filename, e)
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
            _GLOBAL_COUNTRIES_CACHE = pd.read_csv(global_file)
            logger.info(f"Loaded {len(_GLOBAL_COUNTRIES_CACHE)} countries from global.csv")
            return _GLOBAL_COUNTRIES_CACHE
        except Exception as e:
            logger.error(f"Error loading global.csv: {e}")
            return None

    if is_cloud_mode():
        bucket_key = _object_store_bucket_and_key("geometry/global.csv")
        client = _object_store_client()
        if bucket_key and client is not None:
            bucket, key = bucket_key
            try:
                response = client.get_object(Bucket=bucket, Key=key)
                raw = response["Body"].read().decode("utf-8-sig")
                _GLOBAL_COUNTRIES_CACHE = pd.read_csv(StringIO(raw))
                logger.info(
                    "Loaded %d countries from s3://%s/%s",
                    len(_GLOBAL_COUNTRIES_CACHE),
                    bucket,
                    key,
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
