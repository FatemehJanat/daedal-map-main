"""
Constants and static data used across the mapmover application.
"""

# State abbreviations mapping
state_abbreviations = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "DC": "District of Columbia"
}

# Unit multiplier mappings for filter value conversion
UNIT_MULTIPLIERS = {
    "trillion": 1_000_000_000_000,
    "billion": 1_000_000_000,
    "million": 1_000_000,
    "thousand": 1_000,
    "k": 1_000,
    "m": 1_000_000,
    "b": 1_000_000_000,
    "t": 1_000_000_000_000
}

# Datasets that are geometry/reference only - should not be selected as primary data sources
# These will still be used for geometry joins, but won't be offered to the LLM for data queries
GEOMETRY_ONLY_DATASETS = {
    'Countries.csv',        # 252 rows - country polygons with limited snapshot data (not time-series)
    'Populated Places.csv', # 7,342 rows - city point locations, population data has quality issues
    'usplaces.csv',         # 35,841 rows - US place points, only has area data (no demographics/economics)
}

# Essential columns that should always be loaded (identifiers and time)
# Note: Geometry comes from Countries.csv via enrichment, not from data CSVs
ESSENTIAL_COLUMNS = {
    # Identifier columns (for joining/matching)
    'country_name', 'country_code', 'country', 'name', 'iso_code', 'iso3',
    'state', 'state_name', 'state_code', 'stname', 'ctyname',
    'place_name', 'city', 'region',
    # Time columns
    'year', 'data_year', 'date',
}

# Topic-specific columns to include based on query keywords
TOPIC_COLUMNS = {
    'gdp': {'gdp', 'gdp_per_capita', 'gdp_growth'},
    'population': {'population', 'pop', 'popestimate', 'tot_pop', 'total_population'},
    'co2': {'co2', 'co2_per_capita', 'total_ghg', 'ghg', 'emissions', 'coal_co2', 'oil_co2', 'gas_co2'},
    'energy': {'energy', 'energy_per_capita', 'primary_energy', 'renewables', 'fossil_fuel'},
    'health': {'health', 'life_expectancy', 'mortality', 'births', 'deaths'},
    'temperature': {'temperature', 'temp', 'temperature_change'},
    'trade': {'trade', 'exports', 'imports', 'balance'},
    'age': {'median_age', 'age_group', 'age0to4', 'age5to9', 'age10to14', 'age15to19'},
}
