"""Explore-lane route helpers shared across chat endpoints."""

from __future__ import annotations


def build_tutorial_mode_payload(hints: dict, tutorial_mode: dict | None) -> dict:
    action = hints["tutorial_mode"].get("action", "toggle")
    current_enabled = bool((tutorial_mode or {}).get("enabled"))
    enabled = (not current_enabled) if action == "toggle" else (action == "on")
    message = (
        "Tutorial mode on. Hover or tap a help marker to see what that part of the app does."
        if enabled
        else "Tutorial mode off."
    )
    return {
        "type": "tutorial_mode",
        "action": action,
        "enabled": enabled,
        "message": message,
    }


def maybe_build_shortcut_payload(
    *,
    hints: dict,
    request_context: dict,
    query: str,
    address_prompt_response_func,
    build_show_borders_response_func,
    build_drilldown_response_func,
    fetch_geometries_by_loc_ids_func,
):
    if hints.get("tutorial_mode"):
        return build_tutorial_mode_payload(hints, request_context.get("tutorial_mode"))

    if hints.get("address_prompt"):
        return address_prompt_response_func(hints.get("address_prompt"))

    if hints.get("show_borders"):
        previous_options = request_context.get("previous_disambiguation_options")
        loc_ids_to_show = [opt.get("loc_id") for opt in previous_options if opt.get("loc_id")] if previous_options else []
        if loc_ids_to_show:
            geojson = fetch_geometries_by_loc_ids_func(loc_ids_to_show)
            return build_show_borders_response_func(previous_options, original_query=query, geojson=geojson)

    navigation = hints.get("navigation")
    if navigation and navigation.get("is_navigation"):
        locations = navigation.get("locations", [])
        if len(locations) == 1 and locations[0].get("drill_to_level"):
            return build_drilldown_response_func(locations[0], original_query=query)
    return None


def build_navigate_payload(
    result: dict,
    *,
    query: str,
    build_navigate_response_func,
    execute_geometry_overlay_func,
) -> dict:
    locations = result.get("locations", [])
    loc_ids = [loc.get("loc_id") for loc in locations if loc.get("loc_id")]
    geometry_overlay = result.get("geometry_overlay")
    geojson = {"type": "FeatureCollection", "features": []}
    if geometry_overlay:
        geojson = execute_geometry_overlay_func(geometry_overlay, loc_ids)
    return build_navigate_response_func(result, loc_ids=loc_ids, original_query=query, geojson=geojson)


def build_clarify_payload(result: dict, *, compact_followup_func) -> dict:
    return {
        "type": "clarify",
        "message": compact_followup_func(result.get("message", "")),
        "geojson": {"type": "FeatureCollection", "features": []},
        "needsMoreInfo": True,
    }


def build_chat_payload(
    result: dict,
    *,
    query: str,
    hints: dict,
    auth_user,
    compact_followup_func,
    maybe_build_explainer_response_func,
    build_chat_response_func,
    load_source_metadata_func,
    load_source_reference_func,
) -> tuple[dict, str]:
    explainer_result = maybe_build_explainer_response_func(
        query=query,
        hints=hints,
        build_chat_response_func=build_chat_response_func,
        auth_user=auth_user,
        load_source_metadata_func=load_source_metadata_func,
        load_source_reference_func=load_source_reference_func,
    )
    if explainer_result is not None:
        chat_payload = explainer_result
        chat_result = chat_payload.get("message", "")
        return chat_payload, chat_result
    chat_result = compact_followup_func(result.get("message", "I'm not sure how to help with that."))
    return build_chat_response_func(chat_result, auth_user=auth_user), chat_result
