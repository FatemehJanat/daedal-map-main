"""Ops announcement ticker.

Aggregates the live "announcement" feeds (currently space weather: NOAA SWPC
alerts + OVATION aurora) into a compact list of ticker items for the scrolling
announcement bar. Reads the same current_state snapshots the live collectors
publish:

- cloud:  R2 published/live_state/collectors/<name>/snapshot.json
- local:  county-map-private/live/state/<name>/snapshot.json

This is read-only and best-effort: any feed that is missing or malformed is
skipped, so the ticker degrades to fewer items rather than erroring.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from datetime import datetime, timezone

from mapmover import logger

# Announcement feeds, in display priority order. Extend as more live_only /
# forecast announcement feeds ship.
ANNOUNCEMENT_FEEDS = ("noaa_swpc", "noaa_aurora")
MAX_ITEMS_PER_FEED = 8
_SNAPSHOT_CACHE_TTL_SECONDS = 15.0
_TICKER_CACHE_TTL_SECONDS = 30.0
_AURORA_CACHE_TTL_SECONDS = 60.0
_CACHE_LOCK = threading.Lock()
_SNAPSHOT_CACHE: dict[str, dict] = {}
_VIEW_CACHE: dict[str, dict] = {}


def read_live_snapshot(collector: str) -> dict | None:
    """Read one collector's current_state snapshot (cloud R2, then local dev)."""
    try:
        from mapmover.duckdb_helpers import is_cloud_mode
        if is_cloud_mode():
            from mapmover.data_loading import _fetch_json_from_s3
            data = _fetch_json_from_s3(f"live_state/collectors/{collector}/snapshot.json")
            return data if isinstance(data, dict) else None
    except Exception as exc:
        # A missing snapshot (collector not publishing yet) is normal; keep it
        # at debug so the ticker poll does not spam warnings every cycle.
        logger.debug("ticker: cloud snapshot read failed for %s: %s", collector, exc)

    # Local dev fallback: the collectors write under county-map-private/live/state.
    try:
        root = os.environ.get("GLOBAL_MAP_ROOT")
        base = Path(root) if root else Path(__file__).resolve().parents[2]
        path = base / "county-map-private" / "live" / "state" / collector / "snapshot.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("ticker: local snapshot read failed for %s: %s", collector, exc)
    return None


def _parse_issued_timestamp(value: object) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _snapshot_identity(snapshot: dict | None) -> tuple[str, str, str, str]:
    snap = snapshot if isinstance(snapshot, dict) else {}
    return (
        str(snap.get("payload_hash") or "").strip(),
        str(snap.get("fetched_at") or "").strip(),
        str(snap.get("upstream_issued_at") or "").strip(),
        str(snap.get("collector_status") or "").strip(),
    )


def get_cached_live_snapshot(collector: str, *, ttl_seconds: float = _SNAPSHOT_CACHE_TTL_SECONDS) -> dict | None:
    """Return a short-lived cached snapshot so many clients do not re-read R2."""
    now = time.time()
    with _CACHE_LOCK:
        entry = _SNAPSHOT_CACHE.get(collector)
        if entry is not None and (now - float(entry.get("cached_at") or 0.0)) < ttl_seconds:
            return entry.get("snapshot")
    snapshot = read_live_snapshot(collector)
    with _CACHE_LOCK:
        _SNAPSHOT_CACHE[collector] = {
            "cached_at": now,
            "snapshot": snapshot,
        }
    return snapshot


def _get_cached_view(
    cache_key: str,
    *,
    cache_identity: tuple,
    ttl_seconds: float,
    builder,
):
    now = time.time()
    with _CACHE_LOCK:
        entry = _VIEW_CACHE.get(cache_key)
        if (
            entry is not None
            and entry.get("identity") == cache_identity
            and (now - float(entry.get("cached_at") or 0.0)) < ttl_seconds
        ):
            return entry.get("payload")
    payload = builder()
    with _CACHE_LOCK:
        _VIEW_CACHE[cache_key] = {
            "cached_at": now,
            "identity": cache_identity,
            "payload": payload,
        }
    return payload


def _swpc_severity(alert_type: str | None, scale: str | None) -> str:
    s = (scale or "").upper()
    if s[:2] in ("G4", "G5", "S4", "S5", "R4", "R5"):
        return "severe"
    t = (alert_type or "").upper()
    if "WARNING" in t:
        return "warning"
    if "WATCH" in t:
        return "watch"
    if "ALERT" in t:
        return "alert"
    return "info"


def _humanize_swpc_text(alert: dict) -> str:
    summary = str(alert.get("summary") or "").strip()
    if summary:
        return " ".join(summary.split())

    alert_type = str(alert.get("alert_type") or "").strip().title()
    scale = str(alert.get("noaa_scale") or "").strip().upper()
    if alert_type and scale:
        return f"{alert_type} {scale}"
    if alert_type:
        return alert_type
    if scale:
        return f"Space weather {scale}"
    return "Space weather update"


def _items_from_swpc(snap: dict) -> list[dict]:
    summary = snap.get("payload_summary") or {}
    items: list[dict] = []
    for alert in (summary.get("alerts") or [])[:MAX_ITEMS_PER_FEED]:
        text = _humanize_swpc_text(alert)
        if not text:
            continue
        items.append({
            "id": alert.get("alert_id"),
            "source": "Space Weather",
            "text": text,
            "scale": alert.get("noaa_scale") or "",
            "severity": _swpc_severity(alert.get("alert_type"), alert.get("noaa_scale")),
            "issued": alert.get("issued_utc"),
        })
    return items


def _items_from_aurora(snap: dict) -> list[dict]:
    summary = snap.get("payload_summary") or {}
    if not summary.get("aurora_visible"):
        return []
    north = summary.get("north_boundary_lat")
    south = summary.get("south_boundary_lat")
    max_prob = summary.get("max_probability")
    where = []
    if north is not None:
        where.append(f"{abs(int(north))}N")
    if south is not None:
        where.append(f"{abs(int(south))}S")
    where_txt = " / ".join(where) if where else "high latitudes"
    return [{
        "id": "aurora",
        "source": "Aurora",
        "text": f"Aurora visible as far as {where_txt}. Peak intensity {max_prob}%.",
        "scale": "",
        "severity": "warning" if (max_prob or 0) >= 50 else "info",
        "issued": summary.get("forecast_time"),
    }]


_FEED_BUILDERS = {
    "noaa_swpc": _items_from_swpc,
    "noaa_aurora": _items_from_aurora,
}


def build_ticker_items(feeds: tuple[str, ...] = ANNOUNCEMENT_FEEDS) -> list[dict]:
    """Return ticker items aggregated across the announcement feeds, newest first."""
    items: list[dict] = []
    for feed in feeds:
        snap = get_cached_live_snapshot(feed)
        if not snap:
            continue
        builder = _FEED_BUILDERS.get(feed)
        if not builder:
            continue
        try:
            items.extend(builder(snap))
        except Exception as exc:
            logger.warning("ticker: builder failed for %s: %s", feed, exc)
    items.sort(key=lambda it: _parse_issued_timestamp(it.get("issued")), reverse=True)
    return items


def build_cached_ticker_payload(feeds: tuple[str, ...] = ANNOUNCEMENT_FEEDS) -> dict:
    """Small response cache over the announcement ticker view."""
    snapshots: dict[str, dict] = {}
    identities: list[tuple] = []
    for feed in feeds:
        snap = get_cached_live_snapshot(feed)
        snapshots[feed] = snap if isinstance(snap, dict) else {}
        identities.append((feed, _snapshot_identity(snap)))

    def _builder() -> dict:
        items: list[dict] = []
        for feed in feeds:
            snap = snapshots.get(feed) or {}
            builder = _FEED_BUILDERS.get(feed)
            if not builder or not snap:
                continue
            try:
                items.extend(builder(snap))
            except Exception as exc:
                logger.warning("ticker: builder failed for %s: %s", feed, exc)
        items.sort(key=lambda it: _parse_issued_timestamp(it.get("issued")), reverse=True)
        return {"type": "ops_ticker", "items": items, "count": len(items)}

    return _get_cached_view(
        "ops_ticker",
        cache_identity=tuple(identities),
        ttl_seconds=_TICKER_CACHE_TTL_SECONDS,
        builder=_builder,
    )


def build_cached_aurora_payload() -> dict:
    """Small response cache over the current aurora overlay view."""
    snap = get_cached_live_snapshot("noaa_aurora")
    snapshot = snap if isinstance(snap, dict) else {}
    summary = snapshot.get("payload_summary") or {}

    def _builder() -> dict:
        return {
            "type": "aurora",
            "observation_time": summary.get("observation_time"),
            "forecast_time": summary.get("forecast_time"),
            "max_probability": summary.get("max_probability"),
            "cells": summary.get("cells") or [],
        }

    return _get_cached_view(
        "ops_aurora",
        cache_identity=_snapshot_identity(snapshot),
        ttl_seconds=_AURORA_CACHE_TTL_SECONDS,
        builder=_builder,
    )
