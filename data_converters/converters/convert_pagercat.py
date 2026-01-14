"""
Convert PAGER-CAT earthquake impact database to parquet format.

PAGER-CAT is a composite earthquake catalog compiled by USGS with
detailed impact data for calibrating global fatality models.

Input: MATLAB .mat file from USGS ScienceBase
Output:
  - pager_cat/events.parquet - Earthquake events with detailed impact data
  - pager_cat/GLOBAL.parquet - Annual aggregates by country

Usage:
    python convert_pagercat.py

Coverage:
- 1900-2007 earthquakes with human impact
- 140+ fields including deaths by cause (tsunami, landslide, building collapse)
- Focal mechanisms, multiple magnitude estimates
- Secondary effects tracking
"""
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
import sys
from scipy.io import loadmat
import numpy as np
from datetime import datetime

# Add build path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from build.catalog.finalize_source import finalize_source

# Configuration
PAGERCAT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/pager_cat")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/global/pager_cat")

# MATLAB file (latest version)
MAT_FILE = "PAGER_CAT_2008_06.1.mat"


def load_matlab_data():
    """Load PAGER-CAT MATLAB file."""
    print("Loading PAGER-CAT MATLAB data...")

    mat_path = PAGERCAT_DIR / MAT_FILE
    if not mat_path.exists():
        print(f"ERROR: MATLAB file not found: {mat_path}")
        sys.exit(1)

    print(f"  Reading: {mat_path}")
    mat_data = loadmat(str(mat_path))

    # PAGER-CAT data is typically stored in a structured array
    # Let's inspect what variables are in the file
    print(f"\n  Variables in MATLAB file:")
    for key in mat_data.keys():
        if not key.startswith('__'):
            data = mat_data[key]
            print(f"    {key}: {type(data)} - shape {getattr(data, 'shape', 'N/A')}")

    # The main data is usually in a variable called 'pagercat' or similar
    # Try common variable names
    for var_name in ['pagercat', 'PAGERCAT', 'data', 'eq', 'earthquakes']:
        if var_name in mat_data:
            print(f"\n  Using variable: {var_name}")
            return mat_data[var_name]

    # If not found, use the first non-metadata variable
    for key in mat_data.keys():
        if not key.startswith('__'):
            print(f"\n  Using variable: {key}")
            return mat_data[key]

    print("ERROR: Could not find earthquake data in MATLAB file")
    sys.exit(1)


def extract_field(data, field_name, index):
    """Safely extract a field from MATLAB structured array."""
    try:
        if hasattr(data, 'dtype') and data.dtype.names:
            # Structured array
            if field_name in data.dtype.names:
                value = data[field_name][index]
                if isinstance(value, np.ndarray):
                    if value.size == 0:
                        return None
                    elif value.size == 1:
                        return value.item()
                    else:
                        return value[0]
                return value
        return None
    except (IndexError, KeyError, AttributeError):
        return None


def convert_matlab_to_dataframe(mat_data):
    """Convert MATLAB structured array to pandas DataFrame."""
    print("\nConverting MATLAB data to DataFrame...")

    # Check if it's a structured array
    if not hasattr(mat_data, 'dtype') or mat_data.dtype.names is None:
        print("  Data structure:")
        print(f"    Type: {type(mat_data)}")
        print(f"    Shape: {mat_data.shape if hasattr(mat_data, 'shape') else 'N/A'}")

        # Try to access as cell array or matrix
        if isinstance(mat_data, np.ndarray):
            if mat_data.ndim == 2:
                # Matrix format - need to know column order
                print("  WARNING: Matrix format detected - may need manual field mapping")
                # Create basic dataframe
                df = pd.DataFrame(mat_data)
                print(f"  Created DataFrame with {len(df)} rows, {len(df.columns)} columns")
                return df
            elif mat_data.ndim == 1 and mat_data.dtype == object:
                # Cell array - try to extract first element
                if len(mat_data) > 0:
                    return convert_matlab_to_dataframe(mat_data[0])

    # Structured array format
    print(f"  Fields available ({len(mat_data.dtype.names)}):")
    for field in mat_data.dtype.names[:20]:  # Show first 20 fields
        print(f"    - {field}")
    if len(mat_data.dtype.names) > 20:
        print(f"    ... and {len(mat_data.dtype.names) - 20} more")

    num_records = len(mat_data)
    print(f"\n  Processing {num_records:,} earthquake records...")

    events = []

    for i in range(num_records):
        try:
            # Extract common PAGER-CAT fields
            # Note: Actual field names may vary - adjust based on inspection
            event = {}

            # Try common field name variations
            for lat_field in ['lat', 'latitude', 'Lat', 'LATITUDE']:
                if lat_field in mat_data.dtype.names:
                    event['latitude'] = extract_field(mat_data, lat_field, i)
                    break

            for lon_field in ['lon', 'longitude', 'Lon', 'LONGITUDE']:
                if lon_field in mat_data.dtype.names:
                    event['longitude'] = extract_field(mat_data, lon_field, i)
                    break

            for depth_field in ['depth', 'Depth', 'DEPTH']:
                if depth_field in mat_data.dtype.names:
                    event['depth'] = extract_field(mat_data, depth_field, i)
                    break

            for mag_field in ['mag', 'magnitude', 'Mag', 'MAGNITUDE']:
                if mag_field in mat_data.dtype.names:
                    event['magnitude'] = extract_field(mat_data, mag_field, i)
                    break

            for year_field in ['year', 'Year', 'YEAR']:
                if year_field in mat_data.dtype.names:
                    event['year'] = extract_field(mat_data, year_field, i)
                    break

            for month_field in ['month', 'Month', 'MONTH', 'mo']:
                if month_field in mat_data.dtype.names:
                    event['month'] = extract_field(mat_data, month_field, i)
                    break

            for day_field in ['day', 'Day', 'DAY']:
                if day_field in mat_data.dtype.names:
                    event['day'] = extract_field(mat_data, day_field, i)
                    break

            # Impact fields
            for deaths_field in ['deaths', 'Deaths', 'DEATHS', 'fatalities', 'Fatalities']:
                if deaths_field in mat_data.dtype.names:
                    event['deaths'] = extract_field(mat_data, deaths_field, i)
                    break

            for injuries_field in ['injuries', 'Injuries', 'INJURIES', 'injured']:
                if injuries_field in mat_data.dtype.names:
                    event['injuries'] = extract_field(mat_data, injuries_field, i)
                    break

            for homeless_field in ['homeless', 'Homeless', 'HOMELESS']:
                if homeless_field in mat_data.dtype.names:
                    event['homeless'] = extract_field(mat_data, homeless_field, i)
                    break

            # Secondary effects
            for tsunami_field in ['tsunami', 'Tsunami', 'TSUNAMI', 'tsun']:
                if tsunami_field in mat_data.dtype.names:
                    event['tsunami'] = extract_field(mat_data, tsunami_field, i)
                    break

            for landslide_field in ['landslide', 'Landslide', 'LANDSLIDE', 'lands']:
                if landslide_field in mat_data.dtype.names:
                    event['landslide'] = extract_field(mat_data, landslide_field, i)
                    break

            # Country
            for country_field in ['country', 'Country', 'COUNTRY', 'ctry']:
                if country_field in mat_data.dtype.names:
                    event['country'] = extract_field(mat_data, country_field, i)
                    break

            # Only add if we have at least year or magnitude
            if event.get('year') or event.get('magnitude'):
                events.append(event)

        except Exception as e:
            # Skip problematic records
            continue

        # Progress indicator
        if (i + 1) % 1000 == 0:
            print(f"    Processed {i + 1:,} / {num_records:,} records...")

    print(f"\n  Extracted {len(events):,} valid events")

    # Create DataFrame
    df = pd.DataFrame(events)

    # Show what fields we successfully extracted
    print(f"\n  Fields extracted:")
    for col in df.columns:
        non_null = df[col].notna().sum()
        print(f"    {col}: {non_null:,} ({non_null/len(df)*100:.1f}%)")

    return df


def process_events(df):
    """Process and standardize earthquake data."""
    print("\nProcessing events...")

    # Create timestamp from year/month/day
    if 'year' in df.columns:
        df['month'] = df['month'].fillna(1).astype(int)
        df['day'] = df['day'].fillna(1).astype(int)
        df['year'] = df['year'].astype(int)

        # Create timestamps
        timestamps = []
        for _, row in df.iterrows():
            try:
                year = int(row['year'])
                month = max(1, min(12, int(row.get('month', 1))))
                day = max(1, min(31, int(row.get('day', 1))))
                ts = datetime(year, month, day)
                timestamps.append(ts)
            except (ValueError, OverflowError):
                timestamps.append(None)

        df['timestamp'] = pd.to_datetime(timestamps)

    # Create event IDs
    df['event_id'] = df.index.astype(str)
    df['event_id'] = 'PAGERCAT_' + df['event_id']

    # Standardize country codes (if available)
    if 'country' in df.columns:
        # Convert country names/codes to ISO3
        df['loc_id'] = df['country'].astype(str).str.upper()
    else:
        df['loc_id'] = None

    # Convert numeric fields
    for col in ['latitude', 'longitude', 'depth', 'magnitude']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    for col in ['deaths', 'injuries', 'homeless']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int32')

    # Filter: keep only events with impact data
    if 'deaths' in df.columns:
        df = df[df['deaths'].notna() | df['injuries'].notna() | df['homeless'].notna()].copy()

    # Sort by date
    if 'timestamp' in df.columns:
        df = df.sort_values('timestamp', ascending=False)

    print(f"\n  Processed {len(df):,} events with impact data")
    if 'year' in df.columns:
        print(f"  Years: {df['year'].min():.0f}-{df['year'].max():.0f}")
    if 'deaths' in df.columns:
        print(f"  Events with deaths: {df['deaths'].notna().sum():,}")
        print(f"  Total deaths: {df['deaths'].sum():,}")
    if 'magnitude' in df.columns:
        print(f"  Magnitude range: {df['magnitude'].min():.1f}-{df['magnitude'].max():.1f}")

    return df


def create_aggregates(events):
    """Create annual aggregates."""
    print("\nCreating aggregates...")

    if 'loc_id' not in events.columns or events['loc_id'].isna().all():
        print("  WARNING: No country data available for aggregation")
        return pd.DataFrame()

    # Aggregate by country and year
    agg = events.groupby(['loc_id', 'year']).agg({
        'event_id': 'count',
        'deaths': 'sum',
        'injuries': 'sum',
        'homeless': 'sum',
    }).reset_index()

    agg.columns = ['loc_id', 'year', 'total_earthquakes', 'total_deaths',
                   'total_injuries', 'total_homeless']

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
    print("PAGER-CAT Earthquake Impact Database Converter")
    print("=" * 70)
    print()

    # Load MATLAB data
    mat_data = load_matlab_data()

    # Convert to DataFrame
    df = convert_matlab_to_dataframe(mat_data)

    if df.empty:
        print("ERROR: No data converted")
        return

    # Process events
    events = process_events(df)

    # Create aggregates
    aggregates = create_aggregates(events)

    # Save outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    events_path = OUTPUT_DIR / "events.parquet"
    save_parquet(events, events_path, "earthquake event data")

    if not aggregates.empty:
        agg_path = OUTPUT_DIR / "GLOBAL.parquet"
        save_parquet(aggregates, agg_path, "country-year aggregates")

    # Print summary
    print("\n" + "=" * 70)
    print("Conversion Summary")
    print("=" * 70)
    print(f"Total earthquakes: {len(events):,}")

    if 'year' in events.columns:
        print(f"Years: {events['year'].min():.0f}-{events['year'].max():.0f}")

    if 'deaths' in events.columns:
        print(f"\nImpact data:")
        print(f"  Events with deaths: {events['deaths'].notna().sum():,}")
        print(f"  Total deaths: {events['deaths'].sum():,}")

    if 'magnitude' in events.columns:
        print(f"\nMagnitude statistics:")
        print(f"  Range: {events['magnitude'].min():.1f} - {events['magnitude'].max():.1f}")
        print(f"  Mean: {events['magnitude'].mean():.1f}")

    print("\n" + "=" * 70)
    print("COMPLETE!")
    print("=" * 70)

    return events, aggregates


if __name__ == "__main__":
    main()
