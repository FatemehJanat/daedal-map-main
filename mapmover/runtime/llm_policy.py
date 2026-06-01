"""Shared lane-owned LLM selection helpers.

Model/provider choice should live at the orchestrator boundary, not inside
individual lane internals. This module resolves the default selection for one
lane and leaves room for future per-user overrides.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Mapping


@dataclass(frozen=True)
class LLMSelection:
    provider: str
    model: str
    temperature: float


_DEFAULT_SELECTIONS: dict[str, tuple[str, str, float]] = {
    "explore_fast_haiku_default": ("anthropic", "claude-haiku-4-5-20251001", 0.0),
    "research_deep_sonnet_opus_default": ("anthropic", "claude-sonnet-4-6", 0.1),
    "ops_fast_haiku_default": ("anthropic", "claude-haiku-4-5-20251001", 0.0),
    "ops_balanced_sonnet_default": ("anthropic", "claude-sonnet-4-6", 0.1),
}

_ENV_PREFIX_BY_POLICY: dict[str, str] = {
    "explore_fast_haiku_default": "EXPLORE",
    "research_deep_sonnet_opus_default": "RESEARCH",
    "ops_fast_haiku_default": "OPS",
    "ops_balanced_sonnet_default": "OPS",
}


def _env_text(
    env: Mapping[str, str],
    *names: str,
    default: str,
) -> str:
    for name in names:
        value = str(env.get(name, "") or "").strip()
        if value:
            return value
    return default


def _env_float(
    env: Mapping[str, str],
    *names: str,
    default: float,
) -> float:
    for name in names:
        raw = str(env.get(name, "") or "").strip()
        if not raw:
            continue
        try:
            return float(raw)
        except ValueError:
            continue
    return default


def resolve_lane_llm_selection(
    model_policy: str,
    *,
    override: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> LLMSelection:
    """Resolve provider/model/temperature for one orchestrator model policy."""
    policy_key = str(model_policy or "").strip()
    if policy_key not in _DEFAULT_SELECTIONS:
        raise KeyError(f"Unknown orchestrator model policy: {model_policy}")

    default_provider, default_model, default_temperature = _DEFAULT_SELECTIONS[policy_key]
    prefix = _ENV_PREFIX_BY_POLICY[policy_key]
    source_env = env or os.environ

    provider = _env_text(
        source_env,
        f"{prefix}_LLM_PROVIDER",
        "DEFAULT_LLM_PROVIDER",
        default=default_provider,
    ).lower()
    model = _env_text(
        source_env,
        f"{prefix}_MODEL",
        "DEFAULT_LLM_MODEL",
        "ORDER_TAKER_MODEL" if prefix == "EXPLORE" else "",
        default=default_model,
    )
    temperature = _env_float(
        source_env,
        f"{prefix}_TEMPERATURE",
        "DEFAULT_LLM_TEMPERATURE",
        "ORDER_TAKER_TEMPERATURE" if prefix == "EXPLORE" else "",
        default=default_temperature,
    )

    if override:
        override_provider = str(override.get("provider") or "").strip().lower()
        override_model = str(override.get("model") or "").strip()
        override_temperature = override.get("temperature")
        if override_provider:
            provider = override_provider
        if override_model:
            model = override_model
        if override_temperature is not None:
            try:
                temperature = float(override_temperature)
            except (TypeError, ValueError):
                pass

    return LLMSelection(
        provider=provider,
        model=model,
        temperature=temperature,
    )


def build_provider_client(selection: LLMSelection):
    """Return the provider client for this selection.

    Only Anthropic is wired today, but the selection object is provider-aware so
    future user/provider preference work has one shared entry point.
    """
    provider = str(selection.provider or "").strip().lower()
    if provider == "anthropic":
        from anthropic import Anthropic

        return Anthropic()
    raise ValueError(f"Unsupported LLM provider: {selection.provider}")
