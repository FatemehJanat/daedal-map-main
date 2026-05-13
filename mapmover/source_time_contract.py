"""Shared source and metric time-range helpers.

Explore and Research discover sources differently, but once a specific source
and metric are chosen they should use the same metadata contract to derive
effective year bounds.
"""

from __future__ import annotations

from typing import Any


def _coerce_year_token(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value == int(value) else None
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 4 and text[:4].lstrip("-").isdigit():
        try:
            return int(text[:4])
        except ValueError:
            return None
    if text.lstrip("-").isdigit():
        try:
            return int(text)
        except ValueError:
            return None
    return None


def metadata_source_year_range(metadata: dict | None) -> tuple[int | None, int | None]:
    temporal = metadata.get("temporal_coverage") if isinstance(metadata, dict) else {}
    if not isinstance(temporal, dict):
        return None, None
    return _coerce_year_token(temporal.get("start")), _coerce_year_token(temporal.get("end"))


def metadata_metric_year_range(metadata: dict | None, metric_id: str | None) -> tuple[int | None, int | None]:
    if not isinstance(metadata, dict) or not metric_id:
        return None, None
    metrics = metadata.get("metrics")
    if not isinstance(metrics, dict):
        return None, None
    metric_info = metrics.get(str(metric_id))
    if not isinstance(metric_info, dict):
        return None, None
    years = metric_info.get("years")
    if not isinstance(years, list) or len(years) != 2:
        return None, None
    return _coerce_year_token(years[0]), _coerce_year_token(years[1])


def available_years_for_range(min_year: int | None, max_year: int | None, *, max_span: int = 200) -> list[int]:
    if min_year is None or max_year is None or max_year < min_year:
        return []
    if (max_year - min_year) > max_span:
        return []
    return list(range(min_year, max_year + 1))


def build_metric_year_ranges(
    metadata: dict | None,
    metric_ids: list[str] | None = None,
    *,
    fallback_min: int | None = None,
    fallback_max: int | None = None,
    fallback_available_years: list[int] | None = None,
) -> dict[str, dict]:
    if not isinstance(metadata, dict):
        return {}

    metrics = metadata.get("metrics")
    if not isinstance(metrics, dict):
        return {}

    ids = [str(metric_id).strip() for metric_id in (metric_ids or metrics.keys()) if str(metric_id).strip()]
    result: dict[str, dict] = {}
    for metric_id in ids:
        min_year, max_year = metadata_metric_year_range(metadata, metric_id)
        if min_year is None and max_year is None:
            if fallback_min is None and fallback_max is None and not fallback_available_years:
                continue
            result[metric_id] = {
                "min": fallback_min,
                "max": fallback_max,
                "available_years": list(fallback_available_years or []),
            }
            continue
        result[metric_id] = {
            "min": min_year,
            "max": max_year,
            "available_years": available_years_for_range(min_year, max_year),
        }
    return result

