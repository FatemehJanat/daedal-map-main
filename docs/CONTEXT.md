# County Map - Technical Context

Technical index for understanding the system architecture. For a non-technical overview, see [README.md](../README.md).

**Live Demo**: https://county-map.up.railway.app

---

## Documentation Index

| Document | Purpose |
|----------|---------|
| [README.md](../README.md) | Non-technical overview and quick start |
| **CONTEXT.md** (this file) | System architecture and technical index |
| [DATA_PIPELINE.md](DATA_PIPELINE.md) | Data format, converters, dataset catalog |
| [GEOMETRY.md](GEOMETRY.md) | Geometry system, loc_id specification |
| [CHAT.md](CHAT.md) | Chat system, LLM prompting, order model |
| [MAPPING.md](MAPPING.md) | Frontend visualization, MapLibre, choropleth |
| [FRONTEND_MODULES.md](FRONTEND_MODULES.md) | ES6 module structure for mapviewer.js |
| [ADMIN_DASHBOARD.md](ADMIN_DASHBOARD.md) | Admin dashboard design, import wizard |

### Ongoing Implementation Plans

| Document | Status |
|----------|--------|
| [TIME_SLIDER_PLAN.md](TIME_SLIDER_PLAN.md) | Time slider feature spec |
| [WORLD_FACTBOOK_CONVERTER_REFERENCE.md](../data_converters/WORLD_FACTBOOK_CONVERTER_REFERENCE.md) | World Factbook parser reference |

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
+-- RUNTIME (Server) -------------------------------------------
|
|   app.py                       # FastAPI server, /chat endpoint
|   supabase_client.py           # Cloud logging client
|
|   mapmover/                    # Core runtime package
|     __init__.py                # Package exports
|     order_taker.py             # LLM interprets user requests
|     order_executor.py          # Execute orders against parquet
|     response_builder.py        # GeoJSON response building
|     data_loading.py            # Load catalog.json, source metadata
|     data_cascade.py            # Parent/child data lookups
|     geometry_handlers.py       # Geometry endpoints
|     geometry_enrichment.py     # Adding geometry to responses
|     geometry_joining.py        # Auto-join, fuzzy matching
|     name_standardizer.py       # loc_id lookups, name matching
|     constants.py               # State abbrevs, unit multipliers
|     utils.py                   # Normalization, helpers
|     geography.py               # Regions, coordinates
|     logging_analytics.py       # Cloud logging
|     settings.py                # Configuration management
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
|     modules/                   # ES6 modules (see FRONTEND_MODULES.md)
|       app.js                   # Main entry point
|       config.js                # Configuration settings
|       map-adapter.js           # MapLibre interface
|       viewport-loader.js       # Loading strategy
|       (+ 7 more modules)
|
+-- BUILD (Offline Tools) --------------------------------------
|
|   build/                       # Build-time tools (not runtime)
|     geometry/                  # Geometry processing pipeline
|       process_gadm.py          # Main GADM processor
|       aggregate_geometry.py    # Parent boundary creation
|       optimize_geometry.py     # Placeholder removal, bboxes
|       post_process_geometry.py # Full post-processing pipeline
|       build_global_csv.py      # Natural Earth to global.csv
|       rebuild_global_csv.py    # Rebuild from parquets
|     catalog/                   # Catalog generation
|       catalog_builder.py       # Build catalog.json
|       metadata_generator.py    # Generate metadata.json files
|     add_type_column.py         # One-off utility
|     regenerate_metadata.py     # Regenerate metadata files
|
|   data_converters/             # Source-specific converters
|     convert_owid_co2.py        # Our World in Data
|     convert_who_health.py      # WHO health indicators
|     convert_imf_bop.py         # IMF balance of payments
|     convert_census_*.py        # US Census data
|     convert_world_factbook.py  # CIA World Factbook
|
|   admin/                       # Admin dashboard
|     app.py                     # Streamlit UI
|
+-- DOCUMENTATION ----------------------------------------------
|
|   README.md                    # Non-technical overview (root)
|   docs/                        # Technical documentation
|     CONTEXT.md                 # This file - technical index
|     DATA_PIPELINE.md           # Data importing
|     GEOMETRY.md                # Geography system
|     CHAT.md                    # Chat system
|     MAPPING.md                 # Frontend visualization
|     ADMIN_DASHBOARD.md         # Admin tools
|     TIME_SLIDER_PLAN.md        # Time slider feature spec


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
| `python build/geometry/process_gadm.py` | Rebuild geometry files |
| `python build/catalog/catalog_builder.py` | Rebuild catalog.json |
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

### mapmover/ Package (Runtime)

| Module | Purpose |
|--------|---------|
| `order_taker.py` | LLM interprets user requests |
| `order_executor.py` | Execute orders against parquet |
| `response_builder.py` | GeoJSON response construction |
| `data_loading.py` | Load data from county-map-data |
| `data_cascade.py` | Parent/child data lookups |
| `geometry_handlers.py` | Geometry endpoints |
| `geometry_enrichment.py` | Adding geometry to responses |
| `geometry_joining.py` | Auto-join, fuzzy matching |
| `name_standardizer.py` | loc_id lookups, name matching |
| `constants.py` | State abbreviations, unit multipliers |
| `utils.py` | Normalization, helpers |
| `geography.py` | Regions, coordinates |
| `logging_analytics.py` | Cloud logging |
| `settings.py` | Configuration management |

### build/ Package (Offline Tools)

| Module | Purpose |
|--------|---------|
| `geometry/process_gadm.py` | Main GADM geometry processor |
| `geometry/aggregate_geometry.py` | Parent boundary creation |
| `geometry/optimize_geometry.py` | Placeholder removal, bboxes |
| `geometry/post_process_geometry.py` | Full post-processing pipeline |
| `geometry/build_global_csv.py` | Natural Earth to global.csv |
| `geometry/rebuild_global_csv.py` | Rebuild from parquets |
| `catalog/catalog_builder.py` | Build catalog.json |
| `catalog/metadata_generator.py` | Generate metadata.json files |

---

## Design Principles

| Principle | Reasoning |
|-----------|-----------|
| Keep user requests lightweight | Avoid memory issues, fast responses |
| Pre-compute where possible | Heat maps, metadata at ETL time |
| Admin tools are separate | Heavy lifting offline, not during user sessions |
| Database is read-optimized | Exports are copies, never restructure source |
| LLM controls conversation | No keyword shortcuts, full conversational flow |
| Geometry is canonical | All data matches geometry dataset names |
| Log gaps for improvement | Missing data/geometry tracked in Supabase |

---

## Technical Debt

Outstanding items to address:

- Add unit tests for LLM parsing

---

## Future: Offline Operation

Run the entire system without internet connectivity.

**Local Map Tiles (PMTiles):**
- Download PMTiles basemap file (z0-10 = ~1-5GB, z0-15 = ~120GB)
- Configure MapLibre to use local PMTiles protocol
- Serve tiles as static asset (no tile server needed)
- Latency improvement: 50-200ms/tile -> 1-10ms/tile

**Local LLM (Ollama):**
- Install Ollama with Llama 3.1 8B or Mistral 7B
- Update chat_handlers.py to call local endpoint
- Tune prompts for smaller model capabilities
- Latency improvement: 500-2000ms -> 100-500ms

**Benefits:**
- Zero API costs
- Works without internet
- Noticeably snappier UI (pan/zoom instant, faster chat)
- Privacy - no data leaves the machine

**Trade-offs:**
- Disk space (tiles + model weights)
- Hardware requirements for local LLM
- Smaller models less reliable at structured JSON output

---

## Future: Railway Deployment Testing

Production testing on Railway platform:

- Memory profiling with concurrent users
- Response time benchmarking
- Error rate monitoring via Supabase logs
- Large dataset loading performance

---

*Last Updated: 2026-01-01*
