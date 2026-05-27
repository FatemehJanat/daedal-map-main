"""Shared helpers for chat-route surfaces."""

from __future__ import annotations

import ctypes
import gc
import hashlib
import json
import os
import time

import msgpack

from fastapi.responses import Response
from starlette.background import BackgroundTask

from mapmover import logger
from mapmover.catalog_surface import normalize_catalog_surface, request_can_use_wip_catalog
from mapmover.routes.disasters.helpers import msgpack_response
from mapmover.security import get_client_ip, rate_limiter


LARGE_RESPONSE_FEATURE_THRESHOLD = 1000


def _chat_trace_id(session_id: str, query: str) -> str:
    seed = f"{session_id}|{query[:80]}"
    return hashlib.md5(seed.encode()).hexdigest()[:10]


def _chat_log_timing(trace_id: str, stage: str, started_at: float, extra: str = "") -> float:
    now = time.perf_counter()
    elapsed_ms = (now - started_at) * 1000
    suffix = f" | {extra}" if extra else ""
    logger.info(f"[chat:{trace_id}] {stage}: {elapsed_ms:.1f}ms{suffix}")
    return now


def _trim_process_memory() -> None:
    gc.collect()
    if os.name != "posix":
        return
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        return


def _maybe_attach_memory_relief(response: Response, payload: dict | None) -> Response:
    if not isinstance(payload, dict):
        return response
    feature_count = 0
    geojson = payload.get("geojson")
    if isinstance(geojson, dict):
        features = geojson.get("features")
        if isinstance(features, list):
            feature_count = len(features)
    available_count = int(payload.get("available_count") or 0)
    if feature_count < LARGE_RESPONSE_FEATURE_THRESHOLD and available_count < LARGE_RESPONSE_FEATURE_THRESHOLD:
        return response
    response.background = BackgroundTask(_trim_process_memory)
    return response


def _rate_limited_message(message: str, retry_after: int) -> Response:
    response = msgpack_response({"error": message, "retry_after": retry_after}, status_code=429)
    response.headers["Retry-After"] = str(retry_after)
    return response


def _confirmed_order_rate_limit(req, auth_user: dict | None, caller_ctx: dict | None = None) -> Response | None:
    caller_kind = (caller_ctx or {}).get("caller_kind")
    if caller_kind in {"qa_suite", "qa_http_suite"}:
        return None
    user_id = (auth_user or {}).get("id")
    window_seconds = int(os.getenv("CONFIRMED_ORDER_RATE_WINDOW_SECONDS", "60"))
    if user_id:
        limit = int(os.getenv("CONFIRMED_ORDER_RATE_LIMIT_AUTH", "30"))
        allowed, retry_after = rate_limiter.check(
            f"confirmed_order:user:{user_id}",
            limit=limit,
            window_seconds=window_seconds,
        )
        if not allowed:
            return _rate_limited_message(
                "Too many direct order executions. Please slow down and try again shortly.",
                retry_after,
            )
        return None

    client_ip = get_client_ip(req)
    limit = int(os.getenv("CONFIRMED_ORDER_RATE_LIMIT_ANON", "10"))
    allowed, retry_after = rate_limiter.check(
        f"confirmed_order:ip:{client_ip}",
        limit=limit,
        window_seconds=window_seconds,
    )
    if not allowed:
        return _rate_limited_message(
            "Too many anonymous direct order executions. Please wait a moment and try again.",
            retry_after,
        )
    return None


def _confirmed_order_user_error() -> dict:
    return {
        "type": "error",
        "message": "Order execution failed. Please try again.",
    }


def _catalog_surface_for_request(req, body: dict, auth_user: dict | None) -> tuple[str | None, Response | None]:
    surface = normalize_catalog_surface(body.get("catalog_surface"))
    if surface == "wip" and not request_can_use_wip_catalog(req, auth_user):
        return None, msgpack_response(
            {
                "type": "error",
                "message": "WIP catalog access is limited to admin accounts.",
            },
            status_code=403,
        )
    return surface, None


def _set_chat_analytics(
    req,
    *,
    lane: str,
    confirmed_order: bool = False,
    request_key: str | None = None,
    reused_cached_result: bool | None = None,
    force_refetch: bool | None = None,
    result_type: str | None = None,
    source_id: str | None = None,
    error_code: str | None = None,
) -> None:
    if error_code is not None:
        req.state.analytics_error_code = error_code
    if source_id:
        req.state.analytics_source_id = source_id
    req.state.analytics_metadata = {
        "chat_lane": lane,
        "confirmed_order": confirmed_order,
        "request_key": request_key,
        "reused_cached_result": reused_cached_result,
        "force_refetch": force_refetch,
        "result_type": result_type,
    }


async def decode_request_body(request) -> dict:
    body_bytes = await request.body()
    return msgpack.unpackb(body_bytes, raw=False)


async def decode_json_or_msgpack_body(request) -> dict:
    body_bytes = await request.body()
    try:
        return json.loads(body_bytes.decode("utf-8"))
    except json.JSONDecodeError:
        return msgpack.unpackb(body_bytes, raw=False)
