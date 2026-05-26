"""Per-item metric processing helpers extracted from the main executor."""

from __future__ import annotations

import pandas as pd


def process_metric_items(
    *,
    order: dict,
    items: list,
    multi_year_mode: bool,
    aggregate_item_cache: dict,
    year_data,
    boxes,
    all_years: set,
    metric_key,
    all_metrics: list,
    metric_year_ranges: dict,
    metric_source_map: dict,
    aggregation_trace: list,
    loc_level_map: dict,
    location_features: list,
    requested_year_start,
    requested_year_end,
    all_region_codes: set,
    requested_geo_levels: set,
    trace_id: str,
    logger,
    executor_log_func,
    perf_counter_func,
    normalize_year_filters_func,
    normalize_geo_level_func,
    normalize_sort_spec_func,
    load_order_item_dataframe_func,
    derive_eurostat_geo_level_func,
    load_fx_with_aggregation_func,
    find_metric_column_func,
    check_sparse_year_func,
    expand_region_func,
    canonicalize_loc_id_func,
    translate_loc_id_to_geometry_id_func,
    translate_geometry_id_to_local_id_func,
    apply_dataframe_filters_func,
    get_coordinate_columns_func,
    available_years_for_range_func,
    metadata_metric_year_range_func,
    apply_derived_fields_func,
    apply_runtime_result_cap_func=None,
    merge_cap_info_func=None,
) -> dict:
    """Process all metric items and populate the executor data structures."""
    cap_infos = []
    for idx, item in enumerate(items, start=1):
        source_id = item.get("source_id")
        metric = item.get("metric")
        region = item.get("region")
        filters = item.get("filters") or {}
        requested_geo_level = normalize_geo_level_func(item.get("geo_level"))
        if requested_geo_level:
            requested_geo_levels.add(requested_geo_level)
        year, year_start, year_end = normalize_year_filters_func(item)
        sort_spec = normalize_sort_spec_func(item.get("sort"))

        if year_start and year_end:
            requested_year_start = year_start
            requested_year_end = year_end

        if not source_id:
            continue

        t_item_start = perf_counter_func()
        try:
            df, metadata = load_order_item_dataframe_func(
                item=item,
                aggregate_item_cache=aggregate_item_cache,
            )
        except Exception as exc:
            logger.error(f"Error loading {source_id}: {exc}", exc_info=True)
            continue
        t_after_load = executor_log_func(trace_id, "item_loaded", t_item_start, f"item={idx}/{len(items)} source={source_id} rows={len(df)} cols={len(df.columns)}")

        if source_id == "eurostat" and "geo_level" not in df.columns and "loc_id" in df.columns:
            df = df.copy()
            df["geo_level"] = df["loc_id"].map(derive_eurostat_geo_level_func)

        if source_id == "fx_usd_historical":
            fx_df, trace = load_fx_with_aggregation_func(source_id, item, metadata)
            aggregation_trace.append(trace)
            if fx_df is not None:
                df = fx_df
        t_after_fx = executor_log_func(trace_id, "item_aggregation_applied", t_after_load, f"item={idx}/{len(items)} source={source_id} rows={len(df)}")

        if metric:
            metric_col = find_metric_column_func(df, metric, metadata=metadata)
        else:
            metric_col = None
        executor_log_func(trace_id, "metric_resolved", t_after_fx, f"item={idx}/{len(items)} source={source_id} metric={metric_col}")

        item_label = item.get("metric_label", metric_col)
        if metric_col and item_label:
            if not metric_key:
                metric_key = item_label
            if item_label not in all_metrics:
                all_metrics.append(item_label)
            if year_start and year_end:
                metric_year_ranges[item_label] = {
                    "min": year_start,
                    "max": year_end,
                    "available_years": available_years_for_range_func(year_start, year_end),
                }
            else:
                metric_min_year, metric_max_year = metadata_metric_year_range_func(metadata, metric_col)
                if metric_min_year is not None and metric_max_year is not None:
                    metric_year_ranges[item_label] = {
                        "min": metric_min_year,
                        "max": metric_max_year,
                        "available_years": available_years_for_range_func(metric_min_year, metric_max_year),
                    }

        if year_start and year_end and "year" in df.columns:
            df = df[(df["year"] >= year_start) & (df["year"] <= year_end)]
        elif year and "year" in df.columns:
            df = df[df["year"] == year]
        elif "year" in df.columns:
            if metric_col and metric_col in df.columns:
                years_with_data = df[df[metric_col].notna()]["year"].unique()
                if len(years_with_data) > 0:
                    selected_year = max(years_with_data)
                    sparse_clarify = check_sparse_year_func(df, metric_col, selected_year, metadata)
                    if sparse_clarify:
                        return {"early_result": sparse_clarify}
                    df = df[df["year"] == selected_year]
                else:
                    df = df[df["year"] == df["year"].max()]
            else:
                df = df[df["year"] == df["year"].max()]
        t_after_time_filter = executor_log_func(trace_id, "time_filtered", t_after_fx, f"item={idx}/{len(items)} source={source_id} rows={len(df)}")

        region_codes = expand_region_func(region)
        if region_codes:
            all_region_codes.update(region_codes)
        if region_codes and "loc_id" in df.columns:
            loc_id_series = df["loc_id"].map(canonicalize_loc_id_func)
            normalized_region_codes = set()
            for code in region_codes:
                normalized_region_codes.add(code)
                normalized_region_codes.add(translate_loc_id_to_geometry_id_func(code))
                normalized_region_codes.add(translate_geometry_id_to_local_id_func(code))
            region_prefixes = tuple(
                str(code).strip()
                for code in normalized_region_codes
                if isinstance(code, str) and str(code).strip()
            )
            if region_prefixes:
                mask = loc_id_series.str.startswith(region_prefixes, na=False)
                df = df[mask]
        t_after_region_filter = executor_log_func(trace_id, "region_filtered", t_after_time_filter, f"item={idx}/{len(items)} source={source_id} rows={len(df)}")

        if requested_geo_level and "geo_level" in df.columns:
            df = df[df["geo_level"] == requested_geo_level]

        df = apply_dataframe_filters_func(df, filters)
        t_after_filter = executor_log_func(trace_id, "field_filters_applied", t_after_region_filter, f"item={idx}/{len(items)} source={source_id} rows={len(df)}")

        if sort_spec and not multi_year_mode:
            sort_col = sort_spec.get("by")
            if sort_col:
                matched_col = find_metric_column_func(df, sort_col, metadata=metadata)
                if matched_col:
                    ascending = sort_spec.get("order", "desc") == "asc"
                    df = df.sort_values(matched_col, ascending=ascending, na_position="last")
                    if sort_spec.get("limit"):
                        df = df.head(sort_spec["limit"])
        t_after_sort = executor_log_func(trace_id, "sort_applied", t_after_filter, f"item={idx}/{len(items)} source={source_id} rows={len(df)}")

        if apply_runtime_result_cap_func is not None:
            requested_limit = sort_spec.get("limit") if isinstance(sort_spec, dict) else None
            df, item_cap_info = apply_runtime_result_cap_func(
                df,
                source_metadata=metadata,
                requested_limit=requested_limit,
            )
            if item_cap_info:
                cap_infos.append(item_cap_info)
            t_after_sort = executor_log_func(
                trace_id,
                "runtime_cap_applied",
                t_after_sort,
                f"item={idx}/{len(items)} source={source_id} rows={len(df)} cap_hit={bool(item_cap_info)}",
            )

        if str(metadata.get("geojson_shape", "")).strip().lower() == "location_shape":
            lat_col, lon_col = get_coordinate_columns_func(df)
            if lat_col and lon_col:
                for _, row in df.iterrows():
                    lat = row.get(lat_col)
                    lon = row.get(lon_col)
                    if pd.isna(lat) or pd.isna(lon):
                        continue

                    properties = {}
                    for col in df.columns:
                        if col.startswith("_"):
                            continue
                        val = row.get(col)
                        if pd.notna(val):
                            if hasattr(val, "item"):
                                val = val.item()
                            if isinstance(val, pd.Timestamp):
                                val = val.isoformat()
                            properties[col] = val

                    location_features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
                        "properties": properties,
                    })
            executor_log_func(trace_id, "location_features_built", t_after_sort, f"item={idx}/{len(items)} source={source_id} features={len(location_features)}")
            continue

        if not metric_col:
            continue

        label = item.get("metric_label", metric_col)
        if source_id and label not in metric_source_map:
            metric_source_map[label] = source_id

        for _, row in df.iterrows():
            raw_loc_id = row.get("loc_id")
            loc_id = canonicalize_loc_id_func(raw_loc_id)
            if not loc_id:
                continue
            geom_loc_id = translate_loc_id_to_geometry_id_func(loc_id)

            val = row.get(metric_col)
            if pd.notna(val):
                if hasattr(val, "item"):
                    val = val.item()

                if multi_year_mode:
                    row_year = int(row.get("year")) if "year" in df.columns else 0
                    all_years.add(row_year)
                    row_geo_level = row.get("geo_level") if "geo_level" in df.columns else requested_geo_level
                    if row_geo_level:
                        loc_level_map[geom_loc_id] = row_geo_level

                    if row_year not in year_data:
                        year_data[row_year] = {}
                    if geom_loc_id not in year_data[row_year]:
                        year_data[row_year][geom_loc_id] = {}

                    year_data[row_year][geom_loc_id][label] = val
                else:
                    if geom_loc_id not in boxes:
                        box = {"year": row.get("year")} if "year" in df.columns else {}
                        if "geo_level" in df.columns:
                            box["_geo_level"] = row.get("geo_level")
                        elif requested_geo_level:
                            box["_geo_level"] = requested_geo_level
                        boxes[geom_loc_id] = box

                    boxes[geom_loc_id][label] = val
        tracked_rows = len(df)
        box_count = len(year_data) if multi_year_mode and year_data is not None else len(boxes or {})
        executor_log_func(trace_id, "item_values_applied", t_after_sort, f"item={idx}/{len(items)} source={source_id} metric={label} rows={tracked_rows} box_count={box_count}")

    derived_specs = order.get("derived_specs", [])
    if derived_specs and boxes:
        calc_year = None
        if items:
            calc_year = items[0].get("year")
        if not calc_year and boxes:
            first_box = next(iter(boxes.values()))
            calc_year = first_box.get("year")

        derivation_warnings = apply_derived_fields_func(boxes, derived_specs, calc_year)
        if derivation_warnings:
            print(f"Derivation warnings: {derivation_warnings[:5]}")

    merged_cap_info = None
    if cap_infos:
        if merge_cap_info_func is not None:
            merged_cap_info = merge_cap_info_func(*cap_infos)
        else:
            merged_cap_info = cap_infos[0]

    return {
        "year_data": year_data,
        "boxes": boxes,
        "all_years": all_years,
        "metric_key": metric_key,
        "all_metrics": all_metrics,
        "metric_year_ranges": metric_year_ranges,
        "metric_source_map": metric_source_map,
        "aggregation_trace": aggregation_trace,
        "loc_level_map": loc_level_map,
        "location_features": location_features,
        "requested_year_start": requested_year_start,
        "requested_year_end": requested_year_end,
        "all_region_codes": all_region_codes,
        "requested_geo_levels": requested_geo_levels,
        "cap_info": merged_cap_info,
    }
