"""Generic scene-raster API endpoints."""

import io
import os
from pathlib import Path

import msgpack
from fastapi import APIRouter, Request, Response

from mapmover.data_loading import get_source_path, load_full_catalog, load_source_metadata
from mapmover.duckdb_helpers import is_cloud_mode
from mapmover.logging_analytics import logger
from mapmover.paths import COUNTRIES_DIR
from mapmover.routes.disasters.helpers import msgpack_error, msgpack_response
from mapmover.runtime_config import get_runtime_config

router = APIRouter()


def _require_tifffile():
    """Import tifffile only when a raster endpoint is actually exercised."""
    try:
        import tifffile  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Raster endpoints require the optional Python package 'tifffile'. "
            "Install county-map/requirements.txt to enable raster scene reads."
        ) from exc
    return tifffile


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
        logger.warning("Raster cloud read requested without S3 bucket configured")
        return None

    try:
        client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region)
        obj = client.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except Exception as exc:
        logger.warning(f"Raster cloud read failed for {key}: {exc}")
        return None


def _normalize_raster_relative_dir(path_value: str) -> str:
    text = str(path_value or "").strip().strip("/")
    return text.removesuffix("/")


def _source_supports_scene_rasters(source_id: str) -> bool:
    metadata = load_source_metadata(source_id) or {}
    raster_products = metadata.get("raster_products") or {}
    scene_rasters = raster_products.get("scene_rasters") or {}
    scenes = scene_rasters.get("scenes") or []
    return isinstance(scenes, list) and bool(scenes)


def _load_scene_catalog(source_id: str) -> dict | None:
    metadata = load_source_metadata(source_id) or {}
    raster_products = metadata.get("raster_products") or {}
    scene_rasters = raster_products.get("scene_rasters") or {}
    scenes = scene_rasters.get("scenes") or []
    if not isinstance(scenes, list) or not scenes:
        return None
    source_path = get_source_path(source_id)
    relative_dir = _normalize_raster_relative_dir(
        scene_rasters.get("path") or (f"{source_path.relative_to(COUNTRIES_DIR.parent).as_posix()}/rasters" if source_path else "")
    )
    return {
        "source_id": source_id,
        "display_name": str(metadata.get("source_name") or source_id),
        "crs": str(scene_rasters.get("crs") or "EPSG:4326"),
        "nodata": float(scene_rasters.get("nodata") or 0.0),
        "value_unit": str(scene_rasters.get("value_unit") or "Value"),
        "relative_dir": relative_dir,
        "scenes": scenes,
    }


def _find_related_raster_source(source_id: str) -> str | None:
    normalized_source_id = str(source_id or "").strip()
    if not normalized_source_id:
        return None
    if _source_supports_scene_rasters(normalized_source_id):
        return normalized_source_id

    metadata = load_source_metadata(normalized_source_id) or {}
    pack_id = str(metadata.get("pack_id") or "").strip()
    if not pack_id:
        return None

    catalog = load_full_catalog() or {}
    pack_sources = [
        source for source in (catalog.get("sources") or [])
        if str(source.get("pack_id") or "").strip() == pack_id
    ]
    for source in pack_sources:
        candidate = str(source.get("source_id") or "").strip()
        if candidate and candidate != normalized_source_id and _source_supports_scene_rasters(candidate):
            return candidate
    return None


def _raster_dirs_for_source(source_id: str, catalog: dict | None) -> tuple[Path | None, str | None]:
    source_path = get_source_path(source_id)
    local_dir = source_path / "rasters" if source_path else None
    relative_dir = _normalize_raster_relative_dir((catalog or {}).get("relative_dir"))
    if not relative_dir and source_path is not None:
        try:
            relative_dir = source_path.relative_to(COUNTRIES_DIR.parent).as_posix().rstrip("/") + "/rasters"
        except Exception:
            relative_dir = ""
    return local_dir, relative_dir or None


def _clip_bundle_relative_path(raster_relative_dir: str | None, period: str) -> str | None:
    if not raster_relative_dir:
        return None
    base = raster_relative_dir.strip().rstrip("/")
    if not base:
        return None
    return f"{base}/clip_bundles/{period}.msgpack"


def _load_clip_bundle_bytes(source_id: str, catalog: dict | None, period: str) -> bytes | None:
    raster_dir, raster_relative_dir = _raster_dirs_for_source(source_id, catalog)
    relative_path = _clip_bundle_relative_path(raster_relative_dir, period)
    if is_cloud_mode():
        return _cloud_object_bytes(relative_path) if relative_path else None
    if raster_dir is None:
        return None
    bundle_path = raster_dir / "clip_bundles" / f"{period}.msgpack"
    if not bundle_path.exists():
        return None
    return bundle_path.read_bytes()


def _load_clip_bundle_payload(source_id: str, catalog: dict | None, period: str) -> dict | None:
    raw = _load_clip_bundle_bytes(source_id, catalog, period)
    if not raw:
        return None
    try:
        payload = msgpack.unpackb(raw, raw=False)
    except Exception as exc:
        logger.warning(f"Could not decode raster clip bundle for {source_id} {period}: {exc}")
        return None
    return payload if isinstance(payload, dict) else None


async def _decode_msgpack_request(req: Request) -> dict:
    body_bytes = await req.body()
    return msgpack.unpackb(body_bytes, raw=False)


@router.get("/api/raster/resolve/{source_id}")
async def resolve_raster_source(source_id: str):
    """Resolve a source or its pack sibling to the raster-capable source id."""
    resolved_source_id = _find_related_raster_source(source_id)
    if not resolved_source_id:
        return msgpack_error(f"No raster-capable source found for {source_id}", 404)
    catalog = _load_scene_catalog(resolved_source_id)
    if catalog is None:
        return msgpack_error(f"Raster scene catalog not found for {resolved_source_id}", 404)
    return msgpack_response({
        "requested_source_id": source_id,
        "source_id": resolved_source_id,
        "display_name": catalog.get("display_name") or resolved_source_id,
        "scene_count": len(catalog.get("scenes") or []),
    })


@router.get("/api/raster/{source_id}/scenes")
async def get_raster_scenes(source_id: str):
    """Return source-driven scene-raster metadata from the source metadata contract."""
    catalog = _load_scene_catalog(source_id)
    if catalog is None:
        return msgpack_error(f"Raster scene catalog not found for {source_id}", 404)
    return msgpack_response(catalog)


@router.get("/api/raster/{source_id}/{period}")
async def get_raster_scene(source_id: str, period: str):
    """Return pixel data for one published scene raster."""
    import numpy as np

    catalog = _load_scene_catalog(source_id)
    if catalog is None:
        return msgpack_error(f"Raster scene catalog not found for {source_id}", 404)

    scene = next((s for s in catalog.get("scenes", []) if s["period"] == period), None)
    if scene is None:
        return msgpack_error(f"Unknown period: {period}", 404)

    bounds = scene.get("bounds")
    if not bounds:
        return msgpack_error(f"No bounds in metadata for period: {period}", 500)

    raster_dir, raster_relative_dir = _raster_dirs_for_source(source_id, catalog)

    try:
        tifffile = _require_tifffile()
        if is_cloud_mode():
            raw_tif = _cloud_object_bytes(f"{raster_relative_dir}/{scene['file']}")
            if raw_tif is None:
                return msgpack_error(f"Raster file not found for period: {period}", 404)
            data = tifffile.imread(io.BytesIO(raw_tif))
        else:
            tif_path = raster_dir / scene["file"]
            if not tif_path.exists():
                logger.warning(f"Raster file missing for {source_id}: {tif_path}")
                return msgpack_error(f"Raster file not found for period: {period}", 404)
            data = tifffile.imread(str(tif_path))

        return msgpack_response({
            "source_id": source_id,
            "pixels": data.astype(np.float32).tobytes(),
            "width": int(scene["width"]),
            "height": int(scene["height"]),
            "bounds": {
                "west": float(bounds["west"]),
                "south": float(bounds["south"]),
                "east": float(bounds["east"]),
                "north": float(bounds["north"]),
            },
            "nodata": 0.0,
            "period": period,
            "year": int(scene["year"]),
        })

    except Exception as exc:
        logger.error(f"Raster read error for {source_id} period {period}: {exc}")
        return msgpack_error("Failed to read raster data", 500)


@router.get("/api/raster/{source_id}/clip-bundle/{period}")
async def get_raster_clip_bundle(source_id: str, period: str):
    """Return a prebuilt msgpack clip bundle for one scene period."""
    catalog = _load_scene_catalog(source_id)
    if catalog is None:
        return msgpack_error(f"Raster scene catalog not found for {source_id}", 404)

    scene = next((s for s in catalog.get("scenes", []) if s["period"] == period), None)
    if scene is None:
        return msgpack_error(f"Unknown period: {period}", 404)

    raw_bundle = _load_clip_bundle_bytes(source_id, catalog, period)
    if not raw_bundle:
        return msgpack_error(f"Raster clip bundle not found for period: {period}", 404)
    return Response(content=raw_bundle, media_type="application/msgpack")


@router.post("/api/raster/{source_id}/clips")
async def get_raster_clips(source_id: str, req: Request):
    """Return loc_id-specific raster clips for a given source and scene period."""
    try:
        body = await _decode_msgpack_request(req)
        period = str(body.get("period") or "").strip()
        loc_ids = [str(value).strip() for value in (body.get("loc_ids") or []) if str(value).strip()]
        if not period:
            return msgpack_error("No period provided", 400)
        if not loc_ids:
            return msgpack_error("No loc_ids provided", 400)

        catalog = _load_scene_catalog(source_id)
        if catalog is None:
            return msgpack_error(f"Raster scene catalog not found for {source_id}", 404)
        scene = next((s for s in catalog.get("scenes", []) if s["period"] == period), None)
        if scene is None:
            return msgpack_error(f"Unknown period: {period}", 404)

        bundle_payload = _load_clip_bundle_payload(source_id, catalog, period)
        if not bundle_payload:
            return msgpack_error(
                f"Raster clip bundle not found for period: {period}. "
                "This runtime now depends on published clip bundles rather than legacy per-clip TIFFs.",
                404,
            )

        clips_by_loc_id = bundle_payload.get("clips_by_loc_id") or {}
        clips = []
        for loc_id in loc_ids[:50]:
            clip = clips_by_loc_id.get(loc_id)
            if not isinstance(clip, dict):
                continue

            clips.append({
                "loc_id": loc_id,
                "level": str(clip.get("level") or ""),
                "period": period,
                "pixels": clip.get("pixels") or b"",
                "width": int(clip.get("width") or 0),
                "height": int(clip.get("height") or 0),
                "bounds": clip.get("bounds") or {},
                "nodata": float(clip.get("nodata") or 0.0),
            })

        return msgpack_response({
            "source_id": source_id,
            "period": period,
            "year": int(bundle_payload.get("year") or scene["year"]),
            "clip_count": len(clips),
            "clips": clips,
        })
    except Exception as exc:
        logger.error(f"Raster clip read error for {source_id}: {exc}")
        return msgpack_error("Failed to read raster clips", 500)
