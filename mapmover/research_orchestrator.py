"""Research lane orchestrator."""

from __future__ import annotations

import asyncio

from mapmover.orchestrator_specs import OrchestratorSpec, RESEARCH_ORCHESTRATOR_SPEC
from mapmover.progress_bus import ProgressBus, ProgressEvent
from mapmover.research_lane_runtime import run_research_chat
from mapmover.research_orchestrator_runtime import (
    apply_research_runtime_result_cap,
    run_research_orchestrator_call,
    run_research_orchestrator_with_progress,
)
from mapmover.runtime.orchestrator_policy import (
    DEFAULT_RESEARCH_RETRY_POLICY,
    RESEARCH_HEARTBEAT_POLICY,
    build_heartbeat_event,
)
from mapmover.runtime.llm_policy import resolve_lane_llm_selection
from mapmover.runtime.prompt_runtime import build_cached_system_prompt_blocks
from mapmover.runtime.warning_policy import DEFAULT_DISPLAY_WARNING_POLICY
from mapmover.research_prompt import build_research_system_prompt


class ResearchOrchestrator:
    """Behavior-preserving Research workflow wrapper."""

    def __init__(self, spec: OrchestratorSpec = RESEARCH_ORCHESTRATOR_SPEC):
        self.spec = spec

    def heartbeat(self, idle_count: int) -> ProgressEvent:
        return build_heartbeat_event(
            idle_count=idle_count,
            policy=self.heartbeat_policy(),
            progress_event_cls=ProgressEvent,
        )

    def apply_runtime_result_cap(
        self,
        result: dict,
        *,
        load_source_metadata_func=None,
    ) -> dict:
        return apply_research_runtime_result_cap(
            result,
            load_source_metadata_func=load_source_metadata_func,
        )

    def display_warning_policy(self):
        return DEFAULT_DISPLAY_WARNING_POLICY

    def build_system_prompt(self, corpus_manifest: dict) -> str:
        return build_research_system_prompt(corpus_manifest)

    def build_system_prompt_blocks(self, prompt_text: str) -> list[dict]:
        return build_cached_system_prompt_blocks(prompt_text)

    def retry_policy(self):
        return DEFAULT_RESEARCH_RETRY_POLICY

    def heartbeat_policy(self):
        return RESEARCH_HEARTBEAT_POLICY

    async def run(
        self,
        *,
        session_id: str,
        query: str,
        chat_history: list | None,
        research_memory: dict | None,
        force_large_display: bool,
        usage_recorder,
        rescue_usage_recorder,
        catalog_surface: str | None,
    ) -> dict:
        from mapmover.data_loading import load_source_metadata
        return await run_research_orchestrator_call(
            session_id=session_id,
            query=query,
            chat_history=chat_history,
            research_memory=research_memory,
            force_large_display=force_large_display,
            usage_recorder=usage_recorder,
            rescue_usage_recorder=rescue_usage_recorder,
            catalog_surface=catalog_surface,
            run_research_chat_func=run_research_chat,
            load_source_metadata_func=load_source_metadata,
            display_warning_policy=self.display_warning_policy(),
            retry_policy=self.retry_policy(),
            system_prompt_builder=self.build_system_prompt,
            system_prompt_block_builder=self.build_system_prompt_blocks,
            llm_selection=self.llm_selection(),
        )

    async def run_with_progress(
        self,
        *,
        session_id: str,
        query: str,
        chat_history: list | None,
        research_memory: dict | None,
        force_large_display: bool,
        usage_recorder,
        rescue_usage_recorder,
        catalog_surface: str | None,
    ) -> tuple[ProgressBus, asyncio.Task]:
        from mapmover.data_loading import load_source_metadata
        return await run_research_orchestrator_with_progress(
            session_id=session_id,
            query=query,
            chat_history=chat_history,
            research_memory=research_memory,
            force_large_display=force_large_display,
            usage_recorder=usage_recorder,
            rescue_usage_recorder=rescue_usage_recorder,
            catalog_surface=catalog_surface,
            progress_bus_cls=ProgressBus,
            run_research_chat_func=run_research_chat,
            load_source_metadata_func=load_source_metadata,
            display_warning_policy=self.display_warning_policy(),
            retry_policy=self.retry_policy(),
            system_prompt_builder=self.build_system_prompt,
            system_prompt_block_builder=self.build_system_prompt_blocks,
            llm_selection=self.llm_selection(),
        )

    def llm_selection(self, override: dict | None = None):
        return resolve_lane_llm_selection(
            self.spec.model_policy,
            override=override,
        )
