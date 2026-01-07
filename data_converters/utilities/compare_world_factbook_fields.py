"""
Compare all 165 CIA Factbook fields against our existing 3 sources.
"""

# === OUR EXISTING SOURCES ===

# 1. world_factbook (from scrape_world_factbook_2025.py) - time series comparison data
# 2. world_factbook_static (from scrape_cia_static_data.py) - reference data
# 3. reference scraper (from scrape_cia_reference_data.py) - new reference fields

# === MAPPING CIA FIELDS TO OUR SOURCES ===
field_coverage = {
    # --- WE HAVE (world_factbook time series) ---
    'Area': 'world_factbook (area_sq_km)',
    'Population': 'world_factbook (population)',
    'Median age': 'world_factbook (median_age)',
    'Population growth rate': 'world_factbook (pop_growth_rate)',
    'Birth rate': 'world_factbook (birth_rate)',
    'Death rate': 'world_factbook (death_rate)',
    'Net migration rate': 'world_factbook (net_migration_rate)',
    'Maternal mortality ratio': 'world_factbook (maternal_mortality)',
    'Infant mortality rate': 'world_factbook (infant_mortality)',
    'Life expectancy at birth': 'world_factbook (life_expectancy)',
    'Total fertility rate': 'world_factbook (fertility_rate)',
    'Obesity - adult prevalence rate': 'world_factbook (obesity_rate)',
    'Children under the age of 5 years underweight': 'world_factbook (child_underweight)',
    'Education expenditure': 'world_factbook (education_expenditure)',
    'Carbon dioxide emissions': 'world_factbook (co2_emissions)',
    'Real GDP (purchasing power parity)': 'world_factbook (gdp_ppp)',
    'Real GDP growth rate': 'world_factbook (gdp_growth_rate)',
    'Real GDP per capita': 'world_factbook (gdp_per_capita_ppp)',
    'Inflation rate (consumer prices)': 'world_factbook (inflation_rate)',
    'Industrial production growth rate': 'world_factbook (industrial_production_growth)',
    'Labor force': 'world_factbook (labor_force)',
    'Unemployment rate': 'world_factbook (unemployment_rate)',
    'Youth unemployment rate (ages 15-24)': 'world_factbook (youth_unemployment)',
    'Gini Index coefficient - distribution of family income': 'world_factbook (gini_index)',
    'Public debt': 'world_factbook (public_debt_pct_gdp)',
    'Taxes and other revenues': 'world_factbook (taxes_revenue_pct_gdp)',
    'Current account balance': 'world_factbook (current_account_balance)',
    'Exports': 'world_factbook (exports)',
    'Imports': 'world_factbook (imports)',
    'Reserves of foreign exchange and gold': 'world_factbook (foreign_reserves)',
    'Debt - external': 'world_factbook (external_debt)',
    'Telephones - fixed lines': 'world_factbook (telephones_fixed)',
    'Telephones - mobile cellular': 'world_factbook (telephones_mobile)',
    'Broadband - fixed subscriptions': 'world_factbook (broadband_subscriptions)',
    'Airports': 'world_factbook (airports)',
    'Merchant marine': 'world_factbook (merchant_marine)',

    # --- WE HAVE (world_factbook_static) ---
    'Geographic coordinates': 'world_factbook_static (lat/lon)',
    'Coastline': 'world_factbook_static (coastline_km)',
    'Land boundaries': 'world_factbook_static (land_boundaries_km)',
    'Elevation': 'world_factbook_static (highest/lowest/mean)',
    'Capital': 'world_factbook_static (capital_name, lat/lon)',
    'Climate': 'world_factbook_static (climate)',
    'Terrain': 'world_factbook_static (terrain)',
    'Natural resources': 'world_factbook_static (natural_resources)',
    'Natural hazards': 'world_factbook_static (natural_hazards)',

    # --- WE HAVE (reference scraper) ---
    'Languages': 'reference_scraper (languages, official)',
    'Religions': 'reference_scraper (religions)',
    'Ethnic groups': 'reference_scraper (ethnic_groups)',
    'Government type': 'reference_scraper (government_type)',
    'Independence': 'reference_scraper (independence)',
    'Legal system': 'reference_scraper (legal_system)',
    'Suffrage': 'reference_scraper (suffrage)',
    'Internet country code': 'reference_scraper (internet_country_code)',
    'Internet users': 'reference_scraper (internet_users)',
}

# Categorize ALL 165 fields
categories = {
    'Demographics & Population': [
        'Age structure', 'Birth rate', 'Death rate', 'Dependency ratios',
        'Life expectancy at birth', 'Median age', 'Net migration rate',
        'Population', 'Population distribution', 'Population growth rate', 'Sex ratio',
        'Total fertility rate', 'Urbanization', 'Major urban areas - population',
        'Gross reproduction rate', 'Currently married women (ages 15-49)',
        'Mothers mean age at first birth', 'Nationality', 'People - note'
    ],
    'Health & Education': [
        'Alcohol consumption per capita', 'Children under the age of 5 years underweight',
        'Child marriage', 'Drinking water source', 'Education expenditure',
        'Health expenditure', 'Hospital bed density', 'Infant mortality rate',
        'Literacy', 'Maternal mortality ratio', 'Obesity - adult prevalence rate',
        'Physician density', 'Sanitation facility access',
        'School life expectancy (primary to tertiary education)', 'Tobacco use'
    ],
    'Economy & Finance': [
        'Average household expenditures', 'Budget', 'Current account balance',
        'Debt - external', 'Economic overview', 'Exchange rates', 'Exports',
        'GDP (official exchange rate)', 'GDP - composition, by end use',
        'GDP - composition, by sector of origin',
        'Gini Index coefficient - distribution of family income',
        'Household income or consumption by percentage share', 'Imports',
        'Industrial production growth rate', 'Industries', 'Inflation rate (consumer prices)',
        'Labor force', 'Population below poverty line', 'Public debt',
        'Real GDP (purchasing power parity)', 'Real GDP growth rate', 'Real GDP per capita',
        'Remittances', 'Reserves of foreign exchange and gold', 'Taxes and other revenues',
        'Unemployment rate', 'Youth unemployment rate (ages 15-24)'
    ],
    'Trade': [
        'Exports - commodities', 'Exports - partners',
        'Imports - commodities', 'Imports - partners', 'Agricultural products'
    ],
    'Geography': [
        'Area', 'Area - comparative', 'Capital', 'Climate', 'Coastline',
        'Elevation', 'Geographic coordinates', 'Geography - note', 'Geoparks',
        'Irrigated land', 'Land boundaries', 'Land use', 'Location', 'Map references',
        'Maritime claims', 'Natural hazards', 'Natural resources', 'Terrain',
        'Total renewable water resources', 'Major aquifers', 'Major lakes (area sq km)',
        'Major rivers (by length in km)', 'Major watersheds (area sq km)'
    ],
    'Energy & Environment': [
        'Carbon dioxide emissions', 'Coal', 'Electricity', 'Electricity access',
        'Electricity generation sources', 'Energy consumption per capita',
        'Environmental issues', 'International environmental agreements',
        'Methane emissions', 'Natural gas', 'Nuclear energy', 'Particulate matter emissions',
        'Petroleum', 'Total water withdrawal', 'Waste and recycling'
    ],
    'Government & Politics': [
        'Administrative divisions', 'Background', 'Citizenship', 'Constitution',
        'Country name', 'Dependency status', 'Dependent areas', 'Executive branch',
        'Flag', 'Government - note', 'Government type', 'Independence', 'Judicial branch',
        'Legal system', 'Legislative branch', 'Legislative branch - lower chamber',
        'Legislative branch - upper chamber', 'National anthem(s)', 'National coat of arms',
        'National color(s)', 'National heritage', 'National holiday', 'National symbol(s)',
        'Political parties', 'Suffrage'
    ],
    'International Relations': [
        'Diplomatic representation from the US', 'Diplomatic representation in the US',
        'International law organization participation',
        'International organization participation'
    ],
    'Society & Culture': [
        'Ethnic groups', 'Languages', 'Religions'
    ],
    'Military & Security': [
        'Military - note', 'Military and security forces',
        'Military and security service personnel strengths', 'Military deployments',
        'Military equipment inventories and acquisitions', 'Military expenditures',
        'Military service age and obligation', 'Terrorist group(s)'
    ],
    'Transportation': [
        'Airports', 'Civil aircraft registration country code prefix',
        'Heliports', 'Merchant marine', 'Ports', 'Railways', 'Transportation - note'
    ],
    'Communications': [
        'Broadcast media', 'Broadband - fixed subscriptions', 'Communications - note',
        'Internet country code', 'Internet users',
        'Telephones - fixed lines', 'Telephones - mobile cellular'
    ],
    'Space': [
        'Key space-program milestones', 'Space agency/agencies',
        'Space launch site(s)', 'Space program overview'
    ],
    'Other': [
        'Illicit drugs', 'Refugees and internally displaced persons', 'Trafficking in persons'
    ]
}

if __name__ == '__main__':
    print('=' * 80)
    print('CIA FACTBOOK: 165 FIELDS vs OUR 3 SOURCES')
    print('=' * 80)
    print()

    have_count = 0
    missing_count = 0

    for cat_name, fields in categories.items():
        have = []
        missing = []
        for f in fields:
            if f in field_coverage:
                have.append((f, field_coverage[f]))
            else:
                missing.append(f)

        have_count += len(have)
        missing_count += len(missing)

        print(f'### {cat_name} ({len(have)}/{len(fields)} covered)')
        print()
        if have:
            print('HAVE:')
            for f, source in have:
                print(f'  [+] {f} -> {source}')
        if missing:
            print('MISSING:')
            for f in missing:
                print(f'  [ ] {f}')
        print()

    print('=' * 80)
    print(f'SUMMARY: {have_count} covered, {missing_count} missing out of {have_count + missing_count} total')
    print('=' * 80)
