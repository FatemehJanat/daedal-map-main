"""
Utility functions for normalization, unit conversion, and data cleaning.
"""

import re
import unicodedata
import pandas as pd

from .constants import state_abbreviations, UNIT_MULTIPLIERS


def convert_unit(value, from_unit, to_unit, metadata):
    """
    Convert a numerical value from one unit to another using metadata conversions.

    Args:
        value: Numerical value to convert
        from_unit: Original unit (from metadata)
        to_unit: Target unit (from user query)
        metadata: Column metadata containing conversion factors

    Returns:
        Converted value or None if conversion not possible
    """
    if from_unit == to_unit:
        return value

    # Get conversion factors from metadata
    conversions = metadata.get("conversions", {})

    if to_unit in conversions:
        return float(value) * conversions[to_unit]

    # Could not convert
    return None


def state_from_abbr(name):
    """Convert state abbreviation to full state name."""
    return state_abbreviations.get(name.upper(), "Unknown")


def normalize(name: str) -> str:
    """
    Normalize place names for fuzzy matching.
    Removes accents, county suffixes, punctuation, etc.
    """
    name = name.strip()
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))  # remove accents
    name = name.lower()
    name = re.sub(r'\bsaint\b', 'st', name)  # fix saint
    name = re.sub(r'\b(county|borough|census|area|city|and|municipality|gateway|municipio)\b', '', name)  # remove common fluff
    name = re.sub(r'[^\w\s]', '', name)  # remove punctuation
    name = re.sub(r'\s+', ' ', name)  # collapse multiple spaces
    return name.strip()


def parse_year_value(year_val):
    """
    Parse a year value that might be a range like '2022-2023' or a single year.
    Returns an integer year, or None if unparseable.
    For ranges, returns the end year (most recent).
    """
    if year_val is None:
        return None
    year_str = str(year_val).strip()
    # Try direct integer conversion first
    try:
        return int(float(year_str))
    except (ValueError, TypeError):
        pass
    # Try parsing as a range like "2022-2023"
    if '-' in year_str:
        parts = year_str.split('-')
        if len(parts) == 2:
            try:
                # Return the end year (most recent)
                return int(parts[1].strip())
            except (ValueError, TypeError):
                pass
            try:
                # Fall back to start year if end year fails
                return int(parts[0].strip())
            except (ValueError, TypeError):
                pass
    # Try extracting any 4-digit year from the string
    match = re.search(r'\b(19|20)\d{2}\b', year_str)
    if match:
        return int(match.group())
    return None


def clean_nans(obj):
    """
    Recursively clean NaN values from nested data structures.
    Converts NaN/None to None for JSON serialization.
    """
    if isinstance(obj, dict):
        return {k: clean_nans(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_nans(item) for item in obj]
    elif isinstance(obj, float) and (pd.isna(obj) or obj != obj):
        return None
    return obj


def apply_unit_multiplier(filter_spec):
    """
    Apply unit multiplier to filter value if unit is specified.
    Modifies filter_spec in place.

    Args:
        filter_spec: Dict with 'value' and optionally 'unit' keys
    """
    if not filter_spec:
        return

    unit = (filter_spec.get("unit") or "").lower()
    value = filter_spec.get("value")

    if unit in UNIT_MULTIPLIERS and value is not None:
        filter_spec["value"] = value * UNIT_MULTIPLIERS[unit]
        filter_spec["unit"] = ""
