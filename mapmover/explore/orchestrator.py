"""Explore lane orchestrator."""

from __future__ import annotations

import asyncio

from mapmover.explore.explore_followups import compact_followup_message
from mapmover.explore.explore_request_context import apply_resolved_location_override
from mapmover.explore.orchestrator_runtime import (
    apply_explore_runtime_result_cap,
    maybe_build_explore_explainer_response,
    run_explore_interpret,
    run_explore_interpret_with_progress,
)
from mapmover.explore.explore_runtime import (
    finalize_explore_order_result,
    preprocess_explore_request,
)
from mapmover.orchestrator_specs import EXPLORE_ORCHESTRATOR_SPEC, OrchestratorSpec
from mapmover.runtime.orchestrator_policy import (
    EXPLORE_HEARTBEAT_POLICY,
    build_heartbeat_event,
)
from mapmover.runtime.order_taker_prompt import build_system_prompt as build_explore_system_prompt
from mapmover.runtime.prompt_runtime import build_cached_system_prompt_blocks
from mapmover.runtime.warning_policy import DEFAULT_DISPLAY_WARNING_POLICY, DEFAULT_METRIC_WARNING_POLICY
from mapmover.order_taker import interpret_request
from mapmover.postprocessor import get_display_items, postprocess_order
from mapmover.preprocessor import preprocess_query
from mapmover.progress_bus import ProgressBus, ProgressEvent

class ExploreOrchestrator:
    """Behavior-preserving Explore workflow wrapper."""

    def __init__(self, spec: OrchestratorSpec = EXPLORE_ORCHESTRATOR_SPEC):
        self.spec = spec

    def heartbeat(self, idle_count: int) -> ProgressEvent:
        return build_heartbeat_event(
            idle_count=idle_count,
            policy=self.heartbeat_policy(),
            progress_event_cls=ProgressEvent,
        )

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
        return await run_explore_interpret(
            query=query,
            chat_history=chat_history,
            hints=hints,
            usage_recorder=usage_recorder,
            catalog_surface=catalog_surface,
            interpret_request_func=interpret_request,
            system_prompt_builder=self.build_system_prompt,
            system_prompt_block_builder=self.build_system_prompt_blocks,
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
        return await run_explore_interpret_with_progress(
            query=query,
            chat_history=chat_history,
            hints=hints,
            usage_recorder=usage_recorder,
            catalog_surface=catalog_surface,
            progress_bus_cls=ProgressBus,
            interpret_request_func=interpret_request,
            system_prompt_builder=self.build_system_prompt,
            system_prompt_block_builder=self.build_system_prompt_blocks,
        )

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
            metric_warning_policy=self.metric_warning_policy(),
            postprocess_order_func=postprocess_order,
            get_display_items_func=get_display_items,
            build_clarify_response_func=build_clarify_response_func,
            build_metric_warning_response_func=build_metric_warning_response_func,
            build_order_response_func=build_order_response_func,
        )

    def metric_warning_policy(self):
        return DEFAULT_METRIC_WARNING_POLICY

    def build_system_prompt(self, catalog: dict, conversions: dict) -> str:
        return build_explore_system_prompt(catalog, conversions)

    def build_system_prompt_blocks(self, prompt_text: str) -> list[dict]:
        return build_cached_system_prompt_blocks(prompt_text)

    def display_warning_policy(self):
        return DEFAULT_DISPLAY_WARNING_POLICY

    def heartbeat_policy(self):
        return EXPLORE_HEARTBEAT_POLICY

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
        load_source_reference_func=None,
    ) -> dict | None:
        return maybe_build_explore_explainer_response(
            query=query,
            hints=hints,
            build_chat_response_func=build_chat_response_func,
            auth_user=auth_user,
            load_source_metadata_func=load_source_metadata_func,
            load_source_reference_func=load_source_reference_func,
        )

    def apply_runtime_result_cap(
        self,
        result: dict,
        *,
        confirmed_order: dict | None = None,
        load_source_metadata_func=None,
    ) -> dict:
        return apply_explore_runtime_result_cap(
            result,
            confirmed_order=confirmed_order,
            load_source_metadata_func=load_source_metadata_func,
        )
