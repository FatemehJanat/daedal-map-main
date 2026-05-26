"""Research lane orchestrator."""

from __future__ import annotations

import asyncio

from mapmover.catalog_surface import catalog_surface_scope
from mapmover.foundation_helpers import load_runtime_result_cap_helpers
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

    def apply_runtime_result_cap(
        self,
        result: dict,
        *,
        load_source_metadata_func=None,
    ) -> dict:
        if not isinstance(result, dict) or load_source_metadata_func is None:
            return result
        helper = load_runtime_result_cap_helpers()
        cap_payload = helper["apply_runtime_feature_cap_to_payload"]

        next_result = dict(result)
        display = next_result.get("display")
        if isinstance(display, dict):
            source_id = str(display.get("source_id") or next_result.get("source_id") or "").strip()
            metadata = load_source_metadata_func(source_id) if source_id else None
            capped_display, cap_info = cap_payload(display, source_metadata=metadata or {})
            next_result["display"] = capped_display
            if cap_info:
                next_result["cap_info"] = cap_info
                next_result["truncated"] = True

        displays = next_result.get("displays")
        if isinstance(displays, list):
            capped_displays = []
            cap_infos = []
            for display_item in displays:
                if not isinstance(display_item, dict):
                    capped_displays.append(display_item)
                    continue
                source_id = str(display_item.get("source_id") or next_result.get("source_id") or "").strip()
                metadata = load_source_metadata_func(source_id) if source_id else None
                capped_display, cap_info = cap_payload(display_item, source_metadata=metadata or {})
                capped_displays.append(capped_display)
                if cap_info:
                    cap_infos.append(cap_info)
            next_result["displays"] = capped_displays
            if cap_infos and "cap_info" not in next_result:
                next_result["cap_info"] = cap_infos[-1]
                next_result["truncated"] = True

        return next_result

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
            result = await asyncio.to_thread(
                run_research_chat,
                session_id=session_id,
                query=query,
                chat_history=chat_history,
                research_memory=research_memory,
                force_large_display=force_large_display,
                usage_recorder=usage_recorder,
                rescue_usage_recorder=rescue_usage_recorder,
            )
        from mapmover.data_loading import load_source_metadata

        return self.apply_runtime_result_cap(
            result,
            load_source_metadata_func=load_source_metadata,
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
            raw_task = asyncio.create_task(
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

        async def capped_result_task():
            result = await raw_task
            from mapmover.data_loading import load_source_metadata

            return self.apply_runtime_result_cap(
                result,
                load_source_metadata_func=load_source_metadata,
            )

        return bus, asyncio.create_task(capped_result_task())
