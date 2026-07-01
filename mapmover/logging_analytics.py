"""
Logging and analytics functions for query tracking and error monitoring.
"""

import json
import logging
import os
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from .hosted_runtime_events import HostedRuntimeEventSink, hosted_runtime_control_enabled
from .paths import LOGS_DIR, ensure_dir

# Set up logging
try:
    logs_dir = ensure_dir(LOGS_DIR)
    _local_logs_enabled = True
except OSError:
    logs_dir = LOGS_DIR
    _local_logs_enabled = False

error_log_path = logs_dir / "errors.log"

# Create a custom logger with proper configuration
logger = logging.getLogger("mapmover")
logger.setLevel(logging.INFO)

# Remove any existing handlers to avoid duplicates on reload
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# Console handler (optional but useful for debugging)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# File handler - only when the runtime log dir is writable
if _local_logs_enabled:
    file_handler = logging.FileHandler(error_log_path)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Prevent propagation to root logger (avoids duplicate logs)
logger.propagate = False

# Query analytics logger - tracks usage patterns
analytics_dir = logs_dir / "analytics"
if _local_logs_enabled:
    analytics_dir.mkdir(exist_ok=True)
analytics_log_path = analytics_dir / "query_analytics.jsonl"
api_query_analytics_log_path = analytics_dir / "api_query_analytics.jsonl"
route_analytics_log_path = analytics_dir / "route_analytics.jsonl"

# Initialize Supabase client (lazy loaded to avoid import issues)
_supabase_client = None
_missing_ip_salt_warned = False

# Background executor for fire-and-forget Supabase logging.
# Keeps synchronous Supabase HTTP calls off the response path.
_analytics_pool_size = max(1, int(os.getenv("ANALYTICS_BG_WORKERS", "4")))
_analytics_executor = ThreadPoolExecutor(
    max_workers=_analytics_pool_size,
    thread_name_prefix="analytics-bg",
)


def _runtime_analytics_disabled() -> bool:
    return str(os.getenv("QA_DISABLE_RUNTIME_ANALYTICS", "")).strip().lower() in {"1", "true", "yes", "on"}


def _qa_suite_log_metadata() -> dict[str, Any]:
    suite = str(os.getenv("LLM_USAGE_FORCE_QA_SUITE", "")).strip()
    run_id = str(os.getenv("LLM_USAGE_FORCE_QA_RUN_ID", "")).strip()
    label = str(os.getenv("LLM_USAGE_FORCE_QA_LABEL", "")).strip()
    metadata: dict[str, Any] = {}
    if suite:
        metadata["qa_suite_name"] = suite
    if run_id:
        metadata["qa_suite_run_id"] = run_id
    if label:
        metadata["qa_caller_label"] = label
    return metadata


def _submit_background(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    if _runtime_analytics_disabled():
        return
    """Submit a callable to the analytics background pool, fire-and-forget.

    Errors raised inside the worker are swallowed and logged so they cannot
    affect the response path or the next request.

    Retry policy: one retry on any exception with a 100ms backoff. The most
    common failure here is httpx's "Server disconnected" when the postgrest
    connection pool holds a connection the Supabase server has closed (idle
    timeout, restart). httpx evicts the dead connection on the failed attempt,
    so the second try uses a fresh connection. Retrying any exception is
    safe because these calls are idempotent inserts with server-generated ids.
    """
    def _run() -> None:
        last_exc: Exception | None = None
        for attempt in (1, 2):
            try:
                fn(*args, **kwargs)
                return
            except Exception as exc:
                last_exc = exc
                if attempt == 1:
                    logger.warning(
                        "Background analytics call attempt %d failed (retrying): %s",
                        attempt,
                        exc,
                    )
                    time.sleep(0.1)
                    continue
        logger.error("Background analytics call failed after retry: %s", last_exc)

    try:
        _analytics_executor.submit(_run)
    except RuntimeError:
        # Executor was shut down (process exit). Run inline as fallback.
        _run()


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    if _runtime_analytics_disabled():
        return
    if not _local_logs_enabled:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.write("\n")
    except Exception as e:
        logger.error(f"Failed to append analytics event locally: {e}")


def hash_ip_for_analytics(ip_address: Optional[str]) -> Optional[str]:
    global _missing_ip_salt_warned
    raw_ip = (ip_address or "").strip()
    if not raw_ip:
        return None
    salt = os.getenv("API_ANALYTICS_IP_SALT", "").strip()
    if not salt and not _missing_ip_salt_warned:
        logger.warning("API_ANALYTICS_IP_SALT is not set; IP analytics hashes are stable but unsalted.")
        _missing_ip_salt_warned = True
    digest = hashlib.sha256(f"{salt}:{raw_ip}".encode("utf-8")).hexdigest()
    return digest


_MCP_SCANNER_METHODS = frozenset({
    "initialize",
    "notifications/initialized",
    "notifications/cancelled",
    "tools/list",
    "resources/list",
    "prompts/list",
    "ping",
})


def _should_mirror_route_event_to_supabase(
    path: str | None,
    method: str | None = None,
    status_code: int | None = None,
    metadata: dict | None = None,
    rate_limited: bool = False,
    error_code: str | None = None,
) -> bool:
    path = str(path or "").strip()
    http_method = str(method or "").upper()

    # MCP: skip scanner handshake noise (health checkers run these constantly).
    # Only log tool calls, errors, rate limits, and payment challenges.
    if path == "/mcp" or path.startswith("/mcp/"):
        if http_method in {"GET", "HEAD"}:
            return False
        mcp_method = (metadata or {}).get("mcp_method") or ""
        if mcp_method in _MCP_SCANNER_METHODS:
            return False
        # Always log errors, rate limits, and 402 payment challenges
        if rate_limited or error_code or (status_code and status_code >= 400):
            return True
        # Log actual tool calls and anything else not filtered above
        return True

    if path.startswith("/api/"):
        return True
    if path.startswith("/geometry/"):
        return True
    if path.startswith("/reference/"):
        return True
    if path.startswith("/debug/"):
        return True
    if path in {"/chat", "/chat/stream"}:
        return True
    return False


def log_api_query_event(
    *,
    request_id: str,
    capability_id: str,
    pack_id: str,
    source_id: str,
    decision: str,
    payment_rail: str | None = None,
    artifact_token_id: str | None = None,
    auth_user_id: str | None = None,
    ip_hash: str | None = None,
    user_agent: str | None = None,
    execution_latency_ms: int | None = None,
    row_count: int | None = None,
    response_size_bytes: int | None = None,
    status_code: int | None = None,
    warnings_count: int | None = None,
    error_code: str | None = None,
    query_granularity: str | None = None,
    settlement_id: str | None = None,
    amount_charged_usdc_base_units: int | None = None,
    revenue_attributed_usdc_base_units: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if _runtime_analytics_disabled():
        return
    event = {
        "timestamp": datetime.utcnow().isoformat(),
        "request_id": request_id,
        "capability_id": capability_id,
        "pack_id": pack_id,
        "source_id": source_id,
        "decision": decision,
        "payment_rail": payment_rail,
        "artifact_token_id": artifact_token_id,
        "caller": {
            "auth_user_id": auth_user_id,
            "ip_hash": ip_hash,
            "user_agent": user_agent[:300] if user_agent else None,
        },
        "usage": {
            "execution_latency_ms": execution_latency_ms,
            "rows_returned": row_count,
            "response_size_bytes": response_size_bytes,
            "warnings_count": warnings_count,
        },
        "status_code": status_code,
        "error_code": error_code,
        "query_granularity": query_granularity,
        "settlement_id": settlement_id,
        "amount_charged_usdc_base_units": amount_charged_usdc_base_units,
        "revenue_attributed_usdc_base_units": revenue_attributed_usdc_base_units,
        "metadata": metadata or {},
    }

    _append_jsonl(api_query_analytics_log_path, event)

    logger.info(
        "api_query_event request_id=%s pack_id=%s source_id=%s decision=%s status=%s rows=%s latency_ms=%s user_id=%s",
        request_id,
        pack_id,
        source_id,
        decision,
        status_code,
        row_count,
        execution_latency_ms,
        auth_user_id or "anonymous",
    )

    supabase_client = get_supabase()
    if supabase_client:
        _meta = metadata or {}
        _submit_background(
            supabase_client.log_api_usage_event,
            event_kind=decision or "request_completed",
            request_id=request_id,
            capability_id=capability_id,
            pack_id=pack_id,
            source_id=source_id,
            query_granularity=query_granularity,
            decision=decision,
            payment_rail=payment_rail,
            artifact_token_id=artifact_token_id,
            auth_user_id=auth_user_id,
            ip_hash=ip_hash,
            status_code=status_code,
            row_count=row_count or 0,
            response_size_bytes=response_size_bytes or 0,
            execution_latency_ms=execution_latency_ms,
            warnings_count=warnings_count or 0,
            error_code=error_code,
            settlement_id=settlement_id,
            amount_charged_usdc_base_units=amount_charged_usdc_base_units,
            revenue_attributed_usdc_base_units=revenue_attributed_usdc_base_units,
            mcp_client_name=str(_meta.get("mcp_client_name") or "")[:100] or None,
            mcp_client_version=str(_meta.get("mcp_client_version") or "")[:50] or None,
            metadata=event,
        )


def log_route_request_event(
    *,
    method: str,
    path: str,
    status_code: int,
    surface: str | None = None,
    execution_latency_ms: int | None = None,
    auth_user_id: str | None = None,
    ip_hash: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
    pack_id: str | None = None,
    source_id: str | None = None,
    response_size_bytes: int | None = None,
    rate_limited: bool = False,
    retry_after_seconds: int | None = None,
    challenge_issued: bool = False,
    settlement_failed: bool = False,
    concurrency_rejected: bool = False,
    error_code: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if _runtime_analytics_disabled():
        return
    event = {
        "timestamp": datetime.utcnow().isoformat(),
        "request_id": request_id,
        "method": method,
        "path": path,
        "surface": surface,
        "status_code": status_code,
        "pack_id": pack_id,
        "source_id": source_id,
        "caller": {
            "auth_user_id": auth_user_id,
            "ip_hash": ip_hash,
            "user_agent": user_agent[:300] if user_agent else None,
        },
        "usage": {
            "execution_latency_ms": execution_latency_ms,
            "response_size_bytes": response_size_bytes,
        },
        "security": {
            "rate_limited": rate_limited,
            "retry_after_seconds": retry_after_seconds,
            "challenge_issued": challenge_issued,
            "settlement_failed": settlement_failed,
            "concurrency_rejected": concurrency_rejected,
            "error_code": error_code,
        },
        "metadata": metadata or {},
    }

    _append_jsonl(route_analytics_log_path, event)

    # Skip stdout logging for low-signal scanner traffic. JSONL still
    # captures the full event for analytics. Supabase mirror is already
    # selective for the same paths via _should_mirror_route_event_to_supabase.
    # Always log when something interesting happened (rate limit, error).
    _is_low_signal = (
        (path == "/mcp" or path.startswith("/mcp/"))
        and str(method or "").upper() in {"GET", "HEAD"}
        and not rate_limited
        and not error_code
        and (status_code is None or status_code < 400)
    )
    if not _is_low_signal:
        logger.info(
            "route_event method=%s path=%s surface=%s status=%s latency_ms=%s user_id=%s pack_id=%s source_id=%s",
            method,
            path,
            surface or "-",
            status_code,
            execution_latency_ms,
            auth_user_id or "anonymous",
            pack_id or "-",
            source_id or "-",
        )

    supabase_client = get_supabase()
    if supabase_client and _should_mirror_route_event_to_supabase(
        path,
        method=method,
        status_code=status_code,
        metadata=metadata,
        rate_limited=rate_limited,
        error_code=error_code,
    ):
        _submit_background(
            supabase_client.log_security_event,
            method=method,
            path=path,
            surface=surface,
            request_id=request_id,
            pack_id=pack_id,
            source_id=source_id,
            auth_user_id=auth_user_id,
            ip_hash=ip_hash,
            user_agent=user_agent[:300] if user_agent else None,
            status_code=status_code,
            execution_latency_ms=execution_latency_ms,
            response_size_bytes=response_size_bytes or 0,
            rate_limited=rate_limited,
            retry_after_seconds=retry_after_seconds,
            challenge_issued=challenge_issued,
            settlement_failed=settlement_failed,
            concurrency_rejected=concurrency_rejected,
            error_code=error_code,
            metadata=event,
        )


def get_supabase():
    """Get the hosted telemetry sink, initializing if needed."""
    global _supabase_client
    if _runtime_analytics_disabled():
        return None
    if _supabase_client is None:
        try:
            if hosted_runtime_control_enabled():
                _supabase_client = HostedRuntimeEventSink()
                logger.info("Hosted runtime control sink initialized")
            else:
                logger.info("Supabase not configured - using local logging only")
        except Exception as e:
            logger.warning(f"Could not initialize hosted runtime control sink: {e}")
            _supabase_client = False  # Mark as failed to avoid retrying
    return _supabase_client if _supabase_client else None


def log_conversation(
    session_id: str,
    query: str,
    response_text: str,
    *,
    surface: str = "chat",
    intent: str | None = None,
    dataset_selected: str | None = None,
    results_count: int = 0,
    ip_hash: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Log a human-side chat or map interaction to conversation_sessions."""
    if _runtime_analytics_disabled():
        return
    analytics_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "session_id": session_id,
        "surface": surface,
        "query": query,
        "response": response_text[:500] if response_text else None,
        "intent": intent,
        "dataset_selected": dataset_selected,
        "results_count": results_count,
        "metadata": {
            **_qa_suite_log_metadata(),
            **(metadata or {}),
        },
    }

    if _local_logs_enabled:
        try:
            with open(analytics_log_path, "a", encoding="utf-8") as f:
                json.dump(analytics_data, f, ensure_ascii=False)
                f.write("\n")
        except Exception as e:
            logger.error(f"Failed to log conversation locally: {e}")

    supabase_client = get_supabase()
    if supabase_client and session_id:
        _submit_background(
            supabase_client.log_session_message,
            session_id=session_id,
            user_query=query,
            assistant_response=response_text or "",
            surface=surface,
            intent=intent,
            dataset_selected=dataset_selected,
            results_count=results_count,
            ip_hash=ip_hash,
            user_agent=user_agent,
            metadata=metadata,
        )


def log_llm_usage_event(
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    surface: str | None = None,
    call_kind: str | None = None,
    model: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    tool_iterations: int = 0,
    latency_ms: int | None = None,
    caller_kind: str | None = None,
    caller_label: str | None = None,
    auth_user_id: str | None = None,
    plan_id: str | None = None,
    ip_hash: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Fire-and-forget chat-LLM usage event (one per user query, summed across tool loop)."""
    if _runtime_analytics_disabled():
        return
    logger.info(
        "llm_usage surface=%s call_kind=%s model=%s in=%s out=%s cache_c=%s cache_r=%s iters=%s latency_ms=%s caller=%s plan=%s",
        surface or "-",
        call_kind or "-",
        model or "-",
        input_tokens,
        output_tokens,
        cache_creation_tokens,
        cache_read_tokens,
        tool_iterations,
        latency_ms,
        caller_kind or "-",
        plan_id or "-",
    )

    supabase_client = get_supabase()
    if supabase_client:
        _submit_background(
            supabase_client.log_llm_usage_event,
            request_id=request_id,
            session_id=session_id,
            surface=surface,
            call_kind=call_kind,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
            tool_iterations=tool_iterations,
            latency_ms=latency_ms,
            caller_kind=caller_kind,
            caller_label=caller_label,
            auth_user_id=auth_user_id,
            plan_id=plan_id,
            ip_hash=ip_hash,
            metadata=metadata,
        )


def log_app_error(
    error_type: str,
    error_message: str,
    *,
    surface: str | None = None,
    path: str | None = None,
    request_id: str | None = None,
    pack_id: str | None = None,
    query: str | None = None,
    traceback: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Log an application exception to error_logs. surface=human_app or agent_api."""
    if _runtime_analytics_disabled():
        return
    event = {
        "timestamp": datetime.utcnow().isoformat(),
        "surface": surface,
        "path": path,
        "request_id": request_id,
        "pack_id": pack_id,
        "error_type": error_type,
        "error_message": error_message[:500] if error_message else None,
        "metadata": {
            **_qa_suite_log_metadata(),
            **(metadata or {}),
        },
    }
    _append_jsonl(route_analytics_log_path, event)

    logger.error(
        "app_error surface=%s path=%s type=%s message=%s",
        surface or "-",
        path or "-",
        error_type,
        error_message[:200] if error_message else "",
    )

    supabase_client = get_supabase()
    if supabase_client:
        _submit_background(
            supabase_client.log_error,
            error_type=error_type,
            error_message=error_message,
            query=query,
            traceback=traceback,
            metadata={
                "surface": surface,
                "path": path,
                "request_id": request_id,
                "pack_id": pack_id,
                **_qa_suite_log_metadata(),
                **(metadata or {}),
            },
        )


def log_missing_geometry(country_names, query=None, dataset=None, region=None):
    """
    Log countries/places that are missing map geometry.

    This helps track which geometries need to be added to the shared global
    bootstrap geometry layer.

    Args:
        country_names: List of country/place names missing geometry
        query: The query that triggered this (optional)
        dataset: The dataset being queried (optional)
        region: The region filter used (optional)
    """
    if not country_names:
        return
    if _runtime_analytics_disabled():
        return

    # Log locally
    missing_log_path = logs_dir / "analytics" / "missing_geometries.jsonl"
    missing_log_path.parent.mkdir(parents=True, exist_ok=True)

    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "missing_countries": country_names,
        "count": len(country_names),
        "query": query,
        "dataset": dataset,
        "region": region
    }

    if _local_logs_enabled:
        try:
            with open(missing_log_path, 'a', encoding='utf-8') as f:
                json.dump(log_entry, f, ensure_ascii=False)
                f.write('\n')
        except Exception as e:
            logger.error(f"Failed to log missing geometries locally: {e}")

    # Log to Supabase if configured
    supabase_client = get_supabase()
    if supabase_client:
        _submit_background(
            supabase_client.log_missing_geometry,
            country_names=country_names,
            query=query,
            dataset=dataset,
            region=region,
        )


def log_error_to_cloud(error_type, error_message, query=None, tb=None, metadata=None):
    """
    Log errors to Supabase cloud for centralized error tracking.

    Args:
        error_type: Type of error (e.g., "JSONDecodeError", "ValueError")
        error_message: The error message
        query: The query that caused the error (if applicable)
        tb: Traceback string
        metadata: Additional context
    """
    supabase_client = get_supabase()
    if supabase_client:
        _submit_background(
            supabase_client.log_error,
            error_type=error_type,
            error_message=error_message,
            query=query,
            traceback=tb,
            metadata=metadata,
        )


def log_missing_region_to_cloud(region_name, query=None, dataset=None):
    """
    Log missing region lookups to Supabase for tracking gaps in conversions.json.

    Args:
        region_name: The region name that failed lookup
        query: The query that triggered this
        dataset: The dataset being queried
    """
    supabase_client = get_supabase()
    if supabase_client:
        _submit_background(
            supabase_client.log_missing_region,
            region_name=region_name,
            query=query,
            dataset=dataset,
        )

    # Also log locally for backup
    if _local_logs_enabled:
        try:
            log_dir = logs_dir / "analytics"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "missing_regions.jsonl"
            with open(log_file, 'a', encoding='utf-8') as f:
                entry = {
                    "timestamp": datetime.now().isoformat(),
                    "region_name": region_name,
                    "query": query,
                    "dataset": dataset
                }
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.error(f"Failed to log missing region locally: {e}")
