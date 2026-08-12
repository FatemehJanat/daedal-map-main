"""Authored source of truth for per-tool access gates.

This is the tool-level twin of ``pack_registry_shared.PACK_REGISTRY``. Pack
pricing answers "is this dataset paid?"; this answers "how much of this tool can
one caller use for free, and what does paying buy?".

Three product rules this file encodes:

1. **Downloads and samples stay free.** Nothing here gates static downloads or
   sample data. These limits only apply to hosted MCP/API execution.
2. **Paying buys throughput, not data.** A ``paid_bulk`` tool returns the same
   answer to everyone; a paid caller may simply ask for more per call. There is
   no paid-only field, row, or region.
3. **License permission is the ceiling.** A tool may only be ``paid_bulk`` when
   the geometry banks or packs behind it carry ``permission: "paid"``. If the
   upstream license forbids paid hosted service, the tool stays free no matter
   what is authored here. See ``licensing_permits_paid_bulk``.

To change a limit: edit ``free_item_limit`` / ``paid_item_limit`` here.
To swap a tool between free and paid: change ``pricing`` here, and nothing else.

Env vars still override at runtime for incident response and load testing:
``MCP_TOOL_BATCH_LIMIT_<TOOL_NAME>`` first, then the legacy compatibility names
listed per tool, then the value authored here.

Full free<->paid checklist (enforcement, advertised pricing, license, public
docs, catalog surfaces):
county-map-private/docs/future/API/mcp_publishing.md section 15.
"""

from __future__ import annotations


# Only pricing values starting with "paid" are enforced as paid, matching the
# pack registry convention. Default is free.
PRICING_FREE = "free"
PRICING_PAID_BULK = "paid_bulk_x402_base_usdc"

# Tool families. "geography" is the geometry/loc_id utility family; "discovery"
# is the free catalog/helper surface; "dataset" tools price through the pack
# registry instead of here.
FAMILY_GEOGRAPHY = "geography"
FAMILY_DISCOVERY = "discovery"
FAMILY_DATASET = "dataset"


TOOL_ACCESS_REGISTRY: dict[str, dict] = {
    "get_tool_help": {
        "family": FAMILY_DISCOVERY,
        "capability_id": "tool_help_discovery",
        "pricing": PRICING_FREE,
        "notes": "Blind-caller help must stay free on every facade.",
    },
    # ---- geography: bulk-capable, licence-eligible for paid throughput ----
    "resolve_point": {
        "family": FAMILY_GEOGRAPHY,
        "capability_id": "point_lookup",
        "pricing": PRICING_PAID_BULK,
        "item_field": "points",
        "free_item_limit": 25,
        "paid_item_limit": 10000,
        "legacy_limit_env": ("POINT_LOOKUP_BATCH_LIMIT",),
        "legacy_paid_limit_env": ("POINT_LOOKUP_PAID_BATCH_LIMIT",),
    },
    "check_geometry": {
        "family": FAMILY_GEOGRAPHY,
        "capability_id": "geometry_availability",
        "pricing": PRICING_FREE,
        "item_field": "loc_ids",
        "free_item_limit": 1000,
        "paid_item_limit": 25000,
        "legacy_limit_env": ("GEOMETRY_CHECK_BATCH_LIMIT",),
    },
    "get_geometry": {
        "family": FAMILY_GEOGRAPHY,
        "capability_id": "geometry_lookup",
        "pricing": PRICING_FREE,
        "item_field": "loc_ids",
        "free_item_limit": 1000,
        "paid_item_limit": 25000,
        # Polygons are payload-heavy, so they carry their own tighter cap.
        "polygon_item_limit_env": "MCP_TOOL_POLYGON_BATCH_LIMIT_GET_GEOMETRY",
        "legacy_limit_env": ("GEOMETRY_GET_BATCH_LIMIT",),
    },
    "loc_id_info": {
        "family": FAMILY_GEOGRAPHY,
        "capability_id": "loc_id_metadata",
        "pricing": PRICING_FREE,
        "item_field": "loc_ids",
        "free_item_limit": 100,
        "paid_item_limit": 2500,
        "legacy_limit_env": ("LOC_ID_INFO_BATCH_LIMIT",),
        # include_references fans out across bridge artifacts, so it is capped
        # lower than plain metadata enrichment.
        "sub_limits": {
            "references": {
                "free_item_limit": 25,
                "limit_env": "MCP_TOOL_REFERENCES_BATCH_LIMIT_LOC_ID_INFO",
                "legacy_limit_env": ("LOC_ID_INFO_REFERENCES_BATCH_LIMIT",),
            },
        },
    },
    "resolve_reference": {
        "family": FAMILY_GEOGRAPHY,
        "capability_id": "reference_resolution",
        "pricing": PRICING_FREE,
        "item_field": "items",
        "free_item_limit": 100,
        "paid_item_limit": 2500,
        "legacy_limit_env": ("REFERENCE_RESOLVE_BATCH_LIMIT",),
    },
    "convert_reference": {
        "family": FAMILY_GEOGRAPHY,
        "capability_id": "reference_conversion",
        "pricing": PRICING_FREE,
        "item_field": "items",
        "free_item_limit": 100,
        "paid_item_limit": 2500,
        "legacy_limit_env": ("REFERENCE_CONVERT_BATCH_LIMIT",),
    },
    "compare_geographies": {
        "family": FAMILY_GEOGRAPHY,
        "capability_id": "geography_comparison",
        "pricing": PRICING_FREE,
        "item_field": "items",
        "free_item_limit": 100,
        "paid_item_limit": 2500,
    },
    "resolve_loc_id_scope": {
        "family": FAMILY_GEOGRAPHY,
        "capability_id": "loc_id_scope",
        "pricing": PRICING_FREE,
        "item_field": "limit",
        "free_item_limit": 100,
        "paid_item_limit": 5000,
        "trusted_item_limit": 100000,
        "trusted_limit_env": "MCP_TOOL_TRUSTED_BATCH_LIMIT_RESOLVE_LOC_ID_SCOPE",
        "legacy_limit_env": ("LOC_ID_SCOPE_LIMIT",),
    },
    # ---- geography: quote/execute pair. The limit selects inline vs queued
    # execution rather than rejecting the call, so there is no paid item cap.
    "estimate_geometry_package": {
        "family": FAMILY_GEOGRAPHY,
        "capability_id": "geometry_package_estimate",
        "pricing": PRICING_FREE,
        "notes": "Quotes must stay free; this is the measurable boundary before any charge.",
    },
    "create_geometry_export": {
        "family": FAMILY_GEOGRAPHY,
        "capability_id": "geometry_export",
        "pricing": PRICING_FREE,
        "inline_item_limit": 10,
        "legacy_limit_env": ("GEOMETRY_EXPORT_INLINE_LIMIT",),
    },
    "estimate_conversion_job": {
        "family": FAMILY_GEOGRAPHY,
        "capability_id": "conversion_job_estimate",
        "pricing": PRICING_FREE,
        "notes": "Quotes must stay free.",
    },
    "create_conversion_job": {
        "family": FAMILY_GEOGRAPHY,
        "capability_id": "conversion_job",
        "pricing": PRICING_FREE,
        "inline_item_limit": 100,
        "legacy_limit_env": ("CONVERSION_JOB_INLINE_LIMIT",),
    },
    "get_job_status": {
        "family": FAMILY_GEOGRAPHY,
        "capability_id": "geometry_job_status",
        "pricing": PRICING_FREE,
        "notes": "Polling a job you already paid for must never be gated.",
    },
    # ---- geography discovery: always free, no item cap ----
    "read_geometry_catalog": {
        "family": FAMILY_GEOGRAPHY,
        "capability_id": "geometry_catalog_discovery",
        "pricing": PRICING_FREE,
    },
    "list_reference_systems": {
        "family": FAMILY_GEOGRAPHY,
        "capability_id": "reference_system_discovery",
        "pricing": PRICING_FREE,
    },
    # ---- discovery helpers: always free. Gating these would make the catalog
    # undiscoverable and break the funnel. ----
    "get_catalog": {
        "family": FAMILY_DISCOVERY,
        "capability_id": "catalog_discovery",
        "pricing": PRICING_FREE,
    },
    "get_pack": {
        "family": FAMILY_DISCOVERY,
        "capability_id": "pack_detail_discovery",
        "pricing": PRICING_FREE,
    },
    "get_live_earthquake_events": {
        "family": FAMILY_DISCOVERY,
        "capability_id": "live_earthquake_lookup",
        "pricing": PRICING_FREE,
    },
    "get_live_volcano_events": {
        "family": FAMILY_DISCOVERY,
        "capability_id": "live_volcano_lookup",
        "pricing": PRICING_FREE,
    },
    "get_disaster_links_for_event": {
        "family": FAMILY_DISCOVERY,
        "capability_id": "disaster_links_for_event",
        "pricing": PRICING_FREE,
    },
    "get_disaster_link_chain": {
        "family": FAMILY_DISCOVERY,
        "capability_id": "disaster_link_chain",
        "pricing": PRICING_FREE,
    },
    "search_disaster_links": {
        "family": FAMILY_DISCOVERY,
        "capability_id": "disaster_link_search",
        "pricing": PRICING_FREE,
    },
    # ---- dataset tools: priced by pack, not here. Listed so the universe is
    # complete and nothing is silently ungoverned. ----
    "query_dataset": {"family": FAMILY_DATASET, "capability_id": "dataset_query", "pricing": "by_pack"},
    "get_earthquake_events": {"family": FAMILY_DATASET, "capability_id": "dataset_query", "pricing": "by_pack"},
    "get_volcanic_activity": {"family": FAMILY_DATASET, "capability_id": "dataset_query", "pricing": "by_pack"},
    "get_tsunami_events": {"family": FAMILY_DATASET, "capability_id": "dataset_query", "pricing": "by_pack"},
    "get_fx_rates": {"family": FAMILY_DATASET, "capability_id": "dataset_query", "pricing": "by_pack"},
}


def tool_ids() -> tuple[str, ...]:
    return tuple(TOOL_ACCESS_REGISTRY)


def tool_profile(tool_name: str) -> dict:
    return TOOL_ACCESS_REGISTRY.get(str(tool_name or "").strip(), {})


def tool_capability_id(tool_name: str) -> str:
    return str(tool_profile(tool_name).get("capability_id") or tool_name or "").strip()


def tool_family(tool_name: str) -> str:
    return str(tool_profile(tool_name).get("family") or "").strip()


def tool_pricing(tool_name: str) -> str:
    return str(tool_profile(tool_name).get("pricing") or PRICING_FREE).strip()


def tool_is_paid_bulk(tool_name: str) -> bool:
    """True when exceeding the free item limit should produce a paid quote.

    Mirrors the pack registry convention: only values starting with "paid" are
    enforced as paid, so an unknown or misspelled value fails safe to free.
    """
    return tool_pricing(tool_name).startswith("paid")


def tool_free_item_limit(tool_name: str) -> int | None:
    value = tool_profile(tool_name).get("free_item_limit")
    return int(value) if isinstance(value, int) else None


def tool_paid_item_limit(tool_name: str) -> int | None:
    value = tool_profile(tool_name).get("paid_item_limit")
    return int(value) if isinstance(value, int) else None


def tool_inline_item_limit(tool_name: str) -> int | None:
    value = tool_profile(tool_name).get("inline_item_limit")
    return int(value) if isinstance(value, int) else None


def tool_legacy_limit_env(tool_name: str) -> tuple[str, ...]:
    value = tool_profile(tool_name).get("legacy_limit_env") or ()
    return tuple(str(name) for name in value)


def tool_sub_limit(tool_name: str, sub_key: str) -> dict:
    subs = tool_profile(tool_name).get("sub_limits")
    if not isinstance(subs, dict):
        return {}
    entry = subs.get(str(sub_key or "").strip())
    return entry if isinstance(entry, dict) else {}


def free_tool_ids() -> tuple[str, ...]:
    return tuple(name for name in TOOL_ACCESS_REGISTRY if not tool_is_paid_bulk(name))


def paid_bulk_tool_ids() -> tuple[str, ...]:
    return tuple(name for name in TOOL_ACCESS_REGISTRY if tool_is_paid_bulk(name))


def licensing_permits_paid_bulk(permissions) -> bool:
    """True only when every contributing source/bank permits paid hosted use.

    ``permissions`` is the set of ``permission`` values behind the tool, taken
    from pack metadata or geometry bank ``source_license`` entries. The rule
    from docs/future/open_data_business_model.md is deliberately strict:

    - ``paid``  -> the licence allows paid hosted API/MCP lanes
    - ``free``  -> usable in free lanes only; must not sit behind paid access
    - ``other`` -> unresolved research state; never treat as paid

    One ``free`` or unresolved contributor disqualifies the whole tool, because
    a bulk call can span every bank behind it.
    """
    values = {str(value or "").strip().lower() for value in (permissions or [])}
    if not values:
        return False
    return values == {"paid"}
