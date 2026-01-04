"""
Convert CIA Factbook extras scraped JSON to parquet format and generate metadata.
"""

import json
import pandas as pd
from pathlib import Path
import sys

# Add build directory to path for metadata_generator
sys.path.insert(0, str(Path(__file__).parent.parent / "build" / "catalog"))
from metadata_generator import generate_metadata

# Paths
SCRAPED_JSON = Path("C:/Users/Bryan/Desktop/county-map/data_converters/world_factbook_archive/world_factbook_extras_scraped.json")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/data/world_factbook_extras")
PARQUET_FILE = OUTPUT_DIR / "all_countries.parquet"
METADATA_FILE = OUTPUT_DIR / "metadata.json"
REFERENCE_FILE = OUTPUT_DIR / "reference.json"


def main():
    print("Converting CIA Factbook extras to parquet...")

    # Load scraped data
    with open(SCRAPED_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print(f"Loaded {len(data)} records")

    # Convert to DataFrame
    df = pd.DataFrame(data)

    # Ensure proper column types
    df['loc_id'] = df['loc_id'].astype(str)
    df['metric'] = df['metric'].astype(str)
    df['value'] = pd.to_numeric(df['value'], errors='coerce')
    df['year'] = pd.to_numeric(df['year'], errors='coerce').astype('Int64')

    # Remove any rows with missing essential data
    df = df.dropna(subset=['loc_id', 'metric', 'value'])

    print(f"DataFrame shape: {df.shape}")
    print(f"Metrics: {df['metric'].nunique()}")
    print(f"Countries: {df['loc_id'].nunique()}")
    print(f"Year range: {df['year'].min()} - {df['year'].max()}")

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Save to parquet
    df.to_parquet(PARQUET_FILE, index=False)
    print(f"Saved parquet: {PARQUET_FILE}")

    # Generate metadata
    source_info = {
        "source_id": "world_factbook_extras",
        "source_name": "CIA World Factbook - Additional Metrics",
        "source_url": "https://www.cia.gov/the-world-factbook/",
        "license": "Public Domain",
        "description": "Additional numeric metrics from CIA World Factbook not in main scraper - includes military, health, infrastructure, and social indicators",
        "category": "mixed",
        "topic_tags": ["military", "health", "infrastructure", "economy", "demographics"],
        "keywords": ["factbook", "cia", "military spending", "literacy", "urbanization", "poverty"]
    }

    metric_info = {
        "military_expenditure_pct_gdp": {"name": "Military Expenditure (% GDP)", "unit": "%", "keywords": ["defense", "military spending"]},
        "remittances_pct_gdp": {"name": "Remittances (% GDP)", "unit": "%", "keywords": ["migration", "transfers"]},
        "urban_population_pct": {"name": "Urban Population", "unit": "%", "keywords": ["urbanization", "cities"]},
        "urbanization_rate_pct": {"name": "Urbanization Rate", "unit": "%/year", "keywords": ["urbanization", "growth"]},
        "gdp_nominal": {"name": "GDP (Nominal)", "unit": "USD", "keywords": ["economy", "output"]},
        "irrigated_land_sq_km": {"name": "Irrigated Land", "unit": "sq km", "keywords": ["agriculture", "water"]},
        "electricity_consumption_kwh": {"name": "Electricity Consumption", "unit": "kWh", "keywords": ["energy", "power"]},
        "budget_revenues": {"name": "Budget Revenues", "unit": "USD", "keywords": ["government", "fiscal"]},
        "budget_expenditures": {"name": "Budget Expenditures", "unit": "USD", "keywords": ["government", "fiscal"]},
        "physicians_per_1000": {"name": "Physicians per 1000", "unit": "per 1000", "keywords": ["health", "doctors"]},
        "energy_per_capita_btu": {"name": "Energy per Capita", "unit": "BTU", "keywords": ["energy", "consumption"]},
        "health_expenditure_pct_gdp": {"name": "Health Expenditure (% GDP)", "unit": "%", "keywords": ["health", "spending"]},
        "alcohol_consumption_liters": {"name": "Alcohol Consumption", "unit": "liters/year", "keywords": ["health", "alcohol"]},
        "major_ports_count": {"name": "Major Ports", "unit": "count", "keywords": ["infrastructure", "shipping"]},
        "renewable_water_cu_m": {"name": "Renewable Water Resources", "unit": "cubic meters", "keywords": ["water", "environment"]},
        "tobacco_use_pct": {"name": "Tobacco Use", "unit": "%", "keywords": ["health", "smoking"]},
        "heliports": {"name": "Heliports", "unit": "count", "keywords": ["infrastructure", "aviation"]},
        "poverty_rate_pct": {"name": "Poverty Rate", "unit": "%", "keywords": ["poverty", "inequality"]},
        "railways_km": {"name": "Railways", "unit": "km", "keywords": ["infrastructure", "transport"]},
        "literacy_rate_pct": {"name": "Literacy Rate", "unit": "%", "keywords": ["education", "literacy"]},
        "electricity_access_pct": {"name": "Electricity Access", "unit": "%", "keywords": ["energy", "infrastructure"]},
    }

    metadata = generate_metadata(str(PARQUET_FILE), source_info, metric_info)

    with open(METADATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    print(f"Saved metadata: {METADATA_FILE}")

    # Create reference file
    reference = {
        "source_context": "CIA World Factbook - Extended Metrics",
        "about": {
            "name": "World Factbook Extras",
            "publisher": "Central Intelligence Agency (CIA)",
            "purpose": "Additional metrics extracted from individual country pages that complement the main comparison table data",
            "extraction_method": "Scraped from country page-data JSON endpoints"
        },
        "this_dataset": {
            "focus": "Metrics not available in standard comparison tables",
            "categories": [
                {
                    "name": "Military & Security",
                    "metrics": ["military_expenditure_pct_gdp"],
                    "notes": "Multi-year time series of military spending"
                },
                {
                    "name": "Health & Education",
                    "metrics": ["health_expenditure_pct_gdp", "physicians_per_1000", "literacy_rate_pct", "alcohol_consumption_liters", "tobacco_use_pct"],
                    "notes": "Health system capacity and outcomes"
                },
                {
                    "name": "Demographics & Society",
                    "metrics": ["urban_population_pct", "urbanization_rate_pct", "poverty_rate_pct", "remittances_pct_gdp"],
                    "notes": "Population distribution and economic conditions"
                },
                {
                    "name": "Infrastructure",
                    "metrics": ["railways_km", "major_ports_count", "heliports", "electricity_access_pct", "electricity_consumption_kwh"],
                    "notes": "Physical infrastructure measurements"
                },
                {
                    "name": "Economy & Resources",
                    "metrics": ["gdp_nominal", "budget_revenues", "budget_expenditures", "irrigated_land_sq_km", "renewable_water_cu_m", "energy_per_capita_btu"],
                    "notes": "Economic and natural resource indicators"
                }
            ]
        },
        "related_datasets": {
            "world_factbook": "Main comparison table metrics (52 time series fields)",
            "world_factbook_static": "Static geographic data",
            "world_factbook_text": "Descriptive text fields (reference/world_factbook_text.json)"
        },
        "citation": "Central Intelligence Agency. The World Factbook 2025. https://www.cia.gov/the-world-factbook/"
    }

    with open(REFERENCE_FILE, 'w', encoding='utf-8') as f:
        json.dump(reference, f, indent=2, ensure_ascii=False)
    print(f"Saved reference: {REFERENCE_FILE}")

    print("\nDone!")


if __name__ == '__main__':
    main()
