"""Explore lane result-adaptation helpers shared by chat endpoints."""

from __future__ import annotations

from mapmover.catalog_surface import catalog_surface_scope
from mapmover.explore.chat_lane_runtime import (
    build_chat_payload,
    build_clarify_payload,
    build_navigate_payload,
)


def build_explore_final_result(
    *,
    result: dict,
    query: str,
    hints: dict,
    auth_user: dict | None,
    catalog_surface: str | None,
    force_metrics: bool,
    explore_orchestrator,
    build_clarify_response_func,
    build_metric_warning_response_func,
    build_order_response_func,
    build_navigate_response_func,
    execute_geometry_overlay_func,
    build_disambiguate_response_func,
    build_filter_update_response_func,
    build_overlay_toggle_response_func,
    build_chat_response_func,
    load_source_metadata_func,
    load_source_reference_func,
) -> tuple[str, dict, str | None]:
    result_type = result.get("type") or "chat"
    if result_type == "order":
        with catalog_surface_scope(catalog_surface):
            response_tag, final_result = explore_orchestrator.finalize_order(
                result=result,
                hints=hints,
                force_metrics=force_metrics,
                build_clarify_response_func=build_clarify_response_func,
                build_metric_warning_response_func=build_metric_warning_response_func,
                build_order_response_func=build_order_response_func,
            )
        return response_tag, final_result, None

    if result_type == "navigate":
        return (
            "navigate",
            build_navigate_payload(
                result,
                query=query,
                build_navigate_response_func=build_navigate_response_func,
                execute_geometry_overlay_func=execute_geometry_overlay_func,
            ),
            None,
        )

    if result_type == "disambiguate":
        return "disambiguate", build_disambiguate_response_func(result, original_query=query), None

    if result_type == "filter_update":
        return "filter_update", build_filter_update_response_func(result), None

    if result_type == "overlay_toggle":
        return "overlay_toggle", build_overlay_toggle_response_func(result), None

    if result_type == "clarify":
        return (
            "clarify",
            build_clarify_payload(result, compact_followup_func=explore_orchestrator.compact_followup),
            None,
        )

    final_result, chat_message = build_chat_payload(
        result,
        query=query,
        hints=hints,
        auth_user=auth_user,
        compact_followup_func=explore_orchestrator.compact_followup,
        maybe_build_explainer_response_func=explore_orchestrator.maybe_build_explainer_response,
        build_chat_response_func=build_chat_response_func,
        load_source_metadata_func=load_source_metadata_func,
        load_source_reference_func=load_source_reference_func,
    )
    return "chat", final_result, chat_message
