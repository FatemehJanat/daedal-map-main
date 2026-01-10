# Disaster Display System Design

Event-based visualization for disasters including earthquakes, hurricanes, wildfires, and tsunamis. Distinct from aggregate county data - shows individual events with animation support.

**Related docs**:
- [MAPPING.md](MAPPING.md) - Time slider and choropleth system
- [data_pipeline.md](data_pipeline.md) - Data structure and metadata
- [FRONTEND_MODULES.md](FRONTEND_MODULES.md) - Module architecture

---

## Global Disaster Data Sources

All disaster data uses **global sources only** - no country-specific duplicates. Each source has live API endpoints for ongoing updates.

| Type | Source | Data Path | Live Update URL | Coverage |
|------|--------|-----------|-----------------|----------|
| **Earthquakes** | USGS Earthquake Catalog | `global/usgs_earthquakes/` | `https://earthquake.usgs.gov/fdsnws/event/1/query` | 1900-present, M2.5+ global |
| **Tropical Storms** | NOAA IBTrACS v04r01 | `global/tropical_storms/` | `https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/` | 1842-present, all basins |
| **Tsunamis** | NOAA NCEI Historical Tsunami Database | `global/tsunamis/` | `https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/tsunamis/` | 2100 BC-present, global |
| **Volcanoes** | Smithsonian Global Volcanism Program | `global/smithsonian_volcanoes/` | `https://volcano.si.edu/database/webservices.cfm` | Holocene epoch, 1,400+ volcanoes |
| **Wildfires** | Global Fire Atlas (NASA/ORNL) | `global/fire_atlas/` | [Zenodo](https://zenodo.org/records/11400062) | 2002-2024, 13.3M fires, daily progression |

### Data Files Per Source

**Earthquakes:**
- `events.parquet` - Individual events (306K+ rows)
- `GLOBAL.parquet` - Country-year aggregates

**Tropical Storms:**
- `storms.parquet` - Storm metadata (13,541 storms)
- `positions.parquet` - 6-hourly track positions (722,507 rows)

**Tsunamis:**
- `events.parquet` - Source events/epicenters (2,619 events)
- `runups.parquet` - Coastal observation points (33,623 runups)

**Volcanoes:**
- `events.parquet` - Eruption events
- `volcanoes.parquet` - Volcano locations

**Wildfires (Global Fire Atlas):**
- `fires.parquet` - Fire events with perimeters (13.3M fires)
- `ignitions.parquet` - Ignition points with fire metadata
- Attributes: fire_id, start/end dates, size, duration, spread speed/direction
- Daily progression polygons for animation

### Alternative Fire Data Sources

| Source | Coverage | Use Case |
|--------|----------|----------|
| **NASA FIRMS** | Global, 2000+, <3h latency | Live heatmap (Climate section), not tracked events |
| **MTBS** | USA only, 1984+, large fires | Higher precision USA analysis (future enhancement) |

NASA FIRMS provides raw satellite hotspot detections - useful for real-time fire activity heatmaps but not individual fire events. Global Fire Atlas clusters these into tracked fire events with perimeters.

### Live Update Pipeline (Future)

See `docs/future/native_refactor.md` for the planned live data architecture:
1. Always-on scraper monitors live APIs
2. Incremental updates to cloud storage (R2/S3)
3. Client sync on startup
4. Same overlay system displays both live and historical

---

## Design Philosophy

The system is designed for worldwide disaster data:

1. **Converters standardize external data** - Messy source data (USGS, NOAA, BOM, etc.) is transformed into clean internal format
2. **Frontend knows only standard patterns** - The display system handles a few known event types, not source-specific formats
3. **USA is the test case** - Most complete disaster data for testing, but system works globally
4. **Same metadata pattern everywhere** - All countries use identical structure (`events.parquet` + `{COUNTRY}.parquet` + `metadata.json`)

When adding new disaster sources (Japan earthquakes, European floods, etc.), only the converter needs source-specific logic. The display system stays unchanged.

---

## Overlay Selector UI

A sidebar control for toggling data overlays without typing queries.

### UI Design

```
+------------------+
| Overlays      [x]|
+------------------+
| v Disasters      |
|   [ ] Earthquakes|
|   [ ] Hurricanes |
|   [ ] Wildfires  |
|   [ ] Volcanoes  |
+------------------+
| > Climate        |
+------------------+
| > Demographics   |
+------------------+
| Last updated:    |
| 5 min ago        |
+------------------+
```

### Overlay Categories

| Category | Overlays | Data Source | Update Frequency |
|----------|----------|-------------|------------------|
| **Disasters** | Earthquakes | usgs_earthquakes/events.parquet | Live (5 min) |
| | Hurricanes | hurricanes/positions.parquet | Seasonal |
| | Wildfires | wildfires/fires.parquet | Live (hourly) |
| | Volcanoes | volcanoes/eruptions.parquet | As needed |
| **Climate** | Wind patterns | (future) NOAA GFS | 6 hours |
| | Air quality | (future) OpenAQ | Hourly |
| | Temperature | (future) NOAA GFS | 6 hours |
| **Demographics** | Population | census_population | Annual |
| | Density | census_population (derived) | Annual |

### State Management

```javascript
// overlay-manager.js
const OverlayManager = {
  // Current overlay states
  overlays: {
    earthquakes: { enabled: false, layer: null, lastUpdate: null },
    hurricanes: { enabled: false, layer: null, lastUpdate: null },
    wildfires: { enabled: false, layer: null, lastUpdate: null },
    volcanoes: { enabled: false, layer: null, lastUpdate: null }
  },

  // Toggle overlay on/off
  toggle(overlayId) {
    const overlay = this.overlays[overlayId];
    if (!overlay) return;

    overlay.enabled = !overlay.enabled;

    if (overlay.enabled) {
      this.loadOverlay(overlayId);
    } else {
      this.removeOverlay(overlayId);
    }

    // Notify chat of context change
    this.updateChatContext();
  },

  // Get active overlays for chat context
  getActiveOverlays() {
    return Object.entries(this.overlays)
      .filter(([_, state]) => state.enabled)
      .map(([id, _]) => id);
  },

  // Update chat with current context
  updateChatContext() {
    const active = this.getActiveOverlays();
    // Chat now knows: "User has earthquakes and wildfires overlays active"
    ChatModule.setOverlayContext(active);
  }
};
```

### Chat Integration

When overlays are active, the chat has context about what the user is looking at:

**Without overlay context:**
```
User: "What happened here?"
Chat: "I need more context. What are you referring to?"
```

**With overlay context (earthquakes enabled):**
```
User: "What happened here?"
Chat: "I see you have the earthquakes overlay active. Looking at your
current map view, there was a M5.2 earthquake on Jan 5th near Hollister, CA.
Would you like more details about this event?"
```

### Layer Loading

```javascript
// Load overlay data from parquet via backend
async loadOverlay(overlayId) {
  const config = OVERLAY_CONFIG[overlayId];

  const response = await fetch('/api/overlay', {
    method: 'POST',
    body: JSON.stringify({
      source_id: config.source_id,
      event_file: config.event_file,
      bounds: MapAdapter.getBounds(),  // Only load visible area
      limit: config.limit || 1000
    })
  });

  const data = await response.json();

  // Add to map using event layer system
  MapAdapter.loadEventLayer(data.geojson, config.eventType, {
    showRadius: config.showRadius,
    layerId: `overlay-${overlayId}`
  });

  this.overlays[overlayId].layer = `overlay-${overlayId}`;
  this.overlays[overlayId].lastUpdate = new Date();
}
```

### Configuration

```javascript
const OVERLAY_CONFIG = {
  earthquakes: {
    source_id: 'usgs_earthquakes',
    event_file: 'events',
    eventType: 'earthquake',
    showRadius: true,
    limit: 1000,
    refreshInterval: 5 * 60 * 1000,  // 5 minutes
    icon: 'seismic',
    color: '#f03b20'
  },
  hurricanes: {
    source_id: 'hurricanes',
    event_file: 'positions',
    eventType: 'hurricane-point',
    showRadius: false,
    limit: 500,
    refreshInterval: null,  // No auto-refresh (seasonal)
    icon: 'storm',
    color: '#0571b0'
  },
  wildfires: {
    source_id: 'wildfires',
    event_file: 'fires',
    eventType: 'wildfire',
    showRadius: false,
    limit: 500,
    refreshInterval: 60 * 60 * 1000,  // 1 hour
    icon: 'fire',
    color: '#bd0026'
  },
  volcanoes: {
    source_id: 'volcanoes',
    event_file: 'eruptions',
    eventType: 'volcano',
    showRadius: true,
    limit: 200,
    refreshInterval: null,
    icon: 'mountain',
    color: '#fd8d3c'
  }
};
```

### Auto-Refresh (Live Mode)

When overlay has `refreshInterval`, auto-update in background:

```javascript
startAutoRefresh(overlayId) {
  const config = OVERLAY_CONFIG[overlayId];
  if (!config.refreshInterval) return;

  this.overlays[overlayId].refreshTimer = setInterval(() => {
    if (this.overlays[overlayId].enabled) {
      this.loadOverlay(overlayId);
      this.showRefreshIndicator(overlayId);
    }
  }, config.refreshInterval);
}
```

### Viewport-Based Loading

Only load events within current map bounds to keep performance reasonable:

```javascript
// When map moves, reload visible overlays
MapAdapter.map.on('moveend', debounce(() => {
  const activeOverlays = OverlayManager.getActiveOverlays();
  for (const id of activeOverlays) {
    OverlayManager.loadOverlay(id);
  }
}, 500));
```

### Implementation Priority

1. **Earthquakes overlay** - Best test case (point+radius, live updates)
2. **Wildfires overlay** - Different display type (polygons)
3. **Hurricanes overlay** - Track animation complexity
4. **Climate overlays** - Requires new data sources

---

## Frontend Module Architecture

### Current Problem

The `map-adapter.js` file (1700+ lines) contains ALL rendering logic mixed together:
- Earthquake rendering
- Volcano rendering
- Hurricane points and tracks
- Generic event handling

This makes it difficult to add new disaster types and maintain the code.

### Solution: 4 Display Model Files

Split rendering into specialized model files based on visualization type:

```
static/modules/
  models/                        # NEW directory
    model-point-radius.js        # Model A: Earthquakes, Volcanoes, Tornadoes
    model-track.js               # Model B: Hurricanes, animated tracks
    model-polygon.js             # Model C: Wildfires, floods (polygon areas)
    model-registry.js            # Routes data to correct model
  overlay-selector.js            # NEW: UI component (top right)
  choropleth.js                  # Model D: Already exists (aggregates)
  map-adapter.js                 # Refactored: basic map ops only
```

### The 4 Display Models

| Model | File | Renders | Time Behavior |
|-------|------|---------|---------------|
| **A: Point+Radius** | model-point-radius.js | Earthquakes, Volcanoes, Tornadoes | Static (filter by year) |
| **B: Track/Trail** | model-track.js | Hurricanes, Cyclones | Animated (6h positions) |
| **C: Polygon/Area** | model-polygon.js | Wildfires, Floods | Static or animated |
| **D: Choropleth** | choropleth.js (existing) | Census, metrics, aggregates | Year slider (existing) |

### Model Interface

All models implement this interface:

```javascript
const ModelInterface = {
  id: 'model-id',
  supportedTypes: ['earthquake', 'volcano'],

  render(geojson, eventType, options),  // Load and display
  update(geojson),                       // Update data (time filter)
  clear(),                               // Remove layers
  fitBounds(geojson),                    // Zoom to data
  buildPopupHtml(properties, eventType)  // Popup content
};
```

### Overlay Selector UI (Revised)

**Location**: Top right, below zoom level and breadcrumbs

```
+------------------------------------------+
|  [Zoom: 5.2]  [USA > California > ...]   |
+------------------------------------------+
|  [Overlays]                              |
|    [x] Demographics (default, always on) |
|    [ ] Earthquakes                       |
|    [ ] Hurricanes                        |
|    [ ] Wildfires                         |
|    [ ] Volcanoes                         |
+------------------------------------------+
```

**Key behaviors:**
- Demographics is checked by default, serves as base layer
- Clicking overlays toggles visibility
- Active selections passed to LLM preprocessor for query context
- Multiple disaster overlays can be active simultaneously

### Model Registry

Routes event types to correct model:

```javascript
const typeToModel = {
  // Point + Radius events
  earthquake: 'point-radius',
  volcano: 'point-radius',
  tornado: 'point-radius',

  // Track events
  hurricane: 'track',
  typhoon: 'track',
  cyclone: 'track',

  // Polygon events
  wildfire: 'polygon',
  flood: 'polygon'
};

// Usage in app.js
ModelRegistry.render(data.geojson, eventType, options);
```

### Phase 1: Infrastructure + Visual UI [COMPLETE]

**Step 1: Create model directory structure** - DONE
- Created `static/modules/models/` folder
- Created `model-registry.js` with routing logic

**Step 2: Create overlay selector UI** - DONE
- Created `overlay-selector.js` module
- Added HTML element to templates/index.html (top right panel)
- Styled to match dark theme
- Demographics checked by default

**Step 3: Wire up selector** - DONE
- Connected selector to app.js
- Exposed active overlays for preprocessor context
- Toggle functionality working

**Step 4: Create model files** - DONE
- Created all model files with full implementation
- Wired dependencies via existing pattern

### Phase 2: Point+Radius Model [COMPLETE]

Extracted earthquake/volcano rendering from map-adapter.js into `model-point-radius.js`:
- Magnitude-based circle sizing
- Felt/damage radius circles for earthquakes
- VEI-based sizing for volcanoes
- Popup HTML generation

### Phase 2b: Aftershock Sequence Animation [COMPLETE]

Added `sequence-animator.js` for visualizing earthquake aftershock sequences:

**Features:**
- "Ripples in a pond" effect - circles grow from epicenter
- "Spiderweb" connection lines from mainshock to aftershocks
- Geographic radius circles (felt + damage) scale with zoom
- Viewport auto-zooms from damage radius to full sequence extent
- Adaptive time stepping (200 max steps regardless of duration)

**Gardner-Knopoff Windows:**
```python
# Time window: 10^(0.5*M - 1.5) days
# Distance window: 10^(0.5*M - 0.5) km
# M7.0: ~10 days, ~100 km
# M8.0: ~32 days, ~316 km
```

**Activation:**
- Click earthquake with aftershocks -> "View Aftershock Sequence" button in popup
- TimeSlider adds new scale tab for sequence (adaptive granularity)
- Exit button returns to normal earthquake view

**Adaptive Time Stepping:**
```javascript
const MAX_STEPS = 200;
const MIN_STEP_MS = 1 * 60 * 60 * 1000;  // 1 hour minimum
const adaptiveStepMs = Math.max(MIN_STEP_MS, Math.ceil(timeRange / MAX_STEPS));
```
This ensures animations complete in ~200 steps whether the sequence is hours or months long.

### Phase 2c: Unified EventAnimator [IN PROGRESS]

Created `event-animator.js` to unify animation patterns across disaster types:

**Motivation:**
Previously had separate animators (SequenceAnimator for earthquakes, TrackAnimator for hurricanes) with duplicated logic for TimeSlider integration, exit callbacks, and layer management.

**Architecture:**

```
EventAnimator (unified controller)
  |
  +-- Animation Modes
  |     - ACCUMULATIVE: Events appear and stay (earthquakes, volcanoes)
  |     - PROGRESSIVE: Track grows, current position highlighted (hurricanes)
  |     - POLYGON: Areas change over time (wildfires, floods)
  |
  +-- Common Infrastructure
  |     - TimeSlider multi-scale integration (addScale/setActiveScale/removeScale)
  |     - Exit button and cleanup callbacks
  |     - Time stepping and playback
  |     - Layer lifecycle management
  |
  +-- Rendering Delegation
        - Routes to existing models: model-point-radius, model-track, model-polygon
        - Models handle visualization specifics (colors, sizes, symbols)
```

**Usage:**

```javascript
import { EventAnimator, AnimationMode } from './event-animator.js';

// Start earthquake sequence animation
EventAnimator.start({
  id: 'seq-abc123',
  label: 'M7.1 Jan 5',
  mode: AnimationMode.ACCUMULATIVE,
  events: earthquakeFeatures,
  timeField: 'timestamp',
  granularity: '6h',
  renderer: 'point-radius',
  onExit: () => restoreNormalView()
});

// Start hurricane track animation
EventAnimator.start({
  id: 'track-2005236N23285',
  label: 'Katrina',
  mode: AnimationMode.PROGRESSIVE,
  events: trackPositions,
  timeField: 'timestamp',
  granularity: '6h',
  renderer: 'track',
  onExit: () => restoreYearlyView()
});

// Future: wildfire spread animation
EventAnimator.start({
  id: 'fire-camp2018',
  label: 'Camp Fire',
  mode: AnimationMode.POLYGON,
  events: dailyPerimeters,
  timeField: 'date',
  granularity: 'daily',
  renderer: 'polygon',
  onExit: () => restoreStaticView()
});
```

**Key Behaviors by Mode:**

| Mode | Display Logic | TimeSlider Behavior |
|------|---------------|---------------------|
| ACCUMULATIVE | Events appear at timestamp, stay visible | Shows count of visible events |
| PROGRESSIVE | Track grows, only current position active | Shows track progress X/Y positions |
| POLYGON | Area state at exact timestamp | Shows snapshot date |

**Rolling Window + Fade:**

Events don't just appear and stay forever - they use a rolling window based on time granularity with opacity fading:

```javascript
// Window duration based on selected granularity
const WINDOW_DURATIONS = {
  '6h': 24 * 60 * 60 * 1000,      // 24h window (4 data points)
  'daily': 7 * 24 * 60 * 60 * 1000,  // 7 day window
  'weekly': 28 * 24 * 60 * 60 * 1000, // 4 week window
  'monthly': 90 * 24 * 60 * 60 * 1000, // ~3 months
  'yearly': 365 * 24 * 60 * 60 * 1000  // 1 year window
};

// For continuous events like storms, detect when they've "ended"
// Uses 4x the expected update interval as threshold
const INACTIVITY_MULTIPLIER = 4;
const UPDATE_INTERVALS = {
  storm: 6 * 60 * 60 * 1000,      // 6h updates -> 24h threshold
  wildfire: 24 * 60 * 60 * 1000,  // Daily updates -> 4 day threshold
  flood: 24 * 60 * 60 * 1000,     // Daily updates -> 4 day threshold
  default: null                    // Uses animation granularity
};
// Point-in-time events: earthquake, volcano, tornado, tsunami (threshold = 0)
```

**Opacity Calculation:**
- New events appear at full opacity (1.0)
- As events age within the window, opacity decreases linearly
- Events beyond window boundary are removed
- This creates a "rolling view" of what's happening NOW while showing recent context

```javascript
// Each feature gets a _recency property (0-1)
// Renderers multiply base opacity by _recency
'circle-opacity': ['*', 0.9, ['coalesce', ['get', '_recency'], 1.0]]
```

**Visual Result:**
```
Timeline: [----window----][current]
          ^              ^
          fading out     full opacity

Time -->  Jan     Feb     Mar     Apr (current)
          |       |       |       |
Events:   [dim]   [faded] [visible] [BRIGHT]
          0.2     0.4     0.7      1.0 opacity
```

**Files:**
- `static/modules/event-animator.js` - Unified animation controller with rolling window
- `static/modules/models/model-point-radius.js` - Updated with _recency opacity
- `static/modules/models/model-track.js` - Updated with _recency trail fade
- Existing animators (sequence-animator.js, track-animator.js) to be refactored to use EventAnimator

### Phase 3: Track Model [COMPLETE]

Extracted hurricane track rendering into `model-track.js`:
- Storm marker rendering with Saffir-Simpson colors
- Track line rendering with position dots
- Category-based color expressions
- Storm drill-down support

### Phase 4: Polygon Model [COMPLETE]

Created new `model-polygon.js` for area-based events:
- Wildfires, floods, ash clouds, drought areas
- Fill with transparency + stroke outline
- Severity/status-based color coding
- Label rendering

### Phase 5: Backend Integration [COMPLETE]

Created `overlay-controller.js` to orchestrate data loading:
- Listens to OverlaySelector toggle events
- Fetches data from API endpoints
- Caches full datasets client-side
- Filters by TimeSlider year and re-renders

Added API endpoints to `app.py`:
- `/api/earthquakes/geojson` - Earthquake events
- `/api/volcanoes/geojson` - Volcano locations
- `/api/eruptions/geojson` - Volcanic eruptions
- `/api/wildfires/geojson` - Wildfire events

### Files Created/Modified

| File | Status | Description |
|------|--------|-------------|
| static/modules/models/model-point-radius.js | NEW | Earthquakes, volcanoes (~320 lines) |
| static/modules/models/model-track.js | NEW | Hurricanes, tracks (~370 lines) |
| static/modules/models/model-polygon.js | NEW | Wildfires, polygons (~320 lines) |
| static/modules/models/model-registry.js | NEW | Routes types to models |
| static/modules/overlay-selector.js | NEW | UI component |
| static/modules/overlay-controller.js | NEW | Data loading + sequence orchestration |
| static/modules/sequence-animator.js | NEW | Aftershock sequence animation (~850 lines) |
| static/modules/track-animator.js | NEW | Hurricane track animation (~600 lines) |
| static/modules/event-animator.js | NEW | Unified animation controller (~400 lines) |
| static/modules/time-slider.js | MODIFIED | Indexed scale, listener system, multi-scale tabs |
| static/modules/map-adapter.js | MODIFIED | Delegates to models |
| static/modules/app.js | MODIFIED | Initializes all components |
| app.py | MODIFIED | Added API endpoints + sequence endpoint |
| templates/index.html | MODIFIED | Added overlay selector div |
| static/css/style.css | MODIFIED | Overlay selector styling |

---

## Overview

The disaster display system handles TWO distinct modes:

| Mode | Data Source | Visualization | Example |
|------|-------------|---------------|---------|
| **Aggregate** | `USA.parquet` | Choropleth (counties colored by value) | "Show earthquake counts by county 2020" |
| **Event** | `events.parquet` / `fires.parquet` / `positions.parquet` | Points, tracks, polygons | "Show 2024 California wildfires" |

The existing system handles aggregate mode well. This document focuses on **event mode**.

---

## Data File Structure

All disaster data uses global paths under `county-map-data/global/`:

### Earthquakes (global/usgs_earthquakes/)
```
events.parquet     # Individual events with lat/lon/magnitude/radius
GLOBAL.parquet     # Country-year aggregates
metadata.json
```

### Tropical Storms (global/tropical_storms/)
```
storms.parquet     # Storm metadata (13,541 storms)
positions.parquet  # 6-hourly track positions (722,507 positions)
metadata.json
```

### Tsunamis (global/tsunamis/)
```
events.parquet     # Source epicenters (2,619 events)
runups.parquet     # Coastal observations (33,623 runups)
metadata.json
```

### Volcanoes (global/smithsonian_volcanoes/)
```
events.parquet     # Eruption events
volcanoes.parquet  # Volcano locations
metadata.json
```

### Active Fires (global/nasa_firms/)
```
events.parquet     # Fire detections with FRP intensity
metadata.json
```
Columns: event_id, timestamp, latitude, longitude, frp, brightness, confidence, sensor, daynight

### Wildfires (countries/USA/wildfires/) - USA only, large fires
```
fires.parquet      # Individual fires with centroid lat/lon and acres
USA.parquet        # County-year aggregates (fire_count, total_acres)
metadata.json
```

### Metadata Files Descriptor

The `files` object in metadata.json already describes event files:

```json
{
  "files": {
    "aggregate": {
      "name": "USA.parquet",
      "description": "County-level aggregated statistics"
    },
    "events": {
      "name": "events.parquet",
      "description": "Individual earthquake records"
    }
  }
}
```

---

## Event Data Standardization

### Standard Column Patterns

All event files follow these naming conventions (validated during testing):

| Pattern | Columns | Example |
|---------|---------|---------|
| **Position** | `lat`, `lon` or `latitude`, `longitude` | 37.8, -122.4 |
| **Time** | `timestamp` or `event_date` | 2024-04-05T14:32:00Z |
| **ID** | `event_id` or `{type}_id` | "EQ2024001", "AL142024" |
| **Severity** | `magnitude`, `category`, `wind_kt`, `acres` | 5.2, "Cat3", 120, 50000 |
| **Location** | `loc_id` | "USA-CA-06037", "AUS-NSW" |

### Observed Schemas

**Earthquakes (USA, Canada):**
```
timestamp, lat, lon, magnitude, depth_km, felt_radius_km, damage_radius_km, place, loc_id
```

**Hurricanes/Cyclones (USA, Australia):**
```
storm_id, timestamp, lat, lon, wind_kt, pressure_mb, category, loc_id
```

**Wildfires (USA):**
```
event_id, fire_name, ignition_date, burned_acres, centroid_lat, centroid_lon, perimeter, loc_id
```
Note: `perimeter` is a GeoJSON string containing the simplified fire boundary polygon.

### Converter Responsibility

Each converter transforms source-specific formats to these standards:

```python
# Example: USGS uses 'mag', internal uses 'magnitude'
df['magnitude'] = df['mag'].round(2)

# Example: BOM uses separate lat/lon columns
df['lat'] = df['LAT'].astype(float)
df['lon'] = df['LON'].astype(float)

# All converters must output: timestamp/lat/lon/loc_id + type-specific fields
```

The frontend reads these standardized columns regardless of original source format.

---

## Event Type Taxonomy

### Display Model Categories

**Model A: Point + Radius** (epicenter with calculated impact zone)
- Single location event
- Radius calculated from magnitude/intensity
- Good for: Earthquakes, Volcanoes, Tornadoes

**Model B: Track/Trail** (series of timestamped positions)
- Moving event over time
- Optional wind/impact radii at each position
- Good for: Hurricanes, Cyclones

**Model C: Polygon/Area** (geographic shape changing over time)
- Area-based events
- Requires polygon geometry per time step
- Good for: Wildfires, Floods
- Note: MTBS wildfire perimeters now available in fires.parquet as GeoJSON strings

**Model D: Choropleth on Counties** (aggregated area status)
- Weekly/monthly snapshots on admin boundaries
- No event-specific geometry
- Good for: Drought conditions (weekly severity by county)

**Model E: Radial Propagation** (source point -> multiple destination points)
- Central source event (earthquake/volcano epicenter)
- Multiple observation/impact points radiating outward
- Distance-based timing (closer points appear first in animation)
- Optional lines connecting source to destinations
- Good for: Tsunamis (source + runup observations), Volcanic ash clouds, Earthquake-triggered events
- Uses same cross-event linking pattern as volcano->earthquake drill-down

### Current Data Reality

| Type | Model | Time Scale | Key Fields | Notes |
|------|-------|------------|------------|-------|
| **Earthquake** | A (point+radius) | Daily | lat, lon, magnitude, felt_radius_km, damage_radius_km | Radius pre-calculated |
| **Volcano** | A (point+radius) | Yearly | lat, lon, VEI | Could calculate radius from VEI |
| **Tornado** | A (point+radius) | Daily | lat, lon, event_radius_km, tornado_scale | Already has radius! |
| **Hurricane/Cyclone** | B (track) | 6-hourly | lat, lon, wind_kt, category, r34/r50/r64 radii | Full track positions |
| **Tsunami** | E (radial) | Daily | source lat/lon, eq_magnitude, runup water_height_m, dist_from_source_km | Source + runup observations |
| **Wildfire** | C (polygon) | Daily | centroid_lat, centroid_lon, burned_acres, perimeter | Perimeter polygons NOW AVAILABLE |
| **Drought** | D (choropleth) | Weekly | severity levels D0-D4 by county | Use existing choropleth system |

### Polygon Data (Model C)

**Available:**
- MTBS burn perimeters - stored as `perimeter` GeoJSON column in fires.parquet (simplified for web)

**Future:**
- NOAA flood extent polygons
- Active fire perimeters from VIIRS/MODIS
- These would follow same pattern: `perimeter` column with GeoJSON string

---

## Order Schema Extension

### Current Order Format (Aggregate Mode)
```json
{
  "items": [
    {
      "source_id": "usgs_earthquakes",
      "metric": "earthquake_count",
      "region": "California",
      "year": 2024
    }
  ]
}
```

### New Order Format (Event Mode)
```json
{
  "items": [
    {
      "source_id": "usgs_earthquakes",
      "mode": "events",
      "event_file": "events",
      "region": "California",
      "year_start": 2024,
      "year_end": 2024,
      "filters": {
        "magnitude_min": 4.0
      },
      "limit": 1000
    }
  ]
}
```

### New Fields

| Field | Type | Description |
|-------|------|-------------|
| `mode` | string | `"events"` or `"aggregate"` (default) |
| `event_file` | string | Key from metadata.files (e.g., `"events"`, `"positions"`, `"fires"`) |
| `filters` | object | Field-specific filters (magnitude_min, category, etc.) |
| `limit` | int | Max events to return (performance cap) |

---

## Backend Changes

### order_executor.py Additions

```python
def load_event_data(source_id: str, event_file_key: str) -> pd.DataFrame:
    """
    Load event-level parquet instead of aggregate.

    Args:
        source_id: e.g., "usgs_earthquakes"
        event_file_key: Key from metadata.files (e.g., "events", "positions")

    Returns:
        DataFrame with individual events
    """
    source_dir = _get_source_path(source_id)
    meta_path = source_dir / "metadata.json"

    with open(meta_path) as f:
        metadata = json.load(f)

    # Get filename from metadata.files
    file_info = metadata.get("files", {}).get(event_file_key)
    if not file_info:
        raise ValueError(f"No event file '{event_file_key}' in {source_id}")

    parquet_path = source_dir / file_info["name"]
    return pd.read_parquet(parquet_path)


def execute_event_order(order: dict) -> dict:
    """
    Execute order in event mode.

    Returns:
        {
            "type": "events",
            "event_type": "earthquake",  # For renderer selection
            "geojson": {...},            # Point features
            "time_data": {...},          # Keyed by timestamp
            "time_range": {...},
            "granularity": "daily",
            "summary": "..."
        }
    """
    item = order["items"][0]  # Event mode = single source

    df = load_event_data(item["source_id"], item["event_file"])

    # Apply filters
    if item.get("filters"):
        for field, value in item["filters"].items():
            if field.endswith("_min"):
                col = field[:-4]
                df = df[df[col] >= value]
            elif field.endswith("_max"):
                col = field[:-4]
                df = df[df[col] <= value]

    # Apply year range
    if "year_start" in item and "year_end" in item:
        df = df[(df["year"] >= item["year_start"]) &
                (df["year"] <= item["year_end"])]

    # Apply region filter (loc_id prefix)
    if item.get("region"):
        region_codes = expand_region(item["region"])
        if region_codes:
            # Filter by loc_id prefix match
            df = df[df["loc_id"].str.startswith(tuple(region_codes))]

    # Apply limit
    limit = item.get("limit", 1000)
    if len(df) > limit:
        df = df.nlargest(limit, "magnitude" if "magnitude" in df.columns else df.columns[0])

    # Build GeoJSON and time_data
    return build_event_response(df, item)
```

### Response Format

```json
{
  "type": "events",
  "event_type": "earthquake",
  "geojson": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-122.4, 37.8]},
        "properties": {
          "event_id": 12345,
          "magnitude": 5.2,
          "felt_radius_km": 31.6,
          "damage_radius_km": 10.0,
          "timestamp": "2024-04-05T14:32:00Z",
          "place": "10km NE of Hollister, CA"
        }
      }
    ]
  },
  "time_data": {
    "1712327520000": {
      "12345": {"magnitude": 5.2, "felt_radius_km": 31.6}
    }
  },
  "time_range": {
    "min": 1704067200000,
    "max": 1735689600000,
    "available": [1704067200000, 1704153600000, ...]
  },
  "granularity": "daily",
  "summary": "Showing 847 earthquakes M4.0+ in California (2024)"
}
```

---

## Frontend Changes

### Map Layer Types

Extend MapAdapter with generalized event layer support:

```javascript
// map-adapter.js additions

const EVENT_LAYER_CONFIG = {
  earthquake: {
    type: 'circle',
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['get', 'magnitude'],
        3, 4,
        5, 12,
        7, 30
      ],
      'circle-color': ['interpolate', ['linear'], ['get', 'magnitude'],
        3, '#ffeda0',
        5, '#feb24c',
        7, '#f03b20'
      ],
      'circle-opacity': 0.7,
      'circle-stroke-width': 1,
      'circle-stroke-color': '#333'
    }
  },

  'earthquake-radius': {
    type: 'circle',
    paint: {
      'circle-radius': ['/', ['get', 'felt_radius_km'], 0.1],  // km to pixels (approx)
      'circle-color': 'transparent',
      'circle-stroke-width': 2,
      'circle-stroke-color': '#f03b20',
      'circle-stroke-opacity': 0.5
    }
  },

  wildfire: {
    type: 'circle',
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['get', 'acres'],
        1000, 6,
        10000, 15,
        100000, 40
      ],
      'circle-color': ['interpolate', ['linear'], ['get', 'acres'],
        1000, '#fed976',
        10000, '#fd8d3c',
        100000, '#bd0026'
      ],
      'circle-opacity': 0.6
    }
  },

  'hurricane-point': {
    // Already exists - category-based colors
  },

  'hurricane-track': {
    type: 'line',
    paint: {
      'line-color': '#666',
      'line-width': 2,
      'line-dasharray': [2, 2]
    }
  },

  tsunami: {
    type: 'circle',
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['get', 'runup_m'],
        1, 5,
        10, 15,
        30, 35
      ],
      'circle-color': '#0571b0',
      'circle-stroke-color': '#034e7b'
    }
  }
};

/**
 * Load event layer with appropriate styling.
 * @param {Object} geojson - GeoJSON FeatureCollection
 * @param {string} eventType - 'earthquake', 'wildfire', 'hurricane-point', etc.
 * @param {Object} options - Additional options
 */
loadEventLayer(geojson, eventType, options = {}) {
  const config = EVENT_LAYER_CONFIG[eventType];
  if (!config) {
    console.warn(`Unknown event type: ${eventType}`);
    return;
  }

  // Add source
  this.map.addSource('events', {
    type: 'geojson',
    data: geojson
  });

  // Add layer
  this.map.addLayer({
    id: 'events-layer',
    type: config.type,
    source: 'events',
    paint: config.paint
  });

  // Add radius layer for earthquakes
  if (eventType === 'earthquake' && options.showRadius) {
    this.map.addLayer({
      id: 'events-radius',
      type: 'circle',
      source: 'events',
      paint: EVENT_LAYER_CONFIG['earthquake-radius'].paint
    });
  }
}

/**
 * Update event layer with time-filtered data.
 * @param {Object} filteredGeojson - GeoJSON for current timestamp
 */
updateEventLayer(filteredGeojson) {
  const source = this.map.getSource('events');
  if (source) {
    source.setData(filteredGeojson);
  }
}

/**
 * Clear event layers.
 */
clearEventLayer() {
  if (this.map.getLayer('events-layer')) {
    this.map.removeLayer('events-layer');
  }
  if (this.map.getLayer('events-radius')) {
    this.map.removeLayer('events-radius');
  }
  if (this.map.getSource('events')) {
    this.map.removeSource('events');
  }
}
```

### TimeSlider Event Mode Integration

```javascript
// time-slider.js additions

/**
 * Initialize slider in event mode.
 * @param {Object} response - Backend response with event data
 */
initEventMode(response) {
  this.mode = 'events';
  this.eventType = response.event_type;
  this.baseGeojson = response.geojson;
  this.timeData = response.time_data;
  this.granularity = response.granularity;

  // Build available timestamps
  this.availableTimestamps = Object.keys(this.timeData)
    .map(t => parseInt(t))
    .sort((a, b) => a - b);

  this.minTime = this.availableTimestamps[0];
  this.maxTime = this.availableTimestamps[this.availableTimestamps.length - 1];

  // Update slider range
  this.slider.min = this.minTime;
  this.slider.max = this.maxTime;
  this.slider.value = this.minTime;

  // Initial render
  this.setTimestamp(this.minTime);
  this.show();
}

/**
 * Set current timestamp and update map.
 * @param {number} timestamp - Unix timestamp in ms
 */
setTimestamp(timestamp) {
  const eventsAtTime = this.timeData[timestamp] || {};

  // Filter base GeoJSON to only events at this timestamp
  const filteredFeatures = this.baseGeojson.features.filter(f => {
    const eventId = f.properties.event_id;
    return eventsAtTime[eventId] !== undefined;
  });

  // Update feature properties with time-specific data
  for (const feature of filteredFeatures) {
    const eventId = feature.properties.event_id;
    const timeProps = eventsAtTime[eventId];
    Object.assign(feature.properties, timeProps);
  }

  const filteredGeojson = {
    type: 'FeatureCollection',
    features: filteredFeatures
  };

  MapAdapter.updateEventLayer(filteredGeojson);
  this.updateLabel(timestamp);
}
```

---

## Performance Limits

### Event Query Caps

| Event Type | Default Limit | Max Limit | Rationale |
|------------|---------------|-----------|-----------|
| Earthquake | 1,000 | 5,000 | Point features are lightweight |
| Hurricane Track | 500 positions | 2,000 | 6-hourly = ~160 per storm |
| Wildfire | 500 | 2,000 | Larger markers |
| Tsunami | 500 | 1,000 | Rare events |

### Time Range Caps

| Granularity | Max Time Span | Resulting Steps |
|-------------|---------------|-----------------|
| 6h | 6 months | ~730 steps |
| daily | 2 years | ~730 steps |
| weekly | 10 years | ~520 steps |

### Implementation

```python
# order_executor.py

EVENT_LIMITS = {
    "earthquake": {"default": 1000, "max": 5000},
    "hurricane": {"default": 500, "max": 2000},
    "wildfire": {"default": 500, "max": 2000},
    "tsunami": {"default": 500, "max": 1000},
}

TIME_RANGE_LIMITS = {
    "6h": timedelta(days=180),
    "daily": timedelta(days=730),
    "weekly": timedelta(days=3650),
}

def apply_limits(df, event_type, requested_limit=None):
    limits = EVENT_LIMITS.get(event_type, {"default": 1000, "max": 5000})
    limit = min(requested_limit or limits["default"], limits["max"])

    if len(df) > limit:
        # Sort by significance (magnitude, acres, wind, etc.)
        sort_col = get_significance_column(event_type)
        df = df.nlargest(limit, sort_col)

    return df
```

---

## API Endpoints

### Event Query
```
POST /api/query
{
  "items": [{
    "source_id": "usgs_earthquakes",
    "mode": "events",
    "event_file": "events",
    "region": "California",
    "year_start": 2024,
    "year_end": 2024,
    "filters": {"magnitude_min": 4.0},
    "limit": 500
  }]
}
```

### Hurricane Track (Existing)
```
GET /api/hurricane/track/{storm_id}
```

---

## UI Behavior

### Event Mode Activation

1. User query triggers event detection:
   - "Show me earthquakes in California" -> event mode
   - "Show earthquake counts by county" -> aggregate mode

2. LLM postprocessor sets `mode: "events"` when:
   - Query mentions "show [events]" without aggregation words
   - Query asks for specific events ("M5+ earthquakes")
   - Query asks for timeline/animation

3. Frontend detects `response.type === "events"` and:
   - Loads event layer instead of choropleth
   - Initializes TimeSlider in event mode
   - Sets appropriate granularity

### Animation Playback

| Event Type | Default Speed | Granularity |
|------------|---------------|-------------|
| Hurricane | 100ms/step | 6h |
| Earthquake | 200ms/step | daily |
| Wildfire | 300ms/step | daily |

### Legend

Event mode legend differs from choropleth:

```
Earthquakes
o M3.0-3.9
O M4.0-4.9
@ M5.0-5.9
[X] Show felt radius
```

---

## Implementation Phases

### Phase 1: Model A - Point + Radius [COMPLETE]
Earthquakes and volcanoes - simplest display model.

**Backend:**
- [x] Add `mode: "events"` field to order schema
- [x] Add event loading to API endpoints
- [x] Add event type detection to postprocessor

**Frontend:**
- [x] Create generalized `loadEventLayer()` in MapAdapter
- [x] Earthquake point layer (magnitude-sized circles)
- [x] Felt radius circle overlay (uses felt_radius_km)
- [x] Damage radius circle overlay (uses damage_radius_km)
- [x] TimeSlider integration for year-based filtering

**Data fields used:**
- lat, lon - Event location
- magnitude - Circle size
- felt_radius_km - Outer impact circle
- damage_radius_km - Inner damage circle
- year - TimeSlider filtering

### Phase 2: Model B - Track/Trail (Hurricanes) [testing]
- [x] Migrate HurricaneHandler to generalized event system
- [x] Track line rendering (connect positions)
- [x] Category-based coloring (Saffir-Simpson scale)
- [x] Storm drill-down for individual track display

### Phase 3: Model C - Polygon/Area (Wildfires) [incomplete]
- [x] Polygon fill + stroke rendering
- [x] Severity/status-based color coding
- [x] Label rendering for fire names
- [x] Year-based filtering via TimeSlider

### Phase 4: Model D - Choropleth Events (Drought)
- [ ] Weekly drought severity by county
- [ ] Use existing choropleth system
- [ ] Weekly granularity animation

### Phase 5: Additional Sources [PARTIAL]
- [ ] Tornado points (Model A)
- [x] Volcano eruptions (Model A) - Full implementation with cross-linking
- [ ] Tsunami runups (Model A)
- [ ] NOAA storm events (Model A)

---

## Recent Updates (2026-01-09)

### Data Source Cleanup
Removed country-specific duplicate data in favor of global sources:
- **Deleted**: `countries/USA/hurricanes/` (subset of IBTrACS)
- **Deleted**: `countries/USA/tsunamis/` (subset of global)
- **Deleted**: `countries/USA/usgs_earthquakes/` (subset of global)
- **Deleted**: `countries/USA/volcanoes/` (subset of global)
- **Deleted**: `global/reliefweb_disasters/` (redundant aggregate of event data)

All disaster visualization now uses global paths only.

### Global Tsunami Data Added
Created converter for NOAA NCEI Global Historical Tsunami Database:
- **Events**: 2,619 source events (earthquake/volcano epicenters)
- **Runups**: 33,623 coastal observation points
- **Coverage**: 2100 BC to present
- **Files**: `global/tsunamis/events.parquet`, `runups.parquet`
- **Display model**: Model E (Radial Propagation) - source + runup observations

### Volcano Enhancements
- **Duration columns**: Added `end_year`, `end_timestamp`, `duration_days`, `is_ongoing` to track continuous eruptions
- **Activity area**: Added `activity_area` field (e.g., "East rift zone (Puu O'o)")
- **Eruption ID**: Added `eruption_id` for Smithsonian tracking
- **Cross-linking**: Bidirectional volcano-earthquake linking (30 days before, 60 days after eruption)
- **Popup display**: Shows year ranges for multi-year eruptions (e.g., "1983-2018, 35.7 years")
- Example: Kilauea 1983-2018 eruption now shows 13,029 days duration with East rift zone activity

### Earthquake Data Status
- **Current dataset**: M4.5+ global (306K events, 1900-2026)
- **Pending merge**: M2.5-4.5 data downloaded (1.05M events total)
- **Conversion issue**: Full dataset merge times out during processing - needs optimization
- **Workaround**: Using M4.5+ dataset until converter is optimized for larger datasets
- **Aftershock detection**: Working with current dataset, Gardner-Knopoff windows applied

### Overlay Selector Hierarchical Categories
Updated overlay selector with 3 top-level categories:
```
+ Demographics (base layer)
v Disasters
    [ ] Earthquakes
    [ ] Volcanoes
    [ ] Hurricanes
    [ ] Storms (placeholder)
    [ ] Tsunamis (placeholder)
    [ ] Wildfires
> Climate
    [ ] Wind Patterns (placeholder)
    [ ] Currents (placeholder)
    [ ] Pollution (placeholder)
```
- Parent checkbox toggles all children
- Placeholder items disabled with "(soon)" label

### Map Projection Toggle [DISABLED]
- Previously had automatic 2D/globe switching based on zoom level
- Zoom >= 2.0: Mercator (flat 2D map)
- Zoom < 2.0: Globe projection with atmosphere/space effects
- **Disabled 2026-01-09**: Caused interference with tsunami animations and general instability
- Now uses Mercator projection only for stability

### API Path Cleanup
- Removed USA fallback paths for earthquakes and volcanoes
- All disaster data now uses global paths only:
  - `global/usgs_earthquakes/events.parquet`
  - `global/smithsonian_volcanoes/events.parquet`
- Hurricanes now use global IBTrACS data
- Wildfires still use USA paths (no global data yet)

### Global Tropical Storm Data (IBTrACS)
- **Source**: NOAA IBTrACS v04r01 - merges all regional agencies (NHC, JTWC, JMA, BOM, IMD, etc.)
- **Data range**: 1842-2026 (184 years of historical data)
- **Total storms**: 13,541 storms globally
- **Total positions**: 722,507 track positions (6-hourly)
- **Wind radii coverage**: ~10% of positions have r34/r50/r64 quadrant data (mostly modern era)
- **Basins covered**: NA (North Atlantic), EP (East Pacific), WP (West Pacific), SI (South Indian), SP (South Pacific), NI (North Indian), SA (South Atlantic)

**Files created:**
- `global/tropical_storms/storms.parquet` - Storm metadata (0.46 MB)
- `global/tropical_storms/positions.parquet` - Track positions (9.41 MB)
- `data_converters/converters/convert_ibtracs.py` - Converter
- `data_converters/downloaders/download_ibtracs.py` - Downloader

**API endpoints:**
- `GET /api/storms/geojson?year=2005&basin=NA` - Storms as GeoJSON points (at max intensity location)
- `GET /api/storms/{storm_id}/track` - Full track with wind radii for animation
- `GET /api/storms/list?min_year=1950&basin=NA&limit=100` - Storm list for filtering

### Tropical Storm Display Design

**Yearly Overview Mode:**
- Time slider at year granularity
- Show full storm tracks as category-colored line segments
- Click storm for popup with details and "Animate Track" button
- Default: storms from 1950-present

**Storm Animation Mode (drill-down):**
- Triggered by clicking "Animate Track" button in popup
- Time slider switches to 6-hour intervals
- Progressive track drawing with current position marker
- Wind radii circles (r34/r50/r64) displayed at current position
- Exit button returns to yearly overview

**Future Enhancement: Precomputed Wind Swaths**
For better performance and visualization, precompute cumulative wind footprints:
```python
# In convert_ibtracs.py (future enhancement)
def compute_wind_swath(positions_df, storm_id, wind_threshold=34):
    """
    Compute merged polygon of all wind radii positions for a storm.
    Results in a "tube" shape showing total area affected by winds.

    Store as 'footprint_34kt', 'footprint_50kt', 'footprint_64kt'
    GeoJSON columns in storms.parquet.
    """
    # For each position with wind radii:
    # 1. Build quadrant polygon from r34_ne/se/sw/nw
    # 2. Union all position polygons into single MultiPolygon
    # 3. Simplify for web rendering
    pass
```
This would enable showing storm "impact footprints" without loading all positions.
Priority: Low - current line display is sufficient for most use cases.

---

## File Changes Summary

| File | Changes |
|------|---------|
| `mapmover/order_executor.py` | Add `load_event_data()`, `execute_event_order()` |
| `mapmover/postprocessor.py` | Add event mode detection |
| `static/modules/map-adapter.js` | Add `loadEventLayer()`, `updateEventLayer()` |
| `static/modules/time-slider.js` | Add `initEventMode()`, `setTimestamp()` |
| `static/modules/app.js` | Route event responses to correct handlers |

---

---

## Geographic Radius Circles (km to pixels)

MapLibre's `circle-radius` is in screen pixels, not geographic units. To display actual km-based impact radii (felt_radius_km, damage_radius_km), we convert using zoom-dependent expressions.

**Formula:** `pixels = km * 2^zoom / 156.5`

```javascript
// Pre-scale km values in JavaScript because MapLibre can't nest zoom in multiplication
const felt_radius_scaled = feltRadiusKm * animationScale;  // Pre-multiplied

// Then use zoom interpolation for rendering
const kmToPixelsExpr = (kmProp) => [
  'interpolate', ['exponential', 2], ['zoom'],
  0, ['/', ['get', kmProp], 156.5],   // At zoom 0: very small
  5, ['/', ['get', kmProp], 4.9],     // 2^5 / 156.5 = 0.204
  10, ['*', ['get', kmProp], 6.54],   // 2^10 / 156.5 = 6.54
  15, ['*', ['get', kmProp], 209]     // 2^15 / 156.5 = 209
];
```

**Why pre-scaling:** MapLibre doesn't allow zoom expressions nested inside arithmetic operations. We work around this by pre-multiplying km values by the animation scale in JavaScript, then applying the zoom-dependent conversion in the paint expression.

---

## Known Issues

### Volcano Prehistoric Data
The Smithsonian Global Volcanism Program includes eruptions dating back to prehistoric times (some as early as 1280 CE). These dates overflow pandas' nanosecond-based datetime bounds (min year 1677). Current workaround sets these to NaT, resulting in only 36% of eruptions having valid timestamps in the output.

**Future fix:** Store prehistoric dates as integer years in a separate `year` column for display while keeping timestamp for modern events.

### Wildfire Perimeter Timing
MTBS data provides FINAL burn perimeters only - no daily progression data. All fires show the complete burned area regardless of timeline position. To show fire spread over time, we would need:
- VIIRS/MODIS active fire detection (daily hotspots)
- NIFC InciWeb perimeter updates (multi-day progression)
- GOES-R fire detection (15-minute updates)

### MTBS Ignition Dates
The MTBS shapefile has no valid ignition dates (Ig_Date column is empty for all 30,730 fires). Dates are extracted from the Event_ID field which only contains year, so all fires are timestamped to January 1 of their ignition year.

---

## Temporal Visualization Analysis

### Data Reality by Disaster Type

| Type | Temporal Data | Animation Possible? | Notes |
|------|---------------|---------------------|-------|
| **Hurricanes** | 6-hourly positions | YES - full track animation | Best temporal data. 73,330 positions with wind radii (r34/r50/r64) |
| **Tsunamis** | Source + runup distances | YES - wave propagation | Can calculate travel time from `dist_from_source_km` |
| **Earthquakes** | Single timestamp | NO - point in time | Show as dot + radius. 100% have felt/damage radius |
| **Volcanoes** | Single timestamp | NO - point in time | 36% have valid timestamps (prehistoric overflow). 62% have VEI |
| **Wildfires** | Year only | NO - final perimeter only | Need VIIRS/MODIS for daily progression |
| **Tornadoes** | Single timestamp | NO - point in time | Would need multi-point track data |

### Recommended Display Modes

#### Mode A: Static Point + Radius (Earthquakes, Volcanoes)
Time slider not needed - show all events for selected period.

```
Display:
- Epicenter dot (size = magnitude/VEI)
- Felt radius circle (semi-transparent outer ring)
- Damage radius circle (darker inner ring)

Interaction:
- Click for details popup
- Filter by magnitude/VEI threshold
```

**Radius calculation from VEI (volcanoes):**
```python
# Approximate hazard radius based on VEI
VEI_RADIUS_KM = {
    0: 5,    # Effusive
    1: 10,   # Gentle
    2: 25,   # Explosive
    3: 50,   # Severe
    4: 100,  # Cataclysmic
    5: 200,  # Paroxysmal
    6: 500,  # Colossal
    7: 1000, # Super-colossal
}
```

#### Mode B: Animated Track (Hurricanes)
Time slider shows storm progression.

```
Display at each timestamp:
- Current position marker (category-colored)
- Wind radii circles (34kt/50kt/64kt extent)
- Track line (positions so far)
- Future track (dashed, if known)

Animation:
- 6-hour steps
- 100-200ms per step
- Show date/time label
```

**Data available:**
- `wind_kt`, `pressure_mb`, `category` at each position
- `r34_ne/se/sw/nw` - 34kt wind radius in each quadrant
- `r50_*`, `r64_*` - 50kt and 64kt wind radii

#### Mode C: Wave Propagation (Tsunamis)
Time slider shows wave traveling from source to coastlines.

```
Display:
1. Source event (earthquake epicenter in ocean)
2. Expanding wave front circle (based on tsunami speed ~700 km/h)
3. Runup points activate as wave arrives

Animation calculation:
- Wave speed: ~700-800 km/h in open ocean
- Arrival time = dist_from_source_km / 750
- Runup points appear when wave reaches them
```

**Data available:**
- Source: `latitude`, `longitude`, `eq_magnitude`
- Runups: `dist_from_source_km`, `water_height_m`

#### Mode D: Final Perimeter (Wildfires - Current)
No animation - show final burned area.

```
Display:
- Fire perimeter polygon (from GeoJSON)
- Centroid marker with acres label
- Color by fire size or type

Future enhancement:
- Add VIIRS hotspots for daily fire activity
- Could animate hotspot appearance over fire duration
```

### What We're Missing

| Feature | Data Needed | Potential Source |
|---------|-------------|------------------|
| Wildfire daily spread | Daily perimeter snapshots | NIFC InciWeb, GOES-R |
| Tornado tracks | Multi-point path | NOAA Storm Events (some have) |
| Flood extent progression | Daily inundation maps | NOAA NWS, Copernicus |
| Volcanic ash dispersion | Ash cloud polygons over time | VAAC advisories |

### Implementation Priority

1. **Hurricanes** - Already have full track data, just need UI
2. **Earthquakes/Volcanoes** - Static display with radius, straightforward
3. **Tsunamis** - Wave animation from distance data, moderate complexity
4. **Wildfires** - Need additional data source for progression


*Last Updated: 2026-01-09 - Data cleanup: removed USA-specific duplicates in favor of global sources. Added global tsunami data (NOAA NCEI). All disaster data now uses global paths only.*
