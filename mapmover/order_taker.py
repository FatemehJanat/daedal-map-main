"""
Order Taker - interprets user requests into structured orders.
Single LLM call using catalog.json and conversions.json for data awareness.

This replaces the old multi-LLM chat system with a simpler "Fast Food Kiosk" model:
1. User describes what they want in natural language
2. Order Taker LLM interprets and builds structured "order"
3. User confirms/modifies order in UI
4. System executes confirmed order directly (no second LLM)
"""

import json
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

from .data_loading import load_catalog, load_source_metadata

load_dotenv()

CONVERSIONS_PATH = Path(__file__).parent / "conversions.json"
REFERENCE_DIR = Path(__file__).parent / "reference"


def load_conversions() -> dict:
    """Load the conversions/regional groupings."""
    with open(CONVERSIONS_PATH, encoding='utf-8') as f:
        return json.load(f)


def load_usa_admin() -> dict:
    """Load USA admin data from reference/usa_admin.json."""
    usa_path = REFERENCE_DIR / "usa_admin.json"
    if usa_path.exists():
        with open(usa_path, encoding='utf-8') as f:
            return json.load(f)
    return {}


def build_regions_text(conversions: dict) -> str:
    """Build regions text dynamically from conversions.json and usa_admin.json."""
    groupings = conversions.get("regional_groupings", {})
    usa_admin = load_usa_admin()
    state_abbrevs = usa_admin.get("state_abbreviations", {})

    # Mapping for readable display names (use underscore version for orders)
    display_names = {
        "European_Union": "eu",
        "NATO": "nato",
        "G7": "g7",
        "G20": "g20",
        "BRICS": "brics",
        "ASEAN": "asean",
        "Arab_League": "arab_league",
        "African_Union": "african_union",
        "Commonwealth": "commonwealth",
        "Gulf_Cooperation_Council": "gcc",
        "South_America": "south_america",
        "North_America": "north_america",
        "Latin_America": "latin_america",
        "Central_America": "central_america",
        "Caribbean": "caribbean",
        "Nordic_Countries": "nordic",
        "Baltic_States": "baltic",
        "Benelux": "benelux",
        "Maghreb": "maghreb",
        "Pacific_Islands": "pacific_islands",
        "Asia": "asia",
        "Oceania": "oceania"
    }

    # Categorize groupings
    continents = []
    political = []
    economic = []
    geographic = []
    subregions = []

    for name, data in groupings.items():
        count = len(data.get("countries", []))
        display = display_names.get(name, name.lower().replace(" ", "_"))

        # Categorize based on name patterns
        if name in ["Asia", "Oceania"]:
            continents.append(f"{display} ({count})")
        elif name in ["European_Union", "NATO", "G7", "G20", "BRICS"]:
            political.append(f"{display} ({count})")
        elif name in ["ASEAN", "Arab_League", "African_Union", "Commonwealth", "Gulf_Cooperation_Council"]:
            economic.append(f"{display} ({count})")
        elif name in ["South_America", "North_America", "Latin_America", "Central_America", "Caribbean"]:
            geographic.append(f"{display} ({count})")
        elif name in ["Nordic_Countries", "Baltic_States", "Benelux", "Maghreb", "Pacific_Islands"]:
            subregions.append(f"{display} ({count})")
        elif name.startswith("WHO_"):
            # WHO regions map to continent names
            if "African" in name:
                continents.append(f"africa ({count})")
            elif "Americas" in name:
                continents.append(f"americas ({count})")
            elif "European" in name:
                continents.append(f"europe ({count})")

    # Remove duplicates and sort
    continents = sorted(set(continents))

    lines = []
    if continents:
        lines.append(f"- Continents: {', '.join(continents)}")
    if political:
        lines.append(f"- Political: {', '.join(political)}")
    if economic:
        lines.append(f"- Economic: {', '.join(economic)}")
    if geographic:
        lines.append(f"- Geographic: {', '.join(geographic)}")
    if subregions:
        lines.append(f"- Sub-regions: {', '.join(subregions)}")

    # Add US states info
    lines.append(f"- US States: use state name or abbreviation (e.g., \"California\" or \"CA\") - {len(state_abbrevs)} states/territories")

    return "\n".join(lines)


def build_system_prompt(catalog: dict, conversions: dict) -> str:
    """
    Build system prompt with full catalog and column names from metadata.

    Loads metadata.json for each source to get exact column names.
    TODO: Optimize by adding column names to catalog.json later.
    """

    # Build sources text from catalog with exact column names
    sources_text = ""
    usa_only_sources = []

    for src in catalog["sources"]:
        geo = src.get("geographic_coverage", {})
        temp = src.get("temporal_coverage", {})
        coverage = src.get("coverage_description", geo.get("type", "unknown"))

        # Load actual metadata to get exact column names
        source_id = src['source_id']
        metadata = load_source_metadata(source_id)
        metrics = metadata.get("metrics", {})

        # Build column list with descriptions
        if metrics:
            # Format: column_name (Human Name, unit)
            column_entries = []
            for col_name, col_info in list(metrics.items())[:15]:  # Limit to 15 columns
                name = col_info.get("name", col_name)
                unit = col_info.get("unit", "")
                if unit and unit != "unknown":
                    column_entries.append(f"{col_name} ({name}, {unit})")
                else:
                    column_entries.append(f"{col_name} ({name})")
            columns_text = ", ".join(column_entries)
            if len(metrics) > 15:
                columns_text += f" ... and {len(metrics) - 15} more"
        else:
            columns_text = "see metadata"

        sources_text += f"""
**{source_id}** ({src['source_name']})
  Coverage: {coverage}, {temp.get('start', '?')}-{temp.get('end', '?')}
  COLUMNS: {columns_text}
"""
        # Track USA-only sources
        if geo.get("type") == "country" and geo.get("countries") == 1:
            usa_only_sources.append(source_id)

    # Build regions text from conversions
    regions_text = build_regions_text(conversions)

    # USA-only warning
    usa_warning = ""
    if usa_only_sources:
        usa_warning = f"\nUSA-ONLY (counties, not countries): {', '.join(usa_only_sources)}"

    return f"""You are an Order Taker for a map data visualization system.

AVAILABLE DATA SOURCES:
{sources_text}
{usa_warning}

REGIONS:
{regions_text}

ORDER FORMAT (JSON when user requests data):
```json
{{"items": [{{"source_id": "owid_co2", "metric": "co2", "region": "europe", "year": 2022}}], "summary": "CO2 for Europe 2022"}}
```

For trends/time series, use year_start/year_end instead of year.

DERIVED FIELDS:
- Per capita: add "derived": "per_capita" to item
- Density: add "derived": "density" to item
- Custom ratio: use type "derived" with numerator/denominator

RULES:
- source_id: Must EXACTLY match one of the available sources
- metric: Must be an EXACT column name from COLUMNS list (e.g., "co2", "population", "total_pop")
- region: lowercase (europe, g7, africa) or null for global
- year: null = most recent (don't ask unless specified)
- For large sources (10+ metrics): ask before adding all

RESPOND WITH:
- JSON order (for data requests)
- Helpful text (for questions)
- Short clarifying question (if unclear)
"""


def interpret_request(user_query: str, chat_history: list = None, hints: dict = None) -> dict:
    """
    Interpret user request and return structured order or response.

    Args:
        user_query: The user's natural language query
        chat_history: Previous messages for context
        hints: Preprocessor hints (topics, regions, time patterns, reference lookups)

    Returns:
        {"type": "order", "order": {...}, "summary": "..."} or
        {"type": "chat", "message": "..."} or
        {"type": "clarify", "message": "..."}
    """
    catalog = load_catalog()
    conversions = load_conversions()
    system_prompt = build_system_prompt(catalog, conversions)

    # Build messages
    messages = [{"role": "system", "content": system_prompt}]

    if chat_history:
        for msg in chat_history[-4:]:  # Last 4 messages only
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", "")
            })

    # Inject Tier 3/Tier 4 context from preprocessor hints
    if hints:
        context_parts = []

        # Tier 3: Just-in-time context (resolved regions, time patterns)
        if hints.get("summary"):
            context_parts.append(f"[Context: {hints['summary']}]")

        # Add resolved region details
        if hints.get("regions"):
            for region in hints["regions"][:2]:  # Limit to avoid token bloat
                context_parts.append(
                    f"'{region['match']}' resolves to {region['count']} countries"
                )

        # Tier 4: Reference document content
        ref_lookup = hints.get("reference_lookup")
        if ref_lookup:
            ref_type = ref_lookup.get("type")

            # Check for country-specific data first (direct answers)
            if ref_lookup.get("country_data"):
                country_data = ref_lookup["country_data"]
                formatted = country_data.get("formatted", "")
                if formatted:
                    context_parts.append(f"\n[REFERENCE ANSWER: {formatted}]")

            # Fall back to full content for SDG and data source lookups
            elif ref_lookup.get("content"):
                ref_content = ref_lookup["content"]

                if ref_type == "sdg":
                    goal = ref_content.get("goal", {})
                    context_parts.append(
                        f"\n[Reference - SDG {goal.get('number')}]\n"
                        f"Name: {goal.get('name')}\n"
                        f"Full title: {goal.get('full_title')}\n"
                        f"Description: {goal.get('description')}"
                    )
                    if goal.get("targets"):
                        context_parts.append("Targets:")
                        for target in goal["targets"][:3]:
                            context_parts.append(f"  {target['id']}: {target['text']}")

                elif ref_type == "data_source":
                    about = ref_content.get("about", {})
                    context_parts.append(
                        f"\n[Reference - Data Source: {about.get('name', 'Unknown')}]\n"
                        f"Publisher: {about.get('publisher', 'Unknown')}\n"
                        f"URL: {about.get('url', 'N/A')}\n"
                        f"License: {about.get('license', 'Unknown')}"
                    )

                elif ref_type == "capital":
                    capitals = ref_content.get("capitals", {})
                    context_parts.append(f"[Reference: {len(capitals)} country capitals available]")

        # Add context as a system message before user query
        if context_parts:
            messages.append({
                "role": "system",
                "content": "\n".join(context_parts)
            })

    messages.append({"role": "user", "content": user_query})

    # Single LLM call
    client = OpenAI()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.3,
        max_tokens=500
    )

    content = response.choices[0].message.content.strip()

    # Parse response
    return parse_llm_response(content)


def validate_order_item(item: dict) -> dict:
    """
    Validate an order item against actual source metadata.
    Returns item with validation info added.
    """
    source_id = item.get("source_id")
    metric = item.get("metric")
    year = item.get("year")

    if not source_id:
        item["_valid"] = False
        item["_error"] = "Missing source_id"
        return item

    # Load source metadata
    metadata = load_source_metadata(source_id)
    if not metadata:
        item["_valid"] = False
        item["_error"] = f"Unknown source: {source_id}"
        return item

    # Check metric exists
    metrics = metadata.get("metrics", {})
    if metric and metric not in metrics:
        # Try to find close match
        close_matches = [k for k in metrics.keys() if metric.lower() in k.lower() or k.lower() in metric.lower()]
        if close_matches:
            item["_valid"] = False
            item["_error"] = f"Column '{metric}' not found. Did you mean: {', '.join(close_matches[:3])}?"
        else:
            item["_valid"] = False
            item["_error"] = f"Column '{metric}' not found in {source_id}"
        return item

    # Check year is in range
    temp = metadata.get("temporal_coverage", {})
    start_year = temp.get("start")
    end_year = temp.get("end")

    # Handle single year
    if year and start_year and end_year:
        if year < start_year or year > end_year:
            item["_valid"] = False
            item["_error"] = f"Year {year} outside range {start_year}-{end_year}"
            return item

    # Handle year range
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

    # Valid - add metric label if missing
    if metric and not item.get("metric_label"):
        metric_info = metrics.get(metric, {})
        name = metric_info.get("name", metric)
        unit = metric_info.get("unit", "")
        if unit and unit != "unknown":
            item["metric_label"] = f"{name} ({unit})"
        else:
            item["metric_label"] = name

    item["_valid"] = True
    return item


def validate_order(order: dict) -> dict:
    """Validate all items in an order and add validation results."""
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


def parse_llm_response(content: str) -> dict:
    """Parse LLM response into structured result."""

    # Check for JSON block
    if "```json" in content:
        try:
            json_str = content.split("```json")[1].split("```")[0].strip()
            order = json.loads(json_str)
            # Validate the order
            order = validate_order(order)
            return {
                "type": "order",
                "order": order,
                "summary": order.get("summary", "Data request")
            }
        except (json.JSONDecodeError, IndexError):
            pass

    # Check for bare JSON
    if content.startswith("{"):
        try:
            order = json.loads(content)
            # Validate the order
            order = validate_order(order)
            return {
                "type": "order",
                "order": order,
                "summary": order.get("summary", "Data request")
            }
        except json.JSONDecodeError:
            pass

    # Check if it's a clarifying question
    if "?" in content and len(content) < 200:
        return {"type": "clarify", "message": content}

    # Otherwise it's a chat response
    return {"type": "chat", "message": content}
