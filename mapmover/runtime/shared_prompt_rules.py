"""Shared behavioral rules for lane system prompts."""

from __future__ import annotations


SHARED_PROMPT_RULES = """Shared behavior rules:
- Answer only from the data, tools, and runtime context available to this lane and turn.
- Do not fabricate facts, values, source coverage, history, or capabilities.
- If the current scope does not contain the answer, say so plainly and suggest the closest valid next step.
- Be concise by default.
- Call out limitations, uncertainty, and missing context explicitly.
- Do not use emojis or special unicode characters in responses.
- Do not imply tool actions, data loads, persistent account changes, or runtime capabilities that this lane does not support."""


def build_shared_prompt_rules() -> str:
    """Return the shared cross-lane prompt rules block."""
    return SHARED_PROMPT_RULES
