"""Shared order-execution geography helpers."""

from __future__ import annotations


US_REGIONAL_GROUPS = {
    "usa west": {"USA-AZ", "USA-CA", "USA-CO", "USA-ID", "USA-MT", "USA-NM", "USA-NV", "USA-OR", "USA-UT", "USA-WA", "USA-WY"},
    "western us": {"USA-AZ", "USA-CA", "USA-CO", "USA-ID", "USA-MT", "USA-NM", "USA-NV", "USA-OR", "USA-UT", "USA-WA", "USA-WY"},
    "western u.s.": {"USA-AZ", "USA-CA", "USA-CO", "USA-ID", "USA-MT", "USA-NM", "USA-NV", "USA-OR", "USA-UT", "USA-WA", "USA-WY"},
    "western united states": {"USA-AZ", "USA-CA", "USA-CO", "USA-ID", "USA-MT", "USA-NM", "USA-NV", "USA-OR", "USA-UT", "USA-WA", "USA-WY"},
}


def resolve_us_county_slug_loc_id(
    region: str,
    *,
    cache_dict: dict,
    load_country_parquet_func,
):
    from mapmover.runtime.region_expansion import resolve_us_county_slug_loc_id as resolve_us_county_slug_loc_id_impl

    return resolve_us_county_slug_loc_id_impl(
        region,
        cache_dict=cache_dict,
        load_country_parquet_func=load_country_parquet_func,
    )


def derive_eurostat_geo_level(loc_id: str) -> str | None:
    """Infer NUTS admin level from Eurostat loc_id shape."""
    if not loc_id:
        return None
    text = str(loc_id).strip()
    if "-" not in text:
        return "admin_0" if len(text) == 3 else None
    suffix = text.split("-", 1)[1]
    code_len = len(suffix)
    if code_len == 3:
        return "admin_1"
    if code_len == 4:
        return "admin_2"
    if code_len == 5:
        return "admin_3"
    return None


def expand_order_region(
    region: str,
    *,
    resolve_us_county_slug_loc_id_func,
    load_conversions_func,
    load_iso_codes_func,
    load_usa_admin_func,
):
    from mapmover.runtime.region_expansion import expand_region as expand_region_impl

    return expand_region_impl(
        region,
        resolve_us_county_slug_loc_id_func=resolve_us_county_slug_loc_id_func,
        regional_groups=US_REGIONAL_GROUPS,
        load_conversions_func=load_conversions_func,
        load_iso_codes_func=load_iso_codes_func,
        load_usa_admin_func=load_usa_admin_func,
    )
