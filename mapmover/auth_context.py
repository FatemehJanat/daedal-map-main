"""
Open-core auth helpers for the public runtime.

The public repo does not ship DaedalMap's private hosted auth integration.
By default, the open runtime operates in guest/local mode and does not resolve
authenticated hosted users on API requests.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Request


def get_authenticated_user(request: Request, *, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    del force_refresh
    request.state.authenticated_user_context = None
    return None


async def get_authenticated_user_async(request: Request, *, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    del force_refresh
    request.state.authenticated_user_context = None
    return None


def build_session_cache_key(session_id: str, user: Optional[Dict[str, Any]]) -> str:
    """
    Build the backend session cache key.

    Open-core runtime defaults to guest-only behavior, but the helper preserves
    the old user-scoped namespace shape for any future generic auth bridge.
    """
    base_session_id = (session_id or "anonymous").strip() or "anonymous"
    user_id = (user or {}).get("id")
    if user_id:
        return f"user:{user_id}:{base_session_id}"
    return base_session_id
