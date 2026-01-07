"""
Shared constants for data converters.

Includes:
- Country/region code mappings
- Water body codes
- Standard formulas
"""

# =============================================================================
# USA State FIPS Codes
# =============================================================================

USA_STATE_FIPS = {
    '01': 'AL', '02': 'AK', '04': 'AZ', '05': 'AR', '06': 'CA',
    '08': 'CO', '09': 'CT', '10': 'DE', '11': 'DC', '12': 'FL',
    '13': 'GA', '15': 'HI', '16': 'ID', '17': 'IL', '18': 'IN',
    '19': 'IA', '20': 'KS', '21': 'KY', '22': 'LA', '23': 'ME',
    '24': 'MD', '25': 'MA', '26': 'MI', '27': 'MN', '28': 'MS',
    '29': 'MO', '30': 'MT', '31': 'NE', '32': 'NV', '33': 'NH',
    '34': 'NJ', '35': 'NM', '36': 'NY', '37': 'NC', '38': 'ND',
    '39': 'OH', '40': 'OK', '41': 'OR', '42': 'PA', '44': 'RI',
    '45': 'SC', '46': 'SD', '47': 'TN', '48': 'TX', '49': 'UT',
    '50': 'VT', '51': 'VA', '53': 'WA', '54': 'WV', '55': 'WI',
    '56': 'WY', '72': 'PR', '78': 'VI', '66': 'GU', '69': 'MP',
    '60': 'AS'
}

USA_STATE_FIPS_REVERSE = {v: k for k, v in USA_STATE_FIPS.items()}


# =============================================================================
# Canada Province/Territory Codes
# =============================================================================

CAN_PROVINCE_ABBR = {
    "10": "NL",   # Newfoundland and Labrador
    "11": "PE",   # Prince Edward Island
    "12": "NS",   # Nova Scotia
    "13": "NB",   # New Brunswick
    "24": "QC",   # Quebec
    "35": "ON",   # Ontario
    "46": "MB",   # Manitoba
    "47": "SK",   # Saskatchewan
    "48": "AB",   # Alberta
    "59": "BC",   # British Columbia
    "60": "YT",   # Yukon
    "61": "NT",   # Northwest Territories
    "62": "NU",   # Nunavut
}

CAN_PROVINCE_ABBR_REVERSE = {v: k for k, v in CAN_PROVINCE_ABBR.items()}


# =============================================================================
# Australia State/Territory Codes
# =============================================================================

AUS_STATE_ABBR = {
    1: "NSW",  # New South Wales
    2: "VIC",  # Victoria
    3: "QLD",  # Queensland
    4: "SA",   # South Australia
    5: "WA",   # Western Australia
    6: "TAS",  # Tasmania
    7: "NT",   # Northern Territory
    8: "ACT",  # Australian Capital Territory
    9: "OT"    # Other Territories
}

AUS_STATE_ABBR_REVERSE = {v: k for k, v in AUS_STATE_ABBR.items()}


# =============================================================================
# Water Body Codes (ISO 3166-1 X-prefix convention)
# =============================================================================

WATER_BODY_CODES = {
    # Oceans
    "XOP": "Pacific Ocean",
    "XOA": "Atlantic Ocean",
    "XOI": "Indian Ocean",
    "XON": "Arctic Ocean",
    "XOO": "Unknown Ocean",

    # Seas - Americas
    "XSG": "Gulf of Mexico",
    "XSC": "Caribbean Sea",
    "XSB": "Bering Sea",
    "XSL": "Labrador Sea",

    # Seas - Canada
    "XSH": "Hudson Bay",
    "XSE": "Beaufort Sea",

    # Seas - Australia/Pacific
    "XST": "Tasman Sea",
    "XSR": "Coral Sea",
    "XSA": "Arafura Sea",

    # Seas - Asia
    "XSS": "South China Sea",
    "XSJ": "Sea of Japan",

    # Seas - Europe
    "XSN": "North Sea",
    "XSM": "Mediterranean Sea",
    "XSK": "Baltic Sea",
}


# =============================================================================
# Territorial Waters Threshold
# =============================================================================

# 12 nautical miles = ~22.2 km = ~0.2 degrees latitude
TERRITORIAL_WATERS_DEG = 0.2


# =============================================================================
# Hazard Type Categories
# =============================================================================

HAZARD_CATEGORIES = {
    "earthquake": ["earthquake", "seismic", "tremor", "quake"],
    "cyclone": ["hurricane", "typhoon", "cyclone", "tropical storm"],
    "tornado": ["tornado", "twister", "funnel"],
    "flood": ["flood", "flash flood", "coastal flood", "river flood"],
    "wildfire": ["wildfire", "fire", "bushfire", "forest fire"],
    "drought": ["drought", "dry spell", "water shortage"],
    "volcano": ["volcano", "eruption", "volcanic"],
    "tsunami": ["tsunami", "tidal wave"],
    "storm": ["storm", "severe weather", "thunderstorm", "hail"],
    "landslide": ["landslide", "mudslide", "debris flow"],
    "heat": ["heat wave", "extreme heat"],
    "cold": ["cold wave", "freeze", "winter storm", "blizzard"],
}


# =============================================================================
# Magnitude/Intensity Scales
# =============================================================================

# Saffir-Simpson Hurricane Wind Scale
SAFFIR_SIMPSON_SCALE = {
    1: {"min_wind_kt": 64, "max_wind_kt": 82, "description": "Category 1"},
    2: {"min_wind_kt": 83, "max_wind_kt": 95, "description": "Category 2"},
    3: {"min_wind_kt": 96, "max_wind_kt": 112, "description": "Category 3 (Major)"},
    4: {"min_wind_kt": 113, "max_wind_kt": 136, "description": "Category 4 (Major)"},
    5: {"min_wind_kt": 137, "max_wind_kt": 999, "description": "Category 5 (Major)"},
}

# Volcanic Explosivity Index (VEI)
VEI_SCALE = {
    0: {"description": "Non-explosive", "plume_km": "<0.1", "volume_m3": "<1e4"},
    1: {"description": "Gentle", "plume_km": "0.1-1", "volume_m3": "1e4-1e6"},
    2: {"description": "Explosive", "plume_km": "1-5", "volume_m3": "1e6-1e7"},
    3: {"description": "Severe", "plume_km": "3-15", "volume_m3": "1e7-1e8"},
    4: {"description": "Cataclysmic", "plume_km": "10-25", "volume_m3": "1e8-1e9"},
    5: {"description": "Paroxysmal", "plume_km": ">25", "volume_m3": "1e9-1e10"},
    6: {"description": "Colossal", "plume_km": ">25", "volume_m3": "1e10-1e11"},
    7: {"description": "Super-colossal", "plume_km": ">25", "volume_m3": "1e11-1e12"},
    8: {"description": "Mega-colossal", "plume_km": ">25", "volume_m3": ">1e12"},
}

# USDM Drought Levels
DROUGHT_LEVELS = {
    "D0": {"description": "Abnormally Dry", "weight": 1},
    "D1": {"description": "Moderate Drought", "weight": 2},
    "D2": {"description": "Severe Drought", "weight": 3},
    "D3": {"description": "Extreme Drought", "weight": 4},
    "D4": {"description": "Exceptional Drought", "weight": 5},
}
