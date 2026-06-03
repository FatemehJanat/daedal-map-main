"""Ops mode API router endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from mapmover import logger
from mapmover.logging_analytics import hash_ip_for_analytics, log_app_error, log_conversation
from mapmover.ops_route_runtime import (
    prepare_ops_chat_route_context,
    prepare_ops_view_route_context,
    setup_required_ops_message,
    snapshot_ops_report,
)
from mapmover.ops_ticker import build_cached_aurora_payload, build_cached_ticker_payload
from mapmover.orchestrator_registry import get_orchestrator
from mapmover.routes.chat_shared import decode_json_or_msgpack_body, decode_request_body
from mapmover.routes.disasters.helpers import msgpack_error, msgpack_response
from mapmover.runtime.chat_route_support import build_usage_recorder
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
    """Current OVATION aurora forecast band for the map overlay. Public, read-only.

    Returns the renderable cells [[lon, lat, probability], ...] plus the forecast
    times, straight from the noaa_aurora live snapshot.
    """
    try:
        return msgpack_response(build_cached_aurora_payload())
    except Exception as exc:
        logger.exception("Ops aurora error")
        return msgpack_error(str(exc), 500)


@router.post("/api/ops/report")
async def ops_report_endpoint(req: Request):
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
        return msgpack_response({"type": "error", "message": "Ops mode encountered an error. Please try again."}, status_code=500)


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
            yield encode_sse(stage_payload("complete", result={"type": "error", "message": "Ops mode encountered an error. Please try again."}))

    return StreamingResponse(generate_events(), media_type="text/event-stream", headers=SSE_HEADERS)
