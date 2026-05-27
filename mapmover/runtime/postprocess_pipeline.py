"""Shared pre-validation postprocess pipeline helpers."""


def inject_original_query_hints(items: list, original_query: str) -> None:
    """Copy the original query into item-level hints when the LLM omitted it."""
    if not original_query:
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        item_hints = item.get("_hints") if isinstance(item.get("_hints"), dict) else {}
        if not item_hints.get("original_query"):
            item_hints["original_query"] = original_query
            item["_hints"] = item_hints


def apply_preprocessor_time_hints(
    items: list,
    time_hints: dict,
    load_source_metadata,
) -> None:
    """Apply preprocessor-derived time ranges when the LLM left years blank."""
    if not time_hints.get("is_time_series"):
        return
    for item in items:
        if item.get("year") is None and not item.get("year_start") and not item.get("year_end"):
            if time_hints.get("year_start") and time_hints.get("year_end"):
                item["year_start"] = time_hints["year_start"]
                item["year_end"] = time_hints["year_end"]
            elif time_hints.get("pattern_type") == "trend" and item.get("source_id"):
                metadata = load_source_metadata(item["source_id"])
                if metadata:
                    temp = metadata.get("temporal_coverage", {})
                    if temp.get("start") and temp.get("end"):
                        item["year_start"] = temp["start"]
                        item["year_end"] = temp["end"]


def run_pre_validation_pipeline(
    items: list,
    hints: dict,
    catalog: dict,
    detect_event_mode,
    normalize_aggregate_metric_mode,
    normalize_order_items,
    expand_full_pack_loads,
    expand_wildcard_metrics,
    expand_all_derived_fields,
) -> tuple[list, int]:
    """Run the deterministic item expansion pipeline before validation."""
    items = detect_event_mode(items, hints)
    items = normalize_aggregate_metric_mode(items, hints, catalog)
    items = normalize_order_items(items, catalog)
    items = expand_full_pack_loads(items, catalog)
    items = expand_wildcard_metrics(items)
    metric_count = sum(1 for item in items if item.get("type") != "derived_result")
    expanded_items = expand_all_derived_fields(items)
    return expanded_items, metric_count


def split_derived_specs(expanded_items: list) -> tuple[list, list]:
    """Separate derived-result specs from regular validated items."""
    regular_items = []
    derived_specs = []
    for item in expanded_items:
        if item.get("type") == "derived_result":
            derived_specs.append(item)
        else:
            regular_items.append(item)
    return regular_items, derived_specs


def validate_regular_items(
    regular_items: list,
    catalog: dict,
    normalize_source_declared_scope,
    validate_item,
) -> tuple[list, list, int]:
    """Validate regular items and collect error summaries."""
    validated_items = []
    errors = []
    valid_count = 0

    for item in regular_items:
        item = normalize_source_declared_scope(item)
        validated = validate_item(item, catalog)
        validated_items.append(validated)
        if validated.get("_valid"):
            valid_count += 1
        else:
            errors.append(validated.get("_error", "Unknown error"))

    return validated_items, errors, valid_count


def build_validation_summary(validated_items: list, errors: list, valid_count: int) -> str:
    """Build the human-readable validation summary string."""
    total = len(validated_items)
    if errors:
        return f"{valid_count}/{total} items valid. Errors: {'; '.join(errors)}"
    return f"All {total} items validated successfully"
