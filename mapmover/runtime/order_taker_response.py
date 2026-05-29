"""Shared response parsing and validation helpers for the order taker."""

from __future__ import annotations

import json

from mapmover.aggregation_system import validate_aggregation_policy
from mapmover.data_loading import load_catalog, load_source_metadata
from mapmover.runtime.order_taker_prompt import get_source_visibility_mode
from mapmover.runtime.query_intent_primitives import query_prefers_event_source
from mapmover.runtime.source_hints import (
    get_hint_alias_terms,
    get_metric_alias_matches,
    get_routing_hints,
    get_single_metric_default,
    get_supported_geography_summary,
    get_unsupported_metric_aliases,
)


def validate_order_item(item: dict) -> dict:
    _normalize_item_year_fields(item)
    load_scope = str(item.get("load_scope") or "").strip().lower()
    if item.get("pack_id") and (load_scope in {"pack", "all_sources", "full_pack"} or item.get("all_sources") is True):
        item["_valid"] = True
        return item
    source_id = item.get("source_id")
    metric = item.get("metric")
    year = item.get("year")

    if not source_id:
        if item.get("pack_id"):
            source_id = _resolve_source_for_validation(item)
            if source_id:
                item["source_id"] = source_id
                item["_resolved_from_pack"] = True
            else:
                item["_valid"] = False
                item["_error"] = f"Unable to resolve pack_id '{item.get('pack_id')}' to a source"
                return item
        if not source_id:
            item["_valid"] = False
            item["_error"] = "Missing source_id"
            return item

    metadata = load_source_metadata(source_id)
    if not metadata:
        item["_valid"] = False
        item["_error"] = f"Unknown source: {source_id}"
        return item
    if get_source_visibility_mode() == "live" and not metadata.get("pack_id"):
        item["_valid"] = False
        item["_error"] = f"Source '{source_id}' is not published in live mode"
        return item

    metrics = metadata.get("metrics", {})
    if metric in ("*", "all", "all_metrics"):
        item["_valid"] = True
        return item
    if metric and metric not in metrics:
        resolved_metric, close_matches = _resolve_metric_for_validation(metric, metrics)
        if resolved_metric:
            item["metric"] = resolved_metric
            metric = resolved_metric
        else:
            if close_matches:
                item["_valid"] = False
                item["_error"] = f"Column '{metric}' not found. Did you mean: {', '.join(close_matches[:3])}?"
            else:
                item["_valid"] = False
                item["_error"] = f"Column '{metric}' not found in {source_id}"
            return item

    temp = metadata.get("temporal_coverage", {})
    start_year = _coerce_year(temp.get("start"))
    end_year = _coerce_year(temp.get("end"))
    if year and start_year and end_year:
        if year < start_year or year > end_year:
            item["_valid"] = False
            item["_error"] = f"Year {year} outside range {start_year}-{end_year}"
            return item

    year_start = item.get("year_start")
    year_end = item.get("year_end")
    if year_start and year_end and start_year and end_year:
        if year_start < start_year:
            item["_valid"] = False
            item["_error"] = f"Year start {year_start} before available data ({start_year})"
            return item
        if year_end > end_year:
            item["_valid"] = False
            item["_error"] = f"Year end {year_end} after available data ({end_year})"
            return item
        if year_start > year_end:
            item["_valid"] = False
            item["_error"] = f"Year start {year_start} is after year end {year_end}"
            return item

    temporal = metadata.get("temporal_coverage", {})
    frequency = str(temporal.get("frequency", "")).lower()
    requested_granularity = str(item.get("time_granularity") or "").strip().lower()
    if frequency in {"annual", "yearly"} and requested_granularity in {"daily", "weekly", "monthly", "annual"}:
        item["_normalized_time_granularity"] = {
            "from": item.get("time_granularity"),
            "to": "yearly",
            "reason": f"source_frequency={frequency}",
        }
        item["time_granularity"] = "yearly"

    metric_info = metrics.get(metric, {}) if metric else {}
    policy_ok, policy_error, policy_trace = validate_aggregation_policy(
        item,
        source_metadata=metadata,
        metric_name=metric,
        metric_info=metric_info,
    )
    item["_aggregation_policy"] = policy_trace
    if not policy_ok:
        item["_valid"] = False
        item["_error"] = policy_error or "Invalid aggregation policy"
        return item

    if metric and not item.get("metric_label"):
        name = metric_info.get("name", metric)
        unit = metric_info.get("unit", "")
        item["metric_label"] = f"{name} ({unit})" if unit and unit != "unknown" else name

    item["_valid"] = True
    return item


def _scope_matches_region_for_validation(scope: str, region) -> bool:
    if not region:
        return scope == "global"
    r = str(region).lower()
    if scope == "CAN":
        return r.startswith("can") or r.startswith("canada")
    if scope == "USA":
        return r.startswith("usa") or r.startswith("us-")
    if scope == "global":
        return True
    return r.startswith(str(scope).lower())


def _item_prefers_geometry_source_for_validation(item: dict) -> bool:
    text = " ".join(
        str(value or "")
        for value in (
            item.get("summary"),
            item.get("metric"),
            item.get("region"),
            ((item.get("_hints") or {}).get("original_query") if isinstance(item.get("_hints"), dict) else ""),
        )
    ).lower()
    geometry_terms = (
        "county", "counties", "district", "districts", "admin_2", "admin2",
        "tract", "tracts", "state", "states", "province", "provinces",
        "top ", "highest", "lowest", "rank", "ranking",
    )
    return any(term in text for term in geometry_terms)


def _resolve_source_for_validation(item: dict) -> str | None:
    pack_id = item.get("pack_id")
    if not pack_id:
        return item.get("source_id")
    catalog = load_catalog() or {}
    sources = catalog.get("sources", [])
    pack_sources = [src for src in sources if src.get("pack_id") == pack_id]
    if not pack_sources:
        return item.get("source_id")

    region = item.get("region")
    if _item_prefers_geometry_source_for_validation(item):
        geometry_sources = [src for src in pack_sources if src.get("geojson_shape") == "geometry_shape"]
        exact_geometry = [
            src for src in geometry_sources
            if src.get("scope") != "global" and _scope_matches_region_for_validation(src.get("scope", "global"), region)
        ]
        if exact_geometry:
            return exact_geometry[0].get("source_id")
        global_geometry = [src for src in geometry_sources if src.get("scope") == "global"]
        if global_geometry:
            return global_geometry[0].get("source_id")

    exact_matches = [
        src for src in pack_sources
        if src.get("scope") != "global" and _scope_matches_region_for_validation(src.get("scope", "global"), region)
    ]
    if exact_matches:
        return exact_matches[0].get("source_id")

    global_matches = [src for src in pack_sources if src.get("scope") == "global"]
    if global_matches:
        return global_matches[0].get("source_id")
    return pack_sources[0].get("source_id")


def _resolve_metric_for_validation(metric: str, metrics: dict) -> tuple[str | None, list[str]]:
    metric_lower = str(metric or "").strip().lower()
    if not metric_lower or not isinstance(metrics, dict):
        return None, []

    exact_match = None
    close_matches = []
    best_keyword_match = None
    best_keyword_score = 0
    metric_words = set(metric_lower.replace("_", " ").replace("-", " ").split())

    for key, value in metrics.items():
        key_lower = str(key).lower()
        if key_lower == metric_lower:
            return key, []
        phrases = [key_lower]
        if isinstance(value, dict):
            name = str(value.get("name") or "").strip().lower()
            if name:
                phrases.append(name)
            keywords = value.get("keywords") or []
            if isinstance(keywords, list):
                phrases.extend(str(keyword).strip().lower() for keyword in keywords if keyword)
        elif value:
            phrases.append(str(value).strip().lower())

        for phrase in phrases:
            if not phrase:
                continue
            if phrase == metric_lower:
                exact_match = key
                break
            if metric_lower in phrase or phrase in metric_lower:
                close_matches.append(key)
                phrase_words = set(phrase.replace("_", " ").replace("-", " ").split())
                score = len(metric_words & phrase_words) + 2
                if score > best_keyword_score:
                    best_keyword_match = key
                    best_keyword_score = score
            else:
                phrase_words = set(phrase.replace("_", " ").replace("-", " ").split())
                score = len(metric_words & phrase_words)
                if score > best_keyword_score:
                    best_keyword_match = key
                    best_keyword_score = score
        if exact_match:
            break

    if exact_match:
        return exact_match, []
    deduped = list(dict.fromkeys(close_matches))
    if best_keyword_match and best_keyword_score > 0:
        return best_keyword_match, deduped
    return None, deduped


def validate_order(order: dict) -> dict:
    items = order.get("items", [])
    validated_items = []
    all_valid = True
    for item in items:
        validated = validate_order_item(item)
        validated_items.append(validated)
        if not validated.get("_valid", False):
            all_valid = False
    order["items"] = validated_items
    order["_all_valid"] = all_valid
    return order


def _coerce_year(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        if len(text) >= 4 and text[:4].isdigit():
            return int(text[:4])
        return None


def _coerce_date_year(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _coerce_year(value)
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


def _normalize_item_year_fields(item: dict) -> None:
    year = _coerce_year(item.get("year"))
    year_start = _coerce_year(item.get("year_start"))
    year_end = _coerce_year(item.get("year_end"))
    date_start_year = _coerce_date_year(item.get("date_start"))
    date_end_year = _coerce_date_year(item.get("date_end"))
    if year_start is None and date_start_year is not None:
        year_start = date_start_year
    if year_end is None and date_end_year is not None:
        year_end = date_end_year
    if year is None and year_start is not None and year_end is not None and year_start == year_end:
        year = year_start
    if year is not None:
        item["year"] = year
    if year_start is not None:
        item["year_start"] = year_start
    if year_end is not None:
        item["year_end"] = year_end


def _matches_unsupported_metric_alias(user_query: str, metadata: dict) -> bool:
    query_lower = str(user_query or "").strip().lower()
    if not query_lower or not isinstance(metadata, dict):
        return False
    aliases = get_unsupported_metric_aliases(metadata)
    for alias in aliases:
        alias_text = str(alias or "").strip().lower()
        if alias_text and alias_text in query_lower:
            return True
    return False


def _summarize_supported_geography(metadata: dict) -> str:
    return get_supported_geography_summary(metadata)


def _build_metadata_unsupported_metric_clarify(user_query: str, metadata: dict) -> dict:
    source_name = metadata.get("source_name") or metadata.get("source_id") or "this source"
    metrics = metadata.get("metrics") or {}
    metric_names = []
    for info in metrics.values():
        if not isinstance(info, dict):
            continue
        name = str(info.get("name") or "").strip()
        if name:
            metric_names.append(name)
    metric_names = list(dict.fromkeys(metric_names))
    metric_lines = metric_names[:6]
    geo_summary = _summarize_supported_geography(metadata)

    unsupported_label = "that metric"
    aliases = get_unsupported_metric_aliases(metadata)
    query_lower = str(user_query or "").strip().lower()
    for alias in aliases:
        alias_text = str(alias or "").strip()
        if alias_text and alias_text.lower() in query_lower:
            normalized = alias_text
            if " " not in alias_text and alias_text.isalpha() and len(alias_text) <= 5:
                normalized = alias_text.upper()
            unsupported_label = normalized
            break

    lines = [f"{source_name} does not include {unsupported_label}."]
    if metric_lines:
        lines.append("Available metrics for this source include:")
        lines.extend(f"- {name}" for name in metric_lines)
    lines.append(f"This source supports {geo_summary}.")
    lines.append("Which of the available metrics would you like instead?")
    return {"type": "clarify", "message": "\n\n".join([lines[0], "\n".join(lines[1:])])}


def _query_looks_multi_source_comparison(user_query: str) -> bool:
    query_lower = str(user_query or "").strip().lower()
    if not query_lower:
        return False
    comparison_terms = (
        " compare ",
        " compared ",
        " against ",
        " versus ",
        " vs ",
        " alongside ",
        " correlation ",
        " correlated ",
        " relationship ",
        " related to ",
    )
    padded = f" {query_lower} "
    return any(term in padded for term in comparison_terms)


def _distinct_candidate_pack_count(hints: dict | None) -> int:
    candidates = (((hints or {}).get("candidates") or {}).get("sources") or {}).get("candidates") or []
    packs: set[str] = set()
    for candidate in candidates[:5]:
        try:
            confidence = float(candidate.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0.35:
            continue
        pack_id = str(candidate.get("pack_id") or candidate.get("source_id") or "").strip()
        if pack_id:
            packs.add(pack_id)
    return len(packs)


def _select_metadata_guided_metric(user_query: str, metadata: dict) -> str:
    alias_matches = get_metric_alias_matches(metadata, user_query)
    if alias_matches:
        return str(alias_matches[0][1] or "").strip()

    routing_hints = get_routing_hints(metadata)
    if not routing_hints.get("prefer_order_for_analytics"):
        return ""
    default_metric = get_single_metric_default(metadata)
    if not default_metric:
        return ""
    broad_aliases = get_hint_alias_terms(metadata, "broad_topic_aliases", "query_aliases")
    query_lower = str(user_query or "").strip().lower()
    if any(alias in query_lower for alias in broad_aliases):
        return default_metric
    return ""


def _build_metadata_guided_order(user_query: str, hints: dict | None) -> dict | None:
    if not hints or not isinstance(hints, dict):
        return None

    if _query_looks_multi_source_comparison(user_query) and _distinct_candidate_pack_count(hints) > 1:
        return None

    detected_source = hints.get("detected_source") or {}
    source_id = str(detected_source.get("source_id") or "").strip()
    if not source_id:
        return None

    metadata = load_source_metadata(source_id) or {}
    if not metadata:
        return None

    routing_hints = get_routing_hints(metadata)
    wants_event_view = query_prefers_event_source(user_query)
    supports_view_mode_clarify = "view_mode" in (routing_hints.get("clarify_path_dimensions") or [])

    metric = _select_metadata_guided_metric(user_query, metadata)
    if not metric and not (wants_event_view and supports_view_mode_clarify):
        return None

    item = {
        "source_id": source_id,
        "pack_id": str(metadata.get("pack_id") or detected_source.get("pack_id") or "").strip(),
        "_hints": {"original_query": user_query},
    }
    if metric:
        item["metric"] = metric

    location = hints.get("location") or {}
    iso3 = str(location.get("iso3") or "").strip()
    if iso3:
        item["region"] = iso3

    time_hints = hints.get("time") or {}
    year_start = time_hints.get("year_start")
    year_end = time_hints.get("year_end")
    if year_start and year_end:
        item["year_start"] = year_start
        item["year_end"] = year_end
    elif year_start:
        item["year"] = year_start

    metric_info = (metadata.get("metrics") or {}).get(metric) or {}
    metric_name = str(metric_info.get("name") or metric or metadata.get("source_name") or source_id).strip()
    source_name = str(metadata.get("source_name") or source_id).strip()
    summary = f"{metric_name} from {source_name}"
    if item.get("year_start") and item.get("year_end"):
        summary += f", {item['year_start']}-{item['year_end']}"
    elif item.get("year"):
        summary += f" for {item['year']}"
    if item.get("region"):
        summary += f" in {item['region']}"

    return {
        "type": "order",
        "order": {
            "summary": summary,
            "items": [item],
        },
        "summary": summary,
    }


def _apply_metadata_guided_response_normalization(result: dict, *, user_query: str, hints: dict | None) -> dict:
    if not isinstance(result, dict) or result.get("type") not in {"chat", "clarify"}:
        return result
    if not hints or not isinstance(hints, dict):
        return result
    detected_source = hints.get("detected_source") or {}
    source_id = detected_source.get("source_id")
    if not source_id:
        return result
    metadata = load_source_metadata(source_id) or {}
    if not metadata:
        return result
    if _matches_unsupported_metric_alias(user_query, metadata):
        return _build_metadata_unsupported_metric_clarify(user_query, metadata)
    guided_order = _build_metadata_guided_order(user_query, hints)
    if guided_order is not None:
        return guided_order
    return result


def parse_llm_response(content: str, hints: dict = None, user_query: str = "") -> dict:
    parsed_json = None
    if "```json" in content:
        try:
            json_str = content.split("```json")[1].split("```")[0].strip()
            parsed_json = json.loads(json_str)
        except (json.JSONDecodeError, IndexError):
            pass
    elif content.strip().startswith("{"):
        try:
            parsed_json = json.loads(content.strip())
        except json.JSONDecodeError:
            pass

    if parsed_json and isinstance(parsed_json, dict):
        response_type = parsed_json.get("type", "order")
        if response_type == "navigate":
            return {
                "type": "navigate",
                "locations": parsed_json.get("locations", []),
                "message": parsed_json.get("message", "Navigating to location"),
            }
        if response_type == "geometry_remove":
            return {
                "type": "geometry_remove",
                "regions": parsed_json.get("regions", []),
                "geometry_type": parsed_json.get("geometry_type", "zcta"),
                "message": parsed_json.get("message", "Removing geometry"),
            }
        if response_type == "disambiguate":
            return {
                "type": "disambiguate",
                "options": parsed_json.get("options", []),
                "message": parsed_json.get("message", "Multiple locations found"),
                "query_term": parsed_json.get("query_term", "location"),
            }
        if response_type == "filter_update":
            return {
                "type": "filter_update",
                "overlay": parsed_json.get("overlay", ""),
                "filters": parsed_json.get("filters", {}),
                "message": parsed_json.get("message", "Updating filters"),
            }
        if response_type == "overlay_toggle":
            return {
                "type": "overlay_toggle",
                "overlay": parsed_json.get("overlay", ""),
                "enabled": parsed_json.get("enabled", True),
                "message": parsed_json.get("message", ""),
            }
        if response_type == "chat":
            result = {"type": "chat", "message": parsed_json.get("message", "")}
            return _apply_metadata_guided_response_normalization(result, user_query=user_query, hints=hints)
        if response_type == "clarify":
            result = {"type": "clarify", "message": parsed_json.get("message", "Could you provide more details?")}
            return _apply_metadata_guided_response_normalization(result, user_query=user_query, hints=hints)
        order = validate_order(parsed_json)
        return {
            "type": "order",
            "order": order,
            "summary": order.get("summary", "Data request"),
        }

    if "?" in content and len(content) < 200:
        result = {"type": "clarify", "message": content}
        return _apply_metadata_guided_response_normalization(result, user_query=user_query, hints=hints)
    result = {"type": "chat", "message": content}
    return _apply_metadata_guided_response_normalization(result, user_query=user_query, hints=hints)
