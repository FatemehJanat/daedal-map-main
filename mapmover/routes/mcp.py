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
                    "request_id": {"type": "string"},
                    "metrics": {"type": "array", "items": {"type": "string"}},
                    "filters": {"type": "object"},
                    "sort": {"anyOf": [{"type": "array"}, {"type": "object"}]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                    "output": {"type": "object"},
                },
                "required": ["metrics", "filters"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_volcanic_activity",
            "title": "Get Volcanic Activity",
            "description": "Paid x402 tool. Queries volcanoes_events for eruption records and volcanic activity metrics.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string"},
                    "metrics": {"type": "array", "items": {"type": "string"}},
                    "filters": {"type": "object"},
                    "sort": {"anyOf": [{"type": "array"}, {"type": "object"}]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                    "output": {"type": "object"},
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
                    "request_id": {"type": "string"},
                    "metrics": {"type": "array", "items": {"type": "string"}},
                    "filters": {"type": "object"},
                    "sort": {"anyOf": [{"type": "array"}, {"type": "object"}]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                    "output": {"type": "object"},
                },
                "required": ["metrics", "filters"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_fx_rates",
            "title": "Get FX Rates",
            "description": "Paid x402 tool. Queries the currency pack and routes by filters.time.granularity to daily, weekly, or monthly FX data.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string"},
                    "metrics": {"type": "array", "items": {"type": "string"}},
                    "filters": {"type": "object"},
                    "sort": {"anyOf": [{"type": "array"}, {"type": "object"}]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
                    "output": {"type": "object"},
                },
                "required": ["filters"],
                "additionalProperties": False,
            },
        },
        {
            "name": "query_dataset",
            "title": "Query Dataset",
            "description": "Paid x402 tool. Generic structured query for direct source_id or pack_id access using the same contract as POST /api/v1/query/dataset.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string"},
                    "source_id": {"type": "string"},
                    "pack_id": {"type": "string"},
                    "metrics": {"type": "array", "items": {"type": "string"}},
                    "filters": {"type": "object"},
                    "sort": {"anyOf": [{"type": "array"}, {"type": "object"}]},
                    "limit": {"type": "integer", "minimum": 1},
                    "output": {"type": "object"},
                },
                "additionalProperties": False,
            },
        },
    ]


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
