"""Order-dispatch helpers extracted from the main executor."""

from __future__ import annotations


def prepare_execution_items(
    *,
    items: list,
    load_catalog_func,
    normalize_order_items_func,
    get_source_data_type_func,
    source_supports_disaster_aggregates_func,
    validate_execution_items_func,
) -> tuple[list, str | None]:
    """Normalize items, infer aggregate mode, and validate execution inputs."""
    prepared_items = normalize_order_items_func(items, load_catalog_func())
    for item in prepared_items:
        if item.get("mode"):
            continue
        source_id = item.get("source_id")
        if not source_id:
            continue
        if (
            get_source_data_type_func(source_id) == "metrics"
            and source_supports_disaster_aggregates_func(source_id)
        ):
            item["mode"] = "aggregate"
    validation_error = validate_execution_items_func(prepared_items)
    return prepared_items, validation_error


def route_special_order(
    *,
    order: dict,
    items: list,
    action: str,
    primary_source_id: str | None,
    get_source_from_catalog_func,
    execute_removal_order_func,
    execute_mixed_order_if_needed_func,
    execute_multi_layer_order_if_needed_func,
    execute_event_order_func,
) -> dict | None:
    """Handle non-standard order flows before the metrics pipeline."""
    if action == "remove":
        return execute_removal_order_func(order, items, primary_source_id)

    mixed_result = execute_mixed_order_if_needed_func(order, items, primary_source_id)
    if mixed_result:
        return mixed_result

    layered_result = execute_multi_layer_order_if_needed_func(order, items)
    if layered_result:
        return layered_result

    def is_event_item(item):
        source_id = item.get("source_id")
        source_info = get_source_from_catalog_func(source_id) if source_id else None
        source_data_type = (source_info or {}).get("data_type", "metrics")
        if isinstance(source_data_type, list):
            supports_events = "events" in source_data_type
        else:
            supports_events = source_data_type == "events"
        if item.get("mode") == "aggregate":
            return False
        if item.get("mode") == "events":
            return supports_events
        return supports_events

    event_items = [item for item in items if is_event_item(item)]
    if event_items:
        event_order = {**order, "items": event_items}
        result = execute_event_order_func(event_order)
        result["data_type"] = "events"
        result["source_id"] = event_items[0].get("source_id")
        return result

    return None
