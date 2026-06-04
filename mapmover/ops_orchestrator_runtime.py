"""Lane-owned Ops orchestrator runtime helpers."""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import timezone
from functools import lru_cache
from pathlib import Path

from mapmover.geometry_handlers import get_selection_geometries
from mapmover.runtime.orchestrator_threading import run_catalog_scoped_to_thread

try:
    import boto3
except ImportError:
    boto3 = None


PRIVATE_ROOT = Path(__file__).resolve().parents[2] / "county-map-private"
OPS_STATE_ROOT = PRIVATE_ROOT / "live" / "state"
REFERENCE_ROOT = Path(__file__).resolve().parent / "reference"
CURRENCY_MAP_PATH = REFERENCE_ROOT / "country_currency_map.csv"

FEED_ALIASES = {
    "earthquakes": ("earthquake", "earthquakes", "quake", "quakes", "seismic"),
    "currency": ("currency", "currencies", "fx", "exchange rate", "exchange rates", "usd"),
    "tsunamis": ("tsunami", "tsunamis", "runup", "runups"),
    "volcanoes": ("volcano", "volcanoes", "eruption", "eruptions", "vei"),
    "wildfires_us_nifc": ("wildfire", "wildfires", "fire", "fires", "nifc"),
    "hurricanes_ibtracs_nrt": ("hurricane", "hurricanes", "storm", "storms", "cyclone", "typhoon", "ibtracs"),
}

COUNT_QUERY_PATTERNS = (
    r"\bhow many\b",
    r"\bnumber of\b",
    r"\bcount of\b",
    r"\bcount\b",
)

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
        return {
            "feed": feed,
            "collector_status": "missing",
            "history_entry_count": len(history_entries),
            "history_available": bool(history_entries),
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


def build_ops_report(*, watch: dict, effective_feeds: list[str]) -> dict:
    feed_snapshots: list[dict] = []
    recent_change_index: list[dict] = []
    geojson = None
    snapshot_hashes: dict[str, str] = {}
    snapshots_by_feed: dict[str, dict] = {}

    for feed in effective_feeds:
        snapshot = load_current_state_snapshot(feed)
        history_entries = load_current_state_history(feed)
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


def _feed_display_name(feed: str) -> str:
    names = {
        "wildfires_us_nifc": "wildfires",
        "hurricanes_ibtracs_nrt": "storms",
        "earthquakes": "earthquakes",
        "tsunamis": "tsunamis",
        "volcanoes": "volcanoes",
        "currency": "currencies",
        "noaa_aurora": "aurora forecast cells",
        "noaa_swpc": "space weather alerts",
    }
    return names.get(feed, feed.replace("_", " "))


def _feed_status_time(snapshot: dict) -> str | None:
    for key in ("last_changed_at", "fetched_at", "last_checked_at"):
        value = str(snapshot.get(key) or "").strip()
        if value:
            return value
    return None


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
    forecast_time = str(summary.get("forecast_time") or "").strip()
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


def _try_direct_ops_answer(*, query: str, report: dict, watch: dict, effective_feeds: list[str]) -> str | None:
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

    report = build_ops_report(watch=watch, effective_feeds=effective_feeds)
    if isinstance(getattr(cache, "map_state", None), dict):
        cache.map_state["ops_report"] = report

    direct_answer = _try_direct_ops_answer(
        query=query,
        report=report,
        watch=watch,
        effective_feeds=effective_feeds,
    )
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
    targeted_history = build_targeted_history_context(
        query=query,
        effective_feeds=effective_feeds,
        report=report,
        hints=hints,
    )
    prompt_safe_report = _build_prompt_safe_ops_report(report)
    system_prompt = ops_orchestrator.build_system_prompt(watch_context=watch_context, hints=hints)
    system_blocks = ops_orchestrator.build_system_prompt_blocks(system_prompt)
    llm_selection = ops_orchestrator.llm_selection()
    client = ops_orchestrator.build_client(llm_selection)

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
    selected_popup: dict | None = None,
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
        selected_popup=selected_popup,
    )
