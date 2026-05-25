"""Clarify and warning helpers for Explore postprocessing."""

from mapmover.request_risk_gate import warn_gate


def build_clarify_result(order: dict, items: list, clarify_message: str) -> dict:
    """Build the standard early-return payload for grounded clarify responses."""
    return {
        "items": items,
        "derived_specs": [],
        "validation_summary": clarify_message,
        "all_valid": False,
        "needs_clarify": True,
        "clarify_message": clarify_message,
        "summary": order.get("summary"),
        "region": order.get("region"),
        "year": order.get("year"),
        "year_start": order.get("year_start"),
        "year_end": order.get("year_end"),
    }


def build_metric_warning(metric_count: int, metric_display_warn: int = 15) -> dict | None:
    """Build the Explore metric-count warning payload when needed."""
    if metric_count <= metric_display_warn:
        return None
    gate = warn_gate(
        lane="human_web_explore_metrics",
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
