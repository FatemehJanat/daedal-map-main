# Mapping and Visualization

Frontend display system using MapLibre GL JS with globe projection.

**Key files**:
- [static/mapviewer.js](static/mapviewer.js) - MapLibre GL map logic
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

## Time Slider (Planned)

See [TIME_SLIDER_PLAN.md](TIME_SLIDER_PLAN.md) for implementation details.

### Concept

```
+----------------------------------+
|           Map                    |
|                                  |
+----------------------------------+
| [2010]===|===========[2022]  [>] |  <- Time slider
|          2016                    |
+----------------------------------+
```

- Slider scrubs through years
- All year data loaded upfront
- Client-side filtering (instant)
- Play/pause animation

---

## Geometry Simplification

Geometries are simplified for web display to reduce file sizes.

### Recommended Tolerances

| Level | Tolerance | Precision | Use Case |
|-------|-----------|-----------|----------|
| Countries | 0.01 | ~1 km | World map view |
| States/Regions | 0.001 | ~100 m | Country zoom |
| Counties | 0.001 | ~100 m | State zoom |
| Cities/Districts | 0.0001 | ~10 m | County zoom |

### Size Impact

| File | Original | Simplified | Reduction |
|------|----------|------------|-----------|
| global.csv (256 countries) | 31 MB | 7.8 MB | 75% |
| USA.parquet (35,731 counties) | 63 MB | 30 MB | 53% |

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

### Click-to-Select Disambiguation

Handle ambiguous queries by letting users click on the map:
- Backend detects "Washington County" = 30 matches
- Frontend displays all matches with markers
- User clicks to select one or multiple

### Show Me Borders Command

Display geometry via conversational request:
- META intent type for border/geometry requests
- Returns geometry without data (for visual reference)
- Replaces current map content (not layered)
- User can then click to select regions for data queries

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

| Module | Purpose |
|--------|---------|
| MapAdapter | Core map initialization and layer management |
| ChoroplethManager | Color scale calculation and legend |
| TimeSlider | Year range slider and animation |
| PopupBuilder | Format feature properties for display |

---

*Last Updated: 2025-12-31*
