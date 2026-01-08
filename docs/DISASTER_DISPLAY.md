# Disaster Display System Design

Event-based visualization for disasters including earthquakes, hurricanes, wildfires, and tsunamis. Distinct from aggregate county data - shows individual events with animation support.

**Related docs**:
- [MAPPING.md](MAPPING.md) - Time slider and choropleth system
- [data_pipeline.md](data_pipeline.md) - Data structure and metadata
- [FRONTEND_MODULES.md](FRONTEND_MODULES.md) - Module architecture

---

## Design Philosophy

The system is designed for worldwide disaster data:

1. **Converters standardize external data** - Messy source data (USGS, NOAA, BOM, etc.) is transformed into clean internal format
2. **Frontend knows only standard patterns** - The display system handles a few known event types, not source-specific formats
3. **USA is the test case** - Most complete disaster data for testing, but system works globally
4. **Same metadata pattern everywhere** - All countries use identical structure (`events.parquet` + `{COUNTRY}.parquet` + `metadata.json`)

When adding new disaster sources (Japan earthquakes, European floods, etc.), only the converter needs source-specific logic. The display system stays unchanged.

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

Each disaster source has multiple files:

### Earthquakes (usgs_earthquakes/)
```
events.parquet     # Individual events with lat/lon/magnitude/radius
USA.parquet        # County-year aggregates (earthquake_count, max_magnitude)
metadata.json      # Describes both files
```

### Hurricanes (hurricanes/)
```
positions.parquet  # 6-hourly track positions (lat/lon/wind/pressure)
storms.parquet     # Storm summary (name, dates, max_category)
USA.parquet        # County-year aggregates (storm_count, max_wind)
metadata.json
```

### Wildfires (wildfires/)
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

### Current Data Reality

| Type | Model | Time Scale | Key Fields | Notes |
|------|-------|------------|------------|-------|
| **Earthquake** | A (point+radius) | Daily | lat, lon, magnitude, felt_radius_km, damage_radius_km | Radius pre-calculated |
| **Volcano** | A (point+radius) | Yearly | lat, lon, VEI | Could calculate radius from VEI |
| **Tornado** | A (point+radius) | Daily | lat, lon, event_radius_km, tornado_scale | Already has radius! |
| **Hurricane/Cyclone** | B (track) | 6-hourly | lat, lon, wind_kt, category, r34/r50/r64 radii | Full track positions |
| **Tsunami** | A (point) | Daily | lat, lon, max_water_height_m | Runup observation points |
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

### Phase 1: Model A - Point + Radius (Current)
Starting with earthquakes and volcanoes - simplest display model.

**Backend:**
- [ ] Add `mode: "events"` field to order schema
- [ ] Add `load_event_data()` to order_executor.py
- [ ] Add event type detection to postprocessor

**Frontend:**
- [ ] Create generalized `loadEventLayer()` in MapAdapter
- [ ] Earthquake point layer (magnitude-sized circles)
- [ ] Felt radius circle overlay (uses felt_radius_km)
- [ ] Damage radius circle overlay (uses damage_radius_km)
- [ ] TimeSlider integration for daily animation

**Data fields used:**
- lat, lon - Event location
- magnitude - Circle size
- felt_radius_km - Outer impact circle
- damage_radius_km - Inner damage circle
- timestamp - Animation key

**Test query:** "Show M4+ earthquakes in California 2024"

### Phase 2: Model B - Track/Trail (Hurricanes)
- [ ] Migrate HurricaneHandler to generalized event system
- [ ] Track line rendering (connect positions)
- [ ] Animated position marker with wind radii
- [ ] Category-based coloring
- [ ] 6-hourly playback

### Phase 3: Model C - Polygon/Area (Wildfires)
- [ ] Parse perimeter GeoJSON from fires.parquet
- [ ] Render fire polygon boundaries
- [ ] Centroid marker fallback when no perimeter
- [ ] Daily animation for fire season

### Phase 4: Model D - Choropleth Events (Drought)
- [ ] Weekly drought severity by county
- [ ] Use existing choropleth system
- [ ] Weekly granularity animation

### Phase 5: Additional Sources
- [ ] Tornado points (Model A)
- [ ] Volcano eruptions (Model A)
- [ ] Tsunami runups (Model A)
- [ ] NOAA storm events (Model A)

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

*Created: 2026-01-07*
