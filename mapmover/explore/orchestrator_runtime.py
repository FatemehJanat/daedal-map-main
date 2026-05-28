"""Lane-owned Explore orchestrator runtime helpers."""

from __future__ import annotations

from mapmover.foundation_helpers import load_runtime_explainer_helpers
from mapmover.runtime.orchestrator_helper_runtime import (
    best_source_metadata,
    requested_limit_from_order,
)
from mapmover.runtime.orchestrator_result_cap import cap_runtime_payload
from mapmover.runtime.orchestrator_threading import (
    run_catalog_scoped_to_thread,
    run_catalog_scoped_to_thread_with_progress,
)


async def run_explore_interpret(
    *,
    query: str,
    chat_history: list,
    hints: dict,
    usage_recorder,
    catalog_surface: str | None,
    interpret_request_func,
    system_prompt_builder,
    system_prompt_block_builder,
) -> dict:
    return await run_catalog_scoped_to_thread(
        catalog_surface=catalog_surface,
        func=interpret_request_func,
        user_query=query,
        chat_history=chat_history,
        hints=hints,
        usage_recorder=usage_recorder,
        system_prompt_builder=system_prompt_builder,
        system_prompt_block_builder=system_prompt_block_builder,
    )


async def run_explore_interpret_with_progress(
    *,
    query: str,
    chat_history: list,
    hints: dict,
    usage_recorder,
    catalog_surface: str | None,
    progress_bus_cls,
    interpret_request_func,
    system_prompt_builder,
    system_prompt_block_builder,
) -> tuple[object, asyncio.Task]:
    return await run_catalog_scoped_to_thread_with_progress(
        catalog_surface=catalog_surface,
        progress_bus_cls=progress_bus_cls,
        func=interpret_request_func,
        user_query=query,
        chat_history=chat_history,
        hints=hints,
        usage_recorder=usage_recorder,
        system_prompt_builder=system_prompt_builder,
        system_prompt_block_builder=system_prompt_block_builder,
    )


def apply_explore_runtime_result_cap(
    result: dict,
    *,
    confirmed_order: dict | None = None,
    load_source_metadata_func=None,
) -> dict:
    if not isinstance(result, dict) or load_source_metadata_func is None:
        return result
    source_id = str(
        result.get("source_id")
        or result.get("dataset")
        or (((result.get("order") or {}).get("items") or [{}])[0].get("source_id"))
        or ""
    ).strip()
    if not source_id:
        return result
    requested_limit = requested_limit_from_order(confirmed_order)
    payload, _cap_info = cap_runtime_payload(
        result,
        source_id=source_id,
        load_source_metadata_func=load_source_metadata_func,
        requested_limit=requested_limit,
    )
    return payload


def maybe_build_explore_explainer_response(
    *,
    query: str,
    hints: dict | None,
    build_chat_response_func,
    auth_user: dict | None = None,
    load_source_metadata_func=None,
    load_source_reference_func=None,
) -> dict | None:
    if load_source_metadata_func is None:
        return None
    helper = load_runtime_explainer_helpers()
    build_explainer_response_func = helper["build_explainer_response"]

    source_metadata = best_source_metadata(hints or {}, load_source_metadata_func)
    if not source_metadata:
        return None
    source_reference = None
    if load_source_reference_func is not None:
        source_id = str(source_metadata.get("source_id") or "").strip()
        if source_id:
            source_reference = load_source_reference_func(source_id)

    explainer = build_explainer_response_func(source_metadata, query, source_reference)
    if not isinstance(explainer, dict):
        return None

    return build_chat_response_func(
        explainer.get("text") or "I can describe that source, but I do not have a fuller summary yet.",
        auth_user=auth_user,
        source_id=explainer.get("source_id"),
        pack_id=explainer.get("pack_id"),
        explainer_sections=explainer.get("sections"),
        stub_order=explainer.get("stub_order"),
    )
