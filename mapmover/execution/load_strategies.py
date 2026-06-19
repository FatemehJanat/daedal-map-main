"""Load-strategy helpers extracted from the main executor."""

from __future__ import annotations

import re
import time


def _classify_pushdown_filters(filters: dict | None) -> tuple[dict, dict, list[tuple[str, str, object]]]:
    """Translate generic order filters into the shared select_rows contract."""
    exact_filters: dict = {}
    in_filters: dict = {}
    compare_filters: list[tuple[str, str, object]] = []

    if not isinstance(filters, dict) or not filters:
        return exact_filters, in_filters, compare_filters

    for field, value in filters.items():
        if field.endswith("_min"):
            col = field[:-4]
            if col and value is not None:
                compare_filters.append((col, ">=", value))
            continue
        if field.endswith("_max"):
            col = field[:-4]
            if col and value is not None:
                compare_filters.append((col, "<=", value))
            continue

        if isinstance(value, dict):
            min_value = value.get("min")
            max_value = value.get("max")
            if min_value is not None:
                compare_filters.append((field, ">=", min_value))
            if max_value is not None:
                compare_filters.append((field, "<=", max_value))

            op = str(value.get("op") or "").strip().lower()
            if op == "in":
                candidates = [candidate for candidate in (value.get("values") or []) if candidate is not None]
                if candidates:
                    in_filters[field] = candidates
            elif op in {"eq", "="} and "value" in value:
                exact_filters[field] = value.get("value")
            elif op in {"!=", "ne", ">", "gt", ">=", "gte", "<", "lt", "<=", "lte"} and "value" in value:
                op_map = {
                    "!=": "!=",
                    "ne": "!=",
                    ">": ">",
                    "gt": ">",
                    ">=": ">=",
                    "gte": ">=",
                    "<": "<",
                    "lt": "<",
                    "<=": "<=",
                    "lte": "<=",
                }
                compare_filters.append((field, op_map[op], value.get("value")))
            continue

        if isinstance(value, (list, tuple, set)):
            candidates = [candidate for candidate in value if candidate is not None]
            if candidates:
                in_filters[field] = candidates
            continue

        if isinstance(value, bool):
            continue

        if value is not None:
            exact_filters[field] = value

    return exact_filters, in_filters, compare_filters


def collect_source_metadata(
    *,
    items: list,
    expand_region_func,
    load_disaster_aggregate_data_func,
    load_source_metadata_func,
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
                aggregate_like_source = str(source_id or "").strip().endswith("_aggregates")
                if item.get("mode") == "aggregate" or aggregate_like_source:
                    aggregate_df, metadata = load_disaster_aggregate_data_func(source_id, item)
                    if aggregate_df is None:
                        metadata = load_source_metadata_func(source_id)
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
                            None,
                            (),
                            (),
                            (),
                        )
                        aggregate_item_cache[cache_key] = (aggregate_df, dict(metadata or {}))
                else:
                    metadata = load_source_metadata_func(source_id)
                if not metadata:
                    raise ValueError(f"Could not load metadata for {source_id}")
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
    temporal_mode: bool,
    aggregate_item_cache: dict,
    load_disaster_aggregate_data_func,
    load_source_data_func,
    expand_region_func=None,
    load_source_metadata_func=None,
) -> tuple:
    """Load one order item's dataframe and metadata using the current strategy."""
    year = item.get("year")
    year_start = item.get("year_start")
    year_end = item.get("year_end")
    region = item.get("region")
    if not region:
        _plural_regions = item.get("regions")
        if isinstance(_plural_regions, (list, tuple)) and len(_plural_regions) == 1 and _plural_regions[0]:
            region = str(_plural_regions[0])
    filters = item.get("filters") or {}
    if not isinstance(filters, dict):
        filters = {}
    metric = item.get("metric")
    source_id = item.get("source_id")
    aggregate_like_source = str(source_id or "").strip().endswith("_aggregates")

    pushdown_year = year if (year and not year_start and not year_end) else None
    pushdown_prefix = region if (region and re.match(r"^[A-Z]{2,3}(-[A-Z0-9]+)?$", region)) else None
    filters_for_pushdown = dict(filters)
    filter_loc_id_prefix = str(filters_for_pushdown.pop("loc_id_prefix", "") or "").strip()
    if pushdown_prefix is None and filter_loc_id_prefix:
        pushdown_prefix = filter_loc_id_prefix
    # Filter location at the source for marine_zone sources: when a named basin/
    # sea/EEZ region resolves to a single X*/EEZ-* loc_id, push it down to the
    # parquet so the location filter is not lost to the row cap. The X* ocean
    # basins sort past the cap window on a loc_id-sorted marine table, so without
    # pushdown a Mediterranean (XSM) query over a year range would load only the
    # first cap window of EEZ-A* zones and filter to zero. Scoped to marine
    # because land/currency/event sources key on different loc_id spines and a
    # speculative ISO3 pushdown there could mismatch the stored scheme.
    # See live_source_qa_checklist.md (time-before-location / cap-window trap).
    if (
        pushdown_prefix is None
        and region
        and expand_region_func is not None
        and load_source_metadata_func is not None
        and source_id
    ):
        is_marine = False
        try:
            _meta = load_source_metadata_func(source_id) or {}
            is_marine = str(_meta.get("geographic_level") or "").strip().lower() == "marine_zone"
        except Exception:
            is_marine = False
        if is_marine:
            try:
                _resolved = expand_region_func(region, prefer_water_body=True)
            except TypeError:
                _resolved = expand_region_func(region)
            if isinstance(_resolved, (set, list, tuple)) and len(_resolved) == 1:
                _code = str(next(iter(_resolved))).strip()
                if re.match(r"^[A-Z]{2,3}(-[A-Z0-9]+)?$", _code):
                    pushdown_prefix = _code

    # Time-before-location for broad queries: when no specific location is being
    # pushed down and the time range was auto-defaulted by the order-taker (not
    # explicitly requested), drop the range so the latest year is loaded for ALL
    # locations. Otherwise a wide default range (e.g. 10 years x ~300 monthly
    # marine zones) overflows the row cap and truncates to an alphabetical slice
    # of zones -- showing 44 regions instead of the whole world. A specific
    # location (pushdown_prefix set) keeps its full range so "that place across a
    # long time" still loads its whole series. An explicit user-requested range
    # has no _defaulted_time_range marker and is always honored.
    # See live_source_qa_checklist.md (time-before-location / cap-window trap).
    if (
        pushdown_prefix is None
        and pushdown_year is None
        and item.get("_defaulted_time_range")
        and (year_start is not None or year_end is not None)
    ):
        # Collapse to the latest year of the defaulted range and push it down
        # explicitly. Nulling the range is not enough: a range elsewhere flips
        # the executor into temporal/animation mode, which suppresses the
        # latest-year default, so we set the single-year pushdown directly.
        latest_default_year = year_end if year_end is not None else year_start
        year = latest_default_year
        pushdown_year = latest_default_year
        year_start = None
        year_end = None

    exact_filters, in_filters, compare_filters = _classify_pushdown_filters(filters_for_pushdown)
    if pushdown_year is None:
        if year_start is not None:
            compare_filters.append(("year", ">=", year_start))
        if year_end is not None:
            compare_filters.append(("year", "<=", year_end))
    requested_columns = [
        "loc_id",
        "geo_level",
        "year",
        "timestamp",
        "date",
        "time",
        "month",
        "week",
        "lat",
        "latitude",
        "centroid_lat",
        "lon",
        "longitude",
        "centroid_lon",
        "end_latitude",
        "end_longitude",
    ]
    if metric:
        requested_columns.append(str(metric))
    sort_spec = item.get("sort")
    if isinstance(sort_spec, dict) and sort_spec.get("by"):
        requested_columns.append(str(sort_spec.get("by")))
    requested_columns.extend(str(field).strip() for field in filters.keys() if str(field).strip())
    requested_columns = [value for value in dict.fromkeys(requested_columns) if value]

    if item.get("mode") == "aggregate" or aggregate_like_source:
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
            pushdown_prefix,
            tuple(sorted((exact_filters or {}).items())),
            tuple((field, tuple(values) if isinstance(values, list) else values) for field, values in sorted((in_filters or {}).items())),
            tuple(compare_filters or []),
        )
        cached = aggregate_item_cache.get(cache_key)
        if cached is not None:
            return cached[0].copy(), dict(cached[1] or {})
        df, metadata = load_disaster_aggregate_data_func(item.get("source_id"), item)
        if df is None or metadata is None:
            return load_source_data_func(
                item.get("source_id"),
                year=pushdown_year,
                loc_id_prefix=pushdown_prefix,
                exact_filters=exact_filters or None,
                in_filters=in_filters or None,
                compare_filters=compare_filters or None,
                columns=requested_columns,
                prefer_latest_year_when_unspecified=not temporal_mode and year is None and year_start is None and year_end is None,
                requested_limit=None if sort_spec else item.get("limit"),
            )
        return df, metadata

    return load_source_data_func(
        item.get("source_id"),
        year=pushdown_year,
        loc_id_prefix=pushdown_prefix,
        exact_filters=exact_filters or None,
        in_filters=in_filters or None,
        compare_filters=compare_filters or None,
        columns=requested_columns,
        prefer_latest_year_when_unspecified=not temporal_mode and year is None and year_start is None and year_end is None,
        requested_limit=None if sort_spec else item.get("limit"),
    )
