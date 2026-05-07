"""Research mode API router endpoints."""

from __future__ import annotations

import hashlib
import json
import os
import asyncio
import gzip
import math
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from shapely import wkt as shapely_wkt
from shapely.geometry import mapping as shapely_mapping

import msgpack
from anthropic import Anthropic
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from mapmover import logger
from mapmover.auth_context import build_session_cache_key, get_authenticated_user, get_authenticated_user_async
from mapmover.corpus_registry import corpus_registry
from mapmover.logging_analytics import hash_ip_for_analytics, log_app_error, log_conversation
from mapmover.llm_usage import LLMUsageRecorder, classify_caller
from mapmover.security import get_client_ip
from mapmover.data_loading import get_pack_metadata, get_source_path, load_catalog, load_source_metadata
from mapmover.api_query_runtime import execute_dataset_query, get_api_source_columns, get_api_source_spec
from mapmover.duckdb_helpers import is_cloud_mode, parquet_available, parquet_columns, path_to_uri, quote_ident, run_rows, select_columns_from_parquet
from mapmover.geometry_handlers import get_selection_geometries
from mapmover.progress_bus import ProgressBus, ProgressEvent
from mapmover.research_postprocessor import normalize_research_result
from mapmover.research_preprocessor import build_research_hint_context, preprocess_research_query
from mapmover.research_prompt import build_research_system_prompt
from mapmover.research_tools import RESEARCH_TOOL_DEFINITIONS, execute_research_tool
from mapmover.routes.disasters.helpers import msgpack_error, msgpack_response
from mapmover.session_cache import session_manager
from supabase_client import SupabaseClient


# User-facing strings for each research tool. The tool loop emits one
# of these as a ProgressEvent every time the LLM invokes the tool, so
# the streaming UI shows what work is actually happening instead of
# rotating filler messages.
RESEARCH_TOOL_PROGRESS_MESSAGES = {
    "list_artifacts": "Listing loaded research data...",
    "describe_artifact": "Inspecting an artifact...",
    "query_artifact_slice": "Reading values from your workspace...",
    "build_artifact_display_subset": "Preparing the map display...",
}


# Heartbeat copy used only when no real progress event has arrived
# within the heartbeat window. Cycles by idle count so users see
# motion even if a single LLM call is taking a long time.
_RESEARCH_HEARTBEAT_MESSAGES = [
    "Still reading the workspace...",
    "Cross-checking values...",
    "Working through the research context...",
    "Drafting your answer...",
]

_PROMPT_ARTIFACT_WINDOW = 64
_RESEARCH_MAX_TOOL_ITERATIONS = 8
_RESEARCH_MAX_TOKENS = 5000
_PROMPT_METRIC_LIMIT = 24
_PROMPT_FIELD_LIMIT = 12
_PROMPT_SCENE_PERIOD_LIMIT = 4
_PROMPT_SAVED_PACK_LIMIT = 4
_TOOL_ROWS_PREVIEW_LIMIT = 10
_PRIVATE_BROWSER_ARTIFACT_OUTPUT_ROOT = Path(__file__).resolve().parents[3] / "county-map-private" / "build" / "browser_artifacts" / "output"


def _research_heartbeat(idle_count: int) -> ProgressEvent:
    message = _RESEARCH_HEARTBEAT_MESSAGES[idle_count % len(_RESEARCH_HEARTBEAT_MESSAGES)]
    return ProgressEvent(stage="thinking", message=message, extra={"heartbeat": True})


router = APIRouter()


def _manifest_prompt_window_warning(manifest: dict | None) -> str | None:
    artifact_count = int((manifest or {}).get("artifact_count") or 0)
    if artifact_count <= _PROMPT_ARTIFACT_WINDOW:
        return None
    return (
        f"This corpus has {artifact_count} loaded artifacts, which is larger than the current "
        f"prompt-friendly window of {_PROMPT_ARTIFACT_WINDOW}. Research can still work, "
        "but broad questions may be less reliable unless you narrow the corpus or ask about a smaller subset."
    )


def _infer_loc_id_details(loc_id) -> tuple[int | None, str | None]:
    text = str(loc_id or "").strip()
    if not text:
        return None, None
    segment_count = text.count("-")
    kind_map = {
        0: "country",
        1: "state_or_admin_1",
        2: "county",
        3: "tract",
        4: "blockgroup",
        5: "block",
    }
    return segment_count, kind_map.get(segment_count)


def _sample_prompt_metrics(metrics: list | None, limit: int) -> list[str]:
    values = [str(metric).strip() for metric in (metrics or []) if str(metric).strip()]
    if len(values) <= limit:
        return values

    grouped: dict[str, list[str]] = {}
    ordered_prefixes: list[str] = []
    for metric in values:
        prefix = metric.split("_", 1)[0] if "_" in metric else "__root__"
        if prefix not in grouped:
            grouped[prefix] = []
            ordered_prefixes.append(prefix)
        grouped[prefix].append(metric)

    preview: list[str] = []
    seen = set()
    round_index = 0
    while len(preview) < limit:
        added = False
        for prefix in ordered_prefixes:
            items = grouped.get(prefix) or []
            if round_index < len(items):
                metric = items[round_index]
                if metric not in seen:
                    preview.append(metric)
                    seen.add(metric)
                    added = True
                    if len(preview) >= limit:
                        break
        if not added:
            break
        round_index += 1
    return preview


def _build_saved_corpus_summary(corpus_row: dict | None) -> dict | None:
    if not isinstance(corpus_row, dict):
        return None

    items = corpus_row.get("research_corpus_items") or []
    packs = []
    source_ids = []
    pack_ids = []
    resolved_source_ids: list[str] = []
    resolved_seen = set()
    pack_row_count_total = 0
    pack_file_size_mb_total = 0.0
    source_lookup = _catalog_source_lookup()
    resolved_sources = []
    resolved_transfer_bytes_total = 0
    resolved_stored_bytes_total = 0
    resolved_expanded_bytes_total = 0

    for item in items:
        item_type = str(item.get("item_type") or "").strip().lower()
        item_id = str(item.get("item_id") or "").strip()
        if not item_id:
            continue
        if item_type == "pack":
            pack_meta = get_pack_metadata(item_id)
            if pack_meta:
                packs.append(pack_meta)
                pack_ids.append(item_id)
                for pack_source_id in pack_meta.get("source_ids") or []:
                    pack_source_text = str(pack_source_id or "").strip()
                    if pack_source_text and pack_source_text not in resolved_seen:
                        resolved_seen.add(pack_source_text)
                        resolved_source_ids.append(pack_source_text)
                        source_meta = source_lookup.get(pack_source_text)
                        if isinstance(source_meta, dict):
                            resolved_sources.append(deepcopy(source_meta))
                            browser_artifact = _normalize_browser_artifact(source_meta.get("browser_artifact"))
                            if browser_artifact:
                                resolved_transfer_bytes_total += int(browser_artifact.get("transfer_bytes") or 0)
                                resolved_stored_bytes_total += int(browser_artifact.get("stored_bytes") or 0)
                                resolved_expanded_bytes_total += int(browser_artifact.get("expanded_bytes") or 0)
                pack_row_count_total += int(pack_meta.get("row_count_total") or 0)
                pack_file_size_mb_total += float(pack_meta.get("file_size_mb_total") or 0.0)
            else:
                pack_ids.append(item_id)
        elif item_type == "source":
            source_ids.append(item_id)
            if item_id not in resolved_seen:
                resolved_seen.add(item_id)
                resolved_source_ids.append(item_id)
                source_meta = source_lookup.get(item_id)
                if isinstance(source_meta, dict):
                    resolved_sources.append(deepcopy(source_meta))
                    browser_artifact = _normalize_browser_artifact(source_meta.get("browser_artifact"))
                    if browser_artifact:
                        resolved_transfer_bytes_total += int(browser_artifact.get("transfer_bytes") or 0)
                        resolved_stored_bytes_total += int(browser_artifact.get("stored_bytes") or 0)
                        resolved_expanded_bytes_total += int(browser_artifact.get("expanded_bytes") or 0)

    return {
        "id": corpus_row.get("id"),
        "name": corpus_row.get("name") or "Untitled corpus",
        "description": corpus_row.get("description") or "",
        "updated_at": corpus_row.get("updated_at"),
        "pack_ids": pack_ids,
        "source_ids": source_ids,
        "pack_count": len(pack_ids),
        "source_count": len(source_ids),
        "resolved_source_count": len(resolved_source_ids),
        "estimated_row_count_total": pack_row_count_total,
        "estimated_file_size_mb_total": round(pack_file_size_mb_total, 2),
        "packs": packs,
        "resolved_source_ids": resolved_source_ids,
        "sources": resolved_sources,
        "browser_artifact_totals": {
            "transfer_bytes": resolved_transfer_bytes_total,
            "stored_bytes": resolved_stored_bytes_total,
            "expanded_bytes": resolved_expanded_bytes_total,
            "transfer_mb": round(resolved_transfer_bytes_total / (1024 * 1024), 2),
            "stored_mb": round(resolved_stored_bytes_total / (1024 * 1024), 2),
            "expanded_mb": round(resolved_expanded_bytes_total / (1024 * 1024), 2),
        },
    }


def _load_saved_corpus_for_user(user_id: str, corpus_id: str) -> dict | None:
    client = SupabaseClient().client
    result = (
        client
        .table("research_corpora")
        .select("id, name, description, updated_at, research_corpus_items(item_type, item_id, position)")
        .eq("user_id", user_id)
        .eq("id", corpus_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return _build_saved_corpus_summary(rows[0]) if rows else None


def _saved_corpus_request_key(corpus_id: str, source_id: str) -> str:
    seed = f"saved-corpus:{corpus_id}:{source_id}"
    return f"saved_{hashlib.md5(seed.encode('utf-8')).hexdigest()[:16]}"


def _expected_saved_corpus_source_ids(saved_corpus: dict | None) -> list[str]:
    if not isinstance(saved_corpus, dict):
        return []
    resolved = []
    seen = set()
    for pack in saved_corpus.get("packs") or []:
        for source_id in pack.get("source_ids") or []:
            text = str(source_id or "").strip()
            if text and text not in seen:
                seen.add(text)
                resolved.append(text)
    for source_id in saved_corpus.get("source_ids") or []:
        text = str(source_id or "").strip()
        if text and text not in seen:
            seen.add(text)
            resolved.append(text)
    return resolved


def _artifact_source_ids(artifacts: list[dict] | None) -> list[str]:
    resolved = []
    seen = set()
    for artifact in artifacts or []:
        text = str((artifact or {}).get("source_id") or "").strip()
        if text and text not in seen:
            seen.add(text)
            resolved.append(text)
    return resolved


def _artifacts_match_saved_corpus(artifacts: list[dict] | None, saved_corpus: dict | None) -> bool:
    expected = set(_expected_saved_corpus_source_ids(saved_corpus))
    if not expected:
        return True
    actual = set(_artifact_source_ids(artifacts))
    return actual == expected


def _annotate_manifest_saved_corpus_state(manifest: dict) -> dict:
    if not isinstance(manifest, dict):
        return manifest
    saved_corpus = manifest.get("saved_corpus")
    artifacts = manifest.get("artifacts") or []
    expected_source_ids = _expected_saved_corpus_source_ids(saved_corpus)
    if not expected_source_ids:
        manifest["stale_artifacts"] = False
        return manifest
    actual_source_ids = _artifact_source_ids(artifacts)
    manifest["expected_source_ids"] = expected_source_ids
    manifest["actual_source_ids"] = actual_source_ids
    manifest["stale_artifacts"] = set(actual_source_ids) != set(expected_source_ids)
    return manifest


def _source_summary_text(source_id: str, metadata: dict, row_count: int) -> str:
    source_name = str(metadata.get("source_name") or source_id).strip() or source_id
    coverage = str(metadata.get("coverage_description") or "").strip()
    if coverage and coverage.lower() != "unknown coverage":
        return f"{source_name}: {coverage} ({row_count:,} rows loaded for Research)."
    return f"{source_name}: {row_count:,} rows loaded for Research."


def _rows_to_temporal_result(
    rows: list[dict],
    source_id: str,
    metadata: dict,
    spec,
    dimension_columns: list[str] | None = None,
) -> dict:
    features_by_loc: dict[str, dict] = {}
    year_data: dict[str, dict] = {}
    metric_ids = list((metadata.get("metrics") or {}).keys())
    dimension_columns = [str(column).strip() for column in (dimension_columns or []) if str(column).strip()]
    if not metric_ids:
        metric_ids = [metric_id for metric_id in spec.metrics.keys() if metric_id != "event_count"]

    for row in rows:
        loc_id = row.get(spec.location_field)
        if loc_id is None:
            continue
        loc_id = str(loc_id)
        admin_level_num, geography_kind = _infer_loc_id_details(loc_id)
        name = row.get("name") or loc_id
        features_by_loc.setdefault(
            loc_id,
            {
                "type": "Feature",
                "properties": {
                    "loc_id": loc_id,
                    "name": name,
                    "admin_level_num": admin_level_num,
                    "geography_kind": geography_kind,
                },
            },
        )
        feature_props = features_by_loc[loc_id]["properties"]
        for column_name in dimension_columns:
            if column_name in row and column_name not in {spec.location_field, spec.time_field, "name"}:
                feature_props.setdefault(column_name, row.get(column_name))
        time_value = row.get(spec.time_field) if spec.time_field else None
        if time_value is None:
            continue
        time_key = str(time_value)
        metric_values = {
            metric_id: row.get(metric_id)
            for metric_id in metric_ids
            if metric_id in row
        }
        if admin_level_num is not None:
            metric_values["admin_level_num"] = admin_level_num
        if geography_kind:
            metric_values["geography_kind"] = geography_kind
        for column_name in dimension_columns:
            if column_name in row and column_name not in {spec.location_field, spec.time_field, "name"}:
                metric_values[column_name] = row.get(column_name)
        if not metric_values:
            continue
        year_data.setdefault(time_key, {})[loc_id] = metric_values

    return {
        "type": "data",
        "data_type": "metrics",
        "source_id": source_id,
        "time_field": spec.time_field or "year",
        "geojson": {
            "type": "FeatureCollection",
            "features": list(features_by_loc.values()),
        },
        "year_data": year_data,
        "multi_year": True,
        "year_range": sorted(year_data.keys()),
        "available_metrics": metric_ids,
        "metric_year_ranges": {},
        "summary": _source_summary_text(source_id, metadata, len(rows)),
        "count": len(rows),
        "sources": [{"id": source_id, "name": str(metadata.get("source_name") or source_id)}],
    }


def _rows_to_static_result(rows: list[dict], source_id: str, metadata: dict, spec) -> dict:
    features = []
    metric_ids = list((metadata.get("metrics") or {}).keys())
    if not metric_ids:
        metric_ids = [metric_id for metric_id in spec.metrics.keys() if metric_id != "event_count"]
    for row in rows:
        props = dict(row)
        loc_id = props.get(spec.location_field)
        if loc_id is not None:
            props["loc_id"] = str(loc_id)
            admin_level_num, geography_kind = _infer_loc_id_details(loc_id)
            props.setdefault("admin_level_num", admin_level_num)
            props.setdefault("geography_kind", geography_kind)
        if "name" not in props and props.get("loc_id"):
            props["name"] = props["loc_id"]
        features.append({"type": "Feature", "properties": props})

    return {
        "type": "data",
        "data_type": "metrics",
        "source_id": source_id,
        "geojson": {
            "type": "FeatureCollection",
            "features": features,
        },
        "available_metrics": metric_ids,
        "summary": _source_summary_text(source_id, metadata, len(rows)),
        "count": len(rows),
        "sources": [{"id": source_id, "name": str(metadata.get("source_name") or source_id)}],
    }


def _is_runtime_research_source(metadata: dict) -> bool:
    if not isinstance(metadata, dict):
        return False
    release_state = str(metadata.get("release_state") or "").strip().lower()
    return release_state == "published" or bool(metadata.get("pack_id"))


def _find_primary_parquet(source_id: str, metadata: dict):
    source_dir = get_source_path(source_id)
    if source_dir is None:
        return None

    def candidate_accessible(candidate_path) -> bool:
        if not is_cloud_mode():
            return parquet_available(candidate_path)
        try:
            parquet_columns(candidate_path)
            return True
        except Exception:
            return False

    candidate_names: list[str] = []
    for rel_path in metadata.get("primary_files") or []:
        candidate = source_dir / str(rel_path)
        if candidate.suffix.lower() == ".parquet" and candidate_accessible(candidate):
            return candidate
        if candidate.suffix.lower() == ".parquet":
            candidate_names.append(str(rel_path))

    files_section = metadata.get("files") if isinstance(metadata.get("files"), dict) else {}
    for file_info in files_section.values():
        if not isinstance(file_info, dict):
            continue
        file_name = str(file_info.get("name") or file_info.get("filename") or "").strip()
        if file_name.lower().endswith(".parquet"):
            candidate_names.append(file_name)

    seen_candidates = set()
    for candidate_name in candidate_names:
        normalized_name = str(candidate_name or "").strip()
        if not normalized_name or normalized_name in seen_candidates:
            continue
        seen_candidates.add(normalized_name)
        candidate = source_dir / normalized_name
        if candidate_accessible(candidate):
            return candidate

    fallback_names: list[str] = []
    spec = get_api_source_spec(source_id)
    if spec and str(spec.parquet_name or "").strip():
        fallback_names.append(str(spec.parquet_name).strip())

    normalized_kind = str(metadata.get("data_type") or "").strip().lower()
    if normalized_kind == "events" or metadata.get("event_type"):
        fallback_names.extend([
            "events.parquet",
            "storms.parquet",
            "positions.parquet",
            "fires.parquet",
        ])

    fallback_names.extend((
        "all_countries.parquet",
        "all_regions.parquet",
        "data.parquet",
        "events.parquet",
        "full_range.parquet",
        "USA.parquet",
    ))

    seen_fallbacks = set()
    for fallback_name in fallback_names:
        if fallback_name in seen_fallbacks:
            continue
        seen_fallbacks.add(fallback_name)
        if fallback_name in candidate_names:
            continue
        candidate = source_dir / fallback_name
        if candidate_accessible(candidate):
            return candidate
    return None


def _load_runtime_rows(parquet_path, columns: list[str]) -> list[dict]:
    df = select_columns_from_parquet(parquet_path, columns)
    if df.empty:
        return []
    return df.to_dict(orient="records")


def _load_runtime_rows_raw(parquet_path, columns: list[str]) -> list[dict]:
    available_columns = parquet_columns(parquet_path)
    selected = [column for column in columns if column in available_columns]
    if not selected:
        return []
    select_exprs = []
    for column in selected:
        if column == "geometry":
            select_exprs.append(f"CAST({quote_ident(column)} AS VARCHAR) AS {quote_ident(column)}")
        else:
            select_exprs.append(quote_ident(column))
    sql = "SELECT " + ", ".join(select_exprs) + " FROM read_parquet(?)"
    rows = run_rows(sql, [path_to_uri(parquet_path)])
    return [dict(zip(selected, row)) for row in rows]


def _hydrate_runtime_metrics_source(source_id: str, metadata: dict) -> dict:
    parquet_path = _find_primary_parquet(source_id, metadata)
    if parquet_path is None:
        return {"source_id": source_id, "status": "skipped", "reason": "missing_parquet"}

    try:
        available_columns = parquet_columns(parquet_path)
    except Exception as exc:
        return {"source_id": source_id, "status": "skipped", "reason": "source_unavailable", "detail": str(exc)}
    if "loc_id" not in available_columns:
        return {"source_id": source_id, "status": "skipped", "reason": "missing_location_field"}

    time_field = str(((metadata.get("temporal_coverage") or {}).get("field")) or "").strip() or None
    if time_field and time_field not in available_columns:
        time_field = None

    name_field = "name" if "name" in available_columns else ("NAME" if "NAME" in available_columns else None)
    metric_ids = [metric_id for metric_id in (metadata.get("metrics") or {}).keys() if metric_id in available_columns]

    select_columns = ["loc_id"]
    if time_field:
        select_columns.append(time_field)
    if name_field:
        select_columns.append(name_field)
    for metric_id in metric_ids:
        if metric_id not in select_columns:
            select_columns.append(metric_id)

    try:
        rows = _load_runtime_rows(parquet_path, select_columns)
    except Exception as exc:
        return {"source_id": source_id, "status": "skipped", "reason": "source_unavailable", "detail": str(exc)}
    if not rows:
        return {"source_id": source_id, "status": "skipped", "reason": "no_rows"}

    normalized_rows = []
    for row in rows:
        normalized = dict(row)
        if name_field and name_field != "name" and name_field in normalized:
            normalized["name"] = normalized.get(name_field)
        normalized_rows.append(normalized)

    pseudo_spec = SimpleNamespace(
        location_field="loc_id",
        time_field=time_field,
        metrics={metric_id: None for metric_id in metric_ids},
    )
    result = _rows_to_temporal_result(normalized_rows, source_id, metadata, pseudo_spec) if time_field else _rows_to_static_result(normalized_rows, source_id, metadata, pseudo_spec)
    return {"source_id": source_id, "status": "loaded", "row_count": len(normalized_rows), "result": result}


def _hydrate_runtime_geometry_source(source_id: str, metadata: dict) -> dict:
    parquet_path = _find_primary_parquet(source_id, metadata)
    if parquet_path is None:
        return {"source_id": source_id, "status": "skipped", "reason": "missing_parquet"}

    try:
        available_columns = parquet_columns(parquet_path)
    except Exception as exc:
        return {"source_id": source_id, "status": "skipped", "reason": "source_unavailable", "detail": str(exc)}
    if "geometry" not in available_columns:
        return {"source_id": source_id, "status": "skipped", "reason": "missing_geometry"}

    preferred_columns = [
        "loc_id", "parent_id", "name", "NAME", "feature_id", "building_id", "BLDGIDENT",
        "TYPE", "BLDG_CM_TYPE", "BLDG_CM_LABEL", "BLDG_HEIGHT", "SOURCE", "geometry",
    ]
    select_columns = [column for column in preferred_columns if column in available_columns]
    try:
        rows = _load_runtime_rows_raw(parquet_path, select_columns)
    except Exception:
        return _hydrate_runtime_metrics_source(source_id, metadata)
    if not rows:
        return {"source_id": source_id, "status": "skipped", "reason": "no_rows"}

    features = []
    for row in rows:
        geometry_value = row.get("geometry")
        if not geometry_value:
            continue
        try:
            if isinstance(geometry_value, str):
                stripped = geometry_value.strip()
                if stripped.startswith("{"):
                    geometry = json.loads(stripped)
                else:
                    geometry = shapely_mapping(shapely_wkt.loads(stripped))
            else:
                geometry = geometry_value
        except Exception:
            continue
        props = {k: v for k, v in row.items() if k != "geometry"}
        if "name" not in props and props.get("NAME"):
            props["name"] = props.get("NAME")
        if "name" not in props:
            props["name"] = props.get("feature_id") or props.get("building_id") or props.get("BLDGIDENT") or props.get("loc_id")
        features.append({"type": "Feature", "geometry": geometry, "properties": props})

    if not features:
        return {"source_id": source_id, "status": "skipped", "reason": "no_features"}

    result = {
        "type": "data",
        "data_type": "geometry",
        "source_id": source_id,
        "overlay_type": metadata.get("overlay_type"),
        "geojson": {"type": "FeatureCollection", "features": features},
        "available_metrics": [],
        "summary": _source_summary_text(source_id, metadata, len(features)),
        "count": len(features),
        "sources": [{"id": source_id, "name": str(metadata.get("source_name") or source_id)}],
    }
    return {"source_id": source_id, "status": "loaded", "row_count": len(features), "result": result}


def _hydrate_runtime_source(source_id: str, metadata: dict) -> dict:
    data_type = metadata.get("data_type")
    kinds = data_type if isinstance(data_type, list) else [data_type]
    normalized_kinds = {str(kind or "").strip().lower() for kind in kinds if kind}
    if "geometry" in normalized_kinds:
        return _hydrate_runtime_geometry_source(source_id, metadata)
    return _hydrate_runtime_metrics_source(source_id, metadata)


def _hydrate_saved_source_into_research(*, session_id: str, corpus_id: str, source_id: str) -> dict:
    metadata = load_source_metadata(source_id) or {}
    if not _is_runtime_research_source(metadata):
        return {"source_id": source_id, "status": "skipped", "reason": "source_not_runtime_ready"}

    runtime_outcome = _hydrate_runtime_source(source_id, metadata)
    result = runtime_outcome.get("result")
    if runtime_outcome.get("status") == "loaded" and result:
        request_key = _saved_corpus_request_key(corpus_id, source_id)
        session_manager.get_or_create(session_id).store_result(request_key, result)
        order = {
            "items": [{"source_id": source_id, "region": "global", "metric": None}],
            "summary": result.get("summary") or f"Loaded {source_id} into Research.",
        }
        corpus_registry.register_order_result(
            session_id=session_id,
            request_key=request_key,
            order=order,
            response=result,
        )
        return {
            "source_id": source_id,
            "status": "loaded",
            "row_count": int(runtime_outcome.get("row_count") or 0),
        }

    spec = get_api_source_spec(source_id)
    if spec is None:
        return runtime_outcome

    try:
        available_columns = get_api_source_columns(spec)
    except Exception as exc:
        logger.warning("Research hydration skipped source %s while reading columns: %s", source_id, exc)
        return {
            "source_id": source_id,
            "status": "skipped",
            "reason": "source_unavailable",
            "detail": str(exc),
        }
    if spec.location_field not in available_columns:
        return {"source_id": source_id, "status": "skipped", "reason": "missing_location_field"}

    select_columns = [spec.location_field]
    if spec.time_field and spec.time_field in available_columns:
        select_columns.append(spec.time_field)
    if "name" in available_columns:
        select_columns.append("name")
    dimension_columns: list[str] = []
    metadata_dimensions = metadata.get("dimensions") if isinstance(metadata.get("dimensions"), dict) else {}
    for dim_key, dim_spec in metadata_dimensions.items():
        if not isinstance(dim_spec, dict):
            continue
        column_name = str(dim_spec.get("column") or dim_key).strip()
        if not column_name or column_name not in available_columns:
            continue
        if column_name not in dimension_columns:
            dimension_columns.append(column_name)
        if column_name not in select_columns:
            select_columns.append(column_name)

    metric_ids = []
    for metric_id, metric_spec in spec.metrics.items():
        column_name = metric_spec.column
        if metric_id == "event_count":
            continue
        if column_name in available_columns and metric_id not in metric_ids:
            metric_ids.append(metric_id)
            if column_name not in select_columns:
                select_columns.append(column_name)

    try:
        rows = execute_dataset_query(
            spec,
            select_columns=select_columns,
            limit=None,
        )
    except Exception as exc:
        logger.warning("Research hydration skipped source %s while loading rows: %s", source_id, exc)
        return {
            "source_id": source_id,
            "status": "skipped",
            "reason": "source_unavailable",
            "detail": str(exc),
        }
    if not rows:
        return {"source_id": source_id, "status": "skipped", "reason": "no_rows"}

    if spec.time_field:
        result = _rows_to_temporal_result(rows, source_id, metadata, spec, dimension_columns=dimension_columns)
    else:
        result = _rows_to_static_result(rows, source_id, metadata, spec)

    request_key = _saved_corpus_request_key(corpus_id, source_id)
    session_manager.get_or_create(session_id).store_result(request_key, result)

    order = {
        "items": [
            {
                "source_id": source_id,
                "region": "global",
                "metric": metric_ids[0] if metric_ids else None,
            }
        ],
        "summary": result.get("summary") or f"Loaded {source_id} into Research.",
    }
    corpus_registry.register_order_result(
        session_id=session_id,
        request_key=request_key,
        order=order,
        response=result,
    )
    return {
        "source_id": source_id,
        "status": "loaded",
        "row_count": len(rows),
    }


def _hydrate_saved_corpus(session_id: str, saved_corpus: dict) -> dict:
    corpus_registry.clear_artifacts(session_id)
    source_ids = _expected_saved_corpus_source_ids(saved_corpus)

    hydration = {
        "loaded_sources": [],
        "skipped_sources": [],
    }
    for source_id in source_ids:
        outcome = _hydrate_saved_source_into_research(
            session_id=session_id,
            corpus_id=str(saved_corpus.get("id") or "saved"),
            source_id=source_id,
        )
        if outcome.get("status") == "loaded":
            logger.info("Research saved corpus hydrated source %s rows=%s", source_id, outcome.get("row_count"))
            hydration["loaded_sources"].append(outcome)
        else:
            logger.info(
                "Research saved corpus skipped source %s reason=%s detail=%s",
                source_id,
                outcome.get("reason"),
                outcome.get("detail"),
            )
            hydration["skipped_sources"].append(outcome)
    return hydration


def _json_safe_value(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _json_safe_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, set):
        return [_json_safe_value(item) for item in value]
    return value


def _normalize_browser_artifact(raw_value: dict | None) -> dict | None:
    if not isinstance(raw_value, dict):
        return None

    def _coerce_int(value) -> int:
        try:
            return int(round(float(value or 0)))
        except (TypeError, ValueError):
            return 0

    storage_key = str(raw_value.get("storage_key") or "").strip()
    sha256 = str(raw_value.get("sha256") or "").strip()
    artifact_version = str(raw_value.get("artifact_version") or "").strip()
    format_name = str(raw_value.get("format") or "").strip()
    transfer_bytes = _coerce_int(raw_value.get("transfer_bytes"))
    stored_bytes = _coerce_int(raw_value.get("stored_bytes") or transfer_bytes)
    expanded_bytes = _coerce_int(raw_value.get("expanded_bytes"))
    if not storage_key:
        return None
    return {
        "contract_version": int(raw_value.get("contract_version") or 1),
        "artifact_version": artifact_version,
        "format": format_name,
        "storage_key": storage_key,
        "sha256": sha256,
        "transfer_bytes": transfer_bytes,
        "stored_bytes": stored_bytes,
        "expanded_bytes": expanded_bytes,
        "transfer_mb": round(transfer_bytes / (1024 * 1024), 2) if transfer_bytes > 0 else 0.0,
        "stored_mb": round(stored_bytes / (1024 * 1024), 2) if stored_bytes > 0 else 0.0,
        "expanded_mb": round(expanded_bytes / (1024 * 1024), 2) if expanded_bytes > 0 else 0.0,
        "generated_at": str(raw_value.get("generated_at") or "").strip(),
    }


def _catalog_source_lookup() -> dict[str, dict]:
    catalog = load_catalog() or {}
    lookup: dict[str, dict] = {}
    for source in catalog.get("sources") or []:
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("source_id") or "").strip()
        if source_id:
            lookup[source_id] = source
    return lookup


def _saved_corpus_source_pack_map(saved_corpus: dict | None) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not isinstance(saved_corpus, dict):
        return mapping
    for pack in saved_corpus.get("packs") or []:
        if not isinstance(pack, dict):
            continue
        pack_id = str(pack.get("pack_id") or "").strip()
        for source_id in pack.get("source_ids") or []:
            source_text = str(source_id or "").strip()
            if source_text and pack_id and source_text not in mapping:
                mapping[source_text] = pack_id
    return mapping


def _build_browser_install_manifest(saved_corpus: dict) -> dict:
    source_ids = _expected_saved_corpus_source_ids(saved_corpus)
    if not source_ids:
        raise ValueError("Saved corpus has no resolved sources")

    source_lookup = _catalog_source_lookup()
    source_pack_map = _saved_corpus_source_pack_map(saved_corpus)
    manifest_sources = []
    total_transfer_bytes = 0
    total_stored_bytes = 0
    total_expanded_bytes = 0

    for source_id in source_ids:
        source = source_lookup.get(source_id)
        if not isinstance(source, dict):
            raise ValueError(f"Published catalog is missing source metadata for {source_id}")
        artifact = _normalize_browser_artifact(source.get("browser_artifact"))
        if not artifact:
            raise ValueError(f"Published catalog is missing browser artifact metadata for {source_id}")
        if artifact.get("transfer_bytes", 0) <= 0 or artifact.get("stored_bytes", 0) <= 0 or artifact.get("expanded_bytes", 0) <= 0:
            raise ValueError(f"Browser artifact metadata is incomplete for {source_id}")
        total_transfer_bytes += int(artifact["transfer_bytes"])
        total_stored_bytes += int(artifact["stored_bytes"])
        total_expanded_bytes += int(artifact["expanded_bytes"])
        manifest_sources.append({
            "source_id": source_id,
            "source_name": str(source.get("source_name") or source_id),
            "pack_id": source_pack_map.get(source_id) or str(source.get("pack_id") or "").strip(),
            "path": str(source.get("path") or "").strip(),
            "browser_artifact": artifact,
            "size": source.get("size") if isinstance(source.get("size"), dict) else None,
            "download_path": f"/api/research/browser-save/source-artifact/{saved_corpus.get('id')}/{source_id}",
        })

    return {
        "manifest_version": 1,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "saved_corpus": {
            "id": saved_corpus.get("id"),
            "name": saved_corpus.get("name"),
            "updated_at": saved_corpus.get("updated_at"),
            "pack_ids": saved_corpus.get("pack_ids") or [],
            "source_ids": saved_corpus.get("source_ids") or [],
            "resolved_source_ids": source_ids,
            "pack_count": saved_corpus.get("pack_count"),
            "source_count": saved_corpus.get("source_count"),
            "resolved_source_count": len(source_ids),
        },
        "sources": manifest_sources,
        "totals": {
            "transfer_bytes": total_transfer_bytes,
            "stored_bytes": total_stored_bytes,
            "expanded_bytes": total_expanded_bytes,
            "transfer_mb": round(total_transfer_bytes / (1024 * 1024), 2),
            "stored_mb": round(total_stored_bytes / (1024 * 1024), 2),
            "expanded_mb": round(total_expanded_bytes / (1024 * 1024), 2),
        },
    }


def _read_browser_artifact_bytes(storage_key: str) -> tuple[bytes, str]:
    storage_key = str(storage_key or "").strip().lstrip("/")
    if not storage_key:
        raise FileNotFoundError("No browser artifact storage key provided")
    if is_cloud_mode():
        import boto3 as _boto3
        from botocore.exceptions import ClientError as _BotoClientError
        from mapmover.runtime_config import get_runtime_config

        cloud_cfg = get_runtime_config().get("cloud", {})
        bucket = os.environ.get("S3_BUCKET", "").strip() or str(cloud_cfg.get("bucket", "")).strip()
        endpoint_url = os.environ.get("S3_ENDPOINT_URL") or cloud_cfg.get("endpoint_url")
        region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "auto"
        client = _boto3.client("s3", endpoint_url=endpoint_url, region_name=region)
        try:
            obj = client.get_object(Bucket=bucket, Key=storage_key)
        except _BotoClientError as exc:
            error_code = (exc.response or {}).get("Error", {}).get("Code", "")
            status_code = (exc.response or {}).get("ResponseMetadata", {}).get("HTTPStatusCode")
            if error_code in ("NoSuchKey", "NoSuchBucket", "404") or status_code == 404:
                raise FileNotFoundError(
                    f"Browser artifact not found in cloud at key {storage_key}"
                ) from exc
            raise
        body = obj["Body"].read()
        content_type = str(obj.get("ContentType") or "application/gzip")
        return body, content_type

    local_path = (_PRIVATE_BROWSER_ARTIFACT_OUTPUT_ROOT / storage_key.replace("/", os.sep)).resolve()
    if not local_path.exists():
        raise FileNotFoundError(f"Local browser artifact not found: {local_path}")
    return local_path.read_bytes(), "application/gzip"


def _restore_browser_install_source_snapshots(
    session_id: str,
    saved_corpus: dict,
    source_snapshots: list[dict] | None,
) -> dict:
    expected_source_ids = _expected_saved_corpus_source_ids(saved_corpus)
    expected_source_set = set(expected_source_ids)
    if not expected_source_ids:
        raise ValueError("Saved corpus has no resolved sources")

    cache = session_manager.get_or_create(session_id)
    corpus_registry.clear_artifacts(session_id)
    corpus_registry.set_saved_corpus(session_id, saved_corpus)

    seen_source_ids: set[str] = set()
    for snapshot in source_snapshots or []:
        if not isinstance(snapshot, dict):
            continue
        source_meta = snapshot.get("source") or {}
        result = snapshot.get("result")
        source_id = str(source_meta.get("source_id") or "").strip()
        if not source_id:
            raise ValueError("Source snapshot is missing source_id")
        if source_id in seen_source_ids:
            continue
        if source_id not in expected_source_set:
            raise ValueError(f"Source snapshot {source_id} is not part of the saved corpus")
        if not isinstance(result, dict):
            raise ValueError(f"Source snapshot {source_id} is missing result payload")

        request_key = _saved_corpus_request_key(str(saved_corpus.get("id") or "saved"), source_id)
        cache.store_result(request_key, result)
        order = {
            "items": [
                {
                    "source_id": source_id,
                    "region": "global",
                    "metric": next(iter(result.get("available_metrics") or []), None),
                }
            ],
            "summary": result.get("summary") or f"Loaded {source_id} into Research.",
        }
        corpus_registry.register_order_result(
            session_id=session_id,
            request_key=request_key,
            order=order,
            response=result,
        )
        seen_source_ids.add(source_id)

    if seen_source_ids != expected_source_set:
        missing = sorted(expected_source_set - seen_source_ids)
        raise ValueError(
            "Browser source install is incomplete for this saved corpus "
            f"(missing source snapshots: {missing})"
        )

    return corpus_registry.manifest(session_id)


def _decode_browser_source_artifact_payloads(source_artifacts: list[dict] | None) -> list[dict]:
    decoded_snapshots: list[dict] = []
    for artifact_entry in source_artifacts or []:
        if not isinstance(artifact_entry, dict):
            continue
        payload = artifact_entry.get("payload")
        if isinstance(payload, memoryview):
            payload = payload.tobytes()
        elif isinstance(payload, bytearray):
            payload = bytes(payload)
        if not isinstance(payload, (bytes, bytearray)):
            raise ValueError("Browser source artifact payload must be binary")
        try:
            json_bytes = gzip.decompress(bytes(payload))
            decoded_snapshot = json.loads(json_bytes.decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"Could not decode browser source artifact payload: {exc}") from exc
        if not isinstance(decoded_snapshot, dict):
            raise ValueError("Decoded browser source artifact payload is invalid")
        decoded_snapshots.append(decoded_snapshot)
    return decoded_snapshots


async def _decode_msgpack_request(req: Request) -> dict:
    body_bytes = await req.body()
    return msgpack.unpackb(body_bytes, raw=False)


async def _decode_json_or_msgpack_request(req: Request) -> dict:
    body_bytes = await req.body()
    try:
        return json.loads(body_bytes.decode("utf-8"))
    except Exception:
        return msgpack.unpackb(body_bytes, raw=False)


def _research_settings() -> tuple[str, float]:
    model = os.getenv("RESEARCH_MODEL", "claude-sonnet-4-6").strip() or "claude-sonnet-4-6"
    try:
        temperature = float(os.getenv("RESEARCH_TEMPERATURE", "0.1"))
    except ValueError:
        temperature = 0.1
    return model, temperature


def _extract_text(content_blocks) -> str:
    parts = []
    for block in content_blocks or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _content_block_types(content_blocks) -> list[str]:
    types: list[str] = []
    for block in content_blocks or []:
        block_type = getattr(block, "type", None)
        if block_type:
            types.append(str(block_type))
            continue
        if isinstance(block, dict) and block.get("type"):
            types.append(str(block.get("type")))
    return types


def _run_research_rescue_synthesis(
    *,
    client: Anthropic,
    model: str,
    temperature: float,
    system_prompt,  # str or list of cache_control content blocks
    messages: list[dict],
    session_id: str,
    query: str,
    usage_recorder=None,
) -> object | None:
    rescue_messages = list(messages)
    rescue_messages.append(
        {
            "role": "user",
            "content": (
                "Write the best grounded final answer now using only the evidence already gathered above. "
                "Do not call tools. If the evidence is partial, answer the grounded part first and then "
                "name the remaining limitation clearly."
            ),
        }
    )
    try:
        response = client.messages.create(
            model=model,
            system=system_prompt,
            messages=rescue_messages,
            temperature=temperature,
            max_tokens=_RESEARCH_MAX_TOKENS,
        )
        if usage_recorder is not None:
            usage_recorder.record(response)
        return response
    except Exception:
        logger.exception(
            "Research rescue synthesis call failed session=%s query=%r",
            session_id,
            query[:120],
        )
        return None


def _tool_call_signature(tool_name: str, tool_input: dict | None) -> str:
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    filters = tool_input.get("filters") if isinstance(tool_input.get("filters"), dict) else {}
    order_by = tool_input.get("order_by") if isinstance(tool_input.get("order_by"), list) else []
    payload = {
        "tool": tool_name,
        "artifact_id": tool_input.get("artifact_id"),
        "filter_keys": sorted(str(key) for key in filters.keys()),
        "group_by": sorted(str(value) for value in (tool_input.get("group_by") or [])),
        "metrics": sorted(str(value) for value in (tool_input.get("metrics") or [])),
        "fields": sorted(str(value) for value in (tool_input.get("fields") or [])),
        "order_by": [
            {
                "field": str(item.get("field") or ""),
                "direction": str(item.get("direction") or "desc"),
            }
            for item in order_by
            if isinstance(item, dict)
        ],
    }
    return json.dumps(payload, sort_keys=True, default=str)


def _build_research_tool_guardrail_message(
    *,
    tool_iterations_used: int,
    recent_tool_signatures: list[str],
) -> str | None:
    if tool_iterations_used < 3:
        return None

    repeated_signature = (
        len(recent_tool_signatures) >= 2
        and recent_tool_signatures[-1] == recent_tool_signatures[-2]
    )
    repeated_recently = (
        len(recent_tool_signatures) >= 3
        and len(set(recent_tool_signatures[-3:])) == 1
    )

    if tool_iterations_used >= 5 or repeated_recently:
        message = (
            "Tool budget reminder: you have already used several tool rounds. "
            "Do not keep retrying the same artifact with slightly different filters. "
            "Either write the best grounded answer from the evidence you already have, "
            "or ask one short clarifying question if a key ambiguity is blocking the answer. "
            "Prefer a partial grounded answer over more exploratory retries."
        )
    else:
        message = (
            "Tool budget reminder: if you cannot isolate the answer after a few tool rounds, "
            "stop and either answer from the evidence already gathered or ask one short clarifying question. "
            "Do not assume a filter failed just because the preview is capped."
        )

    if repeated_signature:
        message += " You appear to be repeating a very similar tool pattern; switch to synthesis or clarification now."
    return message

def _broad_research_fallback_message(query: str, manifest: dict, research_hints: dict | None = None) -> str:
    artifact_count = int(manifest.get("artifact_count") or 0)
    saved = manifest.get("saved_corpus") or {}
    pack_count = int(saved.get("pack_count") or 0)
    query_text = str(query or "").strip()
    lowered = query_text.lower()
    broad_markers = (
        "other metrics",
        "what can you tell me",
        "what changed",
        "how were",
        "after its biggest earthquake",
    )
    if artifact_count >= 8 or any(marker in lowered for marker in broad_markers):
        return (
            f'That question is broad for the current Research workspace: it spans {artifact_count} loaded artifacts'
            + (f" across {pack_count} packs" if pack_count else "")
            + ". Try narrowing it to one event plus a smaller metric set. For example:\n"
              "- `What changed in Japan after the 2011 Tohoku earthquake in SDG Goal 1 and Goal 8?`\n"
              "- `Compare Japan before vs after 2011 for poverty, population, GDP, and energy use.`\n"
              "- `What was Japan's biggest earthquake, and which 3-5 later indicators moved the most after it?`"
        )
    return "I could not produce a research answer from the active corpus."


def _word_chunks(text: str, words_per_chunk: int = 4):
    words = str(text or "").split(" ")
    for idx in range(0, len(words), words_per_chunk):
        chunk = " ".join(words[idx:idx + words_per_chunk])
        if idx + words_per_chunk < len(words):
            chunk += " "
        yield chunk


def _fallback_display_message(display: dict | None) -> str | None:
    if not isinstance(display, dict):
        return None
    if str(display.get("action") or "").strip() != "highlight_features":
        return None
    feature_count = len(((display.get("geojson") or {}).get("features") or []))
    if feature_count <= 0:
        return None
    source_id = str(display.get("source_id") or "").strip()
    if source_id == "fairfax_buildings":
        noun = "building footprint"
    elif "lst" in source_id or "raster" in source_id:
        noun = "raster area"
    else:
        noun = "matching feature"
    suffix = "" if feature_count == 1 else "s"
    return f"Highlighted {feature_count} {noun}{suffix} on the map."


def _history_messages(history: list, max_messages: int = 12) -> list[dict]:
    messages = []
    for msg in (history or [])[-max_messages:]:
        role = msg.get("role", "user")
        content = (msg.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        messages.append({"role": role, "content": content})
    return messages


def _research_memory_messages(research_memory: dict | None) -> list[dict]:
    if not isinstance(research_memory, dict):
        return []

    messages = []
    original_goal = str(research_memory.get("originalGoal") or "").strip()
    summary = str(research_memory.get("summary") or "").strip()
    compacted_count = research_memory.get("compactedMessageCount")
    active_display_state = research_memory.get("activeDisplayState")

    if original_goal:
        messages.append(
            {
                "role": "user",
                "content": f"Original research goal from earlier in this session: {original_goal}",
            }
        )
    if summary:
        label = "Compacted memory from earlier research turns"
        if compacted_count:
            label += f" ({compacted_count} earlier messages)"
        messages.append(
            {
                "role": "assistant",
                "content": f"{label}:\n{summary}",
            }
        )
    if isinstance(active_display_state, dict) and active_display_state:
        messages.append(
            {
                "role": "assistant",
                "content": "Current active Research display state:\n```json\n" + json.dumps(active_display_state, indent=2, default=str) + "\n```",
            }
        )
    return messages


def _compact_manifest_for_prompt(manifest: dict) -> dict:
    saved_corpus = manifest.get("saved_corpus") or {}
    compact_saved = None
    if saved_corpus:
        compact_saved = {
            "id": saved_corpus.get("id"),
            "name": saved_corpus.get("name"),
            "pack_count": saved_corpus.get("pack_count"),
            "source_count": saved_corpus.get("source_count"),
            "estimated_row_count_total": saved_corpus.get("estimated_row_count_total"),
            "estimated_file_size_mb_total": saved_corpus.get("estimated_file_size_mb_total"),
            "pack_ids": saved_corpus.get("pack_ids") or [],
            "source_ids": saved_corpus.get("source_ids") or [],
            "packs": [
                {
                    "pack_id": pack.get("pack_id"),
                    "pack_name": pack.get("pack_name"),
                    "source_ids": pack.get("source_ids") or [],
                    "source_count": pack.get("source_count"),
                    "file_size_mb_total": pack.get("file_size_mb_total"),
                    "row_count_total": pack.get("row_count_total"),
                    "time_coverage_start": pack.get("time_coverage_start"),
                    "time_coverage_end": pack.get("time_coverage_end"),
                }
                for pack in (saved_corpus.get("packs") or [])[:_PROMPT_SAVED_PACK_LIMIT]
            ],
        }

    manifest_artifacts = manifest.get("artifacts") or []
    artifacts = []
    for artifact in manifest_artifacts[:_PROMPT_ARTIFACT_WINDOW]:
        artifacts.append(
            {
                "artifact_id": artifact.get("artifact_id"),
                "source_id": artifact.get("source_id"),
                "source_name": artifact.get("source_name"),
                "data_type": artifact.get("data_type"),
                "geographic_level": artifact.get("geographic_level"),
                "future_available": artifact.get("future_available"),
                "routing_summary": artifact.get("routing_summary"),
                "metric_groups": artifact.get("metric_groups") or {},
                "metrics": _sample_prompt_metrics(artifact.get("metrics") or [], _PROMPT_METRIC_LIMIT),
                "metric_count": len(artifact.get("metrics") or []),
                "fields": (artifact.get("fields") or [])[:_PROMPT_FIELD_LIMIT],
                "year_range": artifact.get("year_range"),
                "feature_count": artifact.get("feature_count"),
                "row_count": artifact.get("row_count"),
                "summary": artifact.get("summary"),
                "scene_periods": (artifact.get("scene_periods") or [])[:_PROMPT_SCENE_PERIOD_LIMIT],
                "raster_clip_levels": artifact.get("raster_clip_levels") or [],
            }
        )

    compact = {
        "session_id": manifest.get("session_id"),
        "mode": manifest.get("mode"),
        "artifact_count": manifest.get("artifact_count"),
        "artifacts": artifacts,
        "saved_corpus": compact_saved,
    }
    omitted = max(0, len(manifest_artifacts) - len(artifacts))
    if omitted:
        compact["artifacts_omitted"] = omitted
        compact["omitted_source_ids"] = [
            str((artifact or {}).get("source_id") or "").strip()
            for artifact in manifest_artifacts[len(artifacts):len(artifacts) + 20]
            if str((artifact or {}).get("source_id") or "").strip()
        ]
    return compact


def _focus_loc_ids_from_result(result: dict | None) -> list[str]:
    if not isinstance(result, dict):
        return []

    loc_ids: list[str] = []
    seen = set()

    for feature in ((result.get("geojson") or {}).get("features") or []):
        loc_id = ((feature.get("properties") or {}).get("loc_id"))
        if loc_id is None:
            continue
        text = str(loc_id).strip()
        if text and text not in seen:
            seen.add(text)
            loc_ids.append(text)

    for _year, loc_map in (result.get("year_data") or {}).items():
        for loc_id in (loc_map or {}).keys():
            text = str(loc_id).strip()
            if text and text not in seen:
                seen.add(text)
                loc_ids.append(text)

    if not loc_ids:
        return []

    shallowest = min(text.count("-") for text in loc_ids)
    return [text for text in loc_ids if text.count("-") == shallowest][:24]


def _build_research_focus_geojson(session_id: str) -> dict | None:
    cache = session_manager.get(session_id)
    if cache is None:
        return None

    focus_loc_ids: list[str] = []
    seen = set()
    for artifact in corpus_registry.list_artifacts(session_id):
        request_key = str(artifact.get("request_key") or "").strip()
        if not request_key:
            continue
        result = cache.get_cached_result(request_key)
        for loc_id in _focus_loc_ids_from_result(result):
            if loc_id not in seen:
                seen.add(loc_id)
                focus_loc_ids.append(loc_id)

    if not focus_loc_ids:
        return None

    geojson = get_selection_geometries(focus_loc_ids)
    if ((geojson or {}).get("features") or []):
        return geojson
    return None


def _compact_tool_result_for_prompt(tool_name: str, tool_result: dict) -> dict:
    if not isinstance(tool_result, dict):
        return {"type": "unsupported_tool_result"}

    compact = {}
    for key in ("error", "artifact_id", "row_count", "truncated"):
        if key in tool_result:
            compact[key] = tool_result.get(key)

    if tool_name == "list_artifacts":
        artifacts = tool_result.get("artifacts") or []
        compact["artifacts"] = [
            {
                "artifact_id": artifact.get("artifact_id"),
                "source_id": artifact.get("source_id"),
                "source_name": artifact.get("source_name"),
                "data_type": artifact.get("data_type"),
                "geographic_level": artifact.get("geographic_level"),
                "future_available": artifact.get("future_available"),
                "metric_groups": artifact.get("metric_groups") or {},
                "metrics": _sample_prompt_metrics(artifact.get("metrics") or [], min(12, _PROMPT_METRIC_LIMIT)),
                "metric_count": len(artifact.get("metrics") or []),
            }
            for artifact in artifacts[:_PROMPT_ARTIFACT_WINDOW]
        ]
        compact["artifact_count"] = len(artifacts)
        omitted = max(0, len(artifacts) - len(compact["artifacts"]))
        if omitted:
            compact["artifacts_omitted"] = omitted
            compact["omitted_source_ids"] = [
                str((artifact or {}).get("source_id") or "").strip()
                for artifact in artifacts[len(compact["artifacts"]):len(compact["artifacts"]) + 20]
                if str((artifact or {}).get("source_id") or "").strip()
            ]
        return compact

    if tool_name == "describe_artifact":
        artifact = tool_result.get("artifact") or {}
        compact["artifact"] = {
            "artifact_id": artifact.get("artifact_id"),
            "source_id": artifact.get("source_id"),
            "source_name": artifact.get("source_name"),
            "data_type": artifact.get("data_type"),
            "time_field": artifact.get("time_field"),
            "geographic_level": artifact.get("geographic_level"),
            "future_available": artifact.get("future_available"),
            "routing_summary": artifact.get("routing_summary"),
            "metric_groups": artifact.get("metric_groups") or {},
            "metrics": _sample_prompt_metrics(artifact.get("metrics") or [], _PROMPT_METRIC_LIMIT),
            "metric_count": len(artifact.get("metrics") or []),
            "fields": (artifact.get("fields") or [])[:_PROMPT_FIELD_LIMIT],
            "year_range": artifact.get("year_range"),
            "feature_count": artifact.get("feature_count"),
            "row_count": artifact.get("row_count"),
            "summary": artifact.get("summary"),
            "scene_periods": (artifact.get("scene_periods") or [])[:_PROMPT_SCENE_PERIOD_LIMIT],
            "raster_clip_levels": artifact.get("raster_clip_levels") or [],
        }
        return compact

    if tool_name in {"query_artifact_slice", "build_artifact_display_subset"}:
        rows = tool_result.get("rows") or []
        compact["rows_preview"] = rows[:_TOOL_ROWS_PREVIEW_LIMIT]
        compact["preview_count"] = min(len(rows), _TOOL_ROWS_PREVIEW_LIMIT)
        compact["returned_row_count"] = len(rows)
        compact["preview_note"] = (
            "rows_preview is only a capped sample of the returned rows. "
            "Use row_count for total matched rows and returned_row_count for rows actually returned by the tool."
        )
        if isinstance(tool_result.get("display_warning"), dict):
            compact["display_warning"] = tool_result.get("display_warning")
        if tool_name == "build_artifact_display_subset":
            display = tool_result.get("display") or {}
            compact["display"] = {
                "action": display.get("action"),
                "source_id": display.get("source_id"),
                "fit": display.get("fit"),
                "context_visibility": display.get("context_visibility"),
                "feature_count": len(((display.get("geojson") or {}).get("features") or [])),
                "loc_id_count": len(display.get("loc_ids") or []),
            }
        return compact

    return tool_result


def _build_display_warning_result(manifest: dict, warning: dict, query: str) -> dict:
    warning = warning or {}
    level = str(warning.get("level") or "soft_cap")
    row_count = int(warning.get("row_count") or 0)
    soft_cap = int(warning.get("soft_cap") or 0)
    hard_cap = int(warning.get("hard_cap") or 0)
    message = str(warning.get("message") or "").strip()
    gate = warning.get("gate") if isinstance(warning.get("gate"), dict) else None
    if not message:
        if level == "hard_cap":
            message = (
                f"This request would draw about {row_count:,} features, which exceeds the safe display cap of "
                f"{hard_cap:,}. Narrow it first."
            )
        else:
            message = (
                f"This request matches about {row_count:,} features, which may slow the map down. "
                "Narrow it first, or confirm that you want to load it anyway."
            )
    return {
        "type": "display_warning",
        "message": message,
        "corpus": manifest,
        "query": query,
        "warning_level": level,
        "row_count": row_count,
        "soft_cap": soft_cap,
        "hard_cap": hard_cap,
        "override_allowed": level == "soft_cap",
        "gate": gate,
    }


def run_research_chat(
    *,
    session_id: str,
    query: str,
    chat_history: list | None = None,
    research_memory: dict | None = None,
    progress=None,
    force_large_display: bool = False,
    usage_recorder=None,
    rescue_usage_recorder=None,
) -> dict:
    """Synchronous research pipeline.

    The streaming endpoint runs this on a worker thread via
    asyncio.to_thread and passes a thread-safe `progress` callable from
    a ProgressBus. The callable is invoked before each tool execution
    so the UI can show what the model is actually doing. When `progress`
    is None the function behaves identically to before.
    """
    manifest = corpus_registry.manifest(session_id)
    if manifest.get("artifact_count", 0) == 0 and not manifest.get("saved_corpus"):
        return {
            "type": "chat",
            "message": "No data is loaded into the Research workspace yet. Select a saved corpus and load it into Research first.",
            "corpus": manifest,
        }
    if manifest.get("artifact_count", 0) == 0 and manifest.get("saved_corpus"):
        saved = manifest.get("saved_corpus") or {}
        pack_count = int(saved.get("pack_count") or 0)
        source_count = int(saved.get("source_count") or 0)
        return {
            "type": "chat",
            "message": (
                f'Research workspace "{saved.get("name") or "Saved corpus"}" is selected, '
                f'with {pack_count} pack{"s" if pack_count != 1 else ""}'
                + (
                    f' and {source_count} direct source{"s" if source_count != 1 else ""}'
                    if source_count
                    else ""
                )
                + ". I can use that workspace definition to stay oriented, but I do not have loaded Research artifacts to analyze yet. "
                  "Load that corpus into Research first, or expand the Research loader later so this corpus hydrates concrete artifacts."
            ),
            "corpus": manifest,
        }

    model, temperature = _research_settings()
    system_prompt = build_research_system_prompt(manifest)
    research_hints = preprocess_research_query(query, manifest)
    hint_context = build_research_hint_context(research_hints)
    prompt_manifest = _compact_manifest_for_prompt(manifest)
    # Two cache breakpoints (Anthropic allows up to 4 per request):
    #   1. system_prompt_blocks - full research system prompt (stable per deploy).
    #   2. corpus manifest message - stable for the lifetime of the corpus, large.
    # Iterations 2..N of one user query, plus any subsequent queries within the
    # 5-minute TTL, read these from cache at ~10% of the input price.
    system_prompt_blocks = [{
        "type": "text",
        "text": system_prompt,
        "cache_control": {"type": "ephemeral"},
    }]
    messages = [
        {
            "role": "user",
            "content": [{
                "type": "text",
                "text": "Active corpus manifest JSON:\n" + json.dumps(prompt_manifest, default=str, separators=(",", ":")),
                "cache_control": {"type": "ephemeral"},
            }],
        },
        *(
            [{
                "role": "user",
                "content": "Research preprocessor hints:\n" + hint_context,
            }]
            if hint_context else []
        ),
        *_research_memory_messages(research_memory),
        *_history_messages(chat_history or []),
        {"role": "user", "content": query},
    ]

    client = Anthropic()
    max_tool_iterations = _RESEARCH_MAX_TOOL_ITERATIONS
    response = None
    final_display = None
    display_warning = None
    tool_iterations_used = 0
    recent_tool_signatures: list[str] = []
    last_guardrail_message: str | None = None
    for _iteration in range(max_tool_iterations + 1):
        try:
            response = client.messages.create(
                model=model,
                system=system_prompt_blocks,
                messages=messages,
                tools=RESEARCH_TOOL_DEFINITIONS,
                temperature=temperature,
                max_tokens=_RESEARCH_MAX_TOKENS,
            )
            if usage_recorder is not None:
                usage_recorder.record(response)
        except Exception as exc:
            approx_message_chars = sum(len(json.dumps(message, default=str)) for message in messages)
            logger.exception(
                "Research Anthropic call failed iteration=%s session=%s query=%r approx_message_chars=%s artifact_count=%s",
                _iteration,
                session_id,
                query[:120],
                approx_message_chars,
                manifest.get("artifact_count"),
            )
            raise

        if response.stop_reason != "tool_use":
            break
        tool_iterations_used += 1

        assistant_content = []
        tool_results = []
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                if progress is not None:
                    friendly = RESEARCH_TOOL_PROGRESS_MESSAGES.get(
                        block.name,
                        f"Running {block.name}...",
                    )
                    progress(ProgressEvent(
                        stage="tool",
                        message=friendly,
                        extra={"tool": block.name, "iteration": _iteration},
                    ))
                tool_result = execute_research_tool(
                    session_id,
                    block.name,
                    block.input,
                    force_large_display=force_large_display,
                )
                recent_tool_signatures.append(_tool_call_signature(block.name, block.input))
                if len(recent_tool_signatures) > 8:
                    recent_tool_signatures = recent_tool_signatures[-8:]
                if isinstance(tool_result, dict) and isinstance(tool_result.get("display_warning"), dict):
                    display_warning = tool_result.get("display_warning")
                if isinstance(tool_result, dict) and isinstance(tool_result.get("display"), dict):
                    final_display = dict(tool_result["display"])
                    if progress is not None:
                        progress(ProgressEvent(
                            stage="display",
                            message="Updating the map display...",
                            extra={"display": final_display},
                        ))
                compact_tool_result = _compact_tool_result_for_prompt(block.name, tool_result)
                assistant_content.append(block)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(compact_tool_result, default=str),
                    }
                )
            else:
                assistant_content.append(block)

        if display_warning:
            break

        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": tool_results})
        guardrail_message = _build_research_tool_guardrail_message(
            tool_iterations_used=tool_iterations_used,
            recent_tool_signatures=recent_tool_signatures,
        )
        if guardrail_message and guardrail_message != last_guardrail_message:
            messages.append({"role": "user", "content": guardrail_message})
            last_guardrail_message = guardrail_message

    if display_warning:
        logger.info(
            "Research display warning session=%s query=%r level=%s row_count=%s soft_cap=%s hard_cap=%s force=%s",
            session_id,
            query[:120],
            display_warning.get("level"),
            display_warning.get("row_count"),
            display_warning.get("soft_cap"),
            display_warning.get("hard_cap"),
            force_large_display,
        )
        return _build_display_warning_result(manifest, display_warning, query)

    if response and response.stop_reason == "tool_use":
        if progress is not None:
            progress(ProgressEvent(
                stage="writing",
                message="Finishing the analysis...",
                extra={"phase": "final_synthesis"},
            ))
        try:
            response = client.messages.create(
                model=model,
                system=system_prompt_blocks,
                messages=messages,
                temperature=temperature,
                max_tokens=_RESEARCH_MAX_TOKENS,
            )
            if usage_recorder is not None:
                usage_recorder.record(response)
        except Exception:
            logger.exception(
                "Research final synthesis call failed after max tool iterations session=%s query=%r",
                session_id,
                query[:120],
            )

    if progress is not None:
        progress(ProgressEvent(
            stage="writing",
            message="Drafting the answer...",
            extra={"phase": "compose"},
        ))

    text = _extract_text(response.content if response else [])
    if not text:
        logger.warning(
            "Research response missing text session=%s query=%r stop_reason=%s content_types=%s tool_iterations_used=%s artifact_count=%s",
            session_id,
            query[:120],
            getattr(response, "stop_reason", None) if response else None,
            _content_block_types(response.content if response else []),
            tool_iterations_used,
            manifest.get("artifact_count"),
        )
        rescue_response = _run_research_rescue_synthesis(
            client=client,
            model=model,
            temperature=temperature,
            system_prompt=system_prompt_blocks,
            messages=messages,
            session_id=session_id,
            query=query,
            usage_recorder=rescue_usage_recorder,
        )
        rescue_text = _extract_text(rescue_response.content if rescue_response else [])
        if rescue_text:
            response = rescue_response
            text = rescue_text
        else:
            logger.warning(
                "Research rescue synthesis also missing text session=%s query=%r stop_reason=%s content_types=%s",
                session_id,
                query[:120],
                getattr(rescue_response, "stop_reason", None) if rescue_response else None,
                _content_block_types(rescue_response.content if rescue_response else []),
            )
    if not text:
        text = _fallback_display_message(final_display) or _broad_research_fallback_message(query, manifest, research_hints)
    result = {
        "type": "chat",
        "message": text,
        "corpus": manifest,
        "display": final_display,
        "research_hints": research_hints,
    }
    if final_display:
        display_geojson = final_display.get("geojson") or {}
        display_features = display_geojson.get("features") or []
        logger.info(
            "Research final response session=%s query=%r message_len=%s display_action=%s display_source=%s display_features=%s",
            session_id,
            query[:120],
            len(text or ""),
            final_display.get("action"),
            final_display.get("source_id"),
            len(display_features),
        )
    else:
        logger.info(
            "Research final response session=%s query=%r message_len=%s display_action=none",
            session_id,
            query[:120],
            len(text or ""),
        )
    return normalize_research_result(result, lane="research")


@router.post("/api/research/corpus")
async def research_corpus_endpoint(req: Request):
    """Return compact active corpus manifest for a session."""
    try:
        body = await _decode_msgpack_request(req)
        frontend_session_id = body.get("sessionId", "anonymous")
        auth_user = await get_authenticated_user_async(req)
        session_id = build_session_cache_key(frontend_session_id, auth_user)
        return msgpack_response(_annotate_manifest_saved_corpus_state(corpus_registry.manifest(session_id)))
    except Exception as e:
        logger.exception("Research corpus snapshot error")
        return msgpack_error(str(e), 500)


@router.post("/api/research/load-saved-corpus")
async def research_load_saved_corpus_endpoint(req: Request):
    """Attach a saved account corpus definition to the active Research session."""
    try:
        body = await _decode_msgpack_request(req)
        corpus_id = str(body.get("corpusId") or "").strip()
        if not corpus_id:
            return msgpack_error("No corpusId provided", 400)

        auth_user = await get_authenticated_user_async(req)
        user_id = (auth_user or {}).get("id")
        if not user_id:
            return msgpack_error("Authentication required to load a saved corpus", 401)

        frontend_session_id = body.get("sessionId", "anonymous")
        session_id = build_session_cache_key(frontend_session_id, auth_user)
        saved_corpus = _load_saved_corpus_for_user(user_id, corpus_id)
        if not saved_corpus:
            return msgpack_error("Saved corpus not found", 404)

        corpus_registry.set_saved_corpus(session_id, saved_corpus)
        hydration = _hydrate_saved_corpus(session_id, saved_corpus)
        manifest = _annotate_manifest_saved_corpus_state(corpus_registry.manifest(session_id))
        focus_geojson = _build_research_focus_geojson(session_id)
        prompt_window_warning = _manifest_prompt_window_warning(manifest)
        return msgpack_response({
            "type": "saved_corpus_loaded",
            "message": f'Loaded "{saved_corpus.get("name")}" into the Research workspace.',
            "corpus": manifest,
            "hydration": hydration,
            "focus_geojson": focus_geojson,
            "warning": prompt_window_warning,
        })
    except Exception as e:
        logger.exception("Research saved corpus load error")
        return msgpack_error(str(e), 500)

@router.post("/api/research/browser-save/install-manifest")
async def research_build_browser_install_manifest_endpoint(req: Request):
    """Return a source-artifact install manifest for a saved corpus."""
    wants_msgpack = "application/msgpack" in str(req.headers.get("accept") or "").lower()
    try:
        body = await _decode_json_or_msgpack_request(req)
        corpus_id = str(body.get("corpusId") or "").strip()
        if not corpus_id:
            payload = {"ok": False, "error": "No corpusId provided"}
            return msgpack_response(payload, status_code=400) if wants_msgpack else JSONResponse(payload, status_code=400)

        auth_user = await get_authenticated_user_async(req)
        user_id = (auth_user or {}).get("id")
        if not user_id:
            payload = {"ok": False, "error": "Authentication required"}
            return msgpack_response(payload, status_code=401) if wants_msgpack else JSONResponse(payload, status_code=401)

        saved_corpus = _load_saved_corpus_for_user(user_id, corpus_id)
        if not saved_corpus:
            payload = {"ok": False, "error": "Saved corpus not found"}
            return msgpack_response(payload, status_code=404) if wants_msgpack else JSONResponse(payload, status_code=404)

        install_manifest = _build_browser_install_manifest(saved_corpus)
        payload = _json_safe_value({
            "ok": True,
            "install_manifest": install_manifest,
        })
        return msgpack_response(payload) if wants_msgpack else JSONResponse(payload)
    except ValueError as exc:
        payload = {"ok": False, "error": str(exc)}
        return msgpack_response(payload, status_code=409) if wants_msgpack else JSONResponse(payload, status_code=409)
    except Exception as exc:
        logger.exception("Research browser install-manifest error")
        payload = {"ok": False, "error": str(exc)}
        return msgpack_response(payload, status_code=500) if wants_msgpack else JSONResponse(payload, status_code=500)


@router.get("/api/research/browser-save/source-artifact/{corpus_id}/{source_id}")
async def research_browser_source_artifact_endpoint(corpus_id: str, source_id: str, req: Request):
    """Return the published gz browser artifact for one saved-corpus source."""
    try:
        corpus_id = str(corpus_id or "").strip()
        source_id = str(source_id or "").strip()
        if not corpus_id or not source_id:
            return JSONResponse({"ok": False, "error": "Missing corpus_id or source_id"}, status_code=400)

        auth_user = await get_authenticated_user_async(req)
        user_id = (auth_user or {}).get("id")
        if not user_id:
            return JSONResponse({"ok": False, "error": "Authentication required"}, status_code=401)

        saved_corpus = _load_saved_corpus_for_user(user_id, corpus_id)
        if not saved_corpus:
            return JSONResponse({"ok": False, "error": "Saved corpus not found"}, status_code=404)

        install_manifest = _build_browser_install_manifest(saved_corpus)
        source_entry = next(
            (entry for entry in install_manifest.get("sources") or [] if str(entry.get("source_id") or "").strip() == source_id),
            None,
        )
        if not source_entry:
            return JSONResponse({"ok": False, "error": "Source is not part of the saved corpus"}, status_code=404)

        artifact = source_entry.get("browser_artifact") or {}
        storage_key = str(artifact.get("storage_key") or "").strip()
        artifact_bytes, content_type = _read_browser_artifact_bytes(storage_key)
        headers = {
            "Content-Length": str(len(artifact_bytes)),
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": f'inline; filename="{source_id}_runtime_snapshot_v1.json.gz"',
            "X-DaedalMap-Source-Id": source_id,
            "X-DaedalMap-Artifact-Version": str(artifact.get("artifact_version") or ""),
            "X-DaedalMap-Sha256": str(artifact.get("sha256") or ""),
        }
        return Response(content=artifact_bytes, media_type=content_type or "application/gzip", headers=headers)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    except FileNotFoundError as exc:
        logger.warning("Research browser source artifact missing: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=404)
    except Exception as exc:
        logger.exception("Research browser source artifact error")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@router.post("/api/research/browser-save/load-install-manifest")
async def research_load_browser_install_manifest_endpoint(req: Request):
    """Restore a browser-saved install manifest and source artifacts into the active session."""
    wants_msgpack = "application/msgpack" in str(req.headers.get("accept") or "").lower()
    try:
        body = await _decode_json_or_msgpack_request(req)
        corpus_id = str(body.get("corpusId") or "").strip()
        source_snapshots = body.get("sourceSnapshots")
        source_artifacts = body.get("sourceArtifacts")
        if not corpus_id:
            payload = {"ok": False, "error": "No corpusId provided"}
            return msgpack_response(payload, status_code=400) if wants_msgpack else JSONResponse(payload, status_code=400)
        if isinstance(source_artifacts, list):
            source_snapshots = _decode_browser_source_artifact_payloads(source_artifacts)
        if not isinstance(source_snapshots, list):
            payload = {"ok": False, "error": "No sourceArtifacts or sourceSnapshots provided"}
            return msgpack_response(payload, status_code=400) if wants_msgpack else JSONResponse(payload, status_code=400)

        auth_user = await get_authenticated_user_async(req)
        user_id = (auth_user or {}).get("id")
        if not user_id:
            payload = {"ok": False, "error": "Authentication required"}
            return msgpack_response(payload, status_code=401) if wants_msgpack else JSONResponse(payload, status_code=401)

        frontend_session_id = str(body.get("sessionId") or f"browser-save:{corpus_id}").strip() or f"browser-save:{corpus_id}"
        session_id = build_session_cache_key(frontend_session_id, auth_user)
        saved_corpus = _load_saved_corpus_for_user(user_id, corpus_id)
        if not saved_corpus:
            payload = {"ok": False, "error": "Saved corpus not found"}
            return msgpack_response(payload, status_code=404) if wants_msgpack else JSONResponse(payload, status_code=404)

        manifest = _annotate_manifest_saved_corpus_state(
            _restore_browser_install_source_snapshots(
                session_id=session_id,
                saved_corpus=saved_corpus,
                source_snapshots=source_snapshots,
            )
        )
        saved_name = ((manifest.get("saved_corpus") or {}).get("name") or "Saved corpus")
        payload = _json_safe_value({
            "ok": True,
            "corpus": manifest,
            "message": f'Loaded "{saved_name}" into the Research workspace from browser-saved source artifacts.',
        })
        return msgpack_response(payload) if wants_msgpack else JSONResponse(payload)
    except ValueError as exc:
        payload = {"ok": False, "error": str(exc)}
        return msgpack_response(payload, status_code=409) if wants_msgpack else JSONResponse(payload, status_code=409)
    except Exception as exc:
        logger.exception("Research browser install-manifest restore error")
        payload = {"ok": False, "error": str(exc)}
        return msgpack_response(payload, status_code=500) if wants_msgpack else JSONResponse(payload, status_code=500)

@router.post("/chat/research")
async def research_chat_endpoint(req: Request):
    """Blocking Research chat endpoint."""
    client_ip = get_client_ip(req)
    try:
        body = await _decode_msgpack_request(req)
        query = body.get("query", "")
        if not query:
            return msgpack_error("No query provided", 400)
        frontend_session_id = body.get("sessionId", "anonymous")
        auth_user = await get_authenticated_user_async(req)
        session_id = build_session_cache_key(frontend_session_id, auth_user)
        caller_ctx = classify_caller(
            auth_user=auth_user,
            ip_hash=hash_ip_for_analytics(client_ip),
        )
        usage_recorder = LLMUsageRecorder(
            surface="research",
            call_kind="research_main",
            session_id=session_id,
            **caller_ctx,
        )
        rescue_usage_recorder = LLMUsageRecorder(
            surface="research",
            call_kind="research_rescue",
            session_id=session_id,
            **caller_ctx,
        )
        # Run the synchronous LLM-driven research pipeline in a thread so we
        # do not block the event loop. Mirrors the streaming endpoint below.
        try:
            result = await asyncio.to_thread(
                run_research_chat,
                session_id=session_id,
                query=query,
                chat_history=body.get("chatHistory", []),
                research_memory=body.get("researchMemory"),
                force_large_display=bool(body.get("force_research_display")),
                usage_recorder=usage_recorder,
                rescue_usage_recorder=rescue_usage_recorder,
            )
        finally:
            usage_recorder.flush()
            rescue_usage_recorder.flush(skip_if_empty=True)
        log_conversation(
            frontend_session_id,
            query,
            result.get("message", ""),
            surface="research",
            intent=result.get("type"),
            ip_hash=hash_ip_for_analytics(client_ip),
            user_agent=(req.headers.get("user-agent") or "")[:300] or None,
        )
        return msgpack_response(result)
    except Exception as e:
        logger.exception("Research chat error")
        log_app_error(type(e).__name__, str(e), surface="human_app", path="/chat/research")
        return msgpack_response({"type": "error", "message": "Research mode encountered an error. Please try again."}, status_code=500)


@router.post("/chat/research/stream")
async def research_chat_stream_endpoint(req: Request):
    """Streaming Research chat endpoint using existing SSE stage shape."""
    body = await _decode_json_or_msgpack_request(req)
    client_ip = get_client_ip(req)

    async def generate_events():
        try:
            query = body.get("query", "")
            if not query:
                yield f"data: {json.dumps({'stage': 'complete', 'result': {'type': 'error', 'message': 'No query provided'}})}\n\n"
                return
            frontend_session_id = body.get("sessionId", "anonymous")
            auth_user = await get_authenticated_user_async(req)
            session_id = build_session_cache_key(frontend_session_id, auth_user)
            caller_ctx = classify_caller(
                auth_user=auth_user,
                ip_hash=hash_ip_for_analytics(client_ip),
            )
            usage_recorder = LLMUsageRecorder(
                surface="research",
                call_kind="research_main",
                session_id=session_id,
                **caller_ctx,
            )
            rescue_usage_recorder = LLMUsageRecorder(
                surface="research",
                call_kind="research_rescue",
                session_id=session_id,
                **caller_ctx,
            )

            yield f"data: {json.dumps({'stage': 'corpus', 'message': 'Reading Research workspace...'})}\n\n"
            yield f"data: {json.dumps({'stage': 'thinking', 'message': 'Researching loaded workspace data...'})}\n\n"

            # Pipe real progress events from the worker thread through a
            # ProgressBus so the UI shows what tool the LLM is actually
            # calling, not rotating filler text. Heartbeat fires only when
            # no real event arrives within the window.
            bus = ProgressBus()
            task = asyncio.create_task(asyncio.to_thread(
                run_research_chat,
                session_id=session_id,
                query=query,
                chat_history=body.get("chatHistory", []),
                research_memory=body.get("researchMemory"),
                progress=bus.thread_emitter(),
                force_large_display=bool(body.get("force_research_display")),
                usage_recorder=usage_recorder,
                rescue_usage_recorder=rescue_usage_recorder,
            ))
            try:
                async for event in bus.drain_until(
                    task,
                    heartbeat_seconds=4.0,
                    heartbeat=_research_heartbeat,
                ):
                    payload = {"stage": event.stage, "message": event.message}
                    if event.extra:
                        payload["extra"] = event.extra
                        if isinstance(event.extra.get("display"), dict):
                            payload["display"] = event.extra["display"]
                    yield f"data: {json.dumps(payload)}\n\n"

                result = await task
            finally:
                usage_recorder.flush()
                rescue_usage_recorder.flush(skip_if_empty=True)
            log_conversation(
                frontend_session_id,
                query,
                result.get("message", ""),
                surface="research",
                intent=result.get("type"),
                ip_hash=hash_ip_for_analytics(client_ip),
                user_agent=(req.headers.get("user-agent") or "")[:300] or None,
            )
            yield f"data: {json.dumps({'stage': 'writing', 'message': 'Writing research answer...'})}\n\n"
            if result.get("type") == "chat" and result.get("message"):
                yield f"data: {json.dumps({'stage': 'answer_start', 'message': ''})}\n\n"
                for chunk in _word_chunks(result.get("message", "")):
                    yield f"data: {json.dumps({'stage': 'delta', 'text': chunk})}\n\n"
                    await asyncio.sleep(0.035)
            yield f"data: {json.dumps({'stage': 'complete', 'result': result})}\n\n"
        except Exception as e:
            logger.exception("Research chat stream error")
            log_app_error(type(e).__name__, str(e), surface="human_app", path="/chat/research/stream")
            error_result = {"type": "error", "message": "Research mode encountered an error. Please try again."}
            yield f"data: {json.dumps({'stage': 'complete', 'result': error_result})}\n\n"

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
