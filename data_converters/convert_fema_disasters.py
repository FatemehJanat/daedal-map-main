"""
Convert FEMA Disaster Declarations to parquet format.

Processes 68K+ disaster declarations (1953-present) into:
- County-level annual aggregates for mapping
- Full declarations for detailed analysis
- Incident type summaries

Input: Raw JSON from download_fema_all.py
Output:
  - USA.parquet: County-year aggregates (for time-series mapping)
  - USA_declarations.parquet: Full declaration records
  - metadata.json: Field definitions

Usage:
    python convert_fema_disasters.py
"""
import pandas as pd
import json
from pathlib import Path
import sys
from datetime import datetime

# Add build path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from build.catalog.finalize_source import finalize_source

# Configuration
RAW_FILE = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/fema/disasters/disaster_declarations_raw.json")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA/fema_disasters")

# State FIPS to abbreviation mapping
STATE_FIPS = {
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
    '56': 'WY', '60': 'AS', '66': 'GU', '69': 'MP', '72': 'PR', '78': 'VI'
}

# Incident type categories for aggregation
INCIDENT_CATEGORIES = {
    'Tornado': 'tornado',
    'Severe Storm': 'severe_storm',
    'Severe Storm(s)': 'severe_storm',
    'Hurricane': 'hurricane',
    'Typhoon': 'hurricane',
    'Tropical Storm': 'hurricane',
    'Flood': 'flood',
    'Flooding': 'flood',
    'Coastal Storm': 'coastal',
    'Earthquake': 'earthquake',
    'Fire': 'wildfire',
    'Wildfire': 'wildfire',
    'Snow': 'winter',
    'Snowstorm': 'winter',
    'Severe Ice Storm': 'winter',
    'Freezing': 'winter',
    'Drought': 'drought',
    'Volcano': 'volcano',
    'Volcanic Eruption': 'volcano',
    'Tsunami': 'tsunami',
    'Biological': 'biological',
    'Mud/Landslide': 'landslide',
    'Terrorist': 'other',
    'Chemical': 'other',
    'Dam/Levee Break': 'other',
    'Human Cause': 'other',
    'Other': 'other',
    'Fishing Losses': 'other',
    'Toxic Substances': 'other'
}


def load_raw_data():
    """Load raw disaster declarations."""
    print(f"Loading {RAW_FILE}...")

    with open(RAW_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    records = data['records']
    df = pd.DataFrame(records)

    print(f"  {len(df):,} total records")
    print(f"  Date range: {df['declarationDate'].min()} to {df['declarationDate'].max()}")

    return df


def clean_and_enrich(df):
    """Clean data and add derived fields."""
    print("\nCleaning and enriching data...")

    # Parse dates
    date_cols = ['declarationDate', 'incidentBeginDate', 'incidentEndDate',
                 'disasterCloseoutDate', 'lastRefresh']
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')

    # Extract year from declaration date
    df['year'] = df['declarationDate'].dt.year

    # Clean FIPS codes
    df['fipsStateCode'] = df['fipsStateCode'].astype(str).str.zfill(2)
    df['fipsCountyCode'] = df['fipsCountyCode'].astype(str).str.zfill(3)

    # Create state abbreviation
    df['state_abbr'] = df['fipsStateCode'].map(STATE_FIPS)

    # Create full FIPS code
    df['stcofips'] = df['fipsStateCode'] + df['fipsCountyCode']

    # Create loc_id (only for county-specific declarations)
    # County code 000 means statewide, not a specific county
    df['is_county_specific'] = df['fipsCountyCode'] != '000'
    df['loc_id'] = None
    mask = df['is_county_specific'] & df['state_abbr'].notna()
    df.loc[mask, 'loc_id'] = 'USA-' + df.loc[mask, 'state_abbr'] + '-' + df.loc[mask, 'stcofips']

    # Categorize incident types
    df['incident_category'] = df['incidentType'].map(INCIDENT_CATEGORIES).fillna('other')

    # Calculate incident duration in days
    df['incident_duration_days'] = (df['incidentEndDate'] - df['incidentBeginDate']).dt.days

    print(f"  County-specific declarations: {df['is_county_specific'].sum():,}")
    print(f"  Statewide declarations: {(~df['is_county_specific']).sum():,}")
    print(f"  Unique counties: {df[df['is_county_specific']]['loc_id'].nunique():,}")

    return df


def build_county_aggregates(df):
    """Build county-year aggregates for mapping."""
    print("\nBuilding county-year aggregates...")

    # Filter to county-specific declarations only
    county_df = df[df['is_county_specific'] & df['loc_id'].notna()].copy()

    # Group by county and year
    agg_df = county_df.groupby(['loc_id', 'year', 'state_abbr']).agg(
        total_declarations=('disasterNumber', 'nunique'),
        total_records=('id', 'count'),
        disaster_types=('incidentType', lambda x: ','.join(sorted(set(x)))),
        # Count by major category
        tornado_count=('incident_category', lambda x: (x == 'tornado').sum()),
        hurricane_count=('incident_category', lambda x: (x == 'hurricane').sum()),
        flood_count=('incident_category', lambda x: (x == 'flood').sum()),
        severe_storm_count=('incident_category', lambda x: (x == 'severe_storm').sum()),
        wildfire_count=('incident_category', lambda x: (x == 'wildfire').sum()),
        winter_count=('incident_category', lambda x: (x == 'winter').sum()),
        earthquake_count=('incident_category', lambda x: (x == 'earthquake').sum()),
        drought_count=('incident_category', lambda x: (x == 'drought').sum()),
        other_count=('incident_category', lambda x: (x == 'other').sum()),
        # Program declarations
        ia_program=('iaProgramDeclared', 'sum'),
        pa_program=('paProgramDeclared', 'sum'),
        hm_program=('hmProgramDeclared', 'sum'),
    ).reset_index()

    # Add decade for analysis
    agg_df['decade'] = (agg_df['year'] // 10) * 10

    print(f"  {len(agg_df):,} county-year records")
    print(f"  Unique counties: {agg_df['loc_id'].nunique():,}")
    print(f"  Year range: {agg_df['year'].min()} - {agg_df['year'].max()}")

    return agg_df


def build_full_declarations(df):
    """Build full declarations dataset with cleaned fields."""
    print("\nBuilding full declarations dataset...")

    # Select and order columns
    keep_cols = [
        'loc_id', 'year', 'state_abbr', 'stcofips',
        'disasterNumber', 'femaDeclarationString', 'declarationTitle',
        'declarationType', 'incidentType', 'incident_category',
        'declarationDate', 'incidentBeginDate', 'incidentEndDate',
        'incident_duration_days',
        'designatedArea', 'is_county_specific',
        'iaProgramDeclared', 'paProgramDeclared', 'hmProgramDeclared', 'ihProgramDeclared',
        'fyDeclared', 'region', 'tribalRequest',
        'disasterCloseoutDate', 'lastRefresh'
    ]

    # Only keep columns that exist
    keep_cols = [c for c in keep_cols if c in df.columns]
    result = df[keep_cols].copy()

    print(f"  {len(result):,} records, {len(result.columns)} columns")

    return result


def print_statistics(agg_df, full_df):
    """Print summary statistics."""
    print("\n" + "="*70)
    print("STATISTICS")
    print("="*70)

    print("\nDeclarations by Decade:")
    decade_counts = full_df.groupby((full_df['year'] // 10) * 10)['disasterNumber'].nunique()
    for decade, count in sorted(decade_counts.items()):
        print(f"  {decade}s: {count:,} unique disasters")

    print("\nTop 10 Incident Types:")
    type_counts = full_df['incidentType'].value_counts().head(10)
    for itype, count in type_counts.items():
        print(f"  {itype}: {count:,}")

    print("\nMost Disaster-Prone Counties (All Time):")
    county_totals = agg_df.groupby('loc_id')['total_declarations'].sum().nlargest(10)
    for loc_id, count in county_totals.items():
        print(f"  {loc_id}: {count:,} declarations")

    print("\nDeclarations by Category (All Time):")
    cat_counts = full_df['incident_category'].value_counts()
    for cat, count in cat_counts.items():
        print(f"  {cat}: {count:,}")


def save_parquets(agg_df, full_df):
    """Save parquet files."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # County-year aggregates (main file for mapping)
    agg_path = OUTPUT_DIR / "USA.parquet"
    print(f"\nSaving county-year aggregates to {agg_path}...")
    agg_df.to_parquet(agg_path, engine='pyarrow', compression='snappy', index=False)
    agg_size = agg_path.stat().st_size / 1024 / 1024
    print(f"  {agg_size:.2f} MB ({len(agg_df):,} records, {len(agg_df.columns)} columns)")

    # Full declarations
    full_path = OUTPUT_DIR / "USA_declarations.parquet"
    print(f"\nSaving full declarations to {full_path}...")
    full_df.to_parquet(full_path, engine='pyarrow', compression='snappy', index=False)
    full_size = full_path.stat().st_size / 1024 / 1024
    print(f"  {full_size:.2f} MB ({len(full_df):,} records, {len(full_df.columns)} columns)")

    return agg_path, full_path


def main():
    """Main conversion logic."""
    print("="*70)
    print("FEMA Disaster Declarations Converter")
    print("="*70)
    print(f"Started: {datetime.now().isoformat()}")

    # Check input exists
    if not RAW_FILE.exists():
        print(f"ERROR: Missing {RAW_FILE}")
        print("Run download_fema_all.py --disasters-only first")
        return 1

    # Load and process
    df = load_raw_data()
    df = clean_and_enrich(df)

    # Build outputs
    agg_df = build_county_aggregates(df)
    full_df = build_full_declarations(df)

    # Statistics
    print_statistics(agg_df, full_df)

    # Save
    agg_path, full_path = save_parquets(agg_df, full_df)

    # Finalize
    print("\nFinalizing source...")
    finalize_source(str(agg_path), "fema_disasters")

    print("\n" + "="*70)
    print("COMPLETE!")
    print("="*70)
    print(f"\nFiles created:")
    print(f"  {agg_path} - County-year aggregates (for time-series mapping)")
    print(f"  {full_path} - Full declarations (for detailed analysis)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
