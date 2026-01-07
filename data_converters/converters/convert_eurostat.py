"""
Convert Eurostat NUTS 3 regional data to parquet format.

Input: TSV files from Eurostat Bulk Download
  - demo_r_gind3.tsv - Demographics (population, births, deaths, migration)
  - nama_10r_3gdp.tsv - Regional GDP

Output:
  - global/eurostat/NUTS3.parquet - All NUTS 3 regions combined (long format)
  - Per-country files in countries/{ISO3}/eurostat/{ISO3}.parquet

Usage:
    python convert_eurostat.py

Dataset contains ~1,600 NUTS 3 regions across ~38 European countries with:
- 25 years of demographic data (2000-2024)
- 24 years of GDP data (2000-2023)
- Multiple indicators per dataset

loc_id format: {ISO3}-{NUTS3_code} e.g., DEU-DE111 (Stuttgart region)
"""
import pandas as pd
import re
from pathlib import Path
import json

# Configuration
RAW_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/imported/eurostat")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/global/eurostat")
COUNTRIES_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries")

# ISO2 to ISO3 mapping for European countries in Eurostat
ISO2_TO_ISO3 = {
    'AL': 'ALB',  # Albania
    'AT': 'AUT',  # Austria
    'BE': 'BEL',  # Belgium
    'BG': 'BGR',  # Bulgaria
    'CH': 'CHE',  # Switzerland
    'CY': 'CYP',  # Cyprus
    'CZ': 'CZE',  # Czechia
    'DE': 'DEU',  # Germany
    'DK': 'DNK',  # Denmark
    'EE': 'EST',  # Estonia
    'EL': 'GRC',  # Greece (EL is Eurostat code, GR is ISO)
    'ES': 'ESP',  # Spain
    'FI': 'FIN',  # Finland
    'FR': 'FRA',  # France
    'HR': 'HRV',  # Croatia
    'HU': 'HUN',  # Hungary
    'IE': 'IRL',  # Ireland
    'IS': 'ISL',  # Iceland
    'IT': 'ITA',  # Italy
    'LI': 'LIE',  # Liechtenstein
    'LT': 'LTU',  # Lithuania
    'LU': 'LUX',  # Luxembourg
    'LV': 'LVA',  # Latvia
    'ME': 'MNE',  # Montenegro
    'MK': 'MKD',  # North Macedonia
    'MT': 'MLT',  # Malta
    'NL': 'NLD',  # Netherlands
    'NO': 'NOR',  # Norway
    'PL': 'POL',  # Poland
    'PT': 'PRT',  # Portugal
    'RO': 'ROU',  # Romania
    'RS': 'SRB',  # Serbia
    'SE': 'SWE',  # Sweden
    'SI': 'SVN',  # Slovenia
    'SK': 'SVK',  # Slovakia
    'TR': 'TUR',  # Turkey
    'UK': 'GBR',  # United Kingdom
}

# Demographic indicators to extract
DEMO_INDICATORS = {
    'JAN': 'population',           # Population on January 1
    'LBIRTH': 'births',           # Live births
    'DEATH': 'deaths',            # Deaths
    'NATGROW': 'natural_growth',  # Natural population change
    'CNMIGRAT': 'net_migration',  # Net migration
    'GROW': 'pop_change',         # Total population change
}

# GDP indicators to extract (unit codes)
GDP_INDICATORS = {
    'EUR_HAB': 'gdp_per_capita_eur',      # GDP per capita in EUR
    'MIO_EUR': 'gdp_mio_eur',             # GDP in million EUR
    'PPS_HAB_EU27_2020': 'gdp_per_capita_pps',  # GDP per capita in PPS
}


def parse_eurostat_tsv(filepath, indicators_map):
    """Parse Eurostat TSV file into long format DataFrame.

    Eurostat TSV format:
    - First column: 'freq,indic,geo\\TIME_PERIOD' (combined key)
    - Subsequent columns: year values with possible flags (e, p, :, etc.)

    Args:
        filepath: Path to TSV file
        indicators_map: Dict mapping indicator codes to column names

    Returns:
        DataFrame in long format (loc_id, year, metric columns)
    """
    print(f"  Loading {filepath.name}...")

    # Read TSV
    df = pd.read_csv(filepath, sep='\t', dtype=str)

    # Parse the combined first column
    first_col = df.columns[0]  # e.g., 'freq,indic_de,geo\TIME_PERIOD'

    # Split the first column into components
    parts = df[first_col].str.split(',', expand=True)
    df['freq'] = parts[0]
    df['indicator'] = parts[1]
    df['geo'] = parts[2]

    # Drop the combined column
    df = df.drop(columns=[first_col])

    # Get year columns (everything except freq, indicator, geo)
    year_cols = [c for c in df.columns if c not in ['freq', 'indicator', 'geo']]

    # Clean year column names (remove trailing spaces)
    year_rename = {c: c.strip() for c in year_cols}
    df = df.rename(columns=year_rename)
    year_cols = [c.strip() for c in year_cols]

    # Filter to NUTS 3 level (5 character codes: 2 letter country + 3 alphanumeric)
    nuts3_pattern = r'^[A-Z]{2}[A-Z0-9]{3}$'
    df = df[df['geo'].str.match(nuts3_pattern, na=False)]
    print(f"    Filtered to {len(df)} NUTS 3 rows")

    # Filter to indicators we want
    df = df[df['indicator'].isin(indicators_map.keys())]
    print(f"    Filtered to {len(df)} rows for selected indicators")

    if len(df) == 0:
        return pd.DataFrame()

    # Melt to long format
    df_long = df.melt(
        id_vars=['geo', 'indicator'],
        value_vars=year_cols,
        var_name='year',
        value_name='value'
    )

    # Clean values - remove flags and convert to numeric
    # Eurostat uses: ':' for missing, 'e' for estimated, 'p' for provisional, etc.
    df_long['value'] = df_long['value'].str.replace(r'[^0-9.\-]', '', regex=True)
    df_long['value'] = pd.to_numeric(df_long['value'], errors='coerce')
    df_long['year'] = pd.to_numeric(df_long['year'], errors='coerce')

    # Drop rows with missing values
    df_long = df_long.dropna(subset=['value', 'year'])

    # Map indicator codes to column names
    df_long['metric'] = df_long['indicator'].map(indicators_map)

    # Pivot to get one row per geo-year with metric columns
    df_pivot = df_long.pivot_table(
        index=['geo', 'year'],
        columns='metric',
        values='value',
        aggfunc='first'
    ).reset_index()

    print(f"    Result: {len(df_pivot)} rows, columns: {list(df_pivot.columns)}")
    return df_pivot


def create_loc_id(nuts3_code):
    """Convert NUTS 3 code to loc_id format.

    NUTS 3 code: DE111 (2 letter country + 3 char region)
    loc_id: DEU-DE111
    """
    iso2 = nuts3_code[:2]
    iso3 = ISO2_TO_ISO3.get(iso2)
    if not iso3:
        return None
    return f"{iso3}-{nuts3_code}"


def main():
    """Main conversion workflow."""
    print("=" * 60)
    print("Eurostat NUTS 3 Converter")
    print("=" * 60)

    # Parse demographic data
    demo_file = RAW_DIR / "demo_r_gind3" / "demo_r_gind3.tsv"
    if demo_file.exists():
        df_demo = parse_eurostat_tsv(demo_file, DEMO_INDICATORS)
    else:
        print(f"  Warning: {demo_file} not found")
        df_demo = pd.DataFrame()

    # Parse GDP data
    gdp_file = RAW_DIR / "nama_10r_3gdp" / "nama_10r_3gdp.tsv"
    if gdp_file.exists():
        df_gdp = parse_eurostat_tsv(gdp_file, GDP_INDICATORS)
    else:
        print(f"  Warning: {gdp_file} not found")
        df_gdp = pd.DataFrame()

    # Merge demographic and GDP data
    print("\nMerging datasets...")
    if len(df_demo) > 0 and len(df_gdp) > 0:
        df = pd.merge(df_demo, df_gdp, on=['geo', 'year'], how='outer')
    elif len(df_demo) > 0:
        df = df_demo
    elif len(df_gdp) > 0:
        df = df_gdp
    else:
        print("ERROR: No data loaded!")
        return

    print(f"  Merged: {len(df)} rows")

    # Create loc_id
    df['loc_id'] = df['geo'].apply(create_loc_id)
    df = df[df['loc_id'].notna()]  # Drop rows without valid loc_id

    # Rename geo column and reorder
    df = df.drop(columns=['geo'])
    df['year'] = df['year'].astype(int)

    # Reorder columns: loc_id, year, then metrics
    metric_cols = [c for c in df.columns if c not in ['loc_id', 'year']]
    df = df[['loc_id', 'year'] + sorted(metric_cols)]

    # Sort by loc_id and year
    df = df.sort_values(['loc_id', 'year']).reset_index(drop=True)

    print(f"\n=== Final Dataset ===")
    print(f"Rows: {len(df):,}")
    print(f"Locations: {df['loc_id'].nunique()}")
    print(f"Years: {df['year'].min()}-{df['year'].max()}")
    print(f"Columns: {list(df.columns)}")

    # Save global file
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    global_path = OUTPUT_DIR / "NUTS3.parquet"
    df.to_parquet(global_path, index=False)
    print(f"\nSaved: {global_path}")
    print(f"Size: {global_path.stat().st_size / 1024:.1f} KB")

    # Also save per-country files
    print("\nSaving per-country files...")
    df['iso3'] = df['loc_id'].str[:3]
    for iso3, country_df in df.groupby('iso3'):
        country_dir = COUNTRIES_DIR / iso3 / "eurostat"
        country_dir.mkdir(parents=True, exist_ok=True)
        country_path = country_dir / f"{iso3}.parquet"
        country_df.drop(columns=['iso3']).to_parquet(country_path, index=False)
        print(f"  {iso3}: {len(country_df):,} rows -> {country_path.name}")

    # Show sample
    print("\n=== Sample (Germany, first 5 years) ===")
    sample = df[df['loc_id'].str.startswith('DEU-DE1')].head(10)
    print(sample.to_string(index=False))

    # Summary stats
    print("\n=== Coverage by Country ===")
    coverage = df.groupby('iso3').agg({
        'loc_id': 'nunique',
        'year': ['min', 'max']
    }).round(0)
    coverage.columns = ['regions', 'year_min', 'year_max']
    print(coverage.to_string())

    return df


if __name__ == "__main__":
    main()
