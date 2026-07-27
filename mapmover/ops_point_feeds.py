"""
Live point-feed Ops overlays (location with updating data).

Reusable backend for Ops map overlays whose collector snapshot carries a list of
fixed locations, each with current readings -- ocean buoys, weather stations,
sensors, points of interest. One generic builder + a per-feed registry entry, so
adding the next station feed is config, not code.

A point feed is a Type B (live_only) collector whose snapshot payload_summary
holds `items_key` -> [ {lat_key, lon_key, ...props} ]. The builder reads that
collector's current-state snapshot, shapes a GeoJSON FeatureCollection of points,
and caches it on snapshot identity (rebuilds once per collector poll, not per
read). Served generically via GET /api/ops/points/{overlay_id}.

See county-map-private/docs/CLIMATE_DISPLAY.md (Live Point Feeds).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Optional

from mapmover.ops_ticker import (
    get_cached_live_snapshot,
    _get_cached_view,
    _snapshot_identity,
)

_POINT_FEED_CACHE_TTL_SECONDS = 60.0


@dataclass(frozen=True)
class PointFeedSpec:
    """How to turn one collector's snapshot into a GeoJSON point overlay."""
    collector: str                       # collector name (snapshot source)
    items_key: str                       # payload_summary key holding the point list
    lat_key: str = "lat"
    lon_key: str = "lon"
    property_keys: tuple[str, ...] = field(default_factory=tuple)  # props to carry per point
    row_schema: tuple[str, ...] = field(default_factory=tuple)  # compact collector rows, when used
    wip_only: bool = False


# Registry of live point feeds. Add an entry to surface a new station/sensor feed.
POINT_FEEDS: dict[str, PointFeedSpec] = {
    "buoys": PointFeedSpec(
        collector="noaa_ndbc",
        items_key="buoys",
        lat_key="lat",
        lon_key="lon",
        property_keys=("station_id", "sst_c", "air_c", "wave_m", "wind_mps", "obs_utc"),
    ),
    "airnow": PointFeedSpec(
        collector="airnow",
        items_key="reporting_areas",
        lat_key="lat",
        lon_key="lon",
        property_keys=(
            "reporting_area", "state", "parameter", "aqi", "category", "observed_at",
            "agency", "action_day",
        ),
        row_schema=(
            "reporting_area", "state", "parameter", "aqi", "category", "lat", "lon",
            "observed_at", "agency", "action_day",
        ),
        wip_only=True,
    ),
    "openaq": PointFeedSpec(
        collector="openaq", items_key="samples",
        property_keys=("location_id", "station_name", "locality", "country", "provider", "owner", "license", "is_mobile", "measurements", "observed_at"),
        row_schema=("location_id", "station_name", "locality", "country", "provider", "owner", "license", "is_mobile", "lat", "lon", "measurements", "observed_at"),
        wip_only=True,
    ),
}


def is_point_feed(overlay_id: str) -> bool:
    return str(overlay_id or "").strip() in POINT_FEEDS


def _assemble_points_geojson(spec: PointFeedSpec, summary: dict) -> dict:
    items = summary.get(spec.items_key) or []
    features = []
    for item in items:
        if not isinstance(item, dict) and spec.row_schema and isinstance(item, (list, tuple)):
            item = dict(zip(spec.row_schema, item))
        if not isinstance(item, dict):
            continue
        lat = item.get(spec.lat_key)
        lon = item.get(spec.lon_key)
        if lat is None or lon is None:
            continue
        props = {key: item.get(key) for key in spec.property_keys}
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })
    return {"type": "FeatureCollection", "features": features, "count": len(features)}


def build_cached_point_overlay(
    overlay_id: str,
    *,
    bbox: Optional[tuple[float, float, float, float]] = None,
    zoom: Optional[float] = None,
) -> dict:
    """Response-cached GeoJSON point overlay for a registered live point feed."""
    overlay_id = str(overlay_id or "").strip()
    if overlay_id == "air_quality_stations":
        return _visible_air_quality_stations(_build_air_quality_stations(), bbox=bbox, zoom=zoom)
    spec = POINT_FEEDS.get(overlay_id)
    if spec is None:
        return {"type": "FeatureCollection", "features": [], "count": 0}
    snap = get_cached_live_snapshot(spec.collector)
    snapshot = snap if isinstance(snap, dict) else {}

    def _builder() -> dict:
        return _assemble_points_geojson(spec, snapshot.get("payload_summary") or {})

    return _get_cached_view(
        f"ops_points_{overlay_id}",
        cache_identity=_snapshot_identity(snapshot),
        ttl_seconds=_POINT_FEED_CACHE_TTL_SECONDS,
        builder=_builder,
    )


def _aqi_color(value) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "#9aa4bf"
    for threshold, color in ((301, "#7e0023"), (201, "#8f3f97"), (151, "#ff0000"), (101, "#ff7e00"), (51, "#ffff00")):
        if value >= threshold:
            return color
    return "#00e400"


def _build_air_quality_stations() -> dict:
    """One selector family, with source-native point semantics preserved."""
    airnow = get_cached_live_snapshot("airnow") or {}
    openaq = get_cached_live_snapshot("openaq") or {}
    identity = json.dumps([_snapshot_identity(airnow), _snapshot_identity(openaq)])

    def _builder() -> dict:
        features = []
        for feature in _assemble_points_geojson(POINT_FEEDS["airnow"], airnow.get("payload_summary") or {}).get("features") or []:
            props = feature["properties"]
            props.update({"source_label": "AirNow", "station_name": props.get("reporting_area"), "station_kind": "Agency reporting area", "value": props.get("aqi"), "unit": "AQI", "provider": props.get("agency"), "marker_color": _aqi_color(props.get("aqi")), "source_url": "https://www.airnow.gov/"})
            features.append(feature)
        for feature in _assemble_points_geojson(POINT_FEEDS["openaq"], openaq.get("payload_summary") or {}).get("features") or []:
            props = feature["properties"]
            props.update({"source_label": "OpenAQ", "station_kind": "Monitor (six-pollutant WIP index)", "marker_color": "#6a5acd", "source_url": "https://openaq.org/"})
            features.append(feature)
        return {"type": "FeatureCollection", "features": features, "count": len(features), "total_count": len(features)}

    return _get_cached_view("ops_points_air_quality_stations", cache_identity=identity,
                            ttl_seconds=_POINT_FEED_CACHE_TTL_SECONDS, builder=_builder)


def _in_bbox(lon: float, lat: float, bbox: Optional[tuple[float, float, float, float]]) -> bool:
    if bbox is None:
        return True
    west, south, east, north = bbox
    if not south <= lat <= north:
        return False
    # A bounds box crossing the antimeridian has west > east.
    return west <= lon <= east if west <= east else lon >= west or lon <= east


def _visible_air_quality_stations(base: dict, *, bbox, zoom) -> dict:
    """Viewport-filter the WIP station index without changing point meaning.

    The source points are already deduplicated by their native identity. Keep
    them individually clickable during WIP display QA; a future clustering
    design must expose an aggregate-specific popup rather than borrowing one
    member's AQI or readings.
    """
    visible = []
    for feature in base.get("features") or []:
        try:
            lon, lat = feature["geometry"]["coordinates"]
            lon, lat = float(lon), float(lat)
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if _in_bbox(lon, lat, bbox):
            visible.append(feature)
    return {"type": "FeatureCollection", "features": visible, "count": len(visible), "total_count": base.get("count", 0), "merged": False}
