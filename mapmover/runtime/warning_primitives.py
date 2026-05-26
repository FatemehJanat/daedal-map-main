"""Shared warning payload helpers."""

from __future__ import annotations

from mapmover.request_risk_gate import block_gate, warn_gate


DISPLAY_SOFT_CAP = 1000
DISPLAY_HARD_CAP = 5000


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


def build_display_warning(
    available_rows: int,
    *,
    soft_cap: int = DISPLAY_SOFT_CAP,
    hard_cap: int = DISPLAY_HARD_CAP,
    lane: str = "human_web_display",
    soft_narrowing: list[str] | None = None,
    hard_narrowing: list[str] | None = None,
) -> dict | None:
    """Build the standard broad-display warning payload when needed."""
    if available_rows <= soft_cap:
        return None
    if soft_narrowing is None:
        soft_narrowing = ["choose a smaller area", "ask for a top 100 subset", "focus on one state or county"]
    if hard_narrowing is None:
        hard_narrowing = list(soft_narrowing)
    if available_rows > hard_cap:
        gate = block_gate(
            lane=lane,
            reason=(
                f"This request would display about {available_rows:,} map shapes/locations, which exceeds the high-risk "
                f"display threshold of {hard_cap:,}. This may crash the map or make you lose chat history."
            ),
            soft_cap=soft_cap,
            hard_cap=hard_cap,
            estimated_count=available_rows,
            measure="display_features",
            fallback_strategy="narrow_subset",
            suggested_narrowing=hard_narrowing,
        )
        return {
            "level": "hard_cap",
            "row_count": available_rows,
            "soft_cap": soft_cap,
            "hard_cap": hard_cap,
            "message": (
                f"This request would display about {available_rows:,} map shapes/locations. "
                "Are you really sure? This may crash the map and make you lose chat history."
            ),
            "gate": gate,
        }
    gate = warn_gate(
        lane=lane,
        reason=(
            f"This request matches about {available_rows:,} features. Displaying that many at once may hurt map "
            "performance. Narrow it first, or ask for a bounded subset like the top 100 or one state."
        ),
        soft_cap=soft_cap,
        hard_cap=hard_cap,
        estimated_count=available_rows,
        override_allowed=True,
        measure="display_features",
        fallback_strategy="warn_then_override",
        suggested_narrowing=soft_narrowing,
    )
    return {
        "level": "soft_cap",
        "row_count": available_rows,
        "soft_cap": soft_cap,
        "hard_cap": hard_cap,
        "message": gate.get("reason"),
        "gate": gate,
    }


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
