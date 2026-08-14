"""Resolve shape-backed reference-graph identities to their adopted banks.

Reference families do not all live in one global marine file. An identity row
names its geometry-bank directory; that bank's identity-version row names the
partition containing the shape. This module follows that stored contract and
returns the same normalized frame consumed by the existing geometry tools.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from shapely.geometry import mapping, shape
from shapely.wkb import loads as load_wkb

from ..duckdb_helpers import parquet_available, parquet_columns, path_to_uri, run_df, select_rows
from ..paths import DATA_ROOT
from .reference_graph import identities


IDENTITY_VERSION_COLUMNS = ["loc_id", "geometry_partition", "shape_storage"]
DIRECT_ADMIN_PARTITION_BANKS = {"dissemination_area", "dissemination_block"}


def _safe_bank_root(value: str | None) -> Path | None:
    text = str(value or "").strip().replace("\\", "/")
    if not text or Path(text).is_absolute():
        return None
    root = (DATA_ROOT / text).resolve()
    try:
        root.relative_to(DATA_ROOT.resolve())
    except ValueError:
        return None
    return root


def _safe_partition_path(bank_root: Path, value: str | None) -> Path | None:
    text = str(value or "").strip().replace("\\", "/")
    if not text or Path(text).is_absolute() or not text.lower().endswith(".parquet"):
        return None
    path = (bank_root / text).resolve()
    try:
        path.relative_to(bank_root.resolve())
    except ValueError:
        return None
    return path


def _read_shape_partition(path: Path, loc_ids: list[str]) -> pd.DataFrame:
    if not loc_ids or not parquet_available(path):
        return pd.DataFrame()
    available = parquet_columns(path)
    if "loc_id" not in available or "geometry" not in available:
        return pd.DataFrame()
    ordinary = [
        column for column in (
            "loc_id", "name", "name_en", "name_fr", "family", "subtype",
            "source_id", "source_release", "area_square_km",
        ) if column in available
    ]
    selected = ", ".join(f'"{column}"' for column in ordinary)
    placeholders = ", ".join("?" for _ in loc_ids)
    sql = (
        f"SELECT {selected}, ST_AsWKB(\"geometry\") AS __geometry_wkb "
        f"FROM read_parquet(?) WHERE \"loc_id\" IN ({placeholders})"
    )
    return run_df(sql, [path_to_uri(path), *loc_ids])


def _read_single_file_bank(path: Path, loc_ids: list[str]) -> pd.DataFrame:
    """Read a legacy/adopted bank whose polygons live in one Parquet file."""
    if not loc_ids or not parquet_available(path):
        return pd.DataFrame()
    available = parquet_columns(path)
    if "loc_id" not in available or "geometry" not in available:
        return pd.DataFrame()
    columns = [
        column for column in (
            "loc_id", "name", "name_en", "name_fr", "family", "subtype",
            "source_id", "source_release", "area_square_km", "geometry",
        ) if column in available
    ]
    return select_rows(path, columns=columns, in_filters={"loc_id": loc_ids})


def _direct_admin_partitions(bank_root: Path, loc_ids: list[str]) -> dict[Path, list[str]]:
    """Map deep Canada admin ids to their province-sharded Parquet banks."""
    if bank_root.name not in DIRECT_ADMIN_PARTITION_BANKS:
        return {}
    partitions: dict[Path, list[str]] = {}
    for loc_id in loc_ids:
        parts = str(loc_id).split("-")
        if len(parts) < 2 or parts[0] != "CAN" or len(parts[1]) != 2:
            continue
        partitions.setdefault(bank_root / f"CAN-{parts[1]}.parquet", []).append(loc_id)
    return partitions


def _normalized_row(row: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any] | None:
    raw_wkb = row.get("__geometry_wkb")
    raw_geometry = row.get("geometry")
    try:
        if raw_wkb:
            geometry = load_wkb(bytes(raw_wkb))
        elif isinstance(raw_geometry, str):
            geometry = shape(json.loads(raw_geometry))
        elif isinstance(raw_geometry, dict):
            geometry = shape(raw_geometry)
        elif raw_geometry:
            geometry = load_wkb(bytes(raw_geometry))
        else:
            return None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if geometry.is_empty:
        return None
    min_lon, min_lat, max_lon, max_lat = geometry.bounds
    centroid = geometry.centroid
    bank = str(identity.get("geometry_bank") or "").strip()
    return {
        "loc_id": row.get("loc_id") or identity.get("loc_id"),
        "name": row.get("name") or row.get("name_en") or identity.get("name"),
        "name_local": row.get("name_fr"),
        "family": row.get("family") or identity.get("family"),
        "admin_level": identity.get("admin_level"),
        "parent_id": identity.get("parent_loc_id"),
        "centroid_lon": float(centroid.x),
        "centroid_lat": float(centroid.y),
        "bbox_min_lon": float(min_lon),
        "bbox_min_lat": float(min_lat),
        "bbox_max_lon": float(max_lon),
        "bbox_max_lat": float(max_lat),
        "has_polygon": True,
        "geometry": mapping(geometry),
        "source_id": row.get("source_id") or identity.get("native_id"),
        "source_system": identity.get("source_system"),
        "source_vintage": identity.get("source_vintage") or row.get("source_release"),
        "geometry_vintage": identity.get("source_vintage") or row.get("source_release"),
        "geometry_source": identity.get("source_system"),
        "bank_id": bank,
    }


def load_reference_graph_geometry(
    loc_ids: Iterable[str],
    *,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Load shapes for graph identities whose bank owns a shape partition."""
    requested = list(dict.fromkeys(str(item).strip() for item in loc_ids if str(item).strip()))
    if not requested:
        return pd.DataFrame(columns=columns or [])
    identity_rows = identities(requested)
    by_id = {
        str(row.get("loc_id")): row
        for row in identity_rows
        if row.get("has_shape") is True and row.get("geometry_bank")
    }
    by_bank: dict[Path, list[str]] = {}
    for loc_id in requested:
        bank_root = _safe_bank_root((by_id.get(loc_id) or {}).get("geometry_bank"))
        if bank_root is not None:
            by_bank.setdefault(bank_root, []).append(loc_id)

    normalized: list[dict[str, Any]] = []
    for bank_root, bank_ids in by_bank.items():
        if bank_root.suffix.lower() == ".parquet":
            shape_rows = _read_single_file_bank(bank_root, bank_ids)
            for row in shape_rows.to_dict("records"):
                identity = by_id.get(str(row.get("loc_id"))) or {}
                item = _normalized_row(row, identity)
                if item is not None:
                    normalized.append(item)
            continue
        direct_partitions = _direct_admin_partitions(bank_root, bank_ids)
        if direct_partitions:
            for partition, partition_ids in direct_partitions.items():
                shape_rows = _read_single_file_bank(partition, partition_ids)
                for row in shape_rows.to_dict("records"):
                    identity = by_id.get(str(row.get("loc_id"))) or {}
                    item = _normalized_row(row, identity)
                    if item is not None:
                        normalized.append(item)
            continue
        versions_path = bank_root / "identity_versions.parquet"
        version_rows = select_rows(
            versions_path,
            columns=IDENTITY_VERSION_COLUMNS,
            in_filters={"loc_id": bank_ids},
        )
        if version_rows is None or version_rows.empty:
            continue
        partitions: dict[Path, list[str]] = {}
        for row in version_rows.to_dict("records"):
            partition = _safe_partition_path(bank_root, row.get("geometry_partition"))
            if partition is not None and str(row.get("shape_storage") or "").strip() != "identity_only":
                partitions.setdefault(partition, []).append(str(row.get("loc_id")))
        for partition, partition_ids in partitions.items():
            shape_rows = _read_shape_partition(partition, partition_ids)
            for row in shape_rows.to_dict("records"):
                identity = by_id.get(str(row.get("loc_id"))) or {}
                item = _normalized_row(row, identity)
                if item is not None:
                    normalized.append(item)

    frame = pd.DataFrame(normalized)
    if frame.empty:
        return pd.DataFrame(columns=columns or [])
    if columns:
        keep = [column for column in columns if column in frame.columns]
        if "loc_id" not in keep:
            keep.insert(0, "loc_id")
        return frame[keep].copy()
    return frame
