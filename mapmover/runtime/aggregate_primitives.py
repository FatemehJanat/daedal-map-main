from pathlib import Path


def source_has_metrics(catalog_source: dict | None) -> bool:
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


def source_geojson_shape(catalog_source: dict | None) -> str:
    return str((catalog_source or {}).get("geojson_shape") or "").strip().lower()


def source_is_location_shape(catalog_source: dict | None) -> bool:
    return source_geojson_shape(catalog_source) == "location_shape"


def source_has_aggregate_files(
    catalog_source: dict | None,
    *,
    data_root: Path,
    resolve_aggregate_admin2_dir_func,
) -> bool:
    files = (catalog_source or {}).get("files") or {}
    if not isinstance(files, dict):
        files = {}
    if any(key in files for key in ("yearly", "rolling_10y", "rolling_20y")):
        return True

    source_path = (catalog_source or {}).get("path")
    if not source_path:
        return False
    aggregate_dir = resolve_aggregate_admin2_dir_func(str(data_root / source_path))
    candidates = (
        aggregate_dir / "yearly.parquet",
        aggregate_dir / "rolling_10y.parquet",
        aggregate_dir / "rolling_20y.parquet",
    )
    return any(path.exists() for path in candidates)


def source_supports_aggregate_mode(
    catalog_source: dict | None,
    *,
    source_is_location_shape_func,
    source_has_aggregate_files_func,
) -> bool:
    if source_is_location_shape_func(catalog_source):
        return False
    data_type = (catalog_source or {}).get("data_type")
    if isinstance(data_type, list):
        if "events" in data_type and "metrics" not in data_type:
            return False
    elif data_type == "events":
        return False
    return source_has_aggregate_files_func(catalog_source)


def apply_aggregate_query_hints(item: dict, query: str) -> None:
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
