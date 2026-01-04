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

logger = logging.getLogger(__name__)

# Paths
CONVERSIONS_PATH = Path(__file__).parent / "conversions.json"
REFERENCE_DIR = Path(__file__).parent / "reference"
DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/data")
GEOMETRY_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/geometry")

# Parquet cache for location lookups
_PARQUET_NAMES_CACHE = {}  # iso3 -> {name_lower: loc_id}


def load_conversions() -> dict:
    """Load conversions.json for region resolution."""
    if CONVERSIONS_PATH.exists():
        with open(CONVERSIONS_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {}


def load_reference_file(filepath: Path) -> Optional[dict]:
    """Load a reference JSON file if it exists."""
    if filepath.exists():
        with open(filepath, encoding='utf-8') as f:
            return json.load(f)
    return None


# =============================================================================
# Viewport-based Location Lookup
# =============================================================================

def get_countries_in_viewport(bounds: dict) -> list:
    """
    Get list of ISO3 codes for countries visible in viewport.
    Uses global.csv bounding boxes for fast filtering.
    """
    if not bounds:
        return []

    global_csv = GEOMETRY_DIR / "global.csv"
    if not global_csv.exists():
        return []

    try:
        import pandas as pd
        df = pd.read_csv(global_csv)

        # Viewport bounds
        v_west = bounds.get("west", -180)
        v_south = bounds.get("south", -90)
        v_east = bounds.get("east", 180)
        v_north = bounds.get("north", 90)

        # Filter by bounding box intersection
        if 'bbox_min_lon' in df.columns:
            mask = (
                (df['bbox_max_lon'] >= v_west) &
                (df['bbox_min_lon'] <= v_east) &
                (df['bbox_max_lat'] >= v_south) &
                (df['bbox_min_lat'] <= v_north)
            )
            df = df[mask]

        return df['loc_id'].tolist() if 'loc_id' in df.columns else []
    except Exception as e:
        logger.warning(f"Error getting countries in viewport: {e}")
        return []


def load_parquet_names(iso3: str) -> dict:
    """
    Load location names from a country's parquet file.
    Returns dict of {name_lower: [list of location dicts]}
    Multiple locations can share the same name (e.g., 30+ Washington Counties).
    Cached per ISO3 code.
    """
    global _PARQUET_NAMES_CACHE

    if iso3 in _PARQUET_NAMES_CACHE:
        return _PARQUET_NAMES_CACHE[iso3]

    parquet_file = GEOMETRY_DIR / f"{iso3}.parquet"
    if not parquet_file.exists():
        _PARQUET_NAMES_CACHE[iso3] = {}
        return {}

    try:
        import pandas as pd
        # Only load name columns, not geometry (much faster)
        df = pd.read_parquet(parquet_file, columns=['loc_id', 'name', 'parent_id', 'admin_level'])

        names_dict = {}
        for _, row in df.iterrows():
            name = row.get('name')
            if name and isinstance(name, str):
                name_lower = name.lower()
                location_info = {
                    "loc_id": row.get('loc_id'),
                    "parent_id": row.get('parent_id'),
                    "admin_level": row.get('admin_level')
                }
                # Store as list to handle duplicate names (e.g., Washington County in 30+ states)
                if name_lower not in names_dict:
                    names_dict[name_lower] = []
                names_dict[name_lower].append(location_info)

        _PARQUET_NAMES_CACHE[iso3] = names_dict
        logger.debug(f"Loaded {len(names_dict)} unique location names from {iso3}.parquet")
        return names_dict
    except Exception as e:
        logger.warning(f"Error loading parquet names for {iso3}: {e}")
        _PARQUET_NAMES_CACHE[iso3] = {}
        return {}


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
    name_lower = name.lower().strip()
    all_matches = []

    # Get list of countries to search
    if limit_countries:
        countries = limit_countries
    else:
        # Search common large countries first, then others
        priority_countries = ["USA", "CAN", "GBR", "AUS", "DEU", "FRA", "IND", "BRA", "MEX"]
        other_countries = []

        # Get all available parquet files
        if GEOMETRY_DIR.exists():
            for f in GEOMETRY_DIR.glob("*.parquet"):
                iso3 = f.stem
                if iso3 not in priority_countries:
                    other_countries.append(iso3)

        countries = priority_countries + other_countries

    # Search each country's parquet
    iso_data = load_reference_file(REFERENCE_DIR / "iso_codes.json")

    for iso3 in countries:
        names = load_parquet_names(iso3)
        if not names:
            continue

        # Look for exact name match - names[name_lower] is now a LIST of locations
        if name_lower in names:
            locations_list = names[name_lower]
            country_name = iso_data.get("iso3_to_name", {}).get(iso3, iso3) if iso_data else iso3

            for info in locations_list:
                # Check admin level filter
                if admin_level is not None and info.get("admin_level") != admin_level:
                    continue

                all_matches.append({
                    "matched_term": name_lower,
                    "iso3": iso3,
                    "country_name": country_name,
                    "loc_id": info.get("loc_id"),
                    "parent_id": info.get("parent_id"),
                    "admin_level": info.get("admin_level", 0),
                    "is_subregion": info.get("admin_level", 0) > 0
                })

    return all_matches


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
    query_lower = query.lower()
    result = {"match": None, "matches": [], "ambiguous": False}

    # Determine which countries to search
    countries_to_search = []

    if viewport and viewport.get("bounds"):
        # Use viewport to scope search
        countries_to_search = get_countries_in_viewport(viewport["bounds"])
        if not countries_to_search:
            # Viewport might be too small or no global.csv
            logger.debug("No countries in viewport, falling back to global search")
            return result
    else:
        # No viewport - this is handled by existing extract_country_from_query
        return result

    all_matches = []

    # Search for location names in visible countries' parquets
    for iso3 in countries_to_search:
        names = load_parquet_names(iso3)
        if not names:
            continue

        # Get country name for display (once per country)
        iso_data = load_reference_file(REFERENCE_DIR / "iso_codes.json")
        country_name = iso_data.get("iso3_to_name", {}).get(iso3, iso3) if iso_data else iso3

        # Sort by length (longest first) to match most specific names
        sorted_names = sorted(names.keys(), key=len, reverse=True)

        for name in sorted_names:
            # Use word boundary matching
            pattern = r'\b' + re.escape(name) + r'\b'
            if re.search(pattern, query_lower):
                # names[name] is now a LIST of locations
                locations_list = names[name]
                for info in locations_list:
                    is_subregion = info.get("admin_level", 0) > 0

                    all_matches.append({
                        "matched_term": name,
                        "iso3": iso3,
                        "country_name": country_name,
                        "loc_id": info.get("loc_id"),
                        "admin_level": info.get("admin_level", 0),
                        "is_subregion": is_subregion
                    })

    if len(all_matches) == 0:
        return result
    elif len(all_matches) == 1:
        m = all_matches[0]
        result["match"] = (m["matched_term"], m["iso3"], m["is_subregion"])
        result["matches"] = all_matches
    else:
        # Multiple matches - need disambiguation
        result["matches"] = all_matches
        result["ambiguous"] = True
        # Still provide first match as default, but flag ambiguity
        m = all_matches[0]
        result["match"] = (m["matched_term"], m["iso3"], m["is_subregion"])

    return result


# =============================================================================
# Country Name Extraction
# =============================================================================

# Caches for lookups (built once on first use)
_NAME_TO_ISO3_CACHE = None
_SUBREGION_TO_ISO3_CACHE = None


def build_name_to_iso3() -> dict:
    """Build reverse lookup from country name to ISO3 code."""
    global _NAME_TO_ISO3_CACHE
    if _NAME_TO_ISO3_CACHE is not None:
        return _NAME_TO_ISO3_CACHE

    iso_path = REFERENCE_DIR / "iso_codes.json"
    name_to_iso3 = {}

    if iso_path.exists():
        data = load_reference_file(iso_path)
        iso3_to_name = data.get("iso3_to_name", {})

        for iso3, name in iso3_to_name.items():
            # Primary name (lowercase for matching)
            name_to_iso3[name.lower()] = iso3

            # Also add without common suffixes/prefixes for fuzzy matching
            clean_name = name.lower()
            for suffix in [" islands", " island", " republic", " federation"]:
                if clean_name.endswith(suffix):
                    name_to_iso3[clean_name.replace(suffix, "").strip()] = iso3

    # Add common aliases
    aliases = {
        "usa": "USA", "us": "USA", "united states": "USA", "america": "USA",
        "uk": "GBR", "britain": "GBR", "england": "GBR",
        "russia": "RUS", "ussr": "RUS",
        "korea": "KOR", "south korea": "KOR",
        "north korea": "PRK", "dprk": "PRK",
        "taiwan": "TWN", "republic of china": "TWN",
        "iran": "IRN", "persia": "IRN",
        "syria": "SYR",
        "uae": "ARE", "emirates": "ARE",
        "vietnam": "VNM", "viet nam": "VNM",
        "congo": "COD", "drc": "COD",
        "ivory coast": "CIV", "cote d'ivoire": "CIV",
        "turkey": "TUR", "turkiye": "TUR",
        "holland": "NLD", "netherlands": "NLD",
        "czech republic": "CZE", "czechia": "CZE",
    }
    name_to_iso3.update(aliases)

    _NAME_TO_ISO3_CACHE = name_to_iso3
    return name_to_iso3


def build_subregion_to_iso3() -> dict:
    """
    Build lookup from capitals to parent country ISO3.

    Capitals are loaded from reference file.
    Other cities are resolved dynamically from geometry parquet files
    using lookup_location_in_viewport() with viewport context.
    """
    global _SUBREGION_TO_ISO3_CACHE
    if _SUBREGION_TO_ISO3_CACHE is not None:
        return _SUBREGION_TO_ISO3_CACHE

    subregion_to_iso3 = {}

    # Load capitals from country_metadata.json
    metadata_path = REFERENCE_DIR / "country_metadata.json"
    if metadata_path.exists():
        data = load_reference_file(metadata_path)
        capitals = data.get("capitals", {})
        for iso3, capital in capitals.items():
            if isinstance(capital, str) and capital and not capital.startswith("_"):
                subregion_to_iso3[capital.lower()] = iso3

    # Major cities are no longer hardcoded - resolved dynamically from
    # geometry parquet files using viewport context

    _SUBREGION_TO_ISO3_CACHE = subregion_to_iso3
    return subregion_to_iso3


def extract_country_from_query(query: str, viewport: dict = None) -> dict:
    """
    Extract country from query using hierarchical resolution.

    Resolution order:
    1. Direct country name match (from reference file)
    2. Capital city match (from reference file)
    3. Viewport-based location match (from geometry parquet files)

    Args:
        query: User query text
        viewport: Optional viewport dict with bounds and adminLevel

    Returns dict with:
        - match: (matched_term, ISO3, is_subregion) tuple if found
        - ambiguous: True if multiple matches need disambiguation
        - matches: list of all matches (for disambiguation display)
        - source: "country", "capital", or "viewport" indicating match source
    """
    result = {"match": None, "ambiguous": False, "matches": [], "source": None}
    query_lower = query.lower()

    # First try direct country match
    name_to_iso3 = build_name_to_iso3()
    sorted_names = sorted(name_to_iso3.keys(), key=len, reverse=True)

    for name in sorted_names:
        pattern = r'\b' + re.escape(name) + r'\b'
        if re.search(pattern, query_lower):
            iso3 = name_to_iso3[name]
            result["match"] = (name, iso3, False)
            result["source"] = "country"
            return result

    # Try capital cities from reference file
    subregion_to_iso3 = build_subregion_to_iso3()
    sorted_subregions = sorted(subregion_to_iso3.keys(), key=len, reverse=True)

    for subregion in sorted_subregions:
        pattern = r'\b' + re.escape(subregion) + r'\b'
        if re.search(pattern, query_lower):
            iso3 = subregion_to_iso3[subregion]
            result["match"] = (subregion, iso3, True)
            result["source"] = "capital"
            return result

    # Try viewport-based location lookup from geometry parquet files
    if viewport:
        viewport_result = lookup_location_in_viewport(query, viewport)
        if viewport_result.get("match"):
            result["match"] = viewport_result["match"]
            result["ambiguous"] = viewport_result.get("ambiguous", False)
            result["matches"] = viewport_result.get("matches", [])
            result["source"] = "viewport"
            return result

    return result


# =============================================================================
# Topic Extraction
# =============================================================================

# Topic keywords mapped to source categories
TOPIC_KEYWORDS = {
    "economy": ["gdp", "economic", "economy", "income", "wealth", "poverty", "trade", "export", "import"],
    "health": ["health", "disease", "mortality", "life expectancy", "hospital", "medical", "hiv", "aids", "obesity", "fertility"],
    "environment": ["co2", "carbon", "emissions", "climate", "pollution", "renewable", "energy", "electricity"],
    "education": ["education", "school", "literacy", "student", "university"],
    "demographics": ["population", "birth", "death", "age", "gender", "migration"],
    "development": ["sdg", "sustainable", "development goal", "indicator"],
}


def extract_topics(query: str) -> list:
    """
    Extract topic categories from query based on keywords.

    Returns list of topic names that match.
    """
    query_lower = query.lower()
    matched_topics = []

    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in query_lower for kw in keywords):
            matched_topics.append(topic)

    return matched_topics


# =============================================================================
# Region Resolution
# =============================================================================

# Common region aliases (case-insensitive)
REGION_ALIASES = {
    "europe": "WHO_European_Region",
    "european": "WHO_European_Region",
    "africa": "WHO_African_Region",
    "african": "WHO_African_Region",
    "sub-saharan africa": "Sub_Saharan_Africa",
    "asia": "WHO_South_East_Asia_Region",  # Could be multiple
    "middle east": "WHO_Eastern_Mediterranean_Region",
    "americas": "WHO_Region_of_the_Americas",
    "latin america": "Latin_America",
    "south america": "South_America",
    "north america": "North_America",
    "g7": "G7",
    "g20": "G20",
    "oecd": "OECD",
    "eu": "European_Union",
    "european union": "European_Union",
    "nordic": "Nordic_Countries",
    "brics": "BRICS",
    "developed": "High_Income",
    "developing": "Lower_Middle_Income",
    "high income": "High_Income",
    "low income": "Low_Income",
}


def resolve_regions(query: str) -> list:
    """
    Detect region mentions in query and resolve to grouping names.

    Returns list of dicts with region info.
    Uses word boundaries to avoid false positives.
    """
    query_lower = query.lower()
    conversions = load_conversions()
    groupings = conversions.get("regional_groupings", {})

    resolved = []

    # Check aliases first - use word boundaries to avoid partial matches
    for alias, grouping_name in REGION_ALIASES.items():
        # Use regex with word boundaries
        pattern = r'\b' + re.escape(alias) + r'\b'
        if re.search(pattern, query_lower):
            if grouping_name in groupings:
                group_data = groupings[grouping_name]
                resolved.append({
                    "match": alias,
                    "grouping": grouping_name,
                    "code": group_data.get("code"),
                    "countries": group_data.get("countries", []),
                    "count": len(group_data.get("countries", []))
                })

    # Also check for grouping names directly (e.g., "WHO_African_Region")
    for grouping_name, group_data in groupings.items():
        # Check if grouping name is mentioned (with word boundaries)
        name_lower = grouping_name.lower().replace("_", " ")
        name_pattern = r'\b' + re.escape(name_lower) + r'\b'

        # Check if code is mentioned (only for codes 3+ chars, with word boundaries)
        code = group_data.get("code", "").lower()
        code_matched = False
        if code and len(code) >= 3:
            code_pattern = r'\b' + re.escape(code) + r'\b'
            code_matched = bool(re.search(code_pattern, query_lower))

        if re.search(name_pattern, query_lower) or code_matched:
            # Avoid duplicates from alias resolution
            if not any(r["grouping"] == grouping_name for r in resolved):
                resolved.append({
                    "match": grouping_name,
                    "grouping": grouping_name,
                    "code": group_data.get("code"),
                    "countries": group_data.get("countries", []),
                    "count": len(group_data.get("countries", []))
                })

    return resolved


# =============================================================================
# Time Pattern Detection
# =============================================================================

TIME_PATTERNS = {
    "year_range": [
        r"from\s+(\d{4})\s+to\s+(\d{4})",
        r"between\s+(\d{4})\s+and\s+(\d{4})",
        r"(\d{4})\s*[-to]+\s*(\d{4})",
    ],
    "trend_indicators": [
        r"\btrend\b",
        r"\bover time\b",
        r"\bhistor(?:y|ical)\b",
        r"\bchange\b",
        r"\bgrowth\b",
        r"\bdecline\b",
    ],
    "last_n_years": [
        r"last\s+(\d+)\s+years?",
        r"past\s+(\d+)\s+years?",
    ],
    "since_year": [
        r"since\s+(\d{4})",
        r"from\s+(\d{4})",
    ],
    "single_year": [
        r"\bin\s+(\d{4})\b",
        r"\bfor\s+(\d{4})\b",
        r"\b(\d{4})\s+data\b",
    ],
}


def detect_time_patterns(query: str) -> dict:
    """
    Detect time-related patterns in query.

    Returns dict with:
    - is_time_series: bool
    - year_start: int or None
    - year_end: int or None
    - pattern_type: str describing what was detected
    """
    result = {
        "is_time_series": False,
        "year_start": None,
        "year_end": None,
        "pattern_type": None,
    }

    query_lower = query.lower()

    # Check for explicit year ranges
    for pattern in TIME_PATTERNS["year_range"]:
        match = re.search(pattern, query_lower)
        if match:
            result["is_time_series"] = True
            result["year_start"] = int(match.group(1))
            result["year_end"] = int(match.group(2))
            result["pattern_type"] = "year_range"
            return result

    # Check for trend indicators
    for pattern in TIME_PATTERNS["trend_indicators"]:
        if re.search(pattern, query_lower):
            result["is_time_series"] = True
            result["pattern_type"] = "trend"
            # Could set default range here, or let LLM decide
            break

    # Check for "last N years"
    for pattern in TIME_PATTERNS["last_n_years"]:
        match = re.search(pattern, query_lower)
        if match:
            result["is_time_series"] = True
            n_years = int(match.group(1))
            result["year_end"] = 2024  # Current year
            result["year_start"] = 2024 - n_years
            result["pattern_type"] = "last_n_years"
            return result

    # Check for "since YYYY"
    for pattern in TIME_PATTERNS["since_year"]:
        match = re.search(pattern, query_lower)
        if match:
            result["is_time_series"] = True
            result["year_start"] = int(match.group(1))
            result["year_end"] = 2024
            result["pattern_type"] = "since_year"
            return result

    # Check for single year (not time series)
    for pattern in TIME_PATTERNS["single_year"]:
        match = re.search(pattern, query_lower)
        if match:
            year = int(match.group(1))
            if 1900 < year < 2100:  # Sanity check
                result["year_start"] = year
                result["year_end"] = year
                result["pattern_type"] = "single_year"
                return result

    return result


# =============================================================================
# Reference Lookup Detection
# =============================================================================

def lookup_country_specific_data(ref_type: str, iso3: str, country_name: str) -> Optional[dict]:
    """
    Look up specific country data from reference files.

    Returns dict with the specific data, or None if not found.
    """
    if ref_type == "currency":
        ref_path = REFERENCE_DIR / "currencies_scraped.json"
        if ref_path.exists():
            data = load_reference_file(ref_path)
            currencies = data.get("currencies", {})
            if iso3 in currencies:
                currency = currencies[iso3]
                return {
                    "country": country_name,
                    "iso3": iso3,
                    "currency_code": currency.get("code"),
                    "currency_name": currency.get("name"),
                    "formatted": f"{country_name} uses {currency.get('name')} ({currency.get('code')})"
                }

    elif ref_type == "language":
        ref_path = REFERENCE_DIR / "languages_scraped.json"
        if ref_path.exists():
            data = load_reference_file(ref_path)
            languages = data.get("languages", {})
            if iso3 in languages:
                lang_data = languages[iso3]
                official = lang_data.get("official", [])
                all_langs = lang_data.get("languages", [])
                return {
                    "country": country_name,
                    "iso3": iso3,
                    "official_languages": official,
                    "all_languages": all_langs,
                    "formatted": f"{country_name}: Official language(s): {', '.join(official) if official else 'N/A'}. All languages: {', '.join(all_langs[:5]) if all_langs else 'N/A'}"
                }

    elif ref_type == "timezone":
        ref_path = REFERENCE_DIR / "timezones_scraped.json"
        if ref_path.exists():
            data = load_reference_file(ref_path)
            timezones = data.get("timezones", {})
            if iso3 in timezones:
                tz_data = timezones[iso3]
                return {
                    "country": country_name,
                    "iso3": iso3,
                    "utc_offset": tz_data.get("utc_offset"),
                    "has_dst": tz_data.get("has_dst"),
                    "num_timezones": tz_data.get("num_timezones"),
                    "formatted": f"{country_name}: {tz_data.get('utc_offset')}" + (f" (DST observed)" if tz_data.get("has_dst") else "") + (f" ({tz_data.get('num_timezones')} time zones)" if tz_data.get("num_timezones", 1) > 1 else "")
                }

    elif ref_type == "capital":
        ref_path = REFERENCE_DIR / "country_metadata.json"
        if ref_path.exists():
            data = load_reference_file(ref_path)
            capitals = data.get("capitals", {})
            if iso3 in capitals:
                capital = capitals[iso3]
                return {
                    "country": country_name,
                    "iso3": iso3,
                    "capital": capital,
                    "formatted": f"The capital of {country_name} is {capital}" if capital else f"Capital not found for {country_name}"
                }

    return None


def detect_reference_lookup(query: str) -> Optional[dict]:
    """
    Detect if query is asking for reference information.

    Returns dict with reference file path, type, and specific country data if found.
    """
    query_lower = query.lower()

    # SDG pattern - "What is SDG 7?" or "goal 7" or "sustainable development goal 7"
    sdg_match = re.search(r'sdg\s*(\d+)|goal\s*(\d+)|sustainable development goal\s*(\d+)', query_lower)
    if sdg_match:
        num = sdg_match.group(1) or sdg_match.group(2) or sdg_match.group(3)
        num_padded = num.zfill(2)
        ref_path = DATA_DIR / f"un_sdg_{num_padded}" / "reference.json"
        if ref_path.exists():
            return {
                "type": "sdg",
                "sdg_number": int(num),
                "file": str(ref_path),
                "content": load_reference_file(ref_path)
            }

    # Extract country from query for country-specific lookups
    # Returns dict with match tuple and disambiguation info
    country_result = extract_country_from_query(query)
    if country_result.get("match"):
        matched_term, iso3, is_subregion = country_result["match"]
        # Get proper country name from ISO3 for display
        iso_data = load_reference_file(REFERENCE_DIR / "iso_codes.json")
        country_name = iso_data.get("iso3_to_name", {}).get(iso3, matched_term.title()) if iso_data else matched_term.title()
    else:
        matched_term = None
        iso3 = None
        is_subregion = False
        country_name = None

    # Capital pattern - "What is the capital of X?"
    if any(kw in query_lower for kw in ["capital of", "capital city"]):
        result = {
            "type": "capital",
            "file": str(REFERENCE_DIR / "country_metadata.json"),
        }
        if iso3:
            specific = lookup_country_specific_data("capital", iso3, country_name)
            if specific:
                result["country_data"] = specific
        return result

    # Currency pattern - use scraped World Factbook data
    if any(kw in query_lower for kw in ["currency", "money in", "monetary unit"]):
        result = {
            "type": "currency",
            "file": str(REFERENCE_DIR / "currencies_scraped.json"),
        }
        if iso3:
            specific = lookup_country_specific_data("currency", iso3, country_name)
            if specific:
                result["country_data"] = specific
        return result

    # Language pattern - use scraped World Factbook data
    if any(kw in query_lower for kw in ["language", "speak", "spoken", "official language"]):
        result = {
            "type": "language",
            "file": str(REFERENCE_DIR / "languages_scraped.json"),
        }
        if iso3:
            specific = lookup_country_specific_data("language", iso3, country_name)
            if specific:
                result["country_data"] = specific
        return result

    # Timezone pattern - use scraped World Factbook data
    if any(kw in query_lower for kw in ["timezone", "time zone", "what time"]):
        result = {
            "type": "timezone",
            "file": str(REFERENCE_DIR / "timezones_scraped.json"),
        }
        if iso3:
            specific = lookup_country_specific_data("timezone", iso3, country_name)
            if specific:
                result["country_data"] = specific
        return result

    # Country background/overview pattern - "tell me about France" or "history of Germany"
    background_keywords = ["background", "history of", "tell me about", "overview of", "about the country"]
    if iso3 and any(kw in query_lower for kw in background_keywords):
        ref_path = REFERENCE_DIR / "world_factbook_text.json"
        if ref_path.exists():
            data = load_reference_file(ref_path)
            countries = data.get("countries", {})
            if iso3 in countries:
                country_data = countries[iso3]
                background = country_data.get("background", "")
                if background:
                    # Truncate long backgrounds for context injection
                    summary = background[:800] + "..." if len(background) > 800 else background
                    return {
                        "type": "country_info",
                        "file": str(ref_path),
                        "country_data": {
                            "country": country_name,
                            "iso3": iso3,
                            "background": background,
                            "formatted": f"{country_name} Background: {summary}"
                        }
                    }

    # Economy pattern - "economy of France" or "economic overview of Germany"
    if iso3 and any(kw in query_lower for kw in ["economy", "economic", "industries", "gdp"]):
        ref_path = REFERENCE_DIR / "world_factbook_text.json"
        if ref_path.exists():
            data = load_reference_file(ref_path)
            countries = data.get("countries", {})
            if iso3 in countries:
                country_data = countries[iso3]
                econ = country_data.get("economic_overview", "")
                industries = country_data.get("industries", "")
                if econ or industries:
                    parts = []
                    if econ:
                        parts.append(f"Economic Overview: {econ[:400]}")
                    if industries:
                        parts.append(f"Industries: {industries}")
                    return {
                        "type": "economy_info",
                        "file": str(ref_path),
                        "country_data": {
                            "country": country_name,
                            "iso3": iso3,
                            "economic_overview": econ,
                            "industries": industries,
                            "formatted": f"{country_name} - " + "; ".join(parts)
                        }
                    }

    # Trade pattern - "trade partners of Peru" or "exports of Japan"
    trade_keywords = ["trade partner", "trading partner", "export partner", "import partner",
                      "exports of", "imports of", "main export", "main import", "top export", "top import",
                      "trade with", "trades with", "trading with", "who export", "who import"]
    if iso3 and any(kw in query_lower for kw in trade_keywords):
        ref_path = REFERENCE_DIR / "world_factbook_text.json"
        if ref_path.exists():
            data = load_reference_file(ref_path)
            countries = data.get("countries", {})
            if iso3 in countries:
                country_data = countries[iso3]
                exports_commodities = country_data.get("exports_commodities", "")
                exports_partners = country_data.get("exports_partners", "")
                imports_commodities = country_data.get("imports_commodities", "")
                imports_partners = country_data.get("imports_partners", "")
                if exports_partners or imports_partners or exports_commodities or imports_commodities:
                    parts = []
                    if exports_partners:
                        parts.append(f"Export partners: {exports_partners}")
                    if exports_commodities:
                        parts.append(f"Main exports: {exports_commodities}")
                    if imports_partners:
                        parts.append(f"Import partners: {imports_partners}")
                    if imports_commodities:
                        parts.append(f"Main imports: {imports_commodities}")
                    return {
                        "type": "trade_info",
                        "file": str(ref_path),
                        "country_data": {
                            "country": country_name,
                            "iso3": iso3,
                            "exports_partners": exports_partners,
                            "exports_commodities": exports_commodities,
                            "imports_partners": imports_partners,
                            "imports_commodities": imports_commodities,
                            "formatted": f"{country_name} Trade - " + "; ".join(parts)
                        }
                    }

    # Government pattern - "government of France" or "political system"
    if iso3 and any(kw in query_lower for kw in ["government", "political", "constitution", "president", "parliament", "legislature"]):
        ref_path = REFERENCE_DIR / "world_factbook_text.json"
        if ref_path.exists():
            data = load_reference_file(ref_path)
            countries = data.get("countries", {})
            if iso3 in countries:
                country_data = countries[iso3]
                executive = country_data.get("executive_branch", "")
                legislative = country_data.get("legislative_branch", "")
                constitution = country_data.get("constitution", "")
                if executive or legislative or constitution:
                    parts = []
                    if executive:
                        parts.append(f"Executive: {executive[:300]}")
                    if legislative:
                        parts.append(f"Legislature: {legislative[:200]}")
                    return {
                        "type": "government_info",
                        "file": str(ref_path),
                        "country_data": {
                            "country": country_name,
                            "iso3": iso3,
                            "executive": executive,
                            "legislative": legislative,
                            "constitution": constitution,
                            "formatted": f"{country_name} Government - " + "; ".join(parts)
                        }
                    }

    # Data source reference pattern - "what is owid?" or "tell me about who_health"
    source_patterns = [
        (r'\b(owid|owid_co2)\b', "owid_co2"),
        (r'\b(who|who_health|world health)\b', "who_health"),
        (r'\b(imf|imf_bop|balance of payments)\b', "imf_bop"),
        (r'\b(census|us census)\b', "census_population"),
        (r'\b(world factbook|cia factbook|factbook)\b', "world_factbook"),
    ]
    for pattern, source_id in source_patterns:
        if re.search(pattern, query_lower):
            ref_path = DATA_DIR / source_id / "reference.json"
            if ref_path.exists():
                return {
                    "type": "data_source",
                    "source_id": source_id,
                    "file": str(ref_path),
                    "content": load_reference_file(ref_path)
                }

    return None


# =============================================================================
# Derived Field Detection
# =============================================================================

DERIVED_PATTERNS = {
    "per_capita": [
        r"per capita",
        r"per person",
        r"per head",
        r"per inhabitant",
    ],
    "density": [
        r"density",
        r"per square",
        r"per km",
        r"per sq",
    ],
    "per_1000": [
        r"per 1000",
        r"per thousand",
    ],
    "ratio": [
        r"ratio of",
        r"(\w+)\s*/\s*(\w+)",  # GDP/CO2 style
        r"(\w+)\s+to\s+(\w+)\s+ratio",
    ],
}


def detect_derived_intent(query: str) -> Optional[dict]:
    """
    Detect if query is asking for derived/calculated fields.

    Returns dict with derived type and any detected specifics.
    """
    query_lower = query.lower()

    for derived_type, patterns in DERIVED_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, query_lower)
            if match:
                result = {
                    "type": derived_type,
                    "match": match.group(0),
                }
                # For ratio patterns, try to extract numerator/denominator
                if derived_type == "ratio" and len(match.groups()) >= 2:
                    result["numerator_hint"] = match.group(1)
                    result["denominator_hint"] = match.group(2)
                return result

    return None


# =============================================================================
# Navigation Intent Detection
# =============================================================================

# Patterns that indicate user wants to navigate/view locations, not request data
NAVIGATION_PATTERNS = [
    r"^show me\b",
    r"^where is\b",
    r"^where are\b",
    r"^locate\b",
    r"^find\b(?!.*data)",  # "find X" but not "find data for X"
    r"^zoom to\b",
    r"^go to\b",
    r"^take me to\b",
    r"^show\b(?!.*data|.*gdp|.*population)",  # "show X" but not "show data/gdp/population"
]

# Patterns for "show borders/geometry" follow-up requests (no data, just display)
SHOW_BORDERS_PATTERNS = [
    r"^(?:just\s+)?show\s+(?:me\s+)?(?:them|all|all\s+of\s+them)\b",
    r"^display\s+(?:them|all|all\s+of\s+them)\b",
    r"^(?:just\s+)?show\s+(?:me\s+)?(?:the\s+)?(?:borders?|geometr(?:y|ies)|outlines?|boundaries?)\b",
    r"^(?:put|display|show)\s+(?:them\s+)?(?:all\s+)?on\s+(?:the\s+)?map\b",
    r"^(?:just\s+)?the\s+(?:borders?|geometr(?:y|ies)|locations?)\b",
]


def detect_show_borders_intent(query: str) -> dict:
    """
    Detect if query is asking to display geometry/borders without data.
    Typically used as a follow-up after disambiguation lists locations.

    Patterns:
    - "just show me them"
    - "display them all"
    - "show all of them on the map"
    - "just the borders"

    Returns dict with:
    - is_show_borders: True if this is a show-borders request
    - pattern: The matched pattern
    """
    result = {
        "is_show_borders": False,
        "pattern": None,
    }

    query_lower = query.lower().strip()

    for pattern in SHOW_BORDERS_PATTERNS:
        if re.match(pattern, query_lower):
            result["is_show_borders"] = True
            result["pattern"] = pattern
            return result

    return result


def detect_navigation_intent(query: str) -> dict:
    """
    Detect if query is asking to navigate to/view locations.

    Returns dict with:
    - is_navigation: True if this is a navigation request
    - pattern: The matched pattern
    - location_text: The text after the navigation verb (potential location names)
    """
    result = {
        "is_navigation": False,
        "pattern": None,
        "location_text": None,
    }

    query_lower = query.lower().strip()

    for pattern in NAVIGATION_PATTERNS:
        match = re.match(pattern, query_lower)
        if match:
            result["is_navigation"] = True
            result["pattern"] = pattern
            # Extract everything after the navigation verb as potential location(s)
            after_match = query_lower[match.end():].strip()
            result["location_text"] = after_match
            return result

    return result


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
    query_lower = query.lower().strip()

    # Remove common prefixes: "all", "the", "show me", etc.
    query_lower = re.sub(r'^(?:show\s+me\s+)?(?:all\s+)?(?:the\s+)?', '', query_lower)

    # Admin level names to check (plural forms)
    level_names = ["counties", "states", "cities", "districts", "regions",
                   "provinces", "municipalities", "departments", "prefectures",
                   "parishes", "boroughs"]

    # Pattern 1: "[level] in/of [location]" (e.g., "counties in texas")
    for level in level_names:
        # Match patterns like "counties in texas" or "cities of california"
        pattern = rf'^{level}\s+(?:in|of)\s+(.+)$'
        match = re.match(pattern, query_lower)
        if match:
            location_part = match.group(1).strip()
            if location_part:
                # Try to find this as a location
                result = extract_country_from_query(location_part)
                if result.get("match"):
                    matched_term, iso3, is_subregion = result["match"]
                    return {
                        "is_drilldown": True,
                        "parent_location": {
                            "matched_term": matched_term,
                            "iso3": iso3,
                            "loc_id": result.get("loc_id", iso3),
                            "country_name": result.get("country_name", matched_term),
                            "is_subregion": is_subregion
                        },
                        "child_level_name": level
                    }

                # Also try viewport-based lookup
                if viewport:
                    vp_result = lookup_location_in_viewport(location_part, viewport)
                    if vp_result.get("matches") and len(vp_result["matches"]) == 1:
                        loc_match = vp_result["matches"][0]
                        return {
                            "is_drilldown": True,
                            "parent_location": loc_match,
                            "child_level_name": level
                        }

    # Pattern 2: "[location] [level]" (e.g., "texas counties")
    for level in level_names:
        if query_lower.endswith(level):
            # Extract what comes before the level
            location_part = query_lower[:-len(level)].strip()

            if not location_part:
                continue

            # Try to find this as a location (state, country, etc.)
            result = extract_country_from_query(location_part)
            if result.get("match"):
                matched_term, iso3, is_subregion = result["match"]
                return {
                    "is_drilldown": True,
                    "parent_location": {
                        "matched_term": matched_term,
                        "iso3": iso3,
                        "loc_id": result.get("loc_id", iso3),
                        "country_name": result.get("country_name", matched_term),
                        "is_subregion": is_subregion
                    },
                    "child_level_name": level
                }

            # Also try viewport-based lookup for state-level
            if viewport:
                vp_result = lookup_location_in_viewport(location_part, viewport)
                if vp_result.get("matches") and len(vp_result["matches"]) == 1:
                    loc_match = vp_result["matches"][0]
                    return {
                        "is_drilldown": True,
                        "parent_location": loc_match,
                        "child_level_name": level
                    }

    return {"is_drilldown": False}


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
    # First, try to find comma-separated or "and"-separated location names
    # Common patterns: "X, Y, and Z" or "X and Y" or "X, Y, Z"
    query_lower = query.lower()

    # Check for drill-down pattern first (e.g., "texas counties" -> drill into Texas)
    drilldown = detect_drilldown_pattern(query, viewport)
    if drilldown.get("is_drilldown"):
        # Return the parent location with a drill-down flag
        parent = drilldown["parent_location"]
        parent["drill_to_level"] = drilldown["child_level_name"]
        return {"locations": [parent], "needs_disambiguation": False, "suffix_type": "plural"}

    # Track admin level AND whether suffix was singular (disambiguation) or plural (show all)
    singular_suffixes = {
        "county": 2, "parish": 2, "borough": 2,
        "state": 1, "province": 1, "region": 1,
        "city": 3, "town": 3, "place": 3,
        "district": 2,
    }
    plural_suffixes = {
        "counties": 2, "parishes": 2, "boroughs": 2,
        "states": 1, "provinces": 1, "regions": 1,
        "cities": 3, "towns": 3, "places": 3,
        "districts": 2,
    }

    suffix_found = None
    expected_admin_level = None
    suffix_type = None  # 'singular' = user wants one (disambiguate), 'plural' = show all

    # Check singular suffixes first (more specific)
    for suffix, level in singular_suffixes.items():
        if query_lower.endswith(suffix):
            suffix_found = suffix
            expected_admin_level = level
            suffix_type = "singular"
            query_lower = query_lower[:-len(suffix)].strip()
            break

    # Check plural suffixes if no singular match
    if not suffix_found:
        for suffix, level in plural_suffixes.items():
            if query_lower.endswith(suffix):
                suffix_found = suffix
                expected_admin_level = level
                suffix_type = "plural"
                query_lower = query_lower[:-len(suffix)].strip()
                break

    # Split by comma and "and"
    # Replace "and" with comma, then split
    normalized = re.sub(r'\s+and\s+', ', ', query_lower)
    normalized = re.sub(r'\s*,\s*', ',', normalized)
    parts = [p.strip() for p in normalized.split(',') if p.strip()]

    # Don't append suffix back - search by name only, then filter by admin level
    # This prevents matching "washington" in "washington county" to Washington state

    all_matches = []

    # Look up each part
    for part in parts:
        part_matches = []

        if viewport:
            result = lookup_location_in_viewport(part, viewport)
            if result.get("matches"):
                matches = result["matches"]
                # Filter by admin level if suffix implies a specific level
                if expected_admin_level is not None:
                    matches = [m for m in matches if m.get("admin_level") == expected_admin_level]
                part_matches.extend(matches)

        # If viewport lookup failed or returned empty, and we have a specific admin level,
        # do a global search for this name at this admin level
        if not part_matches and expected_admin_level is not None:
            logger.debug(f"Viewport lookup empty for '{part}', doing global search at admin_level={expected_admin_level}")
            global_matches = search_locations_globally(part, admin_level=expected_admin_level)
            if global_matches:
                part_matches.extend(global_matches)
                logger.debug(f"Global search found {len(global_matches)} matches for '{part}'")

        # If still no matches and no specific admin level, try country lookup
        if not part_matches and expected_admin_level is None:
            result = extract_country_from_query(part)
            if result.get("match"):
                matched_term, iso3, is_subregion = result["match"]
                part_matches.append({
                    "matched_term": matched_term,
                    "iso3": iso3,
                    "is_subregion": is_subregion,
                    "source": result.get("source", "country")
                })

        all_matches.extend(part_matches)

    # Determine if disambiguation is needed:
    # - Singular suffix (county, city) with multiple matches = user wants ONE, needs to pick
    # - Plural suffix (counties, cities) with multiple matches = user wants ALL, show them
    needs_disambiguation = (suffix_type == "singular" and len(all_matches) > 1)

    return {
        "locations": all_matches,
        "needs_disambiguation": needs_disambiguation,
        "suffix_type": suffix_type,
        "query_term": query.strip()  # Original query for disambiguation message
    }


# =============================================================================
# Main Preprocessor Function
# =============================================================================

def preprocess_query(query: str, viewport: dict = None) -> dict:
    """
    Main preprocessor function - extracts all hints from query.

    Args:
        query: User query text
        viewport: Optional viewport dict with {center, zoom, bounds, adminLevel}

    Returns a hints dict that can be injected into LLM context.
    """
    # Check for "show borders" intent first - follow-up to display geometry without data
    show_borders = detect_show_borders_intent(query)

    # Check for navigation intent first
    nav_intent = detect_navigation_intent(query)

    # For navigation queries, try to extract multiple locations
    navigation = None
    disambiguation = None

    if nav_intent.get("is_navigation") and nav_intent.get("location_text"):
        # Try to extract multiple locations from the query
        location_result = extract_multiple_locations(nav_intent["location_text"], viewport)
        locations = location_result.get("locations", [])

        if locations:
            # Check if disambiguation is needed (singular suffix with multiple matches)
            if location_result.get("needs_disambiguation"):
                # User said "washington county" (singular) but we found many - need to pick one
                disambiguation = {
                    "needed": True,
                    "query_term": location_result.get("query_term", "location"),
                    "options": locations,
                    "count": len(locations)
                }
            else:
                # Either single match, or plural suffix (show all), or explicit list
                navigation = {
                    "is_navigation": True,
                    "pattern": nav_intent.get("pattern"),
                    "locations": locations,
                    "count": len(locations)
                }

    # Resolve location for non-navigation queries (data orders, etc.)
    # Pass viewport to enable parquet-based city/location lookups
    location = None

    if not navigation and not disambiguation:
        location_result = extract_country_from_query(query, viewport=viewport)

        if location_result.get("match"):
            matched_term, iso3, is_subregion = location_result["match"]
            # Get proper country name from ISO3
            iso_data = load_reference_file(REFERENCE_DIR / "iso_codes.json")
            country_name = iso_data.get("iso3_to_name", {}).get(iso3, matched_term.title()) if iso_data else matched_term.title()
            location = {
                "matched_term": matched_term,
                "iso3": iso3,
                "country_name": country_name,
                "is_subregion": is_subregion,
                "source": location_result.get("source"),
            }

            # Check for ambiguity - multiple locations with same name
            if location_result.get("ambiguous") and location_result.get("matches"):
                disambiguation = {
                    "needed": True,
                    "query_term": matched_term,
                    "options": location_result["matches"],
                    "count": len(location_result["matches"])
                }

    hints = {
        "original_query": query,
        "viewport": viewport,  # Pass through for downstream use
        "show_borders": show_borders if show_borders.get("is_show_borders") else None,  # Display geometry without data
        "navigation": navigation,  # Navigation intent with multiple locations
        "topics": extract_topics(query),
        "regions": resolve_regions(query),
        "location": location,  # Single location resolution (city->country or direct country)
        "disambiguation": disambiguation,  # If multiple locations matched, need user clarification
        "time": detect_time_patterns(query),
        "reference_lookup": detect_reference_lookup(query),
        "derived_intent": detect_derived_intent(query),
    }

    # Build summary for LLM context injection
    summary_parts = []

    # Navigation intent takes priority
    if navigation:
        loc_names = [loc.get("matched_term", loc.get("loc_id", "?")) for loc in navigation["locations"]]
        summary_parts.append(f"NAVIGATION: Show {navigation['count']} locations: {', '.join(loc_names[:5])}")

    if hints["topics"]:
        summary_parts.append(f"Topics detected: {', '.join(hints['topics'])}")

    if hints["regions"]:
        region_names = [r["match"] for r in hints["regions"]]
        summary_parts.append(f"Regions mentioned: {', '.join(region_names)}")

    # Add location resolution to summary - critical for city->country resolution
    if location and not navigation:
        if disambiguation:
            # Multiple matches - note ambiguity in summary
            summary_parts.append(f"AMBIGUOUS: '{location['matched_term']}' matches {disambiguation['count']} locations")
        elif location["is_subregion"]:
            summary_parts.append(f"Location: '{location['matched_term']}' -> {location['country_name']} ({location['iso3']})")
        else:
            summary_parts.append(f"Location: {location['country_name']} ({location['iso3']})")

    if hints["time"]["is_time_series"]:
        if hints["time"]["year_start"] and hints["time"]["year_end"]:
            summary_parts.append(f"Time range: {hints['time']['year_start']}-{hints['time']['year_end']}")
        else:
            summary_parts.append("Time series requested (trend/historical)")

    if hints["reference_lookup"]:
        summary_parts.append(f"Reference lookup: {hints['reference_lookup']['type']}")

    if hints["derived_intent"]:
        summary_parts.append(f"Derived calculation: {hints['derived_intent']['type']}")

    hints["summary"] = "; ".join(summary_parts) if summary_parts else None

    return hints


def build_tier3_context(hints: dict) -> str:
    """
    Build Tier 3 (Just-in-Time) context string from preprocessor hints.

    This is injected into the LLM messages as additional context.
    """
    context_parts = []

    # Add summary if present
    if hints.get("summary"):
        context_parts.append(f"[Preprocessor hints: {hints['summary']}]")

    # Add viewport context - helps LLM understand what level user is viewing
    viewport = hints.get("viewport")
    if viewport:
        admin_level = viewport.get("adminLevel", 0)
        level_names = {0: "countries", 1: "states/provinces", 2: "counties/districts", 3: "subdivisions"}
        level_name = level_names.get(admin_level, f"level {admin_level}")
        context_parts.append(f"[VIEWPORT: User is viewing at {level_name} level]")

    # Check for disambiguation needed FIRST - if ambiguous, LLM should ask for clarification
    disambiguation = hints.get("disambiguation")
    if disambiguation and disambiguation.get("needed"):
        options = disambiguation.get("options", [])
        term = disambiguation.get("query_term", "location")

        # Format options for LLM to present to user
        option_strs = []
        for i, opt in enumerate(options[:5], 1):  # Limit to 5 options
            loc_id = opt.get("loc_id", "")
            country = opt.get("country_name", opt.get("iso3", ""))
            option_strs.append(f"{i}. {opt.get('matched_term', term).title()} in {country} ({loc_id})")

        context_parts.append(
            f"[DISAMBIGUATION REQUIRED: '{term}' matches {len(options)} locations. "
            f"Ask user to clarify which one:\n" + "\n".join(option_strs) + "]"
        )
        # When disambiguation needed, don't add location context - let LLM ask first
        return "\n".join(context_parts)

    # Add location resolution - critical for city->country data queries
    location = hints.get("location")
    if location:
        if location.get("is_subregion"):
            context_parts.append(
                f"[LOCATION RESOLUTION: '{location['matched_term']}' is in {location['country_name']}. "
                f"Use loc_id={location['iso3']} for data queries about {location['matched_term']}]"
            )
        else:
            context_parts.append(
                f"[LOCATION: {location['country_name']} (loc_id={location['iso3']})]"
            )

    # Add resolved region details
    if hints.get("regions"):
        for region in hints["regions"][:3]:  # Limit to 3 regions
            context_parts.append(
                f"Region '{region['match']}' = {region['grouping']} "
                f"({region['count']} countries)"
            )

    # Add time context
    if hints.get("time", {}).get("is_time_series"):
        time = hints["time"]
        if time.get("year_start") and time.get("year_end"):
            context_parts.append(
                f"User wants data from {time['year_start']} to {time['year_end']}"
            )

    return "\n".join(context_parts) if context_parts else ""


def build_tier4_context(hints: dict) -> str:
    """
    Build Tier 4 (Reference) context string from preprocessor hints.

    This is injected when reference lookups are detected.
    If country_data is available, returns the specific answer directly.
    """
    ref_lookup = hints.get("reference_lookup")
    if not ref_lookup:
        return ""

    ref_type = ref_lookup["type"]

    # If we have specific country data, return it directly for the LLM to use
    country_data = ref_lookup.get("country_data")
    if country_data:
        formatted = country_data.get("formatted", "")
        return f"[REFERENCE ANSWER: {formatted}]"

    # Otherwise, provide general reference info
    content = ref_lookup.get("content")

    if ref_type == "sdg" and content:
        # Format SDG reference
        goal = content.get("goal", {})
        parts = [
            f"SDG {goal.get('number')}: {goal.get('name')}",
            f"Full title: {goal.get('full_title')}",
            f"Description: {goal.get('description')}",
        ]
        if goal.get("targets"):
            parts.append("Targets:")
            for target in goal["targets"][:5]:  # Limit targets
                parts.append(f"  {target['id']}: {target['text']}")
        return "\n".join(parts)

    elif ref_type == "data_source" and content:
        # Format data source reference
        about = content.get("about", {})
        this_dataset = content.get("this_dataset", {})
        parts = [
            f"Data Source: {about.get('name', 'Unknown')}",
            f"Publisher: {about.get('publisher', 'Unknown')}",
            f"URL: {about.get('url', 'N/A')}",
            f"License: {about.get('license', 'Unknown')}",
        ]
        if about.get("history"):
            parts.append(f"Background: {about['history'][:200]}...")
        if this_dataset.get("focus"):
            parts.append(f"Focus: {this_dataset['focus']}")
        return "\n".join(parts)

    elif ref_type == "capital":
        return "[Reference: Country capital data available. Ask about a specific country.]"

    elif ref_type == "currency":
        return "[Reference: Currency data for 215 countries available from World Factbook. Ask about a specific country.]"

    elif ref_type == "language":
        return "[Reference: Language data for 200+ countries available from World Factbook. Ask about a specific country.]"

    elif ref_type == "timezone":
        return "[Reference: Timezone data for 200+ countries available from World Factbook. Ask about a specific country.]"

    elif ref_type in ["country_info", "economy_info", "government_info", "trade_info"]:
        # These already have country_data with formatted output
        return "[Reference: Detailed country information available from World Factbook.]"

    return ""
