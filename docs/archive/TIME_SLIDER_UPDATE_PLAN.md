# Time Slider Granularity Update Plan

**Created:** January 5, 2026
**Status:** Phases 1-4, 7-8 Implemented (Phase 6 Testing in progress)

**Related Docs:**
- [DISASTER_DATA.md](DISASTER_DATA.md) - Data source temporal resolutions and gaps
- [GEOMETRY.md](GEOMETRY.md) - loc_id format for county/event linkage

## Overview

Upgrade the time slider to support variable time granularity, from 6-hour increments (hurricane tracking) to 10-year increments (decadal census data). The slider should automatically adapt to the data's natural temporal resolution.

## Background Context

This enhancement was prompted by testing disaster data visualization. Key observations:

1. **Query: "Show all wildfires in 2023"** returned:
   - 454 individual fires (fires.parquet)
   - 199 counties affected (USA.parquet aggregates)
   - 2.24M total acres burned
   - 100% geocoding coverage

2. **Two-layer visualization architecture:**
   - **Choropleth layer**: County polygons colored by aggregated metrics (fire_count, total_burned_acres)
   - **Marker layer**: Individual event points (fire centroids with lat/lon)
   - County click -> shows consolidated popup for all events in that county
   - Marker click -> shows individual event details

3. **User expectation**: Step through wildfire coverage day-by-day, or follow hurricane paths in 6-hour increments

4. **Current limitation**: Time slider only supports yearly stepping

## Data Temporal Resolution Analysis

Analysis of our processed datasets revealed varying temporal granularity:

| Dataset | File | Time Field | Granularity | Notes |
|---------|------|------------|-------------|-------|
| **Hurricanes** | positions.parquet | timestamp | **6-hourly** | 73,330 track positions - EXCELLENT for animation |
| **Hurricanes** | USA.parquet | year | yearly | County aggregates |
| **Earthquakes** | events.parquet | time | **seconds** | 173,971 events - EXCELLENT |
| **NOAA Storms** | events.parquet | timestamp | **daily** | 1.2M+ events |
| **FEMA Disasters** | USA_declarations.parquet | declarationDate | **daily** | Has incident duration range |
| **Wildfires (MTBS)** | fires.parquet | year | **yearly only** | POOR - ignition_date column is 100% null |
| **Drought (USDM)** | USA.parquet | year | weekly | Weekly snapshots aggregated to yearly |

**Key Finding**: Hurricane and earthquake data already have sub-daily timestamps - no pipeline changes needed. Wildfires would need additional data sources (VIIRS/MODIS) for daily tracking. See [DISASTER_DATA.md](DISASTER_DATA.md#mtbs-temporal-limitation) for alternative wildfire sources.

## Current State

**File:** `static/modules/time-slider.js`

- Data structure: `{year: {loc_id: {metric: value}}}` - integer years as keys
- Slider: min/max/value are integers
- Step logic: jumps between available years via `sortedYears` array
- Playback: 600ms normal, 200ms fast (3x)
- Gap handling: carries forward last known values

## Proposed Changes

### 1. New Granularity Options

| Granularity | Step Size | Label Format | Primary Use Case |
|-------------|-----------|--------------|------------------|
| `6h` | 6 hours | "Sep 28, 2022 06:00" | Hurricane track positions |
| `daily` | 1 day | "Sep 28, 2022" | Earthquake sequences, fire spread |
| `weekly` | 7 days | "Week of Sep 28" | Drought progression |
| `monthly` | 1 month | "Sep 2022" | Seasonal patterns |
| `yearly` | 1 year | "2022" | Default, most data |
| `5y` | 5 years | "2020-2024" | Census, ACS data |
| `10y` | 10 years | "2010-2019" | Decadal analysis |

### 2. Updated Data Structures

**TimeRange object (passed to init):**
```javascript
{
  min: 1672531200000,        // Timestamp (ms) or year integer
  max: 1704067200000,
  granularity: '6h',         // NEW
  available: [...],          // Timestamps or years with data
  useTimestamps: true        // NEW: true for sub-yearly, false for yearly+
}
```

**TimeData object:**
```javascript
// For yearly+ granularity (backward compatible)
{ 2020: { 'USA-TX-48201': { metric: 100 } } }

// For sub-yearly granularity
{ 1672531200000: { 'USA-TX-48201': { metric: 100 } } }
```

### 3. Time Slider Module Changes

#### 3.1 New Properties
```javascript
granularity: 'yearly',     // Current granularity setting
useTimestamps: false,      // Whether keys are timestamps vs years
stepMs: null,              // Step size in milliseconds (for sub-yearly)
```

#### 3.2 Updated init() Method
```javascript
init(timeRange, timeData, baseGeojson, metricKey) {
  this.granularity = timeRange.granularity || 'yearly';
  this.useTimestamps = timeRange.useTimestamps || false;

  // Calculate step size based on granularity
  this.stepMs = this.calculateStepMs(this.granularity);

  // Rest of init...
}
```

#### 3.3 New Helper Methods

```javascript
calculateStepMs(granularity) {
  const HOUR = 3600000;
  const DAY = 86400000;
  switch (granularity) {
    case '6h': return HOUR * 6;
    case 'daily': return DAY;
    case 'weekly': return DAY * 7;
    case 'monthly': return DAY * 30;  // Approximate
    case 'yearly': return DAY * 365;
    case '5y': return DAY * 365 * 5;
    case '10y': return DAY * 365 * 10;
    default: return DAY * 365;
  }
}

formatTimeLabel(timestamp) {
  const date = new Date(timestamp);
  switch (this.granularity) {
    case '6h':
      return date.toLocaleString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: '2-digit', minute: '2-digit'
      });
    case 'daily':
      return date.toLocaleDateString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric'
      });
    case 'weekly':
      return `Week of ${date.toLocaleDateString('en-US', {
        month: 'short', day: 'numeric'
      })}`;
    case 'monthly':
      return date.toLocaleDateString('en-US', {
        month: 'short', year: 'numeric'
      });
    case 'yearly':
      return date.getFullYear().toString();
    case '5y':
    case '10y':
      const endYear = date.getFullYear() + parseInt(this.granularity) - 1;
      return `${date.getFullYear()}-${endYear}`;
  }
}
```

#### 3.4 Updated Navigation

```javascript
getNextAvailableTime(fromTime) {
  if (!this.useTimestamps) {
    // Existing year-based logic
    return this.getNextAvailableYear(fromTime);
  }

  // Timestamp-based: find next in sortedTimes > fromTime
  for (const time of this.sortedTimes) {
    if (time > fromTime) return time;
  }
  return this.sortedTimes[0];  // Wrap
}

getPrevAvailableTime(fromTime) {
  if (!this.useTimestamps) {
    return this.getPrevAvailableYear(fromTime);
  }

  for (let i = this.sortedTimes.length - 1; i >= 0; i--) {
    if (this.sortedTimes[i] < fromTime) return this.sortedTimes[i];
  }
  return this.sortedTimes[this.sortedTimes.length - 1];  // Wrap
}
```

#### 3.5 Playback Speed Adjustments

```javascript
getPlaybackInterval() {
  // Base intervals by granularity (faster for finer granularity)
  const baseIntervals = {
    '6h': 150,      // Fast for animation smoothness
    'daily': 200,
    'weekly': 300,
    'monthly': 400,
    'yearly': 600,
    '5y': 800,
    '10y': 1000
  };

  const base = baseIntervals[this.granularity] || 600;
  return this.playSpeed === 3 ? base / 3 : base;
}
```

### 4. Chat Post-Processor Integration

The post-processor analyzes order results to determine appropriate granularity.

**Location:** `static/modules/chat-processor.js` (or similar)

```javascript
function determineTimeGranularity(orderResult) {
  const source = orderResult.source;
  const data = orderResult.data || [];

  // Check for explicit timestamps in data
  const hasTimestamp = data[0]?.timestamp || data[0]?.time;
  const hasYear = data[0]?.year;

  // Source-specific defaults
  const sourceDefaults = {
    'hurricanes': '6h',        // HURDAT2 has 6-hourly positions
    'earthquakes': 'daily',    // Second precision, but daily is practical
    'noaa_storms': 'daily',    // Daily storm events
    'wildfires': 'yearly',     // MTBS only has year
    'fema_disasters': 'yearly',
    'drought': 'weekly',       // USDM is weekly
    'census': '10y',
    'acs': '5y'
  };

  if (sourceDefaults[source]) {
    return sourceDefaults[source];
  }

  // Analyze data distribution for unknown sources
  if (hasTimestamp) {
    const timestamps = data.map(d => d.timestamp || d.time).sort();
    const avgGap = (timestamps[timestamps.length-1] - timestamps[0]) / (timestamps.length - 1);

    if (avgGap < 3600000 * 12) return '6h';      // < 12 hours
    if (avgGap < 86400000 * 2) return 'daily';   // < 2 days
    if (avgGap < 86400000 * 14) return 'weekly'; // < 2 weeks
    if (avgGap < 86400000 * 60) return 'monthly';// < 2 months
  }

  if (hasYear) {
    const years = [...new Set(data.map(d => d.year))].sort((a,b) => a-b);
    if (years.length < 2) return 'yearly';

    const avgGap = (years[years.length-1] - years[0]) / (years.length - 1);
    if (avgGap >= 8) return '10y';
    if (avgGap >= 4) return '5y';
  }

  return 'yearly';  // Default
}

function buildTimeRange(orderResult, granularity) {
  const data = orderResult.data || [];
  const useTimestamps = ['6h', 'daily', 'weekly', 'monthly'].includes(granularity);

  let times;
  if (useTimestamps) {
    times = data.map(d => new Date(d.timestamp || d.time).getTime()).sort((a,b) => a-b);
  } else {
    times = [...new Set(data.map(d => d.year))].sort((a,b) => a-b);
  }

  return {
    min: times[0],
    max: times[times.length - 1],
    granularity: granularity,
    available: times,
    useTimestamps: useTimestamps
  };
}
```

### 5. User Interaction Flow

1. User asks: "Show me Hurricane Ian's path"
2. Chat processes request, queries hurricane data
3. Post-processor detects:
   - Source: hurricanes
   - Data has 6-hourly timestamps
   - Granularity: '6h'
4. Builds timeRange with granularity='6h', useTimestamps=true
5. TimeSlider.init() configures for 6-hour stepping
6. User sees slider with "Sep 28, 2022 06:00" labels
7. Play button animates through positions

**Alternative flow for sparse data:**
1. User asks: "Show population change by county"
2. Chat returns census data (2000, 2010, 2020)
3. Post-processor detects 10-year gaps
4. Granularity: '10y'
5. Slider shows "2000-2009", "2010-2019", "2020-2029"

### 6. UI Considerations

#### Slider Range Label Updates
- Sub-yearly: Show date range (e.g., "Sep 1, 2022" - "Oct 15, 2022")
- Yearly: Show year range (e.g., "1950" - "2025")
- Multi-year: Show decade ranges

#### Granularity Indicator
Consider adding a small label showing current granularity:
```html
<span class="granularity-badge">6-hour</span>
```

#### Keyboard Shortcuts
- Left/Right arrows: Step back/forward
- Shift+Left/Right: Jump 10 steps
- Space: Play/pause

### 7. Data Pipeline Updates (IMPLEMENTED)

The metadata generator now auto-detects temporal granularity. Updated files:
- `build/catalog/metadata_generator.py` - `_detect_temporal_coverage()` now detects granularity
- `build/catalog/catalog_builder.py` - Includes granularity in catalog.json

**Metadata temporal_coverage format:**
```json
{
  "temporal_coverage": {
    "start": "2022-09-23T00:00:00",
    "end": "2022-10-02T18:00:00",
    "frequency": "6-hourly",
    "granularity": "6h",
    "field": "timestamp"
  }
}
```

**Granularity detection logic:**
| Median Gap | Granularity | Frequency Label |
|------------|-------------|-----------------|
| <= 8 hours | `6h` | "6-hourly" |
| <= 36 hours | `daily` | "daily" |
| <= 7 days | `weekly` | "weekly" |
| <= 31 days | `monthly` | "monthly" |
| > 31 days (timestamp) | `yearly` | "annual" |
| Year gaps >= 8 | `10y` | "decadal" |
| Year gaps >= 4 | `5y` | "5-year intervals" |
| Year gaps < 4 | `yearly` | "annual" |

**Catalog entry includes:**
```json
{
  "source_id": "noaa_hurricanes",
  "temporal_coverage": {
    "start": 1851,
    "end": 2024,
    "granularity": "yearly",
    "field": "year"
  }
}
```

For event-level data (positions.parquet), the granularity would be detected as `6h` when regenerating metadata.

This enables the post-processor to determine granularity from catalog without analyzing parquet files.

### 8. Migration/Compatibility

- Existing yearly data works unchanged (granularity defaults to 'yearly')
- No changes to parquet file formats
- Slider automatically detects and adapts
- New `useTimestamps` flag differentiates modes

## Multi-Scale Time Slider (Tabs)

### Use Case: Hurricane Drill-Down

1. User asks: "Show all hurricanes from 2000-2024"
2. Map shows 25 years of hurricane data, time slider in **yearly** mode
3. User clicks on Hurricane Ian marker
4. Time slider adds a **second tab** for "Hurricane Ian" in **6-hour** mode
5. User can switch between tabs to toggle views

### Tab Structure

```
+------------------+---------------------+
| All Data (Years) | Hurricane Ian (6hr) |
+------------------+---------------------+
     [====|================]  Sep 28, 2022 12:00
     |<  <   |>   >  >>|
```

### Data Model

```javascript
// TimeSlider now manages multiple "scales"
scales: [
  {
    id: 'primary',
    label: 'All Data',
    granularity: 'yearly',
    timeRange: { min: 2000, max: 2024 },
    timeData: { /* yearly county aggregates */ },
    active: true
  },
  {
    id: 'hurricane-ian',
    label: 'Hurricane Ian',
    granularity: '6h',
    timeRange: { min: 1664150400000, max: 1664755200000 },
    timeData: { /* 6-hourly track positions */ },
    active: false
  }
]
```

### Scale Management API

```javascript
// Add a new scale (called when user selects an event)
TimeSlider.addScale({
  id: 'hurricane-ian',
  label: 'Hurricane Ian',
  granularity: '6h',
  timeRange: {...},
  timeData: {...}
});

// Switch active scale (called when user clicks tab)
TimeSlider.setActiveScale('hurricane-ian');

// Remove scale (called when user closes tab or clears selection)
TimeSlider.removeScale('hurricane-ian');

// Get current active scale
TimeSlider.getActiveScale();  // returns scale object
```

### Tab UI Component

```html
<div id="timeSliderTabs" class="time-slider-tabs">
  <button class="tab active" data-scale="primary">
    All Data <span class="granularity">yearly</span>
  </button>
  <button class="tab" data-scale="hurricane-ian">
    Hurricane Ian <span class="granularity">6hr</span>
    <span class="tab-close">x</span>
  </button>
</div>
```

### Interaction Flow

| Action | Result |
|--------|--------|
| Query returns multi-year data | Primary tab created (yearly) |
| Click individual event marker | Detail tab added, auto-switched |
| Click primary tab | Switch to yearly overview |
| Click detail tab | Switch to event-specific view |
| Close detail tab (x) | Remove tab, switch to primary |
| New query | Clear all tabs, create fresh primary |

### Event-to-Scale Mapping

Different event types create different detail scales:

| Event Type | Detail Granularity | Time Range |
|------------|-------------------|------------|
| Hurricane | 6h | Storm lifetime (formation to dissipation) |
| Earthquake sequence | daily | Mainshock to 30 days after |
| Wildfire | yearly (or daily if VIIRS) | Fire year (or active fire period) |
| Tornado outbreak | hourly | Outbreak day |
| FEMA disaster | daily | Incident begin to end date |

### Implementation in Event Handlers

```javascript
// In marker click handler (e.g., hurricane marker)
function onHurricaneMarkerClick(hurricane) {
  const trackData = await fetchHurricaneTrack(hurricane.storm_id);

  TimeSlider.addScale({
    id: `hurricane-${hurricane.storm_id}`,
    label: hurricane.name,
    granularity: '6h',
    timeRange: {
      min: trackData[0].timestamp,
      max: trackData[trackData.length - 1].timestamp,
      available: trackData.map(p => p.timestamp),
      useTimestamps: true
    },
    timeData: buildTrackTimeData(trackData),
    // What to show on map at each time step
    mapRenderer: 'hurricane-track'  // special rendering mode
  });

  TimeSlider.setActiveScale(`hurricane-${hurricane.storm_id}`);
}
```

### Map Rendering by Scale

Each scale can specify how the map should render:

| mapRenderer | Behavior |
|-------------|----------|
| `choropleth` (default) | County fill colors by metric |
| `hurricane-track` | Animated track line + current position marker |
| `earthquake-sequence` | Expanding circles for aftershocks |
| `fire-spread` | Growing perimeter animation |

```javascript
// TimeSlider calls appropriate renderer on time change
setTime(timestamp) {
  const scale = this.getActiveScale();

  switch (scale.mapRenderer) {
    case 'hurricane-track':
      HurricaneRenderer.renderAtTime(timestamp, scale.timeData);
      break;
    case 'choropleth':
    default:
      const geojson = this.buildTimeGeojson(timestamp);
      MapAdapter.updateSourceData(geojson);
  }
}
```

---

## Updated Implementation Order

1. **Phase 1: Core granularity support** - IMPLEMENTED (2026-01-05)
   - Added granularity property and calculateStepMs() helper
   - Added formatTimeLabel() with all granularity formats
   - Backward compatibility via sensible defaults (granularity='yearly', available_years fallback)

2. **Phase 2: Sub-yearly timestamp support** - IMPLEMENTED (2026-01-05)
   - Timestamp-based navigation (getNextAvailableTime, getPrevAvailableTime)
   - Granularity-aware playback intervals (getPlaybackInterval)
   - Slider handles both integer years and ms timestamps
   - buildFilledTimeData() differentiates yearly gap-fill vs timestamp-only modes

3. **Phase 3: Multi-scale tabs** - IMPLEMENTED (2026-01-05)
   - scales[] array with addScale/removeScale/setActiveScale API
   - Tab UI component with granularity badges and close buttons
   - Automatic tab hiding when only one scale
   - State preservation when switching scales

4. **Phase 4: Event drill-down integration** - IMPLEMENTED (2026-01-05)
   - Hurricane marker click -> add track scale (HurricaneHandler.drillDown)
   - MapAdapter.loadHurricaneLayer() with click callback
   - App.displayData() auto-detects hurricane data and loads appropriate layer
   - API endpoints: /api/hurricane/track/{storm_id}, /api/hurricane/storms

5. **Phase 5: Custom renderers**
   - Hurricane track renderer
   - Earthquake sequence renderer
   - Fire spread renderer (future, needs VIIRS data)

6. **Phase 6: Testing**
   - Hurricane tracking (6h)
   - Earthquake sequences (daily)
   - Census data (10y)
   - Tab switching behavior
   - Multiple detail tabs open

## Files to Modify

| File | Changes |
|------|---------|
| `static/modules/time-slider.js` | Core granularity + multi-scale support |
| `static/modules/chat-processor.js` | Granularity detection |
| `static/css/time-slider.css` | Tabs and granularity badge styling |
| `static/modules/hurricane-renderer.js` | NEW: Track animation renderer |
| `static/modules/marker-handlers.js` | Add drill-down on marker click |
| `data_converters/*.py` | Add temporal metadata to output |

## Design Decisions

1. **Chat asks about granularity for ambiguous queries?**
   - YES - Suggest what granularities are available in the data and ask user preference

2. **Maximum tabs allowed?**
   - 3 tabs max. Beyond that, show warning: "Too many time scales clutters the display, which ones are you most interested in?"

3. **Support custom granularity (e.g., "every 3 days")?**
   - NO - Only support granularities that match the underlying data

4. **Closing detail tab behavior?**
   - Switching tabs = switching views. Close tab -> switch to remaining tab's view

5. **Map transition when switching scales?**
   - Crossfade between views (not fade-out-then-in, but direct crossfade between the two states)

---

## Data Architecture Notes

### Two-File Pattern for Event Data

Most disaster datasets follow a two-file pattern:

```
{source}/
  USA.parquet        # County-year aggregates (for choropleth)
  events.parquet     # Individual events (for markers + drill-down)
  # or fires.parquet, positions.parquet, etc.
```

**USA.parquet (Aggregates)**:
- Pre-computed county-year statistics
- No on-the-fly summing needed
- Fields: loc_id, year, event_count, total_damage, max_severity, etc.
- Used for: Choropleth coloring, time slider yearly mode

**events.parquet (Individual)**:
- Each row = one event with timestamp + coordinates
- Fields: loc_id, timestamp/time, lat, lon, magnitude/intensity, name, etc.
- Used for: Markers, drill-down detail tabs, sub-yearly animation

### Popup Consolidation

When a county has multiple events (e.g., Coconino County, AZ with 43 fires in 2023):
- **County popup**: Shows aggregated stats from USA.parquet (43 fires, X acres total)
- **Marker popup**: Shows individual event details from events.parquet

The time slider should respect this:
- **Yearly mode**: Uses USA.parquet aggregates, popups show yearly totals
- **Sub-yearly mode**: Uses events.parquet, popups show events visible at current timestamp

### loc_id as Universal Join Key

All data links via `loc_id`:
- County aggregates: `loc_id` matches geometry parquet
- Individual events: `loc_id` links event to county for filtering/grouping
- Water body events: `loc_id` starts with 'X' (XOA, XOP, XSG, etc.)

---

## Future Considerations

1. **Multiple event types in one query**: "Show all disasters in Florida 2020-2024"
   - Could show hurricanes (6h), tornadoes (hourly), floods (daily) on same map
   - Tabs would allow switching between granularities per event type

2. **Aggregate + Detail hybrid view**: Show county choropleth AND event markers simultaneously
   - Choropleth shows "cumulative to date"
   - Markers show "events at current timestamp"

3. **Time range selection**: Brush selection on slider to define custom window
   - "Show all events between Sep 25-30, 2022"

---

## Phase 7: Unified Continuous Speed Slider (2026-01-10)

**Status:** Research complete, implementation pending

### Problem Statement

The current system has several animation speed issues:

1. **Discrete speed presets**: Only "normal" and "5x fast" modes
2. **Separate animation systems**: TrackAnimator, SequenceAnimator, EventAnimator each handle timing differently
3. **Granularity dictates speed**: Playback interval varies by granularity (30ms-200ms), not by user preference
4. **No user control**: Can't smoothly adjust animation speed for different use cases

**User frustration example**: Viewing 10 years of wildfire data at 6hr granularity would take 16+ minutes. User wants "yearly overview speed" but has no way to get there.

### User Vision

> "A slider bar by the time slider, instead of fast forwards and fast rewind. At one end of the slider the 'speed' is yearly, and at the other end the speed is 6hrs. That way the user can easily adjust the slider to get the speed of animation they want to see, and it also smoothly works across datasets with events at different times."

### Current System Analysis

**TimeSlider (time-slider.js)**:
- `FAST_SPEED = 5` - binary multiplier (normal vs 5x fast)
- `getPlaybackInterval()` - returns base interval / speed
- Base intervals by granularity: `{6h: 30, daily: 40, monthly: 80, yearly: 120}`
- Play/pause, step forward/back, fast forward/rewind buttons

**EventAnimator (event-animator.js)**:
- `GRANULARITY_MS` - step sizes from 12m to yearly
- `WINDOW_DURATIONS` - rolling window for event visibility
- Integrates with TimeSlider via `addScale()`

**TrackAnimator (track-animator.js)**:
- Hardcoded 6h granularity
- Uses TimeSlider multi-scale system

**SequenceAnimator (sequence-animator.js)**:
- Uses `requestAnimationFrame` for smooth animations
- Circle growth and viewport interpolation

### Solution: Continuous Speed Slider

Replace discrete speed presets with a **single continuous slider** that controls animation speed across ALL animation systems.

```
TIME SLIDER CONTROLS (current)
+----------------------------------+
| [<<] [<] [|>] [>] [>>]           |
|  Rewind  Play   Fast Forward     |
+----------------------------------+

UNIFIED TIME CONTROLS (proposed)
+--------------------------------------------------+
| [<<] [<] [|>] [>] [>>]  Speed: [=====|======]    |
|  Jump controls          Slow 6hr        Fast Yr  |
+--------------------------------------------------+
```

### Core Constants

```javascript
// time-system.js (new file or added to time-slider.js)

const TIME_SYSTEM = {
  // Base unit: 6 hours in milliseconds
  BASE_STEP_MS: 6 * 60 * 60 * 1000,  // 21,600,000

  // Speed slider range (steps per frame)
  MIN_STEPS_PER_FRAME: 1,      // 6 hours per frame (slowest - detailed view)
  MAX_STEPS_PER_FRAME: 1460,   // ~1 year per frame (fastest - overview)

  // Rendering
  MAX_FPS: 15,  // Start conservative, increase to 60 later
  FRAME_INTERVAL_MS: 1000 / 15,  // ~67ms

  // Convert slider position (0-1) to steps per frame
  sliderToStepsPerFrame(sliderValue) {
    // Logarithmic scale for better control at slow end
    // Most of the slider range devoted to slow/medium speeds
    const log = Math.log;
    const minLog = log(this.MIN_STEPS_PER_FRAME);
    const maxLog = log(this.MAX_STEPS_PER_FRAME);
    return Math.round(Math.exp(minLog + sliderValue * (maxLog - minLog)));
  },

  // Reverse: steps per frame to slider position
  stepsPerFrameToSlider(stepsPerFrame) {
    const log = Math.log;
    const minLog = log(this.MIN_STEPS_PER_FRAME);
    const maxLog = log(this.MAX_STEPS_PER_FRAME);
    return (log(stepsPerFrame) - minLog) / (maxLog - minLog);
  },

  // Get human-readable speed label
  getSpeedLabel(stepsPerFrame) {
    const hoursPerFrame = stepsPerFrame * 6;
    if (hoursPerFrame < 24) return `${hoursPerFrame}h/frame`;
    if (hoursPerFrame < 168) return `${Math.round(hoursPerFrame/24)}d/frame`;
    if (hoursPerFrame < 720) return `${Math.round(hoursPerFrame/168)}w/frame`;
    if (hoursPerFrame < 8760) return `${Math.round(hoursPerFrame/720)}mo/frame`;
    return `${Math.round(hoursPerFrame/8760)}yr/frame`;
  }
};
```

### Speed Slider Math

**Logarithmic Mapping** (better than linear):
- Linear: 0.5 slider position = 730 steps/frame (half of range) - too fast
- Logarithmic: 0.5 slider position = 38 steps/frame (~10 days) - more usable

**Slider Position -> Steps Per Frame**:
| Slider | Steps/Frame | Time/Frame | Use Case |
|--------|-------------|------------|----------|
| 0.00   | 1           | 6 hours    | Tsunami waves, storm tracking |
| 0.25   | 5           | 30 hours   | Hurricane movement |
| 0.50   | 38          | ~10 days   | Earthquake sequences |
| 0.75   | 280         | ~10 weeks  | Fire seasons |
| 1.00   | 1460        | ~1 year    | Decade-scale overview |

### Default Speed by View Mode

Two different default behaviors based on what the user is viewing:

**1. World View (Overview Mode)**
- Default: ~1 year/frame (slider position ~1.0)
- User is browsing global data, wants quick overview
- Slider available to slow down if they want detail

**2. Event Animation Mode**
- Default: Auto-calculate so entire event plays in ~10 seconds
- User clicked a specific event (hurricane, earthquake sequence, tsunami)
- Animation should feel natural - not too fast, not too slow
- Slider available to speed up or slow down as desired

```javascript
const TARGET_ANIMATION_SECONDS = 10;  // Event animations should take ~10 seconds
const TARGET_FRAMES = TARGET_ANIMATION_SECONDS * TIME_SYSTEM.MAX_FPS;  // 150 frames at 15 FPS

/**
 * Calculate speed for world view (overview mode).
 * Defaults to fast yearly overview, adjustable by user.
 */
function getWorldViewSpeed() {
  return 1.0;  // Yearly speed - fast overview
}

/**
 * Calculate speed for event animation mode.
 * Auto-adjusts so the entire event plays in ~10 seconds.
 *
 * @param {number} eventDurationMs - Event lifespan in milliseconds
 * @returns {number} Slider position (0-1)
 */
function getEventAnimationSpeed(eventDurationMs) {
  // Convert event duration to 6-hour steps
  const totalSteps = eventDurationMs / TIME_SYSTEM.BASE_STEP_MS;

  // Calculate steps per frame to complete in TARGET_FRAMES
  const stepsPerFrame = totalSteps / TARGET_FRAMES;

  // Clamp to valid range
  const clampedSteps = Math.max(
    TIME_SYSTEM.MIN_STEPS_PER_FRAME,
    Math.min(TIME_SYSTEM.MAX_STEPS_PER_FRAME, stepsPerFrame)
  );

  // Convert to slider position
  return TIME_SYSTEM.stepsPerFrameToSlider(clampedSteps);
}

// Example calculations at 15 FPS (150 frames in 10 seconds):
//
// Hurricane (7 days = 28 six-hour steps):
//   stepsPerFrame = 28 / 150 = 0.19 -> clamps to 1 -> slider ~0.0 (6hr detail)
//   Actual duration: 28 frames / 15 = ~2 seconds (short events play quickly)
//
// Earthquake sequence (30 days = 120 steps):
//   stepsPerFrame = 120 / 150 = 0.8 -> clamps to 1 -> slider ~0.0
//   Actual duration: 120 frames / 15 = 8 seconds
//
// Wildfire season (6 months = 730 steps):
//   stepsPerFrame = 730 / 150 = 4.9 -> slider ~0.22
//   Actual duration: 150 frames / 15 = 10 seconds (perfect)
//
// Decade overview (10 years = 14,600 steps):
//   stepsPerFrame = 14,600 / 150 = 97 -> slider ~0.63
//   Actual duration: 150 frames / 15 = 10 seconds (perfect)
```

### Mode Switching Behavior

| Action | Speed Default | Why |
|--------|---------------|-----|
| Load global earthquakes (1900-2024) | 1.0 (yearly) | Fast overview of 124 years |
| Click single earthquake sequence | Auto (~0.0-0.3) | ~10 sec animation of 30-day sequence |
| Load global hurricanes (2020) | 1.0 (yearly) | Year of data, fast overview |
| Click Hurricane Ian track | Auto (~0.0) | ~10 sec animation of 7-day storm |
| Load global wildfires (2002-2024) | 1.0 (yearly) | 22 years, fast overview |
| Click specific wildfire | Auto (~0.2) | ~10 sec animation of fire duration |
| Exit event view -> back to world | Restore 1.0 | Return to yearly overview speed |

### Implementation

```javascript
// In TimeSlider or overlay-controller.js

/**
 * Enter event animation mode with auto-calculated speed.
 * Called when user clicks to animate a specific event.
 */
enterEventAnimation(eventStartTime, eventEndTime) {
  const durationMs = eventEndTime - eventStartTime;
  const suggestedSlider = getEventAnimationSpeed(durationMs);

  // Store previous speed for restoration
  this._previousSpeedSlider = this.speedSlider.value;
  this._inEventMode = true;

  // Set new speed
  this.speedSlider.value = suggestedSlider;
  this.setSpeedFromSlider(suggestedSlider);

  console.log(`Event animation: ${(durationMs / 86400000).toFixed(1)} days -> ${TIME_SYSTEM.getSpeedLabel(this.stepsPerFrame)}`);
}

/**
 * Exit event animation and return to world view.
 * Always returns to yearly overview speed (user expectation for browsing).
 */
exitEventAnimation() {
  // Return to fast yearly overview for world browsing
  const worldSpeed = getWorldViewSpeed();
  this.speedSlider.value = worldSpeed;
  this.setSpeedFromSlider(worldSpeed);

  this._inEventMode = false;
  this._previousSpeedSlider = null;
}
```

### User Override

The auto-calculated speed is just a starting point. User can always:
1. Drag speed slider to adjust during animation
2. Their adjustment applies immediately
3. Next event uses fresh auto-calculation (not their previous override)

### Test Scenarios

**Test 1: Hurricane Track (1-2 week event)**
- Event: Hurricane Ian (Sep 23 - Oct 2, 2022 = 9 days)
- Duration: 9 days = 36 six-hour steps
- stepsPerFrame = 36 / 150 = 0.24 -> clamps to 1
- Result: Plays at 6hr detail speed, ~2.4 seconds total
- User sees smooth storm movement across Gulf

**Test 2: Earthquake Sequence (year-long aftershock sequence)**
- Event: 2011 Tohoku M9.0 + aftershocks (1 year of activity)
- Duration: 365 days = 1,460 six-hour steps
- stepsPerFrame = 1460 / 150 = 9.7 -> slider ~0.31
- Result: Plays at ~2.5 days/frame, exactly 10 seconds
- User sees mainshock then aftershocks rippling outward over time

**Test 3: Tsunami Runups (24 hour event)**
- Event: Tsunami wave propagation (24 hours)
- Duration: 24 hours = 4 six-hour steps
- stepsPerFrame = 4 / 150 = 0.03 -> clamps to 1
- Result: Plays at 6hr detail speed, 4 frames = ~0.3 seconds
- Too fast! Need minimum animation duration

**Refinement: Minimum Animation Duration**

Very short events (tsunamis, tornado outbreaks) shouldn't flash by in under a second.

```javascript
const MIN_ANIMATION_SECONDS = 3;  // Very short events still get 3+ seconds
const MIN_FRAMES = MIN_ANIMATION_SECONDS * TIME_SYSTEM.MAX_FPS;  // 45 frames

function getEventAnimationSpeed(eventDurationMs) {
  const totalSteps = eventDurationMs / TIME_SYSTEM.BASE_STEP_MS;

  // Ensure minimum animation duration for very short events
  // For a 4-step event (24 hours), this spreads it across 45 frames = 3 seconds
  const effectiveFrames = Math.max(MIN_FRAMES, Math.min(TARGET_FRAMES, totalSteps));

  const stepsPerFrame = totalSteps / effectiveFrames;

  // For very short events, stepsPerFrame < 1 means we hold each step for multiple frames
  // stepsPerFrame = 4/45 = 0.089 -> hold each 6hr step for ~11 frames (~0.7 sec)

  const clampedSteps = Math.max(0.1, Math.min(TIME_SYSTEM.MAX_STEPS_PER_FRAME, stepsPerFrame));
  return TIME_SYSTEM.stepsPerFrameToSlider(clampedSteps);
}
```

**Updated Test 3: Tsunami with minimum duration**
- Duration: 24 hours = 4 six-hour steps
- effectiveFrames = max(45, min(150, 4)) = 45
- stepsPerFrame = 4 / 45 = 0.089
- Result: Each 6hr step shown for ~11 frames, total ~3 seconds
- User can watch wave propagate at readable pace

### Slideshow Mode (Very Slow Speeds)

For short events, users may want to "step through" even slower than 15 FPS allows. When `stepsPerFrame < 1`, we're no longer animating smoothly - we're showing a series of photographs.

**The math:**
- At 15 FPS with `stepsPerFrame = 1`: each 6hr step = 1 frame = 67ms
- At 15 FPS with `stepsPerFrame = 0.5`: each 6hr step = 2 frames = 133ms
- At 15 FPS with `stepsPerFrame = 0.1`: each 6hr step = 10 frames = 667ms

**Extended slider range for slow motion:**
```javascript
// Extend MIN_STEPS_PER_FRAME below 1 for slideshow mode
MIN_STEPS_PER_FRAME: 0.1,  // Each 6hr step shown for 10 frames (~0.7 sec)

// This extends the slider range:
// Slider 0.0 -> 0.1 steps/frame -> each 6hr step visible for 0.67 seconds
// Slider 0.15 -> 1 step/frame -> smooth 6hr animation (15 FPS)
// Slider 1.0 -> 1460 steps/frame -> yearly overview
```

**Updated hurricane example with slideshow:**
```
Hurricane Ian (7 days = 28 six-hour steps):

At slider = 0.0 (slideshow mode, 0.1 steps/frame):
  - Each 6hr step shown for 10 frames = 0.67 seconds
  - Total: 28 steps x 0.67s = 18.7 seconds
  - User can carefully study each position

At slider = 0.15 (normal slow, 1 step/frame):
  - Each 6hr step = 1 frame = 0.067 seconds
  - Total: 28 frames / 15 = 1.9 seconds
  - Smooth but fast animation

At auto-calculated (~0.08, targeting 10 seconds):
  - stepsPerFrame = 28/150 = 0.19
  - Each step shown for ~5 frames = 0.33 seconds
  - Total: ~10 seconds
```

**Implementation: Variable frame hold time**
```javascript
// When stepsPerFrame < 1, we hold each time step for multiple frames
tick() {
  if (!this.playing) return;

  this.frameCounter = (this.frameCounter || 0) + 1;

  // For fractional steps, only advance time every N frames
  const framesPerStep = Math.max(1, Math.round(1 / this.stepsPerFrame));

  if (this.stepsPerFrame >= 1 || this.frameCounter >= framesPerStep) {
    // Advance time
    const stepSize = this.stepsPerFrame >= 1
      ? TIME_SYSTEM.BASE_STEP_MS * this.stepsPerFrame
      : TIME_SYSTEM.BASE_STEP_MS;  // One step when in slideshow mode

    this.currentTime += stepSize;
    this.frameCounter = 0;

    // Render
    this._notifyTimeChange(this.currentTime);
  }

  // Continue animation
  if (this.currentTime < this.endTime) {
    setTimeout(() => this.tick(), TIME_SYSTEM.FRAME_INTERVAL_MS);
  } else {
    this.playing = false;
  }
}
```

**UI feedback for slideshow mode:**
When slider is in the "slow" zone (stepsPerFrame < 1):
- Speed label shows "0.7s/step" instead of "6h/frame"
- Optional: dim the slider track in this zone to indicate "slideshow" vs "animation"

### Event Visibility Window

Events don't instantly appear/disappear. Use a visibility window that scales with speed:

```javascript
// Window duration = 4x the step duration (events stay visible for ~4 frames)
const WINDOW_MULTIPLIER = 4;

function getWindowDuration(stepsPerFrame) {
  return TIME_SYSTEM.BASE_STEP_MS * stepsPerFrame * WINDOW_MULTIPLIER;
}

// Examples:
// Slow (1 step/frame, 6hr): 24-hour window
// Medium (38 steps/frame): ~40-day window
// Fast (1460 steps/frame): ~4-year window
```

### Opacity Fade

Events fade based on age within the window:

```javascript
function getOpacity(eventTime, currentTime, windowDuration) {
  const age = currentTime - eventTime;
  if (age < 0) return 0;  // Future event
  if (age > windowDuration) return 0;  // Too old

  // Linear fade from 1.0 (new) to 0.2 (about to disappear)
  return 1.0 - (age / windowDuration) * 0.8;
}
```

### Animation Loop (Unified)

```javascript
// TimeAnimator class or TimeSlider extension
class TimeAnimator {
  constructor() {
    this.currentTime = null;
    this.endTime = null;
    this.stepsPerFrame = 4;  // Default: 1 day per frame
    this.playing = false;
    this.animationFrameId = null;
  }

  setSpeed(sliderValue) {
    this.stepsPerFrame = TIME_SYSTEM.sliderToStepsPerFrame(sliderValue);
    console.log(`Speed set to ${TIME_SYSTEM.getSpeedLabel(this.stepsPerFrame)}`);
  }

  tick() {
    if (!this.playing) return;

    // Advance by stepsPerFrame * 6 hours
    this.currentTime += TIME_SYSTEM.BASE_STEP_MS * this.stepsPerFrame;

    // Notify listeners (TimeSlider, EventAnimator, etc.)
    this._notifyTimeChange(this.currentTime);

    // Continue if not at end
    if (this.currentTime < this.endTime) {
      this.animationFrameId = setTimeout(
        () => this.tick(),
        TIME_SYSTEM.FRAME_INTERVAL_MS
      );
    } else {
      this.playing = false;
      this.onComplete?.();
    }
  }

  play() {
    this.playing = true;
    this.tick();
  }

  pause() {
    this.playing = false;
    if (this.animationFrameId) {
      clearTimeout(this.animationFrameId);
    }
  }
}
```

### UI Layout

```
+------------------------------------------------------------------+
| LAYER: Earthquakes (1900-2024)                              [x]  |
+------------------------------------------------------------------+
|                                                                  |
|  [|<] [<] [|>] [>] [>|]    Speed: [======|===============]  1d   |
|   Skip      Play           Detail 6hr              Year   /frame |
|                                                                  |
|  |======================|=============|========================| |
|  1900                  1962          |                    2024   |
|                              Jan 15, 1962                        |
+------------------------------------------------------------------+
```

**Control elements:**
- `[|<]` - Jump to start
- `[<]` - Step back (by stepsPerFrame)
- `[|>]` - Play/Pause toggle
- `[>]` - Step forward
- `[>|]` - Jump to end
- Speed slider - continuous, logarithmic
- Speed label - updates as slider moves

### Speed Slider Tick Marks

While continuous, provide labeled tick marks for quick selection:

```
   |         |         |         |         |
  6hr      1day      1wk      1mo       1yr
```

Clicking a label snaps to that speed.

### Implementation Changes

**1. TimeSlider additions (time-slider.js)**:
```javascript
// New properties
speedSlider: null,           // DOM element
speedLabel: null,            // DOM element for "1d/frame"
stepsPerFrame: 4,            // Current speed (default: 1 day)

// New methods
setSpeedFromSlider(sliderValue) {
  this.stepsPerFrame = TIME_SYSTEM.sliderToStepsPerFrame(sliderValue);
  this.speedLabel.textContent = TIME_SYSTEM.getSpeedLabel(this.stepsPerFrame);
},

suggestSpeedForRange() {
  const rangeMs = this.maxTime - this.minTime;
  const suggestedSlider = suggestSpeed(rangeMs);
  this.speedSlider.value = suggestedSlider;
  this.setSpeedFromSlider(suggestedSlider);
},
```

**2. Update getPlaybackInterval()**:
```javascript
getPlaybackInterval() {
  // Now just returns frame interval - speed is controlled by stepsPerFrame
  return TIME_SYSTEM.FRAME_INTERVAL_MS;
}
```

**3. Update playback loop**:
```javascript
startPlayback() {
  if (this.playInterval) clearInterval(this.playInterval);

  this.isPlaying = true;
  this.updateButtonStates();

  const tick = () => {
    if (!this.isPlaying) return;

    // Advance by stepsPerFrame * BASE_STEP_MS
    const stepMs = TIME_SYSTEM.BASE_STEP_MS * this.stepsPerFrame;

    if (this.playDirection === 1) {
      this.currentTime = Math.min(this.currentTime + stepMs, this.maxTime);
    } else {
      this.currentTime = Math.max(this.currentTime - stepMs, this.minTime);
    }

    this.setTime(this.currentTime, 'playback');

    // Check for end
    if (this.currentTime >= this.maxTime || this.currentTime <= this.minTime) {
      this.pause();
      return;
    }

    this.playTimeout = setTimeout(tick, TIME_SYSTEM.FRAME_INTERVAL_MS);
  };

  tick();
}
```

**4. HTML template additions**:
```html
<div class="speed-control">
  <label for="speedSlider">Speed:</label>
  <input type="range" id="speedSlider" min="0" max="1" step="0.01" value="0.25">
  <span id="speedLabel">1d/frame</span>
</div>
```

**5. EventAnimator integration**:
- Read `stepsPerFrame` from TimeSlider
- Use for visibility window calculation
- Use for opacity fade timing

### Cross-Dataset Compatibility

The unified speed slider handles all disaster types seamlessly:

| Dataset | Typical Range | Suggested Speed | Animation Duration |
|---------|---------------|-----------------|-------------------|
| Tsunami runups | 24 hours | 0.0 (6hr) | ~4 seconds |
| Hurricane season | 6 months | 0.3 (~3 days) | ~1 minute |
| Earthquake year | 1 year | 0.5 (~10 days) | ~36 seconds |
| Wildfire decade | 10 years | 0.75 (~10 weeks) | ~50 seconds |
| Historical record | 100 years | 1.0 (yearly) | ~7 seconds |

### Migration Path

1. Keep existing fast-forward/rewind buttons temporarily
2. Add speed slider alongside them
3. Wire speed slider to stepsPerFrame
4. Test with all animation types
5. Remove fast-forward/rewind buttons once stable

### Files to Modify

| File | Changes |
|------|---------|
| `static/modules/time-slider.js` | Add speedSlider, stepsPerFrame, update playback loop |
| `static/modules/event-animator.js` | Read stepsPerFrame from TimeSlider, update window calculations |
| `static/modules/track-animator.js` | Use unified speed system |
| `static/modules/sequence-animator.js` | Integrate with speed slider |
| `templates/index.html` | Add speed slider HTML |
| `static/css/time-slider.css` | Style speed slider, tick marks |

### Future: 60 FPS Support

When ready to upgrade from 15 FPS to 60 FPS:

```javascript
// time-system.js
MAX_FPS: 60,  // Changed from 15
FRAME_INTERVAL_MS: 1000 / 60,  // ~17ms

// Speed ranges may need adjustment
MIN_STEPS_PER_FRAME: 0.25,  // 1.5hr per frame for smoothest animation
MAX_STEPS_PER_FRAME: 1460,  // Still ~1 year for fast overview
```

Higher frame rate enables smoother animations for:
- Tsunami wave propagation (every 3 hours instead of 6)
- Hurricane spiral tracking
- Fire perimeter growth

---

## Phase 8: Timestamp Unification (2026-01-10)

**Status:** IMPLEMENTED

### Problem Statement

The play button wasn't working correctly at yearly speed. The issue was that `startPlayback()` calculated:
```javascript
nextTime = this.currentTime + stepMs;
```

Where `stepMs` was milliseconds (e.g., 21,600,000 for 6 hours) but `currentTime` was a year integer (e.g., 2024). This produced nonsense values like `21,602,024`.

### Solution: Internal Timestamp Unification

All internal time storage now uses timestamps (milliseconds since Unix epoch). Years are converted on input and converted back for display.

### New Helper Methods (time-slider.js)

```javascript
// Convert year to timestamp (January 1, 00:00:00 UTC)
yearToTimestamp(year) {
  return Date.UTC(year, 0, 1, 0, 0, 0, 0);
}

// Convert timestamp to year
timestampToYear(timestamp) {
  return new Date(timestamp).getUTCFullYear();
}

// Auto-detect and normalize (handles years from -50000 to 50000)
normalizeToTimestamp(time) {
  if (Math.abs(time) < 50000) {
    return this.yearToTimestamp(time);
  }
  return time;  // Already a timestamp
}

// Get key for data lookup (year for yearly mode, timestamp for sub-yearly)
getDataLookupKey(timestamp) {
  if (!this.useTimestamps) {
    return this.timestampToYear(timestamp);
  }
  return timestamp;
}
```

### Functions Updated

| Function | Change |
|----------|--------|
| `initSlider()` | Normalize default min/max values to timestamps |
| `setTimeRange()` | Normalize incoming min/max/available to timestamps |
| `init()` | Normalize timeRange values to timestamps |
| `setActiveScale()` | Normalize scale's time range values |
| `setActiveMetric()` | Normalize metric year ranges |
| `buildFilledTimeData()` | Iterate using years (converted from timestamps) for yearly mode |
| `buildTimeGeojson()` | Use `getDataLookupKey()` to look up data |
| `formatTimeLabel()` | Convert timestamp to year for yearly granularity display |

### Historical Data Support

The `normalizeToTimestamp()` function uses `Math.abs(time) < 50000` to detect years vs timestamps:
- Values -50000 to 50000 treated as years (covers all human history)
- Larger values treated as timestamps
- JavaScript `Date` can handle years from ~271,821 BCE to 275,760 CE

### Backward Compatibility

- Existing code can still pass year integers (they get converted automatically)
- Display still shows years for yearly granularity
- Data lookup uses year keys for yearly data (via `getDataLookupKey()`)
- No changes needed to data files or API responses

---

## Bug Fix: Popup Click Locking (2026-01-10)

**Status:** FIXED

### Problem

Clicking on event markers (wildfires, earthquakes, etc.) showed the popup briefly, then it immediately disappeared. Only hover popups worked.

### Root Cause

In `map-adapter.js`, the global click handler only checked the choropleth `fillLayer` before unlocking popups:

```javascript
// BEFORE (buggy)
this.map.on('click', (e) => {
  const features = this.map.queryRenderedFeatures(e.point, { layers: [fillLayer] });
  if (features.length === 0 && this.popupLocked) {
    this.popupLocked = false;  // Incorrectly unlocked on event marker clicks!
    this.hidePopup();
  }
});
```

When clicking an event marker:
1. PointRadiusModel click handler fired -> set `popupLocked = true`
2. map-adapter click handler fired -> found NO choropleth features
3. Since `features.length === 0`, it reset `popupLocked = false` and hid popup

### Fix

Updated `map-adapter.js` to also check the `event-circle` layer:

```javascript
// AFTER (fixed)
this.map.on('click', (e) => {
  const fillFeatures = this.map.queryRenderedFeatures(e.point, { layers: [fillLayer] });
  const eventFeatures = this.map.queryRenderedFeatures(e.point, { layers: ['event-circle'] });
  const allFeatures = [...fillFeatures, ...eventFeatures];

  if (allFeatures.length === 0 && this.popupLocked) {
    this.popupLocked = false;
    this.hidePopup();
  }
});
```

### Files Changed

- `static/modules/map-adapter.js` - Line ~629

---

## Implementation Status Summary

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Core granularity support | DONE |
| Phase 2 | Sub-yearly timestamp support | DONE |
| Phase 3 | Multi-scale tabs | DONE |
| Phase 4 | Event drill-down integration | DONE |
| Phase 5 | Custom renderers | PARTIAL (SequenceAnimator done) |
| Phase 6 | Testing | IN PROGRESS |
| Phase 7 | Unified Continuous Speed Slider | DONE (spec complete, UI implemented) |
| Phase 8 | Timestamp Unification | DONE |

---

*Last updated: 2026-01-10 - Added Phase 8: Timestamp Unification, Popup Click Fix*
