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
from ..geometry_handlers import get_location_info, get_selection_geometries, get_selection_geometry_metadata
from ..paths import DATA_ROOT
from .admin_hierarchy import infer_admin_level_from_loc_id
from .geography_reference import (
    canonicalize_loc_id,
    classify_loc_id_family,
    legacy_geometry_ids_for_local_id,
    translate_geometry_id_to_local_id,
    translate_loc_id_to_geometry_id,
)
from .geometry_catalog import (
    geometry_capability_summary,
    load_geometry_catalog,
    public_geometry_catalog_records,
    resolve_geometry_name,
)
from .external_reference_adapters import (
    GERS_SYSTEM,
    adapter_available,
    adapter_public_entry,
    admitted_external_adapters,
    edge_dict,
    external_primary_loc_ids,
    external_system_aliases,
    get_external_adapter,
    lookup_external_edges,
    lookup_loc_id_edges,
)
from .geography_relationships import resolve_historical_country_reference
from .loc_id_resolution import resolve_admin_text_to_loc_id
from .sidechain_admin_bridge import (
    admin_level_name,
    resolve_admin_to_sidechains,
    resolve_sidechain_to_admin,
    resolve_sidechains_to_admin,
)


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
    "historical": "historical_country",
    "historical_country_name": "historical_country",
    "iso3166_3": "historical_country",
    "iso_3166_3": "historical_country",
    "geoid": "us_census_geoid",
    "census_geoid": "us_census_geoid",
    "census_2020_geoid": "us_census_geoid",
    "us_census_2020_geoid": "us_census_geoid",
    **external_system_aliases(),
}


def _normalize_system(system: str | None) -> str:
    value = str(system or "").strip().lower().replace("-", "_").replace(" ", "_")
    return SYSTEM_ALIASES.get(value, value)


def verify_loc_ids(values: Any) -> set[str]:
    """Return the canonical subset of ``values`` that name a maintained identity.

    Two independent sources of evidence, because neither is complete on its own.
    The reference graph knows shapeless families such as ``can_economic_region``
    that carry no polygon, while the geometry banks cover countries the active
    country-scoped graph does not reach. A value confirmed by either is real; a
    value confirmed by neither is not a loc_id we hold.

    This exists because string shape is not identity. A dash-separated token
    looks exactly like a loc_id whether or not it is one, so echoing it back
    fabricates an identifier the caller cannot tell from a real one until it
    fails downstream. The marine EEZ branch already refuses on that principle;
    this helper lets every other passthrough refuse the same way.
    """
    candidates: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        canonical = canonicalize_loc_id(str(value or "").strip())
        if canonical and canonical not in seen:
            seen.add(canonical)
            candidates.append(canonical)
    if not candidates:
        return set()

    verified: set[str] = set()
    try:
        payload = get_geometry_references(candidates, include_polygon=False, include_info=False)
    except Exception:
        payload = {}
    for row in payload.get("results") or []:
        if not isinstance(row, dict) or not row.get("has_shape"):
            continue
        row_loc_id = canonicalize_loc_id(str(row.get("loc_id") or ""))
        if row_loc_id:
            verified.add(row_loc_id)

    remaining = [value for value in candidates if value not in verified]
    if not remaining:
        return verified
    try:
        from .reference_graph import identity as graph_identity
    except Exception:
        return verified
    for value in remaining:
        try:
            if graph_identity(value):
                verified.add(value)
        except Exception:
            continue
    return verified


def resolve_external_reference(
    system: str,
    value: str,
    *,
    country_scope: str | None = None,
    source_release: str | None = None,
    internal_release: str | None = None,
    limit: int | None = 10,
) -> dict[str, Any]:
    """Resolve an admitted external id through typed relationship edges.

    Only an explicit ``equivalent_identity`` edge may recommend a loc_id.
    ``contained_by`` and ``overlaps`` edges remain visible without becoming an
    identity claim. No target-admin argument exists on this boundary.
    """
    adapter = get_external_adapter(system)
    text = str(value or "").strip()
    normalized_system = adapter.system if adapter else _normalize_system(system)
    if adapter is None:
        return {"ok": False, "from_system": normalized_system, "input": value,
                "error": {"code": "external_system_not_admitted", "message": "external reference system is not admitted"}}
    if not text:
        return {"ok": False, "from_system": normalized_system, "input": value,
                "error": {"code": "external_id_required", "message": "value is required"}}
    if not adapter_available(adapter):
        return {"ok": False, "from_system": adapter.system, "input": value,
                "error": {"code": "external_system_unavailable", "message": "external reference system has no admitted, verified crosswalk"}}
    edges = lookup_external_edges(
        adapter.system,
        text,
        source_release=source_release,
        internal_release=internal_release,
        country_scope=country_scope,
    )
    if not edges:
        return {"ok": False, "from_system": adapter.system, "input": value,
                "error": {"code": "external_reference_not_found", "message": "no admitted typed edge matches that external identifier"}}
    equivalences = [edge for edge in edges if edge.is_equivalence]
    relationships = [edge for edge in edges if not edge.is_equivalence]
    relationships.sort(key=lambda edge: (-(edge.geometry_confidence or 0.0), edge.loc_id))
    if limit is not None:
        relationships = relationships[: max(0, int(limit) - (1 if equivalences else 0))]
    relationship_rows = [edge_dict(edge) for edge in relationships]
    if not equivalences:
        return _clean_json({
            "ok": False,
            "status": "relationship_only",
            "from_system": adapter.system,
            "input": value,
            "resolved_loc_id": None,
            "error": {
                "code": "external_reference_has_no_equivalence",
                "message": "maintained containment or overlap edges exist, but none asserts identity equivalence",
            },
            "relationships": relationship_rows,
            "relationship_count": len(relationships),
            "source_releases": sorted({edge.source_release for edge in edges if edge.source_release}),
            "internal_releases": sorted({edge.internal_release for edge in edges if edge.internal_release}),
        })
    equivalent_loc_ids = sorted({edge.loc_id for edge in equivalences})
    if len(equivalent_loc_ids) != 1:
        return _clean_json({
            "ok": False,
            "status": "conflicting_equivalence",
            "from_system": adapter.system,
            "input": value,
            "resolved_loc_id": None,
            "error": {
                "code": "external_reference_conflicting_equivalence",
                "message": "the admitted crosswalk asserts equivalence to more than one loc_id",
            },
            "relationships": [edge_dict(edge) for edge in equivalences] + relationship_rows,
            "relationship_count": len(edges),
        })
    equivalences.sort(key=lambda edge: (edge.partition_id or "", edge.edge_id or ""))
    primary = equivalences[0]
    return _clean_json({
        "ok": True,
        "from_system": adapter.system,
        "input": value,
        "resolved_loc_id": primary.loc_id,
        "resolved_family": _reference_family(primary.loc_id),
        "match_type": "exact_identifier_equivalence",
        "relationship_type": primary.relationship_type,
        "identity_confidence": primary.identity_confidence,
        "geometry_confidence": primary.geometry_confidence,
        "source_level": primary.source_level,
        "external_subtype": primary.external_subtype,
        "edge_id": primary.edge_id,
        "partition_id": primary.partition_id,
        "bridge_generation_id": primary.bridge_generation_id,
        "edge_content_hash": primary.edge_content_hash,
        "country": primary.country,
        "source_release": primary.source_release,
        "internal_release": primary.internal_release,
        "relationships": relationship_rows,
        "relationship_count": len(relationships),
    })


def resolve_gers_division(value: str, *, limit: int | None = 10) -> dict[str, Any]:
    """Compatibility wrapper for the generic admitted external adapter."""
    payload = resolve_external_reference(GERS_SYSTEM, value, limit=limit)
    # Preserve the pre-registry response vocabulary while callers migrate to
    # source_release/internal_release/external_subtype/source_level.
    payload.setdefault("overture_release", payload.get("source_release"))
    payload.setdefault("spine_vintage", payload.get("internal_release"))
    payload.setdefault("overture_subtype", payload.get("external_subtype"))
    payload.setdefault("admin_level", payload.get("source_level"))
    payload.setdefault("iso3", payload.get("country"))
    payload.setdefault("overlaps", payload.get("relationships") or [])
    payload.setdefault("overlap_count", payload.get("relationship_count") or 0)
    if payload.get("match_type") == "exact_identifier_equivalence":
        payload["match_type"] = "exact_identifier_crosswalk"
    if payload.get("relationship_type") == "equivalent_identity":
        payload["relationship_type"] = "equivalence"
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    compatibility_codes = {
        "external_id_required": "gers_id_required",
        "external_reference_not_found": "gers_division_not_found",
        "external_reference_has_no_equivalence": "gers_division_has_no_primary_match",
    }
    if error.get("code") in compatibility_codes:
        payload["error"] = {**error, "code": compatibility_codes[error["code"]]}
    return payload


def gers_primary_loc_ids(values: Any) -> dict[str, list[str]]:
    """Compatibility wrapper; only equivalence edges participate."""
    return external_primary_loc_ids(GERS_SYSTEM, list(values or []))


def _reference_family(loc_id: str, *, admin_level: Any = None) -> str | None:
    if admin_level is not None:
        return classify_loc_id_family(loc_id)
    try:
        from .reference_graph import identity as graph_identity

        row = graph_identity(loc_id) or {}
        family = row.get("geography_family") or row.get("family")
        if family:
            return family
    except Exception:
        pass
    return classify_loc_id_family(loc_id)


def _canonical_graph_loc_id(loc_id: str) -> str:
    """Resolve a retired loc_id alias without guessing between multiple versions."""
    canonical = canonicalize_loc_id(loc_id)
    family = classify_loc_id_family(canonical)
    if str(family or "").startswith("admin"):
        # Current admin IDs are already canonical. Point resolution emits these
        # exact values, so do not scan a country reference graph before the
        # bounded admin-spine geometry lookup gets a chance to serve them.
        return canonical
    try:
        from .reference_graph import identify_aliases, identity as graph_identity

        if graph_identity(canonical):
            return canonical
        resolved = {
            str(row.get("loc_id") or "").strip()
            for row in identify_aliases([canonical], limit=50)
            if str(row.get("loc_id") or "").strip()
        }
        if len(resolved) == 1:
            return next(iter(resolved))
    except Exception:
        pass
    return canonical


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


def _first_populated(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() not in {"nan", "nat", "<na>"}:
            return value
    return None


def _catalog_bridge_path(artifact: dict[str, Any]) -> Path | None:
    rel = str(artifact.get("artifact_path") or "").strip()
    if not rel:
        return None
    return DATA_ROOT / rel


def _bridge_source_names(artifact: dict[str, Any]) -> set[str]:
    """Return every normalized family name that may select a bridge."""
    values = [artifact.get("source_family"), *(artifact.get("source_family_aliases") or [])]
    return {
        _normalize_system(str(value))
        for value in values
        if str(value or "").strip()
    }


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
        if source and source not in _bridge_source_names(artifact):
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


"""Resolvers that reach loc_id on their own, without a bridge artifact.

A family carrying one of these answers name and point lookups directly, so it
stays exchangeable even though it owns no bridge row. Every other geometry or
reference-graph family needs a built bridge before a conversion can succeed.
"""
SELF_RESOLVING_RESOLVERS = frozenset({
    "named geometry catalog",
    "admin geometry name and point resolver",
})

_ALWAYS_EXCHANGEABLE_ROLES = frozenset({"reserve", "exact_identifier_system", "external_reference_bridge"})


def _mark_exchangeability(system: dict[str, Any], bridged_systems: set[str]) -> None:
    """Record whether a listed system can actually be converted through loc_id.

    Listing a family the conversion tools will refuse sends agents into
    guaranteed failures, so state the resolution path instead of implying one
    exists for everything in the catalog.
    """
    role = str(system.get("role") or "")
    resolver = str(system.get("resolver") or "").strip().lower()
    name = str(system.get("system") or "")
    if role in _ALWAYS_EXCHANGEABLE_ROLES:
        system["exchangeable"] = True
        system["exchange_via"] = (
            "reserve" if role == "reserve" else
            "typed_external_reference_edges" if role == "external_reference_bridge" else
            "exact_identifier_crosswalk"
        )
        return
    if name in bridged_systems:
        system["exchangeable"] = True
        system["exchange_via"] = "bridge_artifact"
        return
    if resolver in SELF_RESOLVING_RESOLVERS:
        system["exchangeable"] = True
        system["exchange_via"] = "self_resolving_geometry"
        return
    system["exchangeable"] = False
    system["exchange_via"] = None
    system["exchange_status"] = "no_bridge_artifact"


def _resolve_eez_by_country(text: str) -> dict[str, Any] | None:
    """Resolve a country name or ISO3 code to its maintained EEZ.

    EEZ ids carry the owning ISO3, so the country crosswalk already answers
    this; only the name-to-code step was missing. Returns the sovereign zone
    and lists any dependency zones separately rather than guessing between
    them - Australia owns five, and picking one silently would be wrong.
    """
    from .geography_reference import load_country_name_to_iso3_map

    candidate = str(text or "").strip()
    if not candidate:
        return None
    iso3 = candidate.upper() if len(candidate) == 3 and candidate.isalpha() else ""
    if not iso3:
        iso3 = str(load_country_name_to_iso3_map().get(candidate.casefold(), "")).upper()
    if not iso3:
        return None

    catalog = load_geometry_catalog()
    objects = {
        str(entry.get("loc_id")): entry
        for entry in catalog.get("named_reference_objects") or []
        if isinstance(entry, dict) and str(entry.get("family")) == "marine_eez"
    }
    primary = objects.get(f"EEZ-{iso3}")
    if not primary:
        return None
    return {
        "loc_id": primary.get("loc_id"),
        "label": primary.get("label"),
        "family": "marine_eez",
        "country_iso3": iso3,
        "resolved_from": "country_iso3_crosswalk",
    }


def list_reference_systems() -> dict[str, Any]:
    """Return the currently discoverable reference systems and bridges."""
    catalog = load_geometry_catalog()
    systems: dict[str, dict[str, Any]] = {
        LOC_ID_SYSTEM: {
            "system": LOC_ID_SYSTEM,
            "label": "DaedalMap loc_id",
            "role": "reserve",
            "bidirectional": True,
        },
        "us_census_geoid": {
            "system": "us_census_geoid",
            "label": "US Census GEOID",
            "role": "exact_identifier_system",
            "country_scope": "USA",
            "supported_geo_levels": ["admin_1", "admin_2", "admin_3", "admin_4", "admin_5"],
            "supported_vintages": ["2020"],
            "resolver": "exact_identifier_crosswalk",
            "bidirectional": False,
        },
    }
    for adapter in admitted_external_adapters():
        if adapter_available(adapter):
            systems[adapter.system] = adapter_public_entry(adapter)
    for family in catalog.get("geometry_families") or []:
        if not isinstance(family, dict):
            continue
        system = str(family.get("family") or "").strip()
        if not system:
            continue
        # External identifier systems are advertised only through their
        # admitted typed adapter. Legacy geometry-family names must not create
        # a second, target-admin-steerable authority path.
        if get_external_adapter(system):
            continue
        systems.setdefault(system, {
            "system": system,
            "label": family.get("label") or system,
            "role": "geometry_family",
            "feature_count": family.get("feature_count"),
            "resolver": family.get("resolver"),
        })
    try:
        from .reference_graph import reference_graph_families

        for family in reference_graph_families():
            system = str(family.get("family") or "").strip()
            if not system:
                continue
            if get_external_adapter(system):
                continue
            systems.setdefault(system, {
                "system": system,
                "label": system.replace("_", " ").title(),
                "role": "reference_graph_family",
                "identity_count": family.get("identity_count"),
                "shape_count": family.get("shape_count"),
            })
    except Exception:
        pass

    bridges = []
    bridged_systems: set[str] = set()
    for artifact in catalog.get("bridge_artifacts") or []:
        if not isinstance(artifact, dict) or str(artifact.get("status") or "") != "complete":
            continue
        source = str(artifact.get("source_family") or "").strip()
        if get_external_adapter(source):
            continue
        level = str(artifact.get("target_admin_level") or "").strip()
        # A family renamed by the area-depth migration answers to both names.
        # Without this the canonical name looks unreachable even though its
        # bridge exists and is complete.
        for alias in artifact.get("source_family_aliases") or []:
            alias_name = str(alias).strip()
            if alias_name:
                bridged_systems.add(alias_name)
        if source:
            bridged_systems.add(source)
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

    for system in systems.values():
        _mark_exchangeability(system, bridged_systems)
    ordered = sorted(systems.values(), key=lambda row: (not row.get("exchangeable"), str(row.get("system") or "")))
    exchangeable_count = sum(1 for row in ordered if row.get("exchangeable"))
    return _clean_json({
        "ok": True,
        "reserve_system": LOC_ID_SYSTEM,
        "systems": ordered,
        "system_count": len(ordered),
        "exchangeable_count": exchangeable_count,
        "listed_only_count": len(ordered) - exchangeable_count,
        "exchangeability_note": (
            "A system is exchangeable only when it has a real resolution path: the loc_id reserve, an exact "
            "identifier crosswalk, a self-resolving named or admin geometry resolver, or a complete bridge "
            "artifact to loc_id. Systems with exchangeable=false are discoverable geometry or reference-graph "
            "families with no built bridge; resolve_reference and convert_reference will refuse them."
        ),
        "bridges": bridges,
    })


def _public_catalog_records(catalog: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Return the MCP published lane, excluding every candidate lifecycle."""
    return published_geometry_catalog_records(catalog, key)


def _geometry_catalog_records(
    catalog: dict[str, Any], key: str, *, read_wip: bool,
) -> list[dict[str, Any]]:
    if not read_wip:
        return _public_catalog_records(catalog, key)
    return [dict(item) for item in catalog.get(key) or [] if isinstance(item, dict)]


def _geometry_catalog_counts(catalog: dict[str, Any], *, read_wip: bool = False) -> dict[str, int]:
    counts = {
        key: len(_geometry_catalog_records(catalog, key, read_wip=read_wip))
        for key in (
            "geometry_collections",
            "geometry_banks",
            "geometry_families",
            "bridge_artifacts",
            "geometry_products",
            "release_packages",
            "resolver_groups",
            "named_reference_objects",
        )
    }
    counts["country_profiles"] = len(_geometry_catalog_records(catalog, "country_profiles", read_wip=read_wip))
    return counts


def _geometry_catalog_countries(catalog: dict[str, Any], *, read_wip: bool = False) -> list[dict[str, Any]]:
    """Project the catalog-owned active country and family inventory."""
    coverage_by_country = {
        str(item.get("country_code") or "").strip().upper(): item
        for item in catalog.get("country_family_coverage") or []
        if isinstance(item, dict) and str(item.get("country_code") or "").strip()
    }
    countries: list[dict[str, Any]] = []
    for profile in _geometry_catalog_records(catalog, "country_profiles", read_wip=read_wip):
        country_code = str(profile.get("country_code") or "").strip().upper()
        if not country_code:
            continue
        coverage = coverage_by_country.get(country_code) or {}
        levels = [
            int(item["level"])
            for item in profile.get("admin_levels") or []
            if isinstance(item, dict) and str(item.get("level", "")).isdigit()
        ]
        families = [
            {
                "family_id": family.get("family_id"),
                "label": family.get("label"),
                "publication_status": family.get("publication_status"),
                "native_tier_names": family.get("native_tier_names") or [],
                "gap_or_disposition": family.get("gap_or_disposition"),
            }
            for family in coverage.get("families") or []
            if isinstance(family, dict) and (read_wip or family.get("available") is True)
        ]
        country = {
            "country_code": country_code,
            "label": profile.get("label") or coverage.get("label") or country_code,
            "release_version": profile.get("release_version"),
            "active_admin_depth": coverage.get("active_admin_depth") if coverage.get("active_admin_depth") is not None else (max(levels) if levels else None),
            "available_family_ids": list(coverage.get("available_family_ids") or []),
            "families": families,
            "query_layout_available": bool(profile.get("query_layout_manifest")),
            "reference_graph_available": bool(profile.get("reference_graph_manifest")),
        }
        if read_wip:
            country.update({
                "release_status": profile.get("release_status"),
                "publication_status": profile.get("publication_status"),
                "runtime_state": profile.get("runtime_state"),
                "candidate_state": profile.get("candidate_state"),
            })
        countries.append(country)
    return sorted(countries, key=lambda item: (str(item.get("label") or ""), item["country_code"]))


def _geometry_catalog_admin_coverage(catalog: dict[str, Any], *, read_wip: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    assets = _geometry_catalog_records(catalog, "geometry_products", read_wip=read_wip)
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        coverage = asset.get("admin_coverage")
        if not isinstance(coverage, dict):
            continue
        levels = coverage.get("levels") if isinstance(coverage.get("levels"), list) else []
        rows.append({
            "product_id": asset.get("product_id"),
            "label": asset.get("label"),
            "scope": asset.get("scope") or coverage.get("scope"),
            "family": asset.get("family"),
            "feature_count": asset.get("feature_count"),
            "has_shapes": bool(asset.get("has_shapes")),
            "min_admin_level": coverage.get("min_admin_level"),
            "max_admin_level": coverage.get("max_admin_level"),
            "levels": [
                {
                    "admin_level": item.get("admin_level"),
                    "label": item.get("label"),
                    "row_count": item.get("row_count"),
                    "file_count": item.get("file_count"),
                }
                for item in levels
                if isinstance(item, dict)
            ],
        })
    rows.sort(key=lambda item: (str(item.get("scope") or ""), str(item.get("product_id") or "")))
    return rows


def _geometry_catalog_bridges(catalog: dict[str, Any], *, read_wip: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for artifact in _geometry_catalog_records(catalog, "bridge_artifacts", read_wip=read_wip):
        if not isinstance(artifact, dict):
            continue
        source_license = artifact.get("source_license") if isinstance(artifact.get("source_license"), dict) else {}
        rows.append({
            "source_system": artifact.get("source_family"),
            "target_system": LOC_ID_SYSTEM,
            "target_family": artifact.get("target_family"),
            "target_admin_level": artifact.get("target_admin_level"),
            "bridge_vintage": artifact.get("bridge_vintage"),
            "status": artifact.get("status"),
            "row_count": artifact.get("row_count"),
            "source_count": artifact.get("source_count"),
            "target_count": artifact.get("target_count"),
            "license": source_license.get("license"),
            "license_review_status": source_license.get("license_review_status"),
        })
    return rows


def _geometry_catalog_products(catalog: dict[str, Any], *, read_wip: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for package in _geometry_catalog_records(catalog, "geometry_products", read_wip=read_wip):
        if not isinstance(package, dict):
            continue
        coverage = package.get("admin_coverage") if isinstance(package.get("admin_coverage"), dict) else {}
        rows.append({
            "product_id": package.get("product_id"),
            "label": package.get("label"),
            "group": package.get("product_group") or package.get("group"),
            "family": package.get("family"),
            "scope": package.get("scope"),
            "summary": package.get("summary"),
            "feature_count": package.get("feature_count"),
            "has_shapes": bool(package.get("has_shapes")),
            "artifact_kind": package.get("artifact_kind"),
            "max_admin_level": coverage.get("max_admin_level"),
            "cloud_probe_path": package.get("cloud_probe_path"),
        })
    return rows


def _geometry_catalog_named_reference_objects(
    catalog: dict[str, Any], *, limit: int, read_wip: bool = False,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    items = [
        item
        for item in _geometry_catalog_records(catalog, "named_reference_objects", read_wip=read_wip)
    ]
    for item in items[: max(0, limit)]:
        rows.append({
            "loc_id": item.get("loc_id"),
            "label": item.get("label"),
            "family": item.get("family"),
            "resolvable": item.get("resolvable"),
            "parent_loc_id": item.get("parent_loc_id"),
            "geometry_path": item.get("geometry_path"),
            "bank_id": item.get("bank_id"),
        })
    return {"items": rows, "returned": len(rows), "total": len(items), "truncated": len(rows) < len(items)}


def read_geometry_catalog(
    *, view: str = "summary", limit: int | None = 50, country_scope: str | None = None,
    read_wip: bool = False,
) -> dict[str, Any]:
    """Return an agent-oriented published or explicitly authorized WIP view."""
    catalog = load_geometry_catalog()
    try:
        from .reference_graph import reference_graph_families, where_is_geography_data

        data_source = where_is_geography_data()
        graph_families = reference_graph_families()
    except Exception as exc:
        data_source = {"ok": False, "error": str(exc)}
        graph_families = []
    selected_view = str(view or "summary").strip().lower().replace("-", "_")
    row_limit = max(1, min(int(limit or 50), 500))
    base = {
        "ok": True,
        "view": selected_view,
        "catalog_surface": "wip" if read_wip else "published",
        "schema_version": catalog.get("schema_version") or catalog.get("_schema_version"),
        "generated_at": catalog.get("generated_at"),
        "download_url": "https://downloads.daedalmap.com/downloadable/geometry/geometry_catalog.json",
        "app_summary_endpoint": "https://app.daedalmap.com/api/v1/geometry/catalog",
        "counts": _geometry_catalog_counts(catalog, read_wip=read_wip),
        "capabilities": geometry_capability_summary(catalog),
        "runtime_data_source": data_source,
        "runtime_reference_families": graph_families,
        "usage": {
            "start_here": "Use capabilities for the concise current coverage model. Use summary or a focused inventory view only when more catalog detail is needed.",
            "loc_id_rule": "Shape and data tools are keyed to DaedalMap loc_id. If an input is not a loc_id, call resolve_reference first.",
            "bulk_rule": "Prepared bulk point requests should provide country_scope and target_admin_level; geometry exports should preflight before create.",
            "wip_rule": (
                "This local-only view may contain staged, blocked, incomplete, or otherwise non-callable records. Use full to inspect complete lifecycle detail."
                if read_wip else
                "This is the published projection. Staged, blocked, and in-progress records are excluded."
            ),
        },
    }
    selected_country = str(country_scope or "").strip().upper()
    if selected_view == "capabilities" and selected_country:
        from .geometry_inventory import country_capability_record

        country = country_capability_record(catalog, selected_country)
        if country is None:
            return _clean_json({
                **base,
                "ok": False,
                "country_scope": selected_country,
                "error": {
                    "code": "country_not_found",
                    "message": f"Country {selected_country} is not present in the active geometry catalog.",
                },
            })
        return _clean_json({**base, "country_scope": selected_country, "country": country})
    if selected_view == "capabilities":
        return _clean_json(base)
    if selected_view == "summary":
        return _clean_json({
            **base,
            "collections": _geometry_catalog_records(catalog, "geometry_collections", read_wip=read_wip),
            "families": _geometry_catalog_records(catalog, "geometry_families", read_wip=read_wip),
            "admin_coverage": _geometry_catalog_admin_coverage(catalog, read_wip=read_wip),
        })
    if selected_view == "admin_coverage":
        return _clean_json({**base, "admin_coverage": _geometry_catalog_admin_coverage(catalog, read_wip=read_wip)})
    if selected_view == "countries":
        return _clean_json({**base, "countries": _geometry_catalog_countries(catalog, read_wip=read_wip)})
    if selected_view == "bridges":
        return _clean_json({**base, "bridges": _geometry_catalog_bridges(catalog, read_wip=read_wip)})
    if selected_view == "products":
        return _clean_json({**base, "products": _geometry_catalog_products(catalog, read_wip=read_wip)})
    if selected_view == "named_reference_objects":
        return _clean_json({**base, "named_reference_objects": _geometry_catalog_named_reference_objects(catalog, limit=row_limit, read_wip=read_wip)})
    if selected_view == "full":
        if read_wip:
            return _clean_json({**base, "catalog": catalog})
        return _clean_json({
            **base,
            "catalog": {
                "schema_version": catalog.get("schema_version") or catalog.get("_schema_version"),
                "generated_at": catalog.get("generated_at"),
                "capability_summary": geometry_capability_summary(catalog),
                "geometry_collections": _public_catalog_records(catalog, "geometry_collections"),
                "geometry_families": _public_catalog_records(catalog, "geometry_families"),
                "geometry_banks": _public_catalog_records(catalog, "geometry_banks"),
                "bridge_artifacts": _public_catalog_records(catalog, "bridge_artifacts"),
                "resolver_groups": _public_catalog_records(catalog, "resolver_groups"),
                "named_reference_objects": _public_catalog_records(catalog, "named_reference_objects"),
            },
        })
    return _clean_json({
        **base,
        "ok": False,
        "error": {
            "code": "invalid_view",
            "message": "view must be one of capabilities, summary, countries, admin_coverage, bridges, products, named_reference_objects, or full",
        },
    })


def _direct_loc_id_result(value: str, *, request_system: str) -> dict[str, Any]:
    loc_id = canonicalize_loc_id(value)
    if not loc_id:
        return {
            "ok": False,
            "from_system": request_system,
            "input": value,
            "resolved_loc_id": None,
            "error": {
                "code": "loc_id_required",
                "message": "value is not a parseable loc_id",
            },
        }
    # Passthrough normalizes case; it does not confer existence. Without this
    # check an Overture GERS UUID, or any dash-separated token, came back as a
    # confirmed loc_id purely because it had the right punctuation.
    if not verify_loc_ids([loc_id]):
        return {
            "ok": False,
            "from_system": request_system,
            "input": value,
            "normalized_input": loc_id,
            "resolved_loc_id": None,
            "error": {
                "code": "loc_id_not_found",
                "message": "no maintained identity or geometry matches that loc_id",
            },
        }
    return {
        "ok": True,
        "from_system": request_system,
        "input": value,
        "resolved_loc_id": loc_id,
        "resolved_family": classify_loc_id_family(loc_id),
        "match_type": "loc_id_passthrough",
        "references": [{"system": LOC_ID_SYSTEM, "value": loc_id, "role": "reserve"}],
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
    as_of: str | None = None,
    source_release: str | None = None,
    internal_release: str | None = None,
) -> dict[str, Any]:
    """Resolve a reference-system value into one or more ``loc_id`` matches."""
    system = _normalize_system(from_system)
    text = str(value or "").strip()
    if not text:
        return {"ok": False, "from_system": system, "input": value, "error": "value is required"}
    if system in {LOC_ID_SYSTEM, "admin_local", "admin_geometry"}:
        return _clean_json(_direct_loc_id_result(text, request_system=system))
    if get_external_adapter(system):
        # External edges own their typed relationship and two release clocks.
        # An admin level is observed metadata, never caller-steerable input.
        payload = resolve_external_reference(
            system,
            text,
            # `iso3` historically defaults to USA for admin bridges, so using
            # it here would silently filter a Canadian external id. Only the
            # explicit country hint may constrain an external adapter.
            country_scope=country_hint or None,
            source_release=source_release,
            internal_release=internal_release,
            limit=limit,
        )
        if system == GERS_SYSTEM:
            # Transitional aliases only; source_level/source_release/
            # internal_release are the canonical generic fields.
            payload.setdefault("admin_level", payload.get("source_level"))
            payload.setdefault("overture_subtype", payload.get("external_subtype"))
            payload.setdefault("overture_release", payload.get("source_release"))
            payload.setdefault("spine_vintage", payload.get("internal_release"))
        return _clean_json(payload)
    if system == "us_census_geoid":
        from .reference_identification import census_geoid_level, census_geoid_to_loc_id

        loc_id = census_geoid_to_loc_id(text)
        level = census_geoid_level(text)
        if not loc_id:
            return {
                "ok": False,
                "from_system": system,
                "input": value,
                "error": {
                    "code": "invalid_census_geoid",
                    "message": "expected a maintained 2, 5, 11, 12, or 15 digit US Census GEOID",
                },
            }
        availability = get_geometry_availability([loc_id])
        item = (availability.get("items") or [{}])[0]
        return _clean_json({
            "ok": True,
            "from_system": system,
            "input": value,
            "normalized_input": text,
            "resolved_loc_id": loc_id,
            "resolved_family": "admin_boundary",
            "admin_level": level,
            "match_type": "exact_identifier_crosswalk",
            "geometry_available": bool(item.get("has_shape")),
            "geometry": item,
            "source_vintage": "census_2020",
        })
    if system == ADMIN_SYSTEM:
        return _clean_json(_admin_text_result(text, country_hint=country_hint or iso3, admin_level_hint=admin_level_hint, request_system=system))
    if system == "historical_country":
        historical = resolve_historical_country_reference(text, as_of=as_of)
        if historical:
            return _clean_json(historical)
        return {
            "ok": False,
            "from_system": system,
            "input": value,
            "as_of": as_of,
            "error": {"code": "historical_reference_not_found", "message": "no maintained historical country assertion matched the value"},
        }
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
        if system == "marine_eez":
            # EEZ ids are ISO3-suffixed, but the bank labels them "Australian
            # Exclusive Economic Zone" with no aliases, so a country name never
            # matches by name. Resolve the country first, then the zone.
            eez = _resolve_eez_by_country(text)
            if eez:
                return _clean_json({
                    "ok": True,
                    "from_system": system,
                    "input": value,
                    "resolved_loc_id": eez["loc_id"],
                    "resolved_family": "marine_eez",
                    "match_type": "country_to_eez",
                    "match": eez,
                })
            # Never echo the input back as a loc_id. A fabricated identifier is
            # worse than a refusal because the caller cannot tell it apart from
            # a real one until it fails downstream.
            return _clean_json({
                "ok": False,
                "from_system": system,
                "input": value,
                "error": {
                    "code": "marine_eez_not_found",
                    "message": "no maintained EEZ matched that name, country, or ISO3 code",
                },
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
        try:
            from .reference_graph import identity as graph_identity, resolve_alias

            graph_matches = resolve_alias(system, text, limit=limit or 10, iso3=iso3)
        except Exception:
            graph_matches = []
        if graph_matches:
            primary = graph_matches[0]
            graph_node = graph_identity(str(primary.get("loc_id") or "")) or {}
            return _clean_json({
                "ok": True,
                "from_system": system,
                "input": value,
                "resolved_loc_id": primary.get("loc_id"),
                "resolved_family": graph_node.get("family") or classify_loc_id_family(primary.get("loc_id")),
                "match_type": "reference_graph_alias",
                "matches": graph_matches,
                "match_count": len(graph_matches),
            })
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
        "match_type": (
            "bridge_overlap"
            if primary.get("source_area_share") is not None
            else "bridge_identity"
        ),
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


def resolve_references_batch(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve reference requests while scanning each shared bridge only once.

    Direct IDs, names, aliases, historical references, and family-to-family
    conversions retain their existing single-request paths. Only homogeneous
    sidechain-to-admin bridge work is coalesced.
    """
    results: list[dict[str, Any] | None] = [None] * len(requests)
    groups: dict[tuple[Any, ...], list[tuple[int, dict[str, Any]]]] = {}
    for index, request in enumerate(requests):
        if request.get("to_system"):
            results[index] = convert_reference(**request)
            continue
        system = _normalize_system(request.get("from_system"))
        if get_external_adapter(system):
            results[index] = resolve_reference(**request)
            continue
        level = admin_level_name(request.get("target_admin_level") or "admin_2")
        iso3 = str(request.get("iso3") or "USA").strip().upper()
        artifact = _first_bridge_artifact(
            source_family=system,
            target_admin_level=level,
            iso3=iso3,
            bridge_vintage=request.get("bridge_vintage"),
        )
        if not artifact:
            results[index] = resolve_reference(**request)
            continue
        key = (
            system,
            level,
            iso3,
            str(_catalog_bridge_path(artifact) or ""),
            request.get("min_share"),
            int(request.get("limit") or 10),
        )
        groups.setdefault(key, []).append((index, request))

    for (system, level, iso3, artifact_path, min_share, limit), members in groups.items():
        normalized = [
            _normalize_source_loc_id(system, str(request.get("value") or "").strip(), iso3)
            for _, request in members
        ]
        batched = resolve_sidechains_to_admin(
            normalized,
            source_family=system,
            target_admin_level=level,
            iso3=iso3,
            bridge_path=Path(artifact_path),
            min_source_area_share=min_share,
            limit=limit,
        )
        for (index, request), source_loc_id in zip(members, normalized):
            bridge_result = batched.get(source_loc_id) or {}
            primary = bridge_result.get("primary_match") or {}
            results[index] = _clean_json({
                "ok": bool(bridge_result.get("ok")),
                "from_system": system,
                "input": request.get("value"),
                "normalized_input": source_loc_id,
                "resolved_loc_id": primary.get("match_loc_id"),
                "resolved_family": "admin_boundary" if primary.get("match_loc_id") else None,
                "match_type": "bridge_overlap",
                "bridge": {
                    "artifact_path": str(Path(artifact_path).relative_to(DATA_ROOT)).replace("\\", "/") if artifact_path else None,
                    "bridge_vintage": (primary or {}).get("bridge_vintage"),
                    "target_admin_level": level,
                },
                "primary_match": primary,
                "matches": bridge_result.get("overlaps") or [],
                "match_count": bridge_result.get("overlap_count") or 0,
                "error": bridge_result.get("error"),
            })
    return [result or {"ok": False, "error": "batch resolution produced no result"} for result in results]


def loc_id_references(
    loc_id: str,
    *,
    systems: list[str] | None = None,
    iso3: str | None = None,
    target_admin_level: int | str | None = None,
    min_share: float | None = None,
    limit_per_system: int | None = 10,
    source_release: str | None = None,
    internal_release: str | None = None,
) -> dict[str, Any]:
    """Return known references that point at a ``loc_id``."""
    canonical = canonicalize_loc_id(loc_id)
    family = classify_loc_id_family(canonical)
    try:
        from .reference_graph import identity as graph_identity

        family = (graph_identity(canonical) or {}).get("family") or family
    except Exception:
        pass
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
    # The reserve id is authoritative for its own country. `iso3` retains a
    # historical USA default for bridge calls and must not filter a CAN/BRA
    # reverse external-reference lookup out of existence.
    loc_country = canonical.split("-", 1)[0] if "-" in canonical else ""
    country = str(loc_country or iso3 or "").strip().upper()
    for adapter in admitted_external_adapters():
        if requested and adapter.system not in requested:
            continue
        for edge in lookup_loc_id_edges(
            adapter.system,
            canonical,
            country_scope=country or None,
            source_release=source_release,
            internal_release=internal_release,
            limit=limit_per_system,
        ):
            references.append({
                "system": adapter.system,
                "value": edge.external_id,
                "name": edge.external_name,
                "role": edge.relationship_type,
                "is_identity_equivalence": edge.is_equivalence,
                "is_primary": edge.is_primary,
                "source_release": edge.source_release,
                "internal_release": edge.internal_release,
                "country": edge.country,
                "source_level": edge.source_level,
                "external_subtype": edge.external_subtype,
                "edge_id": edge.edge_id,
                "partition_id": edge.partition_id,
                "bridge_generation_id": edge.bridge_generation_id,
                "edge_content_hash": edge.edge_content_hash,
                "identity_confidence": edge.identity_confidence,
                "geometry_confidence": edge.geometry_confidence,
            })
    if family in {"admin_0", "admin_local", "admin_geometry"} or inferred_level is not None:
        for artifact in _bridge_artifacts(target_admin_level=level, iso3=country or None):
            source = str(artifact.get("source_family") or "").strip()
            if get_external_adapter(source):
                continue
            source_names = _bridge_source_names(artifact)
            requested_names = sorted(requested & source_names)
            if requested and not requested_names:
                continue
            output_system = requested_names[0] if requested_names else source
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
                    "system": output_system,
                    "bridge_source_system": source,
                    "value": source_ref.get("loc_id"),
                    "name": source_ref.get("name"),
                    "role": "bridge_overlap",
                    "bridge_vintage": overlap.get("bridge_vintage"),
                    "match_share": overlap.get("match_share"),
                    "match_rank": overlap.get("match_rank"),
                    "is_primary": overlap.get("is_primary"),
                })
    try:
        from .reference_graph import aliases_for_loc_id, relationships_for_loc_id

        for alias in aliases_for_loc_id(canonical, limit=limit_per_system or 10):
            system = str(alias.get("reference_system") or "").strip()
            if get_external_adapter(system):
                continue
            if requested and system not in requested:
                continue
            references.append({
                "system": system,
                "value": alias.get("external_id"),
                "role": alias.get("alias_type") or "reference_graph_alias",
                "source_system": alias.get("source_system"),
                "source_vintage": alias.get("source_vintage"),
            })
        graph_limit = max(1, min(int(limit_per_system or 10) * 10, 100))
        for edge in relationships_for_loc_id(canonical, limit=graph_limit):
            outgoing = str(edge.get("source_loc_id") or "") == canonical
            system = str(edge.get("target_family") if outgoing else edge.get("source_family") or "").strip()
            if get_external_adapter(system):
                continue
            if requested and system not in requested:
                continue
            references.append({
                "system": system,
                "value": edge.get("target_loc_id") if outgoing else edge.get("source_loc_id"),
                "name": edge.get("target_name") if outgoing else edge.get("source_name"),
                "role": edge.get("relationship_type"),
                "relationship_id": edge.get("relationship_id"),
                "direction": "outgoing" if outgoing else "incoming",
                "relationship_subtype": edge.get("relationship_subtype"),
                "relationship_vintage": edge.get("relationship_vintage"),
                "valid_from": edge.get("valid_from"),
                "valid_to": edge.get("valid_to"),
                "source_area_share": edge.get("source_area_share"),
                "target_area_share": edge.get("target_area_share"),
                "is_primary": edge.get("is_primary"),
                "method": edge.get("method"),
                "authority": edge.get("authority"),
            })
    except Exception:
        pass
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
    source_release: str | None = None,
    internal_release: str | None = None,
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
        source_release=source_release,
        internal_release=internal_release,
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
        source_release=source_release,
        internal_release=internal_release,
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
    family = _reference_family(canonical, admin_level=props.get("admin_level"))
    payload = {
        "ok": True,
        "has_shape": True,
        "loc_id": props.get("local_loc_id") or canonical,
        "name": props.get("name"),
        "family": family,
        "admin_level": props.get("admin_level"),
        "centroid": {"lon": props.get("centroid_lon"), "lat": props.get("centroid_lat")},
        "bbox": [
            props.get("bbox_min_lon"),
            props.get("bbox_min_lat"),
            props.get("bbox_max_lon"),
            props.get("bbox_max_lat"),
        ],
        "valid_from": _first_populated(props, "valid_from", "valid_from_date"),
        "valid_to": _first_populated(props, "valid_to", "valid_to_date"),
        "geometry_vintage": props.get("geometry_vintage"),
        "bank_id": props.get("bank_id"),
    }
    if include_info:
        payload["info"] = get_location_info(canonical)
    if include_polygon:
        payload["geometry"] = feature.get("geometry")
    return _clean_json(payload)


def _metadata_geometry_reference(
    loc_id: str,
    row: dict[str, Any] | None,
    *,
    include_info: bool = True,
) -> dict[str, Any]:
    canonical = canonicalize_loc_id(loc_id)
    if not row:
        return {"ok": False, "loc_id": canonical, "has_shape": False, "error": "no geometry found"}
    family = _reference_family(canonical, admin_level=row.get("admin_level"))
    payload = {
        "ok": True,
        "has_shape": True,
        "loc_id": row.get("loc_id") or row.get("source_loc_id") or canonical,
        "name": row.get("name"),
        "family": family,
        "admin_level": row.get("admin_level"),
        "centroid": {"lon": row.get("centroid_lon"), "lat": row.get("centroid_lat")},
        "bbox": [
            row.get("bbox_min_lon"),
            row.get("bbox_min_lat"),
            row.get("bbox_max_lon"),
            row.get("bbox_max_lat"),
        ],
        "valid_from": row.get("valid_from"),
        "valid_to": row.get("valid_to"),
        "geometry_vintage": row.get("geometry_vintage"),
        "bank_id": row.get("bank_id"),
    }
    if include_info:
        payload["info"] = get_location_info(canonical)
    return _clean_json(payload)


def get_geometry_references(
    loc_ids: list[str],
    *,
    include_polygon: bool = False,
    include_info: bool = True,
) -> dict[str, Any]:
    """Return geometry metadata for one or more loc_ids using one geometry fetch pipeline."""
    canonical_ids = [_canonical_graph_loc_id(str(loc_id)) for loc_id in loc_ids if str(loc_id).strip()]
    if not include_polygon:
        rows = get_selection_geometry_metadata(canonical_ids)
        by_loc_id: dict[str, dict[str, Any]] = {}
        for row in rows:
            row_loc_id = row.get("loc_id") or row.get("source_loc_id")
            if row_loc_id:
                by_loc_id[canonicalize_loc_id(str(row_loc_id))] = row
        results = [
            _metadata_geometry_reference(loc_id, by_loc_id.get(loc_id), include_info=include_info)
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
    canonical_ids = [_canonical_graph_loc_id(str(loc_id)) for loc_id in loc_ids if str(loc_id).strip()]
    rows = get_selection_geometry_metadata(canonical_ids)
    by_loc_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        row_loc_id = row.get("loc_id") or row.get("source_loc_id")
        if row_loc_id:
            by_loc_id[canonicalize_loc_id(str(row_loc_id))] = row
    items = []
    for loc_id in canonical_ids:
        result = by_loc_id.get(loc_id)
        has_shape = bool(result)
        item = {
            "loc_id": loc_id,
            "has_shape": has_shape,
            "name": result.get("name") if result else None,
            "family": _reference_family(loc_id, admin_level=result.get("admin_level")) if has_shape else None,
            "admin_level": result.get("admin_level") if result else None,
            "centroid": {"lon": result.get("centroid_lon"), "lat": result.get("centroid_lat")} if has_shape else None,
            "bbox": [
                result.get("bbox_min_lon"),
                result.get("bbox_min_lat"),
                result.get("bbox_max_lon"),
                result.get("bbox_max_lat"),
            ] if has_shape else None,
        }
        if not item["has_shape"]:
            item["error"] = "no geometry found"
        items.append(item)
    available = sum(1 for item in items if item.get("has_shape"))
    return _clean_json(
        {
            "ok": bool(canonical_ids),
            "requested": len(canonical_ids),
            "available": available,
            "missing": len(canonical_ids) - available,
            "items": items,
            "results": items,
        }
    )


def get_geometry_reference(loc_id: str, *, include_polygon: bool = False) -> dict[str, Any]:
    """Return geometry metadata, and optionally polygon, for an exchange loc_id."""
    payload = get_geometry_references([loc_id], include_polygon=include_polygon, include_info=True)
    results = payload.get("results") or []
    if not results:
        return {"ok": False, "loc_id": canonicalize_loc_id(loc_id), "has_shape": False, "error": "no geometry found"}
    return results[0]
