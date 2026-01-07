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
from .preprocessor import build_tier3_context, build_tier4_context

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
    Build system prompt with catalog organized by geographic scope.

    Groups sources by scope and combines related sources (UN SDGs, World Factbook).
    """

    # Group sources by scope
    sources_by_scope = {}
    for src in catalog["sources"]:
        scope = src.get("scope", "global")
        if scope not in sources_by_scope:
            sources_by_scope[scope] = []
        sources_by_scope[scope].append(src)

    # Build sources text with grouping of related sources
    sources_text = ""

    def format_source_group(sources, scope_label):
        """Format sources, grouping related ones together."""
        lines = []

        # Separate UN SDGs and World Factbook for grouping
        sdg_sources = [s for s in sources if s['source_id'].startswith('un_sdg_')]
        factbook_sources = [s for s in sources if 'world_factbook' in s['source_id']]
        other_sources = [s for s in sources if s not in sdg_sources and s not in factbook_sources]

        # Add individual sources with human-readable names
        for src in other_sources:
            temp = src.get("temporal_coverage", {})
            name = src.get("source_name", src["source_id"])
            lines.append(f"- {name} ({src['source_id']}): {temp.get('start', '?')}-{temp.get('end', '?')}")

        # Group UN SDGs
        if sdg_sources:
            years = [s.get("temporal_coverage", {}) for s in sdg_sources]
            min_year = min(t.get("start", 9999) or 9999 for t in years)
            max_year = max(t.get("end", 0) or 0 for t in years)
            lines.append(f"- UN Sustainable Development Goals (un_sdg_01 to un_sdg_17): {min_year}-{max_year} [17 goals]")

        # Group World Factbook
        if factbook_sources:
            names = [s['source_id'] for s in factbook_sources]
            lines.append(f"- World Factbook ({', '.join(names)}): country profiles, demographics, infrastructure")

        return "\n".join(lines)

    # Country-specific sources FIRST (more relevant when asking about a country)
    for scope in sorted(sources_by_scope.keys()):
        if scope == "global":
            continue

        scope_sources = sources_by_scope[scope]
        geo_level = scope_sources[0].get("geographic_level", "admin_2") if scope_sources else "admin_2"

        sources_text += f"\n=== {scope.upper()} ONLY ({geo_level}) ===\n"
        sources_text += format_source_group(scope_sources, scope) + "\n"

    # Global sources SECOND
    if "global" in sources_by_scope:
        sources_text += "\n=== GLOBAL (available for all countries at admin_0) ===\n"
        sources_text += format_source_group(sources_by_scope["global"], "global") + "\n"

    # Build regions text from conversions
    regions_text = build_regions_text(conversions)

    return f"""You are an Order Taker for a map data visualization system.

DATA SOURCES:
{sources_text}
IMPORTANT: Country-specific sources can ONLY be used for that country.

REGIONS:
{regions_text}

WHEN USER ASKS "what data for [country]":
1. List that country's specific sources FIRST (if any)
2. Then mention global sources are also available
3. Be CONCISE - use human-readable names, group related sources
4. Don't list every column or every SDG goal individually

ORDER FORMAT (JSON when user requests data):
```json
{{"items": [{{"source_id": "owid_co2", "metric": "co2", "region": "europe", "year": 2022}}], "summary": "CO2 for Europe 2022"}}
```

RULES:
- source_id: Must EXACTLY match one of the available sources
- metric: Must be an EXACT column name from the source
- region: lowercase (europe, g7, australia) or null for global
- year: null = most recent

RESPOND WITH:
- JSON order (for data requests)
- Concise summary (for questions) - 2-5 sentences max
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
    # Uses preprocessor functions that include metric hints injection
    if hints:
        context_parts = []

        # Tier 3: Just-in-time context (includes metric column hints for location/topic)
        tier3_context = build_tier3_context(hints)
        if tier3_context:
            context_parts.append(tier3_context)

        # Tier 4: Reference document content (SDG, data sources, country info)
        tier4_context = build_tier4_context(hints)
        if tier4_context:
            context_parts.append(tier4_context)

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
