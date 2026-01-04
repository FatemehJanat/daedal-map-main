"""
Scrape CIA World Factbook 2025 Archive for additional metrics not in main scraper.

This scraper targets:
1. Comparison fields we currently skip (alcohol, tobacco, electricity, energy, heliports)
2. Numeric data from individual country pages (military, health, literacy, etc.)

Usage:
    python scrape_world_factbook_extras.py
"""

import requests
import re
import json
import time
import html
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import pycountry

# Base URLs
BASE_URL = "https://www.cia.gov/the-world-factbook/about/archives/2025"
PAGE_DATA_URL = f"{BASE_URL}/page-data"

# Output path
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map/data_converters/world_factbook_archive")
OUTPUT_FILE = OUTPUT_DIR / "world_factbook_extras_scraped.json"


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


def parse_number(text: str) -> Optional[float]:
    """Extract number from text, handling various formats."""
    if not text:
        return None

    text = text.strip()
    text = text.replace(',', '')
    text = text.replace('$', '')

    # Handle negative values
    negative = text.startswith('-') or text.startswith('(')
    text = text.replace('-', '').replace('(', '').replace(')', '')

    # Handle suffixes
    multiplier = 1
    if 'trillion' in text.lower():
        multiplier = 1e12
        text = re.sub(r'\s*trillion\s*', '', text, flags=re.IGNORECASE)
    elif 'billion' in text.lower():
        multiplier = 1e9
        text = re.sub(r'\s*billion\s*', '', text, flags=re.IGNORECASE)
    elif 'million' in text.lower():
        multiplier = 1e6
        text = re.sub(r'\s*million\s*', '', text, flags=re.IGNORECASE)

    # Extract number
    match = re.search(r'(\d+\.?\d*)', text)
    if match:
        try:
            value = float(match.group(1)) * multiplier
            return -value if negative else value
        except ValueError:
            return None
    return None


def parse_year(text: str) -> Optional[int]:
    """Extract year from text like '2024 est.' or '2023'."""
    if not text:
        return None
    match = re.search(r'(20\d{2})', text)
    if match:
        return int(match.group(1))
    return None


def parse_percentage(text: str) -> Optional[float]:
    """Extract percentage value from text."""
    if not text:
        return None
    match = re.search(r'(\d+\.?\d*)\s*%', text)
    if match:
        return float(match.group(1))
    return None


# ============================================================================
# COMPARISON TABLE SCRAPERS - Fields we currently skip
# ============================================================================

# Additional comparison fields to scrape
EXTRA_COMPARISON_FIELDS = {
    "alcohol-consumption-per-capita": "alcohol_consumption_liters",
    "tobacco-use": "tobacco_use_pct",
    "electricity": "electricity_consumption_kwh",
    "energy-consumption-per-capita": "energy_per_capita_btu",
    "heliports": "heliports",
    "health-expenditure": "health_expenditure_pct_gdp",
    "literacy": "literacy_rate_pct",
    "military-expenditures": "military_expenditure_pct_gdp",
    "railways": "railways_km",
    "hospital-bed-density": "hospital_beds_per_1000",
    "physician-density": "physicians_per_1000",
    "drinking-water-source": "drinking_water_access_pct",
    "sanitation-facility-access": "sanitation_access_pct",
    "school-life-expectancy-primary-to-tertiary-education": "school_life_expectancy_years",
}


def fetch_comparison_page(field_slug: str) -> Optional[str]:
    """Fetch the country comparison page for a given field."""
    url = f"{BASE_URL}/field/{field_slug}/country-comparison/"
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.text
        return None
    except Exception as e:
        print(f"  Error fetching {field_slug}: {e}")
        return None


def parse_comparison_table(html_content: str, metric_name: str) -> List[Dict]:
    """Parse comparison table HTML and extract data."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_content, 'html.parser')
    results = []

    rows = soup.find_all('tr')
    for row in rows:
        cells = row.find_all(['td', 'th'])
        if len(cells) >= 3:
            try:
                # Find country name
                country_link = row.find('a')
                if country_link:
                    country_name = country_link.get_text(strip=True)
                else:
                    country_name = cells[1].get_text(strip=True) if len(cells) > 1 else None

                if not country_name or country_name.lower() in ['country', 'name', 'rank']:
                    continue

                # Get value and date
                value_text = cells[2].get_text(strip=True) if len(cells) > 2 else None
                date_text = cells[3].get_text(strip=True) if len(cells) > 3 else None

                value = parse_number(value_text)
                year = parse_year(date_text) or parse_year(value_text) or 2024

                if value is not None:
                    loc_id = normalize_country_name(country_name)
                    if loc_id:
                        results.append({
                            'loc_id': loc_id,
                            'metric': metric_name,
                            'value': value,
                            'year': year,
                        })
            except Exception:
                continue

    return results


# ============================================================================
# COUNTRY PAGE SCRAPERS - Extract additional fields from individual pages
# ============================================================================

def name_to_slug(name: str) -> str:
    """Convert country name to URL slug."""
    slug = name.lower().strip()
    slug = slug.replace("'", "")
    slug = slug.replace("(", "").replace(")", "")
    slug = slug.replace(",", "")
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug


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


# Field extraction functions for country page data
COUNTRY_PAGE_EXTRACTORS = {}


def extractor(field_name: str):
    """Decorator to register field extractors."""
    def decorator(func):
        COUNTRY_PAGE_EXTRACTORS[field_name] = func
        return func
    return decorator


@extractor("Military expenditures")
def extract_military_expenditures(data: str) -> List[Dict]:
    """Extract military expenditure as % of GDP."""
    results = []
    text = clean_html(data)

    # Pattern: X.X% of GDP (YYYY est.)
    pattern = r'(\d+\.?\d*)\s*%\s*of\s*GDP\s*\((\d{4})\s*est\.\)'
    matches = re.findall(pattern, text, re.IGNORECASE)

    for value, year in matches:
        results.append({
            'metric': 'military_expenditure_pct_gdp',
            'value': float(value),
            'year': int(year)
        })

    return results


@extractor("Health expenditure")
def extract_health_expenditure(data: str) -> List[Dict]:
    """Extract health expenditure as % of GDP."""
    results = []
    text = clean_html(data)

    # Pattern: X.X% of GDP (YYYY)
    pattern = r'(\d+\.?\d*)\s*%\s*(?:of\s*GDP)?\s*\((\d{4})\)?'
    matches = re.findall(pattern, text)

    for value, year in matches:
        results.append({
            'metric': 'health_expenditure_pct_gdp',
            'value': float(value),
            'year': int(year)
        })

    return results


@extractor("Literacy")
def extract_literacy(data: str) -> List[Dict]:
    """Extract literacy rate."""
    results = []
    text = clean_html(data)

    # Look for total population literacy rate
    pattern = r'total\s+population\s*:\s*(\d+\.?\d*)\s*%'
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        # Try to find year
        year_match = re.search(r'\((\d{4})\)', text)
        year = int(year_match.group(1)) if year_match else 2020

        results.append({
            'metric': 'literacy_rate_pct',
            'value': float(match.group(1)),
            'year': year
        })

    return results


@extractor("Hospital bed density")
def extract_hospital_beds(data: str) -> List[Dict]:
    """Extract hospital bed density per 1000 population."""
    results = []
    text = clean_html(data)

    # Pattern: X.X beds/1,000 population (YYYY)
    pattern = r'(\d+\.?\d*)\s*beds?/\s*1[,.]?000\s*population\s*\((\d{4})\)'
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        results.append({
            'metric': 'hospital_beds_per_1000',
            'value': float(match.group(1)),
            'year': int(match.group(2))
        })

    return results


@extractor("Physician density")
def extract_physicians(data: str) -> List[Dict]:
    """Extract physician density per 1000 population."""
    results = []
    text = clean_html(data)

    # Pattern: X.X physicians/1,000 population (YYYY)
    pattern = r'(\d+\.?\d*)\s*physicians?/\s*1[,.]?000\s*population\s*\((\d{4})\)'
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        results.append({
            'metric': 'physicians_per_1000',
            'value': float(match.group(1)),
            'year': int(match.group(2))
        })

    return results


@extractor("Drinking water source")
def extract_drinking_water(data: str) -> List[Dict]:
    """Extract drinking water access percentage."""
    results = []
    text = clean_html(data)

    # Look for total population access
    pattern = r'total\s*:\s*(\d+\.?\d*)\s*%\s*of\s*population\s*\((\d{4})\)'
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        results.append({
            'metric': 'drinking_water_access_pct',
            'value': float(match.group(1)),
            'year': int(match.group(2))
        })

    return results


@extractor("Sanitation facility access")
def extract_sanitation(data: str) -> List[Dict]:
    """Extract sanitation access percentage."""
    results = []
    text = clean_html(data)

    # Look for total population access
    pattern = r'total\s*:\s*(\d+\.?\d*)\s*%\s*of\s*population\s*\((\d{4})\)'
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        results.append({
            'metric': 'sanitation_access_pct',
            'value': float(match.group(1)),
            'year': int(match.group(2))
        })

    return results


@extractor("Urbanization")
def extract_urbanization(data: str) -> List[Dict]:
    """Extract urbanization rate."""
    results = []
    text = clean_html(data)

    # Urban population percentage
    pattern = r'urban\s+population\s*:\s*(\d+\.?\d*)\s*%.*?\((\d{4})\)'
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        results.append({
            'metric': 'urban_population_pct',
            'value': float(match.group(1)),
            'year': int(match.group(2))
        })

    # Urbanization rate
    rate_pattern = r'rate\s+of\s+urbanization\s*:\s*(\-?\d+\.?\d*)\s*%.*?\((\d{4})'
    rate_match = re.search(rate_pattern, text, re.IGNORECASE)

    if rate_match:
        results.append({
            'metric': 'urbanization_rate_pct',
            'value': float(rate_match.group(1)),
            'year': int(rate_match.group(2))
        })

    return results


@extractor("Population below poverty line")
def extract_poverty(data: str) -> List[Dict]:
    """Extract poverty rate."""
    results = []
    text = clean_html(data)

    # Pattern: XX.X% (YYYY est.)
    pattern = r'(\d+\.?\d*)\s*%\s*\((\d{4})'
    match = re.search(pattern, text)

    if match:
        results.append({
            'metric': 'poverty_rate_pct',
            'value': float(match.group(1)),
            'year': int(match.group(2))
        })

    return results


@extractor("Electricity access")
def extract_electricity_access(data: str) -> List[Dict]:
    """Extract electricity access percentage."""
    results = []
    text = clean_html(data)

    # Total population access
    pattern = r'electrification\s*-\s*total\s+population\s*:\s*(\d+\.?\d*)\s*%\s*\((\d{4})\)'
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        results.append({
            'metric': 'electricity_access_pct',
            'value': float(match.group(1)),
            'year': int(match.group(2))
        })

    return results


@extractor("Remittances")
def extract_remittances(data: str) -> List[Dict]:
    """Extract remittances as % of GDP."""
    results = []
    text = clean_html(data)

    # Pattern: X.XX% of GDP (YYYY est.)
    pattern = r'(\d+\.?\d*)\s*%\s*of\s*GDP\s*\((\d{4})'
    matches = re.findall(pattern, text, re.IGNORECASE)

    for value, year in matches:
        results.append({
            'metric': 'remittances_pct_gdp',
            'value': float(value),
            'year': int(year)
        })

    return results


@extractor("Budget")
def extract_budget(data: str) -> List[Dict]:
    """Extract budget revenues and expenditures."""
    results = []
    text = clean_html(data)

    # Revenues
    rev_pattern = r'revenues\s*:\s*\$?([\d,.]+)\s*(billion|million|trillion)?'
    rev_match = re.search(rev_pattern, text, re.IGNORECASE)

    if rev_match:
        value = float(rev_match.group(1).replace(',', ''))
        unit = rev_match.group(2)
        if unit:
            if 'trillion' in unit.lower():
                value *= 1e12
            elif 'billion' in unit.lower():
                value *= 1e9
            elif 'million' in unit.lower():
                value *= 1e6

        year_match = re.search(r'\((\d{4})', text)
        year = int(year_match.group(1)) if year_match else 2023

        results.append({
            'metric': 'budget_revenues',
            'value': value,
            'year': year
        })

    # Expenditures
    exp_pattern = r'expenditures\s*:\s*\$?([\d,.]+)\s*(billion|million|trillion)?'
    exp_match = re.search(exp_pattern, text, re.IGNORECASE)

    if exp_match:
        value = float(exp_match.group(1).replace(',', ''))
        unit = exp_match.group(2)
        if unit:
            if 'trillion' in unit.lower():
                value *= 1e12
            elif 'billion' in unit.lower():
                value *= 1e9
            elif 'million' in unit.lower():
                value *= 1e6

        year_match = re.search(r'\((\d{4})', text)
        year = int(year_match.group(1)) if year_match else 2023

        results.append({
            'metric': 'budget_expenditures',
            'value': value,
            'year': year
        })

    return results


@extractor("GDP (official exchange rate)")
def extract_gdp_nominal(data: str) -> List[Dict]:
    """Extract nominal GDP."""
    results = []
    text = clean_html(data)

    # Pattern: $X.XXX trillion/billion (YYYY est.)
    pattern = r'\$?([\d,.]+)\s*(trillion|billion|million)\s*\((\d{4})'
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        value = float(match.group(1).replace(',', ''))
        unit = match.group(2).lower()
        if 'trillion' in unit:
            value *= 1e12
        elif 'billion' in unit:
            value *= 1e9
        elif 'million' in unit:
            value *= 1e6

        results.append({
            'metric': 'gdp_nominal',
            'value': value,
            'year': int(match.group(3))
        })

    return results


@extractor("Railways")
def extract_railways(data: str) -> List[Dict]:
    """Extract railway length in km."""
    results = []
    text = clean_html(data)

    # Pattern: total: X,XXX km
    pattern = r'total\s*:\s*([\d,]+)\s*km'
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        year_match = re.search(r'\((\d{4})\)', text)
        year = int(year_match.group(1)) if year_match else 2022

        results.append({
            'metric': 'railways_km',
            'value': float(match.group(1).replace(',', '')),
            'year': year
        })

    return results


@extractor("Ports")
def extract_ports(data: str) -> List[Dict]:
    """Extract number of major ports."""
    results = []
    text = clean_html(data)

    # Count port entries (crude but works)
    port_pattern = r'<strong>([^<]+)</strong>'
    ports = re.findall(port_pattern, data)
    port_count = len([p for p in ports if p and not any(x in p.lower() for x in ['total', 'major', 'container'])])

    if port_count > 0:
        results.append({
            'metric': 'major_ports_count',
            'value': port_count,
            'year': 2024
        })

    return results


@extractor("Irrigated land")
def extract_irrigated_land(data: str) -> List[Dict]:
    """Extract irrigated land area."""
    results = []
    text = clean_html(data)

    # Pattern: X,XXX sq km (YYYY)
    pattern = r'([\d,]+)\s*sq\s*km\s*\((\d{4})\)'
    match = re.search(pattern, text)

    if match:
        results.append({
            'metric': 'irrigated_land_sq_km',
            'value': float(match.group(1).replace(',', '')),
            'year': int(match.group(2))
        })

    return results


@extractor("Total renewable water resources")
def extract_water_resources(data: str) -> List[Dict]:
    """Extract total renewable water resources."""
    results = []
    text = clean_html(data)

    # Pattern: X.XX billion/million cubic meters
    pattern = r'([\d,.]+)\s*(billion|million)?\s*cubic\s*meters'
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        value = float(match.group(1).replace(',', ''))
        unit = match.group(2)
        if unit and 'billion' in unit.lower():
            value *= 1e9
        elif unit and 'million' in unit.lower():
            value *= 1e6

        results.append({
            'metric': 'renewable_water_cu_m',
            'value': value,
            'year': 2020  # Usually static
        })

    return results


def extract_country_page_data(json_data: Dict, country_info: Dict) -> List[Dict]:
    """Extract all extra metrics from a country's page data."""
    results = []

    try:
        data = json_data.get('result', {}).get('data', {})
        fields_data = data.get('fields', {})
        fields = fields_data.get('nodes', [])

        for field in fields:
            field_name = field.get('name', '')
            field_data = field.get('data', '')

            if field_name in COUNTRY_PAGE_EXTRACTORS:
                extractor_func = COUNTRY_PAGE_EXTRACTORS[field_name]
                extracted = extractor_func(field_data)

                for item in extracted:
                    item['loc_id'] = country_info['iso3']
                    results.append(item)

    except Exception as e:
        print(f"  Error extracting from {country_info['name']}: {e}")

    return results


# ============================================================================
# MAIN SCRAPING LOGIC
# ============================================================================

def scrape_comparison_fields() -> List[Dict]:
    """Scrape extra comparison table fields."""
    all_data = []

    print("Scraping comparison table fields...")
    print("=" * 60)

    for field_slug, metric_name in EXTRA_COMPARISON_FIELDS.items():
        print(f"  Fetching {field_slug}...")
        html_content = fetch_comparison_page(field_slug)

        if html_content:
            data = parse_comparison_table(html_content, metric_name)
            print(f"    Got {len(data)} records")
            all_data.extend(data)
        else:
            print(f"    Not available")

        time.sleep(0.3)

    return all_data


def scrape_country_pages() -> List[Dict]:
    """Scrape extra fields from individual country pages."""
    all_data = []

    print("\nScraping individual country pages...")
    print("=" * 60)

    countries = get_country_list()
    print(f"Found {len(countries)} countries")

    for i, country in enumerate(countries):
        if not country['iso3']:
            continue

        if (i + 1) % 20 == 0:
            print(f"  Processing {i + 1}/{len(countries)}...")

        json_data = fetch_country_json(country['slug'])
        if json_data:
            data = extract_country_page_data(json_data, country)
            all_data.extend(data)

        time.sleep(0.2)

    return all_data


def main():
    print("=" * 60)
    print("CIA World Factbook EXTRAS Scraper")
    print("=" * 60)
    print()

    all_data = []

    # Scrape comparison fields
    comparison_data = scrape_comparison_fields()
    all_data.extend(comparison_data)

    # Scrape country pages
    country_data = scrape_country_pages()
    all_data.extend(country_data)

    # Save results
    if all_data:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, indent=2, ensure_ascii=False)

        print()
        print("=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Total records: {len(all_data)}")
        print(f"Output: {OUTPUT_FILE}")

        # Metrics summary
        metrics = {}
        for row in all_data:
            m = row.get('metric', 'unknown')
            metrics[m] = metrics.get(m, 0) + 1

        print(f"\nMetrics ({len(metrics)}):")
        for m, count in sorted(metrics.items(), key=lambda x: -x[1]):
            print(f"  {m}: {count}")
    else:
        print("No data scraped!")


if __name__ == '__main__':
    main()
