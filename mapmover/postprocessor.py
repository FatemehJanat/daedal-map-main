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
from typing import Optional

from .data_loading import load_catalog, load_source_metadata, get_pack_metadata
from .runtime.postprocess_pipeline import (
    apply_preprocessor_time_hints,
    build_validation_summary,
    inject_original_query_hints,
    run_pre_validation_pipeline,
    split_derived_specs,
    validate_regular_items,
)
from .runtime.clarify_primitives import build_clarify_result
from .runtime.clarify_routing_primitives import (
    build_multiple_paths_clarify as build_multiple_paths_clarify_impl,
    build_pack_load_clarify as build_pack_load_clarify_impl,
    detect_full_pack_load_clarify as detect_full_pack_load_clarify_impl,
    detect_multiple_path_clarify as detect_multiple_path_clarify_impl,
    expand_full_pack_loads as expand_full_pack_loads_impl,
)
from .runtime.aggregate_primitives import (
    apply_aggregate_query_hints as apply_aggregate_query_hints_impl,
    get_disaster_aggregate_metric_columns as get_disaster_aggregate_metric_columns_impl,
    resolve_aggregate_admin2_dir as resolve_aggregate_admin2_dir_impl,
    source_geojson_shape as source_geojson_shape_impl,
    source_has_aggregate_files as source_has_aggregate_files_impl,
    source_has_metrics as source_has_metrics_impl,
    source_is_location_shape as source_is_location_shape_impl,
    source_supports_aggregate_mode as source_supports_aggregate_mode_impl,
)
from .runtime.query_intent_primitives import (
    query_explicit_view_mode as query_explicit_view_mode_impl,
    query_has_time_window as query_has_time_window_impl,
    query_prefers_event_source as query_prefers_event_source_impl,
    query_requests_event_window as query_requests_event_window_impl,
    query_requests_recent_events as query_requests_recent_events_impl,
    query_requests_single_latest_event as query_requests_single_latest_event_impl,
    query_signals_event_vs_aggregate as query_signals_event_vs_aggregate_impl,
    semantic_query_text as semantic_query_text_impl,
)
from .runtime.retry_primitives import (
    reroute_item_to_event_sibling as reroute_item_to_event_sibling_impl,
)
from .runtime.order_semantics import (
    detect_event_mode as detect_event_mode_impl,
    normalize_aggregate_metric_mode as normalize_aggregate_metric_mode_impl,
    resolve_pack_source as resolve_pack_source_impl,
    resolve_pack_source_by_shape,
    resolve_pack_source_for_metric,
)
from .runtime.postprocess_validation import validate_item as validate_item_impl
from .runtime.postprocess_contracts import (
    build_processed_order_result,
    format_validation_messages,
    get_display_items,
)
from .runtime.postprocess_source_helpers import (
    catalog_sources as catalog_sources_impl,
    get_catalog_source as get_catalog_source_impl,
    get_item_source_metadata as get_item_source_metadata_impl,
    is_full_pack_load as is_full_pack_load_impl,
    source_has_aggregate_files as source_has_aggregate_files_helper,
    source_requires_metric as source_requires_metric_impl,
    source_supports_aggregate_mode as source_supports_aggregate_mode_helper,
    source_supports_events as source_supports_events_impl,
)
from .runtime.disaster_semantic_filters import (
    apply_disaster_semantic_filters as apply_disaster_semantic_filters_impl,
    item_disaster_key as item_disaster_key_impl,
    query_semantic_filter_tokens as query_semantic_filter_tokens_impl,
)
from .runtime.population_resolution import (
    find_population_metric_key as find_population_metric_key_impl,
    get_source_admin_levels as get_source_admin_levels_impl,
    resolve_population_dependency as resolve_population_dependency_impl,
    scope_matches_population_region as scope_matches_population_region_impl,
)
from .runtime.warning_primitives import build_metric_warning, METRIC_DISPLAY_WARN
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


def _load_disaster_overlay_reference() -> dict:
    data = load_reference_json("disasters.json")
    overlays = data.get("overlays", {}) if isinstance(data, dict) else {}
    return overlays if isinstance(overlays, dict) else {}


def _item_disaster_key(item: dict, catalog_source: dict | None) -> str | None:
    return item_disaster_key_impl(
        item,
        catalog_source,
        overlays=_load_disaster_overlay_reference(),
        load_source_metadata_func=load_source_metadata,
    )


def _query_semantic_filter_tokens(query: str, disaster_key: str | None) -> list[tuple[str, dict]]:
    return query_semantic_filter_tokens_impl(
        query,
        disaster_key,
        overlays=_load_disaster_overlay_reference(),
    )


def _apply_disaster_semantic_filters(item: dict, catalog_source: dict | None, query: str) -> None:
    return apply_disaster_semantic_filters_impl(
        item,
        catalog_source,
        query,
        overlays=_load_disaster_overlay_reference(),
        item_disaster_key_func=_item_disaster_key,
        query_semantic_filter_tokens_func=_query_semantic_filter_tokens,
    )

def _metric_display_name(source_id: str, metric_key: str) -> str:
    metadata = load_source_metadata(source_id) or {}
    metric_info = (metadata.get("metrics") or {}).get(metric_key, {})
    return metric_info.get("name", metric_key) if isinstance(metric_info, dict) else metric_key


def _catalog_sources(catalog: dict) -> list[dict]:
    return catalog_sources_impl(catalog)


def _get_catalog_source(catalog: dict, source_id: str | None) -> dict | None:
    return get_catalog_source_impl(catalog, source_id)


def _get_catalog_pack(catalog: dict, pack_id: str | None) -> dict | None:
    if not pack_id:
        return None
    return get_pack_metadata(pack_id, catalog)


def _resolve_pack_source(catalog: dict, pack_id: str | None, region: str | None, item: dict | None = None) -> str | None:
    return resolve_pack_source_impl(catalog, pack_id, region, item)


def _is_full_pack_load(item: dict) -> bool:
    return is_full_pack_load_impl(item)


def _source_supports_events(source: dict | None) -> bool:
    return source_supports_events_impl(source)


def expand_full_pack_loads(items: list, catalog: dict) -> list:
    return expand_full_pack_loads_impl(
        items,
        catalog,
        is_full_pack_load_func=_is_full_pack_load,
        catalog_sources_func=_catalog_sources,
        get_catalog_pack_func=_get_catalog_pack,
        source_supports_events_func=_source_supports_events,
        source_has_metrics_func=source_has_metrics_impl,
    )


def _source_has_aggregate_files(catalog_source: dict | None) -> bool:
    return source_has_aggregate_files_helper(
        catalog_source,
        source_has_aggregate_files_func=source_has_aggregate_files_impl,
        data_root=DATA_ROOT,
    )


def _source_supports_aggregate_mode(catalog_source: dict | None) -> bool:
    return source_supports_aggregate_mode_helper(
        catalog_source,
        source_supports_aggregate_mode_func=source_supports_aggregate_mode_impl,
        source_has_aggregate_files_func=_source_has_aggregate_files,
    )


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
    if not source_is_location_shape_impl(catalog_source):
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
    return source_requires_metric_impl(
        item,
        catalog_source,
        source_is_location_shape_func=_source_is_location_shape,
        source_has_metrics_func=source_has_metrics_impl,
    )


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


def _get_disaster_aggregate_metric_columns(catalog_source: dict | None) -> set[str]:
    return get_disaster_aggregate_metric_columns_impl(
        catalog_source,
        data_root=DATA_ROOT,
        parquet_columns_func=parquet_columns,
    )


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
    return get_item_source_metadata_impl(
        item,
        catalog,
        resolve_pack_source_func=_resolve_pack_source,
        load_source_metadata_func=load_source_metadata,
    )


def _get_source_admin_levels(metadata: dict | None) -> list[int]:
    return get_source_admin_levels_impl(metadata)


def _scope_matches_population_region(metadata: dict | None, region: str | None) -> bool:
    return scope_matches_population_region_impl(metadata, region)


def _find_population_metric_key(source_id: str) -> str | None:
    return find_population_metric_key_impl(
        source_id,
        load_source_metadata_func=load_source_metadata,
        population_family=POPULATION_FAMILY,
    )


def _resolve_population_dependency(
    *,
    region: str | None,
    preferred_source_id: str | None,
    target_level: int | None,
) -> tuple[str | None, str]:
    return resolve_population_dependency_impl(
        region=region,
        preferred_source_id=preferred_source_id,
        target_level=target_level,
        cache_dict=_POPULATION_RESOLUTION_CACHE,
        population_family=POPULATION_FAMILY,
        find_population_metric_key_func=_find_population_metric_key,
        load_source_metadata_func=load_source_metadata,
        get_source_admin_levels_func=_get_source_admin_levels,
        scope_matches_population_region_func=_scope_matches_population_region,
        load_catalog_func=load_catalog,
    )

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
        source_has_metrics_func=source_has_metrics_impl,
        source_supports_aggregate_mode_func=_source_supports_aggregate_mode,
        apply_aggregate_query_hints_func=apply_aggregate_query_hints_impl,
        source_supports_events_func=_source_supports_events,
        query_prefers_event_source_func=query_prefers_event_source_impl,
        reroute_item_to_event_sibling_func=reroute_item_to_event_sibling_impl,
        resolve_pack_source_by_shape_func=resolve_pack_source_by_shape,
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

    clarify_message = detect_multiple_path_clarify_impl(
        items,
        catalog,
        hints=hints,
        query_explicit_view_mode_func=query_explicit_view_mode_impl,
        get_item_source_metadata_func=_get_item_source_metadata,
        build_multiple_paths_clarify_func=build_multiple_paths_clarify_impl,
    )
    if clarify_message:
        return build_clarify_result(order, items, clarify_message)

    full_pack_clarify = detect_full_pack_load_clarify_impl(
        items,
        catalog,
        is_full_pack_load_func=_is_full_pack_load,
        get_catalog_pack_func=_get_catalog_pack,
        build_pack_load_clarify_func=build_pack_load_clarify_impl,
    )
    if full_pack_clarify:
        return build_clarify_result(order, items, full_pack_clarify)

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

    return build_processed_order_result(
        order,
        validated_items=validated_items,
        derived_specs=derived_specs,
        validation_summary=summary,
        all_valid=len(errors) == 0,
        summary=_rewrite_processed_order_summary(order, validated_items),
        metric_warning=metric_warning,
    )
