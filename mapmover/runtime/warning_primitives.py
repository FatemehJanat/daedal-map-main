"""Shared warning payload helpers."""

from __future__ import annotations

from mapmover.request_risk_gate import warn_gate


def build_metric_warning(metric_count: int, metric_display_warn: int = 15) -> dict | None:
    """Build the standard metric-count warning payload when needed."""
    if metric_count <= metric_display_warn:
        return None
    gate = warn_gate(
        lane="human_web_metrics",
        reason=(
            f"Your request has {metric_count} metrics. More than 15 is hard to display well in popups. "
            "Would you like all of them in your order?"
        ),
        soft_cap=metric_display_warn,
        estimated_count=metric_count,
        override_allowed=True,
        measure="metric_count",
        fallback_strategy="warn_then_override",
        suggested_narrowing=["choose a few metrics", "split by topic", "display one metric at a time"],
    )
    return {
        "count": metric_count,
        "message": gate.get("reason"),
        "gate": gate,
    }
