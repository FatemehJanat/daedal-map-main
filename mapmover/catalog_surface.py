from __future__ import annotations

import ipaddress
import os
from contextlib import contextmanager
from contextvars import ContextVar


_catalog_surface_override: ContextVar[str | None] = ContextVar("catalog_surface_override", default=None)


def normalize_catalog_surface(value) -> str:
    text = str(value or "").strip().lower()
    return "wip" if text == "wip" else "published"


def get_catalog_surface_override() -> str | None:
    value = _catalog_surface_override.get()
    return normalize_catalog_surface(value) if value else None


@contextmanager
def catalog_surface_scope(surface: str | None):
    normalized = get_catalog_surface_override() if surface is None else normalize_catalog_surface(surface)
    token = _catalog_surface_override.set(normalized)
    try:
        yield normalized
    finally:
        _catalog_surface_override.reset(token)


def _is_loopback_host(value: str) -> bool:
    host = (value or "").strip().lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def request_can_use_wip_catalog(request, auth_user: dict | None) -> bool:
    if not auth_user:
        return False

    service_key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if not service_key:
        deployment = str(os.getenv("DEPLOYMENT", "")).strip().lower()
        client = getattr(request, "client", None)
        client_host = getattr(client, "host", "") if client else ""
        return deployment == "local" and _is_loopback_host(client_host)

    try:
        from supabase_client import SupabaseClient

        supa = SupabaseClient()
        context = supa.get_user_entitlement_context(auth_user.get("id"))
        if not context or context.get("error"):
            return False
        return context.get("plan_id") == "master" or bool(context.get("is_admin"))
    except Exception:
        return False
