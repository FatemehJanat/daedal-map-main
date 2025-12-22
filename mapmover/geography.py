"""
Geography and regional grouping functions.
Handles country codes, region lookups, and coordinate fallbacks.
"""

import json
import logging
import pandas as pd
from pathlib import Path

# Base directory for file paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Global conversions data cache
CONVERSIONS_DATA = {}

# Cache for populated places capitals lookup
_CAPITALS_CACHE = None

logger = logging.getLogger("mapmover")


def load_conversions():
    """Load conversions.json for regional groupings, country codes, etc."""
    global CONVERSIONS_DATA
    conversions_path = BASE_DIR / "data_pipeline" / "conversions.json"
    if conversions_path.exists():
        try:
            with open(conversions_path, 'r', encoding='utf-8') as f:
                CONVERSIONS_DATA = json.load(f)
                print(f"Loaded conversions.json with {len(CONVERSIONS_DATA.get('regional_groupings', {}))} regional groupings")
        except Exception as e:
            print(f"Warning: Failed to load conversions.json: {e}")
    return CONVERSIONS_DATA


def get_conversions_data():
    """Get the conversions data, loading if necessary."""
    if not CONVERSIONS_DATA:
        load_conversions()
    return CONVERSIONS_DATA


def get_countries_in_region(region_name, query=None, dataset=None):
    """
    Get list of country codes for a region name (e.g., 'Europe', 'EU', 'G7').
    Returns list of ISO 3-letter country codes or empty list if not found.

    Args:
        region_name: The region to look up (e.g., 'Europe', 'Asia', 'G7')
        query: Optional - the user query for logging purposes
        dataset: Optional - the dataset being queried for logging purposes
    """
    if not CONVERSIONS_DATA:
        load_conversions()

    # Check aliases first (e.g., "Europe" -> "WHO_European_Region")
    aliases = CONVERSIONS_DATA.get('region_aliases', {})
    groupings = CONVERSIONS_DATA.get('regional_groupings', {})

    logger.debug(f"Looking up region: '{region_name}'")

    # Try direct match first
    region_key = region_name
    if region_name in aliases:
        region_key = aliases[region_name]
        logger.debug(f"  Alias match: '{region_name}' -> '{region_key}'")

    # Try case-insensitive match
    if region_key not in groupings:
        for alias, key in aliases.items():
            if alias.lower() == region_name.lower():
                region_key = key
                logger.debug(f"  Case-insensitive alias match: '{alias}' -> '{key}'")
                break

    if region_key not in groupings:
        for group_name in groupings.keys():
            if group_name.lower().replace('_', ' ') == region_name.lower().replace('_', ' '):
                region_key = group_name
                logger.debug(f"  Grouping name match: '{group_name}'")
                break

    if region_key in groupings:
        countries = groupings[region_key].get('countries', [])
        logger.debug(f"  Found {len(countries)} countries in '{region_key}'")
        return countries

    # No match found - log this gap for tracking
    logger.warning(f"  No match found for region '{region_name}' (final key: '{region_key}')")
    # Import here to avoid circular imports
    from .logging_analytics import log_missing_region_to_cloud
    log_missing_region_to_cloud(region_name, query=query, dataset=dataset)
    return []


def get_country_names_from_codes(country_codes):
    """Convert ISO 3-letter codes to country names."""
    if not CONVERSIONS_DATA:
        load_conversions()

    iso_codes = CONVERSIONS_DATA.get('iso_country_codes', {})
    names = []
    for code in country_codes:
        if code in iso_codes:
            names.append(iso_codes[code])
        else:
            names.append(code)  # Fallback to code if not found
    return names


def get_limited_geometry_countries():
    """
    Get list of country codes that have limited or no polygon geometry.
    These countries may display as points instead of polygons.
    """
    if not CONVERSIONS_DATA:
        load_conversions()

    limited_geom = CONVERSIONS_DATA.get('limited_geometry_countries', {})
    # The fallback_coordinates dict keys are the country codes (only 3 truly missing)
    return set(limited_geom.get('fallback_coordinates', {}).keys())


def _load_capitals_cache():
    """Load capitals from Populated Places.csv into memory."""
    global _CAPITALS_CACHE
    if _CAPITALS_CACHE is not None:
        return _CAPITALS_CACHE

    try:
        capitals_path = BASE_DIR / "data_pipeline" / "data_cleaned" / "Populated Places.csv"
        if capitals_path.exists():
            df = pd.read_csv(capitals_path)
            # Filter to capitals only
            capitals = df[df['level'] == 'capital']
            # Build lookup by country code
            _CAPITALS_CACHE = {}
            for _, row in capitals.iterrows():
                code = row.get('code')
                if code and pd.notna(code):
                    _CAPITALS_CACHE[code] = {
                        'name': row.get('name'),
                        'lat': row.get('latitude'),
                        'lon': row.get('longitude')
                    }
            logging.info(f"Loaded {len(_CAPITALS_CACHE)} capitals from Populated Places")
        else:
            _CAPITALS_CACHE = {}
            logging.warning("Populated Places.csv not found")
    except Exception as e:
        logging.error(f"Error loading capitals: {e}")
        _CAPITALS_CACHE = {}

    return _CAPITALS_CACHE


def get_fallback_coordinates(country_code, log_missing=True):
    """
    Get fallback coordinates for countries missing from Countries.csv.
    First checks Populated Places capitals, then conversions.json fallback.
    Returns (lat, lon) tuple or None if not found.

    Args:
        country_code: ISO-3 country code
        log_missing: If True, log missing places to Supabase for tracking
    """
    if not country_code:
        return None

    # 1. First try Populated Places capitals cache
    capitals = _load_capitals_cache()
    if country_code in capitals:
        cap = capitals[country_code]
        if cap.get('lat') and cap.get('lon'):
            return (cap['lat'], cap['lon'])

    # 2. Fall back to conversions.json (only 3 countries: COK, NIU, NRU)
    if not CONVERSIONS_DATA:
        load_conversions()

    limited_geom = CONVERSIONS_DATA.get('limited_geometry_countries', {})
    coords_data = limited_geom.get('fallback_coordinates', {})

    if country_code in coords_data:
        coords = coords_data[country_code].get('coords')
        if coords and len(coords) == 2:
            # coords is [lon, lat] format (GeoJSON standard)
            return (coords[1], coords[0])  # Return as (lat, lon)

    # 3. Not found anywhere - log to Supabase if enabled
    if log_missing:
        try:
            from supabase_client import get_supabase_client
            supabase = get_supabase_client()
            if supabase:
                supabase.log_data_quality_issue(
                    issue_type="missing_geometry",
                    name=country_code,
                    metadata={"source": "get_fallback_coordinates"}
                )
        except Exception as e:
            logging.debug(f"Could not log missing geometry: {e}")

    return None


def get_region_patterns():
    """
    Build region pattern dictionary dynamically from conversions.json.
    Returns dict mapping lowercase patterns to normalized region names.
    """
    if not CONVERSIONS_DATA:
        load_conversions()

    patterns = {}

    # Add patterns from regional_groupings
    groupings = CONVERSIONS_DATA.get('regional_groupings', {})
    for group_name in groupings.keys():
        # Convert "WHO_European_Region" to "Europe", "European_Union" to "EU", etc.
        normalized = group_name.replace('_', ' ')
        # Common simplifications
        if 'WHO_' in group_name and '_Region' in group_name:
            # WHO_European_Region -> Europe
            simple = group_name.replace('WHO_', '').replace('_Region', '').replace('_', ' ')
            patterns[simple.lower()] = simple
            patterns[simple.lower().replace(' ', '')] = simple  # "southeast asia" variant
        else:
            patterns[normalized.lower()] = normalized

    # Add patterns from region_aliases
    aliases = CONVERSIONS_DATA.get('region_aliases', {})
    for alias, target in aliases.items():
        patterns[alias.lower()] = alias  # Use the alias as the display name
        # Also add variant without spaces
        patterns[alias.lower().replace(' ', '')] = alias

    # Add some common variants manually
    extra_patterns = {
        "european": "Europe",
        "african": "Africa",
        "asian": "Asia",
        "american": "Americas",
        "scandinavia": "Nordic Countries",
        "scandinavian": "Nordic Countries",
    }
    patterns.update(extra_patterns)

    return patterns


def get_supported_regions_text():
    """
    Generate human-readable list of supported regions for LLM prompt.
    Reads from conversions.json dynamically.
    """
    if not CONVERSIONS_DATA:
        load_conversions()

    groupings = CONVERSIONS_DATA.get('regional_groupings', {})
    aliases = CONVERSIONS_DATA.get('region_aliases', {})

    # Categorize regions
    who_regions = []
    political_groups = []
    sub_regions = []

    for group_name in groupings.keys():
        if 'WHO_' in group_name:
            # Convert to friendly name
            friendly = group_name.replace('WHO_', '').replace('_Region', '').replace('_', ' ')
            who_regions.append(friendly)
        elif group_name in ['G7', 'G20', 'NATO', 'ASEAN', 'BRICS', 'European_Union', 'Arab_League', 'African_Union', 'Commonwealth']:
            friendly = group_name.replace('_', ' ')
            political_groups.append(friendly)
        else:
            friendly = group_name.replace('_', ' ')
            sub_regions.append(friendly)

    # Add aliases that point to different names
    for alias in aliases.keys():
        if alias not in who_regions and alias not in political_groups and alias not in sub_regions:
            # Check where it should go
            if 'EU' in alias or 'Union' in alias:
                if alias not in political_groups:
                    political_groups.append(alias)

    lines = []
    if who_regions:
        lines.append(f"- Continents/WHO Regions: {', '.join(sorted(set(who_regions)))}")
    if political_groups:
        lines.append(f"- Political/Economic: {', '.join(sorted(set(political_groups)))}")
    if sub_regions:
        lines.append(f"- Sub-regions: {', '.join(sorted(set(sub_regions)))}")

    return "\n".join(lines)


# Load conversions at module import
load_conversions()
