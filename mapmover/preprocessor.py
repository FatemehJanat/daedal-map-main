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

# Paths
CONVERSIONS_PATH = Path(__file__).parent / "conversions.json"
REFERENCE_DIR = Path(__file__).parent / "reference"
DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/data")


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
    Build lookup from sub-regions (capitals, major cities) to parent country ISO3.

    This enables hierarchical resolution: Paris -> France, Vancouver -> Canada
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

    # Add major cities not covered by capitals (city -> parent country ISO3)
    major_cities = {
        # North America
        "new york": "USA", "los angeles": "USA", "chicago": "USA", "houston": "USA",
        "miami": "USA", "seattle": "USA", "san francisco": "USA", "boston": "USA",
        "vancouver": "CAN", "toronto": "CAN", "montreal": "CAN", "calgary": "CAN",
        "guadalajara": "MEX", "monterrey": "MEX",
        # Europe
        "milan": "ITA", "naples": "ITA", "florence": "ITA", "venice": "ITA",
        "barcelona": "ESP", "seville": "ESP", "valencia": "ESP",
        "munich": "DEU", "hamburg": "DEU", "frankfurt": "DEU", "cologne": "DEU",
        "marseille": "FRA", "lyon": "FRA", "nice": "FRA",
        "manchester": "GBR", "birmingham": "GBR", "liverpool": "GBR",
        "edinburgh": "GBR", "glasgow": "GBR",
        "saint petersburg": "RUS", "st petersburg": "RUS",
        "rotterdam": "NLD", "antwerp": "BEL",
        # Asia
        "shanghai": "CHN", "hong kong": "CHN", "shenzhen": "CHN", "guangzhou": "CHN",
        "osaka": "JPN", "kyoto": "JPN", "yokohama": "JPN",
        "mumbai": "IND", "bangalore": "IND", "chennai": "IND",
        "kolkata": "IND", "hyderabad": "IND",
        "busan": "KOR", "incheon": "KOR",
        "ho chi minh city": "VNM", "saigon": "VNM",
        "istanbul": "TUR",
        "dubai": "ARE", "abu dhabi": "ARE",
        # South America
        "sao paulo": "BRA", "rio de janeiro": "BRA", "rio": "BRA",
        "medellin": "COL", "cartagena": "COL",
        "cusco": "PER", "arequipa": "PER",
        # Africa
        "cape town": "ZAF", "johannesburg": "ZAF", "durban": "ZAF",
        "casablanca": "MAR", "marrakech": "MAR",
        "alexandria": "EGY", "giza": "EGY",
        "mombasa": "KEN",
        # Oceania
        "sydney": "AUS", "melbourne": "AUS", "brisbane": "AUS", "perth": "AUS",
        "auckland": "NZL", "christchurch": "NZL",
    }
    subregion_to_iso3.update(major_cities)

    _SUBREGION_TO_ISO3_CACHE = subregion_to_iso3
    return subregion_to_iso3


def extract_country_from_query(query: str) -> Optional[tuple]:
    """
    Extract country from query using hierarchical resolution.

    Resolution order:
    1. Direct country name match
    2. Sub-region match (capitals, major cities) -> parent country

    Returns (matched_term, ISO3, is_subregion) tuple, or None if not found.
    The is_subregion flag indicates if resolution came from a city/capital.
    """
    query_lower = query.lower()

    # First try direct country match
    name_to_iso3 = build_name_to_iso3()
    sorted_names = sorted(name_to_iso3.keys(), key=len, reverse=True)

    for name in sorted_names:
        pattern = r'\b' + re.escape(name) + r'\b'
        if re.search(pattern, query_lower):
            iso3 = name_to_iso3[name]
            return (name, iso3, False)  # False = direct country match

    # Fall back to sub-region (capital/city) -> parent country
    subregion_to_iso3 = build_subregion_to_iso3()
    sorted_subregions = sorted(subregion_to_iso3.keys(), key=len, reverse=True)

    for subregion in sorted_subregions:
        pattern = r'\b' + re.escape(subregion) + r'\b'
        if re.search(pattern, query_lower):
            iso3 = subregion_to_iso3[subregion]
            return (subregion, iso3, True)  # True = resolved from subregion

    return None


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
    # Returns (matched_term, ISO3, is_subregion) - is_subregion=True means city->country resolution
    country_match = extract_country_from_query(query)
    if country_match:
        matched_term = country_match[0]
        iso3 = country_match[1]
        is_subregion = country_match[2]
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

    # Currency pattern - use scraped CIA Factbook data
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

    # Language pattern - use scraped CIA Factbook data
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

    # Timezone pattern - use scraped CIA Factbook data
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
# Main Preprocessor Function
# =============================================================================

def preprocess_query(query: str) -> dict:
    """
    Main preprocessor function - extracts all hints from query.

    Returns a hints dict that can be injected into LLM context.
    """
    # Resolve location first - used for both reference lookups and data orders
    location_match = extract_country_from_query(query)
    location = None
    if location_match:
        matched_term, iso3, is_subregion = location_match
        # Get proper country name from ISO3
        iso_data = load_reference_file(REFERENCE_DIR / "iso_codes.json")
        country_name = iso_data.get("iso3_to_name", {}).get(iso3, matched_term.title()) if iso_data else matched_term.title()
        location = {
            "matched_term": matched_term,
            "iso3": iso3,
            "country_name": country_name,
            "is_subregion": is_subregion,  # True if city/capital resolved to country
        }

    hints = {
        "original_query": query,
        "topics": extract_topics(query),
        "regions": resolve_regions(query),
        "location": location,  # Single location resolution (city->country or direct country)
        "time": detect_time_patterns(query),
        "reference_lookup": detect_reference_lookup(query),
        "derived_intent": detect_derived_intent(query),
    }

    # Build summary for LLM context injection
    summary_parts = []

    if hints["topics"]:
        summary_parts.append(f"Topics detected: {', '.join(hints['topics'])}")

    if hints["regions"]:
        region_names = [r["match"] for r in hints["regions"]]
        summary_parts.append(f"Regions mentioned: {', '.join(region_names)}")

    # Add location resolution to summary - critical for city->country resolution
    if location:
        if location["is_subregion"]:
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

    # Add location resolution - critical for city->country data queries
    location = hints.get("location")
    if location:
        if location["is_subregion"]:
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
        return "[Reference: Currency data for 215 countries available from CIA World Factbook. Ask about a specific country.]"

    elif ref_type == "language":
        return "[Reference: Language data for 200+ countries available from CIA World Factbook. Ask about a specific country.]"

    elif ref_type == "timezone":
        return "[Reference: Timezone data for 200+ countries available from CIA World Factbook. Ask about a specific country.]"

    elif ref_type in ["country_info", "economy_info", "government_info", "trade_info"]:
        # These already have country_data with formatted output
        return "[Reference: Detailed country information available from CIA World Factbook.]"

    return ""
