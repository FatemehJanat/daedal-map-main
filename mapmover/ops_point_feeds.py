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


def build_cached_point_overlay(overlay_id: str) -> dict:
    """Response-cached GeoJSON point overlay for a registered live point feed."""
    spec = POINT_FEEDS.get(str(overlay_id or "").strip())
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
