# Data Pipeline Review - January 2026

Summary of pipeline review, disaster display design, and implementation readiness.

---

## Current State

### Data Coverage

| Country | Sources | Geometry | Status |
|---------|---------|----------|--------|
| **USA** | 15 datasets | County-level | Production-ready |
| **Australia** | 2 datasets | LGA-level | Production-ready (tested extensively) |
| **Canada** | 2 datasets | CSD-level | Needs more data |
| **Global** | 23 datasets | Country-level | Production-ready |
| **Europe** | 1 dataset (Eurostat) | NUTS3-level | Production-ready |

### Disaster Sources with Events

| Source | Location | Files | Event Count |
|--------|----------|-------|-------------|
| usgs_earthquakes | USA | events.parquet, USA.parquet | ~100K events |
| noaa_hurricanes | USA | positions.parquet, storms.parquet, USA.parquet | ~55K positions |
| mtbs_wildfires | USA | fires.parquet, USA.parquet | ~25K fires |
| bom_cyclones | Australia | events.parquet, AUS.parquet | ~40K positions |
| noaa_tsunamis | USA | events.parquet, USA.parquet | ~2K runups |
| smithsonian_volcanoes | USA | events.parquet, USA.parquet | ~500 eruptions |
| fema_disasters | USA | events.parquet, USA.parquet | ~65K declarations |
| noaa_storms | USA | events.parquet, USA.parquet | ~2M storm events |
| reliefweb_disasters | Global | events.parquet, all_countries.parquet | ~25K disasters |

---

## Pipeline Validation

### What Works

1. **Converter pattern is solid** - ABS population tested thoroughly, same pattern applies everywhere
2. **Metadata generation** - finalize_source() auto-generates consistent metadata.json
3. **loc_id system** - Hierarchical IDs (USA-CA-06037) work for spatial joins
4. **Geometry handling** - 3-pass spatial join assigns events to counties/LGAs reliably
5. **Source registry** - Centralized config with has_events flag already in place

### Standardized Event Schema (Observed)

```
Position:  lat/lon or latitude/longitude
Time:      timestamp or event_date (datetime)
ID:        event_id or {type}_id
Location:  loc_id (hierarchical)
Severity:  magnitude/category/wind_kt/acres (type-specific)
```

All event converters output these standard columns.

---

## Disaster Display Design

Full design in [DISASTER_DISPLAY.md](DISASTER_DISPLAY.md).

### Key Decisions

1. **Two display modes**:
   - Aggregate (choropleth) - existing system, works well
   - Events (points/tracks) - new system to build

2. **Order schema extension**: Add `mode: "events"` field to trigger event loading

3. **Generalized event layers**: Extend hurricane layer pattern to all event types

4. **TimeSlider integration**: Already supports 6h/daily/weekly - just needs event mode init

5. **Performance caps**: 1K-5K events per query, time range limits by granularity

### Event Type Rendering

| Type | Geometry | Styling |
|------|----------|---------|
| Earthquake | Circle + radius | Size by magnitude, red scale |
| Hurricane | Line + point | Category colors, animated position |
| Wildfire | Circle | Size by acres, orange/red scale |
| Tsunami | Circle | Size by runup height, blue |

---

## Implementation Phases

### Phase 1: Foundation
- Add `mode` field to order schema
- Add `load_event_data()` to order_executor
- Create generalized `loadEventLayer()` in MapAdapter
- Estimated effort: 1-2 days

### Phase 2: Earthquake Events (Test Case)
- Implement earthquake point layer with magnitude sizing
- Add felt radius circles option
- Connect to TimeSlider for daily animation
- Test with California earthquake query
- Estimated effort: 1 day

### Phase 3: Hurricane/Cyclone Tracks
- Migrate HurricaneHandler to generalized system
- Implement track line + animated marker
- Test with USA and Australia cyclone data
- Estimated effort: 1 day

### Phase 4: Other Event Types
- Wildfire points
- Tsunami runups
- Volcano eruptions
- Estimated effort: 2-3 days

---

## Next Steps

1. **Start with earthquakes** - Simplest geometry (points), good test case
2. **Build event loader in order_executor** - Load events.parquet instead of USA.parquet
3. **Create loadEventLayer()** - Generalize existing hurricane layer code
4. **Test with California earthquakes 2024** - Validate animation and performance
5. **Iterate on column naming** - Standardize lat/lon vs latitude/longitude during testing

---

## Files Changed/Created

| File | Action |
|------|--------|
| [DISASTER_DISPLAY.md](DISASTER_DISPLAY.md) | Created - full design doc |
| [order_executor.py](../mapmover/order_executor.py) | To be modified - add event mode |
| [map-adapter.js](../static/modules/map-adapter.js) | To be modified - add event layers |
| [time-slider.js](../static/modules/time-slider.js) | To be modified - add event mode init |

---

## Recommendations

1. **Use USA earthquake data first** - Most complete, simple point geometry
2. **Standardize on `lat`/`lon`** - Shorter than latitude/longitude, update converters as needed
3. **Add column validation to finalize_source** - Warn if event files missing required columns
4. **Create event display demo query** - "Show California earthquakes M4+ in 2024" as test case

---

*Review completed: 2026-01-07*
