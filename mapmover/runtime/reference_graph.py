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

import pyarrow.parquet as pq
from pathlib import Path
from typing import Any

from ..duckdb_helpers import build_guarded_connection, is_cloud_mode, parquet_columns, path_to_uri
from ..paths import DATA_ROOT
from ..runtime_config import get_runtime_config
from .published_artifacts import read_artifact_json, relative_data_path


ENV_NAME = "GEOGRAPHY_REFERENCE_GRAPH_ROOT"

#: Every country publishes its graph in the same place and the same shape.
#: There is one format - a hash-pinned partition index - so this module never
#: branches on generation. A country is discovered by its directory, not by a
#: hardcoded default, which is what lets families and countries be added one at
#: a time without touching the runtime.
COUNTRY_GRAPH_GLOB = "geometry/countries/*/reference_graph"
REQUIRED_FILES = ("identity_partitions.parquet", "endpoint_families.parquet", "manifest.json")

#: Identity columns read from partitions. Partitions span countries and
#: families with differing schemas, and some carry a GEOMETRY column DuckDB
#: cannot return through ``SELECT *``. Naming the columns keeps the result
#: stable; ``union_by_name`` fills a missing one with NULL.
IDENTITY_COLUMNS = (
    "loc_id", "family", "native_id", "name", "parent_loc_id", "admin_level",
    "namespace_release", "valid_from", "valid_to", "has_shape", "geometry_bank",
    "geometry_status", "source_system", "source_vintage", "geometry_loc_id",
    "source_loc_id", "sibling_level", "sibling_anchor_loc_id",
    "smallest_full_container_loc_id", "crosses_sibling_boundaries_at_or_above_anchor",
    "source_area_sq_km", "assignment_method",
)

#: Index file naming the partitions for each logical table.
PARTITION_INDEXES = {
    "identities": "identity_partitions.parquet",
    "identity_versions": "identity_partitions.parquet",
    "aliases": "alias_partitions.parquet",
    "relationships": "relationship_partitions.parquet",
}


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
        # Keep JSON sidecars on the same configured immutable lane as the
        # Parquet graph files. Production's active lane is ``published``;
        # isolated operator QA may explicitly select ``staging``.
        payload = read_artifact_json(_relative_data_path(path), lane="active")
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


@lru_cache(maxsize=4)
def _discover_roots(data_root_text: str, override: str, cloud_mode: bool) -> tuple[tuple[str, str], ...]:
    data_root = Path(data_root_text)
    if override:
        path = Path(override)
        resolved = path.resolve() if path.is_absolute() else (data_root / path).resolve()
        country = _country_for_root(resolved)
        return ((country, str(resolved)),) if country else (("", str(resolved)),)
    found: list[tuple[str, str]] = []
    for candidate in sorted(data_root.glob(COUNTRY_GRAPH_GLOB)):
        if _missing_graph_files(str(candidate.resolve()), cloud_mode):
            continue
        country = _country_for_root(candidate.resolve())
        if country:
            found.append((country, str(candidate.resolve())))
    return tuple(found)


def _country_for_root(root: Path) -> str:
    manifest = _graph_json(root / "manifest.json") or {}
    country = str(manifest.get("country") or "").strip().upper()
    if country:
        return country
    # Fall back to the owning directory so a graph is still selectable when its
    # manifest predates the country field.
    parts = root.parts
    return parts[parts.index("countries") + 1].upper() if "countries" in parts else ""


def reference_graph_roots() -> dict[str, Path]:
    """Return every discoverable country graph, keyed by ISO3."""
    override = str(os.getenv(ENV_NAME, "")).strip()
    return {
        country: Path(path)
        for country, path in _discover_roots(str(DATA_ROOT), override, is_cloud_mode())
    }


def graph_root_for_loc_id(loc_id: str | None) -> Path | None:
    """Pick the graph owning a loc_id, using its country prefix."""
    roots = reference_graph_roots()
    if not roots:
        return None
    if loc_id:
        country = str(loc_id).split("-", 1)[0].strip().upper()
        if country in roots:
            return roots[country]
    return None


def active_reference_graph_root() -> Path | None:
    """Kept for callers that still expect a single root."""
    roots = reference_graph_roots()
    return next(iter(roots.values()), None)


def _partition_paths(root: Path, table: str) -> list[Path]:
    """Resolve one logical table to the partition files backing it."""
    index_name = PARTITION_INDEXES.get(table)
    if not index_name:
        return []
    index_path = root / index_name
    if not index_path.is_file():
        return []
    try:
        rows = pq.read_table(index_path, columns=["path"]).to_pydict().get("path", [])
    except Exception:
        return []
    return [DATA_ROOT / str(value) for value in rows if value]


def _table_source(table: str, *, loc_id: str | None = None) -> str:
    """Build the DuckDB read_parquet argument spanning the relevant graphs.

    A loc_id narrows to its owning country; without one every discovered graph
    is searched, so a lookup still works before the country is known.
    """
    selected = graph_root_for_loc_id(loc_id)
    roots = [selected] if selected else list(reference_graph_roots().values())
    paths: list[str] = []
    for root in roots:
        paths.extend(_sql_path(path) for path in _partition_paths(root, table) if path.is_file())
    if not paths:
        return ""
    joined = ", ".join(f"'{path}'" for path in paths)
    return f"[{joined}]"


def _identity_columns() -> str:
    return ", ".join(IDENTITY_COLUMNS)


def reference_graph_available() -> bool:
    return bool(reference_graph_roots())


def where_is_geography_data() -> dict[str, Any]:
    root = active_reference_graph_root()
    configured = str(os.getenv(ENV_NAME, "")).strip()
    available = reference_graph_available()
    result: dict[str, Any] = {
        "ok": available,
        "mode": "explicit_runtime_selection" if configured else "default_runtime_selection",
        "data_root": str(DATA_ROOT),
        "graph_root": str(root) if root else None,
        "country_graph_roots": {country: str(path) for country, path in reference_graph_roots().items()},
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
        candidate_pointer = DATA_ROOT / "geometry" / "countries" / "CAN" / "releases" / "candidates" / "current.json"
        if not is_cloud_mode() and candidate_pointer.exists():
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
                FROM read_parquet({_table_source('identities')}, union_by_name=True)
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
            f"SELECT {_identity_columns()} FROM read_parquet({_table_source('identities', loc_id=loc_id)}, union_by_name=True) WHERE loc_id = ? LIMIT 1",
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
                FROM read_parquet({_table_source('identity_versions')}, union_by_name=True)
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
                    FROM read_parquet({_table_source('identity_versions')}, union_by_name=True)
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
            f"SELECT {_identity_columns()} FROM read_parquet({_table_source('identities')}, union_by_name=True) "
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
            f"""SELECT * FROM read_parquet({_table_source('aliases')}, union_by_name=True)
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
            f"""SELECT * FROM read_parquet({_table_source('aliases')}, union_by_name=True)
                WHERE lower(reference_system) = lower(?) AND external_id = ?
                ORDER BY loc_id LIMIT ?""",
            [str(reference_system), str(external_id), max(1, int(limit))],
        )
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        connection.close()


def identify_aliases(external_ids: list[str], *, limit: int = 500) -> list[dict[str, Any]]:
    """Return exact alias rows across all reference systems in one scan."""
    requested = list(dict.fromkeys(str(item).strip() for item in external_ids if str(item).strip()))
    if not requested or not reference_graph_available():
        return []
    root = active_reference_graph_root()
    placeholders = ", ".join("?" for _ in requested)
    connection = _connection()
    try:
        cursor = connection.execute(
            f"""SELECT * FROM read_parquet({_table_source('aliases')}, union_by_name=True)
                WHERE external_id IN ({placeholders})
                ORDER BY reference_system, external_id, loc_id LIMIT ?""",
            [*requested, max(1, int(limit))],
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
        path = _table_source("relationships", loc_id=loc_id)

        def selected_rows(column: str) -> list[dict[str, Any]]:
            cursor = connection.execute(
                f"SELECT * FROM read_parquet({path}, union_by_name=True) WHERE {column} = ? LIMIT ?",
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
