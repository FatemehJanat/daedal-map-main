"""Research mode API router endpoints."""

from __future__ import annotations

import hashlib
import json
import os
import asyncio
from datetime import datetime
from types import SimpleNamespace
from shapely import wkt as shapely_wkt
from shapely.geometry import mapping as shapely_mapping

import msgpack
from anthropic import Anthropic
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from mapmover import logger
from mapmover.auth_context import build_session_cache_key, get_authenticated_user, get_authenticated_user_async
from mapmover.corpus_registry import corpus_registry
from mapmover.logging_analytics import hash_ip_for_analytics, log_app_error, log_conversation
from mapmover.security import get_client_ip
from mapmover.data_loading import get_pack_metadata, get_source_path, load_source_metadata
from mapmover.api_query_runtime import execute_dataset_query, get_api_source_columns, get_api_source_spec
from mapmover.duckdb_helpers import parquet_available, parquet_columns, path_to_uri, quote_ident, run_rows, select_columns_from_parquet
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


def _research_heartbeat(idle_count: int) -> ProgressEvent:
    message = _RESEARCH_HEARTBEAT_MESSAGES[idle_count % len(_RESEARCH_HEARTBEAT_MESSAGES)]
    return ProgressEvent(stage="thinking", message=message, extra={"heartbeat": True})


router = APIRouter()


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
                pack_row_count_total += int(pack_meta.get("row_count_total") or 0)
                pack_file_size_mb_total += float(pack_meta.get("file_size_mb_total") or 0.0)
            else:
                pack_ids.append(item_id)
        elif item_type == "source":
            source_ids.append(item_id)
            if item_id not in resolved_seen:
                resolved_seen.add(item_id)
                resolved_source_ids.append(item_id)

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


def _rows_to_temporal_result(rows: list[dict], source_id: str, metadata: dict, spec) -> dict:
    features_by_loc: dict[str, dict] = {}
    year_data: dict[str, dict] = {}
    metric_ids = list((metadata.get("metrics") or {}).keys())
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
        if not metric_values:
            continue
        year_data.setdefault(time_key, {})[loc_id] = metric_values

    return {
        "type": "data",
        "data_type": "metrics",
        "source_id": source_id,
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
    candidate_names: list[str] = []
    for rel_path in metadata.get("primary_files") or []:
        candidate = source_dir / str(rel_path)
        if candidate.suffix.lower() == ".parquet" and parquet_available(candidate):
            return candidate
        if candidate.suffix.lower() == ".parquet":
            candidate_names.append(str(rel_path))

    for fallback_name in (
        "USA.parquet",
        "all_countries.parquet",
        "all_regions.parquet",
        "data.parquet",
        "events.parquet",
        "full_range.parquet",
    ):
        if fallback_name in candidate_names:
            continue
        candidate = source_dir / fallback_name
        if parquet_available(candidate):
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

    available_columns = parquet_columns(parquet_path)
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

    rows = _load_runtime_rows(parquet_path, select_columns)
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

    available_columns = parquet_columns(parquet_path)
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
        result = _rows_to_temporal_result(rows, source_id, metadata, spec)
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


def _browser_save_snapshot_bytes(snapshot: dict) -> int:
    try:
        return len(json.dumps(snapshot, separators=(",", ":"), default=str).encode("utf-8"))
    except Exception:
        return 0


def _build_browser_corpus_snapshot(session_id: str, saved_corpus: dict) -> dict:
    artifacts = corpus_registry.export_session_artifacts(session_id)
    request_keys = [str(artifact.get("request_key") or "").strip() for artifact in artifacts if artifact.get("request_key")]
    cache = session_manager.get(session_id)
    results = cache.export_results(request_keys) if cache else {}
    snapshot = {
        "snapshot_version": 1,
        "saved_at": datetime.utcnow().isoformat() + "Z",
        "saved_corpus": saved_corpus,
        "artifacts": artifacts,
        "results": results,
    }
    snapshot["size_bytes"] = _browser_save_snapshot_bytes(snapshot)
    return snapshot


def _restore_browser_corpus_snapshot(
    session_id: str,
    snapshot: dict,
    *,
    expected_saved_corpus: dict | None = None,
) -> dict:
    saved_corpus = snapshot.get("saved_corpus")
    artifacts = snapshot.get("artifacts") or []
    results = snapshot.get("results") or {}
    expected_corpus = expected_saved_corpus or saved_corpus

    if not _artifacts_match_saved_corpus(artifacts, expected_corpus):
        expected_sources = _expected_saved_corpus_source_ids(expected_corpus)
        actual_sources = _artifact_source_ids(artifacts)
        raise ValueError(
            "Browser-saved corpus is out of date for this saved corpus definition "
            f"(expected sources: {expected_sources}, found: {actual_sources})"
        )

    corpus_registry.clear_artifacts(session_id)
    if expected_corpus:
        corpus_registry.set_saved_corpus(session_id, expected_corpus)
    elif saved_corpus:
        corpus_registry.set_saved_corpus(session_id, saved_corpus)
    cache = session_manager.get_or_create(session_id)
    cache.import_results(results)
    corpus_registry.import_session_artifacts(session_id, artifacts)
    return corpus_registry.manifest(session_id)


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
    elif source_id == "fairfax_lst":
        noun = "hot area"
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
                for pack in (saved_corpus.get("packs") or [])[:8]
            ],
        }

    artifacts = []
    for artifact in (manifest.get("artifacts") or [])[:12]:
        artifacts.append(
            {
                "artifact_id": artifact.get("artifact_id"),
                "source_id": artifact.get("source_id"),
                "source_name": artifact.get("source_name"),
                "data_type": artifact.get("data_type"),
                "geographic_level": artifact.get("geographic_level"),
                "metrics": (artifact.get("metrics") or [])[:12],
                "fields": (artifact.get("fields") or [])[:20],
                "year_range": artifact.get("year_range"),
                "feature_count": artifact.get("feature_count"),
                "row_count": artifact.get("row_count"),
                "summary": artifact.get("summary"),
                "scene_periods": (artifact.get("scene_periods") or [])[:8],
                "raster_clip_levels": artifact.get("raster_clip_levels") or [],
            }
        )

    return {
        "session_id": manifest.get("session_id"),
        "mode": manifest.get("mode"),
        "artifact_count": manifest.get("artifact_count"),
        "artifacts": artifacts,
        "saved_corpus": compact_saved,
    }


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
                "metrics": (artifact.get("metrics") or [])[:8],
            }
            for artifact in artifacts[:12]
        ]
        compact["artifact_count"] = len(artifacts)
        return compact

    if tool_name == "describe_artifact":
        artifact = tool_result.get("artifact") or {}
        compact["artifact"] = {
            "artifact_id": artifact.get("artifact_id"),
            "source_id": artifact.get("source_id"),
            "source_name": artifact.get("source_name"),
            "data_type": artifact.get("data_type"),
            "geographic_level": artifact.get("geographic_level"),
            "metrics": (artifact.get("metrics") or [])[:12],
            "fields": (artifact.get("fields") or [])[:20],
            "year_range": artifact.get("year_range"),
            "feature_count": artifact.get("feature_count"),
            "row_count": artifact.get("row_count"),
            "summary": artifact.get("summary"),
            "scene_periods": (artifact.get("scene_periods") or [])[:8],
            "raster_clip_levels": artifact.get("raster_clip_levels") or [],
        }
        return compact

    if tool_name in {"query_artifact_slice", "build_artifact_display_subset"}:
        rows = tool_result.get("rows") or []
        compact["rows_preview"] = rows[:15]
        compact["preview_count"] = min(len(rows), 15)
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
    messages = [
        {
            "role": "user",
            "content": "Active corpus manifest:\n```json\n" + json.dumps(prompt_manifest, indent=2, default=str) + "\n```",
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
    max_tool_iterations = 4
    response = None
    final_display = None
    display_warning = None
    for _iteration in range(max_tool_iterations + 1):
        try:
            response = client.messages.create(
                model=model,
                system=system_prompt,
                messages=messages,
                tools=RESEARCH_TOOL_DEFINITIONS,
                temperature=temperature,
                max_tokens=1400,
            )
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

    if progress is not None:
        progress(ProgressEvent(
            stage="writing",
            message="Drafting the answer...",
            extra={"phase": "compose"},
        ))

    text = _extract_text(response.content if response else [])
    if not text:
        text = _fallback_display_message(final_display) or "I could not produce a research answer from the active corpus."
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
        return msgpack_response({
            "type": "saved_corpus_loaded",
            "message": f'Loaded "{saved_corpus.get("name")}" into the Research workspace.',
            "corpus": manifest,
            "hydration": hydration,
            "focus_geojson": focus_geojson,
        })
    except Exception as e:
        logger.exception("Research saved corpus load error")
        return msgpack_error(str(e), 500)


@router.post("/api/research/browser-save/build")
async def research_build_browser_save_endpoint(req: Request):
    """Build a browser-save snapshot for a saved corpus."""
    try:
        body = await _decode_json_or_msgpack_request(req)
        corpus_id = str(body.get("corpusId") or "").strip()
        if not corpus_id:
            return JSONResponse({"ok": False, "error": "No corpusId provided"}, status_code=400)

        auth_user = await get_authenticated_user_async(req)
        user_id = (auth_user or {}).get("id")
        if not user_id:
            return JSONResponse({"ok": False, "error": "Authentication required"}, status_code=401)

        frontend_session_id = str(body.get("sessionId") or f"browser-save:{corpus_id}").strip() or f"browser-save:{corpus_id}"
        session_id = build_session_cache_key(frontend_session_id, auth_user)
        saved_corpus = _load_saved_corpus_for_user(user_id, corpus_id)
        if not saved_corpus:
            return JSONResponse({"ok": False, "error": "Saved corpus not found"}, status_code=404)

        current_saved = corpus_registry.get_saved_corpus(session_id)
        current_corpus_id = str((current_saved or {}).get("id") or "").strip()
        current_artifacts = corpus_registry.list_artifacts(session_id)
        if (
            current_corpus_id != corpus_id
            or not current_artifacts
            or not _artifacts_match_saved_corpus(current_artifacts, saved_corpus)
        ):
            corpus_registry.set_saved_corpus(session_id, saved_corpus)
            _hydrate_saved_corpus(session_id, saved_corpus)

        manifest = _annotate_manifest_saved_corpus_state(corpus_registry.manifest(session_id))
        snapshot = _build_browser_corpus_snapshot(session_id, saved_corpus)
        return JSONResponse({
            "ok": True,
            "snapshot": snapshot,
            "corpus": manifest,
        })
    except Exception as exc:
        logger.exception("Research browser-save build error")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@router.post("/api/research/browser-save/load")
async def research_load_browser_save_endpoint(req: Request):
    """Restore a browser-saved research corpus snapshot into the active session."""
    try:
        body = await _decode_json_or_msgpack_request(req)
        snapshot = body.get("snapshot")
        if not isinstance(snapshot, dict):
            return JSONResponse({"ok": False, "error": "No snapshot provided"}, status_code=400)

        frontend_session_id = str(body.get("sessionId") or "anonymous").strip() or "anonymous"
        auth_user = await get_authenticated_user_async(req)
        user_id = (auth_user or {}).get("id")
        if not user_id:
            return JSONResponse({"ok": False, "error": "Authentication required"}, status_code=401)
        session_id = build_session_cache_key(frontend_session_id, auth_user)
        snapshot_saved = snapshot.get("saved_corpus") or {}
        corpus_id = str(snapshot_saved.get("id") or "").strip()
        expected_saved_corpus = _load_saved_corpus_for_user(user_id, corpus_id) if corpus_id else None
        manifest = _annotate_manifest_saved_corpus_state(_restore_browser_corpus_snapshot(
            session_id,
            snapshot,
            expected_saved_corpus=expected_saved_corpus,
        ))
        saved_name = ((manifest.get("saved_corpus") or {}).get("name") or "Saved corpus")
        focus_geojson = _build_research_focus_geojson(session_id)
        return JSONResponse({
            "ok": True,
            "message": f'Loaded "{saved_name}" from browser storage into the Research workspace.',
            "corpus": manifest,
            "focus_geojson": focus_geojson,
        })
    except Exception as exc:
        logger.exception("Research browser-save load error")
        status_code = 409 if "out of date" in str(exc).lower() else 500
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=status_code)


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
        # Run the synchronous LLM-driven research pipeline in a thread so we
        # do not block the event loop. Mirrors the streaming endpoint below.
        result = await asyncio.to_thread(
            run_research_chat,
            session_id=session_id,
            query=query,
            chat_history=body.get("chatHistory", []),
            research_memory=body.get("researchMemory"),
            force_large_display=bool(body.get("force_research_display")),
        )
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
            ))
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
