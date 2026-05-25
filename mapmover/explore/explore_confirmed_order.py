"""Explore confirmed-order helpers."""

from __future__ import annotations

import hashlib
import json


def execute_confirmed_order_with_session_cache(
    cache,
    confirmed_order: dict,
    *,
    force_refetch: bool = False,
    execute_order_func,
):
    """Execute one confirmed order with the Explore session cache."""
    order_str = json.dumps(confirmed_order, sort_keys=True)
    request_key = hashlib.md5(order_str.encode()).hexdigest()[:16]
    if not force_refetch:
        cached_result = cache.get_cached_result(request_key)
        if cached_result is not None:
            return cached_result, request_key, True
    result = execute_order_func(confirmed_order)
    cache.store_result(request_key, result)
    return result, request_key, False
