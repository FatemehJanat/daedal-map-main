"""Spatial and temporal relationships between canonical geographic identities.

The public ``compare_geographies`` tool is deliberately loc_id-keyed.  Name and
outside-code resolution remains the responsibility of ``resolve_reference``;
this module compares the resulting identities and their selected geometries.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from shapely import make_valid
from shapely.geometry import shape

from .geography_reference import canonicalize_loc_id, classify_loc_id_family


UN_YUGOSLAVIA_SOURCE = "https://www.un.org/en/about-us/member-states/yugoslavia"
ISO_YUGOSLAVIA_SOURCE = "https://www.iso.org/files/live/sites/isoorg/files/archive/pdf/en/iso_3166-3_newsletter_i-3.pdf"
ISO_SERBIA_MONTENEGRO_SOURCE = "https://www.iso.org/files/live/sites/isoorg/files/archive/pdf/en/iso_3166-3_newsletter_i-4.pdf"


# These are referents, not merely strings.  The ISO YUG assertion spans more
# than one referent, so time-aware resolution selects SFRY before 1992 and FRY
# afterwards instead of pretending that the code denotes one immutable state.
HISTORICAL_ENTITIES: dict[str, dict[str, Any]] = {
    "HIST-YUG-SFRY": {
        "loc_id": "HIST-YUG-SFRY",
        "name": "Socialist Federal Republic of Yugoslavia",
        "short_name": "Yugoslavia",
        "family": "historical_admin_boundary",
        "valid_from": "1945-11-29",
        "valid_to": "1992-04-27",
        "authority": "United Nations",
        "source_url": UN_YUGOSLAVIA_SOURCE,
        "successors": [
            {"loc_id": "BIH", "name": "Bosnia and Herzegovina", "relationship_type": "equal_legal_successor", "effective_from": "1992-05-22"},
            {"loc_id": "HRV", "name": "Croatia", "relationship_type": "equal_legal_successor", "effective_from": "1992-05-22"},
            {"loc_id": "SVN", "name": "Slovenia", "relationship_type": "equal_legal_successor", "effective_from": "1992-05-22"},
            {"loc_id": "MKD", "name": "North Macedonia", "relationship_type": "equal_legal_successor", "effective_from": "1993-04-08", "name_at_transition": "The former Yugoslav Republic of Macedonia"},
            {"loc_id": "HIST-YUG-FRY", "name": "Federal Republic of Yugoslavia", "relationship_type": "equal_legal_successor", "effective_from": "1992-04-27"},
        ],
    },
    "HIST-YUG-FRY": {
        "loc_id": "HIST-YUG-FRY",
        "name": "Federal Republic of Yugoslavia",
        "short_name": "Yugoslavia",
        "family": "historical_admin_boundary",
        "valid_from": "1992-04-27",
        "valid_to": "2003-02-04",
        "authority": "ISO 3166 Maintenance Agency / United Nations",
        "source_url": ISO_YUGOSLAVIA_SOURCE,
        "successors": [
            {
                "loc_id": "HIST-SCG",
                "name": "Serbia and Montenegro",
                "relationship_type": "renamed_state",
                "effective_from": "2003-02-04",
                "source_url": ISO_YUGOSLAVIA_SOURCE,
            }
        ],
    },
    "HIST-SCG": {
        "loc_id": "HIST-SCG",
        "name": "Serbia and Montenegro",
        "family": "historical_admin_boundary",
        "valid_from": "2003-02-04",
        "valid_to": "2006-06-03",
        "authority": "ISO 3166 Maintenance Agency / United Nations",
        "source_url": ISO_SERBIA_MONTENEGRO_SOURCE,
        "successors": [
            {"loc_id": "SRB", "name": "Serbia", "relationship_type": "continuing_state", "effective_from": "2006-06-03"},
            {"loc_id": "MNE", "name": "Montenegro", "relationship_type": "separated_state", "effective_from": "2006-06-03"},
        ],
    },
}


def _parse_date(value: str | date | None, *, field: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        if len(text) == 4:
            return date(int(text), 1, 1)
        if len(text) == 7:
            return date.fromisoformat(f"{text}-01")
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date or year") from exc


def _valid_on(entity: dict[str, Any], when: date | None) -> bool | None:
    if when is None:
        return None
    start = _parse_date(entity.get("valid_from"), field="valid_from")
    end = _parse_date(entity.get("valid_to"), field="valid_to")
    return (start is None or when >= start) and (end is None or when < end)


def _terminal_successors(
    loc_id: str,
    *,
    seen: set[str] | None = None,
    path: list[str] | None = None,
    relationship_chain: list[str] | None = None,
    terminal_hint: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    visited = set(seen or set())
    canonical = str(loc_id).strip().upper()
    if canonical in visited:
        return []
    visited.add(canonical)
    current_path = [*(path or []), canonical]
    entity = HISTORICAL_ENTITIES.get(canonical)
    if not entity:
        hint = terminal_hint or {}
        return [{
            "loc_id": canonical,
            "name": hint.get("name"),
            "relationship_type": "present_day_descendant",
            "path": current_path,
            "relationship_chain": list(relationship_chain or []),
            "geometry_request": {"tool": "get_geometry", "loc_id": canonical, "include_polygon": True},
        }]
    terminals: list[dict[str, Any]] = []
    for successor in entity.get("successors") or []:
        successor_id = str(successor.get("loc_id") or "").strip().upper()
        if not successor_id:
            continue
        nested = _terminal_successors(
            successor_id,
            seen=visited,
            path=current_path,
            relationship_chain=[*(relationship_chain or []), str(successor.get("relationship_type") or "successor")],
            terminal_hint=successor,
        )
        if nested:
            terminals.extend(nested)
        else:
            terminals.append(dict(successor))
    unique: dict[str, dict[str, Any]] = {}
    for item in terminals:
        item_id = str(item.get("loc_id") or "").strip().upper()
        if item_id:
            unique.setdefault(item_id, item)
    return list(unique.values())


def historical_entity_info(loc_id: str, *, as_of: str | date | None = None) -> dict[str, Any] | None:
    canonical = str(loc_id or "").strip().upper()
    entity = HISTORICAL_ENTITIES.get(canonical)
    if not entity:
        return None
    when = _parse_date(as_of, field="as_of")
    direct = []
    for item in entity.get("successors") or []:
        direct.append({
            **dict(item),
            "authority": item.get("authority") or entity.get("authority"),
            "source_url": item.get("source_url") or entity.get("source_url"),
        })
    return {
        **{key: value for key, value in entity.items() if key != "successors"},
        "as_of": when.isoformat() if when else None,
        "valid_at_requested_time": _valid_on(entity, when),
        "lifecycle_status": "historical",
        "direct_successors": direct,
        "present_day_descendants": _terminal_successors(canonical),
        "successor_cardinality": "many" if len(direct) > 1 else ("one" if direct else "none"),
        "successor_semantics": "Successor relationships are a graph; they do not assert identity equivalence or require one replacement.",
    }


def resolve_historical_country_reference(value: str, *, as_of: str | date | None = None) -> dict[str, Any] | None:
    """Resolve the maintained Yugoslavia/Serbia-Montenegro temporal assertions."""
    text = str(value or "").strip().upper().replace("_", "-")
    when = _parse_date(as_of, field="as_of")
    yugoslavia_aliases = {"YUG", "YU", "YUCS", "YUGOSLAVIA", "ISO3166-3-YUG", "HIST-YUG-SFRY", "HIST-YUG-FRY"}
    scg_aliases = {"SCG", "CS", "CSHH", "SERBIA AND MONTENEGRO", "HIST-SCG"}
    if text in yugoslavia_aliases:
        if text == "HIST-YUG-SFRY":
            selected = "HIST-YUG-SFRY"
        elif text == "HIST-YUG-FRY":
            selected = "HIST-YUG-FRY"
        elif when and when < date(1992, 4, 27):
            selected = "HIST-YUG-SFRY"
        else:
            selected = "HIST-YUG-FRY"
    elif text in scg_aliases:
        selected = "HIST-SCG"
    else:
        return None
    info = historical_entity_info(selected, as_of=when)
    result = {
        "ok": True,
        "from_system": "historical_country",
        "input": value,
        "as_of": when.isoformat() if when else None,
        "resolved_loc_id": selected,
        "resolved_family": "historical_admin_boundary",
        "match_type": "time_scoped_historical_identity",
        "valid_at_requested_time": info.get("valid_at_requested_time") if info else None,
        "lifecycle": info,
    }
    if text in yugoslavia_aliases and text not in {"HIST-YUG-SFRY", "HIST-YUG-FRY"}:
        assertions = []
        for referent_id in ("HIST-YUG-SFRY", "HIST-YUG-FRY"):
            referent = historical_entity_info(referent_id, as_of=when) or {}
            assertions.append({
                "loc_id": referent_id,
                "name": referent.get("name"),
                "valid_from": referent.get("valid_from"),
                "valid_to": referent.get("valid_to"),
                "valid_at_requested_time": referent.get("valid_at_requested_time"),
                "present_day_descendants": referent.get("present_day_descendants") or [],
            })
        result["name_history"] = assertions
        result["selection_note"] = (
            "Yugoslavia is a reused historical name/code assertion. The requested date selects a referent; "
            "when the date is later than every assertion, the latest expired referent is returned without creating a current country."
        )
    return result


def _identity_state(loc_id: str, when: date | None) -> dict[str, Any]:
    historical = historical_entity_info(loc_id, as_of=when)
    if historical:
        return historical
    canonical = canonicalize_loc_id(loc_id)
    return {
        "loc_id": canonical,
        "family": classify_loc_id_family(canonical),
        "as_of": when.isoformat() if when else None,
        "valid_at_requested_time": None,
        "lifecycle_status": "unversioned",
        "temporal_confidence": "unknown",
        "direct_successors": [],
        "present_day_descendants": [],
    }


def _apply_geometry_validity(identity: dict[str, Any], geometry: dict[str, Any], when: date | None) -> None:
    """Use bank-row validity when the identity registry has no stronger clock."""
    if identity.get("valid_at_requested_time") is not None or when is None:
        return
    valid_from = geometry.get("valid_from")
    valid_to = geometry.get("valid_to")
    if valid_from in (None, "") and valid_to in (None, ""):
        return
    start = _parse_date(valid_from, field="geometry.valid_from")
    end = _parse_date(valid_to, field="geometry.valid_to")
    identity["valid_from"] = valid_from
    identity["valid_to"] = valid_to
    identity["valid_at_requested_time"] = (start is None or when >= start) and (end is None or when < end)
    identity["lifecycle_status"] = "bank_versioned"
    identity["temporal_confidence"] = "bank_declared"
    identity["geometry_vintage"] = geometry.get("geometry_vintage")
    identity["bank_id"] = geometry.get("bank_id")


def _geodesic_area_km2(geometry: Any) -> float | None:
    if geometry is None or geometry.is_empty:
        return 0.0
    try:
        from pyproj import Geod

        area, _perimeter = Geod(ellps="WGS84").geometry_area_perimeter(geometry)
        return abs(float(area)) / 1_000_000.0
    except Exception:
        return None


def _spatial_relationship(left_geometry: dict[str, Any], right_geometry: dict[str, Any]) -> dict[str, Any]:
    left = make_valid(shape(left_geometry))
    right = make_valid(shape(right_geometry))
    intersection = left.intersection(right)
    if left.equals(right):
        relation = "equals"
    elif left.disjoint(right):
        relation = "disjoint"
    elif left.touches(right):
        relation = "touches"
    elif left.within(right):
        relation = "within"
    elif left.contains(right):
        relation = "contains"
    elif left.overlaps(right):
        relation = "overlaps"
    else:
        relation = "intersects"
    left_area = _geodesic_area_km2(left)
    right_area = _geodesic_area_km2(right)
    intersection_area = _geodesic_area_km2(intersection)
    return {
        "spatial_relation": relation,
        "intersects": not left.disjoint(right),
        "left_inside_right": left.within(right) or left.equals(right),
        "right_inside_left": left.contains(right) or left.equals(right),
        "intersection_area_km2": intersection_area,
        "left_area_km2": left_area,
        "right_area_km2": right_area,
        "left_area_share": (intersection_area / left_area) if intersection_area is not None and left_area else None,
        "right_area_share": (intersection_area / right_area) if intersection_area is not None and right_area else None,
        "de9im": left.relate(right),
    }


def compare_geographies(
    left_loc_id: str,
    right_loc_id: str,
    *,
    as_of: str | date | None = None,
    left_as_of: str | date | None = None,
    right_as_of: str | date | None = None,
    include_successors: bool = True,
    geometry_fetcher: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compare two identities in time and, when available, exact geometry."""
    left_id = str(left_loc_id or "").strip().upper()
    right_id = str(right_loc_id or "").strip().upper()
    if not left_id or not right_id:
        return {"ok": False, "error": {"code": "invalid_comparison", "message": "left_loc_id and right_loc_id are required"}}
    common_when = _parse_date(as_of, field="as_of")
    left_when = _parse_date(left_as_of, field="left_as_of") or common_when
    right_when = _parse_date(right_as_of, field="right_as_of") or common_when
    left_identity = _identity_state(left_id, left_when)
    right_identity = _identity_state(right_id, right_when)
    if not include_successors:
        for identity in (left_identity, right_identity):
            identity.pop("direct_successors", None)
            identity.pop("present_day_descendants", None)

    if geometry_fetcher is None:
        from .reference_exchange import get_geometry_reference

        geometry_fetcher = get_geometry_reference
    left_geometry = geometry_fetcher(left_id, include_polygon=True)
    right_geometry = geometry_fetcher(right_id, include_polygon=True)
    _apply_geometry_validity(left_identity, left_geometry, left_when)
    _apply_geometry_validity(right_identity, right_geometry, right_when)
    left_valid = left_identity.get("valid_at_requested_time")
    right_valid = right_identity.get("valid_at_requested_time")
    if left_valid is False or right_valid is False:
        temporal_relation = "one_or_more_not_valid"
    elif left_valid is True and right_valid is True:
        temporal_relation = "coexistent"
    else:
        temporal_relation = "coexistence_unknown"
    spatial: dict[str, Any]
    if left_valid is False or right_valid is False:
        spatial = {
            "spatial_relation": "not_evaluated",
            "reason": "one or more identities are not valid at the requested time",
        }
    elif left_geometry.get("geometry") and right_geometry.get("geometry"):
        spatial = _spatial_relationship(left_geometry["geometry"], right_geometry["geometry"])
    else:
        spatial = {
            "spatial_relation": "geometry_unavailable",
            "reason": "approved geometry is missing for one or more requested identities",
        }
    return {
        "ok": True,
        "left": left_identity,
        "right": right_identity,
        "temporal_relation": temporal_relation,
        **spatial,
        "geometry_sources": {
            "left": {key: left_geometry.get(key) for key in ("loc_id", "name", "family", "admin_level", "has_shape", "valid_from", "valid_to", "geometry_vintage", "bank_id")},
            "right": {key: right_geometry.get(key) for key in ("loc_id", "name", "family", "admin_level", "has_shape", "valid_from", "valid_to", "geometry_vintage", "bank_id")},
        },
        "area_share_meaning": {
            "left_area_share": "fraction of the left geometry covered by the intersection",
            "right_area_share": "fraction of the right geometry covered by the intersection",
        },
    }
