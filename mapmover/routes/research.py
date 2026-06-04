"""Research mode API router endpoints."""

from __future__ import annotations

import asyncio
import json

from anthropic import Anthropic
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from mapmover import logger
from mapmover.auth_context import build_session_cache_key, get_authenticated_user_async
from mapmover.catalog_surface import catalog_surface_scope
from mapmover.corpus_registry import corpus_registry
from mapmover.logging_analytics import log_app_error
from mapmover.research_chat_helpers import (
    _manifest_prompt_window_warning,
    _word_chunks,
)
from mapmover.research_corpus import (
    _annotate_manifest_saved_corpus_state,
    _build_browser_install_manifest,
    _build_research_focus_geojson,
    _decode_browser_source_artifact_payloads,
    _hydrate_saved_corpus,
    _json_safe_value,
    _load_saved_corpus_for_user,
    _read_browser_artifact_bytes,
    _restore_browser_install_source_snapshots,
    _restore_saved_corpus_from_published_browser_artifacts,
)
from mapmover.research_lane_runtime import (
    json_dumps_safe,
    research_request_id,
    run_research_chat,
)
from mapmover.research_route_runtime import (
    prepare_research_chat_route_context,
    settle_and_log_research_turn,
)
from mapmover.orchestrator_registry import get_orchestrator
from mapmover.routes.disasters.helpers import msgpack_error, msgpack_response
from mapmover.routes.chat_shared import (
    _catalog_surface_for_request,
    decode_json_or_msgpack_body,
    decode_request_body,
)
from mapmover.runtime.chat_route_support import build_usage_recorders
from mapmover.runtime.sse import SSE_HEADERS, encode_sse, stage_payload


router = APIRouter()
research_orchestrator = get_orchestrator("research")


@router.post("/api/research/corpus")
async def research_corpus_endpoint(req: Request):
    try:
        body = await decode_request_body(req)
        frontend_session_id = body.get("sessionId", "anonymous")
        auth_user = await get_authenticated_user_async(req)
        session_id = build_session_cache_key(frontend_session_id, auth_user)
        manifest = _annotate_manifest_saved_corpus_state(corpus_registry.manifest(session_id))
        focus_geojson = _build_research_focus_geojson(session_id)
        if focus_geojson:
            manifest["focus_geojson"] = focus_geojson
        return msgpack_response(manifest)
    except Exception as exc:
        logger.exception("Research corpus snapshot error")
        return msgpack_error(str(exc), 500)


@router.post("/api/research/load-saved-corpus")
async def research_load_saved_corpus_endpoint(req: Request):
    try:
        body = await decode_request_body(req)
        corpus_id = str(body.get("corpusId") or "").strip()
        if not corpus_id:
            return msgpack_error("No corpusId provided", 400)

        auth_user = await get_authenticated_user_async(req)
        user_id = (auth_user or {}).get("id")
        if not user_id:
            return msgpack_error("Authentication required to load a saved corpus", 401)

        frontend_session_id = body.get("sessionId", "anonymous")
        session_id = build_session_cache_key(frontend_session_id, auth_user)
        saved_corpus = _load_saved_corpus_for_user(user_id, corpus_id)
        if not saved_corpus:
            return msgpack_error("Saved corpus not found", 404)

        corpus_registry.set_saved_corpus(session_id, saved_corpus)
        load_path = "raw_hydration"
        hydration_warning = None
        try:
            _restore_saved_corpus_from_published_browser_artifacts(session_id, saved_corpus)
            hydration = {
                "loaded_sources": [],
                "skipped_sources": [],
                "restore_mode": "published_browser_artifacts",
            }
            load_path = "published_browser_artifacts"
        except Exception as snapshot_restore_error:
            logger.warning(
                "Research saved corpus published-browser-artifact restore failed for %s: %s",
                saved_corpus.get("id"),
                snapshot_restore_error,
            )
            hydration_warning = (
                "Published runtime snapshots were unavailable for this corpus, "
                "so Research fell back to a slower server-side restore."
            )
            hydration = _hydrate_saved_corpus(session_id, saved_corpus)
        manifest = _annotate_manifest_saved_corpus_state(corpus_registry.manifest(session_id))
        focus_geojson = _build_research_focus_geojson(session_id)
        prompt_window_warning = _manifest_prompt_window_warning(manifest)
        combined_warning = "\n\n".join(
            part for part in [hydration_warning, prompt_window_warning] if part
        ) or None
        return msgpack_response({
            "type": "saved_corpus_loaded",
            "message": f'Loaded "{saved_corpus.get("name")}" into the Research workspace.',
            "corpus": manifest,
            "hydration": hydration,
            "focus_geojson": focus_geojson,
            "warning": combined_warning,
            "load_path": load_path,
        })
    except Exception as exc:
        logger.exception("Research saved corpus load error")
        return msgpack_error(str(exc), 500)


@router.post("/api/research/browser-save/install-manifest")
async def research_build_browser_install_manifest_endpoint(req: Request):
    wants_msgpack = "application/msgpack" in str(req.headers.get("accept") or "").lower()
    try:
        body = await decode_json_or_msgpack_body(req)
        corpus_id = str(body.get("corpusId") or "").strip()
        if not corpus_id:
            payload = {"ok": False, "error": "No corpusId provided"}
            return msgpack_response(payload, status_code=400) if wants_msgpack else JSONResponse(payload, status_code=400)

        auth_user = await get_authenticated_user_async(req)
        user_id = (auth_user or {}).get("id")
        if not user_id:
            payload = {"ok": False, "error": "Authentication required"}
            return msgpack_response(payload, status_code=401) if wants_msgpack else JSONResponse(payload, status_code=401)

        saved_corpus = _load_saved_corpus_for_user(user_id, corpus_id)
        if not saved_corpus:
            payload = {"ok": False, "error": "Saved corpus not found"}
            return msgpack_response(payload, status_code=404) if wants_msgpack else JSONResponse(payload, status_code=404)

        install_manifest = _build_browser_install_manifest(saved_corpus)
        payload = _json_safe_value({
            "ok": True,
            "install_manifest": install_manifest,
        })
        return msgpack_response(payload) if wants_msgpack else JSONResponse(payload)
    except ValueError as exc:
        payload = {"ok": False, "error": str(exc)}
        return msgpack_response(payload, status_code=409) if wants_msgpack else JSONResponse(payload, status_code=409)
    except Exception as exc:
        logger.exception("Research browser install-manifest error")
        payload = {"ok": False, "error": str(exc)}
        return msgpack_response(payload, status_code=500) if wants_msgpack else JSONResponse(payload, status_code=500)


@router.get("/api/research/browser-save/source-artifact/{corpus_id}/{source_id}")
async def research_browser_source_artifact_endpoint(corpus_id: str, source_id: str, req: Request):
    try:
        corpus_id = str(corpus_id or "").strip()
        source_id = str(source_id or "").strip()
        if not corpus_id or not source_id:
            return JSONResponse({"ok": False, "error": "Missing corpus_id or source_id"}, status_code=400)

        auth_user = await get_authenticated_user_async(req)
        user_id = (auth_user or {}).get("id")
        if not user_id:
            return JSONResponse({"ok": False, "error": "Authentication required"}, status_code=401)

        saved_corpus = _load_saved_corpus_for_user(user_id, corpus_id)
        if not saved_corpus:
            return JSONResponse({"ok": False, "error": "Saved corpus not found"}, status_code=404)

        install_manifest = _build_browser_install_manifest(saved_corpus)
        source_entry = next(
            (entry for entry in install_manifest.get("sources") or [] if str(entry.get("source_id") or "").strip() == source_id),
            None,
        )
        if not source_entry:
            return JSONResponse({"ok": False, "error": "Source is not part of the saved corpus"}, status_code=404)

        artifact = source_entry.get("browser_artifact") or {}
        storage_key = str(artifact.get("storage_key") or "").strip()
        artifact_bytes, content_type = _read_browser_artifact_bytes(storage_key)
        headers = {
            "Content-Length": str(len(artifact_bytes)),
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": f'inline; filename="{source_id}_runtime_snapshot_v1.json.gz"',
            "X-DaedalMap-Source-Id": source_id,
            "X-DaedalMap-Artifact-Version": str(artifact.get("artifact_version") or ""),
            "X-DaedalMap-Sha256": str(artifact.get("sha256") or ""),
        }
        return Response(content=artifact_bytes, media_type=content_type or "application/gzip", headers=headers)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    except FileNotFoundError as exc:
        logger.warning("Research browser source artifact missing: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
    except Exception as exc:
        logger.exception("Research browser source artifact error")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@router.post("/api/research/browser-save/load-install-manifest")
async def research_load_browser_install_manifest_endpoint(req: Request):
    wants_msgpack = "application/msgpack" in str(req.headers.get("accept") or "").lower()
    try:
        body = await decode_json_or_msgpack_body(req)
        corpus_id = str(body.get("corpusId") or "").strip()
        source_snapshots = body.get("sourceSnapshots")
        source_artifacts = body.get("sourceArtifacts")
        if not corpus_id:
            payload = {"ok": False, "error": "No corpusId provided"}
            return msgpack_response(payload, status_code=400) if wants_msgpack else JSONResponse(payload, status_code=400)
        if isinstance(source_artifacts, list):
            source_snapshots = _decode_browser_source_artifact_payloads(source_artifacts)
        if not isinstance(source_snapshots, list):
            payload = {"ok": False, "error": "No sourceArtifacts or sourceSnapshots provided"}
            return msgpack_response(payload, status_code=400) if wants_msgpack else JSONResponse(payload, status_code=400)

        auth_user = await get_authenticated_user_async(req)
        user_id = (auth_user or {}).get("id")
        if not user_id:
            payload = {"ok": False, "error": "Authentication required"}
            return msgpack_response(payload, status_code=401) if wants_msgpack else JSONResponse(payload, status_code=401)

        frontend_session_id = str(body.get("sessionId") or f"browser-save:{corpus_id}").strip() or f"browser-save:{corpus_id}"
        session_id = build_session_cache_key(frontend_session_id, auth_user)
        saved_corpus = _load_saved_corpus_for_user(user_id, corpus_id)
        if not saved_corpus:
            payload = {"ok": False, "error": "Saved corpus not found"}
            return msgpack_response(payload, status_code=404) if wants_msgpack else JSONResponse(payload, status_code=404)

        manifest = _annotate_manifest_saved_corpus_state(
            _restore_browser_install_source_snapshots(
                session_id=session_id,
                saved_corpus=saved_corpus,
                source_snapshots=source_snapshots,
            )
        )
        saved_name = ((manifest.get("saved_corpus") or {}).get("name") or "Saved corpus")
        payload = _json_safe_value({
            "ok": True,
            "corpus": manifest,
            "message": f'Loaded "{saved_name}" into the Research workspace from browser-saved source artifacts.',
        })
        return msgpack_response(payload) if wants_msgpack else JSONResponse(payload)
    except ValueError as exc:
        payload = {"ok": False, "error": str(exc)}
        return msgpack_response(payload, status_code=409) if wants_msgpack else JSONResponse(payload, status_code=409)
    except Exception as exc:
        logger.exception("Research browser install-manifest restore error")
        payload = {"ok": False, "error": str(exc)}
        return msgpack_response(payload, status_code=500) if wants_msgpack else JSONResponse(payload, status_code=500)


@router.post("/chat/research")
async def research_chat_endpoint(req: Request):
    try:
        body = await decode_request_body(req)
        query = body.get("query", "")
        if not query:
            return msgpack_error("No query provided", 400)
        route_context, route_error, rejection_payload, rejection_status, rejection_headers = await prepare_research_chat_route_context(
            req,
            body,
            query=query,
            request_id_func=research_request_id,
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
        usage_recorder, rescue_usage_recorder = build_usage_recorders(
            surface="research",
            call_kinds=("research_main", "research_rescue"),
            session_id=route_context.session_id,
            request_id=route_context.request_id,
            caller_ctx=route_context.caller_ctx,
            qa_suite_metadata=route_context.qa_suite_metadata,
        )
        try:
            result = await research_orchestrator.run(
                session_id=route_context.session_id,
                query=query,
                chat_history=body.get("chatHistory", []),
                research_memory=body.get("researchMemory"),
                force_large_display=bool(body.get("force_research_display")),
                usage_recorder=usage_recorder,
                rescue_usage_recorder=rescue_usage_recorder,
                catalog_surface=route_context.catalog_surface,
            )
        finally:
            usage_recorder.flush()
            rescue_usage_recorder.flush(skip_if_empty=True)
        await settle_and_log_research_turn(
            route_context=route_context,
            query=query,
            result=result,
            user_agent=(req.headers.get("user-agent") or "")[:300] or None,
        )
        return msgpack_response(result)
    except Exception as exc:
        logger.exception("Research chat error")
        log_app_error(type(exc).__name__, str(exc), surface="human_app", path="/chat/research")
        return msgpack_response({"type": "error", "message": "Research mode encountered an error. Please try again."}, status_code=500)


@router.post("/chat/research/stream")
async def research_chat_stream_endpoint(req: Request):
    body = await decode_json_or_msgpack_body(req)

    async def generate_events():
        try:
            query = body.get("query", "")
            if not query:
                yield encode_sse(stage_payload("complete", result={"type": "error", "message": "No query provided"}))
                return
            route_context, route_error, rejection_payload, _rejection_status, _rejection_headers = await prepare_research_chat_route_context(
                req,
                body,
                query=query,
                request_id_func=research_request_id,
            )
            if route_error or rejection_payload is not None:
                payload = rejection_payload or {"type": "error", "message": "WIP catalog access is limited to admin accounts."}
                yield encode_sse(stage_payload("complete", result=payload))
                return
            assert route_context is not None
            usage_recorder, rescue_usage_recorder = build_usage_recorders(
                surface="research",
                call_kinds=("research_main", "research_rescue"),
                session_id=route_context.session_id,
                request_id=route_context.request_id,
                caller_ctx=route_context.caller_ctx,
                qa_suite_metadata=route_context.qa_suite_metadata,
            )

            yield encode_sse(stage_payload("corpus", message="Reading Research workspace..."), dumps=json_dumps_safe)
            yield encode_sse(stage_payload("thinking", message="Researching loaded workspace data..."), dumps=json_dumps_safe)

            bus, task = await research_orchestrator.run_with_progress(
                session_id=route_context.session_id,
                query=query,
                chat_history=body.get("chatHistory", []),
                research_memory=body.get("researchMemory"),
                force_large_display=bool(body.get("force_research_display")),
                usage_recorder=usage_recorder,
                rescue_usage_recorder=rescue_usage_recorder,
                catalog_surface=route_context.catalog_surface,
            )
            try:
                async for event in bus.drain_until(
                    task,
                    heartbeat_seconds=4.0,
                    heartbeat=research_orchestrator.heartbeat,
                ):
                    yield encode_sse(progress_payload(event), dumps=json_dumps_safe)

                result = await task
            finally:
                usage_recorder.flush()
                rescue_usage_recorder.flush(skip_if_empty=True)
            await settle_and_log_research_turn(
                route_context=route_context,
                query=query,
                result=result,
                user_agent=(req.headers.get("user-agent") or "")[:300] or None,
            )
            yield encode_sse(stage_payload("writing", message="Writing research answer..."), dumps=json_dumps_safe)
            if result.get("type") == "chat" and result.get("message"):
                yield encode_sse(stage_payload("answer_start", message=""), dumps=json_dumps_safe)
                for chunk in _word_chunks(result.get("message", "")):
                    yield encode_sse(stage_payload("delta", text=chunk), dumps=json_dumps_safe)
                    await asyncio.sleep(0.035)
            yield encode_sse(stage_payload("complete", result=result), dumps=json_dumps_safe)
        except Exception as exc:
            logger.exception("Research chat stream error")
            log_app_error(type(exc).__name__, str(exc), surface="human_app", path="/chat/research/stream")
            error_result = {"type": "error", "message": "Research mode encountered an error. Please try again."}
            yield encode_sse(stage_payload("complete", result=error_result), dumps=json_dumps_safe)

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
