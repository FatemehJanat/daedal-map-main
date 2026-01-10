# Development Roadmap

Current priorities and implementation phases.

---

## Phase 1: Core Census Data (Current Focus)

Goal: Get basic time-series demographic data working for 4 regions.

| Country | Source | Geometry | Data | Status |
|---------|--------|----------|------|--------|
| **AUS** | ABS | Done (547 LGAs) | abs_population | In progress |
| **Europe** | Eurostat | NUTS downloader built | eurostat_demo exists | Need to run downloader |
| **CAN** | StatsCan | Need CSD boundaries | Need converter | Not started |
| **USA** | Census | GADM (fine) | Multiple sources | Need combining |

### Blockers

1. **Run NUTS geometry downloader** - `download_nuts_geometry.py` exists, need to execute
2. **Download StatsCan CSD boundaries** - Manual download from StatsCan
3. **Build parquet join functions** - Required for US source combinations

### Success Criteria

- Query "show me population for [any region in AUS/EU/CAN/USA]" returns choropleth
- Year slider works across full date range
- Multiple metrics available per source

---

## Phase 2: Admin Dashboard - Data Tools

Goal: Build tools for managing and combining data sources.

| Feature | Purpose | Priority |
|---------|---------|----------|
| Parquet join/merge | Combine US census sources into single file | High |
| Source combination UI | Visual tool for merging sources | Medium |
| Metadata editor | Fix/update metadata.json files | Low |
| Data validation | Check parquet schema compliance | Low |

### Dependencies

- Phase 1 US census sources identified
- Understanding of which sources need combining

---

## Phase 3: Disaster Views

Goal: Verify all 4 disaster datasets work for US, then scale globally.

| Dataset | Source | US Status | Global Status |
|---------|--------|-----------|---------------|
| Earthquakes | USGS | Test | Should work (global data) |
| Storms | NOAA | Test | US-focused |
| Fires | NASA FIRMS | Test | Global coverage |
| Drought | USDM | Test | US only |

### Overlay Selector UI (Quick Win)

Implement a sidebar for toggling data overlays - helps chat understand context and shows off available data.

```
[Overlays]
  [ ] Disasters
      [ ] Earthquakes
      [ ] Hurricanes
      [ ] Wildfires
      [ ] Volcanoes
  [ ] Climate
      [ ] Wind patterns
      [ ] Air quality
  [ ] Demographics (existing choropleth)
```

Benefits:
- Chat knows which overlays are active (context for queries)
- Users can explore data without typing queries
- Multiple overlays can be visible simultaneously
- Establishes visual language for event displays

See [DISASTER_DISPLAY.md](../DISASTER_DISPLAY.md#overlay-selector-ui) for implementation details.

### Tasks

1. Test each disaster view with US data
2. Verify point rendering and clustering
3. Test date range filtering
4. Confirm Canada data works (where applicable)
5. Confirm global data works (earthquakes, fires)
6. Build overlay selector UI

### Success Criteria

- All 4 disaster views render correctly
- Date filtering works
- Tooltip/popup shows event details
- Performance acceptable with large event counts
- Overlay selector toggles layers correctly

---

## Phase 4: Validation Point

At this milestone, the system should "just work" for:

- **Any time-series parquet** in system format -> choropleth display
- **Any point/event data** -> disaster view handles it
- **Any country** with geometry -> data displays

Only work needed per new source = write converter.

### Test Cases

| Query | Expected Result |
|-------|-----------------|
| "population of Germany" | Eurostat data, NUTS regions |
| "earthquakes in Japan last year" | USGS global data |
| "fires in Australia" | NASA FIRMS data |
| "GDP per capita EU" | Eurostat economic data |

---

## Phase 5: Real-time / Climate Expansion

Goal: Add live data streams and climate datasets.

### Live Data Options

| Source | Data Type | Update Rate | Priority |
|--------|-----------|-------------|----------|
| NASA FIRMS | Active fires | 3 hours | High |
| USGS Earthquakes | Seismic events | Real-time | High |
| OpenAQ | Air quality | Hourly | Medium |
| NOAA GFS | Weather grids | 6 hours | Low (complex) |

### New Display Modes Needed

| Mode | Use Case | Complexity |
|------|----------|------------|
| Animated points | Fire/earthquake events | Medium |
| Sensor overlay | Air quality stations | Medium |
| Particle field | Wind/weather (nullschool-style) | High |
| Time scrubbing | Event playback | Medium |

### Infrastructure

- Ingestion server (always-on, lightweight)
- Sync mechanism to GPU workstation
- Time-series storage (append-only parquet or TimescaleDB)

See [native_refactor.md](native_refactor.md) for architecture details.

---

## Business Model Options

The architecture supports open-core monetization while keeping everything open source.

### What's Free (Always)

- All source code (MIT/Apache license)
- Schema documentation
- Example converters
- Self-hosting instructions

### What Can Be Monetized

| Offering | Description | Model |
|----------|-------------|-------|
| **Pre-built Data Packs** | Ready-to-use parquet files | One-time purchase |
| **Update Subscriptions** | Fresh data delivered regularly | Monthly/annual |
| **Converter Library** | Production converters for live sources | Per-converter |
| **Priority Support** | Deployment/customization help | Hourly/retainer |

### Key Insight

Can't sell open data (USGS, Census, NASA is public domain), but CAN sell:
- **Labor** - Converting, cleaning, maintaining takes work
- **Convenience** - Download ready-to-use vs build from scratch
- **Freshness** - Guaranteed updates vs DIY scraping

This is the same model as Mapbox (OSM data), Observable (open tools), PostGIS (open DB).

See [native_refactor.md](native_refactor.md#business-model-open-core) for detailed breakdown.

---

## Immediate Next Steps

1. [ ] Run NUTS geometry downloader
2. [ ] Download StatsCan CSD boundaries
3. [ ] Test AUS choropleth end-to-end
4. [ ] Build parquet join function for US sources
5. [ ] Test all 4 disaster views

---

## Related Documentation

| File | Content |
|------|---------|
| [data_pipeline.md](data_pipeline.md) | Full pipeline docs, metadata schema |
| [data_import.md](data_import.md) | Converter patterns, parquet structure |
| [GEOMETRY.md](GEOMETRY.md) | loc_id spec, geometry sources |
| [native_refactor.md](native_refactor.md) | Future architecture, live streaming |
| [chat_refactor.md](chat_refactor.md) | LLM preprocessing improvements |

---

*Last Updated: 2026-01-08*
