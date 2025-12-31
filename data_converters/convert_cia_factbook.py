"""
CIA World Factbook Converter

Converts CIA World Factbook HTML data to standardized parquet format.

SOURCE TYPE: cia_factbook
This is a multi-year source. Each factbook edition (2000-2024) can be processed.
The factbook is published annually with data from the previous year.

RAW DATA LOCATION:
    county-map-data/Raw data/factbook-{year}/

OUTPUT LOCATION (TBD - folder structure decision needed):
    Option A: county-map-data/data/cia_factbook/all_countries.parquet (all years combined)
    Option B: county-map-data/data/cia_factbook_{year}/all_countries.parquet (per edition)
    Option C: county-map-data/data/cia_factbook/all_countries.parquet + year column (recommended)

DATA OVERLAP CONSIDERATIONS:
    CIA Factbook overlaps with several existing sources:
    - Population: Also in OWID, Census (US), UN SDGs
    - GDP: Also in OWID, IMF, World Bank
    - Life expectancy: Also in WHO, OWID
    - CO2 emissions: Also in OWID

    Trust hierarchy (suggested):
    1. Specialized agencies (WHO for health, IMF for economics) - most authoritative
    2. CIA Factbook - good coverage, consistent methodology, but secondary source
    3. Aggregators (OWID) - convenient but third-hand

    CIA Factbook unique value:
    - Comprehensive single-source coverage (same methodology across all countries)
    - Many unique metrics (military spending, infrastructure, energy details)
    - Historical editions allow time series reconstruction

AVAILABLE METRICS (66 quantitative):
    See METRICS dict below for full list with field IDs
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
    # Unique to CIA Factbook or best coverage here
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
# CIA CODE TO ISO3 MAPPING
# =============================================================================

def build_cia_to_iso3_mapping(factbook_path: str) -> Dict[str, str]:
    """
    Build mapping from CIA country codes to ISO3 codes.
    Parses appendix-d.html from the factbook.

    Returns:
        Dict mapping uppercase CIA codes to ISO3 codes
    """
    appendix_path = os.path.join(factbook_path, 'appendix', 'appendix-d.html')

    if not os.path.exists(appendix_path):
        print(f"Warning: appendix-d.html not found at {appendix_path}")
        return get_fallback_cia_mapping()

    with open(appendix_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Pattern to extract: geos link -> country name -> FIPS -> ISO2 -> ISO3 -> numeric
    pattern = (
        r"<a href='../geos/([a-z]+)\.html'>([^<]+)</a>.*?"
        r"<td[^>]*>([^<]*)</td>.*?"  # FIPS
        r"<td[^>]*>([^<]*)</td>.*?"  # ISO alpha-2
        r"<td[^>]*>([^<]*)</td>.*?"  # ISO alpha-3
        r"<td[^>]*>([^<]*)</td>"     # ISO numeric
    )

    matches = re.findall(pattern, content, re.DOTALL)

    cia_to_iso3 = {}
    for cia, name, fips, iso2, iso3, numeric in matches:
        if iso3 and iso3.strip() != '-':
            cia_to_iso3[cia.upper()] = iso3.strip()

    print(f"Built CIA->ISO3 mapping with {len(cia_to_iso3)} entries")
    return cia_to_iso3


def get_fallback_cia_mapping() -> Dict[str, str]:
    """
    Fallback hardcoded mapping for common countries.
    Used if appendix-d.html parsing fails.
    """
    return {
        'US': 'USA', 'CA': 'CAN', 'MX': 'MEX', 'UK': 'GBR', 'FR': 'FRA',
        'GM': 'DEU', 'IT': 'ITA', 'SP': 'ESP', 'JA': 'JPN', 'CH': 'CHN',
        'IN': 'IND', 'RS': 'RUS', 'BR': 'BRA', 'AS': 'AUS', 'SF': 'ZAF',
        # Add more as needed
    }


# =============================================================================
# VALUE PARSING
# =============================================================================

def parse_value(value_str: str) -> Optional[float]:
    """
    Parse a value string from CIA Factbook into a numeric value.

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

    # Remove currency symbols and parentheses
    s = re.sub(r'[\$\(\)]', '', s)

    # Check for negative (sometimes in parentheses)
    is_negative = s.startswith('-') or '(' in value_str
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

    # Remove commas and whitespace
    s = re.sub(r'[,\s]', '', s)

    # Remove percent sign (keep the number)
    s = s.rstrip('%')

    # Remove any remaining non-numeric characters except decimal point and minus
    s = re.sub(r'[^\d.\-]', '', s)

    if not s:
        return None

    try:
        value = float(s) * multiplier
        return -value if is_negative else value
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
# DATA EXTRACTION
# =============================================================================

def extract_rank_data(factbook_path: str, field_id: str, cia_to_iso3: Dict[str, str], default_year: int = None) -> List[dict]:
    """
    Extract data from a rank file.

    Args:
        factbook_path: Path to factbook directory
        field_id: The field ID (e.g., '335' for population)
        cia_to_iso3: Mapping from CIA codes to ISO3
        default_year: Year to use when not specified in data (factbook_year - 1)

    Returns:
        List of dicts with keys: loc_id, year, value
    """
    rank_file = os.path.join(factbook_path, 'fields', f'{field_id}rank.html')

    if not os.path.exists(rank_file):
        return []

    with open(rank_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Pattern to match table rows
    # <tr id="US" class='rankorder north-america'>
    #   <td scope='row'>23</td>
    #   <td class='region'><a href='../geos/us.html'>United States</a></td>
    #   <td>$55,761</td>
    #   <td>2019 est.</td>
    # </tr>

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

        # Use default year if year not specified in data
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


def extract_all_metrics(factbook_path: str, metric_ids: List[str] = None, factbook_year: int = None) -> pd.DataFrame:
    """
    Extract all specified metrics from a factbook edition.

    Args:
        factbook_path: Path to factbook directory
        metric_ids: List of field IDs to extract (None = all available)
        factbook_year: Edition year (used as default when data doesn't specify year)

    Returns:
        DataFrame with columns: loc_id, year, [metric columns]
    """
    cia_to_iso3 = build_cia_to_iso3_mapping(factbook_path)

    if metric_ids is None:
        metric_ids = list(METRICS.keys())

    # Default year for data without explicit year (factbook typically has prior year data)
    # Use factbook_year - 1 as a reasonable default
    default_year = (factbook_year - 1) if factbook_year else None

    # Collect all data by loc_id and year
    all_data = {}  # (loc_id, year) -> {metric: value}

    for field_id in metric_ids:
        if field_id not in METRICS:
            print(f"Warning: Unknown field ID {field_id}")
            continue

        metric_name = METRICS[field_id][0]
        print(f"  Extracting {metric_name} (field {field_id})...")

        rows = extract_rank_data(factbook_path, field_id, cia_to_iso3, default_year=default_year)

        for row in rows:
            key = (row['loc_id'], row['year'])
            if key not in all_data:
                all_data[key] = {}
            all_data[key][metric_name] = row['value']

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

def create_metadata(factbook_year: int, df: pd.DataFrame, extracted_metrics: List[str]) -> dict:
    """Create metadata.json for a factbook extraction."""

    metric_definitions = {}
    for field_id in extracted_metrics:
        if field_id in METRICS:
            name, unit, agg, desc = METRICS[field_id]
            metric_definitions[name] = {
                'name': desc,
                'unit': unit,
                'aggregation': agg,
                'cia_field_id': field_id
            }

    # Get year range from data
    years = df['year'].dropna().unique()
    year_start = int(min(years)) if len(years) > 0 else factbook_year - 1
    year_end = int(max(years)) if len(years) > 0 else factbook_year - 1

    return {
        'source_id': 'cia_factbook',
        'source_name': 'CIA World Factbook',
        'source_url': 'https://www.cia.gov/the-world-factbook/',
        'license': 'Public Domain (US Government Work)',
        'description': f'CIA World Factbook {factbook_year} edition - comprehensive country data',
        'category': 'reference',
        'topic_tags': ['demographics', 'economy', 'energy', 'infrastructure', 'military', 'health'],
        'keywords': ['cia', 'factbook', 'country profiles', 'world data'],

        'last_updated': datetime.now().strftime('%Y-%m-%d'),
        'factbook_edition': factbook_year,
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
            f'CIA World Factbook {factbook_year}: {df["loc_id"].nunique() if len(df) > 0 else 0} countries, '
            f'{len(extracted_metrics)} metrics including demographics, economy, energy, military, infrastructure.'
        ),

        'data_notes': {
            'overlap_with': ['owid_co2 (GDP, population, CO2)', 'who_health (life expectancy)', 'imf_bop (trade)'],
            'unique_metrics': ['military expenditure', 'infrastructure (airports, railways)', 'energy source percentages'],
            'methodology': 'CIA compiles from multiple sources; values may differ from primary sources'
        }
    }


# =============================================================================
# MAIN CONVERSION
# =============================================================================

def convert_factbook(
    factbook_year: int,
    metric_ids: List[str] = None,
    output_dir: str = None,
    dry_run: bool = True
) -> Tuple[pd.DataFrame, dict]:
    """
    Convert a CIA World Factbook edition to parquet format.

    Args:
        factbook_year: Year of the factbook edition (e.g., 2020)
        metric_ids: List of field IDs to extract (None = priority metrics)
        output_dir: Output directory (None = don't save)
        dry_run: If True, don't create output files

    Returns:
        Tuple of (DataFrame, metadata dict)
    """
    factbook_path = os.path.join(RAW_DATA_BASE, f'factbook-{factbook_year}')

    if not os.path.exists(factbook_path):
        raise FileNotFoundError(f"Factbook not found at {factbook_path}")

    print(f"\n{'='*60}")
    print(f"Converting CIA World Factbook {factbook_year}")
    print(f"{'='*60}")
    print(f"Source: {factbook_path}")

    # Use priority metrics if not specified
    if metric_ids is None:
        metric_ids = PRIORITY_METRICS
        print(f"Using {len(metric_ids)} priority metrics")

    # Extract data
    print("\nExtracting metrics...")
    df = extract_all_metrics(factbook_path, metric_ids, factbook_year=factbook_year)

    print(f"\nExtraction complete:")
    print(f"  Total rows: {len(df)}")
    print(f"  Countries: {df['loc_id'].nunique() if len(df) > 0 else 0}")
    print(f"  Metrics: {len([c for c in df.columns if c not in ['loc_id', 'year']])}")

    # Create metadata
    metadata = create_metadata(factbook_year, df, metric_ids)

    # Save if not dry run
    if not dry_run and output_dir:
        os.makedirs(output_dir, exist_ok=True)

        parquet_path = os.path.join(output_dir, 'all_countries.parquet')
        df.to_parquet(parquet_path, index=False)
        print(f"\nSaved: {parquet_path}")

        metadata_path = os.path.join(output_dir, 'metadata.json')
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        print(f"Saved: {metadata_path}")
    elif dry_run:
        print("\n[DRY RUN - no files created]")

    return df, metadata


def convert_all_factbooks(
    years: List[int],
    output_base: str = None,
    dry_run: bool = True
) -> pd.DataFrame:
    """
    Convert multiple factbook editions and combine into single dataset.

    Args:
        years: List of factbook years to process
        output_base: Base output directory
        dry_run: If True, don't create output files

    Returns:
        Combined DataFrame with all years
    """
    all_dfs = []

    for year in years:
        try:
            df, _ = convert_factbook(year, dry_run=True)
            df['factbook_edition'] = year
            all_dfs.append(df)
        except FileNotFoundError as e:
            print(f"Skipping {year}: {e}")

    if not all_dfs:
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)

    # For duplicate (loc_id, year, metric) entries from different editions,
    # prefer the more recent factbook edition
    combined = combined.sort_values('factbook_edition', ascending=False)
    combined = combined.drop_duplicates(subset=['loc_id', 'year'], keep='first')
    combined = combined.sort_values(['loc_id', 'year']).reset_index(drop=True)

    print(f"\n{'='*60}")
    print(f"Combined dataset: {len(combined)} rows, {combined['loc_id'].nunique()} countries")
    print(f"Year range: {combined['year'].min()}-{combined['year'].max()}")

    return combined


# =============================================================================
# CLI
# =============================================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Convert CIA World Factbook to parquet')
    parser.add_argument('--year', type=int, default=2020, help='Factbook year to convert')
    parser.add_argument('--all-metrics', action='store_true', help='Extract all 66 metrics (default: priority only)')
    parser.add_argument('--dry-run', action='store_true', default=True, help='Do not create output files')
    parser.add_argument('--output', type=str, help='Output directory')
    parser.add_argument('--list-metrics', action='store_true', help='List available metrics and exit')

    args = parser.parse_args()

    if args.list_metrics:
        print("\nAvailable CIA Factbook Metrics:")
        print("="*80)
        for field_id, (name, unit, agg, desc) in sorted(METRICS.items(), key=lambda x: x[1][0]):
            priority = '*' if field_id in PRIORITY_METRICS else ' '
            print(f"{priority} {field_id:4} {name:35} {unit:15} {desc}")
        print("\n* = Priority metric (extracted by default)")
        exit(0)

    # None = all metrics, PRIORITY_METRICS = priority only
    metric_ids = list(METRICS.keys()) if args.all_metrics else PRIORITY_METRICS

    df, metadata = convert_factbook(
        factbook_year=args.year,
        metric_ids=metric_ids,
        output_dir=args.output,
        dry_run=args.dry_run
    )

    # Show sample
    if len(df) > 0:
        print("\nSample data:")
        print(df.head(10).to_string())

        print("\nMetrics extracted:")
        for col in df.columns:
            if col not in ['loc_id', 'year']:
                non_null = df[col].notna().sum()
                print(f"  {col}: {non_null} values")
