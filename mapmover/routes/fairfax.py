"""Fairfax LST raster API endpoints."""

from pathlib import Path

from fastapi import APIRouter

from mapmover.logging_analytics import logger
from mapmover.paths import COUNTRIES_DIR
from mapmover.routes.disasters.helpers import msgpack_error, msgpack_response

router = APIRouter()

RASTER_DIR = COUNTRIES_DIR / "USA" / "fairfax_lst" / "rasters"


def _load_manifest() -> dict | None:
    manifest_path = RASTER_DIR / "manifest.json"
    if not manifest_path.exists():
        return None
    import json
    with open(manifest_path) as f:
        return json.load(f)


@router.get("/api/fairfax/raster/manifest")
async def get_fairfax_raster_manifest():
    """
    Return the scene manifest for Fairfax LST raster files.
    Lists available scenes with period, year, and filename.
    """
    manifest = _load_manifest()
    if manifest is None:
        return msgpack_error("Fairfax raster manifest not found", 404)
    return msgpack_response(manifest)


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
    import numpy as np
    import rasterio

    # Validate period against manifest to prevent path traversal
    manifest = _load_manifest()
    if manifest is None:
        return msgpack_error("Fairfax raster manifest not found", 404)

    scene = next((s for s in manifest.get("scenes", []) if s["period"] == period), None)
    if scene is None:
        return msgpack_error(f"Unknown period: {period}", 404)

    tif_path = RASTER_DIR / scene["file"]
    if not tif_path.exists():
        logger.warning(f"Fairfax raster file missing: {tif_path}")
        return msgpack_error(f"Raster file not found for period: {period}", 404)

    try:
        with rasterio.open(tif_path) as src:
            data = src.read(1)
            bounds = src.bounds

        return msgpack_response({
            "pixels": data.astype(np.float32).tobytes(),
            "width":  int(data.shape[1]),
            "height": int(data.shape[0]),
            "bounds": {
                "west":  float(bounds.left),
                "south": float(bounds.bottom),
                "east":  float(bounds.right),
                "north": float(bounds.top),
            },
            "nodata": 0.0,
            "period": period,
            "year":   int(scene["year"]),
        })

    except Exception as e:
        logger.error(f"Fairfax raster read error for {period}: {e}")
        return msgpack_error("Failed to read raster data", 500)
