from __future__ import annotations

import re
from typing import Any

import pandas as pd

from ..geometry_handlers import (
    load_country_parquet,
    load_global_countries_frame,
    resolve_point_to_location as legacy_resolve_point_to_location,
)
from ..name_standardizer import NameStandardizer
from ..reference.usa.location_lookup import by_zip as usa_zip_lookup
from .admin_hierarchy import get_parent_loc_id, infer_admin_level_from_loc_id
from .geography_reference import (
    canonicalize_loc_id,
    classify_loc_id_family,
    translate_geometry_id_to_local_id,
)

_LOC_ID_RE = re.compile(r"^[A-Z]{3}(?:-[A-Z0-9]+)+$|^[A-Z]{3}$")
_USA_ZIP_RE = re.compile(r"^\d{5}$")
_NAME_STANDARDIZER: NameStandardizer | None = None
_TEXT_COLLAPSE_RE = re.compile(r"[^a-z0-9]+")
_ADMIN_TEXT_SUFFIX_RE = re.compile(
    r"\b(county|parish|borough|municipality|municipio|district|region|province|state|prefecture|department|departement|oblast|county of)\b",
    re.IGNORECASE,
)
_ADMIN_TEXT_ALIASES = {
    "bavaria": "bayern",
    "hesse": "hessen",
    "lower saxony": "niedersachsen",
    "north rhine westphalia": "nordrhein westfalen",
    "north rhine-westphalia": "nordrhein westfalen",
    "rhineland palatinate": "rheinland pfalz",
    "saxony": "sachsen",
    "saxony anhalt": "sachsen anhalt",
    "saxony-anhalt": "sachsen anhalt",
    "thuringia": "thuringen",
    "baden wurttemberg": "baden wurttemberg",
    "baden-wurttemberg": "baden wurttemberg",
    "mecklenburg western pomerania": "mecklenburg vorpommern",
    "mecklenburg-western pomerania": "mecklenburg vorpommern",
}


def _get_name_standardizer() -> NameStandardizer:
    global _NAME_STANDARDIZER
    if _NAME_STANDARDIZER is None:
        _NAME_STANDARDIZER = NameStandardizer()
    return _NAME_STANDARDIZER


def _normalize_admin_text(value: Any) -> str:
    try:
        if value is None or pd.isna(value):
            return ""
    except Exception:
        if value is None:
            return ""
    text = str(value).strip().lower()
    if not text:
        return ""
    text = text.replace("&", " and ")
    text = _ADMIN_TEXT_SUFFIX_RE.sub(" ", text)
    text = text.replace("ü", "u").replace("ö", "o").replace("ä", "a").replace("ß", "ss")
    text = _TEXT_COLLAPSE_RE.sub(" ", text)
    text = " ".join(text.split())
    return _ADMIN_TEXT_ALIASES.get(text, text)


def _resolve_country_geometry_name(
    query: str,
    *,
    country_hint: str,
    admin_level: int,
) -> dict[str, Any] | None:
    df = load_country_parquet(str(country_hint or "").strip().upper(), admin_level=admin_level)
    if df is None or df.empty:
        return None

    normalized_query = _normalize_admin_text(query)
    if not normalized_query:
        return None

    candidates: list[tuple[str, str | None]] = []
    for _, row in df.iterrows():
        loc_id = str(row.get("loc_id") or "").strip()
        if not loc_id:
            continue
        for field in ("name", "name_local", "iso_3166_2", "code"):
            value = row.get(field)
            normalized_value = _normalize_admin_text(value)
            if normalized_value and normalized_value == normalized_query:
                candidates.append((loc_id, row.get("name")))
                break

    if not candidates:
        return None

    loc_id, name = candidates[0]
    return _build_match_entry(
        loc_id,
        admin_level=admin_level,
        name=name,
        method="geometry_name_lookup",
        source_loc_id=loc_id,
    )


def _resolve_country_name_from_global_geometry(query: str) -> dict[str, Any] | None:
    df = load_global_countries_frame()
    if df is None or df.empty:
        return None

    normalized_query = _normalize_admin_text(query)
    if not normalized_query:
        return None

    for _, row in df.iterrows():
        loc_id = str(row.get("loc_id") or "").strip()
        if not loc_id:
            continue
        name = row.get("name")
        if _normalize_admin_text(name) == normalized_query:
            return _build_match_entry(
                loc_id,
                admin_level=0,
                name=name,
                method="geometry_name_lookup",
                source_loc_id=loc_id,
            )
    return None


def _level_key(admin_level: int | None) -> str | None:
    if admin_level is None or admin_level < 0:
        return None
    return f"admin_{int(admin_level)}"


def _build_match_entry(
    loc_id: str,
    *,
    admin_level: int | None,
    name: str | None = None,
    method: str,
    confidence: float = 1.0,
    canonical_match: bool = True,
    source_loc_id: str | None = None,
) -> dict[str, Any]:
    canonical_loc_id = canonicalize_loc_id(loc_id)
    inferred_level = infer_admin_level_from_loc_id(canonical_loc_id)
    return {
        "loc_id": canonical_loc_id,
        "admin_level": int(admin_level if admin_level is not None else inferred_level or 0),
        "name": str(name).strip() if isinstance(name, str) and str(name).strip() else None,
        "method": method,
        "confidence": float(confidence),
        "canonical_match": bool(canonical_match),
        "source_loc_id": source_loc_id or canonical_loc_id,
    }


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_bbox(payload: dict[str, Any]) -> dict[str, float] | None:
    bounds = payload.get("bbox") or payload.get("bounds")
    if not isinstance(bounds, dict):
        return None
    west = _coerce_float(bounds.get("west") or bounds.get("min_lon") or bounds.get("xmin"))
    south = _coerce_float(bounds.get("south") or bounds.get("min_lat") or bounds.get("ymin"))
    east = _coerce_float(bounds.get("east") or bounds.get("max_lon") or bounds.get("xmax"))
    north = _coerce_float(bounds.get("north") or bounds.get("max_lat") or bounds.get("ymax"))
    if None in {west, south, east, north}:
        return None
    return {"west": west, "south": south, "east": east, "north": north}


def _normalize_place_components(payload: dict[str, Any]) -> dict[str, Any]:
    components = payload.get("components")
    if not isinstance(components, dict):
        components = {}
    out = {
        "street_number": components.get("street_number") or payload.get("street_number"),
        "route": components.get("route") or payload.get("route"),
        "locality": components.get("locality") or payload.get("locality") or payload.get("city"),
        "admin_2_name": components.get("admin_2_name") or components.get("county") or payload.get("county"),
        "admin_1_name": components.get("admin_1_name") or components.get("admin_area") or payload.get("state") or payload.get("province"),
        "postal_code": components.get("postal_code") or payload.get("postal_code") or payload.get("zip"),
        "country_name": components.get("country_name") or components.get("country") or payload.get("country"),
        "country_code": (
            components.get("country_code")
            or payload.get("country_code")
            or payload.get("country_iso2")
            or payload.get("country_iso3")
        ),
    }
    return {key: value for key, value in out.items() if isinstance(value, str) and value.strip()}


def _normalize_resolved_place(
    resolved_place: dict[str, Any] | None,
    *,
    query: str,
    provider: str,
) -> dict[str, Any] | None:
    payload = resolved_place if isinstance(resolved_place, dict) else {}
    lat = _coerce_float(payload.get("lat"))
    lng = _coerce_float(payload.get("lng") or payload.get("lon"))

    geometry = payload.get("geometry")
    if isinstance(geometry, dict):
        location = geometry.get("location")
        if isinstance(location, dict):
            lat = lat if lat is not None else _coerce_float(location.get("lat"))
            lng = lng if lng is not None else _coerce_float(location.get("lng") or location.get("lon"))

    label = (
        payload.get("formatted_address")
        or payload.get("label")
        or payload.get("address")
        or payload.get("query")
        or query
    )
    place_type = (
        payload.get("place_type")
        or payload.get("type")
        or ("street_address" if payload.get("place_id") else "place")
    )
    normalized = {
        "query": str(query or "").strip(),
        "provider": str(provider or payload.get("provider") or "").strip() or "unknown",
        "resolved_place": {
            "label": str(label or "").strip(),
            "place_id": str(payload.get("place_id") or "").strip() or None,
            "place_type": str(place_type or "").strip() or None,
            "lat": lat,
            "lng": lng,
            "bbox": _extract_bbox(payload),
            "components": _normalize_place_components(payload),
        },
    }
    if normalized["resolved_place"]["lat"] is None or normalized["resolved_place"]["lng"] is None:
        return normalized
    return normalized


def _looks_like_us_zip(query: str, country_hint: str | None = None) -> bool:
    value = str(query or "").strip()
    if not _USA_ZIP_RE.fullmatch(value):
        return False
    if not country_hint:
        return True
    hint = str(country_hint).strip().upper()
    return hint in {"USA", "US", "UNITED STATES", "UNITED STATES OF AMERICA"}


def _resolve_us_zip_to_stack(query: str) -> dict[str, Any]:
    value = str(query or "").strip()
    if not _looks_like_us_zip(value):
        return {}

    row = usa_zip_lookup(value)
    if not isinstance(row, dict):
        return {
            "query": value,
            "match_type": "postal_code",
            "matches": {},
            "deepest_resolved_loc_id": None,
            "deepest_resolved_admin_level": None,
            "should_persist_deepest_loc_id": False,
            "error": "no ZIP crosswalk match found",
        }

    matches: dict[str, dict[str, Any]] = {
        "admin_0": _build_match_entry(
            row.get("country_loc_id") or "USA",
            admin_level=0,
            method="postal_crosswalk",
        )
    }
    state_loc_id = str(row.get("state_loc_id") or "").strip()
    county_loc_id = str(row.get("county_loc_id") or "").strip()
    if state_loc_id:
        matches["admin_1"] = _build_match_entry(
            state_loc_id,
            admin_level=1,
            name=row.get("state_abbrev"),
            method="postal_crosswalk",
        )
    if county_loc_id:
        matches["admin_2"] = _build_match_entry(
            county_loc_id,
            admin_level=2,
            name=row.get("county_name"),
            method="postal_crosswalk",
        )

    deepest_loc_id = county_loc_id or state_loc_id or "USA"
    deepest_level = _level_key(infer_admin_level_from_loc_id(deepest_loc_id))
    return {
        "query": value,
        "match_type": "postal_code",
        "postal_code": value,
        "postal_system": "usa_zip_crosswalk",
        "postal_metadata": {
            "county_count": row.get("county_count"),
            "all_counties": row.get("all_counties") or [],
        },
        "matches": matches,
        "deepest_resolved_loc_id": deepest_loc_id,
        "deepest_resolved_admin_level": deepest_level,
        "should_persist_deepest_loc_id": bool(deepest_loc_id),
    }


def _iter_parent_chain(loc_id: str, stop_level_inclusive: int) -> list[tuple[int, str]]:
    current = canonicalize_loc_id(loc_id)
    current_level = infer_admin_level_from_loc_id(current)
    if current_level is None:
        return []

    out: list[tuple[int, str]] = []
    while current_level is not None and current_level > stop_level_inclusive:
        out.append((current_level, current))
        parent = get_parent_loc_id(current)
        if not parent:
            break
        current = parent
        current_level = infer_admin_level_from_loc_id(current)
    if current_level is not None and current_level >= stop_level_inclusive:
        out.append((current_level, current))
    return out


def resolve_admin_text_to_loc_id(
    query: str,
    *,
    country_hint: str | None = None,
    admin_level_hint: int | None = None,
) -> dict[str, Any]:
    value = str(query or "").strip()
    if not value:
        return {"query": value, "error": "query is required", "matches": {}}

    postal_match = _resolve_us_zip_to_stack(value)
    if postal_match.get("match_type") == "postal_code":
        return postal_match

    if _LOC_ID_RE.match(value):
        family = classify_loc_id_family(value)
        if family == "event_or_entity":
            return {
                "query": value,
                "match_type": "direct_event_loc_id",
                "matches": {},
                "deepest_resolved_loc_id": None,
                "deepest_resolved_admin_level": None,
                "should_persist_deepest_loc_id": False,
                "loc_id_family": family,
                "error": "event/entity loc_id requires exact-event routing",
            }
        loc_id = translate_geometry_id_to_local_id(value)
        admin_level = infer_admin_level_from_loc_id(loc_id)
        key = _level_key(admin_level)
        entry = _build_match_entry(
            loc_id,
            admin_level=admin_level,
            method="loc_id_passthrough",
            source_loc_id=value,
        )
        return {
            "query": value,
            "match_type": "direct_loc_id",
            "loc_id_family": family,
            "matches": {key: entry} if key else {},
            "deepest_resolved_loc_id": loc_id,
            "deepest_resolved_admin_level": key,
            "should_persist_deepest_loc_id": True,
        }

    standardizer = _get_name_standardizer()
    country = str(country_hint or "").strip().upper() or None

    level_order: list[int | None]
    if admin_level_hint is not None:
        level_order = [int(admin_level_hint)]
    elif country:
        # Let the shared country geometry spine resolve the deepest matching
        # admin level first instead of assuming province/state or county only.
        level_order = [None, 0]
    else:
        level_order = [0]

    for admin_level in level_order:
        resolved = standardizer.get_loc_id_from_name(value, country=country, admin_level=admin_level)
        if not resolved:
            fallback_entry = None
            if admin_level == 0:
                fallback_entry = _resolve_country_name_from_global_geometry(value)
            elif country and admin_level in {1, 2}:
                fallback_entry = _resolve_country_geometry_name(
                    value,
                    country_hint=country,
                    admin_level=int(admin_level),
                )
            if fallback_entry is None:
                continue
            key = _level_key(fallback_entry.get("admin_level"))
            return {
                "query": value,
                "match_type": "direct_admin_name",
                "matches": {key: fallback_entry} if key else {},
                "deepest_resolved_loc_id": fallback_entry.get("loc_id"),
                "deepest_resolved_admin_level": key,
                "should_persist_deepest_loc_id": True,
            }
        local_loc_id = translate_geometry_id_to_local_id(resolved)
        resolved_level = infer_admin_level_from_loc_id(local_loc_id)
        key = _level_key(resolved_level)
        entry = _build_match_entry(
            local_loc_id,
            admin_level=resolved_level,
            method="name_lookup",
            source_loc_id=resolved,
        )
        return {
            "query": value,
            "match_type": "direct_admin_name",
            "matches": {key: entry} if key else {},
            "deepest_resolved_loc_id": local_loc_id,
            "deepest_resolved_admin_level": key,
            "should_persist_deepest_loc_id": True,
        }

    return {
        "query": value,
        "match_type": "direct_admin_name",
        "matches": {},
        "deepest_resolved_loc_id": None,
        "deepest_resolved_admin_level": None,
        "should_persist_deepest_loc_id": False,
        "error": "no direct admin-name match found",
    }


def resolve_place_to_point(
    query: str,
    *,
    resolved_place: dict[str, Any] | None = None,
    provider: str = "google",
    country_hint: str | None = None,
) -> dict[str, Any]:
    value = str(query or "").strip()
    direct_match = resolve_admin_text_to_loc_id(value, country_hint=country_hint)
    if direct_match.get("matches"):
        return {
            "query": value,
            "provider": "direct_admin_text",
            "resolved_place": None,
            "direct_admin_match": direct_match,
        }

    normalized = _normalize_resolved_place(resolved_place, query=value, provider=provider)
    if normalized is None:
        return {
            "query": value,
            "provider": provider,
            "error": "resolved_place payload is required when no direct admin-text match exists",
        }
    if normalized["resolved_place"].get("lat") is None or normalized["resolved_place"].get("lng") is None:
        normalized["error"] = "resolved_place payload does not include a usable point"
    return normalized


def resolve_point_to_loc_id_stack(
    lon: float,
    lat: float,
    *,
    include_geometry: bool = False,
) -> dict[str, Any]:
    raw = legacy_resolve_point_to_location(lon, lat, include_geometry=include_geometry)
    if not isinstance(raw, dict):
        return {"point": {"lon": float(lon), "lat": float(lat)}, "error": "point resolver returned invalid payload"}
    if raw.get("error"):
        return raw

    matches: dict[str, dict[str, Any]] = {}
    for item in raw.get("stack") or []:
        source_loc_id = str(item.get("loc_id") or "").strip()
        if not source_loc_id:
            continue
        local_loc_id = translate_geometry_id_to_local_id(source_loc_id)
        admin_level = item.get("admin_level")
        resolved_level = int(admin_level) if admin_level is not None else infer_admin_level_from_loc_id(local_loc_id)
        key = _level_key(resolved_level)
        if not key:
            continue
        matches[key] = _build_match_entry(
            local_loc_id,
            admin_level=resolved_level,
            name=item.get("name"),
            method="point_containment",
            source_loc_id=source_loc_id,
        )

    matched = raw.get("matched") or {}
    deepest_source_loc_id = str(matched.get("loc_id") or "").strip()
    deepest_local_loc_id = translate_geometry_id_to_local_id(deepest_source_loc_id) if deepest_source_loc_id else None
    deepest_level = matched.get("admin_level")
    deepest_level = int(deepest_level) if deepest_level is not None else infer_admin_level_from_loc_id(deepest_local_loc_id)

    if deepest_local_loc_id and deepest_level is not None:
        for level_value, loc_id_value in _iter_parent_chain(deepest_local_loc_id, 3):
            key = _level_key(level_value)
            if not key or key in matches:
                continue
            matches[key] = _build_match_entry(
                loc_id_value,
                admin_level=level_value,
                method="derived_parent_chain",
                canonical_match=True,
            )

        deepest_key = _level_key(deepest_level)
        if deepest_key:
            existing = matches.get(deepest_key)
            name = (existing or {}).get("name") or matched.get("name")
            matches[deepest_key] = _build_match_entry(
                deepest_local_loc_id,
                admin_level=deepest_level,
                name=name,
                method=(existing or {}).get("method") or "point_containment",
                source_loc_id=deepest_source_loc_id or deepest_local_loc_id,
            )

    ordered_matches = {
        key: matches[key]
        for key in sorted(matches.keys(), key=lambda value: int(value.split("_", 1)[1]))
    }

    normalized_stack = [
        {
            "loc_id": entry["loc_id"],
            "name": entry.get("name"),
            "admin_level": int(entry["admin_level"]),
        }
        for entry in ordered_matches.values()
    ]
    deepest_entry = ordered_matches.get(_level_key(deepest_level) or "")

    result = {
        "point": raw.get("point") or {"lon": float(lon), "lat": float(lat)},
        "country": raw.get("country"),
        "matched": {
            "loc_id": deepest_local_loc_id,
            "name": (deepest_entry or {}).get("name") or matched.get("name"),
            "admin_level": int(deepest_level) if deepest_level is not None else None,
            "country_name": (raw.get("country") or {}).get("name"),
            "iso3": (raw.get("country") or {}).get("loc_id") or matched.get("iso3"),
        },
        "stack": normalized_stack,
        "matches": ordered_matches,
        "deepest_resolved_loc_id": deepest_local_loc_id,
        "deepest_resolved_admin_level": _level_key(deepest_level),
        "should_persist_deepest_loc_id": bool(deepest_local_loc_id),
        "legacy_payload": raw,
    }
    if include_geometry and "geojson" in raw:
        result["geojson"] = raw["geojson"]
    return result


def resolve_place_to_loc_id_stack(
    query: str,
    *,
    resolved_place: dict[str, Any] | None = None,
    provider: str = "google",
    country_hint: str | None = None,
    admin_level_hint: int | None = None,
    include_geometry: bool = False,
) -> dict[str, Any]:
    value = str(query or "").strip()

    direct_match = resolve_admin_text_to_loc_id(
        value,
        country_hint=country_hint,
        admin_level_hint=admin_level_hint,
    )
    if direct_match.get("matches"):
        direct_match["resolution_mode"] = "direct_admin_text"
        return direct_match

    point_payload = resolve_place_to_point(
        value,
        resolved_place=resolved_place,
        provider=provider,
        country_hint=country_hint,
    )
    if point_payload.get("error"):
        point_payload["resolution_mode"] = "place_payload"
        return point_payload

    place = point_payload.get("resolved_place") or {}
    lat = place.get("lat")
    lng = place.get("lng")
    if lat is None or lng is None:
        point_payload["resolution_mode"] = "place_payload"
        point_payload["error"] = point_payload.get("error") or "resolved place does not include a usable point"
        return point_payload

    stack_payload = resolve_point_to_loc_id_stack(lng, lat, include_geometry=include_geometry)
    stack_payload["query"] = value
    stack_payload["provider"] = point_payload.get("provider")
    stack_payload["resolved_place"] = place
    stack_payload["resolution_mode"] = "place_payload"
    return stack_payload
