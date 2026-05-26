"""Explore lane orchestrator."""

from __future__ import annotations

import asyncio

from mapmover.catalog_surface import catalog_surface_scope
from mapmover.explore.explore_followups import compact_followup_message
from mapmover.explore.explore_request_context import apply_resolved_location_override
from mapmover.explore.explore_runtime import (
    finalize_explore_order_result,
    preprocess_explore_request,
)
from mapmover.orchestrator_specs import EXPLORE_ORCHESTRATOR_SPEC, OrchestratorSpec
from mapmover.order_taker import interpret_request
from mapmover.postprocessor import get_display_items, postprocess_order
from mapmover.preprocessor import preprocess_query
from mapmover.progress_bus import ProgressBus, ProgressEvent
from mapmover.foundation_helpers import (
    load_runtime_explainer_helpers,
    load_runtime_result_cap_helpers,
)
from mapmover.runtime.result_cap import cap_payload_for_source


_EXPLORER_HEARTBEAT_MESSAGES = [
    "Still working through your request...",
    "Cross-checking the catalog...",
    "Putting your order together...",
]


class ExploreOrchestrator:
    """Behavior-preserving Explore workflow wrapper."""

    def __init__(self, spec: OrchestratorSpec = EXPLORE_ORCHESTRATOR_SPEC):
        self.spec = spec

    def heartbeat(self, idle_count: int) -> ProgressEvent:
        message = _EXPLORER_HEARTBEAT_MESSAGES[idle_count % len(_EXPLORER_HEARTBEAT_MESSAGES)]
        return ProgressEvent(stage="thinking", message=message, extra={"heartbeat": True})

    def preprocess(
        self,
        *,
        query: str,
        viewport,
        active_overlays,
        cache_stats,
        saved_order_names,
        time_state,
        loaded_data,
        resolved_location,
    ) -> dict:
        return preprocess_explore_request(
            query=query,
            viewport=viewport,
            active_overlays=active_overlays,
            cache_stats=cache_stats,
            saved_order_names=saved_order_names,
            time_state=time_state,
            loaded_data=loaded_data,
            resolved_location=resolved_location,
            preprocess_query_func=preprocess_query,
            apply_resolved_location_override_func=apply_resolved_location_override,
        )

    async def interpret(
        self,
        *,
        query: str,
        chat_history: list,
        hints: dict,
        usage_recorder,
        catalog_surface: str | None,
    ) -> dict:
        with catalog_surface_scope(catalog_surface):
            return await asyncio.to_thread(
                interpret_request,
                query,
                chat_history,
                hints=hints,
                usage_recorder=usage_recorder,
            )

    async def interpret_with_progress(
        self,
        *,
        query: str,
        chat_history: list,
        hints: dict,
        usage_recorder,
        catalog_surface: str | None,
    ) -> tuple[ProgressBus, asyncio.Task]:
        bus = ProgressBus()
        with catalog_surface_scope(catalog_surface):
            llm_task = asyncio.create_task(
                asyncio.to_thread(
                    interpret_request,
                    query,
                    chat_history,
                    hints=hints,
                    progress=bus.thread_emitter(),
                    usage_recorder=usage_recorder,
                )
            )
        return bus, llm_task

    def finalize_order(
        self,
        *,
        result: dict,
        hints: dict,
        force_metrics: bool,
        build_clarify_response_func,
        build_metric_warning_response_func,
        build_order_response_func,
    ) -> tuple[str, dict]:
        return finalize_explore_order_result(
            result=result,
            hints=hints,
            force_metrics=force_metrics,
            postprocess_order_func=postprocess_order,
            get_display_items_func=get_display_items,
            build_clarify_response_func=build_clarify_response_func,
            build_metric_warning_response_func=build_metric_warning_response_func,
            build_order_response_func=build_order_response_func,
        )

    def compact_followup(self, message: str) -> str:
        return compact_followup_message(message)

    def maybe_build_explainer_response(
        self,
        *,
        query: str,
        hints: dict | None,
        build_chat_response_func,
        auth_user: dict | None = None,
        load_source_metadata_func=None,
    ) -> dict | None:
        if load_source_metadata_func is None:
            return None
        helper = load_runtime_explainer_helpers()
        build_explainer_response_func = helper["build_explainer_response"]

        source_metadata = self._best_source_metadata(hints or {}, load_source_metadata_func)
        if not source_metadata:
            return None

        explainer = build_explainer_response_func(source_metadata, query)
        if not isinstance(explainer, dict):
            return None

        return build_chat_response_func(
            explainer.get("text") or "I can describe that source, but I do not have a fuller summary yet.",
            auth_user=auth_user,
            source_id=explainer.get("source_id"),
            pack_id=explainer.get("pack_id"),
            explainer_sections=explainer.get("sections"),
            stub_order=explainer.get("stub_order"),
        )

    def apply_runtime_result_cap(
        self,
        result: dict,
        *,
        confirmed_order: dict | None = None,
        load_source_metadata_func=None,
    ) -> dict:
        if not isinstance(result, dict) or load_source_metadata_func is None:
            return result
        source_id = str(
            result.get("source_id")
            or result.get("dataset")
            or (((result.get("order") or {}).get("items") or [{}])[0].get("source_id"))
            or ""
        ).strip()
        if not source_id:
            return result
        requested_limit = self._requested_limit_from_order(confirmed_order)
        helper = load_runtime_result_cap_helpers()
        payload, _cap_info = cap_payload_for_source(
            result,
            source_id=source_id,
            load_source_metadata_func=load_source_metadata_func,
            requested_limit=requested_limit,
            cap_payload_func=helper["apply_runtime_feature_cap_to_payload"],
        )
        return payload

    @staticmethod
    def _requested_limit_from_order(order: dict | None) -> int | None:
        if not isinstance(order, dict):
            return None
        items = order.get("items") or []
        for item in items:
            if not isinstance(item, dict):
                continue
            sort_spec = item.get("sort") or {}
            raw_limit = sort_spec.get("limit")
            try:
                limit = int(raw_limit)
            except (TypeError, ValueError):
                continue
            if limit > 0:
                return limit
        return None

    @staticmethod
    def _best_source_metadata(hints: dict, load_source_metadata_func) -> dict | None:
        candidate_ids: list[str] = []
        detected = hints.get("detected_source") or {}
        detected_source_id = str(detected.get("source_id") or "").strip()
        if detected_source_id:
            candidate_ids.append(detected_source_id)

        source_bundle = ((hints.get("candidates") or {}).get("sources") or {})
        best_candidate = source_bundle.get("best") or {}
        best_source_id = str(best_candidate.get("source_id") or "").strip()
        if best_source_id and best_source_id not in candidate_ids:
            candidate_ids.append(best_source_id)

        for candidate in source_bundle.get("candidates") or []:
            source_id = str((candidate or {}).get("source_id") or "").strip()
            if source_id and source_id not in candidate_ids:
                candidate_ids.append(source_id)

        for source_id in candidate_ids:
            metadata = load_source_metadata_func(source_id) or {}
            if isinstance(metadata, dict) and metadata:
                metadata.setdefault("source_id", source_id)
                return metadata
        return None
