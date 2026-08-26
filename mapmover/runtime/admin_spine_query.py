"""Bounded two-stage point lookup for published country admin-spine layouts."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from functools import lru_cache

from shapely import from_wkb
from shapely.geometry import Point
import pandas as pd

from ..duckdb_helpers import build_guarded_connection, is_cloud_mode, path_to_uri
from ..paths import COUNTRY_GEOMETRY_DIR, DATA_ROOT
from .geometry_catalog import load_geometry_catalog
from .published_artifacts import read_artifact_json


META_COLUMNS = """
loc_id, parent_id, admin_level, name,
admin_0_loc_id, admin_1_loc_id, admin_2_loc_id, admin_3_loc_id,
admin_4_loc_id, admin_5_loc_id, admin_6_loc_id,
bbox_min_lon, bbox_min_lat, bbox_max_lon, bbox_max_lat
"""


@lru_cache(maxsize=64)
def layout_root(iso3: str) -> Path:
    country = str(iso3 or "").strip().upper()
    profiles = [
        profile for profile in load_geometry_catalog().get("country_profiles") or []
        if isinstance(profile, dict) and str(profile.get("country_code") or "").upper() == country
        and str(profile.get("release_status") or "") in {"approved_for_publication", "published"}
    ]
    if len(profiles) == 1:
        relative = str(profiles[0].get("query_layout_manifest") or "").replace("\\", "/")
        expected_prefix = f"geometry/countries/{country}/releases/geometry/"
        if relative.startswith(expected_prefix) and relative.endswith("/runtime/admin_spine/manifest.json"):
            return Path(DATA_ROOT) / Path(relative).parent
    # Cloud activation is catalog-owned and fails closed. The fixed legacy root
    # remains only for local development against pre-release holdings.
    if is_cloud_mode():
        return Path(DATA_ROOT) / "__catalog_has_no_admitted_country_layout__" / country
    return Path(COUNTRY_GEOMETRY_DIR) / country / "admin_spine"


def layout_available(iso3: str) -> bool:
    root = layout_root(iso3)
    if not is_cloud_mode():
        return (root / "manifest.json").is_file() and (root / "admin_0_3.parquet").is_file()
    try:
        relative_root = root.relative_to(Path(DATA_ROOT)).as_posix()
    except ValueError:
        return False
    if not relative_root.startswith(f"geometry/countries/{str(iso3).upper()}/releases/geometry/"):
        return False
    expected = relative_root + "/manifest.json"
    return _published_layout_manifest_available(str(iso3).upper(), expected)


def clear_admin_spine_query_cache() -> None:
    layout_root.cache_clear()
    _published_layout_manifest_available.cache_clear()


@lru_cache(maxsize=64)
def _published_layout_manifest_available(iso3: str, relative_path: str) -> bool:
    try:
        # Follow the runtime's selected immutable lane. Hosted production sets
        # active=published; release smoke may deliberately set active=staging.
        payload = read_artifact_json(relative_path, lane="active")
    except Exception:
        return False
    return bool(
        isinstance(payload, dict)
        and payload.get("status") == "PASS"
        and str(payload.get("country") or "").upper() == iso3
        and payload.get("layout_policy") == "national_admin_0_3_plus_admin_1_owned_deep"
    )


def _connection():
    connection = build_guarded_connection()
    connection.execute("SET memory_limit='400MB'")
    connection.execute("SET threads=1")
    connection.execute("SET preserve_insertion_order=false")
    return connection


def _metadata(connection, path: Path, lon: float, lat: float,
              admin3: str = "") -> list[tuple]:
    owner_clause = "" if not admin3 else " AND admin_3_loc_id = ?"
    parameters: list[Any] = [path_to_uri(path), lon, lon, lat, lat]
    if admin3:
        parameters.append(admin3)
    return connection.execute(f"""
        SELECT {META_COLUMNS}
        FROM read_parquet(?)
        WHERE bbox_max_lon >= ? AND bbox_min_lon <= ?
          AND bbox_max_lat >= ? AND bbox_min_lat <= ? {owner_clause}
        ORDER BY admin_level, loc_id
    """, parameters).fetchall()


def _exact_rows(connection, path: Path, rows: list[tuple],
                lon: float, lat: float) -> list[tuple[tuple, bytes, float]]:
    if not rows:
        return []
    identifiers = [row[0] for row in rows]
    placeholders = ",".join("?" for _ in identifiers)
    shapes = dict(connection.execute(
        f"SELECT loc_id, ST_AsWKB(geometry) FROM read_parquet(?) WHERE loc_id IN ({placeholders})",
        [path_to_uri(path), *identifiers],
    ).fetchall())
    point = Point(lon, lat)
    matches = []
    for row in rows:
        geometry_wkb = bytes(shapes[row[0]])
        geometry = from_wkb(geometry_wkb)
        if geometry.covers(point):
            matches.append((row, geometry_wkb, float(geometry.area)))
    return matches


def _row_dict(row: tuple) -> dict[str, Any]:
    names = [part.strip() for part in META_COLUMNS.replace("\n", " ").split(",")]
    return dict(zip(names, row))


def resolve_point(
    iso3: str, lon: float, lat: float, *, target_admin_level: int | None = None,
) -> dict[str, Any] | None:
    """Resolve one point through the national Admin0-3 file and one owner file.

    ``target_admin_level`` bounds the work, it does not just filter the answer.
    The national ``admin_0_3.parquet`` already covers Admin 0-3, so a request
    that stops at or above Admin 3 never opens the deep per-Admin1 partition -
    the expensive read in this path. Callers asking for country, state, or
    county geography are the common case, and they now skip it entirely.
    """
    iso3 = str(iso3 or "").strip().upper()
    if not layout_available(iso3):
        return None
    root = layout_root(iso3)
    connection = _connection()
    try:
        shallow_meta = _metadata(connection, root / "admin_0_3.parquet", lon, lat)
        shallow = _exact_rows(connection, root / "admin_0_3.parquet", shallow_meta, lon, lat)
        if not shallow:
            return None
        shallow.sort(key=lambda item: (int(item[0][2]), -item[2], str(item[0][0])))
        shallow_by_level: dict[int, tuple[tuple, bytes, float]] = {}
        for item in shallow:
            shallow_by_level[int(item[0][2])] = item
        anchor = shallow[-1][0]
        admin1, admin3 = str(anchor[5] or ""), str(anchor[7] or "")
        deep: list[tuple[tuple, bytes, float]] = []
        deep_path = root / "deep" / f"{admin1}.parquet"
        needs_deep = target_admin_level is None or int(target_admin_level) > 3
        if needs_deep and admin3 and (is_cloud_mode() or deep_path.is_file()):
            deep_meta = _metadata(connection, deep_path, lon, lat, admin3)
            deep = _exact_rows(connection, deep_path, deep_meta, lon, lat)
            deep.sort(key=lambda item: (int(item[0][2]), -item[2], str(item[0][0])))
        all_matches = [shallow_by_level[level] for level in sorted(shallow_by_level)] + deep
        by_level: dict[int, tuple[tuple, bytes, float]] = {}
        for item in all_matches:
            by_level[int(item[0][2])] = item
        ordered = [by_level[level] for level in sorted(by_level)]
        final = ordered[-1]
        return {
            "country": iso3,
            "stack": [_row_dict(item[0]) for item in ordered],
            "matched": _row_dict(final[0]),
            "geometry_wkb": final[1],
            "shallow_candidate_count": len(shallow_meta),
            "deep_candidate_count": len(deep) if deep else 0,
            "query_layout": True,
        }
    finally:
        connection.close()


def load_rows_by_loc_ids(iso3: str, loc_ids: list[str], columns: list[str] | None = None) -> pd.DataFrame:
    """Load exact rows from an admitted country query layout.

    This is the shape-fetch counterpart to :func:`resolve_point`.  Keeping it
    on the same layout seam lets ``get_geometry`` retrieve the loc_id returned
    by point resolution without falling back to a legacy country bank.
    """
    iso3 = str(iso3 or "").strip().upper()
    requested = list(dict.fromkeys(str(value).strip() for value in loc_ids if str(value).strip()))
    if not requested or not layout_available(iso3):
        return pd.DataFrame()
    projection = list(dict.fromkeys(["loc_id", *(columns or [])]))
    # DuckDB's spatial GEOMETRY logical type cannot be converted directly to
    # a pandas/NumPy column. Runtime geometry loaders use WKB, so normalize the
    # shape at the SQL boundary while preserving every other field.
    select_clause = (
        "* EXCLUDE (geometry), ST_AsWKB(geometry) AS geometry"
        if columns is None
        else ", ".join(f'"{name}"' for name in projection)
    )
    root = layout_root(iso3)
    requests_by_path: dict[Path, list[str]] = {}
    for loc_id in requested:
        parts = loc_id.split("-")
        admin_level = len(parts) - 1
        if admin_level <= 3:
            path = root / "admin_0_3.parquet"
        else:
            owner_loc_id = "-".join(parts[:2])
            path = root / "deep" / f"{owner_loc_id}.parquet"
        requests_by_path.setdefault(path, []).append(loc_id)
    connection = _connection()
    try:
        frames = []
        for path, path_loc_ids in requests_by_path.items():
            if not path.is_file() and not is_cloud_mode():
                continue
            placeholders = ",".join("?" for _ in path_loc_ids)
            frame = connection.execute(
                f"SELECT {select_clause} FROM read_parquet(?) WHERE loc_id IN ({placeholders})",
                [path_to_uri(path), *path_loc_ids],
            ).fetchdf()
            if not frame.empty:
                frames.append(frame)
        if not frames:
            return pd.DataFrame()
        result = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["loc_id"], keep="first")
        order = {loc_id: index for index, loc_id in enumerate(requested)}
        result["_requested_order"] = result["loc_id"].map(order)
        return result.sort_values("_requested_order").drop(columns=["_requested_order"]).reset_index(drop=True)
    finally:
        connection.close()
