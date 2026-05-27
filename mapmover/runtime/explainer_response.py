"""Shared explainer-response helper.

Some recurring user questions are meta / explainer in shape rather than data
requests, for example:

  - "What is the distributed manufacturing source?"
  - "What is the CEJST classification and how does it work?"
  - "Why is this tract classified as disadvantaged?"

Pack metadata already carries enough structured material to answer most of
these (`description`, `llm_summary`, `facility_types`, etc.). This helper
turns that metadata into a chat-only response payload plus a stub order so
the user still has a "view the data" affordance.

Orchestrators should call `build_explainer_response` after the order-taker
declines to produce an executable order. If the question is not meta /
explainer shaped, the helper returns None and the order_first behavior is
preserved on real data requests.

See: county-map-private/docs/future/runtime_and_lane_unification_plan.md
section "Recently Identified Shared Helper Gaps" for the migration order and
call-site inventory.
"""

from __future__ import annotations

import re
from typing import Any, Optional


_EXPLAINER_PREFIXES = (
    "what is ",
    "what's ",
    "what are ",
    "how does ",
    "how do ",
    "why is ",
    "why are ",
    "tell me about ",
    "explain ",
    "describe ",
)

_EXPLAINER_PATTERNS = (
    re.compile(r"\bhow does\b.*\bwork\b", re.IGNORECASE),
    re.compile(r"\bwhat does\b.*\bmean\b", re.IGNORECASE),
    re.compile(r"\bwhat kinds? of\b", re.IGNORECASE),
    re.compile(r"\bwhat types? of\b", re.IGNORECASE),
)

_DATA_REQUEST_BLOCKERS = (
    " per capita",
    " exposure",
    " trend",
    " over the last ",
    " over last ",
    " in the last ",
    " over time",
    " compare ",
    " count",
    " total",
    " average",
    " highest",
    " lowest",
    " counties in ",
    " tracts in ",
    " regions in ",
    " areas in ",
    " in japan",
    " in california",
    " in florida",
)


def _normalize(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    return text.strip().lower()


def looks_like_explainer_question(question: Any) -> bool:
    """Return True when the question is shaped like an explainer/meta query.

    Conservative detection - real data requests with the same prefix still
    fall through to the data path. The caller decides when to consult this
    helper (typically after the order-taker returns no executable order).
    """
    norm = _normalize(question)
    if not norm:
        return False
    if any(token in norm for token in _DATA_REQUEST_BLOCKERS):
        return False
    if any(norm.startswith(prefix) for prefix in _EXPLAINER_PREFIXES):
        return True
    return any(pattern.search(norm) for pattern in _EXPLAINER_PATTERNS)


def _summarize_upstream_sources(source_metadata: dict) -> Optional[str]:
    raw = source_metadata.get("upstream_sources")
    if not isinstance(raw, list) or not raw:
        return None
    pieces = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("agency_short") or entry.get("agency")
        if name:
            pieces.append(str(name))
    if not pieces:
        return None
    return ", ".join(pieces)


def _format_structured_dict(name: str, payload: Any) -> Optional[str]:
    """Render a structured metadata dict (like `facility_types`) as a list block."""
    if not isinstance(payload, dict) or not payload:
        return None
    lines = [f"{name}:"]
    for key, value in payload.items():
        if isinstance(value, str) and value.strip():
            lines.append(f"- {key}: {value.strip()}")
        else:
            lines.append(f"- {key}")
    return "\n".join(lines)


def _build_stub_order(source_metadata: dict) -> Optional[dict]:
    """Return a minimal order pointing at the pack so the user can still view it."""
    source_id = source_metadata.get("source_id")
    if not isinstance(source_id, str) or not source_id:
        return None
    return {
        "type": "explainer_stub",
        "source_id": source_id,
        "pack_id": source_metadata.get("pack_id"),
        "intent": "view_pack",
    }


def _first_nonempty(*values: Any) -> Optional[str]:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_reference_sections(source_reference: dict) -> dict[str, Any]:
    sections: dict[str, Any] = {}
    if not isinstance(source_reference, dict):
        return sections

    source_info = source_reference.get("source")
    if isinstance(source_info, dict):
        description = _first_nonempty(
            source_info.get("description"),
            source_info.get("summary"),
        )
        if description:
            sections["reference_description"] = description

    context = source_reference.get("context")
    if isinstance(context, str) and context.strip():
        sections["reference_context"] = context.strip()
    elif isinstance(context, dict):
        context_parts = []
        for key in ("overview", "methodology", "usage_notes", "interpretation"):
            value = context.get(key)
            if isinstance(value, str) and value.strip():
                context_parts.append(value.strip())
        if context_parts:
            sections["reference_context"] = "\n\n".join(context_parts)

    about = source_reference.get("about")
    if isinstance(about, dict):
        about_parts = []
        for key in ("summary", "history", "methodology", "source_context"):
            value = about.get(key)
            if isinstance(value, str) and value.strip():
                about_parts.append(value.strip())
        if about_parts and "reference_context" not in sections:
            sections["reference_context"] = "\n\n".join(about_parts)

    goal = source_reference.get("goal")
    if isinstance(goal, dict):
        goal_title = _first_nonempty(goal.get("full_title"), goal.get("name"))
        goal_description = _first_nonempty(goal.get("description"))
        if goal_title:
            sections["reference_title"] = goal_title
        if goal_description:
            sections["reference_description"] = goal_description
        targets = goal.get("targets")
        if isinstance(targets, list) and targets:
            lines = []
            for entry in targets[:8]:
                if isinstance(entry, dict):
                    text = _first_nonempty(entry.get("description"), entry.get("title"), entry.get("name"))
                    code = _first_nonempty(entry.get("code"), entry.get("id"))
                    if text and code:
                        lines.append(f"- {code}: {text}")
                    elif text:
                        lines.append(f"- {text}")
                elif isinstance(entry, str) and entry.strip():
                    lines.append(f"- {entry.strip()}")
            if lines:
                sections["reference_targets"] = "Targets:\n" + "\n".join(lines)

    return sections


def build_explainer_response(
    source_metadata: Optional[dict],
    question: Any,
    source_reference: Optional[dict] = None,
) -> Optional[dict]:
    """Build an explainer response from pack metadata, or return None.

    Returns None when:
      - source_metadata is missing or unusable
      - the question does not look like an explainer/meta query
      - the metadata carries no `description` or `llm_summary`

    Returned dict shape:
      {
        "intent": "explainer",
        "source_id": ...,
        "pack_id": ...,
        "text": <assembled chat-only answer>,
        "sections": {description, summary, facility_types, upstream_sources, last_updated},
        "stub_order": <minimal order pointing at the pack> | None,
      }
    """
    if not isinstance(source_metadata, dict) and not isinstance(source_reference, dict):
        return None
    if not looks_like_explainer_question(question):
        return None

    reference_sections = _extract_reference_sections(source_reference or {})
    description = source_metadata.get("description") if isinstance(source_metadata, dict) else None
    llm_summary = source_metadata.get("llm_summary") if isinstance(source_metadata, dict) else None
    if not reference_sections and not (
        (isinstance(description, str) and description.strip())
        or (isinstance(llm_summary, str) and llm_summary.strip())
    ):
        return None

    sections: dict[str, Any] = {}
    for key in ("reference_title", "reference_description", "reference_context", "reference_targets"):
        if key in reference_sections:
            sections[key] = reference_sections[key]
    if isinstance(description, str) and description.strip():
        sections["description"] = description.strip()
    if isinstance(llm_summary, str) and llm_summary.strip():
        sections["summary"] = llm_summary.strip()

    if isinstance(source_metadata, dict):
        facility_types_block = _format_structured_dict(
            "Facility types", source_metadata.get("facility_types")
        )
        if facility_types_block:
            sections["facility_types"] = facility_types_block

    upstream_summary = _summarize_upstream_sources(source_metadata or {})
    if upstream_summary:
        sections["upstream_sources"] = upstream_summary

    last_updated = source_metadata.get("last_updated") if isinstance(source_metadata, dict) else None
    if isinstance(last_updated, str) and last_updated.strip():
        sections["last_updated"] = last_updated.strip()

    text_parts = []
    if "reference_title" in sections:
        text_parts.append(sections["reference_title"])
    if "reference_description" in sections:
        text_parts.append(sections["reference_description"])
    elif "summary" in sections:
        text_parts.append(sections["summary"])
    elif "description" in sections:
        text_parts.append(sections["description"])
    if "reference_context" in sections:
        text_parts.append(sections["reference_context"])
    elif "summary" in sections and sections["summary"] not in text_parts:
        text_parts.append(sections["summary"])
    if "facility_types" in sections:
        text_parts.append(sections["facility_types"])
    if "reference_targets" in sections:
        text_parts.append(sections["reference_targets"])
    if "upstream_sources" in sections:
        text_parts.append(f"Upstream sources: {sections['upstream_sources']}.")
    if "last_updated" in sections:
        text_parts.append(f"Last updated: {sections['last_updated']}.")
    text = "\n\n".join(part for part in text_parts if part)

    source_payload = source_metadata if isinstance(source_metadata, dict) else (source_reference or {})

    return {
        "intent": "explainer",
        "source_id": source_payload.get("source_id"),
        "pack_id": source_payload.get("pack_id"),
        "text": text,
        "sections": sections,
        "stub_order": _build_stub_order(source_payload),
    }
