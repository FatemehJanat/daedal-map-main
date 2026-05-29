import pandas as pd


def _build_default_time_note(items: list) -> str | None:
    defaulted_ranges = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        defaulted = item.get("_defaulted_time_range")
        if isinstance(defaulted, dict):
            defaulted_ranges.append(defaulted)

    if not defaulted_ranges:
        return None

    first = defaulted_ranges[0]
    same_ranges = all(
        entry.get("year_start") == first.get("year_start")
        and entry.get("year_end") == first.get("year_end")
        and entry.get("available_start") == first.get("available_start")
        and entry.get("available_end") == first.get("available_end")
        for entry in defaulted_ranges[1:]
    )

    if same_ranges:
        shown = f"{first.get('year_start')}-{first.get('year_end')}"
        available_start = first.get("available_start")
        available_end = first.get("available_end")
        if available_start and available_end:
            return f"Showing {shown} by default; data available for {available_start}-{available_end} if you want more history."
        return f"Showing {shown} by default because no time range was specified."

    return "Showing default 10-year windows for items without a time range. Ask for a broader period if you want more history."


def detect_event_type(source_id: str, *, get_source_from_catalog_func, load_source_metadata_func, resolve_event_source_id_func) -> str:
    source = get_source_from_catalog_func(source_id)
    if source.get("event_type"):
        return source.get("event_type")
    metadata = load_source_metadata_func(resolve_event_source_id_func(source_id)) or {}
    return metadata.get("event_type", "unknown")


def get_significance_column(source_id: str, *, get_source_from_catalog_func) -> str:
    source = get_source_from_catalog_func(source_id)
    return source.get("significance_column")


def get_coordinate_columns(df: pd.DataFrame) -> tuple:
    lat_candidates = ["lat", "latitude", "centroid_lat"]
    lon_candidates = ["lon", "longitude", "centroid_lon"]

    lat_col = None
    lon_col = None

    for col in lat_candidates:
        if col in df.columns:
            lat_col = col
            break

    for col in lon_candidates:
        if col in df.columns:
            lon_col = col
            break

    return lat_col, lon_col


def get_time_column(df: pd.DataFrame) -> str:
    time_candidates = ["time", "timestamp", "event_date", "date", "ignition_date"]
    for col in time_candidates:
        if col in df.columns:
            return col
    return None


def get_id_column(df: pd.DataFrame, event_type: str) -> str:
    id_candidates = ["event_id", f"{event_type}_id", "id", "storm_id", "fire_id"]
    for col in id_candidates:
        if col in df.columns:
            return col
    return None


def order_item_original_query(item: dict | None) -> str:
    if not isinstance(item, dict):
        return ""
    hints = item.get("_hints") if isinstance(item.get("_hints"), dict) else {}
    return str(hints.get("original_query") or item.get("summary") or "").strip()


def build_empty_wildfire_perimeter_response(
    order: dict,
    item: dict,
    source_id: str,
    *,
    get_source_from_catalog_func,
) -> dict | None:
    query_text = " ".join(
        part for part in (
            order_item_original_query(item),
            str(order.get("summary") or "").strip(),
        )
        if part
    ).lower()
    if "wildfire" not in query_text and "fire" not in query_text:
        return None
    if "perimeter" not in query_text:
        return None

    source_note = (
        "The published USA and Canada wildfire event sources do not reliably include perimeter polygons for every named fire."
        if source_id in {"wildfires_usa", "can_wildfires"}
        else "Perimeter coverage in this wildfire source is incomplete, and this specific fire does not have a published perimeter polygon."
    )
    message = (
        f"{source_note} I could not draw a perimeter for this request from the current published data. "
        "I can still help with the fire's event details, affected areas, or a different wildfire that has perimeter coverage."
    )
    return {
        "type": "chat",
        "data_type": "events",
        "source_id": source_id,
        "geojson": {"type": "FeatureCollection", "features": []},
        "summary": order.get("summary") or "Wildfire perimeter not available in the current published data",
        "message": message,
        "count": 0,
        "sources": [{
            "id": source_id,
            "name": get_source_from_catalog_func(source_id).get("source_name", source_id),
            "url": get_source_from_catalog_func(source_id).get("source_url", ""),
        }],
    }


def execute_event_order_impl(
    order: dict,
    *,
    normalize_year_filters_func,
    normalize_sort_spec_func,
    resolve_event_source_id_func,
    duckdb_can_query_events_func,
    load_event_data_duckdb_func,
    load_event_data_func,
    get_source_from_catalog_func,
    load_source_metadata_func,
    resolve_event_parquet_path_func,
    select_peak_positions_by_storm_ids_func,
    get_coordinate_columns_func,
    get_time_column_func,
    get_id_column_func,
    expand_region_func,
    default_event_limit,
    max_event_limit,
) -> dict:
    items = order.get("items", [])
    summary = order.get("summary", "")

    if not items:
        return {
            "type": "error",
            "message": "No items in order",
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0,
        }

    item = items[0]
    source_id = item.get("source_id")
    resolved_source_id = resolve_event_source_id_func(source_id)
    event_file_key = item.get("event_file", "events")
    region = item.get("region")
    year, year_start, year_end = normalize_year_filters_func(item)
    filters = item.get("filters", {})
    requested_limit = item.get("limit")
    sort_spec = normalize_sort_spec_func(item.get("sort"))

    try:
        if duckdb_can_query_events_func(source_id):
            df, metadata = load_event_data_duckdb_func(resolved_source_id, item, event_file_key)
        else:
            df, metadata = load_event_data_func(resolved_source_id, event_file_key)
    except Exception as e:
        return {
            "type": "error",
            "message": f"Failed to load event data: {e}",
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0,
        }

    event_type = detect_event_type(
        source_id,
        get_source_from_catalog_func=get_source_from_catalog_func,
        load_source_metadata_func=load_source_metadata_func,
        resolve_event_source_id_func=resolve_event_source_id_func,
    )
    print(f"Event mode: {resolved_source_id} -> {event_type}, {len(df)} raw events")

    if (
        source_id == "hurricanes"
        and event_file_key in {"events", "storms"}
        and ("latitude" not in df.columns or "longitude" not in df.columns)
    ):
        positions_path, _ = resolve_event_parquet_path_func(source_id, "positions")
        peak_positions = select_peak_positions_by_storm_ids_func(positions_path, df.get("storm_id", []).tolist())
        if not peak_positions.empty:
            df = df.merge(
                peak_positions[["storm_id", "latitude", "longitude"]],
                on="storm_id",
                how="left",
                suffixes=("", "_pos"),
            )

    lat_col, lon_col = get_coordinate_columns_func(df)
    if not lat_col or not lon_col:
        return {
            "type": "error",
            "message": f"No coordinate columns found in {source_id}",
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0,
        }

    time_col = get_time_column_func(df)
    id_col = get_id_column_func(df, event_type)

    if not duckdb_can_query_events_func(source_id):
        if year_start and year_end:
            if "year" in df.columns:
                df = df[(df["year"] >= year_start) & (df["year"] <= year_end)]
            elif time_col:
                df["_year"] = pd.to_datetime(df[time_col]).dt.year
                df = df[(df["_year"] >= year_start) & (df["_year"] <= year_end)]
        elif year:
            if "year" in df.columns:
                df = df[df["year"] == year]
            elif time_col:
                df["_year"] = pd.to_datetime(df[time_col]).dt.year
                df = df[df["_year"] == year]

        region_codes = expand_region_func(region)
        if region_codes and "loc_id" in df.columns:
            us_state_prefixes = [c for c in region_codes if c.startswith("USA-")]
            country_codes = [c for c in region_codes if not c.startswith("USA-")]

            if us_state_prefixes:
                mask = df["loc_id"].str.startswith(tuple(us_state_prefixes), na=False)
                df = df[mask]
            elif country_codes:
                df["_country"] = df["loc_id"].str.split("-").str[0]
                df = df[df["_country"].isin(country_codes)]

        for field, value in filters.items():
            if field.endswith("_min"):
                col = field[:-4]
                if col in df.columns:
                    df = df[df[col] >= value]
            elif field.endswith("_max"):
                col = field[:-4]
                if col in df.columns:
                    df = df[df[col] <= value]
            elif field in df.columns:
                df = df[df[field] == value]

        print(f"  After filters: {len(df)} events")

        limit = min(requested_limit or default_event_limit, max_event_limit)

        sort_col = None
        ascending = False
        if sort_spec:
            requested_sort_col = str(sort_spec.get("by") or "").strip()
            if requested_sort_col in df.columns:
                sort_col = requested_sort_col
            elif requested_sort_col in {"date", "time"} and "timestamp" in df.columns:
                sort_col = "timestamp"
            ascending = str(sort_spec.get("order", "desc")).lower() == "asc"

        if not sort_col:
            sig_col = get_significance_column(
                source_id,
                get_source_from_catalog_func=get_source_from_catalog_func,
            )
            if sig_col and sig_col in df.columns:
                sort_col = sig_col

        if sort_col and sort_col in df.columns:
            df = df.sort_values(sort_col, ascending=ascending, na_position="last")

        if len(df) > limit:
            df = df.head(limit)
            print(f"  Limited to {limit} events (sorted by {sort_col or 'order'})")
    else:
        print(f"  DuckDB filtered to {len(df)} events")

    features = []
    for idx, row in df.iterrows():
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

        if "event_id" not in properties and id_col:
            properties["event_id"] = properties.get(id_col, idx)
        elif "event_id" not in properties:
            properties["event_id"] = idx

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
            "properties": properties,
        })

    time_range = {"min": None, "max": None, "granularity": "daily"}
    if time_col and len(df) > 0:
        times = pd.to_datetime(df[time_col])
        time_range["min"] = int(times.min().timestamp() * 1000)
        time_range["max"] = int(times.max().timestamp() * 1000)

    primary_item = items[0] if items else {}
    if not features and event_type == "wildfire":
        perimeter_gap = build_empty_wildfire_perimeter_response(
            order,
            primary_item,
            source_id,
            get_source_from_catalog_func=get_source_from_catalog_func,
        )
        if perimeter_gap:
            return perimeter_gap

    source_info = [{
        "id": source_id,
        "name": metadata.get("source_name", source_id),
        "url": metadata.get("source_url", ""),
    }]

    response = {
        "type": "events",
        "data_type": "events",
        "source_id": source_id,
        "event_type": event_type,
        "geojson": {"type": "FeatureCollection", "features": features},
        "time_range": time_range,
        "summary": summary or f"Showing {len(features)} {event_type} events",
        "count": len(features),
        "sources": source_info,
    }
    default_time_note = _build_default_time_note(items)
    if default_time_note:
        response["data_note"] = default_time_note
    return response
