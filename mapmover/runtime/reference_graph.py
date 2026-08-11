"""Read the integrated geographic reference graph selected for this runtime.

Hosted deployments use their configured published data tree. Local processes
may point ``GEOGRAPHY_REFERENCE_GRAPH_ROOT`` at an unpublished candidate under
``DATA_ROOT`` without changing MCP contracts or uploading local data.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import duckdb

from ..paths import DATA_ROOT


ENV_NAME = "GEOGRAPHY_REFERENCE_GRAPH_ROOT"
DEFAULT_RELATIVE_ROOT = Path("countries/CAN/geometry/crosswalks/canada_reference_graph")
REQUIRED_FILES = (
    "identities.parquet", "identity_versions.parquet", "aliases.parquet",
    "relationships.parquet", "metadata.json", "completion_report.json",
)


def _sql_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def active_reference_graph_root() -> Path:
    configured = str(os.getenv(ENV_NAME, "")).strip()
    if configured:
        path = Path(configured)
        return path.resolve() if path.is_absolute() else (DATA_ROOT / path).resolve()
    return (DATA_ROOT / DEFAULT_RELATIVE_ROOT).resolve()


def reference_graph_available() -> bool:
    root = active_reference_graph_root()
    return all((root / filename).exists() for filename in REQUIRED_FILES)


def where_is_geography_data() -> dict[str, Any]:
    root = active_reference_graph_root()
    configured = str(os.getenv(ENV_NAME, "")).strip()
    available = reference_graph_available()
    result: dict[str, Any] = {
        "ok": available,
        "mode": "explicit_runtime_selection" if configured else "default_runtime_selection",
        "data_root": str(DATA_ROOT),
        "graph_root": str(root),
        "selection_variable": ENV_NAME,
        "local_data_uploaded": False,
        "missing_files": [name for name in REQUIRED_FILES if not (root / name).exists()],
    }
    if available:
        metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
        completion = json.loads((root / "completion_report.json").read_text(encoding="utf-8"))
        result.update({
            "release_id": metadata.get("release_id"),
            "status": completion.get("status"),
            "scope": metadata.get("scope"),
            "totals": completion.get("totals"),
        })
        candidate_pointer = DATA_ROOT / "countries" / "CAN" / "geometry" / "releases" / "candidates" / "current.json"
        if candidate_pointer.exists():
            pointer = json.loads(candidate_pointer.read_text(encoding="utf-8"))
            pointer_root = (DATA_ROOT / str(pointer.get("graph_root") or "")).resolve()
            if pointer_root == root:
                result["candidate_release_id"] = pointer.get("release_id")
                result["publication_status"] = pointer.get("publication_status")
    return result


def reference_graph_families() -> list[dict[str, Any]]:
    if not reference_graph_available():
        return []
    root = active_reference_graph_root()
    connection = duckdb.connect()
    try:
        rows = connection.execute(
            f"""SELECT family, count(*) AS identity_count,
                       count(*) FILTER (WHERE has_shape) AS shape_count
                FROM read_parquet('{_sql_path(root / 'identities.parquet')}')
                GROUP BY family ORDER BY family"""
        ).fetchall()
    finally:
        connection.close()
    return [
        {"family": row[0], "identity_count": int(row[1]), "shape_count": int(row[2])}
        for row in rows
    ]


def identity(loc_id: str) -> dict[str, Any] | None:
    if not reference_graph_available():
        return None
    root = active_reference_graph_root()
    connection = duckdb.connect()
    try:
        cursor = connection.execute(
            f"SELECT * FROM read_parquet('{_sql_path(root / 'identities.parquet')}') WHERE loc_id = ? LIMIT 1",
            [str(loc_id)],
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(zip([item[0] for item in cursor.description], row))
    finally:
        connection.close()


def aliases_for_loc_id(loc_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    if not reference_graph_available():
        return []
    root = active_reference_graph_root()
    connection = duckdb.connect()
    try:
        cursor = connection.execute(
            f"""SELECT * FROM read_parquet('{_sql_path(root / 'aliases.parquet')}')
                WHERE loc_id = ? ORDER BY reference_system, external_id LIMIT ?""",
            [str(loc_id), max(1, int(limit))],
        )
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        connection.close()


def resolve_alias(reference_system: str, external_id: str, *, limit: int = 25) -> list[dict[str, Any]]:
    if not reference_graph_available():
        return []
    root = active_reference_graph_root()
    connection = duckdb.connect()
    try:
        cursor = connection.execute(
            f"""SELECT * FROM read_parquet('{_sql_path(root / 'aliases.parquet')}')
                WHERE lower(reference_system) = lower(?) AND external_id = ?
                ORDER BY loc_id LIMIT ?""",
            [str(reference_system), str(external_id), max(1, int(limit))],
        )
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        connection.close()


def relationships_for_loc_id(
    loc_id: str, *, direction: str = "both", limit: int = 100
) -> list[dict[str, Any]]:
    if not reference_graph_available():
        return []
    direction = str(direction).strip().lower()
    if direction == "outgoing":
        predicate, values = "source_loc_id = ?", [str(loc_id)]
    elif direction == "incoming":
        predicate, values = "target_loc_id = ?", [str(loc_id)]
    else:
        predicate, values = "source_loc_id = ? OR target_loc_id = ?", [str(loc_id), str(loc_id)]
    root = active_reference_graph_root()
    connection = duckdb.connect()
    try:
        cursor = connection.execute(
            f"""SELECT * FROM read_parquet('{_sql_path(root / 'relationships.parquet')}')
                WHERE {predicate}
                ORDER BY relationship_type, relationship_vintage, relationship_id
                LIMIT ?""",
            [*values, max(1, int(limit))],
        )
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        connection.close()
