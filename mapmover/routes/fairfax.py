"""Fairfax LST raster API endpoints."""

import io
import json
import os
from pathlib import Path

from fastapi import APIRouter

from mapmover.duckdb_helpers import is_cloud_mode
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


def _load_manifest() -> dict | None:
    if is_cloud_mode():
        raw = _cloud_object_bytes(f"{RASTER_RELATIVE_DIR}/manifest.json")
        if raw is None:
            return None
        return json.loads(raw)

    manifest_path = RASTER_DIR / "manifest.json"
    if not manifest_path.exists():
        return None
    with open(manifest_path, encoding="utf-8") as f:
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
    import io
    import numpy as np
    import tifffile

    # Validate period against manifest to prevent path traversal.
    # Manifest also carries pre-extracted bounds and dimensions so we never
    # need rasterio (or any native C library) at runtime.
    manifest = _load_manifest()
    if manifest is None:
        return msgpack_error("Fairfax raster manifest not found", 404)

    scene = next((s for s in manifest.get("scenes", []) if s["period"] == period), None)
    if scene is None:
        return msgpack_error(f"Unknown period: {period}", 404)

    b = scene.get("bounds")
    if not b:
        return msgpack_error(f"No bounds in manifest for period: {period}", 500)

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
