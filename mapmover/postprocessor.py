"""
Postprocessor - validates orders and expands derived fields.

Runs AFTER the LLM call and:
1. Validates each order item against catalog
2. Expands derived field shortcuts (per_capita, density, etc.)
3. Expands cross-source derived fields
4. Returns processed order with validation results

The postprocessor ensures:
- All items reference valid sources and metrics
- Derived fields are expanded into component items + calculation spec
- Items marked for_derivation are hidden from user display
"""

import json
import re
from pathlib import Path
from typing import Optional

from .data_loading import load_catalog, load_source_metadata, get_pack_metadata
from .explore.postprocess_pipeline import (
    apply_preprocessor_time_hints,
    build_validation_summary,
    inject_original_query_hints,
    run_pre_validation_pipeline,
    split_derived_specs,
    validate_regular_items,
)
from .explore.postprocess_validation import validate_item as validate_item_impl
from .explore.postprocess_warnings import build_clarify_result, build_metric_warning
from .runtime.order_semantics import (
    detect_event_mode as detect_event_mode_impl,
    normalize_aggregate_metric_mode as normalize_aggregate_metric_mode_impl,
    resolve_pack_source_by_shape,
    resolve_pack_source_for_metric,
)
from .source_time_contract import metadata_metric_year_range
from .duckdb_helpers import parquet_columns
from .paths import DATA_ROOT
from .foundation_helpers import load_reference_json


# =============================================================================
# Derived Field Expansion Tables
# =============================================================================

# Shortcut expansions for common derived fields
DERIVED_EXPANSIONS = {
    "per_capita": {
        "denominator": "population",
        "label_suffix": "Per Capita",
    },
    "density": {
        "denominator": "area_sq_km",
        "denominator_source": "world_factbook_static",  # Static area data
        "label_suffix": "Density",
    },
    "per_1000": {
        "denominator": "population",
        "multiplier": 1000,
        "label_suffix": "Per 1000",
    },
}

POPULATION_FAMILY = "population"
_POPULATION_RESOLUTION_CACHE = {}

EVENT_DISPLAY_PATTERNS = [
    "show me", "show the", "display", "map of", "map the",
    "where are", "where were", "where did", "where have",
    "which", "what", "list", "find",
    "struck", "hit", "affected", "impacted",
    "occurred", "happened",
    "significant", "major", "severe", "largest", "strongest", "deadliest",
    "magnitude", "category", "m4", "m5", "m6", "m7",
    "cat 1", "cat 2", "cat 3", "cat 4", "cat 5",
    "individual", "events", "event", "tracks", "track", "points",
]

AGGREGATE_PATTERNS = [
    "how many", "how much", "count", "total", "number of",
    "statistics", "stats", "average", "sum",
    "per year", "annually", "yearly", "annual", "over time",
    "trend", "compare", "frequency", "exposure",
    "per capita", "historically",
    "rolling", "between the 1990s", "between the 2010s",
    "aggregate", "aggregated",
]

EXPLICIT_EVENT_VIEW_PATTERNS = [
    "individual", "individual events", "events", "event",
    "tracks", "track", "track points", "points",
    "occurred", "happened", "struck", "hit",
    "significant", "major", "severe", "largest", "strongest", "deadliest",
    "magnitude", "category", "m4", "m5", "m6", "m7",
    "cat 1", "cat 2", "cat 3", "cat 4", "cat 5",
]

EXPLICIT_AGGREGATE_VIEW_PATTERNS = [
    "aggregate", "aggregated", "annual", "annually", "yearly", "per year",
    "count", "counts", "frequency", "trend", "compare", "rolling",
]

RECENT_EVENT_PATTERNS = [
    "most recent",
    "latest",
    "newest",
    "recent",
]

EVENT_STYLE_ADJECTIVES = (
    "significant",
    "major",
    "severe",
    "largest",
    "strongest",
    "deadliest",
)

AGGREGATE_ONLY_PATTERNS = (
    "how many",
    "count",
    "counts",
    "number of",
    "total",
    "average",
    "avg",
    "mean",
    "sum",
    "frequency",
    "trend",
    "compare",
    "ranking",
    "rank",
    "highest",
    "lowest",
    "most affected",
    "per year",
    "rolling",
    "exposure",
    "share",
    "rate",
)


def _semantic_query_text(query: str) -> str:
    text = str(query or "").strip()
    if not text:
        return ""
    marker = " qa mode:"
    lower = text.lower()
    idx = lower.find(marker)
    if idx >= 0:
        text = text[:idx]
    return text.strip().lower()


def _query_requests_recent_events(query: str) -> bool:
    query_lower = _semantic_query_text(query)
    if not query_lower:
        return False
    return any(pattern in query_lower for pattern in RECENT_EVENT_PATTERNS)


def _query_requests_single_latest_event(query: str) -> bool:
    query_lower = _semantic_query_text(query)
    if not query_lower:
        return False
    if not any(pattern in query_lower for pattern in ("most recent", "latest", "newest")):
        return False
    return not any(pattern in query_lower for pattern in ("top ", "show me 10", "show 10", "ten most recent"))


def _load_disaster_overlay_reference() -> dict:
    data = load_reference_json("disasters.json")
    overlays = data.get("overlays", {}) if isinstance(data, dict) else {}
    return overlays if isinstance(overlays, dict) else {}


def _item_disaster_key(item: dict, catalog_source: dict | None) -> str | None:
    overlays = _load_disaster_overlay_reference()
    metadata = load_source_metadata(item.get("source_id")) or {}
    for candidate in (
        metadata.get("event_type"),
        (catalog_source or {}).get("event_type"),
        item.get("pack_id"),
    ):
        text = str(candidate or "").strip().lower()
        if not text:
            continue
        if text in overlays:
            return text
        plural = f"{text}s"
        if plural in overlays:
            return plural
    return None


def _query_has_time_window(query: str) -> bool:
    query_lower = _semantic_query_text(query)
    if not query_lower:
        return False
    if re.search(r"\b(?:since|from|between|during|in)\s+\d{4}\b", query_lower):
        return True
    return any(
        token in query_lower
        for token in (
            "last 10 years",
            "last 20 years",
            "last 30 years",
            "past 10 years",
            "past 20 years",
            "past 30 years",
            "this year",
            "last year",
        )
    )


def _query_requests_event_window(query: str) -> bool:
    query_lower = _semantic_query_text(query)
    if not query_lower:
        return False
    has_event_subject = any(pattern in query_lower for pattern in EVENT_DISPLAY_PATTERNS)
    has_time_window = _query_has_time_window(query_lower)
    has_aggregate_only = any(pattern in query_lower for pattern in AGGREGATE_ONLY_PATTERNS)
    return has_event_subject and has_time_window and not has_aggregate_only


def _query_prefers_event_source(query: str) -> bool:
    query_lower = _semantic_query_text(query)
    if not query_lower:
        return False
    explicit_events, explicit_aggregate = _query_explicit_view_mode(query_lower)
    if explicit_events and not explicit_aggregate:
        return True
    if _query_requests_event_window(query_lower):
        return True
    has_event_adjective = any(re.search(rf"\b{re.escape(token)}\b", query_lower) for token in EVENT_STYLE_ADJECTIVES)
    has_aggregate_only = any(pattern in query_lower for pattern in AGGREGATE_ONLY_PATTERNS)
    return has_event_adjective and not has_aggregate_only


def _query_semantic_filter_tokens(query: str, disaster_key: str | None) -> list[tuple[str, dict]]:
    if not disaster_key:
        return []
    overlays = _load_disaster_overlay_reference()
    overlay = overlays.get(disaster_key) or {}
    semantic_filters = overlay.get("semantic_filters") or {}
    if not isinstance(semantic_filters, dict):
        return []
    query_lower = str(query or "").strip().lower()
    matched = []
    for token, spec in semantic_filters.items():
        if not isinstance(spec, dict):
            continue
        if re.search(rf"\b{re.escape(str(token).lower())}\b", query_lower):
            matched.append((str(token), spec))
    return matched


def _apply_disaster_semantic_filters(item: dict, catalog_source: dict | None, query: str) -> None:
    disaster_key = _item_disaster_key(item, catalog_source)
    matched = _query_semantic_filter_tokens(query, disaster_key)
    if not matched:
        return

    filters = item.get("filters")
    if not isinstance(filters, dict):
        filters = {}

    for _, spec in matched:
        field = str(spec.get("field") or "").strip()
        if not field or field in filters:
            continue
        if "min" in spec:
            filters[field] = {"min": spec.get("min")}
        elif "max" in spec:
            filters[field] = {"max": spec.get("max")}

    if filters:
        item["filters"] = filters


def _reroute_item_to_event_sibling(item: dict, catalog: dict) -> bool:
    pack_id = item.get("pack_id")
    if not pack_id:
        return False
    event_source_id = resolve_pack_source_by_shape(catalog, pack_id, item.get("region"), "event_shape")
    if not event_source_id:
        return False
    item["source_id"] = event_source_id
    item["_resolved_from_pack"] = True
    item["mode"] = "events"
    item["event_file"] = "events"
    for field in (
        "aggregate_use_rolling",
        "aggregate_window_years",
        "aggregate_rollup_level",
        "aggregate_all_years",
    ):
        item.pop(field, None)
    return True


def _metric_display_name(source_id: str, metric_key: str) -> str:
    metadata = load_source_metadata(source_id) or {}
    metric_info = (metadata.get("metrics") or {}).get(metric_key, {})
    return metric_info.get("name", metric_key) if isinstance(metric_info, dict) else metric_key


def _catalog_sources(catalog: dict) -> list[dict]:
    sources = catalog.get("sources", [])
    return sources if isinstance(sources, list) else []


def _get_catalog_source(catalog: dict, source_id: str | None) -> dict | None:
    if not source_id:
        return None
    for source in _catalog_sources(catalog):
        if source.get("source_id") == source_id:
            return source
    return None


def _get_catalog_pack(catalog: dict, pack_id: str | None) -> dict | None:
    if not pack_id:
        return None
    return get_pack_metadata(pack_id, catalog)


def _scope_matches_region(scope: str, region: str | None) -> bool:
    if not region:
        return scope == "global"
    value = str(region).lower()
    if scope == "CAN":
        return value.startswith("can") or value.startswith("canada")
    if scope == "USA":
        return value.startswith("usa") or value.startswith("us-")
    if scope == "global":
        return True
    return value.startswith(scope.lower())


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


def _resolve_pack_source(catalog: dict, pack_id: str | None, region: str | None, item: dict | None = None) -> str | None:
    if not pack_id:
        return None

    pack_sources = [s for s in _catalog_sources(catalog) if s.get("pack_id") == pack_id]
    if not pack_sources:
        return None

    if _item_prefers_geometry_pack_source(item or {"pack_id": pack_id, "region": region}):
        geometry_sources = [s for s in pack_sources if s.get("geojson_shape") == "geometry_shape"]
        exact_geometry = [
            s for s in geometry_sources
            if s.get("scope") != "global" and _scope_matches_region(s.get("scope", "global"), region)
        ]
        if len(exact_geometry) == 1:
            return exact_geometry[0].get("source_id")
        global_geometry = [s for s in geometry_sources if s.get("scope") == "global"]
        if len(global_geometry) == 1:
            return global_geometry[0].get("source_id")

    exact_matches = [
        s for s in pack_sources
        if s.get("scope") != "global" and _scope_matches_region(s.get("scope", "global"), region)
    ]
    if len(exact_matches) == 1:
        return exact_matches[0].get("source_id")
    if len(exact_matches) > 1:
        return None

    global_matches = [s for s in pack_sources if s.get("scope") == "global"]
    if len(global_matches) == 1:
        return global_matches[0].get("source_id")
    if len(pack_sources) == 1:
        return pack_sources[0].get("source_id")
    return None


def _is_full_pack_load(item: dict) -> bool:
    load_scope = str(item.get("load_scope") or "").strip().lower()
    return bool(item.get("pack_id")) and (
        load_scope in {"pack", "all_sources", "full_pack"}
        or item.get("all_sources") is True
    )


def _source_supports_events(source: dict | None) -> bool:
    data_type = (source or {}).get("data_type")
    if isinstance(data_type, list):
        return "events" in data_type
    return data_type == "events"


def _build_pack_load_clarify(item: dict, pack: dict) -> str:
    load_policy = pack.get("load_policy") or {}
    pack_name = pack.get("pack_name") or pack.get("pack_id") or "this pack"
    source_count = pack.get("source_count", 0)
    size_mb = pack.get("file_size_mb_total", 0)
    row_count = pack.get("row_count_total", 0)
    reason = load_policy.get("reason") or "it is too large to load safely in one step"
    return (
        f"{pack_name} is too large to load all at once right now. "
        f"It has {source_count} sources, about {size_mb} MB, and {row_count:,} rows. "
        f"{reason}. Please narrow it to a source, geography level, metric, or time range."
    )


def detect_full_pack_load_clarify(items: list, catalog: dict) -> str | None:
    for item in items:
        if not _is_full_pack_load(item):
            continue
        pack = _get_catalog_pack(catalog, item.get("pack_id"))
        if not pack:
            return f"Pack '{item.get('pack_id')}' was not found."
        if not (pack.get("load_policy") or {}).get("can_load_all_sources"):
            return _build_pack_load_clarify(item, pack)
    return None


def expand_full_pack_loads(items: list, catalog: dict) -> list:
    expanded = []
    source_lookup = {
        src.get("source_id"): src
        for src in _catalog_sources(catalog)
        if src.get("source_id")
    }

    for item in items:
        if not _is_full_pack_load(item):
            expanded.append(item)
            continue

        pack = _get_catalog_pack(catalog, item.get("pack_id"))
        if not pack:
            expanded.append(item)
            continue

        for source_id in pack.get("source_ids", []):
            source = source_lookup.get(source_id) or {}
            new_item = {k: v for k, v in item.items() if k not in {"load_scope", "all_sources"}}
            new_item["source_id"] = source_id
            new_item["_expanded_from_pack"] = item.get("pack_id")
            if _source_supports_events(source):
                new_item.setdefault("mode", "events")
                new_item.pop("metric", None)
            elif not new_item.get("metric") and _source_has_metrics(source):
                new_item["metric"] = "*"
            elif not _source_has_metrics(source):
                new_item.pop("metric", None)
            expanded.append(new_item)

    return expanded


def _source_has_metrics(catalog_source: dict | None) -> bool:
    metrics = (catalog_source or {}).get("metrics") or {}
    if isinstance(metrics, dict) and metrics:
        return True
    if isinstance(metrics, list) and metrics:
        return True
    metric_count = (catalog_source or {}).get("metric_count")
    try:
        if int(metric_count or 0) > 0:
            return True
    except Exception:
        pass
    return False


def _source_has_aggregate_files(catalog_source: dict | None) -> bool:
    files = (catalog_source or {}).get("files") or {}
    if not isinstance(files, dict):
        files = {}
    if any(key in files for key in ("yearly", "rolling_10y", "rolling_20y")):
        return True

    source_path = (catalog_source or {}).get("path")
    if not source_path:
        return False
    aggregate_dir = _resolve_aggregate_admin2_dir(str(DATA_ROOT / source_path))
    candidates = (
        aggregate_dir / "yearly.parquet",
        aggregate_dir / "rolling_10y.parquet",
        aggregate_dir / "rolling_20y.parquet",
    )
    return any(path.exists() for path in candidates)


def _source_geojson_shape(catalog_source: dict | None) -> str:
    return str((catalog_source or {}).get("geojson_shape") or "").strip().lower()


def _source_is_location_shape(catalog_source: dict | None) -> bool:
    return _source_geojson_shape(catalog_source) == "location_shape"


def _source_supports_aggregate_mode(catalog_source: dict | None) -> bool:
    if _source_is_location_shape(catalog_source):
        return False
    data_type = (catalog_source or {}).get("data_type")
    if isinstance(data_type, list):
        if "events" in data_type and "metrics" not in data_type:
            return False
    elif data_type == "events":
        return False
    return _source_has_aggregate_files(catalog_source)


def _apply_aggregate_query_hints(item: dict, query: str) -> None:
    item["mode"] = "aggregate"
    item.pop("event_file", None)

    if item.get("aggregate_use_rolling") is None and ("rolling" in query or "last 10 years" in query or "past 10 years" in query):
        item["aggregate_use_rolling"] = True
        item["aggregate_window_years"] = 10
    elif item.get("aggregate_use_rolling") is None and ("last 20 years" in query or "past 20 years" in query):
        item["aggregate_use_rolling"] = True
        item["aggregate_window_years"] = 20
    elif item.get("aggregate_use_rolling") is None and ("last 30 years" in query or "past 30 years" in query):
        item["aggregate_use_rolling"] = True
        item["aggregate_window_years"] = 30

    if "historically" in query:
        item["aggregate_all_years"] = True

    if "countries" in query or "country" in query:
        item["aggregate_rollup_level"] = "admin_0"
    elif "counties" in query or "county" in query:
        item["aggregate_rollup_level"] = "admin_2"
    elif not item.get("region") and not item.get("aggregate_rollup_level"):
        geo_terms = (
            "county", "counties", "state", "states", "province", "provinces",
            "district", "districts", "tract", "tracts", "admin_1", "admin_2", "admin_3",
        )
        if not any(term in query for term in geo_terms):
            item["aggregate_rollup_level"] = "admin_0"


def _normalize_item_filters(item: dict, catalog_source: dict | None) -> None:
    filterable_fields = (catalog_source or {}).get("filterable_fields") or []
    if not filterable_fields:
        source_id = item.get("source_id")
        metadata = load_source_metadata(source_id) if source_id else {}
        filterable_fields = metadata.get("filterable_fields") or []
    if not isinstance(filterable_fields, list) or not filterable_fields:
        return

    filters = item.get("filters")
    if not isinstance(filters, dict):
        filters = {}

    reserved = {
        "type", "source_id", "pack_id", "metric", "metric_label", "region", "year", "year_start", "year_end",
        "mode", "event_file", "filters", "sort", "limit", "summary", "all_sources", "load_scope",
        "aggregate_use_rolling", "aggregate_window_years", "aggregate_rollup_level", "aggregate_all_years",
    }

    moved = False
    for field_name in filterable_fields:
        if field_name == "loc_id":
            continue
        if field_name in item and field_name not in reserved and field_name not in filters:
            filters[field_name] = item.pop(field_name)
            moved = True

    if moved or filters:
        item["filters"] = filters


def _normalize_location_shape_metric(item: dict, catalog_source: dict | None) -> None:
    if not _source_is_location_shape(catalog_source):
        return
    metric = str(item.get("metric") or "").strip().lower()
    if metric in {"", "*", "all", "all_metrics", "latitude", "longitude", "lat", "lon", "lng"}:
        item.pop("metric", None)


def _expand_filter_value_aliases(item: dict, metadata: dict | None) -> None:
    filters = item.get("filters")
    if not isinstance(filters, dict) or not filters:
        return
    routing_hints = metadata.get("routing_hints", {}) if isinstance(metadata, dict) else {}
    filter_aliases = routing_hints.get("filter_value_aliases") or {}
    if not isinstance(filter_aliases, dict):
        return

    for field, alias_map in filter_aliases.items():
        if field not in filters or not isinstance(alias_map, dict):
            continue
        raw_value = filters.get(field)
        values = raw_value if isinstance(raw_value, (list, tuple, set)) else [raw_value]
        expanded: list = []
        changed = False
        for value in values:
            if value is None:
                continue
            alias_key = str(value).strip().lower()
            mapped = alias_map.get(alias_key)
            if isinstance(mapped, list):
                expanded.extend(mapped)
                changed = True
            elif mapped is not None:
                expanded.append(mapped)
                changed = True
            else:
                expanded.append(value)
        if changed:
            deduped = []
            seen = set()
            for value in expanded:
                marker = json.dumps(value, sort_keys=True, default=str)
                if marker in seen:
                    continue
                seen.add(marker)
                deduped.append(value)
            filters[field] = deduped
    item["filters"] = filters


def _source_requires_metric(item: dict, catalog_source: dict | None) -> bool:
    if item.get("type") in {"derived", "derived_result"}:
        return False
    if item.get("mode") == "events":
        return False
    if _source_is_location_shape(catalog_source):
        return False
    if not _source_has_metrics(catalog_source):
        return False

    data_type = (catalog_source or {}).get("data_type", "metrics")
    if isinstance(data_type, list):
        if "events" in data_type and item.get("mode") != "aggregate":
            return False
        return "metrics" in data_type
    return data_type == "metrics"


def _format_metric_label(metric_key: str) -> str:
    return str(metric_key or "").replace("_", " ").strip().title()


def _clamp_item_years_to_metric(item: dict, metadata: dict | None, metric_key: str | None) -> None:
    metric_min_year, metric_max_year = metadata_metric_year_range(metadata, metric_key)
    if metric_min_year is None or metric_max_year is None:
        return

    changed = False

    year = item.get("year")
    if isinstance(year, int):
        clamped_year = min(max(year, metric_min_year), metric_max_year)
        if clamped_year != year:
            item["year"] = clamped_year
            changed = True

    year_start = item.get("year_start")
    year_end = item.get("year_end")
    if isinstance(year_start, int) and isinstance(year_end, int):
        clamped_start = max(year_start, metric_min_year)
        clamped_end = min(year_end, metric_max_year)
        if clamped_start > clamped_end:
            clamped_start = metric_min_year
            clamped_end = metric_max_year
        if clamped_start != year_start:
            item["year_start"] = clamped_start
            changed = True
        if clamped_end != year_end:
            item["year_end"] = clamped_end
            changed = True

    item["_metric_year_range"] = {"min": metric_min_year, "max": metric_max_year}
    if changed:
        item["_time_range_clamped"] = True


def _rewrite_processed_order_summary(order: dict, validated_items: list[dict]) -> str | None:
    if not validated_items:
        return order.get("summary")
    if not any(item.get("_time_range_clamped") for item in validated_items):
        return order.get("summary")
    if len(validated_items) != 1:
        return order.get("summary")

    item = validated_items[0]
    if not item.get("_valid"):
        return order.get("summary")

    metric_label = str(item.get("metric_label") or item.get("metric") or item.get("source_id") or "Result").strip()
    source_id = str(item.get("source_id") or "").strip()
    metadata = load_source_metadata(source_id) or {}
    source_name = str(metadata.get("source_name") or source_id).strip()
    region = str(item.get("region") or "").strip()
    year = item.get("year")
    year_start = item.get("year_start")
    year_end = item.get("year_end")

    if isinstance(year, int):
        time_text = f"in {year}"
    elif isinstance(year_start, int) and isinstance(year_end, int):
        time_text = f"in {year_start}" if year_start == year_end else f"from {year_start} to {year_end}"
    else:
        metric_range = item.get("_metric_year_range") or {}
        metric_min_year = metric_range.get("min")
        metric_max_year = metric_range.get("max")
        if isinstance(metric_min_year, int) and isinstance(metric_max_year, int):
            time_text = f"in {metric_min_year}" if metric_min_year == metric_max_year else f"from {metric_min_year} to {metric_max_year}"
        else:
            return order.get("summary")

    if region and region.lower() != "global":
        return f"{metric_label} for {region} {time_text} under {source_name}"
    return f"{metric_label} {time_text} under {source_name}"


def _resolve_aggregate_admin2_dir(source_path: str) -> Path:
    """
    Resolve the admin2 aggregate folder for either a parent hazard source path
    or a dedicated aggregate source path rooted at `.../aggregates/admin2`.
    """
    source_dir = DATA_ROOT / source_path
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


def _get_disaster_aggregate_metric_columns(catalog_source: dict | None) -> set[str]:
    source_path = str((catalog_source or {}).get("path") or "").strip()
    if not source_path:
        return set()

    aggregate_dir = _resolve_aggregate_admin2_dir(source_path)
    candidates = [
        aggregate_dir / "yearly.parquet",
        aggregate_dir / "rolling_10y.parquet",
        aggregate_dir / "rolling_20y.parquet",
    ]
    excluded = {"loc_id", "year", "window_end_year", "window_start_year", "window_years", "source"}
    metric_cols: set[str] = set()

    for candidate in candidates:
        try:
            if not candidate.exists():
                continue
            cols = parquet_columns(candidate)
            metric_cols.update(str(col) for col in cols if str(col) not in excluded)
        except Exception:
            continue

    return metric_cols


def _normalize_source_declared_scope(item: dict) -> dict:
    """
    Apply source-contained scope normalization when metadata declares it.

    This keeps runtime generic: source-specific canonical regions and accepted
    aliases live in metadata/reference, not in hardcoded runtime branches.
    """
    source_id = item.get("source_id")
    if not source_id:
        return item

    metadata = load_source_metadata(source_id) or {}
    coverage = metadata.get("geographic_coverage", {}) or {}
    canonical_region = str(
        coverage.get("canonical_region")
        or metadata.get("canonical_region")
        or ""
    ).strip().lower()
    if not canonical_region:
        return item

    aliases_raw = (
        coverage.get("region_aliases")
        or metadata.get("region_aliases")
        or []
    )
    aliases = {
        str(alias).strip().lower()
        for alias in aliases_raw
        if str(alias).strip()
    }

    region = str(item.get("region") or "").strip().lower()
    if not region or region == canonical_region or region in aliases:
        item["region"] = canonical_region
    return item


def _get_item_source_metadata(item: dict, catalog: dict) -> dict:
    """Load source metadata for an item, resolving pack_id when needed."""
    source_id = item.get("source_id")
    if not source_id and item.get("pack_id"):
        source_id = _resolve_pack_source(catalog, item.get("pack_id"), item.get("region"))
    if not source_id:
        return {}
    return load_source_metadata(source_id) or {}


def _query_signals_event_vs_aggregate(query: str) -> tuple[bool, bool]:
    """Return coarse event-vs-aggregate intent signals from the raw query."""
    query_lower = str(query or "").strip().lower()
    if not query_lower:
        return False, False
    wants_events = any(pattern in query_lower for pattern in EVENT_DISPLAY_PATTERNS)
    wants_aggregate = any(pattern in query_lower for pattern in AGGREGATE_PATTERNS)
    if _query_requests_event_window(query_lower):
        wants_events = True
        wants_aggregate = False
    return wants_events, wants_aggregate


def _query_explicit_view_mode(query: str) -> tuple[bool, bool]:
    """Return whether the query explicitly asks for event-view or aggregate-view semantics."""
    query_lower = str(query or "").strip().lower()
    if not query_lower:
        return False, False
    explicit_events = any(pattern in query_lower for pattern in EXPLICIT_EVENT_VIEW_PATTERNS)
    explicit_aggregate = any(pattern in query_lower for pattern in EXPLICIT_AGGREGATE_VIEW_PATTERNS)
    return explicit_events, explicit_aggregate


def _build_multiple_paths_clarify(item: dict, metadata: dict) -> str:
    """Build a grounded clarify message for metadata-declared multi-path ambiguity."""
    routing_hints = metadata.get("routing_hints") or {}
    summary = str(routing_hints.get("clarify_multiple_paths_summary") or "").strip()
    dimensions = routing_hints.get("clarify_path_dimensions") or []
    options = []

    if "view_mode" in dimensions:
        options = [str(v).strip() for v in (routing_hints.get("view_mode_options") or []) if str(v).strip()]

    source_name = metadata.get("source_name") or item.get("source_id") or item.get("pack_id") or "this source"
    if not summary:
        if options:
            summary = f"{source_name} supports multiple valid views for this request."
        else:
            summary = f"{source_name} supports multiple valid paths for this request."

    if options:
        options_text = " or ".join(options)
        return f"{summary} Would you like {options_text}?"
    return f"{summary} Which path would you like?"


def detect_multiple_path_clarify(items: list, catalog: dict, hints: dict | None = None) -> str | None:
    """Return a clarify message when metadata declares an ambiguous multi-path request."""
    query = (hints or {}).get("original_query", "")
    explicit_events, explicit_aggregate = _query_explicit_view_mode(query)

    for item in items:
        metadata = _get_item_source_metadata(item, catalog)
        routing_hints = metadata.get("routing_hints") or {}
        if not routing_hints.get("clarify_on_multiple_paths"):
            continue

        dimensions = routing_hints.get("clarify_path_dimensions") or []
        if "view_mode" not in dimensions:
            continue

        # Clarify when the query explicitly points both ways, or when it
        # leaves the path ambiguous and metadata says both are valid.
        if explicit_events == explicit_aggregate:
            return _build_multiple_paths_clarify(item, metadata)

    return None


def _get_source_admin_levels(metadata: dict | None) -> list[int]:
    if not metadata:
        return []

    coverage = metadata.get("geographic_coverage", {}) or {}
    admin_levels = coverage.get("admin_levels")
    if isinstance(admin_levels, list):
        return sorted(
            {
                int(level)
                for level in admin_levels
                if isinstance(level, (int, float)) or str(level).isdigit()
            }
        )

    geo_level = metadata.get("geographic_level")
    if isinstance(geo_level, list):
        values = []
        for level in geo_level:
            text = str(level or "")
            if text.startswith("admin_") and text[6:].isdigit():
                values.append(int(text[6:]))
        return sorted(set(values))
    if isinstance(geo_level, str) and geo_level.startswith("admin_") and geo_level[6:].isdigit():
        return [int(geo_level[6:])]
    if geo_level in {"country", "admin_0"}:
        return [0]
    return []


def _scope_matches_population_region(metadata: dict | None, region: str | None) -> bool:
    if not metadata:
        return False
    coverage = metadata.get("geographic_coverage", {}) or {}
    coverage_type = str(coverage.get("type") or "global").lower()
    if not region:
        return coverage_type == "global"

    region_upper = str(region).strip().upper()
    country = region_upper.split("-")[0] if region_upper else ""

    if coverage_type == "global":
        return True
    if coverage_type == "country":
        return str(coverage.get("country") or "").upper() == country
    if coverage_type == "regional":
        missing = {
            str(code).upper()
            for code in coverage.get("common_missing", []) or []
        }
        common_count = coverage.get("common_count")
        if common_count:
            return country not in missing
        return False
    return False


def _find_population_metric_key(source_id: str) -> str | None:
    metadata = load_source_metadata(source_id) or {}
    metrics = metadata.get("metrics", {}) or {}
    preferred = (
        (((metadata.get("selection_priority") or {}).get(POPULATION_FAMILY) or {}).get("metric"))
        or ""
    )
    if preferred and preferred in metrics:
        return preferred
    for candidate in ("population", "total_pop"):
        if candidate in metrics:
            return candidate
    return None


def _resolve_population_dependency(
    *,
    region: str | None,
    preferred_source_id: str | None,
    target_level: int | None,
) -> tuple[str | None, str]:
    cache_key = (region or "", preferred_source_id or "", target_level)
    cached = _POPULATION_RESOLUTION_CACHE.get(cache_key)
    if cached:
        return cached

    if preferred_source_id:
        preferred_metric = _find_population_metric_key(preferred_source_id)
        preferred_metadata = load_source_metadata(preferred_source_id) or {}
        preferred_levels = _get_source_admin_levels(preferred_metadata)
        if preferred_metric and (
            target_level is None
            or not preferred_levels
            or target_level in preferred_levels
        ):
            resolved = (preferred_source_id, preferred_metric)
            _POPULATION_RESOLUTION_CACHE[cache_key] = resolved
            return resolved

    candidates = []
    catalog = load_catalog()
    for source in catalog.get("sources", []):
        source_id = source.get("source_id")
        if not source_id:
            continue
        metadata = load_source_metadata(source_id) or {}
        priority = ((metadata.get("selection_priority") or {}).get(POPULATION_FAMILY) or {})
        metric_key = priority.get("metric")
        if not metric_key:
            continue
        if metric_key not in (metadata.get("metrics") or {}):
            continue
        if not _scope_matches_population_region(metadata, region):
            continue

        admin_levels = _get_source_admin_levels(metadata)
        if target_level is not None and admin_levels and target_level not in admin_levels:
            continue

        candidates.append(
            (
                int(priority.get("priority_rank", 9999)),
                source_id,
                metric_key,
            )
        )

    candidates.sort(key=lambda item: (item[0], item[1]))
    resolved = (candidates[0][1], candidates[0][2]) if candidates else (None, "population")
    _POPULATION_RESOLUTION_CACHE[cache_key] = resolved
    return resolved

# =============================================================================
# Validation
# =============================================================================

def validate_item(item: dict, catalog: dict) -> dict:
    return validate_item_impl(
        item,
        catalog,
        validate_item_func=validate_item,
        resolve_pack_source_func=_resolve_pack_source,
        get_catalog_pack_func=_get_catalog_pack,
        catalog_sources_func=_catalog_sources,
        get_catalog_source_func=_get_catalog_source,
        normalize_item_filters_func=_normalize_item_filters,
        normalize_location_shape_metric_func=_normalize_location_shape_metric,
        apply_disaster_semantic_filters_func=_apply_disaster_semantic_filters,
        source_has_metrics_func=_source_has_metrics,
        source_supports_aggregate_mode_func=_source_supports_aggregate_mode,
        apply_aggregate_query_hints_func=_apply_aggregate_query_hints,
        source_supports_events_func=_source_supports_events,
        query_prefers_event_source_func=_query_prefers_event_source,
        reroute_item_to_event_sibling_func=_reroute_item_to_event_sibling,
        load_source_metadata_func=load_source_metadata,
        expand_filter_value_aliases_func=_expand_filter_value_aliases,
        source_requires_metric_func=_source_requires_metric,
        get_disaster_aggregate_metric_columns_func=_get_disaster_aggregate_metric_columns,
        format_metric_label_func=_format_metric_label,
        resolve_pack_source_for_metric_func=resolve_pack_source_for_metric,
        clamp_item_years_to_metric_func=_clamp_item_years_to_metric,
    )


# =============================================================================
# Wildcard Metric Expansion
# =============================================================================

def expand_wildcard_metrics(items: list) -> list:
    """
    Expand wildcard metrics (metric: "*" or metric: "all") into individual items.

    When LLM outputs {"source_id": "abs_population", "metric": "*", "region": "australia"},
    this expands it into one item per actual metric in that source's metadata.

    This allows the LLM to express "all metrics from this source" without needing
    to know every metric name, keeping the prompt small while enabling full access.
    """
    expanded = []
    catalog = load_catalog()

    for item in items:
        # Skip event mode items - they don't use metrics, "*" means "all events"
        if item.get("mode") == "events":
            expanded.append(item)
            continue

        metric = item.get("metric")

        # Check for wildcard
        if metric in ("*", "all", "all_metrics"):
            source_id = item.get("source_id")
            if not source_id and item.get("pack_id"):
                resolved_source = _resolve_pack_source(catalog, item.get("pack_id"), item.get("region"), item)
                if resolved_source:
                    item["source_id"] = resolved_source
                    item["_resolved_from_pack"] = True
                    source_id = resolved_source
            if not source_id:
                # Can't expand without knowing the source
                expanded.append(item)
                continue

            # Load full metadata for this source
            metadata = load_source_metadata(source_id)
            if not metadata or not metadata.get("metrics"):
                # No metadata found, keep original item (will fail validation)
                expanded.append(item)
                continue

            # Create one item per metric, using per-metric year ranges from metadata
            metrics = metadata.get("metrics", {})
            for metric_key, metric_info in metrics.items():
                new_item = {
                    "source_id": source_id,
                    "metric": metric_key,
                    "region": item.get("region"),
                }

                # Use per-metric year range if available in metadata
                # metadata.metrics.{metric}.years = [start, end]
                metric_min_year, metric_max_year = metadata_metric_year_range(metadata, metric_key)
                if metric_min_year is not None and metric_max_year is not None:
                    new_item["year_start"] = metric_min_year
                    new_item["year_end"] = metric_max_year
                else:
                    # Fallback to item-level years if no per-metric range
                    if item.get("year"):
                        new_item["year"] = item.get("year")
                    if item.get("year_start"):
                        new_item["year_start"] = item.get("year_start")
                    if item.get("year_end"):
                        new_item["year_end"] = item.get("year_end")

                # Remove None values
                new_item = {k: v for k, v in new_item.items() if v is not None}
                expanded.append(new_item)

            # Log expansion for debugging
            import logging
            logging.getLogger(__name__).info(
                f"Expanded wildcard metric for {source_id}: {len(metrics)} metrics"
            )
        else:
            # Not a wildcard, keep as-is
            expanded.append(item)

    return expanded


# =============================================================================
# Derived Field Expansion
# =============================================================================

def expand_derived_shortcut(item: dict) -> list:
    """
    Expand a derived shortcut (e.g., derived: "per_capita") into component items.

    Input: {"source_id": "owid_co2", "metric": "gdp", "region": "EU", "derived": "per_capita"}

    Output: [
        {"source_id": "owid_co2", "metric": "gdp", "region": "EU", "for_derivation": True},
        {"source_id": "eurostat", "metric": "population", "region": "EU", "for_derivation": True},
        {"type": "derived_result", "numerator": "gdp", "denominator": "population", "label": "GDP Per Capita"}
    ]
    """
    derived_type = item.get("derived")
    if not derived_type or derived_type not in DERIVED_EXPANSIONS:
        return [item]  # Return unchanged if not a known shortcut

    expansion = DERIVED_EXPANSIONS[derived_type]
    source_id = item.get("source_id")
    metric = item.get("metric")
    region = item.get("region")
    year = item.get("year")
    year_start = item.get("year_start")
    year_end = item.get("year_end")

    # Build base item properties
    base_props = {"region": region}
    if year:
        base_props["year"] = year
    if year_start:
        base_props["year_start"] = year_start
    if year_end:
        base_props["year_end"] = year_end

    expanded = []

    source_metadata = load_source_metadata(source_id) or {}
    source_admin_levels = _get_source_admin_levels(source_metadata)
    target_level = max(source_admin_levels) if source_admin_levels else None
    numerator_candidates = [metric]
    numerator_display = _metric_display_name(source_id, metric) if source_id and metric else None
    if numerator_display and numerator_display not in numerator_candidates:
        numerator_candidates.append(numerator_display)

    # 1. Numerator item (the original metric)
    numerator_item = {
        "source_id": source_id,
        "metric": metric,
        "for_derivation": True,
        **base_props
    }
    expanded.append(numerator_item)

    # 2. Denominator item (from canonical source)
    denom_metric = expansion["denominator"]
    denom_source = expansion.get("denominator_source", source_id)
    if denom_metric == POPULATION_FAMILY:
        resolved_source, resolved_metric = _resolve_population_dependency(
            region=region,
            preferred_source_id=source_id,
            target_level=target_level,
        )
        if resolved_source:
            denom_source = resolved_source
            denom_metric = resolved_metric
    denominator_item = {
        "source_id": denom_source,
        "metric": denom_metric,
        "for_derivation": True,
        **base_props
    }
    expanded.append(denominator_item)

    # 3. Derived result specification
    label = f"{metric} {expansion['label_suffix']}"
    denominator_candidates = [denom_metric]
    denom_display = _metric_display_name(denom_source, denom_metric) if denom_source and denom_metric else None
    if denom_display and denom_display not in denominator_candidates:
        denominator_candidates.append(denom_display)
    derived_result = {
        "type": "derived_result",
        "numerator": metric,
        "denominator": denom_metric,
        "numerator_candidates": numerator_candidates,
        "denominator_candidates": denominator_candidates,
        "label": label,
    }
    if expansion.get("multiplier"):
        derived_result["multiplier"] = expansion["multiplier"]
    expanded.append(derived_result)

    return expanded


def expand_cross_source_derived(item: dict) -> list:
    """
    Expand a cross-source derived field into component items.

    Input: {
        "type": "derived",
        "numerator": {"source_id": "owid_co2", "metric": "gdp"},
        "denominator": {"source_id": "imf_bop", "metric": "exports"},
        "region": "EU"
    }

    Output: [
        {"source_id": "owid_co2", "metric": "gdp", "region": "EU", "for_derivation": True},
        {"source_id": "imf_bop", "metric": "exports", "region": "EU", "for_derivation": True},
        {"type": "derived_result", "numerator": "gdp", "denominator": "exports", "label": "GDP/Exports"}
    ]
    """
    if item.get("type") != "derived":
        return [item]

    numerator = item.get("numerator", {})
    denominator = item.get("denominator", {})
    region = item.get("region")
    year = item.get("year")
    year_start = item.get("year_start")
    year_end = item.get("year_end")

    # Handle simple string numerator/denominator (same source assumed)
    if isinstance(numerator, str):
        numerator = {"metric": numerator}
    if isinstance(denominator, str):
        denominator = {"metric": denominator}

    # Build base item properties
    base_props = {"region": region}
    if year:
        base_props["year"] = year
    if year_start:
        base_props["year_start"] = year_start
    if year_end:
        base_props["year_end"] = year_end

    expanded = []

    # 1. Numerator item
    num_source = numerator.get("source_id", item.get("source_id"))
    num_metric = numerator.get("metric")
    if num_source and num_metric:
        expanded.append({
            "source_id": num_source,
            "metric": num_metric,
            "for_derivation": True,
            **base_props
        })

    # 2. Denominator item
    denom_source = denominator.get("source_id", item.get("source_id"))
    denom_metric = denominator.get("metric")
    if denom_source and denom_metric:
        expanded.append({
            "source_id": denom_source,
            "metric": denom_metric,
            "for_derivation": True,
            **base_props
        })

    # 3. Derived result
    label = item.get("label", f"{num_metric}/{denom_metric}")
    derived_result = {
        "type": "derived_result",
        "numerator": num_metric,
        "denominator": denom_metric,
        "label": label,
    }
    if item.get("multiplier"):
        derived_result["multiplier"] = item["multiplier"]
    expanded.append(derived_result)

    return expanded


def expand_all_derived_fields(items: list) -> list:
    """
    Expand all derived fields in an items list.

    Handles both:
    - Shortcut syntax: {"derived": "per_capita"}
    - Cross-source syntax: {"type": "derived", "numerator": {...}, "denominator": {...}}
    """
    expanded = []

    for item in items:
        # Check for shortcut syntax first
        if item.get("derived") and item.get("derived") in DERIVED_EXPANSIONS:
            expanded.extend(expand_derived_shortcut(item))

        # Check for cross-source syntax
        elif item.get("type") == "derived":
            expanded.extend(expand_cross_source_derived(item))

        # Regular item - keep as is
        else:
            expanded.append(item)

    return expanded


# =============================================================================
# Main Postprocessor
# =============================================================================

def postprocess_order(order: dict, hints: dict = None) -> dict:
    """
    Main postprocessor function.

    Takes an order from the LLM and:
    1. Injects time range from preprocessor hints
    2. Expands derived fields
    3. Validates all items
    4. Returns processed order with validation results

    Args:
        order: The order dict from LLM (with "items" list)
        hints: Preprocessor hints (for context if needed)

    Returns:
        Processed order with:
        - items: list of validated items (may be expanded)
        - derived_specs: list of derived calculation specs
        - validation_summary: str describing validation results
    """
    catalog = load_catalog()
    items = order.get("items", [])
    original_query = str((hints or {}).get("original_query") or "").strip()

    inject_original_query_hints(items, original_query)

    time_hints = hints.get("time", {}) if hints else {}
    apply_preprocessor_time_hints(items, time_hints, load_source_metadata)

    clarify_message = detect_multiple_path_clarify(items, catalog, hints)
    if clarify_message:
        return build_clarify_result(order, items, clarify_message)

    full_pack_clarify = detect_full_pack_load_clarify(items, catalog)
    if full_pack_clarify:
        return build_clarify_result(order, items, full_pack_clarify)

    METRIC_DISPLAY_WARN = 15
    expanded_items, metric_count = run_pre_validation_pipeline(
        items,
        hints,
        catalog,
        detect_event_mode_impl,
        normalize_aggregate_metric_mode_impl,
        expand_full_pack_loads,
        expand_wildcard_metrics,
        expand_all_derived_fields,
    )
    regular_items, derived_specs = split_derived_specs(expanded_items)
    validated_items, errors, valid_count = validate_regular_items(
        regular_items,
        catalog,
        _normalize_source_declared_scope,
        validate_item,
    )
    summary = build_validation_summary(validated_items, errors, valid_count)

    metric_warning = build_metric_warning(metric_count, METRIC_DISPLAY_WARN)

    # Return processed order
    result = {
        "items": validated_items,
        "derived_specs": derived_specs,
        "validation_summary": summary,
        "all_valid": len(errors) == 0,
        # Preserve original order fields
        "summary": _rewrite_processed_order_summary(order, validated_items),
        "region": order.get("region"),
        "year": order.get("year"),
        "year_start": order.get("year_start"),
        "year_end": order.get("year_end"),
    }
    if metric_warning:
        result["metric_warning"] = metric_warning
    return result


def get_display_items(items: list, derived_specs: list = None) -> list:
    """
    Get items for display in the order panel.

    Filters out items with for_derivation=True.
    Adds display representations for derived specs.
    """
    display = []

    # Add non-derivation regular items
    for item in items:
        if not item.get("for_derivation"):
            display.append(item)

    # Add display items for derived specs
    if derived_specs:
        for spec in derived_specs:
            display.append({
                "type": "derived",
                "metric": spec.get("label", "Derived"),
                "metric_label": f"{spec.get('label', 'Derived')} (calculated)",
                "_valid": True,
                "_is_derived": True,
            })

    return display


def format_validation_messages(order: dict) -> list:
    """
    Format validation results as chat messages.

    Returns list of strings for display to user.
    """
    messages = []
    items = order.get("items", [])

    for item in items:
        if item.get("for_derivation"):
            continue  # Don't show derivation source items

        if item.get("_valid"):
            source = item.get("source_id", "?")
            metric = item.get("metric_label") or item.get("metric", "?")
            messages.append(f"+ {metric}: Found in {source}")
        else:
            metric = item.get("metric", "?")
            error = item.get("_error", "Unknown error")
            messages.append(f"- {metric}: {error}")

    # Add derived field info
    derived = order.get("derived_specs", [])
    for spec in derived:
        label = spec.get("label", "Derived")
        messages.append(f"+ {label} (calculated)")

    return messages
