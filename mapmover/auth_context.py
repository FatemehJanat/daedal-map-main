"""
Helpers for optional Supabase-backed auth context on API requests.

This is intentionally lightweight:
- no auth requirement for public use
- verifies bearer tokens against Supabase when present
- caches verification briefly to avoid repeated auth round-trips
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, Optional

import httpx
import requests
from fastapi import Request

from . import logger


_async_client: Optional[httpx.AsyncClient] = None
_async_client_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_async_client() -> httpx.AsyncClient:
    """Lazily create a shared httpx.AsyncClient for Supabase auth verification.

    Reusing one client keeps TLS sessions warm across requests, which matters
    when many authenticated requests miss the in-memory cache simultaneously.
    """
    global _async_client, _async_client_loop
    current_loop = asyncio.get_running_loop()
    if _async_client is None or _async_client_loop is not current_loop:
        _async_client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
        _async_client_loop = current_loop
    return _async_client


AUTH_CACHE_TTL_SECONDS = 300
AUTH_CACHE_MAXSIZE = 1024
_auth_cache: Dict[str, Dict[str, Any]] = {}


def _get_bearer_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("authorization", "").strip()
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header[7:].strip()
    return token or None


def _get_supabase_auth_config() -> Optional[Dict[str, str]]:
    url = os.getenv("SUPABASE_URL", "").strip()
    anon_key = os.getenv("SUPABASE_ANON_KEY", "").strip()
    if not url or not anon_key:
        return None
    return {"url": url.rstrip("/"), "anon_key": anon_key}


def _get_cached_user(token: str) -> Optional[Dict[str, Any]]:
    entry = _auth_cache.get(token)
    if not entry:
        return None
    if time.time() - entry["cached_at"] > AUTH_CACHE_TTL_SECONDS:
        _auth_cache.pop(token, None)
        return None
    return entry["user"]


def _cache_user(token: str, user: Optional[Dict[str, Any]]) -> None:
    if len(_auth_cache) >= AUTH_CACHE_MAXSIZE:
        oldest_token = min(_auth_cache.items(), key=lambda item: item[1].get("cached_at", 0))[0]
        _auth_cache.pop(oldest_token, None)
    _auth_cache[token] = {
        "cached_at": time.time(),
        "user": user,
    }


def _try_cache_path(
    request: Request,
    *,
    force_refresh: bool = False,
) -> tuple[bool, Optional[Dict[str, Any]], Optional[str], Optional[Dict[str, str]]]:
    """Shared fast-path: per-request state cache, then per-token in-memory cache.

    Returns (resolved, user, token, config). When `resolved` is True, the caller
    should return `user` immediately. When False, the caller must verify against
    Supabase using `token` and `config`.
    """
    if not force_refresh:
        cached_request_user = getattr(request.state, "authenticated_user_context", None)
        if cached_request_user is not None:
            return True, cached_request_user, None, None

    token = _get_bearer_token(request)
    if not token:
        request.state.authenticated_user_context = None
        return True, None, None, None

    if not force_refresh:
        cached = _get_cached_user(token)
        if cached is not None:
            request.state.authenticated_user_context = cached
            return True, cached, None, None

    config = _get_supabase_auth_config()
    if not config:
        request.state.authenticated_user_context = None
        return True, None, None, None

    return False, None, token, config


def get_authenticated_user(request: Request, *, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    """Sync entry point. Blocks the calling thread on cache miss.

    Use `get_authenticated_user_async` from async code paths to avoid blocking
    the event loop on Supabase verification.
    """
    resolved, user, token, config = _try_cache_path(request, force_refresh=force_refresh)
    if resolved:
        return user

    try:
        response = requests.get(
            f"{config['url']}/auth/v1/user",
            headers={
                "apikey": config["anon_key"],
                "Authorization": f"Bearer {token}",
            },
            timeout=5,
        )
        if response.status_code != 200:
            _cache_user(token, None)
            request.state.authenticated_user_context = None
            return None

        user = response.json()
        _cache_user(token, user)
        request.state.authenticated_user_context = user
        return user
    except Exception as exc:
        logger.warning(f"Supabase user verification failed: {exc}")
        request.state.authenticated_user_context = None
        return None


async def get_authenticated_user_async(request: Request, *, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    """Async entry point that does not block the event loop on cache miss.

    Identical contract to `get_authenticated_user`. The cache hit path is
    synchronous in-memory work; only the Supabase verification fetch is awaited.
    """
    resolved, user, token, config = _try_cache_path(request, force_refresh=force_refresh)
    if resolved:
        return user

    try:
        client = _get_async_client()
        response = await client.get(
            f"{config['url']}/auth/v1/user",
            headers={
                "apikey": config["anon_key"],
                "Authorization": f"Bearer {token}",
            },
        )
        if response.status_code != 200:
            _cache_user(token, None)
            request.state.authenticated_user_context = None
            return None

        user = response.json()
        _cache_user(token, user)
        request.state.authenticated_user_context = user
        return user
    except Exception as exc:
        logger.warning(f"Supabase user verification failed: {exc}")
        request.state.authenticated_user_context = None
        return None


def build_session_cache_key(session_id: str, user: Optional[Dict[str, Any]]) -> str:
    """
    Build the backend session cache key.

    Authenticated users get a user-scoped cache namespace.
    Anonymous users keep their existing session ID behavior.
    """
    base_session_id = (session_id or "anonymous").strip() or "anonymous"
    user_id = (user or {}).get("id")
    if user_id:
        return f"user:{user_id}:{base_session_id}"
    return base_session_id
