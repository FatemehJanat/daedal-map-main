from __future__ import annotations

import os
from urllib.parse import urljoin

import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from mapmover.paths import SITE_URL
from mapmover.private_mcp_loader import get_private_mcp_provider


router = APIRouter()
PRIVATE_MCP_PROXY_TIMEOUT_SECONDS = 15.0
PROXY_RESPONSE_HEADERS = (
    "Cache-Control",
    "Content-Type",
    "MCP-Protocol-Version",
    "Retry-After",
    "WWW-Authenticate",
)


def _provider_not_found(provider_slug: str) -> JSONResponse:
    return JSONResponse(
        {
            "error": "Private MCP provider is not mounted in this runtime.",
            "provider_slug": provider_slug,
        },
        status_code=404,
        headers={"Cache-Control": "no-store"},
    )


def _private_mcp_proxy_base_url() -> str:
    configured = str(os.getenv("PRIVATE_MCP_PROXY_BASE_URL", "")).strip().rstrip("/")
    return configured or str(SITE_URL or "").strip().rstrip("/")


def _private_mcp_internal_token() -> str:
    return str(os.getenv("CLOUD_INTERNAL_API_TOKEN", "")).strip()


def _forwarded_request_headers(request: Request) -> dict[str, str]:
    headers = {
        "Accept": request.headers.get("accept", "application/json"),
        "Content-Type": request.headers.get("content-type", "application/json"),
    }
    authorization = str(request.headers.get("authorization") or "").strip()
    if authorization:
        headers["Authorization"] = authorization
    internal_token = _private_mcp_internal_token()
    if internal_token:
        headers["x-internal-api-key"] = internal_token
    protocol_version = str(request.headers.get("mcp-protocol-version") or "").strip()
    if protocol_version:
        headers["MCP-Protocol-Version"] = protocol_version
    return headers


def _proxy_response_headers(source_headers: requests.structures.CaseInsensitiveDict[str]) -> dict[str, str]:
    forwarded: dict[str, str] = {}
    for key in PROXY_RESPONSE_HEADERS:
        value = source_headers.get(key)
        if value:
            forwarded[key] = value
    return forwarded


def _private_mcp_proxy_response(provider_slug: str, method: str, *, body: bytes | None = None, headers: dict[str, str] | None = None) -> Response:
    base_url = _private_mcp_proxy_base_url()
    if not base_url:
        return _provider_not_found(provider_slug)

    target_url = urljoin(f"{base_url}/", f"/internal/mcp/{provider_slug}")
    request_headers = headers or {}
    try:
        response = requests.request(
            method,
            target_url,
            data=body,
            headers=request_headers,
            timeout=PRIVATE_MCP_PROXY_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return JSONResponse(
            {
                "error": "Private MCP upstream request failed.",
                "provider_slug": provider_slug,
                "detail": str(exc),
            },
            status_code=502,
            headers={"Cache-Control": "no-store"},
        )
    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=response.headers.get("Content-Type"),
        headers=_proxy_response_headers(response.headers),
    )


@router.get("/mcp-private/{provider_slug}")
async def private_mcp_info(provider_slug: str, request: Request):
    provider = get_private_mcp_provider(provider_slug)
    if provider is None:
        return _private_mcp_proxy_response(
            provider_slug,
            "GET",
            headers=_forwarded_request_headers(request),
        )
    return await provider.handle_get_info(request)


@router.post("/mcp-private/{provider_slug}")
async def private_mcp_endpoint(provider_slug: str, request: Request):
    provider = get_private_mcp_provider(provider_slug)
    if provider is None:
        return _private_mcp_proxy_response(
            provider_slug,
            "POST",
            body=await request.body(),
            headers=_forwarded_request_headers(request),
        )
    return await provider.handle_post_request(request)
