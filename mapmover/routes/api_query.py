from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
import hashlib
import json
import os
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from mapmover.api_query_commercial import (
    COMMERCIAL_ACCESS_CHECK_PATH,
    commercial_access_enabled,
    commercial_access_internal_token,
    commercial_access_response,
    forwarded_commercial_headers,
    get_trusted_artifact_token,
    pack_requires_commercial_access,
    post_commercial_access,
    pricing_amount_usdc_base_units,
    settle_commercial_access,
    settlement_headers,
)
from mapmover.api_query_limits import QueryConcurrencyLimitError, acquire_query_slot
from mapmover.api_query_scope import (
    build_query_scope,
    format_query_time_value,
    normalize_region_ids,
    parse_time_filter,
    query_scope_rejection,
    validate_metrics,
)
from mapmover.api_query_shared import (
    build_api_error_response,
    build_request_fingerprint_payload,
    get_api_analytics_metadata,
    json_safe_value,
    normalize_api_request_id,
    request_fingerprint as build_request_fingerprint_hash,
)
from mapmover.auth_context import get_authenticated_user
from mapmover.api_query_runtime import (
    api_source_ready,
    execute_dataset_query,
    get_api_source_columns,
    get_api_source_spec,
    get_api_source_time_bounds,
    is_temporal_time_field,
    normalize_time_granularity,
    resolve_effective_time_spec,
    resolve_pack_source_for_query,
)
from mapmover.geography import get_country_names_from_codes
from mapmover.logging_analytics import hash_ip_for_analytics, log_api_query_event
from mapmover.runtime.filter_primitives import resolve_exact_id_filter_field
from mapmover.security import get_client_ip, rate_limiter


router = APIRouter()

EXACT_ID_ALIAS_FIELDS = {"event_id", "storm_id", "fire_id", "id"}


def _get_request_ip(request: Request) -> str | None:
    return get_client_ip(request)


def _coerce_temporal_bound_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day)
    else:
        text = str(value or "").strip()
        if not text:
            return None
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve_api_filter_field_alias(
    spec,
    field_name: str,
    *,
    available_columns: set[str],
) -> str:
    field = str(field_name or "").strip()
    if not field:
        return field
    if field in spec.filterable_fields:
        return field
    if field not in EXACT_ID_ALIAS_FIELDS:
        return field
    return resolve_exact_id_filter_field(
        field,
        available_columns,
        metadata={},
        event_type=str(spec.pack_id or spec.source_id or ""),
    )


async def execute_query_dataset_payload(req: Request, payload: dict[str, Any]) -> Response:
    started_at = time.perf_counter()
    auth_user = get_authenticated_user(req)
    auth_user_id = str((auth_user or {}).get("id") or "").strip() or None
    ip_hash = hash_ip_for_analytics(_get_request_ip(req))
    caller_key = auth_user_id or ip_hash or "anonymous"
    user_agent = req.headers.get("user-agent", "").strip() or None
    payment_rail: str | None = None
    request_fingerprint: str | None = None
    query_scope: dict[str, Any] | None = None

    def error_response(
        request_id: str | None,
        code: str,
        message: str,
        status_code: int,
        *,
        details: dict[str, Any] | None = None,
        retry_hint: str | None = None,
        pack_id: str | None = None,
        source_id: str | None = None,
    ) -> JSONResponse:
        req.state.analytics_error_code = code
        req.state.analytics_concurrency_rejected = code == "rate_limited"
        response = build_api_error_response(
            request_id,
            code,
            message,
            status_code,
            details=details,
            retry_hint=retry_hint,
        )
        if request_id and source_id:
            payload_size_bytes = len(response.body or b"")
            log_api_query_event(
                request_id=request_id,
                capability_id="dataset_query",
                pack_id=pack_id or "unknown",
                source_id=source_id,
                decision="deny",
                payment_rail=None,
                auth_user_id=auth_user_id,
                ip_hash=ip_hash,
                user_agent=user_agent,
                execution_latency_ms=int((time.perf_counter() - started_at) * 1000),
                row_count=0,
                response_size_bytes=payload_size_bytes,
                status_code=status_code,
                warnings_count=0,
                error_code=code,
                metadata=get_api_analytics_metadata(
                    req,
                    request_fingerprint=request_fingerprint,
                    query_scope=query_scope,
                    access_lane="paid" if payment_rail else "free",
                ),
            )
        return response

    request_id = normalize_api_request_id(payload)
    if not request_id:
        return build_api_error_response(
            None,
            "invalid_request",
            "request_id is required.",
            400,
            retry_hint="Include a stable request_id in the JSON body.",
        )
    req.state.analytics_request_id = request_id

    source_id = str(payload.get("source_id") or "").strip()
    pack_id = str(payload.get("pack_id") or "").strip()
    req.state.analytics_source_id = source_id or None
    req.state.analytics_pack_id = pack_id or None

    if source_id and pack_id:
        return error_response(
            request_id,
            "invalid_request",
            "Provide either source_id or pack_id, not both.",
            400,
            retry_hint="Choose a direct source_id or a pack_id-based query, but not both.",
            pack_id=pack_id,
            source_id=source_id,
        )

    if not source_id and not pack_id:
        return error_response(
            request_id,
            "unknown_source",
            "source_id or pack_id is required.",
            404,
            retry_hint="Choose a published source_id from the catalog, or a pack_id with supported metrics.",
            source_id="unknown",
        )

    requested_metrics_raw = payload.get("metrics")
    requested_metrics = [str(metric).strip() for metric in (requested_metrics_raw or []) if str(metric).strip()]
    time_filter = payload.get("filters", {}).get("time") if isinstance(payload.get("filters"), dict) else None
    requested_granularity = None
    if isinstance(time_filter, dict):
        requested_granularity = time_filter.get("granularity")
    normalized_requested_granularity = normalize_time_granularity(requested_granularity)

    resolved_from_pack = False
    if not source_id and pack_id:
        pack_resolution = resolve_pack_source_for_query(
            pack_id,
            requested_metrics,
            requested_granularity=requested_granularity,
        )
        resolution = str(pack_resolution.get("resolution") or "")
        if resolution == "unknown_metrics":
            return error_response(
                request_id,
                "metric_not_available",
                "One or more metrics are not available in this pack.",
                400,
                details={"unknown_metrics": pack_resolution.get("unknown_metrics") or []},
                retry_hint="Choose metrics listed for this pack in the catalog.",
                pack_id=pack_id,
                source_id="unknown",
            )
        if resolution == "multi_source_required":
            return error_response(
                request_id,
                "multi_source_not_supported",
                "This pack requires multiple sources for the requested metrics.",
                400,
                details={"required_sources": pack_resolution.get("required_sources") or []},
                retry_hint="Choose metrics that can be satisfied by one source, or query a specific source_id.",
                pack_id=pack_id,
                source_id="unknown",
            )
        if resolution == "unsupported_granularity":
            return error_response(
                request_id,
                "invalid_time_range",
                f"Requested granularity '{requested_granularity}' is not supported for pack '{pack_id}'.",
                400,
                details={"supported_granularities": pack_resolution.get("supported_granularities") or []},
                retry_hint="Choose one of the supported granularities for this pack.",
                pack_id=pack_id,
                source_id="unknown",
            )
        if resolution == "unknown_pack_sources":
            return error_response(
                request_id,
                "unknown_source",
                f"Pack '{pack_id}' does not have a published API-ready execution source.",
                404,
                retry_hint="Choose a different published pack, or query a published source_id directly.",
                pack_id=pack_id,
                source_id="unknown",
            )
        if resolution == "ambiguous_default_source":
            return error_response(
                request_id,
                "multi_source_not_supported",
                f"Pack '{pack_id}' needs metrics or a specific source_id to choose the right execution source.",
                400,
                details={"required_sources": pack_resolution.get("required_sources") or []},
                retry_hint="Provide metrics, or query a specific source_id from this pack.",
                pack_id=pack_id,
                source_id="unknown",
            )
        source_id = str(pack_resolution.get("selected_source_id") or "").strip()
        if not source_id:
            return error_response(
                request_id,
                "unknown_source",
                f"Pack '{pack_id}' could not be resolved to a published source.",
                404,
                retry_hint="Choose a published source_id from the catalog, or retry with a more specific pack request.",
                pack_id=pack_id,
                source_id="unknown",
            )
        req.state.analytics_source_id = source_id
        resolved_from_pack = True

    spec = get_api_source_spec(source_id)
    if spec is None:
        retry_hint = (
            "Choose a published source_id from the catalog."
            if not pack_id
            else "Choose a published source within this pack from the catalog."
        )
        return error_response(
            request_id,
            "unknown_source",
            f"Source '{source_id}' is not available on the API lane.",
            404,
            retry_hint=retry_hint,
            pack_id=pack_id or None,
            source_id=source_id or "unknown",
        )

    if not api_source_ready(spec):
        return error_response(
            request_id,
            "source_not_api_ready",
            f"Source '{source_id}' is not available in this runtime.",
            503,
            retry_hint="Try again in a runtime with the published source data installed.",
            pack_id=spec.pack_id,
            source_id=source_id,
        )
    req.state.analytics_pack_id = spec.pack_id
    if resolved_from_pack:
        req.state.analytics_pack_id = pack_id or spec.pack_id

    available_columns = get_api_source_columns(spec)

    spec = resolve_effective_time_spec(spec, time_filter if isinstance(time_filter, dict) else None)

    if normalized_requested_granularity:
        source_granularity = normalize_time_granularity(spec.time_granularity)
        if source_granularity and normalized_requested_granularity != source_granularity:
            return error_response(
                request_id,
                "invalid_time_range",
                f"Requested granularity '{requested_granularity}' does not match source '{spec.source_id}'.",
                400,
                details={
                    "requested_granularity": normalized_requested_granularity,
                    "source_granularity": source_granularity,
                },
                retry_hint="Choose a source or pack query that matches the requested granularity.",
                pack_id=pack_id or spec.pack_id,
                source_id=source_id,
            )

    metrics, metrics_error = validate_metrics(spec, payload.get("metrics"), request_id=request_id)
    if metrics_error:
        payload_size_bytes = len(metrics_error.body or b"")
        log_api_query_event(
            request_id=request_id,
            capability_id="dataset_query",
            pack_id=spec.pack_id,
            source_id=spec.source_id,
            decision="deny",
            payment_rail=None,
            auth_user_id=auth_user_id,
            ip_hash=ip_hash,
            user_agent=user_agent,
            execution_latency_ms=int((time.perf_counter() - started_at) * 1000),
            row_count=0,
            response_size_bytes=payload_size_bytes,
            status_code=metrics_error.status_code,
            warnings_count=0,
            error_code="metric_not_available",
            metadata=get_api_analytics_metadata(
                req,
                request_fingerprint=request_fingerprint,
                query_scope=query_scope,
                access_lane="paid" if pack_requires_commercial_access(spec.pack_id) else "free",
            ),
        )
        return metrics_error

    filters = payload.get("filters") or {}
    if not isinstance(filters, dict):
        return error_response(
            request_id,
            "invalid_request",
            "filters must be an object.",
            400,
            retry_hint="Send filters as a JSON object.",
            pack_id=spec.pack_id,
            source_id=source_id,
        )

    region_ids = filters.get("region_ids") or []
    if region_ids and (not isinstance(region_ids, list) or any(not str(value).strip() for value in region_ids)):
        return error_response(
            request_id,
            "location_not_supported",
            "region_ids must be a non-empty list of ids.",
            400,
            retry_hint="Pass region_ids as a list of ISO/admin loc_ids.",
            pack_id=spec.pack_id,
            source_id=source_id,
        )
    normalized_region_ids, region_error = normalize_region_ids(region_ids)
    if region_error:
        error_code = "invalid_region_id" if "invalid characters" in region_error else "location_not_supported"
        return error_response(
            request_id,
            error_code,
            region_error,
            400,
            retry_hint="Use valid loc_ids from the catalog such as G_JPN or C_US_06_001.",
            pack_id=spec.pack_id,
            source_id=source_id,
        )

    time_filter = filters.get("time") or {}
    if time_filter and not isinstance(time_filter, dict):
        return error_response(
            request_id,
            "invalid_time_range",
            "time must be an object.",
            400,
            retry_hint="Pass time as {value} or {start, end}.",
            pack_id=spec.pack_id,
            source_id=source_id,
        )
    if spec.time_field is None and time_filter:
        return error_response(
            request_id,
            "invalid_time_range",
            f"Source '{spec.source_id}' does not support time filters.",
            400,
            retry_hint="Remove time filters for static sources.",
            pack_id=spec.pack_id,
            source_id=source_id,
        )
    if spec.time_field is not None and not time_filter:
        return error_response(
            request_id,
            "invalid_time_range",
            "time is required for this source.",
            400,
            retry_hint="Pass time as {value} or {start, end}.",
            pack_id=spec.pack_id,
            source_id=source_id,
        )

    exact_filters: dict[str, Any] = {}
    in_filters: dict[str, list[Any]] = {}
    hierarchical_prefix_filters: dict[str, list[str]] = {}
    compare_filters: list[tuple[str, str, Any]] = []
    normalized_time: dict[str, Any] = {}

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

    try:
        parsed_time, parsed_exact_filters, parsed_compare_filters = parse_time_filter(spec, time_filter)
        normalized_time.update(parsed_time)
        requested_granularity = time_filter.get("granularity") if isinstance(time_filter, dict) else None
        normalized_granularity = normalize_time_granularity(requested_granularity)
        if normalized_granularity:
            normalized_time["granularity"] = normalized_granularity
        exact_filters.update(parsed_exact_filters)
        compare_filters.extend(parsed_compare_filters)
    except ValueError as exc:
        message = str(exc)
        if message == "start_after_end":
            return error_response(
                request_id,
                "invalid_time_range",
                "time.start cannot be greater than time.end.",
                400,
                retry_hint="Use a time range where start is less than or equal to end.",
                pack_id=spec.pack_id,
                source_id=source_id,
            )
        retry_hint = (
            "Use ISO 8601 values for this source's time field."
            if is_temporal_time_field(spec)
            else "Use integer values for this source's time field."
        )
        return error_response(
            request_id,
            "invalid_time_range",
            "time filters are invalid for this source.",
            400,
            retry_hint=retry_hint,
            pack_id=spec.pack_id,
            source_id=source_id,
        )

    equals_filters = filters.get("equals") or {}
    if equals_filters:
        if not isinstance(equals_filters, dict):
            return error_response(
                request_id,
                "field_not_filterable",
                "equals filters must be an object.",
                400,
                retry_hint="Send equals as a JSON object of field/value pairs.",
                pack_id=spec.pack_id,
                source_id=source_id,
            )
        for field, value in equals_filters.items():
            field_name = str(field).strip()
            resolved_field_name = _resolve_api_filter_field_alias(
                spec,
                field_name,
                available_columns=available_columns,
            )
            if resolved_field_name not in spec.filterable_fields and resolved_field_name not in available_columns:
                available = sorted(spec.filterable_fields)
                return error_response(
                    request_id,
                    "field_not_filterable",
                    f"Field '{field_name}' is not filterable for source '{spec.source_id}'. Filterable fields are: {', '.join(available)}.",
                    400,
                    retry_hint=f"Use one of the filterable fields: {', '.join(available)}.",
                    pack_id=spec.pack_id,
                    source_id=source_id,
                )
            exact_filters[resolved_field_name] = value

    raw_compare_filters = filters.get("compare") or []
    if raw_compare_filters:
        if not isinstance(raw_compare_filters, list):
            return error_response(
                request_id,
                "field_not_filterable",
                "compare filters must be a list.",
                400,
                retry_hint="Send compare as a list of {field, op, value} objects.",
                pack_id=spec.pack_id,
                source_id=source_id,
            )
        available_compare_fields = spec.filterable_fields | {spec.metrics[metric].column for metric in metrics}
        for entry in raw_compare_filters:
            if not isinstance(entry, dict):
                return error_response(
                    request_id,
                    "field_not_filterable",
                    "Each compare filter must be an object.",
                    400,
                    retry_hint="Send compare as a list of {field, op, value} objects.",
                    pack_id=spec.pack_id,
                    source_id=source_id,
                )
            field_name = str(entry.get("field") or "").strip()
            op = str(entry.get("op") or "").strip()
            value = entry.get("value")
            resolved_field_name = _resolve_api_filter_field_alias(
                spec,
                field_name,
                available_columns=available_columns,
            )
            if resolved_field_name not in available_compare_fields and resolved_field_name not in available_columns:
                available = sorted(available_compare_fields)
                return error_response(
                    request_id,
                    "field_not_filterable",
                    f"Field '{field_name}' is not filterable for source '{spec.source_id}'. Filterable or selected metric fields are: {', '.join(available)}.",
                    400,
                    retry_hint=f"Use one of the filterable or selected metric fields: {', '.join(available)}.",
                    pack_id=spec.pack_id,
                    source_id=source_id,
                )
            if op not in {"=", "!=", ">", ">=", "<", "<="}:
                return error_response(
                    request_id,
                    "field_not_filterable",
                    f"Operator '{op}' is not supported.",
                    400,
                    retry_hint="Use one of =, !=, >, >=, <, <=.",
                    pack_id=spec.pack_id,
                    source_id=source_id,
                )
            compare_filters.append((resolved_field_name, op, value))

    requested_limit = payload.get("limit", spec.default_limit)
    try:
        limit = int(requested_limit)
    except (TypeError, ValueError):
        return error_response(
            request_id,
            "invalid_limit",
            "limit must be an integer.",
            400,
            retry_hint="Use an integer limit within the published source ceiling.",
            pack_id=spec.pack_id,
            source_id=source_id,
        )

    if limit <= 0:
        return error_response(
            request_id,
            "invalid_limit",
            "limit must be greater than zero.",
            400,
            retry_hint="Use a positive integer limit.",
            pack_id=spec.pack_id,
            source_id=source_id,
        )

    if limit > spec.max_limit:
        return error_response(
            request_id,
            "result_too_large",
            f"limit {limit} exceeds the maximum of {spec.max_limit}.",
            400,
            retry_hint=f"Reduce limit to {spec.max_limit} or less.",
            pack_id=spec.pack_id,
            source_id=source_id,
        )

    raw_sort = payload.get("sort") or []
    if raw_sort and isinstance(raw_sort, dict):
        sort = [raw_sort]
    else:
        sort = raw_sort
    if sort and not isinstance(sort, list):
        return error_response(
            request_id,
            "invalid_sort_field",
            "sort must be a list.",
            400,
            retry_hint="Send sort as a list of {field, direction} objects.",
            pack_id=spec.pack_id,
            source_id=source_id,
        )

    requested_sort_count = len(sort) if isinstance(sort, list) else 0
    metric_columns = [spec.metrics[metric].column for metric in metrics]
    default_sort_field = metric_columns[0] if metric_columns else spec.time_field
    sort_entries = sort or [{"field": default_sort_field, "direction": "asc"}]
    normalized_sort: list[dict[str, str]] = []
    sort_items: list[tuple[str, str]] = []
    for entry in sort_entries:
        if not isinstance(entry, dict):
            return error_response(
                request_id,
                "invalid_sort_field",
                "Each sort item must be an object.",
                400,
                retry_hint="Send sort as a list of {field, direction} objects.",
                pack_id=spec.pack_id,
                source_id=source_id,
            )
        sort_field = str(entry.get("field") or "").strip()
        sort_direction = str(entry.get("direction") or "asc").strip().lower()
        if not sort_field:
            return error_response(
                request_id,
                "invalid_sort_field",
                "Each sort item must include a field.",
                400,
                retry_hint="Send sort as a list of {field, direction} objects.",
                pack_id=spec.pack_id,
                source_id=source_id,
            )
        if sort_direction not in {"asc", "desc"}:
            return error_response(
                request_id,
                "invalid_sort_field",
                "sort.direction must be 'asc' or 'desc'.",
                400,
                retry_hint="Use sort.direction of 'asc' or 'desc'.",
                pack_id=spec.pack_id,
                source_id=source_id,
            )
        actual_sort_field = metric_columns[0] if sort_field == "value" and len(metric_columns) == 1 else sort_field
        if actual_sort_field not in spec.sortable_fields:
            return error_response(
                request_id,
                "invalid_sort_field",
                f"Field '{sort_field}' is not sortable for source '{spec.source_id}'.",
                400,
                retry_hint="Choose a published sortable field for this source.",
                pack_id=spec.pack_id,
                source_id=source_id,
            )
        normalized_sort.append({"field": sort_field, "direction": sort_direction})
        sort_items.append((actual_sort_field, sort_direction))

    available_start = None
    available_end = None
    available_columns = get_api_source_columns(spec)
    if spec.time_field in available_columns:
        available_start, available_end = get_api_source_time_bounds(spec)
        if available_start is not None and available_end is not None:
            requested_start = normalized_time.get("value", normalized_time.get("start"))
            requested_end = normalized_time.get("value", normalized_time.get("end"))
            requested_start_cmp = _coerce_temporal_bound_value(requested_start)
            requested_end_cmp = _coerce_temporal_bound_value(requested_end)
            available_start_cmp = _coerce_temporal_bound_value(available_start)
            available_end_cmp = _coerce_temporal_bound_value(available_end)
            if requested_start is not None and (
                (requested_start_cmp is not None and available_start_cmp is not None and requested_start_cmp < available_start_cmp)
                or (requested_start_cmp is None or available_start_cmp is None) and requested_start < available_start
            ):
                return error_response(
                    request_id,
                    "time_range_out_of_bounds",
                    f"This source does not contain data for {requested_start}.",
                    400,
                    details={
                        "available_start": available_start,
                        "available_end": available_end,
                        "requested_start": requested_start,
                        "requested_end": requested_end,
                    },
                    retry_hint="Request a time range within the published coverage for this source.",
                    pack_id=spec.pack_id,
                    source_id=source_id,
                )
            if requested_end is not None and (
                (requested_end_cmp is not None and available_end_cmp is not None and requested_end_cmp > available_end_cmp)
                or (requested_end_cmp is None or available_end_cmp is None) and requested_end > available_end
            ):
                return error_response(
                    request_id,
                    "time_range_out_of_bounds",
                    f"This source does not contain data for {requested_end}.",
                    400,
                    details={
                        "available_start": available_start,
                        "available_end": available_end,
                        "requested_start": requested_start,
                        "requested_end": requested_end,
                    },
                    retry_hint="Request a time range within the published coverage for this source.",
                    pack_id=spec.pack_id,
                    source_id=source_id,
                )

    output = payload.get("output") or {}
    if output and not isinstance(output, dict):
        return error_response(
            request_id,
            "invalid_request",
            "output must be an object.",
            400,
            retry_hint="Send output as a JSON object.",
            pack_id=spec.pack_id,
            source_id=source_id,
        )
    output_format = str(output.get("format") or "rows").strip().lower()
    if output_format != "rows":
        return error_response(
            request_id,
            "invalid_request",
            "Only output.format='rows' is supported in v1.",
            400,
            retry_hint="Use output.format='rows'.",
            pack_id=spec.pack_id,
            source_id=source_id,
        )
    include_provenance = bool(output.get("include_provenance", False))
    query_scope = build_query_scope(
        spec,
        normalized_region_ids=normalized_region_ids,
        normalized_time=normalized_time,
        raw_compare_filters=raw_compare_filters,
        normalized_sort=normalized_sort,
        requested_sort_count=requested_sort_count,
        metrics=metrics,
        limit=limit,
        output_format=output_format,
        available_start=available_start,
        available_end=available_end,
    )
    get_api_analytics_metadata(
        req,
        query_scope=query_scope,
        access_lane="paid" if pack_requires_commercial_access(spec.pack_id) else "free",
    )
    scope_rejection = query_scope_rejection(query_scope)
    if scope_rejection:
        return error_response(
            request_id,
            str(scope_rejection["code"]),
            str(scope_rejection["message"]),
            400,
            details=scope_rejection.get("details") if isinstance(scope_rejection.get("details"), dict) else None,
            retry_hint=str(scope_rejection.get("retry_hint") or ""),
            pack_id=spec.pack_id,
            source_id=source_id,
        )

    request_fingerprint_payload = build_request_fingerprint_payload(
        source_id=spec.source_id,
        pack_id=spec.pack_id,
        query_mode=spec.query_mode,
        metrics=metrics,
        normalized_region_ids=normalized_region_ids,
        normalized_time=normalized_time,
        equals_filters=equals_filters,
        compare_filters=compare_filters,
        normalized_sort=normalized_sort,
        limit=limit,
        output_format=output_format,
    )
    request_fingerprint = build_request_fingerprint_hash(request_fingerprint_payload)
    caller_binding = auth_user_id or ip_hash or "anonymous"

    settlement_id: str | None = None
    verifier_payload: dict[str, Any] | None = None
    payment_rail: str | None = None
    amount_charged_usdc_base_units: int | None = None
    artifact_token = get_trusted_artifact_token(req)
    if artifact_token is not None:
        token_limit = int(os.getenv("ARTIFACT_TOKEN_RATE_LIMIT", "20"))
        token_window = int(os.getenv("ARTIFACT_TOKEN_RATE_WINDOW_SECONDS", "60"))
        allowed, retry_after = rate_limiter.check(
            f"artifact_token:{artifact_token}",
            limit=token_limit,
            window_seconds=token_window,
        )
        if not allowed:
            return error_response(
                request_id,
                "rate_limited",
                "Too many requests for this access token. Please slow down and try again shortly.",
                429,
                retry_hint=f"Retry after {retry_after} seconds.",
                pack_id=spec.pack_id,
                source_id=source_id,
            )
        payment_rail = "trusted_artifact"
        token_id = hashlib.sha256(artifact_token.encode()).hexdigest()[:8]
        get_api_analytics_metadata(
            req,
            query_scope=query_scope,
            access_lane="trusted_artifact",
        )
        existing_meta = getattr(req.state, "analytics_metadata", {})
        existing_meta["artifact_token_id"] = token_id
        req.state.analytics_metadata = existing_meta
    elif pack_requires_commercial_access(spec.pack_id):
        if not commercial_access_enabled():
            return error_response(
                request_id,
                "commercial_access_unavailable",
                "This paid endpoint requires a hosted commercial-access verifier.",
                503,
                retry_hint="Use the free discovery endpoints or retry against a runtime with commercial access enabled.",
                pack_id=spec.pack_id,
                source_id=source_id,
            )
        if not commercial_access_internal_token():
            return error_response(
                request_id,
                "commercial_access_unavailable",
                "Commercial access verifier is not configured for this runtime.",
                503,
                retry_hint="Retry on the hosted runtime after verifier configuration is complete.",
                pack_id=spec.pack_id,
                source_id=source_id,
            )
        try:
            verifier_status, verifier_payload = await asyncio.to_thread(
                post_commercial_access,
                COMMERCIAL_ACCESS_CHECK_PATH,
                {
                    "request_id": request_id,
                    "capability_id": "dataset_query",
                    "resource": {
                        "method": "POST",
                        "path": "/api/v1/query/dataset",
                    },
                    "forwarded_headers": forwarded_commercial_headers(req),
                    "subject": {
                        "auth_present": bool(auth_user_id),
                        "user_id": auth_user_id,
                    },
                    "request_context": {
                        "pack_id": spec.pack_id,
                        "source_id": spec.source_id,
                        "request_fingerprint": request_fingerprint,
                        "limit": limit,
                        "query_mode": spec.query_mode,
                        "output_format": output_format,
                        "time_granularity": str(normalized_time.get("granularity") or "") or None,
                        "scope": query_scope,
                    },
                    "caller": {
                        "auth_user_id": auth_user_id,
                        "ip_hash": ip_hash,
                        "caller_binding": caller_binding,
                    },
                },
            )
        except Exception as exc:
            return error_response(
                request_id,
                "commercial_access_unavailable",
                f"Commercial access verifier failed: {exc}",
                503,
                retry_hint="Retry after the hosted verifier is available.",
                pack_id=spec.pack_id,
                source_id=source_id,
            )

        verifier_status_name = str((verifier_payload or {}).get("status") or "").strip().lower()
        payment_rail = str((verifier_payload or {}).get("rail") or "").strip() or None
        amount_charged_usdc_base_units = pricing_amount_usdc_base_units(verifier_payload)
        if verifier_status_name == "challenge":
            response = commercial_access_response(
                request_id,
                verifier_payload,
                pack_id=spec.pack_id,
                source_id=source_id,
            )
            req.state.analytics_error_code = str((verifier_payload or {}).get("code") or "commercial_access_required")
            payload_size_bytes = len(getattr(response, "body", b"") or b"")
            log_api_query_event(
                request_id=request_id,
                capability_id="dataset_query",
                pack_id=spec.pack_id,
                source_id=spec.source_id,
                decision="challenge",
                payment_rail=payment_rail,
                auth_user_id=auth_user_id,
                ip_hash=ip_hash,
                user_agent=user_agent,
                execution_latency_ms=int((time.perf_counter() - started_at) * 1000),
                row_count=0,
                response_size_bytes=payload_size_bytes,
                status_code=response.status_code,
                warnings_count=0,
                error_code=str((verifier_payload or {}).get("code") or "commercial_access_required"),
                query_granularity=str(normalized_time.get("granularity") or "") or None,
                amount_charged_usdc_base_units=amount_charged_usdc_base_units,
                revenue_attributed_usdc_base_units=None,
                metadata=get_api_analytics_metadata(
                    req,
                    request_fingerprint=request_fingerprint,
                    query_scope=query_scope,
                    access_lane="paid",
                ),
            )
            return response
        if verifier_status_name != "allow":
            verifier_context = (verifier_payload or {}).get("context") or {}
            verifier_details = verifier_context if isinstance(verifier_context, dict) and verifier_context else None
            verifier_retry_hint = str((verifier_payload or {}).get("retry_hint") or "").strip() or None
            return error_response(
                request_id,
                str((verifier_payload or {}).get("code") or "commercial_access_denied"),
                str((verifier_payload or {}).get("message") or "Commercial access denied."),
                int((verifier_payload or {}).get("http_status") or verifier_status or 403),
                details=verifier_details,
                retry_hint=verifier_retry_hint or "Retry after satisfying the requested commercial-access challenge.",
                pack_id=spec.pack_id,
                source_id=source_id,
            )
        settlement = (verifier_payload or {}).get("settlement") or {}
        settlement_id = str(settlement.get("settlement_id") or "").strip() or None

    select_columns = [spec.location_field] + metric_columns
    if spec.time_field:
        select_columns.insert(1, spec.time_field)
    for sort_field, _sort_direction in sort_items:
        if sort_field not in select_columns:
            select_columns.append(sort_field)

    try:
        async with acquire_query_slot(caller_key):
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
    except QueryConcurrencyLimitError as exc:
        return error_response(
            request_id,
            exc.code,
            exc.message,
            429,
            details=exc.details,
            retry_hint="Retry after in-flight requests complete or reduce caller concurrency.",
            pack_id=spec.pack_id,
            source_id=source_id,
        )

    response_rows: list[dict[str, Any]] = []
    null_only_rows_omitted = 0
    for row in rows:
        shaped = {
            "loc_id": json_safe_value(row.get(spec.location_field)),
        }
        if spec.time_field:
            shaped[spec.time_field] = json_safe_value(format_query_time_value(row.get(spec.time_field)))
        non_null_metric_count = 0
        for metric in metrics:
            metric_column = spec.metrics[metric].column
            metric_value = json_safe_value(row.get(metric_column))
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

    if settlement_id:
        try:
            settled, settlement_payload = await asyncio.to_thread(
                settle_commercial_access,
                request_id,
                settlement_id,
                success=True,
                request_fingerprint=request_fingerprint,
                caller_binding=caller_binding,
            )
        except Exception as exc:
            req.state.analytics_settlement_failed = True
            return error_response(
                request_id,
                "commercial_access_verifier_error",
                f"Commercial settlement failed: {exc}",
                502,
                retry_hint="Retry the paid request after verifier settlement is healthy.",
                pack_id=spec.pack_id,
                source_id=source_id,
            )
        if not settled:
            req.state.analytics_settlement_failed = True
            return error_response(
                request_id,
                str((settlement_payload or {}).get("code") or "commercial_access_verifier_error"),
                str((settlement_payload or {}).get("message") or "Commercial settlement failed."),
                int((settlement_payload or {}).get("http_status") or 502),
                retry_hint="Retry the paid request after verifier settlement is healthy.",
                pack_id=spec.pack_id,
                source_id=source_id,
            )

    response = JSONResponse(payload_out)
    if settlement_id:
        for key, value in settlement_headers(settlement_payload).items():
            response.headers[key] = value
    response_size_bytes = len(json.dumps(payload_out, ensure_ascii=False).encode("utf-8"))
    log_api_query_event(
        request_id=request_id,
        capability_id="dataset_query",
        pack_id=spec.pack_id,
        source_id=spec.source_id,
        decision="allow",
        payment_rail=payment_rail,
        auth_user_id=auth_user_id,
        ip_hash=ip_hash,
        user_agent=user_agent,
        execution_latency_ms=int((time.perf_counter() - started_at) * 1000),
        row_count=len(response_rows),
        response_size_bytes=response_size_bytes,
        status_code=200,
        warnings_count=len(warnings),
        error_code=None,
        query_granularity=str(normalized_time.get("granularity") or "") or None,
        settlement_id=settlement_id,
        amount_charged_usdc_base_units=amount_charged_usdc_base_units,
        revenue_attributed_usdc_base_units=amount_charged_usdc_base_units,
        metadata=get_api_analytics_metadata(
            req,
            request_fingerprint=request_fingerprint,
            query_scope=query_scope,
            access_lane="paid" if settlement_id or payment_rail else "free",
        ),
    )
    return response


@router.post("/api/v1/query/dataset")
async def query_dataset(req: Request):
    try:
        payload = await req.json()
    except Exception:
        return build_api_error_response(
            None,
            "invalid_request",
            "Request body must be valid JSON.",
            400,
            retry_hint="Send a JSON body matching the query_dataset contract.",
        )
    if not isinstance(payload, dict):
        return build_api_error_response(
            None,
            "invalid_request",
            "Request body must be a JSON object.",
            400,
            retry_hint="Send a JSON object matching the query_dataset contract.",
        )
    return await execute_query_dataset_payload(req, payload)
