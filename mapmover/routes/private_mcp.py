from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from mapmover.private_mcp_loader import get_private_mcp_provider


router = APIRouter()


def _provider_not_found(provider_slug: str) -> JSONResponse:
    return JSONResponse(
        {
            "error": "Private MCP provider is not mounted in this runtime.",
            "provider_slug": provider_slug,
        },
        status_code=404,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/mcp-private/{provider_slug}")
async def private_mcp_info(provider_slug: str, request: Request):
    provider = get_private_mcp_provider(provider_slug)
    if provider is None:
        return _provider_not_found(provider_slug)
    return await provider.handle_get_info(request)


@router.post("/mcp-private/{provider_slug}")
async def private_mcp_endpoint(provider_slug: str, request: Request):
    provider = get_private_mcp_provider(provider_slug)
    if provider is None:
        return _provider_not_found(provider_slug)
    return await provider.handle_post_request(request)
