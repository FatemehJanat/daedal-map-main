"""Shared warning payload helpers."""

from __future__ import annotations

from mapmover.request_risk_gate import block_gate, warn_gate
from mapmover.runtime.warning_policy import (
    DEFAULT_DISPLAY_WARNING_POLICY,
    DEFAULT_METRIC_WARNING_POLICY,
    DisplayWarningPolicy,
    MetricWarningPolicy,
)


def build_metric_warning(
    metric_count: int,
    policy: MetricWarningPolicy = DEFAULT_METRIC_WARNING_POLICY,
) -> dict | None:
    """Build the standard metric-count warning payload when needed."""
    if metric_count <= policy.threshold:
        return None
    gate = warn_gate(
        lane=policy.lane,
        reason=(
            f"Your request has {metric_count} metrics. More than {policy.threshold} is hard to display well in popups. "
            "Would you like all of them in your order?"
        ),
        soft_cap=policy.threshold,
        estimated_count=metric_count,
        override_allowed=policy.override_allowed,
        measure=policy.measure,
        fallback_strategy=policy.fallback_strategy,
        suggested_narrowing=list(policy.suggested_narrowing),
    )
    return {
        "count": metric_count,
        "message": gate.get("reason"),
        "gate": gate,
    }


def build_metric_warning_result(
    order: dict,
    processed: dict,
    *,
    display_items: list,
    summary: str,
) -> dict:
    """Build the shared metric-warning response payload."""
    warning = processed.get("metric_warning") or {}
    return {
        "type": "metric_warning",
        "message": warning.get("message"),
        "metric_count": warning.get("count"),
        "gate": warning.get("gate"),
        "pending_order": {**order, "items": display_items, "derived_specs": processed.get("derived_specs", [])},
        "full_order": processed,
        "summary": summary,
    }


def build_display_warning(
    available_rows: int,
    *,
    policy: DisplayWarningPolicy = DEFAULT_DISPLAY_WARNING_POLICY,
) -> dict | None:
    """Build the standard broad-display warning payload when needed."""
    if available_rows <= policy.soft_cap:
        return None
    if available_rows > policy.hard_cap:
        gate = block_gate(
            lane=policy.lane,
            reason=(
                f"This request would display about {available_rows:,} map shapes/locations, which exceeds the high-risk "
                f"display threshold of {policy.hard_cap:,}. This may crash the map or make you lose chat history."
            ),
            soft_cap=policy.soft_cap,
            hard_cap=policy.hard_cap,
            estimated_count=available_rows,
            measure=policy.measure,
            fallback_strategy="narrow_subset",
            suggested_narrowing=list(policy.hard_narrowing),
        )
        return {
            "level": "hard_cap",
            "row_count": available_rows,
            "soft_cap": policy.soft_cap,
            "hard_cap": policy.hard_cap,
            "message": (
                f"This request would display about {available_rows:,} map shapes/locations. "
                "Are you really sure? This may crash the map and make you lose chat history."
            ),
            "gate": gate,
        }
    gate = warn_gate(
        lane=policy.lane,
        reason=(
            f"This request matches about {available_rows:,} features. Displaying that many at once may hurt map "
            "performance. Narrow it first, or ask for a bounded subset like the top 100 or one state."
        ),
        soft_cap=policy.soft_cap,
        hard_cap=policy.hard_cap,
        estimated_count=available_rows,
        override_allowed=policy.override_allowed,
        measure=policy.measure,
        fallback_strategy=policy.fallback_strategy,
        suggested_narrowing=list(policy.soft_narrowing),
    )
    return {
        "level": "soft_cap",
        "row_count": available_rows,
        "soft_cap": policy.soft_cap,
        "hard_cap": policy.hard_cap,
        "message": gate.get("reason"),
        "gate": gate,
    }


def evaluate_display_warning_gate(
    available_rows: int,
    *,
    policy: DisplayWarningPolicy = DEFAULT_DISPLAY_WARNING_POLICY,
    force_large_display: bool = False,
) -> tuple[dict | None, bool]:
    """Return `(warning, should_interrupt)` for large-display gating.

    This keeps the decision logic aligned across Explore, Research, and any
    future lane that wants shared default warning behavior with lane-specific
    policy overrides.
    """
    warning = build_display_warning(available_rows, policy=policy)
    if not warning:
        return None, False
    should_interrupt = warning.get("level") == "hard_cap" or (
        warning.get("level") == "soft_cap" and not force_large_display
    )
    return warning, should_interrupt


def build_interrupted_display_warning_payload(
    warning: dict,
    *,
    rows: list | None = None,
    truncated: bool = True,
    **extra_fields,
) -> dict:
    """Build the shared interrupted payload used below final lane responses."""
    warning = warning or {}
    return {
        "rows": list(rows or []),
        "row_count": warning.get("row_count"),
        "truncated": bool(truncated),
        "display_warning": warning,
        **extra_fields,
    }


def interrupt_display_payload_if_needed(
    available_rows: int,
    *,
    policy: DisplayWarningPolicy = DEFAULT_DISPLAY_WARNING_POLICY,
    force_large_display: bool = False,
    rows: list | None = None,
    truncated: bool = True,
    **extra_fields,
) -> dict | None:
    """Return a shared interrupted payload when display gating should stop work."""
    warning, should_interrupt = evaluate_display_warning_gate(
        available_rows,
        policy=policy,
        force_large_display=force_large_display,
    )
    if not should_interrupt:
        return None
    return build_interrupted_display_warning_payload(
        warning or {},
        rows=rows,
        truncated=truncated,
        **extra_fields,
    )


def build_display_warning_result(
    warning: dict,
    *,
    override_allowed: bool = True,
    **extra_fields,
) -> dict:
    """Build the shared display-warning response payload."""
    warning = warning or {}
    return {
        "type": "display_warning",
        "message": warning.get("message"),
        "warning_level": warning.get("level"),
        "row_count": warning.get("row_count"),
        "soft_cap": warning.get("soft_cap"),
        "hard_cap": warning.get("hard_cap"),
        "override_allowed": bool(override_allowed),
        "gate": warning.get("gate"),
        **extra_fields,
    }
