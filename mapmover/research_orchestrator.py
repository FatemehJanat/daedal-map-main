"""Research lane orchestrator."""

from __future__ import annotations

import asyncio

from mapmover.catalog_surface import catalog_surface_scope
from mapmover.orchestrator_specs import OrchestratorSpec, RESEARCH_ORCHESTRATOR_SPEC
from mapmover.progress_bus import ProgressBus, ProgressEvent


_RESEARCH_HEARTBEAT_MESSAGES = [
    "Reviewing the workspace...",
    "Scanning the loaded artifacts...",
    "Working through the analysis...",
]


class ResearchOrchestrator:
    """Behavior-preserving Research workflow wrapper."""

    def __init__(self, spec: OrchestratorSpec = RESEARCH_ORCHESTRATOR_SPEC):
        self.spec = spec

    def heartbeat(self, idle_count: int) -> ProgressEvent:
        message = _RESEARCH_HEARTBEAT_MESSAGES[idle_count % len(_RESEARCH_HEARTBEAT_MESSAGES)]
        return ProgressEvent(stage="thinking", message=message, extra={"heartbeat": True})

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
        from mapmover.routes.research import run_research_chat

        with catalog_surface_scope(catalog_surface):
            return await asyncio.to_thread(
                run_research_chat,
                session_id=session_id,
                query=query,
                chat_history=chat_history,
                research_memory=research_memory,
                force_large_display=force_large_display,
                usage_recorder=usage_recorder,
                rescue_usage_recorder=rescue_usage_recorder,
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
        from mapmover.routes.research import run_research_chat

        bus = ProgressBus()
        with catalog_surface_scope(catalog_surface):
            task = asyncio.create_task(
                asyncio.to_thread(
                    run_research_chat,
                    session_id=session_id,
                    query=query,
                    chat_history=chat_history,
                    research_memory=research_memory,
                    progress=bus.thread_emitter(),
                    force_large_display=force_large_display,
                    usage_recorder=usage_recorder,
                    rescue_usage_recorder=rescue_usage_recorder,
                )
            )
        return bus, task
