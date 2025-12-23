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


def load_catalog() -> dict:
    """Load the data catalog."""
    with open(CATALOG_PATH, encoding='utf-8') as f:
        return json.load(f)


def load_conversions() -> dict:
    """Load the conversions/regional groupings."""
    with open(CONVERSIONS_PATH, encoding='utf-8') as f:
        return json.load(f)


def build_regions_text(conversions: dict) -> str:
    """Build regions text dynamically from conversions.json."""
    groupings = conversions.get("regional_groupings", {})
    state_abbrevs = conversions.get("state_abbreviations", {})

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

    # Build sources text from catalog
    sources_text = ""
    usa_only_sources = []
    global_sources = []

    for src in catalog["sources"]:
        geo = src.get("geographic_coverage", {})
        temp = src.get("temporal_coverage", {})
        coverage = src.get("coverage_description", geo.get("type", "unknown"))

        sources_text += f"""
**{src['source_id']}** ({src['source_name']})
  Category: {src.get('category', 'general')}
  Coverage: {coverage}
  Level: {src.get('geographic_level', 'unknown')}
  Years: {temp.get('start', '?')}-{temp.get('end', '?')}
  Keywords: {', '.join(src.get('keywords', []))}
"""
        # Track coverage for notes
        if geo.get("type") == "country" and geo.get("countries") == 1:
            usa_only_sources.append(src['source_id'])
        elif geo.get("type") == "global":
            global_sources.append(f"{src['source_id']} ({geo.get('countries', '?')} countries)")

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
      "metric_label": "CO2 Emissions",
      "region": "europe",
      "year": 2022
    }}
  ],
  "summary": "CO2 emissions for European countries in 2022"
}}
```

RULES:
- source_id: Must match one of the available sources
- metric: Single column name from the dataset
- region: lowercase region name, or null for global/all
- year: Integer year, or null for latest
- For "top N" requests: add sort to items: {{"by": "co2", "order": "desc", "limit": 10}}
- summary: Always include - plain English description

WHEN USER ASKS "what data do you have for X region?":
- Check which sources cover that region (see Coverage field)
- List ONLY the relevant sources with brief descriptions
- Do NOT include census sources for non-US regions

FORMATTING FOR TEXT RESPONSES:
- Use **bold** for source names and headings
- Put each data source on its own line with a blank line between them
- Keep descriptions brief (1-2 sentences each)
- Example format:

**IMF Balance of Payments** (imf_bop)
Trade and financial data, 2005-2022.

**OWID CO2 Emissions** (owid_co2)
Emissions, energy, and climate data, 1750-2024.

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
        max_tokens=300
    )

    content = response.choices[0].message.content.strip()

    # Parse response
    return parse_llm_response(content)


def parse_llm_response(content: str) -> dict:
    """Parse LLM response into structured result."""

    # Check for JSON block
    if "```json" in content:
        try:
            json_str = content.split("```json")[1].split("```")[0].strip()
            order = json.loads(json_str)
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
