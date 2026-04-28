"""Fairfax LST raster API endpoints."""

import io
import os
from pathlib import Path

import msgpack
import tifffile
from fastapi import APIRouter, Request
from shapely.geometry import shape as shapely_shape

from mapmover.data_loading import load_source_metadata
from mapmover.duckdb_helpers import is_cloud_mode
from mapmover.geometry_handlers import get_selection_geometries
from mapmover.logging_analytics import logger
from mapmover.paths import COUNTRIES_DIR
from mapmover.routes.disasters.helpers import msgpack_error, msgpack_response
from mapmover.runtime_config import get_runtime_config

router = APIRouter()

RASTER_DIR = COUNTRIES_DIR / "USA" / "fairfax_lst" / "rasters"
RASTER_RELATIVE_DIR = "countries/USA/fairfax_lst/rasters"


def _cloud_object_bytes(relative_path: str) -> bytes | None:
    """Fetch an object from the active S3/R2 prefix in cloud mode."""
    import boto3

    cloud_cfg = get_runtime_config().get("cloud", {})
    bucket = os.environ.get("S3_BUCKET", "").strip() or str(cloud_cfg.get("bucket", "")).strip()
    prefix = (os.environ.get("S3_PREFIX", "") or str(cloud_cfg.get("prefix", ""))).strip().strip("/")
    endpoint_url = os.environ.get("S3_ENDPOINT_URL") or cloud_cfg.get("endpoint_url")
    region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "auto"
    key = f"{prefix}/{relative_path}" if prefix else relative_path

    if not bucket:
        logger.warning("Fairfax raster cloud read requested without S3 bucket configured")
        return None

    try:
        client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region)
        obj = client.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except Exception as exc:
        logger.warning(f"Fairfax raster cloud read failed for {key}: {exc}")
        return None


def _load_scene_catalog() -> dict | None:
    metadata = load_source_metadata("fairfax_lst") or {}
    raster_products = metadata.get("raster_products") or {}
    scene_rasters = raster_products.get("scene_rasters") or {}
    scenes = scene_rasters.get("scenes") or []
    if not isinstance(scenes, list) or not scenes:
        return None
    return {
        "source_id": str(scene_rasters.get("source_id") or "fairfax_lst_full"),
        "crs": str(scene_rasters.get("crs") or "EPSG:4326"),
        "nodata": float(scene_rasters.get("nodata") or 0.0),
        "value_unit": str(scene_rasters.get("value_unit") or "Fahrenheit"),
        "scenes": scenes,
    }


def _loc_id_clip_level(loc_id: str) -> str | None:
    segment_count = str(loc_id or "").count("-")
    return {
        2: "county",
        3: "tract",
        4: "blockgroup",
        5: "block",
    }.get(segment_count)


async def _decode_msgpack_request(req: Request) -> dict:
    body_bytes = await req.body()
    return msgpack.unpackb(body_bytes, raw=False)


def _selection_bounds_by_loc_id(loc_ids: list[str]) -> dict[str, dict]:
    geojson = get_selection_geometries(loc_ids) or {}
    feature_map = {}
    for feature in (geojson.get("features") or []):
        props = feature.get("properties") or {}
        loc_id = props.get("loc_id")
        geometry = feature.get("geometry")
        if not loc_id or not geometry:
            continue
        try:
            minx, miny, maxx, maxy = shapely_shape(geometry).bounds
        except Exception:
            continue
        feature_map[str(loc_id)] = {
            "west": float(minx),
            "south": float(miny),
            "east": float(maxx),
            "north": float(maxy),
        }
    return feature_map


@router.get("/api/fairfax/raster/scenes")
async def get_fairfax_raster_scenes():
    """Return Fairfax LST scene metadata from the source metadata contract."""
    catalog = _load_scene_catalog()
    if catalog is None:
        return msgpack_error("Fairfax raster scene catalog not found", 404)
    return msgpack_response(catalog)


@router.get("/api/fairfax/raster/{period}")
async def get_fairfax_raster(period: str):
    """
    Return pixel data for one Fairfax LST scene.

    Response fields:
      pixels  - raw float32 bytes (row-major, top to bottom, nodata=0.0)
      width   - pixel columns
      height  - pixel rows
      bounds  - {west, south, east, north} in EPSG:4326
      nodata  - 0.0
      period  - scene period string (e.g. "2024-06-14_06-18")
      year    - int year
    """
    import io
    import numpy as np
    import tifffile

    # Validate period against metadata to prevent path traversal.
    # Metadata also carries pre-extracted bounds and dimensions so we never
    # need rasterio (or any native C library) at runtime.
    catalog = _load_scene_catalog()
    if catalog is None:
        return msgpack_error("Fairfax raster scene catalog not found", 404)

    scene = next((s for s in catalog.get("scenes", []) if s["period"] == period), None)
    if scene is None:
        return msgpack_error(f"Unknown period: {period}", 404)

    b = scene.get("bounds")
    if not b:
        return msgpack_error(f"No bounds in metadata for period: {period}", 500)

    try:
        if is_cloud_mode():
            raw_tif = _cloud_object_bytes(f"{RASTER_RELATIVE_DIR}/{scene['file']}")
            if raw_tif is None:
                return msgpack_error(f"Raster file not found for period: {period}", 404)
            data = tifffile.imread(io.BytesIO(raw_tif))
        else:
            tif_path = RASTER_DIR / scene["file"]
            if not tif_path.exists():
                logger.warning(f"Fairfax raster file missing: {tif_path}")
                return msgpack_error(f"Raster file not found for period: {period}", 404)
            data = tifffile.imread(str(tif_path))

        return msgpack_response({
            "pixels": data.astype(np.float32).tobytes(),
            "width":  int(scene["width"]),
            "height": int(scene["height"]),
            "bounds": {
                "west":  float(b["west"]),
                "south": float(b["south"]),
                "east":  float(b["east"]),
                "north": float(b["north"]),
            },
            "nodata": 0.0,
            "period": period,
            "year":   int(scene["year"]),
        })

    except Exception as e:
        logger.error(f"Fairfax raster read error for {period}: {e}")
        return msgpack_error("Failed to read raster data", 500)


@router.post("/api/fairfax/raster/clips")
async def get_fairfax_raster_clips(req: Request):
    """Return loc_id-specific Fairfax raster clips for a given scene period."""
    try:
        body = await _decode_msgpack_request(req)
        period = str(body.get("period") or "").strip()
        loc_ids = [str(value).strip() for value in (body.get("loc_ids") or []) if str(value).strip()]
        if not period:
            return msgpack_error("No period provided", 400)
        if not loc_ids:
            return msgpack_error("No loc_ids provided", 400)

        catalog = _load_scene_catalog()
        if catalog is None:
            return msgpack_error("Fairfax raster scene catalog not found", 404)
        scene = next((s for s in catalog.get("scenes", []) if s["period"] == period), None)
        if scene is None:
            return msgpack_error(f"Unknown period: {period}", 404)

        bounds_by_loc_id = _selection_bounds_by_loc_id(loc_ids)
        clips = []
        for loc_id in loc_ids[:50]:
            level = _loc_id_clip_level(loc_id)
            if not level:
                continue
            bounds = bounds_by_loc_id.get(loc_id)
            if not bounds:
                continue
            relative_path = f"{RASTER_RELATIVE_DIR}/locid_clips/{level}/{period}/{loc_id}.tif"
            try:
                if is_cloud_mode():
                    raw_tif = _cloud_object_bytes(relative_path)
                    if raw_tif is None:
                        continue
                    data = tifffile.imread(io.BytesIO(raw_tif))
                else:
                    tif_path = RASTER_DIR / "locid_clips" / level / period / f"{loc_id}.tif"
                    if not tif_path.exists():
                        continue
                    data = tifffile.imread(str(tif_path))
            except Exception:
                continue

            clips.append({
                "loc_id": loc_id,
                "level": level,
                "period": period,
                "pixels": data.astype("float32").tobytes(),
                "width": int(data.shape[1]),
                "height": int(data.shape[0]),
                "bounds": bounds,
                "nodata": 0.0,
            })

        return msgpack_response({
            "period": period,
            "year": int(scene["year"]),
            "clip_count": len(clips),
            "clips": clips,
        })
    except Exception as exc:
        logger.error(f"Fairfax raster clip read error: {exc}")
        return msgpack_error("Failed to read raster clips", 500)
