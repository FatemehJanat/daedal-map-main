from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from mapmover.api_query_runtime import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    api_source_ready,
    execute_dataset_query,
    get_api_source_columns,
    get_api_source_spec,
    get_api_source_time_bounds,
)
from mapmover.geography import get_country_names_from_codes


router = APIRouter()


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _error_response(
    request_id: str | None,
    code: str,
    message: str,
    status_code: int,
    *,
    details: dict[str, Any] | None = None,
    retry_hint: str | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {
        "request_id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if details:
        payload["error"]["details"] = details
    if retry_hint:
        payload["error"]["retry_hint"] = retry_hint
    return JSONResponse(payload, status_code=status_code)


def _normalize_request_id(payload: dict[str, Any]) -> str | None:
    request_id = payload.get("request_id")
    if request_id is None:
        return None
    request_id = str(request_id).strip()
    return request_id or None


def _validate_metrics(
    spec,
    metrics: Any,
    *,
    request_id: str | None,
) -> tuple[list[str] | None, JSONResponse | None]:
    if not isinstance(metrics, list) or not metrics:
        return None, _error_response(
            request_id,
            "metric_not_available",
            "At least one valid metric is required.",
            400,
            retry_hint="Choose one or more published metrics for this source.",
        )

    normalized_metrics = [str(metric).strip() for metric in metrics if str(metric).strip()]
    if not normalized_metrics:
        return None, _error_response(
            request_id,
            "metric_not_available",
            "At least one valid metric is required.",
            400,
            retry_hint="Choose one or more published metrics for this source.",
        )

    for metric in normalized_metrics:
        if metric not in spec.metrics:
            return None, _error_response(
                request_id,
                "metric_not_available",
                f"Metric '{metric}' is not available for source '{spec.source_id}'.",
                400,
                retry_hint="Choose a metric listed for this source in the catalog.",
            )

    return normalized_metrics, None


@router.post("/api/v1/query/dataset")
async def query_dataset(req: Request):
    try:
        payload = await req.json()
    except Exception:
        return _error_response(
            None,
            "invalid_request",
            "Request body must be valid JSON.",
            400,
            retry_hint="Send a JSON body matching the query_dataset contract.",
        )

    request_id = _normalize_request_id(payload)
    if not request_id:
        return _error_response(
            None,
            "invalid_request",
            "request_id is required.",
            400,
            retry_hint="Include a stable request_id in the JSON body.",
        )

    source_id = str(payload.get("source_id") or "").strip()
    if not source_id:
        return _error_response(
            request_id,
            "unknown_source",
            "source_id is required.",
            404,
            retry_hint="Choose a published source_id from the catalog.",
        )

    spec = get_api_source_spec(source_id)
    if spec is None:
        return _error_response(
            request_id,
            "unknown_source",
            f"Source '{source_id}' is not available on the API lane.",
            404,
            retry_hint="Choose a published source_id from the catalog.",
        )

    if not api_source_ready(spec):
        return _error_response(
            request_id,
            "source_not_api_ready",
            f"Source '{source_id}' is not available in this runtime.",
            503,
            retry_hint="Try again in a runtime with the published source data installed.",
        )

    metrics, metrics_error = _validate_metrics(spec, payload.get("metrics"), request_id=request_id)
    if metrics_error:
        return metrics_error

    filters = payload.get("filters") or {}
    if not isinstance(filters, dict):
        return _error_response(
            request_id,
            "invalid_request",
            "filters must be an object.",
            400,
            retry_hint="Send filters as a JSON object.",
        )

    region_ids = filters.get("region_ids") or []
    if region_ids and (not isinstance(region_ids, list) or any(not str(value).strip() for value in region_ids)):
        return _error_response(
            request_id,
            "location_not_supported",
            "region_ids must be a non-empty list of ids.",
            400,
            retry_hint="Pass region_ids as a list of ISO/admin loc_ids.",
        )
    normalized_region_ids = []
    seen_region_ids: set[str] = set()
    for value in region_ids:
        normalized_value = str(value).strip().upper()
        if normalized_value and normalized_value not in seen_region_ids:
            seen_region_ids.add(normalized_value)
            normalized_region_ids.append(normalized_value)

    time_filter = filters.get("time") or {}
    if time_filter and not isinstance(time_filter, dict):
        return _error_response(
            request_id,
            "invalid_time_range",
            "time must be an object.",
            400,
            retry_hint="Pass time as {year} or {year_start, year_end}.",
        )
    if spec.time_field is None and time_filter:
        return _error_response(
            request_id,
            "invalid_time_range",
            f"Source '{spec.source_id}' does not support time filters.",
            400,
            retry_hint="Remove time filters for static sources.",
        )
    if spec.time_field is not None and not time_filter:
        return _error_response(
            request_id,
            "invalid_time_range",
            "time is required for this source.",
            400,
            retry_hint="Pass time as {year} or {year_start, year_end}.",
        )

    exact_filters: dict[str, Any] = {}
    in_filters: dict[str, list[Any]] = {}
    hierarchical_prefix_filters: dict[str, list[str]] = {}
    compare_filters: list[tuple[str, str, Any]] = []
    normalized_time: dict[str, int] = {}

    if normalized_region_ids:
        if spec.location_filter_mode == "country_name_or_hierarchical_loc_id":
            prefix_region_ids = [value for value in normalized_region_ids if value.startswith("X")]
            country_region_ids = [value for value in normalized_region_ids if not value.startswith("X")]
            if prefix_region_ids:
                hierarchical_prefix_filters[spec.location_field] = prefix_region_ids
            if country_region_ids:
                country_names = [str(name).strip().upper() for name in get_country_names_from_codes(country_region_ids)]
                country_names = [name for name in country_names if name]
                lookup_field = spec.location_lookup_field or "country"
                if country_names:
                    in_filters[lookup_field] = country_names
        else:
            hierarchical_prefix_filters[spec.location_field] = normalized_region_ids

    year = time_filter.get("year")
    year_start = time_filter.get("year_start")
    year_end = time_filter.get("year_end")
    if spec.time_field is not None and year is not None:
        try:
            coerced_year = int(year)
            exact_filters[spec.time_field] = coerced_year
            normalized_time["year_start"] = coerced_year
            normalized_time["year_end"] = coerced_year
        except (TypeError, ValueError):
            return _error_response(
                request_id,
                "invalid_time_range",
                "time.year must be an integer.",
                400,
                retry_hint="Use an integer year value.",
            )
    elif spec.time_field is not None:
        coerced_year_start = None
        coerced_year_end = None
        if year_start is not None:
            try:
                coerced_year_start = int(year_start)
                normalized_time["year_start"] = coerced_year_start
                compare_filters.append((spec.time_field, ">=", coerced_year_start))
            except (TypeError, ValueError):
                return _error_response(
                    request_id,
                    "invalid_time_range",
                    "time.year_start must be an integer.",
                    400,
                    retry_hint="Use an integer year_start value.",
                )
        if year_end is not None:
            try:
                coerced_year_end = int(year_end)
                normalized_time["year_end"] = coerced_year_end
                compare_filters.append((spec.time_field, "<=", coerced_year_end))
            except (TypeError, ValueError):
                return _error_response(
                    request_id,
                    "invalid_time_range",
                    "time.year_end must be an integer.",
                    400,
                    retry_hint="Use an integer year_end value.",
                )
        if coerced_year_start is not None and coerced_year_end is not None and coerced_year_start > coerced_year_end:
            return _error_response(
                request_id,
                "invalid_time_range",
                "year_start cannot be greater than year_end.",
                400,
                retry_hint="Use a time range where year_start is less than or equal to year_end.",
            )

    equals_filters = filters.get("equals") or {}
    if equals_filters:
        if not isinstance(equals_filters, dict):
            return _error_response(
                request_id,
                "field_not_filterable",
                "equals filters must be an object.",
                400,
                retry_hint="Send equals as a JSON object of field/value pairs.",
            )
        for field, value in equals_filters.items():
            field_name = str(field).strip()
            if field_name not in spec.filterable_fields:
                return _error_response(
                    request_id,
                    "field_not_filterable",
                    f"Field '{field_name}' is not filterable for source '{spec.source_id}'.",
                    400,
                    retry_hint="Only use filterable fields published for this source.",
                )
            exact_filters[field_name] = value

    raw_compare_filters = filters.get("compare") or []
    if raw_compare_filters:
        if not isinstance(raw_compare_filters, list):
            return _error_response(
                request_id,
                "field_not_filterable",
                "compare filters must be a list.",
                400,
                retry_hint="Send compare as a list of {field, op, value} objects.",
            )
        available_compare_fields = spec.filterable_fields | {spec.metrics[metric].column for metric in metrics}
        for entry in raw_compare_filters:
            if not isinstance(entry, dict):
                return _error_response(
                    request_id,
                    "field_not_filterable",
                    "Each compare filter must be an object.",
                    400,
                    retry_hint="Send compare as a list of {field, op, value} objects.",
                )
            field_name = str(entry.get("field") or "").strip()
            op = str(entry.get("op") or "").strip()
            value = entry.get("value")
            if field_name not in available_compare_fields:
                return _error_response(
                    request_id,
                    "field_not_filterable",
                    f"Field '{field_name}' is not filterable for source '{spec.source_id}'.",
                    400,
                    retry_hint="Only compare against filterable fields or selected metric columns.",
                )
            if op not in {"=", "!=", ">", ">=", "<", "<="}:
                return _error_response(
                    request_id,
                    "field_not_filterable",
                    f"Operator '{op}' is not supported.",
                    400,
                    retry_hint="Use one of =, !=, >, >=, <, <=.",
                )
            compare_filters.append((field_name, op, value))

    requested_limit = payload.get("limit", spec.default_limit)
    try:
        limit = int(requested_limit)
    except (TypeError, ValueError):
        return _error_response(
            request_id,
            "invalid_limit",
            "limit must be an integer.",
            400,
            retry_hint="Use an integer limit within the published source ceiling.",
        )

    if limit <= 0:
        return _error_response(
            request_id,
            "invalid_limit",
            "limit must be greater than zero.",
            400,
            retry_hint="Use a positive integer limit.",
        )

    if limit > spec.max_limit:
        return _error_response(
            request_id,
            "result_too_large",
            f"limit {limit} exceeds the maximum of {spec.max_limit}.",
            400,
            retry_hint=f"Reduce limit to {spec.max_limit} or less.",
        )

    sort = payload.get("sort") or []
    if sort and not isinstance(sort, list):
        return _error_response(
            request_id,
            "invalid_sort_field",
            "sort must be a list.",
            400,
            retry_hint="Send sort as a list of {field, direction} objects.",
        )

    metric_columns = [spec.metrics[metric].column for metric in metrics]
    default_sort_field = metric_columns[0] if metric_columns else spec.time_field
    sort_entries = sort or [{"field": default_sort_field, "direction": "asc"}]
    normalized_sort: list[dict[str, str]] = []
    sort_items: list[tuple[str, str]] = []
    for entry in sort_entries:
        if not isinstance(entry, dict):
            return _error_response(
                request_id,
                "invalid_sort_field",
                "Each sort item must be an object.",
                400,
                retry_hint="Send sort as a list of {field, direction} objects.",
            )
        sort_field = str(entry.get("field") or "").strip()
        sort_direction = str(entry.get("direction") or "asc").strip().lower()
        if not sort_field:
            return _error_response(
                request_id,
                "invalid_sort_field",
                "Each sort item must include a field.",
                400,
                retry_hint="Send sort as a list of {field, direction} objects.",
            )
        if sort_direction not in {"asc", "desc"}:
            return _error_response(
                request_id,
                "invalid_sort_field",
                "sort.direction must be 'asc' or 'desc'.",
                400,
                retry_hint="Use sort.direction of 'asc' or 'desc'.",
            )
        if sort_field not in spec.sortable_fields:
            return _error_response(
                request_id,
                "invalid_sort_field",
                f"Field '{sort_field}' is not sortable for source '{spec.source_id}'.",
                400,
                retry_hint="Choose a published sortable field for this source.",
            )
        normalized_sort.append({"field": sort_field, "direction": sort_direction})
        sort_items.append((sort_field, sort_direction))

    available_columns = get_api_source_columns(spec)
    if spec.time_field in available_columns:
        available_start, available_end = get_api_source_time_bounds(spec)
        if available_start is not None and available_end is not None:
            requested_year_start = normalized_time.get("year", normalized_time.get("year_start"))
            requested_year_end = normalized_time.get("year", normalized_time.get("year_end"))
            if requested_year_start is not None and requested_year_start < available_start:
                return _error_response(
                    request_id,
                    "time_range_out_of_bounds",
                    f"This source does not contain data for {requested_year_start}.",
                    400,
                    details={
                        "available_start": available_start,
                        "available_end": available_end,
                        "requested_year_start": requested_year_start,
                        "requested_year_end": requested_year_end,
                    },
                    retry_hint="Request a year range within the published coverage for this source.",
                )
            if requested_year_end is not None and requested_year_end > available_end:
                return _error_response(
                    request_id,
                    "time_range_out_of_bounds",
                    f"This source does not contain data for {requested_year_end}.",
                    400,
                    details={
                        "available_start": available_start,
                        "available_end": available_end,
                        "requested_year_start": requested_year_start,
                        "requested_year_end": requested_year_end,
                    },
                    retry_hint="Request a year range within the published coverage for this source.",
                )

    output = payload.get("output") or {}
    if output and not isinstance(output, dict):
        return _error_response(
            request_id,
            "invalid_request",
            "output must be an object.",
            400,
            retry_hint="Send output as a JSON object.",
        )
    output_format = str(output.get("format") or "rows").strip().lower()
    if output_format != "rows":
        return _error_response(
            request_id,
            "invalid_request",
            "Only output.format='rows' is supported in v1.",
            400,
            retry_hint="Use output.format='rows'.",
        )
    include_provenance = bool(output.get("include_provenance", False))

    select_columns = [spec.location_field] + metric_columns
    if spec.time_field:
        select_columns.insert(1, spec.time_field)
    for sort_field, _sort_direction in sort_items:
        if sort_field not in select_columns:
            select_columns.append(sort_field)

    rows = execute_dataset_query(
        spec,
        select_columns=select_columns,
        exact_filters=exact_filters or None,
        in_filters=in_filters or None,
        hierarchical_prefix_filters=hierarchical_prefix_filters or None,
        compare_filters=compare_filters or None,
        sort_items=sort_items,
        limit=limit,
    )

    response_rows: list[dict[str, Any]] = []
    null_only_rows_omitted = 0
    for row in rows:
        shaped = {
            "loc_id": _json_safe_value(row.get(spec.location_field)),
        }
        if spec.time_field:
            shaped["year"] = _json_safe_value(row.get(spec.time_field))
        non_null_metric_count = 0
        for metric in metrics:
            metric_column = spec.metrics[metric].column
            metric_value = _json_safe_value(row.get(metric_column))
            shaped[metric] = metric_value
            if metric_value is not None:
                non_null_metric_count += 1
        if non_null_metric_count == 0:
            null_only_rows_omitted += 1
            continue
        response_rows.append(shaped)

    filters_applied: dict[str, Any] = {}
    if normalized_region_ids:
        filters_applied["region_ids"] = normalized_region_ids
    if normalized_time:
        filters_applied["time"] = normalized_time
    if equals_filters:
        filters_applied["equals"] = equals_filters
    if raw_compare_filters:
        filters_applied["compare"] = raw_compare_filters

    warnings: list[dict[str, Any]] = []
    if null_only_rows_omitted:
        warnings.append(
            {
                "code": "null_only_rows_omitted",
                "message": "Rows where all requested metrics were null were omitted.",
                "count": null_only_rows_omitted,
            }
        )

    payload_out: dict[str, Any] = {
        "request_id": request_id,
        "capability_id": "dataset_query",
        "source_id": spec.source_id,
        "metrics": metrics,
        "query_mode": spec.query_mode,
        "filters_applied": filters_applied,
        "sort": normalized_sort,
        "row_count": len(response_rows),
        "truncated": False,
        "rows": response_rows,
        "warnings": warnings,
    }
    if include_provenance:
        payload_out["provenance"] = {
            "pack_id": spec.pack_id,
            "source_ids": [spec.source_id],
        }

    return JSONResponse(payload_out)
