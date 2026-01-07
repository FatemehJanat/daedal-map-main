"""
Convert Wildfire Risk to Communities data to parquet format.

Input: Excel file from wildfirerisk.org
Output: USA.parquet with county-level wildfire risk metrics

Usage:
    python convert_wildfire_risk.py

Metrics:
- Building exposure zones (Minimal, Indirect, Direct exposure)
- Burn Probability (BP) percentile rankings
- Risk to Potential Structures (RPS) percentile rankings
"""
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path

# Configuration
INPUT_FILE = Path("C:/Users/bryan/Desktop/county_map_data/Raw data/wildfire_risk/wrc_download_202505.xlsx")
OUTPUT_DIR = Path("C:/Users/bryan/Desktop/county_map_data/data/wildfire_risk")

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
    '56': 'WY', '72': 'PR'
}


def load_county_data():
    """Load and process county wildfire risk data."""
    print("Loading wildfire risk data...")
    df = pd.read_excel(INPUT_FILE, sheet_name='Counties')
    print(f"  Loaded {len(df)} counties")

    # Convert GEOID to loc_id format
    df['GEOID_str'] = df['GEOID'].astype(str).str.zfill(5)
    df['state_fips'] = df['GEOID_str'].str[:2]
    df['state_abbr'] = df['state_fips'].map(STATE_FIPS)

    # Create loc_id
    df['loc_id'] = 'USA-' + df['state_abbr'] + '-' + df['GEOID'].astype(str)

    # Filter to valid counties (those with state mapping)
    df = df[df['state_abbr'].notna()].copy()
    print(f"  Filtered to {len(df)} counties with valid FIPS codes")

    # Select and rename columns
    result = pd.DataFrame({
        'loc_id': df['loc_id'],
        'year': 2025,  # Dataset version year
        'population': df['POP'].astype('Int64'),
        'total_buildings': df['TOTAL_BUILDINGS'].astype('Int64'),
        'pct_buildings_minimal_exposure': (df['BUILDINGS_FRACTION_ME'] * 100).round(1),
        'pct_buildings_indirect_exposure': (df['BUILDINGS_FRACTION_IE'] * 100).round(1),
        'pct_buildings_direct_exposure': (df['BUILDINGS_FRACTION_DE'] * 100).round(1),
        'burn_probability_state_percentile': (df['BP_STATE_RANK'] * 100).round(1),
        'burn_probability_national_percentile': (df['BP_NATIONAL_RANK'] * 100).round(1),
        'risk_state_percentile': (df['RISK_STATE_RANK'] * 100).round(1),
        'risk_national_percentile': (df['RISK_NATIONAL_RANK'] * 100).round(1)
    })

    return result


def save_parquet(df):
    """Save DataFrame to parquet."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "USA.parquet"

    print(f"\nSaving to {output_path}...")

    # Define schema
    schema = pa.schema([
        ('loc_id', pa.string()),
        ('year', pa.int32()),
        ('population', pa.int64()),
        ('total_buildings', pa.int64()),
        ('pct_buildings_minimal_exposure', pa.float32()),
        ('pct_buildings_indirect_exposure', pa.float32()),
        ('pct_buildings_direct_exposure', pa.float32()),
        ('burn_probability_state_percentile', pa.float32()),
        ('burn_probability_national_percentile', pa.float32()),
        ('risk_state_percentile', pa.float32()),
        ('risk_national_percentile', pa.float32())
    ])

    # Convert to Arrow Table
    table = pa.Table.from_pandas(df, schema=schema)

    # Write parquet with compression
    pq.write_table(table, output_path, compression='snappy')

    size_kb = output_path.stat().st_size / 1024
    print(f"  Saved: {size_kb:.1f} KB")

    return output_path


def print_statistics(df):
    """Print summary statistics."""
    print("\n" + "="*80)
    print("STATISTICS")
    print("="*80)

    print(f"\nTotal counties: {len(df):,}")
    print(f"Total population: {df['population'].sum():,}")
    print(f"Total buildings: {df['total_buildings'].sum():,}")

    print("\nBuilding Exposure Distribution:")
    print(f"  Mean % Minimal Exposure: {df['pct_buildings_minimal_exposure'].mean():.1f}%")
    print(f"  Mean % Indirect Exposure: {df['pct_buildings_indirect_exposure'].mean():.1f}%")
    print(f"  Mean % Direct Exposure: {df['pct_buildings_direct_exposure'].mean():.1f}%")

    print("\nBurn Probability (National Percentiles):")
    print(f"  Highest risk counties (>95th percentile): {(df['burn_probability_national_percentile'] > 95).sum()}")
    print(f"  High risk (75-95th): {((df['burn_probability_national_percentile'] > 75) & (df['burn_probability_national_percentile'] <= 95)).sum()}")
    print(f"  Moderate risk (50-75th): {((df['burn_probability_national_percentile'] > 50) & (df['burn_probability_national_percentile'] <= 75)).sum()}")
    print(f"  Lower risk (<50th): {(df['burn_probability_national_percentile'] <= 50).sum()}")

    print("\nHighest Risk Counties (by national burn probability percentile):")
    top_risk = df.nlargest(10, 'burn_probability_national_percentile')[['loc_id', 'burn_probability_national_percentile', 'pct_buildings_direct_exposure']]
    for _, row in top_risk.iterrows():
        print(f"  {row['loc_id']}: {row['burn_probability_national_percentile']:.1f}th percentile ({row['pct_buildings_direct_exposure']:.1f}% direct exposure)")

    print("\nCounties with Highest Direct Exposure:")
    top_exposure = df.nlargest(10, 'pct_buildings_direct_exposure')[['loc_id', 'pct_buildings_direct_exposure', 'total_buildings']]
    for _, row in top_exposure.iterrows():
        print(f"  {row['loc_id']}: {row['pct_buildings_direct_exposure']:.1f}% ({int(row['total_buildings']):,} buildings)")


def main():
    """Main conversion logic."""
    print("="*80)
    print("Wildfire Risk to Communities - Excel to Parquet Converter")
    print("="*80)

    # Load and process data
    df = load_county_data()

    # Print statistics
    print_statistics(df)

    # Save parquet
    save_parquet(df)

    print("\n" + "="*80)
    print("COMPLETE!")
    print("="*80)
    print("\nNext steps:")
    print("  1. Create metadata.json for wildfire risk metrics")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
