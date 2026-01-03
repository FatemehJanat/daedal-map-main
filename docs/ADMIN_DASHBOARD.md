# Admin Dashboard - Design Document

Design for the data preparation and management dashboard.

**Status**: Planning
**Location**: admin/app.py (to be rebuilt)

---

## Purpose

The admin dashboard is the BUILD side of the system. It handles:
1. Importing new datasets
2. Managing metadata
3. Viewing system health and coverage gaps

---

## MVP: Core Import Decisions

The minimum viable import workflow answers two questions:

### Decision 1: Source Folder

```
New data file: world_bank_poverty_2024.csv

Options:
  ( ) Create NEW source folder: world_bank_poverty/
  (x) Add to EXISTING source: owid_co2/
      -> Merge with existing data
```

**When to create new:**
- Different source/provider
- Different update schedule
- Different licensing
- Unrelated topic

**When to combine:**
- Same source, new year
- Same source, additional indicators
- Filling gaps in existing dataset

### Decision 2: File Structure

```
File structure for this source:

  (x) Single file: all_countries.parquet
      Best for: Country-level data, smaller datasets
      Current size: 45 MB, 52,000 rows

  ( ) Per-country files: {ISO3}.parquet
      Best for: Sub-national data (states, counties)
      Creates: 257 separate files
```

**Rule of thumb:**
- Country-level (admin_0) -> single file
- Sub-national (admin_1, admin_2) -> per-country files

### Decision 3: Year Handling (for existing datasets)

```
Existing dataset: owid_co2
Current years: 1750-2023

New file contains: 2024 data

Options:
  (x) APPEND: Add 2024 to existing data
      Result: 1750-2024 (adds ~217 rows)

  ( ) REPLACE year: Overwrite 2024 data only
      Use when: Source corrected/updated values

  ( ) FULL REPLACE: Replace entire dataset
      Use when: Major schema change
```

### Backfill Workflow

For building up historical data year-by-year:

```
Example: Building WHO health data

Step 1: Download 2024 -> creates who_health/all_countries.parquet (2024 only)
Step 2: Download 2023 -> APPEND -> now has 2023-2024
Step 3: Download 2022 -> APPEND -> now has 2022-2024
Step 4: Download 2021 -> APPEND -> now has 2021-2024
...

Each append:
1. Load existing parquet
2. Load new year data
3. Concat (or merge on loc_id + year)
4. Sort by loc_id, year
5. Save back to parquet
```

### MVP Import Flow

```
1. Select file
   [world_bank_poverty_2024.csv]

2. Preview columns
   | Country Code | Year | Poverty Rate | Poverty Gap |
   | AFG          | 2024 | 42.1         | 12.8        |

3. Detect/confirm loc_id mapping
   "Country Code" -> loc_id (ISO3, 98% match)
   Unmatched: 2 rows (aggregates)

4. Source decision
   [New folder: world_bank_poverty] or [Add to: owid_co2]

5. Year handling (if adding to existing)
   [Append 2024] or [Replace 2024] or [Full replace]

6. Execute
   -> Output: county-map-data/data/world_bank_poverty/all_countries.parquet
   -> Output: county-map-data/data/world_bank_poverty/metadata.json

Done.
```

---

## Dashboard Pages

### Page 1: System Overview

**What it shows:**
- Total datasets loaded
- Total locations with data (countries, states, counties)
- Coverage matrix: which datasets cover which regions
- Data freshness: when each dataset was last updated
- Gap analysis: regions/topics with no data

**Coverage Matrix Example:**
```
                    | owid_co2 | who_health | imf_bop | census_pop |
--------------------|----------|------------|---------|------------|
Countries (admin_0) |   217    |    198     |   195   |     -      |
US States (admin_1) |    -     |     -      |    -    |     51     |
US Counties (admin_2)|   -     |     -      |    -    |   3,144    |
```

**Gap Analysis Example:**
```
Missing Coverage:
- No health data for US states/counties
- No economic data below country level (except limited census)
- Countries with geometry but no data: 40 (list...)
- Countries with data but no geometry: 3 (list...)
```

**Master Metadata Summary:**
```
Datasets: 6 loaded
- owid_co2: 217 countries, 1750-2024, 79 indicators
- who_health: 198 countries, 2015-2024, 45 indicators
- imf_bop: 195 countries, 2005-2022, 28 indicators
- census_population: 3,144 counties, 2020-2024, 3 indicators
- census_agesex: 3,144 counties, 2019-2024, 12 indicators
- census_demographics: 3,144 counties, 2020-2024, 18 indicators

Total Indicators: 185
Total Data Points: ~12 million
```

---

### Page 2: Dataset Browser

**What it shows:**
- List of all datasets in county-map-data/data/
- For each dataset:
  - Name and description
  - Source and license
  - Geographic coverage (admin level, countries/regions)
  - Temporal coverage (year range)
  - Columns/indicators available
  - Row count and file size
  - Last updated date

**Dataset Detail View:**
```
Dataset: owid_co2
-----------------
Source: Our World in Data
URL: github.com/owid/co2-data
License: CC-BY

Files:
  all_countries.parquet (45 MB, 217 countries, 1750-2024)

Indicators (79):
  - co2: CO2 emissions (million tonnes)
  - co2_per_capita: CO2 per capita (tonnes)
  - gdp: GDP (current USD)
  - population: Population
  - ... (show all with units)

Sample Data:
  loc_id | year | co2    | gdp
  USA    | 2020 | 4713.5 | 20936...
  CHN    | 2020 | 10667  | 14722...

Metadata Status:
  [x] Description
  [x] Source URL
  [x] License
  [x] Column descriptions
  [ ] LLM summary (not set)
  [ ] Topic tags (not set)
```

---

### Page 3: Import Wizard

**Step 1: File Selection**
- Upload file or select from county-map-data/Raw data/
- Supported formats: CSV, Excel, JSON, Parquet
- Auto-detect: encoding, delimiter, has header

**Step 2: Preview & Analysis**
```
File: world_bank_poverty.csv
Encoding: UTF-8
Delimiter: comma
Rows: 45,230
Columns: 8

Preview:
  Country Name  | Country Code | Year | Poverty Rate | ...
  Afghanistan   | AFG          | 2000 | 47.3         | ...
  Afghanistan   | AFG          | 2005 | 42.1         | ...
  Albania       | ALB          | 2000 | 12.4         | ...
```

**Step 3: Column Detection**
```
Column Analysis:

Column          | Detected Type      | Match Rate | Suggested Mapping
----------------|--------------------| -----------|------------------
Country Name    | country_name       | 98%        | -> loc_id (via lookup)
Country Code    | iso3               | 100%       | -> loc_id (direct)
Year            | year               | 100%       | -> year
Poverty Rate    | numeric (%)        | 95%        | -> poverty_rate
Region          | region_group       | 100%       | -> (drop or keep as tag)
Income Group    | aggregate_row      | -          | -> (filter out)

Unmatched Values (Country Name):
  - "Korea, Republic of" (suggest: KOR)
  - "Micronesia, Fed. Sts." (suggest: FSM)
  - "World" (aggregate - exclude)
```

**Step 4: Mapping Configuration**
```
Geographic Mapping:
  Source column: Country Code (iso3)
  Target: loc_id
  Admin level: 0 (country)

Year Mapping:
  Source column: Year
  Target: year

Data Columns to Include:
  [x] Poverty Rate -> poverty_rate
  [x] Poverty Gap -> poverty_gap
  [ ] Region (exclude)
  [ ] Income Group (exclude)

Aggregate Rows to Exclude:
  [x] World
  [x] High income
  [x] Low income
  [x] Sub-Saharan Africa
  (auto-detected from conversions.json)
```

**Step 5: Output Configuration**
```
Output Settings:
  Dataset ID: world_bank_poverty
  Output path: county-map-data/data/world_bank_poverty/
  Format: parquet

  Files to create:
    [x] all_countries.parquet (country-level data)
    [ ] {ISO3}.parquet (per-country files) - not needed for country-level

Metadata:
  Description: World Bank poverty indicators
  Source: World Bank
  Source URL: data.worldbank.org
  License: CC-BY 4.0
  LLM Summary: (auto-generate or manual)
```

**Step 6: Review & Execute**
```
Conversion Summary:
  Input: 45,230 rows
  After filtering aggregates: 42,100 rows
  After mapping: 42,100 rows with valid loc_id
  Unmapped (excluded): 130 rows (3 unknown locations)

Preview Output:
  loc_id | year | poverty_rate | poverty_gap
  AFG    | 2000 | 47.3         | 15.2
  AFG    | 2005 | 42.1         | 12.8
  ALB    | 2000 | 12.4         | 3.1

[Generate Converter Script] [Run Conversion]
```

---

### Page 4: Metadata Editor

**For each dataset, edit:**

```
Dataset: owid_co2
=================

Basic Info:
  Description: [                                          ]
  Source Name: [Our World in Data                         ]
  Source URL:  [https://github.com/owid/co2-data          ]
  License:     [CC-BY 4.0                            v]

LLM Context:
  Summary (sent to chat LLM):
  [This dataset contains CO2 emissions, energy use, GDP, and   ]
  [population data for 217 countries from 1750-2024. Primary   ]
  [indicators include co2, co2_per_capita, gdp, population.    ]

  Priority Terms (boost in search):
  [ ] co2  [ ] emissions  [ ] carbon  [ ] climate
  [ ] gdp  [ ] economy    [ ] energy  [ ] population

Topic Tags:
  [x] environment  [x] climate  [x] economics  [ ] health
  [ ] demographics [ ] trade    [ ] energy     [ ] social

Column Descriptions:
  co2:           [Annual CO2 emissions in million tonnes        ]
  co2_per_capita:[CO2 per capita in tonnes per person           ]
  gdp:           [GDP in current US dollars                     ]
  population:    [Total population                              ]
  ...

Related Datasets:
  [ ] who_health (correlate emissions with health outcomes)
  [ ] imf_bop (correlate with trade data)
```

---

### Page 5: Dataset Builder (Export Tool)

**Build custom datasets from existing data:**

```
Dataset Builder
===============

Step 1: Select Source Datasets
  [x] owid_co2 (217 countries, 1750-2024)
  [x] who_health (198 countries, 2015-2024)
  [ ] imf_bop
  [ ] census_population

Step 2: Select Fields
  From owid_co2:
    [x] co2
    [x] co2_per_capita
    [x] gdp
    [x] population
    [ ] energy_per_capita
    [ ] ...

  From who_health:
    [x] life_expectancy
    [ ] infant_mortality
    [ ] ...

Step 3: Apply Filters
  Geographic:
    [x] Countries only (admin_0)
    Region: [Europe v]
    Exclude: [ ]

  Temporal:
    Years: [2010] to [2020]

  Values:
    GDP > [1000000000] (optional)

Step 4: Preview
  Rows: 440 (28 countries x 11 years, some gaps)
  Columns: loc_id, year, co2, co2_per_capita, gdp, population, life_expectancy

  Preview:
  loc_id | year | co2    | gdp        | life_expectancy
  DEU    | 2010 | 832.4  | 3417...    | 80.5
  FRA    | 2010 | 388.2  | 2642...    | 81.8
  GBR    | 2010 | 524.1  | 2475...    | 80.4
  ...

Step 5: Export
  Format: [CSV v] [Parquet] [JSON]
  Filename: [europe_climate_health_2010-2020]

  [Download]
```

**Note:** This is an export/analysis tool - does NOT modify the main database.

---

### Page 6: Geometry Status

**Shows geometry coverage:**

```
Geometry Files: 258 total
  global.csv: 257 countries
  Per-country parquet files: 257

Countries with Subdivisions:
  USA: 3,244 locations (51 states + 3,143 counties + DC)
  DEU: 438 locations (16 states + 422 districts)
  FRA: 101 locations (18 regions + 83 departments)
  ... (list all with subdivision counts)

Countries without Subdivisions:
  (51 countries - small nations, data not available)

Geometry-Data Alignment:
  Locations in geometry: 416,066
  Locations with data: 3,589
  Coverage: 0.86%

  Missing geometry for data:
    - (none currently)

  Data available by admin level:
    admin_0 (countries): 217 with data
    admin_1 (states): 51 (USA only)
    admin_2 (counties): 3,144 (USA only)
```

---

## Data Structures

### Master Catalog (catalog.json)

```json
{
  "version": "1.0",
  "last_updated": "2025-12-21",

  "datasets": [
    {
      "id": "owid_co2",
      "name": "Our World in Data - CO2 and Energy",
      "description": "CO2 emissions, energy, GDP, population",
      "source": "Our World in Data",
      "source_url": "https://github.com/owid/co2-data",
      "license": "CC-BY 4.0",

      "files": [
        {
          "path": "data/owid_co2/all_countries.parquet",
          "admin_level": 0,
          "row_count": 52000,
          "size_mb": 45
        }
      ],

      "coverage": {
        "admin_levels": [0],
        "countries": 217,
        "year_start": 1750,
        "year_end": 2024
      },

      "indicators": [
        {"name": "co2", "description": "CO2 emissions", "unit": "million tonnes"},
        {"name": "gdp", "description": "GDP", "unit": "current USD"},
        ...
      ],

      "llm_context": {
        "summary": "CO2 emissions and energy data for 217 countries...",
        "priority_terms": ["co2", "emissions", "carbon", "climate"],
        "topic_tags": ["environment", "climate", "economics"]
      },

      "quality": {
        "completeness": 0.85,
        "last_validated": "2025-12-21"
      }
    }
  ],

  "geometry": {
    "total_locations": 416066,
    "countries": 257,
    "countries_with_subdivisions": 206
  },

  "coverage_matrix": {
    "admin_0": {
      "total_countries": 257,
      "countries_with_data": 217,
      "datasets": ["owid_co2", "who_health", "imf_bop"]
    },
    "admin_1": {
      "total_regions": 4500,
      "regions_with_data": 51,
      "datasets": ["census_population", "census_agesex", "census_demographics"]
    },
    "admin_2": {
      "total_districts": 45000,
      "districts_with_data": 3144,
      "datasets": ["census_population", "census_agesex", "census_demographics"]
    }
  }
}
```

### Per-Dataset Metadata (metadata.json)

Each dataset folder has its own metadata.json:

```
county-map-data/data/owid_co2/
  all_countries.parquet
  metadata.json
```

```json
{
  "id": "owid_co2",
  "name": "Our World in Data - CO2 and Energy",
  "description": "Comprehensive CO2 emissions, energy consumption, and related economic indicators",

  "source": {
    "name": "Our World in Data",
    "url": "https://github.com/owid/co2-data",
    "license": "CC-BY 4.0",
    "citation": "Our World in Data (2024)"
  },

  "coverage": {
    "admin_level": 0,
    "geographic": "global",
    "countries": 217,
    "year_start": 1750,
    "year_end": 2024
  },

  "indicators": [
    {
      "column": "co2",
      "name": "CO2 Emissions",
      "description": "Annual production-based CO2 emissions",
      "unit": "million tonnes",
      "aggregation": "sum"
    },
    {
      "column": "co2_per_capita",
      "name": "CO2 per Capita",
      "description": "CO2 emissions per person",
      "unit": "tonnes per person",
      "aggregation": "mean"
    }
  ],

  "llm_context": {
    "summary": "CO2 emissions and energy data covering 217 countries from 1750-2024. Key indicators include total CO2 emissions, per-capita emissions, GDP, population, and energy consumption metrics.",
    "keywords": ["co2", "carbon", "emissions", "climate", "energy", "gdp", "population"],
    "topic_tags": ["environment", "climate", "economics", "energy"]
  },

  "processing": {
    "converter": "data_converters/convert_owid_co2.py",
    "last_run": "2025-12-21",
    "source_file": "Raw data/owid-co2-data.csv"
  }
}
```

---

## Gap Analysis Logic

**What gaps to detect:**

1. **Geographic gaps**: Locations with geometry but no data
2. **Temporal gaps**: Missing years in time series
3. **Topic gaps**: Categories with no datasets (e.g., no education data)
4. **Admin level gaps**: No sub-national data outside USA
5. **Metadata gaps**: Datasets missing descriptions, LLM context, etc.

**Report format:**

```
COVERAGE GAPS REPORT
====================

Geographic Gaps:
  40 countries have geometry but no data in any dataset:
    - Andorra (AND), Liechtenstein (LIE), Monaco (MCO), ...

  3 locations have data but no geometry:
    - Kosovo (XKX) - disputed territory
    - ...

Admin Level Gaps:
  No sub-national data for:
    - Europe (except country-level)
    - Asia (except country-level)
    - Africa (except country-level)

  US coverage only:
    - admin_1 (states): complete
    - admin_2 (counties): complete

Topic Gaps:
  No data for topics:
    - Education (enrollment, literacy)
    - Infrastructure (roads, electricity access)
    - Agriculture (crop yields, land use)

  Limited data for topics:
    - Health: country-level only, no US state/county
    - Economics: country-level only, no US state/county

Metadata Gaps:
  Datasets missing LLM summary:
    - census_population
    - census_agesex

  Datasets missing topic tags:
    - imf_bop
```

---

## Implementation Priority

**Phase 1: Read-Only Dashboard**
1. System Overview page (catalog.json reader)
2. Dataset Browser (metadata.json reader)
3. Geometry Status page

**Phase 2: Metadata Editing**
4. Metadata Editor (edit metadata.json files)
5. LLM context management

**Phase 3: Import Wizard**
6. File analyzer
7. Column detector
8. loc_id mapper
9. Converter generator

**Phase 4: Source Monitoring & Auto-Update**
10. Source registry (URLs, update frequency, last checked)
11. Change detection (check if source has new data)
12. Auto-download pipeline
13. Review queue (pending imports for approval)
14. Scheduled jobs (cron-style triggers)

**Phase 5: Streaming & Live Data**
15. Streaming source connectors
16. Real-time update pipeline
17. Time-series append (vs full refresh)
18. Live data indicators on map

---

## Phase 4: Source Monitoring & Auto-Update

### Source Registry

Track known data sources and their update patterns:

```json
{
  "sources": [
    {
      "id": "census_population_estimates",
      "name": "Census Population Estimates",
      "type": "periodic",
      "url": "https://www2.census.gov/programs-surveys/popest/datasets/",
      "check_frequency": "weekly",
      "expected_release": "yearly",
      "last_checked": "2025-12-21",
      "last_updated": "2024-12-19",
      "converter": "convert_census_population.py",
      "auto_process": false,
      "notify_on_update": true
    },
    {
      "id": "owid_co2",
      "name": "Our World in Data CO2",
      "type": "periodic",
      "url": "https://github.com/owid/co2-data",
      "check_method": "github_release",
      "check_frequency": "daily",
      "last_checked": "2025-12-21",
      "last_updated": "2024-11-15",
      "converter": "convert_owid_co2.py",
      "auto_process": true,
      "notify_on_update": true
    },
    {
      "id": "world_bank_indicators",
      "name": "World Bank Development Indicators",
      "type": "api",
      "url": "https://api.worldbank.org/v2/",
      "check_frequency": "monthly",
      "indicators": ["NY.GDP.MKTP.CD", "SP.POP.TOTL"],
      "auto_process": true
    }
  ]
}
```

### Check Methods

Different sources need different detection methods:

| Method | How It Works | Examples |
|--------|--------------|----------|
| `http_modified` | Check Last-Modified header | Direct file downloads |
| `http_etag` | Check ETag header | API endpoints |
| `github_release` | Check latest release tag | OWID, open data repos |
| `github_commit` | Check latest commit on file | Frequently updated repos |
| `rss_feed` | Parse RSS/Atom feed | Government data portals |
| `page_scrape` | Check page for date strings | Census, BLS |
| `api_version` | Call API version endpoint | REST APIs |

### Update Pipeline

```
Source Monitor
     |
     v
[Check for Updates] ---(no change)---> Sleep until next check
     |
     | (new data detected)
     v
[Download Raw Data]
     |
     v
[Validate Format] ---(invalid)---> Alert + Manual Review
     |
     | (valid)
     v
[Run Converter]
     |
     v
[Compare to Existing] ---(major changes)---> Review Queue
     |
     | (normal update)
     v
[Auto-Deploy to county-map-data/]
     |
     v
[Notify + Log]
```

### Review Queue

For changes that need human approval:

```
Review Queue:
-----------
1. [PENDING] Census 2024 Population Estimates
   Downloaded: 2025-12-21
   Changes: +15 new columns, 3,144 rows updated
   Action: [Approve] [Reject] [Review Details]

2. [PENDING] WHO Health 2024 Update
   Downloaded: 2025-12-20
   Changes: 23 new countries, 2024 data added
   Action: [Approve] [Reject] [Review Details]

3. [AUTO-APPROVED] OWID CO2 Daily Update
   Processed: 2025-12-21
   Changes: 2024 data updated for 45 countries
```

### Scheduler

```python
# Example schedule configuration
schedules:
  - name: "Check Census Sources"
    cron: "0 6 * * 1"  # Every Monday at 6 AM
    sources: ["census_*"]

  - name: "Check OWID Sources"
    cron: "0 8 * * *"  # Every day at 8 AM
    sources: ["owid_*"]

  - name: "Check World Bank API"
    cron: "0 0 1 * *"  # First of each month
    sources: ["world_bank_*"]
```

---

## Phase 5: Streaming & Live Data

### Streaming Source Types

| Type | Update Frequency | Examples |
|------|------------------|----------|
| **Batch refresh** | Daily/Weekly | Census, World Bank |
| **Incremental append** | Hourly/Daily | Stock prices, weather |
| **Near real-time** | Minutes | News feeds, social trends |
| **Real-time stream** | Seconds | Sensor data, live events |

### Streaming Architecture

```
External APIs / Feeds
        |
        v
[Streaming Connector]
        |
        v
[Message Queue] (Redis/Kafka)
        |
        v
[Stream Processor]
        |
        +---> [Time-Series DB] (for historical)
        |
        +---> [Live Cache] (for current values)
        |
        v
[WebSocket to Frontend]
        |
        v
[Map updates in real-time]
```

### Example: Social Media Trends by Country

```json
{
  "source_id": "twitter_trends",
  "type": "streaming",
  "connector": "twitter_bot_api",  // Your separate bot
  "endpoint": "ws://your-bot.com/trends",
  "update_frequency": "5 minutes",

  "data_schema": {
    "loc_id": "country ISO3",
    "timestamp": "ISO datetime",
    "trends": [
      {"rank": 1, "topic": "string", "volume": "int"},
      {"rank": 2, "topic": "string", "volume": "int"},
      {"rank": 3, "topic": "string", "volume": "int"}
    ]
  },

  "storage": {
    "live": "redis",           // Current values only
    "historical": "timescale"  // Full history
  },

  "display": {
    "map_layer": "trends_overlay",
    "refresh": "auto",
    "show_timestamp": true
  }
}
```

### Live Data Indicators

On the map, live data could show:

```
[Country Hover]
-------------------
France
Population: 67.4M (2024)
GDP: $2.9T (2023)

Live Data:
  Twitter Trends (5 min ago):
    1. #Paris2024
    2. #Eurovision
    3. #Macron

  Weather: 18C, Partly Cloudy
  Air Quality Index: 42 (Good)
```

### Data Freshness Indicators

```
Dataset Status:
  owid_co2:        Updated 2 days ago    [Fresh]
  who_health:      Updated 3 months ago  [Stale]
  twitter_trends:  Updated 5 min ago     [Live]
  weather:         Updated 1 hour ago    [Live]
```

---

## Future Considerations

### Scaling
- Multiple worker processes for parallel source checking
- Queue system for processing jobs
- CDN for serving live data to multiple clients

### Reliability
- Retry logic for failed downloads
- Fallback sources for critical data
- Alert system for prolonged source outages

### Data Quality
- Automated validation rules per source
- Anomaly detection (sudden large changes)
- Data lineage tracking (where did this value come from?)

### Cost Management
- API rate limiting
- Caching to reduce redundant calls
- Priority tiers (critical sources checked more often)

---

## Technical Stack

- **Framework**: Streamlit (matches existing admin/app.py)
- **Data**: pandas, pyarrow for parquet
- **Paths**: Read from county-map-data/ (external folder)
- **State**: Session state for wizard flow

---

*Last Updated: 2025-12-21*
