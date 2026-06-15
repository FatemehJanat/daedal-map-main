"""Shared region-expansion helpers extracted from the executor."""

from __future__ import annotations

from mapmover.runtime.grid_loc_id_resolution import is_eez_loc_id, is_water_body_loc_id, load_water_body_codes


def _normalize_region_text(value: str | None) -> str:
    return str(value or "").strip().lower().replace("_", " ").replace("-", " ")


def _water_body_label_variants(label: str) -> set[str]:
    normalized = _normalize_region_text(label)
    variants = {normalized}
    for suffix in (" sea", " ocean", " waters"):
        if normalized.endswith(suffix):
            variants.add(normalized[: -len(suffix)].strip())
    return {value for value in variants if value}


def _resolve_country_waters(region: str, iso3_to_name: dict[str, str]) -> str | None:
    normalized = _normalize_region_text(region)
    stems = [normalized]

    if normalized.endswith("'s waters"):
        stems.append(normalized[: -len("'s waters")].strip())
    if normalized.endswith(" waters"):
        stems.append(normalized[: -len(" waters")].strip())
    if normalized.startswith("waters around "):
        stems.append(normalized[len("waters around ") :].strip())

    for stem in stems:
        if not stem:
            continue
        for code, name in iso3_to_name.items():
            if _normalize_region_text(name) == stem:
                return f"EEZ-{code}"
    return None


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

    region_text = str(region).strip()
    region_upper = region_text.upper()
    if is_water_body_loc_id(region_upper) or is_eez_loc_id(region_upper):
        return {region_upper}

    subdivision_loc_id = resolve_country_subdivision_slug_loc_id_func(region)
    if subdivision_loc_id:
        return {subdivision_loc_id}

    normalized_region = _normalize_region_text(region_text)
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

    water_body_codes = load_water_body_codes()
    for code, label in water_body_codes.items():
        if normalized_region in _water_body_label_variants(label):
            return {code}

    iso_data = load_iso_codes_func()
    iso3_to_name = iso_data.get("iso3_to_name", {})
    eez_loc_id = _resolve_country_waters(region_text, iso3_to_name)
    if eez_loc_id:
        return {eez_loc_id}
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
