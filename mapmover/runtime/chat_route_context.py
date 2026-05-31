"""Shared request-context helpers for chat-like route shells."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import Response

from mapmover.auth_context import build_session_cache_key, get_authenticated_user_async
from mapmover.llm_usage import classify_caller, extract_qa_http_label, extract_qa_suite_metadata
from mapmover.logging_analytics import hash_ip_for_analytics
from mapmover.routes.chat_shared import _catalog_surface_for_request
from mapmover.security import get_client_ip


_QA_CALLER_KINDS = {"qa_suite", "qa_http_suite"}


@dataclass
class BaseChatRouteContext:
    frontend_session_id: str
    auth_user: dict | None
    client_ip: str | None
    caller_ctx: dict
    user_id: str | None
    session_id: str
    catalog_surface: str | None
    qa_suite_metadata: dict


async def build_base_chat_route_context(
    req: Request,
    body: dict,
) -> tuple[BaseChatRouteContext | None, Response | None]:
    frontend_session_id = body.get("sessionId", "anonymous")
    auth_user = await get_authenticated_user_async(req)
    client_ip = get_client_ip(req)
    caller_ctx = classify_caller(
        auth_user=auth_user,
        ip_hash=hash_ip_for_analytics(client_ip),
        qa_http_label=extract_qa_http_label(req.headers),
    )
    # Only honor QA suite-attribution headers when the caller is already classified
    # as QA. Otherwise an anonymous client could pollute cost-attribution metadata
    # by spoofing the suite/run-id headers. Same trust pattern as the QA label
    # header above.
    raw_qa_metadata = extract_qa_suite_metadata(req.headers)
    qa_suite_metadata = raw_qa_metadata if caller_ctx.get("caller_kind") in _QA_CALLER_KINDS else {}
    user_id = auth_user.get("id") if auth_user else None
    session_id = build_session_cache_key(frontend_session_id, auth_user)
    catalog_surface, surface_error = _catalog_surface_for_request(req, body, auth_user)
    if surface_error:
        return None, surface_error
    return (
        BaseChatRouteContext(
            frontend_session_id=frontend_session_id,
            auth_user=auth_user,
            client_ip=client_ip,
            caller_ctx=caller_ctx,
            user_id=user_id,
            session_id=session_id,
            catalog_surface=catalog_surface,
            qa_suite_metadata=qa_suite_metadata,
        ),
        None,
    )
