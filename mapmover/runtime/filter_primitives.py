"""Shared sort and filter helpers extracted from the executor."""

from __future__ import annotations

import pandas as pd


def normalize_sort_spec(sort_spec):
    """Coerce LLM-generated sort payloads into a consistent dict shape."""
    if not sort_spec:
        return None
    if isinstance(sort_spec, dict):
        by_value = sort_spec.get("by")
        if not by_value:
            return None
        normalized = dict(sort_spec)
        normalized["by"] = str(by_value)
        normalized["order"] = str(sort_spec.get("order", "desc")).lower()
        return normalized
    if isinstance(sort_spec, str):
        raw = str(sort_spec).strip().lower()
        alias_map = {
            "date_desc": {"by": "timestamp", "order": "desc"},
            "date_asc": {"by": "timestamp", "order": "asc"},
            "time_desc": {"by": "timestamp", "order": "desc"},
            "time_asc": {"by": "timestamp", "order": "asc"},
            "timestamp_desc": {"by": "timestamp", "order": "desc"},
            "timestamp_asc": {"by": "timestamp", "order": "asc"},
            "latest": {"by": "timestamp", "order": "desc"},
            "newest": {"by": "timestamp", "order": "desc"},
            "recent": {"by": "timestamp", "order": "desc"},
            "most_recent": {"by": "timestamp", "order": "desc"},
        }
        if raw in alias_map:
            return alias_map[raw]
        return {"by": sort_spec, "order": "desc"}
    if isinstance(sort_spec, list):
        for candidate in sort_spec:
            normalized = normalize_sort_spec(candidate)
            if normalized:
                return normalized
    return None


def apply_dataframe_filters(df: pd.DataFrame, filters: dict | None) -> pd.DataFrame:
    """Apply generic equality/range/presence filters to a DataFrame."""
    if df is None or df.empty or not isinstance(filters, dict) or not filters:
        return df

    filtered = df
    for field, value in filters.items():
        if field.endswith("_min"):
            col = field[:-4]
            if col in filtered.columns:
                filtered = filtered[filtered[col] >= value]
            continue
        if field.endswith("_max"):
            col = field[:-4]
            if col in filtered.columns:
                filtered = filtered[filtered[col] <= value]
            continue
        if field not in filtered.columns:
            continue

        if isinstance(value, dict):
            op = str(value.get("op") or "").strip().lower()
            min_value = value.get("min")
            max_value = value.get("max")
            if min_value is not None:
                filtered = filtered[filtered[field] >= min_value]
            if max_value is not None:
                filtered = filtered[filtered[field] <= max_value]
            if op in {"not_empty", "present", "exists"}:
                series = filtered[field]
                filtered = filtered[series.notna() & (series.astype(str).str.strip() != "")]
            elif op == "in":
                candidates = value.get("values") or []
                if candidates:
                    filtered = filtered[filtered[field].isin(candidates)]
            elif op == "eq" and "value" in value:
                filtered = filtered[filtered[field] == value.get("value")]
            elif op in {"!=", "ne"} and "value" in value:
                filtered = filtered[filtered[field] != value.get("value")]
            elif op in {">", "gt"} and "value" in value:
                filtered = filtered[filtered[field] > value.get("value")]
            elif op in {">=", "gte"} and "value" in value:
                filtered = filtered[filtered[field] >= value.get("value")]
            elif op in {"<", "lt"} and "value" in value:
                filtered = filtered[filtered[field] < value.get("value")]
            elif op in {"<=", "lte"} and "value" in value:
                filtered = filtered[filtered[field] <= value.get("value")]
            continue

        if isinstance(value, (list, tuple, set)):
            candidates = [candidate for candidate in value if candidate is not None]
            if candidates:
                filtered = filtered[filtered[field].isin(candidates)]
            continue

        if isinstance(value, bool):
            series = filtered[field]
            if value:
                filtered = filtered[series.notna() & (series.astype(str).str.strip() != "")]
            else:
                filtered = filtered[series.isna() | (series.astype(str).str.strip() == "")]
            continue

        filtered = filtered[filtered[field] == value]

    return filtered


def append_duckdb_filter_clause(
    where_clauses: list[str],
    params: list,
    available_cols: set[str],
    field: str,
    value,
    *,
    quote_ident_func,
) -> None:
    """Translate an order filter entry into DuckDB WHERE fragments."""
    if field.endswith("_min"):
        col = field[:-4]
        if col in available_cols and value is not None:
            where_clauses.append(f"{quote_ident_func(col)} >= ?")
            params.append(value)
        return

    if field.endswith("_max"):
        col = field[:-4]
        if col in available_cols and value is not None:
            where_clauses.append(f"{quote_ident_func(col)} <= ?")
            params.append(value)
        return

    if field not in available_cols:
        return

    if isinstance(value, dict):
        min_value = value.get("min")
        max_value = value.get("max")
        if min_value is not None:
            where_clauses.append(f"{quote_ident_func(field)} >= ?")
            params.append(min_value)
        if max_value is not None:
            where_clauses.append(f"{quote_ident_func(field)} <= ?")
            params.append(max_value)

        op = str(value.get("op") or "").strip().lower()
        if op in {"not_empty", "present", "exists"}:
            where_clauses.append(f"{quote_ident_func(field)} IS NOT NULL")
            where_clauses.append(f"trim(CAST({quote_ident_func(field)} AS VARCHAR)) <> ''")
            return
        if op == "in":
            candidates = [candidate for candidate in (value.get("values") or []) if candidate is not None]
            if candidates:
                placeholders = ", ".join("?" for _ in candidates)
                where_clauses.append(f"{quote_ident_func(field)} IN ({placeholders})")
                params.extend(candidates)
            return
        if "value" in value:
            op_map = {
                "eq": "=",
                "=": "=",
                "ne": "!=",
                "!=": "!=",
                "gt": ">",
                ">": ">",
                "gte": ">=",
                ">=": ">=",
                "lt": "<",
                "<": "<",
                "lte": "<=",
                "<=": "<=",
            }
            sql_op = op_map.get(op)
            if sql_op:
                where_clauses.append(f"{quote_ident_func(field)} {sql_op} ?")
                params.append(value.get("value"))
            return
        return

    if isinstance(value, (list, tuple, set)):
        candidates = [candidate for candidate in value if candidate is not None]
        if candidates:
            placeholders = ", ".join("?" for _ in candidates)
            where_clauses.append(f"{quote_ident_func(field)} IN ({placeholders})")
            params.extend(candidates)
        return

    if isinstance(value, bool):
        if value:
            where_clauses.append(f"{quote_ident_func(field)} IS NOT NULL")
            where_clauses.append(f"trim(CAST({quote_ident_func(field)} AS VARCHAR)) <> ''")
        else:
            where_clauses.append(
                f"({quote_ident_func(field)} IS NULL OR trim(CAST({quote_ident_func(field)} AS VARCHAR)) = '')"
            )
        return

    where_clauses.append(f"{quote_ident_func(field)} = ?")
    params.append(value)
