from __future__ import annotations

# Shared structured registry for the live agent/API/MCP pack set.
# This is the intended single authored source for:
# - published pack order
# - free vs paid pricing lane
# - MCP facade metadata
# - public display names
# - preferred MCP routing hints
#
# Keep this module stdlib-only so runtime, site, stdio, and helper scripts can
# import it safely.

PACK_REGISTRY: dict[str, dict] = {
    "currency": {
        "display_name": "currency",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "get_fx_rates"),
        "mcp_prompt_allowlist": ("fx_history_for_country",),
        "mcp_name": "com.daedalmap/currency",
        "mcp_title": "DaedalMap Historical FX Rates",
        "mcp_description": "Historical daily FX rates for 100+ currencies normalized to USD, from 1940 to present. Free - no payment required. Supports daily, weekly, and monthly granularity.",
        "registry_meta": {
            "categories": ["economics", "data", "geospatial"],
            "highlights": [
                "Historical foreign exchange rate comparisons",
                "Country-level FX lookups tied to DaedalMap loc_id geography",
                "Free structured MCP access for historical currency data",
            ],
        },
        "routing": {
            "preferred_tool": "get_fx_rates",
        },
    },
    "earthquakes": {
        "display_name": "earthquakes",
        "pricing": "paid_x402_base_usdc",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "get_earthquake_events", "get_live_earthquake_events"),
        "mcp_prompt_allowlist": ("largest_earthquake_in_range", "count_disaster_events"),
        "mcp_name": "com.daedalmap/earthquakes",
        "mcp_title": "DaedalMap Earthquake Data",
        "mcp_description": "Historical earthquake events from 2150 BC to present. Paid via x402 on Base mainnet USDC. Small queries stay cheap; very broad scans cost more or need narrower filters. Call unpaid first to see the exact price before committing.",
        "registry_meta": {
            "categories": ["hazard", "geospatial", "data"],
            "highlights": [
                "Historical earthquake event data with structured filters",
                "Paid MCP access for earthquake counts and event rows",
                "Country and region lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "get_earthquake_events",
            "live_fallback_tool": "get_live_earthquake_events",
            "live_fallback_when": "Only when the caller explicitly asks for live/preliminary upstream data or needs time beyond canonical_available_through.",
        },
    },
    "floods": {
        "display_name": "floods",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_prompt_allowlist": ("count_disaster_events",),
        "mcp_name": "com.daedalmap/floods",
        "mcp_title": "DaedalMap Flood Events",
        "mcp_description": "Global large flood events from 1985 to present from the Dartmouth Flood Observatory Global Flood Records (CC0 public domain), including flood extent polygons, fatalities, displaced, severity, main cause, and a flood impact index, plus MODIS satellite-mapped extents from the Global Flood Database. Free - no payment required.",
        "registry_meta": {
            "categories": ["hazard", "geospatial", "data"],
            "highlights": [
                "Global flood event records 1985-present with extent polygons",
                "Free MCP access for flood counts, fatalities, displaced, and severity",
                "Country and region lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "hurricanes": {
        "display_name": "hurricanes",
        "pricing": "paid_x402_base_usdc",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_prompt_allowlist": ("count_disaster_events",),
        "mcp_name": "com.daedalmap/hurricanes",
        "mcp_title": "DaedalMap Hurricane and Tropical Cyclone Data",
        "mcp_description": "Global tropical cyclone tracks from IBTrACS, 1842-present. Wind, pressure, and paths. Paid via x402 on Base mainnet USDC. Small queries stay cheap; very broad scans cost more or need narrower filters. Call unpaid first to see the exact price before committing.",
        "registry_meta": {
            "categories": ["hazard", "geospatial", "data"],
            "highlights": [
                "Global tropical cyclone and hurricane track records",
                "Paid MCP access for hurricane and cyclone event queries",
                "Country and basin lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "tornadoes": {
        "display_name": "tornadoes",
        "pricing": "paid_x402_base_usdc",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_prompt_allowlist": ("count_disaster_events",),
        "mcp_name": "com.daedalmap/tornadoes",
        "mcp_title": "DaedalMap Tornado Events",
        "mcp_description": "United States tornado events from 1950 to present from the NOAA Storm Prediction Center, including track paths, EF/Fujita intensity ratings, casualties, and damage estimates. Paid via x402 on Base mainnet USDC. Small queries stay cheap; very broad scans cost more or need narrower filters. Call unpaid first to see the exact price before committing.",
        "registry_meta": {
            "categories": ["hazard", "geospatial", "data"],
            "highlights": [
                "US tornado event records 1950-present with track paths and intensity",
                "Paid MCP access for tornado counts, casualties, and damage estimates",
                "State and region lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "tsunamis": {
        "display_name": "tsunamis",
        "pricing": "paid_x402_base_usdc",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "get_tsunami_events"),
        "mcp_prompt_allowlist": ("count_disaster_events",),
        "mcp_name": "com.daedalmap/tsunamis",
        "mcp_title": "DaedalMap Tsunami Data",
        "mcp_description": "Historical tsunami events from 2000 BC to present. Paid via x402 on Base mainnet USDC. Small queries stay cheap; very broad scans cost more or need narrower filters. Call unpaid first to see the exact price before committing.",
        "registry_meta": {
            "categories": ["hazard", "geospatial", "data"],
            "highlights": [
                "Historical tsunami event data and wave-height metrics",
                "Paid MCP access for tsunami counts and event rows",
                "Country and coastal-region lookups tied to DaedalMap geography",
            ],
        },
        "routing": {
            "preferred_tool": "get_tsunami_events",
        },
    },
    "un_sdg": {
        "display_name": "UN SDG",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/un_sdg",
        "mcp_title": "DaedalMap UN Sustainable Development Goals",
        "mcp_description": "UN SDG country indicators across all 17 goals: poverty, health, education, climate. Free.",
        "registry_meta": {
            "categories": ["development", "data", "geospatial"],
            "highlights": [
                "210 UN SDG indicators across all 17 goals",
                "Free MCP access for development and social metrics",
                "Country-level lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "volcanoes": {
        "display_name": "volcanoes",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "get_volcanic_activity", "get_live_volcano_events"),
        "mcp_prompt_allowlist": ("count_disaster_events",),
        "mcp_name": "com.daedalmap/volcanoes",
        "mcp_title": "DaedalMap Volcanic Activity",
        "mcp_description": "Historical volcanic eruption records from Holocene to present, including VEI and location data. Free - no payment required.",
        "registry_meta": {
            "categories": ["hazard", "geospatial", "data"],
            "highlights": [
                "Historical volcanic eruption records and VEI data",
                "Free MCP access for volcanic activity queries",
                "Country and region lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "get_volcanic_activity",
            "live_fallback_tool": "get_live_volcano_events",
            "live_fallback_when": "Only when the caller explicitly asks for live/preliminary upstream data or needs time beyond canonical_available_through.",
        },
    },
    "world_factbook": {
        "display_name": "World Factbook",
        "pricing": "paid_x402_base_usdc",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/world_factbook",
        "mcp_title": "DaedalMap CIA World Factbook",
        "mcp_description": "CIA World Factbook country indicators for infrastructure, energy, demographics, and economy. Paid via x402 on Base mainnet USDC. Small queries stay cheap; very broad scans cost more or need narrower filters. Call unpaid first to see the exact price before committing.",
        "registry_meta": {
            "categories": ["economic", "data", "geospatial"],
            "highlights": [
                "111 CIA World Factbook indicators from 2002-2026 editions",
                "Paid MCP access for country infrastructure and economy metrics",
                "Country-level lookups tied to DaedalMap loc_id geography",
            ],
        },
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "worldpop": {
        "display_name": "WorldPop",
        "pricing": "paid_x402_base_usdc",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "query_dataset"),
        "mcp_name": "com.daedalmap/population",
        "mcp_title": "DaedalMap Population Estimates",
        "mcp_description": "Global population estimates from WorldPop, 2000-2030, at country and sub-national admin levels. Source: WorldPop (CC-BY 4.0). Paid via x402 on Base mainnet USDC. Small queries stay cheap; very broad scans cost more or need narrower filters. Call unpaid first to see the exact price before committing.",
        "registry_meta": {
            "categories": ["demographic", "data", "geospatial"],
            "highlights": [
                "WorldPop population estimates across multiple admin levels",
                "Paid MCP access for country and sub-national population queries",
                "Country and regional lookups tied to DaedalMap loc_id geography",
            ],
        },
        "registry_search_alias": "population",
        "routing": {
            "preferred_tool": "query_dataset",
        },
    },
    "geography": {
        "display_name": "Geography Tools",
        "kind": "tool_family",
        "pricing": "free",
        "mcp_tool_allowlist": ("get_catalog", "get_pack", "resolve_point", "get_boundary", "loc_id_hierarchy", "loc_id_info"),
        "mcp_name": "com.daedalmap/geocoding",
        "mcp_title": "DaedalMap Geocoding and Reverse Geocoding (loc_id)",
        "mcp_description": "Free geocoding and reverse-geocoding utilities built on the DaedalMap loc_id spine: resolve latitude/longitude to administrative areas, fetch boundaries and bounding boxes, and walk the loc_id hierarchy. A utility tool family, not a queryable dataset pack. No payment required.",
        "registry_meta": {
            "categories": ["geospatial", "geocoding", "data"],
            "highlights": [
                "Reverse geocoding: latitude/longitude to administrative loc_id chain",
                "Boundary and bounding-box lookup for any loc_id",
                "Walk the loc_id hierarchy up and down to clip to any admin level",
            ],
        },
        "routing": {
            "preferred_tool": "resolve_point",
        },
        "tool_summaries": (
            {"name": "resolve_point", "summary": "lat/lon -> deepest loc_id plus the full ancestor chain"},
            {"name": "get_boundary", "summary": "loc_id -> bounding box and centroid (optional full polygon)"},
            {"name": "loc_id_hierarchy", "summary": "loc_id -> parent, ancestors, and child summary"},
            {"name": "loc_id_info", "summary": "loc_id -> name, admin level, centroid, bbox, child counts"},
        ),
    },
}


def pack_kind(pack_id: str | None) -> str:
    profile = PACK_REGISTRY.get(str(pack_id or "").strip()) or {}
    return str(profile.get("kind") or "data_pack")


def published_pack_ids() -> tuple[str, ...]:
    # Data packs only. Tool families (e.g. geography) are listed separately via
    # tool_family_ids() so existing pack/catalog/llms surfaces stay unchanged.
    return tuple(pid for pid, p in PACK_REGISTRY.items() if str(p.get("kind") or "data_pack") == "data_pack")


def tool_family_ids() -> tuple[str, ...]:
    return tuple(pid for pid, p in PACK_REGISTRY.items() if str(p.get("kind") or "data_pack") == "tool_family")


def tool_family_catalog_entry(pack_id: str | None) -> dict:
    normalized = str(pack_id or "").strip()
    profile = PACK_REGISTRY.get(normalized) or {}
    pricing = str(profile.get("pricing") or "free")
    return {
        "pack_id": normalized,
        "kind": "tool_family",
        "display_name": str(profile.get("display_name") or normalized.replace("_", " ")),
        "title": profile.get("mcp_title"),
        "description": profile.get("mcp_description"),
        "pricing": pricing,
        "paid_data_calls": pricing != "free",
        "tools": [dict(tool) for tool in (profile.get("tool_summaries") or ())],
    }


def tool_family_pack_detail(pack_id: str | None) -> dict:
    normalized = str(pack_id or "").strip()
    profile = PACK_REGISTRY.get(normalized) or {}
    entry = tool_family_catalog_entry(normalized)
    entry["mcp"] = {"name": profile.get("mcp_name"), "facade_url": f"/mcp/{normalized}"}
    entry["registry_meta"] = dict(profile.get("registry_meta") or {})
    entry["routing"] = dict(profile.get("routing") or {})
    entry["notes"] = (
        "Utility tool family on the DaedalMap loc_id spine. Free, and not a queryable "
        "dataset pack - call the listed tools directly rather than query_dataset."
    )
    return entry


def free_pack_ids() -> tuple[str, ...]:
    return tuple(pack_id for pack_id, profile in PACK_REGISTRY.items() if str(profile.get("pricing") or "") == "free")


def paid_pack_ids() -> tuple[str, ...]:
    return tuple(pack_id for pack_id, profile in PACK_REGISTRY.items() if str(profile.get("pricing") or "") != "free")


def pack_profile(pack_id: str | None) -> dict:
    normalized = str(pack_id or "").strip()
    return dict(PACK_REGISTRY.get(normalized) or {})


def pack_display_name(pack_id: str | None) -> str:
    normalized = str(pack_id or "").strip()
    profile = PACK_REGISTRY.get(normalized) or {}
    return str(profile.get("display_name") or normalized.replace("_", " "))


def pack_registry_alias(pack_id: str | None) -> str | None:
    normalized = str(pack_id or "").strip()
    profile = PACK_REGISTRY.get(normalized) or {}
    alias = str(profile.get("registry_search_alias") or "").strip()
    return alias or None


def pack_mcp_server_profile(pack_id: str | None) -> dict:
    normalized = str(pack_id or "").strip()
    profile = PACK_REGISTRY.get(normalized) or {}
    return {
        "name": profile.get("mcp_name"),
        "title": profile.get("mcp_title"),
        "description": profile.get("mcp_description"),
        "pricing": profile.get("pricing"),
        "registry_meta": dict(profile.get("registry_meta") or {}),
    }


def pack_routing_hints() -> dict[str, dict[str, str]]:
    hints: dict[str, dict[str, str]] = {}
    for pack_id, profile in PACK_REGISTRY.items():
        routing = profile.get("routing")
        if isinstance(routing, dict) and routing:
            hints[pack_id] = dict(routing)
    return hints


def pack_tool_allowlists() -> dict[str, set[str]]:
    allowlists: dict[str, set[str]] = {}
    for pack_id, profile in PACK_REGISTRY.items():
        raw = profile.get("mcp_tool_allowlist") or ()
        allowlists[pack_id] = {str(tool) for tool in raw if str(tool).strip()}
    return allowlists


def pack_prompt_allowlists() -> dict[str, set[str]]:
    allowlists: dict[str, set[str]] = {}
    for pack_id, profile in PACK_REGISTRY.items():
        raw = profile.get("mcp_prompt_allowlist") or ()
        allowlists[pack_id] = {str(prompt) for prompt in raw if str(prompt).strip()}
    return allowlists
