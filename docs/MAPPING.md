# Mapping and Visualization

Frontend display system using MapLibre GL JS with globe projection.

**Related docs:**
- [DISASTER_DISPLAY.md](DISASTER_DISPLAY.md) - **Complete disaster schemas**, display models, API endpoints
- [GEOMETRY.md](GEOMETRY.md) - loc_id specification, geometry system
- [FRONTEND_MODULES.md](FRONTEND_MODULES.md) - ES6 module structure and architecture

**Key files**:
- [templates/index.html](templates/index.html) - Main page with chat + map
- [static/styles.css](static/styles.css) - UI styles

---

## Map Technology

### MapLibre GL JS 5.x

- **Projection**: Globe (3D sphere view)
- **Library size**: ~2MB (vs ~30MB for Cesium)
- **Rendering**: WebGL-based vector tiles
- **Features**: Polygon click detection, smooth zooming, feature state for highlighting

### Why MapLibre

Migrated from Cesium to MapLibre GL JS in December 2025:
- Fixed polygon click detection (Cesium only detected border clicks)
- Resolved memory errors with complex polygons
- Reduced JS library size significantly
- Better performance for choropleth styling

---

## UI Layout

```
+-----------------------------------------------------------------------+
|                                                                       |
|   [Chat Panel]                    [Order Panel]         [Map]         |
|   +-----------------------+       +---------------+                   |
|   | User: Show me GDP     |       | YOUR ORDER:   |                   |
|   |       for Europe      |       |               |                   |
|   |                       |       | - GDP         |                   |
|   | Bot: I found GDP in   |       |   Europe      |                   |
|   |      OWID dataset.    |       |   2023    [x] |                   |
|   |      Years 1990-2024. |       |               |                   |
|   |      Added to order.  |       +---------------+                   |
|   |                       |       | [Display]     |                   |
|   +-----------------------+       +---------------+                   |
|                                                                       |
+-----------------------------------------------------------------------+
```

---

## Data Flow

```
User sends chat message
        |
        v
LLM determines intent (QUERY/MODIFY/CHAT/META)
        |
        v
Load data from county-map-data/data/
        |
        v
Enrich with geometry from county-map-data/geometry/
        |
        v
Return GeoJSON to map
        |
        v
MapLibre renders features with choropleth colors
```

---

## GeoJSON Response Format

The backend returns GeoJSON FeatureCollections:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {
        "loc_id": "DEU",
        "name": "Germany",
        "year": 2024,
        "gdp": 4200000000000,
        "population": 83200000,
        "co2": 674.8
      },
      "geometry": {
        "type": "MultiPolygon",
        "coordinates": [...]
      }
    }
  ]
}
```

---

## Popup Display

When a user clicks on a feature, a popup shows all available data:

```
Germany
-----------------
GDP: $4.2T
Population: 83.2M
CO2: 674.8 Mt
Life Expectancy: 81.2 years

Source: owid_co2, who_health
Year: 2024
```

### Multiple Sources in Popups

The empty box model allows data from multiple sources to appear in the same popup:
- GDP from owid_co2
- Life expectancy from who_health
- Demographics from census data

Missing data shows as "--" rather than hiding the field.

---

## Choropleth Styling

Color countries/regions by data value.

### Color Palettes

**Sequential (single metric, low to high)**:
- Blues: `#f7fbff` -> `#08306b` (light blue to dark blue)
- Reds: `#fff5f0` -> `#67000d` (pink to dark red)
- Viridis: `#440154` -> `#fde725` (purple to yellow, colorblind-friendly)

**Diverging (positive/negative, center point)**:
- RdYlGn: Red -> Yellow -> Green (bad -> neutral -> good)
- RdBu: Red -> White -> Blue

**For Change Over Time**:
- Red = decreased significantly
- Orange = decreased slightly
- Gray = no change
- Light Green = increased slightly
- Dark Green = increased significantly

### Color Expression

MapLibre uses data-driven styling:

```javascript
const colorExpression = ['case'];

for (const feature of geojson.features) {
  const value = feature.properties[metric];
  if (value != null) {
    colorExpression.push(['==', ['get', 'loc_id'], feature.properties.loc_id]);
    colorExpression.push(colorScale(value));
  }
}

colorExpression.push('#cccccc');  // Default for no data
MapAdapter.map.setPaintProperty('countries-fill', 'fill-color', colorExpression);
```

### Legend

Display a color gradient legend in corner of map:

```
CO2 Emissions
[===gradient===]
Low          High
0            5000
```

---

## Geometry Layers

### Admin Levels

| Level | Name | Example |
|-------|------|---------|
| 0 | Country | USA, Germany, France |
| 1 | State/Region | California, Bavaria |
| 2 | County/District | Los Angeles County |
| 3+ | City/Municipality | Deeper subdivisions |

### Layer Loading

```javascript
// Load country outlines (default view)
loadGeometry('global.csv');

// Drill down to US states
loadGeometry('USA.parquet', {adminLevel: 1});

// Drill down to California counties
loadGeometry('USA.parquet', {adminLevel: 2, parent: 'USA-CA'});
```

---

## Show Borders Command

Display geometry via conversational request without data. See [CHAT.md](CHAT.md) for the full chat flow.

### How It Works

1. User says "show me washington county" (singular)
2. System finds 30+ Washington Counties across the US
3. Returns `type: "disambiguate"` with all options
4. User can say "just show me them" or "display them all"
5. System fetches geometry for all options and displays on map

### Trigger Phrases

Patterns detected by `detect_show_borders_intent()`:
- "just show me them"
- "display them all"
- "show all of them on the map"
- "just the borders"
- "display all"

### Singular vs Plural Suffix

The system distinguishes user intent by suffix:

| Suffix | Intent | Behavior |
|--------|--------|----------|
| "washington county" | Want ONE | Disambiguation (pick one) |
| "washington counties" | Want ALL | Navigation (show all) |
| "texas counties" | Drill-down | Show children of Texas |

### Backend Response

```json
{
  "type": "navigate",
  "message": "Showing 31 locations on the map. Click any location to see data options.",
  "locations": [...],
  "loc_ids": ["USA-AL-01129", "USA-AR-05143", ...],
  "geojson": { "type": "FeatureCollection", "features": [...] }
}
```

### Frontend Behavior

1. Receives GeoJSON with geometries
2. Loads into selection/highlight layer (orange/amber colors)
3. Fits map bounds to show all features
4. User can click locations to select for data queries

### Related Files

| File | Purpose |
|------|---------|
| `mapmover/preprocessor.py` | `detect_show_borders_intent()`, `search_locations_globally()` |
| `mapmover/data_loading.py` | `fetch_geometries_by_loc_ids()` |
| `static/modules/chat-panel.js` | Stores `lastDisambiguationOptions` for follow-up |

---

## Feature Interaction

### Click Events

```javascript
map.on('click', 'countries-fill', (e) => {
  const feature = e.features[0];
  const props = feature.properties;

  // Show popup
  new maplibregl.Popup()
    .setLngLat(e.lngLat)
    .setHTML(buildPopupContent(props))
    .addTo(map);
});
```

### Hover Effects

```javascript
map.on('mousemove', 'countries-fill', (e) => {
  map.setFeatureState(
    { source: 'countries', id: e.features[0].id },
    { hover: true }
  );
});

map.on('mouseleave', 'countries-fill', () => {
  // Reset hover state
});
```

---

## Time Slider

Interactive time slider with variable granularity (6-hour to yearly), continuous speed control, and multi-scale tabs for event drill-down. Supports both choropleth animation (county-level data over time) and event animation (individual disaster events).

**Key files:**
- [time-slider.js](../static/modules/time-slider.js) - Core slider, playback, multi-scale tabs
- [event-animator.js](../static/modules/event-animator.js) - Unified event animation (earthquakes, tsunamis, wildfires, tornadoes)
- [track-animator.js](../static/modules/track-animator.js) - Hurricane track animation

**Full planning history:** [archive/TIME_SLIDER_UPDATE_PLAN.md](archive/TIME_SLIDER_UPDATE_PLAN.md)

### Architecture Overview

```
                    TimeSlider (time-slider.js)
                           |
          +----------------+----------------+
          |                |                |
    Choropleth Mode    Event Mode     Drill-Down Mode
    (county data)    (disaster events)  (single event)
          |                |                |
   ChoroplethManager  EventAnimator   EventAnimator
                      (yearly view)   (sequence view)
                                      TrackAnimator
```

### Granularity System

Time steps auto-adapt to data source:

| Granularity | Step Size | Label Format | Use Case |
|-------------|-----------|--------------|----------|
| 6h | 6 hours | "Sep 28, 2022 06:00" | Hurricane positions |
| daily | 1 day | "Sep 28, 2022" | Earthquake sequences, fire spread |
| weekly | 7 days | "Week of Sep 28" | Drought progression |
| monthly | 1 month | "Sep 2022" | Seasonal patterns |
| yearly | 1 year | "2022" | Default for most data |

Granularity is detected from catalog metadata or data timestamps. The slider auto-configures based on source type.

### Speed Slider

Continuous logarithmic slider controls animation speed across all modes:

```
Speed: [=====|==================]  4d/sec
       30m/sec                15yr/sec
```

**Math:**
- Base unit: 6-hour steps
- Frame rate: 15 FPS
- Range: 0.0056 to 1460 steps per frame
- At minimum (0.0056 steps/frame): ~30m/sec (fine-grained animations like tsunamis)
- At maximum (1460 steps/frame): ~15yr/sec (fast overview)

**Logarithmic mapping** gives most slider range to slower speeds where precision matters:
- Slider 0.0 -> 0.0056 steps/frame -> 30m/sec
- Slider 0.25 -> ~0.5 steps/frame -> ~5h/sec
- Slider 0.50 -> ~3 steps/frame -> ~2d/sec
- Slider 0.75 -> ~90 steps/frame -> ~5wk/sec
- Slider 1.0 -> 1460 steps/frame -> ~15yr/sec

### UI Layout

```
+------------------------------------------------------------------+
| LAYER: Earthquakes (1900-2024)                              [x]  |
+------------------------------------------------------------------+
|                                                                  |
|  [|<] [<] [>|<] [>] [>|]    Speed: [======|===============]  1d  |
|   Skip      Play           Detail 6hr              Year   /sec   |
|                                                                  |
|  |======================|=============|========================| |
|  1900                  1962          |                    2024   |
|                              Jan 15, 1962                        |
+------------------------------------------------------------------+
```

**Controls:**
- `[|<]` / `[>|]` - Jump to start/end
- `[<]` / `[>]` - Step backward/forward by current speed
- `[>|<]` - Play/pause toggle
- Speed slider - Continuous adjustment during playback

### Multi-Scale Tabs

Drill down from overview to event detail with separate time scales:

```
+------------------+---------------------+
| All Data (Years) | Hurricane Ian (6hr) |
+------------------+---------------------+
```

**API:**
```javascript
TimeSlider.addScale({
  id: 'hurricane-ian',
  label: 'Hurricane Ian',
  granularity: '6h',
  timeRange: { min: startTimestamp, max: endTimestamp },
  timeData: { /* position data by timestamp */ }
});

TimeSlider.setActiveScale('hurricane-ian');  // Switch to tab
TimeSlider.removeScale('hurricane-ian');     // Remove tab
```

**Drill-down flow:**
1. User loads global hurricanes (yearly overview mode)
2. User clicks Hurricane Ian marker
3. System fetches track positions, adds 6-hour tab
4. Animation shows storm path with 6-hour granularity
5. User can switch tabs to return to overview

---

### Disaster-Specific Animation

Each disaster type has specialized animation behavior:

#### Earthquakes (SequenceAnimator)

**Overview mode:** Points sized by magnitude, colored by depth
- Rolling window shows events from current time period
- Flash effect on new events, fade as they age
- Filter to time window based on current speed

**Aftershock drill-down:** Click mainshock to animate sequence
- Mainshock appears first with expanding circle
- Aftershocks appear at their timestamps
- Circles grow/shrink based on magnitude
- Camera follows sequence center
- Adaptive time stepping (1hr to 2days based on sequence length)

```javascript
// Sequence animation creates expanding circles
SequenceAnimator.animate(mainshockId, {
  aftershocks: [...],  // From /api/earthquakes/{id}/aftershocks
  duration: 10000,     // Animation duration in ms
  onComplete: () => TimeSlider.removeScale(id)
});
```

#### Hurricanes (TrackAnimator)

**Overview mode:** Storm positions as points, latest position highlighted
- 6-hour granularity (matches HURDAT2 data)
- Category coloring (1-5 scale)
- Wind speed in knots

**Track drill-down:** Click storm to animate full path
- Animated line follows historical positions
- Current position marker moves along track
- Shows wind speed, pressure, category at each point
- ~10 second animation for typical 7-day storm

```javascript
// Track data from /api/hurricane/track/{storm_id}
TrackAnimator.animate(stormId, {
  positions: [...],  // Array of {timestamp, lat, lon, wind, pressure, category}
  onComplete: callback
});
```

#### Wildfires (Fire Progression)

**Overview mode:** Final fire perimeters as polygons, colored by size
- Points for fires without perimeter data
- Year filtering via time slider

**Progression drill-down:** Click fire to animate spread
- Daily snapshots of cumulative burn area
- Polygon geometry updates each day
- Shows area burned progression
- Uses day_of_burn raster data converted to daily polygons

```javascript
// Progression data from /api/wildfires/{event_id}/progression
handleFireProgression({
  snapshots: [...],  // Array of {date, day_num, area_km2, geometry}
  eventId: fireId,
  totalDays: duration
});
```

**Data source:** Global Fire Atlas day_of_burn rasters + perimeter shapefiles

#### Tsunamis

**Overview mode:** Runup points sized by wave height
- Flash + fade animation during playback
- Colored by wave height (meters)

**No drill-down currently** - tsunamis are point-in-time events

---

### Rolling Window + Fade

Events use a visibility window that scales with speed:

| Speed | Window Duration | Effect |
|-------|-----------------|--------|
| 6h/sec | 24 hours | 4 data points visible |
| 1d/sec | 7 days | 1 week of events |
| 1mo/sec | ~3 months | Quarter's events |
| 1yr/sec | 1 year | Full year visible |

**Flash + Fade effect:**
```javascript
// _recency property: 1.5 = flash, 1.0 = recent, 0.0 = fading out
const flashPeriod = windowDuration * 0.1;  // First 10% of window
const age = currentTime - eventTime;

if (age < flashPeriod) {
  recency = 1.5;  // Flash with size boost
} else {
  recency = 1.0 - (age / windowDuration);  // Linear fade
}
```

### Indexed Scale Mode

For datasets with large time ranges (earthquakes 1900-2024), the slider auto-enables indexed scaling:

- **Trigger:** 50+ data points in time range
- **Behavior:** Each data point gets equal slider space regardless of gaps
- **Benefit:** Ancient events reachable without 10000-year jumps

```javascript
// Auto-detects based on data density
shouldUseIndexedScale() {
  return this.sortedTimes.length >= 50;
}

// Slider position <-> actual time conversion
indexToTime(index)   // Get time value from slider position
timeToIndex(time)    // Get slider position from time value
```

### Internal Timestamp Handling

All time values stored internally as Unix milliseconds for consistent math:

```javascript
// Years auto-converted on input
normalizeToTimestamp(time) {
  if (Math.abs(time) < 50000) {
    return Date.UTC(time, 0, 1);  // Year -> Jan 1 timestamp
  }
  return time;  // Already a timestamp
}

// Display converts back for yearly granularity
formatTimeLabel(timestamp) {
  if (this.granularity === 'yearly') {
    return new Date(timestamp).getUTCFullYear().toString();
  }
  // Other formats for sub-yearly...
}
```

### Data Flow

```
User selects overlay (e.g., "Earthquakes")
                |
                v
        overlay-controller.js
        loads GeoJSON from /api/earthquakes/geojson
                |
                v
        Extracts year range from data
        Initializes TimeSlider with range
                |
                v
        EventAnimator subscribes to time changes
                |
                v
        User adjusts slider or plays animation
                |
                v
        TimeSlider.setTime(timestamp)
        Notifies all subscribers
                |
                v
        EventAnimator filters events to window
        Updates MapLibre layer with visible events
                |
                v
        User clicks event marker
                |
                v
        Drill-down: SequenceAnimator/TrackAnimator
        Adds new tab with finer granularity
```

### Performance

- Geometry loaded once in `baseGeojson`, reused across time changes
- Year data overlaid on features without geometry duplication
- `updateSourceData()` for fast layer updates (no layer recreation)
- 15 FPS animation loop with requestAnimationFrame
- Adaptive time stepping prevents >200 steps for long sequences
- Events outside visible window removed from layer (not just hidden)

---

## Geometry Simplification

Geometries are simplified for web display. See [GEOMETRY.md](GEOMETRY.md#geometry-simplification) for:
- Recommended tolerances by admin level
- File size impacts
- Simplification code examples

---

## Performance Considerations

### Data Loading
- Geometry files loaded on-demand per admin level
- Country parquets are ~1-30 MB each
- Global.csv is ~8 MB (all countries at admin_0)

### Rendering
- MapLibre handles 400K+ polygons efficiently
- Feature state updates for hover/selection are instant
- Choropleth color updates are efficient (paint property changes)

### Memory
- Display table stored in localStorage (~1-5 MB typical)
- Geometry cached in memory for current view
- Older views garbage collected

---

## Future Features

### Data Availability Heat Map

Visual layer showing data richness per location:

```
Heat Score = Geographic Depth x Metric Breadth

Example:
  USA: depth=4 (country/state/county/city), metrics=12 -> score=48
  France: depth=2 (country/city), metrics=6 -> score=12
  Chad: depth=1 (country only), metrics=2 -> score=2
```

### Geometry Merging (On-Demand Union)

Combine smaller regions into larger ones dynamically:
- "Show Europe as one region"
- "Combine Nordic countries"
- Server-side union using Shapely unary_union()

### Export Options

- CSV export of displayed data
- GeoJSON export with geometry
- Include metadata in export

### Click-to-Select Disambiguation (work in progress)

Handle ambiguous queries by letting users click on the map:
- Backend detects "Washington County" = 30 matches
- Frontend displays all matches with markers
- User clicks to select one or multiple

### Result Summary Cards

Show key stats before/alongside map:
- Total, average, min, max for displayed data
- Count of results
- Data source attribution

### Tile Server

Vector tiles for complex polygons:
- Mapbox/MapLibre vector tile integration
- Reduce GeoJSON payload size for large datasets
- Pre-render tiles during ETL

### Advanced Visualization

Enhanced chart and comparison features:
- Charts alongside map (bar/line for time series)
- Toggle between map and data table view
- Side-by-side comparison mode

---

## Disaster Event Architecture

Central routing system for disaster visualizations. Routes event types to appropriate display models via ModelRegistry.

**Key files:**
- [model-registry.js](../static/modules/models/model-registry.js) - Central dispatcher and type routing
- [model-point-radius.js](../static/modules/models/model-point-radius.js) - Point + radius display
- [model-track.js](../static/modules/models/model-track.js) - Track/path display for storms
- [model-polygon.js](../static/modules/models/model-polygon.js) - Polygon display for areas
- [disaster-popup.js](../static/modules/disaster-popup.js) - Unified popup system

See [DISASTER_DISPLAY.md](DISASTER_DISPLAY.md) for complete disaster schemas and display details.

### Model Registry

Routes event types to display models:

```javascript
const TYPE_TO_MODEL = {
  // Point + Radius events
  earthquake: 'point-radius',
  volcano: 'point-radius',
  tornado: 'point-radius',
  tsunami: 'point-radius',
  wildfire: 'point-radius',
  flood: 'point-radius',

  // Track events
  hurricane: 'track',
  typhoon: 'track',
  cyclone: 'track',

  // Polygon events
  ash_cloud: 'polygon',
  drought_area: 'polygon'
};
```

### Central Sequence Dispatcher

Single listener routes `disaster-sequence-request` events to appropriate models:

```
disaster-popup.js                    model-registry.js
     |                                      |
     | dispatch('disaster-sequence-request') |
     +------------------------------------->|
                                            | lookup TYPE_TO_MODEL[eventType]
                                            | call model.handleSequence()
                                            |
            +-------------------------------+
            |
            v
   model-point-radius.js    OR    model-track.js
   (earthquake, tornado,          (hurricane, typhoon,
    tsunami, wildfire, flood)      cyclone)
```

### handleSequence Interface

Each display model implements:

```javascript
async handleSequence(eventId, eventType, props) {
  // Type-specific sequence/animation logic
  // Fetches from API and triggers animation
}
```

**PointRadiusModel handles:**
- earthquake - Aftershock sequences via sequence_id
- tsunami - Runup animations via /api/tsunamis/{id}/animation
- wildfire - Fire progression via /api/wildfires/{id}/progression
- flood - Extent animation via /api/floods/{id}/geometry
- tornado - Outbreak sequences via /api/tornadoes/{id}/sequence

**TrackModel handles:**
- hurricane/typhoon/cyclone - Storm track drill-down animation

### Event Flow

1. User clicks event marker on map
2. DisasterPopup.show() displays popup with action buttons
3. User clicks "Sequence" button
4. DisasterPopup dispatches `disaster-sequence-request` custom event
5. ModelRegistry.setupSequenceDispatcher() listener catches event
6. Dispatcher looks up model via TYPE_TO_MODEL[eventType]
7. Dispatcher calls model.handleSequence(eventId, eventType, props)
8. Model fetches animation data from API
9. Model triggers animation via EventAnimator or direct layer updates

### Related Events

| Event | Purpose | Dispatched By |
|-------|---------|---------------|
| disaster-sequence-request | Trigger sequence animation | disaster-popup.js |
| disaster-related-request | Show related events | disaster-popup.js |
| sequence-change | Notify animation start | model-point-radius.js |
| track-drill-down | Hurricane track animation | model-track.js |

---

## Module Reference

See [FRONTEND_MODULES.md](FRONTEND_MODULES.md) for detailed module documentation.

| Module | Purpose |
|--------|---------|
| MapAdapter | Core map initialization and layer management |
| ChoroplethManager | Color scale calculation and legend |
| TimeSlider | Year range slider and animation |
| PopupBuilder | Format feature properties for display |
| SelectionManager | Disambiguation and selection overlay |

### Related Documentation

- [CHAT.md](CHAT.md) - Chat system, disambiguation, show borders follow-up
- [DISASTER_DISPLAY.md](DISASTER_DISPLAY.md) - Event animation, overlay system, disaster visualization
- [GEOMETRY.md](GEOMETRY.md) - loc_id specification, geometry structure, special entities
- [data_pipeline.md](data_pipeline.md) - Data sources, metadata, folder structure
- [data_import.md](data_import.md) - Quick reference for creating data converters

---

*Last Updated: 2026-01-11*
