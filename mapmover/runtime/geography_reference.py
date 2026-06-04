from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..foundation_helpers import load_country_crosswalk, load_country_json_asset, load_reference_json

_BASE_DIR = Path(__file__).resolve().parent.parent
_CONVERSIONS_PATH = _BASE_DIR / "conversions.json"

_CONVERSIONS_CACHE: dict[str, Any] | None = None
_ISO_CODES_CACHE: dict[str, Any] | None = None
_USA_ADMIN_CACHE: dict[str, Any] | None = None
_COUNTRY_SUBDIVISION_SLUG_CACHE: dict[tuple[str, str], str | None] = {}

USA_COUNTY_EQUIVALENT_SUFFIXES = (
    " city and borough",
    " county",
    " parish",
    " borough",
    " census area",
    " municipality",
    " city",
)


def canonicalize_loc_id(loc_id: str) -> str:
    """Return runtime loc_ids in canonical form. Legacy formats are not normalized here."""
    return loc_id


def build_crosswalk_maps(crosswalk_data: dict[str, Any] | None) -> tuple[dict[str, str], dict[str, str]]:
    """
    Build local->geometry and geometry->preferred-local maps from crosswalk data.

    Includes:
    - admin_1 `mappings`
    - admin_2 FIPS bridge `admin_2_fips`
    """
    local_to_geo: dict[str, str] = {}
    geo_to_local: dict[str, str] = {}
    if not crosswalk_data:
        return local_to_geo, geo_to_local

    for local_loc_id, geo_loc_id in (crosswalk_data.get("mappings") or {}).items():
        local_norm = canonicalize_loc_id(local_loc_id)
        local_to_geo[local_norm] = geo_loc_id
        geo_to_local.setdefault(geo_loc_id, local_norm)

    for local_loc_id, geo_loc_id in (crosswalk_data.get("admin_2_fips") or {}).items():
        local_norm = canonicalize_loc_id(local_loc_id)
        local_to_geo[local_norm] = geo_loc_id
        geo_to_local.setdefault(geo_loc_id, local_norm)

    return local_to_geo, geo_to_local


def translate_loc_id_to_geometry_id(loc_id: str) -> str:
    """
    Translate a dataset loc_id into the geometry join id used by runtime geometry rows.

    - admin_1 local ids can map to GeoBoundaries G-IDs via `mappings`
    - admin_2 USA FIPS bridge ids can map via `admin_2_fips`
    - admin_3+ local ids stay local after canonicalization
    """
    canonical = canonicalize_loc_id(loc_id)
    if not isinstance(canonical, str) or "-" not in canonical:
        return canonical

    iso3 = canonical.split("-", 1)[0]
    crosswalk = load_country_crosswalk(iso3)
    local_to_geo, _ = build_crosswalk_maps(crosswalk)
    direct = local_to_geo.get(canonical)
    if direct:
        return direct

    if iso3 == "USA":
        parts = canonical.split("-")
        if len(parts) == 3 and parts[2].isdigit() and len(parts[2]) > 3:
            county_only = f"{parts[0]}-{parts[1]}-{parts[2][-3:]}"
            bridged = local_to_geo.get(county_only)
            if bridged:
                return bridged

    return canonical


def translate_geometry_id_to_local_id(loc_id: str) -> str:
    """
    Translate a geometry-side loc_id back to its preferred local/canonical id.
    """
    canonical = canonicalize_loc_id(loc_id)
    if not isinstance(canonical, str) or "-" not in canonical:
        return canonical

    iso3 = canonical.split("-", 1)[0]
    crosswalk = load_country_crosswalk(iso3)
    _, geo_to_local = build_crosswalk_maps(crosswalk)
    return geo_to_local.get(canonical, canonical)


def load_conversions() -> dict[str, Any]:
    """Load shared regional grouping and alias helpers from conversions.json."""
    global _CONVERSIONS_CACHE
    if _CONVERSIONS_CACHE is not None:
        return _CONVERSIONS_CACHE

    if not _CONVERSIONS_PATH.exists():
        _CONVERSIONS_CACHE = {}
        return _CONVERSIONS_CACHE

    with open(_CONVERSIONS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    _CONVERSIONS_CACHE = data if isinstance(data, dict) else {}
    return _CONVERSIONS_CACHE


def load_iso_codes() -> dict[str, Any]:
    """Load shared ISO code helpers from reference/iso_codes.json."""
    global _ISO_CODES_CACHE
    if _ISO_CODES_CACHE is not None:
        return _ISO_CODES_CACHE

    data = load_reference_json("iso_codes.json")
    _ISO_CODES_CACHE = data if isinstance(data, dict) else {}
    return _ISO_CODES_CACHE


def load_usa_admin() -> dict[str, Any]:
    """Load shared USA admin helpers from reference/usa/usa_admin.json."""
    global _USA_ADMIN_CACHE
    if _USA_ADMIN_CACHE is not None:
        return _USA_ADMIN_CACHE

    data = load_reference_json("usa/usa_admin.json")
    _USA_ADMIN_CACHE = data if isinstance(data, dict) else {}
    return _USA_ADMIN_CACHE


def normalize_subdivision_slug(value: str, *, strip_suffixes: tuple[str, ...] = ()) -> str:
    """Normalize a user-facing subdivision slug to a stable lookup key."""
    text = str(value or "").strip().lower()
    text = text.replace("-", " ").replace("_", " ")
    text = re.sub(r"[^\w\s]+", " ", text)
    text = " ".join(text.split())
    for suffix in strip_suffixes:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return " ".join(text.split())


def normalize_county_slug(value: str) -> str:
    """Normalize US county/parish/borough-style slug text for lookup."""
    return normalize_subdivision_slug(value, strip_suffixes=USA_COUNTY_EQUIVALENT_SUFFIXES)


def _country_subdivision_lookup_candidates(region: str) -> list[str]:
    value = str(region or "").strip()
    if not value:
        return []

    raw_key = value.lower()
    parts = [segment for segment in value.split("-") if segment]
    candidates = [raw_key]
    if len(parts) < 3:
        return candidates

    prefix = "-".join(parts[:2]).lower()
    slug = "-".join(parts[2:])
    normalized_slug = normalize_subdivision_slug(slug).replace(" ", "-")
    if normalized_slug:
        normalized_key = f"{prefix}-{normalized_slug}"
        if normalized_key not in candidates:
            candidates.append(normalized_key)
    return candidates


def resolve_country_subdivision_slug_loc_id(
    region: str,
    *,
    cache_dict: dict[tuple[str, str], str | None] | None = None,
) -> str | None:
    """Resolve `ISO3-parent-slug` subdivision aliases via country-owned reference data."""
    value = str(region or "").strip()
    match = re.fullmatch(r"([A-Z]{3})-([A-Za-z0-9]+)-([A-Za-z0-9._-]+)", value)
    if not match:
        return None

    iso3 = match.group(1)
    target_cache = cache_dict if cache_dict is not None else _COUNTRY_SUBDIVISION_SLUG_CACHE
    cache_key = (iso3, value.lower())
    if cache_key in target_cache:
        return target_cache[cache_key]

    alias_asset = load_country_json_asset(iso3, "subdivision_slug_aliases.json")
    if not isinstance(alias_asset, dict):
        return None

    aliases = alias_asset.get("aliases")
    if not isinstance(aliases, dict) or not aliases:
        return None

    for candidate in _country_subdivision_lookup_candidates(value):
        loc_id = aliases.get(candidate)
        if isinstance(loc_id, str) and loc_id:
            target_cache[cache_key] = loc_id
            return loc_id

    target_cache[cache_key] = None
    return None


def resolve_us_county_slug_loc_id(
    region: str,
    *,
    load_country_parquet_func=None,
    cache_dict: dict[tuple[str, str], str | None] | None = None,
) -> str | None:
    """Compatibility wrapper for the shared country subdivision slug resolver."""
    return resolve_country_subdivision_slug_loc_id(region, cache_dict=cache_dict)

