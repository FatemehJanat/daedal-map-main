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
import os
import time
from pathlib import Path
from copy import deepcopy

from .catalog_surface import get_catalog_surface_override
from .foundation_helpers import load_country_crosswalk
from .pack_state import build_active_catalog
from .paths import CATALOG_PATH, COUNTRIES_DIR, DATA_ROOT, GEOMETRY_DIR, WIP_CATALOG_PATH
from .duckdb_helpers import select_rows
from .request_risk_gate import block_gate, safe_gate
from .runtime_config import get_runtime_config

logger = logging.getLogger("mapmover")

# Global data catalog
data_catalog = {}

# Cache for source metadata
_metadata_cache = {}

# Cache for catalog.json with TTL so R2 updates are picked up without a restart.
# After the TTL expires the next request re-reads catalog.json from disk.
_catalog_cache = None
_catalog_cache_time = 0.0
_CATALOG_TTL_SECONDS = 300  # 5 minutes
_catalog_missing_time = 0.0
_CATALOG_MISS_TTL_SECONDS = 15
_full_catalog_cache = None
_full_catalog_cache_time = 0.0
_full_catalog_missing_time = 0.0

_api_catalog_cache = None
_api_catalog_cache_time = 0.0
_api_catalog_missing_time = 0.0
_api_guide_cache = None
_api_guide_cache_time = 0.0
_api_guide_missing_time = 0.0
_api_pack_cache: dict[str, dict] = {}
_api_pack_cache_time: dict[str, float] = {}
_api_pack_missing_time: dict[str, float] = {}
# Agent/API catalog changes only on deliberate publish, not on every live-source
# tick. Use a longer TTL than the human catalog to avoid cold R2 round trips on
# frequent external probes (e.g. 402 Index health checks). clear_api_discovery_cache()
# forces an immediate refresh when a new pack is published.
_API_CATALOG_TTL_SECONDS = 3600  # 1 hour

PACK_LOAD_MAX_SOURCES = 8
PACK_LOAD_MAX_FILE_SIZE_MB = 200.0
PACK_LOAD_MAX_ROW_COUNT = 2_000_000
RETIRED_PACK_SOURCE_IDS = {
    "world_factbook_overlap",
}
PACK_MCP_ROUTING_HINTS: dict[str, dict[str, str]] = {
    "currency": {
        "preferred_tool": "get_fx_rates",
    },
    "earthquakes": {
        "preferred_tool": "get_earthquake_events",
        "live_fallback_tool": "get_live_earthquake_events",
        "live_fallback_when": "Only when the caller explicitly asks for live/preliminary upstream data or needs time beyond canonical_available_through.",
    },
    "tsunamis": {
        "preferred_tool": "get_tsunami_events",
    },
    "volcanoes": {
        "preferred_tool": "get_volcanic_activity",
        "live_fallback_tool": "get_live_volcano_events",
        "live_fallback_when": "Only when the caller explicitly asks for live/preliminary upstream data or needs time beyond canonical_available_through.",
    },
    "hurricanes": {
        "preferred_tool": "query_dataset",
    },
    "un_sdg": {
        "preferred_tool": "query_dataset",
    },
    "world_factbook": {
        "preferred_tool": "query_dataset",
    },
    "worldpop": {
        "preferred_tool": "query_dataset",
    },
}


def get_data_folder():
    """Get the data folder path (resolved via paths.py)."""
    return DATA_ROOT


def get_catalog_path():
    """Get the catalog.json path (resolved via paths.py)."""
    return CATALOG_PATH


def get_wip_catalog_path():
    """Get the wip_catalog.json path (resolved via paths.py)."""
    return WIP_CATALOG_PATH


def _use_wip_catalog_for_local_runtime() -> bool:
    raw = str(os.environ.get("USE_WIP_CATALOG", "")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _requested_catalog_surface() -> str:
    override = get_catalog_surface_override()
    if override in {"published", "wip"}:
        return override
    return "wip" if _use_wip_catalog_for_local_runtime() else "published"


def _fetch_json_from_s3(relative_path: str) -> dict:
    """Fetch a JSON file directly from S3 into memory. Cloud mode only."""
    import boto3 as _boto3
    cloud_cfg = get_runtime_config().get("cloud", {})
    bucket = os.environ.get("S3_BUCKET", "").strip() or str(cloud_cfg.get("bucket", "")).strip()
    prefix = (os.environ.get("S3_PREFIX", "") or str(cloud_cfg.get("prefix", ""))).strip().strip("/")
    key = f"{prefix}/{relative_path}" if prefix else relative_path
    endpoint_url = os.environ.get("S3_ENDPOINT_URL") or cloud_cfg.get("endpoint_url")
    region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "auto"
    client = _boto3.client("s3", endpoint_url=endpoint_url, region_name=region)
    obj = client.get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read())


def _api_catalog_output_root() -> Path:
    return Path(__file__).resolve().parents[2] / "county-map-private" / "build" / "api_catalog" / "output"


def _load_json_from_runtime_or_s3(relative_path: str, *, use_api_prefix: bool = False) -> dict | None:
    runtime_mode = str(get_runtime_config().get("runtime_mode", "local")).strip().lower()
    if runtime_mode == "cloud":
        s3_path = f"api_catalog/{relative_path}" if use_api_prefix else relative_path
        try:
            data = _fetch_json_from_s3(s3_path)
            return data if isinstance(data, dict) else None
        except Exception as e:
            logger.warning(f"Failed to load {s3_path} from S3: {e}")
            return None

    local_path = _api_catalog_output_root() / relative_path
    try:
        if local_path.exists():
            return json.loads(local_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Failed to load local API discovery artifact {local_path}: {e}")
    return None


def load_catalog():
    """
    Load the unified catalog.json file.
    Cached with a 5-minute TTL. In cloud mode, fetches directly from S3 into memory
    on each TTL expiry so catalog updates go live without a restart.

    Returns:
        dict: Catalog with sources, or empty dict if not found
    """
    global _catalog_cache, _catalog_cache_time, _catalog_missing_time

    if _requested_catalog_surface() == "wip":
        return load_full_catalog()

    now = time.time()
    if _catalog_cache is not None and (now - _catalog_cache_time) < _CATALOG_TTL_SECONDS:
        return _catalog_cache

    runtime_mode = str(get_runtime_config().get("runtime_mode", "local")).strip().lower()

    if runtime_mode == "cloud":
        if (now - _catalog_missing_time) < _CATALOG_MISS_TTL_SECONDS and _catalog_cache is None:
            return {"sources": [], "total_sources": 0}
        try:
            raw_catalog = _fetch_json_from_s3("catalog.json")
            _catalog_cache = raw_catalog
            _catalog_cache_time = now
            active_catalog = build_active_catalog(raw_catalog)
            logger.debug(f"Loaded catalog.json from S3 with {len(raw_catalog.get('sources', []))} sources")
            return active_catalog
        except Exception as e:
            _catalog_missing_time = now
            logger.warning(f"catalog.json S3 fetch failed: {e}")
            return {"sources": [], "total_sources": 0}

    # Local mode: read from disk
    use_wip_catalog = _use_wip_catalog_for_local_runtime()
    catalog_path = get_wip_catalog_path() if use_wip_catalog else get_catalog_path()
    if not catalog_path or not catalog_path.exists():
        _catalog_missing_time = now
        logger.warning(f"Catalog not found at {catalog_path}")
        return {"sources": [], "total_sources": 0}

    try:
        with open(catalog_path, 'r', encoding='utf-8-sig') as f:
            raw_catalog = json.load(f)
            _catalog_cache = raw_catalog
            _catalog_cache_time = now
            active_catalog = raw_catalog if use_wip_catalog else build_active_catalog(raw_catalog)
            catalog_label = "wip_catalog.json" if use_wip_catalog else "catalog.json"
            logger.debug(f"Loaded {catalog_label} with {len(raw_catalog.get('sources', []))} sources")
            return active_catalog
    except Exception as e:
        logger.error(f"Error loading {'wip_catalog.json' if use_wip_catalog else 'catalog.json'}: {e}")
        return {"sources": [], "total_sources": 0}


def load_api_catalog() -> dict:
    global _api_catalog_cache, _api_catalog_cache_time, _api_catalog_missing_time

    now = time.time()
    if _api_catalog_cache is not None and (now - _api_catalog_cache_time) < _API_CATALOG_TTL_SECONDS:
        return _api_catalog_cache
    if _api_catalog_cache is None and (now - _api_catalog_missing_time) < _CATALOG_MISS_TTL_SECONDS:
        return {"catalog_version": "1.0", "generated_at": None, "source_mode": "api_catalog", "pack_count": 0, "packs": []}

    payload = _load_json_from_runtime_or_s3("api_catalog.json", use_api_prefix=True)
    if payload is None:
        _api_catalog_missing_time = now
        return {"catalog_version": "1.0", "generated_at": None, "source_mode": "api_catalog", "pack_count": 0, "packs": []}

    _api_catalog_cache = payload
    _api_catalog_cache_time = now
    return payload


def load_api_guide() -> dict:
    global _api_guide_cache, _api_guide_cache_time, _api_guide_missing_time

    now = time.time()
    if _api_guide_cache is not None and (now - _api_guide_cache_time) < _API_CATALOG_TTL_SECONDS:
        return _api_guide_cache
    if _api_guide_cache is None and (now - _api_guide_missing_time) < _CATALOG_MISS_TTL_SECONDS:
        return {}

    payload = _load_json_from_runtime_or_s3("guide.json", use_api_prefix=True)
    if payload is None:
        _api_guide_missing_time = now
        return {}

    _api_guide_cache = payload
    _api_guide_cache_time = now
    return payload


def load_api_pack_detail(pack_id: str) -> dict | None:
    global _api_pack_cache, _api_pack_cache_time, _api_pack_missing_time

    pack_id = str(pack_id or "").strip()
    if not pack_id:
        return None

    now = time.time()
    cached = _api_pack_cache.get(pack_id)
    cached_time = _api_pack_cache_time.get(pack_id, 0.0)
    if cached is not None and (now - cached_time) < _API_CATALOG_TTL_SECONDS:
        return cached
    if cached is None and (now - _api_pack_missing_time.get(pack_id, 0.0)) < _CATALOG_MISS_TTL_SECONDS:
        return None

    payload = _load_json_from_runtime_or_s3(f"packs/{pack_id}.json", use_api_prefix=True)
    if payload is None:
        _api_pack_missing_time[pack_id] = now
        return None

    payload = _hydrate_api_pack_detail_from_source_metadata(payload)

    _api_pack_cache[pack_id] = payload
    _api_pack_cache_time[pack_id] = now
    return payload


def _hydrate_api_pack_detail_from_source_metadata(payload: dict | None) -> dict | None:
    """
    Refresh pack-detail freshness fields from source metadata.

    The generated pack JSON is useful for broad descriptive metadata, but the
    source metadata is the sharper source of truth for live/canonical freshness.
    By overlaying source metadata here, pack detail stays current as long as the
    live pipeline updates metadata.json correctly.
    """
    if not isinstance(payload, dict):
        return payload

    hydrated = deepcopy(payload)
    source_rows = hydrated.get("sources")
    if not isinstance(source_rows, list) or not source_rows:
        return hydrated

    refreshed_sources: list[dict] = []
    pack_start = None
    pack_end = None
    pack_live_watermark = None
    pack_live_updates_enabled = False
    pack_last_updated = None
    pack_processing_states: list[str] = []

    for source in source_rows:
        if not isinstance(source, dict):
            refreshed_sources.append(source)
            continue

        refreshed = deepcopy(source)
        source_id = str(refreshed.get("source_id") or "").strip()
        metadata = load_source_metadata(source_id) if source_id else None
        if isinstance(metadata, dict) and metadata:
            source_temporal = metadata.get("temporal_coverage")
            if isinstance(source_temporal, dict) and source_temporal:
                refreshed["temporal_coverage"] = deepcopy(source_temporal)
                start_value = source_temporal.get("start")
                end_value = source_temporal.get("end")
                if start_value is not None:
                    start_text = str(start_value)
                    if pack_start is None or start_text < pack_start:
                        pack_start = start_text
                if end_value is not None:
                    end_text = str(end_value)
                    if pack_end is None or end_text > pack_end:
                        pack_end = end_text
                    refreshed.setdefault("canonical_available_through", end_text)

            time_field = metadata.get("time_field")
            if time_field:
                refreshed["time_field"] = time_field

            location_field = metadata.get("location_field")
            if location_field:
                refreshed["location_field"] = location_field

            default_limit = metadata.get("default_limit")
            if default_limit is not None:
                refreshed["default_limit"] = default_limit

            browser_artifact = metadata.get("browser_artifact")
            if isinstance(browser_artifact, dict) and browser_artifact:
                refreshed["browser_artifact"] = deepcopy(browser_artifact)

            live_watermark = metadata.get("live_watermark_utc")
            if live_watermark:
                refreshed["live_watermark_utc"] = live_watermark
                refreshed["canonical_available_through"] = str(live_watermark)
                live_text = str(live_watermark)
                if pack_live_watermark is None or live_text > pack_live_watermark:
                    pack_live_watermark = live_text

            live_updates_enabled = bool(metadata.get("live_updates_enabled"))
            if live_updates_enabled:
                refreshed["live_updates_enabled"] = True
                pack_live_updates_enabled = True

            processing_state = metadata.get("processing_state")
            if processing_state:
                refreshed["processing_state"] = processing_state
                pack_processing_states.append(str(processing_state))

            last_updated = metadata.get("last_updated")
            if last_updated:
                refreshed["last_updated"] = last_updated
                last_updated_text = str(last_updated)
                if pack_last_updated is None or last_updated_text > pack_last_updated:
                    pack_last_updated = last_updated_text

        refreshed_sources.append(refreshed)

    hydrated["sources"] = refreshed_sources

    temporal = hydrated.get("temporal_coverage")
    if not isinstance(temporal, dict):
        temporal = {}
    if pack_start is not None:
        temporal["start"] = pack_start
    if pack_end is not None:
        temporal["end"] = pack_end
    if temporal:
        hydrated["temporal_coverage"] = temporal

    if pack_live_watermark is not None:
        hydrated["live_watermark_utc"] = pack_live_watermark
        hydrated["canonical_available_through"] = pack_live_watermark
    elif pack_end is not None:
        hydrated["canonical_available_through"] = pack_end
    if pack_last_updated is not None:
        hydrated["last_updated"] = pack_last_updated
    if pack_live_updates_enabled:
        hydrated["live_updates_enabled"] = True
    if pack_processing_states:
        state_rank = {
            "raw_collected": 1,
            "canonical_ready": 2,
            "event_area_ready": 3,
            "link_ready": 4,
            "aggregate_ready": 5,
        }
        hydrated["processing_state"] = max(
            pack_processing_states,
            key=lambda value: state_rank.get(str(value), 0),
        )

    pack_id = str(hydrated.get("pack_id") or "").strip().lower()
    routing_hints = PACK_MCP_ROUTING_HINTS.get(pack_id) or {}
    for key, value in routing_hints.items():
        hydrated.setdefault(key, value)

    return hydrated


def load_full_catalog():
    """Load the WIP/full catalog without active-pack filtering."""
    global _full_catalog_cache, _full_catalog_cache_time, _full_catalog_missing_time

    now = time.time()
    if _full_catalog_cache is not None and (now - _full_catalog_cache_time) < _CATALOG_TTL_SECONDS:
        return _full_catalog_cache

    runtime_mode = str(get_runtime_config().get("runtime_mode", "local")).strip().lower()

    if runtime_mode == "cloud":
        if (now - _full_catalog_missing_time) < _CATALOG_MISS_TTL_SECONDS and _full_catalog_cache is None:
            fallback = load_catalog()
            return fallback or {"sources": [], "total_sources": 0}
        try:
            raw_catalog = _fetch_json_from_s3("wip_catalog.json")
            _full_catalog_cache = raw_catalog
            _full_catalog_cache_time = now
            logger.debug(f"Loaded wip_catalog.json from S3 with {len(raw_catalog.get('sources', []))} sources")
            return raw_catalog
        except Exception as e:
            _full_catalog_missing_time = now
            logger.warning(f"wip_catalog.json S3 fetch failed, falling back to catalog.json: {e}")
            override = get_catalog_surface_override()
            if override == "wip":
                token = None
                try:
                    from .catalog_surface import _catalog_surface_override
                    token = _catalog_surface_override.set("published")
                    fallback = load_catalog()
                finally:
                    if token is not None:
                        _catalog_surface_override.reset(token)
            else:
                fallback = load_catalog()
            return fallback or {"sources": [], "total_sources": 0}

    catalog_path = get_wip_catalog_path()
    if catalog_path and catalog_path.exists():
        try:
            with open(catalog_path, "r", encoding="utf-8-sig") as f:
                raw_catalog = json.load(f)
            _full_catalog_cache = raw_catalog
            _full_catalog_cache_time = now
            logger.debug(f"Loaded wip_catalog.json with {len(raw_catalog.get('sources', []))} sources")
            return raw_catalog
        except Exception as e:
            logger.error(f"Error loading wip_catalog.json: {e}")

    _full_catalog_missing_time = now
    override = get_catalog_surface_override()
    if override == "wip":
        token = None
        try:
            from .catalog_surface import _catalog_surface_override
            token = _catalog_surface_override.set("published")
            fallback = load_catalog()
        finally:
            if token is not None:
                _catalog_surface_override.reset(token)
    else:
        fallback = load_catalog()
    return fallback or {"sources": [], "total_sources": 0}


def _coerce_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coerce_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _describe_pack_size(source_count: int, file_size_mb_total: float, row_count_total: int) -> str:
    if (
        source_count <= 3
        and file_size_mb_total <= 50
        and row_count_total <= 250_000
    ):
        return "small"
    if (
        source_count <= PACK_LOAD_MAX_SOURCES
        and file_size_mb_total <= PACK_LOAD_MAX_FILE_SIZE_MB
        and row_count_total <= PACK_LOAD_MAX_ROW_COUNT
    ):
        return "medium"
    return "large"


def _humanize_pack_id(pack_id: str) -> str:
    acronyms = {"sdg", "un", "fx", "usa", "can", "cia"}
    parts = [part for part in str(pack_id or "").split("_") if part]
    words = [part.upper() if part.lower() in acronyms else part.title() for part in parts]
    return " ".join(words) or str(pack_id or "")


def _build_pack_load_policy(source_count: int, file_size_mb_total: float, row_count_total: int) -> dict:
    reasons = []
    if source_count > PACK_LOAD_MAX_SOURCES:
        reasons.append(f"{source_count} sources exceeds the {PACK_LOAD_MAX_SOURCES}-source load limit")
    if file_size_mb_total > PACK_LOAD_MAX_FILE_SIZE_MB:
        reasons.append(
            f"{file_size_mb_total:.1f} MB exceeds the {PACK_LOAD_MAX_FILE_SIZE_MB:.0f} MB safety limit"
        )
    if row_count_total > PACK_LOAD_MAX_ROW_COUNT:
        reasons.append(
            f"{row_count_total:,} rows exceeds the {PACK_LOAD_MAX_ROW_COUNT:,}-row safety limit"
        )

    allowed = not reasons
    gate = (
        safe_gate(
            lane="human_web_pack_load",
            reason="Safe to load the full pack at once.",
            soft_cap=PACK_LOAD_MAX_ROW_COUNT,
            hard_cap=PACK_LOAD_MAX_ROW_COUNT,
            estimated_count=row_count_total,
            estimated_size_mb=file_size_mb_total,
            measure="pack_load",
            fallback_strategy="load",
            details={"source_count": source_count, "max_sources": PACK_LOAD_MAX_SOURCES},
        )
        if allowed
        else block_gate(
            lane="human_web_pack_load",
            reason="; ".join(reasons),
            soft_cap=PACK_LOAD_MAX_ROW_COUNT,
            hard_cap=PACK_LOAD_MAX_ROW_COUNT,
            estimated_count=row_count_total,
            estimated_size_mb=file_size_mb_total,
            measure="pack_load",
            fallback_strategy="narrow_pack",
            details={"source_count": source_count, "max_sources": PACK_LOAD_MAX_SOURCES},
        )
    )
    return {
        "can_load_all_sources": allowed,
        "size_bucket": _describe_pack_size(source_count, file_size_mb_total, row_count_total),
        "reason": "Safe to load the full pack at once." if allowed else "; ".join(reasons),
        "max_sources": PACK_LOAD_MAX_SOURCES,
        "max_file_size_mb": PACK_LOAD_MAX_FILE_SIZE_MB,
        "max_row_count": PACK_LOAD_MAX_ROW_COUNT,
        "gate": gate,
    }


def _build_catalog_packs_from_sources(catalog: dict) -> list[dict]:
    sources = [
        source
        for source in (catalog.get("sources", []) or [])
        if str(source.get("source_id") or "").strip() not in RETIRED_PACK_SOURCE_IDS
    ]
    grouped: dict[str, list[dict]] = {}
    for source in sources:
        pack_id = str(source.get("pack_id") or "").strip()
        if not pack_id:
            continue
        grouped.setdefault(pack_id, []).append(source)

    packs = []
    for pack_id, pack_sources in grouped.items():
        representative = next((src for src in pack_sources if src.get("scope") == "global"), pack_sources[0])
        scopes = sorted({str(src.get("scope") or "global") for src in pack_sources})
        categories = sorted({str(src.get("category") or "") for src in pack_sources if src.get("category")})
        data_types = sorted({
            value
            for src in pack_sources
            for value in (
                src.get("data_type") if isinstance(src.get("data_type"), list) else [src.get("data_type")]
            )
            if value
        })
        geographic_levels = sorted({
            str(level)
            for src in pack_sources
            for level in (
                src.get("geographic_levels")
                if isinstance(src.get("geographic_levels"), list)
                else ([src.get("geographic_level")] if src.get("geographic_level") else [])
            )
            if level
        })
        row_count_total = sum(_coerce_int(src.get("row_count")) for src in pack_sources)
        file_size_mb_total = round(sum(_coerce_float(src.get("file_size_mb")) for src in pack_sources), 2)
        source_ids = [src.get("source_id") for src in pack_sources if src.get("source_id")]
        temporal_starts = [
            str(src.get("temporal_coverage", {}).get("start"))
            for src in pack_sources
            if src.get("temporal_coverage", {}).get("start")
        ]
        temporal_ends = [
            str(src.get("temporal_coverage", {}).get("end"))
            for src in pack_sources
            if src.get("temporal_coverage", {}).get("end")
        ]
        default_pack_name = _humanize_pack_id(pack_id)
        pack_name = representative.get("source_name") if len(source_ids) == 1 else default_pack_name
        pack_name = pack_name or default_pack_name
        load_policy = _build_pack_load_policy(len(source_ids), file_size_mb_total, row_count_total)
        packs.append({
            "pack_id": pack_id,
            "pack_name": pack_name,
            "description": representative.get("llm_summary") or representative.get("coverage_description") or "",
            "source_count": len(source_ids),
            "source_ids": source_ids,
            "scopes": scopes,
            "categories": categories,
            "data_types": data_types,
            "geographic_levels": geographic_levels,
            "row_count_total": row_count_total,
            "file_size_mb_total": file_size_mb_total,
            "temporal_coverage": {
                "start": min(temporal_starts) if temporal_starts else None,
                "end": max(temporal_ends) if temporal_ends else None,
            },
            "load_policy": load_policy,
        })

    return sorted(packs, key=lambda pack: pack.get("pack_id", ""))


def get_catalog_packs(catalog: dict | None = None) -> list[dict]:
    payload = catalog or load_catalog() or {}
    packs = payload.get("packs")
    if isinstance(packs, list) and packs:
        return deepcopy(packs)
    return _build_catalog_packs_from_sources(payload)


def get_pack_metadata(pack_id: str, catalog: dict | None = None) -> dict | None:
    pack_id = str(pack_id or "").strip()
    if not pack_id:
        return None
    for pack in get_catalog_packs(catalog):
        if pack.get("pack_id") == pack_id:
            return pack
    return None


def get_source_path(source_id: str):
    """
    Get the path to a source folder using the path field from catalog.

    Args:
        source_id: Source identifier (e.g., 'owid_co2', 'usgs_earthquakes')

    Returns:
        Path: Full path to source folder, or None if not found
    """
    catalog = load_full_catalog()
    for source in catalog.get("sources", []):
        if source.get("source_id") == source_id:
            # Use path field if present, otherwise fall back to old structure
            source_path = source.get("path", f"global/{source_id}")
            return DATA_ROOT / source_path

    # Source not in catalog - try old path as fallback
    return DATA_ROOT / "global" / source_id


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

    runtime_mode = str(get_runtime_config().get("runtime_mode", "local")).strip().lower()

    if runtime_mode == "cloud":
        catalog = load_full_catalog()
        source_rel_path = None
        for source in catalog.get("sources", []):
            if source.get("source_id") == source_id:
                source_rel_path = source.get("path", f"global/{source_id}")
                break
        if source_rel_path is None:
            source_rel_path = f"global/{source_id}"
        try:
            metadata = _fetch_json_from_s3(f"{source_rel_path}/metadata.json")
            _metadata_cache[source_id] = metadata
            return metadata
        except Exception as e:
            logger.error(f"Error loading metadata for {source_id} from S3: {e}")
            return None

    source_folder = get_source_path(source_id)
    if not source_folder or not source_folder.exists():
        return None

    metadata_path = source_folder / "metadata.json"
    if not metadata_path.exists():
        return None

    try:
        with open(metadata_path, 'r', encoding='utf-8-sig') as f:
            metadata = json.load(f)
            _metadata_cache[source_id] = metadata
            return metadata
    except Exception as e:
        logger.error(f"Error loading metadata for {source_id}: {e}")
        return None


def load_source_reference(source_id: str):
    """
    Load reference.json for a specific source.

    Args:
        source_id: Source identifier

    Returns:
        dict: Source reference data or None if not found
    """
    runtime_mode = str(get_runtime_config().get("runtime_mode", "local")).strip().lower()

    if runtime_mode == "cloud":
        catalog = load_full_catalog()
        source_rel_path = None
        for source in catalog.get("sources", []):
            if source.get("source_id") == source_id:
                source_rel_path = source.get("path", f"global/{source_id}")
                break
        if source_rel_path is None:
            source_rel_path = f"global/{source_id}"
        try:
            data = _fetch_json_from_s3(f"{source_rel_path}/reference.json")
            return data if isinstance(data, dict) else None
        except Exception as e:
            logger.error(f"Error loading reference for {source_id} from S3: {e}")
            return None

    source_folder = get_source_path(source_id)
    if not source_folder or not source_folder.exists():
        return None

    reference_path = source_folder / "reference.json"
    if not reference_path.exists():
        return None

    try:
        with open(reference_path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else None
    except Exception as e:
        logger.error(f"Error loading reference for {source_id}: {e}")
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


def prewarm_api_catalog() -> None:
    """Load agent/API discovery artifacts into cache at startup."""
    try:
        catalog = load_api_catalog()
        pack_count = len((catalog or {}).get("packs", []))
        load_api_guide()
        for pack in (catalog or {}).get("packs", []):
            pack_id = pack.get("pack_id")
            if pack_id:
                load_api_pack_detail(pack_id)
        logger.info("API catalog prewarm complete: %d packs loaded", pack_count)
    except Exception as exc:
        logger.warning("API catalog prewarm failed: %s", exc)


def clear_api_discovery_cache():
    """Clear the cached agent/API discovery artifacts."""
    global _api_catalog_cache, _api_catalog_cache_time, _api_catalog_missing_time
    global _api_guide_cache, _api_guide_cache_time, _api_guide_missing_time
    global _api_pack_cache, _api_pack_cache_time, _api_pack_missing_time

    _api_catalog_cache = None
    _api_catalog_cache_time = 0.0
    _api_catalog_missing_time = 0.0
    _api_guide_cache = None
    _api_guide_cache_time = 0.0
    _api_guide_missing_time = 0.0
    _api_pack_cache = {}
    _api_pack_cache_time = {}
    _api_pack_missing_time = {}
    logger.info("API discovery cache cleared")


def clear_catalog_cache():
    """Clear the cached published and WIP catalog payloads."""
    global _catalog_cache, _catalog_cache_time, _catalog_missing_time
    global _full_catalog_cache, _full_catalog_cache_time, _full_catalog_missing_time

    _catalog_cache = None
    _catalog_cache_time = 0.0
    _catalog_missing_time = 0.0
    _full_catalog_cache = None
    _full_catalog_cache_time = 0.0
    _full_catalog_missing_time = 0.0
    logger.info("Catalog caches cleared")


def get_geometry_folder():
    """Get the geometry folder path (resolved via paths.py)."""
    return GEOMETRY_DIR


def get_countries_folder():
    """Get the countries folder path (resolved via paths.py)."""
    return COUNTRIES_DIR


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
                gdf = select_rows(country_geom_path)
                if gdf.empty:
                    gdf = pd.read_parquet(country_geom_path)
                logger.debug(f"Loaded {len(gdf)} features from {country_geom_path}")
                return gdf, None
            except Exception as e:
                logger.warning(f"Error loading {country_geom_path}: {e}")

    # Tier 2: Load crosswalk if exists (for translating loc_ids)
    crosswalk = load_country_crosswalk(iso3)
    if crosswalk:
        logger.debug(f"Loaded crosswalk for {iso3}: {len(crosswalk.get('mappings', {}))} mappings")

    # Tier 3: GADM fallback geometry
    if geometry_folder:
        gadm_path = geometry_folder / f"{iso3}.parquet"
        if gadm_path.exists():
            try:
                gdf = select_rows(gadm_path)
                if gdf.empty:
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
        loc_ids: List of location IDs (e.g., ["USA-WA-073", "USA-OR-067"])

    Returns:
        GeoJSON FeatureCollection with geometries
    """
    import pandas as pd
    import json as json_module

    if not loc_ids:
        return {"type": "FeatureCollection", "features": []}

    from .geometry_handlers import canonicalize_loc_id, translate_loc_id_to_geometry_id

    # Group loc_ids by country (first part before dash, or whole ID for country-level)
    country_loc_ids = {}
    for loc_id in loc_ids:
        loc_id = canonicalize_loc_id(loc_id)
        parts = loc_id.split("-")
        country = parts[0] if parts else loc_id
        if country not in country_loc_ids:
            country_loc_ids[country] = []
        country_loc_ids[country].append(loc_id)

    all_features = []

    for country, lids in country_loc_ids.items():
        countries_folder = get_countries_folder()
        geometry_folder = get_geometry_folder()
        country_geom_path = countries_folder / country / "geometry.parquet" if countries_folder else None
        fallback_geom_path = geometry_folder / f"{country}.parquet" if geometry_folder else None

        parquet_path = None
        crosswalk = None
        uses_crosswalk = False
        _runtime_mode = str(get_runtime_config().get("runtime_mode", "local")).strip().lower()
        if _runtime_mode == "cloud":
            # In cloud mode, assume geometry paths exist; DuckDB will error if missing.
            # Try country-specific geometry first, then GADM fallback.
            if country_geom_path:
                parquet_path = country_geom_path
            elif fallback_geom_path:
                parquet_path = fallback_geom_path
            crosswalk = load_country_crosswalk(country)
            if crosswalk and parquet_path != country_geom_path:
                uses_crosswalk = True
        elif country_geom_path and country_geom_path.exists():
            parquet_path = country_geom_path
        elif fallback_geom_path and fallback_geom_path.exists():
            crosswalk = load_country_crosswalk(country)
            if crosswalk:
                parquet_path = fallback_geom_path
                uses_crosswalk = True
            else:
                parquet_path = fallback_geom_path
        if parquet_path is None and fallback_geom_path and fallback_geom_path.exists():
            parquet_path = fallback_geom_path
            crosswalk = None

        if parquet_path is None:
            logger.warning(f"No geometry found for {country}")
            continue

        remaining_lids = set(lids)
        requested_ids = set(remaining_lids)
        if uses_crosswalk and crosswalk:
            requested_ids.update(
                translate_loc_id_to_geometry_id(loc_id)
                for loc_id in list(remaining_lids)
            )

        gdf = select_rows(
            parquet_path,
            columns=["loc_id", "name", "admin_level", "parent_id", "geometry"],
            in_filters={"loc_id": sorted(requested_ids)},
        )
        if gdf.empty:
            # Fall back to the old whole-file load path if the selective read fails.
            gdf, crosswalk = load_geometry_for_country(country)
        elif uses_crosswalk and crosswalk:
            reverse_map = {}
            for source_map in (crosswalk.get("mappings", {}), crosswalk.get("admin_2_fips", {})):
                for local_loc_id, geo_loc_id in source_map.items():
                    reverse_map.setdefault(geo_loc_id, canonicalize_loc_id(local_loc_id))
            gdf["local_loc_id"] = gdf["loc_id"].map(reverse_map)

        if gdf is None or len(gdf) == 0:
            logger.warning(f"No geometry rows found for {country}")
            continue

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
