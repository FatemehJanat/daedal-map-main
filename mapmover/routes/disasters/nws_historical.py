"""Admin/local-only WIP historical NWS alert frames."""
from functools import lru_cache
import json
from pathlib import Path
import re

import pandas as pd
from fastapi import APIRouter, Request

from mapmover.auth_context import get_authenticated_user
from mapmover.catalog_surface import request_can_use_wip_catalog
from mapmover.geometry_handlers import get_selection_geometries
from mapmover.paths import GLOBAL_DIR
from .helpers import msgpack_error, msgpack_response

router = APIRouter()
EVENTS = GLOBAL_DIR / "disasters" / "nws_alerts" / "events.parquet"
YEARLY_TEXT_ROOT = GLOBAL_DIR / "disasters" / "nws_alerts" / "text_hydration" / "yearly"
_events_df: pd.DataFrame | None = None
_history_payloads: dict[tuple[int, int], dict] = {}
_PRODUCT_ID_RE = re.compile(r"^(?P<year>\d{4})\d{8}-[A-Z0-9-]+$")


def _available_years() -> list[int]:
    """Discover hydrated yearly artifacts without a manually maintained cap."""
    if not YEARLY_TEXT_ROOT.exists():
        return []
    years = []
    for path in YEARLY_TEXT_ROOT.glob("*_finished.parquet"):
        match = re.fullmatch(r"(\d{4})_finished\.parquet", path.name)
        if match:
            years.append(int(match.group(1)))
    return sorted(set(years))


def _load_events() -> pd.DataFrame:
    """Keep the compact event index resident; bulletin text remains on disk."""
    global _events_df
    if _events_df is None:
        _events_df = pd.read_parquet(EVENTS)
        _events_df["_start_at"] = pd.to_datetime(_events_df["start_time"], utc=True, errors="coerce")
        _events_df["_end_at"] = pd.to_datetime(_events_df["end_time"], utc=True, errors="coerce")
    return _events_df


def _event_properties(row: dict) -> dict:
    """Return the popup-safe fields shared by single-frame and full-history APIs."""
    fields = (
        "event_id", "product_id", "event", "headline", "description", "instruction", "area",
        "expires", "certainty", "status", "message_type", "sender_name",
        "urgency", "severity", "is_emergency", "start_time", "end_time",
        "affected_area_names", "source_product_url", "phenomenon_code",
    )
    props = {
        key: value
        for key in fields
        if (value := row.get(key)) is not None
        and not (isinstance(value, float) and pd.isna(value))
    }
    # The VTEC geometry archive calls this affected_area_names; normalize it
    # to the live feed's popup contract without duplicating county geometry.
    if not props.get("area") and props.get("affected_area_names"):
        props["area"] = "\n".join(
            part.strip()
            for part in str(props["affected_area_names"]).split("|")
            if part.strip()
        )
    return props


@lru_cache(maxsize=512)
def _load_yearly_text(product_id: str) -> dict:
    """Return one hydrated bulletin without preloading annual text into playback."""
    match = _PRODUCT_ID_RE.fullmatch(product_id)
    if not match:
        return {"product_id": product_id, "fetch_status": "invalid"}
    year = int(match.group("year"))
    path = YEARLY_TEXT_ROOT / f"{year}_finished.parquet"
    if year not in _available_years() or not path.exists():
        return {"product_id": product_id, "fetch_status": "not_materialized"}
    columns = ["product_id", "headline", "description", "instruction", "area", "fetch_status"]
    frame = pd.read_parquet(path, columns=columns, filters=[("product_id", "=", product_id)])
    if frame.empty:
        return {"product_id": product_id, "fetch_status": "missing"}
    row = frame.iloc[0].to_dict()
    return {
        key: ("" if value is None or (isinstance(value, float) and pd.isna(value)) else value)
        for key, value in row.items()
    }


@router.get("/api/wip/nws-alerts/availability")
async def historical_nws_alert_availability(req: Request):
    """Return years whose completed text artifacts are ready for local playback."""
    if not request_can_use_wip_catalog(req, get_authenticated_user(req)):
        return msgpack_error("WIP catalog access is limited to admin accounts.", 403)
    years = _available_years()
    if not years:
        return msgpack_error("No completed historical NWS yearly artifacts are installed.", 404)
    return msgpack_response({"available_years": years, "newest_year": years[-1]})


@router.get("/api/wip/nws-alerts")
async def active_historical_nws_alerts(req: Request, at: str):
    """Return one historical NWS frame; never available to public callers."""
    if not request_can_use_wip_catalog(req, get_authenticated_user(req)):
        return msgpack_error("WIP catalog access is limited to admin accounts.", 403)
    if not EVENTS.exists():
        return msgpack_error("Historical NWS WIP data is not installed.", 404)
    moment = pd.to_datetime(at, utc=True, errors="coerce")
    if pd.isna(moment):
        return msgpack_error("at must be an ISO timestamp", 400)
    df = _load_events()
    active = df[(df["_start_at"] <= moment) & (df["_end_at"] > moment)].copy()
    needed = sorted({loc for value in active.get("affected_loc_ids", []) for loc in str(value or "").split("|") if loc})
    county = get_selection_geometries(needed) if needed else {"features": []}
    county_by_id = {(f.get("properties") or {}).get("loc_id"): f.get("geometry") for f in county.get("features", [])}
    features = []
    for row in active.to_dict("records"):
        # Cached frame columns are pandas Timestamps. They are query helpers,
        # not source data, and MessagePack cannot serialize them.
        props = _event_properties(row)
        props.update({"alert_id": row["event_id"], "severity": "Extreme" if row.get("is_emergency") else "Severe", "urgency": "Immediate"})
        raw = row.get("native_geometry_geojson")
        if raw:
            features.append({"type": "Feature", "geometry": json.loads(raw), "properties": {**props, "display": "polygon"}})
        else:
            for loc_id in str(row.get("affected_loc_ids") or "").split("|"):
                if county_by_id.get(loc_id):
                    features.append({"type": "Feature", "geometry": county_by_id[loc_id], "properties": {**props, "display": "county"}})
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(row["longitude"]), float(row["latitude"])]}, "properties": {**props, "display": "marker"}})
    return msgpack_response({"type": "FeatureCollection", "features": features, "active_alert_count": len(active)})


@router.get("/api/wip/nws-alerts/history")
async def historical_nws_alerts(req: Request, start_year: int = 2025, end_year: int = 2025):
    """Return one selected local playback range, with shared counties deduplicated."""
    if not request_can_use_wip_catalog(req, get_authenticated_user(req)):
        return msgpack_error("WIP catalog access is limited to admin accounts.", 403)
    if not EVENTS.exists():
        return msgpack_error("Historical NWS WIP data is not installed.", 404)
    available_years = _available_years()
    if not available_years:
        return msgpack_error("No completed historical NWS yearly artifacts are installed.", 404)
    start_year, end_year = sorted((start_year, end_year))
    requested_years = set(range(start_year, end_year + 1))
    if not requested_years.issubset(available_years):
        return msgpack_error("Requested NWS history includes a year that is not materialized yet.", 404)
    cache_key = (start_year, end_year)
    if cache_key not in _history_payloads:
        df = _load_events()
        range_start = pd.Timestamp(f"{start_year}-01-01T00:00:00Z")
        range_end = pd.Timestamp(f"{end_year + 1}-01-01T00:00:00Z")
        frame = df[(df["_start_at"] < range_end) & (df["_end_at"] >= range_start)]
        needed = sorted({
            loc
            for value in frame.get("affected_loc_ids", [])
            for loc in str(value or "").split("|")
            if loc
        })
        county = get_selection_geometries(needed) if needed else {"features": []}
        counties = {
            str((feature.get("properties") or {}).get("loc_id")): feature.get("geometry")
            for feature in county.get("features", [])
            if (feature.get("properties") or {}).get("loc_id") and feature.get("geometry")
        }
        events = []
        for row in frame.to_dict("records"):
            starts_at = row.get("_start_at")
            ends_at = row.get("_end_at")
            if pd.isna(starts_at) or pd.isna(ends_at):
                continue
            raw_geometry = row.get("native_geometry_geojson")
            events.append({
                "id": str(row.get("event_id") or ""),
                "start": int(starts_at.timestamp() * 1000),
                "end": int(ends_at.timestamp() * 1000),
                "point": [float(row["longitude"]), float(row["latitude"])],
                "geometry": json.loads(raw_geometry) if raw_geometry else None,
                "county_ids": [loc for loc in str(row.get("affected_loc_ids") or "").split("|") if loc],
                "properties": _event_properties(row),
            })
        _history_payloads[cache_key] = {
            "events": events,
            "counties": counties,
            "start": int(range_start.timestamp() * 1000),
            "end": int((range_end - pd.Timedelta(milliseconds=1)).timestamp() * 1000),
            "available_years": available_years,
        }
    return msgpack_response(_history_payloads[cache_key])


@router.get("/api/wip/nws-alerts/text")
async def historical_nws_alert_text(req: Request, product_id: str):
    """Load one historical bulletin's parsed text when its popup is opened."""
    if not request_can_use_wip_catalog(req, get_authenticated_user(req)):
        return msgpack_error("WIP catalog access is limited to admin accounts.", 403)
    product_id = str(product_id or "").strip()
    if not _PRODUCT_ID_RE.fullmatch(product_id):
        return msgpack_error("Invalid NWS product ID.", 400)
    try:
        return msgpack_response(_load_yearly_text(product_id))
    except Exception:
        return msgpack_error("Historical NWS bulletin text is unavailable.", 500)
