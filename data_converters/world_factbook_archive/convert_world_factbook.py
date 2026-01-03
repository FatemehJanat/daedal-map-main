"""
World Factbook Converter

Converts World Factbook HTML data to standardized parquet format.
Supports multiple editions with different HTML structures and field ID schemes.

SPLIT SOURCES:
    world_factbook  - 51 metrics NOT available in other sources (infrastructure, military, energy details)
    world_factbook_overlap - 27 metrics also available in OWID/WHO/IMF/SDG (for time series continuity)

OUTPUT:
    county-map-data/data/world_factbook/all_countries.parquet
    county-map-data/data/world_factbook_overlap/all_countries.parquet

EDITION FORMAT DIFFERENCES:
    | Edition | Format      | Field IDs        | Location              |
    |---------|-------------|------------------|----------------------|
    | 2000    | Text-based  | Descriptive names | fields/airports.html |
    | 2005    | Table-based | 2xxx IDs          | rankorder/2119rank.html |
    | 2010    | Table-based | 2xxx IDs          | fields/2119rank.html |
    | 2015    | Table-based | 2xxx IDs          | fields/2119rank.html |
    | 2020    | Modern HTML | 1xx-3xx IDs       | fields/335rank.html  |

USAGE:
    # Import unique metrics only (recommended first)
    python convert_world_factbook.py --editions 2000,2005,2010,2015,2020 --source-type unique --save

    # Import overlap metrics
    python convert_world_factbook.py --editions 2000,2005,2010,2015,2020 --source-type overlap --save

    # Dry run (default) - preview without saving
    python convert_world_factbook.py --editions 2020 --source-type unique --dry-run

    # List metrics by type
    python convert_world_factbook.py --list-metrics

METRICS:
    51 UNIQUE: military, infrastructure, energy source %, oil/gas details, communications
    27 OVERLAP: demographics, health, basic economy (GDP, trade), CO2 emissions
"""

import os
import re
import json
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime

# =============================================================================
# CONFIGURATION
# =============================================================================

# Base paths
RAW_DATA_BASE = r"C:\Users\Bryan\Desktop\county-map-data\Raw data"
OUTPUT_BASE = r"C:\Users\Bryan\Desktop\county-map-data\data"
GEOMETRY_FILE = r"C:\Users\Bryan\Desktop\county-map-data\geometry\global.csv"
FIELD_MAPPINGS_FILE = os.path.join(os.path.dirname(__file__), 'world_factbook_field_mappings.json')

# Supported editions with their format types
# Format types:
#   'text' = descriptive filenames (population.html), text-based extraction
#   'field_listing' = 2xxx IDs (2001.html), table without rank column
#   'rankorder' = 2xxx IDs (2001rank.html) in rankorder/ folder
#   'modern' = 1xx-3xx IDs (335rank.html) in fields/ folder
EDITION_FORMATS = {
    2000: 'text',           # fields/population.html
    2001: 'text',           # fields/population.html
    2002: 'field_listing',  # fields/2001.html (no rank column)
    2003: 'rankorder',      # rankorder/2001rank.html
    2004: 'rankorder',
    2005: 'rankorder',
    2006: 'rankorder',
    2007: 'rankorder',
    2008: 'rankorder',
    2009: 'rankorder',
    2010: 'rankorder',
    2011: 'rankorder',
    2012: 'rankorder',
    2013: 'rankorder',
    2014: 'rankorder',
    2015: 'rankorder',
    2016: 'rankorder',
    2017: 'rankorder',
    2018: 'modern',         # fields/335rank.html
    2019: 'modern',
    2020: 'modern',
}

# =============================================================================
# METRIC CLASSIFICATION
# =============================================================================

# 51 UNIQUE metrics - NOT available in other data sources (OWID, WHO, IMF, UN SDG)
UNIQUE_METRICS = [
    # Infrastructure (5)
    'airports',
    'railways_km',
    'roadways_km',
    'waterways_km',
    'merchant_marine',

    # Military (1)
    'military_expenditure_pct',

    # Economy - Budgetary (4)
    'budget_surplus_deficit',
    'gini_index',
    'gross_national_saving',
    'taxes_revenue_pct_gdp',

    # Economy - Banking (3)
    'central_bank_discount_rate',
    'commercial_bank_prime_rate',
    'foreign_reserves',

    # Economy - Financial Markets (6)
    'market_value_traded_shares',
    'stock_broad_money',
    'stock_domestic_credit',
    'stock_fdi_abroad',
    'stock_fdi_at_home',
    'stock_narrow_money',

    # Economy - Industrial (1)
    'industrial_production_growth',

    # Energy - Oil (8)
    'crude_oil_production',
    'crude_oil_exports',
    'crude_oil_imports',
    'crude_oil_reserves',
    'refined_petroleum_production',
    'refined_petroleum_consumption',
    'refined_petroleum_exports',
    'refined_petroleum_imports',

    # Energy - Natural Gas (5)
    'natural_gas_production',
    'natural_gas_consumption',
    'natural_gas_exports',
    'natural_gas_imports',
    'natural_gas_reserves',

    # Energy - Electricity source percentages (7)
    'electricity_capacity',
    'electricity_exports',
    'electricity_imports',
    'electricity_fossil_pct',
    'electricity_nuclear_pct',
    'electricity_hydro_pct',
    'electricity_renewable_pct',

    # Communications - verified unique (6)
    'broadband_subscriptions',
    'internet_users',
    'internet_hosts',
    'telephones_fixed',
    'telephones_mobile',

    # Demographics - verified unique (5)
    'area_sq_km',
    'median_age',
    'net_migration_rate',
    'labor_force',
    'unemployment_rate',
    'youth_unemployment',
]

# 27 OVERLAP metrics - also available in other data sources
OVERLAP_METRICS = [
    # Demographics - OWID/WHO (4)
    'birth_rate',      # OWID/WHO
    'death_rate',      # OWID/WHO
    'fertility_rate',  # OWID/WHO
    'life_expectancy', # WHO/OWID

    # Demographics - OWID only (2)
    'population',      # OWID
    'pop_growth_rate', # OWID

    # Health - WHO only (8)
    'child_underweight',   # WHO
    'health_expenditures', # WHO
    'hiv_deaths',          # WHO
    'hiv_living',          # WHO
    'hiv_prevalence',      # WHO
    'infant_mortality',    # WHO
    'maternal_mortality',  # WHO
    'obesity_rate',        # WHO

    # Economy - IMF only (7)
    'current_account_balance', # IMF
    'exports',                 # IMF
    'imports',                 # IMF
    'external_debt',           # IMF
    'gdp_ppp',                 # IMF
    'inflation_rate',          # IMF
    'public_debt_pct_gdp',     # IMF

    # Economy - IMF/OWID (2)
    'gdp_growth_rate',     # IMF/OWID
    'gdp_per_capita_ppp',  # IMF/OWID

    # Energy - OWID (3)
    'co2_emissions',          # OWID
    'electricity_production', # OWID
    'electricity_consumption', # OWID

    # Education - UN SDG (1)
    'education_expenditure',  # UN SDG
]


def load_field_mappings() -> Dict[str, Dict[str, str]]:
    """
    Load field ID mappings from world_factbook_field_mappings.json.

    Returns:
        Dict mapping metric_name -> {edition_year: field_id}
    """
    if not os.path.exists(FIELD_MAPPINGS_FILE):
        print(f"Warning: Field mappings file not found at {FIELD_MAPPINGS_FILE}")
        return {}

    with open(FIELD_MAPPINGS_FILE, 'r', encoding='utf-8') as f:
        mappings = json.load(f)

    # Remove comment fields
    return {k: v for k, v in mappings.items() if not k.startswith('_')}

# Metrics available in rank files (field_id: metric_info)
# Format: field_id -> (metric_name, unit, aggregation, description)
METRICS = {
    # Demographics
    '335': ('population', 'count', 'sum', 'Total population'),
    '343': ('median_age', 'years', 'avg', 'Median age of population'),
    '344': ('pop_growth_rate', 'percent', 'avg', 'Annual population growth rate'),
    '345': ('birth_rate', 'per 1000', 'avg', 'Births per 1,000 population'),
    '346': ('death_rate', 'per 1000', 'avg', 'Deaths per 1,000 population'),
    '347': ('net_migration_rate', 'per 1000', 'avg', 'Net migration per 1,000 population'),
    '353': ('maternal_mortality', 'per 100000', 'avg', 'Maternal deaths per 100,000 live births'),
    '354': ('infant_mortality', 'per 1000', 'avg', 'Infant deaths per 1,000 live births'),
    '355': ('life_expectancy', 'years', 'avg', 'Life expectancy at birth'),
    '356': ('fertility_rate', 'children/woman', 'avg', 'Total fertility rate'),

    # Health
    '363': ('hiv_prevalence', 'percent', 'avg', 'HIV/AIDS adult prevalence rate'),
    '364': ('hiv_living', 'count', 'sum', 'People living with HIV/AIDS'),
    '365': ('hiv_deaths', 'count', 'sum', 'HIV/AIDS deaths per year'),
    '367': ('obesity_rate', 'percent', 'avg', 'Adult obesity prevalence'),
    '368': ('child_underweight', 'percent', 'avg', 'Children under 5 underweight'),

    # Economy
    '210': ('gdp_growth_rate', 'percent', 'avg', 'Real GDP growth rate'),
    '211': ('gdp_per_capita_ppp', 'USD', 'avg', 'GDP per capita (PPP)'),
    '212': ('gross_national_saving', 'percent_gdp', 'avg', 'Gross national saving as % of GDP'),
    '217': ('industrial_production_growth', 'percent', 'avg', 'Industrial production growth rate'),
    '218': ('labor_force', 'count', 'sum', 'Total labor force'),
    '220': ('unemployment_rate', 'percent', 'avg', 'Unemployment rate'),
    '373': ('youth_unemployment', 'percent', 'avg', 'Youth unemployment (15-24)'),
    '225': ('tax_revenue', 'percent_gdp', 'avg', 'Taxes and other revenues as % of GDP'),
    '226': ('budget_balance', 'percent_gdp', 'avg', 'Budget surplus/deficit as % of GDP'),
    '227': ('public_debt', 'percent_gdp', 'avg', 'Public debt as % of GDP'),
    '229': ('inflation_rate', 'percent', 'avg', 'Inflation rate (consumer prices)'),
    '238': ('current_account', 'USD', 'sum', 'Current account balance'),
    '239': ('exports', 'USD', 'sum', 'Total exports'),
    '242': ('imports', 'USD', 'sum', 'Total imports'),
    '245': ('foreign_reserves', 'USD', 'sum', 'Reserves of foreign exchange and gold'),
    '246': ('external_debt', 'USD', 'sum', 'External debt'),

    # Energy - Electricity
    '252': ('electricity_production', 'kWh', 'sum', 'Electricity production'),
    '253': ('electricity_consumption', 'kWh', 'sum', 'Electricity consumption'),
    '254': ('electricity_exports', 'kWh', 'sum', 'Electricity exports'),
    '255': ('electricity_imports', 'kWh', 'sum', 'Electricity imports'),
    '256': ('electricity_capacity', 'kW', 'sum', 'Installed generating capacity'),
    '257': ('electricity_fossil_pct', 'percent', 'avg', 'Electricity from fossil fuels'),
    '258': ('electricity_nuclear_pct', 'percent', 'avg', 'Electricity from nuclear'),
    '259': ('electricity_hydro_pct', 'percent', 'avg', 'Electricity from hydroelectric'),
    '260': ('electricity_renewable_pct', 'percent', 'avg', 'Electricity from other renewables'),

    # Energy - Oil
    '261': ('crude_oil_production', 'bbl/day', 'sum', 'Crude oil production'),
    '262': ('crude_oil_exports', 'bbl/day', 'sum', 'Crude oil exports'),
    '263': ('crude_oil_imports', 'bbl/day', 'sum', 'Crude oil imports'),
    '264': ('crude_oil_reserves', 'bbl', 'sum', 'Proved crude oil reserves'),
    '265': ('refined_petroleum_production', 'bbl/day', 'sum', 'Refined petroleum production'),
    '266': ('refined_petroleum_consumption', 'bbl/day', 'sum', 'Refined petroleum consumption'),
    '267': ('refined_petroleum_exports', 'bbl/day', 'sum', 'Refined petroleum exports'),
    '268': ('refined_petroleum_imports', 'bbl/day', 'sum', 'Refined petroleum imports'),

    # Energy - Natural Gas
    '269': ('natural_gas_production', 'cu m', 'sum', 'Natural gas production'),
    '270': ('natural_gas_consumption', 'cu m', 'sum', 'Natural gas consumption'),
    '271': ('natural_gas_exports', 'cu m', 'sum', 'Natural gas exports'),
    '272': ('natural_gas_imports', 'cu m', 'sum', 'Natural gas imports'),
    '273': ('natural_gas_reserves', 'cu m', 'sum', 'Proved natural gas reserves'),

    # Environment
    '274': ('co2_emissions', 'Mt', 'sum', 'CO2 emissions from energy consumption'),

    # Infrastructure
    '196': ('telephones_fixed', 'count', 'sum', 'Fixed telephone subscriptions'),
    '197': ('telephones_mobile', 'count', 'sum', 'Mobile cellular subscriptions'),
    '204': ('internet_users', 'count', 'sum', 'Internet users'),
    '206': ('broadband_subscriptions', 'count', 'sum', 'Fixed broadband subscriptions'),
    '379': ('airports', 'count', 'sum', 'Number of airports'),
    '384': ('railways_km', 'km', 'sum', 'Total railway length'),
    '385': ('roadways_km', 'km', 'sum', 'Total roadway length'),
    '386': ('waterways_km', 'km', 'sum', 'Navigable waterways length'),
    '387': ('merchant_marine', 'count', 'sum', 'Merchant marine vessels'),

    # Military
    '330': ('military_expenditure_pct', 'percent_gdp', 'avg', 'Military expenditures as % of GDP'),

    # Geography
    '279': ('area_sq_km', 'sq km', 'sum', 'Total area'),

    # Education
    '369': ('education_expenditure_pct', 'percent_gdp', 'avg', 'Education expenditures as % of GDP'),
}

# Priority metrics to extract (most useful, least overlap with other sources)
PRIORITY_METRICS = [
    # Unique to World Factbook or best coverage here
    '330',  # military_expenditure_pct
    '379',  # airports
    '384',  # railways_km
    '385',  # roadways_km
    '386',  # waterways_km
    '387',  # merchant_marine
    '196',  # telephones_fixed
    '197',  # telephones_mobile
    '206',  # broadband_subscriptions

    # Energy details (more granular than OWID)
    '257', '258', '259', '260',  # electricity source percentages
    '261', '262', '263', '264',  # crude oil
    '269', '270', '271', '272', '273',  # natural gas

    # Demographics (good for cross-validation)
    '335',  # population
    '343',  # median_age
    '355',  # life_expectancy
    '354',  # infant_mortality

    # Economy
    '211',  # gdp_per_capita_ppp
    '220',  # unemployment_rate
    '227',  # public_debt
]


# =============================================================================
# FILE READING HELPERS
# =============================================================================

def read_html_file(file_path: str) -> Optional[str]:
    """
    Read an HTML file with encoding fallback.
    Older factbook editions use Latin-1 or Windows-1252 encoding.

    Returns:
        File content as string, or None if file cannot be read
    """
    for encoding in ['utf-8', 'latin-1', 'cp1252']:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    return None


# =============================================================================
# FACTBOOK CODE TO ISO3 MAPPING
# =============================================================================

def build_cia_to_iso3_mapping(factbook_path: str) -> Dict[str, str]:
    """
    Build mapping from World Factbook 2-letter country codes to ISO3 codes.
    Parses appendix-d.html from the factbook.

    Returns:
        Dict mapping uppercase Factbook codes to ISO3 codes
    """
    appendix_path = os.path.join(factbook_path, 'appendix', 'appendix-d.html')

    if not os.path.exists(appendix_path):
        print(f"Warning: appendix-d.html not found at {appendix_path}")
        return get_fallback_cia_mapping()

    content = read_html_file(appendix_path)
    if content is None:
        print(f"Warning: Could not decode appendix-d.html with any encoding")
        return get_fallback_cia_mapping()

    cia_to_iso3 = {}

    # Method 1: 2010+ format - geos links with country code in href
    # Pattern: <a href="../geos/xx.html">Country</a> ... FIPS ... ISO2 ... ISO3
    pattern1 = (
        r"<a href=['\"]\.{0,2}/?geos/([a-zA-Z]+)\.html['\"]>([^<]+)</a>.*?"
        r"<td[^>]*>([^<]*)</td>.*?"  # FIPS
        r"<td[^>]*>([^<]*)</td>.*?"  # ISO alpha-2
        r"<td[^>]*>([^<]*)</td>.*?"  # ISO alpha-3
        r"<td[^>]*>([^<]*)</td>"     # ISO numeric
    )

    matches = re.findall(pattern1, content, re.DOTALL | re.IGNORECASE)
    for cia, name, fips, iso2, iso3, numeric in matches:
        if iso3 and iso3.strip() != '-':
            cia_to_iso3[cia.upper()] = iso3.strip()

    # Method 2: 2005-2009 format - country name in <b>, FIPS in next td, ISO3 in later td
    # Pattern: <b>Country</b></td><td>FIPS</td><td>ISO2</td><td>ISO3</td>
    if not cia_to_iso3:
        pattern2 = (
            r"<td[^>]*><b>([^<]+)</b></td>\s*"
            r"<td[^>]*>([A-Z]{2})</td>\s*"    # FIPS (this is also Factbook code)
            r"<td[^>]*>([A-Z]{2})</td>\s*"    # ISO alpha-2
            r"<td[^>]*>([A-Z]{3})</td>"       # ISO alpha-3
        )

        matches = re.findall(pattern2, content, re.DOTALL)
        for name, fips, iso2, iso3 in matches:
            if fips and iso3:
                cia_to_iso3[fips.upper()] = iso3.strip()

    # Method 3: 2002-2004 format - values in <p> tags inside <td>
    # Pattern: <p><b>Country</b></p></td><td><p>FIPS</p></td><td><p>ISO2</p></td><td><p>ISO3</p></td>
    if not cia_to_iso3:
        pattern3 = (
            r"<td[^>]*>\s*<p><b>([^<]+)</b></p>\s*</td>\s*"
            r"<td[^>]*>\s*<p>([A-Z]{2})</p>\s*</td>\s*"    # FIPS
            r"<td[^>]*>\s*<p>([A-Z]{2})</p>\s*</td>\s*"    # ISO alpha-2
            r"<td[^>]*>\s*<p>([A-Z]{3})</p>"               # ISO alpha-3
        )

        matches = re.findall(pattern3, content, re.DOTALL)
        for name, fips, iso2, iso3 in matches:
            if fips and iso3:
                cia_to_iso3[fips.upper()] = iso3.strip()

    print(f"Built Factbook->ISO3 mapping with {len(cia_to_iso3)} entries")
    return cia_to_iso3


def get_fallback_cia_mapping() -> Dict[str, str]:
    """
    Complete Factbook 2-letter code to ISO3 mapping.
    Used as fallback when appendix-d.html is missing (2000-2001 editions).
    Extracted from 2020 edition's appendix-d.html.
    """
    return {
        'AA': 'ABW', 'AC': 'ATG', 'AE': 'ARE', 'AF': 'AFG', 'AG': 'DZA', 'AJ': 'AZE', 'AL': 'ALB', 'AM': 'ARM',
        'AN': 'AND', 'AO': 'AGO', 'AQ': 'ASM', 'AR': 'ARG', 'AS': 'AUS', 'AU': 'AUT', 'AV': 'AIA', 'AY': 'ATA',
        'BA': 'BHR', 'BB': 'BRB', 'BC': 'BWA', 'BD': 'BMU', 'BE': 'BEL', 'BF': 'BHS', 'BG': 'BGD', 'BH': 'BLZ',
        'BK': 'BIH', 'BL': 'BOL', 'BM': 'MMR', 'BN': 'BEN', 'BO': 'BLR', 'BP': 'SLB', 'BR': 'BRA', 'BT': 'BTN',
        'BU': 'BGR', 'BV': 'BVT', 'BX': 'BRN', 'BY': 'BDI', 'CA': 'CAN', 'CB': 'KHM', 'CD': 'TCD', 'CE': 'LKA',
        'CF': 'COG', 'CG': 'COD', 'CH': 'CHN', 'CI': 'CHL', 'CJ': 'CYM', 'CK': 'CCK', 'CM': 'CMR', 'CN': 'COM',
        'CO': 'COL', 'CQ': 'MNP', 'CS': 'CRI', 'CT': 'CAF', 'CU': 'CUB', 'CV': 'CPV', 'CW': 'COK', 'CY': 'CYP',
        'DA': 'DNK', 'DJ': 'DJI', 'DO': 'DMA', 'DR': 'DOM', 'EC': 'ECU', 'EG': 'EGY', 'EI': 'IRL', 'EK': 'GNQ',
        'EN': 'EST', 'ER': 'ERI', 'ES': 'SLV', 'ET': 'ETH', 'EZ': 'CZE', 'FG': 'GUF', 'FI': 'FIN', 'FJ': 'FJI',
        'FK': 'FLK', 'FM': 'FSM', 'FO': 'FRO', 'FP': 'PYF', 'FR': 'FRA', 'FS': 'ATF', 'GA': 'GMB', 'GB': 'GAB',
        'GG': 'GEO', 'GH': 'GHA', 'GI': 'GIB', 'GJ': 'GRD', 'GK': 'GGY', 'GL': 'GRL', 'GM': 'DEU', 'GP': 'GLP',
        'GQ': 'GUM', 'GR': 'GRC', 'GT': 'GTM', 'GV': 'GIN', 'GY': 'GUY', 'GZ': 'PSE', 'HA': 'HTI', 'HK': 'HKG',
        'HM': 'HMD', 'HO': 'HND', 'HR': 'HRV', 'HU': 'HUN', 'IC': 'ISL', 'ID': 'IDN', 'IM': 'IMN', 'IN': 'IND',
        'IO': 'IOT', 'IR': 'IRN', 'IS': 'ISR', 'IT': 'ITA', 'IV': 'CIV', 'IZ': 'IRQ', 'JA': 'JPN', 'JE': 'JEY',
        'JM': 'JAM', 'JO': 'JOR', 'KE': 'KEN', 'KG': 'KGZ', 'KN': 'PRK', 'KR': 'KIR', 'KS': 'KOR', 'KT': 'CXR',
        'KU': 'KWT', 'KV': 'XKS', 'KZ': 'KAZ', 'LA': 'LAO', 'LE': 'LBN', 'LG': 'LVA', 'LH': 'LTU', 'LI': 'LBR',
        'LO': 'SVK', 'LS': 'LIE', 'LT': 'LSO', 'LU': 'LUX', 'LY': 'LBY', 'MA': 'MDG', 'MB': 'MTQ', 'MC': 'MAC',
        'MD': 'MDA', 'MF': 'MYT', 'MG': 'MNG', 'MH': 'MSR', 'MI': 'MWI', 'MJ': 'MNE', 'MK': 'MKD', 'ML': 'MLI',
        'MN': 'MCO', 'MO': 'MAR', 'MP': 'MUS', 'MR': 'MRT', 'MT': 'MLT', 'MU': 'OMN', 'MV': 'MDV', 'MX': 'MEX',
        'MY': 'MYS', 'MZ': 'MOZ', 'NC': 'NCL', 'NE': 'NIU', 'NF': 'NFK', 'NG': 'NER', 'NH': 'VUT', 'NI': 'NGA',
        'NL': 'NLD', 'NN': 'SXM', 'NO': 'NOR', 'NP': 'NPL', 'NR': 'NRU', 'NS': 'SUR', 'NU': 'NIC', 'NZ': 'NZL',
        'OD': 'SSD', 'PA': 'PRY', 'PC': 'PCN', 'PE': 'PER', 'PK': 'PAK', 'PL': 'POL', 'PM': 'PAN', 'PO': 'PRT',
        'PP': 'PNG', 'PS': 'PLW', 'PU': 'GNB', 'QA': 'QAT', 'RE': 'REU', 'RI': 'SRB', 'RM': 'MHL', 'RN': 'MAF',
        'RO': 'ROU', 'RP': 'PHL', 'RQ': 'PRI', 'RS': 'RUS', 'RW': 'RWA', 'SA': 'SAU', 'SB': 'SPM', 'SC': 'KNA',
        'SE': 'SYC', 'SF': 'ZAF', 'SG': 'SEN', 'SH': 'SHN', 'SI': 'SVN', 'SL': 'SLE', 'SM': 'SMR', 'SN': 'SGP',
        'SO': 'SOM', 'SP': 'ESP', 'ST': 'LCA', 'SU': 'SDN', 'SV': 'SJM', 'SW': 'SWE', 'SX': 'SGS', 'SY': 'SYR',
        'SZ': 'CHE', 'TB': 'BLM', 'TD': 'TTO', 'TH': 'THA', 'TI': 'TJK', 'TK': 'TCA', 'TL': 'TKL', 'TN': 'TON',
        'TO': 'TGO', 'TP': 'STP', 'TS': 'TUN', 'TT': 'TLS', 'TU': 'TUR', 'TV': 'TUV', 'TW': 'TWN', 'TX': 'TKM',
        'TZ': 'TZA', 'UC': 'CUW', 'UG': 'UGA', 'UK': 'GBR', 'UP': 'UKR', 'US': 'USA', 'UV': 'BFA', 'UY': 'URY',
        'UZ': 'UZB', 'VC': 'VCT', 'VE': 'VEN', 'VI': 'VGB', 'VM': 'VNM', 'VQ': 'VIR', 'VT': 'VAT', 'WA': 'NAM',
        'WE': 'PSE', 'WF': 'WLF', 'WI': 'ESH', 'WS': 'WSM', 'WZ': 'SWZ', 'YM': 'YEM', 'ZA': 'ZMB', 'ZI': 'ZWE',
    }


# =============================================================================
# VALUE PARSING
# =============================================================================

def parse_value(value_str: str) -> Optional[float]:
    """
    Parse a value string from World Factbook into a numeric value.

    Handles formats like:
    - "$55,761" -> 55761
    - "331,002,651" -> 331002651
    - "2.16%" -> 2.16
    - "1.5 trillion" -> 1500000000000
    - "45.6 million" -> 45600000
    - "-2.5%" -> -2.5
    - "N/A" -> None
    """
    if not value_str or value_str.strip() in ['', '-', 'N/A', 'NA']:
        return None

    # Clean the string
    s = value_str.strip()

    # Remove year in parentheses BEFORE removing parentheses
    # Patterns: "(2001 est.)" or "(July 2002 est.)" or "(2001)" or "(est.)"
    s = re.sub(r'\s*\([A-Za-z]*\s*\d{4}[^)]*\)', '', s)  # "(July 2002 est.)" or "(2002 est.)"
    s = re.sub(r'\s*\(est\.?\s*\)', '', s)  # "(est.)" or "(est)"

    # Check for negative BEFORE removing parentheses
    # Accounting convention: (500) means -500, but "46 (2001 est.)" is positive
    # Only treat as negative if value STARTS with '(' followed by number/currency
    is_negative = s.startswith('-') or bool(re.match(r'^\s*\(\s*[\$\d]', s))

    # Remove currency symbols and parentheses
    s = re.sub(r'[\$\(\)]', '', s)
    s = s.lstrip('-')

    # Handle multipliers
    multiplier = 1
    multiplier_patterns = [
        (r'trillion', 1e12),
        (r'billion', 1e9),
        (r'million', 1e6),
        (r'thousand', 1e3),
    ]

    for pattern, mult in multiplier_patterns:
        if re.search(pattern, s, re.IGNORECASE):
            multiplier = mult
            s = re.sub(pattern, '', s, flags=re.IGNORECASE)
            break

    # Remove percent sign (keep the number)
    s = s.rstrip('%')

    # Extract numeric portion - find the main number, ignoring separator dashes
    # First try to find a number preceded by $ or space or start (these can be negative)
    # Pattern: optional minus, then digits with optional decimal
    num_match = re.search(r'(?:^|[\s\$])(-?[\d,]+\.?\d*)', s)
    if num_match:
        s = num_match.group(1)
    else:
        # Fallback: just find any number (without negative)
        num_match = re.search(r'[\d,]+\.?\d*', s)
        if not num_match:
            return None
        s = num_match.group()

    # Clean up commas
    s = s.replace(',', '')

    try:
        value = float(s) * multiplier
        # Apply is_negative only if the extracted number isn't already negative
        if is_negative and value > 0:
            value = -value
        return value
    except ValueError:
        return None


def parse_year(year_str: str) -> Optional[int]:
    """
    Parse year from strings like "2019 est." or "2020"
    """
    if not year_str:
        return None

    match = re.search(r'(\d{4})', year_str)
    if match:
        return int(match.group(1))
    return None


# =============================================================================
# EDITION-SPECIFIC EXTRACTION
# =============================================================================

def find_rank_file(factbook_path: str, field_id: str, edition_year: int) -> Optional[str]:
    """
    Find the data file for a given field ID and edition.

    Different editions store files in different locations:
    - 2000-2001 (text): fields/{descriptive_name}.html (e.g., population.html)
    - 2002 (field_listing): fields/{id}.html (e.g., 2001.html - no 'rank' suffix)
    - 2003-2017 (rankorder): rankorder/{id}rank.html (e.g., 2001rank.html)
    - 2018-2020 (modern): fields/{id}rank.html (e.g., 335rank.html)
    """
    edition_format = EDITION_FORMATS.get(edition_year, 'rankorder')

    if edition_format == 'text':
        # 2000-2001: descriptive filenames like "population.html"
        if field_id.endswith('.html'):
            text_path = os.path.join(factbook_path, 'fields', field_id)
            if os.path.exists(text_path):
                return text_path

    elif edition_format == 'field_listing':
        # 2002: 2xxx IDs without 'rank' suffix
        field_path = os.path.join(factbook_path, 'fields', f'{field_id}.html')
        if os.path.exists(field_path):
            return field_path

    elif edition_format == 'rankorder':
        # 2003-2017: rankorder folder with 'rank' suffix
        rankorder_path = os.path.join(factbook_path, 'rankorder', f'{field_id}rank.html')
        if os.path.exists(rankorder_path):
            return rankorder_path

    elif edition_format == 'modern':
        # 2018-2020: fields folder with 'rank' suffix
        fields_path = os.path.join(factbook_path, 'fields', f'{field_id}rank.html')
        if os.path.exists(fields_path):
            return fields_path

    return None


def extract_data_2020(file_path: str, cia_to_iso3: Dict[str, str], default_year: int = None) -> List[dict]:
    """
    Extract data from 2020 format rank files.

    HTML pattern:
    <tr id="US" class='rankorder north-america'>
      <td>23</td>
      <td class='region'><a href='../geos/us.html'>United States</a></td>
      <td>$55,761</td>
      <td>2019 est.</td>
    </tr>
    """
    content = read_html_file(file_path)
    if content is None:
        print(f"Warning: Could not read {file_path}")
        return []

    pattern = (
        r"<tr id=\"([A-Z]+)\"[^>]*>.*?"
        r"<td[^>]*>(\d+)</td>.*?"  # rank
        r"<td[^>]*>.*?<a[^>]*>([^<]+)</a>.*?</td>.*?"  # country name
        r"<td>([^<]*)</td>.*?"  # value
        r"<td>([^<]*)</td>"  # year
    )

    matches = re.findall(pattern, content, re.DOTALL)

    results = []
    for cia_code, rank, country_name, value_str, year_str in matches:
        iso3 = cia_to_iso3.get(cia_code)
        if not iso3:
            continue

        value = parse_value(value_str)
        year = parse_year(year_str)

        if year is None and default_year is not None:
            year = default_year

        if value is not None and year is not None:
            results.append({
                'loc_id': iso3,
                'year': year,
                'value': value,
                'rank': int(rank),
                'country_name': country_name.strip()
            })

    return results


def extract_data_2003_2017(file_path: str, cia_to_iso3: Dict[str, str], default_year: int = None) -> List[dict]:
    """
    Extract data from 2003-2017 format rank files (rankorder folder).

    These editions have table structure with rank column.
    Format varies by year:
    - 2003-2009: Simple tr/td structure
    - 2010-2017: Each country in separate <table id="xx"> container
    """
    content = read_html_file(file_path)
    if content is None:
        print(f"Warning: Could not read {file_path}")
        return []

    results = []

    # Method 1: Try table-per-country format (2010-2017)
    # Each country is in: <table id="xx">...</table>
    table_pattern = r'<table[^>]*id="([a-z]{2})"[^>]*>(.*?)</table>'
    tables = re.findall(table_pattern, content, re.DOTALL | re.IGNORECASE)

    if len(tables) > 50:  # This format typically has 200+ tables
        for cia_code_lower, table_html in tables:
            cia_code = cia_code_lower.upper()
            iso3 = cia_to_iso3.get(cia_code)
            if not iso3:
                continue

            # Extract rank (look for currentRow class or just a number in first td)
            rank_match = re.search(r'class="currentRow"[^>]*>\s*(\d+)\s*<', table_html)
            if not rank_match:
                rank_match = re.search(r'<td[^>]*>\s*(\d+)\s*</td>', table_html)
            rank = int(rank_match.group(1)) if rank_match else None

            # Extract country name
            name_match = re.search(r'geos/' + cia_code_lower + r'\.html[^>]*>(?:<strong>)?([^<]+)', table_html, re.IGNORECASE)
            country_name = name_match.group(1).strip() if name_match else cia_code

            # Extract value (look for numbers in category_data or just large numbers)
            value_match = re.search(r'category_data[^>]*>.*?([\d,]+(?:\.\d+)?)\s*<', table_html, re.DOTALL)
            if not value_match:
                value_match = re.search(r'>\s*\$?\s*([\d,]+(?:\.\d+)?)\s*<', table_html)
            value_str = value_match.group(1) if value_match else None

            # Extract year
            year_match = re.search(r'(\d{4})\s*est\.', table_html, re.IGNORECASE)
            year = int(year_match.group(1)) if year_match else default_year

            if value_str:
                value = parse_value(value_str)
                if value is not None and year is not None:
                    results.append({
                        'loc_id': iso3,
                        'year': year,
                        'value': value,
                        'rank': rank,
                        'country_name': country_name
                    })

    # Method 2: Try 2009 format with nested divs (class="currentRow" for rank)
    if not results:
        # 2009 format: <td class="currentRow">1</td> ... <td class="category_data"><div>value</div></td>
        pattern = (
            r'<td[^>]*class="currentRow"[^>]*>\s*(\d+)\s*</td>\s*'  # rank
            r'<td[^>]*class="region"[^>]*>.*?<a[^>]*geos/([a-z]+)\.html[^>]*>.*?([^<]+)</a>.*?</td>\s*'  # country
            r'<td[^>]*class="category_data"[^>]*>.*?>([\d,.\s]+)<.*?</td>\s*'  # value (inside div)
            r'<td[^>]*>.*?class="category_data"[^>]*>(\d{4})</span>'  # year
        )
        matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)

        for rank_str, cia_code_lower, country_name, value_str, year_str in matches:
            cia_code = cia_code_lower.upper()
            iso3 = cia_to_iso3.get(cia_code)
            if not iso3:
                continue

            value = parse_value(value_str.strip())
            year = int(year_str) if year_str.isdigit() else default_year

            if value is not None and year is not None:
                results.append({
                    'loc_id': iso3,
                    'year': year,
                    'value': value,
                    'rank': int(rank_str),
                    'country_name': country_name.strip()
                })

    # Method 3: Line-by-line parsing for 2003-2009 (avoids regex backtracking)
    if not results:
        # Find all country links and their surrounding context
        country_pattern = r'geos/([a-z]{2})\.html[^>]*>(?:<strong>)?([^<]+)'
        value_pattern = r'category_data[^>]*>(?:<div[^>]*>)?\s*([\d,.\s]+)\s*(?:</div>)?</td>'
        year_pattern = r'(\d{4})\s*(?:est\.?)?'
        rank_pattern = r'class="currentRow"[^>]*>\s*(\d+)'

        # Split content into rows
        rows = re.split(r'<tr[^>]*>', content, flags=re.IGNORECASE)

        for row in rows:
            # Find country code
            country_match = re.search(country_pattern, row, re.IGNORECASE)
            if not country_match:
                continue

            cia_code = country_match.group(1).upper()
            iso3 = cia_to_iso3.get(cia_code)
            if not iso3:
                continue

            country_name = country_match.group(2).strip()

            # Find rank
            rank_match = re.search(rank_pattern, row)
            rank = int(rank_match.group(1)) if rank_match else None

            # Find value - look AFTER the country link (skip rank which comes before)
            value_match = re.search(value_pattern, row, re.IGNORECASE)
            if not value_match:
                # For 2010-2017 rankorder format: value is in <td> after </a></td>
                # Pattern: </a></td><td>VALUE</td><td>YEAR</td>
                value_match = re.search(r'</a>\s*</td>\s*<td[^>]*>\s*([\d,.$-]+(?:\.\d+)?)\s*</td>', row, re.IGNORECASE)
            if not value_match:
                # Fallback: find all numbers and take the largest (likely the value, not rank)
                all_nums = re.findall(r'>\s*([\d,]+(?:\.\d+)?)\s*<', row)
                if len(all_nums) >= 2:
                    # Skip rank (first number), take the actual value
                    value_str = all_nums[1] if len(all_nums) > 1 else all_nums[0]
                else:
                    value_str = all_nums[0] if all_nums else None
            else:
                value_str = value_match.group(1)

            # Find year
            year_match = re.search(year_pattern, row)
            year = int(year_match.group(1)) if year_match else default_year

            if value_str:
                value = parse_value(value_str.strip())
                if value is not None and year is not None:
                    results.append({
                        'loc_id': iso3,
                        'year': year,
                        'value': value,
                        'rank': rank,
                        'country_name': country_name
                    })

    return results


def extract_data_2002_field_listing(file_path: str, cia_to_iso3: Dict[str, str], default_year: int = None) -> List[dict]:
    """
    Extract data from 2002 field listing format (no rank column).

    HTML pattern:
    <tr>
      <td valign=top><a href="../geos/us.html" class="CountryLink">United States</a></td>
      <td class="Normal">purchasing power parity - $10.082 trillion (2001 est.)</td>
    </tr>

    Uses row-by-row parsing to avoid regex catastrophic backtracking on large files.
    """
    content = read_html_file(file_path)
    if content is None:
        print(f"Warning: Could not read {file_path}")
        return []

    results = []
    rank = 0

    # Split into rows to avoid catastrophic backtracking with .*? and DOTALL
    rows = re.split(r'<tr[^>]*>', content, flags=re.IGNORECASE)

    # Pattern to find country link and value in each row
    country_pattern = r"geos/([a-zA-Z]{2})\.html['\"][^>]*>([^<]+)</a>"
    value_pattern = r"<td[^>]*class=['\"]Normal['\"][^>]*>\s*([^<]+?)\s*</td>"

    for row in rows:
        # Find country link
        country_match = re.search(country_pattern, row, re.IGNORECASE)
        if not country_match:
            continue

        cia_code = country_match.group(1).upper()
        country_name = country_match.group(2).strip()

        # Find value in "Normal" class cell
        value_match = re.search(value_pattern, row, re.IGNORECASE | re.DOTALL)
        if not value_match:
            # Try alternate pattern without class
            value_match = re.search(r"</a>\s*</td>\s*<td[^>]*>\s*([^<]+?)\s*</td>", row, re.IGNORECASE | re.DOTALL)

        if not value_match:
            continue

        value_text = value_match.group(1).strip()

        iso3 = cia_to_iso3.get(cia_code)
        if not iso3:
            continue

        # Parse value and year from combined text like "purchasing power parity - $10.082 trillion (2001 est.)"
        value = parse_value(value_text)
        year = parse_year(value_text)

        if year is None and default_year is not None:
            year = default_year

        if value is not None and year is not None:
            rank += 1
            results.append({
                'loc_id': iso3,
                'year': year,
                'value': value,
                'rank': rank,
                'country_name': country_name
            })

    return results


def extract_data_2000_text(file_path: str, cia_to_iso3: Dict[str, str], default_year: int = None) -> List[dict]:
    """
    Extract data from 2000 edition text-based format.

    The 2000 edition uses a very different format with text paragraphs.
    Pattern: <p><b>CountryName:</b><br>Value (year est.)

    Need to build country name to code mapping from geos folder.
    """
    content = read_html_file(file_path)
    if content is None:
        print(f"Warning: Could not read {file_path}")
        return []

    # Build name to code mapping for this edition
    factbook_path = os.path.dirname(os.path.dirname(file_path))
    name_to_iso3 = build_name_to_iso3_mapping(factbook_path, cia_to_iso3)

    # Try multiple patterns for 2000-2001 formats
    # 2000 format: <b>CountryName:</b><br>Value
    pattern_2000 = r"<b>([^<:]+):</b>\s*<br>\s*([^<]+)"
    # 2001 format: <b>CountryName:</b></font></td><td...><font...>Value
    pattern_2001 = r"<b>([^<:]+):</b></font></td>\s*<td[^>]*><font[^>]*>\s*([^<]+)"

    matches = re.findall(pattern_2000, content, re.IGNORECASE)
    if not matches:
        matches = re.findall(pattern_2001, content, re.IGNORECASE)

    results = []
    rank = 0
    for country_name, value_text in matches:
        country_name = country_name.strip()
        value_text = value_text.strip()

        # Look up ISO3 code
        iso3 = name_to_iso3.get(country_name.lower())
        if not iso3:
            # Try partial match
            for name, code in name_to_iso3.items():
                if country_name.lower() in name or name in country_name.lower():
                    iso3 = code
                    break
        if not iso3:
            continue

        # Parse value and year from text like "1,330,141,295 (2008 est.)"
        value = parse_value(value_text)
        year = parse_year(value_text)

        if year is None and default_year is not None:
            year = default_year

        if value is not None and year is not None:
            rank += 1
            results.append({
                'loc_id': iso3,
                'year': year,
                'value': value,
                'rank': rank,
                'country_name': country_name
            })

    return results


def build_name_to_iso3_mapping(factbook_path: str, cia_to_iso3: Dict[str, str]) -> Dict[str, str]:
    """
    Build mapping from country names to ISO3 codes.
    Used for 2000 edition which doesn't have codes in data files.
    """
    geos_path = os.path.join(factbook_path, 'geos')
    name_to_iso3 = {}

    if not os.path.exists(geos_path):
        return name_to_iso3

    for filename in os.listdir(geos_path):
        if filename.endswith('.html'):
            cia_code = filename[:-5].upper()  # Remove .html
            iso3 = cia_to_iso3.get(cia_code)
            if not iso3:
                continue

            # Read the geo file to get country name
            geo_file = os.path.join(geos_path, filename)
            try:
                with open(geo_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    # Look for country name in title or header
                    title_match = re.search(r'<title>([^<]+)</title>', content, re.IGNORECASE)
                    if title_match:
                        title = title_match.group(1).strip()
                        # Title formats:
                        # 2000: "CIA -- The World Factbook 2000 -- Afghanistan"
                        # Later: "Country Name - The World Factbook"
                        if '--' in title:
                            # Extract country name after last "--"
                            name = title.split('--')[-1].strip()
                        else:
                            # Clean up common suffixes
                            name = re.sub(r'\s*-?\s*the world factbook.*', '', title, flags=re.IGNORECASE)
                        name = re.sub(r'\s*\(.*\)', '', name).strip()
                        if name and name.lower() not in ['cia', '']:
                            name_to_iso3[name.lower()] = iso3
            except:
                pass

    return name_to_iso3


def extract_rank_data(factbook_path: str, field_id: str, cia_to_iso3: Dict[str, str],
                      edition_year: int, default_year: int = None) -> List[dict]:
    """
    Extract data from a rank file using edition-appropriate parser.

    Args:
        factbook_path: Path to factbook directory
        field_id: The field ID (e.g., '335' for 2020, '2119' for 2003-2017)
        cia_to_iso3: Mapping from Factbook codes to ISO3
        edition_year: The factbook edition year (determines parser)
        default_year: Year to use when not specified in data

    Returns:
        List of dicts with keys: loc_id, year, value, rank, country_name
    """
    # Find the data file (different locations per edition)
    data_file = find_rank_file(factbook_path, field_id, edition_year)

    if not data_file:
        return []

    # Use edition-appropriate parser
    edition_format = EDITION_FORMATS.get(edition_year, 'rankorder')

    if edition_format == 'text':
        return extract_data_2000_text(data_file, cia_to_iso3, default_year)
    elif edition_format == 'field_listing':
        return extract_data_2002_field_listing(data_file, cia_to_iso3, default_year)
    elif edition_format == 'rankorder':
        return extract_data_2003_2017(data_file, cia_to_iso3, default_year)
    elif edition_format == 'modern':
        return extract_data_2020(data_file, cia_to_iso3, default_year)
    else:
        return []


def extract_all_metrics(factbook_path: str, metric_names: List[str] = None,
                        factbook_year: int = None, field_mappings: Dict = None) -> pd.DataFrame:
    """
    Extract all specified metrics from a factbook edition.

    Args:
        factbook_path: Path to factbook directory
        metric_names: List of metric names to extract (None = all mapped metrics)
        factbook_year: Edition year (determines field IDs and parser)
        field_mappings: Field ID mappings across editions (loaded from JSON)

    Returns:
        DataFrame with columns: loc_id, year, [metric columns]
    """
    cia_to_iso3 = build_cia_to_iso3_mapping(factbook_path)

    # Load field mappings if not provided
    if field_mappings is None:
        field_mappings = load_field_mappings()

    # Use all mapped metrics if not specified
    if metric_names is None:
        metric_names = list(field_mappings.keys())

    # Default year for data without explicit year
    default_year = (factbook_year - 1) if factbook_year else None
    edition_key = str(factbook_year)

    # Collect all data by loc_id and year
    all_data = {}  # (loc_id, year) -> {metric: value}
    metrics_found = 0
    metrics_missing = 0

    for metric_name in metric_names:
        if metric_name not in field_mappings:
            print(f"  Warning: No mapping for metric '{metric_name}'")
            continue

        # Get field ID for this edition
        field_id = field_mappings[metric_name].get(edition_key)
        if not field_id:
            metrics_missing += 1
            continue

        print(f"  Extracting {metric_name} (field {field_id})...")

        rows = extract_rank_data(
            factbook_path, field_id, cia_to_iso3,
            edition_year=factbook_year, default_year=default_year
        )

        if rows:
            metrics_found += 1

        for row in rows:
            key = (row['loc_id'], row['year'])
            if key not in all_data:
                all_data[key] = {}
            all_data[key][metric_name] = row['value']

    print(f"  Found {metrics_found} metrics, {metrics_missing} not available for {factbook_year}")

    # Convert to DataFrame
    records = []
    for (loc_id, year), metrics in all_data.items():
        record = {'loc_id': loc_id, 'year': year}
        record.update(metrics)
        records.append(record)

    df = pd.DataFrame(records)

    if len(df) > 0:
        df = df.sort_values(['loc_id', 'year']).reset_index(drop=True)

    return df


# =============================================================================
# LANGUAGE DATA EXTRACTION
# =============================================================================

def extract_languages(factbook_path: str, cia_to_iso3: Dict[str, str]) -> pd.DataFrame:
    """
    Extract language data from field 402.

    Returns DataFrame with columns:
    - loc_id
    - language
    - percentage (if available, else null)
    - is_official (boolean)
    """
    lang_file = os.path.join(factbook_path, 'fields', '402.html')

    if not os.path.exists(lang_file):
        print(f"Warning: Languages file not found at {lang_file}")
        return pd.DataFrame()

    with open(lang_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Pattern to match language entries by country
    # <tr id="AF">
    #   <td class='country'><a href='../geos/af.html'>Afghanistan</a></td>
    #   <td><div id="field-languages">...language text...</div></td>
    # </tr>

    pattern = (
        r'<tr id="([A-Z]+)">\s*'
        r'<td[^>]*>.*?<a[^>]*>([^<]+)</a>.*?</td>\s*'
        r'<td>\s*<div id="field-languages">\s*'
        r"<div class='category_data[^']*'>\s*"
        r'([^<]+)'
    )

    matches = re.findall(pattern, content, re.DOTALL)

    results = []
    for cia_code, country_name, lang_text in matches:
        iso3 = cia_to_iso3.get(cia_code)
        if not iso3:
            continue

        # Parse language text
        # Format: "English only 78.2%, Spanish 13.4%, Chinese 1.1%, other 7.3%"
        # Or: "Arabic (official), French (lingua franca)"

        # Split by comma, handling complex cases
        lang_entries = re.split(r',\s*(?![^(]*\))', lang_text.strip())

        for entry in lang_entries:
            entry = entry.strip()
            if not entry or entry.lower() in ['other', 'none']:
                continue

            # Check for percentage
            pct_match = re.search(r'([\d.]+)%', entry)
            percentage = float(pct_match.group(1)) if pct_match else None

            # Check if official
            is_official = 'official' in entry.lower()

            # Extract language name
            lang_name = re.sub(r'\s*[\d.]+%.*', '', entry)
            lang_name = re.sub(r'\s*\([^)]*\)', '', lang_name).strip()

            if lang_name:
                results.append({
                    'loc_id': iso3,
                    'language': lang_name,
                    'percentage': percentage,
                    'is_official': is_official
                })

    return pd.DataFrame(results)


# =============================================================================
# METADATA GENERATION
# =============================================================================

def create_metadata(df: pd.DataFrame, editions: List[int] = None, source_id: str = 'world_factbook') -> dict:
    """Create metadata.json for a combined factbook extraction."""

    # Build metric definitions from columns in dataframe
    metric_definitions = {}
    metric_cols = [c for c in df.columns if c not in ['loc_id', 'year', 'factbook_edition']]

    for metric_name in metric_cols:
        # Find matching metric info from METRICS dict
        unit = 'unknown'
        agg = 'avg'
        desc = metric_name.replace('_', ' ').title()

        for field_id, (name, m_unit, m_agg, m_desc) in METRICS.items():
            if name == metric_name:
                unit = m_unit
                agg = m_agg
                desc = m_desc
                break

        metric_definitions[metric_name] = {
            'name': desc,
            'unit': unit,
            'aggregation': agg
        }

    # Get year range from data
    years = df['year'].dropna().unique()
    year_start = int(min(years)) if len(years) > 0 else 1999
    year_end = int(max(years)) if len(years) > 0 else 2019

    edition_str = ', '.join(str(e) for e in sorted(editions)) if editions else 'multiple'

    # Source-specific metadata
    if source_id == 'world_factbook':
        source_name = 'World Factbook - Unique Metrics'
        description = f'Unique World Factbook metrics not available elsewhere (infrastructure, military, energy details). Editions: {edition_str}'
        topic_tags = ['infrastructure', 'military', 'energy', 'oil', 'gas', 'communications']
        data_notes = {
            'type': 'unique',
            'note': 'These 51 metrics are NOT available in other data sources (OWID, WHO, IMF, UN SDG)',
            'categories': ['infrastructure', 'military', 'oil/gas', 'electricity sources', 'banking', 'financial markets']
        }
    elif source_id == 'world_factbook_overlap':
        source_name = 'World Factbook - Overlap Metrics'
        description = f'World Factbook metrics also available in other sources (for time series continuity). Editions: {edition_str}'
        topic_tags = ['demographics', 'health', 'economy', 'gdp', 'trade']
        data_notes = {
            'type': 'overlap',
            'note': 'These 27 metrics overlap with OWID, WHO, IMF, or UN SDG. Use for historical continuity.',
            'primary_sources': {
                'demographics': 'OWID, WHO',
                'health': 'WHO',
                'economy': 'IMF',
                'energy': 'OWID',
                'education': 'UN SDG'
            }
        }
    else:
        source_name = 'World Factbook'
        description = f'World Factbook combined data from editions: {edition_str}'
        topic_tags = ['demographics', 'economy', 'energy', 'infrastructure', 'military', 'health']
        data_notes = {
            'overlap_with': ['owid_co2 (GDP, population, CO2)', 'who_health (life expectancy)', 'imf_bop (trade)'],
            'unique_metrics': ['military expenditure', 'infrastructure (airports, railways)', 'energy source percentages'],
            'methodology': 'Factbook compiles from multiple sources; values may differ from primary sources'
        }

    return {
        'source_id': source_id,
        'source_name': source_name,
        'source_url': 'https://www.cia.gov/the-world-factbook/',
        'license': 'Public Domain (US Government Work)',
        'description': description,
        'category': 'reference',
        'topic_tags': topic_tags,
        'keywords': ['world factbook', 'country profiles', 'world data', 'time series'],

        'last_updated': datetime.now().strftime('%Y-%m-%d'),
        'factbook_editions': sorted(editions) if editions else [],
        'geographic_level': 'country',
        'geographic_coverage': {
            'type': 'global',
            'countries': df['loc_id'].nunique() if len(df) > 0 else 0,
            'admin_levels': [0]
        },
        'temporal_coverage': {
            'start': year_start,
            'end': year_end,
            'frequency': 'annual',
            'note': 'Data years vary by metric; factbook published annually'
        },

        'row_count': len(df),
        'metrics': metric_definitions,

        'llm_summary': (
            f'{source_name}: {df["loc_id"].nunique() if len(df) > 0 else 0} countries, '
            f'{len(metric_cols)} metrics. '
            f'Data from editions: {edition_str}.'
        ),

        'data_notes': data_notes
    }


# =============================================================================
# MAIN CONVERSION
# =============================================================================

def convert_factbook(
    factbook_year: int,
    metric_names: List[str] = None,
    field_mappings: Dict = None
) -> pd.DataFrame:
    """
    Convert a single World Factbook edition to DataFrame.

    Args:
        factbook_year: Year of the factbook edition (e.g., 2020)
        metric_names: List of metric names to extract (None = all mapped metrics)
        field_mappings: Field ID mappings (loaded once and passed in)

    Returns:
        DataFrame with columns: loc_id, year, [metric columns]
    """
    factbook_path = os.path.join(RAW_DATA_BASE, f'factbook-{factbook_year}')

    if not os.path.exists(factbook_path):
        raise FileNotFoundError(f"Factbook not found at {factbook_path}")

    print(f"\n{'='*60}")
    print(f"Converting World Factbook {factbook_year}")
    print(f"{'='*60}")
    print(f"Source: {factbook_path}")

    # Load field mappings if not provided
    if field_mappings is None:
        field_mappings = load_field_mappings()

    # Use all mapped metrics if not specified
    if metric_names is None:
        metric_names = list(field_mappings.keys())

    print(f"Processing {len(metric_names)} metrics...")

    # Extract data
    df = extract_all_metrics(
        factbook_path,
        metric_names=metric_names,
        factbook_year=factbook_year,
        field_mappings=field_mappings
    )

    print(f"\nExtraction complete:")
    print(f"  Total rows: {len(df)}")
    print(f"  Countries: {df['loc_id'].nunique() if len(df) > 0 else 0}")
    print(f"  Metrics: {len([c for c in df.columns if c not in ['loc_id', 'year']])}")

    return df


def convert_all_factbooks(
    editions: List[int],
    metric_names: List[str] = None,
    output_dir: str = None,
    dry_run: bool = True,
    source_id: str = 'world_factbook'
) -> Tuple[pd.DataFrame, dict]:
    """
    Convert multiple factbook editions and combine into single dataset.

    Args:
        editions: List of factbook edition years to process
        metric_names: List of metric names to extract (None = all mapped metrics)
        output_dir: Output directory for combined files
        dry_run: If True, don't create output files
        source_id: Source identifier (world_factbook, world_factbook_overlap, or world_factbook_all)

    Returns:
        Tuple of (combined DataFrame, metadata dict)
    """
    # Load field mappings once
    field_mappings = load_field_mappings()

    if metric_names is None:
        metric_names = list(field_mappings.keys())

    print(f"\n{'#'*60}")
    print(f"# World Factbook Multi-Edition Import")
    print(f"# Editions: {editions}")
    print(f"# Metrics: {len(metric_names)}")
    print(f"{'#'*60}")

    all_dfs = []
    successful_editions = []

    for year in editions:
        try:
            df = convert_factbook(year, metric_names=metric_names, field_mappings=field_mappings)
            if len(df) > 0:
                df['factbook_edition'] = year
                all_dfs.append(df)
                successful_editions.append(year)
        except FileNotFoundError as e:
            print(f"Skipping {year}: {e}")

    if not all_dfs:
        print("\nNo data extracted from any edition!")
        return pd.DataFrame(), {}

    combined = pd.concat(all_dfs, ignore_index=True)

    # For duplicate (loc_id, year) entries from different editions,
    # merge values: for each metric, take first non-null from newest edition
    # This preserves data that exists in older editions but is missing in newer ones
    combined = combined.sort_values('factbook_edition', ascending=False)

    # Group by (loc_id, year) and take first non-null for each column
    metric_cols = [c for c in combined.columns if c not in ['loc_id', 'year', 'factbook_edition']]

    # Use groupby with first() - this takes first non-null by default when using skipna
    agg_dict = {col: 'first' for col in metric_cols}
    agg_dict['factbook_edition'] = 'first'  # Keep newest edition marker

    combined = combined.groupby(['loc_id', 'year'], as_index=False).agg(agg_dict)
    combined = combined.sort_values(['loc_id', 'year']).reset_index(drop=True)

    # Validate years - fix any parsing errors by using factbook_edition as fallback
    MIN_VALID_YEAR = 1990
    MAX_VALID_YEAR = 2025
    bad_years = (combined['year'] < MIN_VALID_YEAR) | (combined['year'] > MAX_VALID_YEAR)
    if bad_years.any():
        bad_count = bad_years.sum()
        combined.loc[bad_years, 'year'] = combined.loc[bad_years, 'factbook_edition']
        print(f"  Fixed {bad_count} invalid year values (using edition year as fallback)")

    print(f"\n{'='*60}")
    print(f"Combined Results")
    print(f"{'='*60}")
    print(f"  Editions processed: {successful_editions}")
    print(f"  Total rows: {len(combined)}")
    print(f"  Countries: {combined['loc_id'].nunique()}")
    print(f"  Metrics: {len([c for c in combined.columns if c not in ['loc_id', 'year', 'factbook_edition']])}")
    print(f"  Year range: {int(combined['year'].min())}-{int(combined['year'].max())}")

    # Create metadata
    metadata = create_metadata(combined, editions=successful_editions, source_id=source_id)

    # Save if not dry run
    if not dry_run and output_dir:
        os.makedirs(output_dir, exist_ok=True)

        parquet_path = os.path.join(output_dir, 'all_countries.parquet')

        # Merge with existing data if file exists
        if os.path.exists(parquet_path):
            existing = pd.read_parquet(parquet_path)
            existing_editions = sorted(existing['factbook_edition'].unique())
            print(f"\nMerging with existing data ({len(existing)} rows from editions {existing_editions})")

            # Combine existing + new
            combined = pd.concat([existing, combined], ignore_index=True)

            # Merge values: for each (loc_id, year), take first non-null from newest edition
            combined = combined.sort_values('factbook_edition', ascending=False)
            merge_cols = [c for c in combined.columns if c not in ['loc_id', 'year', 'factbook_edition']]
            merge_dict = {col: 'first' for col in merge_cols}
            merge_dict['factbook_edition'] = 'first'
            combined = combined.groupby(['loc_id', 'year'], as_index=False).agg(merge_dict)
            combined = combined.sort_values(['loc_id', 'year']).reset_index(drop=True)

            # Update editions list for metadata (convert numpy types to Python int)
            all_editions = sorted([int(e) for e in set(existing_editions) | set(successful_editions)])
            metadata = create_metadata(combined, editions=all_editions, source_id=source_id)

            print(f"After merge: {len(combined)} rows, editions {all_editions}")

        combined.to_parquet(parquet_path, index=False)
        print(f"\nSaved: {parquet_path}")

        metadata_path = os.path.join(output_dir, 'metadata.json')
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        print(f"Saved: {metadata_path}")
    elif dry_run:
        print("\n[DRY RUN - no files created]")

    return combined, metadata


# =============================================================================
# CLI
# =============================================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Convert World Factbook to parquet',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Import unique metrics (infrastructure, military, energy details)
  python convert_world_factbook.py --editions 2000,2005,2010,2015,2020 --source-type unique --save

  # Import overlap metrics (demographics, health, GDP)
  python convert_world_factbook.py --editions 2000,2005,2010,2015,2020 --source-type overlap --save

  # Dry run (preview only)
  python convert_world_factbook.py --editions 2020 --source-type unique --dry-run

  # List available metrics by category
  python convert_world_factbook.py --list-metrics
        """
    )

    parser.add_argument('--editions', type=str, default='2020',
                        help='Comma-separated list of editions (e.g., 2000,2005,2010,2015,2020)')
    parser.add_argument('--year', type=int, help='Single factbook year (legacy, use --editions instead)')
    parser.add_argument('--source-type', type=str, choices=['unique', 'overlap', 'all'], default='unique',
                        help='Which metrics to import: unique (51), overlap (27), or all (78)')
    parser.add_argument('--dry-run', action='store_true', help='Preview without saving files (default)')
    parser.add_argument('--save', action='store_true', help='Actually save output files')
    parser.add_argument('--output', type=str, default=None,
                        help='Output directory (auto-set based on source-type if not specified)')
    parser.add_argument('--list-metrics', action='store_true', help='List mapped metrics and exit')

    args = parser.parse_args()

    # --save overrides default dry-run behavior
    dry_run = not args.save

    if args.list_metrics:
        print("\n" + "="*80)
        print("World Factbook Metrics by Category")
        print("="*80)

        print(f"\nUNIQUE METRICS ({len(UNIQUE_METRICS)} - not in other sources):")
        print("-"*60)
        for i, metric in enumerate(sorted(UNIQUE_METRICS), 1):
            print(f"  {i:2}. {metric}")

        print(f"\nOVERLAP METRICS ({len(OVERLAP_METRICS)} - also in OWID/WHO/IMF/SDG):")
        print("-"*60)
        for i, metric in enumerate(sorted(OVERLAP_METRICS), 1):
            print(f"  {i:2}. {metric}")

        print(f"\nTotal: {len(UNIQUE_METRICS)} unique + {len(OVERLAP_METRICS)} overlap = {len(UNIQUE_METRICS) + len(OVERLAP_METRICS)} metrics")

        # Also show which metrics have field mappings
        field_mappings = load_field_mappings()
        mapped = set(field_mappings.keys())
        unique_mapped = set(UNIQUE_METRICS) & mapped
        overlap_mapped = set(OVERLAP_METRICS) & mapped
        print(f"\nCurrently mapped in world_factbook_field_mappings.json:")
        print(f"  Unique: {len(unique_mapped)}/{len(UNIQUE_METRICS)}")
        print(f"  Overlap: {len(overlap_mapped)}/{len(OVERLAP_METRICS)}")
        exit(0)

    # Determine which metrics to extract
    if args.source_type == 'unique':
        metric_names = UNIQUE_METRICS
        source_id = 'world_factbook'
    elif args.source_type == 'overlap':
        metric_names = OVERLAP_METRICS
        source_id = 'world_factbook_overlap'
    else:  # all
        metric_names = UNIQUE_METRICS + OVERLAP_METRICS
        source_id = 'world_factbook_all'

    # Determine output directory
    if args.output:
        output_dir = args.output
    else:
        output_dir = os.path.join(OUTPUT_BASE, source_id)

    # Parse editions
    if args.year:
        editions = [args.year]
    else:
        editions = [int(y.strip()) for y in args.editions.split(',')]

    print(f"\nSource type: {args.source_type}")
    print(f"Metrics to extract: {len(metric_names)}")
    print(f"Output directory: {output_dir}")

    # Run conversion
    df, metadata = convert_all_factbooks(
        editions=editions,
        metric_names=metric_names,
        output_dir=output_dir,
        dry_run=dry_run,
        source_id=source_id
    )

    # Show sample
    if len(df) > 0:
        print("\nSample data:")
        print(df.head(10).to_string())

        print("\nMetrics extracted:")
        for col in sorted(df.columns):
            if col not in ['loc_id', 'year', 'factbook_edition']:
                non_null = df[col].notna().sum()
                print(f"  {col}: {non_null} values")
