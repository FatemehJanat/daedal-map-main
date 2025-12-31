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

### Generation Scripts

- `scripts/regenerate_metadata.py` - Regenerate metadata.json for all sources
- `scripts/build_catalog.py` - Build catalog.json from all metadata files

---

## Dataset Catalog

### Quick Reference

| Source | Level | Topics | Years | Coverage |
|--------|-------|--------|-------|----------|
| [owid_co2](#owid-co2) | country | environment, energy | 1750-2024 | 218 countries |
| [who_health](#who-health) | country | health | 2015-2024 | 198 countries |
| [imf_bop](#imf-bop) | country | economics | 2005-2022 | 195 countries |
| [census_population](#census-population) | county | demographics | 2020-2024 | 3,144 US counties |
| [census_agesex](#census-agesex) | county | demographics | 2019-2024 | 3,144 US counties |
| [census_demographics](#census-demographics) | county | demographics | 2020-2024 | 3,144 US counties |

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

---

## Topic Index

| Topic | Sources |
|-------|---------|
| **economics** | owid_co2, imf_bop |
| **environment** | owid_co2 |
| **health** | who_health |
| **demographics** | census_population, census_agesex, census_demographics |
| **energy** | owid_co2 |

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

---

## Files That Use Data

| File | Purpose |
|------|---------|
| `mapmover/data_loading.py` | Load parquets, build catalog |
| `mapmover/order_taker.py` | LLM interprets user queries using catalog.json |
| `mapmover/order_executor.py` | Execute orders against parquet files |
| `mapmover/metadata_generator.py` | Generate metadata.json from parquet |
| `mapmover/catalog_builder.py` | Build catalog.json from all metadata |

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

*Last Updated: 2025-12-30*
