"""Cross-disaster relationship endpoints."""

from __future__ import annotations

import pandas as pd
import re
import json
from pathlib import Path
from fastapi import APIRouter, Query

from mapmover import logger
from mapmover.data_loading import get_source_path, load_catalog, load_source_metadata
from mapmover.duckdb_helpers import duckdb_available, is_cloud_mode, parquet_available, select_rows
from mapmover.paths import GLOBAL_DIR
from mapmover.runtime_config import get_runtime_config
from mapmover.storage_mode import get_runtime_mode
from mapmover.execution.event_loading import resolve_event_parquet_path_for_source

from .helpers import msgpack_error, msgpack_response
from .earthquakes import get_earthquake_property_builders
from .landslides import get_landslide_property_builders
from .tsunamis import get_tsunami_property_builders
from .volcanoes import get_eruption_property_builders


router = APIRouter()


LINK_COLUMNS = [
    "parent_loc_id",
    "child_loc_id",
    "parent_event_id",
    "child_event_id",
    "link_type",
    "source",
    "confidence",
]

EVENT_TABLES = {
    "earthquake": {
        "path": GLOBAL_DIR / "disasters/earthquakes/events.parquet",
        "builders": get_earthquake_property_builders,
    },
    "tsunami": {
        "path": GLOBAL_DIR / "disasters/tsunamis/events.parquet",
        "builders": get_tsunami_property_builders,
    },
    "volcano": {
        "path": GLOBAL_DIR / "disasters/volcanoes/events.parquet",
        "builders": get_eruption_property_builders,
    },
    "landslide": {
        "path": GLOBAL_DIR / "disasters/landslides/events.parquet",
        "builders": get_landslide_property_builders,
    },
}

MAX_CHAIN_DEPTH = 2
EXACT_EVENT_SOURCE_OVERRIDES = {
    "earthquakes_events": {"id_fields": ("event_id",), "metadata_source_id": "earthquakes_events"},
    "hurricanes": {
        "id_fields": ("storm_id", "event_id"),
        "parquet_path": GLOBAL_DIR / "disasters/hurricanes/events.parquet",
    },
    "volcanoes_events": {"id_fields": ("event_id",), "metadata_source_id": "volcanoes_events"},
    "tsunamis_events": {"id_fields": ("event_id",), "metadata_source_id": "tsunamis_events"},
    "tornadoes": {"id_fields": ("event_id",), "parquet_path": GLOBAL_DIR / "disasters/tornadoes/events.parquet"},
    "floods": {"id_fields": ("event_id",), "parquet_path": GLOBAL_DIR / "disasters/floods/events.parquet"},
    "landslides": {"id_fields": ("event_id",), "parquet_path": GLOBAL_DIR / "disasters/landslides/events.parquet"},
    "drought": {"id_fields": ("event_id",), "parquet_path": GLOBAL_DIR / "disasters/drought/events.parquet"},
}
LAT_FIELDS = ("lat", "latitude", "centroid_lat")
LON_FIELDS = ("lon", "longitude", "centroid_lon")
TIME_FIELDS = ("timestamp", "observed_at", "event_time", "start_time", "updated_at", "last_updated", "time", "date")
EXACT_EVENT_ID_RULES = [
    {"regex": re.compile(r"^ts\d{4,}$", re.IGNORECASE), "packs": ("tsunamis",), "strict": True},
    {"regex": re.compile(r"^ve\d{4,}$", re.IGNORECASE), "packs": ("volcanoes",), "strict": True},
    {"regex": re.compile(r"^(?:dfo|gfd)-\d+$", re.IGNORECASE), "packs": ("floods",), "strict": True},
    {"regex": re.compile(r"^\d{7}[ns]\d{5}$", re.IGNORECASE), "packs": ("hurricanes",), "strict": True},
    {"regex": re.compile(r"^can-\d+$", re.IGNORECASE), "packs": ("tornadoes",), "strict": True},
    {"regex": re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE), "packs": ("wildfires",), "strict": True},
    {"regex": re.compile(r"^[A-Z]{2}\d{17,20}$", re.IGNORECASE), "packs": ("wildfires",), "strict": True},
    {"regex": re.compile(r"^[A-Z]{2}(?:-[A-Z]{2})?-\d{4}-[A-Za-z0-9-]+$", re.IGNORECASE), "packs": ("wildfires",), "strict": True},
    {"regex": re.compile(r"(?:-torn-|tornado)", re.IGNORECASE), "packs": ("tornadoes",), "strict": True},
    {"regex": re.compile(r"^(?:us|ak|at|av|ci|hv|mb|nc|nm|nn|pr|pt|se|tx|uu|uw)[a-z0-9._-]{3,}$", re.IGNORECASE), "packs": ("earthquakes",), "strict": True},
    {"regex": re.compile(r"^(?:iscgem|iscgemsup|rusms|noaa-sig|gcmtc|gcmtb|official|cent|ld|eqh|cdmg|aacse|ismpkansas|ok|snm|wes|flag|ew|ott)", re.IGNORECASE), "packs": ("earthquakes",), "strict": True},
    {"regex": re.compile(r"(?:irwin|mtbs|-fire-)", re.IGNORECASE), "packs": ("wildfires",), "strict": True},
]


def _classify_exact_event_identifier(identifier_value: str) -> tuple[list[str], bool]:
    normalized = str(identifier_value or "").strip()
    if not normalized:
        return [], False

    for rule in EXACT_EVENT_ID_RULES:
        if rule["regex"].search(normalized):
            return list(rule["packs"]), bool(rule["strict"])

    if normalized.isdigit():
        return ["tornadoes", "wildfires"], False

    return ["wildfires"], False


def _infer_exact_event_pack_hints(identifier_value: str) -> list[str]:
    hints, _strict = _classify_exact_event_identifier(identifier_value)
    return hints


def _catalog_event_sources_for_pack(pack_id: str) -> list[dict]:
    normalized_pack_id = str(pack_id or "").strip().lower()
    if not normalized_pack_id:
        return []

    catalog = load_catalog() or {}
    candidates: list[dict] = []
    for source in catalog.get("sources", []):
        if not isinstance(source, dict):
            continue
        if str(source.get("pack_id") or "").strip().lower() != normalized_pack_id:
            continue
        if str(source.get("data_type") or "").strip().lower() != "events":
            continue

        source_id = str(source.get("source_id") or "").strip()
        if not source_id:
            continue

        override = EXACT_EVENT_SOURCE_OVERRIDES.get(source_id, {})
        path_text = str(source.get("path") or "").strip()
        path_parts = Path(path_text).parts if path_text else ()
        normalized_path = path_text.replace("\\", "/")
        event_type = str(
            source.get("event_type")
            or override.get("event_type")
            or normalized_pack_id.rstrip("s")
        ).strip().lower()

        candidate = {
            "pack_id": normalized_pack_id,
            "source_id": source_id,
            "event_type": event_type,
            "id_fields": tuple(override.get("id_fields") or ("event_id",)),
            "metadata_source_id": str(override.get("metadata_source_id") or source_id).strip(),
            "_path_depth": len(path_parts) if path_parts else 999,
            "_normalized_path": normalized_path,
        }
        if override.get("parquet_path"):
            candidate["parquet_path"] = override["parquet_path"]
        candidates.append(candidate)

    candidates.sort(
        key=lambda entry: (
            0 if "/sources/" not in str(entry.get("_normalized_path") or "") else 1,
            int(entry.get("_path_depth") or 999),
            str(entry.get("source_id") or ""),
        )
    )
    return candidates


def _get_exact_event_candidates(pack_id: str | None = None) -> list[dict]:
    if pack_id:
        return _catalog_event_sources_for_pack(pack_id)

    catalog = load_catalog() or {}
    pack_ids: list[str] = []
    seen_pack_ids: set[str] = set()
    for source in catalog.get("sources", []):
        if not isinstance(source, dict):
            continue
        if str(source.get("data_type") or "").strip().lower() != "events":
            continue
        candidate_pack_id = str(source.get("pack_id") or "").strip().lower()
        if not candidate_pack_id or candidate_pack_id in seen_pack_ids:
            continue
        seen_pack_ids.add(candidate_pack_id)
        pack_ids.append(candidate_pack_id)

    candidates: list[dict] = []
    for candidate_pack_id in pack_ids:
        candidates.extend(_catalog_event_sources_for_pack(candidate_pack_id))
    return candidates


def _resolve_exact_event_parquet(source_id: str):
    return resolve_event_parquet_path_for_source(
        source_id,
        "events",
        get_source_path_func=get_source_path,
        load_source_metadata_func=load_source_metadata,
        is_cloud_mode_func=is_cloud_mode,
    )


def _resolve_exact_event_parquet_for_candidate(candidate: dict):
    direct_path = candidate.get("parquet_path")
    if direct_path:
        return Path(direct_path), {}
    return _resolve_exact_event_parquet(str(candidate.get("source_id") or ""))


def _load_exact_event_metadata(candidate: dict) -> dict:
    metadata_source_id = str(candidate.get("metadata_source_id") or "").strip()
    if not metadata_source_id:
        return {}
    metadata = load_source_metadata(metadata_source_id)
    return metadata if isinstance(metadata, dict) else {}


def _find_first_present(row: dict, candidates: tuple[str, ...]):
    for field in candidates:
        value = row.get(field)
        if value is not None and not pd.isna(value):
            return value
    return None


def _parse_bbox_props(value) -> tuple[float, float, float, float] | None:
    if value is None or pd.isna(value):
        return None
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return None
    if not isinstance(parsed, (list, tuple)) or len(parsed) != 4:
        return None
    try:
        min_lon, min_lat, max_lon, max_lat = [float(v) for v in parsed]
    except Exception:
        return None
    return min_lon, min_lat, max_lon, max_lat


def _parse_track_coords(value) -> list[list[float]] | None:
    if value is None or pd.isna(value):
        return None
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return None
    if not isinstance(parsed, list) or len(parsed) < 2:
        return None
    coords: list[list[float]] = []
    for item in parsed:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            lon = float(item[0])
            lat = float(item[1])
        except Exception:
            continue
        coords.append([lon, lat])
    return coords if len(coords) >= 2 else None


def _build_exact_event_geometry(props: dict, event_type: str) -> dict | None:
    lat = _find_first_present(props, LAT_FIELDS)
    lon = _find_first_present(props, LON_FIELDS)
    if lat is not None and lon is not None:
        return {"type": "Point", "coordinates": [float(lon), float(lat)]}

    bbox = _parse_bbox_props(props.get("bbox"))
    if bbox is not None:
        min_lon, min_lat, max_lon, max_lat = bbox
        props.setdefault("bbox_min_lon", min_lon)
        props.setdefault("bbox_min_lat", min_lat)
        props.setdefault("bbox_max_lon", max_lon)
        props.setdefault("bbox_max_lat", max_lat)
        centroid_lon = (min_lon + max_lon) / 2.0
        centroid_lat = (min_lat + max_lat) / 2.0
        props.setdefault("centroid_lon", centroid_lon)
        props.setdefault("centroid_lat", centroid_lat)
        return {"type": "Point", "coordinates": [centroid_lon, centroid_lat]}

    if event_type == "hurricane":
        track_coords = _parse_track_coords(props.get("track_coords"))
        if track_coords:
            mid_index = max(0, len(track_coords) // 2)
            centroid_lon = float(track_coords[mid_index][0])
            centroid_lat = float(track_coords[mid_index][1])
            props.setdefault("centroid_lon", centroid_lon)
            props.setdefault("centroid_lat", centroid_lat)
            return {"type": "Point", "coordinates": [centroid_lon, centroid_lat]}

    return None


def _build_exact_event_feature(row: dict, event_type: str, source_id: str, pack_id: str, identifier_field: str, metadata: dict | None = None) -> dict | None:
    props = {}
    for key, value in row.items():
        if value is None or pd.isna(value):
            continue
        if hasattr(value, "item"):
            value = value.item()
        if isinstance(value, pd.Timestamp):
            value = value.isoformat()
        props[key] = value

    exact_value = str(props.get(identifier_field) or "").strip()
    if exact_value and "event_id" not in props:
        props["event_id"] = exact_value
    props["event_type"] = props.get("event_type") or event_type
    geometry = _build_exact_event_geometry(props, event_type)
    if geometry is None:
        return None
    metadata = metadata or {}
    source_name = str(metadata.get("source_name", source_id))
    source_url = str(metadata.get("source_url", ""))

    return {
        "type": "events",
        "data_type": "events",
        "source_id": source_id,
        "pack_id": pack_id,
        "event_type": event_type,
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": props,
                }
            ],
        },
        "count": 1,
        "summary": f"Showing {pack_id} event {props.get('event_id') or exact_value}",
        "sources": [{
            "id": source_id,
            "name": source_name,
            "url": source_url,
        }],
    }


def _query_exact_event(candidate: dict, identifier_field: str, identifier_value: str) -> pd.DataFrame:
    parquet_path, _metadata = _resolve_exact_event_parquet_for_candidate(candidate)
    variants = [identifier_value]
    if isinstance(identifier_value, str):
        lowered = identifier_value.lower()
        uppered = identifier_value.upper()
        for variant in (lowered, uppered):
            if variant not in variants:
                variants.append(variant)

    for variant in variants:
        df = select_rows(
            parquet_path,
            exact_filters={identifier_field: variant},
        )
        if not df.empty:
            return df

    return pd.DataFrame()


def _resolve_exact_event_payload(identifier_value: str, pack_id: str | None = None) -> dict | None:
    normalized_identifier = str(identifier_value or "").strip()
    if not normalized_identifier:
        return None

    if pack_id:
        normalized_pack = str(pack_id).strip().lower()
        candidates = _get_exact_event_candidates(normalized_pack)
    else:
        candidates = _get_exact_event_candidates()
        hinted_packs, strict_hint = _classify_exact_event_identifier(normalized_identifier)
        if hinted_packs:
            hinted_set = set(hinted_packs)
            if strict_hint:
                candidates = [entry for entry in candidates if entry["pack_id"] in hinted_set]
            else:
                candidates = sorted(
                    candidates,
                    key=lambda entry: (0 if entry["pack_id"] in hinted_set else 1, hinted_packs.index(entry["pack_id"]) if entry["pack_id"] in hinted_set else 999)
                )

    for candidate in candidates:
        source_id = candidate["source_id"]
        event_type = candidate["event_type"]
        metadata = _load_exact_event_metadata(candidate)
        for identifier_field in candidate["id_fields"]:
            try:
                df = _query_exact_event(candidate, identifier_field, normalized_identifier)
            except Exception as exc:
                logger.warning("Exact event lookup failed for %s.%s=%s: %s", source_id, identifier_field, normalized_identifier, exc)
                continue
            if df.empty:
                continue
            row = df.head(1).iloc[0].to_dict()
            payload = _build_exact_event_feature(
                row,
                event_type=event_type,
                source_id=source_id,
                pack_id=candidate["pack_id"],
                identifier_field=identifier_field,
                metadata=metadata,
            )
            if payload:
                return payload
    return None


def _read_link_rows(links_path, column: str, loc_id: str) -> pd.DataFrame:
    if duckdb_available():
        return select_rows(
            links_path,
            columns=LINK_COLUMNS,
            exact_filters={column: loc_id},
        )
    return pd.read_parquet(links_path, columns=LINK_COLUMNS, filters=[(column, "==", loc_id)])


def _normalize_link_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    if "parent_event_id" not in df.columns:
        df["parent_event_id"] = None
    if "child_event_id" not in df.columns:
        df["child_event_id"] = None
    if "parent_loc_id" in df.columns:
        mask = df["parent_event_id"].isna() | (df["parent_event_id"].astype(str).str.strip() == "")
        df.loc[mask, "parent_event_id"] = df.loc[mask, "parent_loc_id"].map(_extract_event_id)
    if "child_loc_id" in df.columns:
        mask = df["child_event_id"].isna() | (df["child_event_id"].astype(str).str.strip() == "")
        df.loc[mask, "child_event_id"] = df.loc[mask, "child_loc_id"].map(_extract_event_id)
    return df


def _extract_event_type(loc_id: str) -> str:
    parts = loc_id.split("-")
    if len(parts) < 2:
        return "unknown"

    type_code = parts[-2] if len(parts) >= 3 else parts[0]
    type_map = {
        "EQ": "earthquake",
        "TSUN": "tsunami",
        "VOLC": "volcano",
        "HRCN": "hurricane",
        "TORN": "tornado",
        "FIRE": "wildfire",
        "FLOOD": "flood",
        "LAND": "landslide",
    }
    return type_map.get(type_code, "unknown")


def _extract_event_id(loc_id: str) -> str:
    parts = loc_id.split("-")
    if len(parts) >= 3:
        for i, part in enumerate(parts):
            if part in ["EQ", "TSUN", "VOLC", "HRCN", "TORN", "FIRE", "FLOOD", "LAND"]:
                return "-".join(parts[i + 1 :])
    return parts[-1] if parts else loc_id


def _load_event_feature_by_loc_id(loc_id: str) -> dict | None:
    event_type = _extract_event_type(loc_id)
    config = EVENT_TABLES.get(event_type)
    if not config:
        return None

    events_path = config["path"]
    if not parquet_available(events_path):
        return None

    try:
        if duckdb_available():
            df = select_rows(events_path, exact_filters={"loc_id": loc_id})
        else:
            df = pd.read_parquet(events_path, filters=[("loc_id", "==", loc_id)])
    except Exception as exc:
        logger.warning("Failed resolving linked event %s from %s: %s", loc_id, events_path, exc)
        return None

    if df.empty:
        return None

    row_df = df.head(1).copy()
    if "year" not in row_df.columns and "timestamp" in row_df.columns:
        row_df["timestamp"] = pd.to_datetime(row_df["timestamp"], errors="coerce")
        row_df["year"] = row_df["timestamp"].dt.year

    row = row_df.iloc[0].to_dict()
    latitude = row.get("latitude")
    longitude = row.get("longitude")
    if pd.isna(latitude) or pd.isna(longitude):
        return None

    builders = config["builders"]()
    props = {name: builder(row) for name, builder in builders.items()}
    props["event_type"] = event_type
    props["loc_id"] = props.get("loc_id") or loc_id

    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [float(longitude), float(latitude)],
        },
        "properties": props,
    }


def _read_related_rows_for_loc_id(loc_id: str) -> pd.DataFrame:
    links_path = GLOBAL_DIR / "disasters/links.parquet"
    if not parquet_available(links_path):
        return pd.DataFrame(columns=LINK_COLUMNS + ["direction", "related_loc_id"])

    children = _normalize_link_rows(_read_link_rows(links_path, "parent_loc_id", loc_id).copy())
    parents = _normalize_link_rows(_read_link_rows(links_path, "child_loc_id", loc_id).copy())

    if children.empty or "parent_loc_id" not in children.columns:
        children = pd.DataFrame(columns=LINK_COLUMNS)
    children["direction"] = "triggered"
    children["related_loc_id"] = children["child_loc_id"]

    if parents.empty or "child_loc_id" not in parents.columns:
        parents = pd.DataFrame(columns=LINK_COLUMNS)
    parents["direction"] = "triggered_by"
    parents["related_loc_id"] = parents["parent_loc_id"]

    return pd.concat([children, parents], ignore_index=True)


def _build_chain_payload(root_loc_id: str, depth: int) -> dict:
    effective_depth = max(1, min(int(depth or 1), MAX_CHAIN_DEPTH))
    queue: list[tuple[str, int]] = [(root_loc_id, 0)]
    visited_nodes: set[str] = set()
    feature_by_loc_id: dict[str, dict] = {}
    chain_links: list[dict] = []
    seen_edges: set[tuple[str, str, str]] = set()

    while queue:
        current_loc_id, current_depth = queue.pop(0)
        if current_loc_id in visited_nodes:
            continue
        visited_nodes.add(current_loc_id)

        feature = _load_event_feature_by_loc_id(current_loc_id)
        if feature is not None:
            feature["properties"]["chain_depth"] = current_depth
            feature_by_loc_id[current_loc_id] = feature

        if current_depth >= effective_depth:
            continue

        related_rows = _read_related_rows_for_loc_id(current_loc_id)
        if related_rows.empty:
            continue

        for _, row in related_rows.iterrows():
            parent_loc_id = row.get("parent_loc_id")
            child_loc_id = row.get("child_loc_id")
            parent_event_id = row.get("parent_event_id") or _extract_event_id(str(parent_loc_id))
            child_event_id = row.get("child_event_id") or _extract_event_id(str(child_loc_id))
            link_type = row.get("link_type") or "linked"
            direction = row.get("direction") or "linked"
            related_loc_id = row.get("related_loc_id")
            if not parent_loc_id or not child_loc_id or not related_loc_id:
                continue

            edge_key = (str(parent_loc_id), str(child_loc_id), str(link_type))
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                chain_links.append(
                    {
                        "parent_loc_id": str(parent_loc_id),
                        "child_loc_id": str(child_loc_id),
                        "parent_event_id": str(parent_event_id) if parent_event_id else None,
                        "child_event_id": str(child_event_id) if child_event_id else None,
                        "related_loc_id": str(related_loc_id),
                        "link_type": str(link_type),
                        "direction": str(direction),
                        "source": row.get("source"),
                        "confidence": row.get("confidence"),
                    }
                )

            if related_loc_id not in visited_nodes:
                queue.append((str(related_loc_id), current_depth + 1))

    source_feature = feature_by_loc_id.get(root_loc_id)
    related_features = [
        feature
        for loc_id, feature in feature_by_loc_id.items()
        if loc_id != root_loc_id
    ]

    return {
        "source": source_feature,
        "features": [source_feature] + related_features if source_feature is not None else related_features,
        "links": chain_links,
        "depth": effective_depth,
        "count": len(related_features),
    }


@router.get("/api/events/related/{loc_id:path}")
async def get_related_events(loc_id: str):
    """Get related disaster events for a given event loc_id."""
    try:
        if not loc_id:
            return msgpack_response({"event_id": loc_id, "related": [], "count": 0, "message": "Missing event loc_id"})

        links_path = GLOBAL_DIR / "disasters/links.parquet"
        if not parquet_available(links_path):
            return msgpack_response({"event_id": loc_id, "related": [], "count": 0, "message": "Links data not available"})

        try:
            children = _normalize_link_rows(_read_link_rows(links_path, "parent_loc_id", loc_id).copy())
            parents = _normalize_link_rows(_read_link_rows(links_path, "child_loc_id", loc_id).copy())
        except Exception as exc:
            runtime_mode = get_runtime_mode(get_runtime_config().get("runtime_mode", "local"))
            if runtime_mode == "cloud":
                logger.warning("Related events links parquet unavailable in cloud runtime: %s", exc)
                return msgpack_response(
                    {
                        "event_id": loc_id,
                        "related": [],
                        "count": 0,
                        "message": "Related-disaster links are not available in the published runtime data.",
                    }
                )
            raise

        if children.empty or "parent_loc_id" not in children.columns:
            children = pd.DataFrame(columns=LINK_COLUMNS)
        children["direction"] = "triggered"
        children["related_loc_id"] = children["child_loc_id"]

        if parents.empty or "child_loc_id" not in parents.columns:
            parents = pd.DataFrame(columns=LINK_COLUMNS)
        parents["direction"] = "triggered_by"
        parents["related_loc_id"] = parents["parent_loc_id"]

        related = pd.concat([children, parents], ignore_index=True)
        if len(related) == 0:
            return msgpack_response({"event_id": loc_id, "related": [], "count": 0, "message": "No related disasters found for this event in links.parquet"})

        related_list = []
        for _, row in related.iterrows():
            related_loc_id = row["related_loc_id"]
            related_list.append(
                {
                    "loc_id": related_loc_id,
                    "event_id": (
                        row.get("child_event_id") if row["direction"] == "triggered" else row.get("parent_event_id")
                    ) or _extract_event_id(related_loc_id),
                    "event_type": _extract_event_type(related_loc_id),
                    "link_type": row["link_type"],
                    "direction": row["direction"],
                    "source": row["source"],
                    "confidence": row["confidence"],
                }
            )

        type_counts = {}
        for item in related_list:
            event_type = item["event_type"]
            type_counts[event_type] = type_counts.get(event_type, 0) + 1

        return msgpack_response(
            {
                "event_id": loc_id,
                "related": related_list,
                "count": len(related_list),
                "by_type": type_counts,
                "message": None,
            }
        )
    except Exception as e:
        logger.error(f"Error fetching related events for {loc_id}: {e}")
        return msgpack_error(str(e), 500)


@router.get("/api/events/by-loc/{loc_id:path}")
async def get_event_by_loc_id(loc_id: str):
    """Resolve a linked disaster event into a map-ready feature using canonical loc_id."""
    try:
        if not loc_id:
            return msgpack_error("Missing event loc_id", 400)

        feature = _load_event_feature_by_loc_id(loc_id)
        if feature is None:
            return msgpack_error(f"Linked event {loc_id} could not be resolved", 404)

        return msgpack_response(
            {
                "type": "FeatureCollection",
                "features": [feature],
                "event_type": feature["properties"].get("event_type"),
                "loc_id": loc_id,
            }
        )
    except Exception as e:
        logger.error(f"Error resolving linked event {loc_id}: {e}")
        return msgpack_error(str(e), 500)


@router.get("/api/events/exact/{event_id:path}")
async def get_event_by_exact_id(event_id: str, pack_id: str | None = Query(default=None)):
    """Resolve one stable event id across canonical event sources."""
    try:
        if not event_id:
            return msgpack_error("Missing event id", 400)

        payload = _resolve_exact_event_payload(event_id, pack_id=pack_id)
        if payload is None:
            scope_text = f" in pack {pack_id}" if pack_id else ""
            return msgpack_error(f"Event {event_id} was not found{scope_text}", 404)

        return msgpack_response(payload)
    except Exception as e:
        logger.error(f"Error resolving exact event {event_id}: {e}")
        return msgpack_error(str(e), 500)


@router.get("/api/events/chain/{loc_id:path}")
async def get_related_event_chain(loc_id: str, depth: int = 1):
    """Resolve a linked disaster chain into map-ready features and edges."""
    try:
        if not loc_id:
            return msgpack_error("Missing event loc_id", 400)

        payload = _build_chain_payload(loc_id, depth)
        if payload["source"] is None:
            return msgpack_error(f"Linked event {loc_id} could not be resolved", 404)

        return msgpack_response(
            {
                "type": "FeatureCollection",
                "features": payload["features"],
                "source": payload["source"],
                "links": payload["links"],
                "depth": payload["depth"],
                "count": payload["count"],
                "loc_id": loc_id,
            }
        )
    except Exception as e:
        logger.error(f"Error building linked event chain for {loc_id}: {e}")
        return msgpack_error(str(e), 500)
