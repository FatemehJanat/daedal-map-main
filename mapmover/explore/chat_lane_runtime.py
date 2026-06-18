"""Explore-lane route helpers shared across chat endpoints."""

from __future__ import annotations

import re

from mapmover.routes.disasters.related import search_named_event_candidates


_EXACT_EVENT_MISS_RE = re.compile(r"\bcould not find exact event\b", re.IGNORECASE)
_FILTER_READ_RE = re.compile(
    r"(what.*filters?|current filters?|what.*showing|how many.*showing|what.*loaded)",
    re.IGNORECASE,
)


def _format_loaded_filter_value(overlay_id: str, loaded_filters: dict) -> str:
    filters = loaded_filters or {}
    parts: list[str] = []

    if overlay_id == "earthquakes":
        min_mag = filters.get("minMagnitude")
        max_mag = filters.get("maxMagnitude")
        if min_mag is not None:
            parts.append(f"magnitude >= {min_mag}")
        if max_mag is not None:
            parts.append(f"magnitude <= {max_mag}")
    elif overlay_id == "hurricanes":
        min_category = filters.get("minCategory")
        if min_category:
            parts.append(f"category >= {min_category}")
    elif overlay_id == "volcanoes":
        min_vei = filters.get("minVei")
        if min_vei is not None:
            parts.append(f"VEI >= {min_vei}")
    elif overlay_id == "wildfires":
        min_area_km2 = filters.get("minAreaKm2")
        if min_area_km2 is not None:
            parts.append(f"area >= {min_area_km2} km2")
    elif overlay_id == "tornadoes":
        min_scale = filters.get("minScale")
        if min_scale:
            scale_text = str(min_scale)
            if not scale_text.upper().startswith("EF"):
                scale_text = f"EF{scale_text}"
            parts.append(f"scale >= {scale_text}")
    elif overlay_id == "floods":
        min_severity = filters.get("minSeverity")
        if min_severity is not None:
            parts.append(f"severity >= {min_severity}")
    elif overlay_id == "tsunamis":
        min_height = filters.get("minHeightM")
        if min_height is not None:
            parts.append(f"height >= {min_height} m")

    return ", ".join(parts) if parts else "no extra severity filter"


def _build_loaded_filters_shortcut(*, request_context: dict, query: str) -> dict | None:
    if not _FILTER_READ_RE.search(str(query or "")):
        return None

    active_overlays = request_context.get("active_overlays") or {}
    active_list = [
        str(value or "").strip()
        for value in (active_overlays.get("allActive") or [])
        if str(value or "").strip()
    ]
    cache_stats = request_context.get("cache_stats") or {}

    if not active_list:
        return {
            "type": "cache_answer",
            "message": "No overlays are currently loaded.",
            "geojson": {"type": "FeatureCollection", "features": []},
        }

    lines = ["Current loaded overlay filters:"]
    for overlay_id in active_list:
        stats = cache_stats.get(overlay_id) or {}
        count = stats.get("count")
        years = stats.get("years") or []
        loaded_filters = stats.get("loadedFilters") or {}
        filter_text = _format_loaded_filter_value(overlay_id, loaded_filters)
        details: list[str] = []
        if count is not None:
            details.append(f"{int(count):,} loaded")
        if years:
            try:
                details.append(f"years {years[0]}-{years[-1]}")
            except Exception:
                pass
        details.append(filter_text)
        lines.append(f"- {overlay_id}: " + "; ".join(details))

    lines.append("Ask me to widen or narrow any one of those filters.")
    return {
        "type": "cache_answer",
        "message": "\n".join(lines),
        "geojson": {"type": "FeatureCollection", "features": []},
    }


def _event_search_pack_hint(query: str, hints: dict) -> str | None:
    detected_source = hints.get("detected_source") if isinstance(hints, dict) else None
    if isinstance(detected_source, dict):
        pack_id = str(detected_source.get("pack_id") or "").strip().lower()
        if pack_id:
            return pack_id

    query_text = str(query or "").lower()
    if any(token in query_text for token in ("volcano", "volcanoes", "volcanos", "eruption", "eruptions")):
        return "volcanoes"
    if any(token in query_text for token in ("hurricane", "storm", "cyclone", "typhoon")):
        return "hurricanes"
    return None


def maybe_build_named_event_search_response(
    *,
    result: dict,
    query: str,
    hints: dict,
    build_chat_response_func,
) -> dict | None:
    message = str(result.get("message") or "").strip()
    if not _EXACT_EVENT_MISS_RE.search(message):
        return None

    pack_hint = _event_search_pack_hint(query, hints)
    matches = search_named_event_candidates(query, pack_id=pack_hint, limit=5)
    if not matches:
        return None

    lines = ["I found named event matches you can open directly:"]
    for match in matches[:5]:
        label = str(match.get("label") or match.get("event_id") or "Unnamed event").strip()
        event_id = str(match.get("event_id") or "").strip()
        extras: list[str] = []
        if match.get("country"):
            extras.append(str(match["country"]).strip())
        if match.get("year") is not None:
            extras.append(str(match["year"]))
        suffix = f" ({', '.join(extras)})" if extras else ""
        lines.append(f"{label}: {event_id}{suffix}")

    lines.append("Use the event id directly, or ask me to load one of those on the map.")
    return build_chat_response_func("\n".join(lines), pack_id=pack_hint)


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
    loaded_filters_payload = _build_loaded_filters_shortcut(
        request_context=request_context,
        query=query,
    )
    if loaded_filters_payload is not None:
        return loaded_filters_payload

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
    named_event_search_result = maybe_build_named_event_search_response(
        result=result,
        query=query,
        hints=hints,
        build_chat_response_func=build_chat_response_func,
    )
    if named_event_search_result is not None:
        chat_result = named_event_search_result.get("message", "")
        return named_event_search_result, chat_result

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
