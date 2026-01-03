"""
Scrape CIA World Factbook 2025 Archive for static/geographic country data.

This scraper pulls data from the JSON page-data endpoints which contain
all the detailed country information.

Static data includes:
- Geographic coordinates (lat/long)
- Area (total, land, water in sq km)
- Coastline (km)
- Land boundaries (km)
- Elevation (highest/lowest points)
- Capital city coordinates

Usage:
    python scrape_cia_static_data.py
"""

import requests
import re
import json
import time
from typing import Dict, List, Optional, Any
import pycountry

# Base URL for the 2025 archive page-data JSON
BASE_URL = "https://www.cia.gov/the-world-factbook/about/archives/2025/page-data"

# Build country name to ISO3 code mapping (same as scrape_cia_factbook_2025.py)
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

    # Remove "the" prefix
    if name_lower.startswith("the "):
        name_lower = name_lower[4:]
        if name_lower in COUNTRY_TO_ISO3:
            return COUNTRY_TO_ISO3[name_lower]

    # Try reversed comma names
    if ", " in name_lower:
        parts = name_lower.split(", ")
        reversed_name = " ".join(reversed(parts))
        if reversed_name in COUNTRY_TO_ISO3:
            return COUNTRY_TO_ISO3[reversed_name]

    return None

def name_to_slug(name: str) -> str:
    """Convert country name to URL slug."""
    slug = name.lower().strip()
    # Handle special cases
    slug = slug.replace("'", "")
    slug = slug.replace("(", "").replace(")", "")
    slug = slug.replace(",", "")
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug

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

        # Navigate JSON structure: result.data.fields.nodes
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

def parse_coordinates(coord_str: str) -> Optional[Dict[str, float]]:
    """Parse coordinate string like '35 00 N, 105 00 E' into lat/long."""
    if not coord_str:
        return None

    # Pattern: DD MM N/S, DD MM E/W or DD MM SS N/S, DD MM SS E/W
    pattern = r'(\d+)\s+(\d+)\s*(\d*)\s*([NS]),?\s*(\d+)\s+(\d+)\s*(\d*)\s*([EW])'
    match = re.search(pattern, coord_str, re.IGNORECASE)

    if match:
        lat_deg = int(match.group(1))
        lat_min = int(match.group(2))
        lat_sec = int(match.group(3)) if match.group(3) else 0
        lat_dir = match.group(4).upper()

        lon_deg = int(match.group(5))
        lon_min = int(match.group(6))
        lon_sec = int(match.group(7)) if match.group(7) else 0
        lon_dir = match.group(8).upper()

        lat = lat_deg + lat_min/60 + lat_sec/3600
        if lat_dir == 'S':
            lat = -lat

        lon = lon_deg + lon_min/60 + lon_sec/3600
        if lon_dir == 'W':
            lon = -lon

        return {'latitude': round(lat, 4), 'longitude': round(lon, 4)}

    return None

def clean_html(text: str) -> str:
    """Remove HTML tags and clean up text."""
    import html
    if not text:
        return text
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Decode HTML entities (handles &iacute; &eacute; &amp; etc.)
    text = html.unescape(text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def parse_elevation(text: str) -> Dict[str, Any]:
    """Parse elevation text for highest/lowest points."""
    result = {}

    # Clean HTML first
    text_clean = clean_html(text)

    # Split text by main delimiters to isolate each section
    # Format: "highest point: X ... lowest point: Y ... mean elevation: Z"

    # Extract highest point section (between "highest point:" and "lowest point:")
    highest_section = re.search(r'highest point\s*:\s*(.+?)(?=\s*lowest point\s*:|$)', text_clean, re.IGNORECASE)
    if highest_section:
        section = highest_section.group(1)
        # Find the FIRST number followed by optional 'm'
        num_match = re.search(r'^(.+?)\s+(-?\d{1,5}(?:,\d{3})*)\s*(?:m\b)?', section)
        if num_match:
            name = num_match.group(1).strip()
            # Remove trailing parenthetical
            name = re.sub(r'\s*\([^)]*$', '', name)
            result['highest_point_name'] = name
            result['highest_point_m'] = int(num_match.group(2).replace(',', ''))

    # Extract lowest point section (between "lowest point:" and "mean elevation:")
    lowest_section = re.search(r'lowest point\s*:\s*(.+?)(?=\s*mean elevation\s*:|$)', text_clean, re.IGNORECASE)
    if lowest_section:
        section = lowest_section.group(1)
        # Find the FIRST number (may be negative)
        num_match = re.search(r'^(.+?)\s+(-?\d{1,5}(?:,\d{3})*)\s*(?:m\b)?', section)
        if num_match:
            name = num_match.group(1).strip()
            name = re.sub(r'\s*\([^)]*$', '', name)
            result['lowest_point_name'] = name
            result['lowest_point_m'] = int(num_match.group(2).replace(',', ''))

    # Mean elevation
    mean_match = re.search(r'mean elevation\s*:?\s*(\d{1,5}(?:,\d{3})*)\s*(?:m|meters)?', text_clean, re.IGNORECASE)
    if mean_match:
        result['mean_elevation_m'] = int(mean_match.group(1).replace(',', ''))

    return result

def parse_number(text: str) -> Optional[float]:
    """Extract number from text like '19,924 km'."""
    if not text:
        return None
    match = re.search(r'(-?\d{1,3}(?:,\d{3})*(?:\.\d+)?)', text)
    if match:
        return float(match.group(1).replace(',', ''))
    return None

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

def extract_static_data(json_data: Dict, country_info: Dict) -> Dict:
    """Extract static geographic data from country JSON."""
    result = {
        'loc_id': country_info['iso3'],
        'country_name': country_info['name'],
    }

    try:
        # Navigate to fields: result.data.fields.nodes
        data = json_data.get('result', {}).get('data', {})
        fields_data = data.get('fields', {})
        fields = fields_data.get('nodes', [])

        # Geographic coordinates
        coords_text = get_field_value(fields, 'Geographic coordinates')
        if coords_text:
            coords = parse_coordinates(coords_text)
            if coords:
                result['latitude'] = coords['latitude']
                result['longitude'] = coords['longitude']

        # Area (has HTML like <strong>total :</strong> 9,833,517 sq km)
        area_text = get_field_value(fields, 'Area')
        if area_text:
            # Clean HTML first for easier matching
            area_clean = clean_html(area_text)

            # Total area
            total_match = re.search(r'total\s*:?\s*([\d,]+)\s*sq\s*km', area_clean, re.IGNORECASE)
            if total_match:
                result['area_total_sq_km'] = int(total_match.group(1).replace(',', ''))

            # Land area
            land_match = re.search(r'land\s*:?\s*([\d,]+)\s*sq\s*km', area_clean, re.IGNORECASE)
            if land_match:
                result['area_land_sq_km'] = int(land_match.group(1).replace(',', ''))

            # Water area
            water_match = re.search(r'water\s*:?\s*([\d,]+)\s*sq\s*km', area_clean, re.IGNORECASE)
            if water_match:
                result['area_water_sq_km'] = int(water_match.group(1).replace(',', ''))

        # Coastline
        coastline_text = get_field_value(fields, 'Coastline')
        if coastline_text:
            coastline = parse_number(coastline_text)
            if coastline is not None:
                result['coastline_km'] = coastline

        # Land boundaries (has HTML)
        boundaries_text = get_field_value(fields, 'Land boundaries')
        if boundaries_text:
            boundaries_clean = clean_html(boundaries_text)
            total_match = re.search(r'total\s*:?\s*([\d,]+)\s*km', boundaries_clean, re.IGNORECASE)
            if total_match:
                result['land_boundaries_km'] = int(total_match.group(1).replace(',', ''))

            # Count border countries
            border_match = re.search(r'border countries\s*\((\d+)\)', boundaries_clean, re.IGNORECASE)
            if border_match:
                result['border_countries_count'] = int(border_match.group(1))

        # Elevation
        elevation_text = get_field_value(fields, 'Elevation')
        if elevation_text:
            elev_data = parse_elevation(elevation_text)
            result.update(elev_data)

        # Capital (for coordinates) - HTML format: <strong>name:</strong> Washington
        capital_text = get_field_value(fields, 'Capital')
        if capital_text:
            # Clean HTML first
            capital_clean = clean_html(capital_text)

            # Extract capital name
            name_match = re.search(r'name\s*:?\s*([^;]+?)(?:\s+geographic|\s*$)', capital_clean, re.IGNORECASE)
            if name_match:
                cap_name = name_match.group(1).strip()
                if cap_name:
                    result['capital_name'] = cap_name

            # Extract capital coordinates
            coord_match = re.search(r'geographic coordinates\s*:?\s*([^;]+?)(?:\s+time|\s*$)', capital_clean, re.IGNORECASE)
            if coord_match:
                cap_coords = parse_coordinates(coord_match.group(1))
                if cap_coords:
                    result['capital_latitude'] = cap_coords['latitude']
                    result['capital_longitude'] = cap_coords['longitude']

        # Climate (text, might be useful)
        climate_text = get_field_value(fields, 'Climate')
        if climate_text:
            climate_clean = clean_html(climate_text)
            if len(climate_clean) < 300:
                result['climate'] = climate_clean

        # Terrain (text)
        terrain_text = get_field_value(fields, 'Terrain')
        if terrain_text:
            terrain_clean = clean_html(terrain_text)
            if len(terrain_clean) < 300:
                result['terrain'] = terrain_clean

        # Natural resources (could be useful)
        resources_text = get_field_value(fields, 'Natural resources')
        if resources_text:
            resources_clean = clean_html(resources_text)
            if len(resources_clean) < 400:
                result['natural_resources'] = resources_clean

    except Exception as e:
        print(f"  Error extracting data: {e}")

    return result

def scrape_all_countries() -> List[Dict]:
    """Scrape static data for all countries."""
    countries = get_country_list()
    if not countries:
        print("No countries found!")
        return []

    all_data = []
    skipped = []

    for i, country in enumerate(countries):
        name = country['name']
        slug = country['slug']
        iso3 = country['iso3']

        print(f"[{i+1}/{len(countries)}] {name} ({slug})...")

        if not iso3:
            print(f"  Skipping - no ISO3 code")
            skipped.append(name)
            continue

        json_data = fetch_country_data(slug)
        if json_data:
            static_data = extract_static_data(json_data, country)
            if static_data.get('latitude') or static_data.get('area_total_sq_km'):
                all_data.append(static_data)
                print(f"  OK - got {len(static_data)} fields")
            else:
                print(f"  No data extracted")
        else:
            print(f"  No JSON data")

        # Be nice to the server
        time.sleep(0.3)

    if skipped:
        print(f"\nSkipped {len(skipped)} countries (no ISO3): {skipped[:10]}...")

    return all_data

def main():
    import pandas as pd

    print("=" * 60)
    print("CIA World Factbook 2025 - Static Data Scraper")
    print("=" * 60)
    print()

    all_data = scrape_all_countries()

    if all_data:
        # Save to JSON (backup)
        json_path = 'cia_factbook_2025_static.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, indent=2, ensure_ascii=False)
        print(f"\nSaved {len(all_data)} countries to {json_path}")

        # Save to Parquet
        df = pd.DataFrame(all_data)
        parquet_path = 'c:/Users/Bryan/Desktop/county-map-data/data/all_countries_factbook_2025_static.parquet'
        df.to_parquet(parquet_path, index=False)
        print(f"Saved to {parquet_path}")

        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Countries: {len(all_data)}")
        print(f"Columns: {list(df.columns)}")

        # Field coverage
        fields = {}
        for row in all_data:
            for key in row:
                if key not in ['loc_id', 'country_name']:
                    fields[key] = fields.get(key, 0) + 1

        print("\nField coverage:")
        for field, count in sorted(fields.items(), key=lambda x: -x[1]):
            print(f"  {field}: {count} countries")
    else:
        print("No data scraped!")

if __name__ == '__main__':
    main()
