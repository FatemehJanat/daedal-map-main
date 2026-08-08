"""Shared runtime helpers for public/admin geometry tool jobs.

These helpers keep MCP, HTTP, and future admin surfaces on one contract. They
wrap existing geometry-spine seams for scope listing, availability checks, and
reference exchange; durable queues/artifacts can replace the in-memory registry
without changing public tool shapes.
"""

from __future__ import annotations

import hashlib
import math
import time
import uuid
from typing import Any

from ..geometry_handlers import GEOMETRY_INDEX_COLUMNS, get_geometry_index, load_country_parquet
from .admin_hierarchy import infer_admin_level_from_loc_id
from .country_geography import get_country_supported_deep_admin_levels
from .geography_reference import translate_geometry_id_to_local_id
from .reference_exchange import convert_reference, get_geometry_availability, get_geometry_references, resolve_reference


_JOB_REGISTRY: dict[str, dict[str, Any]] = {}


def _clean_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if hasattr(value, "item"):
        try:
            return _clean_json(value.item())
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): _clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_json(item) for item in value]
    return str(value)


def _admin_level_value(value: Any) -> int | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    aliases = {"country": 0, "state": 1, "province": 1, "county": 2}
    if raw in aliases:
        return aliases[raw]
    if raw.startswith("admin_"):
        raw = raw.split("_", 1)[1]
    try:
        return max(0, int(raw))
    except ValueError:
        return None


def _bbox_value(value: Any) -> tuple[float, float, float, float] | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        return None
    if len(parts) != 4:
        return None
    try:
        return tuple(float(part) for part in parts)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def _country_code_from_loc_id(loc_id: str) -> str:
    return str(loc_id or "").strip().split("-", 1)[0].upper()


def _base_admin_scope_rows(parent_loc_id: str, admin_level: int, bbox: tuple[float, float, float, float] | None) -> list[dict[str, Any]]:
    parent_level = infer_admin_level_from_loc_id(parent_loc_id)
    if parent_level is None or admin_level > 2:
        return []
    iso3 = _country_code_from_loc_id(parent_loc_id)
    df = load_country_parquet(iso3, admin_level=admin_level, columns=GEOMETRY_INDEX_COLUMNS)
    if df is None or df.empty:
        return []
    if parent_level > 0 and "parent_id" in df.columns:
        parent_ids = {parent_loc_id, translate_geometry_id_to_local_id(parent_loc_id)}
        df = df[df["parent_id"].map(lambda value: translate_geometry_id_to_local_id(str(value or "").strip()) in parent_ids)]
    if bbox is not None and not df.empty:
        min_lon, min_lat, max_lon, max_lat = bbox
        if all(col in df.columns for col in ("bbox_min_lon", "bbox_max_lon", "bbox_min_lat", "bbox_max_lat")):
            df = df[
                (df["bbox_max_lon"] >= min_lon)
                & (df["bbox_min_lon"] <= max_lon)
                & (df["bbox_max_lat"] >= min_lat)
                & (df["bbox_min_lat"] <= max_lat)
            ]
    return [row for row in df.to_dict("records") if isinstance(row, dict)]


def _unsupported_deep_scope_error(parent_loc_id: str, admin_level: int, bbox: tuple[float, float, float, float] | None) -> dict[str, Any] | None:
    if admin_level < 3:
        return None
    iso3 = _country_code_from_loc_id(parent_loc_id)
    supported_levels = get_country_supported_deep_admin_levels(iso3)
    if admin_level not in supported_levels:
        return {
            "ok": False,
            "parent_loc_id": parent_loc_id,
            "admin_level": admin_level,
            "error": {
                "code": "unsupported_admin_level",
                "message": f"{iso3} does not publish admin_{admin_level} geometry through this scope tool",
            },
            "supported_deep_admin_levels": [f"admin_{level}" for level in supported_levels],
        }
    parent_level = infer_admin_level_from_loc_id(parent_loc_id)
    if parent_level is None:
        return {
            "ok": False,
            "parent_loc_id": parent_loc_id,
            "admin_level": admin_level,
            "error": {"code": "invalid_scope", "message": "parent_loc_id is not a recognized admin loc_id shape"},
            "supported_deep_admin_levels": [f"admin_{level}" for level in supported_levels],
        }
    if parent_level < 2 and bbox is None:
        return {
            "ok": False,
            "parent_loc_id": parent_loc_id,
            "admin_level": admin_level,
            "error": {
                "code": "scope_too_broad",
                "message": "Deep admin scope requests require an admin_2 parent or bbox; use estimate/create export for country- or state-scale deep geometry.",
            },
            "supported_deep_admin_levels": [f"admin_{level}" for level in supported_levels],
        }
    return None


def _row_summary(row: dict[str, Any]) -> dict[str, Any]:
    raw_loc_id = str(row.get("loc_id") or "").strip()
    loc_id = translate_geometry_id_to_local_id(raw_loc_id) if raw_loc_id else None
    raw_parent_id = str(row.get("parent_id") or "").strip()
    parent_id = translate_geometry_id_to_local_id(raw_parent_id) if raw_parent_id else None
    bbox = None
    if all(key in row for key in ("bbox_min_lon", "bbox_min_lat", "bbox_max_lon", "bbox_max_lat")):
        bbox = [row.get("bbox_min_lon"), row.get("bbox_min_lat"), row.get("bbox_max_lon"), row.get("bbox_max_lat")]
    centroid = None
    if row.get("centroid_lon") is not None and row.get("centroid_lat") is not None:
        centroid = {"lon": row.get("centroid_lon"), "lat": row.get("centroid_lat")}
    return _clean_json(
        {
            "loc_id": loc_id or row.get("loc_id"),
            "name": row.get("name"),
            "parent_id": parent_id or row.get("parent_id"),
            "admin_level": row.get("admin_level"),
            "code": row.get("code"),
            "bbox": bbox,
            "centroid": centroid,
        }
    )


def _scope_rows(parent_loc_id: str, admin_level: int, bbox: tuple[float, float, float, float] | None) -> list[dict[str, Any]]:
    index = get_geometry_index(parent_loc_id=parent_loc_id, admin_level=admin_level, bbox=bbox)
    rows = [row for row in (index.get("rows") or []) if isinstance(row, dict)]
    if rows:
        return rows

    parent_level = infer_admin_level_from_loc_id(parent_loc_id)
    if parent_level is None or admin_level <= parent_level + 1:
        return _base_admin_scope_rows(parent_loc_id, admin_level, bbox) or rows
    base_rows = _base_admin_scope_rows(parent_loc_id, admin_level, bbox)
    if base_rows:
        return base_rows

    frontier = [parent_loc_id]
    for level in range(parent_level + 1, admin_level + 1):
        level_rows: list[dict[str, Any]] = []
        next_frontier: list[str] = []
        for current_parent in frontier:
            child_index = get_geometry_index(parent_loc_id=current_parent, admin_level=level, bbox=bbox)
            child_rows = [row for row in (child_index.get("rows") or []) if isinstance(row, dict)]
            if level == admin_level:
                level_rows.extend(child_rows)
            else:
                next_frontier.extend(
                    translate_geometry_id_to_local_id(str(row.get("loc_id") or "").strip())
                    for row in child_rows
                    if row.get("loc_id")
                )
        if level == admin_level:
            return level_rows
        frontier = next_frontier
        if not frontier:
            break
    return []


def resolve_loc_id_scope(payload: dict[str, Any], *, default_limit: int = 100) -> dict[str, Any]:
    scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else payload
    parent_loc_id = str(scope.get("parent_loc_id") or payload.get("parent_loc_id") or "").strip()
    admin_level = _admin_level_value(scope.get("admin_level") if isinstance(scope, dict) else payload.get("admin_level"))
    if not parent_loc_id:
        return {"ok": False, "error": {"code": "invalid_scope", "message": "parent_loc_id is required"}}
    if admin_level is None:
        return {"ok": False, "error": {"code": "invalid_scope", "message": "admin_level is required"}}
    bbox = _bbox_value(scope.get("bbox") if isinstance(scope, dict) else payload.get("bbox"))
    unsupported = _unsupported_deep_scope_error(parent_loc_id, admin_level, bbox)
    if unsupported:
        return _clean_json(unsupported)
    limit = max(0, int(payload.get("limit") or default_limit))
    offset = max(0, int(payload.get("offset") or 0))
    count_only = bool(payload.get("count_only"))
    rows = [_row_summary(row) for row in _scope_rows(parent_loc_id, admin_level, bbox)]
    total = len(rows)
    page = [] if count_only else rows[offset : offset + limit]
    return _clean_json(
        {
            "ok": True,
            "parent_loc_id": parent_loc_id,
            "admin_level": admin_level,
            "bbox": list(bbox) if bbox else None,
            "total_count": total,
            "returned_count": len(page),
            "limit": limit,
            "offset": offset,
            "truncated": (offset + len(page)) < total,
            "loc_ids": [row.get("loc_id") for row in page if row.get("loc_id")],
            "rows": page,
        }
    )


def _loc_ids_from_request(payload: dict[str, Any], *, scope_limit: int = 10000) -> tuple[list[str], dict[str, Any] | None]:
    if isinstance(payload.get("loc_ids"), list):
        return [str(item).strip() for item in payload.get("loc_ids") or [] if str(item).strip()], None
    loc_id = str(payload.get("loc_id") or "").strip()
    if loc_id:
        return [loc_id], None
    if isinstance(payload.get("scope"), dict) or payload.get("parent_loc_id"):
        scope_payload = {**payload, "limit": scope_limit}
        scope_result = resolve_loc_id_scope(scope_payload, default_limit=scope_limit)
        if not scope_result.get("ok"):
            return [], scope_result
        return [str(item) for item in scope_result.get("loc_ids") or [] if str(item).strip()], scope_result
    return [], {"ok": False, "error": {"code": "invalid_request", "message": "loc_ids or scope is required"}}


def _estimate_geometry_bytes(available_count: int, *, include_polygon: bool, output_format: str) -> tuple[int, int]:
    metadata_bytes = available_count * 700
    polygon_bytes = available_count * 45000 if include_polygon else 0
    uncompressed = metadata_bytes + polygon_bytes
    compressed_ratio = 0.18 if output_format in {"geojson_gzip", "zip", "geoparquet", "flatgeobuf", "pmtiles"} else 1.0
    return uncompressed, max(0, int(uncompressed * compressed_ratio))


def estimate_geometry_package(payload: dict[str, Any], *, scope_limit: int = 10000) -> dict[str, Any]:
    output_format = str(payload.get("format") or "geojson_gzip").strip().lower()
    include_polygon = bool(payload.get("include_polygon", True))
    loc_ids, scope_result = _loc_ids_from_request(payload, scope_limit=scope_limit)
    if not loc_ids:
        return scope_result or {"ok": False, "error": {"code": "empty_request", "message": "No loc_ids found"}}
    availability = get_geometry_availability(loc_ids)
    available_count = int(availability.get("available") or 0)
    missing_count = int(availability.get("missing") or max(0, len(loc_ids) - available_count))
    uncompressed, transfer = _estimate_geometry_bytes(available_count, include_polygon=include_polygon, output_format=output_format)
    delivery_mode = "inline" if transfer <= 250_000 and len(loc_ids) <= 10 else "artifact_job"
    quote_basis = f"{sorted(loc_ids)[:25]}:{len(loc_ids)}:{output_format}:{include_polygon}"
    quote_id = "geoquote_" + hashlib.sha256(quote_basis.encode("utf-8")).hexdigest()[:16]
    return _clean_json(
        {
            "ok": True,
            "quote_id": quote_id,
            "request_kind": "geometry_package",
            "loc_id_count": len(loc_ids),
            "available_shape_count": available_count,
            "missing_shape_count": missing_count,
            "estimated_uncompressed_bytes": uncompressed,
            "estimated_transfer_bytes": transfer,
            "format": output_format,
            "include_polygon": include_polygon,
            "recommended_delivery_mode": delivery_mode,
            "license_citation_required": True,
            "free_allowance": {"inline_polygon_loc_ids": 10, "metadata_loc_ids": 100},
            "charge_units": max(1, math.ceil(available_count / 10)) if include_polygon else max(1, math.ceil(len(loc_ids) / 100)),
            "pricing_version": "geometry-tools-v0",
            "scope": scope_result,
            "create_call": {
                "tool": "create_geometry_export",
                "arguments": {
                    "quote_id": quote_id,
                    "loc_ids": loc_ids,
                    "format": output_format,
                    "include_polygon": include_polygon,
                },
            },
        }
    )


def _new_job(kind: str, request_payload: dict[str, Any], *, status: str = "queued", result: dict[str, Any] | None = None) -> dict[str, Any]:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    job_id = f"{kind}_{uuid.uuid4().hex[:16]}"
    job = {
        "ok": True,
        "job_id": job_id,
        "kind": kind,
        "status": status,
        "progress": 1.0 if status == "completed" else 0.0,
        "created_at": now,
        "updated_at": now,
        "request": request_payload,
        "result": result,
        "artifact": None,
        "callback_state": "not_configured",
    }
    _JOB_REGISTRY[job_id] = job
    return _clean_json(job)


def create_geometry_export(payload: dict[str, Any], *, inline_limit: int = 10) -> dict[str, Any]:
    include_polygon = bool(payload.get("include_polygon", True))
    loc_ids, scope_result = _loc_ids_from_request(payload)
    if not loc_ids:
        return scope_result or {"ok": False, "error": {"code": "empty_request", "message": "No loc_ids found"}}
    if len(loc_ids) <= inline_limit:
        result = get_geometry_references(loc_ids, include_polygon=include_polygon, include_info=True)
        return _new_job("geometry_export", payload, status="completed", result={"delivery_mode": "inline", **result})
    return _new_job(
        "geometry_export",
        payload,
        status="queued",
        result={
            "delivery_mode": "artifact_job",
            "message": "Queued for hosted worker processing; durable Supabase/R2 storage is the next backing implementation.",
            "loc_id_count": len(loc_ids),
        },
    )


def estimate_conversion_job(payload: dict[str, Any], *, sample_limit: int = 25) -> dict[str, Any]:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    row_count = len(items) if items else max(0, int(payload.get("row_count") or 0))
    sample = items[:sample_limit]
    resolved = 0
    errors = 0
    for item in sample:
        if not isinstance(item, dict):
            errors += 1
            continue
        row = {**payload, **item}
        result = resolve_reference(
            from_system=str(row.get("from_system") or ""),
            value=str(row.get("value") or ""),
            iso3=str(row.get("iso3") or "USA"),
            target_admin_level=row.get("target_admin_level") or "admin_2",
            bridge_vintage=row.get("bridge_vintage"),
            min_share=row.get("min_share"),
            limit=1,
        )
        if result.get("ok"):
            resolved += 1
        else:
            errors += 1
    estimated_resolvable = row_count if not sample else int(row_count * (resolved / max(1, len(sample))))
    quote_id = "convquote_" + uuid.uuid4().hex[:16]
    return _clean_json(
        {
            "ok": True,
            "quote_id": quote_id,
            "request_kind": "conversion_job",
            "row_count": row_count,
            "sampled_rows": len(sample),
            "sample_resolved": resolved,
            "sample_errors": errors,
            "estimated_resolvable_rows": estimated_resolvable,
            "estimated_error_rows": max(0, row_count - estimated_resolvable),
            "estimated_output_bytes": max(1000, row_count * 900),
            "charge_units": max(1, math.ceil(row_count / 100)),
            "pricing_version": "geometry-tools-v0",
            "create_call": {"tool": "create_conversion_job", "arguments": {**payload, "quote_id": quote_id}},
        }
    )


def create_conversion_job(payload: dict[str, Any], *, inline_limit: int = 100) -> dict[str, Any]:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    if not items:
        return {"ok": False, "error": {"code": "invalid_request", "message": "items are required for conversion execution"}}
    if len(items) > inline_limit:
        return _new_job(
            "conversion_job",
            payload,
            status="queued",
            result={
                "delivery_mode": "artifact_job",
                "message": "Queued for hosted worker processing; durable Supabase/R2 storage is the next backing implementation.",
                "row_count": len(items),
            },
        )
    results = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            results.append({"row_index": index, "ok": False, "error": {"code": "invalid_item", "message": "each item must be an object"}})
            continue
        row = {**payload, **item}
        if row.get("to_system"):
            result = convert_reference(
                from_system=str(row.get("from_system") or ""),
                value=str(row.get("value") or ""),
                to_system=str(row.get("to_system") or ""),
                iso3=str(row.get("iso3") or "USA"),
                target_admin_level=row.get("target_admin_level") or "admin_2",
                bridge_vintage=row.get("bridge_vintage"),
                min_share=row.get("min_share"),
                limit=int(row.get("limit") or 10),
            )
        else:
            result = resolve_reference(
                from_system=str(row.get("from_system") or ""),
                value=str(row.get("value") or ""),
                iso3=str(row.get("iso3") or "USA"),
                target_admin_level=row.get("target_admin_level") or "admin_2",
                bridge_vintage=row.get("bridge_vintage"),
                min_share=row.get("min_share"),
                limit=int(row.get("limit") or 10),
            )
        if item.get("row_index") is not None:
            result["row_index"] = item.get("row_index")
        results.append(result)
    return _new_job(
        "conversion_job",
        payload,
        status="completed",
        result={
            "delivery_mode": "inline",
            "row_count": len(items),
            "converted_count": sum(1 for item in results if item.get("ok")),
            "error_count": sum(1 for item in results if not item.get("ok")),
            "results": results,
        },
    )


def get_job_status(job_id: str) -> dict[str, Any]:
    job = _JOB_REGISTRY.get(str(job_id or "").strip())
    if not job:
        return {"ok": False, "job_id": job_id, "status": "not_found", "error": {"code": "job_not_found", "message": "No job found for job_id"}}
    return _clean_json(job)
