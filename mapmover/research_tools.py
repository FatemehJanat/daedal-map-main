"""Research artifact tools.

Tools operate on the corpus registry and existing session cache. They return bounded
JSON-serializable results for LLM context.
"""

from __future__ import annotations

import math
from typing import Any

from mapmover import logger
from mapmover.corpus_registry import corpus_registry
from mapmover.geometry_handlers import get_selection_geometries
from mapmover.request_risk_gate import block_gate, warn_gate
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
        "description": "Return a small filtered, grouped, sorted slice from one loaded artifact. Grouped numeric metrics include sum, avg, count, min, and max fields.",
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
                "style": {
                    "type": "object",
                    "properties": {
                        "fill_color": {"type": "string"},
                        "stroke_color": {"type": "string"},
                    },
                },
            },
            "required": ["artifact_id"],
        },
    },
]


RESEARCH_DISPLAY_SOFT_CAP = 5000
RESEARCH_DISPLAY_HARD_CAP = 25000


def _normalize_tool_input(tool_name: str, tool_input: Any) -> dict:
    if not isinstance(tool_input, dict):
        return {}

    normalized: dict[str, Any] = {}
    artifact_id = tool_input.get("artifact_id")
    if artifact_id is not None:
        normalized["artifact_id"] = str(artifact_id)

    for key in ("fields", "metrics", "group_by"):
        values = tool_input.get(key)
        if isinstance(values, list):
            normalized[key] = [str(value) for value in values if value is not None and str(value).strip()]

    filters = tool_input.get("filters")
    if isinstance(filters, dict):
        normalized["filters"] = filters

    order_by = tool_input.get("order_by")
    if isinstance(order_by, list):
        cleaned_order = []
        for item in order_by:
            if not isinstance(item, dict):
                continue
            field = item.get("field")
            if field is None or not str(field).strip():
                continue
            direction = str(item.get("direction") or "desc").strip().lower()
            cleaned_order.append(
                {
                    "field": str(field),
                    "direction": "asc" if direction == "asc" else "desc",
                }
            )
        normalized["order_by"] = cleaned_order

    if "limit" in tool_input:
        normalized["limit"] = tool_input.get("limit")
    if tool_name == "build_artifact_display_subset":
        if "fit" in tool_input:
            normalized["fit"] = bool(tool_input.get("fit"))
        if "context_visibility" in tool_input:
            visibility = str(tool_input.get("context_visibility") or "keep").strip().lower()
            normalized["context_visibility"] = visibility if visibility in {"keep", "replace"} else "keep"
        style = tool_input.get("style")
        if isinstance(style, dict):
            cleaned_style = {}
            fill_color = str(style.get("fill_color") or "").strip()
            stroke_color = str(style.get("stroke_color") or "").strip()
            if fill_color:
                cleaned_style["fill_color"] = fill_color
            if stroke_color:
                cleaned_style["stroke_color"] = stroke_color
            if cleaned_style:
                normalized["style"] = cleaned_style

    return normalized


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
    time_field = str(result.get("time_field") or "year").strip() or "year"
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
            time_value = int(year) if str(year).isdigit() else year
            row = {"loc_id": loc_id, "name": feature_names.get(str(loc_id), loc_id), time_field: time_value}
            row.update(metrics or {})
            rows.append(_jsonable(row))
    return rows


def _feature_identity_from_props(props: dict, feature_id=None):
    for key in ("feature_id", "building_id", "BLDGIDENT", "OBJECTID", "GlobalID", "loc_id"):
        value = props.get(key)
        if value is not None and value != "":
            return str(value)
    if feature_id is not None and feature_id != "":
        return str(feature_id)
    return None


def _feature_lookup_from_result(result: dict) -> dict[str, dict]:
    lookup = {}
    for feature in (result.get("geojson") or {}).get("features") or []:
        props = dict(feature.get("properties") or {})
        identity = _feature_identity_from_props(props, feature.get("id"))
        if identity:
            lookup[identity] = _jsonable(feature)
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

    def match_condition(actual: Any, condition: dict) -> bool:
        if not isinstance(condition, dict):
            return actual == condition
        if "eq" in condition and actual != condition["eq"]:
            return False
        if "min" in condition and (actual is None or actual < condition["min"]):
            return False
        if "max" in condition and (actual is None or actual > condition["max"]):
            return False
        if "in" in condition and actual not in condition["in"]:
            return False
        if "starts_with" in condition:
            prefix = str(condition["starts_with"] or "")
            if not prefix or actual is None or not str(actual).startswith(prefix):
                return False
        if "starts_with_any" in condition:
            prefixes = [str(prefix or "") for prefix in (condition["starts_with_any"] or []) if str(prefix or "")]
            if prefixes:
                if actual is None or not any(str(actual).startswith(prefix) for prefix in prefixes):
                    return False
        if "contains_segment" in condition:
            segment = str(condition["contains_segment"] or "").strip()
            actual_text = str(actual or "").strip()
            if not segment or not actual_text:
                return False
            if f"-{segment}-" not in f"-{actual_text}-":
                return False
        return True

    def matches(row: dict) -> bool:
        for field, expected in filters.items():
            actual = row.get(field)
            if isinstance(expected, dict):
                if "hierarchy_any" in expected:
                    conditions = expected.get("hierarchy_any") or []
                    if conditions and not any(match_condition(actual, condition) for condition in conditions):
                        return False
                    continue
                if not match_condition(actual, expected):
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
                row[f"{metric}_sum"] = sum(values) if values else None
                row[f"{metric}_avg"] = sum(values) / len(values) if values else None
                row[f"{metric}_count"] = len(values)
                row[f"{metric}_min"] = min(values) if values else None
                row[f"{metric}_max"] = max(values) if values else None
            output.append(row)
        rows = output
    else:
        rows = [{field: row.get(field) for field in selected if field in row} for row in rows]

    for sort in reversed(tool_input.get("order_by") or []):
        field = sort.get("field")
        if group_by and field in metrics:
            field = f"{field}_avg"
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
                if "hierarchy_any" in expected:
                    hierarchy_parts = []
                    for condition in expected.get("hierarchy_any") or []:
                        if not isinstance(condition, dict):
                            continue
                        if "eq" in condition:
                            hierarchy_parts.append(f"{ident} = ?")
                            params.append(condition["eq"])
                        if "starts_with" in condition:
                            prefix = str(condition.get("starts_with") or "").strip()
                            if prefix:
                                hierarchy_parts.append(f"{ident} LIKE ?")
                                params.append(prefix + "%")
                        if "contains_segment" in condition:
                            segment = str(condition.get("contains_segment") or "").strip()
                            if segment:
                                hierarchy_parts.append(f"('-' || CAST({ident} AS VARCHAR) || '-') LIKE ?")
                                params.append("%-" + segment + "-%")
                    if hierarchy_parts:
                        where_parts.append("(" + " OR ".join(hierarchy_parts) + ")")
                    continue
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
                if "starts_with" in expected:
                    prefix = str(expected["starts_with"] or "").strip()
                    if prefix:
                        where_parts.append(f"{ident} LIKE ?")
                        params.append(prefix + "%")
                if "starts_with_any" in expected and expected["starts_with_any"]:
                    prefix_parts = []
                    for prefix in expected["starts_with_any"]:
                        text = str(prefix or "").strip()
                        if not text:
                            continue
                        prefix_parts.append(f"{ident} LIKE ?")
                        params.append(text + "%")
                    if prefix_parts:
                        where_parts.append("(" + " OR ".join(prefix_parts) + ")")
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
                select_parts.append(f"sum({ident}) AS {_quote_identifier(metric + '_sum')}")
                select_parts.append(f"avg({ident}) AS {_quote_identifier(metric + '_avg')}")
                select_parts.append(f"count({ident}) AS {_quote_identifier(metric + '_count')}")
                select_parts.append(f"min({ident}) AS {_quote_identifier(metric + '_min')}")
                select_parts.append(f"max({ident}) AS {_quote_identifier(metric + '_max')}")
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
            if group_by and field in metrics:
                field = f"{field}_avg"
            direction = "ASC" if sort.get("direction") == "asc" else "DESC"
            allowed = (
                set(df.columns)
                | {f"{m}_sum" for m in metrics}
                | {f"{m}_avg" for m in metrics}
                | {f"{m}_count" for m in metrics}
                | {f"{m}_min" for m in metrics}
                | {f"{m}_max" for m in metrics}
            )
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


def _loc_id_depth(loc_id: Any) -> int | None:
    text = str(loc_id or "").strip()
    if not text:
        return None
    return text.count("-")


def _rewrite_hierarchical_loc_id_filters(tool_input: dict) -> dict:
    if not isinstance(tool_input, dict):
        return {}

    filters = tool_input.get("filters")
    if not isinstance(filters, dict) or "loc_id" not in filters:
        return tool_input

    expected = filters.get("loc_id")
    hierarchy_conditions: list[dict[str, str]] = []

    def add_loc_id(value: Any):
        text = str(value or "").strip()
        if not text:
            return
        depth = _loc_id_depth(text)
        exact_condition = {"eq": text}
        if exact_condition not in hierarchy_conditions:
            hierarchy_conditions.append(exact_condition)
        if depth is not None and depth < 5:
            descendant_condition = {"starts_with": text + "-"}
            if descendant_condition not in hierarchy_conditions:
                hierarchy_conditions.append(descendant_condition)
        if "-" not in text:
            segment_condition = {"contains_segment": text}
            if segment_condition not in hierarchy_conditions:
                hierarchy_conditions.append(segment_condition)

    if isinstance(expected, dict):
        if "eq" in expected:
            add_loc_id(expected.get("eq"))
        elif "in" not in expected and "starts_with" not in expected and "starts_with_any" not in expected:
            return tool_input
        for value in expected.get("in") or []:
            add_loc_id(value)
        if "starts_with" in expected:
            prefix = str(expected.get("starts_with") or "").strip()
            if prefix:
                condition = {"starts_with": prefix}
                if condition not in hierarchy_conditions:
                    hierarchy_conditions.append(condition)
        for prefix in expected.get("starts_with_any") or []:
            text = str(prefix or "").strip()
            if text:
                condition = {"starts_with": text}
                if condition not in hierarchy_conditions:
                    hierarchy_conditions.append(condition)
    elif isinstance(expected, list):
        for value in expected:
            add_loc_id(value)
    else:
        add_loc_id(expected)

    if not hierarchy_conditions:
        return tool_input

    rewritten = {
        key: value
        for key, value in filters.items()
        if key != "loc_id"
    }
    rewritten["loc_id"] = {"hierarchy_any": hierarchy_conditions}
    patched = dict(tool_input)
    patched["filters"] = rewritten
    return patched


def _build_display_subset(result: dict, artifact: dict, tool_input: dict) -> dict:
    rows = _rows_from_result(result)
    explicit_limit = _normalize_optional_limit(tool_input.get("limit"), maximum=None)
    force_large_display = bool(tool_input.get("_force_large_display"))
    query_default_limit = None if explicit_limit is not None else (RESEARCH_DISPLAY_HARD_CAP + 1)
    query_result = _query_rows_duckdb(rows, tool_input, default_limit=query_default_limit, maximum_limit=None)
    row_count = int(query_result.get("row_count", 0) or 0)
    if explicit_limit is None and row_count > RESEARCH_DISPLAY_HARD_CAP:
        gate = block_gate(
            lane="human_web_research_display",
            reason=(
                f"This would draw about {row_count:,} features, which exceeds the safe display cap of "
                f"{RESEARCH_DISPLAY_HARD_CAP:,}. Narrow the request or ask for a smaller subset first."
            ),
            soft_cap=RESEARCH_DISPLAY_SOFT_CAP,
            hard_cap=RESEARCH_DISPLAY_HARD_CAP,
            estimated_count=row_count,
            measure="display_features",
            fallback_strategy="narrow_subset",
            suggested_narrowing=["top 100", "one tract", "one building type"],
        )
        return {
            "artifact_id": artifact.get("artifact_id"),
            "rows": [],
            "row_count": row_count,
            "truncated": True,
            "display_warning": {
                "level": "hard_cap",
                "row_count": row_count,
                "soft_cap": RESEARCH_DISPLAY_SOFT_CAP,
                "hard_cap": RESEARCH_DISPLAY_HARD_CAP,
                "message": gate.get("reason"),
                "gate": gate,
            },
        }
    if explicit_limit is None and row_count > RESEARCH_DISPLAY_SOFT_CAP and not force_large_display:
        gate = warn_gate(
            lane="human_web_research_display",
            reason=(
                f"This request matches about {row_count:,} features. Displaying that many at once may hurt map "
                f"performance. Narrow it first, or ask for a bounded subset like the top 100 or one tract."
            ),
            soft_cap=RESEARCH_DISPLAY_SOFT_CAP,
            hard_cap=RESEARCH_DISPLAY_HARD_CAP,
            estimated_count=row_count,
            override_allowed=True,
            measure="display_features",
            fallback_strategy="warn_then_override",
            suggested_narrowing=["top 100", "one tract", "one year", "one building type"],
        )
        return {
            "artifact_id": artifact.get("artifact_id"),
            "rows": [],
            "row_count": row_count,
            "truncated": True,
            "display_warning": {
                "level": "soft_cap",
                "row_count": row_count,
                "soft_cap": RESEARCH_DISPLAY_SOFT_CAP,
                "hard_cap": RESEARCH_DISPLAY_HARD_CAP,
                "message": gate.get("reason"),
                "gate": gate,
            },
        }
    matched_rows = query_result.get("rows") or []
    feature_lookup = _feature_lookup_from_result(result)

    loc_ids = []
    rows_by_identity: dict[str, dict] = {}
    for row in matched_rows:
        loc_id = row.get("loc_id")
        if loc_id is not None:
            loc_text = str(loc_id)
            if loc_text not in loc_ids:
                loc_ids.append(loc_text)
        identity = _feature_identity_from_props(row)
        if identity:
            rows_by_identity.setdefault(identity, row)

    features = []
    for identity, row in rows_by_identity.items():
        feature = feature_lookup.get(identity)
        if not feature:
            continue
        props = dict(feature.get("properties") or {})
        props.update(row or {})
        feature["properties"] = _jsonable(props)
        features.append(feature)

    # Metric artifacts often store only loc_id/name placeholders in their
    # lightweight geojson. Reuse the established selection geometry path to
    # attach real polygons for display/highlight.
    needs_geometry = not features or not any((feature.get("geometry") for feature in features))
    if needs_geometry and loc_ids:
        selection_geojson = get_selection_geometries(loc_ids)
        selection_features = (selection_geojson or {}).get("features") or []
        if selection_features:
            feature_by_loc_id = {}
            for feature in selection_features:
                props = dict(feature.get("properties") or {})
                loc_id = props.get("loc_id")
                if loc_id is not None:
                    feature_by_loc_id[str(loc_id)] = _jsonable(feature)
            rebuilt = []
            for row in matched_rows:
                loc_id = row.get("loc_id")
                if loc_id is None:
                    continue
                feature = feature_by_loc_id.get(str(loc_id))
                if not feature:
                    continue
                props = dict(feature.get("properties") or {})
                props.update(row or {})
                feature["properties"] = _jsonable(props)
                rebuilt.append(feature)
            if rebuilt:
                features = rebuilt

    display = {
        "action": "highlight_features",
        "artifact_id": artifact.get("artifact_id"),
        "source_id": artifact.get("source_id"),
        "geojson": {"type": "FeatureCollection", "features": features},
        "loc_ids": loc_ids,
        "fit": bool(tool_input.get("fit", True)),
        "context_visibility": str(tool_input.get("context_visibility") or "keep"),
    }
    if isinstance(tool_input.get("style"), dict):
        display["style"] = dict(tool_input["style"])
    logger.info(
        "Research display subset source=%s artifact=%s matched_rows=%s rendered_features=%s unique_loc_ids=%s truncated=%s requested_limit=%s",
        artifact.get("source_id"),
        artifact.get("artifact_id"),
        len(matched_rows),
        len(features),
        len(loc_ids),
        bool(query_result.get("truncated")),
        tool_input.get("limit"),
    )
    return {
        "artifact_id": artifact.get("artifact_id"),
        "rows": matched_rows,
        "row_count": row_count,
        "truncated": bool(query_result.get("truncated")),
        "display": display,
    }


def execute_research_tool(
    session_id: str,
    tool_name: str,
    tool_input: dict,
    *,
    force_large_display: bool = False,
) -> dict:
    try:
        tool_input = _normalize_tool_input(tool_name, tool_input)
        if tool_name == "list_artifacts":
            return {"artifacts": corpus_registry.list_artifacts(session_id)}

        artifact_id = tool_input.get("artifact_id")
        artifact = corpus_registry.get_artifact(session_id, artifact_id) if artifact_id else None
        if not artifact:
            return {"error": "artifact_not_found", "artifact_id": artifact_id}

        tool_input = _rewrite_hierarchical_loc_id_filters(tool_input)

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
            if force_large_display:
                tool_input = dict(tool_input or {})
                tool_input["_force_large_display"] = True
            return _build_display_subset(result, artifact, tool_input)

        return {"error": "unknown_tool", "tool_name": tool_name}
    except Exception as exc:
        logger.exception(
            "Research tool execution failed session=%s tool=%s artifact_id=%s",
            session_id,
            tool_name,
            (tool_input or {}).get("artifact_id") if isinstance(tool_input, dict) else None,
        )
        return {
            "error": "tool_execution_failed",
            "tool_name": tool_name,
            "detail": str(exc),
        }
