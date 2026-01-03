"""
Build correct field mappings from scan results.

This script:
1. Reads field_id_scan_results.json
2. Maps our internal metric keys to the scanned titles
3. Generates updated world_factbook_field_mappings.json
"""

import json
import re
from typing import Dict, List, Optional

# Mapping from our internal metric key to possible title patterns
# These patterns will match against the normalized scan titles
METRIC_TITLE_PATTERNS = {
    # 51 Unique metrics (world_factbook)
    "airports": ["airports"],
    "area_sq_km": ["area"],
    "broadband_subscriptions": ["broadband", "fixed.broadband"],
    "budget_surplus_deficit": ["budget surplus", "budget deficit"],
    "central_bank_discount_rate": ["central bank discount", "discount rate"],
    "commercial_bank_prime_rate": ["commercial bank prime", "prime lending rate"],
    "crude_oil_exports": ["crude oil.export", "oil.export"],
    "crude_oil_imports": ["crude oil.import", "oil.import"],
    "crude_oil_production": ["crude oil.production", "oil.production"],
    "crude_oil_reserves": ["crude oil.proved reserve", "oil.proved reserve", "crude oil.reserve"],
    "electricity_capacity": ["electricity.installed", "installed generating"],
    "electricity_exports": ["electricity.export"],
    "electricity_fossil_pct": ["electricity.fossil", "fossil fuel"],
    "electricity_hydro_pct": ["electricity.hydro", "hydroelectric"],
    "electricity_imports": ["electricity.import"],
    "electricity_nuclear_pct": ["electricity.nuclear", "nuclear fuels"],
    "electricity_renewable_pct": ["electricity.other renewable", "other renewable"],
    "foreign_reserves": ["reserves of foreign", "foreign exchange and gold"],
    "gini_index": ["gini", "distribution of family income"],
    "gross_national_saving": ["gross national saving"],
    "industrial_production_growth": ["industrial production growth"],
    "internet_hosts": ["internet hosts"],
    "internet_users": ["internet users"],
    "labor_force": ["labor force"],
    "market_value_traded_shares": ["market value of publicly traded"],
    "median_age": ["median age"],
    "merchant_marine": ["merchant marine"],
    "military_expenditure_pct": ["military expenditure"],
    "natural_gas_consumption": ["natural gas.consumption"],
    "natural_gas_exports": ["natural gas.export"],
    "natural_gas_imports": ["natural gas.import"],
    "natural_gas_production": ["natural gas.production"],
    "natural_gas_reserves": ["natural gas.proved reserve"],
    "net_migration_rate": ["net migration rate"],
    "railways_km": ["railways", "railroad"],
    "refined_petroleum_consumption": ["refined petroleum products.consumption", "refined petroleum.consumption"],
    "refined_petroleum_exports": ["refined petroleum products.export", "refined petroleum.export"],
    "refined_petroleum_imports": ["refined petroleum products.import", "refined petroleum.import"],
    "refined_petroleum_production": ["refined petroleum products.production", "refined petroleum.production"],
    "roadways_km": ["roadways", "highways"],
    "stock_broad_money": ["stock of broad money", "broad money"],
    "stock_domestic_credit": ["stock of domestic credit", "domestic credit"],
    "stock_fdi_abroad": ["stock of direct foreign investment.abroad", "fdi.abroad"],
    "stock_fdi_at_home": ["stock of direct foreign investment.at home", "fdi.at home"],
    "stock_narrow_money": ["stock of narrow money", "narrow money"],
    "taxes_revenue_pct_gdp": ["taxes and other revenues"],
    "telephones_fixed": ["telephones.main lines", "telephones.fixed"],
    "telephones_mobile": ["telephones.mobile", "telephones.cellular"],
    "unemployment_rate": ["unemployment rate"],
    "waterways_km": ["waterways"],
    "youth_unemployment": ["unemployment, youth", "youth unemployment"],

    # 27 Overlap metrics (world_factbook_overlap)
    "birth_rate": ["birth rate"],
    "child_underweight": ["children under the age of 5 years underweight", "children under.weight"],
    "co2_emissions": ["carbon dioxide emission", "co2 emission"],
    "current_account_balance": ["current account balance"],
    "death_rate": ["death rate"],
    "education_expenditure": ["education expenditure"],
    "electricity_consumption": ["electricity.consumption"],
    "electricity_production": ["electricity.production"],
    "exports": ["^exports$"],  # Exact match to avoid matching crude oil exports
    "external_debt": ["external debt", "debt.external"],
    "fertility_rate": ["fertility rate", "total fertility rate"],
    "gdp_growth_rate": ["gdp.real growth", "real gdp growth"],
    "gdp_per_capita_ppp": ["gdp.per capita", "real gdp per capita"],
    "gdp_ppp": ["gdp (purchasing power parity)"],
    "health_expenditures": ["health expenditure"],
    "hiv_deaths": ["hiv.aids.death", "aids.death"],
    "hiv_living": ["hiv.aids.people living", "people living with hiv"],
    "hiv_prevalence": ["hiv.aids.adult prevalence", "hiv.prevalence"],
    "imports": ["^imports$"],  # Exact match
    "infant_mortality": ["infant mortality"],
    "inflation_rate": ["inflation rate"],
    "life_expectancy": ["life expectancy"],
    "maternal_mortality": ["maternal mortality"],
    "obesity_rate": ["obesity.adult prevalence", "obesity"],
    "pop_growth_rate": ["population growth rate"],
    "population": ["^population$"],  # Exact match
    "public_debt_pct_gdp": ["public debt"],
}

def normalize_title(title: str) -> str:
    """Normalize title for matching."""
    title = title.lower()
    # Replace various dashes, slashes, and separators with dots
    title = re.sub(r'\s*[-:/]+\s*', '.', title)
    # Collapse whitespace
    title = re.sub(r'\s+', ' ', title)
    return title.strip()

def matches_pattern(title: str, patterns: List[str]) -> bool:
    """Check if normalized title matches any of the patterns."""
    norm_title = normalize_title(title)
    for pattern in patterns:
        if pattern.startswith('^') and pattern.endswith('$'):
            # Exact match
            if norm_title == pattern[1:-1]:
                return True
        elif pattern.startswith('^'):
            # Start match
            if norm_title.startswith(pattern[1:]):
                return True
        else:
            # Substring match
            if pattern in norm_title:
                return True
    return False

def build_mappings(scan_results: dict) -> dict:
    """Build field mappings from scan results."""
    mappings = {}

    for metric_key, patterns in METRIC_TITLE_PATTERNS.items():
        mappings[metric_key] = {}

        for year_str, fields in scan_results.items():
            year = int(year_str)

            # Find matching field
            best_match = None
            best_row_count = 0

            for field_id, data in fields.items():
                if matches_pattern(data['title'], patterns):
                    # Prefer rankorder files and higher row counts
                    score = data['row_count']
                    if data['file_type'] == 'rankorder':
                        score += 1000  # Boost rankorder files

                    if score > best_row_count:
                        best_match = field_id
                        best_row_count = score

            if best_match:
                mappings[metric_key][str(year)] = best_match

    return mappings

def main():
    # Load scan results
    with open('field_id_scan_results.json', 'r', encoding='utf-8') as f:
        scan_results = json.load(f)

    # Build mappings
    mappings = build_mappings(scan_results)

    # Add metadata
    output = {
        "_comment": "Field ID mappings across World Factbook editions. Format: metric_name -> {edition_year: field_id}",
        "_note": "2000-2001: descriptive filenames. 2002-2017: 2xxx IDs. 2018-2020: 1xx-3xx IDs",
        "_coverage": "78 total metrics (51 unique + 27 overlap)",
        "_generated_from": "field_id_scan_results.json",
    }
    output.update(mappings)

    # Save to file
    with open('world_factbook_field_mappings_new.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Print summary
    print("Field Mappings Summary")
    print("=" * 60)

    for metric_key, years in mappings.items():
        year_count = len(years)
        year_range = f"{min(years.keys())}-{max(years.keys())}" if years else "NONE"
        print(f"{metric_key}: {year_count} years ({year_range})")

    print(f"\nSaved to world_factbook_field_mappings_new.json")

if __name__ == '__main__':
    main()
