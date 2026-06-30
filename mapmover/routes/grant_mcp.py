from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from mapmover.grants import grant_mcp_module
from mapmover.security import get_client_ip, rate_limiter


router = APIRouter()

MCP_PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {
    "name": "com.daedalmap/grants-private",
    "title": "DaedalMap Grants Private MCP",
    "version": "0.1.0",
}
INSTRUCTIONS = (
    "Private phase-aware grant MCP. This server supports only pre-submission "
    "grant workflow phases: prospect research, proposal development, and "
    "submission support. Start with grant_intake_or_update_project, then call "
    "grant_analyze_current_phase. Do not treat this server as a post-award "
    "compliance tool."
)


def _grant_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "grant_intake_or_update_project",
            "title": "Grant Intake Or Update Project",
            "description": "Create or update the normalized project profile and infer the current pre-submission grant phase.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_input": {"type": "string", "description": "User project description or new project facts."},
                    "session_id": {"type": "string", "description": "Optional existing grant MCP session id."},
                    "project_label": {"type": "string", "description": "Optional project label for the session."},
                    "country_code": {"type": "string", "description": "Optional explicit country code such as US or CAN."},
                    "phase_hint": {
                        "type": "string",
                        "enum": [
                            "phase_1_prospect_research",
                            "phase_2_proposal_development",
                            "phase_3_submission_support",
                        ],
                    },
                    "profile_overrides": {"type": "object", "description": "Optional structured profile fields already known."},
                    "allow_inference": {"type": "boolean", "description": "Allow inference of non-critical fields from text. Default true."},
                },
                "required": ["project_input"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": False},
        },
        {
            "name": "grant_analyze_current_phase",
            "title": "Grant Analyze Current Phase",
            "description": "Run the correct phase-specific grant workflow for the stored session state.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Existing grant MCP session id."},
                    "analysis_request": {"type": "string", "description": "Optional immediate follow-up request for this grant phase."},
                    "phase_override": {
                        "type": "string",
                        "enum": [
                            "phase_1_prospect_research",
                            "phase_2_proposal_development",
                            "phase_3_submission_support",
                        ],
                    },
                    "depth": {"type": "string", "enum": ["light", "standard", "full"]},
                    "refresh_profile_from_text": {"type": "boolean", "description": "Whether to merge the new request text into session profile state. Default true."},
                },
                "required": ["session_id"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": False},
        },
        {
            "name": "grant_set_phase",
            "title": "Grant Set Phase",
            "description": "Explicitly override the current pre-submission grant phase for an existing session.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "phase_id": {
                        "type": "string",
                        "enum": [
                            "phase_1_prospect_research",
                            "phase_2_proposal_development",
                            "phase_3_submission_support",
                        ],
                    },
                },
                "required": ["session_id", "phase_id"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": False},
        },
        {
            "name": "grant_select_target_program",
            "title": "Grant Select Target Program",
            "description": "Set the active target program from the current shortlist for an existing session.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "program_id": {"type": "string"},
                },
                "required": ["session_id", "program_id"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": False},
        },
    ]


def _jsonrpc_response(result: dict[str, Any], request_id: Any) -> JSONResponse:
    response = JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})
    response.headers["MCP-Protocol-Version"] = MCP_PROTOCOL_VERSION
    response.headers["Cache-Control"] = "no-store"
    return response


def _jsonrpc_error(request_id: Any, code: int, message: str, *, data: dict[str, Any] | None = None, status_code: int = 200) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if data:
        error["data"] = data
    response = JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": error}, status_code=status_code)
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


def _parse_env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _grant_mcp_tokens() -> set[str]:
    raw = str(os.getenv("GRANT_MCP_ACCESS_TOKENS", "")).strip()
    if not raw:
        return set()
    return {token.strip() for token in raw.split(",") if token.strip()}


def _grant_mcp_authorized(request: Request) -> bool:
    header = str(request.headers.get("Authorization") or "").strip()
    if not header.lower().startswith("bearer "):
        return False
    token = header.split(" ", 1)[1].strip()
    return token in _grant_mcp_tokens()


def _rate_limit_response(request_id: Any, retry_after: int) -> JSONResponse:
    response = _jsonrpc_error(
        request_id,
        -32000,
        "Grant MCP rate limit exceeded",
        data={"retry_after": retry_after},
        status_code=429,
    )
    response.headers["Retry-After"] = str(retry_after)
    return response


def _apply_rate_limit(request: Request, request_id: Any) -> JSONResponse | None:
    limit = _parse_env_int("GRANT_MCP_RATE_LIMIT", 30)
    window_seconds = _parse_env_int("GRANT_MCP_RATE_WINDOW_SECONDS", 60)
    caller = get_client_ip(request) or "unknown"
    allowed, retry_after = rate_limiter.check(
        f"grant-mcp:{caller}",
        limit=limit,
        window_seconds=window_seconds,
    )
    if allowed:
        return None
    return _rate_limit_response(request_id, retry_after)


@router.get("/mcp-private/grants")
async def grant_mcp_info():
    response = JSONResponse(
        {
            "serverInfo": SERVER_INFO,
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "transport": "streamable-http",
            "auth": "bearer",
            "tools": [tool["name"] for tool in _grant_tool_definitions()],
            "private": True,
        }
    )
    response.headers["MCP-Protocol-Version"] = MCP_PROTOCOL_VERSION
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/mcp-private/grants")
async def grant_mcp_endpoint(request: Request):
    if not _grant_mcp_authorized(request):
        return JSONResponse(
            {"error": "Unauthorized. Provide a Bearer token configured in GRANT_MCP_ACCESS_TOKENS."},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        body = await request.json()
    except Exception:
        return _jsonrpc_error(None, -32700, "Parse error", status_code=400)

    if not isinstance(body, dict):
        return _jsonrpc_error(None, -32600, "Invalid Request", status_code=400)

    request_id = body.get("id")
    rate_limit_response = _apply_rate_limit(request, request_id)
    if rate_limit_response:
        return rate_limit_response

    method = str(body.get("method") or "").strip()
    params = body.get("params") or {}
    if params and not isinstance(params, dict):
        return _jsonrpc_error(request_id, -32602, "Invalid params")

    if method == "initialize":
        return _jsonrpc_response(
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"listChanged": False},
                    "prompts": {"listChanged": False},
                },
                "serverInfo": SERVER_INFO,
                "instructions": INSTRUCTIONS,
            },
            request_id,
        )

    if method in {"notifications/initialized", "notifications/cancelled"}:
        response = JSONResponse({}, status_code=202)
        response.headers["MCP-Protocol-Version"] = MCP_PROTOCOL_VERSION
        response.headers["Cache-Control"] = "no-store"
        return response

    if method == "ping":
        return _jsonrpc_response({}, request_id)

    if method == "tools/list":
        return _jsonrpc_response({"tools": _grant_tool_definitions()}, request_id)

    if method == "resources/list":
        return _jsonrpc_response({"resources": []}, request_id)

    if method == "prompts/list":
        return _jsonrpc_response({"prompts": []}, request_id)

    if method != "tools/call":
        return _jsonrpc_error(request_id, -32601, f"Method '{method}' not found")

    tool_name = str(params.get("name") or "").strip()
    arguments = params.get("arguments") or {}
    if not tool_name:
        return _jsonrpc_error(request_id, -32602, "Tool name is required")
    if arguments and not isinstance(arguments, dict):
        return _jsonrpc_error(request_id, -32602, "Tool arguments must be an object")

    if tool_name not in {tool["name"] for tool in _grant_tool_definitions()}:
        return _jsonrpc_error(request_id, -32601, f"Tool '{tool_name}' not found")

    result = grant_mcp_module.call_tool(tool_name, arguments)
    is_error = result.get("outcome") in {
        grant_mcp_module.OUTCOME_ERROR,
        grant_mcp_module.OUTCOME_OUT_OF_SCOPE,
        grant_mcp_module.OUTCOME_UNSUPPORTED_COUNTRY,
        grant_mcp_module.OUTCOME_UNSUPPORTED_CLAIM,
    }
    return _jsonrpc_response(_tool_result(result, is_error=is_error), request_id)
