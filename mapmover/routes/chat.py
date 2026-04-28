"""Chat API router endpoints."""

import asyncio
import hashlib
import json
import os
import time

import msgpack
from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from mapmover.auth_context import build_session_cache_key, get_authenticated_user, get_authenticated_user_async
from mapmover import logger, session_manager
from mapmover.corpus_registry import corpus_registry
from mapmover.order_executor import execute_order
from mapmover.order_taker import interpret_request
from mapmover.postprocessor import get_display_items, postprocess_order
from mapmover.preprocessor import preprocess_query
from mapmover.progress_bus import ProgressBus, ProgressEvent
from mapmover.routes.disasters.helpers import msgpack_error, msgpack_response
from mapmover.logging_analytics import hash_ip_for_analytics, log_app_error, log_conversation
from mapmover.security import get_client_ip, rate_limiter


# Heartbeat copy for explorer mode. Used only when the LLM tool loop
# is silent for longer than the heartbeat window. Cycles by idle count.
_EXPLORER_HEARTBEAT_MESSAGES = [
    "Still working through your request...",
    "Cross-checking the catalog...",
    "Putting your order together...",
]


def _explorer_heartbeat(idle_count: int) -> ProgressEvent:
    message = _EXPLORER_HEARTBEAT_MESSAGES[idle_count % len(_EXPLORER_HEARTBEAT_MESSAGES)]
    return ProgressEvent(stage="thinking", message=message, extra={"heartbeat": True})


router = APIRouter()


def _chat_trace_id(session_id: str, query: str) -> str:
    seed = f"{session_id}|{query[:80]}"
    return hashlib.md5(seed.encode()).hexdigest()[:10]


def _chat_log_timing(trace_id: str, stage: str, started_at: float, extra: str = "") -> float:
    now = time.perf_counter()
    elapsed_ms = (now - started_at) * 1000
    suffix = f" | {extra}" if extra else ""
    logger.info(f"[chat:{trace_id}] {stage}: {elapsed_ms:.1f}ms{suffix}")
    return now


def _rate_limited_message(message: str, retry_after: int) -> Response:
    response = msgpack_response({"error": message, "retry_after": retry_after}, status_code=429)
    response.headers["Retry-After"] = str(retry_after)
    return response


def _confirmed_order_rate_limit(req: Request, auth_user: dict | None) -> Response | None:
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


def _address_prompt_response(prompt: dict | None) -> dict:
    prompt = prompt or {}
    return {
        "type": "address_prompt",
        "message": prompt.get("message") or "Start typing an address and choose a suggestion.",
        "placeholder": prompt.get("placeholder") or "Search for an address...",
    }


def _execute_confirmed_order_with_session_cache(cache, confirmed_order: dict, *, force_refetch: bool = False):
    order_str = json.dumps(confirmed_order, sort_keys=True)
    request_key = hashlib.md5(order_str.encode()).hexdigest()[:16]
    if not force_refetch:
        cached_result = cache.get_cached_result(request_key)
        if cached_result is not None:
            return cached_result, request_key, True
    result = execute_order(confirmed_order)
    cache.store_result(request_key, result)
    return result, request_key, False


def _set_chat_analytics(
    req: Request,
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


async def decode_request_body(request: Request) -> dict:
    """Decode MessagePack request body."""
    body_bytes = await request.body()
    return msgpack.unpackb(body_bytes, raw=False)


@router.post("/chat")
async def chat_endpoint(req: Request):
    """Chat endpoint - Order Taker model."""
    t_request_start = time.perf_counter()
    trace_id = "unknown"
    try:
        body = await decode_request_body(req)

        frontend_session_id = body.get("sessionId", "anonymous")
        auth_user = await get_authenticated_user_async(req)
        client_ip = get_client_ip(req)
        user_id = auth_user.get("id") if auth_user else None
        if user_id:
            allowed, retry_after = rate_limiter.check(f"chat:user:{user_id}", limit=60, window_seconds=60)
            if not allowed:
                return _rate_limited_message("Too many chat requests. Please slow down and try again shortly.", retry_after)
        else:
            allowed, retry_after = rate_limiter.check(f"chat:ip:{client_ip}", limit=20, window_seconds=60)
            if not allowed:
                return _rate_limited_message("Too many anonymous chat requests. Please wait a moment and try again.", retry_after)

        session_id = build_session_cache_key(frontend_session_id, auth_user)
        query_preview = body.get("query", "") or "[confirmed_order]"
        trace_id = _chat_trace_id(session_id, query_preview)
        logger.info(
            f"[chat:{trace_id}] request start | confirmed_order={bool(body.get('confirmed_order'))} "
            f"| query_len={len(body.get('query', '') or '')} | user={'auth' if user_id else 'anon'}"
        )
        _chat_log_timing(trace_id, "body_decoded", t_request_start, f"session={frontend_session_id}")
        cache = session_manager.get_or_create(session_id)

        if body.get("confirmed_order"):
            confirmed_order_rate_limit = _confirmed_order_rate_limit(req, auth_user)
            if confirmed_order_rate_limit:
                _set_chat_analytics(
                    req,
                    lane="confirmed_order",
                    confirmed_order=True,
                    error_code="confirmed_order_rate_limited",
                )
                return confirmed_order_rate_limit
            try:
                confirmed_order = body["confirmed_order"]
                force_refetch = body.get("force", False)
                t_exec_start = time.perf_counter()
                result, request_key, reused_cached_result = _execute_confirmed_order_with_session_cache(
                    cache,
                    confirmed_order,
                    force_refetch=force_refetch,
                )
                _chat_log_timing(
                    trace_id,
                    "confirmed_order_executed",
                    t_exec_start,
                    f"request_key={request_key} type={result.get('type')} source={result.get('source_id')} reused={reused_cached_result}",
                )
                _set_chat_analytics(
                    req,
                    lane="confirmed_order",
                    confirmed_order=True,
                    request_key=request_key,
                    reused_cached_result=reused_cached_result,
                    force_refetch=bool(force_refetch),
                    result_type=result.get("type"),
                    source_id=result.get("source_id"),
                )
                if result.get("type") == "error":
                    _set_chat_analytics(
                        req,
                        lane="confirmed_order",
                        confirmed_order=True,
                        request_key=request_key,
                        reused_cached_result=reused_cached_result,
                        force_refetch=bool(force_refetch),
                        result_type=result.get("type"),
                        source_id=result.get("source_id"),
                        error_code="confirmed_order_execution_error",
                    )
                    return msgpack_response({"type": "error", "message": result.get("message", "Order execution failed.")}, status_code=400)

                if result.get("action") == "remove":
                    logger.info(f"Removal order executed: {result.get('count')} items from {result.get('source_id')}")
                    return msgpack_response({"type": "order_response", **result})
                if result.get("type") == "mixed_order":
                    logger.info(f"Mixed order executed: added {result.get('add_count', 0)}, removed {result.get('remove_count', 0)}")
                    return msgpack_response(result)

                if force_refetch:
                    logger.info("Force refetch requested - clearing session cache for this data")
                    cache.clear()

                is_events = result.get("type") == "events"
                is_geometry = result.get("data_type") == "geometry"
                event_type_to_overlay = {
                    "earthquake": "earthquakes",
                    "volcano": "volcanoes",
                    "tsunami": "tsunamis",
                    "hurricane": "hurricanes",
                    "wildfire": "wildfires",
                    "tornado": "tornadoes",
                    "flood": "floods",
                    "drought": "drought",
                    "landslide": "landslides",
                }
                event_type = result.get("event_type", "")
                source_id = event_type_to_overlay.get(event_type, event_type) if is_events else result.get("metric_key", "data")
                geojson = result["geojson"]
                features = geojson.get("features", [])
                original_count = len(features)

                if is_events:
                    new_features = cache.filter_events(features)
                    delta_count = len(new_features)
                    filtered_geojson = {"type": "FeatureCollection", "features": new_features}
                    filtered_year_data = None
                elif is_geometry:
                    new_features = cache.filter_geometry_features(features)
                    delta_count = len(new_features)
                    filtered_geojson = {"type": "FeatureCollection", "features": new_features}
                    filtered_year_data = None
                elif result.get("multi_year") and result.get("year_data"):
                    year_data = result["year_data"]
                    filtered_year_data = cache.filter_year_data(year_data)

                    new_loc_ids = set()
                    for loc_data in filtered_year_data.values():
                        new_loc_ids.update(loc_data.keys())

                    new_features = [f for f in features if (f.get("properties", {}).get("loc_id") or f.get("id")) in new_loc_ids]
                    delta_count = len(new_features)
                    filtered_geojson = {"type": "FeatureCollection", "features": new_features}
                else:
                    new_features = features
                    delta_count = original_count
                    filtered_geojson = geojson
                    filtered_year_data = None

                if delta_count == 0 and original_count > 0:
                    logger.debug(f"Dedup: all {original_count} features already sent, returning already_loaded")
                    return msgpack_response(
                        {
                            "type": "already_loaded",
                            "message": f"This data ({original_count} features) is already loaded on your map.",
                            "summary": result.get("summary", ""),
                        }
                    )

                response = {
                    "type": result.get("type", "data"),
                    "data_type": result.get("data_type"),
                    "source_id": result.get("source_id"),
                    "available_geo_levels": result.get("available_geo_levels", []),
                    "geojson": filtered_geojson,
                    "summary": result.get("summary", ""),
                    "count": result.get("count", delta_count),
                    "sources": result.get("sources", []),
                }

                if is_events:
                    response["event_type"] = result.get("event_type")
                    response["time_range"] = result.get("time_range")
                if is_geometry:
                    geo_level = result.get("geographic_level") or result.get("overlay_type", "zcta")
                    response["overlay_type"] = geo_level
                    response["geographic_level"] = geo_level
                if result.get("multi_year"):
                    response["multi_year"] = True
                    response["year_range"] = result["year_range"]
                    response["metric_key"] = result.get("metric_key")
                    response["available_metrics"] = result.get("available_metrics", [])
                    response["metric_year_ranges"] = result.get("metric_year_ranges", {})
                    response["year_data"] = filtered_year_data if filtered_year_data else {}

                if is_events and new_features:
                    cache.register_sent_events(new_features, source_id)
                elif is_geometry and new_features:
                    geo_source_id = result.get("source_id") or "geometry_zcta"
                    cache.register_sent_geometry(new_features, geo_source_id)
                elif filtered_year_data:
                    cache.register_sent_year_data(filtered_year_data)

                corpus_registry.register_order_result(
                    session_id=session_id,
                    request_key=request_key,
                    order=confirmed_order,
                    response=response,
                )

                cache.touch()
                if delta_count < original_count:
                    logger.info(f"Delta sent: {delta_count}/{original_count} features ({original_count - delta_count} deduped)")

                _chat_log_timing(trace_id, "responding", t_request_start, f"type={response.get('type')} count={response.get('count')}")
                log_conversation(
                    frontend_session_id,
                    confirmed_order.get("summary", "confirmed_order"),
                    response.get("summary", ""),
                    surface="explorer_map",
                    dataset_selected=response.get("source_id"),
                    results_count=response.get("count", 0),
                    ip_hash=hash_ip_for_analytics(client_ip),
                    user_agent=(req.headers.get("user-agent") or "")[:300] or None,
                )
                return msgpack_response(response)
            except Exception as e:
                logger.exception(f"[chat:{trace_id}] Order execution error")
                _set_chat_analytics(
                    req,
                    lane="confirmed_order",
                    confirmed_order=True,
                    error_code="confirmed_order_exception",
                )
                log_app_error(
                    type(e).__name__,
                    str(e),
                    surface="human_app",
                    path="/chat",
                )
                return msgpack_response(_confirmed_order_user_error(), status_code=400)

        query = body.get("query", "")
        chat_history = body.get("chatHistory", [])
        viewport = body.get("viewport")
        resolved_location = body.get("resolved_location")
        active_overlays = body.get("activeOverlays")
        cache_stats = body.get("cacheStats")
        time_state = body.get("timeState")
        saved_order_names = body.get("savedOrderNames", [])
        loaded_data = body.get("loadedData", [])
        tutorial_mode = body.get("tutorialMode", {})

        if not query:
            return msgpack_error("No query provided", 400)

        logger.debug(f"[chat:{trace_id}] Chat query: {query[:100]}...")
        t_preprocess_start = time.perf_counter()
        hints = preprocess_query(
            query,
            viewport=viewport,
            active_overlays=active_overlays,
            cache_stats=cache_stats,
            saved_order_names=saved_order_names,
            time_state=time_state,
            loaded_data=loaded_data,
        )
        hints["original_query"] = query
        _chat_log_timing(
            trace_id,
            "preprocess_complete",
            t_preprocess_start,
            f"show_borders={bool(hints.get('show_borders'))} nav={bool((hints.get('navigation') or {}).get('is_navigation'))}",
        )

        if resolved_location:
            hints["location"] = {
                "matched_term": resolved_location.get("matched_term"),
                "iso3": resolved_location.get("iso3"),
                "country_name": resolved_location.get("country_name"),
                "loc_id": resolved_location.get("loc_id"),
                "is_subregion": resolved_location.get("loc_id") != resolved_location.get("iso3"),
                "source": "disambiguation_selection",
            }
            hints["disambiguation"] = None

        if hints.get("tutorial_mode"):
            action = hints["tutorial_mode"].get("action", "toggle")
            current_enabled = bool(tutorial_mode.get("enabled"))
            enabled = (not current_enabled) if action == "toggle" else (action == "on")
            message = (
                "Tutorial mode on. Hover or tap a help marker to see what that part of the app does."
                if enabled
                else "Tutorial mode off."
            )
            return msgpack_response(
                {
                    "type": "tutorial_mode",
                    "action": action,
                    "enabled": enabled,
                    "message": message,
                }
            )

        if hints.get("address_prompt"):
            return msgpack_response(_address_prompt_response(hints.get("address_prompt")))

        if hints.get("show_borders"):
            previous_options = body.get("previous_disambiguation_options", [])
            loc_ids_to_show = [opt.get("loc_id") for opt in previous_options if opt.get("loc_id")] if previous_options else []
            if loc_ids_to_show:
                from mapmover.data_loading import fetch_geometries_by_loc_ids

                geojson = fetch_geometries_by_loc_ids(loc_ids_to_show)
                return msgpack_response(
                    {
                        "type": "navigate",
                        "message": f"Showing {len(loc_ids_to_show)} locations on the map. Click any location to see data options.",
                        "locations": previous_options if previous_options else [{"loc_id": lid} for lid in loc_ids_to_show],
                        "loc_ids": loc_ids_to_show,
                        "original_query": query,
                        "geojson": geojson,
                    }
                )
            return msgpack_response(
                {
                    "type": "chat",
                    "reply": "I don't have a list of locations to display. Please first ask about specific locations (e.g., 'show me washington county') to get a list.",
                }
            )

        navigation = hints.get("navigation")
        if navigation and navigation.get("is_navigation"):
            locations = navigation.get("locations", [])
            if len(locations) == 1 and locations[0].get("drill_to_level"):
                loc = locations[0]
                loc_id = loc.get("loc_id")
                drill_level = loc.get("drill_to_level")
                name = loc.get("matched_term", loc_id)
                return msgpack_response(
                    {
                        "type": "drilldown",
                        "message": f"Showing {drill_level} of {name}...",
                        "loc_id": loc_id,
                        "name": name,
                        "drill_to_level": drill_level,
                        "original_query": query,
                    }
                )

        t_interpret_start = time.perf_counter()
        # Run the synchronous LLM call in a thread so we do not block the
        # event loop for other concurrent requests on this worker.
        result = await asyncio.to_thread(interpret_request, query, chat_history, hints=hints)
        _set_chat_analytics(
            req,
            lane="llm_chat",
            confirmed_order=False,
            result_type=result.get("type"),
        )
        _chat_log_timing(trace_id, "interpret_complete", t_interpret_start, f"type={result.get('type')}")

        if result["type"] == "order":
            result_summary = result.get("summary") or result.get("order", {}).get("summary") or "Data request"
            t_postprocess_start = time.perf_counter()
            processed = postprocess_order(result["order"], hints)
            _chat_log_timing(
                trace_id,
                "postprocess_complete",
                t_postprocess_start,
                f"items={len(processed.get('items', []) or [])} derived={len(processed.get('derived_specs', []) or [])}",
            )
            if processed.get("needs_clarify"):
                _chat_log_timing(trace_id, "responding", t_request_start, "type=clarify_multiple_paths")
                return msgpack_response(
                    {
                        "type": "clarify",
                        "message": processed.get("clarify_message") or processed.get("validation_summary") or "I need a more specific path before I can run that.",
                        "summary": result_summary,
                        "full_order": processed,
                    }
                )
            if not processed.get("all_valid", True):
                _chat_log_timing(trace_id, "responding", t_request_start, "type=clarify_invalid_order")
                return msgpack_response(
                    {
                        "type": "clarify",
                        "message": processed.get("validation_summary") or "I need a more specific executable request before I can run that.",
                        "summary": result_summary,
                        "full_order": processed,
                    }
                )
            if processed.get("metric_warning") and not body.get("force_metrics"):
                display_items = get_display_items(processed.get("items", []), processed.get("derived_specs", []))
                full_order = {**result["order"], "items": display_items, "derived_specs": processed.get("derived_specs", [])}
                _chat_log_timing(trace_id, "responding", t_request_start, "type=metric_warning")
                return msgpack_response(
                    {
                        "type": "metric_warning",
                        "message": processed["metric_warning"]["message"],
                        "metric_count": processed["metric_warning"]["count"],
                        "gate": processed["metric_warning"].get("gate"),
                        "pending_order": full_order,
                        "full_order": processed,
                        "summary": result_summary,
                    }
                )

            display_items = get_display_items(processed.get("items", []), processed.get("derived_specs", []))
            _chat_log_timing(trace_id, "responding", t_request_start, "type=order")
            return msgpack_response(
                {
                    "type": "order",
                    "order": {**result["order"], "items": display_items, "derived_specs": processed.get("derived_specs", [])},
                    "full_order": processed,
                    "summary": result_summary,
                    "validation_summary": processed.get("validation_summary"),
                    "all_valid": processed.get("all_valid", True),
                }
            )

        if result["type"] == "navigate":
            locations = result.get("locations", [])
            loc_ids = [loc.get("loc_id") for loc in locations if loc.get("loc_id")]
            geometry_overlay = result.get("geometry_overlay")
            geojson = {"type": "FeatureCollection", "features": []}
            if geometry_overlay:
                from mapmover.order_executor import execute_geometry_overlay

                geojson = execute_geometry_overlay(geometry_overlay, loc_ids)
            _chat_log_timing(trace_id, "responding", t_request_start, f"type=navigate locations={len(locations)}")
            return msgpack_response(
                {
                    "type": "navigate",
                    "data_type": "geometry" if geometry_overlay else None,
                    "message": result.get("message", f"Showing {len(locations)} location(s)"),
                    "locations": locations,
                    "loc_ids": loc_ids,
                    "original_query": query,
                    "geojson": geojson,
                    "geometry_overlay": geometry_overlay,
                }
            )

        if result["type"] == "disambiguate":
            _chat_log_timing(trace_id, "responding", t_request_start, f"type=disambiguate options={len(result.get('options', []))}")
            return msgpack_response(
                {
                    "type": "disambiguate",
                    "message": result.get("message", "Multiple locations found. Please select one."),
                    "query_term": result.get("query_term", "location"),
                    "original_query": query,
                    "options": result.get("options", []),
                    "geojson": {"type": "FeatureCollection", "features": []},
                }
            )

        if result["type"] == "filter_update":
            _chat_log_timing(trace_id, "responding", t_request_start, "type=filter_update")
            return msgpack_response(
                {
                    "type": "filter_update",
                    "overlay": result.get("overlay", ""),
                    "filters": result.get("filters", {}),
                    "message": result.get("message", "Updating filters"),
                }
            )

        if result["type"] == "overlay_toggle":
            _chat_log_timing(trace_id, "responding", t_request_start, "type=overlay_toggle")
            return msgpack_response(
                {
                    "type": "overlay_toggle",
                    "overlay": result.get("overlay", ""),
                    "enabled": result.get("enabled", True),
                    "message": result.get("message", "Toggling overlay"),
                }
            )

        if result["type"] == "clarify":
            _chat_log_timing(trace_id, "responding", t_request_start, "type=clarify")
            return msgpack_response(
                {"type": "clarify", "message": result["message"], "geojson": {"type": "FeatureCollection", "features": []}, "needsMoreInfo": True}
            )

        _chat_log_timing(trace_id, "responding", t_request_start, "type=chat")
        chat_result = result.get("message", "I'm not sure how to help with that.")
        log_conversation(
            frontend_session_id,
            query,
            chat_result,
            surface="explorer",
            intent=result.get("type"),
            ip_hash=hash_ip_for_analytics(client_ip),
            user_agent=(req.headers.get("user-agent") or "")[:300] or None,
        )
        return msgpack_response(
            {
                "type": "chat",
                "message": chat_result,
                "geojson": {"type": "FeatureCollection", "features": []},
                "auth_user": {"id": auth_user.get("id"), "email": auth_user.get("email")} if auth_user else None,
                "needsMoreInfo": False,
            }
        )
    except Exception as e:
        logger.exception(f"[chat:{trace_id}] Chat error")
        log_app_error(
            type(e).__name__,
            str(e),
            surface="human_app",
            path="/chat",
        )
        return msgpack_response(
            {
                "type": "error",
                "message": "Sorry, I encountered an error. Please try again.",
                "geojson": {"type": "FeatureCollection", "features": []},
            },
            status_code=500,
        )


@router.post("/chat/stream")
async def chat_stream_endpoint(req: Request):
    """Streaming chat endpoint - sends progress updates via SSE."""
    import asyncio
    import time

    t_start = time.time()
    client_ip = get_client_ip(req)
    body_bytes = await req.body()
    try:
        body = json.loads(body_bytes.decode("utf-8"))
    except json.JSONDecodeError:
        body = msgpack.unpackb(body_bytes, raw=False)
    t_parse = time.time()
    logger.debug(f"[TIMING] Body parse: {(t_parse - t_start) * 1000:.0f}ms")

    async def generate_events():
        try:
            frontend_session_id = body.get("sessionId", "anonymous")
            auth_user = await get_authenticated_user_async(req)
            confirmed_order_rate_limit = None
            if body.get("confirmed_order"):
                confirmed_order_rate_limit = _confirmed_order_rate_limit(req, auth_user)
            if confirmed_order_rate_limit:
                retry_after = int(confirmed_order_rate_limit.headers.get("Retry-After", "1"))
                message = "Too many direct order executions. Please slow down and try again shortly."
                yield f"data: {json.dumps({'stage': 'complete', 'result': {'type': 'error', 'message': message, 'retry_after': retry_after}})}\n\n"
                return
            session_id = build_session_cache_key(frontend_session_id, auth_user)
            cache = session_manager.get_or_create(session_id)

            if body.get("confirmed_order"):
                yield f"data: {json.dumps({'stage': 'fetching', 'message': 'Fetching data...'})}\n\n"
                try:
                    result, request_key, reused_cached_result = _execute_confirmed_order_with_session_cache(
                        cache,
                        body["confirmed_order"],
                        force_refetch=bool(body.get("force", False)),
                    )
                    logger.info(
                        "Streaming confirmed_order request_key=%s reused=%s type=%s source=%s",
                        request_key,
                        reused_cached_result,
                        result.get("type"),
                        result.get("source_id"),
                    )
                    response = {
                        "type": result.get("type", "data"),
                        "data_type": result.get("data_type"),
                        "source_id": result.get("source_id"),
                        "available_geo_levels": result.get("available_geo_levels", []),
                        "geojson": result["geojson"],
                        "summary": result["summary"],
                        "count": result["count"],
                        "sources": result.get("sources", []),
                    }
                    if result.get("multi_year"):
                        response["multi_year"] = True
                        response["year_data"] = result["year_data"]
                        response["year_range"] = result["year_range"]
                        response["metric_key"] = result.get("metric_key")
                        response["available_metrics"] = result.get("available_metrics", [])
                        response["metric_year_ranges"] = result.get("metric_year_ranges", {})
                    corpus_registry.register_order_result(
                        session_id=session_id,
                        request_key=request_key,
                        order=body["confirmed_order"],
                        response=response,
                    )
                    log_conversation(
                        frontend_session_id,
                        body["confirmed_order"].get("summary", "confirmed_order"),
                        response.get("summary", ""),
                        surface="explorer_map",
                        dataset_selected=response.get("source_id"),
                        results_count=response.get("count", 0),
                        ip_hash=hash_ip_for_analytics(client_ip),
                        user_agent=(req.headers.get("user-agent") or "")[:300] or None,
                    )
                    yield f"data: {json.dumps({'stage': 'complete', 'result': response})}\n\n"
                except Exception as e:
                    logger.exception("Streaming order execution error")
                    log_app_error(type(e).__name__, str(e), surface="human_app", path="/chat/stream")
                    yield f"data: {json.dumps({'stage': 'complete', 'result': _confirmed_order_user_error()})}\n\n"
                return

            query = body.get("query", "")
            chat_history = body.get("chatHistory", [])
            viewport = body.get("viewport")
            resolved_location = body.get("resolved_location")
            active_overlays = body.get("activeOverlays")
            cache_stats = body.get("cacheStats")
            time_state = body.get("timeState")
            saved_order_names = body.get("savedOrderNames", [])
            loaded_data = body.get("loadedData", [])

            if not query:
                yield f"data: {json.dumps({'stage': 'complete', 'result': {'type': 'error', 'message': 'No query provided'}})}\n\n"
                return

            t_preprocess_start = time.time()
            yield f"data: {json.dumps({'stage': 'analyzing', 'message': 'Analyzing your request...'})}\n\n"
            await asyncio.sleep(0)

            hints = preprocess_query(
                query,
                viewport=viewport,
                active_overlays=active_overlays,
                cache_stats=cache_stats,
                saved_order_names=saved_order_names,
                time_state=time_state,
                loaded_data=loaded_data,
            )
            hints["original_query"] = query
            t_preprocess_end = time.time()
            logger.info(f"[TIMING] Preprocessing: {(t_preprocess_end - t_preprocess_start) * 1000:.0f}ms")

            if resolved_location:
                hints["location"] = {
                    "matched_term": resolved_location.get("matched_term"),
                    "iso3": resolved_location.get("iso3"),
                    "country_name": resolved_location.get("country_name"),
                    "loc_id": resolved_location.get("loc_id"),
                    "is_subregion": resolved_location.get("loc_id") != resolved_location.get("iso3"),
                    "source": "disambiguation_selection",
                }
                hints["disambiguation"] = None

            if hints.get("show_borders"):
                previous_options = body.get("previous_disambiguation_options", [])
                if previous_options:
                    loc_ids_to_show = [opt.get("loc_id") for opt in previous_options if opt.get("loc_id")]
                    if loc_ids_to_show:
                        from mapmover.data_loading import fetch_geometries_by_loc_ids

                        geojson = fetch_geometries_by_loc_ids(loc_ids_to_show)
                        result = {
                            "type": "navigate",
                            "message": f"Showing {len(loc_ids_to_show)} locations on the map.",
                            "locations": previous_options,
                            "loc_ids": loc_ids_to_show,
                            "original_query": query,
                            "geojson": geojson,
                        }
                        yield f"data: {json.dumps({'stage': 'complete', 'result': result})}\n\n"
                        return
                result = {"type": "chat", "reply": "I don't have a list of locations to display."}
                yield f"data: {json.dumps({'stage': 'complete', 'result': result})}\n\n"
                return

            if hints.get("address_prompt"):
                yield f"data: {json.dumps({'stage': 'complete', 'result': _address_prompt_response(hints.get('address_prompt'))})}\n\n"
                return

            navigation = hints.get("navigation")
            if navigation and navigation.get("is_navigation"):
                locations = navigation.get("locations", [])
                if len(locations) == 1 and locations[0].get("drill_to_level"):
                    loc = locations[0]
                    result = {
                        "type": "drilldown",
                        "message": f"Showing {loc.get('drill_to_level')} of {loc.get('matched_term', loc.get('loc_id'))}...",
                        "loc_id": loc.get("loc_id"),
                        "name": loc.get("matched_term", loc.get("loc_id")),
                        "drill_to_level": loc.get("drill_to_level"),
                        "original_query": query,
                    }
                    yield f"data: {json.dumps({'stage': 'complete', 'result': result})}\n\n"
                    return

            t_llm_start = time.time()
            yield f"data: {json.dumps({'stage': 'thinking', 'message': 'Understanding your intent...'})}\n\n"
            await asyncio.sleep(0)
            # Run the synchronous LLM call in a thread so we do not block
            # the event loop. Pipe real progress events back through a
            # ProgressBus so the user sees actual tool calls instead of
            # "Understanding your intent..." sitting there for seconds.
            bus = ProgressBus()
            llm_task = asyncio.create_task(asyncio.to_thread(
                interpret_request,
                query,
                chat_history,
                hints=hints,
                progress=bus.thread_emitter(),
            ))
            async for event in bus.drain_until(
                llm_task,
                heartbeat_seconds=4.0,
                heartbeat=_explorer_heartbeat,
            ):
                payload = {"stage": event.stage, "message": event.message}
                if event.extra:
                    payload["extra"] = event.extra
                yield f"data: {json.dumps(payload)}\n\n"
            result = await llm_task
            t_llm_end = time.time()
            logger.info(f"[TIMING] LLM call: {(t_llm_end - t_llm_start) * 1000:.0f}ms")

            if result["type"] == "order":
                yield f"data: {json.dumps({'stage': 'preparing', 'message': 'Preparing your order...'})}\n\n"
                await asyncio.sleep(0)
                result_summary = result.get("summary") or result.get("order", {}).get("summary") or "Data request"
                processed = postprocess_order(result["order"], hints)
                if processed.get("needs_clarify"):
                    final_result = {
                        "type": "clarify",
                        "message": processed.get("clarify_message") or processed.get("validation_summary") or "I need a more specific path before I can run that.",
                        "summary": result_summary,
                        "full_order": processed,
                    }
                    yield f"data: {json.dumps({'stage': 'complete', 'result': final_result})}\n\n"
                    return
                if not processed.get("all_valid", True):
                    final_result = {
                        "type": "clarify",
                        "message": processed.get("validation_summary") or "I need a more specific executable request before I can run that.",
                        "summary": result_summary,
                        "full_order": processed,
                    }
                    yield f"data: {json.dumps({'stage': 'complete', 'result': final_result})}\n\n"
                    return
                display_items = get_display_items(processed.get("items", []), processed.get("derived_specs", []))
                final_result = {
                    "type": "order",
                    "order": {**result["order"], "items": display_items, "derived_specs": processed.get("derived_specs", [])},
                    "full_order": processed,
                    "summary": result_summary,
                    "validation_summary": processed.get("validation_summary"),
                    "all_valid": processed.get("all_valid", True),
                }
                yield f"data: {json.dumps({'stage': 'complete', 'result': final_result})}\n\n"
            elif result["type"] == "navigate":
                locations = result.get("locations", [])
                loc_ids = [loc.get("loc_id") for loc in locations if loc.get("loc_id")]
                geometry_overlay = result.get("geometry_overlay")
                geojson = {"type": "FeatureCollection", "features": []}
                if geometry_overlay:
                    from mapmover.order_executor import execute_geometry_overlay

                    geojson = execute_geometry_overlay(geometry_overlay, loc_ids)
                final_result = {
                    "type": "navigate",
                    "data_type": "geometry" if geometry_overlay else None,
                    "message": result.get("message", f"Showing {len(locations)} location(s)"),
                    "locations": locations,
                    "loc_ids": loc_ids,
                    "original_query": query,
                    "geojson": geojson,
                    "geometry_overlay": geometry_overlay,
                }
                yield f"data: {json.dumps({'stage': 'complete', 'result': final_result})}\n\n"
            elif result["type"] == "disambiguate":
                final_result = {
                    "type": "disambiguate",
                    "message": result.get("message", "Multiple locations found. Please select one."),
                    "query_term": result.get("query_term", "location"),
                    "original_query": query,
                    "options": result.get("options", []),
                    "geojson": {"type": "FeatureCollection", "features": []},
                }
                yield f"data: {json.dumps({'stage': 'complete', 'result': final_result})}\n\n"
            elif result["type"] == "filter_update":
                final_result = {
                    "type": "filter_update",
                    "overlay": result.get("overlay", ""),
                    "filters": result.get("filters", {}),
                    "message": result.get("message", "Updating filters"),
                }
                yield f"data: {json.dumps({'stage': 'complete', 'result': final_result})}\n\n"
            elif result["type"] == "overlay_toggle":
                final_result = {
                    "type": "overlay_toggle",
                    "overlay": result.get("overlay", ""),
                    "enabled": result.get("enabled", True),
                    "message": result.get("message", "Toggling overlay"),
                }
                yield f"data: {json.dumps({'stage': 'complete', 'result': final_result})}\n\n"
            elif result["type"] == "clarify":
                final_result = {"type": "clarify", "message": result["message"], "geojson": {"type": "FeatureCollection", "features": []}, "needsMoreInfo": True}
                yield f"data: {json.dumps({'stage': 'complete', 'result': final_result})}\n\n"
            else:
                chat_msg = result.get("message", "I'm not sure how to help with that.")
                final_result = {
                    "type": "chat",
                    "message": chat_msg,
                    "geojson": {"type": "FeatureCollection", "features": []},
                    "needsMoreInfo": False,
                }
                log_conversation(
                    frontend_session_id,
                    query,
                    chat_msg,
                    surface="explorer",
                    intent=result.get("type"),
                    ip_hash=hash_ip_for_analytics(client_ip),
                    user_agent=(req.headers.get("user-agent") or "")[:300] or None,
                )
                yield f"data: {json.dumps({'stage': 'complete', 'result': final_result})}\n\n"
        except Exception as e:
            logger.exception("Chat stream error")
            log_app_error(type(e).__name__, str(e), surface="human_app", path="/chat/stream")
            error_result = {
                "type": "error",
                "message": "Sorry, I encountered an error. Please try again.",
                "geojson": {"type": "FeatureCollection", "features": []},
            }
            yield f"data: {json.dumps({'stage': 'complete', 'result': error_result})}\n\n"

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
