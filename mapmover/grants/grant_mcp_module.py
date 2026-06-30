"""
Private grant MCP module.

This is the first real module layer for the phase-aware grant MCP. It is
deliberately separate from any public MCP publishing flow:

- no registry metadata
- no server-card generation
- no public discovery/publishing assumptions

It is meant to sit behind a private HTTP MCP endpoint later, where the URL can
be shared manually with trusted users or pilot customers.

The module keeps three core promises from the contract docs:

- phase-aware routing across the pre-submission grant phases
- structured working state rather than chat-history-only state
- explicit clarification and capability-gating instead of silent guessing
"""

from __future__ import annotations

import re
import uuid
from copy import deepcopy
from typing import Any

from . import can_backend
from . import grant_analyzer as ga
from . import us_backend


PHASE_1 = "phase_1_prospect_research"
PHASE_2 = "phase_2_proposal_development"
PHASE_3 = "phase_3_submission_support"
OUT_OF_SCOPE = "out_of_scope_post_award"
AMBIGUOUS = "ambiguous"

FIELD_CONFIRMED = "confirmed"
FIELD_INFERRED = "inferred"
FIELD_MISSING = "missing"
FIELD_CONFLICTING = "conflicting"

OUTCOME_OK = "ok"
OUTCOME_CLARIFICATION = "clarification_needed"
OUTCOME_OUT_OF_SCOPE = "out_of_scope"
OUTCOME_UNSUPPORTED_COUNTRY = "unsupported_country_capability"
OUTCOME_UNSUPPORTED_CLAIM = "unsupported_claim_type"
OUTCOME_ERROR = "error"

PROJECT_PROFILE_FIELDS = (
    "project_description",
    "org_name",
    "org_type",
    "sector_tags",
    "recipient_loc_id",
    "place_of_performance_loc_id",
    "target_country_code",
    "has_government_partner",
    "has_match_funding",
    "target_award_amount",
    "target_project_length_days",
)

_SESSIONS: dict[str, dict[str, Any]] = {}


def reset_sessions() -> None:
    _SESSIONS.clear()


def get_session(session_id: str) -> dict[str, Any] | None:
    session = _SESSIONS.get(str(session_id or "").strip())
    return deepcopy(session) if session else None


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    arguments = dict(arguments or {})
    if name == "grant_intake_or_update_project":
        return grant_intake_or_update_project(**arguments)
    if name == "grant_analyze_current_phase":
        return grant_analyze_current_phase(**arguments)
    if name == "grant_set_phase":
        return grant_set_phase(**arguments)
    if name == "grant_select_target_program":
        return grant_select_target_program(**arguments)
    return {
        "tool_name": name,
        "outcome": OUTCOME_ERROR,
        "error": {"code": "unknown_tool", "message": f"Unknown grant MCP tool '{name}'."},
    }


def grant_intake_or_update_project(
    project_input: str,
    session_id: str | None = None,
    project_label: str | None = None,
    country_code: str | None = None,
    phase_hint: str | None = None,
    profile_overrides: dict[str, Any] | None = None,
    allow_inference: bool = True,
) -> dict[str, Any]:
    if not str(project_input or "").strip():
        return _error_result(
            "grant_intake_or_update_project",
            "invalid_project_input",
            "project_input is required.",
        )

    session = _load_or_create_session(session_id=session_id, project_label=project_label)
    text = str(project_input).strip()
    overrides = dict(profile_overrides or {})

    _set_profile_field(session, "project_description", text, FIELD_CONFIRMED, "project_input")

    for field_name, value in overrides.items():
        if field_name not in PROJECT_PROFILE_FIELDS:
            continue
        _set_profile_field(session, field_name, value, FIELD_CONFIRMED, "profile_override")

    if country_code:
        session["country_code"] = _normalize_country_code(country_code)
    elif not session.get("country_code"):
        session["country_code"] = _infer_backend_country(session, allow_inference=allow_inference)

    if allow_inference:
        _apply_inferred_profile_fields(session, text)

    inferred_phase, phase_confidence = _infer_phase(text, phase_hint=phase_hint, existing_phase=session.get("current_phase"))
    session["current_phase"] = phase_hint or inferred_phase
    session["phase_confidence"] = phase_confidence

    if session["current_phase"] == OUT_OF_SCOPE:
        _SESSIONS[session["session_id"]] = session
        return {
            "tool_name": "grant_intake_or_update_project",
            "outcome": OUTCOME_OUT_OF_SCOPE,
            "session_id": session["session_id"],
            "current_phase": session["current_phase"],
            "notes": ["This grant MCP currently supports only pre-submission phases 1-3."],
        }

    if not _backend_exists(session.get("country_code")):
        _SESSIONS[session["session_id"]] = session
        return {
            "tool_name": "grant_intake_or_update_project",
            "outcome": OUTCOME_UNSUPPORTED_COUNTRY,
            "session_id": session["session_id"],
            "country_code": session.get("country_code"),
            "notes": [f"No grant backend exists for country '{session.get('country_code')}'."],
        }

    missing_fields = _compute_missing_fields(session["current_phase"], session)
    session["project_profile_missing_fields"] = missing_fields
    session["open_questions"] = _build_questions_for_missing_fields(session["current_phase"], missing_fields, session)

    _SESSIONS[session["session_id"]] = session

    if session["open_questions"]:
        return {
            "tool_name": "grant_intake_or_update_project",
            "outcome": OUTCOME_CLARIFICATION,
            "session_id": session["session_id"],
            "current_phase": session["current_phase"],
            "phase_confidence": session["phase_confidence"],
            "country_code": session.get("country_code"),
            "project_profile": deepcopy(session["project_profile"]),
            "project_profile_missing_fields": list(missing_fields),
            "questions": deepcopy(session["open_questions"]),
            "resume_hint": "grant_intake_or_update_project",
        }

    return {
        "tool_name": "grant_intake_or_update_project",
        "outcome": OUTCOME_OK,
        "session_id": session["session_id"],
        "project_label": session.get("project_label"),
        "current_phase": session["current_phase"],
        "phase_confidence": session["phase_confidence"],
        "country_code": session.get("country_code"),
        "project_profile": deepcopy(session["project_profile"]),
        "project_profile_missing_fields": [],
        "conflicting_fields": [],
        "open_questions": [],
        "next_recommended_tool": "grant_analyze_current_phase",
        "notes": [],
    }


def grant_analyze_current_phase(
    session_id: str,
    analysis_request: str | None = None,
    phase_override: str | None = None,
    depth: str = "standard",
    refresh_profile_from_text: bool = True,
) -> dict[str, Any]:
    session = _SESSIONS.get(str(session_id or "").strip())
    if not session:
        return _error_result(
            "grant_analyze_current_phase",
            "unknown_session",
            "session_id was not found.",
        )

    request_text = str(analysis_request or "").strip()
    prior_phase = session.get("current_phase") or AMBIGUOUS

    if refresh_profile_from_text and request_text:
        _merge_request_text_into_profile(session, request_text)

    inferred_phase, phase_confidence = _infer_phase(
        request_text,
        phase_hint=phase_override,
        existing_phase=prior_phase,
    )
    active_phase = phase_override or (inferred_phase if inferred_phase != AMBIGUOUS else prior_phase)
    if active_phase == OUT_OF_SCOPE:
        session["current_phase"] = active_phase
        session["phase_confidence"] = phase_confidence
        _SESSIONS[session["session_id"]] = session
        return {
            "tool_name": "grant_analyze_current_phase",
            "outcome": OUTCOME_OUT_OF_SCOPE,
            "session_id": session["session_id"],
            "phase_run": active_phase,
            "notes": ["Post-award phases are intentionally out of scope for this grant MCP."],
        }

    missing_fields = _compute_missing_fields(active_phase, session)
    questions = _build_questions_for_missing_fields(active_phase, missing_fields, session)
    if questions:
        session["current_phase"] = active_phase
        session["phase_confidence"] = phase_confidence
        session["project_profile_missing_fields"] = missing_fields
        session["open_questions"] = questions
        _SESSIONS[session["session_id"]] = session
        return {
            "tool_name": "grant_analyze_current_phase",
            "outcome": OUTCOME_CLARIFICATION,
            "session_id": session["session_id"],
            "phase_run": active_phase,
            "questions": deepcopy(questions),
            "resume_hint": "grant_analyze_current_phase",
        }

    country_code = session.get("country_code") or "US"
    if not _backend_exists(country_code):
        return {
            "tool_name": "grant_analyze_current_phase",
            "outcome": OUTCOME_UNSUPPORTED_COUNTRY,
            "session_id": session["session_id"],
            "phase_run": active_phase,
            "country_code": country_code,
            "notes": [f"No grant backend exists for country '{country_code}'."],
        }

    phase_changed = active_phase != prior_phase
    session["current_phase"] = active_phase
    session["phase_confidence"] = phase_confidence

    if active_phase == PHASE_1:
        result = _run_phase_1(session, depth=depth)
    elif active_phase == PHASE_2:
        result = _run_phase_2(session, request_text=request_text, depth=depth)
    elif active_phase == PHASE_3:
        result = _run_phase_3(session, request_text=request_text)
    else:
        result = {
            "tool_name": "grant_analyze_current_phase",
            "outcome": OUTCOME_ERROR,
            "session_id": session["session_id"],
            "phase_run": active_phase,
            "error": {"code": "ambiguous_phase", "message": "Could not determine an actionable phase."},
        }

    if result.get("outcome") == OUTCOME_OK:
        result["phase_changed"] = phase_changed
        if phase_changed:
            result["prior_phase"] = prior_phase
            result["new_phase"] = active_phase

    _SESSIONS[session["session_id"]] = session
    return result


def grant_set_phase(session_id: str, phase_id: str) -> dict[str, Any]:
    session = _SESSIONS.get(str(session_id or "").strip())
    if not session:
        return _error_result("grant_set_phase", "unknown_session", "session_id was not found.")
    prior_phase = session.get("current_phase")
    session["current_phase"] = phase_id
    session["phase_confidence"] = 1.0
    _SESSIONS[session["session_id"]] = session
    return {
        "tool_name": "grant_set_phase",
        "outcome": OUTCOME_OK,
        "session_id": session["session_id"],
        "prior_phase": prior_phase,
        "new_phase": phase_id,
    }


def grant_select_target_program(session_id: str, program_id: str) -> dict[str, Any]:
    session = _SESSIONS.get(str(session_id or "").strip())
    if not session:
        return _error_result("grant_select_target_program", "unknown_session", "session_id was not found.")
    program_id = str(program_id or "").strip()
    targets = session.get("current_target_programs") or []
    match = next((item for item in targets if str(item.get("program_id") or "") == program_id), None)
    if not match:
        return _error_result(
            "grant_select_target_program",
            "program_not_in_session",
            f"Program '{program_id}' is not in the current target set.",
        )
    session["current_selected_program_id"] = program_id
    _SESSIONS[session["session_id"]] = session
    return {
        "tool_name": "grant_select_target_program",
        "outcome": OUTCOME_OK,
        "session_id": session["session_id"],
        "current_selected_program_id": program_id,
    }


def _run_phase_1(session: dict[str, Any], *, depth: str) -> dict[str, Any]:
    country_code = session["country_code"]
    profile = session["project_profile"]
    selected_steps: list[str] = []
    top_matches: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    key_blockers: list[str] = []
    precedent_summary: list[dict[str, Any]] = []
    open_now_summary: list[dict[str, Any]] = []

    if country_code == "US":
        scored = us_backend.score_and_rank_programs(
            org_type=_field_value(profile, "org_type"),
            sector_tags=_field_value(profile, "sector_tags") or None,
            recipient_loc_id=_field_value(profile, "recipient_loc_id"),
            place_of_performance_loc_id=_field_value(profile, "place_of_performance_loc_id"),
            has_government_partner=bool(_field_value(profile, "has_government_partner")),
            has_match_funding=bool(_field_value(profile, "has_match_funding")),
            target_award_amount=_field_value(profile, "target_award_amount"),
            target_project_length_days=_field_value(profile, "target_project_length_days"),
            org_name=_field_value(profile, "org_name"),
            target_country_code=_field_value(profile, "target_country_code"),
            top_n=5,
            live_opportunity_fallback=False,
        )
        selected_steps.extend(["match_grant_programs", "score_and_rank_programs"])
        top_matches = list(scored.get("top_matches") or [])
        session["current_scored_results"] = scored
        session["current_target_programs"] = deepcopy(top_matches)
        blocked = [item for item in top_matches if item.get("blockers")]
        key_blockers = _unique_strings(
            blocker
            for item in top_matches
            for blocker in (item.get("blockers") or [])
        )
        precedent_summary = [
            {
                "program_id": item.get("program_id"),
                "program_name": item.get("program_name"),
                "precedent_confidence": item.get("precedent_confidence"),
            }
            for item in top_matches
        ]
        open_now_summary = [
            {
                "program_id": item.get("program_id"),
                "is_currently_open": ((item.get("open_opportunity") or {}).get("is_currently_open")),
                "funding_mechanism": _first_opportunity_mechanism(item.get("open_opportunity") or {}),
            }
            for item in top_matches
            if item.get("open_opportunity") is not None
        ]
    elif country_code == "CAN":
        matches = can_backend.match_can_grant_programs(
            org_type=_field_value(profile, "org_type"),
            sector_tags=_field_value(profile, "sector_tags") or None,
            province=_province_from_loc_id(_field_value(profile, "recipient_loc_id")),
            has_government_partner=bool(_field_value(profile, "has_government_partner")),
            has_match_funding=bool(_field_value(profile, "has_match_funding")),
        )
        selected_steps.append("match_can_grant_programs")
        top_matches = list(matches[:5])
        session["current_target_programs"] = deepcopy(top_matches)
        blocked = [item for item in top_matches if item.get("blockers")]
        key_blockers = _unique_strings(
            blocker
            for item in top_matches
            for blocker in (item.get("blockers") or [])
        )
        if depth == "full":
            selected_steps.append("get_can_precedent")
            for item in top_matches[:3]:
                precedent = can_backend.get_can_precedent(str(item.get("program_id") or ""))
                precedent_summary.append(
                    {
                        "program_id": item.get("program_id"),
                        "program_name": item.get("program_name"),
                        "found": precedent.get("found"),
                        "award_count": precedent.get("award_count"),
                    }
                )
    else:
        return {
            "tool_name": "grant_analyze_current_phase",
            "outcome": OUTCOME_UNSUPPORTED_COUNTRY,
            "session_id": session["session_id"],
            "phase_run": PHASE_1,
            "country_code": country_code,
        }

    return {
        "tool_name": "grant_analyze_current_phase",
        "outcome": OUTCOME_OK,
        "session_id": session["session_id"],
        "phase_run": PHASE_1,
        "selected_workflow_steps": selected_steps,
        "top_matches": top_matches,
        "blocked_but_workable_matches": blocked,
        "key_blockers": key_blockers,
        "precedent_summary": precedent_summary,
        "open_now_summary": open_now_summary,
        "recommended_next_step": {
            "type": "move_to_phase_2_or_select_target",
            "message": "Select one target program before memo and budget work.",
        },
        "limitations": [],
    }


def _run_phase_2(session: dict[str, Any], *, request_text: str, depth: str) -> dict[str, Any]:
    country_code = session["country_code"]
    if country_code != "US":
        return {
            "tool_name": "grant_analyze_current_phase",
            "outcome": OUTCOME_UNSUPPORTED_COUNTRY,
            "session_id": session["session_id"],
            "phase_run": PHASE_2,
            "country_code": country_code,
            "notes": [f"Phase 2 tools are not yet supported for country '{country_code}'."],
        }

    selected_program_id = session.get("current_selected_program_id")
    if not selected_program_id:
        return {
            "tool_name": "grant_analyze_current_phase",
            "outcome": OUTCOME_CLARIFICATION,
            "session_id": session["session_id"],
            "phase_run": PHASE_2,
            "questions": [
                {
                    "question_id": "select_target_program",
                    "prompt": "Which program from the current shortlist are you actively developing the proposal for?",
                    "fields_unblocked": ["current_selected_program_id"],
                }
            ],
            "resume_hint": "grant_analyze_current_phase",
        }

    request_lower = request_text.lower()
    selected_steps: list[str] = []
    memo_support = None
    budget_framework = None
    draft_structure_review = None
    precedent_text_support = None
    profile = session["project_profile"]

    if (
        session.get("current_scored_results") is None
        and _field_value(profile, "org_type")
    ):
        phase1_result = _run_phase_1(session, depth="standard")
        if phase1_result.get("outcome") != OUTCOME_OK:
            return phase1_result

    wants_budget = any(token in request_lower for token in ("budget", "sf-424", "sf424", "cost"))
    wants_draft = "draft" in request_lower or "broader impacts" in request_lower
    wants_precedent_text = "precedent text" in request_lower or "similar abstract" in request_lower

    if wants_budget:
        target_award_amount = _field_value(profile, "target_award_amount")
        if target_award_amount in (None, ""):
            return {
                "tool_name": "grant_analyze_current_phase",
                "outcome": OUTCOME_CLARIFICATION,
                "session_id": session["session_id"],
                "phase_run": PHASE_2,
                "questions": [
                    {
                        "question_id": "target_award_amount",
                        "prompt": "What target award amount are you planning around for the budget framework?",
                        "fields_unblocked": ["target_award_amount"],
                    }
                ],
                "resume_hint": "grant_analyze_current_phase",
            }
        selected_steps.append("build_budget_framework")
        budget_framework = us_backend.build_budget_framework(
            target_award_amount=target_award_amount,
            program_id=selected_program_id,
            target_project_length_days=_field_value(profile, "target_project_length_days"),
            has_negotiated_indirect_rate=False,
        )

    if wants_draft:
        selected_steps.append("score_proposal_structure")
        draft_text = request_text
        draft_structure_review = us_backend.score_proposal_structure(draft_text=draft_text, program_id=selected_program_id)

    if wants_precedent_text:
        selected_steps.append("find_similar_precedent_text")
        precedent_text_support = us_backend.find_similar_precedent_text(
            draft_text=request_text or (_field_value(profile, "project_description") or ""),
            source="nsf",
            keyword=None,
            top_n=3,
        )

    if not selected_steps or (not wants_budget and not wants_draft and not wants_precedent_text):
        selected_steps.append("build_memo_talking_points")
        memo_support = us_backend.build_memo_talking_points(session.get("current_scored_results") or {}, top_n=5)

    return {
        "tool_name": "grant_analyze_current_phase",
        "outcome": OUTCOME_OK,
        "session_id": session["session_id"],
        "phase_run": PHASE_2,
        "selected_program_id": selected_program_id,
        "selected_workflow_steps": selected_steps,
        "memo_support": memo_support,
        "budget_framework": budget_framework,
        "draft_structure_review": draft_structure_review,
        "precedent_text_support": precedent_text_support,
        "recommended_next_step": {
            "type": "confirm_submission_target",
            "message": "If this is the chosen target, the next step is submission-support confirmation.",
        },
        "limitations": [],
    }


def _run_phase_3(session: dict[str, Any], *, request_text: str) -> dict[str, Any]:
    country_code = session["country_code"]
    if country_code != "US":
        return {
            "tool_name": "grant_analyze_current_phase",
            "outcome": OUTCOME_UNSUPPORTED_COUNTRY,
            "session_id": session["session_id"],
            "phase_run": PHASE_3,
            "country_code": country_code,
            "notes": [f"Phase 3 tools are not yet supported for country '{country_code}'."],
        }

    selected_program_id = session.get("current_selected_program_id")
    if not selected_program_id:
        return {
            "tool_name": "grant_analyze_current_phase",
            "outcome": OUTCOME_CLARIFICATION,
            "session_id": session["session_id"],
            "phase_run": PHASE_3,
            "questions": [
                {
                    "question_id": "select_target_program",
                    "prompt": "Which program are you asking submission-support questions about?",
                    "fields_unblocked": ["current_selected_program_id"],
                }
            ],
            "resume_hint": "grant_analyze_current_phase",
        }

    cfda_code = _program_cfda_code_us(selected_program_id)
    if not cfda_code:
        return _error_result(
            "grant_analyze_current_phase",
            "missing_cfda_code",
            f"Could not resolve a CFDA code for program '{selected_program_id}'.",
            session_id=session["session_id"],
            phase_run=PHASE_3,
        )

    selected_steps = ["check_open_opportunity"]
    opportunity_status = us_backend.check_open_opportunity(cfda_code, live_fallback=False)
    funding_mechanism_summary = {
        "funding_mechanism": _first_opportunity_mechanism(opportunity_status),
        "is_currently_open": opportunity_status.get("is_currently_open"),
        "checked_live": opportunity_status.get("checked_live"),
    }

    return {
        "tool_name": "grant_analyze_current_phase",
        "outcome": OUTCOME_OK,
        "session_id": session["session_id"],
        "phase_run": PHASE_3,
        "selected_program_id": selected_program_id,
        "selected_workflow_steps": selected_steps,
        "opportunity_status": opportunity_status,
        "funding_mechanism_summary": funding_mechanism_summary,
        "submission_support_notes": [
            "Confirm the exact funding notice, deadline posture, and final submission requirements outside the tool."
        ],
        "review_process_limitations": [
            "The tool cannot observe internal agency panel or merit review outcomes."
        ],
        "recommended_next_step": {
            "type": "submission_confirmation",
            "message": "Confirm the exact funding notice, deadline posture, and final application requirements outside the tool.",
        },
    }


def _load_or_create_session(*, session_id: str | None, project_label: str | None) -> dict[str, Any]:
    normalized_session_id = str(session_id or "").strip()
    if normalized_session_id and normalized_session_id in _SESSIONS:
        session = deepcopy(_SESSIONS[normalized_session_id])
    else:
        normalized_session_id = normalized_session_id or f"gs_{uuid.uuid4().hex[:12]}"
        session = {
            "session_id": normalized_session_id,
            "project_label": project_label or "Untitled Grant Project",
            "current_phase": PHASE_1,
            "phase_confidence": 0.5,
            "country_code": None,
            "project_profile": _empty_profile(),
            "project_profile_missing_fields": [],
            "current_target_programs": [],
            "current_selected_program_id": None,
            "current_scored_results": None,
            "current_memo_context": None,
            "current_budget_context": None,
            "current_draft_context": None,
            "open_questions": [],
            "last_tool_outputs": [],
        }
    if project_label:
        session["project_label"] = project_label
    return session


def _empty_profile() -> dict[str, dict[str, Any]]:
    return {
        field_name: {"value": None, "status": FIELD_MISSING, "source": None}
        for field_name in PROJECT_PROFILE_FIELDS
    }


def _set_profile_field(session: dict[str, Any], field_name: str, value: Any, status: str, source: str) -> None:
    if field_name not in session["project_profile"]:
        return
    if value is None:
        return
    if isinstance(value, str) and not value.strip():
        return
    session["project_profile"][field_name] = {
        "value": value,
        "status": status,
        "source": source,
    }


def _field_value(profile: dict[str, dict[str, Any]], field_name: str) -> Any:
    return (profile.get(field_name) or {}).get("value")


def _infer_backend_country(session: dict[str, Any], *, allow_inference: bool) -> str:
    recipient_loc_id = _field_value(session["project_profile"], "recipient_loc_id")
    if isinstance(recipient_loc_id, str) and recipient_loc_id.upper().startswith("USA"):
        return "US"
    if isinstance(recipient_loc_id, str) and recipient_loc_id.upper().startswith("CAN"):
        return "CAN"
    if not allow_inference:
        return "US"
    description = str(_field_value(session["project_profile"], "project_description") or "").lower()
    if any(token in description for token in (" british columbia", " alberta", " ontario", " canada", " canadian ")):
        return "CAN"
    return "US"


def _normalize_country_code(country_code: str) -> str:
    raw = str(country_code or "").strip().upper()
    if raw in {"USA", "US"}:
        return "US"
    if raw in {"CAN", "CA"}:
        return "CAN"
    return raw


def _backend_exists(country_code: str | None) -> bool:
    try:
        ga.get_backend(str(country_code or ""))
        return True
    except Exception:
        return False


def _apply_inferred_profile_fields(session: dict[str, Any], text: str) -> None:
    text_lower = text.lower()
    if _field_value(session["project_profile"], "org_type") in (None, ""):
        inferred_org_type = _infer_org_type(text_lower)
        if inferred_org_type:
            _set_profile_field(session, "org_type", inferred_org_type, FIELD_INFERRED, "text_inference")

    if _field_value(session["project_profile"], "sector_tags") in (None, ""):
        sector_tags = _infer_sector_tags(text_lower)
        if sector_tags:
            _set_profile_field(session, "sector_tags", sector_tags, FIELD_INFERRED, "text_inference")

    if _field_value(session["project_profile"], "has_government_partner") in (None, ""):
        if "government partner" in text_lower or "state partner" in text_lower or "city partner" in text_lower:
            _set_profile_field(session, "has_government_partner", True, FIELD_INFERRED, "text_inference")

    if _field_value(session["project_profile"], "has_match_funding") in (None, ""):
        if "match funding" in text_lower and any(token in text_lower for token in ("have", "secured", "confirmed")):
            _set_profile_field(session, "has_match_funding", True, FIELD_INFERRED, "text_inference")


def _infer_org_type(text_lower: str) -> str | None:
    mapping = (
        ("501c3", "nonprofit_501c3"),
        ("nonprofit", "nonprofit_501c3"),
        ("university", "higher_ed"),
        ("college", "higher_ed"),
        ("tribe", "tribal_government"),
        ("city ", "local_government"),
        ("county ", "local_government"),
        ("state agency", "state_government"),
        ("small business", "small_business"),
    )
    for token, org_type in mapping:
        if token in text_lower:
            return org_type
    return None


def _infer_sector_tags(text_lower: str) -> list[str]:
    mapping = {
        "disaster_recovery": ("disaster recovery", "recovery", "reconstruction"),
        "hazard_mitigation": ("hazard mitigation", "mitigation"),
        "community_resilience": ("resilience",),
        "green_infrastructure": ("green infrastructure",),
        "wildfire": ("wildfire", "fuel reduction"),
        "forestry": ("forestry", "forest", "wood products", "biochar"),
        "international_development": ("international development", "usaid", "foreign assistance"),
        "humanitarian": ("humanitarian", "refugee"),
        "research": ("research",),
        "capacity_building": ("capacity building",),
    }
    tags = [tag for tag, tokens in mapping.items() if any(token in text_lower for token in tokens)]
    return sorted(set(tags))


def _infer_phase(text: str, *, phase_hint: str | None, existing_phase: str | None) -> tuple[str, float]:
    if phase_hint:
        return phase_hint, 1.0
    text_lower = str(text or "").lower()
    if any(token in text_lower for token in ("post-award", "compliance", "closeout", "reporting", "reimbursement", "audit")):
        return OUT_OF_SCOPE, 0.95
    if any(token in text_lower for token in ("memo", "budget", "draft", "proposal structure", "broader impacts")):
        return PHASE_2, 0.9
    if any(token in text_lower for token in ("deadline", "is it open", "nofo", "aps", "baa", "submit", "submission")):
        return PHASE_3, 0.9
    if text_lower.strip():
        return PHASE_1, 0.75
    return existing_phase or AMBIGUOUS, 0.5


def _compute_missing_fields(phase_id: str, session: dict[str, Any]) -> list[str]:
    profile = session["project_profile"]
    missing: list[str] = []

    if phase_id == PHASE_1:
        if not _field_value(profile, "org_type"):
            missing.append("org_type")
        if not _field_value(profile, "recipient_loc_id") and not _field_value(profile, "target_country_code"):
            missing.append("recipient_loc_id")
        if _field_value(profile, "recipient_loc_id") and not _field_value(profile, "place_of_performance_loc_id"):
            missing.append("place_of_performance_loc_id")
    elif phase_id == PHASE_2:
        if not session.get("current_selected_program_id"):
            missing.append("current_selected_program_id")
    elif phase_id == PHASE_3:
        if not session.get("current_selected_program_id"):
            missing.append("current_selected_program_id")
    return missing


def _build_questions_for_missing_fields(phase_id: str, missing_fields: list[str], session: dict[str, Any]) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    missing = set(missing_fields)
    if phase_id == PHASE_1 and {"recipient_loc_id", "place_of_performance_loc_id"} & missing:
        questions.append(
            {
                "question_id": "recipient_vs_performance",
                "prompt": "Is the applying organization in the same place the funded work will happen?",
                "fields_unblocked": ["recipient_loc_id", "place_of_performance_loc_id"],
            }
        )
    if "org_type" in missing:
        questions.append(
            {
                "question_id": "org_type",
                "prompt": "What kind of applicant is this organization, for example nonprofit, higher ed, tribal government, or local government?",
                "fields_unblocked": ["org_type"],
            }
        )
    if "current_selected_program_id" in missing:
        targets = session.get("current_target_programs") or []
        target_names = [str(item.get("program_name") or item.get("program_id") or "") for item in targets[:5]]
        questions.append(
            {
                "question_id": "select_target_program",
                "prompt": "Which program from the current shortlist are you actively working on now?"
                + (f" Current shortlist: {', '.join(target_names)}." if target_names else ""),
                "fields_unblocked": ["current_selected_program_id"],
            }
        )
    return questions


def _merge_request_text_into_profile(session: dict[str, Any], request_text: str) -> None:
    if not request_text:
        return
    current_description = str(_field_value(session["project_profile"], "project_description") or "").strip()
    merged = request_text if not current_description else f"{current_description}\n\nFollow-up: {request_text}"
    _set_profile_field(session, "project_description", merged, FIELD_CONFIRMED, "session_merge")


def _province_from_loc_id(loc_id: str | None) -> str | None:
    raw = str(loc_id or "").strip().upper()
    if raw.startswith("CAN-"):
        parts = raw.split("-")
        if len(parts) >= 2:
            return parts[1]
    return None


def _first_opportunity_mechanism(open_opportunity: dict[str, Any]) -> str | None:
    opportunities = open_opportunity.get("opportunities") or []
    if opportunities and isinstance(opportunities[0], dict):
        return opportunities[0].get("funding_mechanism")
    return None


def _program_cfda_code_us(program_id: str) -> str | None:
    df = us_backend.load_programs()
    match = df[df["program_id"] == program_id]
    if match.empty:
        return None
    cfda_value = str(match.iloc[0]["cfda_number"] or "").strip()
    if not cfda_value:
        return None
    return cfda_value.split("|")[0].strip()


def _unique_strings(values: Any) -> list[str]:
    seen: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def _error_result(tool_name: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "tool_name": tool_name,
        "outcome": OUTCOME_ERROR,
        "error": {"code": code, "message": message},
    }
    payload.update(extra)
    return payload
