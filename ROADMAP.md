# County Map - Roadmap

Future development plans and feature ideas.

---

## Current Status (v1.0)

### Completed Features

- [x] CSV self-discovery and catalog system
- [x] Two-stage LLM architecture (conversation + database)
- [x] Conversational chat interface with sidebar
- [x] Natural language query parsing
- [x] MODIFY intent for incremental updates (add field, change year, change region)
- [x] Temporal data support (year filtering, ranges)
- [x] Smart year selection (data completeness + recency)
- [x] Unit conversion system
- [x] Auto-join geometry from separate datasets
- [x] Cesium 3D globe visualization (Leaflet archived)
- [x] Multiple data sources in popups
- [x] Region/continent filtering (Europe, EU, G7, etc.) via conversions.json
- [x] String filters with exclusions ("Europe excluding Germany")
- [x] Aggregate row removal in data pipeline (World, Africa, etc.)
- [x] ETL pipeline with quality analysis
- [x] Shared helper functions (clean_nans, apply_unit_multiplier)
- [x] Coordinate lookup from Countries.csv (no hardcoded coords)
- [x] LLM-controlled conversation flow (no keyword shortcuts)
- [x] Supabase cloud logging (sessions, errors, data quality issues)
- [x] Geometry consolidation (standard 6-column format)
- [x] Multi-level geographic support (country, state, county)

---

## High Priority

### Railway Deployment Testing

Production testing on Railway platform:

- [ ] Memory profiling with concurrent users
- [ ] Response time benchmarking
- [ ] Error rate monitoring via Supabase logs
- [ ] Large dataset loading performance

### Year Slider

Temporal navigation for time-series data:

- [ ] Side panel slider UI component
- [ ] Animate data changes over years
- [ ] Visual indicators for missing data years (gray out / hatching TBD)
- [ ] Scope awareness (all data vs specific layer)
- [ ] Handle datasets with different year ranges gracefully

**Example UX:**
```
User views GDP for Europe 2022
-> Slider appears showing 1990-2024
-> User drags to 2015
-> Map updates with 2015 values
-> Countries missing 2015 data shown differently
```

### Derived Fields / Calculated Metrics

Enable computed fields without hardcoded formulas:

- [ ] Rule-based derivation system (not hardcoded formulas)
- [ ] "Per capita" pattern -> divide by population
- [ ] "Percentage of total" -> sum filtered set, divide each by total
- [ ] "Growth rate" -> compare to previous year
- [ ] LLM prompt updates to recognize derived field requests
- [ ] Caching for expensive calculations

**Example queries:**
- "GDP per capita for African countries" -> gdp / population
- "CO2 emissions by percentage for G7" -> each / sum(all G7)
- "Population growth rate 2020-2023" -> (2023 - 2020) / 2020

**Scope rules:**
- Percentage denominator = filtered set total (user's current selection)
- User can specify "percentage of world total" for global denominator

---

## Medium Priority

### Data Availability Heat Map

Visual layer showing data richness per location:

- [ ] Heat score formula: Geographic Depth x Metric Breadth
- [ ] Pre-compute scores during ETL (store in metadata/heat_scores.json)
- [ ] Toggle layer or "show data coverage" command
- [ ] Choropleth or glow visualization (TBD)
- [ ] Help users discover data-rich areas
- [ ] Explain sparse query results

**Score calculation:**
```
Geographic Depth = admin levels available (country=1, +state=2, +county=3, +city=4)
Metric Breadth = number of data fields available
Heat Score = Depth x Breadth

Example:
  USA: depth=4 (country/state/county/city), metrics=12 -> score=48
  France: depth=2 (country/city), metrics=6 -> score=12
  Chad: depth=1 (country only), metrics=2 -> score=2
```

### Geometry Merging (On-Demand Union)

Combine smaller regions into larger ones dynamically:

- [ ] Server-side union using Shapely unary_union()
- [ ] Or client-side with Turf.js
- [ ] Remove internal borders when merging
- [ ] Use cases: "Show Europe as one region" / "Combine Nordic countries"
- [ ] No pre-computation - always on-demand per user request

**Implementation notes:**
- Niche feature, low priority
- Leverage existing region groupings from conversions.json
- Consider caching frequently requested unions

### Admin Dashboard Cleanup

Streamlit dashboard refinement:

- [ ] Remove unused/experimental features
- [ ] Simplify data ingestion workflow
- [ ] Add "Build Your Own Dataset" export feature
- [ ] Improve aggregate row editor
- [ ] Better metadata editing UI

### Build Your Own Dataset (Admin Feature)

Custom dataset exports for specific use cases:

- [ ] Select fields from multiple datasets
- [ ] Apply filters (region, year range, thresholds)
- [ ] Preview before download
- [ ] Export as CSV or JSON
- [ ] Does NOT modify main database

**Example workflow:**
```
Admin: "I need GDP + population for Europe 2010-2020"
-> Select owid-co2-data.csv
-> Pick fields: country_name, year, gdp, population
-> Filter: region=Europe, year=2010-2020
-> Preview: 440 rows
-> Download: europe_gdp_pop_2010-2020.csv
```

---

## Lower Priority

### Click-to-Select Disambiguation

Handle ambiguous queries by letting users click on the map:

- [ ] Backend detects ambiguous queries (e.g., "Washington County" = 30 matches)
- [ ] Returns `disambiguation_mode: true` with all candidates
- [ ] Frontend displays all matches on map with markers/polygons
- [ ] User clicks to select one or multiple entities
- [ ] Selection highlighting (green = selected, orange = unselected)
- [ ] "Confirm Selection" button sends FIPS codes back to server
- [ ] Multi-select for comparison queries ("Compare these 3 counties")

**Cesium APIs to use:**
- `viewer.selectedEntityChanged` - Click event on entities
- `viewer.scene.pick()` - Get entity at mouse position
- `ScreenSpaceEventHandler` - Low-level click/hover events

**User flow:**
```
User: "Show me Washington County population"
LLM: "Washington County exists in 30 states. I've highlighted all of them - click the one(s) you want."
[Map shows all 30 Washington Counties]
[User clicks on Oregon's Washington County]
System: "Got it! Here's Washington County, Oregon..."
```

**Also enables:**
- "Show me borders" then click to request data for selected regions
- Multi-county/multi-country comparisons via click selection
- Resolving any place name ambiguity visually

### Show Me Borders Command

Display geometry via conversational request:

- [ ] META intent type for border/geometry requests
- [ ] Returns geometry without data (for visual reference)
- [ ] Replaces current map content (not layered)
- [ ] User can then click to select regions for data queries

### Choropleth Styling

Color countries/regions by data value:

- [ ] Heatmap coloring based on selected metric
- [ ] Color scale legend
- [ ] User-defined color gradients (future)

### Result Summary Cards

Show key stats before/alongside map:

- [ ] Total, average, min, max for displayed data
- [ ] Count of results
- [ ] Data source attribution

### Export Options

Download query results:

- [ ] CSV export
- [ ] GeoJSON export
- [ ] Include metadata in export

---

## Future Considerations

### Supabase Database Migration

Migrate from CSV files to Supabase PostgreSQL for better performance and scalability.

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

**Access control (RLS):**
```sql
-- Public read (Railway app)
CREATE POLICY "Public read" ON owid_data FOR SELECT USING (true);

-- Admin write (ETL with service_key)
CREATE POLICY "Admin write" ON owid_data FOR ALL USING (auth.role() = 'service_role');
```

**Cost estimate:**
- Current data ~100 MB (well under 500 MB free tier)
- Pro tier ($25/mo) for production reliability
- No per-query costs

**Migration steps:**
- [ ] Create tables in Supabase with proper schema
- [ ] Update ETL to insert to Supabase (wide->long conversion)
- [ ] Add RLS policies (public read, admin write)
- [ ] Create `supabase_queries.py` module for data fetching
- [ ] Replace pandas CSV loading with Supabase queries in mapmover.py
- [ ] Keep metadata table for LLM dataset selection
- [ ] Test derived field calculations in Python
- [ ] Remove large CSVs from git repo
- [ ] Update admin dashboard for Supabase management

### Query Caching

- [ ] Cache frequent queries (Redis or in-memory)
- [ ] Cache geometry (rarely changes)
- [ ] Invalidate on data updates

### Tile Server

- [ ] Vector tiles for complex polygons
- [ ] Mapbox/MapLibre integration
- [ ] Reduce GeoJSON payload size

### Data Enrichment

- [ ] Cross-dataset queries ("GDP from OWID + health from WHO")
- [ ] Calculated fields in Python after fetch
- [ ] Aggregations ("average GDP by continent")

### Vector Search Layer

Semantic search over external content:

- [ ] Web scraper for supplier sites / documentation
- [ ] Vector database (ChromaDB local, Pinecone cloud)
- [ ] "Where can I buy solar panels in Texas?" -> relevant links

### Multi-Tenant / SaaS

- [ ] User accounts and authentication
- [ ] Per-user dataset uploads
- [ ] Usage tracking and limits
- [ ] API keys for external access

### Advanced Visualization

- [ ] Charts alongside map (bar/line for time series)
- [ ] Toggle between map and data table view
- [ ] Side-by-side comparison mode

---

## Technical Debt

- [ ] Add unit tests for LLM parsing
- [ ] Document metadata schema formally
- [ ] Clean up archive folder
- [ ] Review requirements.txt for unused packages

---

## Ideas Backlog

Ideas that may or may not be implemented:

- Natural language data updates ("Update Canada's GDP to 2 trillion")
- Scheduled data refresh (auto-pull from OWID, WHO, Census)
- Collaborative annotations (users add notes to regions)
- Embeddable widget (like disaster-clippy's embed system)
- Mobile app (React Native with offline support)
- AI-generated insights ("What's interesting about this data?")

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

## Recently Completed

### December 2025
- **MapLibre GL JS migration** - Migrated from Cesium to MapLibre GL JS 5.x with globe projection
  - Fixed polygon click detection (Cesium only detected border clicks)
  - Resolved memory errors with complex polygons
  - Reduced JS library size from ~30MB to ~2MB
- **Codebase refactoring** - Split mapmover.py (4,660 lines) into modular package:
  - app.py (entry point) + mapmover/ package (14 modules)
  - Improved maintainability and testability
  - Archived one-time scripts

### November 2025
- Cesium-only map (Leaflet archived)
- MODIFY intent for incremental map updates
- Map state tracking for modifications
- Aggregate row removal in data pipeline
- Shared helpers, removed hardcoded coordinates
- Column alias mapping for filters
- String comparisons in filters (exclusions)
- Multiple sources display in popups
- Supabase cloud logging (sessions, errors, data quality)
- Geometry consolidation with standard 6-column format:
  - Standard columns: name, abbrev, code, level, coordinates, geometry
  - Extracted data from geometry files (Countries_geometry.csv, country_data.csv)
  - Reduced conversions.json fallback coords to 3 countries (COK, NIU, NRU)
- Census data support at county level

---

*Last Updated: 2025-12-21*
