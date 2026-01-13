# County Map - Technical Context

Technical index for understanding the system architecture. For a non-technical overview, see [README.md](../README.md).

**Live Demo**: https://county-map.up.railway.app

---

## Documentation Index

| Document | Purpose |
|----------|---------|
| [README.md](../README.md) | Non-technical overview and quick start |
| **CONTEXT.md** (this file) | System architecture and technical index |
| [data_import.md](data_import.md) | Adding new data sources (start here for new data) |
| [data_pipeline.md](data_pipeline.md) | Data format, converters, folder structure |
| [GEOMETRY.md](GEOMETRY.md) | Geometry system, loc_id specification |
| [CHAT.md](CHAT.md) | Chat system, LLM prompting, order model |
| [MAPPING.md](MAPPING.md) | Frontend visualization, MapLibre, choropleth |
| [DISASTER_DISPLAY.md](DISASTER_DISPLAY.md) | Disaster schemas, display models, animation system |
| [FRONTEND_MODULES.md](FRONTEND_MODULES.md) | ES6 module structure |
| [ADMIN_DASHBOARD.md](ADMIN_DASHBOARD.md) | Admin dashboard design, import wizard |

### Planning Documents

| Document | Purpose |
|----------|---------|
| [chat_refactor.md](chat_refactor.md) | Future: Candidate-based preprocessor architecture |
| [TIME_SLIDER_PLAN.md](TIME_SLIDER_PLAN.md) | Time slider feature spec |

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
|    catalog.json     Raw data/       global/             countries/           |
|    +------------+   +-----------+   +-------------+     +----------------+   |
|    | 40+sources |   | gadm.gpkg |   | geometry.csv|     | USA/           |   |
|    | for LLM    |   | census/   |   | owid_co2/   |     |   geometry.prq |   |
|    +------------+   | owid/     |   | who_health/ |     |   census_*/    |   |
|                     +-----------+   | un_sdg/     |     | AUS/, CAN/,... |   |
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
|     preprocessor.py            # Query preprocessing, intent detection
|     order_taker.py             # LLM interprets user requests
|     postprocessor.py           # Order validation, metric expansion
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
|       time-slider.js           # Time series playback
|       choropleth.js            # Color scaling
|       chat-panel.js            # Chat UI
|       event-animator.js        # Disaster event animation
|       track-animator.js        # Hurricane track animation
|       overlay-controller.js    # Disaster overlay data loading
|       overlay-selector.js      # Disaster toggle UI
|       models/                  # Disaster display models
|         model-point-radius.js  # Earthquakes, volcanoes, tornadoes
|         model-track.js         # Hurricane tracks
|         model-polygon.js       # Wildfires, floods
|         model-registry.js      # Routes events to models
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
|       source_registry.py       # Central source metadata registry
|     regenerate_metadata.py     # Regenerate metadata files
|
|   data_converters/             # Source-specific converters
|     convert_owid_co2.py        # Our World in Data
|     convert_who_health.py      # WHO health indicators
|     convert_census_*.py        # US Census data
|     convert_abs_population.py  # Australian Bureau of Statistics
|     convert_*_earthquakes.py   # USGS/NRCAN earthquakes
|     (+ 20 more converters)
|
|   admin/                       # Admin dashboard
|     app.py                     # Streamlit UI
|
+-- DOCUMENTATION ----------------------------------------------
|
|   README.md                    # Non-technical overview (root)
|   docs/                        # Technical documentation
|     CONTEXT.md                 # This file - technical index
|     data_import.md             # Adding new data (quick start)
|     data_pipeline.md           # Data format, folder structure
|     GEOMETRY.md                # Geography system
|     CHAT.md                    # Chat system
|     MAPPING.md                 # Frontend visualization


county-map-data/                 # External data folder (THE CONTRACT)
|
|   catalog.json                 # Unified catalog of all sources
|   index.json                   # Router - which countries have data
|
|   Raw data/                    # Original source files
|     gadm_410.gpkg              # GADM geometry source (2GB)
|
|   global/                      # Multi-country datasets (admin_0)
|     geometry.csv               # 252 country outlines
|     owid_co2/                  # Our World in Data - CO2
|     who_health/                # WHO health indicators
|     un_sdg/01-17/              # UN SDG indicators
|     eurostat/                  # European regional statistics
|     world_factbook/            # CIA World Factbook
|
|   countries/                   # Country-specific datasets
|     USA/
|       index.json               # What's available in USA
|       geometry.parquet         # US counties (3,144)
|       census_population/       # Census population data
|       fema_nri/                # FEMA risk indices
|       hurricanes/              # Hurricane tracks
|     AUS/
|       geometry.parquet         # Australian LGAs (547)
|       abs_population/          # ABS demographics
|     CAN/
|       geometry.parquet         # Canadian divisions (5,875)
|       nrcan_earthquakes/       # Canadian earthquakes
|     (+ 37 European countries with Eurostat data)
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

All data uses long format parquet. See [data_pipeline.md](data_pipeline.md).

```
loc_id | year | metric1 | metric2
USA    | 2020 | 5000    | 15.2
USA    | 2021 | 4800    | 14.5
```

### Geometry System

416,066 locations across 257 countries. See [GEOMETRY.md](GEOMETRY.md).

- Global countries: `global/geometry.csv`
- Per-country subdivisions: `countries/{ISO3}/geometry.parquet`

### Disaster Display System

Global disaster events with time-based animation. See [DISASTER_DISPLAY.md](DISASTER_DISPLAY.md).

**Disaster Types:** Earthquakes, Tropical Storms, Tsunamis, Volcanoes, Wildfires, Tornadoes, Floods

**Display Models:**
- Point + Radius: Earthquakes, volcanoes, tornadoes (magnitude-based circles)
- Track/Trail: Hurricanes (progressive line drawing)
- Radial: Tsunamis (expanding wave from source)
- Polygon: Wildfires, floods (area boundaries over time)

**Key Files:**
- Converters: [data_converters/](../data_converters/) (convert_global_earthquakes.py, convert_ibtracs.py, etc.)
- Display models: [static/modules/models/](../static/modules/models/) (model-point-radius.js, model-track.js)
- Animation: [static/modules/event-animator.js](../static/modules/event-animator.js), [static/modules/track-animator.js](../static/modules/track-animator.js)
- API endpoints: [app.py](../app.py) (/api/earthquakes/geojson, /api/storms/geojson, etc.)

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

### Global Sources (multi-country)

| Source | Coverage | Years | Category |
|--------|----------|-------|----------|
| owid_co2 | 217 countries | 1750-2024 | Environment |
| who_health | 198 countries | 2015-2024 | Health |
| imf_bop | 195 countries | 2005-2022 | Economy |
| un_sdg_01-17 | 200+ countries | 2000-2023 | UN SDGs |
| world_factbook | 250+ countries | 2007-2008 | Reference |
| eurostat | 37 European | 2000-2024 | Demographics/Economy |

### Global Disaster Sources

| Source | Data Path | Events | Years |
|--------|-----------|--------|-------|
| USGS Earthquakes | global/usgs_earthquakes/ | 1M+ | 1900-present |
| NOAA IBTrACS | global/tropical_storms/ | 13K storms | 1842-present |
| NOAA Tsunamis | global/tsunamis/ | 2.6K events | 2100 BC-present |
| Smithsonian Volcanoes | global/smithsonian_volcanoes/ | 11K eruptions | Holocene |
| Global Fire Atlas | global/wildfires/ | 13.3M fires | 2002-2024 |
| NOAA Storm Events | countries/USA/noaa_storms/ | 79K tornadoes | 1950-present |

See [DISASTER_DISPLAY.md](DISASTER_DISPLAY.md) for complete schemas and display models.

### Country-Specific Sources

| Country | Sources | Examples |
|---------|---------|----------|
| USA | 15+ | Census, FEMA, NOAA storms, hurricanes, earthquakes, wildfires |
| Australia | 2 | ABS population, BOM cyclones |
| Canada | 1 | NRCAN earthquakes |

**Total**: 40+ data sources across global and country-specific datasets

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
| `preprocessor.py` | Query preprocessing, intent/location/source detection |
| `order_taker.py` | LLM interprets user requests |
| `postprocessor.py` | Order validation, derived metric expansion |
| `order_executor.py` | Execute orders against parquet files |
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
| `catalog/source_registry.py` | Central source metadata (URLs, licenses) |
| `regenerate_metadata.py` | Regenerate all metadata files |

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

*Last Updated: 2026-01-12*
