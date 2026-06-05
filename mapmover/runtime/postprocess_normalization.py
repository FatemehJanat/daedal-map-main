"""Shared postprocess normalization helpers."""

from __future__ import annotations

import json


def normalize_item_filters(
    item: dict,
    catalog_source: dict | None,
    *,
    load_source_metadata_func,
) -> None:
    filterable_fields = (catalog_source or {}).get("filterable_fields") or []
    if not filterable_fields:
        source_id = item.get("source_id")
        metadata = load_source_metadata_func(source_id) if source_id else {}
        filterable_fields = (metadata or {}).get("filterable_fields") or []
    if not isinstance(filterable_fields, list) or not filterable_fields:
        return

    filters = item.get("filters")
    if not isinstance(filters, dict):
        filters = {}

    reserved = {
        "type", "source_id", "pack_id", "metric", "metric_label", "region", "year", "year_start", "year_end",
        "date_start", "date_end", "time_granularity", "aggregation", "aggregation_axis", "missing_policy", "weight_metric", "week_anchor",
        "geo_level", "mode", "event_file", "filters", "sort", "limit", "summary", "all_sources", "load_scope",
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


def normalize_location_shape_metric(
    item: dict,
    catalog_source: dict | None,
    *,
    source_is_location_shape_func,
) -> None:
    if not source_is_location_shape_func(catalog_source):
        return
    metric = str(item.get("metric") or "").strip().lower()
    if metric in {"", "*", "all", "all_metrics", "latitude", "longitude", "lat", "lon", "lng"}:
        item.pop("metric", None)


def expand_filter_value_aliases(item: dict, metadata: dict | None) -> None:
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


def format_metric_label(metric_key: str) -> str:
    return str(metric_key or "").replace("_", " ").strip().title()


def clamp_item_years_to_metric(
    item: dict,
    metadata: dict | None,
    metric_key: str | None,
    *,
    metadata_metric_year_range_func,
) -> None:
    metric_min_year, metric_max_year = metadata_metric_year_range_func(metadata, metric_key)
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


def rewrite_processed_order_summary(
    order: dict,
    validated_items: list[dict],
    *,
    load_source_metadata_func,
) -> str | None:
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
    metadata = load_source_metadata_func(source_id) or {}
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


def normalize_source_declared_scope(
    item: dict,
    *,
    load_source_metadata_func,
) -> dict:
    source_id = item.get("source_id")
    if not source_id:
        return item

    metadata = load_source_metadata_func(source_id) or {}
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
