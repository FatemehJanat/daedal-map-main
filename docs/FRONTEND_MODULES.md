# Frontend Modules

ES6 module structure for the map viewer application.

---

## Overview

The frontend is split into focused modules to improve maintainability. Each module has a single responsibility and exports its functionality for use by other modules.

**Entry point:** `static/modules/app.js`

---

## Module Summary

| Module | Purpose |
|--------|---------|
| config.js | Settings and constants (colors, API endpoints, layer IDs) |
| cache.js | In-memory caching for geometry features and location info |
| viewport-loader.js | Loading strategy - when and what to load based on viewport |
| map-adapter.js | MapLibre interface - layers, sources, events, popups |
| navigation.js | Breadcrumb navigation and hierarchy state |
| popup-builder.js | HTML generation for feature popups |
| chat-panel.js | Chat interface and order confirmation panel |
| time-slider.js | Year slider control for time-series data |
| choropleth.js | Geometry coloring, legends, and data visualization |
| sidebar.js | Sidebar UI - resize handles, width control, settings view |
| app.js | Main controller - wires everything together |

---

## Module Details

### config.js
Central configuration. No dependencies.
- Map defaults (center, zoom)
- Viewport loading settings (debounce, cache expiry)
- Color schemes (fill, stroke, hover, debug)
- Layer IDs for MapLibre
- API endpoints

### cache.js
Caching layer. Imports config.js.
- `GeometryCache` - Stores loaded geometry features with expiry
- `LocationInfoCache` - Caches API responses for location details

### viewport-loader.js
Loading strategy. Imports config.js, cache.js.
- Determines admin level based on viewport area
- Handles debounced loading on pan/zoom
- This is where performance tuning lives

### map-adapter.js
MapLibre abstraction. Imports config.js, cache.js.
- Map initialization and projection
- Layer management (add/remove/update)
- Event handlers (click, hover, zoom)
- Popup display
- City overlay loading
- Parent outline layer

### navigation.js
Breadcrumb state. Imports config.js.
- Navigation path tracking
- Breadcrumb UI updates
- Drill-down and navigate-up logic

### popup-builder.js
Popup HTML generation. No imports.
- Builds formatted popup content from feature properties
- Handles debug mode display
- Formats data values for display

### chat-panel.js
Chat and orders. Imports config.js.
- `ChatManager` - Chat message handling, API calls
- `OrderManager` - Order confirmation panel, data requests

### time-slider.js
Time-series control. No imports.
- Year slider UI
- Playback animation
- Updates map data for selected year

### choropleth.js
Data visualization. Imports config.js.
- Color scale calculation
- Legend rendering
- Data-driven styling expressions
- Future: heatmaps, bubble sizes, patterns

### sidebar.js
Sidebar UI components. No imports.
- `ResizeManager` - Vertical panel resizing
- `SidebarResizer` - Sidebar width control
- `SettingsManager` - Settings view and backup path config

### app.js
Main controller. Imports all modules.
- Wires module dependencies at startup
- Initializes all components
- Handles global state (debug mode, current data)
- Keyboard shortcuts

---

## Dependency Pattern

Modules use a `setDependencies` pattern to handle circular references:

```javascript
// In module file
let MapAdapter = null;

export function setDependencies(deps) {
  MapAdapter = deps.MapAdapter;
}

export const MyModule = {
  doSomething() {
    MapAdapter.someMethod();  // Use the injected dependency
  }
};
```

The `app.js` module wires dependencies during initialization.

---

## Adding a New Module

1. Create `static/modules/your-module.js`
2. Add exports and optional `setDependencies` function
3. Import in `app.js`
4. Wire dependencies in `App.init()` if needed

---

*Last Updated: 2026-01-01*
