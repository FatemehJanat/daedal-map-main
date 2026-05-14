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


def check_research_budget(caller_ctx: dict, model: str | None = None) -> ResearchBudgetDecision:
    caller_kind = str((caller_ctx or {}).get("caller_kind") or "").strip().lower()
    user_id = str((caller_ctx or {}).get("auth_user_id") or "").strip()
    normalized_model = str(model or "").strip().lower()

    if caller_kind not in {"authenticated", "qa_suite"} or not user_id:
        return ResearchBudgetDecision(allowed=True, balance_micro_usd=0)

    balance_micro_usd = get_user_balance_micro_usd(user_id)
    if balance_micro_usd is None:
        # Fail open on billing lookup problems so we do not break Research.
        return ResearchBudgetDecision(allowed=True, balance_micro_usd=0)

    if balance_micro_usd <= RESEARCH_NEGATIVE_FLOOR_MICRO_USD:
        return ResearchBudgetDecision(
            allowed=False,
            balance_micro_usd=balance_micro_usd,
            error_code="research_top_up_required",
            message="Top up your account to continue using hosted Research.",
            cta=RESEARCH_TOP_UP_CTA,
            cta_url=RESEARCH_TOP_UP_URL,
        )

    if normalized_model == "claude-opus-4-7" and balance_micro_usd < 0:
        return ResearchBudgetDecision(
            allowed=False,
            balance_micro_usd=balance_micro_usd,
            error_code="research_opus_requires_positive_balance",
            message="Opus requires a non-negative account balance. Top up to continue.",
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
