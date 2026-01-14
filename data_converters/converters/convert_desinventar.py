"""
Convert DesInventar disaster data to parquet format.

DesInventar is a disaster loss database maintained by UNDRR with structured
impact data for 80+ countries.

Input: XML files from DesInventar exports in Raw data/desinventar/DI_export_*/
Output:
  - desinventar/events.parquet - All disaster events with impact data
  - desinventar/GLOBAL.parquet - Annual aggregates by country

Usage:
    python convert_desinventar.py

Coverage:
- 80+ countries across Latin America, Asia, Africa, Europe, Pacific
- Event-level disaster records with structured impact fields
- Historical depth varies (some countries back to 1900s)
"""
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
import xml.etree.ElementTree as ET
from datetime import datetime
import sys

# Add build path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from build.catalog.finalize_source import finalize_source

# Configuration
DESINVENTAR_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/desinventar")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/global/desinventar")

# Event type mapping (Spanish/local to English standardized)
EVENT_TYPE_MAP = {
    # Geological
    'Sismo': 'earthquake',
    'EARTHQUAKE': 'earthquake',
    'Terremoto': 'earthquake',
    'Actividad Volcánica': 'volcano',
    'ERUPTION': 'volcano',
    'Erupción': 'volcano',
    'Deslizamiento': 'landslide',
    'LANDSLIDE': 'landslide',
    'Aluvión': 'debris_flow',
    'ALLUVION': 'debris_flow',
    'Alud': 'avalanche',
    'AVALANCHE': 'avalanche',

    # Hydrological
    'Inundación': 'flood',
    'FLOOD': 'flood',
    'Flood': 'flood',
    'Avenida torrencial': 'flash_flood',
    'Flash Flood': 'flash_flood',
    'Tsunami': 'tsunami',
    'TSUNAMI': 'tsunami',

    # Meteorological
    'Vendaval': 'storm',
    'STORM': 'storm',
    'Tormenta': 'storm',
    'Viento': 'wind',
    'WIND': 'wind',
    'Granizada': 'hail',
    'HAIL': 'hail',
    'Lluvia': 'heavy_rain',
    'RAIN': 'heavy_rain',
    'Tormenta eléctrica': 'thunderstorm',
    'ELECTRICSTORM': 'thunderstorm',
    'Ciclón': 'tropical_cyclone',
    'Huracán': 'tropical_cyclone',
    'HURRICANE': 'tropical_cyclone',
    'Tifón': 'tropical_cyclone',
    'TYPHOON': 'tropical_cyclone',

    # Climatological
    'Sequía': 'drought',
    'DROUGHT': 'drought',
    'Helada': 'frost',
    'FROST': 'frost',
    'Ola de calor': 'heat_wave',
    'HEATWAVE': 'heat_wave',
    'Ola de frío': 'cold_wave',
    'COLDWAVE': 'cold_wave',
    'Incendio forestal': 'wildfire',
    'WILDFIRE': 'wildfire',
    'Incendio': 'fire',
    'FIRE': 'fire',

    # Biological
    'Epidemia': 'epidemic',
    'EPIDEMIC': 'epidemic',
    'Epizootia': 'animal_disease',
    'EPIZOOTIA': 'animal_disease',
    'Plaga': 'pest',
    'PEST': 'pest',
    'Biológico': 'biological',
    'BIOLOGICAL': 'biological',

    # Other
    'Accidente': 'technological',
    'ACCIDENT': 'technological',
    'Explosión': 'explosion',
    'EXPLOSION': 'explosion',
    'Colapso': 'structural_collapse',
    'COLLAPSE': 'structural_collapse',
    'Contaminación': 'pollution',
    'POLLUTION': 'pollution',
}

# Country code mapping
COUNTRY_CODES = {
    'ago': 'AGO',  # Angola
    'alb': 'ALB',  # Albania
    'ar2': 'ARG',  # Argentina (alternative code)
    'arg': 'ARG',  # Argentina
    'atg': 'ATG',  # Antigua and Barbuda
    'bfa': 'BFA',  # Burkina Faso
    'blz': 'BLZ',  # Belize
    'bol': 'BOL',  # Bolivia
    'brb': 'BRB',  # Barbados
    'btn': 'BTN',  # Bhutan
    'chl': 'CHL',  # Chile
    'com': 'COM',  # Comoros
    'cri': 'CRI',  # Costa Rica
    'khm': 'KHM',  # Cambodia
    'col': 'COL',  # Colombia
    'ecu': 'ECU',  # Ecuador
    'slv': 'SLV',  # El Salvador
    'gtm': 'GTM',  # Guatemala
    'hnd': 'HND',  # Honduras
    'idn': 'IDN',  # Indonesia
    'ind': 'IND',  # India
    'jam': 'JAM',  # Jamaica
    'mex': 'MEX',  # Mexico
    'nic': 'NIC',  # Nicaragua
    'pan': 'PAN',  # Panama
    'per': 'PER',  # Peru
    'phl': 'PHL',  # Philippines
    'ven': 'VEN',  # Venezuela
}


def get_text(element, tag, default=''):
    """Safely extract text from XML element."""
    child = element.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return default


def parse_xml_file(xml_path, country_code):
    """Parse a single DesInventar XML file."""
    print(f"  Parsing {xml_path.name}...")

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception as e:
        print(f"    ERROR parsing XML: {e}")
        return []

    # Find the fichas (event records) section
    fichas = root.find('fichas')
    if fichas is None:
        print(f"    WARNING: No <fichas> section found")
        return []

    events = []

    for tr in fichas.findall('TR'):
        try:
            # Extract basic fields
            serial = get_text(tr, 'serial')

            # Date fields
            year = get_text(tr, 'fechano')
            month = get_text(tr, 'fechames')
            day = get_text(tr, 'fechadia')

            # Skip if no year
            if not year or year == '0':
                continue

            # Create timestamp
            try:
                year_int = int(year)
                month_int = int(month) if month and month != '0' else 1
                day_int = int(day) if day and day != '0' else 1

                # Validate date ranges
                month_int = max(1, min(12, month_int))
                day_int = max(1, min(31, day_int))

                timestamp = datetime(year_int, month_int, day_int).isoformat()
            except (ValueError, OverflowError):
                # Skip invalid dates
                continue

            # Location fields
            level0 = get_text(tr, 'name0')  # Province/State
            level1 = get_text(tr, 'name1')  # Municipality
            level2 = get_text(tr, 'name2')  # Locality
            lugar = get_text(tr, 'lugar')   # Specific location

            # Event type
            evento = get_text(tr, 'evento')
            disaster_type = EVENT_TYPE_MAP.get(evento, 'other')

            # Impact data (Spanish field names)
            muertos = get_text(tr, 'muertos', '0')
            heridos = get_text(tr, 'heridos', '0')
            desaparece = get_text(tr, 'desaparece', '0')
            afectados = get_text(tr, 'afectados', '0')
            vivdest = get_text(tr, 'vivdest', '0')
            vivafec = get_text(tr, 'vivafec', '0')
            damnificados = get_text(tr, 'damnificados', '0')
            evacuados = get_text(tr, 'evacuados', '0')
            valorloc = get_text(tr, 'valorloc', '0')
            valorus = get_text(tr, 'valorus', '0')

            # Convert to integers
            def safe_int(val):
                try:
                    return int(float(val))
                except (ValueError, TypeError):
                    return 0

            deaths = safe_int(muertos)
            injuries = safe_int(heridos)
            missing = safe_int(desaparece)
            affected = safe_int(afectados)
            houses_destroyed = safe_int(vivdest)
            houses_damaged = safe_int(vivafec)
            victims = safe_int(damnificados)
            evacuated = safe_int(evacuados)
            damage_local = safe_int(valorloc)
            damage_usd = safe_int(valorus)

            # GLIDE number
            glide = get_text(tr, 'glide')

            # Coordinates (if available)
            lat = get_text(tr, 'latitude', '0')
            lon = get_text(tr, 'longitude', '0')
            latitude = float(lat) if lat != '0' else None
            longitude = float(lon) if lon != '0' else None

            # Cause
            causa = get_text(tr, 'causa')
            descausa = get_text(tr, 'descausa')

            # Source
            fuentes = get_text(tr, 'fuentes')

            # Create event record
            event = {
                'event_id': f"{country_code}_{serial}",
                'timestamp': timestamp,
                'year': year_int,
                'country_code': country_code,
                'loc_id': country_code,  # Country-level for now
                'level0': level0,
                'level1': level1,
                'level2': level2,
                'location_name': lugar,
                'latitude': latitude,
                'longitude': longitude,
                'disaster_type': disaster_type,
                'event_type_local': evento,
                'glide': glide if glide else None,
                # Impact data
                'deaths': deaths if deaths > 0 else None,
                'injuries': injuries if injuries > 0 else None,
                'missing': missing if missing > 0 else None,
                'affected': affected if affected > 0 else None,
                'houses_destroyed': houses_destroyed if houses_destroyed > 0 else None,
                'houses_damaged': houses_damaged if houses_damaged > 0 else None,
                'victims': victims if victims > 0 else None,
                'evacuated': evacuated if evacuated > 0 else None,
                'damage_local_currency': damage_local if damage_local > 0 else None,
                'damage_usd': damage_usd if damage_usd > 0 else None,
                # Metadata
                'cause': causa,
                'cause_description': descausa,
                'sources': fuentes,
            }

            events.append(event)

        except Exception as e:
            # Skip malformed records
            continue

    print(f"    Extracted {len(events):,} events")
    return events


def load_all_countries():
    """Load DesInventar data from all available country folders."""
    print("Loading DesInventar data from all countries...")

    all_events = []
    countries_processed = []

    # Find all DI_export_* directories
    for country_dir in sorted(DESINVENTAR_DIR.glob('DI_export_*')):
        if not country_dir.is_dir():
            continue

        # Extract country code from directory name
        country_code_raw = country_dir.name.replace('DI_export_', '')
        country_code = COUNTRY_CODES.get(country_code_raw, country_code_raw.upper())

        # Find XML file
        xml_files = list(country_dir.glob('*.xml'))
        if not xml_files:
            print(f"  WARNING: No XML file found in {country_dir.name}")
            continue

        xml_path = xml_files[0]
        events = parse_xml_file(xml_path, country_code)

        if events:
            all_events.extend(events)
            countries_processed.append(country_code)

    print(f"\nTotal events loaded: {len(all_events):,}")
    print(f"Countries processed: {len(countries_processed)} - {', '.join(sorted(countries_processed))}")

    return pd.DataFrame(all_events)


def process_events(df):
    """Process and standardize event data."""
    print("\nProcessing events...")

    # Convert timestamp to datetime
    df = df[df['year'] >= 1700].copy()
    print(f"  Filtered to events after 1700: {len(df):,}")
    df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
    df = df[df['timestamp'].notna()].copy()

    # Sort by date
    df = df.sort_values('timestamp', ascending=False)

    # Print statistics
    print(f"  Total events: {len(df):,}")
    print(f"  Countries: {df['country_code'].nunique()}")
    print(f"  Years: {df['year'].min()}-{df['year'].max()}")
    print(f"  Disaster types: {df['disaster_type'].nunique()}")

    print(f"\n  Impact data coverage:")
    print(f"    Events with deaths: {df['deaths'].notna().sum():,} ({df['deaths'].notna().sum()/len(df)*100:.1f}%)")
    print(f"    Events with injuries: {df['injuries'].notna().sum():,} ({df['injuries'].notna().sum()/len(df)*100:.1f}%)")
    print(f"    Events with missing: {df['missing'].notna().sum():,} ({df['missing'].notna().sum()/len(df)*100:.1f}%)")
    print(f"    Events with affected: {df['affected'].notna().sum():,} ({df['affected'].notna().sum()/len(df)*100:.1f}%)")
    print(f"    Events with houses destroyed: {df['houses_destroyed'].notna().sum():,} ({df['houses_destroyed'].notna().sum()/len(df)*100:.1f}%)")
    print(f"    Events with damage (USD): {df['damage_usd'].notna().sum():,} ({df['damage_usd'].notna().sum()/len(df)*100:.1f}%)")

    print(f"\n  Total impact:")
    print(f"    Deaths: {df['deaths'].sum():,.0f}")
    print(f"    Injuries: {df['injuries'].sum():,.0f}")
    print(f"    Missing: {df['missing'].sum():,.0f}")
    print(f"    Affected: {df['affected'].sum():,.0f}")
    print(f"    Houses destroyed: {df['houses_destroyed'].sum():,.0f}")

    return df


def create_aggregates(events):
    """Create annual aggregates by country."""
    print("\nCreating aggregates...")

    # Aggregate by country and year
    agg = events.groupby(['country_code', 'year']).agg({
        'event_id': 'count',
        'deaths': 'sum',
        'injuries': 'sum',
        'missing': 'sum',
        'affected': 'sum',
        'evacuated': 'sum',
        'houses_destroyed': 'sum',
        'houses_damaged': 'sum',
        'damage_usd': 'sum',
    }).reset_index()

    agg.columns = ['loc_id', 'year', 'total_events', 'total_deaths', 'total_injuries',
                   'total_missing', 'total_affected', 'total_evacuated',
                   'total_houses_destroyed', 'total_houses_damaged', 'total_damage_usd']

    # Add disaster type counts
    type_counts = events.groupby(['country_code', 'year', 'disaster_type']).size().unstack(fill_value=0)
    type_counts.columns = [f'count_{col}' for col in type_counts.columns]
    type_counts = type_counts.reset_index()
    type_counts.rename(columns={'country_code': 'loc_id'}, inplace=True)

    agg = agg.merge(type_counts, on=['loc_id', 'year'], how='left')

    print(f"  Output: {len(agg):,} country-year records")

    return agg


def save_parquet(df, output_path, description):
    """Save dataframe to parquet."""
    print(f"\nSaving {description}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"  Saved: {output_path}")
    print(f"  Size: {size_mb:.2f} MB, {len(df):,} rows")


def main():
    """Main conversion workflow."""
    print("=" * 70)
    print("DesInventar Disaster Database Converter")
    print("=" * 70)
    print()

    # Load all country data
    df = load_all_countries()

    if df.empty:
        print("ERROR: No data loaded. Check DesInventar directory.")
        return

    # Process events
    events = process_events(df)

    # Create aggregates
    aggregates = create_aggregates(events)

    # Save outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    events_path = OUTPUT_DIR / "events.parquet"
    save_parquet(events, events_path, "event data")

    agg_path = OUTPUT_DIR / "GLOBAL.parquet"
    save_parquet(aggregates, agg_path, "country-year aggregates")

    # Print summary
    print("\n" + "=" * 70)
    print("Conversion Summary")
    print("=" * 70)
    print(f"Total events: {len(events):,}")
    print(f"Countries: {events['country_code'].nunique()}")
    print(f"Years: {events['year'].min()}-{events['year'].max()}")

    print("\nTop disaster types:")
    print(events['disaster_type'].value_counts().head(10).to_string())

    print("\nTop countries by event count:")
    print(events['country_code'].value_counts().head(10).to_string())

    print("\nTop countries by deaths:")
    deaths_by_country = events.groupby('country_code')['deaths'].sum().nlargest(10)
    print(deaths_by_country.to_string())

    print("\n" + "=" * 70)
    print("COMPLETE!")
    print("=" * 70)

    return events, aggregates


if __name__ == "__main__":
    main()
