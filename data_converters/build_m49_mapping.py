"""
Build M49 to ISO3 country code mapping from SDG data.

UN M49 codes are numeric country/region codes used in SDG database.
We need to convert these to ISO3 alpha codes used in our system.
"""

import pandas as pd
import json
from pathlib import Path


def build_m49_mapping():
    """Build M49 to ISO3 country code mapping."""

    # Load our existing ISO3 codes from conversions.json
    conv_path = Path(__file__).parent.parent / "mapmover" / "conversions.json"
    with open(conv_path, encoding='utf-8') as f:
        conv = json.load(f)

    iso_codes = conv['iso_country_codes']  # ISO3 -> name
    iso_names = {name.lower(): code for code, name in iso_codes.items()}  # name -> ISO3

    # Comprehensive M49 to ISO3 mapping
    # See: https://unstats.un.org/unsd/methodology/m49/
    direct_m49_mapping = {
        # Major countries with alternate names in SDG data
        840: 'USA',  # United States of America
        826: 'GBR',  # United Kingdom
        643: 'RUS',  # Russian Federation
        410: 'KOR',  # Republic of Korea
        408: 'PRK',  # DPRK
        364: 'IRN',  # Iran
        704: 'VNM',  # Viet Nam
        862: 'VEN',  # Venezuela
        68: 'BOL',   # Bolivia
        158: 'TWN',  # Taiwan
        344: 'HKG',  # Hong Kong SAR
        446: 'MAC',  # Macao SAR
        275: 'PSE',  # Palestine
        336: 'VAT',  # Holy See
        96: 'BRN',   # Brunei
        418: 'LAO',  # Laos
        760: 'SYR',  # Syria
        834: 'TZA',  # Tanzania
        132: 'CPV',  # Cabo Verde
        626: 'TLS',  # Timor-Leste
        748: 'SWZ',  # Eswatini
        807: 'MKD',  # North Macedonia
        178: 'COG',  # Congo
        180: 'COD',  # DR Congo
        384: 'CIV',  # Ivory Coast
        203: 'CZE',  # Czechia
        792: 'TUR',  # Turkey/Turkiye
        498: 'MDA',  # Moldova
        583: 'FSM',  # Micronesia

        # Territories
        16: 'ASM',   # American Samoa
        60: 'BMU',   # Bermuda
        92: 'VGB',   # British Virgin Islands
        136: 'CYM',  # Cayman Islands
        184: 'COK',  # Cook Islands
        238: 'FLK',  # Falkland Islands
        234: 'FRO',  # Faroe Islands
        258: 'PYF',  # French Polynesia
        304: 'GRL',  # Greenland
        312: 'GLP',  # Guadeloupe
        316: 'GUM',  # Guam
        474: 'MTQ',  # Martinique
        500: 'MSR',  # Montserrat
        540: 'NCL',  # New Caledonia
        570: 'NIU',  # Niue
        574: 'NFK',  # Norfolk Island
        580: 'MNP',  # Northern Mariana Islands
        612: 'PCN',  # Pitcairn
        630: 'PRI',  # Puerto Rico
        638: 'REU',  # Reunion
        660: 'AIA',  # Anguilla
        666: 'SPM',  # Saint Pierre and Miquelon
        652: 'BLM',  # Saint Barthelemy
        654: 'SHN',  # Saint Helena
        663: 'MAF',  # Saint Martin (French)
        670: 'VCT',  # Saint Vincent
        796: 'TCA',  # Turks and Caicos
        850: 'VIR',  # US Virgin Islands
        876: 'WLF',  # Wallis and Futuna
        831: 'GGY',  # Guernsey
        832: 'JEY',  # Jersey
        833: 'IMN',  # Isle of Man

        # Standard countries (M49 -> ISO3)
        4: 'AFG', 8: 'ALB', 12: 'DZA', 20: 'AND', 24: 'AGO',
        28: 'ATG', 32: 'ARG', 51: 'ARM', 36: 'AUS', 40: 'AUT',
        31: 'AZE', 44: 'BHS', 48: 'BHR', 50: 'BGD', 52: 'BRB',
        112: 'BLR', 56: 'BEL', 84: 'BLZ', 204: 'BEN', 64: 'BTN',
        70: 'BIH', 72: 'BWA', 76: 'BRA', 100: 'BGR', 854: 'BFA',
        108: 'BDI', 116: 'KHM', 120: 'CMR', 124: 'CAN', 140: 'CAF',
        148: 'TCD', 152: 'CHL', 156: 'CHN', 170: 'COL', 174: 'COM',
        188: 'CRI', 191: 'HRV', 192: 'CUB', 196: 'CYP', 208: 'DNK',
        262: 'DJI', 212: 'DMA', 214: 'DOM', 218: 'ECU', 818: 'EGY',
        222: 'SLV', 226: 'GNQ', 232: 'ERI', 233: 'EST', 231: 'ETH',
        242: 'FJI', 246: 'FIN', 250: 'FRA', 266: 'GAB', 270: 'GMB',
        268: 'GEO', 276: 'DEU', 288: 'GHA', 300: 'GRC', 308: 'GRD',
        320: 'GTM', 324: 'GIN', 624: 'GNB', 328: 'GUY', 332: 'HTI',
        340: 'HND', 348: 'HUN', 352: 'ISL', 356: 'IND', 360: 'IDN',
        368: 'IRQ', 372: 'IRL', 376: 'ISR', 380: 'ITA', 388: 'JAM',
        392: 'JPN', 400: 'JOR', 398: 'KAZ', 404: 'KEN', 296: 'KIR',
        414: 'KWT', 417: 'KGZ', 422: 'LBN', 426: 'LSO', 430: 'LBR',
        434: 'LBY', 438: 'LIE', 440: 'LTU', 442: 'LUX', 450: 'MDG',
        454: 'MWI', 458: 'MYS', 462: 'MDV', 466: 'MLI', 470: 'MLT',
        584: 'MHL', 478: 'MRT', 480: 'MUS', 484: 'MEX', 496: 'MNG',
        499: 'MNE', 504: 'MAR', 508: 'MOZ', 104: 'MMR', 516: 'NAM',
        520: 'NRU', 524: 'NPL', 528: 'NLD', 554: 'NZL', 558: 'NIC',
        562: 'NER', 566: 'NGA', 578: 'NOR', 512: 'OMN', 586: 'PAK',
        585: 'PLW', 591: 'PAN', 598: 'PNG', 600: 'PRY', 604: 'PER',
        608: 'PHL', 616: 'POL', 620: 'PRT', 634: 'QAT', 642: 'ROU',
        646: 'RWA', 659: 'KNA', 662: 'LCA', 882: 'WSM', 674: 'SMR',
        678: 'STP', 682: 'SAU', 686: 'SEN', 688: 'SRB', 690: 'SYC',
        694: 'SLE', 702: 'SGP', 703: 'SVK', 705: 'SVN', 90: 'SLB',
        706: 'SOM', 710: 'ZAF', 728: 'SSD', 724: 'ESP', 144: 'LKA',
        729: 'SDN', 740: 'SUR', 752: 'SWE', 756: 'CHE', 762: 'TJK',
        764: 'THA', 768: 'TGO', 776: 'TON', 780: 'TTO', 788: 'TUN',
        795: 'TKM', 798: 'TUV', 800: 'UGA', 804: 'UKR', 784: 'ARE',
        858: 'URY', 860: 'UZB', 548: 'VUT', 887: 'YEM', 894: 'ZMB',
        716: 'ZWE', 531: 'CUW', 534: 'SXM', 535: 'BES',
    }

    # Load SDG data to find all geographic areas
    sdg_path = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/2025_Q3.2_AllData_Before_20251212.csv")
    print(f"Loading SDG data from {sdg_path}")
    df = pd.read_csv(sdg_path, usecols=['GeoAreaCode', 'GeoAreaName'], low_memory=False)
    unique_areas = df[['GeoAreaCode', 'GeoAreaName']].drop_duplicates().sort_values('GeoAreaCode')
    print(f"Found {len(unique_areas)} unique geographic areas")

    # Regional patterns to exclude
    regional_patterns = [
        'region', 'ecosystem', 'area:', 'africa', 'asia', 'europe',
        'america', 'oceania', 'caribbean', 'caucasus', 'landlocked',
        'developing', 'least developed', 'income', 'small island',
        'sub-saharan', 'middle east', 'northern', 'southern', 'eastern',
        'western', 'central', 'oecd', 'opec', 'world', 'melanesia',
        'polynesia', 'micronesia', 'fao', 'marine', 'fishing'
    ]

    # Build mapping
    m49_to_iso3 = {}
    regional_codes = []
    unmatched = []

    for _, row in unique_areas.iterrows():
        code = int(row['GeoAreaCode'])
        name = row['GeoAreaName']
        name_lower = name.lower()

        # Skip special codes
        if code < 10:  # World=1, continents
            regional_codes.append({'code': code, 'name': name})
            continue

        # Skip regional aggregates
        if any(pattern in name_lower for pattern in regional_patterns):
            regional_codes.append({'code': code, 'name': name})
            continue

        # Check direct M49 mapping
        if code in direct_m49_mapping:
            m49_to_iso3[str(code)] = direct_m49_mapping[code]
            continue

        # Try name match against our ISO codes
        if name_lower in iso_names:
            m49_to_iso3[str(code)] = iso_names[name_lower]
            continue

        # Try partial name match
        matched = False
        for iso_name, iso_code in iso_names.items():
            if iso_name in name_lower or name_lower in iso_name:
                m49_to_iso3[str(code)] = iso_code
                matched = True
                break

        if not matched:
            unmatched.append({'code': code, 'name': name})

    print(f"\nResults:")
    print(f"  Matched countries: {len(m49_to_iso3)}")
    print(f"  Regional aggregates: {len(regional_codes)}")
    print(f"  Unmatched: {len(unmatched)}")

    if unmatched:
        print(f"\nUnmatched areas:")
        for item in unmatched:
            print(f"  {item['code']}: {item['name']}")

    # Save mapping
    output = {
        'm49_to_iso3': m49_to_iso3,
        'regional_codes': regional_codes,
        'unmatched': unmatched,
        'generated': '2025-12-29',
        'country_count': len(m49_to_iso3)
    }

    output_path = Path(__file__).parent / "m49_mapping.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved mapping to {output_path}")
    return m49_to_iso3


if __name__ == "__main__":
    build_m49_mapping()
