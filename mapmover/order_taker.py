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

load_dotenv()

DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/data")
CATALOG_PATH = DATA_DIR.parent / "catalog.json"
CONVERSIONS_PATH = Path(__file__).parent / "conversions.json"
REFERENCE_DIR = Path(__file__).parent / "reference"


def load_catalog() -> dict:
    """Load the data catalog."""
    with open(CATALOG_PATH, encoding='utf-8') as f:
        return json.load(f)


def load_source_metadata(source_id: str) -> dict:
    """Load metadata.json for a specific source."""
    meta_path = DATA_DIR / source_id / "metadata.json"
    if meta_path.exists():
        with open(meta_path, encoding='utf-8') as f:
            return json.load(f)
    return {}


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
    """Build system prompt with catalog and conversions context."""

    # Build sources text from catalog with EXACT column names
    sources_text = ""
    usa_only_sources = []
    global_sources = []

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
  Category: {src.get('category', 'general')}
  Coverage: {coverage}
  Years: {temp.get('start', '?')}-{temp.get('end', '?')}
  COLUMNS: {columns_text}
"""
        # Track coverage for notes
        if geo.get("type") == "country" and geo.get("countries") == 1:
            usa_only_sources.append(source_id)
        elif geo.get("type") == "global":
            global_sources.append(f"{source_id} ({geo.get('countries', '?')} countries)")

    # Build regions text from conversions
    regions_text = build_regions_text(conversions)

    # Build coverage notes dynamically
    coverage_notes = []
    if usa_only_sources:
        coverage_notes.append(f"- {', '.join(usa_only_sources)}: USA ONLY (counties, not countries) - do NOT use for other countries")
    if global_sources:
        coverage_notes.append(f"- {', '.join(global_sources)}: Global coverage")
    coverage_notes.append("- When user asks about a region, ONLY suggest sources that cover that region")
    coverage_notes_text = "\n".join(coverage_notes)

    return f"""You are an Order Taker for a map data visualization system.

AVAILABLE DATA SOURCES:
{sources_text}

SUPPORTED REGIONS (use lowercase in orders):
{regions_text}

IMPORTANT COVERAGE NOTES:
{coverage_notes_text}

YOUR JOB:
1. Understand what the user wants to see on a map
2. Return a structured JSON order OR a helpful response
3. If unclear, ask ONE clarifying question (no JSON)

ORDER FORMAT (only when user requests specific data):
```json
{{
  "items": [
    {{
      "source_id": "owid_co2",
      "metric": "co2",
      "metric_label": "Co2 (million tonnes)",
      "region": "europe",
      "year": 2022
    }}
  ],
  "summary": "CO2 emissions for European countries in 2022"
}}
```

YEAR RANGE FORMAT (for time series / trends):
```json
{{
  "items": [
    {{
      "source_id": "owid_co2",
      "metric": "co2",
      "metric_label": "Co2 (million tonnes)",
      "region": "europe",
      "year_start": 2010,
      "year_end": 2022
    }}
  ],
  "summary": "CO2 emissions trend in Europe from 2010 to 2022"
}}
```

CRITICAL RULES:
- source_id: Must EXACTLY match one of the available sources
- metric: Must be an EXACT column name from the COLUMNS list above (e.g., "co2", "capital_account_balance", "life_expectancy")
  - DO NOT make up column names or use descriptive phrases
  - If unsure which column matches user's request, pick the closest match from COLUMNS
  - If no column matches, say "No matching data found" instead of guessing
- metric_label: Human-readable name shown in UI (from COLUMNS list, e.g., "Co2 (million tonnes)")
- region: lowercase region name, or null for global/all
- year: Integer year for SINGLE year queries, or null for most recent (DEFAULT TO NULL if user doesn't specify - DO NOT ask for year)
- year_start/year_end: Use INSTEAD of year when user asks for trends, changes over time, or specifies a range like "from 2010 to 2022"
  - Triggers: "over time", "trend", "from X to Y", "between X and Y", "last N years", "since X"
  - Example: "CO2 trend in Europe" -> use year_start: 2000, year_end: 2023 (or source's available range)
  - Example: "GDP from 2015 to 2020" -> use year_start: 2015, year_end: 2020
- For "top N" requests: add sort to items: {{"by": "co2", "order": "desc", "limit": 10}}
- summary: Plain English description of what will be displayed

COMPREHENSIVE TOPIC REQUESTS:
When user asks about an entire topic, goal, or source (e.g., "show me SDG 7", "all energy data"):
- Small sources (1-5 metrics): Add all metrics automatically, one order item each
- Medium sources (6-10 metrics): Add all metrics, mention the count in summary
- Large sources (10+ metrics): ASK first before adding. Respond with:
  "This source has X metrics. Would you like me to add all of them, or would you prefer I list them so you can choose?"
  - If user confirms "add all" or similar: add all metrics
  - If user wants to see the list: show numbered list of metrics

VALIDATION:
- If user asks for data outside the Years range, inform them of available years
- If user asks for a metric that doesn't exist, list similar available columns
- If user asks for a region not covered by a source, suggest alternative sources

WHEN USER ASKS "what data do you have for X region?":
- Check which sources cover that region (see Coverage field)
- List ONLY the relevant sources with brief descriptions
- Do NOT include census sources for non-US regions
- If there are MORE THAN 5 matching sources, SUMMARIZE instead of listing all:
  - Group by category (e.g., "17 SDG datasets covering poverty, health, education...")
  - Mention the range of years available
  - Suggest the user ask about a specific topic for details

FORMATTING FOR TEXT RESPONSES:
- Use **bold** for source names and headings
- ALWAYS use NUMBERED lists (1. 2. 3.) instead of bullet points - this lets users say "show me #3"
- Put each item on its own line with a blank line between them
- Keep descriptions brief (1-2 sentences each)
- When listing available metrics/data points, show the human-readable NAME not the column code
  - GOOD: "1. Proportion of population below poverty line (%)"
  - BAD: "1. si_pov_day1: Proportion of population below poverty line"
- When a source has many metrics (more than 5-6), state the TOTAL COUNT and show examples:
  - GOOD: "This source has 12 metrics available, including:"
  - Then list 5-6 representative examples
  - This helps users know there are more options to explore
- Example format for sources:

1. **IMF Balance of Payments** (imf_bop)
Trade and financial data, 2005-2022.

2. **OWID CO2 Emissions** (owid_co2)
Emissions, energy, and climate data, 1750-2024.

- Example format for metrics within a source:

1. Proportion of population below international poverty line (%)
2. Proportion of population living below national poverty line (%)
3. Direct economic loss attributed to disasters (USD)

RESPOND WITH ONLY:
- A JSON order block (when user wants specific data displayed)
- OR a helpful text response (when answering questions about available data)
- OR a short clarifying question
"""


def interpret_request(user_query: str, chat_history: list = None) -> dict:
    """
    Interpret user request and return structured order or response.

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
