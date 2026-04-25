"""Research artifact tools.

Tools operate on the corpus registry and existing session cache. They return bounded
JSON-serializable results for LLM context.
"""

from __future__ import annotations

import math
from typing import Any

from mapmover.corpus_registry import corpus_registry
from mapmover.session_cache import session_manager

try:
    import duckdb
except Exception:  # pragma: no cover - optional runtime dependency
    duckdb = None


RESEARCH_TOOL_DEFINITIONS = [
    {
        "name": "list_artifacts",
        "description": "List the artifacts currently loaded in the active research corpus.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "describe_artifact",
        "description": "Get metadata, fields, metrics, geography, and summary for one loaded artifact.",
        "input_schema": {
            "type": "object",
            "properties": {
                "artifact_id": {"type": "string"},
            },
            "required": ["artifact_id"],
        },
    },
    {
        "name": "query_artifact_slice",
        "description": "Return a small filtered, grouped, sorted slice from one loaded artifact.",
        "input_schema": {
            "type": "object",
            "properties": {
                "artifact_id": {"type": "string"},
                "fields": {"type": "array", "items": {"type": "string"}},
                "metrics": {"type": "array", "items": {"type": "string"}},
                "filters": {"type": "object"},
                "group_by": {"type": "array", "items": {"type": "string"}},
                "order_by": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "direction": {"type": "string", "enum": ["asc", "desc"]},
                        },
                    },
                },
                "limit": {"type": "integer", "minimum": 1},
            },
            "required": ["artifact_id"],
        },
    },
    {
        "name": "build_artifact_display_subset",
        "description": "Build a feature subset from one loaded artifact for map display or highlighting. If limit is omitted, return all matched features.",
        "input_schema": {
            "type": "object",
            "properties": {
                "artifact_id": {"type": "string"},
                "fields": {"type": "array", "items": {"type": "string"}},
                "metrics": {"type": "array", "items": {"type": "string"}},
                "filters": {"type": "object"},
                "order_by": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "direction": {"type": "string", "enum": ["asc", "desc"]},
                        },
                    },
                },
                "limit": {"type": "integer", "minimum": 1},
                "fit": {"type": "boolean"},
                "context_visibility": {"type": "string", "enum": ["keep", "replace"]},
            },
            "required": ["artifact_id"],
        },
    },
]


def _jsonable(value: Any):
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "item"):
        return _jsonable(value.item())
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _get_cached_result(session_id: str, request_key: str) -> dict | None:
    cache = session_manager.get(session_id)
    if not cache:
        return None
    result = cache.get_cached_result(request_key)
    if result is not None:
        return result
    root_key = str(request_key or "").split(":", 1)[0]
    return cache.get_cached_result(root_key) if root_key else None


def _rows_from_result(result: dict) -> list[dict]:
    rows = []
    feature_names = {}
    for feature in (result.get("geojson") or {}).get("features") or []:
        props = dict(feature.get("properties") or {})
        loc_id = props.get("loc_id") or feature.get("id")
        if loc_id:
            feature_names[str(loc_id)] = props.get("name") or loc_id
        if not result.get("year_data"):
            rows.append(_jsonable(props))

    year_data = result.get("year_data") or {}
    for year, loc_map in year_data.items():
        for loc_id, metrics in (loc_map or {}).items():
            row = {"loc_id": loc_id, "name": feature_names.get(str(loc_id), loc_id), "year": int(year) if str(year).isdigit() else year}
            row.update(metrics or {})
            rows.append(_jsonable(row))
    return rows


def _feature_lookup_from_result(result: dict) -> dict[str, dict]:
    lookup = {}
    for feature in (result.get("geojson") or {}).get("features") or []:
        props = dict(feature.get("properties") or {})
        loc_id = props.get("loc_id") or feature.get("id")
        if loc_id:
            lookup[str(loc_id)] = _jsonable(feature)
    return lookup


def _normalize_limit(value) -> int:
    try:
        return max(1, min(int(value), 1000))
    except Exception:
        return 25


def _normalize_optional_limit(value, *, maximum: int | None = None) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = max(1, int(value))
    except Exception:
        return None
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def _filter_rows_python(rows: list[dict], filters: dict | None) -> list[dict]:
    if not filters:
        return rows

    def matches(row: dict) -> bool:
        for field, expected in filters.items():
            actual = row.get(field)
            if isinstance(expected, dict):
                if "min" in expected and (actual is None or actual < expected["min"]):
                    return False
                if "max" in expected and (actual is None or actual > expected["max"]):
                    return False
                if "eq" in expected and actual != expected["eq"]:
                    return False
                if "in" in expected and actual not in expected["in"]:
                    return False
            elif isinstance(expected, list):
                if actual not in expected:
                    return False
            elif actual != expected:
                return False
        return True

    return [row for row in rows if matches(row)]


def _query_rows_python(
    rows: list[dict],
    tool_input: dict,
    *,
    default_limit: int | None = 25,
    maximum_limit: int | None = 1000,
) -> dict:
    rows = _filter_rows_python(rows, tool_input.get("filters"))
    fields = tool_input.get("fields") or []
    metrics = tool_input.get("metrics") or []
    group_by = tool_input.get("group_by") or []
    selected = [f for f in [*group_by, *fields, *metrics] if f]
    if not selected and rows:
        selected = list(rows[0].keys())

    if group_by:
        grouped: dict[tuple, dict] = {}
        for row in rows:
            key = tuple(row.get(field) for field in group_by)
            bucket = grouped.setdefault(key, {field: row.get(field) for field in group_by})
            for metric in metrics:
                value = row.get(metric)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    state = bucket.setdefault(f"_{metric}_values", [])
                    state.append(value)
        output = []
        for bucket in grouped.values():
            row = {field: bucket.get(field) for field in group_by}
            for metric in metrics:
                values = bucket.get(f"_{metric}_values", [])
                row[f"{metric}_avg"] = sum(values) / len(values) if values else None
                row[f"{metric}_count"] = len(values)
            output.append(row)
        rows = output
    else:
        rows = [{field: row.get(field) for field in selected if field in row} for row in rows]

    for sort in reversed(tool_input.get("order_by") or []):
        field = sort.get("field")
        reverse = sort.get("direction", "desc") == "desc"
        if field:
            rows.sort(key=lambda row: (row.get(field) is None, row.get(field)), reverse=reverse)

    limit = _normalize_optional_limit(tool_input.get("limit"), maximum=maximum_limit)
    if limit is None:
        limit = default_limit
    if limit is None:
        return {"rows": rows, "row_count": len(rows), "truncated": False}
    return {"rows": rows[:limit], "row_count": len(rows), "truncated": len(rows) > limit}


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _query_rows_duckdb(
    rows: list[dict],
    tool_input: dict,
    *,
    default_limit: int | None = 25,
    maximum_limit: int | None = 1000,
) -> dict:
    if duckdb is None:
        return _query_rows_python(rows, tool_input, default_limit=default_limit, maximum_limit=maximum_limit)
    try:
        import pandas as pd
    except Exception:
        return _query_rows_python(rows, tool_input, default_limit=default_limit, maximum_limit=maximum_limit)

    if not rows:
        return {"rows": [], "row_count": 0, "truncated": False}

    df = pd.DataFrame(rows)
    con = duckdb.connect(database=":memory:")
    try:
        con.register("artifact_rows", df)
        where_parts = []
        params = []
        for field, expected in (tool_input.get("filters") or {}).items():
            if field not in df.columns:
                continue
            ident = _quote_identifier(field)
            if isinstance(expected, dict):
                if "min" in expected:
                    where_parts.append(f"{ident} >= ?")
                    params.append(expected["min"])
                if "max" in expected:
                    where_parts.append(f"{ident} <= ?")
                    params.append(expected["max"])
                if "eq" in expected:
                    where_parts.append(f"{ident} = ?")
                    params.append(expected["eq"])
                if "in" in expected and expected["in"]:
                    placeholders = ", ".join("?" for _ in expected["in"])
                    where_parts.append(f"{ident} IN ({placeholders})")
                    params.extend(expected["in"])
            elif isinstance(expected, list) and expected:
                placeholders = ", ".join("?" for _ in expected)
                where_parts.append(f"{ident} IN ({placeholders})")
                params.extend(expected)
            else:
                where_parts.append(f"{ident} = ?")
                params.append(expected)

        fields = [f for f in (tool_input.get("fields") or []) if f in df.columns]
        metrics = [m for m in (tool_input.get("metrics") or []) if m in df.columns]
        group_by = [g for g in (tool_input.get("group_by") or []) if g in df.columns]
        if group_by:
            select_parts = [_quote_identifier(field) for field in group_by]
            for metric in metrics:
                ident = _quote_identifier(metric)
                select_parts.append(f"avg({ident}) AS {_quote_identifier(metric + '_avg')}")
                select_parts.append(f"count({ident}) AS {_quote_identifier(metric + '_count')}")
            sql = f"SELECT {', '.join(select_parts)} FROM artifact_rows"
        else:
            selected = [*fields, *metrics] or list(df.columns)
            sql = f"SELECT {', '.join(_quote_identifier(field) for field in selected if field in df.columns)} FROM artifact_rows"

        if where_parts:
            sql += " WHERE " + " AND ".join(where_parts)
        if group_by:
            sql += " GROUP BY " + ", ".join(_quote_identifier(field) for field in group_by)

        order_parts = []
        for sort in tool_input.get("order_by") or []:
            field = sort.get("field")
            direction = "ASC" if sort.get("direction") == "asc" else "DESC"
            allowed = set(df.columns) | {f"{m}_avg" for m in metrics} | {f"{m}_count" for m in metrics}
            if field in allowed:
                order_parts.append(f"{_quote_identifier(field)} {direction}")
        if order_parts:
            sql += " ORDER BY " + ", ".join(order_parts)

        limit = _normalize_optional_limit(tool_input.get("limit"), maximum=maximum_limit)
        if limit is None:
            limit = default_limit
        count_sql = f"SELECT count(*) AS row_count FROM ({sql}) q"
        row_count = con.execute(count_sql, params).fetchone()[0]
        if limit is not None:
            sql += f" LIMIT {limit}"
        output = con.execute(sql, params).fetchdf().to_dict("records")
        return {
            "rows": _jsonable(output),
            "row_count": row_count,
            "truncated": bool(limit is not None and row_count > limit),
        }
    finally:
        con.close()


def _build_display_subset(result: dict, artifact: dict, tool_input: dict) -> dict:
    rows = _rows_from_result(result)
    query_result = _query_rows_duckdb(rows, tool_input, default_limit=None, maximum_limit=None)
    matched_rows = query_result.get("rows") or []
    feature_lookup = _feature_lookup_from_result(result)

    loc_ids = []
    rows_by_loc: dict[str, dict] = {}
    for row in matched_rows:
        loc_id = row.get("loc_id")
        if loc_id is None:
            continue
        loc_text = str(loc_id)
        if loc_text not in loc_ids:
            loc_ids.append(loc_text)
        rows_by_loc.setdefault(loc_text, row)

    features = []
    for loc_id in loc_ids:
        feature = feature_lookup.get(loc_id)
        if not feature:
            continue
        props = dict(feature.get("properties") or {})
        props.update(rows_by_loc.get(loc_id) or {})
        feature["properties"] = _jsonable(props)
        features.append(feature)

    display = {
        "action": "highlight_features",
        "artifact_id": artifact.get("artifact_id"),
        "source_id": artifact.get("source_id"),
        "geojson": {"type": "FeatureCollection", "features": features},
        "loc_ids": loc_ids,
        "fit": bool(tool_input.get("fit", True)),
        "context_visibility": str(tool_input.get("context_visibility") or "keep"),
    }
    return {
        "artifact_id": artifact.get("artifact_id"),
        "rows": matched_rows,
        "row_count": query_result.get("row_count", 0),
        "truncated": bool(query_result.get("truncated")),
        "display": display,
    }


def execute_research_tool(session_id: str, tool_name: str, tool_input: dict) -> dict:
    tool_input = tool_input or {}
    if tool_name == "list_artifacts":
        return {"artifacts": corpus_registry.list_artifacts(session_id)}

    artifact_id = tool_input.get("artifact_id")
    artifact = corpus_registry.get_artifact(session_id, artifact_id) if artifact_id else None
    if not artifact:
        return {"error": "artifact_not_found", "artifact_id": artifact_id}

    if tool_name == "describe_artifact":
        artifact.pop("order", None)
        return {"artifact": artifact}

    if tool_name == "query_artifact_slice":
        result = _get_cached_result(session_id, artifact.get("request_key"))
        if not result:
            return {"error": "artifact_data_unavailable", "artifact_id": artifact_id}
        rows = _rows_from_result(result)
        query_result = _query_rows_duckdb(rows, tool_input, default_limit=25, maximum_limit=1000)
        return {
            "artifact_id": artifact_id,
            "fields": artifact.get("fields", []),
            **query_result,
        }

    if tool_name == "build_artifact_display_subset":
        result = _get_cached_result(session_id, artifact.get("request_key"))
        if not result:
            return {"error": "artifact_data_unavailable", "artifact_id": artifact_id}
        return _build_display_subset(result, artifact, tool_input)

    return {"error": "unknown_tool", "tool_name": tool_name}
