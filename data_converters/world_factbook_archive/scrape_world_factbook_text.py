"""
Scrape CIA World Factbook 2025 Archive for text/descriptive fields.

These are non-numeric fields that provide context and descriptions.
Stored separately to avoid breaking numeric pipelines.

Usage:
    python scrape_world_factbook_text.py
"""

import requests
import re
import json
import time
import html
from typing import Dict, List, Optional, Any
from pathlib import Path
import pycountry

# Base URLs
BASE_URL = "https://www.cia.gov/the-world-factbook/about/archives/2025"
PAGE_DATA_URL = f"{BASE_URL}/page-data"

# Output path
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map/mapmover/reference")
OUTPUT_FILE = OUTPUT_DIR / "world_factbook_text.json"


def build_country_mapping() -> Dict[str, str]:
    """Build comprehensive country name to ISO3 mapping."""
    mapping = {}

    for country in pycountry.countries:
        iso3 = country.alpha_3
        mapping[country.name.lower()] = iso3
        if hasattr(country, 'common_name'):
            mapping[country.common_name.lower()] = iso3
        if hasattr(country, 'official_name'):
            mapping[country.official_name.lower()] = iso3

    # CIA Factbook-specific overrides
    cia_overrides = {
        "united states": "USA", "united kingdom": "GBR", "russia": "RUS",
        "south korea": "KOR", "north korea": "PRK", "iran": "IRN",
        "syria": "SYR", "venezuela": "VEN", "bolivia": "BOL",
        "vietnam": "VNM", "laos": "LAO", "brunei": "BRN",
        "taiwan": "TWN", "hong kong": "HKG", "macau": "MAC",
        "palestine": "PSE", "ivory coast": "CIV", "cote d'ivoire": "CIV",
        "congo, democratic republic of the": "COD", "congo, republic of the": "COG",
        "democratic republic of the congo": "COD", "republic of the congo": "COG",
        "tanzania": "TZA", "cabo verde": "CPV", "cape verde": "CPV",
        "timor-leste": "TLS", "east timor": "TLS", "eswatini": "SWZ",
        "north macedonia": "MKD", "macedonia": "MKD", "czechia": "CZE",
        "czech republic": "CZE", "turkey": "TUR", "turkiye": "TUR",
        "turkey (turkiye)": "TUR",
        "burma": "MMR", "myanmar": "MMR", "micronesia, federated states of": "FSM",
        "federated states of micronesia": "FSM", "saint kitts and nevis": "KNA",
        "saint lucia": "LCA", "saint vincent and the grenadines": "VCT",
        "sao tome and principe": "STP", "holy see (vatican city)": "VAT",
        "holy see": "VAT", "vatican city": "VAT", "gambia, the": "GMB",
        "the gambia": "GMB", "bahamas, the": "BHS", "the bahamas": "BHS",
        "virgin islands": "VIR", "british virgin islands": "VGB",
        "u.s. virgin islands": "VIR", "marshall islands": "MHL",
        "solomon islands": "SLB", "cayman islands": "CYM", "cook islands": "COK",
        "falkland islands (islas malvinas)": "FLK", "falkland islands": "FLK",
        "faroe islands": "FRO", "turks and caicos islands": "TCA",
        "wallis and futuna": "WLF", "french polynesia": "PYF",
        "new caledonia": "NCL", "american samoa": "ASM",
        "northern mariana islands": "MNP", "guam": "GUM", "puerto rico": "PRI",
        "bermuda": "BMU", "greenland": "GRL", "svalbard": "SJM",
        "isle of man": "IMN", "jersey": "JEY", "guernsey": "GGY",
        "gibraltar": "GIB", "aruba": "ABW", "curacao": "CUW",
        "sint maarten": "SXM", "anguilla": "AIA", "montserrat": "MSR",
        "christmas island": "CXR", "cocos (keeling) islands": "CCK",
        "norfolk island": "NFK", "pitcairn islands": "PCN", "niue": "NIU",
        "tokelau": "TKL", "south sudan": "SSD", "kosovo": "XKS",
        "west bank": "PSE", "gaza strip": "PSE", "western sahara": "ESH",
        "korea, south": "KOR", "korea, north": "PRK", "antarctica": "ATA",
        "french southern and antarctic lands": "ATF", "saint barthelemy": "BLM",
        "saint helena, ascension, and tristan da cunha": "SHN",
        "saint martin": "MAF", "south georgia and south sandwich islands": "SGS",
    }

    for name, code in cia_overrides.items():
        mapping[name.lower()] = code

    return mapping


COUNTRY_TO_ISO3 = build_country_mapping()


def normalize_country_name(name: str) -> Optional[str]:
    """Convert country name to ISO3 code."""
    name_lower = name.lower().strip()
    if name_lower in COUNTRY_TO_ISO3:
        return COUNTRY_TO_ISO3[name_lower]

    if name_lower.startswith("the "):
        name_lower = name_lower[4:]
        if name_lower in COUNTRY_TO_ISO3:
            return COUNTRY_TO_ISO3[name_lower]

    if ", " in name_lower:
        parts = name_lower.split(", ")
        reversed_name = " ".join(reversed(parts))
        if reversed_name in COUNTRY_TO_ISO3:
            return COUNTRY_TO_ISO3[reversed_name]

    return None


def clean_html(text: str) -> str:
    """Remove HTML tags and clean up text."""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def name_to_slug(name: str) -> str:
    """Convert country name to URL slug."""
    slug = name.lower().strip()
    slug = slug.replace("'", "")
    slug = slug.replace("(", "").replace(")", "")
    slug = slug.replace(",", "")
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug


# Text fields to extract
TEXT_FIELDS = [
    # Government & Politics
    "Background",
    "Constitution",
    "Executive branch",
    "Legislative branch",
    "Judicial branch",
    "Political parties",
    "Administrative divisions",
    "National holiday",
    "National symbol(s)",
    "National anthem(s)",
    "Flag",

    # Economy
    "Economic overview",
    "Industries",
    "Agricultural products",
    "Exports - commodities",
    "Exports - partners",
    "Imports - commodities",
    "Imports - partners",

    # Society
    "Nationality",
    "Citizenship",

    # International
    "Diplomatic representation in the US",
    "Diplomatic representation from the US",
    "International organization participation",

    # Security
    "Military and security forces",
    "Military - note",
    "Military equipment inventories and acquisitions",
    "Military deployments",
    "Military service age and obligation",
    "Terrorist group(s)",

    # Other
    "Geography - note",
    "People - note",
    "Government - note",
    "Communications - note",
    "Transportation - note",
    "Broadcast media",
    "Illicit drugs",
    "Refugees and internally displaced persons",
    "Trafficking in persons",

    # Space
    "Space program overview",
    "Space agency/agencies",
    "Space launch site(s)",
    "Key space-program milestones",

    # Environment
    "Environmental issues",
    "International environmental agreements",

    # Water features
    "Major aquifers",
    "Major lakes (area sq km)",
    "Major rivers (by length in km)",
    "Major watersheds (area sq km)",
]


def get_country_list() -> List[Dict[str, str]]:
    """Get list of countries from area comparison page."""
    url = f"{PAGE_DATA_URL}/field/area/country-comparison/page-data.json"
    try:
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            return []

        data = response.json()
        countries = []

        result = data.get('result', {})
        result_data = result.get('data', {})
        fields = result_data.get('fields', {})
        nodes = fields.get('nodes', [])

        for entry in nodes:
            place = entry.get('place', {})
            name = place.get('name', '')
            if name:
                slug = name_to_slug(name)
                iso3 = normalize_country_name(name)
                countries.append({
                    'name': name,
                    'slug': slug,
                    'iso3': iso3
                })

        return countries
    except Exception as e:
        print(f"Error getting country list: {e}")
        return []


def fetch_country_json(slug: str) -> Optional[Dict]:
    """Fetch JSON data for a specific country."""
    url = f"{PAGE_DATA_URL}/countries/{slug}/page-data.json"
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception:
        return None


def get_field_value(fields: List[Dict], field_name: str) -> Optional[str]:
    """Get field value from fields list by name."""
    for field in fields:
        if field.get('name', '').lower() == field_name.lower():
            return field.get('data', '')
    return None


def extract_text_fields(json_data: Dict, country_info: Dict) -> Dict[str, str]:
    """Extract all text fields from a country's page data."""
    result = {}

    try:
        data = json_data.get('result', {}).get('data', {})
        fields_data = data.get('fields', {})
        fields = fields_data.get('nodes', [])

        for target_field in TEXT_FIELDS:
            raw_value = get_field_value(fields, target_field)
            if raw_value:
                cleaned = clean_html(raw_value)
                if cleaned:
                    # Convert field name to snake_case key
                    key = target_field.lower()
                    key = re.sub(r'[^\w\s]', '', key)
                    key = re.sub(r'\s+', '_', key)
                    result[key] = cleaned

    except Exception as e:
        print(f"  Error extracting from {country_info['name']}: {e}")

    return result


def main():
    print("=" * 60)
    print("CIA World Factbook TEXT FIELDS Scraper")
    print("=" * 60)
    print()

    print("Getting country list...")
    countries = get_country_list()
    print(f"Found {len(countries)} countries")
    print()

    all_data = {}
    field_counts = {}

    for i, country in enumerate(countries):
        if not country['iso3']:
            continue

        if (i + 1) % 20 == 0:
            print(f"Processing {i + 1}/{len(countries)}...")

        json_data = fetch_country_json(country['slug'])
        if json_data:
            text_fields = extract_text_fields(json_data, country)
            if text_fields:
                all_data[country['iso3']] = text_fields

                # Count fields
                for field in text_fields:
                    field_counts[field] = field_counts.get(field, 0) + 1

        time.sleep(0.2)

    # Save results
    if all_data:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        output = {
            "_source": "CIA World Factbook 2025",
            "_scraped": "2026-01",
            "_count": len(all_data),
            "_fields": list(TEXT_FIELDS),
            "countries": all_data
        }

        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print()
        print("=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Countries processed: {len(all_data)}")
        print(f"Output: {OUTPUT_FILE}")

        print(f"\nFields extracted ({len(field_counts)}):")
        for field, count in sorted(field_counts.items(), key=lambda x: -x[1]):
            print(f"  {field}: {count} countries")
    else:
        print("No data scraped!")


if __name__ == '__main__':
    main()
