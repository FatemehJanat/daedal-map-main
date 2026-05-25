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
from .duckdb_helpers import (
    can_query_event_source,
    is_cloud_mode,
    parquet_columns,
    path_to_uri,
    quote_ident,
    resolve_event_parquet_path,
    run_df,
    select_columns_from_parquet,
    select_event_ids_by_regions,
    select_peak_positions_by_storm_ids,
    select_rows,
)
from .execution.special_order_capabilities import (
    route_default_special_order,
)
from .execution.event_execution import (
    build_empty_wildfire_perimeter_response as build_empty_wildfire_perimeter_response_impl,
    detect_event_type as detect_event_type_impl,
    execute_event_order_impl,
    get_coordinate_columns as get_coordinate_columns_impl,
    get_id_column as get_id_column_impl,
    get_significance_column as get_significance_column_impl,
    get_time_column as get_time_column_impl,
)
from .execution.geometry_execution import (
    execute_geometry_order_impl,
    execute_geometry_overlay_impl,
)
from .execution.removal_execution import (
    execute_removal_order_impl,
)
from .runtime.query_intent_primitives import (
    query_prefers_event_retry as query_prefers_event_retry_impl,
)
from .runtime.retry_primitives import (
    build_event_retry_order as build_event_retry_order_impl,
    resolve_event_sibling_source as resolve_event_sibling_source_impl,
)
from .runtime.execution_primitives import (
    build_metrics_response,
    collect_source_metadata,
    load_order_item_dataframe,
    process_metric_items,
    prepare_execution_items,
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
    text = str(value or "").strip().lower().replace("-", " ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    for suffix in (
        " county",
        " parish",
        " borough",
        " census area",
        " municipality",
        " city and borough",
        " city",
    ):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return " ".join(text.split())


def _resolve_us_county_slug_loc_id(region: str) -> Optional[str]:
    value = str(region or "").strip()
    match = re.fullmatch(r"USA-([A-Z]{2})-([A-Za-z0-9-]+)", value)
    if not match:
        return None

    state_abbrev = match.group(1)
    county_slug = match.group(2)
    if county_slug.isdigit():
        return None

    cache_key = (state_abbrev, county_slug.lower())
    if cache_key in _usa_county_slug_cache:
        return _usa_county_slug_cache[cache_key]

    counties_df = load_country_parquet("USA", admin_level=2)
    if counties_df is None or counties_df.empty or "loc_id" not in counties_df.columns or "name" not in counties_df.columns:
        _usa_county_slug_cache[cache_key] = None
        return None

    target = _normalize_county_slug(county_slug)
    subset = counties_df[counties_df["loc_id"].astype(str).str.startswith(f"USA-{state_abbrev}-", na=False)].copy()
    if subset.empty:
        _usa_county_slug_cache[cache_key] = None
        return None

    subset["_norm_name"] = subset["name"].map(_normalize_county_slug)
    exact = subset[subset["_norm_name"] == target]
    loc_id = str(exact.iloc[0]["loc_id"]) if not exact.empty else None
    _usa_county_slug_cache[cache_key] = loc_id
    return loc_id


def _normalize_sort_spec(sort_spec):
    """Coerce LLM-generated sort payloads into a consistent dict shape."""
    if not sort_spec:
        return None
    if isinstance(sort_spec, dict):
        by_value = sort_spec.get("by")
        if not by_value:
            return None
        normalized = dict(sort_spec)
        normalized["by"] = str(by_value)
        normalized["order"] = str(sort_spec.get("order", "desc")).lower()
        return normalized
    if isinstance(sort_spec, str):
        raw = str(sort_spec).strip().lower()
        alias_map = {
            "date_desc": {"by": "timestamp", "order": "desc"},
            "date_asc": {"by": "timestamp", "order": "asc"},
            "time_desc": {"by": "timestamp", "order": "desc"},
            "time_asc": {"by": "timestamp", "order": "asc"},
            "timestamp_desc": {"by": "timestamp", "order": "desc"},
            "timestamp_asc": {"by": "timestamp", "order": "asc"},
            "latest": {"by": "timestamp", "order": "desc"},
            "newest": {"by": "timestamp", "order": "desc"},
            "recent": {"by": "timestamp", "order": "desc"},
            "most_recent": {"by": "timestamp", "order": "desc"},
        }
        if raw in alias_map:
            return alias_map[raw]
        return {"by": sort_spec, "order": "desc"}
    if isinstance(sort_spec, list):
        for candidate in sort_spec:
            normalized = _normalize_sort_spec(candidate)
            if normalized:
                return normalized
    return None


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


def _scope_matches_region(scope: str, region) -> bool:
    """Return True if the given catalog scope covers the requested region string."""
    if not region:
        return scope == "global"
    r = str(region).lower()
    if scope == "CAN":
        return r.startswith("can") or r.startswith("canada")
    if scope == "USA":
        return r.startswith("usa") or r.startswith("us-")
    if scope == "global":
        return True  # global is always a valid fallback
    # For other ISO scopes (e.g. "AUS") match by lowercase prefix
    return r.startswith(scope.lower())


def _item_prefers_geometry_pack_source(item: dict) -> bool:
    text = " ".join(
        str(value or "")
        for value in (
            item.get("summary"),
            item.get("metric"),
            item.get("region"),
            ((item.get("_hints") or {}).get("original_query") if isinstance(item.get("_hints"), dict) else ""),
        )
    ).lower()
    geometry_terms = (
        "county",
        "counties",
        "district",
        "districts",
        "admin_2",
        "admin2",
        "tract",
        "tracts",
        "state",
        "states",
        "province",
        "provinces",
        "top ",
        "highest",
        "lowest",
        "rank",
        "ranking",
    )
    return any(term in text for term in geometry_terms)


def _resolve_source_for_item(item: dict, catalog: dict) -> str:
    """
    Resolve the correct source_id for an order item.

    Resolution order:
    1. If item already has source_id and no pack_id: use it directly (pre-release / internal).
    2. If item has pack_id: find all catalog sources with that pack_id, pick the best scope match.
    3. If no specific match found: fall back to the global-scoped source in the pack.
    4. If routing is still ambiguous or unsupported: return None so the request can fail early.
    """
    pack_id = item.get("pack_id")
    source_id = item.get("source_id")

    if not pack_id:
        # No pack routing requested - use source_id as-is
        return source_id

    region = item.get("region")
    sources = catalog.get("sources", [])
    pack_sources = [s for s in sources if s.get("pack_id") == pack_id]

    if not pack_sources:
        # Unknown pack - fall back to source_id if provided, else None
        return source_id

    if _item_prefers_geometry_pack_source(item):
        geometry_sources = [s for s in pack_sources if s.get("geojson_shape") == "geometry_shape"]
        exact_geometry = [
            s for s in geometry_sources
            if s.get("scope") != "global" and _scope_matches_region(s.get("scope", "global"), region)
        ]
        if exact_geometry:
            return exact_geometry[0]["source_id"]

        global_geometry = [s for s in geometry_sources if s.get("scope") == "global"]
        if global_geometry:
            return global_geometry[0]["source_id"]

    # Prefer exact (non-global) scope match, fall back to global
    exact_matches = [s for s in pack_sources if s.get("scope") != "global" and _scope_matches_region(s.get("scope", "global"), region)]
    if exact_matches:
        return exact_matches[0]["source_id"]

    global_matches = [s for s in pack_sources if s.get("scope") == "global"]
    if global_matches:
        return global_matches[0]["source_id"]

    # No safe resolution path remains. Let validation stop execution instead of
    # silently choosing an arbitrary source from the pack.
    return None


def _normalize_order_items(items: list, catalog: dict) -> list:
    """
    Resolve pack_id -> source_id for all items in an order.
    Items that already have a valid source_id keep it, even when pack_id is also
    present. This preserves earlier pack resolution done by the order-taker and
    avoids re-routing an aggregate item back to an event source at execution time.
    """
    catalog_sources = {
        str(src.get("source_id") or "").strip(): src
        for src in catalog.get("sources", [])
        if src.get("source_id")
    }
    resolved = []
    for item in items:
        item = dict(item)  # shallow copy so we don't mutate the original
        source_id = str(item.get("source_id") or "").strip()
        pack_id = item.get("pack_id")
        if pack_id and source_id:
            src = catalog_sources.get(source_id)
            if src and src.get("pack_id") == pack_id:
                resolved.append(item)
                continue
        if pack_id:
            item["source_id"] = _resolve_source_for_item(item, catalog)
            logger.debug(f"[routing] pack_id={item['pack_id']} region={item.get('region')} -> source_id={item['source_id']}")
        resolved.append(item)
    return resolved


def _resolve_event_sibling_source(catalog: dict, item: dict) -> str | None:
    return resolve_event_sibling_source_impl(
        catalog,
        item,
        scope_matches_region_func=_scope_matches_region,
    )


def _query_prefers_event_retry(query: str) -> bool:
    return query_prefers_event_retry_impl(query)


def _build_event_retry_order(order: dict, items: list, catalog: dict) -> dict | None:
    return build_event_retry_order_impl(
        order,
        items,
        catalog,
        query_prefers_event_retry_func=_query_prefers_event_retry,
        resolve_event_sibling_source_func=_resolve_event_sibling_source,
    )


def _execution_requires_metric(item: dict, source_info: dict | None) -> bool:
    if item.get("type") in {"derived", "derived_result"}:
        return False
    if item.get("mode") == "events":
        return False
    if str((source_info or {}).get("geojson_shape") or "").strip().lower() == "location_shape":
        return False

    data_type = (source_info or {}).get("data_type", "metrics")
    if isinstance(data_type, list):
        if "events" in data_type and item.get("mode") != "aggregate":
            return False
        return "metrics" in data_type
    return data_type == "metrics"


def _apply_dataframe_filters(df: pd.DataFrame, filters: dict | None) -> pd.DataFrame:
    """Apply generic equality/range/presence filters to a DataFrame."""
    if df is None or df.empty or not isinstance(filters, dict) or not filters:
        return df

    filtered = df
    for field, value in filters.items():
        if field.endswith("_min"):
            col = field[:-4]
            if col in filtered.columns:
                filtered = filtered[filtered[col] >= value]
            continue
        if field.endswith("_max"):
            col = field[:-4]
            if col in filtered.columns:
                filtered = filtered[filtered[col] <= value]
            continue
        if field not in filtered.columns:
            continue

        if isinstance(value, dict):
            op = str(value.get("op") or "").strip().lower()
            min_value = value.get("min")
            max_value = value.get("max")
            if min_value is not None:
                filtered = filtered[filtered[field] >= min_value]
            if max_value is not None:
                filtered = filtered[filtered[field] <= max_value]
            if op in {"not_empty", "present", "exists"}:
                series = filtered[field]
                filtered = filtered[series.notna() & (series.astype(str).str.strip() != "")]
            elif op == "in":
                candidates = value.get("values") or []
                if candidates:
                    filtered = filtered[filtered[field].isin(candidates)]
            elif op == "eq" and "value" in value:
                filtered = filtered[filtered[field] == value.get("value")]
            elif op in {"!=", "ne"} and "value" in value:
                filtered = filtered[filtered[field] != value.get("value")]
            elif op in {">", "gt"} and "value" in value:
                filtered = filtered[filtered[field] > value.get("value")]
            elif op in {">=", "gte"} and "value" in value:
                filtered = filtered[filtered[field] >= value.get("value")]
            elif op in {"<", "lt"} and "value" in value:
                filtered = filtered[filtered[field] < value.get("value")]
            elif op in {"<=", "lte"} and "value" in value:
                filtered = filtered[filtered[field] <= value.get("value")]
            continue

        if isinstance(value, (list, tuple, set)):
            candidates = [candidate for candidate in value if candidate is not None]
            if candidates:
                filtered = filtered[filtered[field].isin(candidates)]
            continue

        if isinstance(value, bool):
            series = filtered[field]
            if value:
                filtered = filtered[series.notna() & (series.astype(str).str.strip() != "")]
            else:
                filtered = filtered[series.isna() | (series.astype(str).str.strip() == "")]
            continue

        filtered = filtered[filtered[field] == value]

    return filtered


def _append_duckdb_filter_clause(
    where_clauses: list[str],
    params: list,
    available_cols: set[str],
    field: str,
    value,
) -> None:
    """Translate an order filter entry into DuckDB WHERE fragments."""
    if field.endswith("_min"):
        col = field[:-4]
        if col in available_cols and value is not None:
            where_clauses.append(f"{quote_ident(col)} >= ?")
            params.append(value)
        return

    if field.endswith("_max"):
        col = field[:-4]
        if col in available_cols and value is not None:
            where_clauses.append(f"{quote_ident(col)} <= ?")
            params.append(value)
        return

    if field not in available_cols:
        return

    if isinstance(value, dict):
        min_value = value.get("min")
        max_value = value.get("max")
        if min_value is not None:
            where_clauses.append(f"{quote_ident(field)} >= ?")
            params.append(min_value)
        if max_value is not None:
            where_clauses.append(f"{quote_ident(field)} <= ?")
            params.append(max_value)

        op = str(value.get("op") or "").strip().lower()
        if op in {"not_empty", "present", "exists"}:
            where_clauses.append(f"{quote_ident(field)} IS NOT NULL")
            where_clauses.append(f"trim(CAST({quote_ident(field)} AS VARCHAR)) <> ''")
            return
        if op == "in":
            candidates = [candidate for candidate in (value.get("values") or []) if candidate is not None]
            if candidates:
                placeholders = ", ".join("?" for _ in candidates)
                where_clauses.append(f"{quote_ident(field)} IN ({placeholders})")
                params.extend(candidates)
            return
        if "value" in value:
            op_map = {
                "eq": "=",
                "=": "=",
                "ne": "!=",
                "!=": "!=",
                "gt": ">",
                ">": ">",
                "gte": ">=",
                ">=": ">=",
                "lt": "<",
                "<": "<",
                "lte": "<=",
                "<=": "<=",
            }
            sql_op = op_map.get(op)
            if sql_op:
                where_clauses.append(f"{quote_ident(field)} {sql_op} ?")
                params.append(value.get("value"))
            return
        return

    if isinstance(value, (list, tuple, set)):
        candidates = [candidate for candidate in value if candidate is not None]
        if candidates:
            placeholders = ", ".join("?" for _ in candidates)
            where_clauses.append(f"{quote_ident(field)} IN ({placeholders})")
            params.extend(candidates)
        return

    if isinstance(value, bool):
        if value:
            where_clauses.append(f"{quote_ident(field)} IS NOT NULL")
            where_clauses.append(f"trim(CAST({quote_ident(field)} AS VARCHAR)) <> ''")
        else:
            where_clauses.append(
                f"({quote_ident(field)} IS NULL OR trim(CAST({quote_ident(field)} AS VARCHAR)) = '')"
            )
        return

    where_clauses.append(f"{quote_ident(field)} = ?")
    params.append(value)


def _validate_execution_items(items: list) -> str | None:
    for idx, item in enumerate(items, start=1):
        source_id = item.get("source_id")
        pack_id = item.get("pack_id")
        if not source_id:
            if pack_id:
                return f"Item {idx} could not resolve pack_id '{pack_id}' to a concrete source_id"
            return f"Item {idx} is missing source_id"

        source_info = _get_source_from_catalog(source_id)
        if not source_info:
            return f"Item {idx} references unknown source_id '{source_id}'"

        if _execution_requires_metric(item, source_info) and not item.get("metric"):
            return f"Item {idx} for source '{source_id}' is missing a concrete metric"

    return None


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


def _resolve_aggregate_admin2_dir(source_dir: Path) -> Path:
    """
    Resolve the admin2 aggregate folder for either:
    - a parent hazard source directory containing `aggregates/admin2/`, or
    - a dedicated aggregate source already rooted at `.../aggregates/admin2`.
    """
    # Pack-facing aggregate source rows live under `.../sources/aggregates`,
    # but the actual parquet files still live at the parent hazard path.
    if (
        source_dir.name.lower() == "admin2"
        and source_dir.parent.name.lower() == "aggregates"
        and source_dir.parent.parent.name.lower() == "sources"
    ):
        return source_dir.parent.parent.parent / "aggregates" / "admin2"
    if source_dir.name.lower() == "aggregates" and source_dir.parent.name.lower() == "sources":
        return source_dir.parent.parent / "aggregates" / "admin2"
    if source_dir.name.lower() == "admin2" and source_dir.parent.name.lower() == "aggregates":
        return source_dir
    if source_dir.name.lower() == "aggregates":
        return source_dir / "admin2"
    return source_dir / "aggregates" / "admin2"


def _load_disaster_aggregate_data(source_id: str, item: dict) -> tuple[Optional[pd.DataFrame], Optional[dict]]:
    """Load disaster aggregate parquet for event sources when query intent is choropleth/aggregate."""
    source_dir = _get_source_path(source_id)
    agg_dir = _resolve_aggregate_admin2_dir(source_dir)
    use_rolling = bool(item.get("aggregate_use_rolling"))
    requested_window = item.get("aggregate_window_years")

    candidates = []
    if use_rolling and requested_window:
        candidates.append(agg_dir / f"rolling_{int(requested_window)}y.parquet")
    if use_rolling:
        candidates.extend([agg_dir / "rolling_20y.parquet", agg_dir / "rolling_10y.parquet"])
    candidates.append(agg_dir / "yearly.parquet")

    parquet_path = None
    df = None
    last_error = None
    year, year_start, year_end = _normalize_year_filters(item)
    region = item.get("region")
    for candidate in candidates:
        if parquet_path is not None:
            break
        if not is_cloud_mode() and not candidate.exists():
            continue
        try:
            exact_filters = {}
            compare_filters = []
            starts_with_filters = {}
            available_cols = parquet_columns(candidate)
            aggregate_year_col = "year" if "year" in available_cols else ("window_end_year" if "window_end_year" in available_cols else None)
            if aggregate_year_col:
                if year is not None:
                    exact_filters[aggregate_year_col] = year
                elif year_start is not None and year_end is not None:
                    compare_filters.extend(
                        [
                            (aggregate_year_col, ">=", year_start),
                            (aggregate_year_col, "<=", year_end),
                        ]
                    )
            if region and "loc_id" in available_cols and re.match(r"^[A-Z]{2,3}(?:-[A-Z0-9]+)*$", str(region).strip()):
                starts_with_filters["loc_id"] = str(region).strip()
            maybe_df = select_rows(
                candidate,
                exact_filters=exact_filters or None,
                compare_filters=compare_filters or None,
                starts_with_filters=starts_with_filters or None,
            )
            if maybe_df.empty and candidate.exists():
                maybe_df = pd.read_parquet(candidate)
            parquet_path = candidate
            df = maybe_df
        except Exception as exc:
            last_error = exc
            continue

    if parquet_path is None or df is None:
        if last_error:
            logger.warning(f"[aggregate] failed to load aggregate parquet for {source_id}: {last_error}")
        return None, None

    metadata = load_source_metadata(source_id) or {}
    metadata = dict(metadata)
    implicit_rollup_level = _infer_implicit_aggregate_rollup_level(item)
    rollup_level = item.get("aggregate_rollup_level") or implicit_rollup_level or "admin_2"
    metadata["geographic_level"] = rollup_level
    metadata["aggregate_parquet"] = str(parquet_path)

    if "window_end_year" in df.columns and "year" not in df.columns:
        df = df.rename(columns={"window_end_year": "year"})

    requested_metric = str(item.get("metric") or "").strip()
    if requested_metric and requested_metric not in df.columns:
        fallback_df, fallback_metadata = _derive_event_metric_aggregate_data(source_id, item, requested_metric)
        if fallback_df is not None and fallback_metadata is not None:
            df = fallback_df
            metadata = fallback_metadata
            rollup_level = "admin_0"
            logger.info(
                f"[aggregate] fallback {source_id}: derived metric='{requested_metric}' from event rows at admin_0"
            )

    # If using rolling windows without an explicit year filter, default to latest window per loc_id.
    year, year_start, year_end = _normalize_year_filters(item)
    if "year" in df.columns and use_rolling and year is None and year_start is None and year_end is None:
        df = df.sort_values(["loc_id", "year"]).groupby("loc_id", as_index=False).tail(1)

    # Historical rollups over all years.
    if item.get("aggregate_all_years") and "year" in df.columns:
        group_cols = ["loc_id"]
        df = _aggregate_metric_frame(df, group_cols)

    # Roll admin2 aggregates up to admin0 when explicitly requested.
    if rollup_level == "admin_0" and "loc_id" in df.columns:
        df = df.copy()
        df["loc_id"] = df["loc_id"].astype(str).str.split("-").str[0]
        group_cols = ["loc_id"]
        if "year" in df.columns:
            group_cols.append("year")
        df = _aggregate_metric_frame(df, group_cols)
        metadata["geographic_level"] = "admin_0"
    elif rollup_level == "admin_1" and "loc_id" in df.columns:
        df = df.copy()
        df["loc_id"] = (
            df["loc_id"]
            .astype(str)
            .map(translate_geometry_id_to_local_id)
            .str.split("-")
            .str[:2]
            .str.join("-")
        )
        group_cols = ["loc_id"]
        if "year" in df.columns:
            group_cols.append("year")
        df = _aggregate_metric_frame(df, group_cols)
        metadata["geographic_level"] = "admin_1"

    logger.info(
        f"[aggregate] load {source_id}: path={path_to_uri(parquet_path) if is_cloud_mode() else parquet_path} "
        f"rows={len(df)} level={metadata.get('geographic_level')}"
    )
    return df, metadata


def _infer_implicit_aggregate_rollup_level(item: dict) -> Optional[str]:
    if item.get("aggregate_rollup_level"):
        return None
    region = item.get("region")
    if not region:
        if item.get("aggregate_all_years") or item.get("aggregate_use_rolling"):
            return "admin_0"
        year = item.get("year")
        year_start = item.get("year_start")
        year_end = item.get("year_end")
        if year_start is not None or year_end is not None:
            if year is None or year_start != year_end:
                return "admin_0"
        return None
    region_codes = expand_region(region)
    if len(region_codes) <= 1:
        return None

    normalized = [str(code) for code in region_codes if isinstance(code, str)]
    if not normalized:
        return None

    if all("-" not in code for code in normalized):
        return "admin_0"

    country_prefixes = {code.split("-")[0] for code in normalized if "-" in code}
    if len(country_prefixes) == 1 and all(code.count("-") >= 1 for code in normalized):
        return "admin_1"

    return None


def _derive_event_metric_aggregate_data(source_id: str, item: dict, requested_metric: str) -> tuple[Optional[pd.DataFrame], Optional[dict]]:
    event_df, metadata = load_event_data(source_id)
    if event_df is None or event_df.empty:
        return None, None
    if requested_metric not in event_df.columns or "timestamp" not in event_df.columns:
        return None, None

    df = event_df.copy()
    timestamps = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df[timestamps.notna()].copy()
    if df.empty:
        return None, None
    df["year"] = timestamps[timestamps.notna()].dt.year.astype("Int64")
    df = df[df["year"].notna()].copy()
    if df.empty:
        return None, None

    # Raw event loc_ids are incident ids with country prefixes; for aggregate fallback
    # we can still build meaningful country-level totals from the prefix.
    df["loc_id"] = df["loc_id"].astype(str).str.split("-").str[0]
    df["event_count"] = 1

    group_cols = ["loc_id", "year"]
    agg_map = {requested_metric: "sum"}
    if requested_metric != "event_count":
        agg_map["event_count"] = "sum"
    out = df.groupby(group_cols, as_index=False).agg(agg_map)
    out["source"] = source_id

    fallback_metadata = dict(metadata or {})
    fallback_metadata["geographic_level"] = "admin_0"
    fallback_metadata["aggregate_parquet"] = "event_metric_fallback"
    return out, fallback_metadata


def _source_supports_disaster_aggregates(source_id: str) -> bool:
    source_dir = _get_source_path(source_id)
    if not source_dir:
        return False
    agg_dir = _resolve_aggregate_admin2_dir(source_dir)
    candidates = (
        agg_dir / "yearly.parquet",
        agg_dir / "rolling_10y.parquet",
        agg_dir / "rolling_20y.parquet",
    )
    if not is_cloud_mode():
        return any(path.exists() for path in candidates)
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


def _get_source_path(source_id: str) -> Optional[str]:
    """Get the path for a source from catalog."""
    catalog = _load_catalog()
    for src in catalog.get("sources", []):
        if src.get("source_id") == source_id:
            return src.get("path")
    return None


def _resolve_event_source_id(source_id: str) -> str:
    """Resolve a human-facing event pack alias to its canonical event source id."""
    normalized = str(source_id or "").strip()
    if not normalized:
        return normalized
    if load_source_metadata(normalized) is not None:
        return normalized

    catalog = _load_catalog()
    event_sources = [
        str(src.get("source_id") or "").strip()
        for src in catalog.get("sources", [])
        if str(src.get("pack_id") or "").strip() == normalized and str(src.get("data_type") or "").strip() == "events"
    ]
    event_sources = [source for source in event_sources if source]
    if len(event_sources) == 1:
        return event_sources[0]
    return normalized


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
    """Get the full path to a source directory using catalog path field."""
    catalog = _load_catalog()
    for source in catalog.get("sources", []):
        if source.get("source_id") == source_id:
            # Use path field if present, otherwise fall back to old structure
            source_path = source.get("path", f"global/{source_id}")
            return DATA_ROOT / source_path

    # Source not in catalog - try old path as fallback
    return DATA_ROOT / "global" / source_id


def _candidate_parquet_paths(source_dir: Path, metadata: dict) -> list[Path]:
    """Return ordered parquet candidates for a source.

    Cloud mode cannot list remote directories, so we need to trust metadata
    before falling back to generic filenames.
    """
    candidates: list[Path] = []
    seen: set[str] = set()

    def _add_candidate(name: str | None) -> None:
        filename = str(name or "").strip()
        if not filename or not filename.endswith(".parquet"):
            return
        if filename in seen:
            return
        seen.add(filename)
        candidates.append(source_dir / filename)

    files_section = metadata.get("files")
    if isinstance(files_section, dict):
        for info in files_section.values():
            if not isinstance(info, dict):
                continue
            _add_candidate(info.get("name") or info.get("filename"))

    primary_files = metadata.get("primary_files")
    if isinstance(primary_files, list):
        for entry in primary_files:
            _add_candidate(entry)

    for key in ("primary_file", "parquet_file", "data_file", "data_filename", "filename", "file_name"):
        _add_candidate(metadata.get(key))

    coverage = metadata.get("geographic_coverage", {}) or {}
    country_code = str(coverage.get("country", "")).strip().upper()
    if country_code:
        _add_candidate(f"{country_code}.parquet")

    source_parts = source_dir.parts
    if "countries" in source_parts:
        try:
            countries_idx = source_parts.index("countries")
            inferred_country = source_parts[countries_idx + 1].upper()
            _add_candidate(f"{inferred_country}.parquet")
        except Exception:
            pass

    for fallback_name in ("all_countries.parquet", "GLOBAL.parquet", "data.parquet"):
        _add_candidate(fallback_name)

    return candidates


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
    """
    Load parquet and metadata for a source.

    Args:
        year: If provided, push year filter into DuckDB query (avoids full scan).
        loc_id_prefix: If provided, push loc_id prefix filter into DuckDB query (e.g. 'USA-CA').

    Returns:
        tuple: (DataFrame, metadata dict)
    """
    source_dir = _get_source_path(source_id)

    metadata = load_source_metadata(source_id)
    if metadata is None:
        raise ValueError(f"Could not load metadata for {source_id}")

    exact_filters = {}
    starts_with_filters = {}
    if year is not None:
        exact_filters["year"] = year
    if loc_id_prefix:
        starts_with_filters["loc_id"] = loc_id_prefix

    parquet_candidates = _candidate_parquet_paths(source_dir, metadata)
    if is_cloud_mode():
        # In S3 mode, no local parquet files exist. Try metadata-declared parquet
        # names first, then only fall back to generic filenames.
        if not parquet_candidates:
            raise ValueError(f"Cannot determine parquet path for {source_id} in S3 mode")

        last_df = pd.DataFrame()
        for parquet_path in parquet_candidates:
            uri = path_to_uri(parquet_path)
            logger.info(f"[S3] load_source_data({source_id}): trying uri={uri} year={year} prefix={loc_id_prefix}")
            df = select_rows(parquet_path, exact_filters=exact_filters or None, starts_with_filters=starts_with_filters or None)
            logger.info(f"[S3] load_source_data({source_id}): candidate={parquet_path.name} rows={len(df)}")
            last_df = df
            if not df.empty:
                return df, metadata
        df = last_df
    else:
        # Local mode: glob for parquet files on disk
        parquet_files = list(source_dir.glob("*.parquet"))
        if not parquet_files:
            raise ValueError(f"No parquet file found for {source_id} in {source_dir}")

        parquet_path = None
        for candidate in parquet_candidates:
            if candidate.exists():
                parquet_path = candidate
                break
        if parquet_path is None:
            parquet_path = parquet_files[0]

        df = select_rows(parquet_path, exact_filters=exact_filters or None, starts_with_filters=starts_with_filters or None)
        if df.empty and not exact_filters and not starts_with_filters:
            df = pd.read_parquet(parquet_path)

    return df, metadata


def load_event_data(source_id: str, event_file_key: str = "events") -> tuple:
    """
    Load event-level parquet (e.g., events.parquet, fires.parquet) for a source.

    Args:
        source_id: e.g., "usgs_earthquakes", "mtbs_wildfires"
        event_file_key: Key from metadata.files (e.g., "events", "fires", "positions")

    Returns:
        tuple: (DataFrame, metadata dict)
    """
    source_dir = _get_source_path(source_id)

    metadata = load_source_metadata(source_id)
    if metadata is None:
        raise ValueError(f"Could not load metadata for {source_id}")

    # Get filename from metadata.files
    files_section = metadata.get("files")
    files_info = files_section if isinstance(files_section, dict) else {}
    file_info = files_info.get(event_file_key)
    if not isinstance(file_info, dict):
        file_info = None

    if not file_info:
        # Try common event file names as fallback
        fallback_names = [
            f"{event_file_key}.parquet",
            "events.parquet",
            "fires.parquet",
            "positions.parquet",
            "storms.parquet",
        ]
        for name in fallback_names:
            candidate = source_dir / name
            if is_cloud_mode() or candidate.exists():
                df = select_rows(candidate)
                if df.empty and not is_cloud_mode():
                    df = pd.read_parquet(candidate)
                return df, metadata
        if not is_cloud_mode():
            # Last-resort fallback: use any parquet in source dir (local mode only)
            parquet_candidates = sorted(source_dir.glob("*.parquet"))
            for candidate in parquet_candidates:
                if candidate.name in ("all_countries.parquet", "all_regions.parquet"):
                    continue
                df = select_rows(candidate)
                if df.empty:
                    df = pd.read_parquet(candidate)
                return df, metadata
        raise ValueError(f"No event file '{event_file_key}' found in {source_id}")

    # Get filename - handle both 'name' and 'filename' keys
    filename = file_info.get("name") or file_info.get("filename")
    if not filename:
        raise ValueError(f"No filename specified for '{event_file_key}' in {source_id}")

    parquet_path = source_dir / filename
    if not is_cloud_mode() and not parquet_path.exists():
        raise ValueError(f"Event file not found: {parquet_path}")

    df = select_rows(parquet_path)
    if df.empty:
        df = pd.read_parquet(parquet_path)
    return df, metadata


def _resolve_event_parquet_path(source_id: str, event_file_key: str = "events") -> tuple[Path, dict]:
    """Resolve event parquet path from source metadata without loading the full dataframe.
    Uses load_source_metadata so it works in both local and cloud mode."""
    source_dir = _get_source_path(source_id)
    metadata = load_source_metadata(source_id)
    if metadata is None:
        raise ValueError(f"Could not load metadata for {source_id}")

    files_section = metadata.get("files")
    files_info = files_section if isinstance(files_section, dict) else {}
    file_info = files_info.get(event_file_key)
    if not isinstance(file_info, dict):
        file_info = None

    if not file_info:
        fallback_names = [
            f"{event_file_key}.parquet",
            "events.parquet",
            "fires.parquet",
            "positions.parquet",
            "storms.parquet",
        ]
        for name in fallback_names:
            candidate = source_dir / name
            if is_cloud_mode() or candidate.exists():
                return candidate, metadata
        if not is_cloud_mode():
            parquet_candidates = sorted(source_dir.glob("*.parquet"))
            for candidate in parquet_candidates:
                if candidate.name in ("all_countries.parquet", "all_regions.parquet"):
                    continue
                return candidate, metadata
        raise ValueError(f"No event file '{event_file_key}' found in {source_dir}")

    filename = file_info.get("name") or file_info.get("filename")
    if not filename:
        raise ValueError(f"No filename specified for '{event_file_key}' in {source_dir}")

    parquet_path = source_dir / filename
    if not is_cloud_mode() and not parquet_path.exists():
        raise ValueError(f"Event file not found: {parquet_path}")
    return parquet_path, metadata


def _duckdb_can_query_events(source_id: str) -> bool:
    return can_query_event_source(source_id)


def _load_event_data_duckdb(source_id: str, item: dict, event_file_key: str = "events") -> tuple[pd.DataFrame, dict]:
    """
    Load and filter event data with DuckDB for first-pass migration sources.

    This keeps the response-building contract unchanged while moving the heavy
    parquet scan/filter work into DuckDB.
    """
    parquet_path, metadata = _resolve_event_parquet_path(source_id, event_file_key)

    available_cols = parquet_columns(parquet_path)

    region = item.get("region")
    year, year_start, year_end = _normalize_year_filters(item)
    filters = item.get("filters", {}) or {}
    requested_limit = item.get("limit")
    sort_spec = _normalize_sort_spec(item.get("sort"))
    time_col = "year" if "year" in available_cols else ("timestamp" if "timestamp" in available_cols else None)
    loc_id_col = "loc_id" if "loc_id" in available_cols else None

    where_clauses = []
    params = [path_to_uri(parquet_path)]

    if year_start is not None and year_end is not None:
        if time_col == "year":
            where_clauses.append('"year" BETWEEN ? AND ?')
            params.extend([year_start, year_end])
        elif time_col:
            where_clauses.append(f"year({quote_ident(time_col)}) BETWEEN ? AND ?")
            params.extend([year_start, year_end])
    elif year is not None:
        if time_col == "year":
            where_clauses.append('"year" = ?')
            params.append(year)
        elif time_col:
            where_clauses.append(f"year({quote_ident(time_col)}) = ?")
            params.append(year)

    region_codes = expand_region(region)
    if region_codes:
        us_state_prefixes = sorted(c for c in region_codes if c.startswith("USA-"))
        country_codes = sorted(c for c in region_codes if not c.startswith("USA-"))
        region_parts = []

        if loc_id_col:
            for prefix in us_state_prefixes:
                region_parts.append(f"{quote_ident(loc_id_col)} LIKE ?")
                params.append(f"{prefix}%")

            if country_codes:
                placeholders = ", ".join("?" for _ in country_codes)
                region_parts.append(f"split_part({quote_ident(loc_id_col)}, '-', 1) IN ({placeholders})")
                params.extend(country_codes)

        # Some event sources use loc_id as an event identifier instead of a hierarchical
        # geography code. Fall back to country/name fields so regional filtering still works.
        country_name_cols = [col for col in ("country", "country_name") if col in available_cols]
        if country_codes and country_name_cols:
            iso3_to_name = _load_iso_codes().get("iso3_to_name", {})
            country_names = sorted(
                {
                    str(iso3_to_name.get(code, "")).strip().upper()
                    for code in country_codes
                    if str(iso3_to_name.get(code, "")).strip()
                }
            )
            for col in country_name_cols:
                if country_names:
                    placeholders = ", ".join("?" for _ in country_names)
                    region_parts.append(f"upper({quote_ident(col)}) IN ({placeholders})")
                    params.extend(country_names)

        state_abbrevs = _load_usa_admin().get("state_abbreviations", {})
        state_name_cols = [col for col in ("state", "state_name", "admin1_name") if col in available_cols]
        state_text_cols = [col for col in ("place", "location", "name", "title") if col in available_cols]
        for prefix in us_state_prefixes:
            state_abbrev = prefix.split("-")[1]
            state_name = str(state_abbrevs.get(state_abbrev, "")).strip().upper()
            if state_name:
                for col in state_name_cols:
                    region_parts.append(f"upper({quote_ident(col)}) = ?")
                    params.append(state_name)
                for col in state_text_cols:
                    region_parts.append(f"upper({quote_ident(col)}) LIKE ?")
                    params.append(f"%{state_name}%")

        if region_parts:
            where_clauses.append("(" + " OR ".join(region_parts) + ")")

    for field, value in filters.items():
        _append_duckdb_filter_clause(where_clauses, params, available_cols, field, value)

    sql = "SELECT * FROM read_parquet(?)"
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)

    limit = min(requested_limit or DEFAULT_EVENT_LIMIT, MAX_EVENT_LIMIT)
    sort_col = None
    sort_order = "DESC"
    if sort_spec:
        requested_sort_col = str(sort_spec.get("by") or "").strip()
        if requested_sort_col in available_cols:
            sort_col = requested_sort_col
            sort_order = "ASC" if str(sort_spec.get("order", "desc")).lower() == "asc" else "DESC"
        elif requested_sort_col in {"date", "time"} and "timestamp" in available_cols:
            sort_col = "timestamp"
            sort_order = "ASC" if str(sort_spec.get("order", "desc")).lower() == "asc" else "DESC"
    if not sort_col:
        sig_col = metadata.get("significance_column")
        if sig_col and sig_col in available_cols:
            sort_col = sig_col
            sort_order = "DESC"
    if sort_col:
        sql += f" ORDER BY {quote_ident(sort_col)} {sort_order} NULLS LAST"
    sql += " LIMIT ?"
    params.append(limit)

    df = run_df(sql, params)
    return df, metadata


def expand_region(region: str) -> set:
    """
    Expand a region name to a set of country codes (ISO3).

    Supports:
    - Region aliases (e.g., "europe" -> WHO_European_Region countries)
    - Direct grouping names (e.g., "European_Union")
    - Single country names (returns that country code)
    - "global" or null -> empty set (means no filtering)

    Returns:
        set: Country codes (ISO3), or empty set for global/all
    """
    if not region or region.lower() in ("global", "all", "world"):
        return set()

    county_loc_id = _resolve_us_county_slug_loc_id(region)
    if county_loc_id:
        return {county_loc_id}

    normalized_region = str(region).strip().lower().replace("_", " ").replace("-", " ")
    if normalized_region in _US_REGIONAL_GROUPS:
        return set(_US_REGIONAL_GROUPS[normalized_region])
    if normalized_region in {"puerto rico", "puerto rico usa"}:
        return {"USA-PR"}

    # If it's already a loc_id format (e.g., USA-FL, USA-CA-037), return as-is
    if "-" in region and region.split("-")[0].isupper() and len(region.split("-")[0]) == 3:
        return {region}

    conversions = _load_conversions()
    region_lower = region.lower()
    region_normalized = region_lower.replace("_", " ").replace("-", " ")

    # Check region_aliases first (maps friendly names to grouping keys)
    region_aliases = conversions.get("region_aliases", {})
    for alias, grouping_key in region_aliases.items():
        alias_lower = alias.lower()
        if alias_lower == region_lower or alias_lower.replace("_", " ").replace("-", " ") == region_normalized:
            grouping = conversions.get("regional_groupings", {}).get(grouping_key, {})
            return set(grouping.get("countries", []))

    # Check direct grouping names
    regional_groupings = conversions.get("regional_groupings", {})
    for key, grouping in regional_groupings.items():
        key_lower = key.lower()
        if key_lower == region_lower or key_lower.replace("_", " ").replace("-", " ") == region_normalized:
            return set(grouping.get("countries", []))

    # Check if it's a country name -> return its ISO3 code
    iso_data = _load_iso_codes()
    iso3_to_name = iso_data.get("iso3_to_name", {})
    for code, name in iso3_to_name.items():
        if name.lower() == region_lower:
            return {code}

    # Check if it's already an ISO3 code
    if region.upper() in iso3_to_name:
        return {region.upper()}

    # Check US state abbreviations for state-level queries
    usa_admin = _load_usa_admin()
    state_abbrevs = usa_admin.get("state_abbreviations", {})
    for abbrev, name in state_abbrevs.items():
        if name.lower() == region_lower or abbrev.lower() == region_lower:
            # Return special marker for US state filtering
            return {f"USA-{abbrev}"}

    return set()


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


def _detect_event_type(source_id: str) -> str:
    return detect_event_type_impl(
        source_id,
        get_source_from_catalog_func=_get_source_from_catalog,
        load_source_metadata_func=load_source_metadata,
        resolve_event_source_id_func=_resolve_event_source_id,
    )


def _get_significance_column(source_id: str) -> str:
    return get_significance_column_impl(
        source_id,
        get_source_from_catalog_func=_get_source_from_catalog,
    )


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


def _get_coordinate_columns(df: pd.DataFrame) -> tuple:
    return get_coordinate_columns_impl(df)


def _get_time_column(df: pd.DataFrame) -> str:
    return get_time_column_impl(df)


def _get_id_column(df: pd.DataFrame, event_type: str) -> str:
    return get_id_column_impl(df, event_type)


def _order_item_original_query(item: dict | None) -> str:
    if not isinstance(item, dict):
        return ""
    hints = item.get("_hints") if isinstance(item.get("_hints"), dict) else {}
    return str(hints.get("original_query") or item.get("summary") or "").strip()


def _build_empty_wildfire_perimeter_response(order: dict, item: dict, source_id: str) -> dict | None:
    return build_empty_wildfire_perimeter_response_impl(
        order,
        item,
        source_id,
        get_source_from_catalog_func=_get_source_from_catalog,
    )


def execute_event_order(order: dict) -> dict:
    return execute_event_order_impl(
        order,
        normalize_year_filters_func=_normalize_year_filters,
        normalize_sort_spec_func=_normalize_sort_spec,
        resolve_event_source_id_func=_resolve_event_source_id,
        duckdb_can_query_events_func=_duckdb_can_query_events,
        load_event_data_duckdb_func=_load_event_data_duckdb,
        load_event_data_func=load_event_data,
        detect_event_type_func=_detect_event_type,
        resolve_event_parquet_path_func=_resolve_event_parquet_path,
        select_peak_positions_by_storm_ids_func=select_peak_positions_by_storm_ids,
        get_coordinate_columns_func=_get_coordinate_columns,
        get_time_column_func=_get_time_column,
        get_id_column_func=_get_id_column,
        expand_region_func=expand_region,
        get_significance_column_func=_get_significance_column,
        build_empty_wildfire_perimeter_response_func=_build_empty_wildfire_perimeter_response,
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
    """
    Check if order has mixed add/remove items and execute accordingly.

    Checks for:
    1. Explicit item.action = "remove" on some items
    2. Session cache: regions already loaded should be removed, new regions added

    If mixed, splits into two operations and returns combined results.
    Returns None if not a mixed order (let normal flow handle it).
    """
    logger = logging.getLogger(__name__)
    from .session_cache import session_manager

    session_id = order.get("session_id")
    cache = session_manager.get(session_id) if session_id else None

    # Check for explicit item-level actions (works for all data types: geometry, metrics, events)
    add_items = []
    remove_items = []

    for item in items:
        item_action = item.get("action", "add")
        if item_action == "remove":
            remove_items.append(item)
        else:
            add_items.append(item)

    # If we have explicit removes, handle the split
    if remove_items:
        logger.info(f"Mixed order detected: {len(add_items)} adds, {len(remove_items)} removes")
        return _execute_split_order(order, add_items, remove_items, source_id)

    # No explicit removes - check cache to see if any regions already exist
    # (user says "show california" when texas is loaded = remove texas, add california)
    # This is optional behavior - for now, just return None and let normal accumulation happen
    return None


def _execute_split_order(order: dict, add_items: list, remove_items: list, source_id: str) -> dict:
    """
    Execute a split order with both adds and removes.

    Executes removals first, then adds, returns combined response.
    """
    logger = logging.getLogger(__name__)
    results = []

    # Execute removals first
    if remove_items:
        remove_order = {
            **order,
            "action": "remove",
            "items": remove_items,
            "summary": f"Removing {len(remove_items)} region(s)"
        }
        remove_result = _execute_removal_order(remove_order, remove_items, source_id)
        results.append(remove_result)
        logger.info(f"Split order: removed {remove_result.get('count', 0)} items")

    # Execute adds second
    add_result = None
    if add_items:
        add_order = {
            **order,
            "action": "add",
            "items": add_items,
        }
        # Call execute_order recursively for adds (but it won't recurse again since no removes)
        add_result = execute_order(add_order)
        results.append(add_result)
        logger.info(f"Split order: added {add_result.get('count', 0)} items")

    # Return combined response
    if len(results) == 1:
        return results[0]

    # Combine results for mixed response
    return {
        "type": "mixed_order",
        "results": results,
        "summary": order.get("summary", f"Processed {len(add_items)} adds and {len(remove_items)} removes"),
        "add_count": add_result.get("count", 0) if add_result else 0,
        "remove_count": results[0].get("count", 0) if remove_items else 0
    }


def _classify_execution_family(item: dict) -> str:
    """
    Classify an item into the renderer family it needs at execution time.

    This stays generic:
    - geometry overlays render through the geometry pipeline
    - event items render through the event pipeline
    - everything else renders through the metrics/choropleth pipeline
    """
    source_id = item.get("source_id")
    source_info = _get_source_from_catalog(source_id) if source_id else {}
    data_type = (source_info or {}).get("data_type", "metrics")
    geo_level = str((source_info or {}).get("geographic_level") or "").strip().lower()

    if item.get("overlay_type") or (geo_level in SPECIAL_GEOMETRY_LEVELS and _has_geometry_data_type(data_type)):
        return "geometry"

    if item.get("mode") == "aggregate":
        return "metrics"

    supports_events = False
    if isinstance(data_type, list):
        supports_events = "events" in data_type
    else:
        supports_events = data_type == "events"

    if item.get("mode") == "events" or supports_events:
        return "events"

    return "metrics"


def _execute_multi_layer_order_if_needed(order: dict, items: list) -> dict | None:
    """
    Execute multi-item orders as layered results.

    The shared map-facing contract is one payload containing independent layers.
    Preserve one layer per order item so:
    - metrics + events can coexist
    - two metrics sources can coexist without collapsing into one choropleth
    - multiple geometry overlays can coexist
    """
    if len(items) <= 1:
        return None

    results = []
    for item in items:
        family = _classify_execution_family(item)
        sub_order = {**order, "items": [item]}
        if family == "geometry":
            result = execute_geometry_order(sub_order)
        else:
            result = execute_order(sub_order)
        if isinstance(result, dict):
            result.setdefault("layer_source_id", item.get("source_id"))
            result.setdefault("layer_family", family)
        results.append(result)

    return {
        "type": "mixed_order",
        "results": results,
        "summary": order.get("summary", f"Rendered {len(results)} map layers"),
        "layer_count": len(results),
    }


def _check_sparse_year(
    df,
    metric_col: str,
    selected_year: int,
    metadata: dict | None,
) -> dict | None:
    """Return a clarify dict when selected_year has suspiciously sparse coverage.

    Uses density * countries from metric metadata as the expected-per-year baseline.
    Only fires when year was not explicitly requested by the user (null-year path).
    Returns None when coverage looks normal or the metric is inherently sparse.
    """
    metrics = (metadata or {}).get("metrics", {})
    metric_info = metrics.get(metric_col) if isinstance(metrics, dict) else None
    if not isinstance(metric_info, dict):
        return None

    density = float(metric_info.get("density") or 0)
    countries = int(metric_info.get("countries") or 0)
    expected_per_year = density * countries

    # Skip inherently sparse metrics - if the average expectation is < 5 per year,
    # sparsity is normal for this metric and we should not second-guess it.
    if expected_per_year < 5:
        return None

    actual_count = int((df[metric_col].notna() & (df["year"] == selected_year)).sum())

    # Not sparse - coverage is at least 25% of what's expected.
    if actual_count >= expected_per_year * 0.25:
        return None

    # Find the best alternative: most recent year with meaningful coverage.
    year_counts = (
        df[df[metric_col].notna()]
        .groupby("year")[metric_col]
        .count()
        .sort_index()
    )
    if year_counts.empty:
        return None

    best_count = int(year_counts.max())
    # Suggested year: most recent year with >= 50% of best coverage.
    good_years = year_counts[year_counts >= max(int(best_count * 0.5), int(expected_per_year * 0.25))]
    if good_years.empty:
        return None

    suggested_year = int(good_years.index.max())
    suggested_count = int(year_counts[suggested_year])

    # Do not clarify if the suggested year is the same as the selected year.
    if suggested_year == selected_year:
        return None

    metric_name = metric_info.get("name") or metric_col
    noun = "country" if actual_count == 1 else "countries"
    msg = (
        f"{selected_year} only has data for {actual_count} {noun} "
        f"for \"{metric_name}\". "
        f"{suggested_year} has much better coverage ({suggested_count} countries). "
        f"Would you like to use {suggested_year} instead, or specify a different year?"
    )
    return {
        "type": "clarify",
        "message": msg,
        "geojson": {"type": "FeatureCollection", "features": []},
        "count": 0,
    }


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
        check_sparse_year_func=_check_sparse_year,
        expand_region_func=expand_region,
        canonicalize_loc_id_func=canonicalize_loc_id,
        translate_loc_id_to_geometry_id_func=translate_loc_id_to_geometry_id,
        translate_geometry_id_to_local_id_func=translate_geometry_id_to_local_id,
        apply_dataframe_filters_func=_apply_dataframe_filters,
        get_coordinate_columns_func=_get_coordinate_columns,
        available_years_for_range_func=available_years_for_range,
        metadata_metric_year_range_func=metadata_metric_year_range,
        apply_derived_fields_func=apply_derived_fields,
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
        build_event_retry_order_func=_build_event_retry_order,
        execute_order_func=execute_order,
        load_catalog_func=_load_catalog,
    )
