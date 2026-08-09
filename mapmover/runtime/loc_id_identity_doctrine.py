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
    "electoral",
    "school_district",
    "health_region",
    "service_territory",
    "hazard_zone",
    "custom_private",
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


def _clean(value: Any) -> str:
    return str(value or "").strip().upper()


def _parts(value: str) -> list[str]:
    return [part for part in _clean(value).split("-") if part]


def _looks_like_country_scoped_sidechain(value: str) -> bool:
    text = _clean(value)
    return any(pattern.fullmatch(text) for pattern in COUNTRY_SCOPED_SIDECHAIN_PATTERNS)


def infer_identity_role(identifier: str | None, *, family_id: str | None = None) -> str:
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


def infer_first_segment_scope(identifier: str | None, *, family_id: str | None = None) -> str | None:
    """Classify what the first loc_id segment is allowed to mean."""
    value = _clean(identifier)
    if not value:
        return None
    first = value.split("-", 1)[0]
    family = _clean(family_id).lower()
    if re.fullmatch(r"[A-Z]{3}", value):
        return "admin_country"
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


def loc_id_may_encode_admin_hierarchy(identifier: str | None, *, family_id: str | None = None) -> bool:
    family = _clean(family_id).lower() or classify_loc_id_family(identifier)
    return family in ADMIN_FAMILIES


def expected_parent_semantics(identifier: str | None, *, family_id: str | None = None) -> str:
    family = _clean(family_id).lower() or classify_loc_id_family(identifier)
    if family in ADMIN_FAMILIES:
        return "strict_admin_parent"
    if family in SIDECHAIN_FAMILIES:
        return "context_or_bridge_only"
    return "not_applicable"


def evaluate_identity_case(case: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one weird-geography fixture against the loc_id doctrine.

    This is intentionally deterministic and schema-light. It is a guardrail for
    design fixtures, not a full geometry resolver.
    """
    identifier = case.get("id") or case.get("loc_id") or case.get("candidate_id")
    family_id = case.get("family_id")
    role = infer_identity_role(identifier, family_id=family_id)
    loc_family = classify_loc_id_family(identifier)
    first_segment_scope = infer_first_segment_scope(identifier, family_id=family_id)
    may_encode_admin = loc_id_may_encode_admin_hierarchy(identifier, family_id=family_id)
    parent_semantics = expected_parent_semantics(identifier, family_id=family_id)
    issues: list[str] = []

    expected_role = case.get("expected_role")
    if expected_role and expected_role not in IDENTITY_ROLES:
        issues.append(f"unknown expected_role {expected_role!r}")
    elif expected_role and role != expected_role:
        issues.append(f"role mismatch: expected {expected_role}, got {role}")

    expected_scope = case.get("expected_first_segment_scope")
    if expected_scope and first_segment_scope != expected_scope:
        issues.append(f"first segment scope mismatch: expected {expected_scope}, got {first_segment_scope}")

    expected_parent = case.get("expected_parent_semantics")
    if expected_parent and parent_semantics != expected_parent:
        issues.append(f"parent semantics mismatch: expected {expected_parent}, got {parent_semantics}")

    public_promise = case.get("public_promise")
    if public_promise and public_promise not in PUBLIC_PROMISES:
        issues.append(f"unknown public_promise {public_promise!r}")

    if role != "loc_id" and case.get("should_persist_as_loc_id"):
        issues.append(f"{role} must not be persisted as loc_id")

    if role == "loc_id" and not family_id and not loc_family:
        issues.append("loc_id case needs a family_id or recognized runtime family")

    if not may_encode_admin and case.get("admin_level") is not None:
        issues.append("non-admin families must not expose admin_level as spine depth")

    if parent_semantics != "strict_admin_parent" and case.get("parent_id"):
        issues.append("non-admin parent_id must be represented as context or bridge metadata")

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

    expected_issues = [str(issue) for issue in case.get("expected_issues") or []]
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
        "role": role,
        "loc_id_family": loc_family,
        "first_segment_scope": first_segment_scope,
        "may_encode_admin_hierarchy": may_encode_admin,
        "parent_semantics": parent_semantics,
        "issues": issues,
        "expected_issues": expected_issues,
        "unexpected_issues": unexpected_issues,
        "missing_expected_issues": missing_expected_issues,
        "design_questions": case.get("design_questions") or [],
        "ok": not unexpected_issues and not missing_expected_issues,
        "signal": signal,
    }


def evaluate_identity_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [evaluate_identity_case(case) for case in cases]
