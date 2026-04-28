"""Postprocessing helpers for Research mode."""

from __future__ import annotations

from copy import deepcopy


def _coerce_display(display: dict, research_hints: dict | None) -> dict | None:
    geojson = display.get("geojson") or {}
    features = geojson.get("features") or []
    loc_ids = display.get("loc_ids") or []
    action = str(display.get("action") or "").strip()
    raster = display.get("raster")
    has_raster = isinstance(raster, dict) and str(raster.get("provider") or "").strip()
    if action != "highlight_features" and not has_raster:
        return None
    if action == "highlight_features" and (not features or not loc_ids):
        return None

    display["fit"] = bool(display.get("fit", True))
    display["context_visibility"] = str(display.get("context_visibility") or "keep")

    hint_time = (research_hints or {}).get("time") or {}
    specific_year = hint_time.get("specific_year")
    if isinstance(raster, dict):
        provider = str(raster.get("provider") or "").strip()
        if provider:
            normalized_raster = {"provider": provider}
            period = str(raster.get("period") or "").strip()
            if period:
                normalized_raster["period"] = period
            visibility = str(raster.get("visibility") or "").strip().lower()
            if visibility in {"show", "hide"}:
                normalized_raster["visibility"] = visibility
            year = raster.get("year")
            if isinstance(year, int):
                normalized_raster["year"] = year
            elif provider == "fairfax_lst" and isinstance(specific_year, int):
                normalized_raster["year"] = specific_year
            display["raster"] = normalized_raster
        else:
            display.pop("raster", None)
    else:
        display.pop("raster", None)

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
