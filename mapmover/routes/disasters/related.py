"""Cross-disaster relationship endpoints."""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter

from mapmover import logger
from mapmover.duckdb_helpers import duckdb_available, parquet_available, select_rows
from mapmover.paths import GLOBAL_DIR
from mapmover.runtime_config import get_runtime_config
from mapmover.storage_mode import get_runtime_mode

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
