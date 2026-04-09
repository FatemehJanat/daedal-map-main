"""
Logging and analytics functions for query tracking and error monitoring.
"""

import json
import logging
import os
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

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


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
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
    raw_ip = (ip_address or "").strip()
    if not raw_ip:
        return None
    salt = os.getenv("API_ANALYTICS_IP_SALT", "").strip()
    digest = hashlib.sha256(f"{salt}:{raw_ip}".encode("utf-8")).hexdigest()
    return digest


def log_api_query_event(
    *,
    request_id: str,
    capability_id: str,
    pack_id: str,
    source_id: str,
    decision: str,
    payment_rail: str | None = None,
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
    amount_charged_usd_cents: int | None = None,
    revenue_attributed_usd_cents: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    event = {
        "timestamp": datetime.utcnow().isoformat(),
        "request_id": request_id,
        "capability_id": capability_id,
        "pack_id": pack_id,
        "source_id": source_id,
        "decision": decision,
        "payment_rail": payment_rail,
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
        "amount_charged_usd_cents": amount_charged_usd_cents,
        "revenue_attributed_usd_cents": revenue_attributed_usd_cents,
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
        try:
            supabase_client.log_api_usage_event(
                event_kind=decision or "request_completed",
                request_id=request_id,
                capability_id=capability_id,
                pack_id=pack_id,
                source_id=source_id,
                query_granularity=query_granularity,
                decision=decision,
                payment_rail=payment_rail,
                auth_user_id=auth_user_id,
                ip_hash=ip_hash,
                status_code=status_code,
                row_count=row_count or 0,
                response_size_bytes=response_size_bytes or 0,
                execution_latency_ms=execution_latency_ms,
                warnings_count=warnings_count or 0,
                error_code=error_code,
                settlement_id=settlement_id,
                amount_charged_usd_cents=amount_charged_usd_cents,
                revenue_attributed_usd_cents=revenue_attributed_usd_cents,
                metadata=event,
            )
        except Exception as e:
            logger.error(f"Failed to log API query event to Supabase: {e}")


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
    if supabase_client:
        try:
            supabase_client.log_security_event(
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
        except Exception as e:
            logger.error(f"Failed to log route security event to Supabase: {e}")


def get_supabase():
    """Get the Supabase client, initializing if needed."""
    global _supabase_client
    if _supabase_client is None:
        try:
            from supabase_client import get_supabase_client
            _supabase_client = get_supabase_client()
            if _supabase_client:
                logger.info("Supabase client initialized - cloud logging enabled")
            else:
                logger.info("Supabase not configured - using local logging only")
        except Exception as e:
            logger.warning(f"Could not initialize Supabase client: {e}")
            _supabase_client = False  # Mark as failed to avoid retrying
    return _supabase_client if _supabase_client else None


def log_conversation(session_id, query, response_text, intent=None,
                     dataset_selected=None, results_count=0, endpoint=None):
    """
    Log a conversation message to session-based storage.

    Each session (browser tab) gets one row in Supabase with all messages.
    Also logs locally to JSONL for backup.

    Args:
        session_id: Unique session identifier from frontend
        query: The user's query string
        response_text: The assistant's response
        intent: The query intent ('chat', 'clarify', 'fetch_data', 'modify_data', 'meta')
        dataset_selected: Which dataset was used (None for chat-only queries)
        results_count: Number of results returned (0 for chat-only queries)
        endpoint: Which endpoint the request came from ('chat', 'location', etc.)
    """
    # Build analytics data for local logging
    analytics_data = {
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "query": query,
        "response": response_text[:500] if response_text else None,  # Truncate for local log
        "intent": intent,
        "dataset_selected": dataset_selected,
        "results_count": results_count,
        "endpoint": endpoint
    }

    # Always log locally first
    if _local_logs_enabled:
        try:
            with open(analytics_log_path, 'a', encoding='utf-8') as f:
                json.dump(analytics_data, f, ensure_ascii=False)
                f.write('\n')
        except Exception as e:
            logger.error(f"Failed to log analytics locally: {e}")

    # Log to Supabase session if configured
    supabase_client = get_supabase()
    if supabase_client and session_id:
        try:
            supabase_client.log_session_message(
                session_id=session_id,
                user_query=query,
                assistant_response=response_text or "",
                intent=intent,
                dataset_selected=dataset_selected,
                results_count=results_count
            )
        except Exception as e:
            logger.error(f"Failed to log session to Supabase: {e}")


def log_missing_geometry(country_names, query=None, dataset=None, region=None):
    """
    Log countries/places that are missing map geometry.

    This helps track which geometries need to be added to Countries.csv.

    Args:
        country_names: List of country/place names missing geometry
        query: The query that triggered this (optional)
        dataset: The dataset being queried (optional)
        region: The region filter used (optional)
    """
    if not country_names:
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
        try:
            supabase_client.log_missing_geometry(
                country_names=country_names,
                query=query,
                dataset=dataset,
                region=region
            )
        except Exception as e:
            logger.error(f"Failed to log missing geometries to Supabase: {e}")


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
        try:
            supabase_client.log_error(
                error_type=error_type,
                error_message=error_message,
                query=query,
                traceback=tb,
                metadata=metadata
            )
        except Exception as e:
            logger.error(f"Failed to log error to Supabase: {e}")


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
        try:
            supabase_client.log_missing_region(
                region_name=region_name,
                query=query,
                dataset=dataset
            )
        except Exception as e:
            logger.error(f"Failed to log missing region to Supabase: {e}")

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
