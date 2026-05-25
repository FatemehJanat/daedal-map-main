"""LLM usage tracking for chat surfaces (Explorer + Research).

One LLMUsageRecorder per user query. The chat route constructs it after caller
classification, the LLM call site(s) call .record(response) after each
messages.create(), and the route calls .flush() in a finally block to emit one
llm_usage_events row per user query.

Cost is computed in the llm_usage_events_with_cost view, not here.

Caller classification:
- qa_suite      explicit in-process QA override
- authenticated profile present (including master plan)
- anonymous     no auth

See docs/future/llm_usage_tracking_implementation.md for the full design.
"""

from __future__ import annotations

import os
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from .logging_analytics import log_llm_usage_event, logger


_QA_OVERRIDE_ENV = "LLM_USAGE_FORCE_QA_USER_ID"
_QA_OVERRIDE_LABEL_ENV = "LLM_USAGE_FORCE_QA_LABEL"


def _qa_override_classification(ip_hash: Optional[str]) -> Optional[dict]:
    """If LLM_USAGE_FORCE_QA_USER_ID is set, return a qa_suite classification.

    This is the in-process testing path. HTTP-based callers should remain
    authenticated traffic, even when they use the master plan.
    """
    forced_id = (os.getenv(_QA_OVERRIDE_ENV) or "").strip()
    if not forced_id:
        return None
    label = (os.getenv(_QA_OVERRIDE_LABEL_ENV) or "qa-runner").strip() or "qa-runner"
    return {
        "caller_kind": "qa_suite",
        "caller_label": label,
        "auth_user_id": forced_id,
        "plan_id": "master",
        "ip_hash": ip_hash,
    }


_PROFILE_CACHE: dict[str, tuple[float, dict | None]] = {}
_PROFILE_CACHE_TTL_S = 300.0  # 5 minutes
_PROFILE_CACHE_LOCK = threading.Lock()


def _get_cached_profile(user_id: str) -> Optional[dict]:
    """Read-through cache around supabase_client.get_profile.

    Avoids hitting Supabase on every chat call. 5-minute TTL is fine because
    plan_id changes are rare and the worst case (slightly stale tier) is harmless
    for analytics.
    """
    if not user_id:
        return None
    now = time.time()
    with _PROFILE_CACHE_LOCK:
        cached = _PROFILE_CACHE.get(user_id)
        if cached and (now - cached[0]) < _PROFILE_CACHE_TTL_S:
            return cached[1]

    profile: Optional[dict] = None
    try:
        from supabase_client import get_supabase_client
        client = get_supabase_client()
        if client:
            profile = client.get_profile(user_id)
    except Exception as exc:
        logger.warning("llm_usage profile fetch failed user=%s: %s", user_id, exc)
        profile = None

    with _PROFILE_CACHE_LOCK:
        _PROFILE_CACHE[user_id] = (now, profile)
    return profile


def classify_caller(
    *,
    auth_user: Optional[dict],
    ip_hash: Optional[str],
) -> dict:
    """Return a dict describing the caller for llm_usage tagging.

    Keys: caller_kind, caller_label, auth_user_id, plan_id, ip_hash.

    - qa_suite      explicit in-process QA override
    - authenticated auth present (defaults to 'free' if profile missing)
    - anonymous     no auth
    """
    forced = _qa_override_classification(ip_hash)
    if forced is not None:
        return forced

    user_id: Optional[str] = None
    if auth_user:
        raw_id = auth_user.get("id")
        if raw_id:
            user_id = str(raw_id)

    if not user_id:
        return {
            "caller_kind": "anonymous",
            "caller_label": ip_hash or None,
            "auth_user_id": None,
            "plan_id": None,
            "ip_hash": ip_hash,
        }

    profile = _get_cached_profile(user_id) or {}
    plan_id = (profile.get("plan_id") or "free").strip() or "free"
    email = (auth_user.get("email") or profile.get("email") or "").strip() or None

    return {
        "caller_kind": "authenticated",
        "caller_label": email,
        "auth_user_id": user_id,
        "plan_id": plan_id,
        "ip_hash": ip_hash,
    }


def ensure_recorder(
    recorder: "Optional[LLMUsageRecorder]",
    *,
    surface: str,
    call_kind: str,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> tuple["LLMUsageRecorder", bool]:
    """Return (recorder, owns_lifecycle).

    Guarantees every chat-path call site gets a recorder so we always log
    billing rows, no matter how the function was reached (HTTP route, in-process
    QA suite, future Ops mode, agent/API path).

    - If a recorder was already passed in (HTTP routes do this after caller
      classification), return it with owns_lifecycle=False; the original caller
      owns flush().
    - Otherwise, build a fresh recorder using the current QA env override (if
      set) or the anonymous classification, and return owns_lifecycle=True.
      The caller MUST flush() it in a finally block.
    """
    if recorder is not None:
        return recorder, False
    caller_ctx = classify_caller(auth_user=None, ip_hash=None)
    return (
        LLMUsageRecorder(
            surface=surface,
            call_kind=call_kind,
            session_id=session_id,
            request_id=request_id,
            **caller_ctx,
        ),
        True,
    )


@dataclass
class LLMUsageRecorder:
    """Per-request token + latency accumulator across a tool-loop.

    Lifecycle:
        recorder = LLMUsageRecorder(surface=..., call_kind=..., **caller_context)
        for iteration in range(...):
            response = client.messages.create(...)
            recorder.record(response)
            ...
        recorder.flush()  # in a finally block, emits one row

    .flush() is idempotent and safe to call when no .record() ever fired
    (it will emit a zero-token row with iterations=0 to make failures visible).
    Set .skip_flush = True to suppress entirely (e.g. when the request errored
    before any LLM call).
    """

    surface: str
    call_kind: str
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    caller_kind: Optional[str] = None
    caller_label: Optional[str] = None
    auth_user_id: Optional[str] = None
    plan_id: Optional[str] = None
    ip_hash: Optional[str] = None

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    tool_iterations: int = 0
    last_model: Optional[str] = None
    last_stop_reason: Optional[str] = None
    tool_names: list[str] = field(default_factory=list)
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    _started_at: float = field(default_factory=time.perf_counter)
    _flushed: bool = False
    skip_flush: bool = False

    def record(self, response: Any, *, tool_name: Optional[str] = None) -> None:
        """Pull token counts off response.usage and accumulate.

        Anthropic SDK exposes input_tokens, output_tokens, cache_creation_input_tokens,
        cache_read_input_tokens on response.usage. Defensive against missing fields
        because we never want to break the chat response on an analytics shape change.
        """
        try:
            usage = getattr(response, "usage", None)
            if usage is not None:
                self.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
                self.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
                self.cache_creation_tokens += int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
                self.cache_read_tokens += int(getattr(usage, "cache_read_input_tokens", 0) or 0)
            model = getattr(response, "model", None)
            if model:
                self.last_model = str(model)
            stop_reason = getattr(response, "stop_reason", None)
            if stop_reason:
                self.last_stop_reason = str(stop_reason)
            self.tool_iterations += 1
            if tool_name:
                self.tool_names.append(str(tool_name))
        except Exception as exc:
            logger.warning("LLMUsageRecorder.record failed: %s", exc)

    def add_metadata(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if value is not None:
                self.extra_metadata[key] = value

    def flush(self, *, skip_if_empty: bool = False) -> None:
        if self._flushed or self.skip_flush:
            return
        if skip_if_empty and self.tool_iterations == 0:
            self._flushed = True
            return
        self._flushed = True
        latency_ms = int((time.perf_counter() - self._started_at) * 1000)
        metadata: dict[str, Any] = {
            "stop_reason": self.last_stop_reason,
        }
        if self.tool_names:
            metadata["tool_names"] = self.tool_names
        if self.extra_metadata:
            metadata.update(self.extra_metadata)
        try:
            log_llm_usage_event(
                request_id=self.request_id,
                session_id=self.session_id,
                surface=self.surface,
                call_kind=self.call_kind,
                model=self.last_model,
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
                cache_creation_tokens=self.cache_creation_tokens,
                cache_read_tokens=self.cache_read_tokens,
                tool_iterations=self.tool_iterations,
                latency_ms=latency_ms,
                caller_kind=self.caller_kind,
                caller_label=self.caller_label,
                auth_user_id=self.auth_user_id,
                plan_id=self.plan_id,
                ip_hash=self.ip_hash,
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning("LLMUsageRecorder.flush failed: %s", exc)
