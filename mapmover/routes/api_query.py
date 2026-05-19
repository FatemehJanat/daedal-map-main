from __future__ import annotations

import asyncio
import base64
import hashlib
import math
import json
import os
import re
import time
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

_REGION_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9_]{0,29}$")

import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from mapmover.auth_context import get_authenticated_user
from mapmover.pack_pricing import FREE_PACK_IDS as _FREE_PACK_IDS
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
from mapmover.security import get_client_ip, rate_limiter


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
FREE_QUERY_PACK_IDS = _FREE_PACK_IDS


def _get_request_ip(request: Request) -> str | None:
    return get_client_ip(request)


def _api_analytics_metadata(
    req: Request,
    *,
    request_fingerprint: str | None = None,
    query_scope: dict[str, Any] | None = None,
    access_lane: str | None = None,
) -> dict[str, Any]:
    existing = getattr(req.state, "analytics_metadata", None)
    metadata = dict(existing) if isinstance(existing, dict) else {}
    metadata.setdefault("surface", getattr(req.state, "analytics_surface", None) or "agent_api")
    if access_lane:
        metadata["access_lane"] = access_lane
    if request_fingerprint:
        metadata["request_fingerprint"] = request_fingerprint
    if query_scope:
        metadata["query_scope"] = query_scope
    req.state.analytics_metadata = metadata
    return metadata


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


def _canonical_request_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonical_request_value(value[key])
            for key in sorted(value.keys(), key=lambda item: str(item))
        }
    if isinstance(value, list):
        return [_canonical_request_value(item) for item in value]
    if isinstance(value, tuple):
        return [_canonical_request_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _canonical_compare_filters(compare_filters: list[tuple[str, str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for field_name, op, value in compare_filters:
        normalized.append(
            {
                "field": str(field_name),
                "op": str(op),
                "value": _canonical_request_value(value),
            }
        )
    normalized.sort(
        key=lambda item: (
            item["field"],
            item["op"],
            json.dumps(item["value"], ensure_ascii=True, sort_keys=True, separators=(",", ":")),
        )
    )
    return normalized


def _build_request_fingerprint_payload(
    *,
    source_id: str,
    pack_id: str,
    query_mode: str,
    metrics: list[str],
    normalized_region_ids: list[str],
    normalized_time: dict[str, Any],
    equals_filters: dict[str, Any],
    compare_filters: list[tuple[str, str, Any]],
    normalized_sort: list[dict[str, str]],
    limit: int,
    output_format: str,
) -> dict[str, Any]:
    return {
        "capability_id": "dataset_query",
        "source_id": source_id,
        "pack_id": pack_id,
        "query_mode": query_mode,
        "metrics": sorted(str(metric) for metric in metrics),
        "filters": {
            "region_ids": sorted(str(region_id) for region_id in normalized_region_ids),
            "time": _canonical_request_value(normalized_time),
            "equals": _canonical_request_value(equals_filters),
            "compare": _canonical_compare_filters(compare_filters),
        },
        "sort": _canonical_request_value(normalized_sort),
        "limit": int(limit),
        "output_format": str(output_format),
    }


def _request_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        _canonical_request_value(payload),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def _trusted_artifact_tokens() -> set[str]:
    raw = os.getenv("ARTIFACT_ACCESS_TOKENS", "").strip()
    if not raw:
        return set()
    return {tok.strip() for tok in raw.split(",") if tok.strip()}


def _get_trusted_artifact_token(request: Request) -> str | None:
    """Return the matched token string if the request carries a valid artifact token, else None."""
    tokens = _trusted_artifact_tokens()
    if not tokens:
        return None
    auth_header = request.headers.get("authorization", "").strip()
    if not auth_header.lower().startswith("bearer "):
        return None
    provided = auth_header[7:].strip()
    return provided if provided in tokens else None


def _pack_requires_commercial_access(pack_id: str | None) -> bool:
    normalized = str(pack_id or "").strip().lower()
    return bool(normalized) and normalized not in FREE_QUERY_PACK_IDS


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
    *,
    pack_id: str | None = None,
    source_id: str | None = None,
) -> Response:
    def _discovery_payload(pricing: dict[str, Any] | None = None) -> dict[str, Any]:
        site_url = str(SITE_URL or "https://daedalmap.com").rstrip("/")
        payload: dict[str, Any] = {
            "docs_url": f"{site_url}/docs/for-agents",
            "examples_url": f"{site_url}/docs/agent-examples",
            "catalog_url": "https://app.daedalmap.com/api/v1/catalog",
            "guide_url": "https://app.daedalmap.com/api/v1/guide",
            "first_steps": [
                "GET /api/v1/catalog",
                f"GET /api/v1/packs/{pack_id or 'earthquakes'}",
                "Retry this same paid call only after inspecting the free pack detail.",
            ],
        }
        if pack_id:
            payload["pack_id"] = pack_id
            payload["pack_url"] = f"https://app.daedalmap.com/api/v1/packs/{pack_id}"
            payload["public_pack_url"] = f"{site_url}/packs/{pack_id}"
        if source_id:
            payload["source_id"] = source_id
        if isinstance(pricing, dict):
            suggestions = pricing.get("suggestions") or []
            if isinstance(suggestions, list) and suggestions:
                payload["narrowing_suggestions"] = [str(item) for item in suggestions[:5] if str(item).strip()]
        return payload

    def _pricing_payload(pricing: dict[str, Any] | None = None) -> dict[str, Any]:
        pricing = pricing if isinstance(pricing, dict) else {}
        return {
            "message": "Small queries stay cheap; broad scans cost more or need narrower filters.",
            "price_display": pricing.get("price_display"),
            "scope_class": pricing.get("scope_class"),
            "soft_cap_usd": pricing.get("soft_cap_usd"),
            "suggestions": pricing.get("suggestions") or [],
        }

    def _augment_payment_required_header(
        header_value: str,
        *,
        pricing: dict[str, Any] | None = None,
    ) -> str:
        raw = str(header_value or "").strip()
        if not raw:
            return raw
        try:
            decoded = base64.b64decode(raw).decode("utf-8")
            challenge_payload = json.loads(decoded)
        except Exception:
            return raw
        if not isinstance(challenge_payload, dict):
            return raw

        resource = challenge_payload.get("resource")
        if isinstance(resource, dict):
            if pack_id and source_id:
                resource["description"] = (
                    f"DaedalMap paid dataset query for pack '{pack_id}' and source '{source_id}'. "
                    "Use the free catalog and pack detail endpoints first, then retry this call with payment."
                )
            elif pack_id:
                resource["description"] = (
                    f"DaedalMap paid dataset query for pack '{pack_id}'. "
                    "Use the free catalog and pack detail endpoints first, then retry this call with payment."
                )

        extensions = challenge_payload.get("extensions")
        if not isinstance(extensions, dict):
            extensions = {}
            challenge_payload["extensions"] = extensions
        extensions["daedalmap"] = {
            "discovery": _discovery_payload(pricing),
            "pricing": _pricing_payload(pricing),
        }
        try:
            encoded = base64.b64encode(
                json.dumps(challenge_payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            ).decode("ascii")
            return encoded
        except Exception:
            return raw

    payload = verifier_payload or {}
    challenge = payload.get("challenge") if isinstance(payload, dict) else None
    headers = {}
    body = None
    context = payload.get("context") if isinstance(payload, dict) else None
    pricing = context.get("pricing") if isinstance(context, dict) else None
    if isinstance(challenge, dict):
        raw_headers = challenge.get("headers") or {}
        if isinstance(raw_headers, dict):
            headers = {
                str(key): str(value)
                for key, value in raw_headers.items()
                if str(key).strip() and value is not None
            }
        body = challenge.get("body")
    payment_required_header = headers.get("payment-required") or headers.get("Payment-Required")
    if payment_required_header:
        enriched = _augment_payment_required_header(payment_required_header, pricing=pricing)
        headers["payment-required"] = enriched
        if "Payment-Required" in headers:
            headers["Payment-Required"] = enriched

    status_code = int(payload.get("http_status") or 402)
    if isinstance(body, dict):
        response_body = dict(body)
        if isinstance(pricing, dict):
            response_body.setdefault(
                "daedalmap_pricing",
                _pricing_payload(pricing),
            )
        response_body.setdefault("daedalmap_discovery", _discovery_payload(pricing))
        response = JSONResponse(response_body, status_code=status_code)
    elif isinstance(body, list):
        response = JSONResponse(body, status_code=status_code)
    elif isinstance(body, str) and body.strip():
        response = Response(content=body, status_code=status_code, media_type="application/json")
    else:
        fallback_body = {
            "request_id": request_id,
            "payment_required": True,
            "error": {
                "code": str(payload.get("code") or "commercial_access_required"),
                "message": str(payload.get("message") or "Commercial access is required for this capability."),
                "retry_hint": "Use the free catalog and pack detail endpoints first, then retry this exact paid call with payment.",
            },
            "daedalmap_discovery": _discovery_payload(pricing),
            "daedalmap_pricing": _pricing_payload(pricing),
        }
        response = JSONResponse(fallback_body, status_code=status_code)
    for key, value in headers.items():
        response.headers[key] = value
    return response


def _settle_commercial_access(
    request_id: str,
    settlement_id: str,
    *,
    success: bool,
    request_fingerprint: str | None = None,
    caller_binding: str | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    _status_code, payload = _post_commercial_access(
        COMMERCIAL_ACCESS_SETTLE_PATH,
        {
            "request_id": request_id,
            "settlement_id": settlement_id,
            "outcome": {"status": "success" if success else "failed"},
            "request_context": {"request_fingerprint": request_fingerprint} if request_fingerprint else {},
            "caller": {"caller_binding": caller_binding} if caller_binding else {},
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


def _pricing_amount_usdc_base_units(payload: dict[str, Any] | None) -> int | None:
    context = (payload or {}).get("context") or {}
    if not isinstance(context, dict):
        return None
    pricing = context.get("pricing") or {}
    if not isinstance(pricing, dict):
        return None
    raw_value = pricing.get("amount_usdc_base_units")
    if raw_value is None:
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _coerce_scope_year(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.year
    if isinstance(value, date):
        return value.year
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text[:4])
    except ValueError:
        return None


def _scope_time_span_years(
    normalized_time: dict[str, Any],
    *,
    available_start: Any = None,
    available_end: Any = None,
) -> tuple[int | None, Any, Any, bool]:
    if "value" in normalized_time:
        value = normalized_time.get("value")
        return 1, value, value, False

    start = normalized_time.get("start")
    end = normalized_time.get("end")
    estimated = False
    if start is None:
        start = available_start
        estimated = True
    if end is None:
        end = available_end
        estimated = True

    start_year = _coerce_scope_year(start)
    end_year = _coerce_scope_year(end)
    if start_year is None or end_year is None:
        return None, start, end, estimated
    return max(1, end_year - start_year + 1), start, end, estimated


def _query_scope_suggestions(scope: dict[str, Any]) -> list[str]:
    suggestions = [
        "Small queries stay cheap; very broad scans cost more or need narrower filters.",
    ]
    if not scope.get("has_time_filter"):
        suggestions.append("Add a time range, such as year_start/year_end or start/end.")
    elif scope.get("time_span_years") and int(scope.get("time_span_years") or 0) > 5:
        suggestions.append("Use a narrower time window when you only need a sample or top-N result.")
    if not scope.get("has_region_filter"):
        suggestions.append("Add region_ids to limit the geographic scope.")
    if not scope.get("is_event_count"):
        suggestions.append("Use event_count when you only need an aggregate count.")
    if scope.get("user_sort_count") and not scope.get("has_region_filter"):
        suggestions.append("Avoid sorting across a full dataset unless you also filter by time or geography.")
    return suggestions


def _build_query_scope(
    spec,
    *,
    normalized_region_ids: list[str],
    normalized_time: dict[str, Any],
    raw_compare_filters: Any,
    normalized_sort: list[dict[str, str]],
    requested_sort_count: int,
    metrics: list[str],
    limit: int,
    output_format: str,
    available_start: Any = None,
    available_end: Any = None,
) -> dict[str, Any]:
    time_span_years, time_start, time_end, time_span_estimated = _scope_time_span_years(
        normalized_time,
        available_start=available_start,
        available_end=available_end,
    )
    compare_filter_count = len(raw_compare_filters) if isinstance(raw_compare_filters, list) else 0
    is_event_count = metrics == ["event_count"]
    has_region_filter = bool(normalized_region_ids)
    has_time_filter = bool(normalized_time)

    work_score = 0
    if not has_time_filter and spec.time_field:
        work_score += 40
    elif time_span_years is not None:
        if time_span_years > 50:
            work_score += 30
        elif time_span_years > 25:
            work_score += 20
        elif time_span_years > 5:
            work_score += 10

    region_count = len(normalized_region_ids)
    if not has_region_filter:
        work_score += 20
    elif region_count > 25:
        work_score += 20
    elif region_count > 10:
        work_score += 10

    if not is_event_count:
        work_score += 15
    if requested_sort_count:
        work_score += 20 if not has_region_filter and (time_span_years is None or time_span_years > 5) else 10
    if compare_filter_count:
        work_score = max(0, work_score - min(15, compare_filter_count * 5))
    if limit > 500:
        work_score += 10

    if work_score >= 75:
        scope_class = "too_broad"
    elif work_score >= 45:
        scope_class = "broad"
    elif work_score >= 20:
        scope_class = "standard"
    else:
        scope_class = "small"

    return {
        "pack_id": spec.pack_id,
        "source_id": spec.source_id,
        "query_mode": spec.query_mode,
        "output_format": output_format,
        "limit": int(limit),
        "source_max_limit": int(spec.max_limit),
        "time_field": spec.time_field,
        "time_start": _format_time_value(time_start),
        "time_end": _format_time_value(time_end),
        "time_span_years": time_span_years,
        "time_span_estimated": bool(time_span_estimated),
        "has_time_filter": has_time_filter,
        "region_count": region_count,
        "has_region_filter": has_region_filter,
        "compare_filter_count": compare_filter_count,
        "sort_count": len(normalized_sort),
        "user_sort_count": requested_sort_count,
        "sort_fields": [str(item.get("field") or "") for item in normalized_sort if item.get("field")],
        "metric_count": len(metrics),
        "is_event_count": is_event_count,
        "scope_class": scope_class,
        "estimated_work_score": work_score,
        "pricing_guidance": _query_scope_suggestions(
            {
                "has_time_filter": has_time_filter,
                "time_span_years": time_span_years,
                "has_region_filter": has_region_filter,
                "is_event_count": is_event_count,
                "user_sort_count": requested_sort_count,
            }
        ),
    }


def _query_scope_rejection(scope: dict[str, Any]) -> dict[str, Any] | None:
    if str(scope.get("query_mode") or "") != "single_source_events":
        return None

    no_time = not scope.get("has_time_filter")
    no_region = not scope.get("has_region_filter")
    is_event_count = bool(scope.get("is_event_count"))
    time_span_years = scope.get("time_span_years")
    try:
        span = int(time_span_years) if time_span_years is not None else None
    except (TypeError, ValueError):
        span = None

    max_unscoped_years = _env_int("QUERY_MAX_UNSCOPED_YEARS", 5, minimum=1)
    max_region_years = _env_int("QUERY_MAX_REGION_YEARS", 50, minimum=1)
    max_aggregate_unscoped_years = _env_int("QUERY_MAX_AGGREGATE_UNSCOPED_YEARS", 50, minimum=1)
    max_region_ids = _env_int("QUERY_MAX_REGION_IDS", 25, minimum=1)
    reject_score = _env_int("QUERY_REJECT_WORK_SCORE", 75, minimum=1)

    if int(scope.get("region_count") or 0) > max_region_ids:
        reason = f"region_ids is limited to {max_region_ids} entries for live dataset queries."
    elif no_time and no_region and not is_event_count:
        reason = "Event row queries must include a time filter or region_ids."
    elif no_time and no_region and bool(scope.get("user_sort_count")):
        reason = "Sorting a full event dataset without time or geography filters is too broad for live API access."
    elif no_region and span is not None and span > (max_aggregate_unscoped_years if is_event_count else max_unscoped_years):
        reason = "This time window is too broad without region_ids for live API access."
    elif scope.get("has_region_filter") and span is not None and span > max_region_years and not is_event_count:
        reason = "This time window is too broad for row-level live API access."
    elif int(scope.get("estimated_work_score") or 0) >= reject_score:
        reason = "This request is too broad for live API access."
    else:
        return None

    return {
        "code": "query_too_broad",
        "message": reason,
        "details": {
            "scope_class": scope.get("scope_class"),
            "estimated_work_score": scope.get("estimated_work_score"),
            "suggestions": scope.get("pricing_guidance") or _query_scope_suggestions(scope),
        },
        "retry_hint": "Narrow the request by time, geography, or aggregation before retrying.",
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
                metadata=_api_analytics_metadata(
                    req,
                    request_fingerprint=request_fingerprint,
                    query_scope=query_scope,
                    access_lane="paid" if payment_rail else "free",
                ),
            )
        return response

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
            metadata=_api_analytics_metadata(
                req,
                request_fingerprint=request_fingerprint,
                query_scope=query_scope,
                access_lane="paid" if _pack_requires_commercial_access(spec.pack_id) else "free",
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
    normalized_region_ids = []
    seen_region_ids: set[str] = set()
    for value in region_ids:
        normalized_value = str(value).strip().upper()
        if not normalized_value:
            continue
        if not _REGION_ID_RE.match(normalized_value):
            return error_response(
                request_id,
                "invalid_region_id",
                f"region_id '{value}' contains invalid characters.",
                400,
                retry_hint="Use valid loc_ids from the catalog such as G_JPN or C_US_06_001.",
                pack_id=spec.pack_id,
                source_id=source_id,
            )
        if normalized_value not in seen_region_ids:
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
    query_scope = _build_query_scope(
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
    _api_analytics_metadata(
        req,
        query_scope=query_scope,
        access_lane="paid" if _pack_requires_commercial_access(spec.pack_id) else "free",
    )
    scope_rejection = _query_scope_rejection(query_scope)
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

    request_fingerprint_payload = _build_request_fingerprint_payload(
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
    request_fingerprint = _request_fingerprint(request_fingerprint_payload)
    caller_binding = auth_user_id or ip_hash or "anonymous"

    settlement_id: str | None = None
    verifier_payload: dict[str, Any] | None = None
    payment_rail: str | None = None
    amount_charged_usdc_base_units: int | None = None
    artifact_token = _get_trusted_artifact_token(req)
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
        _api_analytics_metadata(
            req,
            query_scope=query_scope,
            access_lane="trusted_artifact",
        )
        existing_meta = getattr(req.state, "analytics_metadata", {})
        existing_meta["artifact_token_id"] = token_id
        req.state.analytics_metadata = existing_meta
    elif _pack_requires_commercial_access(spec.pack_id):
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
        amount_charged_usdc_base_units = _pricing_amount_usdc_base_units(verifier_payload)
        if verifier_status_name == "challenge":
            response = _commercial_access_response(
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
                metadata=_api_analytics_metadata(
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
        amount_charged_usdc_base_units=amount_charged_usdc_base_units,
        revenue_attributed_usdc_base_units=amount_charged_usdc_base_units,
        metadata=_api_analytics_metadata(
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
        return _error_response(
            None,
            "invalid_request",
            "Request body must be valid JSON.",
            400,
            retry_hint="Send a JSON body matching the query_dataset contract.",
        )
    if not isinstance(payload, dict):
        return _error_response(
            None,
            "invalid_request",
            "Request body must be a JSON object.",
            400,
            retry_hint="Send a JSON object matching the query_dataset contract.",
        )
    return await execute_query_dataset_payload(req, payload)
