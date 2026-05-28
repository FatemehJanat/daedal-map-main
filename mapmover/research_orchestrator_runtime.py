"""Lane-owned Research orchestrator runtime helpers."""

from __future__ import annotations

from mapmover.runtime.orchestrator_result_cap import (
    cap_runtime_result_field,
    cap_runtime_result_list_field,
)
from mapmover.runtime.orchestrator_threading import (
    run_catalog_scoped_to_thread,
    run_catalog_scoped_to_thread_with_progress,
)


def apply_research_runtime_result_cap(
    result: dict,
    *,
    load_source_metadata_func=None,
) -> dict:
    if not isinstance(result, dict) or load_source_metadata_func is None:
        return result
    next_result, cap_info = cap_runtime_result_field(
        result,
        field_name="display",
        source_id=str(((result.get("display") or {}).get("source_id") or result.get("source_id") or "")).strip(),
        load_source_metadata_func=load_source_metadata_func,
    )
    if cap_info:
        next_result["cap_info"] = cap_info
        next_result["truncated"] = True

    next_result, cap_infos = cap_runtime_result_list_field(
        next_result,
        field_name="displays",
        source_id_func=lambda display_item, outer_result: display_item.get("source_id") or outer_result.get("source_id"),
        load_source_metadata_func=load_source_metadata_func,
    )
    if cap_infos and "cap_info" not in next_result:
        next_result["cap_info"] = cap_infos[-1]
        next_result["truncated"] = True
    return next_result


async def run_research_orchestrator_call(
    *,
    session_id: str,
    query: str,
    chat_history: list | None,
    research_memory: dict | None,
    force_large_display: bool,
    usage_recorder,
    rescue_usage_recorder,
    catalog_surface: str | None,
    run_research_chat_func,
    load_source_metadata_func,
    display_warning_policy,
    retry_policy,
    system_prompt_builder,
    system_prompt_block_builder,
    llm_selection,
) -> dict:
    result = await run_catalog_scoped_to_thread(
        catalog_surface=catalog_surface,
        func=run_research_chat_func,
        session_id=session_id,
        query=query,
        chat_history=chat_history,
        research_memory=research_memory,
        force_large_display=force_large_display,
        usage_recorder=usage_recorder,
        rescue_usage_recorder=rescue_usage_recorder,
        display_warning_policy=display_warning_policy,
        retry_policy=retry_policy,
        system_prompt_builder=system_prompt_builder,
        system_prompt_block_builder=system_prompt_block_builder,
        llm_selection=llm_selection,
    )
    return apply_research_runtime_result_cap(
        result,
        load_source_metadata_func=load_source_metadata_func,
    )


async def run_research_orchestrator_with_progress(
    *,
    session_id: str,
    query: str,
    chat_history: list | None,
    research_memory: dict | None,
    force_large_display: bool,
    usage_recorder,
    rescue_usage_recorder,
    catalog_surface: str | None,
    progress_bus_cls,
    run_research_chat_func,
    load_source_metadata_func,
    display_warning_policy,
    retry_policy,
    system_prompt_builder,
    system_prompt_block_builder,
    llm_selection,
) -> tuple[object, asyncio.Task]:
    bus, raw_task = await run_catalog_scoped_to_thread_with_progress(
        catalog_surface=catalog_surface,
        progress_bus_cls=progress_bus_cls,
        func=run_research_chat_func,
        session_id=session_id,
        query=query,
        chat_history=chat_history,
        research_memory=research_memory,
        force_large_display=force_large_display,
        usage_recorder=usage_recorder,
        rescue_usage_recorder=rescue_usage_recorder,
        display_warning_policy=display_warning_policy,
        retry_policy=retry_policy,
        system_prompt_builder=system_prompt_builder,
        system_prompt_block_builder=system_prompt_block_builder,
        llm_selection=llm_selection,
    )

    async def capped_result_task():
        result = await raw_task
        return apply_research_runtime_result_cap(
            result,
            load_source_metadata_func=load_source_metadata_func,
        )

    return bus, asyncio.create_task(capped_result_task())
