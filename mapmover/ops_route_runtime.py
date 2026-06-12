"""Lane-specific Ops route runtime helpers."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import Response

from mapmover import session_manager
from mapmover.paths import ACCOUNT_URL
from mapmover.ops_orchestrator_runtime import build_ops_report
from mapmover.runtime.chat_route_context import build_base_chat_route_context
from mapmover.runtime.chat_route_support import anonymous_budget_rejection_payload
from mapmover.routes.chat_shared import human_chat_rate_limit_response


@dataclass
class OpsChatRouteContext:
    frontend_session_id: str
    auth_user: dict | None
    client_ip: str | None
    caller_ctx: dict
    session_id: str
    catalog_surface: str | None
    request_id: str
    qa_suite_metadata: dict
    cache: object
    allowed_feeds: list[str]
    watch: dict
    effective_feeds: list[str]


def snapshot_ops_report(*, cache, watch: dict, effective_feeds: list[str]) -> dict:
    report = build_ops_report(watch=watch, effective_feeds=effective_feeds)
    if cache is not None and isinstance(getattr(cache, "map_state", None), dict):
        cache.map_state["ops_report"] = report
    return report


def ops_request_id(session_id: str, query: str) -> str:
    query_hash = hashlib.md5((query or "").encode("utf-8")).hexdigest()[:8]
    session_hash = hashlib.md5((session_id or "").encode("utf-8")).hexdigest()[:8]
    return f"ops_{session_hash}_{query_hash}_{uuid.uuid4().hex[:8]}"


def _normalize_feed_names(values) -> list[str]:
    normalized: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _account_ops_feeds(auth_user: dict | None) -> list[str]:
    metadata = (auth_user or {}).get("user_metadata") or {}
    if not isinstance(metadata, dict):
        return []
    return _normalize_feed_names(metadata.get("ops_feeds") or [])


def _public_default_ops_feeds() -> list[str]:
    return [
        "currency",
        "earthquakes",
        "hurricanes_ibtracs_nrt",
        "noaa_aurora",
        "noaa_swpc",
        "tsunamis",
        "usa_nws_alerts",
        "volcanoes",
        "wildfires_us_nifc",
    ]


def _base_ops_feeds(auth_user: dict | None) -> list[str]:
    account_feeds = _account_ops_feeds(auth_user)
    if account_feeds:
        return account_feeds
    return _public_default_ops_feeds()


def _requested_ops_feeds(body: dict) -> list[str]:
    watch_context = body.get("watch_context") if isinstance(body.get("watch_context"), dict) else {}
    return _normalize_feed_names(watch_context.get("sources") or [])


def _merge_ops_feeds(*feed_lists) -> list[str]:
    merged: list[str] = []
    for values in feed_lists:
        for feed in _normalize_feed_names(values or []):
            if feed not in merged:
                merged.append(feed)
    return merged


def _watch_from_cache(cache, watch_id: str | None) -> dict | None:
    if cache is None:
        return None
    map_state = cache.map_state if isinstance(getattr(cache, "map_state", None), dict) else {}
    watch = map_state.get("ops_watch")
    if not isinstance(watch, dict):
        return None
    if watch_id and str(watch.get("watch_id") or "").strip() != str(watch_id).strip():
        return None
    return watch


def _build_default_watch(*, session_id: str, body: dict, allowed_feeds: list[str]) -> dict:
    watch_context = body.get("watch_context") if isinstance(body.get("watch_context"), dict) else {}
    viewport = body.get("viewport") if isinstance(body.get("viewport"), dict) else {}
    requested_feeds = _normalize_feed_names(watch_context.get("sources") or [])
    active_feeds = [feed for feed in requested_feeds if feed in allowed_feeds] if requested_feeds else list(allowed_feeds)
    watch_id = str(body.get("watch_id") or "").strip() or f"watch_{session_id.replace(':', '_')}"
    label = str(watch_context.get("label") or watch_context.get("focus") or "").strip()
    if not label:
        label = "Ops watch"
    return {
        "watch_id": watch_id,
        "label": label,
        "geography": {
            "viewport": viewport,
        },
        "active_feeds": active_feeds,
    }


def load_or_create_ops_watch(*, cache, session_id: str, body: dict, allowed_feeds: list[str]) -> dict:
    requested_watch_id = str(body.get("watch_id") or "").strip() or None
    existing = _watch_from_cache(cache, requested_watch_id)
    if isinstance(existing, dict):
        return existing
    watch = _build_default_watch(session_id=session_id, body=body, allowed_feeds=allowed_feeds)
    if cache is not None and isinstance(getattr(cache, "map_state", None), dict):
        cache.map_state["ops_watch"] = watch
    return watch


def setup_required_ops_message(auth_user: dict | None) -> str:
    if not auth_user:
        return (
            "Ops mode needs account-level feed setup first. Sign in, open your account page, "
            f"and use Choose your feeds: {ACCOUNT_URL}"
        )
    return (
        "No Ops feeds are enabled for this account yet. Open your account page and use "
        f"Choose your feeds first: {ACCOUNT_URL}"
    )


async def prepare_ops_chat_route_context(
    req: Request,
    body: dict,
    *,
    query: str,
) -> tuple[OpsChatRouteContext | None, Response | None, dict | None, int | None, dict[str, str] | None]:
    base_context, route_error = await build_base_chat_route_context(req, body, force_auth_refresh=True)
    if route_error:
        return None, route_error, None, getattr(route_error, "status_code", 400), None
    assert base_context is not None
    request_id = ops_request_id(base_context.session_id, query)
    req.state.analytics_request_id = request_id

    rate_limit_response = human_chat_rate_limit_response(
        lane="ops",
        user_id=(base_context.auth_user or {}).get("id"),
        client_ip=base_context.client_ip,
        caller_ctx=base_context.caller_ctx,
        request_id=request_id,
    )
    if rate_limit_response:
        return None, rate_limit_response, None, getattr(rate_limit_response, "status_code", 429), None

    rejection_payload, rejection_status, rejection_headers = anonymous_budget_rejection_payload(base_context.caller_ctx)
    if rejection_payload is not None:
        return None, None, rejection_payload, rejection_status, rejection_headers

    cache = session_manager.get_or_create(base_context.session_id)
    base_feeds = _base_ops_feeds(base_context.auth_user)
    allowed_feeds = list(base_feeds)
    watch = load_or_create_ops_watch(
        cache=cache,
        session_id=base_context.session_id,
        body=body,
        allowed_feeds=allowed_feeds,
    )
    effective_feeds = [feed for feed in _normalize_feed_names(watch.get("active_feeds") or []) if feed in allowed_feeds]
    watch["active_feeds"] = effective_feeds
    if isinstance(cache.map_state, dict):
        cache.map_state["ops_watch"] = watch

    return (
        OpsChatRouteContext(
            frontend_session_id=base_context.frontend_session_id,
            auth_user=base_context.auth_user,
            client_ip=base_context.client_ip,
            caller_ctx=base_context.caller_ctx,
            session_id=base_context.session_id,
            catalog_surface=base_context.catalog_surface,
            request_id=request_id,
            qa_suite_metadata=base_context.qa_suite_metadata,
            cache=cache,
            allowed_feeds=allowed_feeds,
            watch=watch,
            effective_feeds=effective_feeds,
        ),
        None,
        None,
        None,
        None,
    )


async def prepare_ops_view_route_context(
    req: Request,
    body: dict,
) -> tuple[OpsChatRouteContext | None, Response | None, dict | None, int | None, dict[str, str] | None]:
    return await prepare_ops_chat_route_context(req, body, query="ops_view")
