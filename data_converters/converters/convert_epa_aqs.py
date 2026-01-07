"""
Convert EPA Air Quality System (AQS) annual county data to parquet format.

Input: Annual AQI CSV files from EPA AQS (1980-2025)
Output:
  - epa_aqs/USA.parquet - Annual AQI metrics by county

Usage:
    python convert_epa_aqs.py

Dataset contains Air Quality Index (AQI) statistics by US county:
- 46 years of data (1980-2025)
- AQI category days (Good, Moderate, Unhealthy, etc.)
- Max/median/90th percentile AQI values
- Pollutant-specific observation days (CO, NO2, Ozone, PM2.5, PM10)
"""
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
import sys

# Add build path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from build.catalog.finalize_source import finalize_source
from data_converters.utilities.us_fips import (
    STATE_NAME_TO_FIPS,
    STATE_FIPS_TO_ABBR,
    normalize_county_name,
    load_county_fips_mapping,
)

# Configuration
INPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/epa_aqs")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/USA/epa_aqs")

# Additional state names not in standard mapping (EPA-specific)
EPA_STATE_NAME_TO_FIPS = {
    **STATE_NAME_TO_FIPS,
    'Country Of Mexico': None,  # Skip
    'Canada': None,  # Skip
}


def load_all_years():
    """Load all yearly AQI files and combine."""
    print("Loading EPA AQS annual data...")

    all_dfs = []
    files = sorted(INPUT_DIR.glob("annual_aqi_by_county_*.csv"))

    for f in files:
        year = int(f.stem.split('_')[-1])
        df = pd.read_csv(f)
        df['Year'] = year  # Ensure year column exists
        all_dfs.append(df)
        print(f"  {year}: {len(df)} counties")

    combined = pd.concat(all_dfs, ignore_index=True)
    print(f"  Total: {len(combined)} records across {len(files)} years")
    return combined


def process_data(df, fips_map):
    """Process raw data into output format with loc_ids."""
    print("\nProcessing data...")

    # Clean state/county names (EPA has trailing spaces sometimes)
    df['State'] = df['State'].str.strip()
    df['County'] = df['County'].str.strip()

    # Build loc_ids
    loc_ids = []
    skipped = 0

    for _, row in df.iterrows():
        state_name = row['State']
        county_name = row['County']

        # Get state FIPS
        state_fips = EPA_STATE_NAME_TO_FIPS.get(state_name)
        if state_fips is None:
            skipped += 1
            loc_ids.append(None)
            continue

        # Get county FIPS
        county_norm = normalize_county_name(county_name)
        fips = fips_map.get((state_fips, county_norm))

        if fips:
            state_abbr = STATE_FIPS_TO_ABBR.get(state_fips, 'XX')
            loc_ids.append(f"USA-{state_abbr}-{fips}")
        else:
            # Fallback: use state abbr + normalized county (for unmapped)
            state_abbr = STATE_FIPS_TO_ABBR.get(state_fips, 'XX')
            loc_ids.append(f"USA-{state_abbr}-{county_norm}")

    df['loc_id'] = loc_ids

    # Filter out rows without loc_id
    df = df[df['loc_id'].notna()].copy()
    print(f"  Skipped {skipped} non-US records")

    # Rename columns to snake_case
    column_map = {
        'State': 'state',
        'County': 'county',
        'Year': 'year',
        'Days with AQI': 'days_with_aqi',
        'Good Days': 'good_days',
        'Moderate Days': 'moderate_days',
        'Unhealthy for Sensitive Groups Days': 'unhealthy_sensitive_days',
        'Unhealthy Days': 'unhealthy_days',
        'Very Unhealthy Days': 'very_unhealthy_days',
        'Hazardous Days': 'hazardous_days',
        'Max AQI': 'max_aqi',
        '90th Percentile AQI': 'aqi_90th_pct',
        'Median AQI': 'median_aqi',
        'Days CO': 'days_co',
        'Days NO2': 'days_no2',
        'Days Ozone': 'days_ozone',
        'Days PM2.5': 'days_pm25',
        'Days PM10': 'days_pm10',
    }
    df = df.rename(columns=column_map)

    # Select and order columns
    output_cols = [
        'loc_id', 'state', 'county', 'year',
        'days_with_aqi', 'good_days', 'moderate_days',
        'unhealthy_sensitive_days', 'unhealthy_days', 'very_unhealthy_days', 'hazardous_days',
        'max_aqi', 'aqi_90th_pct', 'median_aqi',
        'days_co', 'days_no2', 'days_ozone', 'days_pm25', 'days_pm10'
    ]
    df = df[output_cols]

    # Convert to appropriate types
    int_cols = ['year', 'days_with_aqi', 'good_days', 'moderate_days',
                'unhealthy_sensitive_days', 'unhealthy_days', 'very_unhealthy_days', 'hazardous_days',
                'max_aqi', 'aqi_90th_pct', 'median_aqi',
                'days_co', 'days_no2', 'days_ozone', 'days_pm25', 'days_pm10']
    for col in int_cols:
        df[col] = df[col].astype('Int64')

    # Sort by loc_id and year
    df = df.sort_values(['loc_id', 'year'])

    print(f"  Output: {len(df)} records, {df['loc_id'].nunique()} unique counties")
    print(f"  Years: {df['year'].min()}-{df['year'].max()}")

    return df


def save_parquet(df, output_path, description):
    """Save dataframe to parquet."""
    print(f"\nSaving {description}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"  Saved: {output_path}")
    print(f"  Size: {size_mb:.2f} MB, {len(df):,} rows")
    return size_mb


def main():
    """Main conversion workflow."""
    print("=" * 60)
    print("EPA AQS Annual AQI Converter")
    print("=" * 60)

    # Load FIPS mapping
    fips_map = load_county_fips_mapping()

    # Load all yearly data
    df = load_all_years()

    # Process data
    df = process_data(df, fips_map)

    # Save output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "USA.parquet"
    save_parquet(df, output_path, "AQI data")

    # Print summary
    print("\n" + "=" * 60)
    print("Conversion Summary")
    print("=" * 60)
    print(f"Records: {len(df):,}")
    print(f"Counties: {df['loc_id'].nunique()}")
    print(f"Years: {df['year'].min()}-{df['year'].max()}")

    print("\nSample data (recent years, high AQI counties):")
    sample = df[df['year'] >= 2020].nlargest(5, 'max_aqi')[
        ['loc_id', 'county', 'year', 'max_aqi', 'hazardous_days', 'good_days']
    ]
    print(sample.to_string())

    # Finalize
    print("\n" + "=" * 60)
    print("Finalizing source...")
    print("=" * 60)

    try:
        finalize_source(
            parquet_path=str(output_path),
            source_id="epa_aqs"
        )
    except ValueError as e:
        print(f"  Note: {e}")
        print("  Add 'epa_aqs' to source_registry.py to enable auto-finalization")

    return df


if __name__ == "__main__":
    main()
