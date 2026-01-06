# Time Slider Granularity Update Plan

**Created:** January 5, 2026
**Status:** Phases 1-4 Implemented

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

*This plan will be updated as implementation progresses.*
