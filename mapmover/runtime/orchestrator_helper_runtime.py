"""Shared helper runtime for orchestrator-adjacent utility logic."""

from __future__ import annotations


def requested_limit_from_order(order: dict | None) -> int | None:
    if not isinstance(order, dict):
        return None
    items = order.get("items") or []
    for item in items:
        if not isinstance(item, dict):
            continue
        sort_spec = item.get("sort") or {}
        raw_limit = sort_spec.get("limit")
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            continue
        if limit > 0:
            return limit
    return None


def best_source_metadata(hints: dict, load_source_metadata_func) -> dict | None:
    candidate_ids: list[str] = []
    detected = hints.get("detected_source") or {}
    detected_source_id = str(detected.get("source_id") or "").strip()
    if detected_source_id:
        candidate_ids.append(detected_source_id)

    source_bundle = ((hints.get("candidates") or {}).get("sources") or {})
    best_candidate = source_bundle.get("best") or {}
    best_source_id = str(best_candidate.get("source_id") or "").strip()
    if best_source_id and best_source_id not in candidate_ids:
        candidate_ids.append(best_source_id)

    for candidate in source_bundle.get("candidates") or []:
        source_id = str((candidate or {}).get("source_id") or "").strip()
        if source_id and source_id not in candidate_ids:
            candidate_ids.append(source_id)

    for source_id in candidate_ids:
        metadata = load_source_metadata_func(source_id) or {}
        if isinstance(metadata, dict) and metadata:
            metadata.setdefault("source_id", source_id)
            return metadata
    return None
