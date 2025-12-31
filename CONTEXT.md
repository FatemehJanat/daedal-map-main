# County Map - System Context

Navigation index for understanding the system. This document describes where to find information about each component.

**Live Demo**: https://county-map.up.railway.app

---

## Documentation Index

| Document | Purpose |
|----------|---------|
| [README.md](README.md) | Project overview, quick start, examples |
| **CONTEXT.md** (this file) | System index and navigation |
| [DEVELOPER.md](DEVELOPER.md) | Technical docs, module reference, debugging |
| [GEOMETRY.md](GEOMETRY.md) | Geometry system, loc_id specification, process_gadm.py |
| [DATA_PIPELINE.md](DATA_PIPELINE.md) | Data format, converters, dataset catalog |
| [ADMIN_DASHBOARD.md](ADMIN_DASHBOARD.md) | Admin dashboard design, import wizard, metadata |
| [CHAT_REDESIGN.md](CHAT_REDESIGN.md) | Fast food kiosk model for chat UI |
| [geographic_data_reference.md](geographic_data_reference.md) | Data sources, geometry sources, free vs paid |
| [ROADMAP.md](ROADMAP.md) | Future features and plans |

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
|  | Dual LLM System  |                |                                       |
|  | (chat_handlers)  |                |                                       |
|  | (llm.py)         |                |                                       |
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
|  +----------------------+                                                    |
|  | Admin Dashboard      |     STATUS: Needs rebuild                          |
|  | (admin/app.py)       |     - CSV import wizard                            |
|  |                      |     - Metadata editor                              |
|  | Streamlit UI for     |     - Data quality tools                           |
|  | data preparation     |     - Backup management                            |
|  +----------------------+                                                    |
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
|     order_taker.py             # LLM interprets user requests
|     order_executor.py          # Execute orders against parquet
|     conversions.json           # Country codes, regional groupings (lean)
|
|     reference/                 # Modular reference data (see Reference Architecture below)
|       admin_levels.json        # Country-specific admin level names + synonyms
|       country_metadata.json    # Capitals, currencies, timezones
|       geographic_features.json # Mountains, rivers, islands (structure only)
|       iso_codes.json           # ISO 3166-1 country codes (alpha-2/alpha-3)
|       languages.json           # Language codes, country languages
|       query_synonyms.json      # LLM query interpretation helpers
|       usa_admin.json           # US state abbreviations, FIPS codes
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
|     convert_census_population.py
|     convert_census_agesex.py
|     convert_census_demographics.py
|
|   mapmover/process_gadm.py     # Geometry builder (TODO: move)
|
|   admin/                       # Admin dashboard (BROKEN)
|     app.py                     # Streamlit UI - needs rebuild
|
+-- CONFIG & DOCS -----------------------------------------------
|
|   config/                      # App configuration
|   .env                         # API keys (not in git)
|   requirements.txt             # Python dependencies
|   CONTEXT.md                   # This file
|   DEVELOPER.md                 # Technical documentation
|   LOC_ID_SPECIFICATION.md      # loc_id format spec
|   DATA_CATALOG.md              # Dataset documentation
|   data conversion.md           # Converter documentation
|   ROADMAP.md                   # Future plans


county-map-data/                 # External data folder (THE CONTRACT)
|
|   catalog.json                 # Unified catalog of all sources (for LLM)
|
|   Raw data/                    # Original source files
|     gadm36.gpkg                # GADM geometry source (1.9GB)
|     (census CSVs, OWID CSVs, etc. go here for processing)
|
|   geometry/                    # OUTPUT: Location geometries
|     global.csv                 # All countries (admin_0)
|     {ISO3}.parquet             # Per-country subdivisions (257 files)
|
|   data/                        # OUTPUT: Indicator data by source
|     owid_co2/
|       all_countries.parquet    # Country-level data
|       metadata.json            # Source metadata
|     who_health/
|       all_countries.parquet
|       metadata.json
|     un_sdg_01/ ... un_sdg_17/  # UN SDG indicators (17 goals)
|     census_population/
|       USA.parquet              # US-only data
|       metadata.json
|     (etc.)
```

---

## Runtime vs Build Separation

### Runtime (Frontend)

**Purpose**: Display data on the globe, handle chat queries

**Entry point**: `python app.py` (port 7000)

**Key files**:
- [app.py](app.py) - FastAPI server
- [mapmover/](mapmover/) - All runtime logic
- [templates/index.html](templates/index.html) - Web UI
- [static/mapviewer.js](static/mapviewer.js) - Map rendering

**Data flow**:
1. User sends chat message
2. LLM determines intent (QUERY/MODIFY/CHAT/META)
3. Load data from `county-map-data/data/`
4. Enrich with geometry from `county-map-data/geometry/`
5. Return GeoJSON to map

**Reads from**: `county-map-data/` (never writes)

---

### Build (Backend)

**Purpose**: Process raw data into the format runtime expects

**Entry points**:
- `python data_converters/convert_*.py` - Individual converters
- `python mapmover/process_gadm.py` - Geometry builder
- `streamlit run admin/app.py` - Admin dashboard (broken)

**Key files**:
- [data_converters/](data_converters/) - 6 working converters
- [mapmover/process_gadm.py](mapmover/process_gadm.py) - Geometry builder
- [admin/app.py](admin/app.py) - Dashboard (needs rebuild)

**Data flow**:
1. Put raw files in `county-map-data/Raw data/`
2. Run converter or geometry builder
3. Output goes to `county-map-data/geometry/` or `county-map-data/data/`

**Writes to**: `county-map-data/` (the shared contract)

---

## Build Tools Status

| Tool | Location | Status | Purpose |
|------|----------|--------|---------|
| process_gadm.py | mapmover/ | Working | Build geometry from GADM gpkg |
| post_process_geometry.py | mapmover/ | Working | Aggregate geometry, bboxes, children counts |
| convert_owid_co2.py | data_converters/ | Working | OWID emissions data |
| convert_who_health.py | data_converters/ | Working | WHO health indicators |
| convert_imf_bop.py | data_converters/ | Working | IMF trade data |
| convert_census_*.py | data_converters/ | Working | US Census data (3 files) |
| admin/app.py | admin/ | Broken | Data prep dashboard |

### Import Workflow

```
1. process_gadm.py           # Import raw geometry from GADM
2. post_process_geometry.py  # Aggregate, compute bboxes + children counts
3. convert_*.py              # Import indicator data
4. build_catalog.py          # Update catalog.json
```

**TODO**:
- Move `process_gadm.py` out of `mapmover/` to build folder
- Consolidate shared utilities (STATE_FIPS, fips_to_loc_id)
- Rebuild admin dashboard with correct paths

---

## Order Taker System (Phase 1B)

The chat system uses a "fast food kiosk" model - one LLM interprets requests and executes them.

### Order Taker LLM
- **Purpose**: Interpret user request, select source, build query
- **Location**: [mapmover/order_taker.py](mapmover/order_taker.py)
- **Model**: gpt-4o-mini
- **Input**: User message + catalog.json (source summaries)
- **Output**: Order JSON with source_id, metric, region, year

### Order Executor
- **Purpose**: Execute order against parquet files, return GeoJSON
- **Location**: [mapmover/order_executor.py](mapmover/order_executor.py)
- **No LLM**: Direct data operations only
- **Output**: GeoJSON FeatureCollection with data properties

---

## Key Concepts

### Location IDs (loc_id)
Canonical identifier for all locations. See [GEOMETRY.md](GEOMETRY.md).
- Countries: ISO3 code (e.g., `USA`, `DEU`, `FRA`)
- US states: `USA-{abbrev}` (e.g., `USA-CA`)
- US counties: `USA-{abbrev}-{fips}` (e.g., `USA-CA-6037`)
- International subdivisions: `{ISO3}-{code}` (e.g., `DEU-BY`)

### Geometry System
416,066 locations across 257 countries stored in parquet files.
- Source of truth for loc_ids
- Global countries: `county-map-data/geometry/global.csv`
- Per-country subdivisions: `county-map-data/geometry/{ISO3}.parquet`

### Indicator Data
Time-series data organized by source in parquet format. See [DATA_PIPELINE.md](DATA_PIPELINE.md).
- Each source folder: `county-map-data/data/{source_id}/`
- Long format: `loc_id | year | metric1 | metric2 | ...`
- Metadata: `metadata.json` per source (used by LLM)

### Regional Groupings
Defined in [mapmover/conversions.json](mapmover/conversions.json). Supports:
- Continents: Europe, Africa, Americas, Asia, Oceania
- Political groups: EU, G7, G20, NATO, ASEAN, BRICS
- Sub-regions: Nordic, Baltic, Caribbean, Gulf, Maghreb

---

## Reference Data Architecture

Geographic reference data is split into modular JSON files under `mapmover/reference/` for maintainability and selective loading.

### File Structure

| File | Purpose | Status |
|------|---------|--------|
| [admin_levels.json](mapmover/reference/admin_levels.json) | Country-specific admin level names (states, provinces, counties, etc.) with synonyms | Complete - 40+ countries |
| [country_metadata.json](mapmover/reference/country_metadata.json) | Capitals, currencies, timezones per country | Capitals complete, currencies/timezones TODO |
| [geographic_features.json](mapmover/reference/geographic_features.json) | Mountains, rivers, lakes, deserts, islands | Structure only - TODO from Natural Earth |
| [iso_codes.json](mapmover/reference/iso_codes.json) | ISO 3166-1 alpha-2/alpha-3 country codes and name mappings | Complete - 200 countries |
| [languages.json](mapmover/reference/languages.json) | ISO 639-1 language codes, country languages | Structure + codes - TODO country mappings |
| [query_synonyms.json](mapmover/reference/query_synonyms.json) | LLM query interpretation helpers (metric, time, comparison synonyms) | Basic set - expand from user logs |
| [usa_admin.json](mapmover/reference/usa_admin.json) | US state abbreviations to names | Complete - TODO add FIPS codes |

### Design Principles

1. **Lean conversions.json** - Core lookups only (ISO codes, regional groupings, aliases)
2. **Modular loading** - Only load reference files when needed
3. **Schema versioning** - Each file has `_schema_version` for evolution
4. **TODO markers** - Clear notes on what needs official source data
5. **LLM-friendly** - Reference files can be included in prompts for context

### What Stays in conversions.json

- `regional_groupings` - G20, EU, BRICS, WHO regions, income groups, etc.
- `region_aliases` - "Europe" -> "WHO_European_Region"
- `limited_geometry_countries` - Fallback coordinates for tiny nations

### Usage

Reference files are loaded on-demand by the modules that need them:
- `admin_levels.json` - Popup display, chat interpretation
- `country_metadata.json` - Popup enrichment, validation
- `iso_codes.json` - Country code lookups, name resolution
- `query_synonyms.json` - LLM prompt context

---

## Quick Reference

| Command | Purpose |
|---------|---------|
| `python app.py` | Start runtime server (port 7000) |
| `python -m uvicorn app:app --reload` | Start with hot reload |
| `python data_converters/convert_owid_co2.py` | Run OWID converter |
| `python mapmover/process_gadm.py` | Rebuild geometry files |

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

**Total**: 23 data sources in catalog.json

---

*Last Updated: 2025-12-30*
