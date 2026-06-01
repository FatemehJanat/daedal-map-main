"""Explore lane request-preparation helpers shared by chat endpoints."""

from __future__ import annotations

from mapmover.catalog_surface import catalog_surface_scope


def prepare_explore_request(
    *,
    body: dict,
    route_context,
    explore_orchestrator,
    extract_chat_request_context_func,
    maybe_build_shortcut_payload_func,
    address_prompt_response_func,
    build_show_borders_response_func,
    build_drilldown_response_func,
    fetch_geometries_by_loc_ids_func,
    apply_selected_popup_override_func,
) -> dict:
    request_context = extract_chat_request_context_func(body)
    query = request_context["query"]
    chat_history = request_context["chat_history"]
    viewport = request_context["viewport"]
    resolved_location = request_context["resolved_location"]
    active_overlays = request_context["active_overlays"]
    cache_stats = request_context["cache_stats"]
    time_state = request_context["time_state"]
    saved_order_names = request_context["saved_order_names"]
    loaded_data = request_context["loaded_data"]
    selected_popup = request_context.get("selected_popup")

    if not query:
        return {
            "request_context": request_context,
            "query": query,
            "chat_history": chat_history,
            "hints": {},
            "shortcut_payload": None,
        }

    with catalog_surface_scope(route_context.catalog_surface):
        hints = explore_orchestrator.preprocess(
            query=query,
            viewport=viewport,
            active_overlays=active_overlays,
            cache_stats=cache_stats,
            saved_order_names=saved_order_names,
            time_state=time_state,
            loaded_data=loaded_data,
            resolved_location=resolved_location,
            selected_popup=selected_popup,
        )
        if selected_popup:
            hints = apply_selected_popup_override_func(hints, selected_popup)

    shortcut_payload = maybe_build_shortcut_payload_func(
        hints=hints,
        request_context=request_context,
        query=query,
        address_prompt_response_func=address_prompt_response_func,
        build_show_borders_response_func=build_show_borders_response_func,
        build_drilldown_response_func=build_drilldown_response_func,
        fetch_geometries_by_loc_ids_func=fetch_geometries_by_loc_ids_func,
    )
    return {
        "request_context": request_context,
        "query": query,
        "chat_history": chat_history,
        "hints": hints,
        "shortcut_payload": shortcut_payload,
    }
