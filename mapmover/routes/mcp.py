from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from mapmover.data_loading import load_api_catalog, load_api_pack_detail
from mapmover.routes.api_query import execute_query_dataset_payload
from mapmover.security import get_allowed_origins


router = APIRouter()

MCP_PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = {MCP_PROTOCOL_VERSION, "2024-11-05"}
SERVER_INFO = {
    "name": "com.daedalmap/county-map",
    "title": "DaedalMap Disaster and Geospatial Data",
    "version": "1.0.1",
}
PACK_SERVER_PROFILES = {
    "currency": {
        "name": "com.daedalmap/currency",
        "title": "DaedalMap Historical FX Rates",
        "description": "Historical foreign exchange rates and currency comparisons from the DaedalMap MCP lane.",
        "registry_meta": {
            "categories": ["economics", "data", "geospatial"],
            "highlights": [
                "Historical foreign exchange rate comparisons",
                "Country-level FX lookups tied to DaedalMap loc_id geography",
                "Free structured MCP access for historical currency data",
            ],
        },
    },
    "earthquakes": {
        "name": "com.daedalmap/earthquakes",
        "title": "DaedalMap Earthquake Data",
        "description": "Historical earthquake event data and structured earthquake queries from the DaedalMap MCP lane.",
        "registry_meta": {
            "categories": ["hazard", "geospatial", "data"],
            "highlights": [
                "Historical earthquake event data with structured filters",
                "Paid MCP access for earthquake counts and event rows",
                "Country and region lookups tied to DaedalMap loc_id geography",
            ],
        },
    },
    "tsunamis": {
        "name": "com.daedalmap/tsunamis",
        "title": "DaedalMap Tsunami Data",
        "description": "Historical tsunami event data and structured tsunami queries from the DaedalMap MCP lane.",
        "registry_meta": {
            "categories": ["hazard", "geospatial", "data"],
            "highlights": [
                "Historical tsunami event data and wave-height metrics",
                "Paid MCP access for tsunami counts and event rows",
                "Country and coastal-region lookups tied to DaedalMap geography",
            ],
        },
    },
    "volcanoes": {
        "name": "com.daedalmap/volcanoes",
        "title": "DaedalMap Volcanic Activity",
        "description": "Historical volcanic eruption records and volcanic activity queries from the DaedalMap MCP lane.",
        "registry_meta": {
            "categories": ["hazard", "geospatial", "data"],
            "highlights": [
                "Historical volcanic eruption records and VEI data",
                "Free MCP access for volcanic activity queries",
                "Country and region lookups tied to DaedalMap loc_id geography",
            ],
        },
    },
}


def _normalize_pack_id(pack_id: str | None) -> str | None:
    normalized = str(pack_id or "").strip().lower()
    return normalized if normalized in PACK_SERVER_PROFILES else None


def get_server_info(pack_id: str | None = None) -> dict[str, Any]:
    normalized = _normalize_pack_id(pack_id)
    if not normalized:
        return dict(SERVER_INFO)
    profile = PACK_SERVER_PROFILES[normalized]
    return {
        "name": profile["name"],
        "title": profile["title"],
        "version": SERVER_INFO["version"],
    }


def get_server_description(pack_id: str | None = None) -> str:
    normalized = _normalize_pack_id(pack_id)
    if not normalized:
        return "Geospatial MCP server for earthquake, tsunami, volcano, disaster, and FX data queries."
    return PACK_SERVER_PROFILES[normalized]["description"]


def get_server_registry_meta(pack_id: str | None = None) -> dict[str, Any]:
    normalized = _normalize_pack_id(pack_id)
    if not normalized:
        return {
            "categories": ["geospatial", "hazard", "economics", "data"],
            "highlights": [
                "Historical earthquake event data",
                "Volcanic eruption and VEI records",
                "Tsunami events with wave height metrics",
                "Historical FX rates for country-level analysis",
                "Free discovery plus mixed free and paid structured retrieval",
            ],
        }
    profile = PACK_SERVER_PROFILES[normalized]
    return dict(profile.get("registry_meta") or {})


def _public_app_url() -> str:
    from mapmover.paths import APP_URL

    return str(APP_URL or "").rstrip("/")


def _public_site_url() -> str:
    from mapmover.paths import SITE_URL

    return str(SITE_URL or "").rstrip("/")


def _docs_url(path: str) -> str:
    return f"{_public_site_url()}{path}"


def _mcp_origin_allowed(request: Request) -> bool:
    origin = str(request.headers.get("origin") or "").strip()
    if not origin:
        return True
    return origin in set(get_allowed_origins())


def _jsonrpc_response(result: dict[str, Any], request_id: Any) -> JSONResponse:
    response = JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }
    )
    response.headers["MCP-Protocol-Version"] = MCP_PROTOCOL_VERSION
    response.headers["Cache-Control"] = "no-store"
    return response


def _jsonrpc_error(request_id: Any, code: int, message: str, *, data: dict[str, Any] | None = None, status_code: int = 200) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if data:
        error["data"] = data
    response = JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": error,
        },
        status_code=status_code,
    )
    response.headers["MCP-Protocol-Version"] = MCP_PROTOCOL_VERSION
    response.headers["Cache-Control"] = "no-store"
    return response


def _tool_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=False, indent=2) if isinstance(payload, (dict, list)) else str(payload)
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": text}],
        "structuredContent": payload if isinstance(payload, (dict, list)) else {"value": payload},
    }
    if is_error:
        result["isError"] = True
    return result


def _resource_text_result(uri: str, text: str, *, mime_type: str = "text/markdown") -> dict[str, Any]:
    return {
        "contents": [
            {
                "uri": uri,
                "mimeType": mime_type,
                "text": text,
            }
        ]
    }


def _ensure_request_id(arguments: dict[str, Any], tool_name: str) -> dict[str, Any]:
    normalized = dict(arguments)
    request_id = str(normalized.get("request_id") or "").strip()
    if not request_id:
        normalized["request_id"] = f"mcp-{tool_name}-{uuid.uuid4().hex[:12]}"
    return normalized


def _tool_definitions() -> list[dict[str, Any]]:
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
            "description": "Free discovery. Returns detailed metadata, coverage, metrics, and first-query guidance for one pack.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "pack_id": {
                        "type": "string",
                        "description": "Pack identifier such as 'currency', 'earthquakes', 'volcanoes', or 'tsunamis'.",
                    }
                },
                "required": ["pack_id"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_earthquake_events",
            "title": "Get Earthquake Events",
            "description": "Paid x402 tool. Queries earthquakes_events. Use event_count for aggregate counts or event metrics for raw event rows.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing and idempotency."},
                    "metrics": {"type": "array", "items": {"type": "string"}, "description": "Metric ids to return, such as 'event_count' or event attributes like 'magnitude'."},
                    "filters": {"type": "object", "description": "Structured filters including time ranges, region_ids, and compare clauses."},
                    "sort": {"anyOf": [{"type": "array"}, {"type": "object"}], "description": "Optional sort instructions for row-returning queries."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Maximum number of rows to return. Use small limits for top-N queries such as largest event in a range."},
                    "output": {"type": "object", "description": "Optional output controls such as response format hints."},
                },
                "required": ["metrics", "filters"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_volcanic_activity",
            "title": "Get Volcanic Activity",
            "description": "Free tool. Queries volcanoes_events for eruption records and volcanic activity metrics.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing and idempotency."},
                    "metrics": {"type": "array", "items": {"type": "string"}, "description": "Metric ids to return, such as 'event_count', 'VEI', or eruption attributes."},
                    "filters": {"type": "object", "description": "Structured filters including time ranges, region_ids, and compare clauses."},
                    "sort": {"anyOf": [{"type": "array"}, {"type": "object"}], "description": "Optional sort instructions for row-returning queries."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Maximum number of rows to return. Use small limits for top-N eruption lookups."},
                    "output": {"type": "object", "description": "Optional output controls such as response format hints."},
                },
                "required": ["metrics", "filters"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "get_tsunami_events",
            "title": "Get Tsunami Events",
            "description": "Paid x402 tool. Queries tsunamis_events for tsunami source events and related metrics.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing and idempotency."},
                    "metrics": {"type": "array", "items": {"type": "string"}, "description": "Metric ids to return, such as 'event_count', 'max_water_height_m', or event attributes."},
                    "filters": {"type": "object", "description": "Structured filters including time ranges, region_ids, and compare clauses."},
                    "sort": {"anyOf": [{"type": "array"}, {"type": "object"}], "description": "Optional sort instructions for row-returning queries."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Maximum number of rows to return. Use small limits for largest-wave or latest-event queries."},
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
            "description": "Generic structured query for direct source_id or pack_id access using the same contract as POST /api/v1/query/dataset. Currency and volcanoes are free; earthquakes and tsunamis are paid via x402.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing and idempotency."},
                    "source_id": {"type": "string", "description": "Concrete source id such as 'earthquakes_events' or 'volcanoes_events'."},
                    "pack_id": {"type": "string", "description": "Pack id such as 'currency', 'earthquakes', 'volcanoes', or 'tsunamis'."},
                    "metrics": {"type": "array", "items": {"type": "string"}, "description": "Metric ids to return. Use event_count for aggregate counts when supported."},
                    "filters": {"type": "object", "description": "Structured filters including time, region_ids, and compare clauses."},
                    "sort": {"anyOf": [{"type": "array"}, {"type": "object"}], "description": "Optional sort instructions for row-returning queries."},
                    "limit": {"type": "integer", "minimum": 1, "description": "Maximum number of rows to return for the requested source or pack."},
                    "output": {"type": "object", "description": "Optional output controls such as response format hints."},
                },
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
    ]


def _prompt_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "largest_earthquake_in_range",
            "title": "Largest Earthquake In Range",
            "description": "Starter prompt for finding the largest earthquake in a time range, optionally scoped to a loc_id region.",
            "arguments": [
                {"name": "start_date", "description": "Inclusive start date in YYYY-MM-DD format.", "required": True},
                {"name": "end_date", "description": "Inclusive end date in YYYY-MM-DD format.", "required": True},
                {"name": "region_id", "description": "Optional loc_id region such as USA or JPN to scope the query.", "required": False},
            ],
        },
        {
            "name": "count_disaster_events",
            "title": "Count Disaster Events",
            "description": "Starter prompt for counting earthquakes, volcanoes, or tsunamis in a time range with optional threshold and loc_id filtering.",
            "arguments": [
                {"name": "pack_id", "description": "One of earthquakes, volcanoes, or tsunamis.", "required": True},
                {"name": "start", "description": "Inclusive start date or year for the chosen pack.", "required": True},
                {"name": "end", "description": "Inclusive end date or year for the chosen pack.", "required": True},
                {"name": "region_id", "description": "Optional loc_id region to filter by.", "required": False},
                {"name": "threshold_field", "description": "Optional metric field such as magnitude, VEI, or max_water_height_m.", "required": False},
                {"name": "threshold_value", "description": "Optional numeric threshold value.", "required": False},
            ],
        },
        {
            "name": "fx_history_for_country",
            "title": "FX History For Country",
            "description": "Starter prompt for fetching USD-normalized FX history for one or more countries at daily, weekly, or monthly granularity.",
            "arguments": [
                {"name": "country_ids", "description": "Comma-separated loc_id country codes such as JPN,CAN,DEU.", "required": True},
                {"name": "granularity", "description": "One of daily, weekly, or monthly.", "required": True},
                {"name": "start", "description": "Inclusive start date in YYYY-MM-DD format.", "required": True},
                {"name": "end", "description": "Inclusive end date in YYYY-MM-DD format.", "required": True},
            ],
        },
    ]


def _render_prompt(name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    if name == "largest_earthquake_in_range":
        start_date = str(arguments.get("start_date") or "2024-01-01").strip()
        end_date = str(arguments.get("end_date") or "2024-12-31").strip()
        region_id = str(arguments.get("region_id") or "").strip()
        region_line = f'      "region_ids": ["{region_id}"],\n' if region_id else ""
        text = (
            "Use `get_earthquake_events` to return the largest earthquake in the requested range.\n\n"
            "Suggested tool call:\n"
            "```json\n"
            "{\n"
            '  "name": "get_earthquake_events",\n'
            '  "arguments": {\n'
            '    "metrics": ["magnitude", "timestamp", "place", "depth_km"],\n'
            '    "filters": {\n'
            f'      "time": {{"start": "{start_date}", "end": "{end_date}"}}'
            + (",\n" + region_line.rstrip("\n") if region_line else "")
            + "\n"
            "    },\n"
            '    "sort": [{"field": "magnitude", "direction": "desc"}],\n'
            '    "limit": 1\n'
            "  }\n"
            "}\n"
            "```\n"
        )
        return {"description": "Find the largest earthquake in a range.", "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}

    if name == "count_disaster_events":
        pack_id = str(arguments.get("pack_id") or "earthquakes").strip() or "earthquakes"
        start = str(arguments.get("start") or "2020-01-01").strip()
        end = str(arguments.get("end") or "2020-12-31").strip()
        region_id = str(arguments.get("region_id") or "").strip()
        threshold_field = str(arguments.get("threshold_field") or "").strip()
        threshold_value = str(arguments.get("threshold_value") or "").strip()
        tool_name = {
            "earthquakes": "get_earthquake_events",
            "volcanoes": "get_volcanic_activity",
            "tsunamis": "get_tsunami_events",
        }.get(pack_id, "query_dataset")
        metric_compare = ""
        if threshold_field and threshold_value:
            metric_compare = (
                ',\n      "compare": [\n'
                f'        {{"field": "{threshold_field}", "op": ">=", "value": {threshold_value}}}\n'
                "      ]"
            )
        region_line = f',\n      "region_ids": ["{region_id}"]' if region_id else ""
        text = (
            f"Use `{tool_name}` to count {pack_id} events in the requested range.\n\n"
            "Suggested tool call:\n"
            "```json\n"
            "{\n"
            f'  "name": "{tool_name}",\n'
            '  "arguments": {\n'
            '    "metrics": ["event_count"],\n'
            '    "filters": {\n'
            f'      "time": {{"start": "{start}", "end": "{end}"}}{region_line}{metric_compare}\n'
            "    }\n"
            "  }\n"
            "}\n"
            "```\n"
        )
        return {"description": "Count disaster events with optional threshold filtering.", "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}

    if name == "fx_history_for_country":
        country_ids = str(arguments.get("country_ids") or "JPN").strip()
        granularity = str(arguments.get("granularity") or "monthly").strip()
        start = str(arguments.get("start") or "2024-01-01").strip()
        end = str(arguments.get("end") or "2024-12-31").strip()
        ids = [item.strip() for item in country_ids.split(",") if item.strip()]
        ids_json = ", ".join(f'"{item}"' for item in ids) or '"JPN"'
        text = (
            "Use `get_fx_rates` to fetch USD-normalized FX history for the requested countries.\n\n"
            "Suggested tool call:\n"
            "```json\n"
            "{\n"
            '  "name": "get_fx_rates",\n'
            '  "arguments": {\n'
            '    "filters": {\n'
            f'      "region_ids": [{ids_json}],\n'
            f'      "time": {{"start": "{start}", "end": "{end}", "granularity": "{granularity}"}}\n'
            "    },\n"
            '    "metrics": ["local_per_usd"]\n'
            "  }\n"
            "}\n"
            "```\n\n"
            "If you need a cross-rate like EUR/CAD, request both countries for the same dates and derive the ratio client-side."
        )
        return {"description": "Fetch FX history for one or more countries.", "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}

    return None


def _resource_definitions() -> list[dict[str, Any]]:
    app_url = _public_app_url()
    return [
        {
            "uri": "daedalmap://guide",
            "name": "Guide",
            "title": "DaedalMap Agent Guide",
            "description": "High-level guide to the hosted agent API surface and discovery flow.",
            "mimeType": "application/json",
        },
        {
            "uri": "daedalmap://catalog",
            "name": "Catalog",
            "title": "Live Pack Catalog",
            "description": "Machine-readable list of live agent-ready packs.",
            "mimeType": "application/json",
        },
        {
            "uri": "daedalmap://docs/for-agents",
            "name": "For Agents",
            "title": "For Agents",
            "description": "Bot-facing quickstart for the DaedalMap hosted API and MCP lane.",
            "mimeType": "text/markdown",
        },
        {
            "uri": "daedalmap://docs/agent-examples",
            "name": "Agent Examples",
            "title": "Agent Examples",
            "description": "Worked examples for free and paid query flows across the live packs.",
            "mimeType": "text/markdown",
        },
        {
            "uri": "daedalmap://docs/loc-id",
            "name": "loc_id Guide",
            "title": "loc_id Guide",
            "description": "Guide to the shared location identifier system used across packs.",
            "mimeType": "text/markdown",
        },
        {
            "uri": "daedalmap://access",
            "name": "Access Model",
            "title": "Access Model",
            "description": "Current free-versus-paid split for the live hosted packs.",
            "mimeType": "text/markdown",
        },
        {
            "uri": "daedalmap://pack/currency",
            "name": "Currency Pack",
            "title": "Currency Pack Detail",
            "description": "Pack detail and quick-start metadata for the currency lane.",
            "mimeType": "application/json",
        },
        {
            "uri": "daedalmap://pack/earthquakes",
            "name": "Earthquakes Pack",
            "title": "Earthquakes Pack Detail",
            "description": "Pack detail and quick-start metadata for the earthquakes lane.",
            "mimeType": "application/json",
        },
        {
            "uri": "daedalmap://pack/volcanoes",
            "name": "Volcanoes Pack",
            "title": "Volcanoes Pack Detail",
            "description": "Pack detail and quick-start metadata for the volcanoes lane.",
            "mimeType": "application/json",
        },
        {
            "uri": "daedalmap://pack/tsunamis",
            "name": "Tsunamis Pack",
            "title": "Tsunamis Pack Detail",
            "description": "Pack detail and quick-start metadata for the tsunamis lane.",
            "mimeType": "application/json",
        },
        {
            "uri": "daedalmap://links",
            "name": "Public Links",
            "title": "Canonical Public Links",
            "description": "Canonical public URLs for docs, MCP, and hosted API endpoints.",
            "mimeType": "text/markdown",
            "annotations": {"readOnlyHint": True},
        },
    ]


def _read_resource(uri: str) -> dict[str, Any] | None:
    app_url = _public_app_url()
    site_url = _public_site_url()
    if uri == "daedalmap://guide":
        return _resource_text_result(
            uri,
            json.dumps(
                {
                    "guide_url": f"{app_url}/api/v1/guide",
                    "catalog_url": f"{app_url}/api/v1/catalog",
                    "packs_url_template": f"{app_url}/api/v1/packs/{{pack_id}}",
                    "query_url": f"{app_url}/api/v1/query/dataset",
                    "mcp_url": f"{app_url}/mcp",
                    "docs_url": f"{site_url}/docs/for-agents",
                    "current_access_model": {
                        "currency": "free",
                        "volcanoes": "free",
                        "earthquakes": "paid_x402_base_usdc",
                        "tsunamis": "paid_x402_base_usdc",
                    },
                },
                indent=2,
            ),
            mime_type="application/json",
        )
    if uri == "daedalmap://catalog":
        payload = load_api_catalog() or {"packs": []}
        return _resource_text_result(uri, json.dumps(payload, ensure_ascii=False, indent=2), mime_type="application/json")
    if uri.startswith("daedalmap://pack/"):
        pack_id = uri.rsplit("/", 1)[-1].strip()
        payload = load_api_pack_detail(pack_id)
        if not payload:
            payload = {"error": "Pack not found", "pack_id": pack_id}
        return _resource_text_result(uri, json.dumps(payload, ensure_ascii=False, indent=2), mime_type="application/json")
    if uri == "daedalmap://docs/for-agents":
        return _resource_text_result(
            uri,
            (
                "# For Agents\n\n"
                "Use the hosted discovery lane first.\n\n"
                f"- Catalog: {app_url}/api/v1/catalog\n"
                f"- Pack detail: {app_url}/api/v1/packs/{{pack_id}}\n"
                f"- MCP: {app_url}/mcp\n"
                f"- Full docs: {site_url}/docs/for-agents\n\n"
                "Current live hosted packs:\n"
                "- currency: free\n"
                "- volcanoes: free\n"
                "- earthquakes: paid via x402 on Base USDC\n"
                "- tsunamis: paid via x402 on Base USDC\n"
            ),
        )
    if uri == "daedalmap://docs/agent-examples":
        return _resource_text_result(
            uri,
            (
                "# Agent Examples\n\n"
                f"Canonical examples live at {site_url}/docs/agent-examples.\n\n"
                "Question shapes supported today include:\n"
                "- largest earthquake in a time range\n"
                "- count of earthquakes above a threshold in a location and time range\n"
                "- largest volcanic event in a time range\n"
                "- count of tsunamis above a water-height threshold in a location and time range\n"
                "- historical FX rates for one or more countries at daily, weekly, or monthly granularity\n"
            ),
        )
    if uri == "daedalmap://docs/loc-id":
        return _resource_text_result(
            uri,
            (
                "# loc_id Guide\n\n"
                f"Read the full guide at {site_url}/docs/loc-id.\n\n"
                "loc_id is the shared geographic key used across packs. Country and hierarchical regional ids are common, "
                "but tsunami examples can also use ocean-region ids such as XOO."
            ),
        )
    if uri == "daedalmap://access":
        return _resource_text_result(
            uri,
            (
                "# Access Model\n\n"
                "Live hosted pack access split:\n"
                "- currency: free\n"
                "- volcanoes: free\n"
                "- earthquakes: paid via x402 on Base mainnet USDC\n"
                "- tsunamis: paid via x402 on Base mainnet USDC\n\n"
                "Discovery endpoints are always free:\n"
                f"- {app_url}/api/v1/guide\n"
                f"- {app_url}/api/v1/catalog\n"
                f"- {app_url}/api/v1/packs/{{pack_id}}\n"
            ),
        )
    if uri == "daedalmap://links":
        return _resource_text_result(
            uri,
            (
                "# Canonical Public Links\n\n"
                f"- Site docs index: {site_url}/docs\n"
                f"- For Agents: {site_url}/docs/for-agents\n"
                f"- Agent Examples: {site_url}/docs/agent-examples\n"
                f"- loc_id Guide: {site_url}/docs/loc-id\n"
                f"- MCP endpoint: {app_url}/mcp\n"
                f"- Guide endpoint: {app_url}/api/v1/guide\n"
                f"- Catalog endpoint: {app_url}/api/v1/catalog\n"
            ),
        )
    return None


def _build_named_dataset_payload(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    payload = _ensure_request_id(arguments, tool_name)
    if tool_name == "get_fx_rates":
        payload.setdefault("metrics", ["local_per_usd"])
        payload["pack_id"] = "currency"
        payload.pop("source_id", None)
        return payload

    source_ids = {
        "get_earthquake_events": "earthquakes_events",
        "get_volcanic_activity": "volcanoes_events",
        "get_tsunami_events": "tsunamis_events",
    }
    payload["source_id"] = source_ids[tool_name]
    payload.pop("pack_id", None)
    return payload


async def _execute_paid_tool(request: Request, tool_name: str, arguments: dict[str, Any], rpc_request_id: Any) -> Response:
    if tool_name == "query_dataset":
        payload = _ensure_request_id(arguments, tool_name)
    else:
        payload = _build_named_dataset_payload(tool_name, arguments)

    response = await execute_query_dataset_payload(request, payload)
    if response.status_code == 402 and response.headers.get("payment-required"):
        response.headers["MCP-Protocol-Version"] = MCP_PROTOCOL_VERSION
        response.headers["Cache-Control"] = "no-store"
        return response

    raw_body = getattr(response, "body", b"") or b""
    parsed_body: Any
    try:
        parsed_body = json.loads(raw_body.decode("utf-8"))
    except Exception:
        parsed_body = {"status_code": response.status_code, "body": raw_body.decode("utf-8", errors="replace")}

    if response.status_code == 200:
        return _jsonrpc_response(_tool_result(parsed_body), rpc_request_id)

    return _jsonrpc_response(_tool_result(parsed_body, is_error=True), rpc_request_id)


@router.get("/mcp")
@router.get("/mcp/{pack_id}")
async def mcp_endpoint_info(pack_id: str | None = None):
    normalized_pack_id = _normalize_pack_id(pack_id)
    if pack_id and not normalized_pack_id:
        return JSONResponse({"error": "Pack MCP facade not found"}, status_code=404)
    response = JSONResponse(
        {
            "serverInfo": get_server_info(normalized_pack_id),
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "transport": "streamable-http",
            "tools": [tool["name"] for tool in _tool_definitions()],
        }
    )
    response.headers["MCP-Protocol-Version"] = MCP_PROTOCOL_VERSION
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/mcp")
@router.post("/mcp/{pack_id}")
async def mcp_endpoint(request: Request, pack_id: str | None = None):
    normalized_pack_id = _normalize_pack_id(pack_id)
    if pack_id and not normalized_pack_id:
        return JSONResponse({"error": "Pack MCP facade not found"}, status_code=404)
    if not _mcp_origin_allowed(request):
        return JSONResponse({"error": "Origin not allowed"}, status_code=403)

    try:
        body = await request.json()
    except Exception:
        return _jsonrpc_error(None, -32700, "Parse error", status_code=400)

    if not isinstance(body, dict):
        return _jsonrpc_error(None, -32600, "Invalid Request", status_code=400)

    request_id = body.get("id")
    method = str(body.get("method") or "").strip()
    params = body.get("params") or {}
    if params and not isinstance(params, dict):
        return _jsonrpc_error(request_id, -32602, "Invalid params")

    protocol_header = str(request.headers.get("MCP-Protocol-Version") or "").strip()
    if method != "initialize" and protocol_header and protocol_header not in SUPPORTED_PROTOCOL_VERSIONS:
        return _jsonrpc_error(
            request_id,
            -32000,
            "Unsupported protocol version",
            data={"supported": sorted(SUPPORTED_PROTOCOL_VERSIONS)},
            status_code=400,
        )

    if method == "initialize":
        requested_version = str(params.get("protocolVersion") or "").strip()
        negotiated = requested_version if requested_version in SUPPORTED_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSION
        response = _jsonrpc_response(
            {
                "protocolVersion": negotiated,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"listChanged": False},
                    "prompts": {"listChanged": False},
                },
                "serverInfo": get_server_info(normalized_pack_id),
                "instructions": (
                    "Use tools/list, resources/list, and prompts/list to discover available capabilities. Free discovery tools require no payment. "
                    "Paid tools can return HTTP 402 with x402 challenge headers when payment is required."
                ),
            },
            request_id,
        )
        response.headers["MCP-Protocol-Version"] = negotiated
        return response

    if method in {"notifications/initialized", "notifications/cancelled"}:
        response = Response(status_code=202)
        response.headers["MCP-Protocol-Version"] = MCP_PROTOCOL_VERSION
        response.headers["Cache-Control"] = "no-store"
        return response

    if method == "ping":
        return _jsonrpc_response({}, request_id)

    if method == "tools/list":
        return _jsonrpc_response({"tools": _tool_definitions()}, request_id)

    if method == "resources/list":
        return _jsonrpc_response({"resources": _resource_definitions()}, request_id)

    if method == "resources/read":
        uri = str(params.get("uri") or "").strip()
        if not uri:
            return _jsonrpc_error(request_id, -32602, "Resource uri is required")
        payload = _read_resource(uri)
        if not payload:
            return _jsonrpc_error(request_id, -32602, f"Resource '{uri}' not found")
        return _jsonrpc_response(payload, request_id)

    if method == "prompts/list":
        return _jsonrpc_response({"prompts": _prompt_definitions()}, request_id)

    if method == "prompts/get":
        prompt_name = str(params.get("name") or "").strip()
        arguments = params.get("arguments") or {}
        if not prompt_name:
            return _jsonrpc_error(request_id, -32602, "Prompt name is required")
        if arguments and not isinstance(arguments, dict):
            return _jsonrpc_error(request_id, -32602, "Prompt arguments must be an object")
        payload = _render_prompt(prompt_name, arguments)
        if not payload:
            return _jsonrpc_error(request_id, -32602, f"Prompt '{prompt_name}' not found")
        return _jsonrpc_response(payload, request_id)

    if method != "tools/call":
        return _jsonrpc_error(request_id, -32601, f"Method '{method}' not found")

    tool_name = str(params.get("name") or "").strip()
    arguments = params.get("arguments") or {}
    if not tool_name:
        return _jsonrpc_error(request_id, -32602, "Tool name is required")
    if arguments and not isinstance(arguments, dict):
        return _jsonrpc_error(request_id, -32602, "Tool arguments must be an object")

    if tool_name == "get_catalog":
        payload = load_api_catalog() or {"packs": []}
        return _jsonrpc_response(_tool_result(payload), request_id)

    if tool_name == "get_pack":
        pack_id = str(arguments.get("pack_id") or "").strip()
        if not pack_id:
            return _jsonrpc_error(request_id, -32602, "pack_id is required")
        payload = load_api_pack_detail(pack_id)
        if not payload:
            return _jsonrpc_response(_tool_result({"error": "Pack not found", "pack_id": pack_id}, is_error=True), request_id)
        return _jsonrpc_response(_tool_result(payload), request_id)

    if tool_name not in {
        "get_earthquake_events",
        "get_volcanic_activity",
        "get_tsunami_events",
        "get_fx_rates",
        "query_dataset",
    }:
        return _jsonrpc_error(request_id, -32601, f"Tool '{tool_name}' not found")

    return await _execute_paid_tool(request, tool_name, arguments, request_id)
