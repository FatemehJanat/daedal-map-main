"""Research mode API router endpoints."""

from __future__ import annotations

import json
import os
import asyncio

import msgpack
from anthropic import Anthropic
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from mapmover import logger
from mapmover.auth_context import build_session_cache_key, get_authenticated_user
from mapmover.corpus_registry import corpus_registry
from mapmover.data_loading import get_pack_metadata
from mapmover.research_prompt import build_research_system_prompt
from mapmover.research_tools import RESEARCH_TOOL_DEFINITIONS, execute_research_tool
from mapmover.routes.disasters.helpers import msgpack_error, msgpack_response
from supabase_client import SupabaseClient


router = APIRouter()


def _build_saved_corpus_summary(corpus_row: dict | None) -> dict | None:
    if not isinstance(corpus_row, dict):
        return None

    items = corpus_row.get("research_corpus_items") or []
    packs = []
    source_ids = []
    pack_ids = []
    pack_row_count_total = 0
    pack_file_size_mb_total = 0.0

    for item in items:
        item_type = str(item.get("item_type") or "").strip().lower()
        item_id = str(item.get("item_id") or "").strip()
        if not item_id:
            continue
        if item_type == "pack":
            pack_meta = get_pack_metadata(item_id)
            if pack_meta:
                packs.append(pack_meta)
                pack_ids.append(item_id)
                pack_row_count_total += int(pack_meta.get("row_count_total") or 0)
                pack_file_size_mb_total += float(pack_meta.get("file_size_mb_total") or 0.0)
            else:
                pack_ids.append(item_id)
        elif item_type == "source":
            source_ids.append(item_id)

    return {
        "id": corpus_row.get("id"),
        "name": corpus_row.get("name") or "Untitled corpus",
        "description": corpus_row.get("description") or "",
        "updated_at": corpus_row.get("updated_at"),
        "pack_ids": pack_ids,
        "source_ids": source_ids,
        "pack_count": len(pack_ids),
        "source_count": len(source_ids),
        "estimated_row_count_total": pack_row_count_total,
        "estimated_file_size_mb_total": round(pack_file_size_mb_total, 2),
        "packs": packs,
    }


def _load_saved_corpus_for_user(user_id: str, corpus_id: str) -> dict | None:
    client = SupabaseClient().client
    result = (
        client
        .table("research_corpora")
        .select("id, name, description, updated_at, research_corpus_items(item_type, item_id, position)")
        .eq("user_id", user_id)
        .eq("id", corpus_id)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return _build_saved_corpus_summary(rows[0]) if rows else None


async def _decode_msgpack_request(req: Request) -> dict:
    body_bytes = await req.body()
    return msgpack.unpackb(body_bytes, raw=False)


async def _decode_json_or_msgpack_request(req: Request) -> dict:
    body_bytes = await req.body()
    try:
        return json.loads(body_bytes.decode("utf-8"))
    except Exception:
        return msgpack.unpackb(body_bytes, raw=False)


def _research_settings() -> tuple[str, float]:
    model = os.getenv("RESEARCH_MODEL", "claude-sonnet-4-6").strip() or "claude-sonnet-4-6"
    try:
        temperature = float(os.getenv("RESEARCH_TEMPERATURE", "0.1"))
    except ValueError:
        temperature = 0.1
    return model, temperature


def _extract_text(content_blocks) -> str:
    parts = []
    for block in content_blocks or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _word_chunks(text: str, words_per_chunk: int = 4):
    words = str(text or "").split(" ")
    for idx in range(0, len(words), words_per_chunk):
        chunk = " ".join(words[idx:idx + words_per_chunk])
        if idx + words_per_chunk < len(words):
            chunk += " "
        yield chunk


def _history_messages(history: list, max_messages: int = 12) -> list[dict]:
    messages = []
    for msg in (history or [])[-max_messages:]:
        role = msg.get("role", "user")
        content = (msg.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        messages.append({"role": role, "content": content})
    return messages


def _research_memory_messages(research_memory: dict | None) -> list[dict]:
    if not isinstance(research_memory, dict):
        return []

    messages = []
    original_goal = str(research_memory.get("originalGoal") or "").strip()
    summary = str(research_memory.get("summary") or "").strip()
    compacted_count = research_memory.get("compactedMessageCount")

    if original_goal:
        messages.append(
            {
                "role": "user",
                "content": f"Original research goal from earlier in this session: {original_goal}",
            }
        )
    if summary:
        label = "Compacted memory from earlier research turns"
        if compacted_count:
            label += f" ({compacted_count} earlier messages)"
        messages.append(
            {
                "role": "assistant",
                "content": f"{label}:\n{summary}",
            }
        )
    return messages


def run_research_chat(*, session_id: str, query: str, chat_history: list | None = None, research_memory: dict | None = None) -> dict:
    manifest = corpus_registry.manifest(session_id)
    if manifest.get("artifact_count", 0) == 0 and not manifest.get("saved_corpus"):
        return {
            "type": "chat",
            "message": "No data is loaded into the research corpus yet. Load data in Explore first, then switch back to Research.",
            "corpus": manifest,
        }
    if manifest.get("artifact_count", 0) == 0 and manifest.get("saved_corpus"):
        saved = manifest.get("saved_corpus") or {}
        pack_count = int(saved.get("pack_count") or 0)
        source_count = int(saved.get("source_count") or 0)
        return {
            "type": "chat",
            "message": (
                f'Research workspace "{saved.get("name") or "Saved corpus"}" is selected, '
                f'with {pack_count} pack{"s" if pack_count != 1 else ""}'
                + (
                    f' and {source_count} direct source{"s" if source_count != 1 else ""}'
                    if source_count
                    else ""
                )
                + ". I can use that workspace definition to stay oriented, but I do not have loaded research artifacts to analyze yet. "
                  "Load the relevant data in Explore, or expand the Research loader later so this corpus hydrates concrete artifacts."
            ),
            "corpus": manifest,
        }

    model, temperature = _research_settings()
    system_prompt = build_research_system_prompt(manifest)
    messages = [
        {
            "role": "user",
            "content": "Active corpus manifest:\n```json\n" + json.dumps(manifest, indent=2, default=str) + "\n```",
        },
        *_research_memory_messages(research_memory),
        *_history_messages(chat_history or []),
        {"role": "user", "content": query},
    ]

    client = Anthropic()
    max_tool_iterations = 4
    response = None
    for _iteration in range(max_tool_iterations + 1):
        response = client.messages.create(
            model=model,
            system=system_prompt,
            messages=messages,
            tools=RESEARCH_TOOL_DEFINITIONS,
            temperature=temperature,
            max_tokens=1400,
        )

        if response.stop_reason != "tool_use":
            break

        assistant_content = []
        tool_results = []
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                tool_result = execute_research_tool(session_id, block.name, block.input)
                assistant_content.append(block)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(tool_result, default=str),
                    }
                )
            else:
                assistant_content.append(block)

        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": tool_results})

    text = _extract_text(response.content if response else [])
    return {
        "type": "chat",
        "message": text or "I could not produce a research answer from the active corpus.",
        "corpus": manifest,
    }


@router.post("/api/research/corpus")
async def research_corpus_endpoint(req: Request):
    """Return compact active corpus manifest for a session."""
    try:
        body = await _decode_msgpack_request(req)
        frontend_session_id = body.get("sessionId", "anonymous")
        auth_user = get_authenticated_user(req)
        session_id = build_session_cache_key(frontend_session_id, auth_user)
        return msgpack_response(corpus_registry.manifest(session_id))
    except Exception as e:
        logger.exception("Research corpus snapshot error")
        return msgpack_error(str(e), 500)


@router.post("/api/research/load-saved-corpus")
async def research_load_saved_corpus_endpoint(req: Request):
    """Attach a saved account corpus definition to the active Research session."""
    try:
        body = await _decode_msgpack_request(req)
        corpus_id = str(body.get("corpusId") or "").strip()
        if not corpus_id:
            return msgpack_error("No corpusId provided", 400)

        auth_user = get_authenticated_user(req)
        user_id = (auth_user or {}).get("id")
        if not user_id:
            return msgpack_error("Authentication required to load a saved corpus", 401)

        frontend_session_id = body.get("sessionId", "anonymous")
        session_id = build_session_cache_key(frontend_session_id, auth_user)
        saved_corpus = _load_saved_corpus_for_user(user_id, corpus_id)
        if not saved_corpus:
            return msgpack_error("Saved corpus not found", 404)

        corpus_registry.set_saved_corpus(session_id, saved_corpus)
        manifest = corpus_registry.manifest(session_id)
        return msgpack_response({
            "type": "saved_corpus_loaded",
            "message": f'Loaded "{saved_corpus.get("name")}" into the Research workspace.',
            "corpus": manifest,
        })
    except Exception as e:
        logger.exception("Research saved corpus load error")
        return msgpack_error(str(e), 500)


@router.post("/chat/research")
async def research_chat_endpoint(req: Request):
    """Blocking Research chat endpoint."""
    try:
        body = await _decode_msgpack_request(req)
        query = body.get("query", "")
        if not query:
            return msgpack_error("No query provided", 400)
        frontend_session_id = body.get("sessionId", "anonymous")
        auth_user = get_authenticated_user(req)
        session_id = build_session_cache_key(frontend_session_id, auth_user)
        result = run_research_chat(
            session_id=session_id,
            query=query,
            chat_history=body.get("chatHistory", []),
            research_memory=body.get("researchMemory"),
        )
        return msgpack_response(result)
    except Exception as e:
        logger.exception("Research chat error")
        return msgpack_response({"type": "error", "message": "Research mode encountered an error. Please try again."}, status_code=500)


@router.post("/chat/research/stream")
async def research_chat_stream_endpoint(req: Request):
    """Streaming Research chat endpoint using existing SSE stage shape."""
    body = await _decode_json_or_msgpack_request(req)

    async def generate_events():
        try:
            query = body.get("query", "")
            if not query:
                yield f"data: {json.dumps({'stage': 'complete', 'result': {'type': 'error', 'message': 'No query provided'}})}\n\n"
                return
            frontend_session_id = body.get("sessionId", "anonymous")
            auth_user = get_authenticated_user(req)
            session_id = build_session_cache_key(frontend_session_id, auth_user)

            yield f"data: {json.dumps({'stage': 'corpus', 'message': 'Reading active corpus...'})}\n\n"
            yield f"data: {json.dumps({'stage': 'thinking', 'message': 'Researching loaded data...'})}\n\n"

            task = asyncio.create_task(asyncio.to_thread(
                run_research_chat,
                session_id=session_id,
                query=query,
                chat_history=body.get("chatHistory", []),
                research_memory=body.get("researchMemory"),
            ))
            heartbeat_messages = [
                "Inspecting the active corpus...",
                "Querying loaded artifacts...",
                "Checking values before answering...",
                "Still working through the research context...",
            ]
            heartbeat_index = 0
            while not task.done():
                await asyncio.sleep(3)
                if task.done():
                    break
                message = heartbeat_messages[heartbeat_index % len(heartbeat_messages)]
                heartbeat_index += 1
                yield f"data: {json.dumps({'stage': 'thinking', 'message': message})}\n\n"

            result = await task
            yield f"data: {json.dumps({'stage': 'writing', 'message': 'Writing research answer...'})}\n\n"
            if result.get("type") == "chat" and result.get("message"):
                yield f"data: {json.dumps({'stage': 'answer_start', 'message': ''})}\n\n"
                for chunk in _word_chunks(result.get("message", "")):
                    yield f"data: {json.dumps({'stage': 'delta', 'text': chunk})}\n\n"
                    await asyncio.sleep(0.035)
            yield f"data: {json.dumps({'stage': 'complete', 'result': result})}\n\n"
        except Exception:
            logger.exception("Research chat stream error")
            error_result = {"type": "error", "message": "Research mode encountered an error. Please try again."}
            yield f"data: {json.dumps({'stage': 'complete', 'result': error_result})}\n\n"

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
