"""Shared metadata/reference hint helpers used across runtime lanes."""

from __future__ import annotations


def get_routing_hints(metadata: dict | None) -> dict:
    if not isinstance(metadata, dict):
        return {}
    routing_hints = metadata.get("routing_hints")
    return routing_hints if isinstance(routing_hints, dict) else {}


def get_hint_alias_terms(metadata: dict | None, *fields: str) -> list[str]:
    routing_hints = get_routing_hints(metadata)
    aliases: list[str] = []
    for field_name in fields:
        field_values = routing_hints.get(field_name) or []
        if isinstance(field_values, dict):
            values = field_values.keys()
        elif isinstance(field_values, list):
            values = field_values
        else:
            continue
        for value in values:
            text = str(value or "").strip().lower()
            if text and text not in aliases:
                aliases.append(text)
    return aliases


def get_hint_query_priority(metadata: dict | None) -> float:
    routing_hints = get_routing_hints(metadata)
    try:
        value = float(routing_hints.get("query_priority") or 0.0)
    except (TypeError, ValueError):
        value = 0.0
    return max(0.0, min(0.25, value))


def get_single_metric_default(metadata: dict | None) -> str:
    routing_hints = get_routing_hints(metadata)
    return str(routing_hints.get("single_metric_default") or "").strip()


def get_unsupported_metric_aliases(metadata: dict | None) -> list[str]:
    routing_hints = get_routing_hints(metadata)
    aliases = routing_hints.get("unsupported_metric_aliases") or []
    if not isinstance(aliases, list):
        return []
    return [str(alias).strip() for alias in aliases if str(alias).strip()]


def get_supported_geography_summary(metadata: dict | None) -> str:
    routing_hints = get_routing_hints(metadata)
    geo_summary = str(routing_hints.get("supported_geography_summary") or "").strip()
    if geo_summary:
        return geo_summary
    if not isinstance(metadata, dict):
        return "see source metadata"
    geo_levels = metadata.get("geographic_level")
    if isinstance(geo_levels, list):
        cleaned = [str(level).replace("_", " ") for level in geo_levels if level]
        if cleaned:
            return ", ".join(cleaned)
    if geo_levels:
        return str(geo_levels).replace("_", " ")
    return "see source metadata"


def get_geo_level_aliases(metadata: dict | None) -> dict[str, str]:
    routing_hints = get_routing_hints(metadata)
    aliases = routing_hints.get("geo_level_aliases") or {}
    if not isinstance(aliases, dict):
        return {}
    normalized: dict[str, str] = {}
    for alias, target in aliases.items():
        alias_text = str(alias or "").strip().lower().replace("-", "_").replace(" ", "_")
        target_text = str(target or "").strip().lower().replace("-", "_").replace(" ", "_")
        if alias_text and target_text:
            normalized[alias_text] = target_text
    return normalized


def normalize_requested_geo_level_for_source(requested_geo_level: str | None, metadata: dict | None) -> str | None:
    if not requested_geo_level:
        return None

    requested = str(requested_geo_level).strip().lower().replace("-", "_").replace(" ", "_")
    if not requested:
        return None

    aliases = get_geo_level_aliases(metadata)
    if requested in aliases:
        return aliases[requested]

    if requested in aliases.values():
        return requested

    admin_to_friendly = {
        "admin_2": "county",
        "admin_3": "tract",
        "admin_4": "blockgroup",
        "admin_5": "block",
    }
    friendly = admin_to_friendly.get(requested)
    if friendly and friendly in aliases.values():
        return friendly

    reverse_aliases = {value: key for key, value in aliases.items()}
    if requested in reverse_aliases:
        return aliases.get(reverse_aliases[requested], requested)

    return requested


def get_metric_alias_matches(metadata: dict | None, query: str | None) -> list[tuple[str, str]]:
    routing_hints = get_routing_hints(metadata)
    metric_aliases = routing_hints.get("metric_aliases") or {}
    query_lower = str(query or "").strip().lower()
    if not isinstance(metric_aliases, dict) or not query_lower:
        return []

    matches: list[tuple[str, str]] = []
    for alias, metric_name in metric_aliases.items():
        alias_text = str(alias or "").strip().lower()
        metric_text = str(metric_name or "").strip()
        if alias_text and metric_text and alias_text in query_lower:
            matches.append((alias_text, metric_text))
    matches.sort(key=lambda item: len(item[0]), reverse=True)
    return matches


def build_scenario_routing_lines(scenario_defaults: dict | None) -> list[str]:
    if not isinstance(scenario_defaults, dict):
        return []
    lines: list[str] = []
    for concept_key, scenario_map in scenario_defaults.items():
        if not isinstance(scenario_map, dict) or not scenario_map:
            continue
        pretty_concept = {
            "projected_risk_score": "projected risk score",
            "hazard_multiplier": "hazard multiplier",
            "projected_annual_loss_rate_band": "projected annual loss rate band",
            "annual_loss_rate_change_band": "annual loss rate change band",
        }.get(concept_key, str(concept_key).replace("_", " "))
        scenario_examples = []
        for scenario_key, metric_name in scenario_map.items():
            metric_text = str(metric_name or "").strip()
            if not metric_text:
                continue
            pretty_scenario = str(scenario_key).replace("_", " ")
            scenario_examples.append(f'"{pretty_scenario}" -> metric="{metric_text}"')
        if scenario_examples:
            lines.append(
                f"For {pretty_concept} requests, map scenario language to explicit metrics as follows: "
                + "; ".join(scenario_examples[:6])
                + "."
            )
    return lines


def build_source_routing_guidance(metadata: dict | None, source_id: str) -> list[str]:
    routing_hints = get_routing_hints(metadata)
    if not source_id:
        source_id = str((metadata or {}).get("source_id") or "").strip()
    pack_id = str((metadata or {}).get("pack_id") or "").strip()
    lines = [
        f'When this detected source clearly matches the query, keep the order item anchored to source_id="{source_id}" instead of switching to a different same-pack source.'
    ]
    if pack_id:
        lines.append(
            f'If the query is clearly anchored to pack_id="{pack_id}", prefer this pack family and its sibling sources before switching to a different pack for a single overlapping metric.'
        )

    default_metric = get_single_metric_default(metadata)
    if routing_hints.get("prefer_order_for_analytics") and default_metric:
        lines.append(
            f'For broad analytical queries that clearly match this source, prefer type="order" with metric="{default_metric}" unless the user asks for a different metric.'
        )
        lines.append(
            "This includes count/share/ranking questions. Do not fall back to chat just because the source is static, tract-level, or analytical."
        )

    if routing_hints.get("clarify_on_missing_metric"):
        lines.append(
            'For broad topic/goal queries without a specific metric, respond with type="clarify" and ask the user which metric they want using human-readable metric names.'
        )

    filter_advice = str(routing_hints.get("filter_advice") or "").strip()
    if filter_advice:
        lines.append(f"Filter guidance: {filter_advice}")

    unsupported_aliases = get_unsupported_metric_aliases(metadata)
    if unsupported_aliases:
        examples = ", ".join(unsupported_aliases[:4])
        lines.append(
            f"If the user asks for an unsupported metric such as {examples}, clarify honestly using the supported metrics above and accurately mention the supported geography ({get_supported_geography_summary(metadata)})."
        )

    lines.extend(build_scenario_routing_lines(routing_hints.get("scenario_metric_defaults")))

    metric_aliases = routing_hints.get("metric_aliases") or {}
    if isinstance(metric_aliases, dict) and metric_aliases:
        alias_examples = []
        for alias, metric_name in metric_aliases.items():
            alias_text = str(alias or "").strip()
            metric_text = str(metric_name or "").strip()
            if alias_text and metric_text:
                alias_examples.append(f'"{alias_text}" -> metric="{metric_text}"')
        if alias_examples:
            lines.append(
                "When the query uses one of these metric phrases, map it directly to the matching metric: "
                + "; ".join(alias_examples[:8])
                + "."
            )

    if str((metadata or {}).get("geojson_shape", "")).strip().lower() == "location_shape":
        lines.append(
            'For point-location registry queries ("show/find/map/list/count locations in X"), prefer type="order" anchored to this source. Use loc_id for country filters and facility_type/source/website when the query names a facility class or asks for websites/public spaces. It is valid to omit metric entirely for location listings and filtered point maps.'
        )
        lines.append(
            'If this detected location source already clearly matches the user query, do not switch to type="chat" just to describe the source. Queries such as "show all fab labs in the United States", "show all public Prusa spaces on the map", or "map all fab labs globally" should return a real order with region and filters when needed.'
        )

    return lines


def build_query_matched_metric_guidance(metadata: dict | None, query: str | None) -> list[str]:
    query_text = str(query or "").strip()
    if not query_text:
        return []

    routing_hints = get_routing_hints(metadata)
    lines: list[str] = []

    metric_matches = get_metric_alias_matches(metadata, query_text)
    if metric_matches:
        alias_text, metric_name = metric_matches[0]
        lines.append(
            f'The user query already contains the metric phrase "{alias_text}". Return type="order" and set metric="{metric_name}" unless the user explicitly asks for a different metric.'
        )
        lines.append(
            "Do not switch to chat or ask a follow-up just to restate the matching metric when the request already includes a clear time range, geography, or comparison."
        )

    if routing_hints.get("prefer_order_for_analytics"):
        default_metric = get_single_metric_default(metadata)
        broad_aliases = get_hint_alias_terms(metadata, "broad_topic_aliases", "query_aliases")
        query_lower = query_text.lower()
        if default_metric and any(alias in query_lower for alias in broad_aliases):
            lines.append(
                f'This query matches the source topic closely enough to default to metric="{default_metric}". Prefer type="order" instead of chat when the user is asking to show, compare, trend, rank, or map the data.'
            )

    return lines


def build_pack_family_preference_guidance(
    detected_source: dict | None,
    source_candidates: dict | None,
) -> list[str]:
    detected = detected_source or {}
    detected_pack_id = str(detected.get("pack_id") or "").strip()
    detected_source_id = str(detected.get("source_id") or "").strip()
    if not detected_pack_id:
        return []

    candidates = (source_candidates or {}).get("candidates") or []
    same_pack_ids: list[str] = []
    outside_pack_ids: list[str] = []
    for candidate in candidates:
        source_id = str(candidate.get("source_id") or "").strip()
        candidate_pack_id = str(candidate.get("pack_id") or "").strip()
        if not source_id:
            continue
        if candidate_pack_id == detected_pack_id:
            if source_id not in same_pack_ids:
                same_pack_ids.append(source_id)
        elif candidate_pack_id and source_id not in outside_pack_ids:
            outside_pack_ids.append(source_id)

    lines = [
        f'The current query appears to belong to pack_id="{detected_pack_id}". Stay inside that pack family by default.'
    ]
    if same_pack_ids:
        sibling_ids = [source_id for source_id in same_pack_ids if source_id != detected_source_id]
        if sibling_ids:
            lines.append(
                "If the metric is ambiguous, clarify within this pack family first instead of jumping to another pack. "
                f"Same-pack candidates here include: {', '.join(sibling_ids[:5])}."
            )
    if outside_pack_ids:
        lines.append(
            "Do not jump to another pack just because a similar metric exists there. "
            f"Only switch packs if the user explicitly asks for it or this pack family cannot answer. Other candidate packs are represented by: {', '.join(outside_pack_ids[:5])}."
        )
    return lines


def build_reference_summary(reference_data: dict | None) -> str:
    if not isinstance(reference_data, dict) or not reference_data:
        return ""

    goal = reference_data.get("goal")
    if isinstance(goal, dict):
        name = str(goal.get("name") or "").strip()
        description = str(goal.get("description") or "").strip()
        parts = []
        if name:
            parts.append(f"Goal: {name}")
        if description:
            parts.append(f"Description: {description}")
        return "\n".join(parts)

    about = reference_data.get("about")
    dataset = reference_data.get("this_dataset")
    if isinstance(about, dict) or isinstance(dataset, dict):
        parts = []
        if isinstance(about, dict):
            name = str(about.get("name") or "").strip()
            publisher = str(about.get("publisher") or "").strip()
            history = str(about.get("history") or "").strip()
            if name:
                parts.append(f"About: {name}")
            if publisher:
                parts.append(f"Publisher: {publisher}")
            if history:
                parts.append(f"Background: {history[:220]}")
        if isinstance(dataset, dict):
            focus = str(dataset.get("focus") or "").strip()
            if focus:
                parts.append(f"Dataset focus: {focus}")
        return "\n".join(parts)

    return ""
