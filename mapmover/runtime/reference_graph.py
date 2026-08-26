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

from ..duckdb_helpers import build_guarded_connection, is_cloud_mode, parquet_columns, path_to_uri, select_rows
from ..paths import DATA_ROOT
from ..runtime_config import get_runtime_config
from .published_artifacts import read_artifact_json, relative_data_path
from .geometry_catalog import load_geometry_catalog


ENV_NAME = "GEOGRAPHY_REFERENCE_GRAPH_ROOT"

#: Every country publishes its graph in the same place and the same shape.
#: There is one format - a hash-pinned partition index - so this module never
#: branches on generation. A country is discovered by its directory, not by a
#: hardcoded default, which is what lets families and countries be added one at
#: a time without touching the runtime.
COUNTRY_GRAPH_GLOB = "geometry/countries/*/reference_graph"
GLOBAL_GRAPH_RELATIVE = Path("geometry/global/reference_graph")
COUNTRY_REQUIRED_FILES = (
    "identity_partitions.parquet", "endpoint_families.parquet", "manifest.json",
)
FULL_GRAPH_FILES = (
    "identity_partitions.parquet", "alias_partitions.parquet",
    "shape_partitions.parquet", "relationship_partitions.parquet",
    "endpoint_families.parquet", "source_manifests.parquet", "manifest.json",
)

#: Identity columns read from partitions. Partitions span countries and
#: families with differing schemas, and some carry a GEOMETRY column DuckDB
#: cannot return through ``SELECT *``. Naming the columns keeps the result
#: stable; ``union_by_name`` fills a missing one with NULL.
IDENTITY_COLUMNS = (
    "loc_id", "family", "geography_family", "native_id", "name", "parent_loc_id", "admin_level",
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


@lru_cache(maxsize=16)
def _missing_graph_files(
    root_text: str,
    cloud_mode: bool,
    required_files: tuple[str, ...] = COUNTRY_REQUIRED_FILES,
) -> tuple[str, ...]:
    root = Path(root_text)
    missing: list[str] = []
    for filename in required_files:
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
    for profile in load_geometry_catalog().get("country_profiles") or []:
        if not isinstance(profile, dict):
            continue
        country = str(profile.get("country_code") or "").strip().upper()
        status = str(profile.get("release_status") or "")
        relative = str(profile.get("reference_graph_manifest") or "").replace("\\", "/")
        expected_prefix = f"geometry/countries/{country}/releases/geometry/"
        if (
            len(country) != 3
            or status not in {"approved_for_publication", "published"}
            or not relative.startswith(expected_prefix)
            or not relative.endswith("/runtime/reference_graph/manifest.json")
        ):
            continue
        candidate = (data_root / relative).parent.resolve()
        if not _missing_graph_files(str(candidate), cloud_mode):
            found.append((country, str(candidate)))
    if cloud_mode:
        return tuple(found)
    admitted = {country for country, _ in found}
    for candidate in sorted(data_root.glob(COUNTRY_GRAPH_GLOB)):
        if _missing_graph_files(str(candidate.resolve()), cloud_mode):
            continue
        manifest = _graph_json(candidate / "manifest.json") or {}
        if manifest.get("graph_scope") not in (None, "", "country"):
            continue
        if str(manifest.get("completeness_status") or "").startswith("partial"):
            continue
        country = _country_for_root(candidate.resolve())
        if country and country not in admitted:
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


def clear_reference_graph_cache() -> None:
    _load_graph_json.cache_clear()
    _missing_graph_files.cache_clear()
    _discover_roots.cache_clear()


def global_reference_graph_root() -> Path | None:
    """Return the complete global graph used after country authority."""
    root = (DATA_ROOT / GLOBAL_GRAPH_RELATIVE).resolve()
    if _missing_graph_files(str(root), is_cloud_mode(), FULL_GRAPH_FILES):
        return None
    manifest = _graph_json(root / "manifest.json") or {}
    if manifest.get("graph_scope") != "global":
        return None
    if str(manifest.get("completeness_status") or "").startswith("partial"):
        return None
    return root


def graph_root_for_loc_id(loc_id: str | None) -> Path | None:
    """Pick the graph owning a loc_id, using its country prefix."""
    roots = reference_graph_roots()
    if loc_id:
        country = str(loc_id).split("-", 1)[0].strip().upper()
        if country in roots:
            return roots[country]
    return global_reference_graph_root()


def graph_roots_for_loc_id(loc_id: str | None) -> list[Path]:
    """Prefer country authority, then retain the global fallback."""
    roots: list[Path] = []
    country = graph_root_for_loc_id(loc_id)
    if country is not None:
        roots.append(country)
    global_root = global_reference_graph_root()
    if global_root is not None and global_root not in roots:
        roots.append(global_root)
    return roots


def active_reference_graph_root() -> Path | None:
    """Kept for callers that still expect a single root."""
    roots = reference_graph_roots()
    return next(iter(roots.values()), global_reference_graph_root())


def _partition_paths(root: Path, table: str) -> list[Path]:
    """Resolve one logical table to the partition files backing it."""
    index_name = PARTITION_INDEXES.get(table)
    if not index_name:
        return []
    index_path = root / index_name
    try:
        if index_path.is_file():
            rows = pq.read_table(index_path, columns=["path"]).to_pydict().get("path", [])
        elif is_cloud_mode():
            frame = select_rows(index_path, columns=["path"])
            rows = frame["path"].tolist() if "path" in frame.columns else []
        else:
            return []
    except Exception:
        return []
    return list(dict.fromkeys(DATA_ROOT / str(value) for value in rows if value))


def _table_source(table: str, *, loc_id: str | None = None) -> str:
    """Build the DuckDB read_parquet argument spanning the relevant graphs.

    A loc_id narrows to its owning country; without one every discovered graph
    is searched, so a lookup still works before the country is known.
    """
    roots = (
        graph_roots_for_loc_id(loc_id)
        if loc_id else
        [*reference_graph_roots().values(), *([global_reference_graph_root()] if global_reference_graph_root() else [])]
    )
    return _table_source_for_roots(table, roots)


def _table_source_for_roots(table: str, roots: list[Path]) -> str:
    paths: list[str] = []
    for root in roots:
        paths.extend(
            _sql_path(path)
            for path in _partition_paths(root, table)
            if is_cloud_mode() or path.is_file()
        )
    if not paths:
        return ""
    joined = ", ".join(f"'{path}'" for path in paths)
    return f"[{joined}]"


def _identity_columns(loc_id: str | None = None) -> str:
    """Select the stable identity surface even when every partition omits a field."""
    roots = graph_roots_for_loc_id(loc_id) if loc_id else [
        *reference_graph_roots().values(),
        *([global_reference_graph_root()] if global_reference_graph_root() else []),
    ]
    return _identity_columns_for_roots(roots)


def _identity_columns_for_roots(roots: list[Path]) -> str:
    available: set[str] = set()
    for root in roots:
        for path in _partition_paths(root, "identities"):
            try:
                available.update(parquet_columns(path))
            except Exception:
                continue
    expressions: list[str] = []
    for column in IDENTITY_COLUMNS:
        if column == "family" and "admin_level" in available:
            expressions.append(
                "COALESCE(family, 'admin_' || CAST(CAST(admin_level AS BIGINT) AS VARCHAR)) AS family"
                if "family" in available else
                "'admin_' || CAST(CAST(admin_level AS BIGINT) AS VARCHAR) AS family"
            )
        elif column == "parent_loc_id" and "parent_id" in available:
            expressions.append(
                "COALESCE(parent_loc_id, parent_id) AS parent_loc_id"
                if "parent_loc_id" in available else
                "parent_id AS parent_loc_id"
            )
        else:
            expressions.append(column if column in available else f"NULL AS {column}")
    return ", ".join(expressions)


def reference_graph_available() -> bool:
    return bool(reference_graph_roots() or global_reference_graph_root())


def where_is_geography_data(loc_id: str | None = None) -> dict[str, Any]:
    matching_roots = graph_roots_for_loc_id(loc_id) if loc_id else []
    root = matching_roots[0] if matching_roots else active_reference_graph_root()
    configured = str(os.getenv(ENV_NAME, "")).strip()
    available = reference_graph_available()
    result: dict[str, Any] = {
        "ok": available,
        "mode": "explicit_runtime_selection" if configured else "default_runtime_selection",
        "data_root": str(DATA_ROOT),
        "graph_root": str(root) if root else None,
        "country_graph_roots": {country: str(path) for country, path in reference_graph_roots().items()},
        "global_graph_root": str(global_reference_graph_root()) if global_reference_graph_root() else None,
        "selection_variable": ENV_NAME,
        "local_data_uploaded": False,
        "missing_files": list(_missing_graph_files(str(root), is_cloud_mode())) if root else list(COUNTRY_REQUIRED_FILES),
    }
    if available:
        # Report every discovered graph rather than one. A single release id
        # would have to pick a country arbitrarily now that several are served.
        countries: dict[str, Any] = {}
        for country, country_root in reference_graph_roots().items():
            manifest = _graph_json(country_root / "manifest.json") or {}
            countries[country] = {
                "release_id": manifest.get("release_id"),
                "status": manifest.get("status"),
                "publication_status": manifest.get("publication_status"),
                "families": manifest.get("converted_families") or manifest.get("admitted_families"),
                "totals": manifest.get("metrics"),
            }
        result["countries"] = countries
        global_root = global_reference_graph_root()
        if global_root:
            global_manifest = _graph_json(global_root / "manifest.json") or {}
            result["global"] = {
                "release_id": global_manifest.get("release_id"),
                "status": global_manifest.get("status"),
                "publication_status": global_manifest.get("publication_status"),
                "totals": global_manifest.get("metrics"),
            }
        primary = countries.get(_country_for_root(root), {}) if root else {}
        if not primary and global_root:
            primary = result.get("global", {})
        result.update({
            "release_id": primary.get("release_id"),
            "status": primary.get("status"),
            "scope": ",".join([*sorted(countries), *(["GLOBAL"] if global_root else [])]),
            "totals": primary.get("totals"),
        })
    return result


def reference_graph_families() -> list[dict[str, Any]]:
    """List catalog-admitted canonical families, enriched with graph counts.

    ``geometry_catalog.json`` owns discovery. Partition indexes may enrich a
    catalog family with an identity count, but they never independently expose
    a family. This keeps MCP discovery current when one catalog activation adds
    a country or family, including in cloud mode where graph paths are virtual.
    """
    catalog_families = {
        str(family_id).strip()
        for country in load_geometry_catalog().get("country_family_coverage") or []
        if isinstance(country, dict)
        for family_id in country.get("available_family_ids") or []
        if str(family_id).strip()
    }
    totals = {family: 0 for family in catalog_families}
    roots = list(reference_graph_roots().values())
    global_root = global_reference_graph_root()
    if global_root:
        roots.append(global_root)
    for root in roots:
        index_path = root / PARTITION_INDEXES["identities"]
        try:
            if index_path.is_file():
                rows = pq.read_table(index_path, columns=["family", "row_count"]).to_pydict()
            elif is_cloud_mode():
                frame = select_rows(index_path, columns=["family", "row_count"])
                rows = frame.to_dict(orient="list")
            else:
                continue
        except Exception:
            continue
        for family, count in zip(rows.get("family", []), rows.get("row_count", [])):
            name = str(family or "")
            if not name or name not in catalog_families:
                continue
            try:
                rows_count = int(count)
            except (TypeError, ValueError):
                rows_count = 0
            totals[name] += rows_count
    return [
        {"family": name, "identity_count": identity_count}
        for name, identity_count in sorted(totals.items())
    ]


def identity(loc_id: str) -> dict[str, Any] | None:
    if not reference_graph_available():
        return None
    connection = _connection()
    try:
        # Query roots one at a time so country authority wins deterministically
        # when its Admin0 loc_id is also present in the global fallback.
        for root in graph_roots_for_loc_id(loc_id):
            source = _table_source_for_roots("identities", [root])
            if not source:
                continue
            cursor = connection.execute(
                f"SELECT {_identity_columns_for_roots([root])} "
                f"FROM read_parquet({source}, union_by_name=True) WHERE loc_id = ? LIMIT 1",
                [str(loc_id)],
            )
            row = cursor.fetchone()
            if row is not None:
                return dict(zip([item[0] for item in cursor.description], row))
        return None
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
    source = _table_source("identities")
    if not source:
        return []
    placeholders = ", ".join("?" for _ in requested)
    connection = _connection()
    try:
        cursor = connection.execute(
            f"SELECT {_identity_columns()} FROM read_parquet({source}, union_by_name=True) "
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


def resolve_alias(
    reference_system: str,
    external_id: str,
    *,
    limit: int = 25,
    iso3: str | None = None,
) -> list[dict[str, Any]]:
    if not reference_graph_available():
        return []
    roots = reference_graph_roots()
    country = str(iso3 or "").strip().upper()
    selected_roots = [roots[country]] if country in roots else ([] if country else list(roots.values()))
    global_root = global_reference_graph_root()
    if global_root and not country:
        selected_roots.append(global_root)
    source = _table_source_for_roots("aliases", selected_roots)
    if not source:
        return []
    connection = _connection()
    try:
        cursor = connection.execute(
            f"""SELECT * FROM read_parquet({source}, union_by_name=True)
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
