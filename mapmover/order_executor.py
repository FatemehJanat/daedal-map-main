"""
Order Executor - executes confirmed orders against parquet data.
No LLM calls - direct data operations.

Implements the "Empty Box" model from CHAT_REDESIGN.md:
1. Expand regions to loc_ids
2. Create empty boxes for each location
3. Process each order item independently (may be from different sources)
4. Fill boxes with values from each source
5. Join with geometry
6. Return GeoJSON with all filled properties
"""

import logging
import hashlib
import re
import pandas as pd
import json
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mapmover")


def _executor_trace_id(order: dict) -> str:
    summary = order.get("summary", "") or ""
    items = order.get("items", []) or []
    lead = items[0].get("source_id", "") if items else ""
    seed = f"{summary[:80]}|{lead}|{len(items)}"
    return hashlib.md5(seed.encode()).hexdigest()[:10]


def _executor_log(trace_id: str, stage: str, started_at: float, extra: str = "") -> float:
    now = time.perf_counter()
    elapsed_ms = (now - started_at) * 1000
    suffix = f" | {extra}" if extra else ""
    logger.info(f"[executor:{trace_id}] {stage}: {elapsed_ms:.1f}ms{suffix}")
    return now

from .geometry_handlers import (
    canonicalize_loc_id,
    load_global_countries,
    load_country_parquet,
    load_geometry_rows_by_loc_ids,
    load_subcounty_geometry,
    translate_geometry_id_to_local_id,
    translate_loc_id_to_geometry_id,
    df_to_geojson,
)

from .paths import DATA_ROOT, CATALOG_PATH
from .data_loading import load_source_metadata
from .source_time_contract import available_years_for_range, metadata_metric_year_range
from .aggregation_system import build_aggregation_spec, apply_temporal_aggregation
from .foundation_helpers import load_reference_json
from .foundation_helpers import load_runtime_result_cap_helpers
from .duckdb_helpers import (
    can_query_event_source,
    is_cloud_mode,
    parquet_columns,
    path_to_uri,
    quote_ident,
    run_df,
    select_columns_from_parquet,
    select_event_ids_by_regions,
    select_peak_positions_by_storm_ids,
    select_rows,
)
from .execution.event_loading import (
    load_event_data as load_event_data_impl,
    load_event_data_duckdb as load_event_data_duckdb_impl,
    resolve_event_parquet_path_for_source,
    resolve_event_source_id as resolve_event_source_id_impl,
)
from .execution.source_loading import (
    candidate_parquet_paths as candidate_parquet_paths_impl,
    get_source_path as get_source_path_impl,
    load_source_data as load_source_data_impl,
)
from .execution.special_order_capabilities import (
    route_default_special_order,
)
from .execution.event_execution import (
    execute_event_order_impl,
    get_coordinate_columns as get_coordinate_columns_impl,
    get_id_column as get_id_column_impl,
    get_time_column as get_time_column_impl,
)
from .execution.aggregate_loading import (
    derive_event_metric_aggregate_data as derive_event_metric_aggregate_data_impl,
    infer_implicit_aggregate_rollup_level as infer_implicit_aggregate_rollup_level_impl,
    load_disaster_aggregate_data_impl,
)
from .execution.geometry_execution import (
    execute_geometry_order_impl,
    execute_geometry_overlay_impl,
)
from .execution.multi_order_execution import (
    classify_execution_family_impl,
    execute_mixed_order_if_needed_impl,
    execute_multi_layer_order_if_needed_impl,
    execute_split_order_impl,
)
from .execution.removal_execution import (
    execute_removal_order_impl,
)
from .runtime.query_intent_primitives import (
    query_prefers_event_retry as query_prefers_event_retry_impl,
)
from .runtime.order_semantics import (
    resolve_pack_source as resolve_pack_source_impl,
    scope_matches_region as scope_matches_region_impl,
)
from .runtime.order_routing import (
    normalize_order_items as normalize_order_items_impl,
    resolve_source_for_item as resolve_source_for_item_impl,
)
from .runtime.aggregate_primitives import (
    resolve_aggregate_admin2_dir as resolve_aggregate_admin2_dir_impl,
    source_has_aggregate_files as source_has_aggregate_files_impl,
)
from .runtime.region_expansion import (
    expand_region as expand_region_impl,
    normalize_county_slug as normalize_county_slug_impl,
    resolve_us_county_slug_loc_id as resolve_us_county_slug_loc_id_impl,
)
from .runtime.sparse_year_clarify import (
    check_sparse_year as check_sparse_year_impl,
)
from .runtime.execution_primitives import (
    build_metrics_response,
    collect_source_metadata,
    load_order_item_dataframe,
    process_metric_items,
    prepare_execution_items,
)
from .runtime.filter_primitives import (
    append_duckdb_filter_clause as append_duckdb_filter_clause_impl,
    apply_dataframe_filters as apply_dataframe_filters_impl,
    normalize_sort_spec as normalize_sort_spec_impl,
)
from .runtime.order_validation import (
    execution_requires_metric as execution_requires_metric_impl,
    validate_execution_items as validate_execution_items_impl,
)

CONVERSIONS_PATH = Path(__file__).parent / "conversions.json"
# Cache conversions to avoid repeated file reads
_conversions_cache = None
_iso_codes_cache = None
_usa_admin_cache = None
_usa_county_slug_cache = {}
_US_REGIONAL_GROUPS = {
    "usa west": {"USA-AZ", "USA-CA", "USA-CO", "USA-ID", "USA-MT", "USA-NM", "USA-NV", "USA-OR", "USA-UT", "USA-WA", "USA-WY"},
    "western us": {"USA-AZ", "USA-CA", "USA-CO", "USA-ID", "USA-MT", "USA-NM", "USA-NV", "USA-OR", "USA-UT", "USA-WA", "USA-WY"},
    "western u.s.": {"USA-AZ", "USA-CA", "USA-CO", "USA-ID", "USA-MT", "USA-NM", "USA-NV", "USA-OR", "USA-UT", "USA-WA", "USA-WY"},
    "western united states": {"USA-AZ", "USA-CA", "USA-CO", "USA-ID", "USA-MT", "USA-NM", "USA-NV", "USA-OR", "USA-UT", "USA-WA", "USA-WY"},
}


def _coerce_year(value) -> Optional[int]:
    """Best-effort year coercion for LLM-generated order fields."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)

    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        # Accept ISO-ish strings like "2015-01-01" by reading first 4 digits.
        if len(text) >= 4 and text[:4].isdigit():
            return int(text[:4])
        return None


def _coerce_date_year(value) -> Optional[int]:
    """Best-effort extraction of a calendar year from ISO-ish date fields."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _coerce_year(value)
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


def _normalize_year_filters(item: dict) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """Normalize year/year_start/year_end in-place and bridge ISO date bounds to years."""
    year = _coerce_year(item.get("year"))
    year_start = _coerce_year(item.get("year_start"))
    year_end = _coerce_year(item.get("year_end"))
    date_start_year = _coerce_date_year(item.get("date_start"))
    date_end_year = _coerce_date_year(item.get("date_end"))

    if year_start is None and date_start_year is not None:
        year_start = date_start_year
    if year_end is None and date_end_year is not None:
        year_end = date_end_year
    if year is None and year_start is not None and year_end is not None and year_start == year_end:
        year = year_start

    if year is not None:
        item["year"] = year
    if year_start is not None:
        item["year_start"] = year_start
    if year_end is not None:
        item["year_end"] = year_end

    return year, year_start, year_end


def _normalize_county_slug(value: str) -> str:
    return normalize_county_slug_impl(value)


def _resolve_us_county_slug_loc_id(region: str) -> Optional[str]:
    return resolve_us_county_slug_loc_id_impl(
        region,
        cache_dict=_usa_county_slug_cache,
        load_country_parquet_func=load_country_parquet,
    )


def _normalize_sort_spec(sort_spec):
    return normalize_sort_spec_impl(sort_spec)


def _normalize_geo_level(value) -> Optional[str]:
    """Normalize requested geo_level values from the order."""
    if not value:
        return None
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"country", "admin_0"}:
        return "admin_0"
    if text.startswith("admin_") and text[6:].isdigit():
        return text
    return None


def _derive_eurostat_geo_level(loc_id: str) -> Optional[str]:
    """
    Infer NUTS admin level from Eurostat loc_id shape.

    Examples:
    - FRA -> admin_0
    - FRA-FR1 -> admin_1
    - FRA-FR10 -> admin_2
    - FRA-FR101 -> admin_3
    """
    if not loc_id:
        return None
    text = str(loc_id).strip()
    if "-" not in text:
        return "admin_0" if len(text) == 3 else None
    suffix = text.split("-", 1)[1]
    code_len = len(suffix)
    if code_len == 3:
        return "admin_1"
    if code_len == 4:
        return "admin_2"
    if code_len == 5:
        return "admin_3"
    return None


def _load_catalog() -> dict:
    """Load catalog via data_loading (handles both local and cloud mode with TTL caching)."""
    from .data_loading import load_catalog as _load_catalog_dl
    return _load_catalog_dl()


def _resolve_source_for_item(item: dict, catalog: dict) -> str:
    return resolve_source_for_item_impl(
        item,
        catalog,
        resolve_pack_source_func=resolve_pack_source_impl,
    )


def _normalize_order_items(items: list, catalog: dict) -> list:
    return normalize_order_items_impl(
        items,
        catalog,
        resolve_source_for_item_func=_resolve_source_for_item,
        logger=logger,
    )


def _execution_requires_metric(item: dict, source_info: dict | None) -> bool:
    return execution_requires_metric_impl(item, source_info)


def _apply_dataframe_filters(df: pd.DataFrame, filters: dict | None) -> pd.DataFrame:
    return apply_dataframe_filters_impl(df, filters)


def _append_duckdb_filter_clause(
    where_clauses: list[str],
    params: list,
    available_cols: set[str],
    field: str,
    value,
) -> None:
    append_duckdb_filter_clause_impl(
        where_clauses,
        params,
        available_cols,
        field,
        value,
        quote_ident_func=quote_ident,
    )


def _validate_execution_items(items: list) -> str | None:
    return validate_execution_items_impl(
        items,
        get_source_from_catalog_func=_get_source_from_catalog,
        execution_requires_metric_func=_execution_requires_metric,
    )


def _aggregate_metric_frame(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    """Aggregate a disaster metric frame to a coarser spatial level."""
    agg_map = {}
    for col in df.columns:
        if col in group_cols or col == "source":
            continue
        if col in {"year", "window_end_year"}:
            continue
        if col.startswith("max_"):
            agg_map[col] = "max"
        elif col.startswith("avg_"):
            agg_map[col] = "mean"
        elif col in {"event_count", "deaths", "injuries", "damage_usd", "damage_millions"}:
            agg_map[col] = "sum"
        elif col.startswith("total_"):
            agg_map[col] = "sum"
        elif col in {"years_observed"}:
            agg_map[col] = "max"
        elif col in {"window_start_year", "window_years"}:
            agg_map[col] = "first"
        else:
            if pd.api.types.is_numeric_dtype(df[col]):
                agg_map[col] = "sum"

    if not agg_map:
        return df[group_cols].drop_duplicates().reset_index(drop=True)

    out = df.groupby(group_cols, as_index=False).agg(agg_map)
    if "source" in df.columns:
        out["source"] = df["source"].iloc[0]
    return out


def _load_disaster_aggregate_data(source_id: str, item: dict) -> tuple[Optional[pd.DataFrame], Optional[dict]]:
    return load_disaster_aggregate_data_impl(
        source_id,
        item,
        get_source_path_func=_get_source_path,
        resolve_aggregate_admin2_dir_func=resolve_aggregate_admin2_dir_impl,
        normalize_year_filters_func=_normalize_year_filters,
        parquet_columns_func=parquet_columns,
        select_rows_func=select_rows,
        is_cloud_mode_func=is_cloud_mode,
        load_source_metadata_func=load_source_metadata,
        infer_implicit_aggregate_rollup_level_func=_infer_implicit_aggregate_rollup_level,
        derive_event_metric_aggregate_data_func=_derive_event_metric_aggregate_data,
        aggregate_metric_frame_func=_aggregate_metric_frame,
        translate_geometry_id_to_local_id_func=translate_geometry_id_to_local_id,
        path_to_uri_func=path_to_uri,
        logger=logger,
    )


def _infer_implicit_aggregate_rollup_level(item: dict) -> Optional[str]:
    return infer_implicit_aggregate_rollup_level_impl(
        item,
        expand_region_func=expand_region,
    )


def _derive_event_metric_aggregate_data(source_id: str, item: dict, requested_metric: str) -> tuple[Optional[pd.DataFrame], Optional[dict]]:
    return derive_event_metric_aggregate_data_impl(
        source_id,
        item,
        requested_metric,
        load_event_data_func=load_event_data,
    )


def _source_supports_disaster_aggregates(source_id: str) -> bool:
    catalog_source = _get_source_from_catalog(source_id)
    if not catalog_source:
        return False
    if not is_cloud_mode():
        return source_has_aggregate_files_impl(
            catalog_source,
            data_root=DATA_ROOT,
        )

    files = (catalog_source or {}).get("files") or {}
    if not isinstance(files, dict):
        files = {}
    if any(key in files for key in ("yearly", "rolling_10y", "rolling_20y")):
        return True

    source_path = (catalog_source or {}).get("path")
    if not source_path:
        return False
    agg_dir = resolve_aggregate_admin2_dir_impl(source_path, data_root=DATA_ROOT)
    candidates = (
        agg_dir / "yearly.parquet",
        agg_dir / "rolling_10y.parquet",
        agg_dir / "rolling_20y.parquet",
    )
    for path in candidates:
        try:
            if parquet_columns(path):
                return True
        except Exception:
            continue
    return False


def _get_source_data_type(source_id: str) -> str:
    """
    Get data_type for a source from catalog.
    Returns: 'events', 'metrics', 'gridded', 'geometry', or 'metrics' as default.
    """
    catalog = _load_catalog()
    for src in catalog.get("sources", []):
        if src.get("source_id") == source_id:
            return src.get("data_type", "metrics")
    return "metrics"  # Default to metrics if not found


def _resolve_event_source_id(source_id: str) -> str:
    return resolve_event_source_id_impl(
        source_id,
        load_source_metadata_func=load_source_metadata,
        load_catalog_func=_load_catalog,
    )


# Special geographic levels that need geometry from dual sources (not standard admin hierarchy)
SPECIAL_GEOMETRY_LEVELS = {"zcta", "tribal"}


def _has_geometry_data_type(data_type) -> bool:
    """Check if data_type includes geometry (handles both string and array formats)."""
    if data_type is None:
        return False
    if isinstance(data_type, list):
        return "geometry" in data_type
    return data_type == "geometry"


def _find_geometry_source_for_level(geo_level: str, scope: str = None) -> Optional[dict]:
    """
    Find a catalog source that provides geometry for a special geographic level.

    For special levels like 'zcta' or 'tribal', we need to find the dual source
    that has both geometry data and matches the geographic_level.

    Args:
        geo_level: The geographic level (e.g., 'zcta', 'tribal')
        scope: Optional scope filter (e.g., 'usa')

    Returns:
        Source dict from catalog if found, None otherwise
    """
    catalog = _load_catalog()
    for src in catalog.get("sources", []):
        # Match geographic_level
        if src.get("geographic_level") != geo_level:
            continue
        # Must have geometry in data_type
        if not _has_geometry_data_type(src.get("data_type")):
            continue
        # Optional scope filter
        if scope and src.get("scope", "").lower() != scope.lower():
            continue
        return src
    return None


def _load_geometry_from_source(source_info: dict, filter_regions: set = None) -> Optional[pd.DataFrame]:
    """
    Load geometry dataframe from a catalog source, optionally filtered by region.

    Args:
        source_info: Source dict from catalog with 'path' key
        filter_regions: Optional set of parent region codes to filter by (e.g., {"USA-FL"})

    Returns:
        DataFrame with loc_id, name, geometry columns, or None
    """
    import logging
    logger = logging.getLogger(__name__)

    source_path = source_info.get("path")
    if not source_path:
        return None

    full_path = DATA_ROOT / source_path
    parquet_files = list(full_path.glob("*.parquet")) if full_path.is_dir() else []

    if not parquet_files:
        logger.warning(f"No parquet files found in {full_path}")
        return None

    # Load the parquet file
    parquet_path = parquet_files[0]
    logger.info(f"Loading geometry from dual source: {parquet_path}")

    try:
        columns = ["loc_id", "name", "geometry", "parent_id"]
        df = select_columns_from_parquet(parquet_path, columns)
        if df.empty:
            df = pd.read_parquet(parquet_path, columns=columns)

        # Filter by parent region if specified (e.g., filter_region = "USA-FL" for Florida ZIPs)
        # parent_id is at county bridge level (USA-FL-001), so use prefix matching
        # Use vectorized str.startswith with tuple for efficiency (same pattern as metrics pipeline)
        if filter_regions and "parent_id" in df.columns:
            # Build prefix tuple with trailing dash for hierarchy matching
            prefixes = tuple(f"{r}-" for r in filter_regions)
            # Vectorized: match prefix OR exact match
            mask = df["parent_id"].str.startswith(prefixes, na=False) | df["parent_id"].isin(filter_regions)
            df = df[mask]
            logger.info(f"Filtered to {len(df)} features matching regions: {filter_regions}")

        # Return only geometry-relevant columns
        cols = ["loc_id", "name", "geometry", "parent_id"]
        available_cols = [c for c in cols if c in df.columns]
        if "loc_id" not in available_cols or "geometry" not in available_cols:
            logger.warning(f"Missing required columns in {parquet_path}")
            return None
        return df[available_cols]
    except Exception as e:
        logger.error(f"Error loading geometry from {parquet_path}: {e}")
        return None


def execute_geometry_overlay(geometry_overlay: dict, filter_loc_ids: list = None) -> dict:
    return execute_geometry_overlay_impl(
        geometry_overlay,
        filter_loc_ids=filter_loc_ids,
        get_source_path_func=_get_source_path,
        parquet_columns_func=parquet_columns,
        select_columns_from_parquet_func=select_columns_from_parquet,
        df_to_geojson_func=df_to_geojson,
    )


def execute_geometry_order(order: dict) -> dict:
    return execute_geometry_order_impl(
        order,
        execute_geometry_overlay_func=execute_geometry_overlay,
        load_source_metadata_func=load_source_metadata,
    )


def _get_source_path(source_id: str) -> Path:
    return get_source_path_impl(
        source_id,
        load_catalog_func=_load_catalog,
        data_root=DATA_ROOT,
    )


def _candidate_parquet_paths(source_dir: Path, metadata: dict) -> list[Path]:
    return candidate_parquet_paths_impl(source_dir, metadata)


def _load_conversions() -> dict:
    """Load conversions.json with caching."""
    global _conversions_cache
    if _conversions_cache is None:
        with open(CONVERSIONS_PATH, encoding='utf-8') as f:
            _conversions_cache = json.load(f)
    return _conversions_cache


def _load_iso_codes() -> dict:
    """Load reference/iso_codes.json with caching."""
    global _iso_codes_cache
    if _iso_codes_cache is None:
        data = load_reference_json("iso_codes.json")
        _iso_codes_cache = data if isinstance(data, dict) else {}
    return _iso_codes_cache


def _load_usa_admin() -> dict:
    """Load reference/usa_admin.json with caching."""
    global _usa_admin_cache
    if _usa_admin_cache is None:
        data = load_reference_json("usa/usa_admin.json")
        _usa_admin_cache = data if isinstance(data, dict) else {}
    return _usa_admin_cache


def load_source_data(source_id: str, *, year: int | None = None, loc_id_prefix: str | None = None) -> tuple:
    return load_source_data_impl(
        source_id,
        year=year,
        loc_id_prefix=loc_id_prefix,
        get_source_path_func=_get_source_path,
        load_source_metadata_func=load_source_metadata,
        candidate_parquet_paths_func=_candidate_parquet_paths,
        is_cloud_mode_func=is_cloud_mode,
        path_to_uri_func=path_to_uri,
        select_rows_func=select_rows,
        logger=logger,
    )


def load_event_data(source_id: str, event_file_key: str = "events") -> tuple:
    return load_event_data_impl(
        source_id,
        event_file_key,
        get_source_path_func=_get_source_path,
        load_source_metadata_func=load_source_metadata,
        is_cloud_mode_func=is_cloud_mode,
        select_rows_func=select_rows,
    )


def _resolve_event_parquet_path(source_id: str, event_file_key: str = "events") -> tuple[Path, dict]:
    return resolve_event_parquet_path_for_source(
        source_id,
        event_file_key,
        get_source_path_func=_get_source_path,
        load_source_metadata_func=load_source_metadata,
        is_cloud_mode_func=is_cloud_mode,
    )


def _duckdb_can_query_events(source_id: str) -> bool:
    return can_query_event_source(source_id)


def _load_event_data_duckdb(source_id: str, item: dict, event_file_key: str = "events") -> tuple[pd.DataFrame, dict]:
    return load_event_data_duckdb_impl(
        source_id,
        item,
        event_file_key,
        resolve_event_parquet_path_func=_resolve_event_parquet_path,
        parquet_columns_func=parquet_columns,
        normalize_year_filters_func=_normalize_year_filters,
        normalize_sort_spec_func=_normalize_sort_spec,
        expand_region_func=expand_region,
        load_iso_codes_func=_load_iso_codes,
        load_usa_admin_func=_load_usa_admin,
        append_duckdb_filter_clause_func=_append_duckdb_filter_clause,
        path_to_uri_func=path_to_uri,
        quote_ident_func=quote_ident,
        run_df_func=run_df,
        default_event_limit=DEFAULT_EVENT_LIMIT,
        max_event_limit=MAX_EVENT_LIMIT,
    )


def expand_region(region: str) -> set:
    return expand_region_impl(
        region,
        resolve_us_county_slug_loc_id_func=_resolve_us_county_slug_loc_id,
        regional_groups=_US_REGIONAL_GROUPS,
        load_conversions_func=_load_conversions,
        load_iso_codes_func=_load_iso_codes,
        load_usa_admin_func=_load_usa_admin,
    )


def find_metric_column(df: pd.DataFrame, metric: str, metadata: Optional[dict] = None) -> Optional[str]:
    """
    Find matching column name for a metric (fuzzy match).

    Returns:
        Column name or None if not found
    """
    def _norm(value: str) -> str:
        return str(value).lower().replace("_", " ").replace("-", " ").strip()

    def _find_alias_match(candidates: list[str]) -> Optional[str]:
        normalized_columns = {_norm(col): col for col in df.columns}
        for candidate in candidates:
            matched = normalized_columns.get(_norm(candidate))
            if matched:
                return matched
        return None

    def _find_term_bundle_match(term_bundles: list[set[str]]) -> Optional[str]:
        best_match = None
        best_score = 0
        for col in df.columns:
            if col in ("loc_id", "year"):
                continue
            col_words = set(_norm(col).split())
            for bundle in term_bundles:
                if bundle.issubset(col_words):
                    score = len(bundle)
                    if score > best_score:
                        best_match = col
                        best_score = score
        return best_match

    def _find_metadata_metric_match() -> Optional[str]:
        metrics_meta = (metadata or {}).get("metrics") or {}
        if not isinstance(metrics_meta, dict):
            return None

        best_match = None
        best_score = 0

        for col, metric_meta in metrics_meta.items():
            if col not in df.columns:
                continue

            phrases = [col]
            if isinstance(metric_meta, dict):
                metric_name = metric_meta.get("name")
                if metric_name:
                    phrases.append(metric_name)
                metric_keywords = metric_meta.get("keywords") or []
                if isinstance(metric_keywords, list):
                    phrases.extend(str(keyword) for keyword in metric_keywords if keyword)
            elif metric_meta:
                phrases.append(str(metric_meta))

            for phrase in phrases:
                phrase_norm = _norm(phrase)
                if not phrase_norm:
                    continue
                if phrase_norm == metric_lower or metric_lower == phrase_norm:
                    return col
                if metric_lower in phrase_norm or phrase_norm in metric_lower:
                    score = len(set(phrase_norm.split()) & metric_words) + 2
                else:
                    phrase_words = set(phrase_norm.split())
                    score = len(metric_words & phrase_words)
                if score > best_score:
                    best_match = col
                    best_score = score

        return best_match if best_score > 0 else None

    metric_lower = _norm(metric)
    metric_words = set(metric_lower.split())

    alias_candidates = {
        "event count": ["event_count"],
        "frequency": ["event_count"],
        "tornado count": ["event_count", "tornado_count"],
        "earthquake count": ["event_count"],
        "hurricane count": ["event_count"],
        "wildfire count": ["event_count"],
        "tsunami count": ["event_count"],
        "railways length": [
            "railways_km", "railway_km", "railways_length_km", "railways_length", "railways"
        ],
        "railway length": [
            "railways_km", "railway_km", "railways_length_km", "railways_length", "railways"
        ],
        "life expectancy": [
            "life_expectancy", "life_expectancy_years", "life_expectancy_at_birth"
        ],
        "gdp per capita": [
            "gdp_per_capita", "gdp_per_capita_ppp", "gdp_per_capita_usd", "gdp_per_capita_ppp_usd"
        ],
        "birth rate": [
            "birth_rate", "birth_rate_per_1000", "births_per_1000_population", "crude_birth_rate"
        ],
        "highest peaks": ["highest_point_m"],
        "highest peak": ["highest_point_m"],
        "coastline length": ["coastline_km"],
        "coastline": ["coastline_km"],
    }
    alias_term_bundles = {
        "event count": [{"event", "count"}],
        "frequency": [{"event", "count"}],
        "tornado count": [{"event", "count"}, {"tornado", "count"}],
        "earthquake count": [{"event", "count"}, {"earthquake", "count"}],
        "hurricane count": [{"event", "count"}, {"hurricane", "count"}],
        "wildfire count": [{"event", "count"}, {"wildfire", "count"}],
        "tsunami count": [{"event", "count"}, {"tsunami", "count"}],
        "railways length": [{"railways"}, {"railway"}, {"railways", "km"}],
        "railway length": [{"railways"}, {"railway"}, {"railway", "km"}],
        "life expectancy": [{"life", "expectancy"}],
        "gdp per capita": [{"gdp", "capita"}, {"income", "capita"}],
        "birth rate": [{"birth", "rate"}, {"births", "rate"}],
        "highest peaks": [{"highest", "point"}, {"peak"}],
        "highest peak": [{"highest", "point"}, {"peak"}],
        "coastline length": [{"coastline"}, {"coast", "length"}],
        "coastline": [{"coastline"}],
    }

    metadata_match = _find_metadata_metric_match()
    if metadata_match:
        return metadata_match

    alias_match = _find_alias_match(alias_candidates.get(metric_lower, []))
    if alias_match:
        return alias_match

    bundle_match = _find_term_bundle_match(alias_term_bundles.get(metric_lower, []))
    if bundle_match:
        return bundle_match

    # Exact match first (normalized)
    for col in df.columns:
        col_norm = _norm(col)
        if col_norm == metric_lower:
            return col

    # Metric contained in column name
    for col in df.columns:
        col_norm = _norm(col)
        if metric_lower in col_norm:
            return col

    # Column name contained in metric (reverse)
    for col in df.columns:
        if col in ("loc_id", "year"):
            continue
        col_norm = _norm(col)
        if col_norm in metric_lower:
            return col

    # Word overlap - at least 2 words match
    if len(metric_words) >= 2:
        for col in df.columns:
            if col in ("loc_id", "year"):
                continue
            col_words = set(_norm(col).split())
            overlap = metric_words & col_words
            if len(overlap) >= 2:
                return col

    # Single significant word match (last resort)
    significant_words = metric_words - {"of", "the", "a", "an", "for", "in", "on", "to"}
    for col in df.columns:
        if col in ("loc_id", "year"):
            continue
        col_words = set(_norm(col).split())
        if significant_words & col_words:
            return col

    return None


def _extract_date_window(item: dict) -> tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    """Infer date window from order item fields."""
    date_start = pd.to_datetime(item.get("date_start"), errors="coerce")
    date_end = pd.to_datetime(item.get("date_end"), errors="coerce")

    year, year_start, year_end = _normalize_year_filters(item)

    if pd.isna(date_start) and year_start:
        date_start = pd.Timestamp(year_start, 1, 1)
    if pd.isna(date_end) and year_end:
        date_end = pd.Timestamp(year_end, 12, 31)
    if pd.isna(date_start) and year:
        date_start = pd.Timestamp(year, 1, 1)
    if pd.isna(date_end) and year:
        date_end = pd.Timestamp(year, 12, 31)

    return (None if pd.isna(date_start) else date_start, None if pd.isna(date_end) else date_end)


def _load_fx_with_aggregation(source_id: str, item: dict, metadata: dict) -> tuple[Optional[pd.DataFrame], dict]:
    """
    Load FX data with temporal aggregation contract.

    Returns:
        (df_or_none, trace)
    """
    trace = {
        "source_id": source_id,
        "requested": {
            "time_granularity": item.get("time_granularity"),
            "aggregation": item.get("aggregation"),
            "date_start": item.get("date_start"),
            "date_end": item.get("date_end"),
            "year": item.get("year"),
            "year_start": item.get("year_start"),
            "year_end": item.get("year_end"),
        },
    }

    spec = build_aggregation_spec(item, metadata)
    trace["spec"] = spec.to_dict()

    # Currency now defaults to the published monthly lane for the human app unless
    # the order explicitly requests a different temporal shape.
    has_temporal_override = bool(
        item.get("time_granularity")
        or item.get("aggregation")
        or item.get("date_start")
        or item.get("date_end")
        or source_id == "fx_usd_historical"
    )
    if not has_temporal_override:
        trace["applied"] = {"path": "all_countries.parquet", "mode": "native_yearly"}
        return None, trace

    requested_granularity = str(spec.time_granularity or "").strip().lower()
    runtime_source_id = source_id
    parquet_name = "data.parquet"
    if requested_granularity == "weekly":
        runtime_source_id = "fx_usd_historical_weekly"
    elif requested_granularity == "monthly":
        runtime_source_id = "fx_usd_historical_monthly"

    source_dir = _get_source_path(runtime_source_id)
    published_path = source_dir / parquet_name
    if not published_path.exists():
        trace["applied"] = {
            "path": "all_countries.parquet",
            "mode": "fallback_no_published_temporal_source",
            "resolved_source_id": runtime_source_id,
        }
        return None, trace

    try:
        fx = select_columns_from_parquet(published_path, ["date", "loc_id", "local_per_usd"])
        if fx.empty:
            fx = pd.read_parquet(published_path, columns=["date", "loc_id", "local_per_usd"])
    except Exception as e:
        trace["applied"] = {
            "path": "all_countries.parquet",
            "mode": "fallback_read_error",
            "resolved_source_id": runtime_source_id,
            "error": str(e),
        }
        return None, trace

    start_ts, end_ts = _extract_date_window(item)
    if start_ts is not None:
        fx = fx[pd.to_datetime(fx["date"], errors="coerce") >= start_ts]
    if end_ts is not None:
        fx = fx[pd.to_datetime(fx["date"], errors="coerce") <= end_ts]

    if fx.empty:
        trace["applied"] = {
            "path": str(published_path),
            "mode": "empty_after_filter",
            "resolved_source_id": runtime_source_id,
        }
        return pd.DataFrame(columns=["loc_id", "year", "source", "local_per_usd"]), trace

    aggregated = apply_temporal_aggregation(
        fx,
        spec,
        date_col="date",
        value_col="local_per_usd",
        group_cols=("loc_id",),
    )

    if aggregated.empty:
        trace["applied"] = {
            "path": str(published_path),
            "mode": "empty_after_aggregation",
            "resolved_source_id": runtime_source_id,
        }
        return pd.DataFrame(columns=["loc_id", "year", "source", "local_per_usd"]), trace

    aggregated["year"] = pd.to_datetime(aggregated["date"], errors="coerce").dt.year
    aggregated = aggregated.dropna(subset=["year"])
    aggregated["year"] = aggregated["year"].astype(int)

    # Keep runtime map contract stable: loc_id + year + metric.
    yearly_method = "last" if spec.method == "last" else "mean"
    if yearly_method == "last":
        yearly = (
            aggregated.sort_values(["loc_id", "year", "date"])
            .groupby(["loc_id", "year"], as_index=False)
            .tail(1)[["loc_id", "year", "local_per_usd"]]
            .reset_index(drop=True)
        )
    else:
        yearly = (
            aggregated.groupby(["loc_id", "year"], as_index=False)
            .agg(local_per_usd=("local_per_usd", "mean"))
        )

    yearly["source"] = source_id
    trace["applied"] = {
        "path": str(published_path),
        "mode": "published_temporal_aggregation",
        "resolved_source_id": runtime_source_id,
        "requested_granularity": spec.time_granularity,
        "requested_method": spec.method,
        "coerced_output": "yearly_for_runtime",
        "input_rows": int(len(fx)),
        "post_agg_rows": int(len(aggregated)),
        "yearly_rows": int(len(yearly)),
    }
    return yearly[["loc_id", "year", "source", "local_per_usd"]], trace


# =============================================================================
# Derived Field Calculations
# =============================================================================

def apply_derived_fields(boxes: dict, derived_specs: list, year: int = None) -> list:
    """
    Apply derived field calculations to filled boxes.

    Args:
        boxes: Dict of loc_id -> {metric: value, ...}
        derived_specs: List of derived field specifications from postprocessor
        year: Year for context (unused, kept for API compatibility)

    Returns:
        List of warning messages for missing data
    """
    warnings = []

    def _resolve_metric_value(metrics: dict, candidates) -> tuple[object, str | None]:
        candidate_list = [c for c in (candidates or []) if c]
        if not candidate_list:
            return None, None

        for candidate in candidate_list:
            if candidate in metrics:
                return metrics[candidate], candidate

        lowered = {str(key).lower(): key for key in metrics.keys()}
        for candidate in candidate_list:
            matched_key = lowered.get(str(candidate).lower())
            if matched_key is not None:
                return metrics[matched_key], matched_key

        return None, None

    for spec in derived_specs:
        numerator_name = spec.get("numerator")
        denominator_name = spec.get("denominator")
        numerator_candidates = spec.get("numerator_candidates") or [numerator_name]
        denominator_candidates = spec.get("denominator_candidates") or [denominator_name]
        label = spec.get("label", f"{numerator_name}/{denominator_name}")
        multiplier = spec.get("multiplier", 1)

        for loc_id, metrics in boxes.items():
            # Get numerator value
            num_val, _ = _resolve_metric_value(metrics, numerator_candidates)

            if num_val is None:
                continue  # Skip silently if numerator not available

            # Get denominator value
            denom_val, resolved_denominator_key = _resolve_metric_value(metrics, denominator_candidates)

            # Calculate derived value
            if denom_val is None:
                warnings.append(f"{loc_id}: {denominator_name} unavailable")
                continue

            if denom_val == 0:
                zero_name = resolved_denominator_key or denominator_name
                warnings.append(f"{loc_id}: {zero_name} is zero")
                continue

            result = (float(num_val) / float(denom_val)) * multiplier
            metrics[f"{label} (calculated)"] = result

    return warnings


# =============================================================================
# Event Mode Execution (for disaster/event data)
# =============================================================================

# Default event limits (can be overridden by metadata.default_limit)
DEFAULT_EVENT_LIMIT = 1000
MAX_EVENT_LIMIT = 5000


def _get_source_from_catalog(source_id: str) -> dict:
    """Get source info from catalog by source_id."""
    catalog = _load_catalog()
    if not catalog:
        return {}
    for source in catalog.get("sources", []):
        if source.get("source_id") == source_id:
            return source
    return {}


def _find_source_files(source_id: str) -> list:
    """
    Find parquet files for a source_id.

    Args:
        source_id: Source ID (e.g., "geometry_zcta")

    Returns:
        List of Path objects to parquet files, or empty list if not found
    """
    source = _get_source_from_catalog(source_id)
    if not source:
        return []

    source_path = source.get("path")
    if not source_path:
        return []

    full_path = DATA_ROOT / source_path
    if full_path.is_dir():
        return list(full_path.glob("*.parquet"))
    elif full_path.with_suffix(".parquet").exists():
        return [full_path.with_suffix(".parquet")]
    return []


def execute_event_order(order: dict) -> dict:
    return execute_event_order_impl(
        order,
        normalize_year_filters_func=_normalize_year_filters,
        normalize_sort_spec_func=_normalize_sort_spec,
        resolve_event_source_id_func=_resolve_event_source_id,
        duckdb_can_query_events_func=_duckdb_can_query_events,
        load_event_data_duckdb_func=_load_event_data_duckdb,
        load_event_data_func=load_event_data,
        get_source_from_catalog_func=_get_source_from_catalog,
        load_source_metadata_func=load_source_metadata,
        resolve_event_parquet_path_func=_resolve_event_parquet_path,
        select_peak_positions_by_storm_ids_func=select_peak_positions_by_storm_ids,
        get_coordinate_columns_func=get_coordinate_columns_impl,
        get_time_column_func=get_time_column_impl,
        get_id_column_func=get_id_column_impl,
        expand_region_func=expand_region,
        default_event_limit=DEFAULT_EVENT_LIMIT,
        max_event_limit=MAX_EVENT_LIMIT,
    )


def _execute_removal_order(order: dict, items: list, source_id: str) -> dict:
    from .session_cache import session_manager

    return execute_removal_order_impl(
        order,
        items,
        source_id,
        get_source_data_type_func=_get_source_data_type,
        get_source_from_catalog_func=_get_source_from_catalog,
        expand_region_func=expand_region,
        get_loc_ids_by_region_func=_get_loc_ids_by_region,
        get_event_ids_by_region_func=_get_event_ids_by_region,
        session_manager=session_manager,
        coerce_year_func=_coerce_year,
    )


def _get_event_ids_by_region(source_id: str, regions: list) -> list:
    """
    Query parquet file to get event_ids matching regions.

    Args:
        source_id: Source ID (e.g., "earthquakes_usgs")
        regions: List of region prefixes (e.g., ["USA-CA"])

    Returns:
        List of matching event_ids
    """
    logger = logging.getLogger(__name__)
    try:
        parquet_files = _find_source_files(source_id)
        if not parquet_files:
            return []

        if _duckdb_can_query_events(source_id):
            event_ids = select_event_ids_by_regions(parquet_files[0], regions)
            logger.info(f"Found {len(event_ids)} event_ids matching regions {regions} in {source_id} via DuckDB")
            return event_ids

        columns = ["loc_id", "parent_id"]
        df = select_columns_from_parquet(parquet_files[0], columns)
        if df.empty:
            df = pd.read_parquet(parquet_files[0], columns=columns)

        if "event_id" not in df.columns:
            return []

        # Events use loc_id for region matching (where the event occurred)
        if "loc_id" in df.columns and regions:
            prefixes = tuple(f"{r}-" for r in regions)
            region_set = set(regions)
            mask = df["loc_id"].str.startswith(prefixes, na=False) | df["loc_id"].isin(region_set)
            matching = df[mask]
        else:
            matching = df

        event_ids = matching["event_id"].tolist()
        logger.info(f"Found {len(event_ids)} event_ids matching regions {regions} in {source_id}")
        return event_ids

    except Exception as e:
        logger.error(f"Error getting event_ids by region: {e}")
        return []


def _get_loc_ids_by_region(source_id: str, regions: list) -> list:
    """
    Query parquet file to get loc_ids matching regions by parent_id prefix.

    Args:
        source_id: Source ID (e.g., "geometry_zcta")
        regions: List of region prefixes (e.g., ["USA-FL"])

    Returns:
        List of matching loc_ids
    """
    logger = logging.getLogger(__name__)
    try:
        # Find parquet file for this source
        parquet_files = _find_source_files(source_id)
        if not parquet_files:
            logger.warning(f"No parquet files found for source: {source_id}")
            return []

        # Load only needed columns for region matching
        columns = ["loc_id", "parent_id"]
        df = select_columns_from_parquet(parquet_files[0], columns)
        if df.empty:
            df = pd.read_parquet(parquet_files[0], columns=columns)

        if "parent_id" not in df.columns:
            logger.warning(f"No parent_id column in {source_id}")
            return []

        # Build prefix tuple for matching
        prefixes = tuple(f"{r}-" for r in regions)
        region_set = set(regions)

        # Vectorized filter
        mask = df["parent_id"].str.startswith(prefixes, na=False) | df["parent_id"].isin(region_set)
        matching = df[mask]

        loc_ids = matching["loc_id"].tolist() if "loc_id" in matching.columns else []
        logger.info(f"Found {len(loc_ids)} loc_ids matching regions {regions} in {source_id}")
        return loc_ids

    except Exception as e:
        logger.error(f"Error getting loc_ids by region: {e}")
        return []


def _execute_mixed_order_if_needed(order: dict, items: list, source_id: str) -> dict:
    return execute_mixed_order_if_needed_impl(
        order,
        items,
        source_id,
        execute_split_order_func=_execute_split_order,
        logger=logging.getLogger(__name__),
    )


def _execute_split_order(order: dict, add_items: list, remove_items: list, source_id: str) -> dict:
    return execute_split_order_impl(
        order,
        add_items,
        remove_items,
        source_id,
        execute_removal_order_func=_execute_removal_order,
        execute_order_func=execute_order,
        logger=logging.getLogger(__name__),
    )


def _classify_execution_family(item: dict) -> str:
    return classify_execution_family_impl(
        item,
        get_source_from_catalog_func=_get_source_from_catalog,
        special_geometry_levels=SPECIAL_GEOMETRY_LEVELS,
        has_geometry_data_type_func=_has_geometry_data_type,
    )


def _execute_multi_layer_order_if_needed(order: dict, items: list) -> dict | None:
    return execute_multi_layer_order_if_needed_impl(
        order,
        items,
        classify_execution_family_func=_classify_execution_family,
        execute_geometry_order_func=execute_geometry_order,
        execute_order_func=execute_order,
    )


def execute_order(order: dict) -> dict:
    """
    Execute a confirmed order and return GeoJSON response.

    Implements the "Empty Box" model:
    1. Expand all regions to loc_ids
    2. Create empty boxes for each target location
    3. Process each item, fill boxes with values
    4. Join with geometry
    5. Build GeoJSON

    Supports multi-year mode when year_start/year_end provided:
    - Returns base geometry + year_data dict for efficient time slider

    Supports event mode when mode="events":
    - Returns individual events as GeoJSON points

    Args:
        order: {items: [{source_id, metric, region, year, year_start, year_end, sort, mode}, ...], summary: str}

    Returns:
        Single year: {type, geojson, summary, count, sources}
        Multi-year: {type, geojson, year_data, year_range, multi_year, summary, count, sources}
        Event mode: {type: "events", event_type, geojson, time_range, summary, count, sources}
    """
    t_execute_start = time.perf_counter()
    trace_id = _executor_trace_id(order)
    items = order.get("items", [])
    summary = order.get("summary", "")
    action = order.get("action", "add")  # "add" (default) or "remove"

    logger.info(f"[executor:{trace_id}] start | items={len(items)} action={action}")

    if not items:
        return {
            "type": "error",
            "message": "No items in order",
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0
        }

    items, validation_error = prepare_execution_items(
        items=items,
        load_catalog_func=_load_catalog,
        normalize_order_items_func=_normalize_order_items,
        get_source_data_type_func=_get_source_data_type,
        source_supports_disaster_aggregates_func=_source_supports_disaster_aggregates,
        validate_execution_items_func=_validate_execution_items,
    )
    if validation_error:
        return {
            "type": "error",
            "message": validation_error,
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0,
        }

    # Determine data_type for this order from first item's source
    # (for tagging the response so frontend knows which pipeline to use)
    primary_source_id = items[0].get("source_id") if items else None
    order_data_type = _get_source_data_type(primary_source_id) if primary_source_id else "metrics"

    routed_result = route_default_special_order(
        order=order,
        items=items,
        action=action,
        primary_source_id=primary_source_id,
        get_source_from_catalog_func=_get_source_from_catalog,
        execute_removal_order_func=_execute_removal_order,
        execute_mixed_order_if_needed_func=_execute_mixed_order_if_needed,
        execute_multi_layer_order_if_needed_func=_execute_multi_layer_order_if_needed,
        execute_event_order_func=execute_event_order,
    )
    if routed_result is not None:
        return routed_result

    # Note: Geometry orders (dual sources like ZCTA) go through metrics pipeline
    # They get special handling in Step 4 based on geographic_level

    # Check if any item uses year range (multi-year mode)
    multi_year_mode = any(
        item.get("year_start") and item.get("year_end")
        for item in items
    )

    # Step 1: Determine all target loc_ids and collect metadata
    metadata_state = collect_source_metadata(
        items=items,
        expand_region_func=expand_region,
        load_disaster_aggregate_data_func=_load_disaster_aggregate_data,
        load_source_data_func=load_source_data,
        logger=logger,
        trace_id=trace_id,
    )
    target_countries = metadata_state["target_countries"]
    geo_levels = metadata_state["geo_levels"]
    sources_used = metadata_state["sources_used"]
    aggregate_item_cache = metadata_state["aggregate_item_cache"]
    normalized_geo_levels = sorted(str(level) for level in geo_levels if level is not None)
    _executor_log(
        trace_id,
        "source_metadata_collected",
        t_execute_start,
        f"sources={len(sources_used)} geo_levels={normalized_geo_levels}",
    )

    # For multi-year: year_data[year][loc_id] = {metric: value}
    # For single-year: boxes[loc_id] = {metric: value}
    year_data = {} if multi_year_mode else None
    boxes = {} if not multi_year_mode else None
    all_years = set()
    metric_key = None  # Track the primary metric label for frontend
    all_metrics = []  # Track ALL metric labels for multi-metric support
    metric_year_ranges = {}  # Track year range per metric for time slider adjustment
    metric_source_map = {}  # Track which metric belongs to which source
    aggregation_trace = []  # Track applied aggregation contract per item
    loc_level_map = {}  # Track loc_id -> geo_level for multi-level multi-year filtering
    location_features = []  # Direct point features for location_shape sources
    requested_year_start = None  # Track requested range for comparison
    requested_year_end = None
    all_region_codes = set()  # Track all requested region codes for GeoJSON
    requested_geo_levels = set()

    item_state = process_metric_items(
        order=order,
        items=items,
        multi_year_mode=multi_year_mode,
        aggregate_item_cache=aggregate_item_cache,
        year_data=year_data,
        boxes=boxes,
        all_years=all_years,
        metric_key=metric_key,
        all_metrics=all_metrics,
        metric_year_ranges=metric_year_ranges,
        metric_source_map=metric_source_map,
        aggregation_trace=aggregation_trace,
        loc_level_map=loc_level_map,
        location_features=location_features,
        requested_year_start=requested_year_start,
        requested_year_end=requested_year_end,
        all_region_codes=all_region_codes,
        requested_geo_levels=requested_geo_levels,
        trace_id=trace_id,
        logger=logger,
        executor_log_func=_executor_log,
        perf_counter_func=time.perf_counter,
        normalize_year_filters_func=_normalize_year_filters,
        normalize_geo_level_func=_normalize_geo_level,
        normalize_sort_spec_func=_normalize_sort_spec,
        load_order_item_dataframe_func=lambda **kwargs: load_order_item_dataframe(
            **kwargs,
            load_disaster_aggregate_data_func=_load_disaster_aggregate_data,
            load_source_data_func=load_source_data,
        ),
        derive_eurostat_geo_level_func=_derive_eurostat_geo_level,
        load_fx_with_aggregation_func=_load_fx_with_aggregation,
        find_metric_column_func=find_metric_column,
        check_sparse_year_func=check_sparse_year_impl,
        expand_region_func=expand_region,
        canonicalize_loc_id_func=canonicalize_loc_id,
        translate_loc_id_to_geometry_id_func=translate_loc_id_to_geometry_id,
        translate_geometry_id_to_local_id_func=translate_geometry_id_to_local_id,
        apply_dataframe_filters_func=_apply_dataframe_filters,
        get_coordinate_columns_func=_get_coordinate_columns,
        available_years_for_range_func=available_years_for_range,
        metadata_metric_year_range_func=metadata_metric_year_range,
        apply_derived_fields_func=apply_derived_fields,
        apply_runtime_result_cap_func=load_runtime_result_cap_helpers()["apply_runtime_result_cap"],
        merge_cap_info_func=load_runtime_result_cap_helpers()["merge_cap_info"],
    )
    if item_state.get("early_result") is not None:
        return item_state["early_result"]
    year_data = item_state["year_data"]
    boxes = item_state["boxes"]
    all_years = item_state["all_years"]
    metric_key = item_state["metric_key"]
    all_metrics = item_state["all_metrics"]
    metric_year_ranges = item_state["metric_year_ranges"]
    metric_source_map = item_state["metric_source_map"]
    aggregation_trace = item_state["aggregation_trace"]
    loc_level_map = item_state["loc_level_map"]
    location_features = item_state["location_features"]
    requested_year_start = item_state["requested_year_start"]
    requested_year_end = item_state["requested_year_end"]
    all_region_codes = item_state["all_region_codes"]
    requested_geo_levels = item_state["requested_geo_levels"]
    cap_info = item_state.get("cap_info")
    _executor_log(trace_id, "data_boxes_ready", t_execute_start, f"multi_year={multi_year_mode} boxes={len(boxes or {})} years={len(year_data or {})}")

    return build_metrics_response(
        order=order,
        items=items,
        summary=summary,
        multi_year_mode=multi_year_mode,
        geo_levels=geo_levels,
        requested_geo_levels=requested_geo_levels,
        sources_used=sources_used,
        boxes=boxes,
        year_data=year_data,
        loc_level_map=loc_level_map,
        location_features=location_features,
        all_region_codes=all_region_codes,
        metric_source_map=metric_source_map,
        aggregation_trace=aggregation_trace,
        requested_year_start=requested_year_start,
        requested_year_end=requested_year_end,
        all_years=all_years,
        metric_key=metric_key,
        all_metrics=all_metrics,
        metric_year_ranges=metric_year_ranges,
        trace_id=trace_id,
        t_execute_start=t_execute_start,
        logger=logger,
        executor_log_func=_executor_log,
        perf_counter_func=time.perf_counter,
        special_geometry_levels=SPECIAL_GEOMETRY_LEVELS,
        find_geometry_source_for_level_func=_find_geometry_source_for_level,
        load_geometry_from_source_func=_load_geometry_from_source,
        load_global_countries_func=load_global_countries,
        load_subcounty_geometry_func=load_subcounty_geometry,
        load_geometry_rows_by_loc_ids_func=load_geometry_rows_by_loc_ids,
        load_country_parquet_func=load_country_parquet,
        query_prefers_event_retry_func=query_prefers_event_retry_impl,
        scope_matches_region_func=scope_matches_region_impl,
        execute_order_func=execute_order,
        load_catalog_func=_load_catalog,
        cap_info=cap_info,
    )
