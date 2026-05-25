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
