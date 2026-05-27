from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..foundation_helpers import load_reference_json

_BASE_DIR = Path(__file__).resolve().parent.parent
_CONVERSIONS_PATH = _BASE_DIR / "conversions.json"

_CONVERSIONS_CACHE: dict[str, Any] | None = None
_ISO_CODES_CACHE: dict[str, Any] | None = None
_USA_ADMIN_CACHE: dict[str, Any] | None = None


def load_conversions() -> dict[str, Any]:
    """Load shared regional grouping and alias helpers from conversions.json."""
    global _CONVERSIONS_CACHE
    if _CONVERSIONS_CACHE is not None:
        return _CONVERSIONS_CACHE

    if not _CONVERSIONS_PATH.exists():
        _CONVERSIONS_CACHE = {}
        return _CONVERSIONS_CACHE

    with open(_CONVERSIONS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    _CONVERSIONS_CACHE = data if isinstance(data, dict) else {}
    return _CONVERSIONS_CACHE


def load_iso_codes() -> dict[str, Any]:
    """Load shared ISO code helpers from reference/iso_codes.json."""
    global _ISO_CODES_CACHE
    if _ISO_CODES_CACHE is not None:
        return _ISO_CODES_CACHE

    data = load_reference_json("iso_codes.json")
    _ISO_CODES_CACHE = data if isinstance(data, dict) else {}
    return _ISO_CODES_CACHE


def load_usa_admin() -> dict[str, Any]:
    """Load shared USA admin helpers from reference/usa/usa_admin.json."""
    global _USA_ADMIN_CACHE
    if _USA_ADMIN_CACHE is not None:
        return _USA_ADMIN_CACHE

    data = load_reference_json("usa/usa_admin.json")
    _USA_ADMIN_CACHE = data if isinstance(data, dict) else {}
    return _USA_ADMIN_CACHE
