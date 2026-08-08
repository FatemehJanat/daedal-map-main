"""Internal geographic reference exchange helpers.

This module treats ``loc_id`` as the reserve geographic identifier and every
external or adjacent geography family as a reference system that can be bridged
to or from it. Public MCP tools should wrap these functions instead of carrying
their own ZIP, NWS, tribal, or admin-specific conversion logic.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ..duckdb_helpers import is_cloud_mode
from ..geometry_handlers import get_location_info, get_selection_geometries
from ..paths import DATA_ROOT
from .admin_hierarchy import infer_admin_level_from_loc_id
from .geography_reference import (
    canonicalize_loc_id,
    classify_loc_id_family,
    legacy_geometry_ids_for_local_id,
    translate_geometry_id_to_local_id,
    translate_loc_id_to_geometry_id,
)
from .geometry_catalog import load_geometry_catalog, resolve_geometry_name
from .loc_id_resolution import resolve_admin_text_to_loc_id
from .sidechain_admin_bridge import admin_level_name, resolve_admin_to_sidechains, resolve_sidechain_to_admin


LOC_ID_SYSTEM = "daedalmap.loc_id"
ADMIN_SYSTEM = "admin_boundary"

SYSTEM_ALIASES = {
    "loc_id": LOC_ID_SYSTEM,
    "locid": LOC_ID_SYSTEM,
    "daedalmap": LOC_ID_SYSTEM,
    "daedalmap_loc_id": LOC_ID_SYSTEM,
    "admin": ADMIN_SYSTEM,
    "admin_geometry": ADMIN_SYSTEM,
    "administrative_boundary": ADMIN_SYSTEM,
    "administrative_boundaries": ADMIN_SYSTEM,
    "zcta": "overlay_zcta",
    "zip": "overlay_zcta",
    "zip_code": "overlay_zcta",
    "zipcode": "overlay_zcta",
    "postal_code": "overlay_zcta",
    "nws_zone": "overlay_nws_public_zone",
    "nws_public": "overlay_nws_public_zone",
    "nws_public_zone": "overlay_nws_public_zone",
    "nws_fire": "overlay_nws_fire_weather_zone",
    "nws_fire_zone": "overlay_nws_fire_weather_zone",
    "nws_fire_weather": "overlay_nws_fire_weather_zone",
    "fire_weather_zone": "overlay_nws_fire_weather_zone",
    "tribal": "overlay_tribal",
    "tribal_area": "overlay_tribal",
    "tribal_lands": "overlay_tribal",
    "eez": "marine_eez",
    "exclusive_economic_zone": "marine_eez",
    "iho": "water_body",
    "iho_water_body": "water_body",
    "nuts": "regional_base",
    "eurostat_nuts": "regional_base",
}


def _normalize_system(system: str | None) -> str:
    value = str(system or "").strip().lower().replace("-", "_").replace(" ", "_")
    return SYSTEM_ALIASES.get(value, value)


def _clean_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if hasattr(value, "item"):
        try:
            return _clean_json(value.item())
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): _clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_json(item) for item in value]
    return str(value)


def _catalog_bridge_path(artifact: dict[str, Any]) -> Path | None:
    rel = str(artifact.get("artifact_path") or "").strip()
    if not rel:
        return None
    return DATA_ROOT / rel


def _bridge_artifacts(
    *,
    source_family: str | None = None,
    target_admin_level: int | str | None = None,
    iso3: str | None = None,
    bridge_vintage: str | None = None,
) -> list[dict[str, Any]]:
    source = _normalize_system(source_family) if source_family else None
    level = admin_level_name(target_admin_level) if target_admin_level not in (None, "") else None
    country = str(iso3 or "").strip().upper()
    vintage = str(bridge_vintage or "").strip()
    out: list[dict[str, Any]] = []
    for artifact in load_geometry_catalog().get("bridge_artifacts") or []:
        if not isinstance(artifact, dict) or str(artifact.get("status") or "") != "complete":
            continue
        if source and str(artifact.get("source_family") or "").strip().lower() != source:
            continue
        if level and str(artifact.get("target_admin_level") or "").strip().lower() != level:
            continue
        path = _catalog_bridge_path(artifact)
        if country and path and f"_{country.lower()}.parquet" not in path.name.lower():
            continue
        if vintage and str(artifact.get("bridge_vintage") or "") != vintage:
            continue
        if path and (path.exists() or is_cloud_mode()):
            out.append(artifact)
    out.sort(
        key=lambda item: (
            str(item.get("bridge_vintage") or "") != "usa_geometry_current",
            -int(item.get("row_count") or 0),
            str(item.get("artifact_path") or ""),
        )
    )
    return out


def _first_bridge_artifact(**filters: Any) -> dict[str, Any] | None:
    artifacts = _bridge_artifacts(**filters)
    return artifacts[0] if artifacts else None


def _normalize_source_loc_id(source_family: str, value: str, iso3: str) -> str:
    text = str(value or "").strip()
    family = _normalize_system(source_family)
    country = str(iso3 or "USA").strip().upper() or "USA"
    if family == "overlay_zcta" and text.isdigit() and len(text) == 5:
        return f"{country}-Z-{text}"
    if family == "overlay_nws_public_zone" and len(text) == 6 and text[:2].isalpha() and text[2].upper() == "Z":
        return f"{country}-NWSZ-{text.upper()}"
    if family == "overlay_nws_fire_weather_zone" and len(text) == 6 and text[:2].isalpha() and text[2].upper() == "Z":
        return f"{country}-NWSFZ-{text.upper()}"
    return text


def list_reference_systems() -> dict[str, Any]:
    """Return the currently discoverable reference systems and bridges."""
    catalog = load_geometry_catalog()
    systems: dict[str, dict[str, Any]] = {
        LOC_ID_SYSTEM: {
            "system": LOC_ID_SYSTEM,
            "label": "DaedalMap loc_id",
            "role": "reserve",
            "bidirectional": True,
        }
    }
    for family in catalog.get("geometry_families") or []:
        if not isinstance(family, dict):
            continue
        system = str(family.get("family") or "").strip()
        if not system:
            continue
        systems.setdefault(system, {
            "system": system,
            "label": family.get("label") or system,
            "role": "geometry_family",
            "feature_count": family.get("feature_count"),
            "resolver": family.get("resolver"),
        })

    bridges = []
    for artifact in catalog.get("bridge_artifacts") or []:
        if not isinstance(artifact, dict) or str(artifact.get("status") or "") != "complete":
            continue
        source = str(artifact.get("source_family") or "").strip()
        level = str(artifact.get("target_admin_level") or "").strip()
        if source:
            systems.setdefault(source, {
                "system": source,
                "label": source.replace("_", " ").title(),
                "role": "reference_system",
            })
        bridges.append({
            "source_system": source,
            "target_system": LOC_ID_SYSTEM,
            "target_family": artifact.get("target_family"),
            "target_admin_level": level,
            "bridge_vintage": artifact.get("bridge_vintage"),
            "row_count": artifact.get("row_count"),
            "source_count": artifact.get("source_count"),
            "target_count": artifact.get("target_count"),
            "artifact_path": artifact.get("artifact_path"),
            "license": artifact.get("source_license"),
        })
    return _clean_json({"ok": True, "reserve_system": LOC_ID_SYSTEM, "systems": list(systems.values()), "bridges": bridges})


def _direct_loc_id_result(value: str, *, request_system: str) -> dict[str, Any]:
    loc_id = canonicalize_loc_id(value)
    family = classify_loc_id_family(loc_id)
    return {
        "ok": bool(loc_id),
        "from_system": request_system,
        "input": value,
        "resolved_loc_id": loc_id or None,
        "resolved_family": family,
        "match_type": "loc_id_passthrough",
        "references": [{"system": LOC_ID_SYSTEM, "value": loc_id, "role": "reserve"}] if loc_id else [],
    }


def _admin_text_result(value: str, *, country_hint: str | None, admin_level_hint: int | None, request_system: str) -> dict[str, Any]:
    raw = resolve_admin_text_to_loc_id(value, country_hint=country_hint, admin_level_hint=admin_level_hint)
    loc_id = raw.get("deepest_resolved_loc_id")
    return {
        "ok": bool(loc_id) and not raw.get("error"),
        "from_system": request_system,
        "input": value,
        "resolved_loc_id": loc_id,
        "resolved_family": classify_loc_id_family(loc_id),
        "match_type": raw.get("match_type"),
        "admin_level": raw.get("deepest_resolved_admin_level"),
        "matches": raw.get("matches") or {},
        "error": raw.get("error"),
    }


def resolve_reference(
    *,
    from_system: str,
    value: str,
    iso3: str = "USA",
    target_admin_level: int | str | None = "admin_2",
    bridge_vintage: str | None = None,
    min_share: float | None = None,
    limit: int | None = 10,
    country_hint: str | None = None,
    admin_level_hint: int | None = None,
) -> dict[str, Any]:
    """Resolve a reference-system value into one or more ``loc_id`` matches."""
    system = _normalize_system(from_system)
    text = str(value or "").strip()
    if not text:
        return {"ok": False, "from_system": system, "input": value, "error": "value is required"}
    if system in {LOC_ID_SYSTEM, "admin_local", "admin_geometry"}:
        return _clean_json(_direct_loc_id_result(text, request_system=system))
    if system == ADMIN_SYSTEM:
        return _clean_json(_admin_text_result(text, country_hint=country_hint or iso3, admin_level_hint=admin_level_hint, request_system=system))
    if system in {"water_body", "marine_eez", "regional_base"}:
        named = resolve_geometry_name(text)
        if named and named.get("loc_id"):
            return _clean_json({
                "ok": True,
                "from_system": system,
                "input": value,
                "resolved_loc_id": named.get("loc_id"),
                "resolved_family": named.get("family") or classify_loc_id_family(named.get("loc_id")),
                "match_type": "named_geometry",
                "match": named,
            })
        return _clean_json(_direct_loc_id_result(text, request_system=system))

    level = admin_level_name(target_admin_level or "admin_2")
    artifact = _first_bridge_artifact(
        source_family=system,
        target_admin_level=level,
        iso3=iso3,
        bridge_vintage=bridge_vintage,
    )
    if not artifact:
        return {
            "ok": False,
            "from_system": system,
            "input": value,
            "error": f"no bridge artifact found for {system} -> {level}",
        }
    source_loc_id = _normalize_source_loc_id(system, text, iso3)
    result = resolve_sidechain_to_admin(
        source_loc_id,
        source_family=system,
        target_admin_level=level,
        iso3=iso3,
        bridge_path=_catalog_bridge_path(artifact),
        min_source_area_share=min_share,
        limit=limit,
    )
    primary = result.get("primary_match") or {}
    return _clean_json({
        "ok": bool(result.get("ok")),
        "from_system": system,
        "input": value,
        "normalized_input": source_loc_id,
        "resolved_loc_id": primary.get("match_loc_id"),
        "resolved_family": "admin_boundary" if primary.get("match_loc_id") else None,
        "match_type": "bridge_overlap",
        "bridge": {
            "artifact_path": artifact.get("artifact_path"),
            "bridge_vintage": artifact.get("bridge_vintage"),
            "target_admin_level": level,
        },
        "primary_match": primary,
        "matches": result.get("overlaps") or [],
        "match_count": result.get("overlap_count") or 0,
        "error": result.get("error"),
    })


def loc_id_references(
    loc_id: str,
    *,
    systems: list[str] | None = None,
    iso3: str | None = None,
    target_admin_level: int | str | None = None,
    min_share: float | None = None,
    limit_per_system: int | None = 10,
) -> dict[str, Any]:
    """Return known references that point at a ``loc_id``."""
    canonical = canonicalize_loc_id(loc_id)
    family = classify_loc_id_family(canonical)
    requested = {_normalize_system(system) for system in systems or [] if str(system or "").strip()}
    references: list[dict[str, Any]] = [
        {"system": LOC_ID_SYSTEM, "value": canonical, "role": "reserve", "family": family},
    ]
    geometry_id = translate_loc_id_to_geometry_id(canonical)
    local_id = translate_geometry_id_to_local_id(canonical)
    if geometry_id and geometry_id != canonical:
        references.append({"system": "admin_geometry", "value": geometry_id, "role": "geometry_join_id"})
    for legacy_geometry_id in legacy_geometry_ids_for_local_id(canonical):
        references.append({"system": "legacy_admin_geometry", "value": legacy_geometry_id, "role": "accepted_storage_alias"})
    if local_id and local_id != canonical:
        references.append({"system": "admin_local", "value": local_id, "role": "preferred_local_id"})

    inferred_level = infer_admin_level_from_loc_id(canonical)
    level = admin_level_name(target_admin_level if target_admin_level not in (None, "") else inferred_level)
    country = str(iso3 or canonical.split("-", 1)[0] if "-" in canonical else iso3 or "").strip().upper()
    if family in {"admin_0", "admin_local", "admin_geometry"} or inferred_level is not None:
        for artifact in _bridge_artifacts(target_admin_level=level, iso3=country or None):
            source = str(artifact.get("source_family") or "").strip()
            if requested and source not in requested:
                continue
            result = resolve_admin_to_sidechains(
                canonical,
                source_family=source,
                target_admin_level=level,
                iso3=country or "USA",
                bridge_path=_catalog_bridge_path(artifact),
                min_target_area_share=min_share,
                limit=limit_per_system,
            )
            for overlap in result.get("overlaps") or []:
                source_ref = overlap.get("source") or {}
                references.append({
                    "system": source,
                    "value": source_ref.get("loc_id"),
                    "name": source_ref.get("name"),
                    "role": "bridge_overlap",
                    "bridge_vintage": overlap.get("bridge_vintage"),
                    "match_share": overlap.get("match_share"),
                    "match_rank": overlap.get("match_rank"),
                    "is_primary": overlap.get("is_primary"),
                })
    if requested:
        references = [ref for ref in references if ref.get("system") in requested or ref.get("system") == LOC_ID_SYSTEM]
    return _clean_json({"ok": bool(canonical), "loc_id": canonical, "family": family, "references": references, "reference_count": len(references)})


def convert_reference(
    *,
    from_system: str,
    value: str,
    to_system: str,
    iso3: str = "USA",
    target_admin_level: int | str | None = "admin_2",
    bridge_vintage: str | None = None,
    min_share: float | None = None,
    limit: int | None = 10,
) -> dict[str, Any]:
    """Convert a value from one reference system to another through ``loc_id``."""
    target = _normalize_system(to_system)
    resolved = resolve_reference(
        from_system=from_system,
        value=value,
        iso3=iso3,
        target_admin_level=target_admin_level,
        bridge_vintage=bridge_vintage,
        min_share=min_share,
        limit=limit,
    )
    loc_id = resolved.get("resolved_loc_id")
    if not loc_id:
        return _clean_json({"ok": False, "from": resolved, "to_system": target, "error": "source reference did not resolve to loc_id"})
    if target in {LOC_ID_SYSTEM, "admin_local", "admin_geometry"}:
        return _clean_json({"ok": True, "from": resolved, "to_system": target, "results": [{"system": target, "value": loc_id}]})
    references = loc_id_references(
        loc_id,
        systems=[target],
        iso3=iso3,
        target_admin_level=target_admin_level,
        min_share=min_share,
        limit_per_system=limit,
    )
    results = [ref for ref in references.get("references") or [] if ref.get("system") == target]
    if not results:
        return _clean_json({
            "ok": False,
            "from": resolved,
            "to_system": target,
            "results": [],
            "loc_id": loc_id,
            "error": {
                "code": "unsupported_target_system",
                "message": f"no references found from loc_id to {target}",
            },
        })
    return _clean_json({
        "ok": True,
        "from": resolved,
        "to_system": target,
        "results": results,
        "loc_id": loc_id,
    })


def _shape_geometry_reference(
    loc_id: str,
    feature: dict[str, Any] | None,
    *,
    include_polygon: bool = False,
    include_info: bool = True,
) -> dict[str, Any]:
    canonical = canonicalize_loc_id(loc_id)
    if not feature:
        return {"ok": False, "loc_id": canonical, "has_shape": False, "error": "no geometry found"}
    props = feature.get("properties") or {}
    payload = {
        "ok": True,
        "has_shape": True,
        "loc_id": props.get("local_loc_id") or canonical,
        "name": props.get("name"),
        "family": classify_loc_id_family(canonical),
        "admin_level": props.get("admin_level"),
        "centroid": {"lon": props.get("centroid_lon"), "lat": props.get("centroid_lat")},
        "bbox": [
            props.get("bbox_min_lon"),
            props.get("bbox_min_lat"),
            props.get("bbox_max_lon"),
            props.get("bbox_max_lat"),
        ],
    }
    if include_info:
        payload["info"] = get_location_info(canonical)
    if include_polygon:
        payload["geometry"] = feature.get("geometry")
    return _clean_json(payload)


def get_geometry_references(
    loc_ids: list[str],
    *,
    include_polygon: bool = False,
    include_info: bool = True,
) -> dict[str, Any]:
    """Return geometry metadata for one or more loc_ids using one geometry fetch pipeline."""
    canonical_ids = [canonicalize_loc_id(str(loc_id)) for loc_id in loc_ids if str(loc_id).strip()]
    feature_payload = get_selection_geometries(canonical_ids)
    features = (feature_payload or {}).get("features") or []
    by_loc_id: dict[str, dict[str, Any]] = {}
    for feature in features:
        props = feature.get("properties") or {}
        feature_loc_id = props.get("local_loc_id") or props.get("loc_id")
        if feature_loc_id:
            by_loc_id[canonicalize_loc_id(str(feature_loc_id))] = feature
    results = [
        _shape_geometry_reference(loc_id, by_loc_id.get(loc_id), include_polygon=include_polygon, include_info=include_info)
        for loc_id in canonical_ids
    ]
    available = sum(1 for result in results if result.get("has_shape"))
    return _clean_json(
        {
            "ok": bool(results),
            "requested": len(canonical_ids),
            "available": available,
            "missing": len(canonical_ids) - available,
            "results": results,
        }
    )


def get_geometry_availability(loc_ids: list[str]) -> dict[str, Any]:
    """Return a lightweight shape-availability preflight for one or more loc_ids."""
    payload = get_geometry_references(loc_ids, include_polygon=False, include_info=False)
    items = []
    for result in payload.get("results") or []:
        item = {
            "loc_id": result.get("loc_id"),
            "has_shape": bool(result.get("has_shape")),
            "family": result.get("family"),
            "admin_level": result.get("admin_level"),
            "centroid": result.get("centroid") if result.get("has_shape") else None,
            "bbox": result.get("bbox") if result.get("has_shape") else None,
        }
        if not item["has_shape"]:
            item["error"] = result.get("error") or "no geometry found"
        items.append(item)
    return _clean_json({**payload, "items": items, "results": items})


def get_geometry_reference(loc_id: str, *, include_polygon: bool = False) -> dict[str, Any]:
    """Return geometry metadata, and optionally polygon, for an exchange loc_id."""
    payload = get_geometry_references([loc_id], include_polygon=include_polygon, include_info=True)
    results = payload.get("results") or []
    if not results:
        return {"ok": False, "loc_id": canonicalize_loc_id(loc_id), "has_shape": False, "error": "no geometry found"}
    return results[0]
