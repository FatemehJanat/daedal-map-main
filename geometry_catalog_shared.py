"""Pure projections shared by geometry catalog builders and consumers.

The generated ``geometry/geometry_catalog.json`` is the capability authority.
This module contains only deterministic projections of that document so build,
runtime, and website code do not maintain parallel country lists or depth
claims.
"""

from __future__ import annotations

from typing import Any


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _country_code(value: Any) -> str:
    return str(value or "").strip().upper()


def public_geometry_catalog_records(catalog: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Return admitted/current records without exposing internal release lanes."""
    hidden_states = {
        "blocked", "candidate", "candidate_blocked", "in_preparation",
        "preparing", "researching", "wip",
    }
    rows = []
    for item in catalog.get(key) or []:
        if not isinstance(item, dict):
            continue
        states = {
            str(item.get(field) or "").strip().lower()
            for field in ("status", "release_state", "publication_status")
            if str(item.get(field) or "").strip()
        }
        has_hidden_candidate = any(
            state.startswith("candidate") and state not in {"candidate_pass", "candidate_published"}
            for state in states
        )
        if states & hidden_states or has_hidden_candidate or any("blocked" in state for state in states):
            continue
        public_item = dict(item)
        if key == "country_profiles":
            for field in (
                "release_status", "release_id", "graph_release_id",
                "candidate_state", "publication_status", "runtime_state",
                "profile_required", "active_runtime_unchanged",
            ):
                public_item.pop(field, None)
            public_item["qa_highlights"] = [
                str(value).replace("adopted local ", "maintained ").replace("local Census", "Census")
                for value in (item.get("qa_highlights") or [])
                if "candidate" not in str(value).lower()
                and "unpublished" not in str(value).lower()
            ]
            public_item["family_coverage"] = [
                {
                    field: value
                    for field, value in family.items()
                    if field not in {"state", "included", "implementation_ids", "source_ids"}
                }
                for family in (item.get("family_coverage") or [])
                if isinstance(family, dict) and family.get("available") is True
            ]
            public_item["package_recipes"] = [
                dict(recipe)
                for recipe in (item.get("package_recipes") or [])
                if isinstance(recipe, dict) and recipe.get("download_available") is True
            ]
        elif key == "country_family_coverage":
            public_item = {
                field: value
                for field, value in public_item.items()
                if not field.startswith("candidate_")
                and field not in {
                    "release_status", "release_id", "graph_release_id",
                    "publication_status", "runtime_state", "profile_required",
                    "active_runtime_unchanged",
                }
            }
        rows.append(public_item)
    return rows


def build_geometry_capability_summary(catalog: dict[str, Any]) -> dict[str, Any]:
    """Return the public global-baseline plus country-enrichment contract."""
    baseline_rows = [
        item for item in (catalog.get("global_admin_baseline") or [])
        if isinstance(item, dict) and _country_code(item.get("country_code"))
    ]
    baseline_depth_by_country = {
        _country_code(item.get("country_code")): _as_int(item.get("max_admin_level"))
        for item in baseline_rows
    }
    depth_counts: dict[str, int] = {}
    for depth in baseline_depth_by_country.values():
        key = "unknown" if depth is None else str(depth)
        depth_counts[key] = depth_counts.get(key, 0) + 1
    known_depths = [value for value in baseline_depth_by_country.values() if value is not None]

    profiles = {
        _country_code(item.get("country_code")): item
        for item in (catalog.get("country_profiles") or [])
        if isinstance(item, dict) and _country_code(item.get("country_code"))
    }
    enhanced: list[dict[str, Any]] = []
    for item in catalog.get("country_family_coverage") or []:
        if not isinstance(item, dict):
            continue
        code = _country_code(item.get("country_code"))
        if not code or code == "GLOBAL":
            continue
        active_depth = _as_int(item.get("active_admin_depth"))
        if active_depth is None:
            active_depth = _as_int(item.get("max_admin_level"))
        baseline_depth = baseline_depth_by_country.get(code)
        if active_depth is None:
            active_depth = baseline_depth
        family_ids = sorted({
            str(value).strip()
            for value in (item.get("available_family_ids") or [])
            if str(value).strip()
        })
        added_families = [value for value in family_ids if value != "administrative"]
        reasons = []
        if active_depth is not None and (baseline_depth is None or active_depth > baseline_depth):
            reasons.append("deeper_admin_spine")
        if added_families:
            reasons.append("additional_reference_families")
        profile = profiles.get(code) or {}
        row = {
            "country_code": code,
            "label": item.get("label") or profile.get("label") or code,
            "baseline_admin_depth": baseline_depth,
            "active_admin_depth": active_depth,
            "available_family_ids": family_ids,
            "enrichment_reasons": reasons,
            "profile_id": profile.get("profile_id"),
            "release_status": profile.get("release_status"),
        }
        if reasons:
            enhanced.append(row)

    enhanced.sort(key=lambda item: (str(item.get("label") or ""), item["country_code"]))
    baseline_max = max(known_depths) if known_depths else None
    enhanced_labels = [str(item.get("label") or item["country_code"]) for item in enhanced]
    baseline_phrase = f"a cataloged baseline of {len(baseline_rows)} geographic entities"
    if baseline_max is not None:
        baseline_phrase += f", reaching up to Admin {baseline_max}"
    enrichment_phrase = (
        f" Additional detail is currently available for {', '.join(enhanced_labels)}."
        if enhanced_labels else ""
    )
    return {
        "model": "global_baseline_plus_catalog_admitted_country_enrichment",
        "public_claim": (
            f"The same geography tools work worldwide across {baseline_phrase}. Where additional "
            f"country releases are available, the same calls automatically return deeper administrative "
            f"tiers or maintained reference families.{enrichment_phrase}"
        ),
        "global_baseline": {
            "geographic_entity_count": len(baseline_rows),
            "max_admin_depth": baseline_max,
            "depth_counts": depth_counts,
        },
        "enhanced_country_count": len(enhanced),
        "enhanced_country_codes": [item["country_code"] for item in enhanced],
        "enhanced_countries": enhanced,
    }
