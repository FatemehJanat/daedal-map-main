"""Runtime discovery for named, shared geometry families.

Geometry is not a pack and should not be copied into every source catalog.
This module reads the generated geometry catalog once and gives every chat,
API, and MCP path the same name -> canonical ``loc_id`` lookup.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..paths import GEOMETRY_DIR


CATALOG_PATH = GEOMETRY_DIR / "geometry_catalog.json"
WATER_BODY_CROSSWALK_PATH = GEOMETRY_DIR / "marine" / "water_bodies_crosswalk.json"


def _normalize(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


@lru_cache(maxsize=1)
def load_geometry_catalog() -> dict[str, Any]:
    """Load the generated catalog, with a narrow water-body fallback for dev."""
    try:
        payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except (OSError, json.JSONDecodeError):
        pass

    # A local checkout may predate the generated catalog. Keep the resolver
    # correct for the existing marine bank rather than silently using the old
    # heuristic registry.
    try:
        payload = json.loads(WATER_BODY_CROSSWALK_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"geometry_families": [], "named_geometries": []}
    entries = []
    for loc_id, item in (payload.get("crosswalk") or {}).items():
        if not isinstance(item, dict):
            continue
        entries.append({
            "loc_id": str(loc_id).upper(),
            "label": str(item.get("label") or loc_id),
            "family": "water_body",
            "aliases": list(item.get("iho_names") or []),
            "resolvable": True,
        })
    return {"geometry_families": [], "named_geometries": entries}


@lru_cache(maxsize=1)
def _named_index() -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for entry in load_geometry_catalog().get("named_geometries") or []:
        if not isinstance(entry, dict):
            continue
        loc_id = str(entry.get("loc_id") or "").strip().upper()
        label = str(entry.get("label") or "").strip()
        if not loc_id or not label:
            continue
        normalized_entry = dict(entry)
        normalized_entry["loc_id"] = loc_id
        for alias in [loc_id, label, *(entry.get("aliases") or [])]:
            key = _normalize(str(alias))
            if key:
                index.setdefault(key, normalized_entry)
        # “Mediterranean” is a natural request for “Mediterranean Sea”.
        for suffix in (" sea", " ocean", " waters"):
            key = _normalize(label)
            if key.endswith(suffix):
                index.setdefault(key[: -len(suffix)].strip(), normalized_entry)
    return index


def resolve_geometry_name(value: str | None) -> dict[str, Any] | None:
    """Resolve a named shared geometry without falling back to land aliases."""
    entry = _named_index().get(_normalize(value))
    if not entry or not bool(entry.get("resolvable", True)):
        return None
    return dict(entry)


def expand_geometry_loc_id(value: str | None) -> list[str]:
    """Return a resolvable geometry id plus all catalogued descendants.

    Named-water source rows use the smallest containing polygon. This shared
    expansion makes a parent selection include its detailed child waters.
    """
    root = str(value or "").strip().upper()
    if not root:
        return []
    entries = [entry for entry in load_geometry_catalog().get("named_geometries") or [] if isinstance(entry, dict)]
    known = {str(entry.get("loc_id") or "").strip().upper() for entry in entries if bool(entry.get("resolvable", True))}
    if root not in known:
        return []
    children: dict[str, list[str]] = {}
    for entry in entries:
        loc_id = str(entry.get("loc_id") or "").strip().upper()
        parent = str(entry.get("parent_loc_id") or "").strip().upper()
        if loc_id and parent:
            children.setdefault(parent, []).append(loc_id)
    expanded: list[str] = []
    pending = [root]
    while pending:
        loc_id = pending.pop(0)
        if loc_id in expanded:
            continue
        expanded.append(loc_id)
        pending.extend(sorted(children.get(loc_id) or []))
    return expanded


def is_known_geometry_loc_id(value: str | None) -> bool:
    entry = _named_index().get(_normalize(value))
    return bool(entry and entry.get("loc_id") == str(value or "").strip().upper() and entry.get("resolvable", True))


def is_deprecated_geometry_loc_id(value: str | None) -> bool:
    entry = _named_index().get(_normalize(value))
    return bool(entry and entry.get("loc_id") == str(value or "").strip().upper() and not entry.get("resolvable", True))
