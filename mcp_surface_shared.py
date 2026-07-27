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
            "description": "Free geography utility (reverse geocoding). Converts a latitude/longitude into the DaedalMap loc_id administrative chain - the deepest available level plus its parents - so you can join any spatial data to the same loc_id spine the data packs use. Returns the matched country, the deepest resolved loc_id, and the full admin-level stack so you can clip to any level. No payment required.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number", "minimum": -90, "maximum": 90, "description": "Latitude in WGS84 decimal degrees."},
                    "lon": {"type": "number", "minimum": -180, "maximum": 180, "description": "Longitude in WGS84 decimal degrees."},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "required": ["lat", "lon"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_boundary",
            "title": "Get loc_id Boundary",
            "description": "Free geography utility. Returns the geographic extent of a DaedalMap loc_id: its bounding box and centroid by default, and the full boundary polygon when include_polygon is true. Use the bbox to clip or index your own grid/raster data against DaedalMap administrative areas; request the polygon only when you need the exact perimeter (it can be large). No payment required.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "loc_id": {"type": "string", "description": "DaedalMap loc_id, e.g. 'USA-CA' or 'USA-CA-037'."},
                    "include_polygon": {"type": "boolean", "description": "When true, include the full boundary GeoJSON geometry. Default false (bbox + centroid only) to keep responses small."},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "required": ["loc_id"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "loc_id_hierarchy",
            "title": "Get loc_id Hierarchy",
            "description": "Free geography utility. Returns the administrative hierarchy around a DaedalMap loc_id: its parent and full ancestor chain up to the country, plus a summary of its children by level. Use this to walk up or down the loc_id spine and clip to any administrative level. No payment required.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "loc_id": {"type": "string", "description": "DaedalMap loc_id, e.g. 'USA-CA-037'."},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "required": ["loc_id"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "loc_id_info",
            "title": "Get loc_id Info",
            "description": "Free geography utility. Returns descriptive metadata for a DaedalMap loc_id: name, admin level, parent, centroid, bounding box, and child counts by level. No payment required.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "loc_id": {"type": "string", "description": "DaedalMap loc_id, e.g. 'USA-CA'."},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "required": ["loc_id"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "sidechain_to_admin",
            "title": "Bridge Side-Chain Geometry to Admin loc_id",
            "description": "Free geography utility. Converts a side-chain geometry such as a Census ZCTA or tribal area to a target administrative level using measured polygon overlap. Returns the primary match plus ranked overlaps with source_area_share and target_area_share. For ZIP workflows use source_family='overlay_zcta' and pass source_loc_id as either 'USA-Z-10001' or '10001'. No payment required.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source_family": {"type": "string", "enum": ["overlay_zcta", "overlay_tribal"], "description": "Side-chain geometry family. Use overlay_zcta for Census ZCTAs and overlay_tribal for tribal areas."},
                    "source_loc_id": {"type": "string", "description": "Side-chain loc_id. For ZCTAs, either canonical form such as 'USA-Z-10001' or a five-digit ZIP/ZCTA like '10001' is accepted."},
                    "target_admin_level": {"anyOf": [{"type": "string"}, {"type": "integer"}], "description": "Target admin level. Accepts admin_0..admin_4, 0..4, or friendly names such as country, state, county, tract, or block_group."},
                    "iso3": {"type": "string", "description": "Country code for bridge artifacts. Default USA."},
                    "min_source_area_share": {"type": "number", "minimum": 0, "maximum": 1, "description": "Optional minimum share of the source polygon covered by a target match."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Maximum ranked overlaps to return. Default returns all matches."},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "required": ["source_family", "source_loc_id", "target_admin_level"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "admin_to_sidechain",
            "title": "Bridge Admin loc_id to Side-Chain Geometry",
            "description": "Free geography utility. Converts a canonical administrative loc_id to overlapping side-chain shapes such as Census ZCTAs or tribal areas using measured polygon overlap. Returns the primary match plus ranked overlaps with target_area_share and source_area_share. No payment required.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target_loc_id": {"type": "string", "description": "Canonical admin loc_id, such as 'USA-NY-061-009903-2'."},
                    "source_family": {"type": "string", "enum": ["overlay_zcta", "overlay_tribal"], "description": "Side-chain geometry family to return. Use overlay_zcta for Census ZCTAs and overlay_tribal for tribal areas."},
                    "target_admin_level": {"anyOf": [{"type": "string"}, {"type": "integer"}], "description": "Admin level of target_loc_id. Accepts admin_0..admin_4, 0..4, or friendly names such as country, state, county, tract, or block_group."},
                    "iso3": {"type": "string", "description": "Country code for bridge artifacts. Default USA."},
                    "min_target_area_share": {"type": "number", "minimum": 0, "maximum": 1, "description": "Optional minimum share of the target admin polygon covered by a side-chain match."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Maximum ranked overlaps to return. Default returns all matches."},
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing."},
                },
                "required": ["target_loc_id", "source_family", "target_admin_level"],
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
