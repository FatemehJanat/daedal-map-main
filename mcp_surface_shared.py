from __future__ import annotations

from pack_registry_shared import published_pack_ids
from pack_pricing_shared import FREE_PACK_IDS, PAID_PACK_IDS


CURRENT_HOSTED_PACK_IDS: tuple[str, ...] = published_pack_ids()


def _pack_id_description() -> str:
    return (
        "Pack identifier such as 'currency', 'earthquakes', 'floods', "
        "'hurricanes', 'tornadoes', 'tsunamis', 'un_sdg', 'volcanoes', "
        "'world_factbook', or 'worldpop'."
    )


def _query_props() -> dict:
    return {
        "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing and idempotency."},
        "metrics": {"type": "array", "items": {"type": "string"}, "description": "Metric ids to return."},
        "filters": {"type": "object", "description": "Structured filters including time ranges, region_ids, and compare clauses."},
        "sort": {"anyOf": [{"type": "array"}, {"type": "object"}], "description": "Optional sort instructions for row-returning queries."},
        "limit": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Maximum number of rows to return."},
        "output": {"type": "object", "description": "Optional output controls such as response format hints."},
    }


def _query_tool(name: str, title: str, description: str, required: list[str]) -> dict:
    return {
        "name": name,
        "title": title,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": dict(_query_props()),
            "required": list(required),
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    }


def build_mcp_instructions(*, safety_notice: str | None = None) -> str:
    free = ", ".join(sorted(FREE_PACK_IDS))
    paid = ", ".join(sorted(PAID_PACK_IDS))
    base = (
        f"Geospatial data MCP server. Free packs: {free}. Paid packs: {paid} "
        "(x402 Base USDC). Start with get_catalog, then get_pack before querying "
        "a new pack."
    )
    if safety_notice:
        return f"{base} Safety: {safety_notice}"
    return base


def build_tool_definitions() -> list[dict]:
    return [
        {
            "name": "get_catalog",
            "title": "Get Catalog",
            "description": "Free discovery. Returns the list of live agent-ready data packs available on DaedalMap.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_pack",
            "title": "Get Pack",
            "description": "Free discovery. Returns detailed metadata, coverage, freshness, preferred canonical tool guidance, and first-query examples for one pack. Call this before querying a new pack so you can see time shape, coverage limits, and the paste-ready first query.",
            "inputSchema": {
                "type": "object",
                "properties": {"pack_id": {"type": "string", "description": _pack_id_description()}},
                "required": ["pack_id"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_disaster_links_for_event",
            "title": "Get Disaster Links For Event",
            "description": "Free linked-disaster helper. Resolves one exact disaster event id into its published related-disaster links. Use this only when you already have an exact event id from a supported pack such as earthquakes, tsunamis, volcanoes, or wildfires.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "Exact disaster event id from a supported pack row, such as 'NOAA-SIG-2' or 'USA-CA-FIRE-215'."},
                    "pack_id": {"type": "string", "description": "Optional pack id hint when the event id is ambiguous. Supported exact-event link packs are earthquakes, tsunamis, volcanoes, and wildfires."},
                    "cross_type_only": {"type": "boolean", "description": "When true, only return cross-hazard links. Default true."},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "required": ["event_id"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_disaster_link_chain",
            "title": "Get Disaster Link Chain",
            "description": "Free linked-disaster helper. Expands one exact disaster event id into a bounded related-event chain. Use this only when you already have an exact event id from a supported pack such as earthquakes, tsunamis, volcanoes, or wildfires.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "Exact disaster event id from a supported pack row, such as 'NOAA-SIG-2' or 'USA-CA-FIRE-215'."},
                    "pack_id": {"type": "string", "description": "Optional pack id hint when the event id is ambiguous. Supported exact-event link packs are earthquakes, tsunamis, volcanoes, and wildfires."},
                    "depth": {"type": "integer", "minimum": 1, "maximum": 2, "description": "Maximum link-chain depth to traverse. Default 1."},
                    "cross_type_only": {"type": "boolean", "description": "When true, only return cross-hazard links. Default true."},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "required": ["event_id"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "search_disaster_links",
            "title": "Search Disaster Links",
            "description": "Free linked-disaster discovery helper. Searches published cross-disaster link families by event-type direction, optional via-event type, and optional year window. Use this when you want to discover whether a relationship family exists before you have an exact event id.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "start_event_type": {"type": "string", "description": "Optional starting event type such as earthquake, hurricane, volcano, wildfire, flood, tornado, or tsunami."},
                    "via_event_type": {"type": "string", "description": "Optional intermediate event type for bounded chain discovery."},
                    "end_event_type": {"type": "string", "description": "Optional ending event type such as tsunami, flood, tornado, or earthquake."},
                    "year_start": {"type": "integer", "description": "Optional inclusive starting year filter."},
                    "year_end": {"type": "integer", "description": "Optional inclusive ending year filter."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Maximum number of matching chains to return. Default 10."},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "resolve_point",
            "title": "Resolve Point to loc_id",
            "description": "Geography utility (reverse geocoding). Converts one WGS84 latitude/longitude point, or a bounded list of points, into DaedalMap loc_id administrative chains at a requested admin level in one MCP tool call. Default target_admin_level is admin_2; responses say when deeper admin_3+ levels exist so callers can ask intentionally. The free preview executes small batches; larger valid batches return a payment-required quote that can be satisfied through account credits or x402.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number", "minimum": -90, "maximum": 90, "description": "Latitude in WGS84 decimal degrees."},
                    "lon": {"type": "number", "minimum": -180, "maximum": 180, "description": "Longitude in WGS84 decimal degrees."},
                    "points": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "lat": {"type": "number", "minimum": -90, "maximum": 90, "description": "Latitude in WGS84 decimal degrees."},
                                "lon": {"type": "number", "minimum": -180, "maximum": 180, "description": "Longitude in WGS84 decimal degrees."},
                                "row_index": {"anyOf": [{"type": "integer"}, {"type": "string"}], "description": "Optional caller row identifier echoed in the result."},
                                "id": {"anyOf": [{"type": "integer"}, {"type": "string"}], "description": "Optional caller point identifier echoed in the result."},
                            },
                            "required": ["lat", "lon"],
                            "additionalProperties": False,
                        },
                        "description": "Points to resolve. Hosted default free preview is 25 points; larger valid batches return a payment-required quote instead of executing for free.",
                    },
                    "target_admin_level": {
                        "anyOf": [{"type": "string"}, {"type": "integer"}],
                        "description": "Requested administrative level such as admin_0, admin_1, admin_2, admin_3, admin_4, or admin_5. Default admin_2. Use deepest/all only when the caller explicitly needs the deepest supported local geometry.",
                    },
                    "parent_loc_id": {"type": "string", "description": "Optional country scope such as USA, CAN, or IND. Required for paid/trusted bulk point batches over the free preview limit. Bulk should use one country and one target_admin_level per call."},
                    "country_scope": {"type": "string", "description": "Alias for parent_loc_id when the scope is an admin_0/country loc_id."},
                    "country_hint": {"type": "string", "description": "Alias for parent_loc_id/iso3. Use one country per paid/trusted bulk batch."},
                    "iso3": {"type": "string", "description": "Alias for parent_loc_id/country_scope when the scope is an ISO3 country code."},
                    "country": {"type": "string", "description": "Alias for parent_loc_id/country_scope when the scope is an ISO3 country code."},
                    "include_geometry": {"type": "boolean", "description": "When true, include geometry in resolver internals where available. Default false to keep responses small."},
                    "batch_id": {"type": "string", "description": "Optional caller-supplied batch id echoed in the result."},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "anyOf": [
                    {"required": ["lat", "lon"]},
                    {"required": ["points"]},
                ],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "loc_id_info",
            "title": "Get loc_id Info",
            "description": "Free geography utility. Returns descriptive metadata for one DaedalMap loc_id, or a bounded list of loc_ids: name, admin level, parent, centroid, bounding box, and child counts by level. Set include_hierarchy for ancestors and include_references for known external/side-chain references. No payment required.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "loc_id": {"type": "string", "description": "DaedalMap loc_id, e.g. 'USA-CA'."},
                    "loc_ids": {"type": "array", "items": {"type": "string"}, "description": "DaedalMap loc_ids to inspect in one call. Default public cap is deployment-configurable."},
                    "include_hierarchy": {"type": "boolean", "description": "When true, include parent and full ancestor chain. Default false."},
                    "include_references": {"type": "boolean", "description": "When true, include known external or side-chain references attached to each loc_id. Default false."},
                    "systems": {"type": "array", "items": {"type": "string"}, "description": "Optional reference systems to include when include_references is true, such as zcta, nws_fire, overlay_tribal, or overlay_nws_public_zone."},
                    "iso3": {"type": "string", "description": "Optional country hint for bridge artifacts. Defaults to the loc_id country when possible."},
                    "target_admin_level": {"anyOf": [{"type": "string"}, {"type": "integer"}], "description": "Admin level for bridge-backed reverse reference lookup. Inferred when omitted."},
                    "min_share": {"type": "number", "minimum": 0, "maximum": 1, "description": "Optional minimum target-area share for reverse overlap references."},
                    "limit_per_system": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Maximum overlap references to return per bridge/system. Default 10."},
                    "batch_id": {"type": "string", "description": "Optional caller-supplied batch id for tracing."},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "anyOf": [
                    {"required": ["loc_id"]},
                    {"required": ["loc_ids"]},
                ],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "list_reference_systems",
            "title": "List Geographic Reference Systems",
            "description": "Free geography utility. Lists the currently exchangeable geographic reference systems in DaedalMap, including catalog-backed geometry families, bridge artifacts, row counts, vintages, target levels, and source license metadata. Call this first when you need to know whether ZIP/ZCTA, NWS zones, tribal areas, marine ids, NUTS-style regional ids, or other systems can be exchanged through loc_id. No payment required.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "resolve_reference",
            "title": "Resolve Reference to loc_id",
            "description": "Free geography utility. Converts one value, or a bounded list of values, from an external or adjacent geographic reference system into the DaedalMap loc_id universe. Examples: from_system='zip' value='00601'; from_system='nws_fire' value='AKZ317'; from_system='admin_boundary' value='Fairfax County'. Returns ranked loc_id matches with bridge vintage, overlap weights, and provenance where applicable. No payment required.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "from_system": {"type": "string", "description": "Input reference system, such as loc_id, admin_boundary, zip, zcta, overlay_zcta, nws_zone, nws_fire, overlay_nws_fire_weather_zone, tribal, water_body, marine_eez, nuts, or a catalog family id."},
                    "value": {"type": "string", "description": "Identifier or name in the input system. Examples: 00601, USA-Z-00601, AKZ317, USA-NWSFZ-AKZ317, Fairfax County, Mediterranean Sea."},
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "from_system": {"type": "string", "description": "Input reference system for this row. Defaults to top-level from_system when omitted."},
                                "value": {"type": "string", "description": "Identifier or name in the input system."},
                                "iso3": {"type": "string", "description": "Optional country hint for this row."},
                                "target_admin_level": {"anyOf": [{"type": "string"}, {"type": "integer"}], "description": "Optional admin target level for this row."},
                                "bridge_vintage": {"type": "string", "description": "Optional bridge vintage for this row."},
                                "min_share": {"type": "number", "minimum": 0, "maximum": 1, "description": "Optional minimum area-share threshold for this row."},
                                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Maximum ranked matches for this row."},
                                "country_hint": {"type": "string", "description": "Optional country hint for admin/name resolution."},
                                "admin_level_hint": {"type": "integer", "minimum": 0, "maximum": 5, "description": "Optional admin-level hint for admin/name resolution."},
                                "row_index": {"anyOf": [{"type": "integer"}, {"type": "string"}], "description": "Optional caller row identifier echoed in the result."},
                                "id": {"anyOf": [{"type": "integer"}, {"type": "string"}], "description": "Optional caller identifier echoed in the result."},
                            },
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                        "description": "Reference values to resolve in one call. Default public cap is deployment-configurable.",
                    },
                    "iso3": {"type": "string", "description": "Country hint for system-specific bridges. Default USA."},
                    "target_admin_level": {"anyOf": [{"type": "string"}, {"type": "integer"}], "description": "Admin target level for bridge-backed resolution. Default admin_2. Accepts admin_0..admin_5, 0..5, or names such as country, state, county, tract, block_group, or block."},
                    "bridge_vintage": {"type": "string", "description": "Optional bridge vintage to require, such as usa_geometry_current or census_2020_relationship_files."},
                    "min_share": {"type": "number", "minimum": 0, "maximum": 1, "description": "Optional minimum area-share threshold for overlap matches."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Maximum ranked matches to return. Default 10."},
                    "country_hint": {"type": "string", "description": "Optional country hint for admin/name resolution."},
                    "admin_level_hint": {"type": "integer", "minimum": 0, "maximum": 5, "description": "Optional admin-level hint for admin/name resolution."},
                    "batch_id": {"type": "string", "description": "Optional caller-supplied batch id for tracing."},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "anyOf": [
                    {"required": ["from_system", "value"]},
                    {"required": ["items"]},
                ],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "convert_reference",
            "title": "Convert Geographic Reference",
            "description": "Free geography utility. Converts one reference, or a bounded list of references, from one geographic reference system into another by resolving through DaedalMap loc_id: X -> loc_id -> Y. Use this for workflows like ZIP/ZCTA to NWS fire zones, NWS zone to counties, county to overlapping ZCTAs, or any future catalog-backed reference bridge. No payment required.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "from_system": {"type": "string", "description": "Input reference system, such as zip, overlay_zcta, nws_fire, tribal, admin_boundary, or loc_id."},
                    "value": {"type": "string", "description": "Identifier or name in the input system."},
                    "to_system": {"type": "string", "description": "Output reference system, such as loc_id, zcta, nws_fire, overlay_nws_public_zone, overlay_tribal, admin_local, or admin_geometry."},
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "from_system": {"type": "string", "description": "Input reference system for this row. Defaults to top-level from_system when omitted."},
                                "value": {"type": "string", "description": "Identifier or name in the input system."},
                                "to_system": {"type": "string", "description": "Output reference system for this row. Defaults to top-level to_system when omitted."},
                                "iso3": {"type": "string", "description": "Optional country hint for this row."},
                                "target_admin_level": {"anyOf": [{"type": "string"}, {"type": "integer"}], "description": "Optional intermediate admin target level for this row."},
                                "bridge_vintage": {"type": "string", "description": "Optional bridge vintage for this row."},
                                "min_share": {"type": "number", "minimum": 0, "maximum": 1, "description": "Optional minimum overlap share threshold for this row."},
                                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Maximum ranked output references for this row."},
                                "row_index": {"anyOf": [{"type": "integer"}, {"type": "string"}], "description": "Optional caller row identifier echoed in the result."},
                                "id": {"anyOf": [{"type": "integer"}, {"type": "string"}], "description": "Optional caller identifier echoed in the result."},
                            },
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                        "description": "Reference conversions to run in one call. Default public cap is deployment-configurable.",
                    },
                    "iso3": {"type": "string", "description": "Country hint for bridge artifacts. Default USA."},
                    "target_admin_level": {"anyOf": [{"type": "string"}, {"type": "integer"}], "description": "Admin level used as the intermediate bridge target. Default admin_2."},
                    "bridge_vintage": {"type": "string", "description": "Optional source bridge vintage to require."},
                    "min_share": {"type": "number", "minimum": 0, "maximum": 1, "description": "Optional minimum overlap share threshold."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Maximum ranked output references to return. Default 10."},
                    "batch_id": {"type": "string", "description": "Optional caller-supplied batch id for tracing."},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "anyOf": [
                    {"required": ["from_system", "value", "to_system"]},
                    {"required": ["items"]},
                ],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "check_geometry",
            "title": "Check loc_id Geometry Availability",
            "description": "Free geography utility. Fast preflight for one DaedalMap loc_id, or a bounded list of loc_ids, that reports whether DaedalMap has reusable boundary shapes before requesting full GeoJSON geometry. No payment required.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "loc_id": {"type": "string", "description": "DaedalMap loc_id to check for available geometry."},
                    "loc_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "DaedalMap loc_ids to check for available geometry. Default public cap is deployment-configurable.",
                    },
                    "batch_id": {"type": "string", "description": "Optional caller-supplied batch id for tracing."},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "anyOf": [
                    {"required": ["loc_id"]},
                    {"required": ["loc_ids"]},
                ],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_geometry",
            "title": "Get loc_id Geometry",
            "description": "Free geography utility. Returns reusable geometry metadata for one DaedalMap loc_id, or a bounded list of loc_ids: name, family, admin level, centroid, bounding box, and optional full GeoJSON polygon. Prefer bbox/centroid unless you need exact rendering or clipping. No payment required.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "loc_id": {"type": "string", "description": "DaedalMap loc_id, such as USA-CA-037, USA-Z-00601, USA-NWSFZ-AKZ317, EEZ-USA, or IHO1953-240001002."},
                    "loc_ids": {"type": "array", "items": {"type": "string"}, "description": "DaedalMap loc_ids to fetch in one call. Default public cap is deployment-configurable and lower when include_polygon is true."},
                    "include_polygon": {"type": "boolean", "description": "When true, include the full GeoJSON geometry. Default false."},
                    "batch_id": {"type": "string", "description": "Optional caller-supplied batch id for tracing."},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "anyOf": [
                    {"required": ["loc_id"]},
                    {"required": ["loc_ids"]},
                ],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "resolve_loc_id_scope",
            "title": "Resolve loc_id Scope",
            "description": "Free geography utility. Given a strict parent loc_id and target admin level, returns a count and bounded list of descendant loc_ids. Use this before package requests such as all USA county shapes. No natural-language scope decoding is performed.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "parent_loc_id": {"type": "string", "description": "Parent DaedalMap loc_id, such as USA or CAN-BC."},
                    "admin_level": {"anyOf": [{"type": "string"}, {"type": "integer"}], "description": "Target level, such as admin_2, 2, county, or state."},
                    "scope": {
                        "type": "object",
                        "properties": {
                            "parent_loc_id": {"type": "string"},
                            "admin_level": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                            "bbox": {"anyOf": [{"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}, {"type": "string"}]},
                        },
                        "additionalProperties": False,
                    },
                    "bbox": {"anyOf": [{"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}, {"type": "string"}], "description": "Optional minLon,minLat,maxLon,maxLat filter."},
                    "limit": {"type": "integer", "minimum": 0, "maximum": 1000, "description": "Maximum rows to return inline. Counts are returned even when rows are truncated."},
                    "offset": {"type": "integer", "minimum": 0, "description": "Offset for preview paging."},
                    "count_only": {"type": "boolean", "description": "When true, return counts without loc_id rows."},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "anyOf": [
                    {"required": ["parent_loc_id", "admin_level"]},
                    {"required": ["scope"]},
                ],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "estimate_geometry_package",
            "title": "Estimate Geometry Package",
            "description": "Free dry-run quote. Estimates loc_id count, shape availability, bytes, delivery mode, citation requirements, and charge units for a geometry package before execution.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "loc_id": {"type": "string", "description": "Single loc_id to package."},
                    "loc_ids": {"type": "array", "items": {"type": "string"}, "description": "Explicit loc_ids to package."},
                    "scope": {
                        "type": "object",
                        "properties": {
                            "parent_loc_id": {"type": "string"},
                            "admin_level": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                            "bbox": {"anyOf": [{"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}, {"type": "string"}]},
                        },
                        "additionalProperties": False,
                    },
                    "format": {"type": "string", "description": "Requested delivery format: geojson, geojson_gzip, zip, geoparquet, flatgeobuf, or pmtiles."},
                    "include_polygon": {"type": "boolean", "description": "Estimate full shapes when true; metadata-only when false."},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "anyOf": [
                    {"required": ["loc_id"]},
                    {"required": ["loc_ids"]},
                    {"required": ["scope"]},
                ],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "create_geometry_export",
            "title": "Create Geometry Export",
            "description": "Creates an accepted geometry package request. Tiny requests can complete inline; larger requests return a queued job_id for artifact processing and status polling.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "quote_id": {"type": "string", "description": "Quote id returned by estimate_geometry_package, when available."},
                    "loc_id": {"type": "string"},
                    "loc_ids": {"type": "array", "items": {"type": "string"}},
                    "scope": {
                        "type": "object",
                        "properties": {
                            "parent_loc_id": {"type": "string"},
                            "admin_level": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                            "bbox": {"anyOf": [{"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}, {"type": "string"}]},
                        },
                        "additionalProperties": False,
                    },
                    "format": {"type": "string"},
                    "include_polygon": {"type": "boolean"},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "anyOf": [
                    {"required": ["loc_id"]},
                    {"required": ["loc_ids"]},
                    {"required": ["scope"]},
                ],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": False},
        },
        {
            "name": "estimate_conversion_job",
            "title": "Estimate loc_id Conversion Job",
            "description": "Free dry-run quote for uploaded or pasted user data conversion. Estimates rows, sample resolvability, output bytes, errors, and charge units before execution.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "from_system": {"type": "string", "description": "Input reference system for rows."},
                    "to_system": {"type": "string", "description": "Optional output reference system. Omit to normalize to loc_id."},
                    "items": {"type": "array", "items": {"type": "object"}, "description": "Sample or full rows with at least value; row-level systems may override top-level systems."},
                    "row_count": {"type": "integer", "minimum": 0, "description": "Expected total row count when only a sample or artifact pointer is provided."},
                    "target_admin_level": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "anyOf": [
                    {"required": ["from_system", "items"]},
                    {"required": ["from_system", "row_count"]},
                ],
                "additionalProperties": True,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "create_conversion_job",
            "title": "Create loc_id Conversion Job",
            "description": "Creates an accepted user-data conversion job. Small item batches can complete inline; larger batches return a queued job_id for artifact processing and status polling.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "quote_id": {"type": "string", "description": "Quote id returned by estimate_conversion_job, when available."},
                    "from_system": {"type": "string"},
                    "to_system": {"type": "string", "description": "Optional output reference system. Omit to normalize to loc_id."},
                    "items": {"type": "array", "items": {"type": "object"}, "description": "Rows to convert; each row needs value and may include row_index."},
                    "target_admin_level": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "required": ["from_system", "items"],
                "additionalProperties": True,
            },
            "annotations": {"readOnlyHint": False},
        },
        {
            "name": "get_job_status",
            "title": "Get Geometry Job Status",
            "description": "Checks queued/running/completed async geometry export and conversion jobs. Returns progress, errors, callback state, and artifact links when available.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job id returned by create_geometry_export or create_conversion_job."},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "required": ["job_id"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_earthquake_events",
            "title": "Get Earthquake Events",
            "description": "Paid x402 canonical tool. Queries the published earthquakes_events lane. Use this first for earthquake questions because it is the enriched DaedalMap history lane with stable loc_id geography, not the preliminary upstream wrapper. Call without payment first - the server returns HTTP 402 with the exact USDC price before any charge. Small queries stay cheap; broad scans cost more or need narrower filters.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing and idempotency."},
                    "metrics": {"type": "array", "items": {"type": "string"}, "description": "Metric ids to return, such as 'event_count' or event attributes like 'magnitude'."},
                    "filters": {"type": "object", "description": "Structured filters including time ranges, region_ids, and compare clauses."},
                    "sort": {"anyOf": [{"type": "array"}, {"type": "object"}], "description": "Optional sort instructions for row-returning queries."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Maximum number of rows to return. For top-N requests, include a narrow time range or region_ids before sorting."},
                    "output": {"type": "object", "description": "Optional output controls such as response format hints."},
                },
                "required": ["metrics", "filters"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_live_earthquake_events",
            "title": "Get Live Earthquake Events",
            "description": "Free live wrapper. Calls the USGS FDSN API for recent preliminary earthquake events normalized to DaedalMap event fields. Use this only when the caller explicitly wants live/preliminary upstream results or needs a very recent window not yet present in the published canonical earthquake lane. This is not the enriched canonical history lane.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                    "hours": {"type": "integer", "minimum": 1, "maximum": 168, "description": "Recent lookback window in hours. Ignored when start_time is provided."},
                    "start_time": {"type": "string", "description": "Optional inclusive ISO-8601 start datetime."},
                    "end_time": {"type": "string", "description": "Optional exclusive-ish ISO-8601 end datetime. Defaults to now."},
                    "min_magnitude": {"type": "number", "description": "Minimum earthquake magnitude. Defaults to 2.5."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Maximum live rows to return."},
                    "orderby": {"type": "string", "enum": ["time", "time-asc", "magnitude", "magnitude-asc"], "description": "USGS result ordering."},
                    "min_latitude": {"type": "number", "description": "Optional bounding box minimum latitude."},
                    "max_latitude": {"type": "number", "description": "Optional bounding box maximum latitude."},
                    "min_longitude": {"type": "number", "description": "Optional bounding box minimum longitude."},
                    "max_longitude": {"type": "number", "description": "Optional bounding box maximum longitude."},
                },
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_volcanic_activity",
            "title": "Get Volcanic Activity",
            "description": "Free canonical tool. Queries volcanoes_events for historical eruption records and volcanic activity metrics. Best for eruption counts, VEI thresholds, and top-event lookups. Volcano queries normally use year-style time filters rather than ISO date strings.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing and idempotency."},
                    "metrics": {"type": "array", "items": {"type": "string"}, "description": "Metric ids to return, such as 'event_count', 'VEI', or eruption attributes."},
                    "filters": {"type": "object", "description": "Structured filters including year-based time ranges, region_ids, and compare clauses. For most volcano queries, pass numeric years or time.value."},
                    "sort": {"anyOf": [{"type": "array"}, {"type": "object"}], "description": "Optional sort instructions for row-returning queries."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Maximum number of rows to return. For top-N VEI or latest-eruption requests, include a narrow year range or region_ids before sorting."},
                    "output": {"type": "object", "description": "Optional output controls such as response format hints."},
                },
                "required": ["metrics", "filters"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_live_volcano_events",
            "title": "Get Live Volcano Events",
            "description": "Free live wrapper. Calls the Smithsonian/GVP WFS for recent preliminary volcanic eruption updates normalized to DaedalMap event fields. This is not the enriched canonical history lane.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                    "days": {"type": "integer", "minimum": 1, "maximum": 730, "description": "Recent lookback window in days. Ignored when start_time is provided."},
                    "start_time": {"type": "string", "description": "Optional inclusive ISO-8601 start datetime or date."},
                    "end_time": {"type": "string", "description": "Optional inclusive ISO-8601 end datetime or date. Defaults to now."},
                    "min_vei": {"type": "number", "description": "Optional minimum Volcanic Explosivity Index."},
                    "ongoing_only": {"type": "boolean", "description": "When true, only return eruptions marked continuing by GVP."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Maximum live rows to return."},
                    "orderby": {"type": "string", "enum": ["time", "time-asc", "vei", "vei-asc"], "description": "Result ordering."},
                },
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_tsunami_events",
            "title": "Get Tsunami Events",
            "description": "Paid x402 canonical tool. Queries tsunamis_events for historical tsunami records and water-height/runup metrics. Best for event counts, max water height thresholds, and top-event lookups. Region filters may use ISO3 country ids or reviewed named-water loc_ids such as IHO1953-240001002 for the Mediterranean Sea; XOO is deprecated. Call without payment first - the server returns HTTP 402 with the exact USDC price before any charge.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing and idempotency."},
                    "metrics": {"type": "array", "items": {"type": "string"}, "description": "Metric ids to return, such as 'event_count', 'max_water_height_m', or event attributes."},
                    "filters": {"type": "object", "description": "Structured filters including time ranges, region_ids, and compare clauses. Tsunami queries commonly use year-style windows and may use geometry-backed ocean/sea ids such as XSM."},
                    "sort": {"anyOf": [{"type": "array"}, {"type": "object"}], "description": "Optional sort instructions for row-returning queries."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Maximum number of rows to return. For largest-wave or latest-event requests, include a narrow time range or region_ids before sorting."},
                    "output": {"type": "object", "description": "Optional output controls such as response format hints."},
                },
                "required": ["metrics", "filters"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_fx_rates",
            "title": "Get FX Rates",
            "description": "Free tool. Queries the currency pack using filters.region_ids plus filters.time.granularity to return daily, weekly, or monthly FX data.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing and idempotency."},
                    "metrics": {"type": "array", "items": {"type": "string"}, "description": "Optional metric ids. Defaults to 'local_per_usd' for FX rate queries."},
                    "filters": {"type": "object", "description": "Structured filters including region_ids with loc_id country codes, time range, and granularity."},
                    "sort": {"anyOf": [{"type": "array"}, {"type": "object"}], "description": "Optional sort instructions for row-returning queries."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "Maximum number of rows to return for the requested granularity and time span."},
                    "output": {"type": "object", "description": "Optional output controls such as response format hints."},
                },
                "required": ["filters"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "query_dataset",
            "title": "Query Dataset",
            "description": "Generic structured query for direct source_id or pack_id access using the same contract as POST /api/v1/query/dataset. Free packs: "
            + ", ".join(sorted(FREE_PACK_IDS))
            + ". Paid packs: "
            + ", ".join(sorted(PAID_PACK_IDS))
            + " (x402 Base USDC).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing and idempotency."},
                    "source_id": {"type": "string", "description": "Concrete source id such as 'earthquakes_events', 'volcanoes_events', 'hurricanes_events', or 'un_sdg/01'."},
                    "pack_id": {"type": "string", "description": _pack_id_description()},
                    "metrics": {"type": "array", "items": {"type": "string"}, "description": "Metric ids to return. Use event_count for aggregate counts when supported."},
                    "filters": {"type": "object", "description": "Structured filters including time, region_ids, and compare clauses."},
                    "sort": {"anyOf": [{"type": "array"}, {"type": "object"}], "description": "Optional sort instructions for row-returning queries."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Maximum number of rows to return for the requested source or pack."},
                    "output": {"type": "object", "description": "Optional output controls such as response format hints."},
                },
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
    ]
