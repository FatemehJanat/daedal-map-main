"""
Convert FEMA NRI historical data to time-series parquet format.

Merges all 4 NRI versions (2021-2025) into a single time-series dataset.
Handles:
- Different field counts across versions
- County count changes (3,142 -> 3,232)
- Creates loc_id for joining with geometry

Input: Raw JSON files from download_fema_all.py
Output:
  - USA.parquet: Time-series with all versions (for trend analysis)
  - USA_latest.parquet: Latest version only with ALL fields
  - metadata.json: Field definitions

Usage:
    python convert_fema_nri_timeseries.py
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
RAW_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/fema/nri_counties")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA/fema_nri")

# Version metadata with release years
VERSIONS = {
    "v1_17": {"file": "nri_v1_17_raw.json", "year": 2021, "release": "2021"},
    "v1_18_1": {"file": "nri_v1_18_1_raw.json", "year": 2021, "release": "November 2021"},
    "v1_19_0": {"file": "nri_v1_19_0_raw.json", "year": 2023, "release": "March 2023"},
    "v1_20_0": {"file": "nri_v1_20_0_raw.json", "year": 2025, "release": "December 2025"},
}

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

# Hazard codes
HAZARDS = {
    'AVLN': 'avalanche', 'CFLD': 'coastal_flooding', 'CWAV': 'cold_wave',
    'DRGT': 'drought', 'ERQK': 'earthquake', 'HAIL': 'hail',
    'HWAV': 'heat_wave', 'HRCN': 'hurricane', 'ISTM': 'ice_storm',
    'LNDS': 'landslide', 'LTNG': 'lightning', 'IFLD': 'inland_flooding',
    'SWND': 'strong_wind', 'TRND': 'tornado', 'TSUN': 'tsunami',
    'VLCN': 'volcanic', 'WFIR': 'wildfire', 'WNTW': 'winter_weather'
}

# Core fields to always include in time-series (exist across all versions)
CORE_FIELDS = [
    # Identifiers
    'STCOFIPS', 'STATE', 'STATEABBRV', 'STATEFIPS', 'COUNTY', 'COUNTYFIPS',
    # Demographics
    'POPULATION', 'BUILDVALUE', 'AGRIVALUE', 'AREA',
    # Composite scores
    'RISK_VALUE', 'RISK_SCORE', 'RISK_RATNG', 'RISK_SPCTL',
    'EAL_SCORE', 'EAL_RATNG', 'EAL_SPCTL', 'EAL_VALT',
    'SOVI_SCORE', 'SOVI_RATNG', 'SOVI_SPCTL',
    'RESL_SCORE', 'RESL_RATNG', 'RESL_SPCTL',
    # Per-hazard risk scores and EAL
]

# Add hazard-specific fields
for code in HAZARDS.keys():
    CORE_FIELDS.extend([
        f'{code}_RISKS', f'{code}_RISKR', f'{code}_EALT', f'{code}_EVNTS', f'{code}_AFREQ'
    ])


def load_version(version_key, version_info):
    """Load a single NRI version from raw JSON."""
    file_path = RAW_DIR / version_info["file"]
    print(f"  Loading {version_key} from {file_path.name}...")

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    features = data.get('features', [])
    records = [f['attributes'] for f in features]
    df = pd.DataFrame(records)

    print(f"    {len(df)} records, {len(df.columns)} fields")
    return df


def create_loc_id(df):
    """Create loc_id column from FIPS codes."""
    df['state_fips'] = df['STATEFIPS'].astype(str).str.zfill(2)
    df['state_abbr'] = df['state_fips'].map(STATE_FIPS)
    df['loc_id'] = 'USA-' + df['state_abbr'] + '-' + df['STCOFIPS'].astype(str)
    return df[df['state_abbr'].notna()].copy()


def convert_to_numeric(df, exclude_cols):
    """Convert numeric columns, keeping text columns as-is."""
    rating_cols = [c for c in df.columns if c.endswith('_RATNG') or c.endswith('_RISKR')]
    exclude_cols = exclude_cols + rating_cols

    for col in df.columns:
        if col not in exclude_cols and df[col].dtype == 'object':
            df[col] = pd.to_numeric(df[col], errors='coerce')

    return df


def build_timeseries():
    """Build time-series dataset from all versions."""
    print("\n" + "="*70)
    print("Building NRI Time-Series Dataset")
    print("="*70)

    all_dfs = []

    for version_key, version_info in VERSIONS.items():
        print(f"\n{version_key}:")
        df = load_version(version_key, version_info)
        df = create_loc_id(df)

        # Add version info
        df['nri_version'] = version_key.replace('_', '.')
        df['year'] = version_info['year']

        # Select core fields that exist in this version
        available_fields = ['loc_id', 'year', 'nri_version']
        for field in CORE_FIELDS:
            if field in df.columns:
                available_fields.append(field)

        df_subset = df[available_fields].copy()

        # Convert numeric
        df_subset = convert_to_numeric(df_subset, ['loc_id', 'nri_version'])

        all_dfs.append(df_subset)
        print(f"    Kept {len(available_fields)} fields")

    # Combine all versions
    print("\nCombining all versions...")
    combined = pd.concat(all_dfs, ignore_index=True)
    print(f"  Total: {len(combined):,} records")
    print(f"  Unique counties: {combined['loc_id'].nunique():,}")
    print(f"  Years: {sorted(combined['year'].unique())}")

    return combined


def build_latest_full():
    """Build latest version with ALL fields."""
    print("\n" + "="*70)
    print("Building Latest Full Dataset (ALL 467 fields)")
    print("="*70)

    # Load latest version
    version_info = VERSIONS['v1_20_0']
    df = load_version('v1_20_0', version_info)
    df = create_loc_id(df)

    # Add year column
    df['year'] = 2025

    # Rename columns to be more readable
    # Keep original field names for now - can add aliases in metadata

    # Convert numeric
    exclude = ['loc_id', 'STATE', 'STATEABBRV', 'COUNTY', 'COUNTYTYPE', 'NRI_ID', 'NRI_VER']
    df = convert_to_numeric(df, exclude)

    # Reorder columns
    first_cols = ['loc_id', 'year', 'STATE', 'STATEABBRV', 'COUNTY', 'STCOFIPS']
    other_cols = [c for c in df.columns if c not in first_cols]
    df = df[first_cols + other_cols]

    print(f"  {len(df):,} records, {len(df.columns)} fields")

    return df


def print_statistics(df_ts, df_full):
    """Print summary statistics."""
    print("\n" + "="*70)
    print("STATISTICS")
    print("="*70)

    print("\nTime-Series Dataset:")
    print(f"  Total records: {len(df_ts):,}")
    print(f"  Unique counties: {df_ts['loc_id'].nunique():,}")
    print(f"  Versions: {df_ts['nri_version'].unique().tolist()}")

    # Risk score trends
    print("\n  Average Risk Score by Version:")
    for version in sorted(df_ts['nri_version'].unique()):
        mask = df_ts['nri_version'] == version
        avg = df_ts.loc[mask, 'RISK_SCORE'].mean()
        count = mask.sum()
        print(f"    {version}: {avg:.2f} ({count:,} counties)")

    # Counties with biggest risk changes
    print("\n  Counties with Largest Risk Score Changes (v1.17 to v1.20):")
    df_v117 = df_ts[df_ts['nri_version'] == 'v1.17'][['loc_id', 'RISK_SCORE', 'COUNTY', 'STATEABBRV']].copy()
    df_v120 = df_ts[df_ts['nri_version'] == 'v1.20'][['loc_id', 'RISK_SCORE']].copy()

    merged = df_v117.merge(df_v120, on='loc_id', suffixes=('_2021', '_2025'))
    merged['change'] = merged['RISK_SCORE_2025'] - merged['RISK_SCORE_2021']

    print("\n    Largest Increases:")
    top_increases = merged.nlargest(5, 'change')
    for _, row in top_increases.iterrows():
        print(f"      {row['COUNTY']}, {row['STATEABBRV']}: {row['RISK_SCORE_2021']:.1f} -> {row['RISK_SCORE_2025']:.1f} (+{row['change']:.1f})")

    print("\n    Largest Decreases:")
    top_decreases = merged.nsmallest(5, 'change')
    for _, row in top_decreases.iterrows():
        print(f"      {row['COUNTY']}, {row['STATEABBRV']}: {row['RISK_SCORE_2021']:.1f} -> {row['RISK_SCORE_2025']:.1f} ({row['change']:.1f})")

    print("\n\nFull Latest Dataset:")
    print(f"  Records: {len(df_full):,}")
    print(f"  Fields: {len(df_full.columns)}")

    # Top risk counties
    print("\n  Top 10 Highest Risk Counties (2025):")
    top_risk = df_full.nlargest(10, 'RISK_SCORE')[['loc_id', 'COUNTY', 'STATEABBRV', 'RISK_SCORE', 'RISK_RATNG']]
    for _, row in top_risk.iterrows():
        print(f"    {row['COUNTY']}, {row['STATEABBRV']}: {row['RISK_SCORE']:.1f} ({row['RISK_RATNG']})")


def save_parquets(df_ts, df_full):
    """Save both parquet files."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Time-series version
    ts_path = OUTPUT_DIR / "USA.parquet"
    print(f"\nSaving time-series to {ts_path}...")
    df_ts.to_parquet(ts_path, engine='pyarrow', compression='snappy', index=False)
    ts_size = ts_path.stat().st_size / 1024 / 1024
    print(f"  {ts_size:.2f} MB ({len(df_ts):,} records, {len(df_ts.columns)} columns)")

    # Full latest version
    full_path = OUTPUT_DIR / "USA_full.parquet"
    print(f"\nSaving full latest to {full_path}...")
    df_full.to_parquet(full_path, engine='pyarrow', compression='snappy', index=False)
    full_size = full_path.stat().st_size / 1024 / 1024
    print(f"  {full_size:.2f} MB ({len(df_full):,} records, {len(df_full.columns)} columns)")

    return ts_path, full_path


def main():
    """Main conversion logic."""
    print("="*70)
    print("FEMA NRI Time-Series Converter")
    print("="*70)
    print(f"Started: {datetime.now().isoformat()}")

    # Check input files exist
    for version_key, version_info in VERSIONS.items():
        file_path = RAW_DIR / version_info["file"]
        if not file_path.exists():
            print(f"ERROR: Missing {file_path}")
            print("Run download_fema_all.py --nri-only first")
            return 1

    # Build datasets
    df_ts = build_timeseries()
    df_full = build_latest_full()

    # Statistics
    print_statistics(df_ts, df_full)

    # Save
    ts_path, full_path = save_parquets(df_ts, df_full)

    # Finalize (generates metadata.json, updates index.json)
    print("\nFinalizing source...")
    finalize_source(str(ts_path), "fema_nri")

    print("\n" + "="*70)
    print("COMPLETE!")
    print("="*70)
    print(f"\nFiles created:")
    print(f"  {ts_path} - Time-series (4 versions, for trend analysis)")
    print(f"  {full_path} - Full latest (ALL 467 fields)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
