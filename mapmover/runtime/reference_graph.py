"""Read the integrated geographic reference graph selected for this runtime.

Hosted deployments use their configured published data tree. Local processes
may point ``GEOGRAPHY_REFERENCE_GRAPH_ROOT`` at an unpublished candidate under
``DATA_ROOT`` without changing MCP contracts or uploading local data.
"""

from __future__ import annotations

import json
import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..duckdb_helpers import build_guarded_connection, is_cloud_mode, parquet_columns, path_to_uri
from ..paths import DATA_ROOT
from ..runtime_config import get_runtime_config
from .published_artifacts import read_artifact_json, relative_data_path


ENV_NAME = "GEOGRAPHY_REFERENCE_GRAPH_ROOT"
DEFAULT_RELATIVE_ROOT = Path("countries/CAN/geometry/crosswalks/canada_reference_graph")
REQUIRED_FILES = (
    "identities.parquet", "identity_versions.parquet", "aliases.parquet",
    "relationships.parquet", "metadata.json", "completion_report.json",
)


def _sql_path(path: Path) -> str:
    return path_to_uri(path).replace("'", "''")


def _connection():
    connection = build_guarded_connection()
    if connection is None:
        raise RuntimeError("DuckDB is required for reference-graph queries")
    connection.execute("SET enable_progress_bar=false")
    return connection


def _relative_data_path(path: Path) -> str:
    return relative_data_path(path, data_root=DATA_ROOT)


@lru_cache(maxsize=16)
def _load_graph_json(path_text: str, cloud_mode: bool) -> dict[str, Any] | None:
    path = Path(path_text)
    if not cloud_mode:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    try:
        payload = read_artifact_json(_relative_data_path(path), lane="published")
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _graph_json(path: Path) -> dict[str, Any] | None:
    return _load_graph_json(str(path.resolve()), is_cloud_mode())


@lru_cache(maxsize=8)
def _missing_graph_files(root_text: str, cloud_mode: bool) -> tuple[str, ...]:
    root = Path(root_text)
    missing: list[str] = []
    for filename in REQUIRED_FILES:
        path = root / filename
        if filename.endswith(".json"):
            available = _load_graph_json(str(path.resolve()), cloud_mode) is not None
        elif cloud_mode:
            try:
                available = bool(parquet_columns(path))
            except Exception:
                available = False
        else:
            available = path.is_file()
        if not available:
            missing.append(filename)
    return tuple(missing)


def active_reference_graph_root() -> Path:
    configured = str(os.getenv(ENV_NAME, "")).strip()
    if configured:
        path = Path(configured)
        return path.resolve() if path.is_absolute() else (DATA_ROOT / path).resolve()
    return (DATA_ROOT / DEFAULT_RELATIVE_ROOT).resolve()


def reference_graph_available() -> bool:
    root = active_reference_graph_root()
    return not _missing_graph_files(str(root), is_cloud_mode())


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
        "missing_files": list(_missing_graph_files(str(root), is_cloud_mode())),
    }
    if available:
        metadata = _graph_json(root / "metadata.json") or {}
        completion = _graph_json(root / "completion_report.json") or {}
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
    connection = _connection()
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
    connection = _connection()
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


def identity_at(loc_id: str, as_of: date | None = None) -> dict[str, Any] | None:
    """Return the graph identity state selected for a requested date.

    ``identity_versions`` may contain several releases for a durable loc_id.
    A dated lookup selects the row whose half-open validity window contains
    the date; an undated lookup retains the canonical ``identities`` behavior.
    """
    if as_of is None:
        return identity(loc_id)
    if not reference_graph_available():
        return None
    root = active_reference_graph_root()
    connection = _connection()
    try:
        cursor = connection.execute(
            f"""SELECT *
                FROM read_parquet('{_sql_path(root / 'identity_versions.parquet')}')
                WHERE loc_id = ?
                  AND (valid_from IS NULL OR valid_from = '' OR CAST(valid_from AS DATE) <= ?)
                  AND (valid_to IS NULL OR valid_to = '' OR CAST(valid_to AS DATE) > ?)
                ORDER BY valid_from DESC NULLS LAST, namespace_release DESC
                LIMIT 1""",
            [str(loc_id), as_of, as_of],
        )
        row = cursor.fetchone()
        if row is None:
            # Preserve the identity and its declared window even when the
            # requested date falls outside it, so callers can report a typed
            # temporal mismatch instead of treating the loc_id as unknown.
            cursor = connection.execute(
                f"""SELECT *
                    FROM read_parquet('{_sql_path(root / 'identity_versions.parquet')}')
                    WHERE loc_id = ?
                    ORDER BY valid_from DESC NULLS LAST, namespace_release DESC
                    LIMIT 1""",
                [str(loc_id)],
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return dict(zip([item[0] for item in cursor.description], row))
    finally:
        connection.close()


def identities(loc_ids: list[str]) -> list[dict[str, Any]]:
    """Return graph identities in caller order with one predicate-pushed scan."""
    requested = list(dict.fromkeys(str(item).strip() for item in loc_ids if str(item).strip()))
    if not requested or not reference_graph_available():
        return []
    root = active_reference_graph_root()
    placeholders = ", ".join("?" for _ in requested)
    connection = _connection()
    try:
        cursor = connection.execute(
            f"SELECT * FROM read_parquet('{_sql_path(root / 'identities.parquet')}') "
            f"WHERE loc_id IN ({placeholders})",
            requested,
        )
        columns = [item[0] for item in cursor.description]
        found = {str(row[0]): dict(zip(columns, row)) for row in cursor.fetchall()}
        return [found[loc_id] for loc_id in requested if loc_id in found]
    finally:
        connection.close()


def aliases_for_loc_id(loc_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    if not reference_graph_available():
        return []
    root = active_reference_graph_root()
    connection = _connection()
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
    connection = _connection()
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
    root = active_reference_graph_root()
    connection = _connection()
    try:
        requested_limit = max(1, int(limit))
        path = _sql_path(root / "relationships.parquet")

        def selected_rows(column: str) -> list[dict[str, Any]]:
            cursor = connection.execute(
                f"SELECT * FROM read_parquet('{path}') WHERE {column} = ? LIMIT ?",
                [str(loc_id), requested_limit],
            )
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

        if direction == "outgoing":
            rows = selected_rows("source_loc_id")
        elif direction == "incoming":
            rows = selected_rows("target_loc_id")
        else:
            rows = selected_rows("source_loc_id") + selected_rows("target_loc_id")
            rows = list({str(row.get("relationship_id")): row for row in rows}.values())

        rows.sort(key=lambda row: (
            str(row.get("relationship_type") or ""),
            str(row.get("relationship_vintage") or ""),
            str(row.get("relationship_id") or ""),
        ))
        return rows[:requested_limit]
    finally:
        connection.close()
