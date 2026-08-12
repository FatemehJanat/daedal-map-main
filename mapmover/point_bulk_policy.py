"""Shared request-shaping rules for interactive point resolution."""

from __future__ import annotations

from typing import Any


GLOBAL_BULK_PRESETS = {"global_admin_0": 0, "global_admin_1": 1}


def apply_global_bulk_preset(
    value: Any,
    *,
    country_scope: str | None,
    target_admin_level: int | None,
) -> tuple[str | None, str | None, int | None, dict[str, Any] | None]:
    """Validate a cross-country preset and apply its bounded admin level."""
    preset = str(value or "").strip().lower() or None
    if preset is None:
        return None, country_scope, target_admin_level, None
    if preset not in GLOBAL_BULK_PRESETS:
        return preset, country_scope, target_admin_level, {
            "code": "invalid_bulk_preset",
            "message": "bulk_preset must be global_admin_0 or global_admin_1.",
            "supported_values": list(GLOBAL_BULK_PRESETS),
        }
    preset_level = GLOBAL_BULK_PRESETS[preset]
    conflicts = []
    if country_scope:
        conflicts.append("country_scope")
    if target_admin_level is not None and target_admin_level != preset_level:
        conflicts.append("target_admin_level")
    if conflicts:
        return preset, country_scope, target_admin_level, {
            "code": "bulk_preset_conflict",
            "message": (
                "A global bulk preset replaces country_scope and fixes the target admin "
                "level; remove the conflicting fields."
            ),
            "conflicting_fields": conflicts,
        }
    return preset, None, preset_level, None


def point_bulk_shape_error(
    *,
    point_count: int,
    country_scope: str | None,
    target_admin_level: int | None,
    bulk_preset: str | None,
    threshold: int,
) -> dict[str, Any] | None:
    """Require either one country/level bank or an authored global preset."""
    if point_count <= threshold or bulk_preset in GLOBAL_BULK_PRESETS:
        return None
    missing = []
    if not country_scope:
        missing.append("country_scope")
    if target_admin_level is None:
        missing.append("target_admin_level")
    if not missing:
        return None
    return {
        "code": "bulk_scope_required",
        "message": (
            f"Point batches above {threshold} must declare one country_scope and one "
            "target_admin_level, or use bulk_preset global_admin_0/global_admin_1. "
            "Split other multi-country inputs into separate calls."
        ),
        "missing_fields": missing,
        "supported_cross_country_presets": list(GLOBAL_BULK_PRESETS),
    }
