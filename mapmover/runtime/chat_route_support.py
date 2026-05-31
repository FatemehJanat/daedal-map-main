"""Shared chat-route budget and usage helpers."""

from __future__ import annotations

from mapmover.chat_budget import budget_rejection_payload, check_anonymous_chat_budget
from mapmover.llm_usage import LLMUsageRecorder


def anonymous_budget_rejection_payload(caller_ctx: dict) -> tuple[dict | None, int | None, dict[str, str] | None]:
    budget_decision = check_anonymous_chat_budget(caller_ctx)
    if budget_decision.allowed:
        return None, None, None
    return (
        budget_rejection_payload(budget_decision),
        429,
        {
            "Retry-After": str(budget_decision.retry_after_seconds),
            "Cache-Control": "no-store",
        },
    )


def build_usage_recorder(
    *,
    surface: str,
    call_kind: str,
    session_id: str,
    caller_ctx: dict,
    request_id: str | None = None,
    qa_suite_metadata: dict | None = None,
) -> LLMUsageRecorder:
    recorder_kwargs = {
        "surface": surface,
        "call_kind": call_kind,
        "session_id": session_id,
        **caller_ctx,
    }
    if request_id:
        recorder_kwargs["request_id"] = request_id
    recorder = LLMUsageRecorder(**recorder_kwargs)
    if qa_suite_metadata:
        recorder.add_metadata(**qa_suite_metadata)
    return recorder


def build_usage_recorders(
    *,
    surface: str,
    call_kinds: tuple[str, ...],
    session_id: str,
    caller_ctx: dict,
    request_id: str | None = None,
    qa_suite_metadata: dict | None = None,
) -> tuple[LLMUsageRecorder, ...]:
    return tuple(
        build_usage_recorder(
            surface=surface,
            call_kind=call_kind,
            session_id=session_id,
            caller_ctx=caller_ctx,
            request_id=request_id,
            qa_suite_metadata=qa_suite_metadata,
        )
        for call_kind in call_kinds
    )
