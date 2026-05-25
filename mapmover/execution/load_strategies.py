"""Load-strategy helpers extracted from the main executor."""

from __future__ import annotations

import re
import time


def collect_source_metadata(
    *,
    items: list,
    expand_region_func,
    load_disaster_aggregate_data_func,
    load_source_data_func,
    logger,
    trace_id: str,
) -> dict:
    """Collect source metadata and cache aggregate loads before item execution."""
    target_countries = set()
    geo_levels = set()
    sources_used = {}
    aggregate_item_cache = {}

    for item in items:
        region = item.get("region")
        countries = expand_region_func(region)
        if countries:
            target_countries.update(countries)

        source_id = item.get("source_id")
        if source_id and source_id not in sources_used:
            try:
                if item.get("mode") == "aggregate":
                    aggregate_df, metadata = load_disaster_aggregate_data_func(source_id, item)
                    if aggregate_df is None:
                        _, metadata = load_source_data_func(source_id)
                    else:
                        cache_key = (
                            source_id,
                            item.get("metric"),
                            item.get("region"),
                            item.get("year"),
                            item.get("year_start"),
                            item.get("year_end"),
                            item.get("aggregate_use_rolling"),
                            item.get("aggregate_window_years"),
                            item.get("aggregate_rollup_level"),
                            item.get("aggregate_all_years"),
                        )
                        aggregate_item_cache[cache_key] = (aggregate_df, dict(metadata or {}))
                else:
                    _, metadata = load_source_data_func(source_id)
                sources_used[source_id] = metadata
                geographic_level = metadata.get("geographic_level", "country")
                if isinstance(geographic_level, list):
                    for level in geographic_level:
                        geo_levels.add(level)
                else:
                    geo_levels.add(geographic_level)
            except Exception as exc:
                logger.warning(f"[executor:{trace_id}] failed to collect source metadata for {source_id}: {exc}")

    return {
        "target_countries": target_countries,
        "geo_levels": geo_levels,
        "sources_used": sources_used,
        "aggregate_item_cache": aggregate_item_cache,
    }


def load_order_item_dataframe(
    *,
    item: dict,
    aggregate_item_cache: dict,
    load_disaster_aggregate_data_func,
    load_source_data_func,
) -> tuple:
    """Load one order item's dataframe and metadata using the current strategy."""
    year = item.get("year")
    year_start = item.get("year_start")
    year_end = item.get("year_end")
    region = item.get("region")

    pushdown_year = year if (year and not year_start and not year_end) else None
    pushdown_prefix = region if (region and re.match(r"^[A-Z]{2,3}(-[A-Z0-9]+)?$", region)) else None

    if item.get("mode") == "aggregate":
        cache_key = (
            item.get("source_id"),
            item.get("metric"),
            item.get("region"),
            item.get("year"),
            item.get("year_start"),
            item.get("year_end"),
            item.get("aggregate_use_rolling"),
            item.get("aggregate_window_years"),
            item.get("aggregate_rollup_level"),
            item.get("aggregate_all_years"),
        )
        cached = aggregate_item_cache.get(cache_key)
        if cached is not None:
            return cached[0].copy(), dict(cached[1] or {})
        df, metadata = load_disaster_aggregate_data_func(item.get("source_id"), item)
        if df is None or metadata is None:
            return load_source_data_func(item.get("source_id"), year=pushdown_year, loc_id_prefix=pushdown_prefix)
        return df, metadata

    return load_source_data_func(item.get("source_id"), year=pushdown_year, loc_id_prefix=pushdown_prefix)
