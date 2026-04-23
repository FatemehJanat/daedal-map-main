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
from mapmover.research_prompt import build_research_system_prompt
from mapmover.research_tools import RESEARCH_TOOL_DEFINITIONS, execute_research_tool
from mapmover.routes.disasters.helpers import msgpack_error, msgpack_response


router = APIRouter()


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


def _history_messages(history: list) -> list[dict]:
    messages = []
    for msg in (history or [])[-8:]:
        role = msg.get("role", "user")
        content = (msg.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        messages.append({"role": role, "content": content})
    return messages


def run_research_chat(*, session_id: str, query: str, chat_history: list | None = None) -> dict:
    manifest = corpus_registry.manifest(session_id)
    if manifest.get("artifact_count", 0) == 0:
        return {
            "type": "chat",
            "message": "No data is loaded into the research corpus yet. Load data in Explore first, then switch back to Research.",
            "corpus": manifest,
        }

    model, temperature = _research_settings()
    system_prompt = build_research_system_prompt(manifest)
    messages = [
        {
            "role": "user",
            "content": "Active corpus manifest:\n```json\n" + json.dumps(manifest, indent=2, default=str) + "\n```",
        },
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
