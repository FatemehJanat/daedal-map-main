"""Private control-plane client for runtime account reads."""

from __future__ import annotations

import logging
from typing import Any

from mapmover.hosted_runtime_events import _post_internal, hosted_runtime_control_enabled


logger = logging.getLogger("mapmover")
RUNTIME_ACCOUNT_CONTEXT_PATH = "/internal/runtime-account/context"
RUNTIME_ACCOUNT_CORPUS_PATH = "/internal/runtime-account/corpus"


def load_account_context(user_id: str) -> dict[str, Any] | None:
    if not hosted_runtime_control_enabled():
        return None
    payload = {"user_id": user_id}
    try:
        status_code, body = _post_internal(RUNTIME_ACCOUNT_CONTEXT_PATH, payload)
    except Exception as exc:
        logger.warning("Hosted account-context read failed user=%s: %s", user_id, exc)
        return None
    if status_code != 200 or not isinstance(body, dict):
        logger.warning(
            "Hosted account-context read returned invalid response user=%s status=%s body=%s",
            user_id,
            status_code,
            body,
        )
        return None
    return body


def load_saved_corpus_for_user(user_id: str, corpus_id: str) -> dict[str, Any] | None:
    if not hosted_runtime_control_enabled():
        return None
    payload = {
        "user_id": user_id,
        "corpus_id": corpus_id,
    }
    try:
        status_code, body = _post_internal(RUNTIME_ACCOUNT_CORPUS_PATH, payload)
    except Exception as exc:
        logger.warning("Hosted saved-corpus read failed user=%s corpus=%s: %s", user_id, corpus_id, exc)
        return None
    if status_code != 200 or not isinstance(body, dict):
        logger.warning(
            "Hosted saved-corpus read returned invalid response user=%s corpus=%s status=%s body=%s",
            user_id,
            corpus_id,
            status_code,
            body,
        )
        return None
    corpus = body.get("corpus")
    return corpus if isinstance(corpus, dict) else None
