"""Lane-owned Ops orchestrator runtime helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path

from mapmover.runtime.orchestrator_threading import run_catalog_scoped_to_thread

try:
    import boto3
except ImportError:
    boto3 = None


PRIVATE_ROOT = Path(__file__).resolve().parents[2] / "county-map-private"
OPS_STATE_ROOT = PRIVATE_ROOT / "live" / "state"


def _history_messages(chat_history: list | None, limit: int = 8) -> list[dict]:
    out: list[dict] = []
    for msg in (chat_history or [])[-limit:]:
        role = str((msg or {}).get("role") or "user").strip().lower()
        content = str((msg or {}).get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        out.append({"role": role, "content": content})
    return out


def _extract_text(response) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(part.strip() for part in parts if str(part).strip()).strip()


def _object_store_bucket() -> str:
    return str(os.environ.get("S3_BUCKET", "") or "").strip()


def _live_state_prefix() -> str:
    configured = str(os.environ.get("S3_LIVE_STATE_PREFIX", "") or "").strip().strip("/")
    if configured:
        return configured
    published_prefix = (
        str(os.environ.get("S3_PUBLISHED_PREFIX", "") or "").strip()
        or str(os.environ.get("S3_PREFIX", "") or "").strip()
        or "published"
    )
    published_prefix = published_prefix.strip("/")
    return f"{published_prefix}/live_state/collectors" if published_prefix else "live_state/collectors"


def _build_object_store_client():
    if boto3 is None or not _object_store_bucket():
        return None
    endpoint_url = str(os.environ.get("S3_ENDPOINT_URL", "") or "").strip() or None
    region = (
        str(os.environ.get("AWS_DEFAULT_REGION", "") or "").strip()
        or str(os.environ.get("AWS_REGION", "") or "").strip()
        or "auto"
    )
    return boto3.client("s3", endpoint_url=endpoint_url, region_name=region)


def _read_json_object(relative_key: str) -> dict | None:
    client = _build_object_store_client()
    if client is None:
        return None
    key = f"{_live_state_prefix()}/{relative_key}".strip("/")
    try:
        response = client.get_object(Bucket=_object_store_bucket(), Key=key)
        payload = json.loads(response["Body"].read().decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _read_jsonl_object(relative_key: str) -> list[dict]:
    client = _build_object_store_client()
    if client is None:
        return []
    key = f"{_live_state_prefix()}/{relative_key}".strip("/")
    try:
        response = client.get_object(Bucket=_object_store_bucket(), Key=key)
        raw = response["Body"].read().decode("utf-8")
    except Exception:
        return []
    entries: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def load_current_state_snapshot(collector_name: str) -> dict | None:
    collector = str(collector_name or "").strip()
    if not collector:
        return None
    snapshot_path = OPS_STATE_ROOT / collector / "snapshot.json"
    if snapshot_path.exists():
        try:
            return json.loads(snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return _read_json_object(f"{collector}/snapshot.json")


def load_current_state_history(collector_name: str, limit: int | None = None) -> list[dict]:
    collector = str(collector_name or "").strip()
    if not collector:
        return []
    history_path = OPS_STATE_ROOT / collector / "history.jsonl"
    entries: list[dict] = []
    if history_path.exists():
        try:
            with open(history_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            entries = []
    else:
        entries = _read_jsonl_object(f"{collector}/history.jsonl")
    if limit is not None and limit >= 0:
        return entries[-limit:]
    return entries


def _snapshot_to_geojson(snapshot: dict) -> dict | None:
    if not isinstance(snapshot, dict):
        return None
    collector = str(snapshot.get("collector") or "").strip()
    summary = snapshot.get("payload_summary") if isinstance(snapshot.get("payload_summary"), dict) else {}
    if collector != "earthquakes":
        return None
    events = summary.get("events") or []
    features = []
    for event in events:
        try:
            lon = float(event.get("longitude"))
            lat = float(event.get("latitude"))
        except (TypeError, ValueError):
            continue
        props = {
            "event_id": event.get("event_id"),
            "timestamp": event.get("timestamp"),
            "magnitude": event.get("magnitude"),
            "depth_km": event.get("depth_km"),
            "place": event.get("place"),
            "source": event.get("source"),
            "collector": collector,
        }
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })
    if not features:
        return None
    return {"type": "FeatureCollection", "features": features}


def build_ops_report(*, watch: dict, effective_feeds: list[str]) -> dict:
    snapshots = []
    geojson = None
    snapshot_hashes = {}
    for feed in effective_feeds:
        snapshot = load_current_state_snapshot(feed)
        if snapshot:
            snapshots.append(snapshot)
            payload_hash = str(snapshot.get("payload_hash") or "").strip()
            if payload_hash:
                snapshot_hashes[feed] = payload_hash
            if geojson is None:
                geojson = _snapshot_to_geojson(snapshot)
        else:
            snapshots.append({
                "collector": feed,
                "collector_status": "missing",
                "payload_summary": {},
                "schema_version": 1,
            })
    return {
        "watch": watch,
        "effective_feeds": effective_feeds,
        "snapshot_count": len(snapshots),
        "snapshot_hashes": snapshot_hashes,
        "snapshots": snapshots,
        "geojson": geojson,
    }


def run_ops_chat(
    *,
    query: str,
    chat_history: list | None,
    watch: dict,
    effective_feeds: list[str],
    ops_orchestrator,
    usage_recorder,
    cache,
) -> dict:
    if not effective_feeds:
        return {
            "type": "chat",
            "message": "Ops has no active feeds in this watch yet.",
            "watch_id": watch.get("watch_id"),
            "watch_context": watch,
            "effective_feeds": [],
        }

    report = build_ops_report(watch=watch, effective_feeds=effective_feeds)
    if isinstance(getattr(cache, "map_state", None), dict):
        cache.map_state["ops_report"] = report

    preloaded = ops_orchestrator.preprocess(query=query, watch_context={
        "label": watch.get("label"),
        "sources": effective_feeds,
        "geography": watch.get("geography"),
    })
    hints = preloaded.get("hints") if isinstance(preloaded, dict) else {}
    watch_context = preloaded.get("watch_context") if isinstance(preloaded, dict) else {}
    system_prompt = ops_orchestrator.build_system_prompt(watch_context=watch_context, hints=hints)
    system_blocks = ops_orchestrator.build_system_prompt_blocks(system_prompt)
    llm_selection = ops_orchestrator.llm_selection()
    client = ops_orchestrator.build_client(llm_selection)

    messages = [
        {
            "role": "user",
            "content": [{
                "type": "text",
                "text": "Active Ops watch JSON:\n" + json.dumps(watch_context, default=str, separators=(",", ":")),
                "cache_control": {"type": "ephemeral"},
            }],
        },
        {
            "role": "user",
            "content": [{
                "type": "text",
                "text": "Current Ops report JSON:\n" + json.dumps(report, default=str, separators=(",", ":")),
                "cache_control": {"type": "ephemeral"},
            }],
        },
        *_history_messages(chat_history),
        {"role": "user", "content": query},
    ]

    response = client.messages.create(
        model=llm_selection.model,
        system=system_blocks,
        messages=messages,
        temperature=llm_selection.temperature,
        max_tokens=700,
    )
    if usage_recorder is not None:
        usage_recorder.record(response)
    message = _extract_text(response) or "Ops report loaded, but I could not produce a fuller answer yet."
    summary = f"Ops watch: {watch.get('label') or 'Watch'} | feeds: {', '.join(effective_feeds)}"
    result = {
        "type": "chat",
        "message": message,
        "summary": summary,
        "watch_id": watch.get("watch_id"),
        "watch_context": watch_context,
        "effective_feeds": effective_feeds,
        "ops_report": report,
    }
    if report.get("geojson"):
        result["geojson"] = report["geojson"]
    return result


async def run_ops_orchestrator_call(
    *,
    query: str,
    chat_history: list | None,
    watch: dict,
    effective_feeds: list[str],
    usage_recorder,
    catalog_surface: str | None,
    ops_orchestrator,
    cache,
) -> dict:
    return await run_catalog_scoped_to_thread(
        catalog_surface=catalog_surface,
        func=run_ops_chat,
        query=query,
        chat_history=chat_history,
        watch=watch,
        effective_feeds=effective_feeds,
        ops_orchestrator=ops_orchestrator,
        usage_recorder=usage_recorder,
        cache=cache,
    )
