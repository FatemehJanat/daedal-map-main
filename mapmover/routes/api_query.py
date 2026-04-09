from __future__ import annotations

import asyncio
import math
import json
import os
import time
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from mapmover.auth_context import get_authenticated_user
from mapmover.api_query_limits import QueryConcurrencyLimitError, acquire_query_slot
from mapmover.api_query_runtime import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    api_source_ready,
    execute_dataset_query,
    get_api_source_columns,
    get_api_source_spec,
    get_api_source_time_bounds,
    is_temporal_time_field,
    normalize_time_granularity,
    resolve_pack_source_for_query,
)
from mapmover.geography import get_country_names_from_codes
from mapmover.logging_analytics import hash_ip_for_analytics, log_api_query_event
from mapmover.paths import SITE_URL


router = APIRouter()

COMMERCIAL_ACCESS_CHECK_PATH = "/internal/commercial-access/check"
COMMERCIAL_ACCESS_SETTLE_PATH = "/internal/commercial-access/settle"
COMMERCIAL_ACCESS_TIMEOUT_SECONDS = 10.0
COMMERCIAL_ACCESS_FORWARDED_HEADERS = {
    "accept",
    "authorization",
    "payment-required",
    "payment-response",
    "payment-signature",
    "user-agent",
    "x-payment",
    "x-payment-response",
}


def _get_request_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        first_hop = forwarded_for.split(",")[0].strip()
        if first_hop:
            return first_hop
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    return request.client.host if request.client else None


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


def _format_time_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _parse_temporal_filter_value(raw_value: Any) -> str:
    if isinstance(raw_value, (datetime, date)):
        return raw_value.isoformat()
    if raw_value is None:
        raise ValueError("missing")
    normalized = str(raw_value).strip()
    if not normalized:
        raise ValueError("blank")
    return normalized


def _commercial_access_enabled() -> bool:
    return str(os.getenv("COMMERCIAL_ACCESS_ENABLED", "")).strip().lower() in {"1", "true", "yes", "on"}


def _commercial_access_timeout_seconds() -> float:
    raw_value = str(os.getenv("COMMERCIAL_ACCESS_TIMEOUT_SECONDS", "")).strip()
    if not raw_value:
        return COMMERCIAL_ACCESS_TIMEOUT_SECONDS
    try:
        return max(1.0, float(raw_value))
    except ValueError:
        return COMMERCIAL_ACCESS_TIMEOUT_SECONDS


def _commercial_access_base_url() -> str:
    configured = str(os.getenv("COMMERCIAL_ACCESS_VERIFIER_BASE_URL", "")).strip().rstrip("/")
    return configured or SITE_URL.rstrip("/")


def _commercial_access_internal_token() -> str:
    return str(os.getenv("CLOUD_INTERNAL_API_TOKEN", "")).strip()


def _forwarded_commercial_headers(request: Request) -> dict[str, str]:
    forwarded: dict[str, str] = {}
    for header_name in COMMERCIAL_ACCESS_FORWARDED_HEADERS:
        raw_value = request.headers.get(header_name)
        if raw_value is not None and str(raw_value).strip():
            forwarded[header_name] = str(raw_value).strip()
    return forwarded


def _post_commercial_access(path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
    url = urljoin(f"{_commercial_access_base_url()}/", path.lstrip("/"))
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    token = _commercial_access_internal_token()
    if token:
        headers["x-internal-api-key"] = token
    response = requests.post(
        url,
        json=payload,
        headers=headers,
        timeout=_commercial_access_timeout_seconds(),
    )
    try:
        body = response.json()
    except Exception:
        body = None
    return response.status_code, body


def _commercial_access_response(
    request_id: str | None,
    verifier_payload: dict[str, Any] | None,
) -> Response:
    payload = verifier_payload or {}
    challenge = payload.get("challenge") if isinstance(payload, dict) else None
    headers = {}
    body = None
    if isinstance(challenge, dict):
        raw_headers = challenge.get("headers") or {}
        if isinstance(raw_headers, dict):
            headers = {
                str(key): str(value)
                for key, value in raw_headers.items()
                if str(key).strip() and value is not None
            }
        body = challenge.get("body")

    status_code = int(payload.get("http_status") or 402)
    if isinstance(body, (dict, list)):
        response = JSONResponse(body, status_code=status_code)
    elif isinstance(body, str) and body.strip():
        response = Response(content=body, status_code=status_code, media_type="application/json")
    else:
        response = _error_response(
            request_id,
            str(payload.get("code") or "commercial_access_required"),
            str(payload.get("message") or "Commercial access is required for this capability."),
            status_code,
        )
    for key, value in headers.items():
        response.headers[key] = value
    return response


def _settle_commercial_access(request_id: str, settlement_id: str, *, success: bool) -> tuple[bool, dict[str, Any] | None]:
    _status_code, payload = _post_commercial_access(
        COMMERCIAL_ACCESS_SETTLE_PATH,
        {
            "request_id": request_id,
            "settlement_id": settlement_id,
            "outcome": {"status": "success" if success else "failed"},
        },
    )
    if isinstance(payload, dict) and str(payload.get("status") or "").strip().lower() == "allow":
        return True, payload
    return False, payload


def _settlement_headers(payload: dict[str, Any] | None) -> dict[str, str]:
    settlement = (payload or {}).get("settlement") or {}
    raw_headers = settlement.get("headers") or {}
    if not isinstance(raw_headers, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in raw_headers.items()
        if str(key).strip() and value is not None
    }


def _parse_time_filter(
    spec,
    time_filter: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[tuple[str, str, Any]]]:
    normalized_time: dict[str, Any] = {}
    exact_filters: dict[str, Any] = {}
    compare_filters: list[tuple[str, str, Any]] = []

    if spec.time_field is None:
        return normalized_time, exact_filters, compare_filters

    exact_value = time_filter.get("value")
    start_value = time_filter.get("start")
    end_value = time_filter.get("end")

    if exact_value is None and "year" in time_filter:
        exact_value = time_filter.get("year")
    if start_value is None and "year_start" in time_filter:
        start_value = time_filter.get("year_start")
    if end_value is None and "year_end" in time_filter:
        end_value = time_filter.get("year_end")

    if is_temporal_time_field(spec):
        if exact_value is not None:
            coerced_value = _parse_temporal_filter_value(exact_value)
            exact_filters[spec.time_field] = coerced_value
            normalized_time["value"] = coerced_value
            return normalized_time, exact_filters, compare_filters

        coerced_start = None
        coerced_end = None
        if start_value is not None:
            coerced_start = _parse_temporal_filter_value(start_value)
            normalized_time["start"] = coerced_start
            compare_filters.append((spec.time_field, ">=", coerced_start))
        if end_value is not None:
            coerced_end = _parse_temporal_filter_value(end_value)
            normalized_time["end"] = coerced_end
            compare_filters.append((spec.time_field, "<=", coerced_end))
        if coerced_start is not None and coerced_end is not None and coerced_start > coerced_end:
            raise ValueError("start_after_end")
        return normalized_time, exact_filters, compare_filters

    if exact_value is not None:
        coerced_value = int(exact_value)
        exact_filters[spec.time_field] = coerced_value
        normalized_time["value"] = coerced_value
        return normalized_time, exact_filters, compare_filters

    coerced_start = None
    coerced_end = None
    if start_value is not None:
        coerced_start = int(start_value)
        normalized_time["start"] = coerced_start
        compare_filters.append((spec.time_field, ">=", coerced_start))
    if end_value is not None:
        coerced_end = int(end_value)
        normalized_time["end"] = coerced_end
        compare_filters.append((spec.time_field, "<=", coerced_end))
    if coerced_start is not None and coerced_end is not None and coerced_start > coerced_end:
        raise ValueError("start_after_end")
    return normalized_time, exact_filters, compare_filters


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

    if "event_count" in normalized_metrics and len(normalized_metrics) > 1:
        return None, _error_response(
            request_id,
            "metric_not_available",
            "event_count must be requested on its own.",
            400,
            retry_hint="Request event_count alone, or request raw event metrics without event_count.",
        )

    return normalized_metrics, None


@router.post("/api/v1/query/dataset")
async def query_dataset(req: Request):
    started_at = time.perf_counter()
    auth_user = get_authenticated_user(req)
    auth_user_id = str((auth_user or {}).get("id") or "").strip() or None
    ip_hash = hash_ip_for_analytics(_get_request_ip(req))
    caller_key = auth_user_id or ip_hash or "anonymous"
    user_agent = req.headers.get("user-agent", "").strip() or None
    payment_rail: str | None = None

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
        response = _error_response(
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
                metadata={"surface": "agent_api_paid"},
            )
        return response

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

    metrics, metrics_error = _validate_metrics(spec, payload.get("metrics"), request_id=request_id)
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
    normalized_region_ids = []
    seen_region_ids: set[str] = set()
    for value in region_ids:
        normalized_value = str(value).strip().upper()
        if normalized_value and normalized_value not in seen_region_ids:
            seen_region_ids.add(normalized_value)
            normalized_region_ids.append(normalized_value)

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
        parsed_time, parsed_exact_filters, parsed_compare_filters = _parse_time_filter(spec, time_filter)
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
            if field_name not in spec.filterable_fields:
                return error_response(
                    request_id,
                    "field_not_filterable",
                    f"Field '{field_name}' is not filterable for source '{spec.source_id}'.",
                    400,
                    retry_hint="Only use filterable fields published for this source.",
                    pack_id=spec.pack_id,
                    source_id=source_id,
                )
            exact_filters[field_name] = value

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
            if field_name not in available_compare_fields:
                return error_response(
                    request_id,
                    "field_not_filterable",
                    f"Field '{field_name}' is not filterable for source '{spec.source_id}'.",
                    400,
                    retry_hint="Only compare against filterable fields or selected metric columns.",
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
            compare_filters.append((field_name, op, value))

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

    available_columns = get_api_source_columns(spec)
    if spec.time_field in available_columns:
        available_start, available_end = get_api_source_time_bounds(spec)
        if available_start is not None and available_end is not None:
            requested_start = normalized_time.get("value", normalized_time.get("start"))
            requested_end = normalized_time.get("value", normalized_time.get("end"))
            if requested_start is not None and requested_start < available_start:
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
            if requested_end is not None and requested_end > available_end:
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

    settlement_id: str | None = None
    if not _commercial_access_enabled():
        return error_response(
            request_id,
            "commercial_access_unavailable",
            "This paid endpoint requires a hosted commercial-access verifier.",
            503,
            retry_hint="Use the free discovery endpoints or retry against a runtime with commercial access enabled.",
            pack_id=spec.pack_id,
            source_id=source_id,
        )
    if not _commercial_access_internal_token():
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
            _post_commercial_access,
            COMMERCIAL_ACCESS_CHECK_PATH,
            {
                "request_id": request_id,
                "capability_id": "dataset_query",
                "resource": {
                    "method": "POST",
                    "path": "/api/v1/query/dataset",
                },
                "forwarded_headers": _forwarded_commercial_headers(req),
                "caller": {
                    "auth_user_id": auth_user_id,
                    "ip_hash": ip_hash,
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
    if verifier_status_name == "challenge":
        response = _commercial_access_response(request_id, verifier_payload)
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
            metadata={"surface": "agent_api_paid"},
        )
        return response
    if verifier_status_name != "allow":
        return error_response(
            request_id,
            str((verifier_payload or {}).get("code") or "commercial_access_denied"),
            str((verifier_payload or {}).get("message") or "Commercial access denied."),
            int((verifier_payload or {}).get("http_status") or verifier_status or 403),
            retry_hint="Retry after satisfying the requested commercial-access challenge.",
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
            "loc_id": _json_safe_value(row.get(spec.location_field)),
        }
        if spec.time_field:
            shaped[spec.time_field] = _json_safe_value(_format_time_value(row.get(spec.time_field)))
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

    if settlement_id:
        try:
            settled, settlement_payload = await asyncio.to_thread(
                _settle_commercial_access,
                request_id,
                settlement_id,
                success=True,
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
        for key, value in _settlement_headers(settlement_payload).items():
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
        metadata={"surface": "agent_api_paid"},
    )
    return response
