# Time Slider Implementation Plan

## Overview

Enable time-series visualization with a slider that scrubs through years.
All data for the year range is loaded upfront; slider filtering is client-side (instant).

---

## Current Flow

```
User query -> Order Taker (LLM) -> Order with single year
                                          |
                                          v
                               Order Executor (Python)
                                          |
                                          v
                              GeoJSON for single year
                                          |
                                          v
                              MapAdapter.loadGeoJSON()
                                          |
                                          v
                                   Static fill color
```

## New Flow

```
User query -> Order Taker (LLM) -> Order with year_start/year_end
                                          |
                                          v
                               Order Executor (Python)
                                          |
                                          v
                     GeoJSON with ALL years in range
                     + year_range metadata {min, max}
                                          |
                                          v
                         App stores full dataset
                         TimeSlider.init(year_range)
                                          |
                                          v
                         TimeSlider filters to year
                         Map updates with choropleth
```

---

## Order Format Changes

### Current (single year)
```json
{
  "items": [{
    "source_id": "owid_co2",
    "metric": "co2",
    "region": "europe",
    "year": 2022
  }]
}
```

### New (year range)
```json
{
  "items": [{
    "source_id": "owid_co2",
    "metric": "co2",
    "region": "europe",
    "year_start": 2010,
    "year_end": 2022
  }]
}
```

### Backward Compatibility
- If `year` is provided (single year) -> behave as before
- If `year_start`/`year_end` provided -> load range
- If neither -> use latest year with data (current behavior)

---

## Backend Changes

### 1. order_taker.py - Prompt Update

Add to ORDER FORMAT section:
```
- year: Single year, OR use year_start/year_end for ranges
- year_start: Start of year range (for time series)
- year_end: End of year range (for time series)
- When user asks for "over time", "trend", "from X to Y" -> use year range
```

### 2. order_executor.py - Multi-Year Loading

```python
def execute_order(order: dict) -> dict:
    # ... existing code ...

    for item in items:
        year = item.get("year")
        year_start = item.get("year_start")
        year_end = item.get("year_end")

        # Determine year filtering mode
        if year_start and year_end:
            # Range mode - keep all years
            if "year" in df.columns:
                df = df[(df["year"] >= year_start) & (df["year"] <= year_end)]
            multi_year = True
        elif year:
            # Single year mode (existing)
            if "year" in df.columns:
                df = df[df["year"] == year]
            multi_year = False
        else:
            # Latest year mode (existing)
            # ... existing logic ...
            multi_year = False
```

### 3. Response Format for Multi-Year

```python
# For multi-year data, return features per location-year combination
# Each feature has properties including year

return {
    "type": "success",
    "geojson": {
        "type": "FeatureCollection",
        "features": features  # Multiple features per location (one per year)
    },
    "year_range": {
        "min": year_start,
        "max": year_end,
        "available_years": sorted(list(years_in_data))
    },
    "multi_year": True,
    "summary": summary,
    "count": len(features),
    "sources": source_info
}
```

### Alternative: Grouped by Year

Instead of duplicating geometry per year, return:
```json
{
  "geojson": {...},  // Base geometry (no year-specific values)
  "year_data": {
    "2010": {"USA": {"co2": 5000}, "GBR": {"co2": 400}, ...},
    "2011": {"USA": {"co2": 5100}, "GBR": {"co2": 390}, ...},
    ...
  },
  "year_range": {"min": 2010, "max": 2022}
}
```

**Recommendation**: Use the grouped approach - geometry stays constant, only values change.
This reduces response size significantly (geometry is ~95% of the payload).

---

## Frontend Changes

### 1. TimeSlider Component

```javascript
const TimeSlider = {
  container: null,
  slider: null,
  label: null,
  playButton: null,

  yearData: null,      // {year: {loc_id: {metrics}}}
  baseGeojson: null,   // Geometry without year-specific data
  currentYear: null,
  minYear: null,
  maxYear: null,
  isPlaying: false,
  playInterval: null,

  init(yearRange, yearData, baseGeojson) {
    this.minYear = yearRange.min;
    this.maxYear = yearRange.max;
    this.currentYear = yearRange.max;  // Start at latest
    this.yearData = yearData;
    this.baseGeojson = baseGeojson;

    this.createUI();
    this.show();
    this.setYear(this.currentYear);
  },

  createUI() {
    // Create slider container below order panel
    // Slider input element
    // Year label display
    // Play/pause button
  },

  setYear(year) {
    this.currentYear = year;
    this.label.textContent = year;
    this.slider.value = year;

    // Build GeoJSON for this year
    const geojson = this.buildYearGeojson(year);
    MapAdapter.loadGeoJSON(geojson);

    // Update choropleth colors
    ChoroplethManager.update(geojson);
  },

  buildYearGeojson(year) {
    // Clone base geojson, inject year-specific values
    const yearValues = this.yearData[year] || {};

    return {
      type: "FeatureCollection",
      features: this.baseGeojson.features.map(f => ({
        ...f,
        properties: {
          ...f.properties,
          ...yearValues[f.properties.loc_id],
          year: year
        }
      }))
    };
  },

  play() {
    this.isPlaying = true;
    this.playInterval = setInterval(() => {
      let nextYear = this.currentYear + 1;
      if (nextYear > this.maxYear) nextYear = this.minYear;
      this.setYear(nextYear);
    }, 500);  // 500ms per year
  },

  pause() {
    this.isPlaying = false;
    clearInterval(this.playInterval);
  },

  show() { this.container.style.display = 'block'; },
  hide() { this.container.style.display = 'none'; }
};
```

### 2. ChoroplethManager Component

```javascript
const ChoroplethManager = {
  metric: null,      // Which property to color by
  colorScale: null,  // Color interpolation function
  legend: null,      // Legend element

  init(metric, geojson) {
    this.metric = metric;

    // Calculate value range from data
    const values = geojson.features
      .map(f => f.properties[metric])
      .filter(v => v != null);

    const min = Math.min(...values);
    const max = Math.max(...values);

    // Create color scale (blue = low, red = high)
    this.colorScale = this.createScale(min, max);

    // Create legend
    this.createLegend(min, max);
  },

  createScale(min, max) {
    // Return function that maps value to color
    return (value) => {
      if (value == null) return '#cccccc';  // Gray for no data
      const t = (value - min) / (max - min);
      // Interpolate from blue to yellow to red
      return this.interpolateColor(t);
    };
  },

  interpolateColor(t) {
    // 0 = blue, 0.5 = yellow, 1 = red
    // Use HSL for smooth transitions
    const hue = (1 - t) * 240;  // 240=blue, 60=yellow, 0=red
    return `hsl(${hue}, 70%, 50%)`;
  },

  update(geojson) {
    // Update map layer colors based on values
    const colorExpression = this.buildColorExpression(geojson);
    MapAdapter.map.setPaintProperty('countries-fill', 'fill-color', colorExpression);
  },

  buildColorExpression(geojson) {
    // Build Mapbox GL expression for data-driven colors
    const cases = ['case'];

    for (const feature of geojson.features) {
      const value = feature.properties[this.metric];
      if (value != null) {
        cases.push(['==', ['get', 'loc_id'], feature.properties.loc_id]);
        cases.push(this.colorScale(value));
      }
    }

    cases.push('#cccccc');  // Default for no data
    return cases;
  },

  createLegend(min, max) {
    // Create gradient legend in corner of map
  }
};
```

### 3. UI Layout

```
+----------------------------------+
|           Map                    |
|                                  |
|                                  |
+----------------------------------+
| [2010]===|===========[2022]  [>] |  <- Time slider (below map or in sidebar)
|          2016                    |
+----------------------------------+
```

**Legend (bottom-left of map):**
```
CO2 Emissions
[===gradient===]
Low          High
0            5000
```

---

## Color Palette Options

### 1. Sequential (single metric, low to high)
- **Blues**: `#f7fbff` -> `#08306b` (light blue to dark blue)
- **Reds**: `#fff5f0` -> `#67000d` (pink to dark red)
- **Viridis**: `#440154` -> `#fde725` (purple to yellow, colorblind-friendly)

### 2. Diverging (positive/negative, center point)
- **RdYlGn**: Red -> Yellow -> Green (bad -> neutral -> good)
- **RdBu**: Red -> White -> Blue

### 3. For Change Over Time
When showing change between years:
- **Red** = decreased significantly
- **Orange** = decreased slightly
- **Gray** = no change
- **Light Green** = increased slightly
- **Dark Green** = increased significantly

---

## Implementation Order

### Phase A: Backend Multi-Year Support
1. Update order_taker.py prompt for year ranges
2. Modify order_executor.py to return multi-year data
3. Test with curl/Postman

### Phase B: Time Slider UI
1. Create TimeSlider component structure
2. Add HTML container to index.html
3. Wire up slider events
4. Test with mock data

### Phase C: Choropleth Coloring
1. Create ChoroplethManager component
2. Implement color scale calculation
3. Build Mapbox GL color expressions
4. Add legend

### Phase D: Integration
1. Connect TimeSlider to App.displayData
2. Handle play/pause animation
3. Test with real SDG data (has long time series)

---

## Test Cases

1. **Single year query**: "Show CO2 emissions in Europe for 2022"
   - Should work as before (no slider)

2. **Year range query**: "Show CO2 emissions in Europe from 2010 to 2022"
   - Should show slider, default to 2022
   - Scrubbing should update colors

3. **Trend query**: "Show poverty rate trend in Africa"
   - LLM should infer year range from data availability
   - Slider appears

4. **Animation**: Click play button
   - Should cycle through years automatically
   - Stop at end or loop

5. **No data for year**: Some countries missing data for certain years
   - Should show gray for missing data

---

## Files to Modify

| File | Changes |
|------|---------|
| `mapmover/order_taker.py` | Add year_start/year_end to prompt |
| `mapmover/order_executor.py` | Load and return multi-year data |
| `templates/index.html` | Add time slider container, legend container |
| `static/mapviewer.js` | Add TimeSlider, ChoroplethManager components |
| `static/mapviewer.js` | Modify App.displayData to handle multi-year |

---

## Performance Considerations

- **Data size**: 200 countries x 30 years x 1 metric = 6,000 data points (trivial)
- **Geometry size**: Same geometry reused for all years (no duplication)
- **Rendering**: Mapbox GL handles color updates efficiently
- **Slider updates**: Debounce to ~50ms for smooth scrubbing

---

*Ready for implementation after approval*
