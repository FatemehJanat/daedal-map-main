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

## Phase 5: NASA LANCE Flood Integration

Goal: Fill flood data gap (2020-present) and enable near-real-time flood monitoring.

### Current State

| Period | Source | Status |
|--------|--------|--------|
| 1985-1999 | DFO (metadata only) | Have it |
| 2000-2018 | DFO + GFD satellite | Have it |
| 2019 | DFO only | Have it |
| 2020-present | **Gap** | Need NASA LANCE |

### NASA LANCE NRT Global Flood Product

**Source:** https://www.earthdata.nasa.gov/data/instruments/viirs/near-real-time-data/nrt-global-flood-products

| Feature | Details |
|---------|---------|
| Resolution | 250m (MODIS), 375m (VIIRS) |
| Latency | ~3 hours from satellite pass |
| Archive | 2003-2024 (22 years reprocessed) |
| Composites | 1-day, 2-day, 3-day (cloud filtering) |
| License | NASA open data (no restrictions) |
| Access | Earthdata login (free) |

**Data Products:**
- MCDWD_L3_NRT (MODIS): https://nrt3.modaps.eosdis.nasa.gov/archive/allData/61/MCDWD_L3_NRT
- VCDWD_L3_NRT (VIIRS): https://nrt3.modaps.eosdis.nasa.gov/archive/allData/5200/VCDWD_L3_NRT

**Dec 2025 Update:** Added "recurring flood" class to distinguish normal vs unusual flooding.

### Processing Pipeline (Streaming Approach)

```
Weekly cron job:
1. Download last 7 days of LANCE tiles (~15-30 GB temp)
2. For each day:
   - Extract flood pixels (HDF band: flooded=1,2,3)
   - Vectorize to polygons (rasterio.features.shapes)
   - Simplify geometry (shapely.simplify)
   - Calculate centroid, area_km2, bbox
   - Spatial join for country/loc_id
   - Append to events.parquet
3. Delete raw HDF files
4. Repeat next week
```

**Storage estimate:** ~200 MB/year processed (vs 50-100 GB/year raw)

### Output Schema

```python
{
  'event_id': 'LANCE-2024-01-15-h08v05',
  'timestamp': '2024-01-15',
  'latitude': 28.5,
  'longitude': -81.2,
  'area_km2': 245.8,
  'flood_class': 2,        # 1=water, 2=flood, 3=recurring
  'composite_days': 3,     # 1, 2, or 3 day composite
  'country': 'USA',
  'loc_id': 'USA/FL/Orange',
  'source': 'NASA_LANCE',
  'geometry': {...}        # simplified polygon
}
```

### Implementation Files

| File | Purpose |
|------|---------|
| download_lance_floods.py | Fetch HDF tiles from NASA |
| process_lance_floods.py | Vectorize, simplify, merge |
| convert_lance_floods.py | Convert to events.parquet |

### Dependencies

- Earthdata account (free registration)
- rasterio (HDF/GeoTIFF reading)
- shapely (geometry simplification)
- h5py or pyhdf (HDF4 format)

### Questions to Research

- Does LANCE provide daily progression (duration bands)?
- Can we get flood extent growth over time for animation?
- What's in the "duration" band of LANCE products?

### Simpler Event-Driven Approach (Recommended)

Instead of downloading all LANCE tiles globally, use flood event catalogs as triggers:

**Available Event Catalogs:**

| Source | Events | Years | Has Coords | Has Polygons |
|--------|--------|-------|------------|--------------|
| GFD (already have) | 4,825 | 1985-2019 | Yes | Some |
| Global Flood Monitor | 26,552 | 2014-2023 | Via geonames | No |
| GFD QC (new) | 913 | 2000-2010 | Yes | Yes |

**Implementation:**
1. Download event catalogs: `download_flood_events.py --all`
2. Merge into unified event list with date/location
3. For 2020-present: Use event list to trigger LANCE downloads for specific dates/tiles
4. Process only those tiles into flood extent polygons

**Benefits:**
- Reduces download from ~1.4 TB to ~50-100 GB (event-targeted only)
- Already have 2000-2018 coverage via GFD
- Global Flood Monitor provides 2014-2023 event triggers

**Files:**
- `download_flood_events.py` - Downloads event catalogs from GFM, GFD
- `convert_flood_events.py` - Merges sources into unified list (TODO)

---

## Phase 6: Real-time / Climate Expansion

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
