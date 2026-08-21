"""Identify unknown geography identifiers against maintained reference banks.

This is the discovery step immediately before ``resolve_reference``.  It works
only from exact identifier evidence: format signatures, reference-graph alias
rows, and geometry-bank availability.  It does not inspect polygons or infer a
vintage that the evidence cannot support.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .sidechain_admin_bridge import admin_level_name


US_CENSUS_GEOID_SYSTEM = "us_census_geoid"

US_STATE_FIPS_TO_ABBR = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA",
    "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
    "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN",
    "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
    "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS",
    "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
    "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
    "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI",
    "56": "WY", "60": "AS", "66": "GU", "69": "MP", "72": "PR",
    "78": "VI",
}

_SYSTEM_ALIASES = {
    "loc_id": "daedalmap.loc_id",
    "locid": "daedalmap.loc_id",
    "daedalmap": "daedalmap.loc_id",
    "daedalmap_loc_id": "daedalmap.loc_id",
    "geoid": US_CENSUS_GEOID_SYSTEM,
    "census_geoid": US_CENSUS_GEOID_SYSTEM,
    "census_2020_geoid": US_CENSUS_GEOID_SYSTEM,
    "us_census_2020_geoid": US_CENSUS_GEOID_SYSTEM,
    "zip": "overlay_zcta",
    "zcta": "overlay_zcta",
    "usa.census.2020.zcta5.geoid": "overlay_zcta",
    "nws_zone": "overlay_nws_public_zone",
    "nws_fire": "overlay_nws_fire_weather_zone",
}


def normalize_identifier_system(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _SYSTEM_ALIASES.get(text, text)


def census_geoid_level(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text.isdigit() or text[:2] not in US_STATE_FIPS_TO_ABBR:
        return None
    return {2: "admin_1", 5: "admin_2", 11: "admin_3", 12: "admin_4", 15: "admin_5"}.get(len(text))


def census_geoid_to_loc_id(value: Any) -> str | None:
    text = str(value or "").strip()
    level = census_geoid_level(text)
    if not level:
        return None
    state = US_STATE_FIPS_TO_ABBR[text[:2]]
    if level == "admin_1":
        return f"USA-{state}"
    county = text[2:5]
    if level == "admin_2":
        return f"USA-{state}-{county}"
    tract = text[5:11]
    if level == "admin_3":
        return f"USA-{state}-{county}-{tract}"
    block_group = text[11]
    if level == "admin_4":
        return f"USA-{state}-{county}-{tract}-{block_group}"
    return f"USA-{state}-{county}-{tract}-{block_group}-{text[11:15]}"


def _expected_level(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return admin_level_name(value)
    except Exception:
        return str(value).strip().lower().replace(" ", "_")


def _geometry_rows(loc_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not loc_ids:
        return {}
    from .reference_exchange import get_geometry_references

    payload = get_geometry_references(loc_ids, include_polygon=False, include_info=False)
    return {
        str(row.get("loc_id") or ""): row
        for row in payload.get("results") or []
        if isinstance(row, dict) and row.get("loc_id")
    }


def _catalog_bank(*, country_scope: str, admin_level: str, expected_vintage: str | None) -> dict[str, Any] | None:
    from .geometry_catalog import load_geometry_catalog

    country = str(country_scope or "").strip().upper()
    vintage = str(expected_vintage or "").strip().lower()
    matches = []
    for bank in load_geometry_catalog().get("geometry_banks") or []:
        if not isinstance(bank, dict):
            continue
        if country and str(bank.get("scope") or "").strip().upper() != country:
            continue
        try:
            bank_level = admin_level_name(bank.get("admin_level"))
        except Exception:
            bank_level = str(bank.get("admin_level") or "").strip().lower()
        if bank_level != admin_level:
            continue
        bank_vintage = str(bank.get("source_vintage") or bank.get("release_id") or "").strip().lower()
        if vintage and vintage not in bank_vintage:
            continue
        matches.append(bank)
    matches.sort(key=lambda item: (
        str(item.get("spine_readiness") or "") != "ready",
        str(item.get("bank_id") or ""),
    ))
    return matches[0] if matches else None


def _candidate(
    *,
    system: str,
    identifiers: list[str],
    matches: dict[str, list[str]],
    levels: dict[str, str] | None = None,
    method: str,
    expected_vintage: str | None = None,
    country_scope: str = "",
) -> dict[str, Any]:
    matched_identifiers = [value for value in identifiers if matches.get(value)]
    loc_ids = list(dict.fromkeys(loc_id for value in matched_identifiers for loc_id in matches[value]))
    geometry = _geometry_rows(loc_ids)
    shape_ids = {loc_id for loc_id, row in geometry.items() if row.get("has_shape")}
    level_values = sorted({level for level in (levels or {}).values() if level})
    bank_ids = sorted({str(geometry[loc_id].get("bank_id")) for loc_id in shape_ids if geometry[loc_id].get("bank_id")})
    geometry_vintages = sorted({str(geometry[loc_id].get("geometry_vintage")) for loc_id in shape_ids if geometry[loc_id].get("geometry_vintage")})
    catalog_bank = None
    if len(level_values) == 1:
        catalog_bank = _catalog_bank(
            country_scope=country_scope,
            admin_level=level_values[0],
            expected_vintage=expected_vintage,
        )
        if catalog_bank and catalog_bank.get("bank_id") and str(catalog_bank["bank_id"]) not in bank_ids:
            bank_ids.append(str(catalog_bank["bank_id"]))
    sample_matches = [
        {
            "identifier": value,
            "loc_ids": matches[value][:5],
            "geo_level": (levels or {}).get(value),
            "geometry_available": any(loc_id in shape_ids for loc_id in matches[value]),
        }
        for value in matched_identifiers[:10]
    ]
    return {
        "system": system,
        "method": method,
        "match_count": len(matched_identifiers),
        "unmatched_count": len(identifiers) - len(matched_identifiers),
        "match_rate": round(len(matched_identifiers) / len(identifiers), 6) if identifiers else 0.0,
        "ambiguous_identifier_count": sum(1 for value in matched_identifiers if len(matches[value]) > 1),
        "geo_levels": level_values,
        "loc_id_resolvable": bool(loc_ids),
        "geometry_available": bool(shape_ids),
        "geometry_available_count": sum(
            1 for value in matched_identifiers if any(loc_id in shape_ids for loc_id in matches[value])
        ),
        "geometry_bank_ids": sorted(bank_ids),
        "geometry_vintages": geometry_vintages,
        "expected_vintage_supported": (catalog_bank is not None) if expected_vintage else None,
        "catalog_bank": {
            "bank_id": catalog_bank.get("bank_id"),
            "source_vintage": catalog_bank.get("source_vintage"),
            "release_id": catalog_bank.get("release_id"),
            "geometry_path": catalog_bank.get("geometry_path"),
            "feature_count": catalog_bank.get("feature_count"),
            "spine_readiness": catalog_bank.get("spine_readiness"),
        } if catalog_bank else None,
        "sample_matches": sample_matches,
    }


def _reference_graph_candidates(identifiers: list[str], *, country_scope: str = "") -> list[dict[str, Any]]:
    try:
        from .reference_graph import identify_aliases

        alias_rows = identify_aliases(identifiers, limit=max(100, len(identifiers) * 25))
    except Exception:
        alias_rows = []
    grouped: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for row in alias_rows:
        system = normalize_identifier_system(row.get("reference_system"))
        external_id = str(row.get("external_id") or "")
        loc_id = str(row.get("loc_id") or "")
        if country_scope and not (loc_id == country_scope or loc_id.startswith(country_scope + "-")):
            continue
        if system and external_id and loc_id:
            grouped[system][external_id].append(loc_id)
    return [
        _candidate(
            system=system,
            identifiers=identifiers,
            matches=dict(matches),
            method="reference_graph_exact_alias",
        )
        for system, matches in grouped.items()
    ]


def _invalid_identification_contract(*, code: str, message: str, reason: str, question_id: str, prompt: str, maps_to: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "invalid_request",
        "error": {"code": code, "message": message},
        "warnings": [{
            "code": "strict_input_contract",
            "message": "Translate natural language into the documented JSON shape before calling this tool; identifier values must remain strings so leading zeros survive.",
        }],
        "guidance": {
            "action": "translate_then_retry",
            "required_shape": {"identifiers": ["06073000100", "06073000201"]},
            "example_call": {
                "tool": "identify_reference_system",
                "arguments": {
                    "identifiers": ["06073000100", "06073000201"],
                    "expected": {"system": "us_census_geoid", "geo_level": "tract", "vintage": "2020"},
                    "country_scope": "USA",
                },
            },
        },
        "clarification": {
            "required": True,
            "reason": reason,
            "questions": [{
                "id": question_id,
                "prompt": prompt,
                "answer_schema": {"type": "array", "minItems": 1, "items": {"type": "string"}} if maps_to == "identifiers" else {"type": "string"},
                "maps_to": maps_to,
            }],
        },
    }


def identify_reference_system(
    identifiers: list[Any],
    *,
    expected: dict[str, Any] | None = None,
    country_scope: str | None = None,
    validation_scope: str = "sample",
) -> dict[str, Any]:
    """Rank maintained reference systems for a bounded identifier set."""
    if not isinstance(identifiers, list):
        return _invalid_identification_contract(
            code="invalid_identifiers_type",
            message="identifiers must be an array of strings, not prose or a comma-delimited string",
            reason="identifier_values_malformed",
            question_id="identifier_values",
            prompt="Provide the geography identifiers as a list of strings while preserving leading zeros.",
            maps_to="identifiers",
        )
    if any(not isinstance(value, str) for value in identifiers):
        return _invalid_identification_contract(
            code="identifier_strings_required",
            message="every identifier must be a string so leading zeros are preserved",
            reason="identifier_values_malformed",
            question_id="identifier_values",
            prompt="Provide the geography identifiers as strings, including any leading zeros.",
            maps_to="identifiers",
        )
    if expected is not None and not isinstance(expected, dict):
        return _invalid_identification_contract(
            code="invalid_expected_type",
            message="expected must be an object with optional system, geo_level, vintage, and country_scope fields",
            reason="expected_declaration_malformed",
            question_id="expected_declaration",
            prompt="What system, geography level, vintage, and country does the dataset declare?",
            maps_to="expected",
        )
    if validation_scope not in {"sample", "all_distinct_identifiers"}:
        return _invalid_identification_contract(
            code="invalid_validation_scope",
            message="validation_scope must be 'sample' or 'all_distinct_identifiers'",
            reason="validation_scope_malformed",
            question_id="validation_scope",
            prompt="Are these values a representative sample or every distinct identifier in the dataset?",
            maps_to="validation_scope",
        )
    values = list(dict.fromkeys(str(value).strip() for value in identifiers if str(value).strip()))
    if not values:
        return _invalid_identification_contract(
            code="identifiers_required",
            message="at least one non-empty identifier is required",
            reason="identifier_values_missing",
            question_id="identifier_values",
            prompt="Which column or values contain the geography identifiers? Provide a representative list while preserving leading zeros.",
            maps_to="identifiers",
        )
    expected = expected if isinstance(expected, dict) else {}
    expected_system = normalize_identifier_system(expected.get("system"))
    expected_level = _expected_level(expected.get("geo_level") or expected.get("admin_level"))
    expected_vintage = str(expected.get("vintage") or "").strip() or None
    country = str(country_scope or expected.get("country_scope") or "").strip().upper()

    candidates: list[dict[str, Any]] = []

    census_matches: dict[str, list[str]] = {}
    census_levels: dict[str, str] = {}
    if (not country or country == "USA") and (not expected_system or expected_system == US_CENSUS_GEOID_SYSTEM):
        for value in values:
            level = census_geoid_level(value)
            loc_id = census_geoid_to_loc_id(value)
            if loc_id and (not expected_level or level == expected_level):
                census_matches[value] = [loc_id]
                census_levels[value] = str(level)
        if census_matches:
            candidates.append(_candidate(
                system=US_CENSUS_GEOID_SYSTEM,
                identifiers=values,
                matches=census_matches,
                levels=census_levels,
                method="exact_identifier_crosswalk",
                expected_vintage=expected_vintage or "2020",
                country_scope=country or "USA",
            ))

    if not expected_system or expected_system == "daedalmap.loc_id":
        loc_matches = {
            value: [value.upper()]
            for value in values
            if re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+", value)
        }
        if loc_matches:
            candidates.append(_candidate(
                system="daedalmap.loc_id", identifiers=values, matches=loc_matches,
                method="loc_id_passthrough", country_scope=country,
            ))

    for system, prefix in (
        ("overlay_nws_public_zone", "USA-NWSZ-"),
        ("overlay_nws_fire_weather_zone", "USA-NWSFZ-"),
    ):
        if expected_system and expected_system != system:
            continue
        matches = {
            value: [prefix + value.upper()]
            for value in values
            if re.fullmatch(r"[A-Za-z]{2}Z\d{3}", value)
        }
        if matches:
            candidates.append(_candidate(
                system=system, identifiers=values, matches=matches,
                method="exact_identifier_lookup", country_scope=country or "USA",
            ))

    for candidate in _reference_graph_candidates(values, country_scope=country):
        if not expected_system or candidate["system"] == expected_system:
            candidates.append(candidate)

    # Merge duplicate systems while preferring the candidate with more exact
    # evidence. This can occur when a graph alias and a format adapter agree.
    by_system: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        prior = by_system.get(candidate["system"])
        if prior is None or (
            candidate["match_count"], candidate["geometry_available_count"]
        ) > (prior["match_count"], prior["geometry_available_count"]):
            by_system[candidate["system"]] = candidate
    candidates = list(by_system.values())
    candidates.sort(key=lambda item: (
        -float(item.get("match_rate") or 0),
        -int(item.get("geometry_available_count") or 0),
        int(item.get("ambiguous_identifier_count") or 0),
        str(item.get("system") or ""),
    ))

    # Only a vintage explicitly declared by the caller may disqualify an
    # otherwise exact identifier-system match. Census adapters use their
    # maintained vintage while looking up a geometry bank, but a temporarily
    # unavailable catalog entry must not make a five-digit county/ZCTA value
    # appear unambiguous and silently select the other system.
    vintage_is_constrained = expected_vintage is not None
    full_matches = [
        candidate for candidate in candidates
        if candidate.get("match_rate") == 1.0
        and (
            not vintage_is_constrained
            or candidate.get("expected_vintage_supported") is not False
        )
    ]
    if not candidates:
        status = "unmatched"
    elif expected_system:
        status = "matched" if candidates[0] in full_matches else "partial_match"
    elif len(full_matches) == 1:
        status = "matched"
    elif len(full_matches) > 1:
        status = "ambiguous"
    else:
        status = "partial_match"

    selected = candidates[0] if candidates and status == "matched" else None
    recommended_binding = None
    if selected:
        levels = selected.get("geo_levels") or []
        recommended_binding = {
            "mode": "reference",
            "system": selected["system"],
            "geo_level": levels[0] if len(levels) == 1 else expected_level,
            "vintage": expected_vintage or (
                "2020" if selected["system"] == US_CENSUS_GEOID_SYSTEM else None
            ),
            "country_scope": country or ("USA" if selected["system"] == US_CENSUS_GEOID_SYSTEM else None),
        }
    warnings: list[dict[str, Any]] = []
    guidance = None
    clarification = None
    if str(validation_scope or "sample") == "sample" and status in {"matched", "ambiguous", "partial_match"}:
        warnings.append({
            "code": "sample_validation_only",
            "message": "Only the supplied sample was checked. Use validation_scope='all_distinct_identifiers' with every distinct key before treating the binding as dataset-wide.",
        })
    if status == "ambiguous":
        choices = [
            {
                "value": candidate.get("system"),
                "label": str(candidate.get("system") or "").replace("_", " "),
                "geo_levels": candidate.get("geo_levels") or [],
                "match_rate": candidate.get("match_rate"),
                "geometry_available": candidate.get("geometry_available"),
            }
            for candidate in full_matches
        ]
        warnings.append({"code": "ambiguous_identifier_system", "message": "More than one maintained reference system matches every supplied identifier; no binding was selected."})
        guidance = {"action": "ask_user_then_retry", "message": "Ask which candidate system the dataset uses, then retry with expected.system (and level/vintage when known)."}
        clarification = {
            "required": True,
            "reason": "ambiguous_reference_system",
            "questions": [{
                "id": "reference_system",
                "prompt": "Which geography identifier system does this dataset use?",
                "answer_schema": {"type": "string", "enum": [choice["value"] for choice in choices]},
                "choices": choices,
                "maps_to": "expected.system",
            }],
            "retry": {
                "tool": "identify_reference_system",
                "base_arguments": {"identifiers": values, "country_scope": country or None, "validation_scope": validation_scope},
                "answer_mapping": {"reference_system": "expected.system"},
            },
        }
    elif status == "partial_match":
        vintage_conflict = any(candidate.get("expected_vintage_supported") is False for candidate in candidates)
        code = "expected_vintage_unavailable" if vintage_conflict else "partial_identifier_match"
        message = (
            "The identifiers match the declared system and level, but the requested vintage has no maintained matching geometry bank."
            if vintage_conflict else
            "Only part of the supplied identifier set matched the declared or detected system."
        )
        warnings.append({"code": code, "message": message})
        field = "vintage" if vintage_conflict else "reference_system"
        clarification = {
            "required": True,
            "reason": code,
            "questions": [{
                "id": field,
                "prompt": "What source vintage does the dataset use?" if vintage_conflict else "Do all rows use the same geography identifier system?",
                "answer_schema": {"type": "string" if vintage_conflict else "boolean"},
                "maps_to": "expected.vintage" if vintage_conflict else None,
            }],
        }
        guidance = {"action": "ask_user_then_retry", "message": message, "recommended_tool": "list_reference_systems" if vintage_conflict else "identify_reference_system"}
    elif status == "unmatched":
        code = "unknown_expected_system" if expected_system else "no_reference_system_match"
        warnings.append({
            "code": code,
            "message": "The expected.system value is not a supported canonical name or alias." if expected_system else "No maintained exact identifier system matched the supplied values.",
        })
        guidance = {
            "action": "inspect_contract_then_retry",
            "message": "Use list_reference_systems for canonical system names, or omit expected.system to detect from exact values.",
            "next_call": {"tool": "list_reference_systems", "arguments": {}},
            "accepted_examples": ["us_census_geoid", "daedalmap.loc_id", "overlay_zcta", "overlay_nws_public_zone", "overlay_nws_fire_weather_zone"],
        }
        clarification = {
            "required": True,
            "reason": code,
            "questions": [{
                "id": "reference_system_description",
                "prompt": "What organization, identifier system, geography level, and vintage produced these values?",
                "answer_schema": {"type": "string"},
                "maps_to": None,
            }],
        }

    return {
        "ok": status in {"matched", "ambiguous", "partial_match"},
        "status": status,
        "validation_scope": str(validation_scope or "sample"),
        "identifier_count": len(identifiers),
        "distinct_identifier_count": len(values),
        "expected": {
            "system": expected_system or None,
            "geo_level": expected_level,
            "vintage": expected_vintage,
            "country_scope": country or None,
        },
        "candidates": candidates,
        "recommended_binding": recommended_binding,
        "next_call": {
            "tool": "estimate_conversion_job",
            "arguments": {"geography_binding": recommended_binding},
        } if recommended_binding else None,
        "needed_context": ["system", "geo_level", "vintage"] if status == "ambiguous" else [],
        "warnings": warnings,
        "guidance": guidance,
        "clarification": clarification,
    }
