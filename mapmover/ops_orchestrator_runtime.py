"""Lane-owned Ops orchestrator runtime helpers."""

from __future__ import annotations

import csv
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from mapmover.geometry_handlers import get_selection_geometries

try:
    import boto3
except ImportError:
    boto3 = None

try:
    import requests
except ImportError:
    requests = None


PRIVATE_ROOT = Path(__file__).resolve().parents[2] / "county-map-private"
OPS_STATE_ROOT = PRIVATE_ROOT / "live" / "state"
REFERENCE_ROOT = Path(__file__).resolve().parent / "reference"
CURRENCY_MAP_PATH = REFERENCE_ROOT / "country_currency_map.csv"
LIVE_STATE_SNAPSHOT_TTL_SECONDS = 60.0
LIVE_STATE_HISTORY_TTL_SECONDS = 60.0
_LIVE_STATE_CACHE: dict[tuple[str, str], tuple[float, object]] = {}
_LIVE_STATE_CACHE_LOCK = threading.Lock()
_LIVE_STATE_STATUS: dict[tuple[str, str], str] = {}
_LIVE_STATE_STATUS_LOCK = threading.Lock()

FEED_ALIASES = {
    "earthquakes": ("earthquake", "earthquakes", "quake", "quakes", "seismic"),
    "currency": ("currency", "currencies", "fx", "exchange rate", "exchange rates", "usd"),
    "tsunamis": ("tsunami", "tsunamis", "runup", "runups"),
    "volcanoes": ("volcano", "volcanoes", "eruption", "eruptions", "vei"),
    "wildfires_us_nifc": ("wildfire", "wildfires", "fire", "fires", "nifc"),
    "hurricanes_ibtracs_nrt": ("hurricane", "hurricanes", "storm", "storms", "cyclone", "typhoon", "ibtracs"),
    "usa_nws_alerts": ("nws", "nws alerts", "weather alert", "weather alerts", "warning", "warnings", "alert", "alerts"),
    "noaa_swpc": ("space weather", "space weather alerts", "geomagnetic", "solar storm", "radio blackout"),
    "noaa_aurora": ("aurora", "aurora forecast", "northern lights"),
}

COUNT_QUERY_PATTERNS = (
    r"\bhow many\b",
    r"\bnumber of\b",
    r"\bcount of\b",
    r"\bcount\b",
)

MAP_FOCUS_PATTERNS = (
    r"\bshow me\b",
    r"\bshow them\b",
    r"\bshow those\b",
    r"\bshow it\b",
    r"\btake me to\b",
    r"\bzoom to\b",
    r"\bgo to\b",
    r"\bmap them\b",
    r"\bmap those\b",
    r"\bmap it\b",
    r"\bput them on the map\b",
    r"\bput those on the map\b",
    r"\blocate\b",
    r"\bwhere is\b",
)

SUPERLATIVE_PATTERNS = (
    r"\bbiggest\b",
    r"\blargest\b",
    r"\bworst\b",
    r"\bstrongest\b",
    r"\bhighest\b",
    r"\bmost severe\b",
)

FEED_FOCUS_SPECS = {
    "wildfires_us_nifc": {
        "metric_keys": ("burned_acres", "area_km2"),
        "label": "wildfire",
        "id_keys": ("event_id", "incident_id", "fire_name"),
    },
    "earthquakes": {
        "metric_keys": ("magnitude",),
        "label": "earthquake",
        "id_keys": ("event_id",),
    },
    "tsunamis": {
        "metric_keys": ("max_water_height_m", "runup_m", "eq_magnitude"),
        "label": "tsunami event",
        "id_keys": ("event_id",),
    },
    "volcanoes": {
        "metric_keys": ("VEI", "vei"),
        "label": "volcano event",
        "id_keys": ("event_id", "volcano_name"),
    },
    "hurricanes_ibtracs_nrt": {
        "metric_keys": ("max_category", "category", "max_wind_kt"),
        "label": "storm",
        "id_keys": ("storm_id", "name"),
    },
}

DEEP_HISTORY_PATTERNS = (
    r"\bchange\b",
    r"\bchanged\b",
    r"\bchanges\b",
    r"\bhistory\b",
    r"\bhistorical\b",
    r"\btrend\b",
    r"\btrends\b",
    r"\btimeline\b",
    r"\bsince\b",
    r"\bprevious\b",
    r"\bearlier\b",
    r"\bbefore\b",
    r"\bhow has\b",
    r"\bwhat changed\b",
    r"\blast\s+\d+",
    r"\bpast\s+\d+",
    r"\btoday\b",
    r"\byesterday\b",
    r"\bintensif",
    r"\bworsen",
    r"\bimprov",
    r"\bgrow",
    r"\bgrew\b",
    r"\bdecrease\b",
    r"\bincrease\b",
)


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


def _site_live_state_base_url() -> str:
    value = (
        str(os.environ.get("SITE_URL", "") or "").strip()
        or str(os.environ.get("CLOUD_URL", "") or "").strip()
    ).rstrip("/")
    return value


def _live_state_cache_ttl(kind: str) -> float:
    if kind == "history":
        return LIVE_STATE_HISTORY_TTL_SECONDS
    return LIVE_STATE_SNAPSHOT_TTL_SECONDS


def _get_live_state_cache(collector: str, kind: str) -> object | None:
    key = (collector, kind)
    now = time.monotonic()
    with _LIVE_STATE_CACHE_LOCK:
        record = _LIVE_STATE_CACHE.get(key)
        if not record:
            return None
        cached_at, payload = record
        if now - cached_at > _live_state_cache_ttl(kind):
            _LIVE_STATE_CACHE.pop(key, None)
            return None
        return payload


def _set_live_state_cache(collector: str, kind: str, payload: object) -> None:
    key = (collector, kind)
    with _LIVE_STATE_CACHE_LOCK:
        _LIVE_STATE_CACHE[key] = (time.monotonic(), payload)


def _set_live_state_status(collector: str, kind: str, status: str) -> None:
    key = (collector, kind)
    with _LIVE_STATE_STATUS_LOCK:
        _LIVE_STATE_STATUS[key] = status


def _get_live_state_status(collector: str, kind: str) -> str:
    key = (collector, kind)
    with _LIVE_STATE_STATUS_LOCK:
        return str(_LIVE_STATE_STATUS.get(key) or "").strip()


def _cloud_live_state_expected() -> bool:
    return bool(_object_store_bucket() and str(os.environ.get("AWS_ACCESS_KEY_ID", "") or "").strip() and str(os.environ.get("AWS_SECRET_ACCESS_KEY", "") or "").strip())


def _fetch_live_state_via_site(collector_name: str, kind: str) -> dict | list | None:
    if requests is None:
        return None
    base_url = _site_live_state_base_url()
    collector = str(collector_name or "").strip()
    if not base_url or not collector or kind not in {"snapshot", "history"}:
        return None
    try:
        response = requests.get(
            f"{base_url}/api/internal/live-state/{collector}/{kind}",
            timeout=4,
        )
        if response.status_code >= 300:
            return None
        payload = response.json()
    except Exception:
        return None
    if kind == "snapshot":
        return payload if isinstance(payload, dict) else None
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return None


def load_current_state_snapshot(collector_name: str) -> dict | None:
    collector = str(collector_name or "").strip()
    if not collector:
        return None
    cached = _get_live_state_cache(collector, "snapshot")
    if isinstance(cached, dict):
        _set_live_state_status(collector, "snapshot", "cache")
        return cached
    snapshot = _read_json_object(f"{collector}/snapshot.json")
    if isinstance(snapshot, dict):
        _set_live_state_cache(collector, "snapshot", snapshot)
        _set_live_state_status(collector, "snapshot", "cloud")
        return snapshot
    snapshot = _fetch_live_state_via_site(collector, "snapshot")
    if isinstance(snapshot, dict):
        _set_live_state_cache(collector, "snapshot", snapshot)
        _set_live_state_status(collector, "snapshot", "site_fallback")
        return snapshot
    snapshot_path = OPS_STATE_ROOT / collector / "snapshot.json"
    if snapshot_path.exists():
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            if isinstance(snapshot, dict):
                _set_live_state_cache(collector, "snapshot", snapshot)
                _set_live_state_status(collector, "snapshot", "local_fallback")
                return snapshot
        except Exception:
            pass
    _set_live_state_status(
        collector,
        "snapshot",
        "cloud_unavailable" if _cloud_live_state_expected() else "cloud_not_configured",
    )
    return None


def load_current_state_history(collector_name: str, limit: int | None = None) -> list[dict]:
    collector = str(collector_name or "").strip()
    if not collector:
        return []
    cached = _get_live_state_cache(collector, "history")
    if isinstance(cached, list):
        _set_live_state_status(collector, "history", "cache")
        entries = cached
    else:
        entries = _read_jsonl_object(f"{collector}/history.jsonl")
        if isinstance(entries, list) and entries:
            _set_live_state_status(collector, "history", "cloud")
        else:
            entries = _fetch_live_state_via_site(collector, "history")
            if isinstance(entries, list) and entries:
                _set_live_state_status(collector, "history", "site_fallback")
    if not isinstance(entries, list) or not entries:
        history_path = OPS_STATE_ROOT / collector / "history.jsonl"
        local_entries: list[dict] = []
        if history_path.exists():
            try:
                with open(history_path, "r", encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            local_entries.append(json.loads(line))
                        except Exception:
                            continue
            except Exception:
                local_entries = []
        entries = local_entries
        if entries:
            _set_live_state_status(collector, "history", "local_fallback")
    if isinstance(entries, list) and entries:
        _set_live_state_cache(collector, "history", entries)
    else:
        _set_live_state_status(
            collector,
            "history",
            "cloud_unavailable" if _cloud_live_state_expected() else "cloud_not_configured",
        )
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
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": props,
            }
        )
    if not features:
        return None
    return {"type": "FeatureCollection", "features": features}


def _build_point_event_display_payload(
    snapshot: dict | None,
    *,
    collector: str,
    event_type: str,
    label: str,
) -> dict | None:
    if not isinstance(snapshot, dict):
        return None
    summary = snapshot.get("payload_summary") if isinstance(snapshot.get("payload_summary"), dict) else {}
    rows = summary.get("events") if isinstance(summary.get("events"), list) else None
    if not rows:
        return None

    features: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            lon = float(row.get("longitude"))
            lat = float(row.get("latitude"))
        except (TypeError, ValueError):
            continue
        props = dict(row)
        props.setdefault("collector", collector)
        if collector == "volcanoes":
            props.setdefault("VEI", row.get("vei"))
        if collector == "wildfires_us_nifc":
            acres = row.get("burned_acres")
            try:
                props.setdefault("area_km2", float(acres) * 0.00404686)
            except (TypeError, ValueError):
                pass
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": props,
            }
        )

    if not features:
        return None

    count = len(features)
    return {
        "type": "events",
        "data_type": "events",
        "event_type": event_type,
        "source_id": f"{collector}_live_ops",
        "snapshot_hash": snapshot.get("payload_hash"),
        "dataset_name": label,
        "source_name": label,
        "summary": f"Showing latest {label.lower()} snapshot ({count} items).",
        "count": count,
        "fit": False,
        "geojson": {
            "type": "FeatureCollection",
            "features": features,
        },
    }


def _build_hurricane_display_payload(snapshot: dict | None) -> dict | None:
    if not isinstance(snapshot, dict):
        return None
    summary = snapshot.get("payload_summary") if isinstance(snapshot.get("payload_summary"), dict) else {}
    storms = summary.get("storms") if isinstance(summary.get("storms"), list) else []
    positions = summary.get("positions") if isinstance(summary.get("positions"), list) else []
    if not storms or not positions:
        return None

    storm_lookup: dict[str, dict] = {}
    for storm in storms:
        if not isinstance(storm, dict):
            continue
        storm_id = str(storm.get("storm_id") or "").strip()
        if storm_id:
            storm_lookup[storm_id] = storm

    positions_by_storm: dict[str, list[dict]] = {}
    for row in positions:
        if not isinstance(row, dict):
            continue
        storm_id = str(row.get("storm_id") or "").strip()
        if not storm_id:
            continue
        try:
            lon = float(row.get("longitude"))
            lat = float(row.get("latitude"))
        except (TypeError, ValueError):
            continue
        normalized = dict(row)
        normalized["_lon"] = lon
        normalized["_lat"] = lat
        positions_by_storm.setdefault(storm_id, []).append(normalized)

    features: list[dict] = []
    for storm_id, rows in positions_by_storm.items():
        ordered = sorted(rows, key=lambda row: str(row.get("timestamp") or ""))
        coords = [[row["_lon"], row["_lat"]] for row in ordered]
        if len(coords) < 2:
            continue
        storm = storm_lookup.get(storm_id, {})
        props = {
            "storm_id": storm_id,
            "name": storm.get("name"),
            "year": storm.get("year"),
            "basin": storm.get("basin"),
            "nature": storm.get("nature"),
            "start_date": storm.get("start_date"),
            "end_date": storm.get("end_date"),
            "max_wind_kt": storm.get("max_wind_kt"),
            "max_category": storm.get("max_category"),
            "category": storm.get("max_category"),
            "num_positions": len(coords),
            "collector": "hurricanes_ibtracs_nrt",
        }
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": props,
            }
        )

    if not features:
        return None

    return {
        "type": "data",
        "data_type": "events",
        "source_id": "ibtracs_live_ops",
        "snapshot_hash": snapshot.get("payload_hash"),
        "dataset_name": "Ops Hurricane Snapshot",
        "source_name": "Live hurricane snapshot",
        "summary": f"Showing latest hurricane tracks for {len(features)} storms.",
        "count": len(features),
        "fit": False,
        "geojson": {
            "type": "FeatureCollection",
            "features": features,
        },
    }


def _sample_rows(rows: list[dict], fields: tuple[str, ...], limit: int) -> list[dict]:
    sampled: list[dict] = []
    for row in (rows or [])[:limit]:
        if not isinstance(row, dict):
            continue
        sampled.append({field: row.get(field) for field in fields if field in row})
    return sampled


@lru_cache(maxsize=1)
def _load_country_currency_map() -> list[dict]:
    rows: list[dict] = []
    if not CURRENCY_MAP_PATH.exists():
        return rows
    try:
        with open(CURRENCY_MAP_PATH, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if not isinstance(row, dict):
                    continue
                loc_id = str(row.get("loc_id") or "").strip()
                currency_code = str(row.get("currency_code") or "").strip().upper()
                if not loc_id or not currency_code:
                    continue
                rows.append(
                    {
                        "loc_id": loc_id,
                        "currency_code": currency_code,
                    }
                )
    except Exception:
        return []
    return rows


def _build_currency_display_payload(snapshot: dict | None) -> dict | None:
    if not isinstance(snapshot, dict):
        return None
    summary = snapshot.get("payload_summary") if isinstance(snapshot.get("payload_summary"), dict) else {}
    rates = summary.get("rates") if isinstance(summary.get("rates"), list) else []
    if not rates:
        return None

    latest_by_code: dict[str, dict] = {}
    for rate in rates:
        if not isinstance(rate, dict):
            continue
        code = str(rate.get("currency_code") or "").strip().upper()
        if not code:
            continue
        latest_by_code[code] = rate

    loc_ids: list[str] = []
    rows_by_loc_id: dict[str, dict] = {}
    for mapping in _load_country_currency_map():
        loc_id = str(mapping.get("loc_id") or "").strip()
        code = str(mapping.get("currency_code") or "").strip().upper()
        rate = latest_by_code.get(code)
        if not loc_id or rate is None:
            continue
        try:
            local_per_usd = float(rate.get("local_per_usd"))
        except (TypeError, ValueError):
            continue
        rows_by_loc_id[loc_id] = {
            "loc_id": loc_id,
            "local_per_usd": local_per_usd,
            "currency_code": code,
            "date": rate.get("date"),
            "source_id": rate.get("source_id"),
        }
        loc_ids.append(loc_id)

    if not rows_by_loc_id:
        return None

    selection_geojson = get_selection_geometries(loc_ids) or {}
    features = []
    year_bucket: dict[str, dict] = {}
    for feature in selection_geojson.get("features") or []:
        if not isinstance(feature, dict):
            continue
        props = dict(feature.get("properties") or {})
        loc_id = str(props.get("loc_id") or "").strip()
        row = rows_by_loc_id.get(loc_id)
        if row is None:
            continue
        metric_props = {
            **props,
            "local_per_usd": row.get("local_per_usd"),
            "currency_code": row.get("currency_code"),
            "date": row.get("date"),
            "source_id": row.get("source_id"),
        }
        features.append(
            {
                "type": "Feature",
                "geometry": feature.get("geometry"),
                "properties": metric_props,
            }
        )
        year_bucket[loc_id] = {
            "local_per_usd": row.get("local_per_usd"),
            "currency_code": row.get("currency_code"),
            "date": row.get("date"),
            "source_id": row.get("source_id"),
        }

    if not features:
        return None

    return {
        "type": "data",
        "data_type": "metrics",
        "source_id": "currency_live_ops",
        "snapshot_hash": snapshot.get("payload_hash"),
        "dataset_name": "Ops Currency Snapshot",
        "source_name": "Live currency snapshot",
        "geographic_level": "admin_0",
        "summary": f"Showing latest FX snapshot for {len(features)} countries.",
        "count": len(features),
        "fit": False,
        "metric_key": "local_per_usd",
        "available_metrics": ["local_per_usd"],
        "loc_ids": sorted(year_bucket.keys()),
        "geojson": {
            "type": "FeatureCollection",
            "features": features,
        },
    }


def _build_display_payloads(snapshots_by_feed: dict[str, dict]) -> list[dict]:
    payloads: list[dict] = []
    earthquakes_payload = _build_point_event_display_payload(
        snapshots_by_feed.get("earthquakes"),
        collector="earthquakes",
        event_type="earthquake",
        label="Ops Earthquake Snapshot",
    )
    if earthquakes_payload:
        payloads.append(earthquakes_payload)
    tsunami_payload = _build_point_event_display_payload(
        snapshots_by_feed.get("tsunamis"),
        collector="tsunamis",
        event_type="tsunami",
        label="Ops Tsunami Snapshot",
    )
    if tsunami_payload:
        payloads.append(tsunami_payload)
    volcano_payload = _build_point_event_display_payload(
        snapshots_by_feed.get("volcanoes"),
        collector="volcanoes",
        event_type="volcano",
        label="Ops Volcano Snapshot",
    )
    if volcano_payload:
        payloads.append(volcano_payload)
    wildfire_payload = _build_point_event_display_payload(
        snapshots_by_feed.get("wildfires_us_nifc"),
        collector="wildfires_us_nifc",
        event_type="wildfire",
        label="Ops Wildfire Snapshot",
    )
    if wildfire_payload:
        payloads.append(wildfire_payload)
    hurricane_payload = _build_hurricane_display_payload(snapshots_by_feed.get("hurricanes_ibtracs_nrt"))
    if hurricane_payload:
        payloads.append(hurricane_payload)
    currency_payload = _build_currency_display_payload(snapshots_by_feed.get("currency"))
    if currency_payload:
        payloads.append(currency_payload)
    return payloads


def _build_ops_payload_for_feed(feed: str) -> dict | None:
    snapshot = load_current_state_snapshot(feed)
    if not isinstance(snapshot, dict):
        return None
    if feed == "earthquakes":
        return _build_point_event_display_payload(
            snapshot,
            collector="earthquakes",
            event_type="earthquake",
            label="Ops Earthquake Snapshot",
        )
    if feed == "tsunamis":
        return _build_point_event_display_payload(
            snapshot,
            collector="tsunamis",
            event_type="tsunami",
            label="Ops Tsunami Snapshot",
        )
    if feed == "volcanoes":
        return _build_point_event_display_payload(
            snapshot,
            collector="volcanoes",
            event_type="volcano",
            label="Ops Volcano Snapshot",
        )
    if feed == "wildfires_us_nifc":
        return _build_point_event_display_payload(
            snapshot,
            collector="wildfires_us_nifc",
            event_type="wildfire",
            label="Ops Wildfire Snapshot",
        )
    if feed == "hurricanes_ibtracs_nrt":
        return _build_hurricane_display_payload(snapshot)
    if feed == "currency":
        return _build_currency_display_payload(snapshot)
    return None


def _compact_payload_summary(collector: str, summary: dict, *, sample_limit: int = 3) -> dict:
    if not isinstance(summary, dict):
        return {}

    if collector == "earthquakes":
        return {
            "event_count": summary.get("event_count"),
            "max_magnitude": summary.get("max_magnitude"),
            "top_events": _sample_rows(
                summary.get("events") or [],
                ("event_id", "timestamp", "place", "magnitude", "depth_km"),
                sample_limit,
            ),
        }
    if collector == "currency":
        priority = {"USD": 0, "EUR": 1, "JPY": 2, "GBP": 3, "CNY": 4, "CAD": 5}
        rates = sorted(
            [row for row in (summary.get("rates") or []) if isinstance(row, dict)],
            key=lambda row: (priority.get(str(row.get("currency_code") or "").upper(), 99), str(row.get("currency_code") or "")),
        )
        return {
            "rate_count": summary.get("rate_count"),
            "base_currency": summary.get("base_currency"),
            "latest_snapshot_date": summary.get("latest_snapshot_date"),
            "sample_rates": _sample_rows(
                rates,
                ("currency_code", "date", "local_per_usd", "source_id"),
                max(sample_limit, 5),
            ),
        }
    if collector == "tsunamis":
        return {
            "event_count": summary.get("event_count"),
            "runup_count": summary.get("runup_count"),
            "top_events": _sample_rows(
                summary.get("events") or [],
                ("event_id", "timestamp", "country", "location", "cause", "eq_magnitude", "max_water_height_m"),
                sample_limit,
            ),
        }
    if collector == "volcanoes":
        return {
            "event_count": summary.get("event_count"),
            "ongoing_count": summary.get("ongoing_count"),
            "top_events": _sample_rows(
                summary.get("events") or [],
                ("event_id", "timestamp", "volcano_name", "activity_type", "vei", "is_ongoing"),
                sample_limit,
            ),
        }
    if collector == "wildfires_us_nifc":
        return {
            "event_count": summary.get("event_count"),
            "incident_count": summary.get("incident_count"),
            "active_count": summary.get("active_count"),
            "max_burned_acres": summary.get("max_burned_acres"),
            "top_events": _sample_rows(
                summary.get("events") or [],
                ("event_id", "fire_name", "state", "county_name", "status", "burned_acres", "last_updated"),
                sample_limit,
            ),
        }
    if collector == "hurricanes_ibtracs_nrt":
        return {
            "storm_count": summary.get("storm_count"),
            "position_count": summary.get("position_count"),
            "top_storms": _sample_rows(
                summary.get("storms") or [],
                ("storm_id", "name", "year", "basin", "max_wind_kt", "max_category", "end_date"),
                sample_limit,
            ),
        }
    if collector == "noaa_swpc":
        return {
            "alert_count": summary.get("alert_count"),
            "active_scales": summary.get("active_scales"),
            "alerts": _sample_rows(
                summary.get("alerts") or [],
                ("alert_id", "issued_utc", "alert_type", "noaa_scale", "summary"),
                sample_limit,
            ),
        }
    if collector == "noaa_aurora":
        return {
            "forecast_time": summary.get("forecast_time"),
            "aurora_visible": summary.get("aurora_visible"),
            "max_probability": summary.get("max_probability"),
            "visible_cell_count": summary.get("visible_cell_count"),
            "strong_cell_count": summary.get("strong_cell_count"),
            "north_boundary_lat": summary.get("north_boundary_lat"),
            "south_boundary_lat": summary.get("south_boundary_lat"),
        }
    compact: dict = {}
    for key in ("event_count", "incident_count", "storm_count", "position_count", "rate_count", "alert_count"):
        if key in summary:
            compact[key] = summary.get(key)
    if not compact:
        compact["keys"] = sorted(summary.keys())[:12]
    return compact


def _compact_feed_snapshot(feed: str, snapshot: dict | None, history_entries: list[dict]) -> dict:
    if not isinstance(snapshot, dict):
        snapshot_status = _get_live_state_status(feed, "snapshot")
        history_status = _get_live_state_status(feed, "history")
        return {
            "feed": feed,
            "collector_status": snapshot_status or "missing",
            "history_entry_count": len(history_entries),
            "history_available": bool(history_entries),
            "live_state_status": {
                "snapshot": snapshot_status or "missing",
                "history": history_status or "missing",
            },
            "summary": {},
        }
    summary = snapshot.get("payload_summary") if isinstance(snapshot.get("payload_summary"), dict) else {}
    return {
        "feed": feed,
        "collector_status": snapshot.get("collector_status"),
        "fetched_at": snapshot.get("fetched_at"),
        "last_checked_at": snapshot.get("last_checked_at"),
        "last_changed_at": snapshot.get("last_changed_at"),
        "expected_next_at": snapshot.get("expected_next_at"),
        "payload_hash": snapshot.get("payload_hash"),
        "previous_payload_hash": snapshot.get("previous_payload_hash"),
        "changed_since_previous": snapshot.get("changed_since_previous"),
        "history_entry_count": len(history_entries),
        "history_available": bool(history_entries),
        "live_state_status": {
            "snapshot": _get_live_state_status(feed, "snapshot") or "unknown",
            "history": _get_live_state_status(feed, "history") or "unknown",
        },
        "summary": _compact_payload_summary(feed, summary),
    }


def _build_recent_change_entry(feed: str, snapshot: dict | None, history_entries: list[dict]) -> dict | None:
    if not isinstance(snapshot, dict):
        return None
    if not history_entries and not snapshot.get("last_changed_at"):
        return None
    latest_history = history_entries[-1] if history_entries else {}
    latest_summary = latest_history.get("payload_summary") if isinstance(latest_history, dict) else {}
    return {
        "feed": feed,
        "collector_status": snapshot.get("collector_status"),
        "last_changed_at": snapshot.get("last_changed_at"),
        "payload_hash": snapshot.get("payload_hash"),
        "previous_payload_hash": snapshot.get("previous_payload_hash"),
        "history_entry_count": len(history_entries),
        "latest_change": _compact_payload_summary(feed, latest_summary, sample_limit=2),
    }


def _build_headline_summary(feed_snapshots: list[dict]) -> str:
    if not feed_snapshots:
        return "No Ops feeds are active in this watch."
    status_counts: dict[str, int] = {}
    for item in feed_snapshots:
        status = str(item.get("collector_status") or "unknown").strip() or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
    ordered_status = ", ".join(f"{status}:{count}" for status, count in sorted(status_counts.items()))
    notable_bits: list[str] = []
    for item in feed_snapshots[:3]:
        feed = str(item.get("feed") or "").strip()
        summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
        for key in ("event_count", "incident_count", "storm_count", "rate_count"):
            if key in summary and summary.get(key) is not None:
                notable_bits.append(f"{feed} {key}={summary.get(key)}")
                break
    if notable_bits:
        return f"Active Ops report with {len(feed_snapshots)} feeds ({ordered_status}). " + "; ".join(notable_bits)
    return f"Active Ops report with {len(feed_snapshots)} feeds ({ordered_status})."


def _build_map_items(feed_snapshots: list[dict]) -> list[dict]:
    items: list[dict] = []
    for snapshot in feed_snapshots:
        summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
        top_key = None
        for candidate in ("top_events", "top_storms", "sample_rates"):
            if summary.get(candidate):
                top_key = candidate
                break
        items.append(
            {
                "feed": snapshot.get("feed"),
                "collector_status": snapshot.get("collector_status"),
                "summary_key": top_key,
                "items": (summary.get(top_key) or [])[:3] if top_key else [],
            }
        )
    return items


def build_ops_report(
    *,
    watch: dict,
    effective_feeds: list[str],
    history_feeds: list[str] | None = None,
) -> dict:
    feed_snapshots: list[dict] = []
    recent_change_index: list[dict] = []
    geojson = None
    snapshot_hashes: dict[str, str] = {}
    snapshots_by_feed: dict[str, dict] = {}
    history_feed_set = {str(feed or "").strip() for feed in (history_feeds or []) if str(feed or "").strip()}
    state_by_feed: dict[str, tuple[dict | None, list[dict]]] = {}

    def _load_feed_state(feed: str) -> tuple[dict | None, list[dict]]:
        snapshot = load_current_state_snapshot(feed)
        history_entries = load_current_state_history(feed) if feed in history_feed_set else []
        return snapshot, history_entries

    max_workers = max(1, min(len(effective_feeds), 8))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_load_feed_state, feed): feed for feed in effective_feeds}
        for future in as_completed(future_map):
            feed = future_map[future]
            try:
                state_by_feed[feed] = future.result()
            except Exception:
                state_by_feed[feed] = (None, [])

    for feed in effective_feeds:
        snapshot, history_entries = state_by_feed.get(feed, (None, []))
        if isinstance(snapshot, dict):
            snapshots_by_feed[feed] = snapshot
            payload_hash = str(snapshot.get("payload_hash") or "").strip()
            if payload_hash:
                snapshot_hashes[feed] = payload_hash
            if geojson is None:
                geojson = _snapshot_to_geojson(snapshot)
        feed_snapshot = _compact_feed_snapshot(feed, snapshot, history_entries)
        feed_snapshots.append(feed_snapshot)
        change_entry = _build_recent_change_entry(feed, snapshot, history_entries)
        if change_entry:
            recent_change_index.append(change_entry)

    recent_change_index.sort(
        key=lambda entry: str(entry.get("last_changed_at") or ""),
        reverse=True,
    )
    report = {
        "report_version": 1,
        "watch_id": watch.get("watch_id"),
        "generated_at": max((str(item.get("last_checked_at") or "") for item in feed_snapshots), default=None),
        "effective_feeds": effective_feeds,
        "snapshot_hashes": snapshot_hashes,
        "headline_summary": _build_headline_summary(feed_snapshots),
        "feed_snapshots": feed_snapshots,
        "recent_change_index": recent_change_index[:6],
        "map_items": _build_map_items(feed_snapshots),
        "geojson": geojson,
        "display_payloads": _build_display_payloads(snapshots_by_feed),
    }
    return report


def _query_requests_broad_recent_changes(query: str) -> bool:
    text = str(query or "").strip().lower()
    if not text:
        return False
    if "what changed" in text or "what's changed" in text or "whats changed" in text:
        return True
    if "changed recently" in text or "recent changes" in text:
        return True
    if "recently changed" in text:
        return True
    return False


def _build_prompt_safe_ops_report(report: dict | None) -> dict:
    if not isinstance(report, dict):
        return {}
    return {
        "report_version": report.get("report_version"),
        "watch_id": report.get("watch_id"),
        "generated_at": report.get("generated_at"),
        "effective_feeds": report.get("effective_feeds") or [],
        "snapshot_hashes": report.get("snapshot_hashes") or {},
        "headline_summary": report.get("headline_summary"),
        "feed_snapshots": report.get("feed_snapshots") or [],
        "recent_change_index": report.get("recent_change_index") or [],
        "map_items": report.get("map_items") or [],
    }


def _query_requests_deep_history(query: str, hints: dict | None = None) -> bool:
    text = str(query or "").strip().lower()
    if not text:
        return False
    if any(re.search(pattern, text) for pattern in DEEP_HISTORY_PATTERNS):
        return True
    time_hints = (hints or {}).get("time") if isinstance(hints, dict) else {}
    if isinstance(time_hints, dict) and any(time_hints.get(key) for key in ("specific_year", "start_year", "end_year")):
        return True
    return False


def _parse_iso_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _history_observed_at(entry: dict | None) -> datetime | None:
    if not isinstance(entry, dict):
        return None
    for key in ("published_at", "last_changed_at", "fetched_at", "last_checked_at", "upstream_issued_at"):
        parsed = _parse_iso_datetime(entry.get(key))
        if parsed is not None:
            return parsed
    return None


def _extract_history_window(query: str, hints: dict | None = None) -> tuple[datetime | None, str | None]:
    text = str(query or "").strip().lower()
    if not text:
        return None, None
    now = datetime.now(timezone.utc)

    hours_match = re.search(r"\b(?:last|past)\s+(\d{1,3})\s+hours?\b", text)
    if hours_match:
        hours = max(1, int(hours_match.group(1)))
        return now.replace(microsecond=0) - timedelta(hours=hours), f"the last {hours} hour{'s' if hours != 1 else ''}"

    days_match = re.search(r"\b(?:last|past)\s+(\d{1,3})\s+days?\b", text)
    if days_match:
        days = max(1, int(days_match.group(1)))
        return now.replace(microsecond=0) - timedelta(days=days), f"the last {days} day{'s' if days != 1 else ''}"

    if re.search(r"\btoday\b", text):
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return cutoff, "today"

    if re.search(r"\byesterday\b", text):
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        return cutoff, "yesterday and today"

    time_hints = (hints or {}).get("time") if isinstance(hints, dict) else {}
    start_year = time_hints.get("start_year") if isinstance(time_hints, dict) else None
    end_year = time_hints.get("end_year") if isinstance(time_hints, dict) else None
    if isinstance(start_year, int):
        start_dt = datetime(start_year, 1, 1, tzinfo=timezone.utc)
        label = f"since {start_year}"
        if isinstance(end_year, int) and end_year >= start_year:
            start_dt = datetime(start_year, 1, 1, tzinfo=timezone.utc)
            label = f"{start_year}-{end_year}"
        return start_dt, label

    return None, None


def _mentioned_feeds(query: str, effective_feeds: list[str]) -> list[str]:
    text = str(query or "").strip().lower()
    matched: list[str] = []
    for feed in effective_feeds:
        aliases = FEED_ALIASES.get(feed, ()) + (feed.replace("_", " "), feed)
        for alias in aliases:
            alias_text = str(alias or "").strip().lower()
            if alias_text and alias_text in text:
                matched.append(feed)
                break
    return matched


def _query_requests_map_focus(query: str) -> bool:
    text = str(query or "").strip().lower()
    if not text:
        return False
    return any(re.search(pattern, text) for pattern in MAP_FOCUS_PATTERNS)


def _query_requests_superlative(query: str) -> bool:
    text = str(query or "").strip().lower()
    if not text:
        return False
    return any(re.search(pattern, text) for pattern in SUPERLATIVE_PATTERNS)


def _recent_feed_from_history(chat_history: list | None, effective_feeds: list[str]) -> str | None:
    for message in reversed(chat_history or []):
        if str((message or {}).get("role") or "").strip().lower() != "user":
            continue
        content = str((message or {}).get("content") or "").strip()
        mentioned = _mentioned_feeds(content, effective_feeds)
        if len(mentioned) == 1:
            return mentioned[0]
    return None


def _report_display_payload_by_feed(report: dict | None) -> dict[str, dict]:
    payloads: dict[str, dict] = {}
    for payload in (report or {}).get("display_payloads") or []:
        if not isinstance(payload, dict):
            continue
        source_id = str(payload.get("source_id") or "").strip()
        if source_id == "currency_live_ops":
            payloads["currency"] = payload
        elif source_id == "ibtracs_live_ops":
            payloads["hurricanes_ibtracs_nrt"] = payload
        elif source_id.endswith("_live_ops"):
            payloads[source_id[:-9]] = payload
    return payloads


def _feature_numeric_value(feature: dict, keys: tuple[str, ...]) -> float | None:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    for key in keys:
        value = props.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _focus_feature_name(feed: str, props: dict) -> str:
    if feed == "wildfires_us_nifc":
        return str(props.get("fire_name") or props.get("event_id") or "Unnamed wildfire").strip()
    if feed == "earthquakes":
        return str(props.get("place") or props.get("event_id") or "Unnamed earthquake").strip()
    if feed == "tsunamis":
        return str(props.get("location") or props.get("country") or props.get("event_id") or "Unnamed tsunami").strip()
    if feed == "volcanoes":
        return str(props.get("volcano_name") or props.get("event_id") or "Unnamed volcano").strip()
    if feed == "hurricanes_ibtracs_nrt":
        return str(props.get("name") or props.get("storm_id") or "Unnamed storm").strip()
    return str(props.get("event_id") or props.get("storm_id") or "Unnamed event").strip()


def _focus_feature_location(feed: str, props: dict) -> str | None:
    if feed == "wildfires_us_nifc":
        county = str(props.get("county_name") or "").strip()
        state = str(props.get("state") or "").strip()
        if county and state:
            return f"{county}, {state}"
        return county or state or None
    if feed == "tsunamis":
        location = str(props.get("location") or "").strip()
        country = str(props.get("country") or "").strip()
        if location and country and location.lower() not in country.lower():
            return f"{location}, {country}"
        return location or country or None
    if feed == "hurricanes_ibtracs_nrt":
        basin = str(props.get("basin") or "").strip()
        return basin or None
    return None


def _focus_metric_text(feed: str, props: dict) -> str | None:
    if feed == "wildfires_us_nifc":
        try:
            return f"{int(float(props.get('burned_acres'))):,} acres burned"
        except (TypeError, ValueError):
            return None
    if feed == "earthquakes":
        value = props.get("magnitude")
        return f"magnitude {value}" if value not in (None, "") else None
    if feed == "tsunamis":
        value = props.get("max_water_height_m")
        return f"{value} m max water height" if value not in (None, "") else None
    if feed == "volcanoes":
        value = props.get("VEI") if props.get("VEI") not in (None, "") else props.get("vei")
        return f"VEI {value}" if value not in (None, "") else None
    if feed == "hurricanes_ibtracs_nrt":
        category = props.get("max_category") if props.get("max_category") not in (None, "") else props.get("category")
        wind = props.get("max_wind_kt")
        if category not in (None, "") and wind not in (None, ""):
            return f"Category {category}, {wind} kt"
        if category not in (None, ""):
            return f"Category {category}"
        if wind not in (None, ""):
            return f"{wind} kt"
    return None


def _format_ops_timestamp(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00") if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%b %d, %Y %H:%M UTC")


def _focus_timestamp(feed: str, props: dict) -> str | None:
    for key in ("last_updated", "timestamp", "end_date", "start_date"):
        formatted = _format_ops_timestamp(props.get(key))
        if formatted:
            return formatted
    return None


def _category_rank(value: object) -> float:
    text = str(value or "").strip().upper()
    ranks = {
        "TD": 0.0,
        "TS": 1.0,
        "CAT1": 2.0,
        "CAT2": 3.0,
        "CAT3": 4.0,
        "CAT4": 5.0,
        "CAT5": 6.0,
    }
    return ranks.get(text, -1.0)


def _coords_text(lat: object, lon: object) -> str | None:
    try:
        lat_value = float(lat)
        lon_value = float(lon)
    except (TypeError, ValueError):
        return None
    lat_dir = "N" if lat_value >= 0 else "S"
    lon_dir = "E" if lon_value >= 0 else "W"
    return f"{abs(lat_value):.1f}{lat_dir}, {abs(lon_value):.1f}{lon_dir}"


def _selected_popup_feed(selected_popup: dict | None, effective_feeds: list[str]) -> str | None:
    if not isinstance(selected_popup, dict):
        return None
    props = selected_popup.get("properties") if isinstance(selected_popup.get("properties"), dict) else {}
    event_type = str(selected_popup.get("event_type") or props.get("event_type") or "").strip().lower()
    if event_type in {"hurricane", "storm", "cyclone", "typhoon"} and "hurricanes_ibtracs_nrt" in effective_feeds:
        return "hurricanes_ibtracs_nrt"
    if str(props.get("storm_id") or "").strip() and "hurricanes_ibtracs_nrt" in effective_feeds:
        return "hurricanes_ibtracs_nrt"
    return None


def _selected_storm_identity(selected_popup: dict | None) -> tuple[str | None, str | None]:
    if not isinstance(selected_popup, dict):
        return None, None
    props = selected_popup.get("properties") if isinstance(selected_popup.get("properties"), dict) else {}
    storm_id = str(
        props.get("storm_id")
        or selected_popup.get("event_id")
        or ""
    ).strip()
    storm_name = str(
        props.get("name")
        or selected_popup.get("name")
        or ""
    ).strip()
    return storm_id or None, storm_name or None


def _latest_position_for_storm(rows: list[dict], storm_id: str | None) -> dict | None:
    if not storm_id:
        return None
    matching = [
        row for row in rows
        if isinstance(row, dict) and str(row.get("storm_id") or "").strip() == storm_id
    ]
    if not matching:
        return None
    return max(matching, key=lambda row: str(row.get("timestamp") or ""))


def _build_selected_hurricane_history_answer(selected_popup: dict | None) -> str | None:
    storm_id, storm_name = _selected_storm_identity(selected_popup)
    if not storm_id and not storm_name:
        return None

    entries = load_current_state_history("hurricanes_ibtracs_nrt")
    label = storm_name or storm_id or "the selected storm"
    if not entries:
        return (
            f"I know which storm is selected ({label}), but there is no retained Ops hurricane history "
            "available yet in this environment, so I cannot compare the last few days."
        )

    timeline: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        summary = entry.get("payload_summary") if isinstance(entry.get("payload_summary"), dict) else {}
        storms = summary.get("storms") if isinstance(summary.get("storms"), list) else []
        positions = summary.get("positions") if isinstance(summary.get("positions"), list) else []
        matched_storm = None
        if storm_id:
            for storm in storms:
                if not isinstance(storm, dict):
                    continue
                if str(storm.get("storm_id") or "").strip() == storm_id:
                    matched_storm = storm
                    break
        if matched_storm is None and storm_name:
            for storm in storms:
                if not isinstance(storm, dict):
                    continue
                if str(storm.get("name") or "").strip().lower() == storm_name.lower():
                    matched_storm = storm
                    break
        if matched_storm is None:
            continue
        resolved_storm_id = str(matched_storm.get("storm_id") or storm_id or "").strip() or None
        timeline.append(
            {
                "published_at": entry.get("published_at") or entry.get("last_changed_at") or entry.get("upstream_issued_at"),
                "storm": matched_storm,
                "position": _latest_position_for_storm(positions, resolved_storm_id),
            }
        )

    if not timeline:
        return (
            f"I know which storm is selected ({label}), but it is not present in the retained Ops hurricane "
            "history window yet, so I cannot compare its recent changes."
        )

    ordered = sorted(timeline, key=lambda item: str(item.get("published_at") or ""))
    earliest = ordered[0]
    latest = ordered[-1]

    early_storm = earliest.get("storm") if isinstance(earliest.get("storm"), dict) else {}
    latest_storm = latest.get("storm") if isinstance(latest.get("storm"), dict) else {}
    early_position = earliest.get("position") if isinstance(earliest.get("position"), dict) else {}
    latest_position = latest.get("position") if isinstance(latest.get("position"), dict) else {}

    early_name = str(early_storm.get("name") or storm_name or storm_id or "Selected storm").strip()
    early_category = early_position.get("category") or early_storm.get("max_category")
    latest_category = latest_position.get("category") or latest_storm.get("max_category")
    early_wind = early_position.get("wind_kt") or early_storm.get("max_wind_kt")
    latest_wind = latest_position.get("wind_kt") or latest_storm.get("max_wind_kt")
    early_time = _format_ops_timestamp(
        early_position.get("timestamp") or early_storm.get("end_date") or earliest.get("published_at")
    )
    latest_time = _format_ops_timestamp(
        latest_position.get("timestamp") or latest_storm.get("end_date") or latest.get("published_at")
    )

    sentences: list[str] = [
        f"{early_name} appears in {len(ordered)} retained Ops hurricane snapshots over the last 72 hours."
    ]

    change_bits: list[str] = []
    if early_category not in (None, "") and latest_category not in (None, ""):
        if str(early_category) == str(latest_category):
            change_bits.append(f"it remained at {latest_category}")
        elif _category_rank(latest_category) > _category_rank(early_category):
            change_bits.append(f"it strengthened from {early_category} to {latest_category}")
        elif _category_rank(latest_category) < _category_rank(early_category):
            change_bits.append(f"it weakened from {early_category} to {latest_category}")
        else:
            change_bits.append(f"its classification changed from {early_category} to {latest_category}")

    try:
        if early_wind not in (None, "") and latest_wind not in (None, ""):
            early_wind_value = float(early_wind)
            latest_wind_value = float(latest_wind)
            wind_delta = latest_wind_value - early_wind_value
            if abs(wind_delta) < 0.5:
                change_bits.append(f"winds stayed near {latest_wind_value:.0f} kt")
            elif wind_delta > 0:
                change_bits.append(f"winds increased from {early_wind_value:.0f} kt to {latest_wind_value:.0f} kt")
            else:
                change_bits.append(f"winds decreased from {early_wind_value:.0f} kt to {latest_wind_value:.0f} kt")
    except (TypeError, ValueError):
        pass

    if change_bits:
        sentences.append("Over that window, " + " and ".join(change_bits) + ".")

    if early_time and latest_time:
        sentences.append(f"Window compared: {early_time} to {latest_time}.")

    latest_coords = _coords_text(latest_position.get("latitude"), latest_position.get("longitude"))
    latest_basin = str(latest_storm.get("basin") or "").strip()
    if latest_coords and latest_basin:
        sentences.append(f"Latest retained position is near {latest_coords} in basin {latest_basin}.")
    elif latest_coords:
        sentences.append(f"Latest retained position is near {latest_coords}.")

    return " ".join(sentences)


def _try_selected_history_answer(
    *,
    query: str,
    selected_popup: dict | None,
    effective_feeds: list[str],
) -> str | None:
    if not _query_requests_deep_history(query):
        return None
    selected_feed = _selected_popup_feed(selected_popup, effective_feeds)
    if selected_feed != "hurricanes_ibtracs_nrt":
        return None
    return _build_selected_hurricane_history_answer(selected_popup)


def _select_focus_candidate(
    *,
    feed: str,
    report: dict,
) -> tuple[dict, dict, float] | tuple[None, None, None]:
    spec = FEED_FOCUS_SPECS.get(feed)
    if not spec:
        return None, None, None
    payload = _report_display_payload_by_feed(report).get(feed) or _build_ops_payload_for_feed(feed)
    return _select_focus_candidate_from_payload(feed=feed, payload=payload)


def _select_focus_candidate_from_payload(
    *,
    feed: str,
    payload: dict | None,
) -> tuple[dict, dict, float] | tuple[None, None, None]:
    spec = FEED_FOCUS_SPECS.get(feed)
    if not spec or not isinstance(payload, dict):
        return None, None, None
    if not isinstance(payload, dict):
        return None, None, None
    features = (payload.get("geojson") or {}).get("features") if isinstance(payload.get("geojson"), dict) else None
    if not isinstance(features, list):
        return None, None, None
    best_feature = None
    best_value = None
    for feature in features:
        if not isinstance(feature, dict):
            continue
        value = _feature_numeric_value(feature, spec["metric_keys"])
        if value is None:
            continue
        if best_value is None or value > best_value:
            best_feature = feature
            best_value = value
    if best_feature is None or best_value is None:
        return None, None, None
    return payload, best_feature, float(best_value)


def _focus_identifier(feed: str, feature: dict) -> dict:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    spec = FEED_FOCUS_SPECS.get(feed) or {}
    for key in spec.get("id_keys", ()):
        value = str(props.get(key) or "").strip()
        if value:
            return {"key": key, "value": value}
    return {}


def _store_ops_focus_target(cache, *, feed: str, payload: dict, feature: dict) -> None:
    if not isinstance(getattr(cache, "map_state", None), dict):
        return
    cache.map_state["ops_focus_target"] = {
        "feed": feed,
        "source_id": payload.get("source_id"),
        "identifier": _focus_identifier(feed, feature),
        "feature": feature,
    }


def _store_ops_history_payload(cache, *, feed: str, payload: dict) -> None:
    if not isinstance(getattr(cache, "map_state", None), dict):
        return
    cache.map_state["ops_history_payload"] = {
        "feed": feed,
        "payload": payload,
    }


def _resolve_cached_history_payload(*, cache, effective_feeds: list[str]) -> tuple[str, dict] | tuple[None, None]:
    map_state = cache.map_state if isinstance(getattr(cache, "map_state", None), dict) else {}
    stored = map_state.get("ops_history_payload") if isinstance(map_state, dict) else None
    if not isinstance(stored, dict):
        return None, None
    feed = str(stored.get("feed") or "").strip()
    payload = stored.get("payload")
    if not feed or feed not in effective_feeds or not isinstance(payload, dict):
        return None, None
    return feed, payload


def _resolve_cached_focus_target(*, cache, report: dict, effective_feeds: list[str]) -> tuple[str, dict, dict] | tuple[None, None, None]:
    map_state = cache.map_state if isinstance(getattr(cache, "map_state", None), dict) else {}
    stored = map_state.get("ops_focus_target") if isinstance(map_state, dict) else None
    if not isinstance(stored, dict):
        return None, None, None
    feed = str(stored.get("feed") or "").strip()
    if not feed or feed not in effective_feeds:
        return None, None, None
    payload = _report_display_payload_by_feed(report).get(feed) or _build_ops_payload_for_feed(feed)
    if not isinstance(payload, dict):
        fallback_feature = stored.get("feature")
        if isinstance(fallback_feature, dict):
            return feed, {
                "type": stored.get("source_id") == "ibtracs_live_ops" and "data" or "events",
                "data_type": "events",
                "event_type": FEED_FOCUS_SPECS.get(feed, {}).get("label"),
                "source_id": stored.get("source_id"),
                "geojson": {"type": "FeatureCollection", "features": [fallback_feature]},
            }, fallback_feature
        return None, None, None
    features = (payload.get("geojson") or {}).get("features") if isinstance(payload.get("geojson"), dict) else []
    identifier = stored.get("identifier") if isinstance(stored.get("identifier"), dict) else {}
    key = str(identifier.get("key") or "").strip()
    value = str(identifier.get("value") or "").strip()
    if key and value:
        for feature in features or []:
            props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
            if str(props.get(key) or "").strip() == value:
                return feed, payload, feature
    fallback_feature = stored.get("feature")
    if isinstance(fallback_feature, dict):
        return feed, payload, fallback_feature
    return None, None, None


def _build_focus_chat_message(*, feed: str, feature: dict) -> str:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    label = FEED_FOCUS_SPECS.get(feed, {}).get("label") or "event"
    name = _focus_feature_name(feed, props)
    location = _focus_feature_location(feed, props)
    metric = _focus_metric_text(feed, props)
    timestamp = _focus_timestamp(feed, props)
    pieces = [f"The largest active {label} is {name}"]
    if location:
        pieces[-1] += f" in {location}"
    if metric:
        pieces[-1] += f", with {metric}"
    pieces[-1] += "."
    if timestamp:
        pieces.append(f"Last updated {timestamp}.")
    return " ".join(pieces)


def _build_history_focus_chat_message(*, feed: str, feature: dict) -> str:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    label = FEED_FOCUS_SPECS.get(feed, {}).get("label") or "event"
    name = _focus_feature_name(feed, props)
    location = _focus_feature_location(feed, props)
    metric = _focus_metric_text(feed, props)
    timestamp = _focus_timestamp(feed, props)
    pieces = [f"The largest retained {label} in that window is {name}"]
    if location:
        pieces[-1] += f" in {location}"
    if metric:
        pieces[-1] += f", with {metric}"
    pieces[-1] += "."
    if timestamp:
        pieces.append(f"Observed {timestamp}.")
    return " ".join(pieces)


def _build_focus_map_result(*, feed: str, payload: dict, feature: dict, watch: dict, effective_feeds: list[str], message: str | None = None) -> dict:
    subset_payload = dict(payload)
    subset_payload["geojson"] = {
        "type": "FeatureCollection",
        "features": [feature],
    }
    subset_payload["count"] = 1
    subset_payload["fit"] = True
    summary = message or _build_focus_chat_message(feed=feed, feature=feature)
    subset_payload["summary"] = summary
    subset_payload["message"] = summary
    subset_payload["watch_id"] = watch.get("watch_id")
    subset_payload["watch_context"] = watch
    subset_payload["effective_feeds"] = effective_feeds
    return subset_payload


def _load_history_focus_payload(
    *,
    feed: str,
    query: str,
    hints: dict | None = None,
    cache=None,
) -> dict | None:
    live_snapshot = load_current_state_snapshot(feed) or {}
    history_entries = load_current_state_history(feed)
    in_window, window_label = _history_entries_in_window(
        snapshot=live_snapshot,
        history_entries=history_entries,
        query=query,
        hints=hints,
    )
    history_payload = _build_history_event_payload(
        feed=feed,
        in_window=in_window,
        window_label=window_label,
    )
    if history_payload:
        _store_ops_history_payload(cache, feed=feed, payload=history_payload)
    return history_payload


def _select_deep_history_feeds(
    *,
    query: str,
    effective_feeds: list[str],
    report: dict,
    hints: dict | None = None,
    max_feeds: int = 2,
) -> list[str]:
    if not _query_requests_deep_history(query, hints=hints):
        return []
    explicit = _mentioned_feeds(query, effective_feeds)
    if explicit:
        return explicit[:max_feeds]
    if len(effective_feeds) == 1:
        return effective_feeds[:1]
    recent = report.get("recent_change_index") if isinstance(report, dict) else []
    chosen: list[str] = []
    for entry in recent or []:
        feed = str((entry or {}).get("feed") or "").strip()
        if feed and feed in effective_feeds and feed not in chosen:
            chosen.append(feed)
        if len(chosen) >= max_feeds:
            return chosen
    return effective_feeds[:max_feeds]


def _report_snapshot_by_feed(report: dict | None) -> dict[str, dict]:
    snapshots: dict[str, dict] = {}
    for item in (report or {}).get("feed_snapshots") or []:
        if not isinstance(item, dict):
            continue
        feed = str(item.get("feed") or "").strip()
        if feed:
            snapshots[feed] = item
    return snapshots


def _is_count_query(query: str) -> bool:
    text = str(query or "").strip().lower()
    if not text:
        return False
    return any(re.search(pattern, text) for pattern in COUNT_QUERY_PATTERNS)


def _query_explicitly_requests_current_snapshot(query: str) -> bool:
    text = str(query or "").strip().lower()
    if not text:
        return False
    current_patterns = (
        r"\bcurrent\b",
        r"\bright now\b",
        r"\bactive now\b",
        r"\bcurrently\b",
        r"\bcurrent watch\b",
        r"\bcurrent snapshot\b",
        r"\bnow\b",
    )
    return any(re.search(pattern, text) for pattern in current_patterns)


def _feed_prefers_history_by_default(feed: str) -> bool:
    return feed in {
        "earthquakes",
        "tsunamis",
        "volcanoes",
        "wildfires_us_nifc",
        "hurricanes_ibtracs_nrt",
        "usa_nws_alerts",
        "noaa_swpc",
        "noaa_aurora",
        "currency",
    }


def _feed_display_name(feed: str) -> str:
    names = {
        "wildfires_us_nifc": "wildfires",
        "hurricanes_ibtracs_nrt": "storms",
        "earthquakes": "earthquakes",
        "tsunamis": "tsunamis",
        "volcanoes": "volcanoes",
        "currency": "currencies",
        "usa_nws_alerts": "NWS alerts",
        "noaa_aurora": "aurora forecast cells",
        "noaa_swpc": "space weather alerts",
    }
    return names.get(feed, feed.replace("_", " "))


def _feed_status_time(snapshot: dict) -> str | None:
    for key in ("last_changed_at", "fetched_at", "last_checked_at"):
        formatted = _format_ops_timestamp(snapshot.get(key))
        if formatted:
            return formatted
    return None


def _feed_history_id_set(feed: str, summary: dict) -> set[str]:
    if not isinstance(summary, dict):
        return set()
    rows = []
    id_keys: tuple[str, ...] = ()
    if feed == "earthquakes":
        rows = summary.get("events") or []
        id_keys = ("event_id",)
    elif feed == "tsunamis":
        rows = summary.get("events") or []
        id_keys = ("event_id",)
    elif feed == "volcanoes":
        rows = summary.get("events") or []
        id_keys = ("event_id",)
    elif feed == "wildfires_us_nifc":
        rows = summary.get("events") or []
        id_keys = ("event_id",)
    elif feed == "hurricanes_ibtracs_nrt":
        rows = summary.get("storms") or []
        id_keys = ("storm_id",)
    elif feed == "currency":
        rows = summary.get("rates") or []
        id_keys = ("currency_code",)
    elif feed == "noaa_swpc":
        rows = summary.get("alerts") or []
        id_keys = ("alert_id",)
    elif feed == "usa_nws_alerts":
        rows = summary.get("alerts") or []
        id_keys = ("alert_id",)

    ids: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        for key in id_keys:
            value = str(row.get(key) or "").strip()
            if value:
                ids.add(value)
                break
    return ids


def _history_count_noun(feed: str) -> str:
    nouns = {
        "earthquakes": "earthquakes",
        "tsunamis": "tsunami events",
        "volcanoes": "volcano events",
        "wildfires_us_nifc": "wildfires",
        "hurricanes_ibtracs_nrt": "storms",
        "currency": "currency rates",
        "noaa_swpc": "space weather alerts",
        "usa_nws_alerts": "NWS alerts",
        "noaa_aurora": "aurora forecast cells",
    }
    return nouns.get(feed, _feed_display_name(feed))


def _history_entries_in_window(
    *,
    snapshot: dict,
    history_entries: list[dict],
    query: str,
    hints: dict | None = None,
) -> tuple[list[dict], str | None]:
    cutoff, window_label = _extract_history_window(query, hints=hints)
    if cutoff is None:
        return [], None
    timeline: list[dict] = []
    if isinstance(snapshot, dict):
        timeline.append(snapshot)
    timeline.extend(entry for entry in history_entries if isinstance(entry, dict))
    in_window: list[dict] = []
    for entry in timeline:
        observed_at = _history_observed_at(entry)
        if observed_at is None or observed_at < cutoff:
            continue
        in_window.append(entry)
    return in_window, window_label


def _build_history_event_payload(*, feed: str, in_window: list[dict], window_label: str | None) -> dict | None:
    if feed not in {"earthquakes", "tsunamis", "volcanoes", "wildfires_us_nifc"}:
        return None
    features: list[dict] = []
    seen_ids: set[str] = set()
    for entry in in_window:
        summary = entry.get("payload_summary") if isinstance(entry.get("payload_summary"), dict) else {}
        rows = summary.get("events") if isinstance(summary.get("events"), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                lon = float(row.get("longitude"))
                lat = float(row.get("latitude"))
            except (TypeError, ValueError):
                continue
            identifier = str(row.get("event_id") or row.get("id") or "").strip()
            if not identifier:
                identifier = f"{feed}:{row.get('timestamp')}:{row.get('place') or row.get('location') or lat}:{lon}"
            if identifier in seen_ids:
                continue
            seen_ids.add(identifier)
            props = dict(row)
            props.setdefault("collector", feed)
            if feed == "volcanoes":
                props.setdefault("VEI", row.get("vei"))
            if feed == "wildfires_us_nifc":
                acres = row.get("burned_acres")
                try:
                    props.setdefault("area_km2", float(acres) * 0.00404686)
                except (TypeError, ValueError):
                    pass
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": props,
                }
            )
    if not features:
        return None
    title = f"Ops {feed.replace('_', ' ').title()} History"
    label = window_label or "the retained window"
    return {
        "type": "events",
        "data_type": "events",
        "event_type": FEED_FOCUS_SPECS.get(feed, {}).get("label") or _feed_display_name(feed),
        "source_id": f"{feed}_history_ops",
        "dataset_name": title,
        "source_name": title,
        "summary": f"Showing {len(features)} retained {_history_count_noun(feed)} from {label}.",
        "count": len(features),
        "fit": True,
        "geojson": {
            "type": "FeatureCollection",
            "features": features,
        },
    }


def _build_history_count_answer(*, feed: str, snapshot: dict, history_entries: list[dict], query: str, hints: dict | None = None) -> str | None:
    cutoff, _ = _extract_history_window(query, hints=hints)
    in_window, window_label = _history_entries_in_window(
        snapshot=snapshot,
        history_entries=history_entries,
        query=query,
        hints=hints,
    )
    if window_label is None:
        return None

    noun = _history_count_noun(feed)
    if not in_window:
        available_count = len(history_entries)
        if available_count == 0:
            history_status = _get_live_state_status(feed, "history")
            if history_status == "cloud_unavailable":
                return f"I could not read cloud Ops history for {noun}, so I cannot answer for {window_label} right now."
            if history_status == "cloud_not_configured":
                return f"Cloud Ops history is not configured in this runtime for {noun}, so I cannot answer for {window_label}."
            return f"I do not have retained Ops history for {noun} in this environment yet, so I cannot answer for {window_label}."
        return f"I do not have any retained {noun} history entries covering {window_label}."

    unique_ids: set[str] = set()
    peak_count: int | None = None
    newest_time: datetime | None = None
    oldest_time: datetime | None = None
    for entry in in_window:
        summary = entry.get("payload_summary") if isinstance(entry.get("payload_summary"), dict) else {}
        unique_ids.update(_feed_history_id_set(feed, summary))
        count_value, _ = _active_count_for_feed(feed, summary, query.lower())
        if count_value is not None:
            peak_count = count_value if peak_count is None else max(peak_count, count_value)
        observed_at = _history_observed_at(entry)
        if observed_at is not None:
            newest_time = observed_at if newest_time is None or observed_at > newest_time else newest_time
            oldest_time = observed_at if oldest_time is None or observed_at < oldest_time else oldest_time

    if unique_ids:
        count = len(unique_ids)
        message = f"There {'was' if count == 1 else 'were'} {count} {noun} seen in retained Ops history over {window_label}."
    elif peak_count is not None:
        message = f"The peak retained count for {noun} over {window_label} was {peak_count}."
    else:
        return f"I found retained history for {noun} over {window_label}, but not a stable count field to summarize it yet."

    if oldest_time and newest_time:
        retained_span = newest_time - oldest_time
        if cutoff is not None and retained_span < (datetime.now(timezone.utc) - cutoff):
            message += f" Available retained window here is {oldest_time.strftime('%b %d, %Y %H:%M UTC')} to {newest_time.strftime('%b %d, %Y %H:%M UTC')}."
        else:
            message += f" Latest update: {newest_time.strftime('%b %d, %Y %H:%M UTC')}."
    return message


def _active_count_for_feed(feed: str, summary: dict, query_text: str) -> tuple[int | None, str | None]:
    if not isinstance(summary, dict):
        return None, None
    if feed == "wildfires_us_nifc":
        value = summary.get("active_count")
        return (int(value), "active wildfires") if value is not None else (None, None)
    if feed == "hurricanes_ibtracs_nrt":
        value = summary.get("storm_count")
        return (int(value), "active storms") if value is not None else (None, None)
    if feed == "volcanoes":
        value = summary.get("ongoing_count")
        if value is not None:
            return int(value), "ongoing volcano events"
        value = summary.get("event_count")
        return (int(value), "volcano events") if value is not None else (None, None)
    if feed == "earthquakes":
        value = summary.get("event_count")
        return (int(value), "earthquakes") if value is not None else (None, None)
    if feed == "tsunamis":
        value = summary.get("event_count")
        return (int(value), "tsunami events") if value is not None else (None, None)
    if feed == "currency":
        value = summary.get("rate_count")
        return (int(value), "currency rates") if value is not None else (None, None)
    if feed == "noaa_swpc":
        value = summary.get("alert_count")
        return (int(value), "space weather alerts") if value is not None else (None, None)
    if feed == "usa_nws_alerts":
        value = summary.get("alert_count")
        return (int(value), "NWS alerts") if value is not None else (None, None)
    if feed == "noaa_aurora":
        value = summary.get("visible_cell_count")
        return (int(value), "aurora forecast cells") if value is not None else (None, None)
    for key in ("active_count", "ongoing_count", "storm_count", "event_count", "incident_count", "rate_count"):
        value = summary.get(key)
        if value is not None:
            return int(value), _feed_display_name(feed)
    return None, None


def _severity_rank(scale: str) -> tuple[int, int]:
    text = str(scale or "").strip().upper()
    if len(text) < 2:
        return (-1, -1)
    family_order = {"G": 3, "S": 2, "R": 1}
    try:
        level = int(text[1:])
    except ValueError:
        level = -1
    return (family_order.get(text[:1], 0), level)


def _try_warning_severity_answer(*, effective_feeds: list[str], report: dict) -> str | None:
    if "noaa_swpc" not in effective_feeds:
        return None
    snapshot = _report_snapshot_by_feed(report).get("noaa_swpc") or {}
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    active_scales = [str(value or "").strip().upper() for value in (summary.get("active_scales") or []) if str(value or "").strip()]
    if not active_scales:
        alert_count = summary.get("alert_count")
        if alert_count == 0:
            return "There are no active space weather alerts in the current watch."
        return None
    top_scale = max(active_scales, key=_severity_rank)
    alerts = [item for item in (summary.get("alerts") or []) if isinstance(item, dict)]
    matching = [item for item in alerts if str(item.get("noaa_scale") or "").strip().upper() == top_scale]
    top_summary = str((matching[0] or {}).get("summary") or "").strip() if matching else ""
    freshness = _feed_status_time(snapshot)
    if top_summary and freshness:
        return f"The highest active space weather warning is {top_scale}. {top_summary}. Last update: {freshness}."
    if top_summary:
        return f"The highest active space weather warning is {top_scale}. {top_summary}."
    if freshness:
        return f"The highest active space weather warning in the current watch is {top_scale}. Last update: {freshness}."
    return f"The highest active space weather warning in the current watch is {top_scale}."


def _format_lat_band(north_boundary: object, south_boundary: object) -> str | None:
    try:
        north = float(north_boundary) if north_boundary is not None else None
    except (TypeError, ValueError):
        north = None
    try:
        south = float(south_boundary) if south_boundary is not None else None
    except (TypeError, ValueError):
        south = None
    parts: list[str] = []
    if north is not None:
        parts.append(f"north of about {abs(north):.0f}N")
    if south is not None:
        parts.append(f"south of about {abs(south):.0f}S")
    if not parts:
        return None
    return " and ".join(parts)


def _try_aurora_visibility_answer(*, effective_feeds: list[str], report: dict) -> str | None:
    if "noaa_aurora" not in effective_feeds:
        return None
    snapshot = _report_snapshot_by_feed(report).get("noaa_aurora") or {}
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    if not summary:
        return None
    visible = bool(summary.get("aurora_visible"))
    max_probability = summary.get("max_probability")
    band = _format_lat_band(summary.get("north_boundary_lat"), summary.get("south_boundary_lat"))
    forecast_time = _format_ops_timestamp(summary.get("forecast_time")) or str(summary.get("forecast_time") or "").strip()
    if not visible:
        if forecast_time:
            return f"The current aurora forecast does not show a visible band right now. Forecast time: {forecast_time}."
        return "The current aurora forecast does not show a visible band right now."
    probability_text = ""
    if max_probability not in (None, ""):
        probability_text = f" with peak probability around {max_probability}%"
    if band and forecast_time:
        return f"The aurora is currently forecast to be visible {band}{probability_text}. Forecast time: {forecast_time}."
    if band:
        return f"The aurora is currently forecast to be visible {band}{probability_text}."
    if forecast_time:
        return f"The aurora is currently forecast to be visible{probability_text}. Forecast time: {forecast_time}."
    return f"The aurora is currently forecast to be visible{probability_text}."


def _focus_feed_from_query(
    *,
    query: str,
    chat_history: list | None,
    effective_feeds: list[str],
    cache,
) -> str | None:
    mentioned = _mentioned_feeds(query, effective_feeds)
    if len(mentioned) == 1:
        return mentioned[0]
    recent_feed = _recent_feed_from_history(chat_history, effective_feeds)
    if recent_feed:
        return recent_feed
    cached_feed, _payload, _feature = _resolve_cached_focus_target(
        cache=cache,
        report={"display_payloads": []},
        effective_feeds=effective_feeds,
    )
    return cached_feed


def _try_focus_result(
    *,
    query: str,
    report: dict,
    watch: dict,
    effective_feeds: list[str],
    chat_history: list | None,
    cache,
    hints: dict | None = None,
) -> dict | None:
    lower = str(query or "").strip().lower()
    if not lower:
        return None

    show_only = _query_requests_map_focus(lower) and not _query_requests_superlative(lower)
    if show_only:
        history_feed, history_payload = _resolve_cached_history_payload(
            cache=cache,
            effective_feeds=effective_feeds,
        )
        history_features = (history_payload.get("geojson") or {}).get("features") if isinstance((history_payload or {}).get("geojson"), dict) else []
        if history_feed and isinstance(history_features, list) and history_features:
            payload = dict(history_payload)
            payload["fit"] = True
            return payload
        cached_feed, cached_payload, cached_feature = _resolve_cached_focus_target(
            cache=cache,
            report=report,
            effective_feeds=effective_feeds,
        )
        if cached_feed and cached_payload and cached_feature:
            return _build_focus_map_result(
                feed=cached_feed,
                payload=cached_payload,
                feature=cached_feature,
                watch=watch,
                effective_feeds=effective_feeds,
                message=f"Showing {_focus_feature_name(cached_feed, cached_feature.get('properties') or {})}.",
            )

    if not _query_requests_superlative(lower):
        return None

    feed = _focus_feed_from_query(
        query=lower,
        chat_history=chat_history,
        effective_feeds=effective_feeds,
        cache=cache,
    )
    if not feed:
        return None

    history_feed, history_payload = _resolve_cached_history_payload(
        cache=cache,
        effective_feeds=effective_feeds,
    )
    if history_feed == feed:
        payload, feature, _score = _select_focus_candidate_from_payload(feed=feed, payload=history_payload)
        if payload and feature:
            _store_ops_focus_target(cache, feed=feed, payload=payload, feature=feature)
            focus_message = _build_history_focus_chat_message(feed=feed, feature=feature)
            if _query_requests_map_focus(lower):
                return _build_focus_map_result(
                    feed=feed,
                    payload=payload,
                    feature=feature,
                    watch=watch,
                    effective_feeds=effective_feeds,
                    message=focus_message,
                )
            return {
                "type": "chat",
                "message": focus_message,
            }

    if _query_requests_deep_history(lower, hints=hints):
        history_payload = _load_history_focus_payload(
            feed=feed,
            query=query,
            hints=hints,
            cache=cache,
        )
        payload, feature, _score = _select_focus_candidate_from_payload(feed=feed, payload=history_payload)
        if payload and feature:
            _store_ops_focus_target(cache, feed=feed, payload=payload, feature=feature)
            focus_message = _build_history_focus_chat_message(feed=feed, feature=feature)
            if _query_requests_map_focus(lower):
                return _build_focus_map_result(
                    feed=feed,
                    payload=payload,
                    feature=feature,
                    watch=watch,
                    effective_feeds=effective_feeds,
                    message=focus_message,
                )
            return {
                "type": "chat",
                "message": focus_message,
            }

    payload, feature, _score = _select_focus_candidate(feed=feed, report=report)
    if not payload or not feature:
        return None

    _store_ops_focus_target(cache, feed=feed, payload=payload, feature=feature)
    focus_message = _build_focus_chat_message(feed=feed, feature=feature)

    if _query_requests_map_focus(lower):
        return _build_focus_map_result(
            feed=feed,
            payload=payload,
            feature=feature,
            watch=watch,
            effective_feeds=effective_feeds,
            message=focus_message,
        )

    return {
        "type": "chat",
        "message": focus_message,
    }


def _try_direct_ops_answer(*, query: str, report: dict, watch: dict, effective_feeds: list[str], hints: dict | None = None, cache=None) -> str | None:
    text = str(query or "").strip()
    lower = text.lower()
    if not text:
        return None

    if "what feeds" in lower and "active" in lower:
        return f"Active watch has {len(effective_feeds)} feeds: {', '.join(effective_feeds)}."
    if re.search(r"\bhow many feeds\b", lower):
        return f"Active watch has {len(effective_feeds)} feeds."

    if (
        ("highest severity" in lower or "most severe" in lower)
        and ("warning" in lower or "warnings" in lower or "alert" in lower or "alerts" in lower)
    ):
        warning_answer = _try_warning_severity_answer(
            effective_feeds=effective_feeds,
            report=report,
        )
        if warning_answer:
            return warning_answer

    generic_aurora_query = (
        "aurora" in lower
        and ("where" in lower or "see" in lower or "visible" in lower)
        and not re.search(r"\b(here|near me|my area|from here|from my|in my area)\b", lower)
    )
    if generic_aurora_query:
        aurora_answer = _try_aurora_visibility_answer(
            effective_feeds=effective_feeds,
            report=report,
        )
        if aurora_answer:
            return aurora_answer

    if not _is_count_query(text):
        return None

    mentioned = _mentioned_feeds(text, effective_feeds)
    if len(mentioned) != 1:
        return None

    feed = mentioned[0]
    snapshot = _report_snapshot_by_feed(report).get(feed) or {}
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}

    prefers_history = _feed_prefers_history_by_default(feed) and not _query_explicitly_requests_current_snapshot(text)
    if prefers_history or _query_requests_deep_history(text, hints=hints):
        history_entries = load_current_state_history(feed)
        live_snapshot = load_current_state_snapshot(feed) or {}
        history_answer = _build_history_count_answer(
            feed=feed,
            snapshot=live_snapshot,
            history_entries=history_entries,
            query=text,
            hints=hints,
        )
        in_window, window_label = _history_entries_in_window(
            snapshot=live_snapshot,
            history_entries=history_entries,
            query=text,
            hints=hints,
        )
        history_payload = _build_history_event_payload(
            feed=feed,
            in_window=in_window,
            window_label=window_label,
        )
        if history_payload:
            _store_ops_history_payload(cache, feed=feed, payload=history_payload)
        if history_answer:
            return history_answer

    count, noun = _active_count_for_feed(feed, summary, lower)
    if count is None or not noun:
        return None

    freshness = _feed_status_time(snapshot)
    if freshness:
        return f"There are {count} {noun} in the current watch. Last update: {freshness}."
    return f"There are {count} {noun} in the current watch."


def _compact_history_entries(feed: str, entries: list[dict], *, limit: int = 6) -> list[dict]:
    compact: list[dict] = []
    for entry in entries[-limit:]:
        if not isinstance(entry, dict):
            continue
        summary = entry.get("payload_summary") if isinstance(entry.get("payload_summary"), dict) else {}
        compact.append(
            {
                "fetched_at": entry.get("fetched_at"),
                "last_checked_at": entry.get("last_checked_at"),
                "last_changed_at": entry.get("last_changed_at"),
                "collector_status": entry.get("collector_status"),
                "payload_hash": entry.get("payload_hash"),
                "previous_payload_hash": entry.get("previous_payload_hash"),
                "changed_since_previous": entry.get("changed_since_previous"),
                "summary": _compact_payload_summary(feed, summary, sample_limit=2),
            }
        )
    return compact


def build_targeted_history_context(
    *,
    query: str,
    effective_feeds: list[str],
    report: dict,
    hints: dict | None = None,
) -> dict | None:
    feeds = _select_deep_history_feeds(
        query=query,
        effective_feeds=effective_feeds,
        report=report,
        hints=hints,
    )
    if not feeds:
        return None
    feed_contexts: list[dict] = []
    for feed in feeds:
        entries = load_current_state_history(feed)
        feed_contexts.append(
            {
                "feed": feed,
                "history_entry_count": len(entries),
                "entries": _compact_history_entries(feed, entries),
            }
        )
    return {
        "requested_by_query": True,
        "feeds": feed_contexts,
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
    selected_popup: dict | None = None,
) -> dict:
    if not effective_feeds:
        return {
            "type": "chat",
            "message": "Ops has no active feeds in this watch yet.",
            "watch_id": watch.get("watch_id"),
            "watch_context": watch,
            "effective_feeds": [],
        }

    preloaded = ops_orchestrator.preprocess(
        query=query,
        watch_context={
            "label": watch.get("label"),
            "sources": effective_feeds,
            "geography": watch.get("geography"),
        },
    )
    hints = preloaded.get("hints") if isinstance(preloaded, dict) else {}
    watch_context = preloaded.get("watch_context") if isinstance(preloaded, dict) else {}
    report_history_feeds = effective_feeds if _query_requests_broad_recent_changes(query) else []

    report = build_ops_report(
        watch=watch,
        effective_feeds=effective_feeds,
        history_feeds=report_history_feeds,
    )
    if isinstance(getattr(cache, "map_state", None), dict):
        cache.map_state["ops_report"] = report

    focus_result = _try_focus_result(
        query=query,
        report=report,
        watch=watch,
        effective_feeds=effective_feeds,
        chat_history=chat_history,
        cache=cache,
        hints=hints,
    )
    if focus_result:
        focus_result.setdefault("watch_id", watch.get("watch_id"))
        focus_result.setdefault("watch_context", watch)
        focus_result.setdefault("effective_feeds", effective_feeds)
        focus_result["ops_report"] = report
        if report.get("display_payloads") and "display_payloads" not in focus_result:
            focus_result["display_payloads"] = report.get("display_payloads")
        if report.get("geojson") and "geojson" not in focus_result:
            focus_result["geojson"] = report["geojson"]
        if focus_result.get("type") == "chat":
            focus_result.setdefault(
                "summary",
                f"Ops watch: {watch.get('label') or 'Watch'} | feeds: {', '.join(effective_feeds)}",
            )
        return focus_result

    direct_answer = _try_direct_ops_answer(
        query=query,
        report=report,
        watch=watch,
        effective_feeds=effective_feeds,
        hints=hints,
        cache=cache,
    )
    selected_history_answer = _try_selected_history_answer(
        query=query,
        selected_popup=selected_popup,
        effective_feeds=effective_feeds,
    )
    if selected_history_answer:
        result = {
            "type": "chat",
            "message": selected_history_answer,
            "summary": f"Ops watch: {watch.get('label') or 'Watch'} | feeds: {', '.join(effective_feeds)}",
            "watch_id": watch.get("watch_id"),
            "watch_context": watch,
            "effective_feeds": effective_feeds,
            "ops_report": report,
        }
        if report.get("display_payloads"):
            result["display_payloads"] = report.get("display_payloads")
        if report.get("geojson"):
            result["geojson"] = report["geojson"]
        return result
    if direct_answer:
        result = {
            "type": "chat",
            "message": direct_answer,
            "summary": f"Ops watch: {watch.get('label') or 'Watch'} | feeds: {', '.join(effective_feeds)}",
            "watch_id": watch.get("watch_id"),
            "watch_context": watch,
            "effective_feeds": effective_feeds,
            "ops_report": report,
        }
        if report.get("display_payloads"):
            result["display_payloads"] = report.get("display_payloads")
        if report.get("geojson"):
            result["geojson"] = report["geojson"]
        return result

    targeted_history = build_targeted_history_context(
        query=query,
        effective_feeds=effective_feeds,
        report=report,
        hints=hints,
    )
    prompt_safe_report = _build_prompt_safe_ops_report(report)
    system_prompt = ops_orchestrator.build_system_prompt(watch_context=watch_context, hints=hints)
    llm_runtime = ops_orchestrator.build_llm_runtime_context(system_prompt)
    system_blocks = llm_runtime["system_blocks"]
    llm_selection = llm_runtime["llm_selection"]
    client = llm_runtime["client"]

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Active Ops watch JSON:\n" + json.dumps(watch_context, default=str, separators=(",", ":")),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Compact Ops report JSON:\n" + json.dumps(prompt_safe_report, default=str, separators=(",", ":")),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        },
    ]
    if targeted_history:
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Targeted feed history JSON:\n" + json.dumps(targeted_history, default=str, separators=(",", ":")),
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        )
    if isinstance(selected_popup, dict):
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Selected popup JSON:\n" + json.dumps(selected_popup, default=str, separators=(",", ":")),
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        )
    messages.extend(_history_messages(chat_history))
    messages.append({"role": "user", "content": query})

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
    if report.get("display_payloads"):
        result["display_payloads"] = report.get("display_payloads")
    if targeted_history:
        result["ops_targeted_history"] = targeted_history
    if report.get("geojson"):
        result["geojson"] = report["geojson"]
    return result
