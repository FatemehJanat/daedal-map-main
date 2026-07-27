"""Ops mode API router endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from mapmover import logger
from mapmover.logging_analytics import hash_ip_for_analytics, log_app_error, log_conversation
from mapmover.ops_route_runtime import (
    prepare_ops_chat_route_context,
    prepare_ops_view_route_context,
    build_ops_orientation_payload,
    setup_required_ops_message,
    snapshot_ops_report,
)
from mapmover.ops_ticker import (
    build_cached_aurora_payload,
    build_cached_aurora_frames_payload,
    build_cached_nws_alerts_payload,
    build_cached_ticker_payload,
)
from mapmover.ops_point_feeds import POINT_FEEDS, build_cached_point_overlay, is_point_feed
from mapmover.auth_context import get_authenticated_user
from mapmover.catalog_surface import request_uses_wip_catalog
from mapmover.orchestrator_registry import get_orchestrator
from mapmover.routes.chat_shared import build_chat_error_payload, build_provider_error_payload, decode_json_or_msgpack_body, decode_request_body
from mapmover.routes.disasters.helpers import msgpack_error, msgpack_response
from mapmover.runtime.chat_route_support import (
    anonymous_turn_limit_rejection_payload,
    build_chat_gate_log_metadata,
    build_usage_recorder,
    register_anonymous_chat_turn,
)
from mapmover.runtime.sse import SSE_HEADERS, encode_sse, stage_payload


router = APIRouter()
ops_orchestrator = get_orchestrator("ops")


def _ops_report_payload(route_context) -> dict:
    report = snapshot_ops_report(
        cache=route_context.cache,
        watch=route_context.watch,
        effective_feeds=route_context.effective_feeds,
    )
    return {
        "type": "ops_report",
        "watch_id": route_context.watch.get("watch_id"),
        "watch": route_context.watch,
        "effective_feeds": route_context.effective_feeds,
        "ops_report": report,
    }


@router.get("/api/ops/ticker")
async def ops_ticker_endpoint(req: Request):
    """Live announcement ticker items (space weather, etc.). Public, read-only.

    Open in all modes - the ticker is a standalone announcement bar, not tied to
    a watch or the chat ops_report.
    """
    try:
        return msgpack_response(build_cached_ticker_payload())
    except Exception as exc:
        logger.exception("Ops ticker error")
        return msgpack_error(str(exc), 500)


@router.get("/api/ops/aurora")
async def ops_aurora_endpoint(req: Request):
    """Latest OVATION aurora model band for the map overlay. Public, read-only.

    Returns the renderable cells [[lon, lat, probability], ...] plus the forecast
    timestamps, straight from the noaa_aurora live snapshot.
    """
    try:
        return msgpack_response(build_cached_aurora_payload())
    except Exception as exc:
        logger.exception("Ops aurora error")
        return msgpack_error(str(exc), 500)


@router.get("/api/ops/aurora/frames")
async def ops_aurora_frames_endpoint(req: Request):
    """Rolling, compact Aurora model frames for the real-history loop."""
    try:
        return msgpack_response(build_cached_aurora_frames_payload())
    except Exception as exc:
        logger.exception("Ops aurora frame history error")
        return msgpack_error(str(exc), 500)


@router.get("/api/ops/nws-alerts")
async def ops_nws_alerts_endpoint(req: Request):
    """NWS active alerts as a GeoJSON overlay. Public, read-only.

    Each alert renders as its exact warning polygon when the feed provided one,
    else the highlighted affected county polygons, else a pin at the centroid.
    """
    try:
        return msgpack_response(build_cached_nws_alerts_payload())
    except Exception as exc:
        logger.exception("Ops NWS alerts error")
        return msgpack_error(str(exc), 500)


@router.get("/api/ops/points/{overlay_id}")
async def ops_points_endpoint(overlay_id: str, req: Request):
    """Generic live point-feed overlay (GeoJSON points). Public, read-only.

    One endpoint for every registered "location with updating data" feed (ocean
    buoys, weather stations, sensors): each point carries its latest reading for
    the click popup. See mapmover/ops_point_feeds.py POINT_FEEDS.
    """
    if not is_point_feed(overlay_id):
        return msgpack_error(f"Unknown point feed: {overlay_id}", 404)
    spec = POINT_FEEDS[str(overlay_id or "").strip()]
    if spec.wip_only and not request_uses_wip_catalog(req, get_authenticated_user(req)):
        # Do not advertise an unreviewed Ops feed through a public endpoint.
        return msgpack_error(f"Unknown point feed: {overlay_id}", 404)
    try:
        return msgpack_response(build_cached_point_overlay(overlay_id))
    except Exception as exc:
        logger.exception("Ops point feed error: %s", overlay_id)
        return msgpack_error(str(exc), 500)


@router.post("/api/ops/report")
async def ops_report_endpoint(req: Request):
    try:
        body = await decode_request_body(req)
        route_context, route_error, rejection_payload, rejection_status, rejection_headers = await prepare_ops_view_route_context(req, body)
        if route_error:
            return route_error
        if rejection_payload is not None:
            log_conversation(
                route_context.frontend_session_id if route_context else body.get("sessionId", "anonymous"),
                query,
                rejection_payload.get("message", ""),
                surface="ops",
                intent=rejection_payload.get("error_code") or "anonymous_budget_blocked",
                metadata=build_chat_gate_log_metadata(
                    rejection_payload,
                    gate_kind="anonymous_daily_budget",
                ),
            )
            return msgpack_response(
                rejection_payload,
                status_code=rejection_status or 400,
                headers=rejection_headers or {},
            )
        assert route_context is not None
        payload = _ops_report_payload(route_context)
        if not route_context.allowed_feeds:
            payload["warning"] = setup_required_ops_message(route_context.auth_user)
        return msgpack_response(payload)
    except Exception as exc:
        logger.exception("Ops report snapshot error")
        return msgpack_error(str(exc), 500)


@router.post("/api/ops/load-watch")
async def ops_load_watch_endpoint(req: Request):
    try:
        body = await decode_request_body(req)
        route_context, route_error, rejection_payload, rejection_status, rejection_headers = await prepare_ops_view_route_context(req, body)
        if route_error:
            return route_error
        if rejection_payload is not None:
            return msgpack_response(
                rejection_payload,
                status_code=rejection_status or 400,
                headers=rejection_headers or {},
            )
        assert route_context is not None
        payload = _ops_report_payload(route_context)
        payload["type"] = "ops_watch_loaded"
        payload["message"] = (
            f'Loaded "{route_context.watch.get("label") or "Ops watch"}" with '
            f"{len(route_context.effective_feeds)} feed"
            f"{'' if len(route_context.effective_feeds) == 1 else 's'}."
        )
        if not route_context.allowed_feeds:
            payload["warning"] = setup_required_ops_message(route_context.auth_user)
        return msgpack_response(payload)
    except Exception as exc:
        logger.exception("Ops watch load error")
        return msgpack_error(str(exc), 500)


@router.post("/chat/ops")
async def ops_chat_endpoint(req: Request):
    try:
        body = await decode_request_body(req)
        query = body.get("query", "")
        if not query:
            return msgpack_error("No query provided", 400)
        route_context, route_error, rejection_payload, rejection_status, rejection_headers = await prepare_ops_chat_route_context(
            req,
            body,
            query=query,
        )
        if route_error:
            return route_error
        if rejection_payload is not None:
            return msgpack_response(
                rejection_payload,
                status_code=rejection_status or 400,
                headers=rejection_headers or {},
            )
        assert route_context is not None
        if not route_context.allowed_feeds:
            payload = {
                "type": "chat",
                "message": setup_required_ops_message(route_context.auth_user),
                "watch_id": route_context.watch.get("watch_id"),
                "watch_context": route_context.watch,
                "effective_feeds": [],
            }
            return msgpack_response(payload)
        orientation = build_ops_orientation_payload(
            query=query,
            effective_feeds=route_context.effective_feeds,
            selected_popup=body.get("selectedPopup"),
        )
        if orientation is not None:
            return msgpack_response(orientation)
        turn_limit_payload, turn_limit_status, turn_limit_headers = anonymous_turn_limit_rejection_payload(
            session_id=route_context.session_id,
            caller_ctx=route_context.caller_ctx,
            lane="ops",
        )
        if turn_limit_payload is not None:
            log_conversation(
                route_context.frontend_session_id,
                query,
                turn_limit_payload.get("message", ""),
                surface="ops",
                intent=turn_limit_payload.get("error_code") or "anonymous_turn_limit_reached",
                metadata=build_chat_gate_log_metadata(
                    turn_limit_payload,
                    gate_kind="anonymous_turn_limit",
                ),
            )
            return msgpack_response(
                turn_limit_payload,
                status_code=turn_limit_status or 429,
                headers=turn_limit_headers or {},
            )
        register_anonymous_chat_turn(
            session_id=route_context.session_id,
            caller_ctx=route_context.caller_ctx,
            lane="ops",
        )

        usage_recorder = build_usage_recorder(
            surface="ops",
            call_kind="ops_main",
            session_id=route_context.session_id,
            request_id=route_context.request_id,
            caller_ctx=route_context.caller_ctx,
            qa_suite_metadata=route_context.qa_suite_metadata,
        )
        try:
            result = await ops_orchestrator.run(
                query=query,
                chat_history=body.get("chatHistory", []),
                watch=route_context.watch,
                effective_feeds=route_context.effective_feeds,
                usage_recorder=usage_recorder,
                catalog_surface=route_context.catalog_surface,
                cache=route_context.cache,
                selected_popup=body.get("selectedPopup"),
            )
        finally:
            usage_recorder.flush()
        log_conversation(
            route_context.frontend_session_id,
            query,
            result.get("message", ""),
            surface="ops",
            intent=result.get("type"),
            ip_hash=hash_ip_for_analytics(route_context.client_ip),
            user_agent=(req.headers.get("user-agent") or "")[:300] or None,
        )
        return msgpack_response(result)
    except Exception as exc:
        logger.exception("Ops chat error")
        log_app_error(type(exc).__name__, str(exc), surface="human_app", path="/chat/ops")
        return msgpack_response(
            build_provider_error_payload(
                exc,
                lane="ops",
                request_id=getattr(getattr(req, "state", None), "analytics_request_id", None),
            )
            or build_chat_error_payload(
                lane="ops",
                message="Ops mode hit an internal error.",
                error_code="ops_internal_error",
                request_id=getattr(getattr(req, "state", None), "analytics_request_id", None),
                stage="route",
                retry_hint="Retry the watch question. If it keeps failing, ask about one feed at a time."
            ),
            status_code=500,
        )


@router.post("/chat/ops/stream")
async def ops_chat_stream_endpoint(req: Request):
    body = await decode_json_or_msgpack_body(req)

    async def generate_events():
        try:
            query = body.get("query", "")
            if not query:
                yield encode_sse(stage_payload("complete", result={"type": "error", "message": "No query provided"}))
                return
            route_context, route_error, rejection_payload, _rejection_status, _rejection_headers = await prepare_ops_chat_route_context(
                req,
                body,
                query=query,
            )
            if route_error or rejection_payload is not None:
                payload = rejection_payload or {"type": "error", "message": "Ops request could not be prepared."}
                if rejection_payload is not None and route_context is not None:
                    log_conversation(
                        route_context.frontend_session_id,
                        query,
                        rejection_payload.get("message", ""),
                        surface="ops",
                        intent=rejection_payload.get("error_code") or "anonymous_budget_blocked",
                        metadata=build_chat_gate_log_metadata(
                            rejection_payload,
                            gate_kind="anonymous_daily_budget",
                        ),
                    )
                yield encode_sse(stage_payload("complete", result=payload))
                return
            assert route_context is not None
            if not route_context.allowed_feeds:
                yield encode_sse(stage_payload("complete", result={
                    "type": "chat",
                    "message": setup_required_ops_message(route_context.auth_user),
                    "watch_id": route_context.watch.get("watch_id"),
                    "watch_context": route_context.watch,
                    "effective_feeds": [],
                }))
                return
            orientation = build_ops_orientation_payload(
                query=query,
                effective_feeds=route_context.effective_feeds,
                selected_popup=body.get("selectedPopup"),
            )
            if orientation is not None:
                yield encode_sse(stage_payload("complete", result=orientation))
                return
            turn_limit_payload, _turn_limit_status, _turn_limit_headers = anonymous_turn_limit_rejection_payload(
                session_id=route_context.session_id,
                caller_ctx=route_context.caller_ctx,
                lane="ops",
            )
            if turn_limit_payload is not None:
                log_conversation(
                    route_context.frontend_session_id,
                    query,
                    turn_limit_payload.get("message", ""),
                    surface="ops",
                    intent=turn_limit_payload.get("error_code") or "anonymous_turn_limit_reached",
                    metadata=build_chat_gate_log_metadata(
                        turn_limit_payload,
                        gate_kind="anonymous_turn_limit",
                    ),
                )
                yield encode_sse(stage_payload("complete", result=turn_limit_payload))
                return
            register_anonymous_chat_turn(
                session_id=route_context.session_id,
                caller_ctx=route_context.caller_ctx,
                lane="ops",
            )

            usage_recorder = build_usage_recorder(
                surface="ops",
                call_kind="ops_main",
                session_id=route_context.session_id,
                request_id=route_context.request_id,
                caller_ctx=route_context.caller_ctx,
                qa_suite_metadata=route_context.qa_suite_metadata,
            )
            try:
                yield encode_sse(stage_payload("analyzing", message="Reviewing the Ops watch..."))
                yield encode_sse(stage_payload("thinking", message="Reading the current Ops report..."))
                result = await ops_orchestrator.run(
                    query=query,
                    chat_history=body.get("chatHistory", []),
                    watch=route_context.watch,
                    effective_feeds=route_context.effective_feeds,
                    usage_recorder=usage_recorder,
                    catalog_surface=route_context.catalog_surface,
                    cache=route_context.cache,
                    selected_popup=body.get("selectedPopup"),
                )
            finally:
                usage_recorder.flush()
            yield encode_sse(stage_payload("complete", result=result))
        except Exception as exc:
            logger.exception("Ops streaming chat error")
            log_app_error(type(exc).__name__, str(exc), surface="human_app", path="/chat/ops/stream")
            yield encode_sse(
                stage_payload(
                    "complete",
                    result=build_provider_error_payload(
                        exc,
                        lane="ops",
                        request_id=getattr(getattr(req, "state", None), "analytics_request_id", None),
                        stage="llm_call",
                    )
                    or build_chat_error_payload(
                        lane="ops",
                        message="Ops mode hit an internal error.",
                        error_code="ops_internal_error",
                        request_id=getattr(getattr(req, "state", None), "analytics_request_id", None),
                        stage="stream_route",
                        retry_hint="Retry the watch question. If it keeps failing, ask about one feed at a time."
                    ),
                )
            )

    return StreamingResponse(generate_events(), media_type="text/event-stream", headers=SSE_HEADERS)
