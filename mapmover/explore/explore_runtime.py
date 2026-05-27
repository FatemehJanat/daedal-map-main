"""Explore runtime workflow helpers."""

from __future__ import annotations


def preprocess_explore_request(
    *,
    query: str,
    viewport,
    active_overlays,
    cache_stats,
    saved_order_names,
    time_state,
    loaded_data,
    resolved_location,
    preprocess_query_func,
    apply_resolved_location_override_func,
) -> dict:
    """Run the deterministic Explore preprocessing stage for one request."""
    hints = preprocess_query_func(
        query,
        viewport=viewport,
        active_overlays=active_overlays,
        cache_stats=cache_stats,
        saved_order_names=saved_order_names,
        time_state=time_state,
        loaded_data=loaded_data,
    )
    hints["original_query"] = query
    return apply_resolved_location_override_func(hints, resolved_location)


def finalize_explore_order_result(
    *,
    result: dict,
    hints: dict,
    force_metrics: bool,
    metric_warning_policy,
    postprocess_order_func,
    get_display_items_func,
    build_clarify_response_func,
    build_metric_warning_response_func,
    build_order_response_func,
) -> tuple[str, dict]:
    """Postprocess one Explore order-taker result into a final route payload."""
    processed = postprocess_order_func(result["order"], hints, metric_warning_policy=metric_warning_policy)
    result_summary = processed.get("summary") or result.get("summary") or result.get("order", {}).get("summary") or "Data request"

    if processed.get("needs_clarify"):
        return (
            "clarify_multiple_paths",
            build_clarify_response_func(
                processed.get("clarify_message") or processed.get("validation_summary") or "I need a more specific path before I can run that.",
                summary=result_summary,
                full_order=processed,
            ),
        )

    if not processed.get("all_valid", True):
        return (
            "clarify_invalid_order",
            build_clarify_response_func(
                processed.get("validation_summary") or "I need a more specific executable request before I can run that.",
                summary=result_summary,
                full_order=processed,
            ),
        )

    display_items = get_display_items_func(processed.get("items", []), processed.get("derived_specs", []))
    if processed.get("metric_warning") and not force_metrics:
        return (
            "metric_warning",
            build_metric_warning_response_func(
                result["order"],
                processed,
                display_items=display_items,
                summary=result_summary,
            ),
        )

    return (
        "order",
        build_order_response_func(
            result["order"],
            processed,
            display_items=display_items,
            summary=result_summary,
        ),
    )
