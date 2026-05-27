"""Shared orchestrator policy objects and helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HeartbeatPolicy:
    stage: str
    messages: tuple[str, ...]


@dataclass(frozen=True)
class ResearchRetryPolicy:
    max_tool_iterations: int
    guardrail_start_iteration: int
    strong_guardrail_iteration: int
    rescue_prompt: str


EXPLORE_HEARTBEAT_POLICY = HeartbeatPolicy(
    stage="thinking",
    messages=(
        "Still working through your request...",
        "Cross-checking the catalog...",
        "Putting your order together...",
    ),
)


RESEARCH_HEARTBEAT_POLICY = HeartbeatPolicy(
    stage="thinking",
    messages=(
        "Reviewing the workspace...",
        "Scanning the loaded artifacts...",
        "Working through the analysis...",
    ),
)


DEFAULT_RESEARCH_RETRY_POLICY = ResearchRetryPolicy(
    max_tool_iterations=8,
    guardrail_start_iteration=3,
    strong_guardrail_iteration=5,
    rescue_prompt=(
        "Write the best grounded final answer now using only the evidence already gathered above. "
        "Do not call tools. If the evidence is partial, answer the grounded part first and then "
        "name the remaining limitation clearly."
    ),
)


def build_heartbeat_event(*, idle_count: int, policy: HeartbeatPolicy, progress_event_cls):
    message = policy.messages[idle_count % len(policy.messages)]
    return progress_event_cls(stage=policy.stage, message=message, extra={"heartbeat": True})
