# Disaster Display System

Event-based visualization for disasters including earthquakes, hurricanes, wildfires, tsunamis, and volcanoes. Shows individual events with animation support.

**Related docs:**
- [MAPPING.md](MAPPING.md) - Time slider, **detailed animation behavior per disaster type**, choropleth system
- [data_pipeline.md](data_pipeline.md) - Data schema, metadata, folder structure
- [data_import.md](data_import.md) - Quick reference for creating converters
- [disaster data.md](disaster%20data.md) - Research on additional data sources, inventory

---

## Disaster Types at a Glance

| Type | Global Source | Live API | Animation | Year Range | Display Model |
|------|---------------|----------|-----------|------------|---------------|
| **Earthquakes** | USGS Global Catalog | Yes (real-time) | Aftershock sequences | 1900-present | Point + Radius |
| **Tropical Storms** | NOAA IBTrACS | Yes (6h updates) | Track progression | 1842-present | Track/Trail |
| **Tsunamis** | NOAA NCEI | Yes (as events) | Wave propagation | 2100 BC-present | Radial |
| **Volcanoes** | Smithsonian GVP | Yes (weekly) | Static (with duration) | Holocene | Point + Radius |
| **Wildfires** | Global Fire Atlas | Zenodo (periodic) | Daily progression | 2002-2024 | Polygon |
| **Drought** | US Drought Monitor | Yes (weekly) | Weekly snapshots | 2000-present | Choropleth |
| **Tornadoes** | NOAA Storm Events | Yes (monthly) | Track drill-down | 1950-present | Point + Track |
| **Floods** | (future) | - | - | - | Polygon |

**Display Models:**
- **Point + Radius**: Static points with magnitude-based circles (felt/damage radius)
- **Track/Trail**: Progressive line drawing with current position marker
- **Radial**: Expanding wave from source to observation points
- **Polygon**: Area boundaries that change over time
- **Choropleth**: County-level shading by severity

---

## Global Data Sources

All disaster data uses **global sources only** - no country-specific duplicates.

| Type | Source | Data Path | Live Update URL | Coverage |
|------|--------|-----------|-----------------|----------|
| **Earthquakes** | USGS Earthquake Catalog | `global/usgs_earthquakes/` | https://earthquake.usgs.gov/fdsnws/event/1/query | 1900-present, M2.5+ global |
| **Tropical Storms** | NOAA IBTrACS v04r01 | `global/tropical_storms/` | https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/ | 1842-present, all basins |
| **Tsunamis** | NOAA NCEI Historical Tsunami Database | `global/tsunamis/` | https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/tsunamis/ | 2100 BC-present, global |
| **Volcanoes** | Smithsonian Global Volcanism Program | `global/smithsonian_volcanoes/` | https://volcano.si.edu/database/webservices.cfm | Holocene epoch, 1,400+ volcanoes |
| **Wildfires** | Global Fire Atlas (NASA/ORNL) | `global/wildfires/` | [Zenodo](https://zenodo.org/records/11400062) | 2002-2024, 13.3M fires |

### Data Files Per Source

**Earthquakes** - `global/usgs_earthquakes/`
- `events.parquet` - Individual events (306K+ rows)
- `GLOBAL.parquet` - Country-year aggregates
- Schema: event_id, timestamp, latitude, longitude, magnitude, depth_km, felt_radius_km, damage_radius_km, place, loc_id
- Aftershock columns: mainshock_id, sequence_id, is_mainshock, aftershock_count

**Tropical Storms** - `global/tropical_storms/`
- `storms.parquet` - Storm metadata (13,541 storms)
- `positions.parquet` - 6-hourly track positions (722,507 rows)
- Schema: storm_id, timestamp, latitude, longitude, wind_kt, pressure_mb, category, basin
- Wind radii: r34_ne/se/sw/nw, r50_*, r64_*

**Tsunamis** - `global/tsunamis/`
- `events.parquet` - Source events/epicenters (2,619 events)
- `runups.parquet` - Coastal observation points (33,623 runups)
- Schema: event_id, timestamp, latitude, longitude, eq_magnitude, cause, max_water_height_m
- Runup schema: runup_id, event_id, dist_from_source_km, water_height_m

**Volcanoes** - `global/smithsonian_volcanoes/`
- `events.parquet` - Eruption events (11,079 eruptions)
- `volcanoes.parquet` - Volcano locations (1,400+ volcanoes)
- Schema: event_id, timestamp, latitude, longitude, VEI, volcano_name, activity_type
- Duration columns: end_year, end_timestamp, duration_days, is_ongoing, eruption_id

**Wildfires** - `global/wildfires/`
- `fires.parquet` - Fire events with perimeters (13.3M fires)
- `fire_progression_{year}.parquet` - Daily burn polygons for animation
- Schema: fire_id, start/end dates, size (km2), duration, spread speed/direction
- Progression schema: event_id, date, day_num, area_km2, perimeter (GeoJSON)

---

## Earthquakes

### Display: Point + Radius

Two concentric circles - felt radius (outer, where shaking noticeable) and damage radius (inner, where structural damage possible).

**Radius Formulas:**
```python
felt_radius = 10 ** (0.44 * magnitude - 0.29)
damage_radius = 10 ** (0.32 * magnitude - 0.78)  # Only M5+
# Depth correction: deep (>300km) = 50% reduction, intermediate (>70km) = 30% reduction
```

| Magnitude | Felt Radius | Damage Radius |
|-----------|-------------|---------------|
| M4.0 | ~30 km | 0 km |
| M5.0 | ~80 km | ~7 km |
| M6.0 | ~220 km | ~14 km |
| M7.0 | ~620 km | ~29 km |
| M8.0 | ~1700 km | ~60 km |

### Aftershock Sequences

Click earthquake to animate sequence:
- Mainshock appears with expanding circle
- Aftershocks appear at their timestamps
- "Spiderweb" lines connect mainshock to aftershocks

**Gardner-Knopoff Windows:**
- Time: `10^(0.5*M - 1.5)` days (M7 = ~10 days)
- Distance: `10^(0.5*M - 0.5)` km (M7 = ~100 km)

**Converter:** `convert_global_earthquakes.py`

---

## Tropical Storms

### Display: Track/Trail

Animated tracks showing storm path:
1. **Yearly view**: Full track lines colored by max category
2. **Drill-down**: Progressive drawing with current position marker
3. **Wind radii**: Optional circles at 34/50/64 kt extent

### Category Colors (Saffir-Simpson)

| Category | Wind (kt) | Color |
|----------|-----------|-------|
| TD | < 34 | Gray |
| TS | 34-63 | Blue |
| Cat 1 | 64-82 | Yellow |
| Cat 2 | 83-95 | Orange |
| Cat 3 | 96-112 | Light Red |
| Cat 4 | 113-136 | Red |
| Cat 5 | > 136 | Dark Red |

### Basin Codes

NA (North Atlantic), EP (East Pacific), WP (West Pacific), SI (South Indian), SP (South Pacific), NI (North Indian)

**Converter:** `convert_ibtracs.py`

---

## Tsunamis

### Display: Radial Propagation

Expanding wave from source to coastal observations:
1. Source event marker (earthquake epicenter)
2. Expanding wave circle at ~700 km/h
3. Runup points appear as wave reaches them

### Animation Settings

- Granularity: 12 minutes (smooth wave)
- Playback: 200ms intervals (1 sec = 1 hour real-time)
- 5% visibility buffer so runups appear after wave front

**Converter:** `convert_tsunami.py`

---

## Volcanoes

### Display: Point + Radius

VEI-based impact circles:

| VEI | Felt Radius | Damage Radius | Example |
|-----|-------------|---------------|---------|
| 0 | ~5 km | ~1 km | Effusive lava |
| 2 | ~23 km | ~4 km | Minor eruption |
| 4 | ~105 km | ~16 km | Cataclysmic |
| 5 | ~224 km | ~32 km | Mt St Helens 1980 |
| 6 | ~478 km | ~63 km | Pinatubo 1991 |

### Continuous Eruptions

Duration columns track multi-year eruptions (e.g., Kilauea 1983-2018 = 35 years):
- `end_year`, `end_timestamp`, `duration_days`, `is_ongoing`

### Cross-Event Linking

Volcanoes link to nearby earthquakes (30 days before to 60 days after, 150km radius).

**Converter:** `convert_global_volcanoes.py`

---

## Wildfires

### Display: Polygon + Daily Progression

Fire perimeter polygons that grow over time:
1. **Static**: Final perimeter (or point if no perimeter data)
2. **Drill-down**: Daily snapshots of cumulative burn area

### Fire Progression Processing

The converter extracts daily burn polygons from day_of_burn rasters:

| Min Size Filter | Fires (23 years) | Processing Time |
|-----------------|------------------|-----------------|
| >= 10 km2 | ~1.3M | ~12 hours |
| >= 25 km2 | ~473K | ~4.4 hours |
| >= 50 km2 | ~196K | ~1.8 hours |
| >= 100 km2 | ~75K | ~42 minutes |

```bash
python convert_fire_progression.py --all --min-size 25  # Recommended
```

Processes years in reverse order (newest first), skips completed years.

### Alternative Fire Sources

| Source | Coverage | Use Case |
|--------|----------|----------|
| NASA FIRMS | Global, <3h latency | Live heatmap |
| MTBS | USA only, 1984+ | Higher precision USA |
| CNFDB | Canada, 1946+ | Canadian fires |

**Converter:** `convert_global_fire_atlas.py`, `convert_fire_progression.py`

---

## Tornadoes

### Display: Point + Track Drill-down

USA tornadoes from NOAA Storm Events database (1950-present). No reliable global tornado database exists - ~75% of recorded tornadoes occur in the USA.

**Overview Mode:**
- Points colored by Enhanced Fujita (EF) or legacy Fujita (F) scale
- Point size scales with tornado intensity
- Impact radius circle shows damage path width

**Drill-down Mode:**
- Click tornado to view track
- Track line connects start and end points
- Green marker = start point, Red marker = end point
- Impact corridor shown along track

### EF Scale Colors

| Scale | Wind (mph) | Color | Damage |
|-------|------------|-------|--------|
| EF0 | 65-85 | Pale Green | Light |
| EF1 | 86-110 | Lime Green | Moderate |
| EF2 | 111-135 | Gold | Significant |
| EF3 | 136-165 | Dark Orange | Severe |
| EF4 | 166-200 | Orange-Red | Devastating |
| EF5 | >200 | Dark Red | Incredible |

### Data Files

**NOAA Storm Events** - `countries/USA/noaa_storms/`
- `events.parquet` - All storm events including tornadoes (1.2M events, 79K tornadoes)
- Schema: event_id, timestamp, latitude, longitude, end_latitude, end_longitude, tornado_scale, tornado_length_mi, tornado_width_yd
- Damage/casualty columns: deaths_direct, injuries_direct, damage_property

**Converter:** `data_converters/utilities/build_noaa_events.py`

---

## Frontend Architecture

### Display Models

| Model | File | Disasters |
|-------|------|-----------|
| Point+Radius | model-point-radius.js | Earthquakes, Volcanoes, Tornadoes |
| Track/Trail | model-track.js | Hurricanes, Cyclones |
| Polygon/Area | model-polygon.js | Wildfires, Floods |
| Choropleth | choropleth.js | Drought, Aggregates |
| Radial | event-animator.js | Tsunamis |

### Key Files

| File | Purpose |
|------|---------|
| `models/model-point-radius.js` | Earthquake, volcano, tornado rendering |
| `models/model-track.js` | Hurricane track rendering |
| `models/model-polygon.js` | Wildfire polygon rendering |
| `models/model-registry.js` | Routes event types to models |
| `event-animator.js` | Unified animation controller (earthquakes, tsunamis, wildfires, tornadoes) |
| `track-animator.js` | Hurricane track animation |
| `overlay-selector.js` | UI checkbox panel |
| `overlay-controller.js` | Data loading orchestration |
| `time-slider.js` | Time controls, multi-scale tabs |

### Overlay Selector

```
+------------------+
| Overlays      [x]|
+------------------+
| v Disasters      |
|   [x] Earthquakes|
|   [ ] Hurricanes |
|   [ ] Wildfires  |
|   [ ] Volcanoes  |
|   [ ] Tsunamis   |
|   [ ] Tornadoes  |
+------------------+
```

### Rolling Window + Fade

See mapping.md for more details
Events use a visibility window that scales with speed:

| Speed | Window | Effect |
|-------|--------|--------|
| 6h/sec | 24 hours | 4 data points visible |
| 1d/sec | 7 days | 1 week of events |
| 1yr/sec | 1 year | Full year visible |

Events fade from full opacity to 0 as they leave the window.

---

## API Endpoints

### GeoJSON Endpoints

| Endpoint | Parameters |
|----------|------------|
| `/api/earthquakes/geojson` | year, min_magnitude |
| `/api/storms/geojson` | year, basin |
| `/api/storms/{storm_id}/track` | - |
| `/api/volcanoes/geojson` | - |
| `/api/eruptions/geojson` | year |
| `/api/wildfires/geojson` | year |
| `/api/tsunamis/geojson` | year |
| `/api/tornadoes/geojson` | year, min_scale |

### Drill-Down Endpoints

| Endpoint | Returns |
|----------|---------|
| `/api/earthquakes/{id}/aftershocks` | Aftershock sequence |
| `/api/tsunamis/{id}/runups` | Coastal observations |
| `/api/wildfires/{id}/progression` | Daily burn snapshots |
| `/api/tornadoes/{id}` | Tornado detail with track |

---

## Implementation Status

### Complete

- [x] Earthquake display (Point+Radius, aftershock sequences)
- [x] Volcano display (Point+Radius, cross-linking)
- [x] Hurricane display (Track/Trail, drill-down animation)
- [x] Tsunami display (Radial propagation)
- [x] Wildfire display (Polygon)
- [x] Tornado display (Point + Track drill-down)
- [x] Time slider (variable granularity, speed control)
- [x] Overlay selector UI
- [x] EventAnimator (unified controller)

### In Progress

- [ ] Fire progression animation (converter ready)
- [ ] Drought choropleth animation

### Future

- [ ] Flood polygon display
- [ ] Live data pipeline

---

## Live Data Sources (Future)

See `docs/future/native_refactor.md` for planned live architecture.

**Key APIs:**
- USGS Earthquakes: Real-time, minutes latency
- NASA FIRMS: 12-hour latency, global fires
- NOAA DART Buoys: 15-second samples during tsunami events
- IOC Sea Level: 1-minute values globally

---

## Known Issues

**Volcano prehistoric data:** Smithsonian GVP includes eruptions back to ~1280 CE which overflow pandas datetime. Only 36% have valid timestamps.

**Map projection:** Globe projection disabled due to animation interference. Uses Mercator only.

---

*Last Updated: 2026-01-10*
