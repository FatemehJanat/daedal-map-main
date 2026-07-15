"""Geometry API router endpoints."""

import msgpack
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from mapmover import logger
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
)
from mapmover.routes.disasters.helpers import msgpack_error, msgpack_response
from mapmover.runtime.loc_id_resolution import resolve_point_to_loc_id_stack


router = APIRouter()
MAX_SELECTION_LOC_IDS = 1_000


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


@router.post("/geometry/resolve-point")
async def resolve_point_endpoint(req: Request):
    """Resolve a lon/lat point to the deepest available containing loc_id."""
    try:
        body = await decode_request_body(req)
        lon = body.get("lon")
        lat = body.get("lat")
        if lon is None or lat is None:
            return msgpack_error("lon and lat are required", 400)

        result = resolve_point_to_loc_id_stack(lon, lat, include_geometry=True)
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
        result = resolve_point_to_loc_id_stack(lon, lat, include_geometry=include_geometry)
        if result.get("error"):
            return JSONResponse(result, status_code=404)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"Error in /api/v1/resolve/point: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
