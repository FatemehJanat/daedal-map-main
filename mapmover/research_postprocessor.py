"""Postprocessing helpers for Research mode."""

from __future__ import annotations

from copy import deepcopy


def _coerce_display(display: dict, research_hints: dict | None) -> dict | None:
    geojson = display.get("geojson") or {}
    features = geojson.get("features") or []
    loc_ids = display.get("loc_ids") or []
    action = str(display.get("action") or "").strip()
    if action != "highlight_features" or not features or not loc_ids:
        return None

    display["fit"] = bool(display.get("fit", True))
    display["context_visibility"] = str(display.get("context_visibility") or "keep")

    source_id = str(display.get("source_id") or "").strip()
    hint_time = (research_hints or {}).get("time") or {}
    specific_year = hint_time.get("specific_year")
    if source_id.startswith("fairfax_lst"):
        raster = {"provider": "fairfax_lst"}
        if isinstance(specific_year, int):
            raster["year"] = specific_year
        display["raster"] = raster

    return display


def normalize_research_result(result: dict | None, *, lane: str = "research") -> dict:
    """Normalize a Research response into a frontend-safe shape."""
    payload = deepcopy(result or {})
    display = payload.get("display")
    research_hints = payload.get("research_hints")

    if isinstance(display, dict):
        display["lane"] = lane
        normalized = _coerce_display(display, research_hints)
        if not normalized:
            payload.pop("display", None)
        else:
            payload["display"] = normalized

    return payload
