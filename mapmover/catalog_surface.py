from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar

from mapmover.hosted_runtime_account import load_account_context


_catalog_surface_override: ContextVar[str | None] = ContextVar("catalog_surface_override", default=None)
CATALOG_FILE_SURFACES = {"published", "wip"}
CATALOG_PRODUCT_SURFACES = {"explore", "research", "api", "downloadable"}
DEFAULT_RELEASED_CATALOG_SURFACES = ("explore", "research")


def normalize_catalog_surface(value) -> str:
    text = str(value or "").strip().lower()
    if text == "wip":
        return "wip"
    if text in CATALOG_PRODUCT_SURFACES:
        return text
    return "published"


def catalog_file_surface(value) -> str:
    return "wip" if normalize_catalog_surface(value) == "wip" else "published"


def catalog_product_surface(value) -> str | None:
    normalized = normalize_catalog_surface(value)
    if normalized == "wip":
        return None
    if normalized == "published":
        return "explore"
    return normalized


def normalize_catalog_surfaces(value, *, default: tuple[str, ...] | None = DEFAULT_RELEASED_CATALOG_SURFACES) -> list[str]:
    if isinstance(value, str):
        raw_values = [value]
    elif isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        raw_values = []

    surfaces: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        surface = str(raw or "").strip().lower()
        if surface not in CATALOG_PRODUCT_SURFACES or surface in seen:
            continue
        seen.add(surface)
        surfaces.append(surface)

    if surfaces:
        return sorted(surfaces)
    return sorted(default or ())


def catalog_surface_values(record: dict | None) -> list[str]:
    if not isinstance(record, dict):
        return list(DEFAULT_RELEASED_CATALOG_SURFACES)
    return normalize_catalog_surfaces(record.get("catalog_surfaces"))


def has_catalog_product_surface(record: dict | None, surface: str | None) -> bool:
    normalized = str(surface or "").strip().lower()
    if not normalized:
        return True
    if normalized not in CATALOG_PRODUCT_SURFACES:
        return True
    return normalized in catalog_surface_values(record)


def filter_catalog_for_product_surface(catalog: dict, surface: str | None) -> dict:
    if not isinstance(catalog, dict):
        return {"sources": [], "packs": [], "total_sources": 0, "total_packs": 0}
    normalized = str(surface or "").strip().lower()
    if not normalized:
        return catalog

    sources = [
        dict(source)
        for source in catalog.get("sources", [])
        if isinstance(source, dict) and has_catalog_product_surface(source, normalized)
    ]
    active_source_ids = {source.get("source_id") for source in sources if source.get("source_id")}
    active_pack_ids = {source.get("pack_id") for source in sources if source.get("pack_id")}
    packs = []
    for pack in catalog.get("packs", []):
        if not isinstance(pack, dict):
            continue
        pack_id = pack.get("pack_id")
        pack_source_ids = pack.get("source_ids") if isinstance(pack.get("source_ids"), list) else []
        has_active_source = any(source_id in active_source_ids for source_id in pack_source_ids)
        if (
            (pack_id and pack_id in active_pack_ids)
            or has_active_source
            or has_catalog_product_surface(pack, normalized)
        ):
            packs.append(dict(pack))

    filtered = dict(catalog)
    filtered["sources"] = sources
    filtered["packs"] = packs
    filtered["total_sources"] = len(sources)
    filtered["total_packs"] = len(packs)
    return filtered


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
    """Return whether this caller is allowed to inspect the WIP catalog.

    Hosted requests must carry a verified bearer token whose account context is
    master/admin.  The local wrapper intentionally has a second, loopback-only
    proof: its browser sync writes the same account summary for the local app
    shell.  Without this fallback, a locally signed-in master user can see the
    account UI but the catalog request can race the browser token bootstrap and
    be treated as anonymous.
    """
    if auth_user:
        account_context = load_account_context(str(auth_user.get("id") or ""))
        if account_context is not None:
            return (
                account_context.get("plan_id") == "master"
                or bool(account_context.get("is_admin"))
            )

    deployment = str(os.getenv("DEPLOYMENT", "")).strip().lower()
    client = getattr(request, "client", None)
    client_host = getattr(client, "host", "") if client else ""
    if deployment != "local" or not _is_loopback_host(client_host):
        return False

    try:
        from mapmover.paths import STATE_DIR

        state_path = Path(STATE_DIR) / "local_wrapper_auth_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return False

    return bool(state.get("authenticated")) and (
        state.get("plan_id") == "master" or bool(state.get("is_admin"))
    )


def request_uses_wip_catalog(request, auth_user: dict | None) -> bool:
    """Return whether this request should serve WIP, not merely access it.

    WIP selection is a local-only explicit switch.  Authorization alone must
    not silently change a master's normal catalog to the draft catalog.
    """
    deployment = str(os.getenv("DEPLOYMENT", "")).strip().lower()
    client = getattr(request, "client", None)
    client_host = getattr(client, "host", "") if client else ""
    local_switch_enabled = str(os.getenv("USE_WIP_CATALOG", "")).strip().lower() in {
        "1", "true", "yes", "on"
    }
    return (
        deployment == "local"
        and _is_loopback_host(client_host)
        and local_switch_enabled
        and request_can_use_wip_catalog(request, auth_user)
    )
