"""Shared postprocess validation helpers."""

from __future__ import annotations

from .source_hints import (
    get_single_metric_default,
    infer_requested_geo_level_from_query,
    select_pack_family_source_for_query,
    select_query_guided_metric,
    source_geometry_kind,
    source_geometry_subkind,
)


def _currency_granularity_source_id(item: dict) -> str | None:
    if str(item.get("pack_id") or "").strip() != "currency":
        return None
    granularity = str(item.get("time_granularity") or "").strip().lower()
    if granularity == "weekly":
        return "fx_usd_historical_weekly"
    if granularity == "monthly":
        return "fx_usd_historical_monthly"
    if granularity == "daily":
        return "fx_usd_historical"
    return None


def validate_item(
    item: dict,
    catalog: dict,
    *,
    validate_item_func,
    resolve_pack_source_func,
    get_catalog_pack_func,
    catalog_sources_func,
    get_catalog_source_func,
    normalize_item_filters_func,
    normalize_location_shape_metric_func,
    apply_disaster_semantic_filters_func,
    source_has_metrics_func,
    source_supports_aggregate_mode_func,
    apply_aggregate_query_hints_func,
    source_supports_events_func,
    query_prefers_event_source_func,
    query_requests_short_current_window_func,
    reroute_item_to_event_sibling_func,
    resolve_pack_source_by_shape_func,
    load_source_metadata_func,
    expand_filter_value_aliases_func,
    source_requires_metric_func,
    get_disaster_aggregate_metric_columns_func,
    format_metric_label_func,
    resolve_pack_source_for_metric_func,
    clamp_item_years_to_metric_func,
) -> dict:
    """Validate one postprocessed order item against catalog and metadata."""
    item.pop("_error", None)
    item.pop("_valid", None)
    source_id = item.get("source_id")
    metric = item.get("metric")
    query = str(((item.get("_hints") or {}).get("original_query")) or "").lower()

    if item.get("type") == "derived_result":
        item["_valid"] = True
        return item

    if item.get("type") == "derived":
        item["_valid"] = True
        item["_needs_expansion"] = True
        return item

    if not source_id and item.get("pack_id"):
        resolved_source = resolve_pack_source_func(catalog, item.get("pack_id"), item.get("region"), item)
        if resolved_source:
            item["source_id"] = resolved_source
            item["_resolved_from_pack"] = True
            source_id = resolved_source
        else:
            item["_valid"] = False
            item["_error"] = f"Unable to resolve pack_id '{item.get('pack_id')}' to a concrete source"
            return item

    if not source_id:
        item["_valid"] = False
        item["_error"] = "Missing source_id"
        return item

    if not item.get("pack_id"):
        pack = get_catalog_pack_func(catalog, source_id)
        if pack:
            item["pack_id"] = source_id
            item.pop("source_id", None)
            resolved_source = resolve_pack_source_func(catalog, source_id, item.get("region"), item)
            if resolved_source:
                item["source_id"] = resolved_source
                item["_resolved_from_pack"] = True
                source_id = resolved_source
            else:
                item["_valid"] = False
                item["_error"] = f"Unable to resolve pack_id '{source_id}' to a concrete source"
                return item

    sources = catalog_sources_func(catalog)
    source_ids = [s.get("source_id") for s in sources] if isinstance(sources, list) else list(sources.keys())
    if source_id not in source_ids:
        item["_valid"] = False
        item["_error"] = f"Unknown source: {source_id}"
        return item

    catalog_source = get_catalog_source_func(catalog, source_id)
    if catalog_source and not item.get("pack_id"):
        source_pack_id = str(catalog_source.get("pack_id") or "").strip()
        if source_pack_id:
            item["pack_id"] = source_pack_id
    pack_id = str(item.get("pack_id") or "").strip()
    explicit_currency_source = _currency_granularity_source_id(item)
    if explicit_currency_source and explicit_currency_source != source_id:
        item["source_id"] = explicit_currency_source
        item["_resolved_from_pack"] = True
        source_id = explicit_currency_source
        catalog_source = get_catalog_source_func(catalog, source_id)
    if pack_id and query:
        preferred_source_id, preferred_metadata, preferred_metric = select_pack_family_source_for_query(
            pack_id,
            query,
            catalog=catalog,
            load_source_metadata_func=load_source_metadata_func,
        )
        if explicit_currency_source:
            preferred_source_id = explicit_currency_source
        if preferred_source_id and preferred_source_id != source_id:
            item["source_id"] = preferred_source_id
            item["_resolved_from_pack"] = True
            source_id = preferred_source_id
            catalog_source = get_catalog_source_func(catalog, source_id)
            if catalog_source and not item.get("pack_id"):
                source_pack_id = str(catalog_source.get("pack_id") or "").strip()
                if source_pack_id:
                    item["pack_id"] = source_pack_id
        metadata = preferred_metadata or load_source_metadata_func(source_id)
        inferred_metric = preferred_metric or select_query_guided_metric(query, metadata)
        if inferred_metric and not metric:
            item["metric"] = inferred_metric
            metric = inferred_metric
        inferred_geo_level = infer_requested_geo_level_from_query(query, metadata)
        if inferred_geo_level:
            item["geo_level"] = inferred_geo_level
    else:
        metadata = None
    normalize_item_filters_func(item, catalog_source)
    normalize_location_shape_metric_func(item, catalog_source)
    metric = item.get("metric")
    apply_disaster_semantic_filters_func(item, catalog_source, query)

    if (
        not item.get("mode")
        and source_has_metrics_func(catalog_source)
        and source_supports_aggregate_mode_func(catalog_source)
    ):
        apply_aggregate_query_hints_func(item, query)
    elif item.get("mode") == "aggregate":
        apply_aggregate_query_hints_func(item, query)

    if item.get("mode") == "events" and not source_supports_events_func(catalog_source):
        item.pop("event_file", None)
        if (
            item.get("aggregate_use_rolling")
            or item.get("aggregate_window_years")
            or item.get("aggregate_rollup_level")
            or item.get("aggregate_all_years")
            or source_supports_aggregate_mode_func(catalog_source)
        ):
            item["mode"] = "aggregate"
        else:
            item.pop("mode", None)

    if (
        (
            query_prefers_event_source_func(query)
            or query_requests_short_current_window_func(query)
        )
        and not source_supports_events_func(catalog_source)
        and reroute_item_to_event_sibling_func(
            item,
            catalog,
            resolve_pack_source_by_shape_func=resolve_pack_source_by_shape_func,
        )
    ):
        return validate_item_func(item, catalog)

    if item.get("mode") == "events":
        item.pop("_error", None)
        item["_valid"] = True
        return item

    metadata = metadata or load_source_metadata_func(source_id)
    expand_filter_value_aliases_func(item, metadata)

    if source_requires_metric_func(item, catalog_source) and not metric:
        default_metric = get_single_metric_default(metadata)
        if default_metric:
            item["metric"] = default_metric
            metric = default_metric
        elif (
            query_prefers_event_source_func(query)
            or query_requests_short_current_window_func(query)
        ) and reroute_item_to_event_sibling_func(
            item,
            catalog,
            resolve_pack_source_by_shape_func=resolve_pack_source_by_shape_func,
        ):
            return validate_item_func(item, catalog)
        else:
            item["_valid"] = False
            item["_error"] = f"Source '{source_id}' requires a concrete metric before execution"
            return item

    if not metadata:
        item.pop("_error", None)
        item["_valid"] = True
        return item

    metrics = metadata.get("metrics", {})
    aggregate_metric_cols = set()
    if item.get("mode") == "aggregate":
        aggregate_metric_cols = get_disaster_aggregate_metric_columns_func(catalog_source)

    if metric and metric not in metrics and metric in aggregate_metric_cols:
        item["metric_label"] = format_metric_label_func(metric)
        item.pop("_error", None)
        item["_valid"] = True
        return item

    if metric and metric not in metrics:
        metric_lower = metric.lower()
        exact_match = None
        for key in metrics.keys():
            if key.lower() == metric_lower:
                exact_match = key
                break

        if not exact_match:
            for key, value in metrics.items():
                if isinstance(value, dict):
                    name = value.get("name", "")
                    if name.lower() == metric_lower:
                        exact_match = key
                        break

        if exact_match:
            item["metric"] = exact_match
            metric = exact_match
        else:
            if item.get("mode") == "aggregate" and aggregate_metric_cols:
                aggregate_exact_match = next((col for col in aggregate_metric_cols if col.lower() == metric_lower), None)
                if aggregate_exact_match:
                    item["metric"] = aggregate_exact_match
                    item["metric_label"] = format_metric_label_func(aggregate_exact_match)
                    item.pop("_error", None)
                    item["_valid"] = True
                    return item

            pack_metric_source = resolve_pack_source_for_metric_func(
                catalog,
                item.get("pack_id"),
                item.get("region"),
                metric,
            )
            if pack_metric_source and pack_metric_source != source_id:
                item["source_id"] = pack_metric_source
                item["_resolved_from_pack"] = True
                return validate_item_func(item, catalog)

            close_matches = []
            for key, value in metrics.items():
                name = value.get("name", "") if isinstance(value, dict) else ""
                if metric_lower in key.lower() or key.lower() in metric_lower:
                    close_matches.append(key)
                elif name and (metric_lower in name.lower() or name.lower() in metric_lower):
                    close_matches.append(key)
            if item.get("mode") == "aggregate":
                for col in aggregate_metric_cols:
                    if metric_lower in col.lower() or col.lower() in metric_lower:
                        close_matches.append(col)
            close_matches = list(dict.fromkeys(close_matches))
            if close_matches:
                item["_valid"] = False
                item["_error"] = f"Metric '{metric}' not found. Did you mean: {', '.join(close_matches[:3])}?"
            else:
                item["_valid"] = False
                item["_error"] = f"Metric '{metric}' not found in {source_id}"
            return item

    if metric:
        metric_info = metrics.get(metric, {})
        name = metric_info.get("name", metric)
        unit = metric_info.get("unit", "")
        if unit and unit != "unknown":
            item["metric_label"] = f"{name} ({unit})"
        else:
            item["metric_label"] = name

        clamp_item_years_to_metric_func(item, metadata, metric)

    if not item.get("sort") and metric:
        row_count = metadata.get("row_count") if isinstance(metadata, dict) else None
        geometry_kind = source_geometry_kind(metadata)
        geometry_subkind = source_geometry_subkind(metadata)
        if (
            isinstance(row_count, int)
            and row_count >= 50000
            and (
                geometry_kind == "admin"
                or (geometry_kind == "entity" and geometry_subkind == "area")
            )
            and any(term in query for term in ("tallest", "highest", "lowest", "top ", "most "))
        ):
            item["sort"] = {"by": metric, "order": "desc", "limit": 100}

    item.pop("_error", None)
    item["_valid"] = True
    return item


__all__ = ["validate_item"]
