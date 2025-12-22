"""
Convert WHO Health Statistics (WHS) data to parquet format.

Input: WHS2025_DATADOWNLOAD.csv (narrow format - indicators as rows)
Output: who_health/all_countries.parquet (wide format - indicators as columns)

The WHO data has disaggregations (by sex, age group, substance).
This script creates separate columns for each disaggregation:
- life_expectancy_total, life_expectancy_male, life_expectancy_female
- adolescent_birth_rate_10_14, adolescent_birth_rate_15_19
"""

import pandas as pd
import os
import json
import re

# Configuration
INPUT_FILE = r"C:\Users\Bryan\Desktop\county-map\data_pipeline\data_cleaned\WHS2025_DATADOWNLOAD.csv"
OUTPUT_DIR = r"C:\Users\Bryan\Desktop\county-map-data\data\who_health"

# Column name mapping: IndicatorCode -> clean column name
INDICATOR_NAMES = {
    "AMR_INFECT_ECOLI": "amr_ecoli_resistance",
    "AMR_INFECT_MRSA": "amr_mrsa_resistance",
    "FINPROTECTION_CATA_TOT_10_POP": "health_expenditure_over_10pct",
    "FINPROTECTION_CATA_TOT_25_POP": "health_expenditure_over_25pct",
    "GHED_GGHE-DGGE_SHA2011": "govt_health_expenditure_pct",
    "HWF_0001": "doctors_per_10k",
    "HWF_0006": "nurses_per_10k",
    "HWF_0010": "dentists_per_10k",
    "HWF_0014": "pharmacists_per_10k",
    "MALARIA_EST_INCIDENCE": "malaria_incidence",
    "MCV2": "measles_immunization",
    "MDG_0000000003": "adolescent_birth_rate",  # has age disaggregation
    "MDG_0000000007": "under5_mortality",
    "MDG_0000000020": "tb_incidence",
    "MDG_0000000025": "skilled_birth_attendance",
    "MDG_0000000026": "maternal_mortality",
    "M_Est_tob_curr_std": "tobacco_use",
    "NCDMORT3070": "ncd_mortality_30_70",
    "NUTOVERWEIGHTPREV": "child_overweight",
    "NUTRITION_ANAEMIA_REPRODUCTIVEAGE_PREV": "anaemia_women",
    "NUTRITION_WH_2": "child_wasting",
    "NUTSTUNTINGPREV": "child_stunting",
    "PCV3": "pneumococcal_immunization",
    "PHE_HHAIR_PROP_POP_CLEAN_FUELS": "clean_fuels",
    "RS_198": "road_traffic_mortality",
    "SA_0000001688": "alcohol_consumption",
    "SDGAIRBODA": "air_pollution_mortality",
    "SDGFPALL": "family_planning_need_met",
    "SDGHEALTHFACILITIESESSENTIALMEDS": "essential_medicines_access",
    "SDGHEPHBSAGPRV": "hepatitis_b_prevalence",
    "SDGHIV": "hiv_incidence",
    "SDGHPVRECEIVED": "hpv_immunization",
    "SDGIHR2021": "health_regulations_score",
    "SDGIPV12M": "intimate_partner_violence_12m",
    "SDGIPVLT": "intimate_partner_violence_lifetime",
    "SDGNTDTREATMENT": "ntd_treatment_needed",
    "SDGODA01": "health_oda_research",
    "SDGODAWS": "wash_oda",
    "SDGPM25": "pm25_concentration",
    "SDGPOISON": "poisoning_mortality",
    "SDGSUICIDE": "suicide_mortality",
    "SDGWSHBOD": "unsafe_wash_mortality",
    "SUD_TREATMENTSERVICES_COVERAGE": "substance_treatment_coverage",  # has substance disaggregation
    "UHC_INDEX_REPORTED": "uhc_index",
    "VIOLENCE_HOMICIDERATE": "homicide_mortality",
    "WHOSIS_000001": "life_expectancy",  # has sex disaggregation
    "WHOSIS_000002": "healthy_life_expectancy",  # has sex disaggregation
    "WHOSIS_000003": "neonatal_mortality",
    "WHS4_100": "dtp3_immunization",
    "WSH_DOMESTIC_WASTE_SAFELY_TREATED": "wastewater_treated",
    "WSH_HYGIENE_BASIC": "hygiene_basic",
    "WSH_SANITATION_SAFELY_MANAGED": "sanitation_safe",
    "WSH_WATER_SAFELY_MANAGED": "water_safe",
}

# Disaggregation suffixes
DISAGG_SUFFIXES = {
    "SEX_BTSX": "_total",
    "SEX_MLE": "_male",
    "SEX_FMLE": "_female",
    "AGEGROUP_YEARS10-14": "_10_14",
    "AGEGROUP_YEARS15-19": "_15_19",
    "ALCOHOL": "_alcohol",
    "DRUGS": "_drugs",
}


def get_column_name(indicator_code, disaggregation):
    """Generate column name from indicator code and disaggregation."""
    base_name = INDICATOR_NAMES.get(indicator_code, indicator_code.lower())

    # Add disaggregation suffix if applicable
    suffix = DISAGG_SUFFIXES.get(disaggregation, "")

    return base_name + suffix


def convert_who_data():
    """Convert WHO CSV to parquet format."""
    print("Loading WHO data...")
    df = pd.read_csv(INPUT_FILE)
    print(f"Loaded {len(df):,} rows")

    # Create column name for each row
    df['column_name'] = df.apply(
        lambda row: get_column_name(row['IndicatorCode'], row['Disaggregation']),
        axis=1
    )

    # Pivot to wide format
    print("Pivoting to wide format...")
    pivot_df = df.pivot_table(
        index=['country_code', 'data_year'],
        columns='column_name',
        values='NumericValue',
        aggfunc='first'  # Take first value if duplicates
    ).reset_index()

    # Rename columns
    pivot_df = pivot_df.rename(columns={
        'country_code': 'loc_id',
        'data_year': 'year'
    })

    # Reorder columns: loc_id, year first
    cols = ['loc_id', 'year'] + [c for c in sorted(pivot_df.columns) if c not in ['loc_id', 'year']]
    pivot_df = pivot_df[cols]

    print(f"Result: {len(pivot_df):,} rows x {len(pivot_df.columns)} columns")

    # Verify country codes match geometry
    print("\nVerifying country codes...")
    geom = pd.read_csv(r"C:\Users\Bryan\Desktop\county-map-data\geometry\global.csv")
    geom_codes = set(geom['loc_id'])
    who_codes = set(pivot_df['loc_id'])

    matched = who_codes & geom_codes
    unmatched = who_codes - geom_codes

    print(f"Matched: {len(matched)}")
    if unmatched:
        print(f"Unmatched: {unmatched}")

    # Save parquet
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "all_countries.parquet")
    pivot_df.to_parquet(out_path, index=False)
    print(f"\nSaved: {out_path}")
    print(f"Size: {os.path.getsize(out_path) / 1024:.1f} KB")

    # Show sample
    print("\n=== Sample (USA) ===")
    usa = pivot_df[pivot_df['loc_id'] == 'USA']
    print(usa[['loc_id', 'year', 'life_expectancy_total', 'uhc_index', 'doctors_per_10k']].to_string(index=False))

    return pivot_df


def create_metadata(df):
    """Create metadata.json for the dataset."""

    # Get list of metric columns
    metric_cols = [c for c in df.columns if c not in ['loc_id', 'year']]

    metadata = {
        "source_id": "who_health",
        "source_name": "World Health Organization",
        "description": "WHO Global Health Observatory indicators",
        "source_url": "https://www.who.int/data/gho",
        "last_updated": "2024-12-21",
        "license": "CC BY-NC-SA 3.0 IGO",
        "geographic_level": "country",
        "year_range": {
            "start": int(df['year'].min()),
            "end": int(df['year'].max())
        },
        "countries_covered": df['loc_id'].nunique(),
        "metrics": {},
        "topic_tags": ["health", "mortality", "disease", "healthcare"],
        "llm_summary": f"WHO health indicators for {df['loc_id'].nunique()} countries ({df['year'].min()}-{df['year'].max()})"
    }

    # Add key metrics
    key_metrics = {
        "life_expectancy_total": ("Life expectancy at birth", "years", "avg"),
        "healthy_life_expectancy_total": ("Healthy life expectancy", "years", "avg"),
        "uhc_index": ("Universal health coverage index", "0-100", "avg"),
        "maternal_mortality": ("Maternal mortality ratio", "per 100K", "avg"),
        "under5_mortality": ("Under-5 mortality rate", "per 1000", "avg"),
        "neonatal_mortality": ("Neonatal mortality rate", "per 1000", "avg"),
        "doctors_per_10k": ("Medical doctors density", "per 10K", "avg"),
        "nurses_per_10k": ("Nurses and midwives density", "per 10K", "avg"),
        "tb_incidence": ("Tuberculosis incidence", "per 100K", "avg"),
        "hiv_incidence": ("HIV incidence", "per 1000", "avg"),
        "malaria_incidence": ("Malaria incidence", "per 1000 at risk", "avg"),
    }

    for col, (name, unit, agg) in key_metrics.items():
        if col in metric_cols:
            metadata["metrics"][col] = {
                "name": name,
                "unit": unit,
                "aggregation": agg
            }

    # Save metadata
    meta_path = os.path.join(OUTPUT_DIR, "metadata.json")
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved: {meta_path}")

    return metadata


if __name__ == "__main__":
    df = convert_who_data()
    create_metadata(df)
    print("\nDone!")
