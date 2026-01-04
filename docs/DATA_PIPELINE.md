# Data Pipeline

Convert raw data sources to standardized parquet format for the globe display.

**Converters**: `data_converters/`
**Output**: `county-map-data/data/{source_id}/`
**Geometry**: See [GEOMETRY.md](GEOMETRY.md) for loc_id specification

---

## Data Format

All indicator data uses **long format** with parquet storage:

```
loc_id      | year | metric1 | metric2 | metric3
USA         | 2020 | 5000    | 15.2    | 800
USA         | 2021 | 4800    | 14.5    | 790
USA-CA      | 2020 | 400     | 10.1    | 50
```

**Required columns**:
- `loc_id` - Canonical location ID (must match geometry files)
- `year` - Integer year
- `[metric columns]` - One or more data columns

**Why long format**:
- Adding new years = append rows (no schema change)
- Parquet compresses repeated loc_ids efficiently
- Query "all 2020 data" with simple filter
- Sparse data is fine - only include rows where data exists

---

## Output Structure

Each source gets its own folder:

```
county-map-data/data/
  owid_co2/
    all_countries.parquet    # Country-level data
    metadata.json            # Source and metric definitions

  census_population/
    USA.parquet              # US-only data
    metadata.json
```

**Naming convention**:
- Country-level sources: `all_countries.parquet`
- US-only sources: `USA.parquet`

---

## Metadata Schema

Each source folder contains a `metadata.json`:

```json
{
  "source_id": "owid_co2",
  "source_name": "Our World in Data",
  "description": "CO2 and greenhouse gas emissions data",
  "source_url": "https://github.com/owid/co2-data",
  "last_updated": "2024-12-21",
  "license": "CC-BY",
  "geographic_level": "country",
  "year_range": {
    "start": 1990,
    "end": 2022
  },
  "countries_covered": 200,
  "metrics": {
    "co2": {
      "name": "Annual CO2 emissions",
      "unit": "million tonnes",
      "aggregation": "sum",
      "description": "Total CO2 emissions from fossil fuels and industry"
    },
    "co2_per_capita": {
      "name": "CO2 per capita",
      "unit": "tonnes per person",
      "aggregation": "avg"
    }
  },
  "topic_tags": ["climate", "emissions", "environment"],
  "llm_summary": "CO2 and greenhouse gas emissions for 200 countries (1990-2022)"
}
```

### Required Fields

| Field | Description |
|-------|-------------|
| `source_id` | Unique identifier (matches folder name) |
| `source_name` | Human-readable source name |
| `description` | Brief description of dataset |
| `last_updated` | Date of last update (YYYY-MM-DD) |
| `geographic_level` | Deepest admin level (country, state, county) |
| `year_range` | Start and end years |
| `metrics` | Dictionary of metric definitions |

### Metric Fields

| Field | Description |
|-------|-------------|
| `name` | Human-readable metric name |
| `unit` | Unit of measurement |
| `aggregation` | How to aggregate: sum, avg, first, max, min |

The `llm_summary` field is sent to the conversation LLM to help it understand available data.

---

## Enhanced Metadata Schema

The enhanced schema adds fields for LLM comprehension and data discovery.

### Full metadata.json Structure

```json
{
  "source_id": "owid_co2",
  "source_name": "Our World in Data",
  "source_url": "https://github.com/owid/co2-data",
  "license": "CC-BY",
  "description": "CO2 and greenhouse gas emissions, energy, and economic data",
  "category": "environmental",
  "topic_tags": ["climate", "emissions", "environment", "energy"],
  "keywords": ["carbon", "pollution", "greenhouse", "warming"],

  "last_updated": "2024-12-22",
  "geographic_level": "country",
  "geographic_coverage": {
    "type": "global",
    "countries": 217,
    "regions": ["Europe", "Asia", "Africa", "Americas", "Oceania"],
    "admin_levels": [0]
  },
  "temporal_coverage": {
    "start": 1750,
    "end": 2024,
    "frequency": "annual"
  },
  "update_schedule": "annual",
  "expected_next_update": "2025-06",
  "row_count": 42000,
  "file_size_mb": 2.0,
  "data_completeness": 0.85,

  "metrics": {
    "gdp": {
      "name": "GDP",
      "unit": "USD",
      "aggregation": "sum",
      "keywords": ["economy", "economic output", "wealth"]
    },
    "co2": {
      "name": "CO2 emissions",
      "unit": "million tonnes",
      "aggregation": "sum",
      "keywords": ["carbon", "emissions", "pollution"]
    }
  },

  "llm_summary": "217 countries, 1750-2024. CO2, GDP, population, energy metrics."
}
```

### New Fields

| Field | Type | Description |
|-------|------|-------------|
| `category` | string | Category: environmental, economic, health, demographic |
| `keywords` | array | Synonyms/related terms for LLM matching |
| `geographic_coverage` | object | Structured coverage info |
| `geographic_coverage.type` | string | global, country, or regional |
| `geographic_coverage.countries` | int | Number of countries covered |
| `geographic_coverage.regions` | array | Regions with data: Europe, Asia, Africa, Americas, Oceania |
| `geographic_coverage.admin_levels` | array | Admin levels present: 0=country, 1=state, 2=county |
| `temporal_coverage` | object | Structured time range |
| `temporal_coverage.start` | int | First year of data |
| `temporal_coverage.end` | int | Last year of data |
| `temporal_coverage.frequency` | string | annual, monthly, or daily |
| `update_schedule` | string | How often source publishes: annual, quarterly, monthly, or unknown |
| `expected_next_update` | string | When to check for new data: YYYY-MM or unknown |
| `row_count` | int | Total rows in parquet |
| `file_size_mb` | float | File size in MB |
| `data_completeness` | float | Non-null ratio (0-1) |
| `metrics[].keywords` | array | Per-metric synonyms for LLM matching |

### Unified Catalog

The `catalog.json` aggregates all metadata into one file for the LLM:

```json
{
  "catalog_version": "1.0",
  "last_updated": "2024-12-22",
  "total_sources": 6,
  "sources": [
    {
      "source_id": "owid_co2",
      "source_name": "Our World in Data",
      "category": "environmental",
      "topic_tags": ["climate", "emissions"],
      "keywords": ["carbon", "pollution"],
      "geographic_level": "country",
      "geographic_coverage": {"type": "global", "countries": 217},
      "temporal_coverage": {"start": 1750, "end": 2024},
      "llm_summary": "217 countries, 1750-2024. CO2, GDP, population, energy."
    }
  ]
}
```

The catalog contains summary info only. The LLM reads the catalog for an overview, then can request full metadata for specific sources if needed.

### Reference Documents (reference.json)

For complex datasets with domain-specific context (SDGs, IMF codes, WHO classifications), an optional `reference.json` provides LLM-readable context:

```json
{
  "source_context": "United Nations SDG Framework",
  "goal": {
    "number": 1,
    "name": "No Poverty",
    "full_title": "End poverty in all its forms everywhere",
    "description": "Goal 1 calls for an end to poverty...",
    "targets": [
      {"id": "1.1", "text": "Eradicate extreme poverty..."},
      {"id": "1.2", "text": "Reduce poverty by half..."}
    ],
    "key_indicators": ["SI_POV_DAY1", "SI_POV_EMP1"]
  },
  "shared_with": ["un_sdg_08", "un_sdg_10"]
}
```

**When to use reference.json**:
- Dataset has domain-specific terminology (SDG targets, IMF BOP codes)
- Indicators have hierarchical structure (goals -> targets -> indicators)
- Some metrics appear in multiple related datasets
- LLM needs context to understand what metrics measure

### Generation Scripts

Scripts are located in `build/` and `build/catalog/`:

```bash
# Regenerate metadata.json for all sources
python build/regenerate_metadata.py

# Build catalog.json from all metadata files
python build/catalog/catalog_builder.py

# Generate metadata for a single source
python build/catalog/metadata_generator.py owid_co2
```

### Metadata Generation Process

The metadata generator (`build/catalog/metadata_generator.py`) introspects parquet files to auto-generate metadata:

1. **Parquet Inspection**: Reads column names, row counts, year ranges
2. **Metric Discovery**: Lists all non-standard columns as metrics
3. **Coverage Analysis**: Counts unique loc_ids, detects admin levels
4. **Template Generation**: Creates metadata.json with placeholders for descriptions

```python
# Example output structure
{
    "source_id": "owid_co2",
    "source_name": "Our World in Data",  # Auto-detected or manual
    "geographic_level": "country",        # Inferred from loc_id format
    "year_range": {"start": 1750, "end": 2024},  # From parquet
    "countries_covered": 217,             # Count of unique loc_ids
    "row_count": 42000,                   # Total rows
    "metrics": {
        "co2": {"name": "co2", "unit": "unknown"}  # Needs manual enrichment
    }
}
```

### Catalog Build Process

The catalog builder (`build/catalog/catalog_builder.py`) aggregates all metadata:

1. **Scan Sources**: Finds all `data/{source_id}/metadata.json` files
2. **Extract Summaries**: Pulls key fields for LLM context
3. **Build Index**: Creates searchable catalog structure
4. **Write Output**: Saves to `county-map-data/catalog.json`

```python
# Catalog structure
{
    "catalog_version": "1.0",
    "last_updated": "2026-01-03",
    "total_sources": 25,
    "sources": [
        {
            "source_id": "owid_co2",
            "source_name": "Our World in Data",
            "category": "environmental",
            "topic_tags": ["climate", "emissions"],
            "geographic_coverage": {"type": "global", "countries": 217},
            "temporal_coverage": {"start": 1750, "end": 2024},
            "llm_summary": "217 countries, 1750-2024. CO2, GDP, population, energy."
        }
    ]
}
```

### Workflow After Adding New Data

```bash
# 1. Run converter to create parquet
python data_converters/convert_mysource.py

# 2. Generate metadata (auto-detects from parquet)
python build/catalog/metadata_generator.py mysource

# 3. Edit metadata.json to add descriptions, units, topic_tags

# 4. Rebuild catalog to include new source
python build/catalog/catalog_builder.py

# 5. Restart server to pick up new catalog
```

---

## Dataset Catalog

### Quick Reference

| Source | Level | Topics | Years | Coverage |
|--------|-------|--------|-------|----------|
| [owid_co2](#owid-co2) | country | environment, energy | 1750-2024 | 218 countries |
| [who_health](#who-health) | country | health | 2015-2024 | 198 countries |
| [imf_bop](#imf-bop) | country | economics | 2005-2022 | 195 countries |
| [un_sdg_01-17](#un-sdg) | country | development | 1970-2024 | 200+ countries |
| [census_population](#census-population) | county | demographics | 2020-2024 | 3,144 US counties |
| [census_agesex](#census-agesex) | county | demographics | 2019-2024 | 3,144 US counties |
| [census_demographics](#census-demographics) | county | demographics | 2020-2024 | 3,144 US counties |
| [world_factbook](#world-factbook) | country | infrastructure, military, energy | 1990-2020 | 250 countries |

---

### world_factbook (World Factbook)

World Factbook - 51 unique metrics not available elsewhere.

**Converter**: `data_converters/convert_world_factbook.py`
**Output**: `data/world_factbook/all_countries.parquet`
**Source**: https://www.cia.gov/the-world-factbook/
**Editions**: 2000-2020 (21 years, 5-year intervals recommended)

Split into two sources:
- `world_factbook` - 51 metrics NOT in other sources (in catalog)
- `world_factbook_overlap` - 27 metrics also in OWID/WHO/IMF (excluded from catalog)

**Unique Metrics by Category**:

| Category | Metrics |
|----------|---------|
| Infrastructure | airports, railways_km, roadways_km, waterways_km, merchant_marine |
| Military | military_expenditure_pct |
| Oil/Gas | crude_oil_production/exports/imports/reserves, natural_gas_* |
| Electricity | electricity_capacity, fossil/nuclear/hydro/renewable_pct |
| Banking | central_bank_discount_rate, commercial_bank_prime_rate, foreign_reserves |
| Financial | stock_fdi_abroad/at_home, gini_index |
| Communications | telephones_fixed/mobile, broadband_subscriptions, internet_users |

**Usage**:
```bash
# Import unique metrics (recommended)
python convert_world_factbook.py --editions 2000,2005,2010,2015,2020 --source-type unique --save

# Import overlap metrics (for historical time series)
python convert_world_factbook.py --editions 2000,2005,2010,2015,2020 --source-type overlap --save

# List all metrics
python convert_world_factbook.py --list-metrics
```

**Technical Notes**:
- HTML format changed across editions (text 2000-2001, rankorder 2003-2017, modern 2018-2020)
- Field ID mappings stored in `world_factbook_field_mappings.json`
- 2-letter codes mapped to ISO3 via appendix-d.html
- Detailed format docs in `WORLD_FACTBOOK_CONVERTER_REFERENCE.md`

---

### owid_co2

Our World in Data CO2 and greenhouse gas emissions.

**Converter**: `data_converters/convert_owid_co2.py`
**Output**: `data/owid_co2/all_countries.parquet` (2.0 MB, 42K rows)
**Source**: https://github.com/owid/co2-data

| Metric | Unit | Description |
|--------|------|-------------|
| `co2` | million tonnes | Annual CO2 emissions |
| `co2_per_capita` | tonnes/person | Per-capita emissions |
| `gdp` | USD | Gross Domestic Product |
| `population` | count | Total population |
| `primary_energy_consumption` | TWh | Energy consumption |
| `methane` | million tonnes CO2eq | Methane emissions |
| `nitrous_oxide` | million tonnes CO2eq | N2O emissions |

---

### who_health

World Health Organization health indicators.

**Converter**: `data_converters/convert_who_health.py`
**Output**: `data/who_health/all_countries.parquet` (111 KB, 1.5K rows)
**Source**: WHO Global Health Observatory

| Metric | Unit | Description |
|--------|------|-------------|
| `life_expectancy` | years | Life expectancy at birth |
| `healthy_life_expectancy` | years | Healthy life expectancy |
| `maternal_mortality` | per 100K | Maternal mortality ratio |
| `infant_mortality` | per 1K | Infant mortality rate |
| `uhc_index` | 0-100 | Universal health coverage index |

54 total metrics including disaggregations by sex.

---

### imf_bop

International Monetary Fund balance of payments.

**Converter**: `data_converters/convert_imf_bop.py`
**Output**: `data/imf_bop/all_countries.parquet` (1.0 MB, 3.3K rows)
**Source**: IMF Data Portal

| Metric | Unit | Description |
|--------|------|-------------|
| `current_account` | USD millions | Current account balance |
| `financial_account` | USD millions | Financial account balance |
| `exports` | USD millions | Goods and services exports |
| `imports` | USD millions | Goods and services imports |

37 total metrics.

---

### un_sdg

UN Sustainable Development Goals - 17 goal-specific datasets.

**Converter**: `data_converters/convert_sdg.py`
**Output**: `data/un_sdg_01/` through `data/un_sdg_17/`
**Source**: https://unstats.un.org/sdgs/indicators/database/

Each goal folder contains:
- `all_countries.parquet` - Wide format data (loc_id, year, metric columns)
- `metadata.json` - Source info and metric definitions
- `reference.json` - Goal context for LLM (targets, descriptions)

| Goal | Name | Key Topics |
|------|------|------------|
| 1 | No Poverty | poverty, income, social protection |
| 2 | Zero Hunger | food, nutrition, agriculture |
| 3 | Good Health | health, mortality, disease |
| 4 | Quality Education | education, literacy, school |
| 5 | Gender Equality | gender, women, empowerment |
| 6 | Clean Water | water, sanitation, hygiene |
| 7 | Clean Energy | energy, electricity, renewable |
| 8 | Economic Growth | employment, labor, jobs, GDP |
| 9 | Infrastructure | industry, innovation, technology |
| 10 | Reduced Inequalities | inequality, discrimination |
| 11 | Sustainable Cities | urban, housing, transport |
| 12 | Responsible Consumption | waste, recycling, production |
| 13 | Climate Action | climate, emissions, disaster |
| 14 | Life Below Water | ocean, marine, fishing |
| 15 | Life on Land | forest, biodiversity, land |
| 16 | Peace and Justice | governance, violence, institutions |
| 17 | Partnerships | cooperation, trade, aid |

**Note**: Uses M49 to ISO3 country code mapping (stored in `data_converters/m49_mapping.json`).

---

### census_population

US Census Bureau county-level population estimates.

**Converter**: `data_converters/convert_census_population.py`
**Output**: `data/census_population/USA.parquet` (290 KB, 15.7K rows)
**Source**: US Census Bureau

| Metric | Unit | Description |
|--------|------|-------------|
| `total_pop` | count | Total population |
| `male` | count | Male population |
| `female` | count | Female population |

**loc_id format**: `USA-{state}-{fips}` (e.g., `USA-CA-6037`)

---

### census_agesex

US Census Bureau age and sex demographics.

**Converter**: `data_converters/convert_census_agesex.py`
**Output**: `data/census_agesex/USA.parquet` (854 KB, 18.9K rows)
**Source**: US Census Bureau

| Metric | Unit | Description |
|--------|------|-------------|
| `median_age` | years | Median age |
| `under_5` | count | Population under 5 |
| `age_18_plus` | count | Adult population |
| `age_65_plus` | count | Senior population |

15 total metrics with age brackets.

---

### census_demographics

US Census Bureau race/ethnicity demographics.

**Converter**: `data_converters/convert_census_demographics.py`
**Output**: `data/census_demographics/USA.parquet` (638 KB, 15.7K rows)
**Source**: US Census Bureau

| Metric | Unit | Description |
|--------|------|-------------|
| `white` | count | White population |
| `black` | count | Black population |
| `asian` | count | Asian population |
| `hispanic` | count | Hispanic population |

14 total metrics with breakdowns by sex.

---

## Running Converters

```bash
cd county-map

# Country-level
python data_converters/convert_owid_co2.py
python data_converters/convert_who_health.py
python data_converters/convert_imf_bop.py

# US Census
python data_converters/convert_census_population.py
python data_converters/convert_census_agesex.py
python data_converters/convert_census_demographics.py
```

---

## Adding New Data Sources

### 1. Create converter script

Create `data_converters/convert_{source_id}.py`:

```python
import pandas as pd
import os
import json

# Paths
RAW_FILE = r"C:\Users\Bryan\Desktop\county-map-data\Raw data\source.csv"
OUTPUT_DIR = r"C:\Users\Bryan\Desktop\county-map-data\data\source_id"
GEOMETRY_FILE = r"C:\Users\Bryan\Desktop\county-map-data\geometry\global.csv"

def convert():
    df = pd.read_csv(RAW_FILE)

    # Transform to standard format
    df['loc_id'] = df['country_code']  # or use fips_to_loc_id for US data
    df = df.rename(columns={'data_year': 'year'})

    # Select and order columns
    metric_cols = ['metric1', 'metric2', 'metric3']
    df = df[['loc_id', 'year'] + metric_cols]

    # Verify loc_ids match geometry
    geom = pd.read_csv(GEOMETRY_FILE)
    valid_ids = set(geom['loc_id'])
    df = df[df['loc_id'].isin(valid_ids)]

    # Save
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df.to_parquet(os.path.join(OUTPUT_DIR, "all_countries.parquet"), index=False)
    print(f"Saved {len(df)} rows")

def create_metadata():
    metadata = {
        "source_id": "source_id",
        "source_name": "Source Name",
        "description": "What this data contains",
        "source_url": "https://...",
        "last_updated": "2024-12-21",
        "geographic_level": "country",
        "year_range": {"start": 2000, "end": 2024},
        "metrics": {
            "metric1": {
                "name": "Metric One",
                "unit": "count",
                "aggregation": "sum"
            }
        },
        "topic_tags": ["economics"],
        "llm_summary": "Brief description for the chat LLM"
    }

    with open(os.path.join(OUTPUT_DIR, "metadata.json"), 'w') as f:
        json.dump(metadata, f, indent=2)

if __name__ == "__main__":
    convert()
    create_metadata()
    print("Done!")
```

### 2. For US data: FIPS to loc_id

```python
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

def fips_to_loc_id(state_fips, county_fips):
    """Convert FIPS codes to loc_id format."""
    state_str = str(state_fips).zfill(2)
    county_str = str(county_fips).zfill(3)
    abbrev = STATE_FIPS.get(state_str)
    if not abbrev:
        return None
    full_fips = int(state_str + county_str)
    return f'USA-{abbrev}-{full_fips}'
```

### 3. Validate and run

```bash
python data_converters/convert_mysource.py
```

Check that:
- All loc_ids match entries in geometry files
- Year column is integer
- Metric columns have reasonable values
- metadata.json is valid JSON

### 4. Data Type Requirements

**IMPORTANT**: All metric columns must be stored as numeric types (float64/double), not strings.

Raw CSV data often has values as strings. Always convert before saving to parquet:

```python
# Convert metric columns to numeric (REQUIRED)
metric_cols = [c for c in df.columns if c not in ['loc_id', 'year']]
for col in metric_cols:
    df[col] = pd.to_numeric(df[col], errors='coerce')

# Then save
df.to_parquet(output_path, index=False)
```

**Why this matters**:
- String columns break aggregation queries (sum, mean, etc.)
- Time series charts fail with string data
- Parquet files are larger with string encoding

**Verify with**:
```python
import pyarrow.parquet as pq
pf = pq.read_table('output.parquet')
print(pf.schema)  # All metrics should show 'double', not 'string'
```

This was discovered when SDG data had all 578 metrics stored as strings, breaking global aggregation queries.

---

## Topic Index

| Topic | Sources |
|-------|---------|
| **economics** | owid_co2, imf_bop, un_sdg_08, world_factbook (banking, financial) |
| **environment** | owid_co2, un_sdg_13, un_sdg_14, un_sdg_15 |
| **health** | who_health, un_sdg_03 |
| **demographics** | census_population, census_agesex, census_demographics |
| **energy** | owid_co2, un_sdg_07, world_factbook (oil, gas, electricity sources) |
| **poverty** | un_sdg_01, un_sdg_10 |
| **education** | un_sdg_04 |
| **water/sanitation** | un_sdg_06 |
| **gender** | un_sdg_05 |
| **governance** | un_sdg_16 |
| **infrastructure** | world_factbook (airports, railways, roads, waterways) |
| **military** | world_factbook (military expenditure) |
| **communications** | world_factbook (telephones, internet, broadband) |

---

## Primary Source Selection

When multiple sources have the same metric, the app selects:

| Query Type | Primary Source | Fallback |
|------------|----------------|----------|
| CO2/emissions | owid_co2 | - |
| GDP | owid_co2 | imf_bop |
| Population (global) | owid_co2 | - |
| Population (US counties) | census_population | - |
| Health indicators | who_health | - |
| Trade/finance | imf_bop | - |
| Infrastructure | world_factbook | - |
| Military spending | world_factbook | - |
| Oil/gas production | world_factbook | - |
| Electricity sources | world_factbook | - |

---

## Files That Use Data

| File | Purpose |
|------|---------|
| `mapmover/data_loading.py` | Load parquets, initialize catalog |
| `mapmover/preprocessor.py` | Extract topics, resolve regions, detect patterns |
| `mapmover/order_taker.py` | LLM interprets user queries with context injection |
| `mapmover/postprocessor.py` | Validate orders, expand derived fields |
| `mapmover/order_executor.py` | Execute orders, calculate derived fields |
| `build/catalog/metadata_generator.py` | Generate metadata.json from parquet |
| `build/catalog/catalog_builder.py` | Build catalog.json from all metadata |
| `build/regenerate_metadata.py` | Batch regenerate all metadata files |

---

## Complete Import Workflow

When importing new data (especially with geometry), follow this sequence:

### 1. Geometry Import (if new locations)

If your data includes new geographic entities (NYC boroughs, watersheds, etc.):

```bash
# Import geometry to country parquet
python scripts/import_geometry.py nyc_boroughs.geojson --country USA

# Or for cross-cutting entities
python scripts/import_geometry.py watersheds.geojson --global
```

### 2. Post-Process Geometry

Always run after geometry changes:

```bash
python mapmover/post_process_geometry.py
```

This adds:
- Aggregated parent geometry (dissolve children)
- Bounding boxes (for viewport filtering)
- Children counts (for popup info)

### 3. Run Data Converter

Convert your raw data to parquet format:

```bash
python data_converters/convert_mysource.py
```

### 4. Rebuild Catalog

Update catalog.json with the new source:

```bash
python scripts/build_catalog.py
```

### Workflow Diagram

```
Raw Data + GeoJSON
       |
       v
+------------------+
| Geometry Import  |  (if new locations)
+------------------+
       |
       v
+------------------+
| Post-Processing  |  <-- Aggregates, bboxes, children counts
+------------------+
       |
       v
+------------------+
| Data Converter   |  <-- Creates parquet with loc_id
+------------------+
       |
       v
+------------------+
| Catalog Builder  |  <-- Updates catalog.json
+------------------+
       |
       v
    Ready for
    Runtime Use
```

---

## Future: Supabase Database Migration

Migrate from CSV/parquet files to Supabase PostgreSQL for better performance and scalability.

**Why migrate:**
- Server-side filtering (not loading 358k rows into memory)
- Faster queries with indexes
- Less Railway memory usage
- Cross-dataset queries become natural
- Scales better as data grows

**Architecture:**
```
Current:  CSV files -> pandas -> filter -> GeoJSON
Future:   Supabase tables -> SQL query -> small result -> GeoJSON
```

**Table structure:**
```sql
countries_geometry (code, name, geometry, continent, ...)
owid_data (country_code, year, gdp, population, co2, ...)
who_health (country_code, year, indicator, value, ...)
census_demographics (state_code, county_code, year, population, ...)
dataset_metadata (table_name, source_name, source_url, columns JSONB, ...)
```

**Multi-query approach (not JOINs):**
```python
# 1. Get geometry
geometry = supabase.table('countries_geometry').select('*').in_('code', codes).execute()

# 2. Get each data field separately (can fail independently)
gdp = supabase.table('owid_data').select('country_code, gdp').eq('year', 2022).execute()
pop = supabase.table('owid_data').select('country_code, population').eq('year', 2022).execute()

# 3. Merge in Python and calculate derived fields
for country in result:
    country['gdp_per_capita'] = country['gdp'] / country['population']
```

**ETL changes:**
- Convert wide format to long format (years as rows, not columns)
- `df.melt()` to transform IMF-style data
- Insert to Supabase instead of writing CSV

**Cost estimate:**
- Current data ~100 MB (well under 500 MB free tier)
- Pro tier ($25/mo) for production reliability
- No per-query costs

**Migration steps:**
1. Create tables in Supabase with proper schema
2. Update ETL to insert to Supabase (wide->long conversion)
3. Add RLS policies (public read, admin write)
4. Create `supabase_queries.py` module for data fetching
5. Replace pandas CSV loading with Supabase queries in mapmover.py
6. Keep metadata table for LLM dataset selection
7. Test derived field calculations in Python
8. Remove large CSVs from git repo
9. Update admin dashboard for Supabase management

---

*Last Updated: 2026-01-03*
