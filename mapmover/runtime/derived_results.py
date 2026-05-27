"""Shared derived-result calculation helpers."""

from __future__ import annotations


def apply_derived_fields(boxes: dict, derived_specs: list, year: int = None) -> list:
    """Apply derived field calculations to filled metric boxes."""
    warnings = []

    def _resolve_metric_value(metrics: dict, candidates) -> tuple[object, str | None]:
        candidate_list = [candidate for candidate in (candidates or []) if candidate]
        if not candidate_list:
            return None, None

        for candidate in candidate_list:
            if candidate in metrics:
                return metrics[candidate], candidate

        lowered = {str(key).lower(): key for key in metrics.keys()}
        for candidate in candidate_list:
            matched_key = lowered.get(str(candidate).lower())
            if matched_key is not None:
                return metrics[matched_key], matched_key

        return None, None

    for spec in derived_specs:
        numerator_name = spec.get("numerator")
        denominator_name = spec.get("denominator")
        numerator_candidates = spec.get("numerator_candidates") or [numerator_name]
        denominator_candidates = spec.get("denominator_candidates") or [denominator_name]
        label = spec.get("label", f"{numerator_name}/{denominator_name}")
        multiplier = spec.get("multiplier", 1)

        for loc_id, metrics in boxes.items():
            num_val, _ = _resolve_metric_value(metrics, numerator_candidates)
            if num_val is None:
                continue

            denom_val, resolved_denominator_key = _resolve_metric_value(metrics, denominator_candidates)
            if denom_val is None:
                warnings.append(f"{loc_id}: {denominator_name} unavailable")
                continue

            if denom_val == 0:
                zero_name = resolved_denominator_key or denominator_name
                warnings.append(f"{loc_id}: {zero_name} is zero")
                continue

            result = (float(num_val) / float(denom_val)) * multiplier
            metrics[f"{label} (calculated)"] = result

    return warnings
