"""
Scrape CIA World Factbook 2025 for reference data (currencies, timezones, languages, etc.)

Extends the static data scraper to capture all available reference fields.

Output: JSON file with all extracted reference data for each country.

Usage:
    python scrape_cia_reference_data.py
"""

import requests
import re
import json
import time
import html
from typing import Dict, List, Optional, Any
from pathlib import Path
import pycountry

# Base URL for the 2025 archive page-data JSON
BASE_URL = "https://www.cia.gov/the-world-factbook/about/archives/2025/page-data"

# Output paths
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map/mapmover/reference")
RAW_OUTPUT = OUTPUT_DIR / "world_factbook_raw_fields.json"


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
        "czech republic": "CZE", "turkey": "TUR", "turkiye": "TUR", "turkey (turkiye)": "TUR",
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


def name_to_slug(name: str) -> str:
    """Convert country name to URL slug."""
    slug = name.lower().strip()
    slug = slug.replace("'", "")
    slug = slug.replace("(", "").replace(")", "")
    slug = slug.replace(",", "")
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug


def clean_html(text: str) -> str:
    """Remove HTML tags and clean up text."""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def get_country_list() -> List[Dict[str, str]]:
    """Get list of countries from area comparison page."""
    url = f"{BASE_URL}/field/area/country-comparison/page-data.json"
    try:
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            print(f"Error fetching country list: {response.status_code}")
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

        print(f"Found {len(countries)} countries")
        return countries

    except Exception as e:
        print(f"Error: {e}")
        return []


def get_field_value(fields: List[Dict], field_name: str) -> Optional[str]:
    """Get field value from fields list by name."""
    for field in fields:
        if field.get('name', '').lower() == field_name.lower():
            return field.get('data', '')
    return None


def fetch_country_data(slug: str) -> Optional[Dict]:
    """Fetch JSON data for a specific country."""
    url = f"{BASE_URL}/countries/{slug}/page-data.json"
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return None
        else:
            print(f"  Error {response.status_code} for {slug}")
            return None
    except Exception as e:
        print(f"  Exception for {slug}: {e}")
        return None


def parse_languages(text: str) -> Dict[str, Any]:
    """Parse languages field."""
    if not text:
        return {}

    clean = clean_html(text)
    result = {"raw": clean}

    # Try to extract primary language(s)
    # Format varies: "English (official)" or "Arabic (official), French, English"
    # Look for (official) markers
    official_match = re.findall(r'([^,;]+?)\s*\(official[^)]*\)', clean, re.IGNORECASE)
    if official_match:
        result["official"] = [lang.strip() for lang in official_match]

    # Extract all mentioned languages (before percentages/notes)
    languages = []
    # Split on common delimiters
    parts = re.split(r'[,;]', clean.split('note:')[0])
    for part in parts:
        # Remove percentages and parentheticals for the language name
        lang = re.sub(r'\s*\([^)]*\)', '', part)
        lang = re.sub(r'\s*\d+\.?\d*%.*', '', lang)
        lang = lang.strip()
        if lang and len(lang) < 50 and not lang.lower().startswith('note'):
            languages.append(lang)

    if languages:
        result["languages"] = languages[:10]  # Cap at 10

    return result


def parse_timezone(text: str) -> Dict[str, Any]:
    """Parse timezone from Capital field."""
    if not text:
        return {}

    clean = clean_html(text)
    result = {}

    # Look for UTC offset pattern
    # "time difference: UTC+5" or "UTC-8 (during Standard Time)"
    utc_match = re.search(r'UTC\s*([+-]?\d+(?::\d+)?)', clean, re.IGNORECASE)
    if utc_match:
        result["utc_offset"] = f"UTC{utc_match.group(1)}"

    # Check for daylight saving time
    if 'daylight saving time' in clean.lower():
        result["has_dst"] = True
        dst_match = re.search(r'daylight saving time\s*:?\s*([+-]\d+)', clean, re.IGNORECASE)
        if dst_match:
            result["dst_adjustment"] = dst_match.group(1)

    # Note about multiple time zones
    multi_match = re.search(r'(\d+)\s*time zones?', clean, re.IGNORECASE)
    if multi_match:
        result["num_timezones"] = int(multi_match.group(1))

    return result


def parse_currency(text: str) -> Dict[str, Any]:
    """Parse currency from exchange rates or currency field."""
    if not text:
        return {}

    clean = clean_html(text)
    result = {"raw": clean[:200]}  # Keep first 200 chars of raw

    # Currency name patterns
    # "US dollars (USD)" or "euros (EUR)" or "Jamaican dollars (JMD)"
    currency_match = re.search(r'([A-Za-z][A-Za-z\s]+?)\s*\(([A-Z]{3})\)', clean)
    if currency_match:
        result["currency_name"] = currency_match.group(1).strip()
        result["currency_code"] = currency_match.group(2)
    else:
        # Try just the code in parentheses
        code_match = re.search(r'\(([A-Z]{3})\)', clean)
        if code_match:
            result["currency_code"] = code_match.group(1)

    return result


def parse_government_type(text: str) -> str:
    """Parse government type."""
    if not text:
        return ""
    clean = clean_html(text)
    # Truncate to reasonable length
    return clean[:200] if len(clean) > 200 else clean


def parse_religions(text: str) -> Dict[str, Any]:
    """Parse religions field."""
    if not text:
        return {}

    clean = clean_html(text)
    result = {"raw": clean[:300]}

    # Extract religions with percentages
    # Pattern: "Muslim 95.6%, Christian 3.2%"
    religion_pattern = re.findall(r'([A-Za-z][A-Za-z\s\-]+?)\s+(\d+\.?\d*)%', clean)
    if religion_pattern:
        result["religions"] = [
            {"name": r[0].strip(), "percent": float(r[1])}
            for r in religion_pattern[:5]  # Top 5
        ]

    return result


def parse_ethnic_groups(text: str) -> Dict[str, Any]:
    """Parse ethnic groups field."""
    if not text:
        return {}

    clean = clean_html(text)
    result = {"raw": clean[:300]}

    # Extract groups with percentages
    group_pattern = re.findall(r'([A-Za-z][A-Za-z\s\-]+?)\s+(\d+\.?\d*)%', clean)
    if group_pattern:
        result["groups"] = [
            {"name": g[0].strip(), "percent": float(g[1])}
            for g in group_pattern[:5]
        ]

    return result


def parse_independence(text: str) -> Dict[str, Any]:
    """Parse independence field."""
    if not text:
        return {}

    clean = clean_html(text)
    result = {"raw": clean[:200]}

    # Look for year
    year_match = re.search(r'\b(1\d{3}|20\d{2})\b', clean)
    if year_match:
        result["year"] = int(year_match.group(1))

    # Look for "from X" pattern
    from_match = re.search(r'from\s+([A-Za-z\s]+?)(?:\)|,|;|$)', clean, re.IGNORECASE)
    if from_match:
        result["from"] = from_match.group(1).strip()

    return result


def parse_flag_description(text: str) -> str:
    """Parse flag description."""
    if not text:
        return ""
    clean = clean_html(text)
    return clean[:500] if len(clean) > 500 else clean


def parse_national_symbol(text: str) -> Dict[str, Any]:
    """Parse national symbol field."""
    if not text:
        return {}

    clean = clean_html(text)
    result = {}

    # Extract national colors
    colors_match = re.search(r'national colors?\s*:?\s*([^;]+)', clean, re.IGNORECASE)
    if colors_match:
        colors_text = colors_match.group(1)
        # Split by comma or "and"
        colors = re.split(r',\s*|\s+and\s+', colors_text)
        result["national_colors"] = [c.strip() for c in colors if c.strip() and len(c.strip()) < 20][:5]

    # Everything before "national colors" is the symbol
    symbol_part = clean.split('national color')[0].strip()
    if symbol_part:
        result["symbol"] = symbol_part[:200]

    return result


def parse_internet(text: str) -> Dict[str, Any]:
    """Parse internet country code field."""
    if not text:
        return {}

    clean = clean_html(text)
    result = {}

    # Look for .xx pattern
    tld_match = re.search(r'\.([a-z]{2,3})\b', clean, re.IGNORECASE)
    if tld_match:
        result["tld"] = f".{tld_match.group(1).lower()}"

    return result


def parse_calling_code(text: str) -> Dict[str, Any]:
    """Parse country calling code."""
    if not text:
        return {}

    clean = clean_html(text)
    result = {}

    # Look for country code pattern
    code_match = re.search(r'country code\s*:?\s*\+?(\d+)', clean, re.IGNORECASE)
    if code_match:
        result["calling_code"] = f"+{code_match.group(1)}"
    else:
        # Try just finding a number
        num_match = re.search(r'\+?(\d{1,4})\b', clean)
        if num_match:
            result["calling_code"] = f"+{num_match.group(1)}"

    return result


def extract_all_reference_data(json_data: Dict, country_info: Dict) -> Dict:
    """Extract all reference data from country JSON."""
    result = {
        'loc_id': country_info['iso3'],
        'country_name': country_info['name'],
    }

    try:
        data = json_data.get('result', {}).get('data', {})
        fields_data = data.get('fields', {})
        fields = fields_data.get('nodes', [])

        # Store all available field names for analysis
        all_field_names = [f.get('name', '') for f in fields]
        result['_available_fields'] = all_field_names

        # Languages
        languages_text = get_field_value(fields, 'Languages')
        if languages_text:
            result['languages'] = parse_languages(languages_text)

        # Capital (for timezone)
        capital_text = get_field_value(fields, 'Capital')
        if capital_text:
            timezone = parse_timezone(capital_text)
            if timezone:
                result['timezone'] = timezone

            # Also extract capital name
            capital_clean = clean_html(capital_text)
            name_match = re.search(r'name\s*:?\s*([^;]+?)(?:\s+geographic|\s*$)', capital_clean, re.IGNORECASE)
            if name_match:
                result['capital_name'] = name_match.group(1).strip()

        # Currency / Exchange rates
        # Try multiple possible field names
        for currency_field in ['Currency', 'Exchange rates']:
            currency_text = get_field_value(fields, currency_field)
            if currency_text:
                currency_data = parse_currency(currency_text)
                if currency_data:
                    result['currency'] = currency_data
                    break

        # Government type
        gov_text = get_field_value(fields, 'Government type')
        if gov_text:
            result['government_type'] = parse_government_type(gov_text)

        # Religions
        religion_text = get_field_value(fields, 'Religions')
        if religion_text:
            result['religions'] = parse_religions(religion_text)

        # Ethnic groups
        ethnic_text = get_field_value(fields, 'Ethnic groups')
        if ethnic_text:
            result['ethnic_groups'] = parse_ethnic_groups(ethnic_text)

        # Independence
        independence_text = get_field_value(fields, 'Independence')
        if independence_text:
            result['independence'] = parse_independence(independence_text)

        # Flag description
        flag_text = get_field_value(fields, 'Flag description')
        if flag_text:
            result['flag_description'] = parse_flag_description(flag_text)

        # National symbol
        symbol_text = get_field_value(fields, 'National symbol(s)')
        if symbol_text:
            result['national_symbol'] = parse_national_symbol(symbol_text)

        # Internet country code
        internet_text = get_field_value(fields, 'Internet country code')
        if internet_text:
            result['internet'] = parse_internet(internet_text)

        # Telephone system (for calling code)
        phone_text = get_field_value(fields, 'Telephones - fixed lines')
        if not phone_text:
            phone_text = get_field_value(fields, 'Communications')
        # Try country code field directly
        code_text = get_field_value(fields, 'Country code')
        if code_text:
            result['calling_code'] = parse_calling_code(code_text)

        # Driving side (if available)
        transport_text = get_field_value(fields, 'Roadways')
        if transport_text and ('left' in transport_text.lower() or 'right' in transport_text.lower()):
            if 'left-hand' in transport_text.lower() or 'drives on the left' in transport_text.lower():
                result['driving_side'] = 'left'
            elif 'right-hand' in transport_text.lower() or 'drives on the right' in transport_text.lower():
                result['driving_side'] = 'right'

        # Legal system
        legal_text = get_field_value(fields, 'Legal system')
        if legal_text:
            result['legal_system'] = clean_html(legal_text)[:200]

        # Executive branch (head of state)
        exec_text = get_field_value(fields, 'Executive branch')
        if exec_text:
            exec_clean = clean_html(exec_text)
            # Try to get chief of state
            chief_match = re.search(r'chief of state\s*:?\s*([^;]+?)(?:head of government|$)', exec_clean, re.IGNORECASE)
            if chief_match:
                result['chief_of_state'] = chief_match.group(1).strip()[:150]

    except Exception as e:
        print(f"  Error extracting data: {e}")
        result['_error'] = str(e)

    return result


def scrape_all_countries() -> List[Dict]:
    """Scrape reference data for all countries."""
    countries = get_country_list()
    if not countries:
        print("No countries found!")
        return []

    all_data = []
    skipped = []
    all_fields_seen = set()

    for i, country in enumerate(countries):
        name = country['name']
        slug = country['slug']
        iso3 = country['iso3']

        print(f"[{i+1}/{len(countries)}] {name} ({iso3 or 'NO CODE'})...")

        if not iso3:
            print(f"  Skipping - no ISO3 code")
            skipped.append(name)
            continue

        json_data = fetch_country_data(slug)
        if json_data:
            ref_data = extract_all_reference_data(json_data, country)

            # Track all field names seen
            if '_available_fields' in ref_data:
                all_fields_seen.update(ref_data['_available_fields'])

            all_data.append(ref_data)

            # Count extracted fields
            extracted = len([k for k in ref_data.keys() if not k.startswith('_')])
            print(f"  OK - {extracted} fields extracted")
        else:
            print(f"  No JSON data")

        time.sleep(0.3)

    if skipped:
        print(f"\nSkipped {len(skipped)} countries (no ISO3): {skipped[:10]}...")

    # Print all unique fields seen
    print(f"\n{'='*60}")
    print(f"ALL FIELD NAMES SEEN ({len(all_fields_seen)}):")
    print("="*60)
    for field in sorted(all_fields_seen):
        print(f"  - {field}")

    return all_data


def summarize_results(data: List[Dict]):
    """Print summary of extracted data."""
    print(f"\n{'='*60}")
    print("EXTRACTION SUMMARY")
    print("="*60)

    field_counts = {}
    for row in data:
        for key in row.keys():
            if not key.startswith('_'):
                field_counts[key] = field_counts.get(key, 0) + 1

    print(f"\nTotal countries: {len(data)}")
    print(f"\nField coverage:")
    for field, count in sorted(field_counts.items(), key=lambda x: -x[1]):
        pct = count / len(data) * 100
        print(f"  {field}: {count} ({pct:.1f}%)")

    # Sample currency codes
    print(f"\nSample currency codes:")
    for row in data[:20]:
        if 'currency' in row and 'currency_code' in row.get('currency', {}):
            print(f"  {row['loc_id']}: {row['currency']['currency_code']}")

    # Sample timezones
    print(f"\nSample timezones:")
    for row in data[:20]:
        if 'timezone' in row and 'utc_offset' in row.get('timezone', {}):
            print(f"  {row['loc_id']}: {row['timezone']['utc_offset']}")


def main():
    print("=" * 60)
    print("CIA World Factbook 2025 - Reference Data Scraper")
    print("=" * 60)
    print()

    all_data = scrape_all_countries()

    if all_data:
        # Save raw JSON
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        with open(RAW_OUTPUT, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, indent=2, ensure_ascii=False)
        print(f"\nSaved {len(all_data)} countries to {RAW_OUTPUT}")

        summarize_results(all_data)

        # Also create simplified lookup files
        create_lookup_files(all_data)
    else:
        print("No data scraped!")


def create_lookup_files(data: List[Dict]):
    """Create simplified lookup JSON files."""

    # Currency lookup: ISO3 -> currency_code
    currencies = {}
    for row in data:
        if 'currency' in row and 'currency_code' in row.get('currency', {}):
            currencies[row['loc_id']] = {
                "code": row['currency']['currency_code'],
                "name": row['currency'].get('currency_name', '')
            }

    currency_file = OUTPUT_DIR / "currencies_scraped.json"
    with open(currency_file, 'w', encoding='utf-8') as f:
        json.dump({
            "_source": "CIA World Factbook 2025",
            "_scraped": "2026-01",
            "_count": len(currencies),
            "currencies": currencies
        }, f, indent=2, ensure_ascii=False)
    print(f"Saved currencies to {currency_file}")

    # Timezone lookup: ISO3 -> utc_offset
    timezones = {}
    for row in data:
        if 'timezone' in row:
            tz = row['timezone']
            timezones[row['loc_id']] = {
                "utc_offset": tz.get('utc_offset', ''),
                "has_dst": tz.get('has_dst', False),
                "num_timezones": tz.get('num_timezones', 1)
            }

    timezone_file = OUTPUT_DIR / "timezones_scraped.json"
    with open(timezone_file, 'w', encoding='utf-8') as f:
        json.dump({
            "_source": "CIA World Factbook 2025",
            "_scraped": "2026-01",
            "_count": len(timezones),
            "timezones": timezones
        }, f, indent=2, ensure_ascii=False)
    print(f"Saved timezones to {timezone_file}")

    # Languages lookup: ISO3 -> languages
    languages = {}
    for row in data:
        if 'languages' in row:
            lang = row['languages']
            languages[row['loc_id']] = {
                "official": lang.get('official', []),
                "languages": lang.get('languages', []),
            }

    language_file = OUTPUT_DIR / "languages_scraped.json"
    with open(language_file, 'w', encoding='utf-8') as f:
        json.dump({
            "_source": "CIA World Factbook 2025",
            "_scraped": "2026-01",
            "_count": len(languages),
            "languages": languages
        }, f, indent=2, ensure_ascii=False)
    print(f"Saved languages to {language_file}")


if __name__ == '__main__':
    main()
