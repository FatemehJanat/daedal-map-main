"""
Convert FEMA National Risk Index data to parquet format.

Input: Raw JSON from ArcGIS REST API download
Output: USA.parquet with county-level natural hazard risk metrics

Usage:
    python convert_fema_nri.py

Dataset contains 18 hazard types with composite risk scores:
- Avalanche, Coastal Flooding, Cold Wave, Drought, Earthquake, Hail
- Heat Wave, Hurricane, Ice Storm, Landslide, Lightning, Inland Flooding
- Strong Wind, Tornado, Tsunami, Volcanic Activity, Wildfire, Winter Weather
"""
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
import json
import sys

# Add build path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from build.catalog.finalize_source import finalize_source

# Configuration
INPUT_FILE = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/fema_nri_counties_raw.json")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA/fema_nri")

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

# Hazard codes and names
HAZARDS = {
    'AVLN': 'avalanche',
    'CFLD': 'coastal_flooding',
    'CWAV': 'cold_wave',
    'DRGT': 'drought',
    'ERQK': 'earthquake',
    'HAIL': 'hail',
    'HWAV': 'heat_wave',
    'HRCN': 'hurricane',
    'ISTM': 'ice_storm',
    'LNDS': 'landslide',
    'LTNG': 'lightning',
    'IFLD': 'inland_flooding',
    'SWND': 'strong_wind',
    'TRND': 'tornado',
    'TSUN': 'tsunami',
    'VLCN': 'volcanic',
    'WFIR': 'wildfire',
    'WNTW': 'winter_weather'
}


def load_raw_data():
    """Load raw JSON data from download."""
    print("Loading raw NRI data...")
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print(f"  Download date: {data.get('download_date', 'unknown')}")
    print(f"  Total records: {data.get('total_records', 0)}")

    # Extract features
    features = data.get('features', [])
    if not features:
        raise ValueError("No features found in raw data")

    # Convert to dataframe
    records = [f['attributes'] for f in features]
    df = pd.DataFrame(records)
    print(f"  Loaded {len(df)} counties")

    return df


def process_data(df):
    """Process raw data into output format."""
    print("\nProcessing data...")

    # Create loc_id from STCOFIPS
    df['state_fips'] = df['STATEFIPS'].astype(str).str.zfill(2)
    df['state_abbr'] = df['state_fips'].map(STATE_FIPS)
    df['loc_id'] = 'USA-' + df['state_abbr'] + '-' + df['STCOFIPS'].astype(str)

    # Filter to valid counties
    df = df[df['state_abbr'].notna()].copy()
    print(f"  {len(df)} counties with valid FIPS codes")

    # Build output dataframe
    result = pd.DataFrame()

    # Identifiers and geography
    result['loc_id'] = df['loc_id']
    result['county_name'] = df['COUNTY']
    result['state_name'] = df['STATE']
    result['state_abbr'] = df['STATEABBRV']
    result['fips'] = df['STCOFIPS']

    # Demographics
    result['population'] = pd.to_numeric(df['POPULATION'], errors='coerce').astype('Int64')
    result['building_value'] = pd.to_numeric(df['BUILDVALUE'], errors='coerce')
    result['agriculture_value'] = pd.to_numeric(df['AGRIVALUE'], errors='coerce')
    result['area_sq_mi'] = pd.to_numeric(df['AREA'], errors='coerce')

    # Composite Risk Scores
    result['risk_score'] = pd.to_numeric(df['RISK_SCORE'], errors='coerce')
    result['risk_rating'] = df['RISK_RATNG']
    result['risk_state_percentile'] = pd.to_numeric(df['RISK_SPCTL'], errors='coerce')

    # Expected Annual Loss (Composite)
    result['eal_score'] = pd.to_numeric(df['EAL_SCORE'], errors='coerce')
    result['eal_rating'] = df['EAL_RATNG']
    result['eal_total'] = pd.to_numeric(df['EAL_VALT'], errors='coerce')

    # Social Vulnerability
    result['sovi_score'] = pd.to_numeric(df['SOVI_SCORE'], errors='coerce')
    result['sovi_rating'] = df['SOVI_RATNG']

    # Community Resilience
    result['resilience_score'] = pd.to_numeric(df['RESL_SCORE'], errors='coerce')
    result['resilience_rating'] = df['RESL_RATNG']

    # Add hazard-specific scores (risk score and expected annual loss for each)
    for code, name in HAZARDS.items():
        # Risk score
        risk_col = f'{code}_RISKS'
        if risk_col in df.columns:
            result[f'{name}_risk_score'] = pd.to_numeric(df[risk_col], errors='coerce')

        # Risk rating
        rating_col = f'{code}_RISKR'
        if rating_col in df.columns:
            result[f'{name}_risk_rating'] = df[rating_col]

        # Expected annual loss total
        eal_col = f'{code}_EALT'
        if eal_col in df.columns:
            result[f'{name}_eal'] = pd.to_numeric(df[eal_col], errors='coerce')

    # NRI Version
    if 'NRI_VER' in df.columns:
        result['nri_version'] = df['NRI_VER']

    return result


def save_parquet(df):
    """Save DataFrame to parquet."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "USA.parquet"

    print(f"\nSaving to {output_path}...")

    # Write parquet with compression
    df.to_parquet(output_path, engine='pyarrow', compression='snappy', index=False)

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"  Saved: {size_mb:.2f} MB ({len(df)} records, {len(df.columns)} columns)")

    return output_path


def print_statistics(df):
    """Print summary statistics."""
    print("\n" + "="*80)
    print("STATISTICS")
    print("="*80)

    print(f"\nTotal counties: {len(df):,}")
    print(f"Total population: {df['population'].sum():,}")
    print(f"Total building value: ${df['building_value'].sum()/1e12:.2f} trillion")

    print("\nRisk Rating Distribution:")
    for rating in ['Very High', 'Relatively High', 'Relatively Moderate', 'Relatively Low', 'Very Low']:
        count = (df['risk_rating'] == rating).sum()
        print(f"  {rating}: {count} counties")

    print("\nHighest Risk Counties (by risk score):")
    top_risk = df.nlargest(10, 'risk_score')[['loc_id', 'county_name', 'state_abbr', 'risk_score', 'risk_rating']]
    for _, row in top_risk.iterrows():
        print(f"  {row['county_name']}, {row['state_abbr']}: {row['risk_score']:.1f} ({row['risk_rating']})")

    print("\nLowest Risk Counties (by risk score):")
    low_risk = df.nsmallest(10, 'risk_score')[['loc_id', 'county_name', 'state_abbr', 'risk_score', 'risk_rating']]
    for _, row in low_risk.iterrows():
        print(f"  {row['county_name']}, {row['state_abbr']}: {row['risk_score']:.1f} ({row['risk_rating']})")

    print("\nExpected Annual Loss (Top 10 Counties):")
    top_eal = df.nlargest(10, 'eal_total')[['county_name', 'state_abbr', 'eal_total']]
    for _, row in top_eal.iterrows():
        print(f"  {row['county_name']}, {row['state_abbr']}: ${row['eal_total']/1e6:.1f}M")

    # Hazard breakdown
    print("\nHazard with Highest Risk by Region:")
    for state in ['CA', 'FL', 'TX', 'NY', 'OK']:
        state_df = df[df['state_abbr'] == state]
        if len(state_df) > 0:
            # Find hazard with highest avg risk score
            hazard_cols = [col for col in df.columns if col.endswith('_risk_score') and col != 'risk_score']
            if hazard_cols:
                max_hazard = None
                max_score = 0
                for col in hazard_cols:
                    avg = state_df[col].mean()
                    if pd.notna(avg) and avg > max_score:
                        max_score = avg
                        max_hazard = col.replace('_risk_score', '')
                if max_hazard:
                    print(f"  {state}: {max_hazard.replace('_', ' ').title()} (avg score: {max_score:.1f})")


def main():
    """Main conversion logic."""
    print("="*80)
    print("FEMA National Risk Index - JSON to Parquet Converter")
    print("="*80)

    # Check input file
    if not INPUT_FILE.exists():
        print(f"ERROR: Input file not found: {INPUT_FILE}")
        print("\nRun download_fema_nri.py first to download the data.")
        return 1

    # Load and process data
    df_raw = load_raw_data()
    df = process_data(df_raw)

    # Print statistics
    print_statistics(df)

    # Save parquet
    parquet_path = save_parquet(df)

    # Finalize source (generates metadata.json, updates index.json)
    finalize_source(str(parquet_path), "fema_nri")

    print("\n" + "="*80)
    print("COMPLETE!")
    print("="*80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
