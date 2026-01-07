"""
Convert U.S. Drought Monitor data to parquet format.

Aggregates weekly drought data to annual statistics per county-year.

Input: CSV files from download_usdm_drought.py
Output: USA.parquet with annual drought statistics

Usage:
    python convert_usdm_drought.py

Metrics calculated per county-year:
- max_drought_severity: Highest drought category reached (0-4)
- avg_drought_severity: Average drought severity weighted by area
- weeks_in_drought: Number of weeks with any drought (D0+)
- weeks_d0, weeks_d1, weeks_d2, weeks_d3, weeks_d4: Weeks in each category
- pct_year_in_drought: Percent of year with any drought
- pct_year_severe: Percent of year in severe+ drought (D2+)
"""
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
from datetime import datetime

# Configuration
RAW_DATA_DIR = Path("C:/Users/bryan/Desktop/county_map_data/Raw data/usdm_drought")
OUTPUT_DIR = Path("C:/Users/bryan/Desktop/county_map_data/data/usdm_drought")

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


def fips_to_loc_id(fips_code):
    """Convert 5-digit FIPS code to loc_id format."""
    fips_str = str(fips_code).zfill(5)
    state_fips = fips_str[:2]
    state_abbr = STATE_FIPS.get(state_fips)

    if not state_abbr:
        return None

    return f"USA-{state_abbr}-{int(fips_str)}"


def calculate_drought_severity(row):
    """
    Calculate weighted average drought severity for a week.

    Severity scale:
    - None: 0
    - D0 (Abnormally Dry): 1
    - D1 (Moderate): 2
    - D2 (Severe): 3
    - D3 (Extreme): 4
    - D4 (Exceptional): 5

    Returns weighted average based on percentage of area in each category.
    """
    weights = {
        'None': 0,
        'D0': 1,
        'D1': 2,
        'D2': 3,
        'D3': 4,
        'D4': 5
    }

    total = 0
    for category, weight in weights.items():
        pct = row.get(category, 0)
        total += (pct / 100.0) * weight

    return total


def process_csv_files():
    """Load and aggregate all CSV files to annual statistics."""
    print("\nProcessing CSV files...")

    csv_files = list(RAW_DATA_DIR.glob("usdm_*.csv"))
    print(f"  Found {len(csv_files)} CSV files")

    all_data = []

    for csv_path in csv_files:
        state = csv_path.stem.split('_')[1]
        print(f"  Loading {state}...")

        try:
            df = pd.read_csv(csv_path)

            # Convert MapDate to datetime
            df['date'] = pd.to_datetime(df['MapDate'], format='%Y%m%d')
            df['year'] = df['date'].dt.year

            # Ensure FIPS is 5 digits
            df['FIPS'] = df['FIPS'].astype(str).str.zfill(5)

            # Calculate weekly drought severity
            df['severity'] = df.apply(calculate_drought_severity, axis=1)

            # Flag if county is in any drought (D0+)
            df['in_drought'] = (df['D0'] + df['D1'] + df['D2'] + df['D3'] + df['D4']) > 0

            # Flag if county is in severe+ drought (D2+)
            df['severe_drought'] = (df['D2'] + df['D3'] + df['D4']) > 0

            # Group by county-year
            grouped = df.groupby(['FIPS', 'year'])

            for (fips, year), group in grouped:
                # Convert FIPS to loc_id
                loc_id = fips_to_loc_id(fips)
                if not loc_id:
                    continue

                # Count weeks in each category
                # A week counts for a category if >0% of area is in that category
                weeks_d0 = (group['D0'] > 0).sum()
                weeks_d1 = (group['D1'] > 0).sum()
                weeks_d2 = (group['D2'] > 0).sum()
                weeks_d3 = (group['D3'] > 0).sum()
                weeks_d4 = (group['D4'] > 0).sum()

                # Total weeks with data for this year
                total_weeks = len(group)

                # Weeks in any drought
                weeks_in_drought = group['in_drought'].sum()

                # Weeks in severe+ drought
                weeks_severe = group['severe_drought'].sum()

                # Max severity reached
                max_severity = group['severity'].max()

                # Average severity (mean of weekly weighted averages)
                avg_severity = group['severity'].mean()

                # Percent of year metrics
                pct_year_in_drought = (weeks_in_drought / total_weeks) * 100 if total_weeks > 0 else 0
                pct_year_severe = (weeks_severe / total_weeks) * 100 if total_weeks > 0 else 0

                all_data.append({
                    'loc_id': loc_id,
                    'year': int(year),
                    'max_drought_severity': round(max_severity, 2),
                    'avg_drought_severity': round(avg_severity, 2),
                    'weeks_in_drought': int(weeks_in_drought),
                    'weeks_d0': int(weeks_d0),
                    'weeks_d1': int(weeks_d1),
                    'weeks_d2': int(weeks_d2),
                    'weeks_d3': int(weeks_d3),
                    'weeks_d4': int(weeks_d4),
                    'pct_year_in_drought': round(pct_year_in_drought, 1),
                    'pct_year_severe': round(pct_year_severe, 1),
                    'total_weeks': int(total_weeks)
                })

        except Exception as e:
            print(f"    ERROR processing {csv_path.name}: {e}")
            continue

    print(f"\n  Processed {len(all_data)} county-year records")
    return pd.DataFrame(all_data)


def save_parquet(df):
    """Save DataFrame to parquet."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "USA.parquet"

    print(f"\nSaving to {output_path}...")

    # Define schema
    schema = pa.schema([
        ('loc_id', pa.string()),
        ('year', pa.int32()),
        ('max_drought_severity', pa.float32()),
        ('avg_drought_severity', pa.float32()),
        ('weeks_in_drought', pa.int32()),
        ('weeks_d0', pa.int32()),
        ('weeks_d1', pa.int32()),
        ('weeks_d2', pa.int32()),
        ('weeks_d3', pa.int32()),
        ('weeks_d4', pa.int32()),
        ('pct_year_in_drought', pa.float32()),
        ('pct_year_severe', pa.float32()),
        ('total_weeks', pa.int32())
    ])

    # Convert to Arrow Table
    table = pa.Table.from_pandas(df, schema=schema)

    # Write parquet with compression
    pq.write_table(table, output_path, compression='snappy')

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Saved: {size_mb:.2f} MB")

    return output_path


def print_statistics(df):
    """Print summary statistics."""
    print("\n" + "="*80)
    print("STATISTICS")
    print("="*80)

    print(f"\nTotal county-year records: {len(df):,}")
    print(f"Unique counties: {df['loc_id'].nunique():,}")
    print(f"Year range: {df['year'].min()} - {df['year'].max()}")

    print("\nDrought Severity (0-5 scale):")
    print(f"  Max ever recorded: {df['max_drought_severity'].max():.2f}")
    print(f"  Mean max severity: {df['max_drought_severity'].mean():.2f}")
    print(f"  Mean avg severity: {df['avg_drought_severity'].mean():.2f}")

    print("\nDrought Frequency:")
    print(f"  Mean weeks in drought per year: {df['weeks_in_drought'].mean():.1f}")
    print(f"  Mean weeks in severe+ drought: {df[['weeks_d2', 'weeks_d3', 'weeks_d4']].sum(axis=1).mean():.1f}")

    print("\nMost drought-prone counties (by avg % of year in drought):")
    top_drought = df.groupby('loc_id')['pct_year_in_drought'].mean().nlargest(5)
    for loc_id, pct in top_drought.items():
        print(f"  {loc_id}: {pct:.1f}%")

    print("\nMost severe drought years (by avg severity across all counties):")
    severe_years = df.groupby('year')['avg_drought_severity'].mean().nlargest(5)
    for year, severity in severe_years.items():
        print(f"  {year}: {severity:.2f}")


def main():
    """Main conversion logic."""
    print("="*80)
    print("U.S. Drought Monitor - CSV to Parquet Converter")
    print("="*80)

    # Process CSV files
    df = process_csv_files()

    if df.empty:
        print("\nERROR: No data processed")
        return 1

    # Print statistics
    print_statistics(df)

    # Save parquet
    save_parquet(df)

    print("\n" + "="*80)
    print("COMPLETE!")
    print("="*80)
    print("\nNext steps:")
    print("  1. Create metadata.json for drought metrics")
    print("  2. Add to catalog.json")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
