# County Map - Technical Context

Technical index for understanding the system architecture. For a non-technical overview, see [README.md](README.md).

**Live Demo**: https://county-map.up.railway.app

---

## Documentation Index

| Document | Purpose |
|----------|---------|
| [README.md](README.md) | Non-technical overview and quick start |
| **CONTEXT.md** (this file) | System architecture and technical index |
| [DATA_PIPELINE.md](DATA_PIPELINE.md) | Data format, converters, dataset catalog |
| [GEOMETRY.md](GEOMETRY.md) | Geometry system, loc_id specification |
| [CHAT.md](CHAT.md) | Chat system, LLM prompting, order model |
| [MAPPING.md](MAPPING.md) | Frontend visualization, MapLibre, choropleth |
| [ADMIN_DASHBOARD.md](ADMIN_DASHBOARD.md) | Admin dashboard design, import wizard |
| [ROADMAP.md](ROADMAP.md) | Future features and plans |
| [geographic_data_reference.md](geographic_data_reference.md) | Data sources, geometry sources, reference notes |

### Ongoing Implementation Plans

| Document | Status |
|----------|--------|
| [TIME_SLIDER_PLAN.md](TIME_SLIDER_PLAN.md) | Time slider feature spec |
| [data_converters/CIA_FACTBOOK_NOTES.md](data_converters/CIA_FACTBOOK_NOTES.md) | CIA Factbook import notes |

---

## System Architecture

The system is split into two distinct sides with a shared data folder as the contract between them.

```
+==============================================================================+
|                              RUNTIME (Frontend)                              |
|                         Reads data, displays on globe                        |
+==============================================================================+
|                                                                              |
|  +------------------+     +---------------------+                            |
|  |   Chat Sidebar   |     |   MapLibre GL Map   |                            |
|  |   (index.html)   |     |   (mapviewer.js)    |                            |
|  +--------+---------+     +----------+----------+                            |
|           |                          |                                       |
|           v                          |                                       |
|  +------------------+                |                                       |
|  |  /chat endpoint  |                |                                       |
|  |  (app.py)        |                |                                       |
|  +--------+---------+                |                                       |
|           |                          |                                       |
|           v                          |                                       |
|  +------------------+                |                                       |
|  | Order Taker LLM  |                |                                       |
|  | (order_taker.py) |                |                                       |
|  +--------+---------+                |                                       |
|           |                          v                                       |
|           |              +---------------------+                             |
|           +------------->|  GeoJSON Response   |                             |
|                          |  (features + props) |                             |
|                          +---------------------+                             |
|                                     |                                        |
+==============================================================================+
                                      |
                                      | READS FROM
                                      v
+==============================================================================+
|                         county-map-data/ (SHARED)                            |
|                      The contract between both sides                         |
+==============================================================================+
|                                                                              |
|    catalog.json     Raw data/       geometry/           data/                |
|    +------------+   +-----------+   +-------------+     +----------------+   |
|    | 23 sources |   | gadm.gpkg |   | global.csv  |     | owid_co2/      |   |
|    | for LLM    |   | census/   |   | USA.parquet |     | who_health/    |   |
|    +------------+   | owid/     |   | DEU.parquet |     | un_sdg_01-17/  |   |
|                     +-----------+   | ...257 more |     | census_*/      |   |
|                                     +-------------+     +----------------+   |
|                                                                              |
+==============================================================================+
                                      ^
                                      | WRITES TO
                                      |
+==============================================================================+
|                               BUILD (Backend)                                |
|                  Processes raw data, creates parquet files                   |
+==============================================================================+
|                                                                              |
|  +----------------------+     +----------------------+                       |
|  | Geometry Builder     |     | Data Converters      |                       |
|  | (process_gadm.py)    |     | (data_converters/)   |                       |
|  |                      |     |                      |                       |
|  | Input: GADM gpkg     |     | Input: Raw CSVs      |                       |
|  | Output: geometry/    |     | Output: data/        |                       |
|  +----------------------+     +----------------------+                       |
|                                                                              |
+==============================================================================+
```

---

## Project Structure

```
county-map/                      # Main repository
|
+-- RUNTIME (Frontend) ------------------------------------------
|
|   app.py                       # FastAPI server, /chat endpoint
|   supabase_client.py           # Cloud logging client
|
|   mapmover/                    # Core runtime package
|     __init__.py                # Package exports
|     chat_handlers.py           # Chat endpoint logic
|     llm.py                     # LLM init, prompts, parsing
|     order_taker.py             # LLM interprets user requests
|     order_executor.py          # Execute orders against parquet
|     response_builder.py        # GeoJSON response building
|     map_state.py               # Session state management
|     data_loading.py            # Load catalog.json, source metadata
|     data_cascade.py            # Parent/child data lookups
|     geometry_handlers.py       # Geometry endpoints
|     geometry_enrichment.py     # Adding geometry to responses
|     geometry_joining.py        # Auto-join, fuzzy matching
|     meta_queries.py            # "What data?" queries
|     name_standardizer.py       # loc_id lookups, name matching
|     constants.py               # State abbrevs, unit multipliers
|     utils.py                   # Normalization, helpers
|     geography.py               # Regions, coordinates
|     logging_analytics.py       # Cloud logging
|     conversions.json           # Country codes, regional groupings
|
|     reference/                 # Modular reference data
|       admin_levels.json        # Country-specific admin level names
|       country_metadata.json    # Capitals, currencies, timezones
|       iso_codes.json           # ISO 3166-1 country codes
|       usa_admin.json           # US state abbreviations
|
|   templates/                   # Frontend HTML
|     index.html                 # Main page with chat + map
|
|   static/                      # JS, CSS assets
|     mapviewer.js               # MapLibre GL map logic
|     styles.css                 # UI styles
|
+-- BUILD (Backend) ---------------------------------------------
|
|   data_converters/             # Source-specific converters
|     convert_owid_co2.py        # Our World in Data
|     convert_who_health.py      # WHO health indicators
|     convert_imf_bop.py         # IMF balance of payments
|     convert_census_*.py        # US Census data
|
|   mapmover/process_gadm.py     # Geometry builder
|   mapmover/post_process_geometry.py  # Aggregate, bboxes, children
|
|   admin/                       # Admin dashboard
|     app.py                     # Streamlit UI
|
+-- DOCUMENTATION -----------------------------------------------
|
|   README.md                    # Non-technical overview
|   CONTEXT.md                   # This file - technical index
|   DATA_PIPELINE.md             # Data importing
|   GEOMETRY.md                  # Geography system
|   CHAT.md                      # Chat system
|   MAPPING.md                   # Frontend visualization
|   ADMIN_DASHBOARD.md           # Admin tools
|   ROADMAP.md                   # Future plans


county-map-data/                 # External data folder (THE CONTRACT)
|
|   catalog.json                 # Unified catalog of all sources
|
|   Raw data/                    # Original source files
|     gadm_410.gpkg              # GADM geometry source (2GB)
|
|   geometry/                    # OUTPUT: Location geometries
|     global.csv                 # All countries (admin_0)
|     {ISO3}.parquet             # Per-country subdivisions (257 files)
|
|   data/                        # OUTPUT: Indicator data by source
|     owid_co2/
|       all_countries.parquet
|       metadata.json
|     who_health/
|       all_countries.parquet
|       metadata.json
|     un_sdg_01/ ... un_sdg_17/
|     census_population/
|       USA.parquet
|       metadata.json
```

---

## Key Concepts

### Location IDs (loc_id)

Canonical identifier for all locations. See [GEOMETRY.md](GEOMETRY.md).

| Level | Format | Example |
|-------|--------|---------|
| Country | ISO3 | `USA`, `DEU`, `FRA` |
| US State | `USA-{abbrev}` | `USA-CA` |
| US County | `USA-{abbrev}-{fips}` | `USA-CA-6037` |
| International | `{ISO3}-{code}` | `DEU-BY` |

### Order Taker System

The chat uses a "fast food kiosk" model. See [CHAT.md](CHAT.md).

1. Order Taker LLM interprets user requests
2. Builds structured order (source, metric, region, year)
3. User confirms via Order Panel
4. Order Executor fills data from parquet files
5. Returns GeoJSON to map

### Data Pipeline

All data uses long format parquet. See [DATA_PIPELINE.md](DATA_PIPELINE.md).

```
loc_id | year | metric1 | metric2
USA    | 2020 | 5000    | 15.2
USA    | 2021 | 4800    | 14.5
```

### Geometry System

416,066 locations across 257 countries. See [GEOMETRY.md](GEOMETRY.md).

- Global countries: `geometry/global.csv`
- Per-country subdivisions: `geometry/{ISO3}.parquet`

---

## Quick Commands

| Command | Purpose |
|---------|---------|
| `python app.py` | Start runtime server (port 7000) |
| `python -m uvicorn app:app --reload` | Start with hot reload |
| `python data_converters/convert_owid_co2.py` | Run OWID converter |
| `python mapmover/process_gadm.py` | Rebuild geometry files |
| `streamlit run admin/app.py` | Admin dashboard |

---

## Data Sources Summary

| Source | Coverage | Years | Metrics |
|--------|----------|-------|---------|
| owid_co2 | 217 countries | 1750-2024 | CO2, GDP, population, energy |
| who_health | 198 countries | 2015-2024 | Life expectancy, mortality |
| imf_bop | 195 countries | 2005-2022 | Trade balance, investments |
| un_sdg_01-17 | 200+ countries | 2000-2023 | UN Sustainable Development Goals |
| census_population | 3,144 US counties | 2020-2024 | Population by sex |
| census_agesex | 3,144 US counties | 2019-2024 | Age brackets, median age |
| census_demographics | 3,144 US counties | 2020-2024 | Race/ethnicity by sex |

**Total**: 23+ data sources in catalog.json

---

## Environment Setup

### Prerequisites
- Python 3.12+
- OpenAI API key

### Environment Variables

```bash
# Required
OPENAI_API_KEY=your-key-here

# Optional: Cloud logging
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-key
```

### Installation

```bash
git clone https://github.com/xyver/county-map.git
cd county-map
pip install -r requirements.txt
python app.py
```

---

## Module Reference

### mapmover/ Package

| Module | Purpose |
|--------|---------|
| `chat_handlers.py` | Chat endpoint logic |
| `llm.py` | LLM initialization, prompts, parsing |
| `order_taker.py` | LLM interprets user requests |
| `order_executor.py` | Execute orders against parquet |
| `response_builder.py` | GeoJSON response construction |
| `map_state.py` | Session state management |
| `data_loading.py` | Load data from county-map-data |
| `data_cascade.py` | Parent/child data lookups |
| `geometry_handlers.py` | Geometry endpoints |
| `geometry_enrichment.py` | Adding geometry to responses |
| `geometry_joining.py` | Auto-join, fuzzy matching |
| `meta_queries.py` | "What data?" queries |
| `name_standardizer.py` | loc_id lookups, name matching |
| `constants.py` | State abbreviations, unit multipliers |
| `utils.py` | Normalization, helpers |
| `geography.py` | Regions, coordinates |
| `logging_analytics.py` | Cloud logging |
| `process_gadm.py` | Geometry builder (build tool) |

---

*Last Updated: 2025-12-31*
