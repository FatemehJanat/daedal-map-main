"""Shared region-expansion helpers extracted from the executor."""

from __future__ import annotations


def expand_region(
    region: str,
    *,
    resolve_country_subdivision_slug_loc_id_func,
    regional_groups: dict[str, set[str]],
    load_conversions_func,
    load_iso_codes_func,
    load_usa_admin_func,
) -> set[str]:
    """Expand a region name to a set of country or loc_id prefixes."""
    if not region or region.lower() in ("global", "all", "world"):
        return set()

    subdivision_loc_id = resolve_country_subdivision_slug_loc_id_func(region)
    if subdivision_loc_id:
        return {subdivision_loc_id}

    normalized_region = str(region).strip().lower().replace("_", " ").replace("-", " ")
    if normalized_region in regional_groups:
        return set(regional_groups[normalized_region])
    if normalized_region in {"puerto rico", "puerto rico usa"}:
        return {"USA-PR"}

    if "-" in region and region.split("-")[0].isupper() and len(region.split("-")[0]) == 3:
        return {region}

    conversions = load_conversions_func()
    region_lower = region.lower()
    region_normalized = region_lower.replace("_", " ").replace("-", " ")

    region_aliases = conversions.get("region_aliases", {})
    for alias, grouping_key in region_aliases.items():
        alias_lower = alias.lower()
        if alias_lower == region_lower or alias_lower.replace("_", " ").replace("-", " ") == region_normalized:
            grouping = conversions.get("regional_groupings", {}).get(grouping_key, {})
            return set(grouping.get("countries", []))

    regional_groupings = conversions.get("regional_groupings", {})
    for key, grouping in regional_groupings.items():
        key_lower = key.lower()
        if key_lower == region_lower or key_lower.replace("_", " ").replace("-", " ") == region_normalized:
            return set(grouping.get("countries", []))

    iso_data = load_iso_codes_func()
    iso3_to_name = iso_data.get("iso3_to_name", {})
    for code, name in iso3_to_name.items():
        if name.lower() == region_lower:
            return {code}

    if region.upper() in iso3_to_name:
        return {region.upper()}

    usa_admin = load_usa_admin_func()
    state_abbrevs = usa_admin.get("state_abbreviations", {})
    for abbrev, name in state_abbrevs.items():
        if name.lower() == region_lower or abbrev.lower() == region_lower:
            return {f"USA-{abbrev}"}

    return set()
