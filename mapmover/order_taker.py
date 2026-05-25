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
import os
import re
from datetime import datetime
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv

from .data_loading import load_catalog, load_source_metadata, get_source_path
from .foundation_helpers import load_reference_json
from .preprocessor import build_tier3_context, build_tier4_context
from .constants import CHAT_HISTORY_LLM_LIMIT
from .llm_tools import format_tools_for_provider, execute_tool, format_tool_result_for_llm
from .aggregation_system import validate_aggregation_policy
from .paths import APP_URL, SITE_URL
from .progress_bus import ProgressEvent


# User-facing strings for each explorer tool. Streaming /chat/stream
# emits one of these as a ProgressEvent every time the LLM invokes the
# tool, so the user sees real progress instead of "Understanding your
# intent..." sitting there for several seconds.
EXPLORER_TOOL_PROGRESS_MESSAGES = {
    "get_source_details": "Looking up source details...",
    "get_source_reference": "Reading source documentation...",
    "list_source_metrics": "Listing available metrics...",
    "list_multiple_sources_metrics": "Comparing source metrics...",
    "list_packs": "Listing available packs...",
    "get_pack_details": "Looking up pack details...",
}

load_dotenv()

CONVERSIONS_PATH = Path(__file__).parent / "conversions.json"

def load_conversions() -> dict:
    """Load the conversions/regional groupings."""
    with open(CONVERSIONS_PATH, encoding='utf-8') as f:
        return json.load(f)


def load_usa_admin() -> dict:
    """Load USA admin data from reference/usa_admin.json."""
    data = load_reference_json("usa/usa_admin.json")
    return data if isinstance(data, dict) else {}


def _is_localish_url(url: str) -> bool:
    value = (url or "").strip().lower()
    return (
        not value
        or "localhost" in value
        or "127.0.0.1" in value
        or value.startswith("/")
    )


def _catalog_help_links_text() -> str:
    lines = []
    if not _is_localish_url(SITE_URL):
        lines.append(f"   - Public pack library: {SITE_URL}/packs")
    lines.append(f"   - Runtime settings: {APP_URL}/settings")
    return "\n".join(lines)


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


def get_source_visibility_mode() -> str:
    """
    Order Taker source visibility policy.

    live:
      Only published sources (those with pack_id) are visible/selectable.
    test:
      All sources are visible for QA, but prompt guidance should prefer
      published pack_id sources when multiple candidates overlap.
    """
    configured = os.getenv("ORDER_TAKER_SOURCE_MODE", "").strip().lower()
    if configured in {"live", "test"}:
        selected = configured
    else:
        deployment = os.getenv("DEPLOYMENT", "railway").strip().lower()
        selected = "test" if deployment == "local" else "live"
    runtime_mode = os.getenv("RUNTIME_MODE", "").strip().lower()
    install_mode = os.getenv("INSTALL_MODE", "").strip().lower()
    if selected == "test" and (runtime_mode == "cloud" or install_mode == "cloud"):
        raise RuntimeError(
            "ORDER_TAKER_SOURCE_MODE=test is not allowed in cloud/hosted runtime"
        )
    return selected


def build_system_prompt(catalog: dict, conversions: dict) -> str:
    """
    Build system prompt with catalog organized by geographic scope.

    Groups sources by scope and combines related sources (UN SDGs, World Factbook).
    Multi-scope packs (sources spanning different geographic scopes within the same pack)
    are shown as a single consolidated pack entry so the LLM emits pack_id, not source_id.
    The executor resolves pack_id + region -> correct source_id at runtime.
    """

    source_visibility_mode = get_source_visibility_mode()
    all_sources = catalog["sources"]
    published_sources = [src for src in all_sources if src.get("pack_id")]
    visible_sources = published_sources if source_visibility_mode == "live" else all_sources

    # Identify multi-scope packs: packs where sources span more than just "global" scope.
    # These are shown as a single consolidated entry; the LLM emits pack_id + region.
    # Single-scope packs (all global, like SDGs/Factbook) keep individual source_id entries.
    pack_sources_map = {}  # pack_id -> list of catalog source entries
    for src in visible_sources:
        pid = src.get("pack_id")
        if pid:
            pack_sources_map.setdefault(pid, []).append(src)

    multi_scope_pack_ids = set()  # packs that need consolidated display
    for pid, srcs in pack_sources_map.items():
        scopes = {s.get("scope", "global") for s in srcs}
        if scopes - {"global"}:  # has at least one non-global scope
            multi_scope_pack_ids.add(pid)

    # Sources belonging to multi-scope packs are excluded from individual scope sections
    multi_scope_excluded = {id(s) for s in visible_sources if s.get("pack_id") in multi_scope_pack_ids}

    # Group remaining sources by scope for individual display
    sources_by_scope = {}
    chat_first_sources = []
    hybrid_sources = []
    for src in visible_sources:
        if id(src) in multi_scope_excluded:
            continue
        scope = src.get("scope", "global")
        if scope not in sources_by_scope:
            sources_by_scope[scope] = []
        sources_by_scope[scope].append(src)

        interaction_mode = src.get("interaction_mode", "order_first")
        if interaction_mode == "chat_first":
            chat_first_sources.append(src.get("source_id"))
        elif interaction_mode == "hybrid":
            hybrid_sources.append(src.get("source_id"))

    published_pack_text = ", ".join(sorted({src.get("pack_id") for src in published_sources if src.get("pack_id")})) or "(none)"

    def _year(dt_str):
        """Extract a 4-digit year string from mixed int / float / ISO-like inputs."""
        if dt_str is None or dt_str == "":
            return "?"
        if isinstance(dt_str, bool):
            return "?"
        if isinstance(dt_str, int):
            return str(dt_str)
        if isinstance(dt_str, float):
            return str(int(dt_str))
        text = str(dt_str).strip()
        return text[:4] if len(text) >= 4 else text or "?"

    def _year_int(value):
        """Coerce temporal coverage values into comparable year ints when possible."""
        text = _year(value)
        return int(text) if text.isdigit() else None

    def _shape_note(shape_value):
        shape = str(shape_value or "").strip().lower()
        if shape == "geometry_shape":
            return "county/tract/admin geometry choropleth with geometry-region popups"
        if shape == "event_shape":
            return "event/perimeter overlay with disaster/event popups"
        if shape == "location_shape":
            return "point-location map with place/facility popups"
        if shape == "building_shape":
            return "building footprint geometry with building popups"
        return ""

    def format_multi_scope_pack(pid, srcs):
        """
        Build a single catalog line for a multi-scope pack.
        Example:
          - Wildfires [pack_id: wildfires]: Wildfire events - burned area, date, location
            Coverage: Global (via Global Fire Atlas), Canada (CNFDB, 1930-2024), USA (NIFC/IRWIN, 1984-2024)
            Time range: 1930-2024
        """
        # Use the global source as the representative name, fall back to first source
        global_src = next((s for s in srcs if s.get("scope") == "global"), srcs[0])
        pack_name = global_src.get("source_name", pid)

        # Build per-source coverage labels
        coverage_parts = []
        scope_order = {"global": 0, "CAN": 1, "USA": 2}
        sorted_srcs = sorted(srcs, key=lambda s: scope_order.get(s.get("scope", "global"), 99))
        for src in sorted_srcs:
            scope = src.get("scope", "global")
            sname = src.get("source_name", "")
            temp = src.get("temporal_coverage", {})
            yr_s = _year(temp.get("start"))
            yr_e = _year(temp.get("end"))
            if scope == "global":
                coverage_parts.append(f"Global (via {sname})")
            else:
                coverage_parts.append(f"{scope} ({sname}, {yr_s}-{yr_e})")

        # Overall time range
        all_starts = [
            year for year in (
                _year_int(src.get("temporal_coverage", {}).get("start"))
                for src in srcs
            )
            if year is not None
        ]
        all_ends = [
            year for year in (
                _year_int(src.get("temporal_coverage", {}).get("end"))
                for src in srcs
            )
            if year is not None
        ]
        time_range = f"{min(all_starts)}-{max(all_ends)}" if all_starts and all_ends else "?"

        shape_notes = []
        for src in sorted_srcs:
            shape_note = _shape_note(src.get("geojson_shape"))
            if not shape_note:
                continue
            scope = src.get("scope", "global")
            sname = src.get("source_name", src.get("source_id", "?"))
            shape_notes.append(f"{scope}: {sname} -> {shape_note}")

        # Admin area coverage (from event_areas join)
        total_admin2 = sum(
            src.get("affected_coverage", {}).get("admin2_regions_affected", 0) or 0
            for src in srcs
        )

        coverage_str = ", ".join(coverage_parts)
        lines = [
            f"- {pack_name} [pack_id: {pid}]",
            f"  Coverage: {coverage_str}",
            f"  Time range: {time_range}",
        ]
        if total_admin2 > 0:
            lines.append(f"  Admin regions: {total_admin2:,} counties/districts covered (event_areas join available)")
        if shape_notes:
            lines.append(f"  Map shape behavior: {'; '.join(shape_notes)}")
        return "\n".join(lines)

    def format_source_group(sources, scope_label):
        """Format sources, grouping related ones together."""
        lines = []

        # Separate SDGs and Factbook for grouping - detect by topic_tags, not hardcoded source_id
        sdg_sources = [s for s in sources if any(tag.startswith('goal') for tag in s.get('topic_tags', []))]
        factbook_sources = [s for s in sources if 'factbook' in s.get('category', '').lower() or
                           any('factbook' in tag.lower() for tag in s.get('topic_tags', []))]
        other_sources = [s for s in sources if s.get('source_id') and s not in sdg_sources and s not in factbook_sources]

        # Add individual sources with human-readable names AND source_id
        for src in other_sources:
            temp = src.get("temporal_coverage", {})
            name = src.get("source_name", src["source_id"])
            sid = src["source_id"]
            pid = src.get("pack_id")
            publish_note = f"pack_id: {pid}" if pid else "pre-release: no pack_id yet"
            geo_level = src.get("geographic_level", "")
            geo_level_str = "/".join(geo_level) if isinstance(geo_level, list) else geo_level
            geo_note = f"; {geo_level_str}" if geo_level_str and geo_level_str not in ("country", "admin_0") else ""
            shape_note = _shape_note(src.get("geojson_shape"))
            shape_suffix = f"; map shape: {shape_note}" if shape_note else ""
            lines.append(f"- {name} [{publish_note}; source_id: {sid}{geo_note}{shape_suffix}]: {temp.get('start', '?')}-{temp.get('end', '?')}")

        # List SDG sources individually with human-readable goal titles
        if sdg_sources:
            # Sort by goal number extracted from topic_tags
            def get_goal_num(src):
                for tag in src.get('topic_tags', []):
                    if tag.startswith('goal'):
                        try:
                            return int(tag[4:])
                        except ValueError:
                            pass
                return 999
            sdg_sources_sorted = sorted(sdg_sources, key=get_goal_num)

            for src in sdg_sources_sorted:
                sid = src.get('source_id', '')
                temp = src.get("temporal_coverage", {})
                year_range = f"{temp.get('start', '?')}-{temp.get('end', '?')}"

                # Get goal title from catalog reference data or source_name
                goal_title = None
                reference = src.get("reference", {})
                if reference.get("goal"):
                    goal_info = reference["goal"]
                    goal_num = goal_info.get("number", "")
                    goal_name = goal_info.get("name", "")
                    if goal_num and goal_name:
                        goal_title = f"SDG {goal_num}: {goal_name}"

                # Fallback to source_name
                if not goal_title:
                    goal_title = src.get("source_name", sid)

                publish_note = f"pack_id: {src.get('pack_id')}" if src.get("pack_id") else "pre-release: no pack_id yet"
                lines.append(f"- {goal_title} [{publish_note}; source_id: {sid}]: {year_range}")

        # Group World Factbook
        if factbook_sources:
            by_id = {s["source_id"]: s for s in factbook_sources}
            merged = by_id.get("factbook_merged")
            unique = by_id.get("world_factbook")
            static = by_id.get("world_factbook_static")

            if merged:
                pid = merged.get("pack_id")
                publish_note = f"pack_id: {pid}" if pid else "pre-release: no pack_id yet"
                lines.append(
                    f"- CIA World Factbook Merged Temporal [{publish_note}; source_id: factbook_merged]: "
                    f"yearly country metrics such as internet users, military expenditure (% of GDP), railways (km), airports, electricity consumption, life expectancy, GDP purchasing power parity, GDP per capita PPP, birth rate, death rate, and population"
                )
            if unique:
                pid = unique.get("pack_id")
                publish_note = f"pack_id: {pid}" if pid else "pre-release: no pack_id yet"
                lines.append(
                    f"- CIA World Factbook [{publish_note}; source_id: world_factbook]: "
                    f"yearly country metrics such as internet users, military expenditure (% of GDP), railways (km), airports, electricity consumption, life expectancy, GDP purchasing power parity, GDP per capita PPP, birth rate, death rate, and population"
                )
            if static:
                pid = static.get("pack_id")
                publish_note = f"pack_id: {pid}" if pid else "pre-release: no pack_id yet"
                lines.append(
                    f"- CIA World Factbook Static Geography [{publish_note}; source_id: world_factbook_static]: "
                    f"country-level static numeric fields such as total area, coastline length, highest point elevation, mean elevation, border count, capital coordinates"
                )

        return "\n".join(lines)

    # Build sources_text
    sources_text = ""

    # Country-specific individual sources FIRST
    for scope in sorted(sources_by_scope.keys()):
        if scope == "global":
            continue
        scope_sources = sources_by_scope[scope]
        geo_level_raw = scope_sources[0].get("geographic_level", "admin_2") if scope_sources else "admin_2"
        geo_level = "/".join(geo_level_raw) if isinstance(geo_level_raw, list) else geo_level_raw
        sources_text += f"\n=== {scope.upper()} ONLY ({geo_level}) ===\n"
        sources_text += format_source_group(scope_sources, scope) + "\n"

    # Global section: individual global sources + consolidated multi-scope pack entries
    global_individual = format_source_group(sources_by_scope.get("global", []), "global")
    multi_scope_entries = "\n".join(
        format_multi_scope_pack(pid, pack_sources_map[pid])
        for pid in sorted(multi_scope_pack_ids)
    )
    global_section_content = "\n".join(filter(None, [global_individual, multi_scope_entries]))
    if global_section_content:
        sources_text += "\n=== GLOBAL (worldwide coverage, geographic level varies by source) ===\n"
        sources_text += global_section_content + "\n"

    # Build regions text from conversions
    regions_text = build_regions_text(conversions)
    unpublished_visibility_note = (
        'Sources marked "pre-release: no pack_id yet" may still exist for internal QA and direct map requests, '
        'but they are not public library items yet.'
        if source_visibility_mode == "test"
        else "In live mode, unpublished sources with no pack_id are invisible and must never be selected."
    )
    chat_first_text = ", ".join(sorted(chat_first_sources)) if chat_first_sources else "(none)"
    hybrid_text = ", ".join(sorted(hybrid_sources)) if hybrid_sources else "(none)"
    catalog_help_links_text = _catalog_help_links_text()

    return f"""You are an Order Taker for a map data visualization system.

FORMATTING: Never use emojis or special unicode characters in responses. Use plain text only with standard punctuation. Use bullet points (- or *) for lists.

DATA HIERARCHY (what you know vs. what you can fetch):
- CATALOG (below): Summary of all sources with names and year ranges - you always have this
- METADATA: Detailed metrics, statistics, coverage - use get_source_details or list_source_metrics tool
- REFERENCE: Background, methodology, context - use get_source_reference tool

When user asks about metrics for a SPECIFIC source, use the list_source_metrics tool to get accurate info.
When user asks about MULTIPLE sources generally (e.g., "what SDG data"), offer to show details for specific ones.
When user asks what packs are available, use the list_packs tool.
When user asks what is inside a pack or whether a full-pack load is safe, use the get_pack_details tool before deciding.
Example: "I have 17 SDG goals available. Which would you like to explore, or should I pick a few to highlight?"

DATA SOURCES:
{sources_text}
IMPORTANT: Country-specific sources can ONLY be used for that country.
Published pack_ids currently in the public library: {published_pack_text}
Order Taker source visibility mode: {source_visibility_mode}
Only sources with a pack_id are published and should be described to users in general catalog/library answers.
{unpublished_visibility_note}
Any source or pack shown with `[pack_id: X]` is live/queryable in the public system. Never describe it as pre-release, unpublished, or unavailable.
If a user asks to show/map/query data from a published pack, return a real order or a tight metric/time clarification. Do not claim the pack is inaccessible when it is listed with a pack_id.

REGIONS:
{regions_text}

WHEN USER ASKS "what data for [country]" or "what do you have":
1. List that country's specific sources FIRST (if any)
2. Then mention global sources are also available
3. Only mention published packs/sources with a pack_id
4. Be CONCISE - use human-readable names, group related sources
5. End with:
{catalog_help_links_text}

PACK LIBRARY RULES:
- Treat packs as the main user-facing library units when the user asks broadly about available data.
- Use list_packs for "what packs do you have", "list the packs", or similar library questions.
- Use get_pack_details for "what's inside this pack?", "how big is this pack?", or before any request to load the full pack.
- If the user asks to load an entire pack and get_pack_details says full-pack load is safe, return a real order using `load_scope: "pack"`.
- If the user asks to load an entire pack and get_pack_details says it is not safe, return type="clarify" with the size reason and ask them to narrow it by source, geography level, metric, or time range.
- Never silently expand a large pack in chat. Call out the size/risk first.

FACTBOOK-SPECIFIC RULES:
- The World Factbook sources are all country-level (admin_0), similar to SDG country choropleths.
- If the user explicitly asks to show/map/rank a numeric Factbook metric, prefer type="order", even if the source is pre-release.
- Use world_factbook for World Factbook temporal requests. It combines the old world_factbook and world_factbook_overlap temporal metrics, including internet users, military expenditure, railways, airports, electricity consumption, life expectancy, GDP purchasing power parity, GDP per capita, birth rate, death rate, and population.
- For world_factbook_static numeric fields (highest_point_m, mean_elevation_m, coastline_km, area_total_sq_km, border_countries_count), prefer a map order rather than a chat explanation.
- Use world_factbook_static for static geography metrics like highest peaks, coastline length, mean elevation, and total area.
- Reserve chat/reference behavior for text-heavy static fields like climate, terrain, natural_resources, or named peak/capital descriptions.

DISASTER AGGREGATE RULES:
- Disaster event packs (wildfires, earthquakes, etc.) store event-level data. Always use mode="events" in the order item UNLESS you are explicitly using a rolling-window aggregate source (e.g., "highest exposure over 20 years"). Mode="events" works for: specific year queries, trend queries, ranking by region, "which had most", and "how has it changed" questions.
- Do NOT omit mode="events" for wildfire/disaster queries — omitting it routes to the choropleth path which requires pre-aggregated region files and will return 0 results for year-specific or trend queries.
- For "which counties/regions/areas were affected by [disaster]" questions, always prefer type="order" using mode="events" for that region — do not respond with chat explaining limitations. Show the events on the map and let the user explore which areas are covered.
- Disaster packs with "Admin regions: X counties/districts covered" in the catalog have county-level data available via event_areas join. The executor handles the join automatically — never tell users that county-level data is unavailable for these packs.
- Use existing disaster sources only. Never ask the user if they have another dataset/source, and never suggest unpublished or imaginary alternatives.
- If the user asks about US counties or Texas counties, assume the existing disaster aggregate data can be used when available instead of claiming only country-level support.
- Multi-hazard risk questions may be answered with a multi-item order using the available aggregate metrics; do not over-clarify unless execution is genuinely impossible.
- Named storm or event queries ("show me Hurricane Katrina", "show me Typhoon Haiyan's track", "show me wind data for [storm]") must use type="order" with mode="events", never overlay_toggle. The IBTrACS hurricanes pack contains individual track-point data for all named storms.
- "Typhoons" and "cyclones" are the same as hurricanes in the IBTrACS pack — use pack_id="hurricanes" for all tropical cyclone queries regardless of regional name.
- If the user asks a cross-pack exposure or comparison question that can be
  shown as multiple layers on the same geography, return a real multi-item
  type="order" instead of stopping at chat. This includes questions combining:
  - disaster exposure or event frequency with population
  - disaster exposure or event frequency with economic context
  - disaster exposure or event frequency with NRI/FEMA risk layers
- When no single precomputed fused metric exists, still prefer a multi-item
  order with one item per compatible layer, using the same region and time
  window where possible. Do not reply with "I could show these as separate
  layers" — actually return the layered order.


DISASTER ROUTING CORRECTION:
- When disaster guidance conflicts, follow map-shape and subject semantics first.
- If the user is asking for counties, tracts, districts, states, provinces, countries, rankings, or affected regions, prefer geometry_shape or aggregate routing when available in the pack.
- If the user is asking for individual incidents, named events, perimeters, tracks, or actual fires/storms/earthquakes on the map, prefer event_shape routing with mode="events".
- Do not use raw event overlays to satisfy county rankings when the pack has a geometry_shape regional source.
- Do not use aggregate region layers to satisfy "biggest fires", named-event, perimeter, or incident-overlay requests when the pack has an event_shape source.

WHEN USER ASKS about a specific source ("what's in X?" or "show me metrics"):
- Use the list_source_metrics tool to get the actual metrics
- List the available metrics using ONLY the human-readable names (never show column names)
- If there are 10 or fewer metrics, list them all
- If there are more than 10, say "There are X metrics available, here are the key ones:" and show 5-8
- Mention the year range available
- Say "I can get them all" or "I can show any of these" (never mention "*" or wildcards to the user)
- If the user then replies with "all", "all of them", or equivalent for that detected source, return type="order" using that source with `metric: "*"` instead of another chat/clarify reply.

INTERACTION POLICY:
- Default for all sources: order_first.
- If a source has interaction_mode="chat_first", prefer conversational/reference response unless user explicitly asks to map/query metrics.
- If a source has interaction_mode="hybrid", use judgment between chat and order.
- For source-backed analytical questions, prefer returning type="order" over type="chat".
- For cross-pack analytical questions where the compatible layers share the
  same loc_id geography, prefer a multi-item type="order" over a chat
  explanation. Use chat only when the geography, time basis, or metrics are
  genuinely incompatible.
- For published geographic packs, "show me/map/display [place] [topic]" should default to a real order, not a catalog-status explanation.
- If the user broadly asks to show/map/display a specific source or pack's "data" without naming a metric, prefer a real order using `metric: "*"` over a metric-list clarification, unless metadata explicitly requires choosing one metric first.
- Respect `map shape` in the catalog. `geometry_shape` means region geometry like counties/tracts with geometry-region popups. `event_shape` means incident/perimeter/event overlays with disaster/event popups. `location_shape` means point locations or facilities that should usually be shown directly on the map.
- For county/tract/state/province ranking requests ("top counties", "highest counties on the map"), prefer `geometry_shape` sources. Do not satisfy region choropleths with `event_shape` sources.
- For `location_shape` sources, "show/find/map/list/count [locations/facilities/sites] in [place]" should default to a real order instead of chat. Use `location_shape` for point registries, facilities, workshops, labs, and nearest-site style questions.
- For `location_shape` sources, it is valid to omit `metric` entirely when the user is asking to display or filter matching locations. Use `region` plus `filters` for facility type, website presence, source, or public/private distinctions.
- When a user combines regional rankings with event-derived metrics, prefer an aggregate regional source if one exists in the same pack. Use direct event sources only when the user is asking for incidents, perimeters, tracks, or individual events on the map.
- For mixed packs that expose both event and aggregate siblings, a plain place/time incident request still belongs on the event lane even when it mentions a long window like "since 2000" or "in the last 10 years". A time window alone does not make the request aggregate.
- If the user asks "how many", "most", "highest count", "frequency", "share", or "rank", prefer a count/frequency/share metric or an aggregate regional source when available. Do not choose unrelated numeric metrics like duration just because they are present.
- If the user uses severity adjectives like "significant", "major", or "severe", prefer the event lane unless they clearly asked for a regional count/ranking/trend. Only rely on metadata/reference-backed thresholds for those adjectives; do not invent ad hoc cutoffs.
- For static analytical geography sources like CEJST, count/share/rank/filter questions are still valid order requests. Do not switch to chat just because the source is tract-level, classification-oriented, or non-temporal.
- If the user names a published geographic pack/topic but not an exact metric, choose the best-fit metric from the source's keywords/names and use the latest available year unless the user asked for a specific year or comparison.
- If the user asks broadly for a published source's "data" and then says "all", prefer a real order for all metrics rather than re-describing availability or publication state.
- Do not say you cannot retrieve metrics for a published pack just because the user asked broadly. Either return an order or ask one tight clarification about metric/time if genuinely needed.
- When source metadata or reference material provides routing guidance, follow it. In particular:
  - prefer an order for single-metric analytical sources when metadata marks them as order-first analytics
  - prefer clarify for broad multi-metric topics when metadata says a metric choice is required
  - for unsupported-metric requests, use metadata-supported metrics and geography in the clarify message instead of guessing
- chat_first sources: {chat_first_text}
- hybrid sources: {hybrid_text}

ORDER FORMAT (JSON when user requests data):

For sources shown with [pack_id: X] AND a Coverage line (geographic packs), use pack_id in the order.
Event packs (wildfires, earthquakes, etc.) REQUIRE mode="events":
```json
{{"items": [{{"pack_id": "wildfires", "metric": "area_km2", "region": "canada-bc", "mode": "events"}}], "summary": "Wildfires in BC"}}
```
The system routes to the correct regional source automatically based on region.
Only include mode="events" when the user is asking for the actual incidents or event overlays. For county or region rankings, omit event mode and prefer the pack's geometry_shape or aggregate source.

For sources shown with [source_id: X] (individual sources, SDGs, Factbook, pre-release), use source_id:
```json
{{"items": [{{"source_id": "owid_co2", "metric": "co2", "region": "europe", "year": 2022}}], "summary": "CO2 for Europe 2022"}}
```

OPTIONAL AGGREGATION FIELDS (only when user explicitly asks):
- `time_granularity`: `daily | weekly | monthly | yearly`
- `aggregation`: `period_end | period_avg` (FX default is period_end if omitted)
- `date_start` / `date_end`: ISO date bounds for time filtering when needed
- `geo_level`: `admin_0 | admin_1 | admin_2 | admin_3 | admin_4 | admin_5` when the user explicitly asks for a geographic granularity such as `NUTS3`, `department`, `arrondissement`, `commune`, `county`, `tract`, etc.

RULES:
- pack_id: Use for geographic packs (shown with Coverage line in catalog). System selects the right regional source.
- source_id: Use for individual sources that are listed by source_id in the catalog (for example SDGs, Factbook, or internal/pre-release sources).
- metric: Must be an EXACT column name from the source, OR use "*" for ALL metrics from that source. Exception: `location_shape` point-registry orders may omit metric when the goal is to show/filter matching locations.
- region: lowercase (europe, g7, australia, canada-bc, usa-ca) or null for global
- year: null = most recent
- geo_level: include only when the user explicitly asks for a geography level or named layer; map local names to the canonical runtime level when possible
- Only include aggregation fields when the user asks for a specific time granularity or averaging behavior

Examples:
- "France population by NUTS3 region" -> use `source_id: "eurostat"` and `geo_level: "admin_3"`
- "France population by department" -> use `source_id: "eurostat"` and `geo_level: "admin_3"`
- "France population by commune" -> if a served France-specific deep layer exists, use its canonical `geo_level`; otherwise clarify instead of inventing a fake mapping

WILDCARD METRICS (internal - never mention "*" to users):
Use "metric": "*" when user asks for "all data", "everything", or "all metrics" from a source.
Example: {{"source_id": "abs_population", "metric": "*", "region": "australia"}}
This will be expanded to include ALL metrics from that source.
In your response, say "I'll get all the metrics" - never show the "*" symbol to users.

FULL PACK LOADS (internal - check size first):
Use `load_scope: "pack"` when the user explicitly wants the whole pack loaded across all sources in that pack.
Example: {{"pack_id": "fairfax_climate", "load_scope": "pack", "region": "usa-va-fairfax"}}
Before doing this, use get_pack_details and only return the order if `load_policy.can_load_all_sources` is true.
Do not combine `load_scope: "pack"` with a concrete `source_id`.

RESPONSE TYPES (return JSON with "type" field):

1. DATA ORDER - User wants to see data on the map:
```json
{{"type": "order", "items": [{{"pack_id": "wildfires", "metric": "area_km2", "region": "canada-bc"}}], "summary": "..."}}
```

1a. LAYERED DATA ORDER - User wants multiple compatible layers together:
```json
{{"type": "order", "items": [
  {{"pack_id": "wildfires", "metric": "event_count", "region": "usa-ca", "year_start": 2004, "year_end": 2024}},
  {{"pack_id": "worldpop", "metric": "population", "region": "usa-ca", "year": 2024}}
], "summary": "Wildfire exposure and population in California"}}
```
Use this pattern for side-by-side disaster + population/economics/risk
questions when the layers can share region/time framing, even if there is not a
single fused metric yet.

2. GEOMETRY ORDER - User wants to see boundary overlays (ZIP codes, tribal areas, watersheds, etc.):
```json
{{"type": "order", "items": [{{"source_id": "geometry_xxx", "region": "USA-CA", "overlay_type": "xxx"}}], "summary": "..."}}
```
Geometry sources are in the catalog with category="geography" and data_type containing "geometry".
Match the user's request to the appropriate source_id from the catalog based on source_name/description.
The overlay_type is derived from the source_id (e.g., geometry_zcta -> overlay_type="zcta", geometry_tribal -> overlay_type="tribal").

Examples:
- "show me ZIP codes in California": find the ZCTA source in catalog, use its source_id
- "show me tribal areas in Arizona": find the tribal/reservation source in catalog, use its source_id
- For "remove California": use action="remove" at order level
- For mixed "remove Texas, add California": use item-level action for each item

3. NAVIGATION - User wants to zoom/navigate to a location:
```json
{{"type": "navigate", "locations": [{{"loc_id": "USA-CA", "name": "California"}}], "message": "Zooming to California"}}
```

4. DISAMBIGUATION - Multiple locations match, need user to pick:
```json
{{"type": "disambiguate", "message": "Which Washington did you mean?", "options": [{{"loc_id": "USA-WA", "name": "Washington State"}}, {{"loc_id": "USA-DC", "name": "Washington DC"}}]}}
```

5. FILTER UPDATE - User wants to change disaster overlay filters:
```json
{{"type": "filter_update", "overlay": "earthquakes", "filters": {{"minMagnitude": 5.0}}, "message": "Filtering to magnitude 5+"}}
```

6. OVERLAY TOGGLE - User wants to enable/disable a disaster overlay:
```json
{{"type": "overlay_toggle", "overlay": "earthquakes", "enabled": true, "message": "Enabling earthquakes overlay"}}
```
Overlays: earthquakes, hurricanes, volcanoes, tsunamis, tornadoes, wildfires, floods

7. CHAT - General response, information, or clarifying question:
```json
{{"type": "chat", "message": "..."}}
```

INTERPRETATION RULES:
- Check [INTERPRETATION CANDIDATES] section for possible intents with confidence scores
- If "data_request" has highest confidence, return type "order"
- If "navigation" has highest confidence AND no data keywords, return type "navigate"
- If location is marked [LIKELY FALSE POSITIVE], ignore that location match
- If query mentions a data source by name, it's almost certainly a data request, NOT navigation
- "show me data from X" = data request, NOT navigation to a place called "data"
- When multiple sources could satisfy the same metric/request, prefer a published source with a pack_id over a pre-release source with no pack_id
- If the user explicitly names a source or pack, honor that source/pack even if another published source could also answer
- Do not mention source_id to users unless necessary for internal QA; prefer pack/source display names in explanations
- In live mode, never select a source that has no pack_id

INCREMENTAL ORDERS (IMPORTANT):
- Orders describe ONLY what's changing, not the total map state
- The system automatically maintains loaded data - users don't need to repeat previous items
- "add Alaska" = only include Alaska in the order items, NOT previously loaded regions
- "remove Iowa" = only include Iowa with action="remove"
- NEVER include items from previous orders unless the user explicitly asks for them again
- If user says "add X and remove Y", the order should have exactly 2 items: X (add) and Y (remove)

CLARIFYING QUESTIONS - BE SPECIFIC:
- "Which metric?" if they didn't specify what data
- "Which location/country?" if no region specified
- "Which time period/year?" if time is ambiguous
- Example: "Which metric would you like? Population, GDP, births, or I can get them all?"
- NEVER show internal column names (like co2_per_capita) - always use human-readable names only
"""


def interpret_request(
    user_query: str,
    chat_history: list = None,
    hints: dict = None,
    progress=None,
    usage_recorder=None,
) -> dict:
    """
    Interpret user request and return structured order or response.

    Args:
        user_query: The user's natural language query
        chat_history: Previous messages for context
        hints: Preprocessor hints (topics, regions, time patterns, reference lookups)
        progress: Optional callable invoked before each tool call so a streaming
            caller can show real progress. Pass `bus.thread_emitter()` from a
            ProgressBus when calling via asyncio.to_thread; pass None (default)
            for the non-streaming /chat endpoint, where progress reporting is
            not consumed anyway.

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

    # Inject Tier 3/Tier 4 context BEFORE chat history
    # This ensures current location/metric context takes priority over old conversations
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

        # Add context as a system message BEFORE chat history
        # This makes current context more prominent than historical messages
        if context_parts:
            messages.append({
                "role": "system",
                "content": "[CURRENT CONTEXT - USE THIS FOR THE CURRENT QUERY]\n" + "\n".join(context_parts)
            })

    if chat_history:
        for msg in chat_history[-CHAT_HISTORY_LLM_LIMIT:]:
            content = msg.get("content", "")
            # Skip messages with empty content (API rejects them)
            if not content or not content.strip():
                continue
            messages.append({
                "role": msg.get("role", "user"),
                "content": content
            })

    messages.append({"role": "user", "content": user_query})

    # LLM call with tool support
    client = Anthropic()

    # Extract system prompt from messages (Anthropic handles it separately)
    system_content = ""
    chat_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system_content += msg["content"] + "\n\n"
        else:
            chat_messages.append(msg)

    # Get tools in Anthropic format
    tools = format_tools_for_provider("anthropic")

    # Tool use loop - allow up to 3 tool calls per request
    max_tool_iterations = 3
    # Cache the system prompt (full catalog + instructions). Stable across all
    # iterations of this query AND across other calls within the 5-minute TTL,
    # so a stream of orders from the same user benefits from cache reads.
    system_blocks = [{
        "type": "text",
        "text": system_content.strip(),
        "cache_control": {"type": "ephemeral"},
    }]
    # Guarantee a recorder so in-process callers (QA suites, ops/agent paths)
    # still log llm_usage_events rows even when no recorder was passed in.
    from .llm_usage import ensure_recorder
    usage_recorder, _owns_recorder = ensure_recorder(
        usage_recorder, surface="explorer", call_kind="order_taker",
    )
    try:
        for iteration in range(max_tool_iterations + 1):
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                system=system_blocks,
                messages=chat_messages,
                tools=tools,
                temperature=0.0,
                max_tokens=500
            )
            if usage_recorder is not None:
                usage_recorder.record(response)

            # Check if LLM wants to use a tool
            if response.stop_reason == "tool_use":
                # Find tool use block(s) in response
                tool_results = []
                assistant_content = []

                for block in response.content:
                    if block.type == "tool_use":
                        # Execute the tool
                        tool_name = block.name
                        tool_input = block.input
                        if progress is not None:
                            friendly = EXPLORER_TOOL_PROGRESS_MESSAGES.get(
                                tool_name,
                                f"Running {tool_name}...",
                            )
                            progress(ProgressEvent(
                                stage="tool",
                                message=friendly,
                                extra={"tool": tool_name, "iteration": iteration},
                            ))
                        result = execute_tool(tool_name, tool_input)

                        # Format result for context
                        formatted_result = format_tool_result_for_llm(result)

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": formatted_result
                        })
                        assistant_content.append(block)
                    elif block.type == "text":
                        assistant_content.append(block)

                # Add assistant message with tool calls
                chat_messages.append({
                    "role": "assistant",
                    "content": assistant_content
                })

                # Add tool results
                chat_messages.append({
                    "role": "user",
                    "content": tool_results
                })

                # Continue loop for next LLM response
                continue

            # No tool use - we have the final response
            break

        # Extract final text response
        content = ""
        for block in response.content:
            if hasattr(block, 'text'):
                content += block.text

        content = content.strip()

        # Parse response
        return parse_llm_response(content, hints=hints, user_query=user_query)
    finally:
        if _owns_recorder:
            usage_recorder.flush(skip_if_empty=True)


def validate_order_item(item: dict) -> dict:
    """
    Validate an order item against actual source metadata.
    Returns item with validation info added.
    """
    _normalize_item_year_fields(item)
    load_scope = str(item.get("load_scope") or "").strip().lower()
    if item.get("pack_id") and (load_scope in {"pack", "all_sources", "full_pack"} or item.get("all_sources") is True):
        item["_valid"] = True
        return item
    source_id = item.get("source_id")
    metric = item.get("metric")
    year = item.get("year")

    if not source_id:
        if item.get("pack_id"):
            source_id = _resolve_source_for_validation(item)
            if source_id:
                item["source_id"] = source_id
                item["_resolved_from_pack"] = True
            else:
                item["_valid"] = False
                item["_error"] = f"Unable to resolve pack_id '{item.get('pack_id')}' to a source"
                return item
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
    if get_source_visibility_mode() == "live" and not metadata.get("pack_id"):
        item["_valid"] = False
        item["_error"] = f"Source '{source_id}' is not published in live mode"
        return item

    # Check metric exists
    metrics = metadata.get("metrics", {})
    # Skip wildcard metrics - they'll be expanded or handled by the postprocessor
    if metric in ("*", "all", "all_metrics"):
        item["_valid"] = True
        return item
    if metric and metric not in metrics:
        resolved_metric, close_matches = _resolve_metric_for_validation(metric, metrics)
        if resolved_metric:
            # Auto-correct to the actual metric key
            item["metric"] = resolved_metric
            metric = resolved_metric
        else:
            # No exact match - suggest close matches by key or display name
            if close_matches:
                item["_valid"] = False
                item["_error"] = f"Column '{metric}' not found. Did you mean: {', '.join(close_matches[:3])}?"
            else:
                item["_valid"] = False
                item["_error"] = f"Column '{metric}' not found in {source_id}"
            return item

    # Check year is in range
    temp = metadata.get("temporal_coverage", {})
    start_year = _coerce_year(temp.get("start"))
    end_year = _coerce_year(temp.get("end"))

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

    # Validate optional aggregation fields against canonical policy.
    temporal = metadata.get("temporal_coverage", {})
    frequency = str(temporal.get("frequency", "")).lower()
    requested_granularity = str(item.get("time_granularity") or "").strip().lower()
    if frequency in {"annual", "yearly"} and requested_granularity in {"daily", "weekly", "monthly", "annual"}:
        item["_normalized_time_granularity"] = {
            "from": item.get("time_granularity"),
            "to": "yearly",
            "reason": f"source_frequency={frequency}",
        }
        item["time_granularity"] = "yearly"

    metric_info = metrics.get(metric, {}) if metric else {}
    policy_ok, policy_error, policy_trace = validate_aggregation_policy(
        item,
        source_metadata=metadata,
        metric_name=metric,
        metric_info=metric_info,
    )
    item["_aggregation_policy"] = policy_trace
    if not policy_ok:
        item["_valid"] = False
        item["_error"] = policy_error or "Invalid aggregation policy"
        return item

    # Valid - add metric label if missing
    if metric and not item.get("metric_label"):
        name = metric_info.get("name", metric)
        unit = metric_info.get("unit", "")
        if unit and unit != "unknown":
            item["metric_label"] = f"{name} ({unit})"
        else:
            item["metric_label"] = name

    item["_valid"] = True
    return item


def _scope_matches_region_for_validation(scope: str, region) -> bool:
    """Mirror pack routing logic so validation can resolve pack_id -> source_id early."""
    if not region:
        return scope == "global"
    r = str(region).lower()
    if scope == "CAN":
        return r.startswith("can") or r.startswith("canada")
    if scope == "USA":
        return r.startswith("usa") or r.startswith("us-")
    if scope == "global":
        return True
    return r.startswith(str(scope).lower())


def _item_prefers_geometry_source_for_validation(item: dict) -> bool:
    text = " ".join(
        str(value or "")
        for value in (
            item.get("summary"),
            item.get("metric"),
            item.get("region"),
            ((item.get("_hints") or {}).get("original_query") if isinstance(item.get("_hints"), dict) else ""),
        )
    ).lower()
    geometry_terms = (
        "county",
        "counties",
        "district",
        "districts",
        "admin_2",
        "admin2",
        "tract",
        "tracts",
        "state",
        "states",
        "province",
        "provinces",
        "top ",
        "highest",
        "lowest",
        "rank",
        "ranking",
    )
    return any(term in text for term in geometry_terms)


def _resolve_source_for_validation(item: dict) -> str | None:
    """Resolve pack_id to a concrete source_id during validation."""
    pack_id = item.get("pack_id")
    if not pack_id:
        return item.get("source_id")

    catalog = load_catalog() or {}
    sources = catalog.get("sources", [])
    pack_sources = [src for src in sources if src.get("pack_id") == pack_id]
    if not pack_sources:
        return item.get("source_id")

    region = item.get("region")
    if _item_prefers_geometry_source_for_validation(item):
        geometry_sources = [src for src in pack_sources if src.get("geojson_shape") == "geometry_shape"]
        exact_geometry = [
            src for src in geometry_sources
            if src.get("scope") != "global" and _scope_matches_region_for_validation(src.get("scope", "global"), region)
        ]
        if exact_geometry:
            return exact_geometry[0].get("source_id")
        global_geometry = [src for src in geometry_sources if src.get("scope") == "global"]
        if global_geometry:
            return global_geometry[0].get("source_id")

    exact_matches = [
        src for src in pack_sources
        if src.get("scope") != "global" and _scope_matches_region_for_validation(src.get("scope", "global"), region)
    ]
    if exact_matches:
        return exact_matches[0].get("source_id")

    global_matches = [src for src in pack_sources if src.get("scope") == "global"]
    if global_matches:
        return global_matches[0].get("source_id")

    return pack_sources[0].get("source_id")


def _resolve_metric_for_validation(metric: str, metrics: dict) -> tuple[str | None, list[str]]:
    """Resolve metric keys using source metadata names and keywords before failing validation."""
    metric_lower = str(metric or "").strip().lower()
    if not metric_lower or not isinstance(metrics, dict):
        return None, []

    exact_match = None
    close_matches = []
    best_keyword_match = None
    best_keyword_score = 0
    metric_words = set(metric_lower.replace("_", " ").replace("-", " ").split())

    for key, value in metrics.items():
        key_lower = str(key).lower()
        if key_lower == metric_lower:
            return key, []

        phrases = [key_lower]
        if isinstance(value, dict):
            name = str(value.get("name") or "").strip().lower()
            if name:
                phrases.append(name)
            keywords = value.get("keywords") or []
            if isinstance(keywords, list):
                phrases.extend(str(keyword).strip().lower() for keyword in keywords if keyword)
        elif value:
            phrases.append(str(value).strip().lower())

        for phrase in phrases:
            if not phrase:
                continue
            if phrase == metric_lower:
                exact_match = key
                break
            if metric_lower in phrase or phrase in metric_lower:
                close_matches.append(key)
                phrase_words = set(phrase.replace("_", " ").replace("-", " ").split())
                score = len(metric_words & phrase_words) + 2
                if score > best_keyword_score:
                    best_keyword_match = key
                    best_keyword_score = score
            else:
                phrase_words = set(phrase.replace("_", " ").replace("-", " ").split())
                score = len(metric_words & phrase_words)
                if score > best_keyword_score:
                    best_keyword_match = key
                    best_keyword_score = score

        if exact_match:
            break

    if exact_match:
        return exact_match, []

    deduped = list(dict.fromkeys(close_matches))
    if best_keyword_match and best_keyword_score > 0:
        return best_keyword_match, deduped

    return None, deduped


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


def _coerce_year(value):
    """Best-effort conversion for LLM year values (e.g., '2020', 2020.0, '2020-01-01')."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        if len(text) >= 4 and text[:4].isdigit():
            return int(text[:4])
        return None


def _coerce_date_year(value) -> int | None:
    """Best-effort extraction of a calendar year from ISO-ish date fields."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _coerce_year(value)
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


def _normalize_item_year_fields(item: dict) -> None:
    """Normalize year fields on order item in place, including ISO date bounds."""
    year = _coerce_year(item.get("year"))
    year_start = _coerce_year(item.get("year_start"))
    year_end = _coerce_year(item.get("year_end"))
    date_start_year = _coerce_date_year(item.get("date_start"))
    date_end_year = _coerce_date_year(item.get("date_end"))

    if year_start is None and date_start_year is not None:
        year_start = date_start_year
    if year_end is None and date_end_year is not None:
        year_end = date_end_year
    if year is None and year_start is not None and year_end is not None and year_start == year_end:
        year = year_start

    if year is not None:
        item["year"] = year
    if year_start is not None:
        item["year_start"] = year_start
    if year_end is not None:
        item["year_end"] = year_end


def _matches_unsupported_metric_alias(user_query: str, metadata: dict) -> bool:
    """Return True when the query explicitly names an unsupported metric alias from metadata."""
    query_lower = str(user_query or "").strip().lower()
    if not query_lower or not isinstance(metadata, dict):
        return False
    routing_hints = metadata.get("routing_hints") or {}
    aliases = routing_hints.get("unsupported_metric_aliases") or []
    for alias in aliases:
        alias_text = str(alias or "").strip().lower()
        if alias_text and alias_text in query_lower:
            return True
    return False


def _summarize_supported_geography(metadata: dict) -> str:
    """Build a user-facing geography summary from metadata."""
    routing_hints = metadata.get("routing_hints") or {}
    geo_summary = str(routing_hints.get("supported_geography_summary") or "").strip()
    if geo_summary:
        return geo_summary

    geo_levels = metadata.get("geographic_level")
    if isinstance(geo_levels, list):
        cleaned = [str(level).replace("_", " ") for level in geo_levels if level]
        if cleaned:
            return ", ".join(cleaned)
    if geo_levels:
        return str(geo_levels).replace("_", " ")
    return "see source metadata"


def _build_metadata_unsupported_metric_clarify(user_query: str, metadata: dict) -> dict:
    """Build a generic metadata-grounded clarify for unsupported metric requests."""
    source_name = metadata.get("source_name") or metadata.get("source_id") or "this source"
    metrics = metadata.get("metrics") or {}
    metric_names = []
    for info in metrics.values():
        if not isinstance(info, dict):
            continue
        name = str(info.get("name") or "").strip()
        if name:
            metric_names.append(name)
    metric_names = list(dict.fromkeys(metric_names))
    metric_lines = metric_names[:6]
    geo_summary = _summarize_supported_geography(metadata)

    unsupported_label = "that metric"
    routing_hints = metadata.get("routing_hints") or {}
    aliases = routing_hints.get("unsupported_metric_aliases") or []
    query_lower = str(user_query or "").strip().lower()
    for alias in aliases:
        alias_text = str(alias or "").strip()
        if alias_text and alias_text.lower() in query_lower:
            normalized = alias_text
            if " " not in alias_text and alias_text.isalpha() and len(alias_text) <= 5:
                normalized = alias_text.upper()
            unsupported_label = normalized
            break

    lines = [
        f"{source_name} does not include {unsupported_label}.",
    ]
    if metric_lines:
        lines.append("Available metrics for this source include:")
        lines.extend(f"- {name}" for name in metric_lines)
    lines.append(f"This source supports {geo_summary}.")
    lines.append("Which of the available metrics would you like instead?")
    return {"type": "clarify", "message": "\n\n".join([lines[0], "\n".join(lines[1:])])}


def _apply_metadata_guided_response_normalization(result: dict, *, user_query: str, hints: dict | None) -> dict:
    """Normalize chat/clarify responses using metadata-backed routing hints when available."""
    if not isinstance(result, dict):
        return result
    if result.get("type") not in {"chat", "clarify"}:
        return result
    if not hints or not isinstance(hints, dict):
        return result

    detected_source = hints.get("detected_source") or {}
    source_id = detected_source.get("source_id")
    if not source_id:
        return result

    metadata = load_source_metadata(source_id) or {}
    if not metadata:
        return result

    if _matches_unsupported_metric_alias(user_query, metadata):
        return _build_metadata_unsupported_metric_clarify(user_query, metadata)

    return result


def parse_llm_response(content: str, hints: dict = None, user_query: str = "") -> dict:
    """
    Parse LLM response into structured result.

    Handles all response types from LLM:
    - order: Data request
    - navigate: Zoom to location(s)
    - disambiguate: Multiple locations match, need user to pick
    - filter_update: Change overlay filters
    - chat: General response
    - clarify: Need more information
    """
    parsed_json = None

    # Try to extract JSON from response
    if "```json" in content:
        try:
            json_str = content.split("```json")[1].split("```")[0].strip()
            parsed_json = json.loads(json_str)
        except (json.JSONDecodeError, IndexError):
            pass
    elif content.strip().startswith("{"):
        try:
            parsed_json = json.loads(content.strip())
        except json.JSONDecodeError:
            pass

    # If we got valid JSON, route based on type field
    if parsed_json and isinstance(parsed_json, dict):
        response_type = parsed_json.get("type", "order")  # Default to order for backwards compat

        if response_type == "navigate":
            # Navigation request - zoom to location(s)
            return {
                "type": "navigate",
                "locations": parsed_json.get("locations", []),
                "message": parsed_json.get("message", "Navigating to location")
            }

        elif response_type == "geometry_remove":
            # Remove geometry regions from display
            return {
                "type": "geometry_remove",
                "regions": parsed_json.get("regions", []),
                "geometry_type": parsed_json.get("geometry_type", "zcta"),
                "message": parsed_json.get("message", "Removing geometry")
            }

        elif response_type == "disambiguate":
            # Disambiguation needed - multiple locations match
            return {
                "type": "disambiguate",
                "options": parsed_json.get("options", []),
                "message": parsed_json.get("message", "Multiple locations found"),
                "query_term": parsed_json.get("query_term", "location")
            }

        elif response_type == "filter_update":
            # Filter update for disaster overlays
            return {
                "type": "filter_update",
                "overlay": parsed_json.get("overlay", ""),
                "filters": parsed_json.get("filters", {}),
                "message": parsed_json.get("message", "Updating filters")
            }

        elif response_type == "overlay_toggle":
            # Toggle overlay on/off (binary choice, no confidence needed)
            return {
                "type": "overlay_toggle",
                "overlay": parsed_json.get("overlay", ""),
                "enabled": parsed_json.get("enabled", True),
                "message": parsed_json.get("message", "")
            }

        elif response_type == "chat":
            # General chat response
            result = {
                "type": "chat",
                "message": parsed_json.get("message", "")
            }
            return _apply_metadata_guided_response_normalization(result, user_query=user_query, hints=hints)

        elif response_type == "clarify":
            # Need more information
            result = {"type": "clarify", "message": parsed_json.get("message", "Could you provide more details?")}
            return _apply_metadata_guided_response_normalization(result, user_query=user_query, hints=hints)

        else:
            # Default: treat as order (type == "order" or legacy format without type)
            order = validate_order(parsed_json)
            return {
                "type": "order",
                "order": order,
                "summary": order.get("summary", "Data request")
            }

    # No valid JSON - check if it's a clarifying question
    if "?" in content and len(content) < 200:
        result = {"type": "clarify", "message": content}
        return _apply_metadata_guided_response_normalization(result, user_query=user_query, hints=hints)

    # Otherwise it's a chat response
    result = {"type": "chat", "message": content}
    return _apply_metadata_guided_response_normalization(result, user_query=user_query, hints=hints)
