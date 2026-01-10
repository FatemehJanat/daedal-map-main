# Mapping and Visualization

Frontend display system using MapLibre GL JS with globe projection.

**Key files**:
- [FRONTEND_MODULES.md](FRONTEND_MODULES.md) - ES6 module structure and architecture
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

Interactive year slider for time-series data visualization with animated playback.

### Trigger Conditions

The time slider appears when the LLM detects year range queries:
- "over time", "trend", "from X to Y", "between X and Y"
- "last N years", "since X"
- Example: "show CO2 trend in Europe from 2000 to 2022"

### Order Format

**Single year** (no slider):
```json
{
  "year": 2022
}
```

**Year range** (slider appears):
```json
{
  "year_start": 2000,
  "year_end": 2022
}
```

### Response Format (Multi-Year)

```json
{
  "type": "data",
  "multi_year": true,
  "geojson": {...},
  "year_data": {
    "2000": {"USA": {"co2": 5000}, "GBR": {"co2": 400}},
    "2001": {...}
  },
  "year_range": {
    "min": 2000,
    "max": 2022,
    "available_years": [2000, 2001, ..., 2022]
  },
  "metric_key": "co2"
}
```

### Frontend Components

See [FRONTEND_MODULES.md](FRONTEND_MODULES.md) for module details.

**TimeSlider** (modules/time-slider.js):
- Slider control for year selection
- Play/pause animation (600ms per year)
- Year label display
- `buildYearGeojson()` merges year data with base geometry

**ChoroplethManager** (modules/choropleth.js):
- Viridis color scale (colorblind-friendly)
- Global min/max across all years (consistent scale)
- Legend with gradient and formatted values (K/M/B suffixes)
- Efficient interpolate expression for MapLibre

### UI Layout

```
+----------------------------------+
|           Map                    |
|                                  |
|   [Legend]                       |
|   CO2 (Mt)                       |
|   [gradient]                     |
|   0        5000                  |
+----------------------------------+
| [2000]====|========[2022]   [>]  |  <- Time slider
|          2016                    |
+----------------------------------+
```

### Performance

- Geometry loaded once, stored in `baseGeojson`
- Year data overlaid on features (no geometry duplication)
- `updateSourceData()` for fast year changes (no layer recreation)
- MapLibre interpolate expression auto-updates with new values

### Indexed Scale (Data-Density Scaling)

For datasets with large time ranges (e.g., earthquake history 1900-2026), the slider auto-enables indexed scale mode:

- **Trigger**: 50+ data points in `sortedTimes`
- **Behavior**: Each data point gets equal slider space regardless of time gaps
- **Benefit**: Ancient data points are reachable (no 10000-year jumps)

```javascript
// Auto-detects based on data density
shouldUseIndexedScale() {
  return this.sortedTimes.length >= this.indexedScaleMinPoints;
}

// Slider position <-> actual time conversion
indexToTime(index)   // Get time value from slider position
timeToIndex(time)    // Get slider position from time value
```

### Data-Driven Year Range

Year ranges are derived from actual data, not hardcoded config:

```javascript
// overlay-controller.js extracts years from features
const availableYears = new Set();
for (const feature of geojson.features) {
  const year = feature.properties[endpoint.yearField];
  if (year != null) availableYears.add(parseInt(year));
}
const sortedYears = Array.from(availableYears).sort((a, b) => a - b);

// Min/max derived from actual data
const minYear = sortedYears[0];
const maxYear = sortedYears[sortedYears.length - 1];
```

### Adaptive Time Stepping (Sequence Animation)

For aftershock sequences with long durations, time steps scale adaptively:

```javascript
const MAX_STEPS = 200;
const MIN_STEP_MS = 1 * 60 * 60 * 1000;  // 1 hour minimum
const timeRange = maxTime - minTime;

// Calculate adaptive step (never smaller than 1 hour)
const adaptiveStepMs = Math.max(MIN_STEP_MS, Math.ceil(timeRange / MAX_STEPS));
```

**Results:**
- Short sequences (hours): 1-hour steps
- Medium sequences (days): 6-hour steps
- Long sequences (months): 12h-2day steps
- Animation always completes in ~200 steps regardless of duration

### Rolling Window + Fade (Event Animation)

For disaster event animations (earthquakes, storms, wildfires), events use a rolling window with opacity fading for smooth visualization during fast playback.

**Window Duration by Granularity:**
| Granularity | Window Size | Effect |
|-------------|-------------|--------|
| 6h | 24 hours | 4 data points visible |
| daily | 7 days | 1 week of events |
| monthly | ~3 months | Quarter's events |
| yearly | 1 year | Full year |

**Flash + Fade Effect:**
- Brand new events get a "flash" (recency = 1.5) with size boost
- Flash period is first 10% of window duration
- After flash, events fade linearly from 1.0 to 0.0
- Events beyond window boundary are removed
- Creates attention-grabbing "pop" when events occur, then smooth fade

```javascript
// _recency: 1.5 = flash (new), 1.0 = recent, 0.0 = fading out
// Opacity capped at 1.0, size boosted up to 50% for flash
const opacityExpr = ['min', 1.0, ['*', 0.9, recencyExpr]];
const sizeBoostExpr = ['*', baseSize, ['max', 1.0, recencyExpr]];
```

**Inactivity Detection (Continuous Events):**

For events with periodic updates (storms, wildfires), the system detects when they've "ended" based on missed updates:

| Event Type | Update Interval | Inactivity Threshold |
|------------|-----------------|---------------------|
| Storm | 6 hours | 24h (4x interval) |
| Wildfire | Daily | 4 days (4x interval) |
| Earthquake | Instant | N/A (point-in-time) |

See [DISASTER_DISPLAY.md](DISASTER_DISPLAY.md#phase-2c-unified-eventanimator-in-progress) for full EventAnimator architecture.

### Simplified Playback Display

During animation playback, the time label shows simplified format to reduce visual noise:

| Granularity | During Playback | When Paused |
|-------------|-----------------|-------------|
| 6h | "Jan 2005" | "Jan 15, 2005, 06:00 AM" |
| daily | "Jan 2005" | "Jan 15, 2005" |
| monthly | "2005" | "Jan 2005" |
| yearly | "2005" | "2005" |

This prevents "flashing text" during fast-forward playback while still showing precise time when user pauses.

### Data Flow

```
User: "show CO2 trend in Europe from 2000 to 2022"
                    |
                    v
           Order Taker LLM
           (detects year range trigger)
                    |
                    v
           Order: {year_start: 2000, year_end: 2022}
                    |
                    v
           Order Executor
           (loads all years, builds year_data)
                    |
                    v
           Response: {multi_year: true, year_data: {...}}
                    |
                    v
           App.displayData()
           (detects multi_year flag)
                    |
                    v
           TimeSlider.init()
           ChoroplethManager.init()
                    |
                    v
           User scrubs slider -> setYear() -> updateSourceData()
```

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

*Last Updated: 2026-01-09*
