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


router = APIRouter()


LINK_COLUMNS = [
    "parent_loc_id",
    "child_loc_id",
    "link_type",
    "source",
    "confidence",
]


def _read_link_rows(links_path, column: str, loc_id: str) -> pd.DataFrame:
    if duckdb_available():
        return select_rows(
            links_path,
            columns=LINK_COLUMNS,
            exact_filters={column: loc_id},
        )
    return pd.read_parquet(links_path, columns=LINK_COLUMNS, filters=[(column, "==", loc_id)])


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
            children = _read_link_rows(links_path, "parent_loc_id", loc_id).copy()
            parents = _read_link_rows(links_path, "child_loc_id", loc_id).copy()
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
                    "event_id": _extract_event_id(related_loc_id),
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
