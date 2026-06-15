from __future__ import annotations

import json
import math
from typing import Any

import pandas as pd
from shapely.geometry import box, shape
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from ..foundation_helpers import load_reference_json
from .admin_hierarchy import infer_admin_level_from_loc_id

_WATER_BODY_CODES_CACHE: dict[str, str] | None = None


def load_water_body_codes() -> dict[str, str]:
    """Load shared X-prefix water body loc_id codes."""
    global _WATER_BODY_CODES_CACHE
    if _WATER_BODY_CODES_CACHE is not None:
        return _WATER_BODY_CODES_CACHE
    payload = load_reference_json("water_body_codes.json")
    codes = {}
    if isinstance(payload, dict):
        all_codes = payload.get("all_codes")
        if isinstance(all_codes, dict):
            for key, value in all_codes.items():
                code = str(key or "").strip().upper()
                label = str(value or "").strip()
                if code:
                    codes[code] = label or code
    _WATER_BODY_CODES_CACHE = codes
    return codes


def is_water_body_loc_id(loc_id: str | None) -> bool:
    value = str(loc_id or "").strip().upper()
    return bool(value) and value in load_water_body_codes()


def is_eez_loc_id(loc_id: str | None) -> bool:
    """Marine EEZ loc_ids (EEZ-<ISO3>, EEZ-<ISO3>-<mrgid>, EEZ-MRGID-<n>).

    EEZ zones are a marine overlay namespace: not part of the admin_0..admin_5
    spine, but a valid grid-aggregation target alongside the X* water bodies.
    They crosswalk back to canonical admin_0 sovereign/territory loc_ids via the
    EEZ geometry bank's crosswalk, so they still participate in the shared loc_id
    crosswalk model.
    """
    return str(loc_id or "").strip().upper().startswith("EEZ-")


def classify_grid_target_loc_id(loc_id: str | None) -> str | None:
    value = str(loc_id or "").strip()
    if not value:
        return None
    if is_water_body_loc_id(value):
        return "water_body"
    # EEZ must be checked before the admin inference: "EEZ-USA" would otherwise
    # be mis-parsed as an admin stack ("EEZ" + "USA").
    if is_eez_loc_id(value):
        return "marine_eez"
    admin_level = infer_admin_level_from_loc_id(value)
    if admin_level is not None:
        return f"admin_{admin_level}"
    return None


def _coerce_geometry(value: Any) -> BaseGeometry | None:
    if value is None:
        return None
    if isinstance(value, BaseGeometry):
        return value
    if isinstance(value, (list, tuple)) and len(value) == 4:
        west, south, east, north = value
        return box(float(west), float(south), float(east), float(north))
    if isinstance(value, dict):
        geom_type = str(value.get("type") or "").strip()
        if geom_type:
            return shape(value)
        bbox_value = value.get("bbox")
        if isinstance(bbox_value, (list, tuple)) and len(bbox_value) == 4:
            return _coerce_geometry(bbox_value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.startswith("{"):
            try:
                return _coerce_geometry(json.loads(text))
            except Exception:
                return None
    return None


def build_regular_grid_cell_rows(
    *,
    west: float,
    south: float,
    east: float,
    north: float,
    width: int,
    height: int,
    cell_id_prefix: str = "cell",
) -> list[dict[str, Any]]:
    """Build one bbox-backed row per cell for a regular lon/lat grid."""
    width = int(width)
    height = int(height)
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive integers")
    west = float(west)
    south = float(south)
    east = float(east)
    north = float(north)
    if east <= west or north <= south:
        raise ValueError("grid bounds must have east>west and north>south")

    cell_width = (east - west) / width
    cell_height = (north - south) / height
    rows: list[dict[str, Any]] = []
    for row_idx in range(height):
        cell_north = north - (row_idx * cell_height)
        cell_south = cell_north - cell_height
        for col_idx in range(width):
            cell_west = west + (col_idx * cell_width)
            cell_east = cell_west + cell_width
            rows.append(
                {
                    "cell_id": f"{cell_id_prefix}_{row_idx}_{col_idx}",
                    "row": row_idx,
                    "col": col_idx,
                    "bbox": [cell_west, cell_south, cell_east, cell_north],
                    "center_lon": cell_west + (cell_width / 2.0),
                    "center_lat": cell_south + (cell_height / 2.0),
                    "cell_width_deg": cell_width,
                    "cell_height_deg": cell_height,
                }
            )
    return rows


def build_centered_grid_cell_rows(
    center_rows: list[dict[str, Any]],
    *,
    lon_field: str = "lon",
    lat_field: str = "lat",
    cell_width_deg: float,
    cell_height_deg: float,
    cell_id_field: str = "cell_id",
) -> list[dict[str, Any]]:
    """Expand center-point rows into bbox-backed cell rows."""
    half_width = float(cell_width_deg) / 2.0
    half_height = float(cell_height_deg) / 2.0
    if half_width <= 0 or half_height <= 0:
        raise ValueError("cell_width_deg and cell_height_deg must be positive")

    rows: list[dict[str, Any]] = []
    for idx, row in enumerate(center_rows):
        lon = float(row[lon_field])
        lat = float(row[lat_field])
        cell_id = str(row.get(cell_id_field) or f"cell_{idx}").strip()
        out = dict(row)
        out[cell_id_field] = cell_id
        out["bbox"] = [lon - half_width, lat - half_height, lon + half_width, lat + half_height]
        out["center_lon"] = lon
        out["center_lat"] = lat
        out["cell_width_deg"] = float(cell_width_deg)
        out["cell_height_deg"] = float(cell_height_deg)
        rows.append(out)
    return rows


def _row_geometry(row: dict[str, Any]) -> BaseGeometry | None:
    geometry = _coerce_geometry(row.get("geometry"))
    if geometry is not None:
        return geometry
    bbox_value = row.get("bbox")
    geometry = _coerce_geometry(bbox_value)
    if geometry is not None:
        return geometry
    west = row.get("west", row.get("min_lon", row.get("bbox_min_lon")))
    south = row.get("south", row.get("min_lat", row.get("bbox_min_lat")))
    east = row.get("east", row.get("max_lon", row.get("bbox_max_lon")))
    north = row.get("north", row.get("max_lat", row.get("bbox_max_lat")))
    if None not in {west, south, east, north}:
        return box(float(west), float(south), float(east), float(north))
    return None


def _normalize_feature_rows(
    rows: list[dict[str, Any]],
    *,
    id_field: str,
    loc_id_field: str | None = None,
    validate_loc_ids: bool = False,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        feature_id = str(row.get(id_field) or "").strip()
        if not feature_id:
            continue
        geometry = _row_geometry(row)
        if geometry is None or geometry.is_empty:
            continue
        record = dict(row)
        record[id_field] = feature_id
        record["_geometry"] = geometry
        record["_geometry_area"] = float(geometry.area)
        if loc_id_field:
            loc_id = str(row.get(loc_id_field) or "").strip()
            if not loc_id:
                continue
            record[loc_id_field] = loc_id
            if validate_loc_ids and classify_grid_target_loc_id(loc_id) is None:
                raise ValueError(f"Unsupported target loc_id: {loc_id}")
        normalized.append(record)
    return normalized


def build_grid_target_overlaps(
    cell_rows: list[dict[str, Any]],
    target_rows: list[dict[str, Any]],
    *,
    cell_id_field: str = "cell_id",
    target_loc_id_field: str = "loc_id",
) -> pd.DataFrame:
    """
    Compute cell-to-target overlap weights from supplied geometries or bboxes.

    Cells and targets may use:
    - `geometry`: shapely geometry, GeoJSON dict, or GeoJSON string
    - `bbox`: [west, south, east, north]
    - explicit bounds fields such as `west/south/east/north`
    """
    cells = _normalize_feature_rows(cell_rows, id_field=cell_id_field)
    targets = _normalize_feature_rows(
        target_rows,
        id_field=target_loc_id_field,
        loc_id_field=target_loc_id_field,
        validate_loc_ids=True,
    )
    if not cells or not targets:
        return pd.DataFrame(
            columns=[
                cell_id_field,
                target_loc_id_field,
                "target_kind",
                "overlap_area",
                "cell_fraction",
                "target_fraction",
            ]
        )

    target_geometries = [row["_geometry"] for row in targets]
    tree = STRtree(target_geometries)
    records: list[dict[str, Any]] = []

    for cell in cells:
        cell_geom = cell["_geometry"]
        cell_area = float(cell["_geometry_area"] or 0.0)
        if cell_area <= 0.0:
            continue
        for match in tree.query(cell_geom):
            if isinstance(match, (int, pd.api.extensions.ExtensionArray)) or hasattr(match, "__index__"):
                target = targets[int(match)]
                candidate = target["_geometry"]
            else:
                candidate = match
                target = next((row for row in targets if row["_geometry"].equals(candidate)), None)
                if target is None:
                    continue
            if not cell_geom.intersects(candidate):
                continue
            intersection = cell_geom.intersection(candidate)
            if intersection.is_empty:
                continue
            overlap_area = float(intersection.area)
            if overlap_area <= 0.0:
                continue
            target_area = float(target["_geometry_area"] or 0.0)
            records.append(
                {
                    cell_id_field: cell[cell_id_field],
                    target_loc_id_field: target[target_loc_id_field],
                    "target_kind": classify_grid_target_loc_id(target[target_loc_id_field]),
                    "overlap_area": overlap_area,
                    "cell_fraction": overlap_area / cell_area if cell_area > 0 else None,
                    "target_fraction": overlap_area / target_area if target_area > 0 else None,
                }
            )

    return pd.DataFrame.from_records(records)


def normalize_overlap_weights(
    overlap_rows: pd.DataFrame | list[dict[str, Any]],
    *,
    group_by: str = "cell",
    cell_id_field: str = "cell_id",
    target_loc_id_field: str = "loc_id",
    fraction_field: str = "cell_fraction",
    normalized_field: str = "normalized_weight",
) -> pd.DataFrame:
    """
    Normalize overlap fractions within each cell or each target loc_id group.

    `group_by="cell"` is useful for `loc_id -> grid` projection.
    `group_by="target"` is useful for auditing how source cells contribute to one target.
    """
    overlaps_df = pd.DataFrame(overlap_rows).copy()
    if overlaps_df.empty:
        return overlaps_df

    if group_by == "cell":
        group_cols = [cell_id_field]
    elif group_by == "target":
        group_cols = [target_loc_id_field]
    else:
        raise ValueError("group_by must be 'cell' or 'target'")

    overlaps_df[fraction_field] = pd.to_numeric(overlaps_df[fraction_field], errors="coerce").fillna(0.0)
    denom = overlaps_df.groupby(group_cols, dropna=False)[fraction_field].transform("sum")
    overlaps_df[normalized_field] = overlaps_df[fraction_field] / denom.where(denom > 0, other=pd.NA)
    return overlaps_df


def _resolve_metric_aggregation(metric: str, aggregation_method: str, metric_aggregations: dict[str, str] | None) -> str:
    if metric_aggregations and metric in metric_aggregations:
        return str(metric_aggregations[metric]).strip().lower()
    return str(aggregation_method or "area_weighted_mean").strip().lower()


def _weighted_quantile(values: pd.Series, weights: pd.Series, quantile: float) -> float | None:
    if values.empty or weights.empty:
        return None
    q = float(quantile)
    if math.isnan(q):
        return None
    q = max(0.0, min(1.0, q))
    ordered = pd.DataFrame({"value": values.astype(float), "weight": weights.astype(float)})
    ordered = ordered.replace([float("inf"), float("-inf")], pd.NA).dropna()
    ordered = ordered.loc[ordered["weight"] > 0].sort_values("value").reset_index(drop=True)
    if ordered.empty:
        return None
    cumulative = ordered["weight"].cumsum()
    threshold = q * float(ordered["weight"].sum())
    match = ordered.loc[cumulative >= threshold, "value"]
    if match.empty:
        return float(ordered["value"].iloc[-1])
    return float(match.iloc[0])


def aggregate_grid_to_loc_ids(
    cell_rows: list[dict[str, Any]],
    overlap_rows: pd.DataFrame | list[dict[str, Any]],
    *,
    metric_columns: list[str],
    time_columns: list[str] | None = None,
    cell_id_field: str = "cell_id",
    target_loc_id_field: str = "loc_id",
    aggregation_method: str = "area_weighted_mean",
    metric_aggregations: dict[str, str] | None = None,
    metric_stats: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """
    Aggregate cell metrics to loc_ids using overlap-derived cell fractions.

    Mean-like metrics are weighted by `cell_fraction`.
    Count/sum metrics should be pre-expressed at the cell level and use the
    same weighting so partial cell overlap contributes proportionally.
    """
    time_columns = list(time_columns or [])
    cells_df = pd.DataFrame(cell_rows).copy()
    if cells_df.empty:
        columns = [target_loc_id_field, *time_columns, *metric_columns]
        return pd.DataFrame(columns=columns)
    overlaps_df = pd.DataFrame(overlap_rows).copy()
    if overlaps_df.empty:
        columns = [target_loc_id_field, *time_columns, *metric_columns]
        return pd.DataFrame(columns=columns)

    merged = overlaps_df.merge(cells_df, on=cell_id_field, how="inner")
    if merged.empty:
        columns = [target_loc_id_field, *time_columns, *metric_columns]
        return pd.DataFrame(columns=columns)

    group_cols = [target_loc_id_field, *time_columns]
    out_rows: list[dict[str, Any]] = []
    for group_key, group in merged.groupby(group_cols, dropna=False):
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        row = {col: group_key[idx] for idx, col in enumerate(group_cols)}
        weight_sum = pd.to_numeric(group["cell_fraction"], errors="coerce").fillna(0.0).sum()
        row["weight_sum"] = float(weight_sum)
        row["source_cell_count"] = int(group[cell_id_field].nunique())
        for metric in metric_columns:
            values = pd.to_numeric(group[metric], errors="coerce")
            weights = pd.to_numeric(group["cell_fraction"], errors="coerce").fillna(0.0)
            valid = values.notna() & (weights > 0)
            if not valid.any():
                row[metric] = None
                continue
            valid_values = values[valid]
            valid_weights = weights[valid]
            mode = _resolve_metric_aggregation(metric, aggregation_method, metric_aggregations)
            if mode in {"area_weighted_mean", "weighted_mean", "mean"}:
                weighted_total = float((valid_values * valid_weights).sum())
                denom = float(valid_weights.sum())
                row[metric] = weighted_total / denom if denom > 0 else None
            elif mode in {"weighted_sum", "sum"}:
                row[metric] = float((valid_values * valid_weights).sum())
            elif mode == "max":
                row[metric] = float(valid_values.max())
            elif mode == "min":
                row[metric] = float(valid_values.min())
            else:
                raise ValueError(f"Unsupported aggregation mode for {metric}: {mode}")
            requested_stats = [str(stat or "").strip().lower() for stat in (metric_stats or {}).get(metric, []) if str(stat or "").strip()]
            for stat_name in requested_stats:
                stat_col = f"{metric}__{stat_name}"
                if stat_name == "min":
                    row[stat_col] = float(valid_values.min())
                elif stat_name == "max":
                    row[stat_col] = float(valid_values.max())
                elif stat_name in {"p05", "p5", "q05", "q5"}:
                    row[stat_col] = _weighted_quantile(valid_values, valid_weights, 0.05)
                elif stat_name in {"p50", "median", "q50"}:
                    row[stat_col] = _weighted_quantile(valid_values, valid_weights, 0.5)
                elif stat_name in {"p95", "q95"}:
                    row[stat_col] = _weighted_quantile(valid_values, valid_weights, 0.95)
                else:
                    raise ValueError(f"Unsupported metric stat for {metric}: {stat_name}")
        out_rows.append(row)
    return pd.DataFrame(out_rows)


def project_loc_id_metrics_to_grid(
    cell_rows: list[dict[str, Any]],
    overlap_rows: pd.DataFrame | list[dict[str, Any]],
    loc_id_rows: list[dict[str, Any]],
    *,
    metric_columns: list[str],
    time_columns: list[str] | None = None,
    cell_id_field: str = "cell_id",
    target_loc_id_field: str = "loc_id",
    aggregation_method: str = "weighted_mean",
    metric_aggregations: dict[str, str] | None = None,
) -> pd.DataFrame:
    """
    Project loc_id metrics back onto grid cells through overlap weights.

    For each cell/time slice, target loc_id metrics are blended using
    normalized overlap weights.
    """
    time_columns = list(time_columns or [])
    cells_df = pd.DataFrame(cell_rows).copy()
    overlaps_df = pd.DataFrame(overlap_rows).copy()
    loc_df = pd.DataFrame(loc_id_rows).copy()
    if cells_df.empty or overlaps_df.empty or loc_df.empty:
        columns = [cell_id_field, *time_columns, *metric_columns]
        return pd.DataFrame(columns=columns)

    if time_columns:
        cell_time_cols = [col for col in time_columns if col in cells_df.columns]
        if cell_time_cols:
            overlaps_df = overlaps_df.merge(
                cells_df[[cell_id_field, *cell_time_cols]].drop_duplicates(),
                on=[cell_id_field],
                how="left",
            )

    overlaps_df = normalize_overlap_weights(
        overlaps_df,
        group_by="cell",
        cell_id_field=cell_id_field,
        target_loc_id_field=target_loc_id_field,
        fraction_field="cell_fraction",
        normalized_field="normalized_weight",
    )
    merged = overlaps_df.merge(loc_df, on=[target_loc_id_field, *time_columns], how="inner")
    if merged.empty:
        columns = [cell_id_field, *time_columns, *metric_columns]
        return pd.DataFrame(columns=columns)

    group_cols = [cell_id_field, *time_columns]
    out_rows: list[dict[str, Any]] = []
    for group_key, group in merged.groupby(group_cols, dropna=False):
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        row = {col: group_key[idx] for idx, col in enumerate(group_cols)}
        weights = pd.to_numeric(group["normalized_weight"], errors="coerce").fillna(0.0)
        row["source_loc_id_count"] = int(group[target_loc_id_field].nunique())
        for metric in metric_columns:
            values = pd.to_numeric(group[metric], errors="coerce")
            valid = values.notna() & (weights > 0)
            if not valid.any():
                row[metric] = None
                continue
            mode = _resolve_metric_aggregation(metric, aggregation_method, metric_aggregations)
            if mode in {"weighted_mean", "mean", "area_weighted_mean"}:
                weighted_total = float((values[valid] * weights[valid]).sum())
                valid_weight_sum = float(weights[valid].sum())
                row[metric] = weighted_total / valid_weight_sum if valid_weight_sum > 0 else None
            elif mode in {"weighted_sum", "sum"}:
                row[metric] = float((values[valid] * weights[valid]).sum())
            elif mode == "max":
                row[metric] = float(values[valid].max())
            elif mode == "min":
                row[metric] = float(values[valid].min())
            else:
                raise ValueError(f"Unsupported projection mode for {metric}: {mode}")
        out_rows.append(row)

    projected = pd.DataFrame(out_rows)
    if cell_id_field in cells_df.columns:
        projected = cells_df[[cell_id_field, *[col for col in time_columns if col in cells_df.columns]]].drop_duplicates().merge(
            projected,
            on=[cell_id_field, *[col for col in time_columns if col in projected.columns and col in cells_df.columns]],
            how="left",
        )
    return projected
