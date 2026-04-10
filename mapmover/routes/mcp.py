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
    "title": "DaedalMap Geographic Data Intelligence",
    "version": "1.0.0",
}


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
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                    "output": {"type": "object", "description": "Optional output controls such as response format hints."},
                },
                "required": ["metrics", "filters"],
                "additionalProperties": False,
            },
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
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                    "output": {"type": "object", "description": "Optional output controls such as response format hints."},
                },
                "required": ["metrics", "filters"],
                "additionalProperties": False,
            },
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
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                    "output": {"type": "object", "description": "Optional output controls such as response format hints."},
                },
                "required": ["metrics", "filters"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_fx_rates",
            "title": "Get FX Rates",
            "description": "Free tool. Queries the currency pack and routes by filters.time.granularity to daily, weekly, or monthly FX data.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "Optional caller-supplied request id for tracing and idempotency."},
                    "metrics": {"type": "array", "items": {"type": "string"}, "description": "Optional metric ids. Defaults to 'local_per_usd' for FX rate queries."},
                    "filters": {"type": "object", "description": "Structured filters including currencies, time range, and granularity."},
                    "sort": {"anyOf": [{"type": "array"}, {"type": "object"}], "description": "Optional sort instructions for row-returning queries."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
                    "output": {"type": "object", "description": "Optional output controls such as response format hints."},
                },
                "required": ["filters"],
                "additionalProperties": False,
            },
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
                    "limit": {"type": "integer", "minimum": 1},
                    "output": {"type": "object", "description": "Optional output controls such as response format hints."},
                },
                "additionalProperties": False,
            },
        },
    ]


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
async def mcp_endpoint_info():
    response = JSONResponse(
        {
            "serverInfo": SERVER_INFO,
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "transport": "streamable-http",
            "tools": [tool["name"] for tool in _tool_definitions()],
        }
    )
    response.headers["MCP-Protocol-Version"] = MCP_PROTOCOL_VERSION
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/mcp")
async def mcp_endpoint(request: Request):
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
                },
                "serverInfo": SERVER_INFO,
                "instructions": (
                    "Use tools/list to discover available tools. Free discovery tools require no payment. "
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
