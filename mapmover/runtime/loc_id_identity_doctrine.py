from __future__ import annotations

import re
from typing import Any

from .geography_reference import classify_loc_id_family

IDENTITY_ROLES = {
    "loc_id",
    "entity_id",
    "event_id",
    "route_id",
    "segment_id",
    "reach_id",
    "grid_id",
    "relationship_id",
    "crosswalk_id",
    "membership_set_id",
    "source_alias",
}

PUBLIC_PROMISES = {
    "stable_public",
    "public_alias",
    "internal",
    "private",
    "source_id",
    "blocked",
    "undecided",
}

ADMIN_FAMILIES = {
    "admin_0",
    "admin_local",
    "admin_geometry",
    "regional_base",
    "country_admin_extension",
}

SIDECHAIN_FAMILIES = {
    "overlay_zcta",
    "overlay_tribal",
    "overlay_nws_public_zone",
    "overlay_nws_fire_weather_zone",
    "postal",
    "water_body",
    "marine_eez",
    "marine_jurisdiction",
    "watershed",
    "protected_area",
    "ecoregion",
    "forest",
    "urban_area",
    "municipality",
    "electoral",
    "school_district",
    "health_region",
    "service_territory",
    "hazard_zone",
    "custom_private",
}

REFERENCE_LEVELS = {"label_0", "label_1", "label_2", "label_3", "label_4", "label_5"}

REFERENCE_LEVEL_REASONS = {
    "admin_spine",
    "official_admin_equivalent",
    "scale_hint",
    "source_native_hierarchy",
    "temporal_spine_version",
    "unresolved",
}

CONTAINMENT_METHODS = {
    "full_geometry",
    "centroid",
    "largest_overlap",
    "declared_by_source",
    "none",
}

SOURCE_FAMILY_PREFIXES = {
    "EEZ",
    "HYBAS",
    "HUC",
    "IHO1953",
    "MRGID",
    "WDPA",
    "WWF",
    "WWF-ECO",
    "OSM",
}

COUNTRY_SCOPED_SIDECHAIN_PATTERNS = (
    re.compile(r"^[A-Z]{3}-Z-\d{5}$"),
    re.compile(r"^[A-Z]{3}-FSA-[A-Z]\d[A-Z]$"),
    re.compile(r"^[A-Z]{3}-POA-\d{4}$"),
    re.compile(r"^[A-Z]{3}-TRIBAL-[A-Z0-9]+$"),
    re.compile(r"^[A-Z]{3}-NWS[ZF]Z-[A-Z]{2}Z\d{3}$"),
)

EVENT_MARKERS = {"EQ", "FIRE", "FLOOD", "HRCN", "TORN", "TSUN", "VOLC", "ALERT"}
GRID_PREFIXES = {"H3", "S2", "OLC", "PLUSCODE", "ERA5", "CMIP", "OISST", "SENTINEL"}
ROUTE_PREFIXES = {"ROUTE", "ROAD", "TRAIL", "RIVER"}
SEGMENT_PREFIXES = {"SEGMENT", "REACH", "WAY", "LINE"}

SPATIALLY_PLACEABLE_ROLES = {"loc_id", "entity_id", "route_id", "segment_id"}

DOCTRINE_DECISIONS: dict[str, list[dict[str, str]]] = {
    "present_system": [
        {
            "id": "present-001",
            "decision": "ISO3-dash fallback is early and broad.",
            "effect": "Many unknown country-prefixed strings are treated as admin/local loc_ids.",
        },
        {
            "id": "present-002",
            "decision": "Sidechains mostly depend on existing ad hoc parser exceptions.",
            "effect": "Postal, NWS, source, historical, and contested cases can fall through inconsistently.",
        },
    ],
    "proposed_changes": [
        {
            "id": "proposed-001",
            "decision": "Registry-first parsing beats broad string fallback.",
            "effect": "Known sidechains, events, grids, and source aliases are classified before admin fallback.",
        },
        {
            "id": "proposed-002",
            "decision": "Non-admin geography uses bridge/context rather than parent_id.",
            "effect": "ZCTAs, districts, watersheds, zones, and protected areas avoid fake admin hierarchy.",
        },
    ],
    "containing_loc_id": [
        {
            "id": "contain-001",
            "decision": "Spatial sibling layers can declare containing_loc_id placement.",
            "effect": "Placeable sidechains and spatial objects can be routed without becoming admin children.",
        },
        {
            "id": "contain-002",
            "decision": "reference_level is a declared depth/scale hint, not raw dash count.",
            "effect": "Lakes, forests, routes, cities, and zones can carry lookup scale separately from identity.",
        },
    ],
    "solidified_sibling_layer": [
        {
            "id": "solid-001",
            "decision": "Spatial sibling layer is the default for placeable non-admin things.",
            "effect": "loc_id, entity_id, route_id, and segment_id may all carry placement fields.",
        },
        {
            "id": "solid-002",
            "decision": "Historical and contested areas are registered temporal/claim sidechains.",
            "effect": "They stop pretending to be present admin children and stop falling to source_alias.",
        },
        {
            "id": "solid-003",
            "decision": "Crosswalks and membership sets are relationship identities.",
            "effect": "NHGIS/NUTS correspondence and Euro area membership are not ordinary loc_ids.",
        },
        {
            "id": "solid-004",
            "decision": "Country-scoped health/local/statistical sidechains beat admin fallback.",
            "effect": "Canada health regions and similar operational geographies avoid fake admin hierarchy.",
        },
        {
            "id": "solid-005",
            "decision": "Adopted city loc_ids use an explicit family token in the DaedalMap public form.",
            "effect": "A core city loc_id can look like USA-CA-CITY-LosAngeles while source codes, abbreviations, translations, and nicknames remain aliases/crosswalks.",
        },
    ],
}

PROPOSED_NAMESPACE_REGISTRY: list[dict[str, Any]] = [
    {
        "namespace": "current_admin_iso3",
        "pattern": r"^[A-Z]{3}$",
        "identity_role": "loc_id",
        "family_id": "admin_0",
        "scope_type": "admin_country",
        "public_promise": "stable_public_loc_id",
        "raw_input_allowed": True,
        "canonical_output_allowed": True,
        "bridge_policy": "admin_spine",
        "lifecycle_policy": "current_with_supersession",
        "license_policy": "public",
    },
    {
        "namespace": "current_admin_local",
        "pattern": r"^[A-Z]{3}(?:-[A-Z0-9]+)+$",
        "identity_role": "loc_id",
        "family_id": "admin_local",
        "scope_type": "admin_hierarchy",
        "public_promise": "stable_public_alias",
        "raw_input_allowed": True,
        "canonical_output_allowed": True,
        "bridge_policy": "admin_spine_or_country_crosswalk",
        "lifecycle_policy": "current_with_alias_lifecycle",
        "license_policy": "public",
    },
    {
        "namespace": "geoboundaries_storage",
        "pattern": r"^[A-Z]{3}(?:-G[A-Z0-9]+)+$",
        "identity_role": "loc_id",
        "family_id": "admin_geometry",
        "scope_type": "admin_hierarchy",
        "public_promise": "canonical_storage_identity",
        "raw_input_allowed": True,
        "canonical_output_allowed": False,
        "bridge_policy": "admin_spine_storage",
        "lifecycle_policy": "geometry_bank_lifecycle",
        "license_policy": "public",
    },
    {
        "namespace": "usa_zcta",
        "pattern": r"^USA-Z-\d{5}$",
        "identity_role": "loc_id",
        "family_id": "overlay_zcta",
        "scope_type": "country_reference_scope",
        "public_promise": "stable_public_loc_id",
        "raw_input_allowed": True,
        "canonical_output_allowed": True,
        "bridge_policy": "admin_overlap",
        "lifecycle_policy": "source_vintage",
        "license_policy": "public",
    },
    {
        "namespace": "country_postal_sidechain",
        "pattern": r"^[A-Z]{3}-(?:FSA|POA|PC)-[A-Z0-9]+$",
        "identity_role": "loc_id",
        "family_id": "postal",
        "scope_type": "country_reference_scope",
        "public_promise": "resolver_or_family_specific",
        "raw_input_allowed": True,
        "canonical_output_allowed": False,
        "bridge_policy": "family_specific",
        "lifecycle_policy": "source_vintage",
        "license_policy": "family_specific",
    },
    {
        "namespace": "country_scoped_sidechain",
        "pattern": r"^[A-Z]{3}-(?:TRIBAL|NWSZ|NWSFZ|HUC\d*|CD\d*|SD|UA\d*|CITY|MUNI|FOREST|PARK|FEMA|POWER|FED|CPCAD|TREATY)[A-Z0-9-]*$",
        "identity_role": "loc_id",
        "family_id": "sidechain",
        "scope_type": "country_reference_scope",
        "public_promise": "family_specific",
        "raw_input_allowed": True,
        "canonical_output_allowed": False,
        "bridge_policy": "family_specific",
        "lifecycle_policy": "family_specific",
        "license_policy": "family_specific",
    },
    {
        "namespace": "source_family_sidechain",
        "pattern": r"^(?:EEZ|HYBAS|HYDROLAKES|IHO1953|MRGID|WDPA|WWF-ECO|MRGID-EEZ|FOREST|URBAN)-[A-Z0-9-]+$",
        "identity_role": "loc_id",
        "family_id": "source_sidechain",
        "scope_type": "source_family_scope",
        "public_promise": "family_specific",
        "raw_input_allowed": True,
        "canonical_output_allowed": False,
        "bridge_policy": "family_specific",
        "lifecycle_policy": "source_vintage",
        "license_policy": "family_specific",
    },
    {
        "namespace": "external_source_alias",
        "pattern": r"^(?:OSM|GADM|WIKIDATA|GEONAMES|UNLOCODE|ISO3166-3|COW|FCC|PLACEKEY|WHG|GERS)-.+$",
        "identity_role": "source_alias",
        "family_id": "source_alias",
        "scope_type": "source_family_scope",
        "public_promise": "source_alias_only",
        "raw_input_allowed": True,
        "canonical_output_allowed": False,
        "bridge_policy": "reviewed_alias_or_relationship",
        "lifecycle_policy": "source_lifecycle",
        "license_policy": "source_specific",
    },
    {
        "namespace": "grid_or_tile",
        "pattern": r"^(?:H3|S2|OLC|PLUSCODE|MGRS|QUADKEY|LANDSAT|SENTINEL2|GHSL|PLACEKEY-@)-.+$",
        "identity_role": "grid_id",
        "family_id": "grid",
        "scope_type": "grid_scope",
        "public_promise": "source_alias_only",
        "raw_input_allowed": True,
        "canonical_output_allowed": False,
        "bridge_policy": "grid_overlap",
        "lifecycle_policy": "source_grid_version",
        "license_policy": "source_specific",
    },
    {
        "namespace": "event_or_forecast",
        "pattern": r"^(?:EQ|FIRE|FLOOD|HRCN|TORN|TSUN|VOLC|NHC|NWS|GFM)(?:-|:).+$",
        "identity_role": "event_id",
        "family_id": "event",
        "scope_type": "source_family_scope",
        "public_promise": "event_identity",
        "raw_input_allowed": True,
        "canonical_output_allowed": False,
        "bridge_policy": "event_affected_area",
        "lifecycle_policy": "event_time_window",
        "license_policy": "source_specific",
    },
    {
        "namespace": "network_or_route",
        "pattern": r"^(?:ROUTE|ROAD|TRAIL|RIVER|HYDRORIVERS|SEGMENT|REACH|WAY|LINE|UN-LOC).+$",
        "identity_role": "segment_id",
        "family_id": "network_segment",
        "scope_type": "source_family_scope",
        "public_promise": "source_alias_only",
        "raw_input_allowed": True,
        "canonical_output_allowed": False,
        "bridge_policy": "network_intersection",
        "lifecycle_policy": "network_version",
        "license_policy": "source_specific",
    },
    {
        "namespace": "historical_or_claim_area",
        "pattern": r"^(?:CSHAPES|AHCB|CLAIM|NE-DISPUTED|UN-ABYEI|EUROAREA)-.+$",
        "identity_role": "loc_id",
        "family_id": "temporal_or_claim_sidechain",
        "scope_type": "source_family_scope",
        "public_promise": "internal_candidate_identity",
        "raw_input_allowed": True,
        "canonical_output_allowed": False,
        "bridge_policy": "temporal_or_claim_crosswalk",
        "lifecycle_policy": "validity_window",
        "license_policy": "source_specific",
    },
    {
        "namespace": "crosswalk_artifact",
        "pattern": r"^(?:NHGIS-XWALK|NUTS-XWALK)-.+$",
        "identity_role": "crosswalk_id",
        "family_id": "relationship",
        "scope_type": "source_family_scope",
        "public_promise": "source_alias_only",
        "raw_input_allowed": True,
        "canonical_output_allowed": False,
        "bridge_policy": "versioned_crosswalk",
        "lifecycle_policy": "artifact_version",
        "license_policy": "source_specific",
    },
]

SOLIDIFIED_SIBLING_LAYER_REGISTRY: list[dict[str, Any]] = [
    {
        **entry,
        "pattern": r"^[A-Z]{3}(?:-[A-Z0-9]{2,3})?-(?:HA|CLHA|LHA|HEALTH|CITY|MUNI|PLACE|Z|ZCTA|FSA|POA|PC|TRIBAL|NWSZ|NWSFZ|HUC\d*|CD\d*|SD|UA\d*|FOREST|PARK|FEMA|POWER|FED|CPCAD|TREATY|NHGIS)[A-Z0-9-]*$",
        "scope_type": "country_reference_scope",
        "bridge_policy": "sibling_layer_placement",
    }
    if entry["namespace"] == "country_scoped_sidechain"
    else {
        **entry,
        "pattern": r"^(?:EEZ|HYBAS|HYDROLAKES|IHO1953|MRGID|WDPA|WWF-ECO|MRGID-EEZ|FOREST|URBAN|CSHAPES|AHCB|CLAIM|NE-DISPUTED|UN-ABYEI)-[A-Z0-9-]+$",
        "family_id": "source_or_temporal_sidechain",
        "bridge_policy": "sibling_layer_placement_or_temporal_crosswalk",
    }
    if entry["namespace"] == "source_family_sidechain"
    else {
        **entry,
        "pattern": r"^(?:NHGIS-XWALK|NUTS-XWALK|EUROAREA|COW-STATE)-.+$",
        "identity_role": "relationship_id",
        "family_id": "relationship",
        "bridge_policy": "versioned_relationship",
    }
    if entry["namespace"] == "crosswalk_artifact"
    else {
        **entry,
        "pattern": r"^(?:(?:OSM|GADM|WIKIDATA|GEONAMES|UNLOCODE|ISO3166-3|COW|FCC|WHG)-.+|PLACEKEY-(?!@).+|GERS-.+)$",
    }
    if entry["namespace"] == "external_source_alias"
    else entry
    for entry in PROPOSED_NAMESPACE_REGISTRY
    if entry["namespace"] != "historical_or_claim_area"
]

PRESENT_SYSTEM_REGISTRY: list[dict[str, Any]] = [
    {
        "namespace": "current_admin_iso3",
        "pattern": r"^[A-Z]{3}$",
        "identity_role": "loc_id",
        "family_id": "admin_0",
        "scope_type": "admin_country",
        "public_promise": "stable_public_loc_id",
    },
    {
        "namespace": "current_admin_local",
        "pattern": r"^[A-Z]{3}(?:-[A-Z0-9]+)+$",
        "identity_role": "loc_id",
        "family_id": "admin_local",
        "scope_type": "admin_hierarchy",
        "public_promise": "stable_public_alias",
    },
    {
        "namespace": "geoboundaries_storage",
        "pattern": r"^[A-Z]{3}(?:-G[A-Z0-9]+)+$",
        "identity_role": "loc_id",
        "family_id": "admin_geometry",
        "scope_type": "admin_hierarchy",
        "public_promise": "canonical_storage_identity",
    },
    {
        "namespace": "known_grid",
        "pattern": r"^(?:H3|S2|OLC|PLUSCODE|MGRS|QUADKEY|LANDSAT|SENTINEL2|GHSL)-.+$",
        "identity_role": "grid_id",
        "family_id": "grid",
        "scope_type": "grid_scope",
        "public_promise": "source_alias_only",
    },
    {
        "namespace": "known_event",
        "pattern": r"^(?:EQ|FIRE|FLOOD|HRCN|TORN|TSUN|VOLC|NHC|NWS|GFM)(?:-|:).+$",
        "identity_role": "event_id",
        "family_id": "event",
        "scope_type": "source_family_scope",
        "public_promise": "event_identity",
    },
]

DOCTRINE_PROFILES: dict[str, dict[str, Any]] = {
    "present_system": {
        "description": "Broad current runtime-style parsing where ISO3-dash strings tend to become admin/local loc_ids.",
        "registry": PRESENT_SYSTEM_REGISTRY,
        "admin_fallback_precedence": "first",
        "placement_policy": "parent_id",
    },
    "proposed_changes": {
        "description": "Registry-first present admin spine with explicit sidechain/source/entity/event/grid roles.",
        "registry": PROPOSED_NAMESPACE_REGISTRY,
        "admin_fallback_precedence": "last",
        "placement_policy": "bridge_only",
    },
    "containing_loc_id": {
        "description": "Registry-first doctrine where every location-like family may declare reference_level and containing_loc_id placement without becoming admin hierarchy.",
        "registry": PROPOSED_NAMESPACE_REGISTRY,
        "admin_fallback_precedence": "last",
        "placement_policy": "containing_loc_id",
    },
    "solidified_sibling_layer": {
        "description": "Next-pass doctrine that solidifies spatial sibling placement, temporal/claim sidechains, relationship artifacts, and country-scoped sidechains before admin fallback.",
        "registry": SOLIDIFIED_SIBLING_LAYER_REGISTRY,
        "admin_fallback_precedence": "last",
        "placement_policy": "containing_loc_id",
        "generic_expected_issues": "retired",
    },
}

NAMESPACE_REGISTRY = PROPOSED_NAMESPACE_REGISTRY


def _clean(value: Any) -> str:
    return str(value or "").strip().upper()


def _parts(value: str) -> list[str]:
    return [part for part in _clean(value).split("-") if part]


def _looks_like_country_scoped_sidechain(value: str) -> bool:
    text = _clean(value)
    return any(pattern.fullmatch(text) for pattern in COUNTRY_SCOPED_SIDECHAIN_PATTERNS)


def _profile(doctrine: str | None = None) -> dict[str, Any]:
    return DOCTRINE_PROFILES.get(str(doctrine or "proposed_changes"), DOCTRINE_PROFILES["proposed_changes"])


def doctrine_decisions(doctrine: str | None = None) -> list[dict[str, str]]:
    """Return the explicit policy decisions attached to a doctrine profile."""
    return list(DOCTRINE_DECISIONS.get(str(doctrine or "proposed_changes"), []))


def lookup_namespace(identifier: str | None, *, doctrine: str | None = None) -> dict[str, Any] | None:
    """Return the first registry entry that matches a raw identifier."""
    value = _clean(identifier)
    if not value:
        return None
    profile = _profile(doctrine)
    registry = profile["registry"]
    admin_fallback_precedence = str(profile.get("admin_fallback_precedence") or "last")
    fallback: dict[str, Any] | None = None
    for entry in registry:
        if re.fullmatch(str(entry["pattern"]), value):
            if entry["namespace"] == "current_admin_local" and admin_fallback_precedence == "last":
                fallback = entry
                continue
            return entry
    return fallback


def infer_identity_role(identifier: str | None, *, family_id: str | None = None, doctrine: str | None = None) -> str:
    """Return the smallest honest identity role for a candidate identifier."""
    value = _clean(identifier)
    family = _clean(family_id).lower()
    parts = _parts(value)
    if family in ADMIN_FAMILIES or family in SIDECHAIN_FAMILIES:
        return "loc_id"
    if family in {"entity", "entity_point", "entity_area"}:
        return "entity_id"
    if family == "event":
        return "event_id"
    if family in {"route", "network_route"}:
        return "route_id"
    if family in {"segment", "reach", "network_segment"}:
        return "segment_id"
    if family in {"grid", "raster", "cell"}:
        return "grid_id"
    if family == "source_alias":
        return "source_alias"

    registry = lookup_namespace(value, doctrine=doctrine)
    if registry:
        return str(registry["identity_role"])

    loc_family = classify_loc_id_family(value)
    if loc_family in ADMIN_FAMILIES or loc_family in SIDECHAIN_FAMILIES:
        return "loc_id"
    if loc_family == "event_or_entity":
        return "event_id"
    if _looks_like_country_scoped_sidechain(value):
        return "loc_id"
    if parts and (parts[0] in GRID_PREFIXES or any(part in GRID_PREFIXES for part in parts[:2])):
        return "grid_id"
    if parts and (parts[0] in ROUTE_PREFIXES):
        return "route_id"
    if parts and (parts[0] in SEGMENT_PREFIXES or parts[0] in {"HYDRORIVERS"}):
        return "segment_id"
    if any(part in EVENT_MARKERS for part in parts):
        return "event_id"
    return "source_alias"


def infer_first_segment_scope(identifier: str | None, *, family_id: str | None = None, doctrine: str | None = None) -> str | None:
    """Classify what the first loc_id segment is allowed to mean."""
    value = _clean(identifier)
    if not value:
        return None
    first = value.split("-", 1)[0]
    family = _clean(family_id).lower()
    if re.fullmatch(r"[A-Z]{3}", value):
        return "admin_country"
    registry = lookup_namespace(value, doctrine=doctrine)
    if registry and family not in ADMIN_FAMILIES:
        return str(registry["scope_type"])
    if first in SOURCE_FAMILY_PREFIXES or value.startswith("WWF-ECO-"):
        return "source_family_scope"
    country_scoped_match = re.match(r"^([A-Z]{3})-", value)
    if family in {"grid", "raster", "cell"}:
        return "grid_scope"
    if family in {"route", "network_route", "segment", "reach", "network_segment"} and re.match(r"^[A-Z]{3}-", value):
        return "country_reference_scope"
    if family in SIDECHAIN_FAMILIES and (
        _looks_like_country_scoped_sidechain(value)
        or (country_scoped_match is not None and first == country_scoped_match.group(1))
    ):
        return "country_reference_scope"
    if family in ADMIN_FAMILIES or classify_loc_id_family(value) in ADMIN_FAMILIES:
        return "admin_hierarchy"
    if _looks_like_country_scoped_sidechain(value):
        return "country_reference_scope"
    if first in GRID_PREFIXES:
        return "grid_scope"
    return "unknown"


def loc_id_may_encode_admin_hierarchy(identifier: str | None, *, family_id: str | None = None, doctrine: str | None = None) -> bool:
    registry = lookup_namespace(identifier, doctrine=doctrine)
    family = _clean(family_id).lower() or (str(registry.get("family_id")) if registry else None) or classify_loc_id_family(identifier)
    return family in ADMIN_FAMILIES


def expected_parent_semantics(identifier: str | None, *, family_id: str | None = None, doctrine: str | None = None) -> str:
    registry = lookup_namespace(identifier, doctrine=doctrine)
    if registry and registry.get("identity_role") in {"relationship_id", "crosswalk_id", "membership_set_id"}:
        return "not_applicable"
    family = _clean(family_id).lower() or (str(registry.get("family_id")) if registry else None) or classify_loc_id_family(identifier)
    if family in ADMIN_FAMILIES:
        return "strict_admin_parent"
    if family in SIDECHAIN_FAMILIES or family in {
        "sidechain",
        "source_sidechain",
        "source_or_temporal_sidechain",
        "temporal_or_claim_sidechain",
        "historical_admin",
        "historical_statistical_area",
        "temporal_membership_area",
        "contested_admin",
        "claim_area",
        "boundary_line",
    }:
        return "context_or_bridge_only"
    return "not_applicable"


def infer_admin_reference_level(identifier: str | None, *, family_id: str | None = None, doctrine: str | None = None) -> str | None:
    """Infer the admin-spine label depth when the identifier is truly admin."""
    if not loc_id_may_encode_admin_hierarchy(identifier, family_id=family_id, doctrine=doctrine):
        return None
    depth = max(0, min(len(_parts(identifier)) - 1, 5))
    return f"label_{depth}"


def expected_placement_semantics(identifier: str | None, *, family_id: str | None = None, doctrine: str | None = None) -> str:
    parent_semantics = expected_parent_semantics(identifier, family_id=family_id, doctrine=doctrine)
    if parent_semantics == "strict_admin_parent":
        return "identity_parent"
    profile = _profile(doctrine)
    if profile.get("placement_policy") == "containing_loc_id" and infer_identity_role(identifier, family_id=family_id, doctrine=doctrine) in SPATIALLY_PLACEABLE_ROLES:
        return "containing_loc_id"
    if parent_semantics == "context_or_bridge_only":
        return "bridge_or_context"
    return "not_applicable"


def _raw_case(case: dict[str, Any]) -> dict[str, Any]:
    raw = dict(case)
    raw.pop("family_id", None)
    raw.pop("expected_role", None)
    raw.pop("expected_first_segment_scope", None)
    raw.pop("expected_parent_semantics", None)
    raw.pop("expected_reference_level", None)
    raw.pop("expected_placement_semantics", None)
    raw.pop("expected_issues", None)
    return raw


def _expected_issues(case: dict[str, Any], *, doctrine: str | None = None) -> list[str]:
    doctrine_name = str(doctrine or "proposed_changes")
    by_doctrine = case.get("expected_issues_by_doctrine") or {}
    if doctrine_name in by_doctrine:
        return [str(issue) for issue in by_doctrine[doctrine_name]]
    if _profile(doctrine).get("generic_expected_issues") == "retired":
        return []
    return [str(issue) for issue in case.get("expected_issues") or []]


def _expected_value(case: dict[str, Any], key: str, *, doctrine: str | None = None) -> Any:
    doctrine_name = str(doctrine or "proposed_changes")
    by_doctrine = case.get(f"{key}_by_doctrine") or {}
    if doctrine_name in by_doctrine:
        return by_doctrine[doctrine_name]
    return case.get(key)


def evaluate_identity_case(case: dict[str, Any], *, doctrine: str | None = None) -> dict[str, Any]:
    """Evaluate one weird-geography fixture against the loc_id doctrine.

    This is intentionally deterministic and schema-light. It is a guardrail for
    design fixtures, not a full geometry resolver.
    """
    identifier = case.get("id") or case.get("loc_id") or case.get("candidate_id")
    family_id = case.get("family_id")
    role = infer_identity_role(identifier, family_id=family_id, doctrine=doctrine)
    loc_family = classify_loc_id_family(identifier)
    first_segment_scope = infer_first_segment_scope(identifier, family_id=family_id, doctrine=doctrine)
    may_encode_admin = loc_id_may_encode_admin_hierarchy(identifier, family_id=family_id, doctrine=doctrine)
    parent_semantics = expected_parent_semantics(identifier, family_id=family_id, doctrine=doctrine)
    registry = lookup_namespace(identifier, doctrine=doctrine)
    reference_level = case.get("reference_level") or infer_admin_reference_level(identifier, family_id=family_id, doctrine=doctrine)
    reference_level_reason = case.get("reference_level_reason")
    placement_semantics = expected_placement_semantics(identifier, family_id=family_id, doctrine=doctrine)
    issues: list[str] = []

    expected_role = _expected_value(case, "expected_role", doctrine=doctrine)
    if expected_role and expected_role not in IDENTITY_ROLES:
        issues.append(f"unknown expected_role {expected_role!r}")
    elif expected_role and role != expected_role:
        issues.append(f"role mismatch: expected {expected_role}, got {role}")

    expected_scope = _expected_value(case, "expected_first_segment_scope", doctrine=doctrine)
    if expected_scope and first_segment_scope != expected_scope:
        issues.append(f"first segment scope mismatch: expected {expected_scope}, got {first_segment_scope}")

    expected_parent = _expected_value(case, "expected_parent_semantics", doctrine=doctrine)
    if expected_parent and parent_semantics != expected_parent:
        issues.append(f"parent semantics mismatch: expected {expected_parent}, got {parent_semantics}")

    expected_reference_level = _expected_value(case, "expected_reference_level", doctrine=doctrine)
    if expected_reference_level and reference_level != expected_reference_level:
        issues.append(f"reference level mismatch: expected {expected_reference_level}, got {reference_level}")

    expected_placement = _expected_value(case, "expected_placement_semantics", doctrine=doctrine)
    if expected_placement and placement_semantics != expected_placement:
        issues.append(f"placement semantics mismatch: expected {expected_placement}, got {placement_semantics}")

    public_promise = case.get("public_promise")
    if public_promise and public_promise not in PUBLIC_PROMISES:
        issues.append(f"unknown public_promise {public_promise!r}")

    if role != "loc_id" and case.get("should_persist_as_loc_id"):
        issues.append(f"{role} must not be persisted as loc_id")

    if role == "loc_id" and not family_id and not loc_family and not registry:
        issues.append("loc_id case needs a family_id or recognized runtime family")

    if not may_encode_admin and case.get("admin_level") is not None:
        issues.append("non-admin families must not expose admin_level as spine depth")

    if reference_level and reference_level not in REFERENCE_LEVELS:
        issues.append(f"unknown reference_level {reference_level!r}")

    if reference_level_reason and reference_level_reason not in REFERENCE_LEVEL_REASONS:
        issues.append(f"unknown reference_level_reason {reference_level_reason!r}")

    if may_encode_admin and reference_level_reason and reference_level_reason not in {"admin_spine", "official_admin_equivalent", "temporal_spine_version"}:
        issues.append("admin families need an admin reference_level_reason")

    if not may_encode_admin and reference_level and not reference_level_reason:
        issues.append("non-admin reference_level requires reference_level_reason")

    if not may_encode_admin and reference_level_reason == "admin_spine":
        issues.append("non-admin reference_level must not claim admin_spine")

    if parent_semantics != "strict_admin_parent" and case.get("parent_id"):
        issues.append("non-admin parent_id must be represented as context or bridge metadata")

    containing_loc_id = case.get("containing_loc_id")
    containment_method = case.get("containment_method")
    crosses_admin_boundaries = case.get("crosses_admin_boundaries")
    if containing_loc_id and _profile(doctrine).get("placement_policy") != "containing_loc_id":
        issues.append("containing_loc_id belongs to containing_loc_id doctrine or resolver placement output")

    if containing_loc_id and not containment_method:
        issues.append("containing_loc_id requires containment_method")

    if containment_method and containment_method not in CONTAINMENT_METHODS:
        issues.append(f"unknown containment_method {containment_method!r}")

    if crosses_admin_boundaries is True and containment_method == "full_geometry":
        issues.append("cross-boundary geography cannot use full_geometry containment_method")

    if crosses_admin_boundaries is True and containing_loc_id and not case.get("overlapping_admin_loc_ids"):
        issues.append("cross-boundary containing_loc_id requires overlapping_admin_loc_ids")

    parent_status = case.get("parent_status")
    if parent_status == "contested" and not case.get("parent_claims"):
        issues.append("contested parentage requires parent_claims")
    if parent_status in {"missing", "unverified"}:
        parent_token = _clean(case.get("parent_id"))
        if parent_token and "NULL" not in parent_token:
            issues.append("missing or unverified admin parent must use NULL<n> sentinel")

    temporal_rule = case.get("temporal_rule")
    if temporal_rule == "supersession_required" and not (
        case.get("superseded_by") or case.get("supersedes")
    ):
        issues.append("supersession_required needs superseded_by or supersedes")

    if case.get("bridge_required") and not case.get("required_bridge_type"):
        issues.append("bridge_required cases must declare required_bridge_type")

    expected_issues = _expected_issues(case, doctrine=doctrine)
    unexpected_issues = [issue for issue in issues if issue not in expected_issues]
    missing_expected_issues = [issue for issue in expected_issues if issue not in issues]
    signal = "pass"
    if unexpected_issues:
        signal = "unexpected_issue"
    elif missing_expected_issues:
        signal = "missing_expected_issue"
    elif issues:
        signal = "expected_issue"

    return {
        "case": case.get("case"),
        "id": identifier,
        "source_system": case.get("source_system"),
        "sample_kind": case.get("sample_kind"),
        "doctrine": doctrine or "proposed_changes",
        "namespace": (lookup_namespace(identifier, doctrine=doctrine) or {}).get("namespace"),
        "role": role,
        "loc_id_family": loc_family,
        "first_segment_scope": first_segment_scope,
        "may_encode_admin_hierarchy": may_encode_admin,
        "parent_semantics": parent_semantics,
        "reference_level": reference_level,
        "reference_level_reason": reference_level_reason,
        "placement_semantics": placement_semantics,
        "issues": issues,
        "expected_issues": expected_issues,
        "unexpected_issues": unexpected_issues,
        "missing_expected_issues": missing_expected_issues,
        "design_questions": case.get("design_questions") or [],
        "ok": not unexpected_issues and not missing_expected_issues,
        "signal": signal,
    }


def evaluate_identity_cases(cases: list[dict[str, Any]], *, doctrine: str | None = None) -> list[dict[str, Any]]:
    return [evaluate_identity_case(case, doctrine=doctrine) for case in cases]


def evaluate_dual_mode_case(case: dict[str, Any], *, doctrine: str | None = None) -> dict[str, Any]:
    """Compare declared-metadata classification with raw-string classification."""
    declared = evaluate_identity_case(case, doctrine=doctrine)
    raw = evaluate_identity_case(_raw_case(case), doctrine=doctrine)
    deltas: list[str] = []
    for key in (
        "role",
        "first_segment_scope",
        "parent_semantics",
        "may_encode_admin_hierarchy",
        "reference_level",
        "placement_semantics",
    ):
        if declared.get(key) != raw.get(key):
            deltas.append(f"{key}: declared={declared.get(key)} raw={raw.get(key)}")

    signal = "pass"
    if deltas:
        signal = "raw_declared_delta"
    if declared.get("signal") in {"unexpected_issue", "missing_expected_issue"} or raw.get("signal") in {"unexpected_issue", "missing_expected_issue"}:
        signal = "needs_policy_decision"
    if deltas and case.get("allow_doctrine_conflict"):
        signal = "doctrine_conflict"

    return {
        "case": case.get("case"),
        "id": case.get("id") or case.get("loc_id") or case.get("candidate_id"),
        "source_system": case.get("source_system"),
        "declared": declared,
        "raw": raw,
        "deltas": deltas,
        "signal": signal,
    }


def evaluate_dual_mode_cases(cases: list[dict[str, Any]], *, doctrine: str | None = None) -> list[dict[str, Any]]:
    return [evaluate_dual_mode_case(case, doctrine=doctrine) for case in cases]


def compare_doctrine_case(case: dict[str, Any], *, left: str = "present_system", right: str = "proposed_changes") -> dict[str, Any]:
    left_result = evaluate_dual_mode_case(case, doctrine=left)
    right_result = evaluate_dual_mode_case(case, doctrine=right)
    deltas: list[str] = []
    for mode in ("declared", "raw"):
        for key in (
            "role",
            "first_segment_scope",
            "parent_semantics",
            "may_encode_admin_hierarchy",
            "reference_level",
            "placement_semantics",
            "namespace",
        ):
            if left_result[mode].get(key) != right_result[mode].get(key):
                deltas.append(
                    f"{mode}.{key}: {left}={left_result[mode].get(key)} {right}={right_result[mode].get(key)}"
                )
    signal = "pass" if not deltas else "doctrine_delta"
    if right_result["signal"] == "needs_policy_decision" or left_result["signal"] == "needs_policy_decision":
        signal = "needs_policy_decision"
    return {
        "case": case.get("case"),
        "id": case.get("id") or case.get("loc_id") or case.get("candidate_id"),
        "source_system": case.get("source_system"),
        "left_doctrine": left,
        "right_doctrine": right,
        "left": left_result,
        "right": right_result,
        "deltas": deltas,
        "signal": signal,
    }


def compare_doctrine_cases(
    cases: list[dict[str, Any]],
    *,
    left: str = "present_system",
    right: str = "proposed_changes",
) -> list[dict[str, Any]]:
    return [compare_doctrine_case(case, left=left, right=right) for case in cases]
