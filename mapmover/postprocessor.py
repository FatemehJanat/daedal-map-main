"""
Postprocessor - validates orders and expands derived fields.

Runs AFTER the LLM call and:
1. Validates each order item against catalog
2. Expands derived field shortcuts (per_capita, density, etc.)
3. Expands cross-source derived fields
4. Returns processed order with validation results

The postprocessor ensures:
- All items reference valid sources and metrics
- Derived fields are expanded into component items + calculation spec
- Items marked for_derivation are hidden from user display
"""

import json
from pathlib import Path
from typing import Optional

DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/data")
CATALOG_PATH = DATA_DIR.parent / "catalog.json"


def load_catalog() -> dict:
    """Load the data catalog."""
    if CATALOG_PATH.exists():
        with open(CATALOG_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {}


def load_source_metadata(source_id: str) -> dict:
    """Load metadata.json for a specific source."""
    meta_path = DATA_DIR / source_id / "metadata.json"
    if meta_path.exists():
        with open(meta_path, encoding='utf-8') as f:
            return json.load(f)
    return {}


# =============================================================================
# Derived Field Expansion Tables
# =============================================================================

# Shortcut expansions for common derived fields
DERIVED_EXPANSIONS = {
    "per_capita": {
        "denominator": "population",
        "denominator_source": "owid_co2",  # Canonical source for population
        "label_suffix": "Per Capita",
    },
    "density": {
        "denominator": "area_sq_km",
        "denominator_source": "world_factbook_static",  # Static area data
        "label_suffix": "Density",
    },
    "per_1000": {
        "denominator": "population",
        "denominator_source": "owid_co2",
        "multiplier": 1000,
        "label_suffix": "Per 1000",
    },
}

# Canonical sources for common metrics used in derivations
CANONICAL_SOURCES = {
    "population": "owid_co2",
    "area_sq_km": "world_factbook_static",
    "gdp": "owid_co2",
}


# =============================================================================
# Validation
# =============================================================================

def validate_item(item: dict, catalog: dict) -> dict:
    """
    Validate an order item against catalog.

    Returns item with validation fields added:
    - _valid: bool
    - _error: str (if invalid)
    - metric_label: str (if valid)
    """
    source_id = item.get("source_id")
    metric = item.get("metric")

    # Skip derived_result items - they're calculated, not fetched
    if item.get("type") == "derived_result":
        item["_valid"] = True
        return item

    # Skip derived items that need expansion first
    if item.get("type") == "derived":
        item["_valid"] = True
        item["_needs_expansion"] = True
        return item

    if not source_id:
        item["_valid"] = False
        item["_error"] = "Missing source_id"
        return item

    # Check source exists in catalog (sources is a list)
    sources = catalog.get("sources", [])
    source_ids = [s.get("source_id") for s in sources] if isinstance(sources, list) else list(sources.keys())
    if source_id not in source_ids:
        item["_valid"] = False
        item["_error"] = f"Unknown source: {source_id}"
        return item

    # Load full metadata for metric validation
    metadata = load_source_metadata(source_id)
    if not metadata:
        # Source in catalog but no metadata file - still valid
        item["_valid"] = True
        return item

    # Check metric exists
    metrics = metadata.get("metrics", {})
    if metric and metric not in metrics:
        close_matches = [k for k in metrics.keys()
                         if metric.lower() in k.lower() or k.lower() in metric.lower()]
        if close_matches:
            item["_valid"] = False
            item["_error"] = f"Metric '{metric}' not found. Did you mean: {', '.join(close_matches[:3])}?"
        else:
            item["_valid"] = False
            item["_error"] = f"Metric '{metric}' not found in {source_id}"
        return item

    # Add metric label
    if metric:
        metric_info = metrics.get(metric, {})
        name = metric_info.get("name", metric)
        unit = metric_info.get("unit", "")
        if unit and unit != "unknown":
            item["metric_label"] = f"{name} ({unit})"
        else:
            item["metric_label"] = name

    item["_valid"] = True
    return item


# =============================================================================
# Derived Field Expansion
# =============================================================================

def expand_derived_shortcut(item: dict) -> list:
    """
    Expand a derived shortcut (e.g., derived: "per_capita") into component items.

    Input: {"source_id": "owid_co2", "metric": "gdp", "region": "EU", "derived": "per_capita"}

    Output: [
        {"source_id": "owid_co2", "metric": "gdp", "region": "EU", "for_derivation": True},
        {"source_id": "owid_co2", "metric": "population", "region": "EU", "for_derivation": True},
        {"type": "derived_result", "numerator": "gdp", "denominator": "population", "label": "GDP Per Capita"}
    ]
    """
    derived_type = item.get("derived")
    if not derived_type or derived_type not in DERIVED_EXPANSIONS:
        return [item]  # Return unchanged if not a known shortcut

    expansion = DERIVED_EXPANSIONS[derived_type]
    source_id = item.get("source_id")
    metric = item.get("metric")
    region = item.get("region")
    year = item.get("year")
    year_start = item.get("year_start")
    year_end = item.get("year_end")

    # Build base item properties
    base_props = {"region": region}
    if year:
        base_props["year"] = year
    if year_start:
        base_props["year_start"] = year_start
    if year_end:
        base_props["year_end"] = year_end

    expanded = []

    # 1. Numerator item (the original metric)
    numerator_item = {
        "source_id": source_id,
        "metric": metric,
        "for_derivation": True,
        **base_props
    }
    expanded.append(numerator_item)

    # 2. Denominator item (from canonical source)
    denom_metric = expansion["denominator"]
    denom_source = expansion.get("denominator_source", source_id)
    denominator_item = {
        "source_id": denom_source,
        "metric": denom_metric,
        "for_derivation": True,
        **base_props
    }
    expanded.append(denominator_item)

    # 3. Derived result specification
    label = f"{metric} {expansion['label_suffix']}"
    derived_result = {
        "type": "derived_result",
        "numerator": metric,
        "denominator": denom_metric,
        "label": label,
    }
    if expansion.get("multiplier"):
        derived_result["multiplier"] = expansion["multiplier"]
    expanded.append(derived_result)

    return expanded


def expand_cross_source_derived(item: dict) -> list:
    """
    Expand a cross-source derived field into component items.

    Input: {
        "type": "derived",
        "numerator": {"source_id": "owid_co2", "metric": "gdp"},
        "denominator": {"source_id": "imf_bop", "metric": "exports"},
        "region": "EU"
    }

    Output: [
        {"source_id": "owid_co2", "metric": "gdp", "region": "EU", "for_derivation": True},
        {"source_id": "imf_bop", "metric": "exports", "region": "EU", "for_derivation": True},
        {"type": "derived_result", "numerator": "gdp", "denominator": "exports", "label": "GDP/Exports"}
    ]
    """
    if item.get("type") != "derived":
        return [item]

    numerator = item.get("numerator", {})
    denominator = item.get("denominator", {})
    region = item.get("region")
    year = item.get("year")
    year_start = item.get("year_start")
    year_end = item.get("year_end")

    # Handle simple string numerator/denominator (same source assumed)
    if isinstance(numerator, str):
        numerator = {"metric": numerator}
    if isinstance(denominator, str):
        denominator = {"metric": denominator}

    # Build base item properties
    base_props = {"region": region}
    if year:
        base_props["year"] = year
    if year_start:
        base_props["year_start"] = year_start
    if year_end:
        base_props["year_end"] = year_end

    expanded = []

    # 1. Numerator item
    num_source = numerator.get("source_id", item.get("source_id"))
    num_metric = numerator.get("metric")
    if num_source and num_metric:
        expanded.append({
            "source_id": num_source,
            "metric": num_metric,
            "for_derivation": True,
            **base_props
        })

    # 2. Denominator item
    denom_source = denominator.get("source_id", item.get("source_id"))
    denom_metric = denominator.get("metric")
    if denom_source and denom_metric:
        expanded.append({
            "source_id": denom_source,
            "metric": denom_metric,
            "for_derivation": True,
            **base_props
        })

    # 3. Derived result
    label = item.get("label", f"{num_metric}/{denom_metric}")
    derived_result = {
        "type": "derived_result",
        "numerator": num_metric,
        "denominator": denom_metric,
        "label": label,
    }
    if item.get("multiplier"):
        derived_result["multiplier"] = item["multiplier"]
    expanded.append(derived_result)

    return expanded


def expand_all_derived_fields(items: list) -> list:
    """
    Expand all derived fields in an items list.

    Handles both:
    - Shortcut syntax: {"derived": "per_capita"}
    - Cross-source syntax: {"type": "derived", "numerator": {...}, "denominator": {...}}
    """
    expanded = []

    for item in items:
        # Check for shortcut syntax first
        if item.get("derived") and item.get("derived") in DERIVED_EXPANSIONS:
            expanded.extend(expand_derived_shortcut(item))

        # Check for cross-source syntax
        elif item.get("type") == "derived":
            expanded.extend(expand_cross_source_derived(item))

        # Regular item - keep as is
        else:
            expanded.append(item)

    return expanded


# =============================================================================
# Main Postprocessor
# =============================================================================

def postprocess_order(order: dict, hints: dict = None) -> dict:
    """
    Main postprocessor function.

    Takes an order from the LLM and:
    1. Expands derived fields
    2. Validates all items
    3. Returns processed order with validation results

    Args:
        order: The order dict from LLM (with "items" list)
        hints: Preprocessor hints (for context if needed)

    Returns:
        Processed order with:
        - items: list of validated items (may be expanded)
        - derived_specs: list of derived calculation specs
        - validation_summary: str describing validation results
    """
    catalog = load_catalog()
    items = order.get("items", [])

    # Step 1: Expand derived fields
    expanded_items = expand_all_derived_fields(items)

    # Step 2: Separate derived specs from regular items
    regular_items = []
    derived_specs = []

    for item in expanded_items:
        if item.get("type") == "derived_result":
            derived_specs.append(item)
        else:
            regular_items.append(item)

    # Step 3: Validate regular items
    validated_items = []
    errors = []
    valid_count = 0

    for item in regular_items:
        validated = validate_item(item, catalog)
        validated_items.append(validated)
        if validated.get("_valid"):
            valid_count += 1
        else:
            errors.append(validated.get("_error", "Unknown error"))

    # Build validation summary
    total = len(validated_items)
    if errors:
        summary = f"{valid_count}/{total} items valid. Errors: {'; '.join(errors)}"
    else:
        summary = f"All {total} items validated successfully"

    # Return processed order
    return {
        "items": validated_items,
        "derived_specs": derived_specs,
        "validation_summary": summary,
        "all_valid": len(errors) == 0,
        # Preserve original order fields
        "summary": order.get("summary"),
        "region": order.get("region"),
        "year": order.get("year"),
        "year_start": order.get("year_start"),
        "year_end": order.get("year_end"),
    }


def get_display_items(items: list, derived_specs: list = None) -> list:
    """
    Get items for display in the order panel.

    Filters out items with for_derivation=True.
    Adds display representations for derived specs.
    """
    display = []

    # Add non-derivation regular items
    for item in items:
        if not item.get("for_derivation"):
            display.append(item)

    # Add display items for derived specs
    if derived_specs:
        for spec in derived_specs:
            display.append({
                "type": "derived",
                "metric": spec.get("label", "Derived"),
                "metric_label": f"{spec.get('label', 'Derived')} (calculated)",
                "_valid": True,
                "_is_derived": True,
            })

    return display


def format_validation_messages(order: dict) -> list:
    """
    Format validation results as chat messages.

    Returns list of strings for display to user.
    """
    messages = []
    items = order.get("items", [])

    for item in items:
        if item.get("for_derivation"):
            continue  # Don't show derivation source items

        if item.get("_valid"):
            source = item.get("source_id", "?")
            metric = item.get("metric_label") or item.get("metric", "?")
            messages.append(f"+ {metric}: Found in {source}")
        else:
            metric = item.get("metric", "?")
            error = item.get("_error", "Unknown error")
            messages.append(f"- {metric}: {error}")

    # Add derived field info
    derived = order.get("derived_specs", [])
    for spec in derived:
        label = spec.get("label", "Derived")
        messages.append(f"+ {label} (calculated)")

    return messages
