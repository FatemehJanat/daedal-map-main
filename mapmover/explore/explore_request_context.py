"""Explore request-context helpers."""

from __future__ import annotations


def extract_chat_request_context(body: dict) -> dict:
    """Extract the Explore chat request fields used by the route workflow."""
    return {
        "query": body.get("query", ""),
        "chat_history": body.get("chatHistory", []),
        "viewport": body.get("viewport"),
        "resolved_location": body.get("resolved_location"),
        "active_overlays": body.get("activeOverlays"),
        "cache_stats": body.get("cacheStats"),
        "time_state": body.get("timeState"),
        "saved_order_names": body.get("savedOrderNames", []),
        "loaded_data": body.get("loadedData", []),
        "tutorial_mode": body.get("tutorialMode", {}),
        "previous_disambiguation_options": body.get("previous_disambiguation_options", []),
    }


def apply_resolved_location_override(hints: dict, resolved_location: dict | None) -> dict:
    """Merge an explicit frontend disambiguation selection into Explore hints."""
    if not resolved_location:
        return hints

    hints["location"] = {
        "matched_term": resolved_location.get("matched_term"),
        "iso3": resolved_location.get("iso3"),
        "country_name": resolved_location.get("country_name"),
        "loc_id": resolved_location.get("loc_id"),
        "is_subregion": resolved_location.get("loc_id") != resolved_location.get("iso3"),
        "source": "disambiguation_selection",
    }
    hints["disambiguation"] = None
    return hints
