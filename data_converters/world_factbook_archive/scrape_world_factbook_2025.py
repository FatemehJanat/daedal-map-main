"""
Scrape CIA World Factbook 2025 Archive for country comparison data.

This scraper pulls data from the online 2025 archive which contains
historical data with estimates from multiple years (2024 est., 2023 est., etc.)

Usage:
    python scrape_world_factbook_2025.py
"""

import requests
import re
import json
import time
from typing import Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
import pycountry

# Base URL for the 2025 archive
BASE_URL = "https://www.cia.gov/the-world-factbook/about/archives/2025"

# Build country name to ISO3 code mapping
def build_country_mapping() -> Dict[str, str]:
    """Build comprehensive country name to ISO3 mapping."""
    mapping = {}

    # Add all pycountry countries
    for country in pycountry.countries:
        iso3 = country.alpha_3
        mapping[country.name.lower()] = iso3
        if hasattr(country, 'common_name'):
            mapping[country.common_name.lower()] = iso3
        if hasattr(country, 'official_name'):
            mapping[country.official_name.lower()] = iso3

    # CIA Factbook-specific name variations
    cia_overrides = {
        # Common variations
        "united states": "USA",
        "united kingdom": "GBR",
        "russia": "RUS",
        "south korea": "KOR",
        "north korea": "PRK",
        "iran": "IRN",
        "syria": "SYR",
        "venezuela": "VEN",
        "bolivia": "BOL",
        "vietnam": "VNM",
        "laos": "LAO",
        "brunei": "BRN",
        "taiwan": "TWN",
        "hong kong": "HKG",
        "macau": "MAC",
        "palestine": "PSE",
        "ivory coast": "CIV",
        "cote d'ivoire": "CIV",
        "congo, democratic republic of the": "COD",
        "congo, republic of the": "COG",
        "democratic republic of the congo": "COD",
        "republic of the congo": "COG",
        "tanzania": "TZA",
        "cabo verde": "CPV",
        "cape verde": "CPV",
        "timor-leste": "TLS",
        "east timor": "TLS",
        "eswatini": "SWZ",
        "swaziland": "SWZ",
        "north macedonia": "MKD",
        "macedonia": "MKD",
        "czechia": "CZE",
        "czech republic": "CZE",
        "turkey": "TUR",
        "turkiye": "TUR",
        "turkey (turkiye)": "TUR",
        "burma": "MMR",
        "myanmar": "MMR",
        "micronesia, federated states of": "FSM",
        "federated states of micronesia": "FSM",
        "saint kitts and nevis": "KNA",
        "saint lucia": "LCA",
        "saint vincent and the grenadines": "VCT",
        "sao tome and principe": "STP",
        "holy see (vatican city)": "VAT",
        "holy see": "VAT",
        "vatican city": "VAT",
        "gambia, the": "GMB",
        "the gambia": "GMB",
        "bahamas, the": "BHS",
        "the bahamas": "BHS",
        "netherlands, the": "NLD",
        "the netherlands": "NLD",
        "virgin islands": "VIR",
        "british virgin islands": "VGB",
        "u.s. virgin islands": "VIR",
        "marshall islands": "MHL",
        "solomon islands": "SLB",
        "cayman islands": "CYM",
        "cook islands": "COK",
        "falkland islands (islas malvinas)": "FLK",
        "falkland islands": "FLK",
        "faroe islands": "FRO",
        "turks and caicos islands": "TCA",
        "wallis and futuna": "WLF",
        "french polynesia": "PYF",
        "new caledonia": "NCL",
        "american samoa": "ASM",
        "northern mariana islands": "MNP",
        "guam": "GUM",
        "puerto rico": "PRI",
        "bermuda": "BMU",
        "greenland": "GRL",
        "svalbard": "SJM",
        "isle of man": "IMN",
        "jersey": "JEY",
        "guernsey": "GGY",
        "gibraltar": "GIB",
        "aruba": "ABW",
        "curacao": "CUW",
        "sint maarten": "SXM",
        "anguilla": "AIA",
        "montserrat": "MSR",
        "christmas island": "CXR",
        "cocos (keeling) islands": "CCK",
        "norfolk island": "NFK",
        "pitcairn islands": "PCN",
        "niue": "NIU",
        "tokelau": "TKL",
        "south sudan": "SSD",
        "kosovo": "XKS",
        "west bank": "PSE",
        "gaza strip": "PSE",
        "western sahara": "ESH",
        "paracel islands": "CHN",  # Disputed, map to China
        "spratly islands": "CHN",  # Disputed
        "korea, south": "KOR",
        "korea, north": "PRK",
        # Territories and special areas
        "akrotiri and dhekelia": "XAD",  # British Sovereign Base Areas
        "ashmore and cartier islands": "AUS",  # Australia territory
        "clipperton island": "FRA",  # France territory
        "coral sea islands": "AUS",  # Australia territory
        "french southern and antarctic lands": "ATF",
        "jan mayen": "SJM",  # Part of Svalbard and Jan Mayen
        "navassa island": "USA",  # US territory
        "saint barthelemy": "BLM",
        "saint helena, ascension, and tristan da cunha": "SHN",
        "saint martin": "MAF",
        "south georgia and south sandwich islands": "SGS",
        "united states pacific island wildlife refuges": "UMI",
        "wake island": "UMI",  # US Minor Outlying Islands
    }

    # Add overrides (these take priority)
    for name, code in cia_overrides.items():
        mapping[name.lower()] = code

    return mapping

COUNTRY_TO_ISO3 = build_country_mapping()

# Mapping from URL field slug to our internal metric name
# Based on the 59 available country comparison fields
FIELD_MAPPINGS = {
    # Geography
    "area": "area_sq_km",

    # People and Society
    "population": "population",
    "median-age": "median_age",
    "population-growth-rate": "pop_growth_rate",
    "birth-rate": "birth_rate",
    "death-rate": "death_rate",
    "net-migration-rate": "net_migration_rate",
    "maternal-mortality-ratio": "maternal_mortality",
    "infant-mortality-rate": "infant_mortality",
    "life-expectancy-at-birth": "life_expectancy",
    "total-fertility-rate": "fertility_rate",
    "obesity-adult-prevalence-rate": "obesity_rate",
    "alcohol-consumption-per-capita": None,  # New metric, not in our schema
    "tobacco-use": None,  # New metric, not in our schema
    "children-under-the-age-of-5-years-underweight": "child_underweight",
    "education-expenditure": "education_expenditure",

    # Environment
    "carbon-dioxide-emissions": "co2_emissions",

    # Economy
    "real-gdp-purchasing-power-parity": "gdp_ppp",
    "real-gdp-growth-rate": "gdp_growth_rate",
    "real-gdp-per-capita": "gdp_per_capita_ppp",
    "inflation-rate-consumer-prices": "inflation_rate",
    "gdp-composition-by-sector-of-origin": None,  # Complex, skip
    "industrial-production-growth-rate": "industrial_production_growth",
    "labor-force": "labor_force",
    "unemployment-rate": "unemployment_rate",
    "youth-unemployment-rate-ages-15-24": "youth_unemployment",
    "gini-index-coefficient-distribution-of-family-income": "gini_index",
    "public-debt": "public_debt_pct_gdp",
    "taxes-and-other-revenues": "taxes_revenue_pct_gdp",
    "current-account-balance": "current_account_balance",
    "exports": "exports",
    "imports": "imports",
    "reserves-of-foreign-exchange-and-gold": "foreign_reserves",
    "debt-external": "external_debt",

    # Energy
    "electricity": None,  # Need to check sub-fields
    "energy-consumption-per-capita": None,  # New metric

    # Communications
    "telephones-fixed-lines": "telephones_fixed",
    "telephones-mobile-cellular": "telephones_mobile",
    "broadband-fixed-subscriptions": "broadband_subscriptions",

    # Transportation
    "airports": "airports",
    "heliports": None,  # New metric
    "merchant-marine": "merchant_marine",
}

# Track unmapped countries for debugging
UNMAPPED_COUNTRIES = set()

def normalize_country_name(name: str) -> Optional[str]:
    """Convert country name to ISO3 loc_id format.

    Returns ISO3 code (e.g., 'USA', 'GBR', 'CHN') or None if unmapped.
    """
    name_lower = name.lower().strip()

    # Direct lookup
    if name_lower in COUNTRY_TO_ISO3:
        return COUNTRY_TO_ISO3[name_lower]

    # Try fuzzy matching for common patterns
    # Remove "the" prefix
    if name_lower.startswith("the "):
        name_lower = name_lower[4:]
        if name_lower in COUNTRY_TO_ISO3:
            return COUNTRY_TO_ISO3[name_lower]

    # Try with/without commas for reversed names like "Korea, South"
    if ", " in name_lower:
        parts = name_lower.split(", ")
        reversed_name = " ".join(reversed(parts))
        if reversed_name in COUNTRY_TO_ISO3:
            return COUNTRY_TO_ISO3[reversed_name]

    # Track unmapped for debugging
    UNMAPPED_COUNTRIES.add(name)
    return None

def parse_value(value_str: str) -> Optional[float]:
    """Parse a value string into a float."""
    if not value_str:
        return None

    # Remove common formatting
    value_str = value_str.strip()
    value_str = value_str.replace(',', '')
    value_str = value_str.replace('$', '')
    value_str = value_str.replace('%', '')

    # Handle negative values
    negative = value_str.startswith('-') or value_str.startswith('(')
    value_str = value_str.replace('-', '').replace('(', '').replace(')', '')

    # Handle suffixes (trillion, billion, million)
    multiplier = 1
    if 'trillion' in value_str.lower():
        multiplier = 1e12
        value_str = re.sub(r'\s*trillion\s*', '', value_str, flags=re.IGNORECASE)
    elif 'billion' in value_str.lower():
        multiplier = 1e9
        value_str = re.sub(r'\s*billion\s*', '', value_str, flags=re.IGNORECASE)
    elif 'million' in value_str.lower():
        multiplier = 1e6
        value_str = re.sub(r'\s*million\s*', '', value_str, flags=re.IGNORECASE)

    try:
        value = float(value_str) * multiplier
        return -value if negative else value
    except ValueError:
        return None

def parse_year(date_str: str) -> Optional[int]:
    """Extract year from date string like '2024 est.' or '2023'."""
    if not date_str:
        return None

    match = re.search(r'(\d{4})', date_str)
    if match:
        return int(match.group(1))
    return None

def fetch_comparison_page(field_slug: str) -> Optional[str]:
    """Fetch the country comparison page for a given field."""
    url = f"{BASE_URL}/field/{field_slug}/country-comparison/"

    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.text
        else:
            print(f"  Error {response.status_code} for {field_slug}")
            return None
    except Exception as e:
        print(f"  Exception fetching {field_slug}: {e}")
        return None

def parse_comparison_page(html: str, metric_name: str) -> List[Dict]:
    """Parse the HTML and extract country data."""
    soup = BeautifulSoup(html, 'html.parser')
    results = []

    # Find the data table or list
    # The structure varies, so we try multiple approaches

    # Look for table rows
    rows = soup.find_all('tr')

    for row in rows:
        cells = row.find_all(['td', 'th'])
        if len(cells) >= 3:
            # Try to extract: rank, country, value, date
            try:
                # Find country name (usually in a link)
                country_link = row.find('a')
                if country_link:
                    country_name = country_link.get_text(strip=True)
                else:
                    # Fallback: use second cell
                    country_name = cells[1].get_text(strip=True) if len(cells) > 1 else None

                if not country_name:
                    continue

                # Skip header rows
                if country_name.lower() in ['country', 'name', 'rank']:
                    continue

                # Get value (usually third cell)
                value_text = cells[2].get_text(strip=True) if len(cells) > 2 else None

                # Get date (usually fourth cell, but some metrics like area don't have it)
                date_text = cells[3].get_text(strip=True) if len(cells) > 3 else None

                value = parse_value(value_text)
                year = parse_year(date_text)

                # For metrics without dates (like area), use 2024 as default
                if year is None:
                    year = 2024

                if value is not None:
                    loc_id = normalize_country_name(country_name)
                    if loc_id:  # Only add if we got a valid ISO3 code
                        results.append({
                            'loc_id': loc_id,
                            'country_name': country_name,
                            'metric': metric_name,
                            'value': value,
                            'year': year,
                            'factbook_edition': 2025
                        })
            except Exception as e:
                continue

    return results

def scrape_all_metrics() -> List[Dict]:
    """Scrape all available metrics from the 2025 archive."""
    all_data = []

    for field_slug, metric_name in FIELD_MAPPINGS.items():
        if metric_name is None:
            print(f"Skipping {field_slug} (not mapped)")
            continue

        print(f"Fetching {field_slug} -> {metric_name}...")

        html = fetch_comparison_page(field_slug)
        if html:
            data = parse_comparison_page(html, metric_name)
            print(f"  Got {len(data)} records")
            all_data.extend(data)

        # Be nice to the server
        time.sleep(0.5)

    return all_data

def save_results(data: List[Dict], output_path: str):
    """Save scraped data to JSON file."""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(data)} records to {output_path}")

def main():
    print("=" * 60)
    print("CIA World Factbook 2025 Archive Scraper")
    print("=" * 60)
    print()

    # Scrape all metrics
    all_data = scrape_all_metrics()

    if all_data:
        # Save to JSON
        output_path = 'world_factbook_2025_scraped.json'
        save_results(all_data, output_path)

        # Summary stats
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)

        metrics = {}
        years = set()
        countries = set()

        for row in all_data:
            metric = row['metric']
            metrics[metric] = metrics.get(metric, 0) + 1
            years.add(row['year'])
            countries.add(row['loc_id'])

        print(f"\nTotal records: {len(all_data)}")
        print(f"Unique countries: {len(countries)}")
        print(f"Data years: {sorted(years)}")
        print(f"\nMetrics scraped ({len(metrics)}):")
        for m, count in sorted(metrics.items(), key=lambda x: -x[1]):
            print(f"  {m}: {count} records")

        # Report unmapped countries
        if UNMAPPED_COUNTRIES:
            print(f"\n" + "=" * 60)
            print(f"WARNING: {len(UNMAPPED_COUNTRIES)} unmapped countries (skipped)")
            print("=" * 60)
            for name in sorted(UNMAPPED_COUNTRIES):
                print(f"  {name}")
            print("\nAdd these to cia_overrides in build_country_mapping() if needed.")
    else:
        print("No data scraped!")

if __name__ == '__main__':
    main()
