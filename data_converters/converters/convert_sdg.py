"""
SDG Data Converter

Converts UN SDG database CSV to 17 parquet files (one per goal).
Each goal becomes a self-contained source folder with:
  - all_countries.parquet (wide format: loc_id, year, metric columns)
  - metadata.json (source info, metrics, coverage)
  - reference.json (goal context for LLM - generated separately)

Usage:
    python data_converters/convert_sdg.py
"""

import pandas as pd
import json
from pathlib import Path
from datetime import datetime


# Paths
RAW_DATA_PATH = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/2025_Q3.2_AllData_Before_20251212.csv")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/data")
MAPPING_PATH = Path(__file__).parent / "m49_mapping.json"

# SDG Goal names for metadata
SDG_GOAL_NAMES = {
    1: "No Poverty",
    2: "Zero Hunger",
    3: "Good Health and Well-being",
    4: "Quality Education",
    5: "Gender Equality",
    6: "Clean Water and Sanitation",
    7: "Affordable and Clean Energy",
    8: "Decent Work and Economic Growth",
    9: "Industry, Innovation and Infrastructure",
    10: "Reduced Inequalities",
    11: "Sustainable Cities and Communities",
    12: "Responsible Consumption and Production",
    13: "Climate Action",
    14: "Life Below Water",
    15: "Life on Land",
    16: "Peace, Justice and Strong Institutions",
    17: "Partnerships for the Goals",
}

# Topic tags for each goal (for catalog discovery)
SDG_TOPIC_TAGS = {
    1: ["poverty", "income", "social protection"],
    2: ["hunger", "food", "nutrition", "agriculture"],
    3: ["health", "mortality", "disease", "wellbeing"],
    4: ["education", "literacy", "school", "learning"],
    5: ["gender", "women", "equality", "empowerment"],
    6: ["water", "sanitation", "hygiene", "drinking water"],
    7: ["energy", "electricity", "renewable", "clean energy"],
    8: ["employment", "labor", "economic growth", "jobs", "gdp"],
    9: ["infrastructure", "industry", "innovation", "technology"],
    10: ["inequality", "income distribution", "discrimination"],
    11: ["cities", "urban", "housing", "transport", "sustainable"],
    12: ["consumption", "production", "waste", "recycling"],
    13: ["climate", "emissions", "disaster", "resilience"],
    14: ["ocean", "marine", "sea", "fishing", "coastal"],
    15: ["land", "forest", "biodiversity", "desertification"],
    16: ["peace", "justice", "institutions", "governance", "violence"],
    17: ["partnership", "cooperation", "trade", "development aid"],
}


def load_m49_mapping() -> dict:
    """Load M49 to ISO3 country code mapping."""
    with open(MAPPING_PATH, encoding='utf-8') as f:
        data = json.load(f)
    # Convert string keys back to int for lookup
    return {int(k): v for k, v in data['m49_to_iso3'].items()}


def filter_to_totals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filter to 'total' aggregation rows only.
    SDG data has disaggregation by Age, Sex, Location, etc.
    We want the overall totals for initial import.
    """
    # Define what counts as "total" for each dimension
    total_values = {
        'Age': ['ALLAGE', '_T', ''],
        'Sex': ['BOTHSEX', '_T', ''],
        'Location': ['ALLAREA', '_T', ''],
    }

    mask = pd.Series(True, index=df.index)

    for col, valid_values in total_values.items():
        if col in df.columns:
            col_mask = df[col].isna() | df[col].isin(valid_values)
            mask = mask & col_mask

    return df[mask]


def convert_goal(goal_num: int, df_goal: pd.DataFrame, m49_to_iso3: dict) -> dict:
    """
    Convert data for a single SDG goal to parquet format.

    Returns dict with stats about the conversion.
    """
    source_id = f"un_sdg_{goal_num:02d}"
    output_dir = OUTPUT_DIR / source_id
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*50}")
    print(f"Processing Goal {goal_num}: {SDG_GOAL_NAMES.get(goal_num, 'Unknown')}")
    print(f"{'='*50}")
    print(f"Input rows: {len(df_goal):,}")

    # Filter to totals only
    df_filtered = filter_to_totals(df_goal)
    print(f"After filtering to totals: {len(df_filtered):,}")

    # Map GeoAreaCode to ISO3
    df_filtered = df_filtered.copy()
    df_filtered['loc_id'] = df_filtered['GeoAreaCode'].map(m49_to_iso3)

    # Keep only rows with valid country mapping
    df_countries = df_filtered[df_filtered['loc_id'].notna()].copy()
    print(f"After country mapping: {len(df_countries):,}")

    if len(df_countries) == 0:
        print(f"WARNING: No data for Goal {goal_num} after filtering!")
        return {'goal': goal_num, 'rows': 0, 'countries': 0, 'series': 0}

    # Extract series info for metadata
    series_info = {}
    for _, row in df_countries[['SeriesCode', 'SeriesDescription', 'Units']].drop_duplicates().iterrows():
        code = row['SeriesCode']
        if code and pd.notna(code):
            series_info[code.lower()] = {
                'name': row['SeriesDescription'][:100] if pd.notna(row['SeriesDescription']) else code,
                'unit': row['Units'] if pd.notna(row['Units']) else 'unknown',
                'original_code': code
            }

    print(f"Unique series: {len(series_info)}")

    # Pivot to wide format
    # Columns: loc_id, year, {series_code_1}, {series_code_2}, ...
    df_pivot = df_countries.pivot_table(
        index=['loc_id', 'TimePeriod'],
        columns='SeriesCode',
        values='Value',
        aggfunc='first'  # Take first value if duplicates
    ).reset_index()

    # Rename columns
    df_pivot.columns.name = None
    df_pivot = df_pivot.rename(columns={'TimePeriod': 'year'})

    # Lowercase all series columns
    new_cols = {}
    for col in df_pivot.columns:
        if col not in ['loc_id', 'year']:
            new_cols[col] = col.lower()
    df_pivot = df_pivot.rename(columns=new_cols)

    # Ensure year is integer
    df_pivot['year'] = df_pivot['year'].astype(int)

    # Convert metric columns to numeric (they come as strings from CSV)
    metric_cols = [c for c in df_pivot.columns if c not in ['loc_id', 'year']]
    for col in metric_cols:
        df_pivot[col] = pd.to_numeric(df_pivot[col], errors='coerce')

    # Sort by loc_id, year
    df_pivot = df_pivot.sort_values(['loc_id', 'year']).reset_index(drop=True)

    print(f"Final shape: {df_pivot.shape[0]} rows x {df_pivot.shape[1]} columns")
    print(f"Countries: {df_pivot['loc_id'].nunique()}")
    print(f"Year range: {df_pivot['year'].min()}-{df_pivot['year'].max()}")

    # Save parquet
    parquet_path = output_dir / "all_countries.parquet"
    df_pivot.to_parquet(parquet_path, index=False)
    print(f"Saved: {parquet_path}")

    # Generate metadata
    metadata = generate_metadata(goal_num, df_pivot, series_info)
    metadata_path = output_dir / "metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved: {metadata_path}")

    return {
        'goal': goal_num,
        'rows': len(df_pivot),
        'countries': df_pivot['loc_id'].nunique(),
        'series': len(series_info),
        'year_min': int(df_pivot['year'].min()),
        'year_max': int(df_pivot['year'].max())
    }


def generate_metadata(goal_num: int, df: pd.DataFrame, series_info: dict) -> dict:
    """Generate metadata.json for an SDG goal."""

    source_id = f"un_sdg_{goal_num:02d}"
    goal_name = SDG_GOAL_NAMES.get(goal_num, f"Goal {goal_num}")

    # Get list of country codes
    country_codes = sorted(df['loc_id'].unique().tolist())

    # Build metrics dict
    metrics = {}
    for code, info in series_info.items():
        metrics[code] = {
            'name': info['name'],
            'unit': info['unit'],
            'aggregation': 'avg',  # Most SDG indicators are rates/percentages
            'keywords': []
        }

    return {
        "source_id": source_id,
        "source_name": f"UN SDG Goal {goal_num}: {goal_name}",
        "source_url": "https://unstats.un.org/sdgs/indicators/database/",
        "license": "Open Data",
        "description": f"Sustainable Development Goal {goal_num} ({goal_name}) indicators from UN Statistics Division",
        "category": "development",
        "topic_tags": ["sdg", f"goal{goal_num}"] + SDG_TOPIC_TAGS.get(goal_num, []),
        "keywords": [goal_name.lower()] + SDG_TOPIC_TAGS.get(goal_num, []),
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
        "geographic_level": "country",
        "geographic_coverage": {
            "type": "global",
            "countries": len(country_codes),
            "country_codes": country_codes[:30],  # First 30 for preview
            "country_codes_all": country_codes
        },
        "temporal_coverage": {
            "start": int(df['year'].min()),
            "end": int(df['year'].max()),
            "frequency": "annual"
        },
        "row_count": len(df),
        "file_size_mb": round((df.memory_usage(deep=True).sum() / 1024 / 1024), 2),
        "metrics": metrics,
        "llm_summary": f"{len(country_codes)} countries. {int(df['year'].min())}-{int(df['year'].max())}. {len(metrics)} indicators for {goal_name}."
    }


def main():
    """Main conversion function."""
    print("=" * 60)
    print("SDG Data Converter")
    print("=" * 60)

    # Load M49 mapping
    print("\nLoading M49 to ISO3 mapping...")
    m49_to_iso3 = load_m49_mapping()
    print(f"Loaded {len(m49_to_iso3)} country mappings")

    # Read CSV in chunks by Goal to manage memory
    print(f"\nReading SDG data from: {RAW_DATA_PATH}")

    # Columns we need
    use_cols = [
        'Goal', 'Target', 'Indicator', 'SeriesCode', 'SeriesDescription',
        'GeoAreaCode', 'GeoAreaName', 'TimePeriod', 'Value', 'Units',
        'Age', 'Sex', 'Location'
    ]

    # Read full CSV (this takes a while with 2GB)
    print("Loading CSV (this may take a minute)...")
    df = pd.read_csv(RAW_DATA_PATH, usecols=use_cols, low_memory=False)
    print(f"Loaded {len(df):,} rows")

    # Process each goal
    results = []
    for goal_num in range(1, 18):
        df_goal = df[df['Goal'] == goal_num]
        if len(df_goal) > 0:
            result = convert_goal(goal_num, df_goal, m49_to_iso3)
            results.append(result)

    # Summary
    print("\n" + "=" * 60)
    print("CONVERSION COMPLETE")
    print("=" * 60)
    print(f"\n{'Goal':<6} {'Rows':>10} {'Countries':>10} {'Series':>8} {'Years':>12}")
    print("-" * 50)

    total_rows = 0
    for r in results:
        if r['rows'] > 0:
            print(f"{r['goal']:<6} {r['rows']:>10,} {r['countries']:>10} {r['series']:>8} {r['year_min']}-{r['year_max']:>4}")
            total_rows += r['rows']

    print("-" * 50)
    print(f"Total: {total_rows:,} rows across {len(results)} goals")
    print(f"\nOutput directory: {OUTPUT_DIR}")
    print("\nNext steps:")
    print("  1. Generate reference.json for each goal (run generate_sdg_references.py)")
    print("  2. Regenerate catalog: python -m mapmover.catalog_builder")


if __name__ == "__main__":
    main()
