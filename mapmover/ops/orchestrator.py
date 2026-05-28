"""Ops lane orchestrator."""

from __future__ import annotations

from mapmover.ops_prompt import build_ops_system_prompt
from mapmover.ops_watch_runtime import preload_ops_watch_scope
from mapmover.orchestrator_specs import OPS_ORCHESTRATOR_SPEC, OrchestratorSpec
from mapmover.progress_bus import ProgressEvent
from mapmover.runtime.orchestrator_policy import (
    DEFAULT_OPS_RETRY_POLICY,
    OPS_HEARTBEAT_POLICY,
    build_heartbeat_event,
)
from mapmover.runtime.prompt_runtime import build_cached_system_prompt_blocks
from mapmover.runtime.warning_policy import DEFAULT_DISPLAY_WARNING_POLICY


class OpsOrchestrator:
    """Behavior-preserving Ops shell on top of the shared runtime spine."""

    def __init__(self, spec: OrchestratorSpec = OPS_ORCHESTRATOR_SPEC):
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
        watch_context: dict | None = None,
    ) -> dict:
        return preload_ops_watch_scope(query=query, watch_context=watch_context)

    def build_system_prompt(
        self,
        watch_context: dict | None = None,
        hints: dict | None = None,
    ) -> str:
        return build_ops_system_prompt(watch_context=watch_context, hints=hints)

    def build_system_prompt_blocks(self, prompt_text: str) -> list[dict]:
        return build_cached_system_prompt_blocks(prompt_text)

    def display_warning_policy(self):
        return DEFAULT_DISPLAY_WARNING_POLICY

    def retry_policy(self):
        return DEFAULT_OPS_RETRY_POLICY

    def heartbeat_policy(self):
        return OPS_HEARTBEAT_POLICY
