"""Account-credit helpers for hosted Research billing."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional

from mapmover import logger
from supabase_client import get_supabase_client


MICRO_USD_PER_DOLLAR = 1_000_000
RESEARCH_NEGATIVE_FLOOR_MICRO_USD = -1_000_000
RESEARCH_TOP_UP_CTA = "top_up"
RESEARCH_TOP_UP_URL = "/settings/account"


@dataclass
class ResearchBudgetDecision:
    allowed: bool
    balance_micro_usd: int
    floor_micro_usd: int = RESEARCH_NEGATIVE_FLOOR_MICRO_USD
    error_code: Optional[str] = None
    message: Optional[str] = None
    cta: Optional[str] = None
    cta_url: Optional[str] = None


def _to_micro_usd(cost_usd: Decimal) -> int:
    scaled = (cost_usd * Decimal(MICRO_USD_PER_DOLLAR)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(scaled)


def get_user_balance_micro_usd(user_id: str) -> Optional[int]:
    """Fetch authoritative balance from Supabase. Used by settlement only;
    the pre-call hot path reads `account_locked` from the cached profile via
    `_get_cached_profile()` in `mapmover.llm_usage` to avoid a round trip."""
    client = get_supabase_client()
    if client is None:
        return None
    profile = client.get_profile(user_id)
    if not isinstance(profile, dict):
        return None
    try:
        return int(profile.get("balance_micro_usd") or 0)
    except Exception:
        return None


def _cached_profile(user_id: str) -> Optional[dict]:
    """Read from the 5-minute in-process profile cache used by classify_caller.

    Returns None if the cache layer is unavailable. The caller decides whether
    to fail open or block on cache miss.
    """
    try:
        from mapmover.llm_usage import _get_cached_profile  # type: ignore
    except Exception:
        return None
    try:
        return _get_cached_profile(user_id)
    except Exception:
        return None


def check_research_budget(caller_ctx: dict, model: str | None = None) -> ResearchBudgetDecision:
    """Pre-call budget gate. Reads `account_locked` from the cached profile so
    the hot path costs zero Supabase round trips. Settlement still runs
    post-call against the authoritative ledger inside
    `deduct_micro_credits_with_floor()`.

    Lock semantics: `account_locked = TRUE` whenever the most recent settlement
    pushed `balance_micro_usd` below zero. The previous turn already completed
    (settlement is post-call); this gate rejects the *next* turn. Top-up via
    `grant_micro_credits()` clears the flag in the same transaction.
    """
    caller_kind = str((caller_ctx or {}).get("caller_kind") or "").strip().lower()
    user_id = str((caller_ctx or {}).get("auth_user_id") or "").strip()

    if caller_kind not in {"authenticated", "qa_suite"} or not user_id:
        return ResearchBudgetDecision(allowed=True, balance_micro_usd=0)

    profile = _cached_profile(user_id)
    if not isinstance(profile, dict):
        # Fail open on cache lookup problems so we never break Research on
        # transient Supabase issues. Settlement still enforces the floor.
        return ResearchBudgetDecision(allowed=True, balance_micro_usd=0)

    account_locked = bool(profile.get("account_locked"))
    try:
        balance_micro_usd = int(profile.get("balance_micro_usd") or 0)
    except Exception:
        balance_micro_usd = 0

    if account_locked:
        return ResearchBudgetDecision(
            allowed=False,
            balance_micro_usd=balance_micro_usd,
            error_code="research_top_up_required",
            message="Top up your account to continue using hosted Research.",
            cta=RESEARCH_TOP_UP_CTA,
            cta_url=RESEARCH_TOP_UP_URL,
        )

    return ResearchBudgetDecision(allowed=True, balance_micro_usd=balance_micro_usd)


def research_budget_rejection_payload(decision: ResearchBudgetDecision) -> dict:
    return {
        "type": "error",
        "error_code": decision.error_code or "research_top_up_required",
        "message": decision.message or "Top up your account to continue using hosted Research.",
        "cta": decision.cta or RESEARCH_TOP_UP_CTA,
        "cta_url": decision.cta_url or RESEARCH_TOP_UP_URL,
        "balance_micro_usd": decision.balance_micro_usd,
        "balance_usd": decision.balance_micro_usd / MICRO_USD_PER_DOLLAR,
        "floor_micro_usd": decision.floor_micro_usd,
    }


def settle_research_charge(
    *,
    request_id: str,
    caller_ctx: dict,
    request_fingerprint: Optional[str] = None,
    selected_model: Optional[str] = None,
) -> Optional[dict]:
    caller_kind = str((caller_ctx or {}).get("caller_kind") or "").strip().lower()
    user_id = str((caller_ctx or {}).get("auth_user_id") or "").strip()
    if caller_kind not in {"authenticated", "qa_suite"} or not user_id or not request_id:
        return None

    client = get_supabase_client()
    if client is None:
        return None

    cost_usd = client.get_llm_usage_cost_usd(
        request_id=request_id,
        auth_user_id=user_id,
        surface="research",
    )
    if cost_usd <= 0:
        return {
            "success": True,
            "balance_micro_usd": get_user_balance_micro_usd(user_id),
            "deducted_micro_usd": 0,
            "charged_cost_usd": 0.0,
            "idempotent_replay": False,
        }

    try:
        charged_micro_usd = _to_micro_usd(cost_usd)
    except (InvalidOperation, ValueError) as exc:
        logger.warning("Failed to convert research cost for request %s: %s", request_id, exc)
        return None

    result = client.deduct_micro_credits_with_floor(
        user_id=user_id,
        amount_micro_usd=charged_micro_usd,
        operation_type="research_chat",
        min_balance_micro_usd=RESEARCH_NEGATIVE_FLOOR_MICRO_USD,
        request_id=request_id,
        request_fingerprint=request_fingerprint,
        idempotency_key=f"research_chat:{request_id}",
        notes="Hosted Research chat settlement",
        metadata={
            "surface": "research",
            "selected_model": selected_model,
            "charged_cost_usd": float(cost_usd),
        },
    )
    if not isinstance(result, dict):
        return None
    if not result.get("success"):
        logger.warning("Research charge settlement failed request=%s result=%s", request_id, result)
        return result

    result["charged_cost_usd"] = float(cost_usd)
    result["charged_micro_usd"] = charged_micro_usd
    return result
