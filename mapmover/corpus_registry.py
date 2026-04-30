"""Research corpus artifact registry.

The registry is the contract between Explore-loaded data and Research mode. It stores
compact artifact metadata for each successful order result while leaving raw data in the
existing order/session cache.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from typing import Any

from mapmover.data_loading import load_source_metadata


def _stable_hash(value: Any) -> str:
    try:
        payload = json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        payload = str(value)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()[:12]


def _clean_list(values) -> list:
    result = []
    for value in values or []:
        if value is None:
            continue
        text = str(value)
        if text and text not in result:
            result.append(text)
    return result


def _source_name_from_response(source_id: str | None, response: dict) -> str | None:
    for source in response.get("sources") or []:
        if source.get("id") == source_id:
            return source.get("name") or source_id
    return source_id


def _collect_geojson_fields(response: dict) -> list:
    features = ((response.get("geojson") or {}).get("features") or [])[:25]
    fields = []
    for feature in features:
        for key in (feature.get("properties") or {}).keys():
            if key not in fields:
                fields.append(key)
    return fields


def _collect_year_data_fields(response: dict) -> list:
    time_field = str(response.get("time_field") or "year").strip() or "year"
    fields = ["loc_id", time_field]
    for loc_map in (response.get("year_data") or {}).values():
        for metrics in (loc_map or {}).values():
            for key in (metrics or {}).keys():
                if key not in fields:
                    fields.append(key)
    return fields


def _collect_order_metrics(order: dict, response: dict) -> list:
    metrics = []
    for item in order.get("items") or []:
        metric = item.get("metric_label") or item.get("metric")
        if metric and metric not in metrics:
            metrics.append(metric)
    for metric in response.get("available_metrics") or []:
        if metric and metric not in metrics:
            metrics.append(metric)
    metric_key = response.get("metric_key")
    if metric_key and metric_key not in metrics:
        metrics.append(metric_key)
    return metrics


def _collect_year_range(order: dict, response: dict):
    response_range = response.get("year_range")
    if isinstance(response_range, dict):
        min_year = response_range.get("min")
        max_year = response_range.get("max")
        if min_year is not None or max_year is not None:
            return {"min": min_year, "max": max_year, "available_years": response_range.get("available_years", [])}
    if isinstance(response_range, list) and response_range:
        cleaned = [value for value in response_range if value is not None]
        if cleaned:
            return {"min": cleaned[0], "max": cleaned[-1], "available_years": cleaned[:50]}
    years = []
    for item in order.get("items") or []:
        for key in ("year", "year_start", "year_end"):
            value = item.get(key)
            if isinstance(value, int):
                years.append(value)
    if years:
        return {"min": min(years), "max": max(years), "available_years": sorted(set(years))}
    return None


def _build_scope(order: dict, response: dict) -> dict:
    items = order.get("items") or []
    return {
        "regions": _clean_list(item.get("region") for item in items),
        "geographic_level": response.get("geographic_level") or next((item.get("geo_level") for item in items if item.get("geo_level")), None),
        "filters": [deepcopy(item.get("filters")) for item in items if item.get("filters")],
        "year_range": _collect_year_range(order, response),
    }


def _extract_source_runtime_hints(source_id: str | None) -> dict:
    if not source_id:
        return {}
    metadata = load_source_metadata(source_id) or {}
    raster_products = metadata.get("raster_products") or {}
    scene_rasters = raster_products.get("scene_rasters") or {}
    loc_id_clips = raster_products.get("loc_id_clips") or {}
    hints = {}

    scenes = scene_rasters.get("scenes") or []
    if scenes:
        hints["scene_periods"] = [
            {
                "period": scene.get("period"),
                "year": scene.get("year"),
            }
            for scene in scenes[:12]
            if scene.get("period")
        ]

    supported_levels = loc_id_clips.get("supported_levels") or {}
    if supported_levels:
        hints["raster_clip_levels"] = list(supported_levels.keys())
        hints["supports_loc_id_raster_clips"] = True

    if scene_rasters:
        hints["supports_scene_rasters"] = True

    return hints


class CorpusRegistry:
    """In-memory research artifact registry keyed by authenticated session id."""

    def __init__(self):
        self._sessions: dict[str, dict[str, dict]] = {}
        self._saved_corpora: dict[str, dict] = {}

    def register_order_result(
        self,
        *,
        session_id: str,
        request_key: str,
        order: dict,
        response: dict,
    ) -> dict | None:
        if not session_id or not request_key or not order or not response:
            return None
        if response.get("type") == "error" or response.get("action") == "remove":
            return None
        if response.get("type") not in {"data", "events", "mixed_order"} and not response.get("geojson"):
            return None

        artifacts = self._sessions.setdefault(session_id, {})
        if response.get("type") == "mixed_order":
            registered = None
            for idx, result in enumerate(response.get("results") or []):
                child_key = f"{request_key}:{idx}"
                registered = self.register_order_result(
                    session_id=session_id,
                    request_key=child_key,
                    order=order,
                    response=result,
                ) or registered
            return registered

        items = order.get("items") or []
        source_id = response.get("source_id") or next((item.get("source_id") for item in items if item.get("source_id")), None)
        data_type = response.get("data_type") or response.get("type") or "data"
        fields = _collect_year_data_fields(response) if response.get("year_data") else _collect_geojson_fields(response)
        metrics = _collect_order_metrics(order, response)
        year_range = _collect_year_range(order, response)
        artifact_id = f"artifact_{_stable_hash({'session': session_id, 'request': request_key, 'source': source_id, 'metrics': metrics})}"

        artifact = {
            "artifact_id": artifact_id,
            "session_id": session_id,
            "request_key": request_key,
            "source_id": source_id,
            "source_name": _source_name_from_response(source_id, response),
            "data_type": data_type,
            "time_field": response.get("time_field"),
            "region": next((item.get("region") for item in items if item.get("region")), None),
            "geographic_level": response.get("geographic_level") or response.get("overlay_type"),
            "metrics": metrics,
            "year_range": year_range,
            "feature_count": len(((response.get("geojson") or {}).get("features") or [])),
            "row_count": response.get("count"),
            "fields": fields,
            "summary": response.get("summary") or order.get("summary") or "",
            "loaded_scope": _build_scope(order, response),
            "view_scope": None,
            "order": deepcopy(order),
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        artifact.update(_extract_source_runtime_hints(source_id))
        artifacts[artifact_id] = artifact
        return deepcopy(artifact)

    def manifest(self, session_id: str) -> dict:
        artifacts = list(self._sessions.get(session_id, {}).values())
        return {
            "session_id": session_id,
            "mode": "research",
            "artifact_count": len(artifacts),
            "artifacts": [self._public_artifact(a) for a in artifacts],
            "saved_corpus": deepcopy(self._saved_corpora.get(session_id)),
            "focus": {
                "active_geographies": [],
                "active_question": None,
            },
        }

    def get_artifact(self, session_id: str, artifact_id: str) -> dict | None:
        artifact = self._sessions.get(session_id, {}).get(artifact_id)
        return deepcopy(artifact) if artifact else None

    def list_artifacts(self, session_id: str) -> list[dict]:
        return [self._public_artifact(a) for a in self._sessions.get(session_id, {}).values()]

    def export_session_artifacts(self, session_id: str) -> list[dict]:
        return [self._public_artifact(artifact) for artifact in self._sessions.get(session_id, {}).values()]

    def import_session_artifacts(self, session_id: str, artifacts: list[dict] | None) -> None:
        if not session_id:
            return
        restored: dict[str, dict] = {}
        for artifact in artifacts or []:
            if not isinstance(artifact, dict):
                continue
            artifact_id = str(artifact.get("artifact_id") or "").strip()
            if not artifact_id:
                continue
            restored[artifact_id] = deepcopy(artifact)
        if restored:
            self._sessions[session_id] = restored
        else:
            self._sessions.pop(session_id, None)

    def clear_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._saved_corpora.pop(session_id, None)

    def clear_all(self) -> dict[str, int]:
        artifact_sessions = len(self._sessions)
        saved_corpora = len(self._saved_corpora)
        self._sessions = {}
        self._saved_corpora = {}
        return {
            "artifact_sessions": artifact_sessions,
            "saved_corpora": saved_corpora,
        }

    def clear_artifacts(self, session_id: str) -> None:
        if not session_id:
            return
        self._sessions.pop(session_id, None)

    def remove_source(self, session_id: str, source_id: str) -> int:
        artifacts = self._sessions.get(session_id)
        if not artifacts:
            return 0
        to_remove = [
            artifact_id
            for artifact_id, artifact in artifacts.items()
            if artifact.get("source_id") == source_id
        ]
        for artifact_id in to_remove:
            artifacts.pop(artifact_id, None)
        return len(to_remove)

    def set_saved_corpus(self, session_id: str, saved_corpus: dict | None) -> None:
        if not session_id:
            return
        if not saved_corpus:
            self._saved_corpora.pop(session_id, None)
            return
        self._saved_corpora[session_id] = deepcopy(saved_corpus)

    def get_saved_corpus(self, session_id: str) -> dict | None:
        value = self._saved_corpora.get(session_id)
        return deepcopy(value) if value else None

    @staticmethod
    def _public_artifact(artifact: dict) -> dict:
        public = {k: deepcopy(v) for k, v in artifact.items() if k != "order"}
        return public


corpus_registry = CorpusRegistry()
