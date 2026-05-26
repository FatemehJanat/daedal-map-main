"""
Preprocessor - extracts hints from user queries before LLM call.

Part of the tiered context system:
- Tier 1: System prompt (cached)
- Tier 2: Preprocessor (this file, 0 LLM tokens)
- Tier 3: Just-in-time context (preprocessor hints)
- Tier 4: Reference documents (on-demand)

The preprocessor runs BEFORE the LLM call and:
1. Extracts topics from keywords
2. Resolves regions ("Europe" -> country codes)
3. Detects time patterns ("trend", "from X to Y")
4. Detects reference lookups (SDG, capitals, languages)

Output is a hints dict that can be injected into LLM context.
"""

import re
import json
from pathlib import Path
from typing import Optional
import logging

from .data_loading import load_catalog, load_source_metadata, get_source_path
from .runtime.preprocess_pipeline import build_preprocessor_hints
from .runtime.preprocess_pipeline import build_candidate_bundle
from .runtime.preprocess_pipeline import resolve_navigation_and_location
from .explore.preprocess_summary import build_preprocessor_summary
from .foundation_helpers import load_reference_json
from .runtime.candidate_scoring import (
    adjust_scores_with_context as adjust_scores_with_context_impl,
    detect_intent_candidates as detect_intent_candidates_impl,
    detect_source_candidates as detect_source_candidates_impl,
)
from .preprocessor_context import (
    build_tier3_context as build_tier3_context_impl,
    build_tier4_context as build_tier4_context_impl,
    format_filter_description as format_filter_description_impl,
)
from .runtime.preprocess_primitives import (
    build_name_to_iso3 as build_name_to_iso3_impl,
    build_subregion_to_iso3 as build_subregion_to_iso3_impl,
    detect_derived_intent as detect_derived_intent_impl,
    detect_drilldown_pattern as detect_drilldown_pattern_impl,
    detect_filter_intent as detect_filter_intent_impl,
    detect_location_candidates as detect_location_candidates_impl,
    detect_navigation_intent as detect_navigation_intent_impl,
    detect_overlay_intent as detect_overlay_intent_impl,
    detect_reference_lookup as detect_reference_lookup_impl,
    detect_show_borders_intent as detect_show_borders_intent_impl,
    detect_time_patterns as detect_time_patterns_impl,
    extract_country_from_query as extract_country_from_query_impl,
    extract_multiple_locations as extract_multiple_locations_impl,
    extract_topics as extract_topics_impl,
    get_countries_in_viewport as get_countries_in_viewport_impl,
    get_region_aliases as get_region_aliases_impl,
    get_relevant_sources_with_metrics as get_relevant_sources_with_metrics_impl,
    get_sorted_location_names as get_sorted_location_names_impl,
    load_country_index as load_country_index_impl,
    load_parquet_names as load_parquet_names_impl,
    lookup_country_specific_data as lookup_country_specific_data_impl,
    lookup_location_in_viewport as lookup_location_in_viewport_impl,
    resolve_regions as resolve_regions_impl,
    search_locations_globally as search_locations_globally_impl,
)
from .paths import GEOMETRY_DIR as GEOM_DIR, COUNTRIES_DIR

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIDENCE SCORING CONFIGURATION
# Adjust these values to tune the LLM candidate selection behavior
# =============================================================================

# Intent detection - data_request scoring
SCORE_DATA_KEYWORDS = 0.4       # "data", "statistics", "metrics"
SCORE_DATA_FROM = 0.2           # "from the", "from", "dataset"
SCORE_SOURCE_MENTIONED = 0.3    # Source name detected in query
SCORE_METRIC_KEYWORDS = 0.2     # "population", "gdp", "births", etc.

# Intent detection - navigation scoring
SCORE_NAV_PATTERN = 0.5         # Matches "show me", "go to", etc.
SCORE_NAV_PENALTY_DATA = -0.3   # Penalty if "data" keyword or source present
SCORE_NAV_LOCATION_ONLY = 0.3   # Location mentioned but no nav pattern

# Cross-reference adjustments (adjust_scores_with_context)
PENALTY_LOCATION_IN_SOURCE = -0.5   # Penalize location if it's part of source name (e.g., "bureau" in "Bureau of Statistics")
PENALTY_NAV_SOURCE_DETECTED = -0.3  # Reduce navigation confidence when source detected

# Source detection
SCORE_SOURCE_FULL_MATCH = 1.0   # Full source_name match
SCORE_SOURCE_ID_MATCH = 0.9     # source_id match
SCORE_SOURCE_PARTIAL_8 = 0.7    # Partial name match (>8 chars)
SCORE_SOURCE_PARTIAL_4 = 0.5    # Partial name match (4-8 chars)

# Overlay intent detection - loaded from reference/disasters.json
# Use _load_disaster_overlays() to access

# =============================================================================

# Paths
CONVERSIONS_PATH = Path(__file__).parent / "conversions.json"
REFERENCE_DIR = Path(__file__).parent / "reference"
GEOMETRY_DIR = GEOM_DIR

# Conversions.json cache
_CONVERSIONS_CACHE = None

# Caches for reference files
_TOPICS_CACHE = None
_DISASTERS_CACHE = None


def _load_topics() -> dict:
    """
    Load topic keywords by aggregating from catalog.

    Each source in the catalog has:
    - category: broad topic (economic, health, etc.)
    - topic_tags: specific topic tags
    - keywords: search terms

    Returns dict mapping category -> list of all keywords for that category.
    """
    global _TOPICS_CACHE
    if _TOPICS_CACHE is not None:
        return _TOPICS_CACHE

    try:
        catalog = load_catalog()
        sources = catalog.get("sources", [])

        # Aggregate keywords by category
        topics_dict = {}
        for source in sources:
            category = source.get("category") or ""
            category = category.lower()
            if not category:
                continue

            if category not in topics_dict:
                topics_dict[category] = set()

            # Add topic_tags as keywords
            for tag in source.get("topic_tags", []):
                topics_dict[category].add(tag.lower())

            # Add keywords
            for kw in source.get("keywords", []):
                topics_dict[category].add(kw.lower())

        # Convert sets to lists
        _TOPICS_CACHE = {cat: list(kws) for cat, kws in topics_dict.items()}
        logger.debug(f"Loaded {len(_TOPICS_CACHE)} topic categories from catalog")
        return _TOPICS_CACHE
    except Exception as e:
        logger.warning(f"Error loading topics from catalog: {e}")
        _TOPICS_CACHE = {}
        return _TOPICS_CACHE


def _load_disaster_overlays() -> dict:
    """Load disaster overlay keywords from reference file."""
    global _DISASTERS_CACHE
    if _DISASTERS_CACHE is not None:
        return _DISASTERS_CACHE

    data = load_reference_json("disasters.json")
    if isinstance(data, dict):
        overlays = data.get("overlays", {})
        _DISASTERS_CACHE = {
            overlay: info.get("keywords", [])
            for overlay, info in overlays.items()
            if not overlay.startswith("_")
        }
        logger.debug(f"Loaded {len(_DISASTERS_CACHE)} disaster overlays from reference file")
        return _DISASTERS_CACHE
    logger.warning("Error loading disasters.json")
    _DISASTERS_CACHE = {}
    return _DISASTERS_CACHE

def normalize_query_for_location_matching(query: str) -> str:
    """
    Normalize query to improve location matching.

    Handles:
    - Possessive forms: "australia's" -> "australia", "australias" -> "australia"
    - Trailing apostrophe: "texas'" -> "texas"
    """
    # Remove apostrophe-s possessive
    query = re.sub(r"'s\b", "", query)
    # Handle trailing apostrophe (e.g., "texas'")
    query = re.sub(r"'\b", "", query)
    # Handle informal possessive without apostrophe (e.g., "australias" -> "australia")
    # Only for words that look like country names (capitalized or at word boundary)
    # This pattern matches word + trailing 's' when followed by common words
    query = re.sub(r'\b(\w+?)s\s+(population|gdp|economy|data|capital|government|president|leader)',
                   r'\1 \2', query, flags=re.IGNORECASE)
    return query


def load_conversions() -> dict:
    """Load conversions.json for region resolution. Cached after first load."""
    global _CONVERSIONS_CACHE

    if _CONVERSIONS_CACHE is not None:
        return _CONVERSIONS_CACHE

    if CONVERSIONS_PATH.exists():
        with open(CONVERSIONS_PATH, encoding='utf-8') as f:
            _CONVERSIONS_CACHE = json.load(f)
            logger.debug("Cached conversions.json")
            return _CONVERSIONS_CACHE

    _CONVERSIONS_CACHE = {}
    return {}


def load_reference_file(filepath: Path) -> Optional[dict]:
    """Compatibility shim to the shared runtime foundation helper loader."""
    data = load_reference_json(filepath)
    return data if isinstance(data, dict) else None


# =============================================================================
# Viewport-based Location Lookup
# =============================================================================

def get_countries_in_viewport(bounds: dict) -> list:
    """
    Get list of ISO3 codes for countries visible in viewport.
    Uses global.csv bounding boxes for fast filtering.
    DataFrame is cached after first load.
    """
    return get_countries_in_viewport_impl(bounds, geometry_dir=GEOMETRY_DIR, logger=logger)


def load_parquet_names(iso3: str) -> dict:
    """
    Load location names from a country's parquet file.
    Returns dict of {name_lower: [list of location dicts]}
    Multiple locations can share the same name (e.g., 30+ Washington Counties).
    Cached per ISO3 code.
    """
    return load_parquet_names_impl(iso3, geometry_dir=GEOMETRY_DIR, logger=logger)


def get_sorted_location_names(iso3: str) -> list:
    """
    Get pre-sorted list of location names for a country (cached).
    Names are sorted by length (longest first) and filtered to remove
    numbers and single characters.
    """
    return get_sorted_location_names_impl(iso3, load_parquet_names_func=load_parquet_names, logger=logger)


def search_locations_globally(name: str, admin_level: int = None, limit_countries: list = None) -> list:
    """
    Search for locations by name across all parquet files globally.
    Used when viewport-based search fails or isn't available.

    Args:
        name: Location name to search for (case-insensitive)
        admin_level: Optional admin level to filter by (1=state, 2=county, 3=city)
        limit_countries: Optional list of ISO3 codes to limit search to

    Returns:
        List of match dicts with loc_id, matched_term, iso3, admin_level, etc.
    """
    return search_locations_globally_impl(
        name,
        admin_level,
        limit_countries,
        geometry_dir=GEOMETRY_DIR,
        reference_dir=REFERENCE_DIR,
        load_reference_file=load_reference_file,
        load_parquet_names_func=load_parquet_names,
    )


def lookup_location_in_viewport(query: str, viewport: dict = None) -> dict:
    """
    Search for a location name in parquet files, scoped by viewport.

    Args:
        query: User query text
        viewport: Optional viewport dict with bounds and adminLevel

    Returns:
        Dict with:
        - "match": (matched_term, iso3, is_subregion) if single match
        - "matches": list of all matches if multiple found
        - "ambiguous": True if multiple matches need disambiguation
        - None values if no match found
    """
    return lookup_location_in_viewport_impl(
        query,
        viewport,
        get_countries_in_viewport_func=get_countries_in_viewport,
        load_parquet_names_func=load_parquet_names,
        load_reference_file=load_reference_file,
        get_sorted_location_names_func=get_sorted_location_names,
        reference_dir=REFERENCE_DIR,
    )


# =============================================================================
# Country Name Extraction
# =============================================================================

def build_name_to_iso3() -> dict:
    """Build reverse lookup from country name to ISO3 code."""
    return build_name_to_iso3_impl(reference_dir=REFERENCE_DIR, load_reference_file=load_reference_file)


def build_subregion_to_iso3() -> dict:
    """
    Build lookup from capitals to parent country ISO3.

    Capitals are loaded from reference file.
    Other locations are recognized by the LLM (no preprocessing lookup needed).
    """
    return build_subregion_to_iso3_impl(reference_dir=REFERENCE_DIR, load_reference_file=load_reference_file)


def extract_country_from_query(query: str, viewport: dict = None) -> dict:
    """
    Extract a country or capital match from a query.

    `viewport` is retained for compatibility with existing callers.
    """
    return extract_country_from_query_impl(
        query,
        normalize_query_for_location_matching=normalize_query_for_location_matching,
        reference_dir=REFERENCE_DIR,
        load_reference_file=load_reference_file,
    )


# =============================================================================
# Source/Metric Hints for Context Injection
# =============================================================================

def load_country_index(iso3: str) -> Optional[dict]:
    """
    Load a country's index.json file for context injection.
    Contains llm_summary and dataset categories. Cached per country.
    """
    return load_country_index_impl(iso3, countries_dir=COUNTRIES_DIR, logger=logger)


def get_relevant_sources_with_metrics(topics: list, iso3: str = None) -> dict:
    """
    Find relevant sources based on detected topics and location.
    Returns dict with sources list and optional country context.

    Args:
        topics: List of detected topic names (e.g., ["demographics", "economy"])
        iso3: ISO3 country code if location was detected (e.g., "AUS")

    Returns:
        Dict with:
        - sources: List of relevant sources with metric names (FULL list for country sources)
        - country_summary: llm_summary from country index.json (if available)
        - country_index: Full country index data (datasets, admin_levels, etc.)
    """
    return get_relevant_sources_with_metrics_impl(
        topics,
        iso3,
        load_catalog=load_catalog,
        load_source_metadata=load_source_metadata,
        load_country_index_func=load_country_index,
    )


# =============================================================================
# Topic Extraction
# =============================================================================

# Topic keywords - derived from catalog.json (category, topic_tags, keywords)
# Use _load_topics() to access


def extract_topics(query: str) -> list:
    """
    Extract topic categories from query based on keywords.

    Returns list of topic names that match.
    """
    return extract_topics_impl(query, load_topics=_load_topics)


# =============================================================================
# Region Resolution
# =============================================================================

# Region aliases - loaded from conversions.json
# Use _get_region_aliases() to access

def _get_region_aliases() -> dict:
    """Load region aliases from conversions.json."""
    return get_region_aliases_impl(load_conversions=load_conversions)


def resolve_regions(query: str) -> list:
    """
    Detect region mentions in query and resolve to grouping names.

    Returns list of dicts with region info.
    Uses word boundaries to avoid false positives.
    """
    return resolve_regions_impl(query, load_conversions=load_conversions, get_region_aliases_func=_get_region_aliases)


# =============================================================================
# Time Pattern Detection
# =============================================================================

def detect_time_patterns(query: str) -> dict:
    """
    Detect time-related patterns in query.

    Returns dict with:
    - is_time_series: bool
    - year_start: int or None
    - year_end: int or None
    - pattern_type: str describing what was detected
    """
    return detect_time_patterns_impl(query)


# =============================================================================
# Reference Lookup Detection
# =============================================================================

def lookup_country_specific_data(ref_type: str, iso3: str, country_name: str) -> Optional[dict]:
    """Look up specific country data from reference files."""
    return lookup_country_specific_data_impl(
        ref_type,
        iso3,
        country_name,
        reference_dir=REFERENCE_DIR,
        load_reference_file=load_reference_file,
    )


def detect_reference_lookup(query: str) -> Optional[dict]:
    """Detect if query is asking for reference information."""
    return detect_reference_lookup_impl(
        query,
        reference_dir=REFERENCE_DIR,
        load_catalog=load_catalog,
        get_source_path=get_source_path,
        load_reference_file=load_reference_file,
        extract_country_from_query=extract_country_from_query,
    )


# =============================================================================
# Derived Field Detection
# =============================================================================

def detect_derived_intent(query: str) -> Optional[dict]:
    """Detect if query is asking for derived/calculated fields."""
    return detect_derived_intent_impl(query)


# =============================================================================
# Filter Intent Detection (Overlay Integration)
# =============================================================================

def detect_filter_intent(query: str, active_overlays: dict) -> Optional[dict]:
    """Detect if user is asking about or changing overlay filters."""
    return detect_filter_intent_impl(query, active_overlays)


def detect_overlay_intent(query: str, active_overlays: dict = None) -> Optional[dict]:
    """Detect if user is asking about a disaster overlay."""
    return detect_overlay_intent_impl(
        query,
        load_disaster_overlays=_load_disaster_overlays,
        detect_filter_intent_func=detect_filter_intent,
        active_overlays=active_overlays,
    )


# =============================================================================
# Candidate-Based Detection
# =============================================================================

def detect_source_candidates(query: str) -> dict:
    """Detect all possible source matches in query with confidence scores."""
    return detect_source_candidates_impl(
        query,
        load_catalog=load_catalog,
        load_source_metadata=load_source_metadata,
        score_source_full_match=SCORE_SOURCE_FULL_MATCH,
        score_source_id_match=SCORE_SOURCE_ID_MATCH,
        score_source_partial_8=SCORE_SOURCE_PARTIAL_8,
        score_source_partial_4=SCORE_SOURCE_PARTIAL_4,
    )


def detect_location_candidates(query: str, viewport: dict = None) -> dict:
    """
    Detect likely location candidates in a query.

    `viewport` is retained for compatibility with existing callers.
    """
    return detect_location_candidates_impl(
        query,
        normalize_query_for_location_matching=normalize_query_for_location_matching,
        reference_dir=REFERENCE_DIR,
        load_reference_file=load_reference_file,
    )


def detect_intent_candidates(query: str, source_candidates: dict, location_candidates: dict) -> dict:
    """Detect possible user intents with confidence scores."""
    return detect_intent_candidates_impl(
        query,
        source_candidates,
        location_candidates,
        detect_navigation_intent=detect_navigation_intent,
        detect_show_borders_intent=detect_show_borders_intent,
        detect_filter_intent=detect_filter_intent,
        score_data_keywords=SCORE_DATA_KEYWORDS,
        score_data_from=SCORE_DATA_FROM,
        score_source_mentioned=SCORE_SOURCE_MENTIONED,
        score_metric_keywords=SCORE_METRIC_KEYWORDS,
        score_nav_pattern=SCORE_NAV_PATTERN,
        score_nav_penalty_data=SCORE_NAV_PENALTY_DATA,
        score_nav_location_only=SCORE_NAV_LOCATION_ONLY,
    )


def adjust_scores_with_context(source_candidates: dict, location_candidates: dict, intent_candidates: dict) -> dict:
    """Cross-reference candidates to adjust confidence scores."""
    return adjust_scores_with_context_impl(
        source_candidates,
        location_candidates,
        intent_candidates,
        penalty_location_in_source=PENALTY_LOCATION_IN_SOURCE,
        penalty_nav_source_detected=PENALTY_NAV_SOURCE_DETECTED,
    )


def detect_show_borders_intent(query: str) -> dict:
    """Detect if query is asking to display geometry/borders without data."""
    return detect_show_borders_intent_impl(query)


def detect_tutorial_mode_intent(query: str) -> Optional[dict]:
    """Detect tutorial mode on/off/toggle commands before the LLM call."""
    query_lower = (query or "").strip().lower()
    if not query_lower:
        return None

    has_tutorial = "tutorial" in query_lower
    has_ui_help = "help me understand the ui" in query_lower or "show me what everything does" in query_lower
    if not has_tutorial and not has_ui_help:
        return None

    if re.search(r"\b(turn|switch|set|make)\s+(the\s+)?tutorial(\s+mode)?\s+(off|disable|disabled)\b", query_lower):
        return {"action": "off"}
    if re.search(r"\b(turn|switch|set|make)\s+(the\s+)?tutorial(\s+mode)?\s+(on|enable|enabled)\b", query_lower):
        return {"action": "on"}
    if re.search(r"\b(enable|start|show)\s+(the\s+)?tutorial(\s+mode)?\b", query_lower):
        return {"action": "on"}
    if re.search(r"\b(disable|stop|hide)\s+(the\s+)?tutorial(\s+mode)?\b", query_lower):
        return {"action": "off"}
    if re.search(r"\btutorial(\s+mode)?\s+on\b", query_lower):
        return {"action": "on"}
    if re.search(r"\btutorial(\s+mode)?\s+off\b", query_lower):
        return {"action": "off"}
    if re.search(r"\btoggle\s+(the\s+)?tutorial(\s+mode)?\b", query_lower) or re.search(r"\btutorial(\s+mode)?\s+toggle\b", query_lower):
        return {"action": "toggle"}
    if has_ui_help or re.search(r"\btutorial(\s+mode)?\b", query_lower):
        return {"action": "on"}
    return None


def detect_address_prompt_intent(query: str) -> Optional[dict]:
    """Detect explicit requests to open the address entry UI."""
    query_lower = (query or "").strip().lower()
    if not query_lower:
        return None

    trigger_patterns = [
        r"\b(add|enter|use|check|view|show|open|start)\s+(an?\s+)?address\b",
        r"\baddress\s+(lookup|input|entry|search|mode|finder)\b",
        r"\b(type|search)\s+(for\s+)?an?\s+address\b",
        r"\bfind\s+an?\s+address\b",
    ]
    if any(re.search(pattern, query_lower) for pattern in trigger_patterns):
        return {
            "action": "open",
            "message": "Start typing an address and pick the best match from autocomplete.",
            "placeholder": "Search for an address...",
        }
    return None


def detect_navigation_intent(query: str) -> dict:
    """Detect if query is asking to navigate to or view locations."""
    return detect_navigation_intent_impl(query)


def detect_drilldown_pattern(query: str, viewport: dict = None) -> dict:
    """
    Detect "drill-down" patterns like:
    - "texas counties" or "california cities" ([location] [level])
    - "counties in texas" or "cities of california" ([level] in/of [location])
    - "all the texas counties" (with "all the" prefix)

    Returns dict with:
    - is_drilldown: True if this is a drill-down pattern
    - parent_location: The parent location dict (e.g., Texas)
    - child_level_name: The child level name (e.g., "counties")
    """
    return detect_drilldown_pattern_impl(
        query,
        extract_country_from_query_func=lambda value: extract_country_from_query(value),
    )


def extract_multiple_locations(query: str, viewport: dict = None) -> dict:
    """
    Extract multiple location names from a query.
    Handles patterns like "Simpson and Woodford counties" or
    "Butler, Franklin, Knox, Laurel, Lawrence and Whitley".

    Returns dict with:
    - locations: list of location match dicts
    - needs_disambiguation: True if singular suffix with multiple matches (user wants ONE)
    - suffix_type: 'singular', 'plural', or None
    """
    return extract_multiple_locations_impl(
        query,
        detect_drilldown_pattern_func=lambda value: detect_drilldown_pattern(value),
        search_locations_globally=search_locations_globally,
        extract_country_from_query_func=lambda value: extract_country_from_query(value),
        logger=logger,
    )


# =============================================================================
# Main Preprocessor Function
# =============================================================================

def preprocess_query(query: str, viewport: dict = None, active_overlays: dict = None, cache_stats: dict = None, saved_order_names: list = None, time_state: dict = None, loaded_data: list = None) -> dict:
    """
    Main preprocessor function - extracts all hints from query.

    Args:
        query: User query text
        viewport: Optional viewport dict with {center, zoom, bounds, adminLevel}
        active_overlays: Optional dict with {type, filters, allActive} from frontend
        cache_stats: Optional dict with per-overlay stats {overlayId: {count, years, ...}}
        saved_order_names: Optional list of saved order names from frontend
        time_state: Optional dict with time slider state {isLiveLocked, currentTime, etc.}
        loaded_data: Optional list of loaded data entries {source_id, region, metric, years, data_type}

    Returns a hints dict that can be injected into LLM context.
    """
    show_borders = detect_show_borders_intent(query)
    resolution = resolve_navigation_and_location(
        query=query,
        viewport=viewport,
        detect_navigation_intent=detect_navigation_intent,
        extract_multiple_locations=extract_multiple_locations,
        detect_source_candidates=detect_source_candidates,
        extract_country_from_query=extract_country_from_query,
        load_reference_file=load_reference_file,
        reference_dir=REFERENCE_DIR,
        get_countries_in_viewport=get_countries_in_viewport,
        logger=logger,
    )
    navigation = resolution["navigation"]
    disambiguation = resolution["disambiguation"]
    source_candidates = resolution["source_candidates"]
    detected_source = resolution["detected_source"]
    location = resolution["location"]

    filter_intent = detect_filter_intent(query, active_overlays) if active_overlays else None

    overlay_intent = detect_overlay_intent(query, active_overlays)

    candidates = build_candidate_bundle(
        query=query,
        viewport=viewport,
        source_candidates=source_candidates,
        detect_location_candidates=detect_location_candidates,
        detect_intent_candidates=detect_intent_candidates,
        adjust_scores_with_context=adjust_scores_with_context,
    )

    hints = build_preprocessor_hints(
        query=query,
        viewport=viewport,
        show_borders=show_borders,
        navigation=navigation,
        address_prompt=detect_address_prompt_intent(query),
        topics=extract_topics(query),
        regions=resolve_regions(query),
        location=location,
        disambiguation=disambiguation,
        time_hints=detect_time_patterns(query),
        reference_lookup=detect_reference_lookup(query),
        derived_intent=detect_derived_intent(query),
        tutorial_mode=detect_tutorial_mode_intent(query),
        detected_source=detected_source,
        active_overlays=active_overlays,
        cache_stats=cache_stats,
        filter_intent=filter_intent,
        overlay_intent=overlay_intent,
        candidates=candidates,
        saved_order_names=saved_order_names,
        time_state=time_state,
        loaded_data=loaded_data,
    )

    hints["summary"] = build_preprocessor_summary(
        hints,
        navigation=navigation,
        location=location,
        disambiguation=disambiguation,
        active_overlays=active_overlays,
        filter_intent=filter_intent,
        overlay_intent=overlay_intent,
        time_state=time_state,
        saved_order_names=saved_order_names,
        loaded_data=loaded_data,
        format_filter_description_func=format_filter_description,
    )

    return hints


def format_filter_description(filters: dict, overlay_type: str) -> str:
    """Format filter settings as human-readable description."""
    return format_filter_description_impl(filters, overlay_type)


def build_tier3_context(hints: dict) -> str:
    """Build Tier 3 (Just-in-Time) context string from preprocessor hints."""
    return build_tier3_context_impl(
        hints,
        format_filter_description_func=format_filter_description,
        get_countries_in_viewport=get_countries_in_viewport,
        load_reference_file=load_reference_file,
        reference_dir=REFERENCE_DIR,
        load_source_metadata=load_source_metadata,
        get_source_path=get_source_path,
        get_relevant_sources_with_metrics=get_relevant_sources_with_metrics,
        logger=logger,
        countries_dir=COUNTRIES_DIR,
    )


def build_tier4_context(hints: dict) -> str:
    """Build Tier 4 (Reference) context string from preprocessor hints."""
    return build_tier4_context_impl(hints)
