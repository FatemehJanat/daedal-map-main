"""Bounded two-stage point lookup for published country admin-spine layouts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
from shapely import from_wkb
from shapely.geometry import Point

from ..paths import COUNTRY_GEOMETRY_DIR


META_COLUMNS = """
loc_id, parent_id, admin_level, name,
admin_0_loc_id, admin_1_loc_id, admin_2_loc_id, admin_3_loc_id,
admin_4_loc_id, admin_5_loc_id, admin_6_loc_id,
bbox_min_lon, bbox_min_lat, bbox_max_lon, bbox_max_lat
"""


def layout_root(iso3: str) -> Path:
    return Path(COUNTRY_GEOMETRY_DIR) / str(iso3 or "").strip().upper() / "admin_spine"


def layout_available(iso3: str) -> bool:
    root = layout_root(iso3)
    return (root / "manifest.json").is_file() and (root / "admin_0_3.parquet").is_file()


def _connection() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute("SET memory_limit='400MB'")
    connection.execute("SET threads=1")
    connection.execute("SET preserve_insertion_order=false")
    return connection


def _metadata(connection: duckdb.DuckDBPyConnection, path: Path, lon: float, lat: float,
              admin3: str = "") -> list[tuple]:
    owner_clause = "" if not admin3 else " AND admin_3_loc_id = ?"
    parameters: list[Any] = [str(path), lon, lon, lat, lat]
    if admin3:
        parameters.append(admin3)
    return connection.execute(f"""
        SELECT {META_COLUMNS}
        FROM read_parquet(?)
        WHERE bbox_max_lon >= ? AND bbox_min_lon <= ?
          AND bbox_max_lat >= ? AND bbox_min_lat <= ? {owner_clause}
        ORDER BY admin_level, loc_id
    """, parameters).fetchall()


def _exact_rows(connection: duckdb.DuckDBPyConnection, path: Path, rows: list[tuple],
                lon: float, lat: float) -> list[tuple[tuple, bytes, float]]:
    if not rows:
        return []
    identifiers = [row[0] for row in rows]
    placeholders = ",".join("?" for _ in identifiers)
    shapes = dict(connection.execute(
        f"SELECT loc_id, ST_AsWKB(geometry) FROM read_parquet(?) WHERE loc_id IN ({placeholders})",
        [str(path), *identifiers],
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


def resolve_point(iso3: str, lon: float, lat: float) -> dict[str, Any] | None:
    """Resolve one point through the national Admin0-3 file and one owner file."""
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
        if admin3 and deep_path.is_file():
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
