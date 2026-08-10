"""Runtime discovery for named, shared geometry families.

Geometry is not a pack and should not be copied into every source catalog.
This module reads the generated geometry catalog once and gives every chat,
API, and MCP path the same name -> canonical ``loc_id`` lookup.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..paths import GEOMETRY_DIR
from ..runtime_config import get_runtime_config


CATALOG_PATH = GEOMETRY_DIR / "geometry_catalog.json"


def _normalize(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _is_cloud_mode() -> bool:
    return str(get_runtime_config().get("runtime_mode", "local")).strip().lower() == "cloud"


def _fetch_geometry_catalog_from_s3() -> dict[str, Any] | None:
    import boto3

    cloud_cfg = get_runtime_config().get("cloud", {})
    bucket = os.environ.get("S3_BUCKET", "").strip() or str(cloud_cfg.get("bucket", "")).strip()
    if not bucket:
        return None
    prefix = (
        os.environ.get("S3_PREFIX", "").strip()
        or str(cloud_cfg.get("prefix", "")).strip()
    ).strip("/")
    key = f"{prefix}/geometry/geometry_catalog.json" if prefix else "geometry/geometry_catalog.json"
    endpoint_url = os.environ.get("S3_ENDPOINT_URL") or cloud_cfg.get("endpoint_url")
    region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "auto"
    client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region)
    obj = client.get_object(Bucket=bucket, Key=key)
    payload = json.loads(obj["Body"].read())
    return payload if isinstance(payload, dict) else None


@lru_cache(maxsize=1)
def load_geometry_catalog() -> dict[str, Any]:
    """Load the generated schema-1.1 geometry catalog."""
    if _is_cloud_mode():
        try:
            payload = _fetch_geometry_catalog_from_s3()
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass

    try:
        payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except (OSError, json.JSONDecodeError):
        pass

    return {
        "schema_version": "1.1.0",
        "geometry_collections": [],
        "geometry_families": [],
        "geometry_banks": [],
        "geometry_products": [],
        "release_packages": [],
        "bridge_artifacts": [],
        "resolver_groups": [],
        "named_reference_objects": [],
    }


def clear_geometry_catalog_cache() -> None:
    load_geometry_catalog.cache_clear()
    _named_index.cache_clear()
    _named_group_index.cache_clear()


@lru_cache(maxsize=1)
def _named_index() -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    catalog = load_geometry_catalog()
    for entry in catalog.get("named_reference_objects") or []:
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


@lru_cache(maxsize=1)
def _named_group_index() -> dict[str, dict[str, Any]]:
    """Index explicit human-name groups before individual geometry aliases.

    A whole-ocean name can represent multiple IHO polygons (Pacific and
    Arctic). It is not safe to select whichever individual polygon happens to
    be first, nor to substitute a legacy X* SST product zone.
    """
    index: dict[str, dict[str, Any]] = {}
    catalog = load_geometry_catalog()
    for entry in catalog.get("resolver_groups") or []:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label") or "").strip()
        loc_ids = [str(value).strip().upper() for value in entry.get("loc_ids") or [] if str(value).strip()]
        if not label:
            continue
        normalized = dict(entry)
        normalized["label"] = label
        normalized["loc_ids"] = loc_ids
        for alias in [label, *(entry.get("aliases") or [])]:
            key = _normalize(str(alias))
            if key:
                index.setdefault(key, normalized)
    return index


def resolve_geometry_name(value: str | None) -> dict[str, Any] | None:
    """Resolve a named shared geometry without falling back to land aliases."""
    key = _normalize(value)
    group = _named_group_index().get(key)
    if group:
        # Return an explicitly unresolved group as well. Callers can then give
        # a truthful "no approved geometry" result instead of treating a known
        # ocean name as an unknown place or falling back to an X* SST zone.
        return dict(group)
    entry = _named_index().get(key)
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
    catalog = load_geometry_catalog()
    entries = [
        entry
        for entry in catalog.get("named_reference_objects") or []
        if isinstance(entry, dict)
    ]
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
