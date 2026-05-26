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


def build_explainer_response(
    source_metadata: Optional[dict],
    question: Any,
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
    if not isinstance(source_metadata, dict):
        return None
    if not looks_like_explainer_question(question):
        return None

    description = source_metadata.get("description")
    llm_summary = source_metadata.get("llm_summary")
    if not (isinstance(description, str) and description.strip()) and not (
        isinstance(llm_summary, str) and llm_summary.strip()
    ):
        return None

    sections: dict[str, Any] = {}
    if isinstance(description, str) and description.strip():
        sections["description"] = description.strip()
    if isinstance(llm_summary, str) and llm_summary.strip():
        sections["summary"] = llm_summary.strip()

    facility_types_block = _format_structured_dict(
        "Facility types", source_metadata.get("facility_types")
    )
    if facility_types_block:
        sections["facility_types"] = facility_types_block

    upstream_summary = _summarize_upstream_sources(source_metadata)
    if upstream_summary:
        sections["upstream_sources"] = upstream_summary

    last_updated = source_metadata.get("last_updated")
    if isinstance(last_updated, str) and last_updated.strip():
        sections["last_updated"] = last_updated.strip()

    text_parts = []
    if "summary" in sections:
        text_parts.append(sections["summary"])
    elif "description" in sections:
        text_parts.append(sections["description"])
    if "facility_types" in sections:
        text_parts.append(sections["facility_types"])
    if "upstream_sources" in sections:
        text_parts.append(f"Upstream sources: {sections['upstream_sources']}.")
    if "last_updated" in sections:
        text_parts.append(f"Last updated: {sections['last_updated']}.")
    text = "\n\n".join(part for part in text_parts if part)

    return {
        "intent": "explainer",
        "source_id": source_metadata.get("source_id"),
        "pack_id": source_metadata.get("pack_id"),
        "text": text,
        "sections": sections,
        "stub_order": _build_stub_order(source_metadata),
    }
