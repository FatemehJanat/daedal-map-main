"""Shared access contract for immutable runtime artifacts.

This module owns object-store location and basic bytes/JSON reads for data,
geometry, reference, catalog, and raster artifacts.  It intentionally does not
serve mutable control/Ops objects or account-owned/generated artifacts.

Tier-2 local hydration will be added behind this contract.  Callers should not
construct published bucket keys or create their own S3 clients.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

from ..runtime_config import get_runtime_config


ArtifactLane = Literal["active", "published"]


@dataclass(frozen=True)
class PublishedArtifactRef:
    """Canonical object identity for one immutable runtime artifact."""

    relative_path: str
    bucket: str
    key: str
    prefix: str
    endpoint_url: str | None
    region: str
    lane: ArtifactLane

    @property
    def uri(self) -> str:
        return f"s3://{self.bucket}/{self.key}"


def _cloud_config() -> dict[str, Any]:
    config = get_runtime_config().get("cloud", {}) or {}
    return config if isinstance(config, dict) else {}


def _normalize_relative_path(relative_path: str | Path) -> str:
    raw = str(relative_path).strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if (
        not raw
        or raw in {".", ".."}
        or path.is_absolute()
        or PureWindowsPath(raw).is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"Artifact path must be a safe non-empty relative path: {relative_path!r}")
    return path.as_posix()


def artifact_prefix(lane: ArtifactLane = "published") -> str:
    """Return the one configured object prefix for the requested immutable lane."""
    cloud_cfg = _cloud_config()
    active = (
        os.environ.get("S3_PREFIX", "").strip()
        or str(cloud_cfg.get("prefix", "")).strip()
    )
    if lane == "active":
        return (active or "published").strip("/")
    if lane != "published":
        raise ValueError(f"Unsupported artifact lane: {lane}")
    return (
        os.environ.get("S3_PUBLISHED_PREFIX", "").strip()
        or active
        or "published"
    ).strip("/")


def artifact_ref(
    relative_path: str | Path,
    *,
    lane: ArtifactLane = "published",
) -> PublishedArtifactRef:
    """Build the canonical object-store identity for an immutable artifact."""
    cloud_cfg = _cloud_config()
    bucket = os.environ.get("S3_BUCKET", "").strip() or str(cloud_cfg.get("bucket", "")).strip()
    if not bucket:
        raise RuntimeError("Published artifact access requires S3_BUCKET or cloud.bucket")
    relative = _normalize_relative_path(relative_path)
    prefix = artifact_prefix(lane)
    key = f"{prefix}/{relative}" if prefix else relative
    endpoint_url = os.environ.get("S3_ENDPOINT_URL", "").strip() or str(
        cloud_cfg.get("endpoint_url", "") or ""
    ).strip()
    region = (
        os.environ.get("AWS_DEFAULT_REGION", "").strip()
        or os.environ.get("AWS_REGION", "").strip()
        or "auto"
    )
    return PublishedArtifactRef(
        relative_path=relative,
        bucket=bucket,
        key=key,
        prefix=prefix,
        endpoint_url=endpoint_url or None,
        region=region,
        lane=lane,
    )


def relative_data_path(path: Path, *, data_root: Path) -> str:
    """Return a canonical published path for a file under DATA_ROOT."""
    try:
        relative = path.resolve().relative_to(data_root.resolve())
    except ValueError as exc:
        raise ValueError(f"Artifact path is outside DATA_ROOT: {path}") from exc
    return _normalize_relative_path(relative)


def data_artifact_ref(
    path: Path,
    *,
    data_root: Path,
    lane: ArtifactLane = "active",
) -> PublishedArtifactRef:
    return artifact_ref(relative_data_path(path, data_root=data_root), lane=lane)


def _object_store_client(ref: PublishedArtifactRef):
    import boto3

    return boto3.client("s3", endpoint_url=ref.endpoint_url, region_name=ref.region)


def read_artifact_bytes(
    relative_path: str | Path,
    *,
    lane: ArtifactLane = "published",
) -> bytes:
    """Read immutable artifact bytes from object storage.

    Missing objects and transport errors intentionally propagate so each domain
    caller can apply its existing fallback/error policy.
    """
    ref = artifact_ref(relative_path, lane=lane)
    response = _object_store_client(ref).get_object(Bucket=ref.bucket, Key=ref.key)
    return response["Body"].read()


def read_artifact_json(
    relative_path: str | Path,
    *,
    lane: ArtifactLane = "published",
) -> Any:
    """Read and decode one immutable JSON artifact."""
    return json.loads(read_artifact_bytes(relative_path, lane=lane))
