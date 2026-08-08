"""Geometry API router endpoints."""

import os
import time
import msgpack
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from mapmover import logger
from mapmover.logging_analytics import hash_ip_for_analytics, log_api_query_event
from mapmover.security import get_client_ip
from mapmover.routes.system import _require_local_or_admin
from mapmover.geometry_handlers import (
    clear_cache as clear_geometry_cache,
    get_countries_geometry as get_countries_geometry_handler,
    get_geometry_index as get_geometry_index_handler,
    get_location_children as get_location_children_handler,
    get_location_info,
    get_location_places as get_location_places_handler,
    get_selection_geometries as get_selection_geometries_handler,
    get_viewport_geometry as get_viewport_geometry_handler,
    resolve_points_to_locations,
)
from mapmover.routes.disasters.helpers import msgpack_error, msgpack_response
from mapmover.runtime.reference_exchange import (
    convert_reference,
    get_geometry_reference,
    list_reference_systems,
    loc_id_references,
    resolve_reference,
)


router = APIRouter()
MAX_SELECTION_LOC_IDS = 1_000


def _point_lookup_batch_limit() -> int:
    try:
        return max(1, int(str(os.getenv("POINT_LOOKUP_BATCH_LIMIT", "25")).strip() or "25"))
    except ValueError:
        return 25


async def decode_request_body(request: Request) -> dict:
    """Decode MessagePack request body."""
    body_bytes = await request.body()
    return msgpack.unpackb(body_bytes, raw=False)


@router.get("/geometry/countries")
async def get_countries_geometry_endpoint(debug: bool = False):
    """Get all country geometries for initial map display."""
    try:
        result = get_countries_geometry_handler(debug=debug)
        return msgpack_response(result)
    except Exception as e:
        logger.error(f"Error in /geometry/countries: {e}")
        return msgpack_error(str(e), 500)


@router.get("/geometry/{loc_id}/children")
async def get_location_children_endpoint(loc_id: str):
    """Get child geometries for a location drill-down."""
    try:
        result = get_location_children_handler(loc_id)
        return msgpack_response(result)
    except Exception as e:
        logger.error(f"Error in /geometry/{loc_id}/children: {e}")
        return msgpack_error(str(e), 500)


@router.get("/geometry/{loc_id}/places")
async def get_location_places_endpoint(loc_id: str):
    """Get place points for a location as a separate overlay layer."""
    try:
        result = get_location_places_handler(loc_id)
        return msgpack_response(result)
    except Exception as e:
        logger.error(f"Error in /geometry/{loc_id}/places: {e}")
        return msgpack_error(str(e), 500)


@router.get("/geometry/{loc_id}/info")
async def get_location_info_endpoint(loc_id: str):
    """Get metadata about a specific location."""
    try:
        result = get_location_info(loc_id)
        return msgpack_response(result)
    except Exception as e:
        logger.error(f"Error in /geometry/{loc_id}/info: {e}")
        return msgpack_error(str(e), 500)


@router.get("/geometry/viewport")
async def get_viewport_geometry_endpoint(level: int = 0, bbox: str = None, debug: bool = False):
    """Get geometry features that intersect the viewport bounding box."""
    try:
        if bbox:
            parts = [float(x) for x in bbox.split(",")]
            if len(parts) != 4:
                return msgpack_error("bbox must be minLon,minLat,maxLon,maxLat", 400)
            bbox_tuple = tuple(parts)
        else:
            bbox_tuple = (-180, -90, 180, 90)

        result = get_viewport_geometry_handler(level, bbox_tuple, debug=debug)
        return msgpack_response(result)
    except Exception as e:
        logger.error(f"Error in /geometry/viewport: {e}")
        return msgpack_error(str(e), 500)


@router.get("/geometry/index")
async def get_geometry_index_endpoint(parent_loc_id: str = None, admin_level: int = None, bbox: str = None):
    """Get lightweight geometry index rows for diff-based loading."""
    try:
        bbox_tuple = None
        if bbox:
            parts = [float(x) for x in bbox.split(",")]
            if len(parts) != 4:
                return msgpack_error("bbox must be minLon,minLat,maxLon,maxLat", 400)
            bbox_tuple = tuple(parts)

        result = get_geometry_index_handler(parent_loc_id=parent_loc_id, admin_level=admin_level, bbox=bbox_tuple)
        return msgpack_response(result)
    except Exception as e:
        logger.error(f"Error in /geometry/index: {e}")
        return msgpack_error(str(e), 500)


@router.post("/geometry/cache/clear")
async def clear_geometry_cache_endpoint(req: Request):
    """Clear the geometry cache after data updates."""
    _context, error = _require_local_or_admin(req)
    if error:
        return error
    try:
        clear_geometry_cache()
        return msgpack_response({"message": "Geometry cache cleared"})
    except Exception as e:
        logger.error(f"Error clearing geometry cache: {e}")
        return msgpack_error(str(e), 500)


@router.post("/geometry/selection")
async def get_selection_geometry_endpoint(req: Request):
    """Get geometries for specific loc_ids for selection/disambiguation mode."""
    try:
        body = await decode_request_body(req)
        loc_ids = body.get("loc_ids", [])
        if not loc_ids:
            return msgpack_response({"type": "FeatureCollection", "features": []})
        if not isinstance(loc_ids, list) or len(loc_ids) > MAX_SELECTION_LOC_IDS:
            return msgpack_error(
                f"loc_ids must be a list of at most {MAX_SELECTION_LOC_IDS} ids",
                413,
            )

        result = get_selection_geometries_handler(loc_ids)
        return msgpack_response(result)
    except Exception as e:
        logger.error(f"Error in /geometry/selection: {e}")
        return msgpack_error(str(e), 500)


@router.post("/geometry/features")
async def get_geometry_features_endpoint(req: Request):
    """Return canonical reusable geometry for explicit ``loc_id`` values.

    This is the mode-neutral geometry-resource endpoint.  It intentionally
    carries no metric, event state, or temporal claim, letting the browser
    cache geometry independently from Explore, Research, and Ops payloads.
    ``/geometry/selection`` remains as a compatibility alias for the
    selection workflow.
    """
    try:
        body = await decode_request_body(req)
        loc_ids = body.get("loc_ids", [])
        if not loc_ids:
            return msgpack_response({"type": "FeatureCollection", "features": []})
        if not isinstance(loc_ids, list) or len(loc_ids) > MAX_SELECTION_LOC_IDS:
            return msgpack_error(
                f"loc_ids must be a list of at most {MAX_SELECTION_LOC_IDS} ids",
                413,
            )
        return msgpack_response(get_selection_geometries_handler(loc_ids))
    except Exception as e:
        logger.error(f"Error in /geometry/features: {e}")
        return msgpack_error(str(e), 500)


@router.post("/geometry/resolve-point")
async def resolve_point_endpoint(req: Request):
    """Resolve a lon/lat point to the deepest available containing loc_id."""
    try:
        body = await decode_request_body(req)
        lon = body.get("lon")
        lat = body.get("lat")
        if lon is None or lat is None:
            return msgpack_error("lon and lat are required", 400)

        results = resolve_points_to_locations([{"lon": lon, "lat": lat}], include_geometry=True)
        result = results[0] if results else {"error": "point did not resolve"}
        if result.get("error"):
            return msgpack_response(result, status_code=404)
        return msgpack_response(result)
    except Exception as e:
        logger.error(f"Error in /geometry/resolve-point: {e}")
        return msgpack_error(str(e), 500)


@router.post("/api/v1/resolve/point")
async def resolve_point_json_endpoint(req: Request):
    """Resolve a lon/lat point to the deepest available containing loc_id as JSON."""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON request body"}, status_code=400)

    lon = body.get("lon")
    lat = body.get("lat")
    if lon is None or lat is None:
        return JSONResponse({"error": "lon and lat are required"}, status_code=400)

    include_geometry = bool(body.get("include_geometry", False))
    try:
        results = resolve_points_to_locations([{"lon": lon, "lat": lat}], include_geometry=include_geometry)
        result = results[0] if results else {"error": "point did not resolve"}
        if result.get("error"):
            return JSONResponse(result, status_code=404)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"Error in /api/v1/resolve/point: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/v1/resolve/points")
async def resolve_points_json_endpoint(req: Request):
    """Resolve a small batch of lon/lat points to containing loc_ids as JSON."""
    started_at = time.perf_counter()
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON request body"}, status_code=400)

    points = body.get("points")
    if not isinstance(points, list):
        return JSONResponse({"error": "points must be a list"}, status_code=400)

    limit = _point_lookup_batch_limit()
    if len(points) > limit:
        source = str(body.get("source") or "").strip()[:80] or "unknown"
        batch_id = str(body.get("batch_id") or "").strip()[:120] or None
        metadata = {
            "surface": "test_data" if source == "try_dataset" else source,
            "event": "point_lookup_batch",
            "batch_id": batch_id,
            "point_count": len(points),
            "resolved_count": 0,
            "unresolved_count": len(points),
            "limit": limit,
            "reject_reason": "too_many_points",
        }
        try:
            log_api_query_event(
                request_id=batch_id or f"point-batch-deny-{int(time.time() * 1000)}",
                capability_id="point_lookup_batch",
                pack_id="geography_tools",
                source_id="resolve_points",
                decision="deny",
                payment_rail="free_preview",
                auth_user_id=None,
                ip_hash=hash_ip_for_analytics(get_client_ip(req)),
                user_agent=req.headers.get("user-agent", "").strip() or None,
                execution_latency_ms=int((time.perf_counter() - started_at) * 1000),
                row_count=len(points),
                status_code=413,
                error_code="too_many_points",
                query_granularity=f"bulk_{len(points)}",
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning(f"Point lookup batch deny analytics failed: {exc}")
        return JSONResponse({"error": f"points must contain at most {limit} items", "limit": limit}, status_code=413)

    include_geometry = bool(body.get("include_geometry", False))
    source = str(body.get("source") or "").strip()[:80] or "unknown"
    batch_id = str(body.get("batch_id") or "").strip()[:120] or None
    valid_points = []
    invalid_by_index = {}
    resolved_count = 0
    unresolved_count = 0

    for index, point in enumerate(points):
        if not isinstance(point, dict):
            invalid_by_index[index] = {"index": index, "error": "point must be an object"}
            continue
        lon = point.get("lon")
        lat = point.get("lat")
        row_index = point.get("row_index", index)
        if lon is None or lat is None:
            invalid_by_index[index] = {"index": index, "row_index": row_index, "error": "lon and lat are required"}
            continue
        try:
            lon_value = float(lon)
            lat_value = float(lat)
        except (TypeError, ValueError):
            invalid_by_index[index] = {"index": index, "row_index": row_index, "error": "lon and lat must be numbers"}
            continue
        if not (-90.0 <= lat_value <= 90.0) or not (-180.0 <= lon_value <= 180.0):
            invalid_by_index[index] = {"index": index, "row_index": row_index, "error": "lat must be within -90..90 and lon within -180..180"}
            continue
        valid_points.append({"index": index, "row_index": row_index, "lon": lon_value, "lat": lat_value})

    try:
        raw_results = resolve_points_to_locations(valid_points, include_geometry=include_geometry)
    except Exception as exc:
        raw_results = [{"error": str(exc), "point": {"lon": point.get("lon"), "lat": point.get("lat")}} for point in valid_points]

    by_index = dict(invalid_by_index)
    for point, result in zip(valid_points, raw_results):
        by_index[point["index"]] = {"index": point["index"], "row_index": point["row_index"], **result}

    results = []
    for index in range(len(points)):
        item = by_index.get(index) or {"index": index, "error": "point did not produce a result"}
        if item.get("error"):
            unresolved_count += 1
        elif item.get("deepest_resolved_loc_id") or (item.get("matched") or {}).get("loc_id"):
            resolved_count += 1
        else:
            unresolved_count += 1
        results.append(item)

    status_code = 200
    payload = {
        "batch_id": batch_id,
        "source": source,
        "limit": limit,
        "point_count": len(points),
        "resolved_count": resolved_count,
        "unresolved_count": unresolved_count,
        "results": results,
    }

    req.state.analytics_request_id = batch_id
    req.state.analytics_pack_id = "geography_tools"
    req.state.analytics_source_id = "resolve_points"
    req.state.analytics_metadata = {
        "surface": "test_data" if source == "try_dataset" else source,
        "event": "point_lookup_batch",
        "batch_id": batch_id,
        "point_count": len(points),
        "resolved_count": resolved_count,
        "unresolved_count": unresolved_count,
        "limit": limit,
    }

    try:
        log_api_query_event(
            request_id=batch_id or f"point-batch-{int(time.time() * 1000)}",
            capability_id="point_lookup_batch",
            pack_id="geography_tools",
            source_id="resolve_points",
            decision="allow",
            payment_rail="free_preview",
            auth_user_id=None,
            ip_hash=hash_ip_for_analytics(get_client_ip(req)),
            user_agent=req.headers.get("user-agent", "").strip() or None,
            execution_latency_ms=int((time.perf_counter() - started_at) * 1000),
            row_count=len(points),
            status_code=status_code,
            query_granularity=f"bulk_{len(points)}",
            metadata=req.state.analytics_metadata,
        )
    except Exception as exc:
        logger.warning(f"Point lookup batch analytics failed: {exc}")

    return JSONResponse(payload, status_code=status_code)


def _internal_json_allowed(req: Request):
    _context, error = _require_local_or_admin(req)
    if error:
        status_code = getattr(error, "status_code", 403) or 403
        message = "Unauthorized" if status_code == 401 else "Forbidden"
        return JSONResponse({"ok": False, "error": message}, status_code=status_code)
    return error


async def _json_body(req: Request) -> tuple[dict, JSONResponse | None]:
    try:
        body = await req.json()
    except Exception:
        return {}, JSONResponse({"ok": False, "error": "Invalid JSON request body"}, status_code=400)
    if not isinstance(body, dict):
        return {}, JSONResponse({"ok": False, "error": "JSON request body must be an object"}, status_code=400)
    return body, None


@router.get("/api/internal/reference/systems")
async def list_reference_systems_endpoint(req: Request):
    """List loc_id exchange systems discovered from the geometry catalog."""
    error = _internal_json_allowed(req)
    if error:
        return error
    try:
        return JSONResponse(list_reference_systems())
    except Exception as e:
        logger.error(f"Error in /api/internal/reference/systems: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/api/internal/reference/resolve")
async def resolve_reference_endpoint(req: Request):
    """Resolve one reference-system value into the loc_id universe."""
    error = _internal_json_allowed(req)
    if error:
        return error
    body, body_error = await _json_body(req)
    if body_error:
        return body_error
    from_system = body.get("from_system") or body.get("system")
    value = body.get("value")
    if not from_system or value in (None, ""):
        return JSONResponse({"ok": False, "error": "from_system and value are required"}, status_code=400)
    try:
        result = resolve_reference(
            from_system=str(from_system),
            value=str(value),
            iso3=str(body.get("iso3") or "USA"),
            target_admin_level=body.get("target_admin_level", "admin_2"),
            bridge_vintage=body.get("bridge_vintage"),
            min_share=body.get("min_share"),
            limit=body.get("limit", 10),
            country_hint=body.get("country_hint"),
            admin_level_hint=body.get("admin_level_hint"),
        )
        return JSONResponse(result, status_code=200 if result.get("ok") else 404)
    except Exception as e:
        logger.error(f"Error in /api/internal/reference/resolve: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/api/internal/reference/loc-id-references")
async def loc_id_references_endpoint(req: Request):
    """Return known references that point at a loc_id."""
    error = _internal_json_allowed(req)
    if error:
        return error
    body, body_error = await _json_body(req)
    if body_error:
        return body_error
    loc_id = body.get("loc_id")
    if not loc_id:
        return JSONResponse({"ok": False, "error": "loc_id is required"}, status_code=400)
    try:
        result = loc_id_references(
            str(loc_id),
            systems=body.get("systems"),
            iso3=body.get("iso3"),
            target_admin_level=body.get("target_admin_level"),
            min_share=body.get("min_share"),
            limit_per_system=body.get("limit_per_system", 10),
        )
        return JSONResponse(result, status_code=200 if result.get("ok") else 404)
    except Exception as e:
        logger.error(f"Error in /api/internal/reference/loc-id-references: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/api/internal/reference/convert")
async def convert_reference_endpoint(req: Request):
    """Convert between two reference systems through loc_id."""
    error = _internal_json_allowed(req)
    if error:
        return error
    body, body_error = await _json_body(req)
    if body_error:
        return body_error
    from_system = body.get("from_system")
    to_system = body.get("to_system")
    value = body.get("value")
    if not from_system or not to_system or value in (None, ""):
        return JSONResponse({"ok": False, "error": "from_system, to_system, and value are required"}, status_code=400)
    try:
        result = convert_reference(
            from_system=str(from_system),
            value=str(value),
            to_system=str(to_system),
            iso3=str(body.get("iso3") or "USA"),
            target_admin_level=body.get("target_admin_level", "admin_2"),
            bridge_vintage=body.get("bridge_vintage"),
            min_share=body.get("min_share"),
            limit=body.get("limit", 10),
        )
        return JSONResponse(result, status_code=200 if result.get("ok") else 404)
    except Exception as e:
        logger.error(f"Error in /api/internal/reference/convert: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/api/internal/reference/geometry")
async def get_reference_geometry_endpoint(req: Request):
    """Return geometry metadata, and optionally polygon, for a loc_id."""
    error = _internal_json_allowed(req)
    if error:
        return error
    body, body_error = await _json_body(req)
    if body_error:
        return body_error
    loc_id = body.get("loc_id")
    if not loc_id:
        return JSONResponse({"ok": False, "error": "loc_id is required"}, status_code=400)
    try:
        result = get_geometry_reference(str(loc_id), include_polygon=bool(body.get("include_polygon", False)))
        return JSONResponse(result, status_code=200 if result.get("ok") else 404)
    except Exception as e:
        logger.error(f"Error in /api/internal/reference/geometry: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
