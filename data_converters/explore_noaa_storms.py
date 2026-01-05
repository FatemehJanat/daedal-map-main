"""
NOAA Storm Events Data Explorer

Analyzes NOAA Storm Events database to report:
- Available years and coverage
- Geographic coverage (states, counties)
- Event types and metrics
- Data volume estimates

Generates a comprehensive report before downloading.

Usage:
    python explore_noaa_storms.py
"""

import requests
import gzip
import io
import pandas as pd
from pathlib import Path
import re

BASE_URL = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"
TIMEOUT = 60

def fetch_directory_listing():
    """Fetch and parse NOAA directory listing."""
    print("Fetching NOAA Storm Events directory...")

    try:
        response = requests.get(BASE_URL, timeout=TIMEOUT)
        response.raise_for_status()

        # Parse HTML table to find files
        lines = response.text.split('\n')
        files = []

        for line in lines:
            if 'StormEvents_details' in line and '.csv.gz' in line:
                # Extract filename using regex
                match = re.search(r'href="([^"]*StormEvents_details[^"]*\.csv\.gz)"', line)
                if match:
                    filename = match.group(1)

                    # Extract year from filename: StormEvents_details-ftp_v1.0_d2024_c20251204.csv.gz
                    year_match = re.search(r'_d(\d{4})_', filename)
                    if year_match:
                        year = int(year_match.group(1))
                        files.append({
                            'filename': filename,
                            'year': year,
                            'url': BASE_URL + filename
                        })

        files.sort(key=lambda x: x['year'])
        return files

    except Exception as e:
        print(f"Error: {e}")
        return []

def sample_file(url, max_rows=10000):
    """Download and sample a CSV file to understand schema."""
    print(f"  Sampling: {url.split('/')[-1]}")

    try:
        # Download compressed file
        response = requests.get(url, timeout=TIMEOUT, stream=True)
        response.raise_for_status()

        # Decompress in memory
        compressed_data = b''.join(response.iter_content(chunk_size=8192))
        decompressed = gzip.decompress(compressed_data)

        # Read into pandas (sample first N rows)
        df = pd.read_csv(io.BytesIO(decompressed), nrows=max_rows)

        return df

    except Exception as e:
        print(f"  Error sampling: {e}")
        return None

def analyze_data_structure(df):
    """Analyze DataFrame to extract metrics and coverage."""
    info = {
        'total_rows': len(df),
        'columns': list(df.columns),
        'event_types': [],
        'states': [],
        'years': [],
        'metrics': []
    }

    # Event types
    if 'EVENT_TYPE' in df.columns:
        info['event_types'] = df['EVENT_TYPE'].value_counts().to_dict()

    # States
    if 'STATE' in df.columns:
        info['states'] = sorted(df['STATE'].dropna().unique().tolist())

    # Years
    if 'YEAR' in df.columns:
        info['years'] = sorted(df['YEAR'].dropna().unique().tolist())
    elif 'BEGIN_YEARMONTH' in df.columns:
        # Extract year from YYYYMM format
        years = df['BEGIN_YEARMONTH'].dropna().astype(str).str[:4].unique()
        info['years'] = sorted([int(y) for y in years if y.isdigit()])

    # Identify numeric columns (potential metrics)
    numeric_cols = df.select_dtypes(include=['int64', 'float64']).columns.tolist()
    info['metrics'] = numeric_cols

    # Sample data types
    info['dtypes'] = {col: str(dtype) for col, dtype in df.dtypes.items()}

    return info

def generate_report(files):
    """Generate comprehensive data availability report."""
    print("\n" + "=" * 80)
    print("NOAA STORM EVENTS DATABASE - DATA AVAILABILITY REPORT")
    print("=" * 80)

    # Overview
    print(f"\n{'OVERVIEW':-^80}")
    print(f"Total files available: {len(files)}")
    print(f"Year range: {files[0]['year']} - {files[-1]['year']}")
    print(f"Years covered: {files[-1]['year'] - files[0]['year'] + 1}")
    print(f"Base URL: {BASE_URL}")

    # Sample recent and old file to understand structure
    print(f"\n{'ANALYZING DATA STRUCTURE':-^80}")
    print("Sampling recent file (2024) and historical file (2000) to understand schema...")

    recent_file = next((f for f in reversed(files) if f['year'] == 2024), files[-1])
    old_file = next((f for f in files if f['year'] == 2000), files[0])

    print(f"\nRecent: {recent_file['filename']}")
    df_recent = sample_file(recent_file['url'], max_rows=50000)

    print(f"\nHistorical: {old_file['filename']}")
    df_old = sample_file(old_file['url'], max_rows=50000)

    if df_recent is None or df_old is None:
        print("\nError: Could not sample files")
        return

    info_recent = analyze_data_structure(df_recent)
    info_old = analyze_data_structure(df_old)

    # Geographic Coverage
    print(f"\n{'GEOGRAPHIC COVERAGE':-^80}")
    print(f"States in recent data: {len(info_recent['states'])}")
    print(f"States in historical data: {len(info_old['states'])}")

    all_states = sorted(set(info_recent['states'] + info_old['states']))
    print(f"\nAll states represented ({len(all_states)}):")
    for i in range(0, len(all_states), 10):
        print("  " + ", ".join(all_states[i:i+10]))

    # Event Types
    print(f"\n{'EVENT TYPES':-^80}")
    print(f"Event types in recent data: {len(info_recent['event_types'])}")
    print("\nTop 20 event types (recent data):")
    sorted_events = sorted(info_recent['event_types'].items(), key=lambda x: x[1], reverse=True)
    for event, count in sorted_events[:20]:
        pct = (count / info_recent['total_rows']) * 100
        print(f"  {event:30} {count:6,} events ({pct:5.1f}%)")

    if len(sorted_events) > 20:
        print(f"\n  ... and {len(sorted_events) - 20} more event types")

    # Data Schema
    print(f"\n{'DATA SCHEMA':-^80}")
    print(f"Total columns: {len(info_recent['columns'])}")

    print("\nKey identification columns:")
    id_cols = [c for c in info_recent['columns'] if any(k in c.upper() for k in ['STATE', 'COUNTY', 'FIPS', 'ZONE', 'CZ'])]
    for col in id_cols:
        print(f"  - {col}")

    print("\nTemporal columns:")
    time_cols = [c for c in info_recent['columns'] if any(k in c.upper() for k in ['YEAR', 'MONTH', 'DAY', 'DATE', 'TIME', 'BEGIN', 'END'])]
    for col in time_cols:
        print(f"  - {col}")

    print("\nNumeric metrics (potential data points):")
    metrics = info_recent['metrics']
    for col in metrics[:30]:  # Show first 30
        dtype = info_recent['dtypes'][col]
        print(f"  - {col:40} ({dtype})")

    if len(metrics) > 30:
        print(f"  ... and {len(metrics) - 30} more numeric columns")

    # Sample data
    print(f"\n{'SAMPLE DATA (first 3 rows from 2024)':-^80}")
    print(df_recent.head(3).to_string())

    # Volume estimates
    print(f"\n{'DATA VOLUME ESTIMATES':-^80}")

    total_rows_sample = info_recent['total_rows']
    print(f"Rows in 2024 sample: {total_rows_sample:,}")

    # Estimate total if we download all years
    est_total = total_rows_sample * len(files)
    print(f"Estimated total rows (all {len(files)} years): {est_total:,}")

    # Estimate file sizes
    avg_file_mb = 12  # From earlier observation
    total_mb = avg_file_mb * len(files)
    print(f"Estimated compressed size: ~{total_mb:,} MB")
    print(f"Estimated decompressed size: ~{total_mb * 10:,} MB")

    # Recommendations
    print(f"\n{'RECOMMENDATIONS':-^80}")
    print("\nTo maximize data coverage, download:")
    print(f"  • All {len(files)} years ({files[0]['year']}-{files[-1]['year']})")
    print(f"  • All {len(all_states)} states")
    print(f"  • All {len(sorted_events)} event types")
    print(f"\nEstimated disk space needed: ~{total_mb * 10 / 1024:.1f} GB (decompressed)")

    print("\nKey metrics to extract:")
    priority_metrics = [m for m in metrics if any(k in m.upper() for k in [
        'DAMAGE', 'DEATH', 'INJUR', 'MAGNITUDE', 'TOR_F', 'BEGIN_LAT', 'BEGIN_LON'
    ])]
    for metric in priority_metrics[:15]:
        print(f"  - {metric}")

    # Next steps
    print(f"\n{'NEXT STEPS':-^80}")
    print("\n1. Run downloader to get all data:")
    print("   python data_converters/download_noaa_storms.py recent")
    print("\n2. Or download all years:")
    print("   python data_converters/download_noaa_storms.py all")
    print("\n3. Build converter to process into parquet format:")
    print("   python data_converters/convert_noaa_storms.py")

    print("\n" + "=" * 80)

def main():
    """Main exploration logic."""
    files = fetch_directory_listing()

    if not files:
        print("Error: Could not fetch file listing")
        return 1

    print(f"Found {len(files)} files")

    generate_report(files)

    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
