"""Shared order-execution geography helpers."""

from __future__ import annotations

from mapmover.runtime.geography_reference import (
    derive_eurostat_geo_level as derive_eurostat_geo_level_impl,
    resolve_country_subdivision_slug_loc_id as resolve_country_subdivision_slug_loc_id_impl,
    resolve_us_county_slug_loc_id as resolve_us_county_slug_loc_id_impl,
)

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
    load_country_parquet_func=None,
):
    return resolve_us_county_slug_loc_id_impl(
        region,
        cache_dict=cache_dict,
        load_country_parquet_func=load_country_parquet_func,
    )


def resolve_country_subdivision_slug_loc_id(
    region: str,
    *,
    cache_dict: dict,
):
    return resolve_country_subdivision_slug_loc_id_impl(
        region,
        cache_dict=cache_dict,
    )


def derive_eurostat_geo_level(loc_id: str) -> str | None:
    return derive_eurostat_geo_level_impl(loc_id)


def expand_order_region(
    region: str,
    *,
    resolve_country_subdivision_slug_loc_id_func,
    load_conversions_func,
    load_iso_codes_func,
    load_usa_admin_func,
):
    from mapmover.runtime.region_expansion import expand_region as expand_region_impl

    return expand_region_impl(
        region,
        resolve_country_subdivision_slug_loc_id_func=resolve_country_subdivision_slug_loc_id_func,
        regional_groups=US_REGIONAL_GROUPS,
        load_conversions_func=load_conversions_func,
        load_iso_codes_func=load_iso_codes_func,
        load_usa_admin_func=load_usa_admin_func,
    )
