/**
 * Map Viewer - Modular Geographic Data Explorer
 *
 * Architecture:
 * - MapAdapter: Abstraction layer for map library (currently MapLibre, easy to swap)
 * - NavigationManager: Hierarchical navigation and breadcrumb state
 * - ChatManager: Sidebar chat functionality
 * - PopupBuilder: Popup content generation
 * - App: Main application controller
 */

// ============================================================================
// CONFIGURATION
// ============================================================================

const CONFIG = {
  // Map settings
  defaultCenter: [-78.64, 35.78],  // Centered on Raleigh, NC
  defaultZoom: 2.5,

  // Zoom thresholds for automatic navigation
  zoom: {
    world: 1.5,       // Show globe
    country: 3,       // Drill into country
    state: 5,         // Drill into state
    county: 7,        // Drill into county
    outThreshold: 0.8 // Zoom out this much below current level to go up
  },

  // Colors
  colors: {
    fill: '#2266aa',       // Darker blue
    fillOpacity: 0.4,
    fillHover: '#4488cc',  // Lighter blue on hover
    fillHoverOpacity: 0.6,
    stroke: '#1a5599',     // Dark blue stroke
    strokeWidth: 1,
    strokeHover: '#66aadd',
    strokeHoverWidth: 2
  },

  // Debug mode colors (by coverage ratio: actual_depth / expected_depth)
  // Press 'D' to toggle debug mode
  debugColors: {
    none: '#666666',   // Gray - no coverage data
    low: '#ff4444',    // Red - 0-49% coverage
    medium: '#ff9900', // Orange - 50-74% coverage
    high: '#ffcc00',   // Yellow - 75-99% coverage
    full: '#44aa44'    // Green - 100% coverage
  },

  // Layer IDs (for MapLibre)
  layers: {
    fill: 'regions-fill',
    stroke: 'regions-stroke',
    source: 'regions',
    // Parent outline layer (shows what region you're drilling into)
    parentSource: 'parent-region',
    parentStroke: 'parent-stroke',
    parentFill: 'parent-fill',
    // City overlay layer
    citySource: 'cities',
    cityCircle: 'cities-circle',
    cityLabel: 'cities-label',
    cityMinZoom: 8  // Cities appear at this zoom level
  },

  // API endpoints
  api: {
    countries: '/geometry/countries',
    children: '/geometry/{loc_id}/children',
    chat: '/chat'
  }
};

// ============================================================================
// MAP ADAPTER - Abstraction layer for map library
// Swap this section to change map libraries (MapLibre, Leaflet, deck.gl, etc.)
// ============================================================================

const MapAdapter = {
  map: null,
  popup: null,
  hoveredFeatureId: null,
  lastZoom: null,
  zoomNavigationEnabled: true,
  zoomDebounceTimer: null,
  citiesLoaded: false,
  currentStateLocId: null,
  currentRegionGeojson: null,  // Store current regions for parent outline

  /**
   * Initialize the map
   */
  init() {
    this.map = new maplibregl.Map({
      container: 'map',
      style: 'https://tiles.openfreemap.org/styles/liberty',
      center: CONFIG.defaultCenter,
      zoom: CONFIG.defaultZoom
    });

    // Create popup instance
    this.popup = new maplibregl.Popup({
      closeButton: true,
      closeOnClick: false,
      maxWidth: '320px'
    });

    // Enable globe projection when style loads
    this.map.on('style.load', () => {
      this.enableGlobe();
    });

    // Setup zoom-based navigation
    this.map.on('zoomend', () => this.handleZoomChange());
    this.map.on('zoom', () => this.updateZoomDisplay(this.map.getZoom()));

    return new Promise((resolve) => {
      this.map.on('load', () => {
        console.log('Map loaded');
        this.lastZoom = this.map.getZoom();
        this.updateZoomDisplay(this.lastZoom);
        resolve();
      });
    });
  },

  /**
   * Handle zoom changes for automatic navigation
   */
  handleZoomChange() {
    const currentZoom = this.map.getZoom();

    // Always update zoom display
    this.updateZoomDisplay(currentZoom);

    if (!this.zoomNavigationEnabled) return;

    const zoomDelta = currentZoom - (this.lastZoom || currentZoom);
    this.lastZoom = currentZoom;

    // Clear any pending navigation
    if (this.zoomDebounceTimer) {
      clearTimeout(this.zoomDebounceTimer);
    }

    // Debounce to avoid rapid navigation
    this.zoomDebounceTimer = setTimeout(() => {
      this.processZoomNavigation(currentZoom, zoomDelta);
    }, 300);
  },

  /**
   * Update the zoom level display
   */
  updateZoomDisplay(zoom) {
    const zoomEl = document.getElementById('zoomLevel');
    if (zoomEl) {
      zoomEl.textContent = `Zoom: ${zoom.toFixed(1)}`;
    }
  },

  /**
   * Process zoom level and trigger navigation if needed
   */
  processZoomNavigation(zoom, delta) {
    const level = NavigationManager.currentLevel;

    // Skip if navigation is in progress
    if (NavigationManager.isNavigating) {
      console.log('Navigation in progress, skipping zoom navigation');
      return;
    }

    // Zooming OUT - go up hierarchy (triggers 1-2 steps earlier)
    if (delta < -0.3) {
      // Define zoom thresholds for each level - when to go UP
      const thresholds = {
        'city': 7,        // Below zoom 7, go back to county/state (was 6)
        'us_county': 5,   // Below zoom 5, go back to state (was 4)
        'us_state': 3.5,  // Below zoom 3.5, go back to country (was 2.5)
        'state': 3.5,     // Below zoom 3.5, go back to country (was 2.5)
        'county': 5,      // Below zoom 5, go back to state (was 4)
        'country': 4      // Below zoom 4, go back to world
      };

      const threshold = thresholds[level];
      if (threshold !== undefined && zoom < threshold) {
        console.log(`Zoom out: ${zoom.toFixed(1)} < ${threshold} for level ${level}, navigating up`);
        this.navigateUp();
        return;
      }
    }

    // Zooming IN - drill down if hovering over a feature
    if (delta > 0.5 && this.hoveredFeatureId !== null) {
      const thresholds = {
        'world': CONFIG.zoom.country,
        'country': CONFIG.zoom.state,
        'us_state': CONFIG.zoom.county
      };

      const threshold = thresholds[level];
      if (threshold && zoom > threshold) {
        console.log(`Zoom in detected (${zoom.toFixed(1)}), drilling down from ${level}`);
        this.drillDownHovered();
      }
    }
  },

  /**
   * Navigate up one level in hierarchy
   */
  navigateUp() {
    // Check if we can go up and if navigation isn't already in progress
    if (NavigationManager.path.length <= 1) {
      console.log('Already at world level, cannot go up');
      return;
    }
    if (NavigationManager.isNavigating) {
      console.log('Navigation in progress, skipping navigateUp');
      return;
    }

    // Temporarily disable zoom navigation to prevent loops
    this.zoomNavigationEnabled = false;

    const targetIndex = NavigationManager.path.length - 2;
    console.log(`Navigating up to index ${targetIndex}: ${NavigationManager.path[targetIndex].name}`);
    NavigationManager.navigateTo(targetIndex);

    // Re-enable after navigation completes
    setTimeout(() => {
      this.zoomNavigationEnabled = true;
      this.lastZoom = this.map.getZoom();
    }, 1500);
  },

  /**
   * Drill down into the currently hovered feature
   */
  drillDownHovered() {
    if (this.hoveredFeatureId === null) return;
    if (NavigationManager.isNavigating) {
      console.log('Navigation in progress, skipping drillDownHovered');
      return;
    }

    // Get the hovered feature's properties
    const features = this.map.querySourceFeatures(CONFIG.layers.source, {
      filter: ['==', ['id'], this.hoveredFeatureId]
    });

    if (features.length > 0) {
      const feature = features[0];
      const locId = feature.properties.loc_id;
      const name = feature.properties.name || 'Unknown';

      if (locId) {
        // Temporarily disable zoom navigation
        this.zoomNavigationEnabled = false;

        App.drillDown(locId, name);

        // Re-enable after navigation completes
        setTimeout(() => {
          this.zoomNavigationEnabled = true;
          this.lastZoom = this.map.getZoom();
        }, 1500);
      }
    }
  },

  /**
   * Enable globe projection (3D sphere view)
   */
  enableGlobe() {
    try {
      this.map.setProjection({ type: 'globe' });
      console.log('Globe projection enabled');

      // Add space/atmosphere effect
      this.map.setSky({
        'sky-color': '#000011',           // Deep space blue-black
        'horizon-color': '#000033',       // Slightly lighter at horizon
        'fog-color': '#000011',           // Match space color
        'fog-ground-blend': 0.5,
        'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 5, 0.5, 10, 0]
      });

      // Add atmosphere glow around the globe
      this.map.setFog({
        'color': 'rgb(20, 30, 50)',        // Dark blue-gray fog
        'high-color': 'rgb(10, 15, 30)',   // Darker at high altitudes
        'horizon-blend': 0.1,
        'space-color': 'rgb(5, 5, 15)',    // Deep space color
        'star-intensity': 0.3              // Subtle stars
      });

    } catch (e) {
      console.log('Globe projection not available:', e.message);
    }
  },

  /**
   * Load GeoJSON data onto the map
   * @param {Object} geojson - GeoJSON FeatureCollection
   * @param {boolean} debugMode - If true, use hierarchy-depth colors
   */
  loadGeoJSON(geojson, debugMode = false) {
    // Add unique IDs to features for hover state
    geojson.features.forEach((feature, index) => {
      feature.id = index;
    });

    // Store current geojson for use as parent outline later
    this.currentRegionGeojson = geojson;

    // Remove existing source and layers
    this.clearLayers();

    // Add source
    this.map.addSource(CONFIG.layers.source, {
      type: 'geojson',
      data: geojson,
      generateId: true
    });

    // Determine fill color based on debug mode
    const fillColor = debugMode
      ? this.getDebugFillColorExpression()
      : [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          CONFIG.colors.fillHover,
          CONFIG.colors.fill
        ];

    // Add fill layer
    this.map.addLayer({
      id: CONFIG.layers.fill,
      type: 'fill',
      source: CONFIG.layers.source,
      paint: {
        'fill-color': fillColor,
        'fill-opacity': [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          CONFIG.colors.fillHoverOpacity,
          CONFIG.colors.fillOpacity
        ]
      }
    });

    // Add stroke layer
    this.map.addLayer({
      id: CONFIG.layers.stroke,
      type: 'line',
      source: CONFIG.layers.source,
      paint: {
        'line-color': [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          CONFIG.colors.strokeHover,
          CONFIG.colors.stroke
        ],
        'line-width': [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          CONFIG.colors.strokeHoverWidth,
          CONFIG.colors.strokeWidth
        ]
      }
    });

    // Setup event handlers
    this.setupEventHandlers();

    // Update stats
    document.getElementById('totalAreas').textContent = geojson.features.length;
  },

  /**
   * Get MapLibre expression for debug fill color based on coverage ratio
   * Coverage = actual_depth / expected_depth (0 to 1)
   */
  getDebugFillColorExpression() {
    // Use step expression based on coverage value (0-1)
    return [
      'case',
      ['boolean', ['feature-state', 'hover'], false],
      '#ffffff',  // White on hover for debug mode
      [
        'step',
        ['coalesce', ['get', 'coverage'], 0],
        CONFIG.debugColors.none,   // Default: gray (no data)
        0.01, CONFIG.debugColors.low,    // 0-49%: red
        0.50, CONFIG.debugColors.medium, // 50-74%: orange
        0.75, CONFIG.debugColors.high,   // 75-99%: yellow
        1.0, CONFIG.debugColors.full     // 100%: green
      ]
    ];
  },

  /**
   * Update fill colors based on debug mode
   * @param {boolean} debugMode - Whether debug mode is on
   */
  updateDebugColors(debugMode) {
    if (!this.map.getLayer(CONFIG.layers.fill)) return;

    const fillColor = debugMode
      ? this.getDebugFillColorExpression()
      : [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          CONFIG.colors.fillHover,
          CONFIG.colors.fill
        ];

    this.map.setPaintProperty(CONFIG.layers.fill, 'fill-color', fillColor);
    console.log(`Fill colors updated for ${debugMode ? 'debug' : 'normal'} mode`);
  },

  /**
   * Clear all layers and sources
   */
  clearLayers() {
    if (this.map.getLayer(CONFIG.layers.fill)) {
      this.map.removeLayer(CONFIG.layers.fill);
    }
    if (this.map.getLayer(CONFIG.layers.stroke)) {
      this.map.removeLayer(CONFIG.layers.stroke);
    }
    if (this.map.getSource(CONFIG.layers.source)) {
      this.map.removeSource(CONFIG.layers.source);
    }
  },

  /**
   * Setup mouse and click event handlers
   */
  setupEventHandlers() {
    const fillLayer = CONFIG.layers.fill;

    // Click handler
    this.map.on('click', fillLayer, (e) => {
      if (e.features.length > 0) {
        const feature = e.features[0];
        App.handleFeatureClick(feature, e.lngLat);
      }
    });

    // Double-click handler for drill-down
    this.map.on('dblclick', fillLayer, (e) => {
      e.preventDefault();
      if (e.features.length > 0) {
        const feature = e.features[0];
        App.handleFeatureDrillDown(feature);
      }
    });

    // Hover handlers
    this.map.on('mousemove', fillLayer, (e) => {
      if (e.features.length > 0) {
        // Reset previous hover state
        if (this.hoveredFeatureId !== null) {
          this.map.setFeatureState(
            { source: CONFIG.layers.source, id: this.hoveredFeatureId },
            { hover: false }
          );
        }

        // Set new hover state
        this.hoveredFeatureId = e.features[0].id;
        this.map.setFeatureState(
          { source: CONFIG.layers.source, id: this.hoveredFeatureId },
          { hover: true }
        );

        this.map.getCanvas().style.cursor = 'pointer';
      }
    });

    this.map.on('mouseleave', fillLayer, () => {
      if (this.hoveredFeatureId !== null) {
        this.map.setFeatureState(
          { source: CONFIG.layers.source, id: this.hoveredFeatureId },
          { hover: false }
        );
      }
      this.hoveredFeatureId = null;
      this.map.getCanvas().style.cursor = '';
    });
  },

  /**
   * Show popup at location
   * @param {Array} lngLat - [longitude, latitude]
   * @param {string} html - Popup HTML content
   */
  showPopup(lngLat, html) {
    this.popup
      .setLngLat(lngLat)
      .setHTML(html)
      .addTo(this.map);
  },

  /**
   * Hide popup
   */
  hidePopup() {
    this.popup.remove();
  },

  /**
   * Fly to a location
   * @param {Array} center - [longitude, latitude]
   * @param {number} zoom - Zoom level
   */
  flyTo(center, zoom) {
    this.map.flyTo({
      center: center,
      zoom: zoom,
      duration: 1500
    });
  },

  // Fixed center points for countries with problematic bounding boxes
  countryFixedCenters: {
    'USA': { center: [-98.5, 39.5], zoom: 4 },  // Center of contiguous US
    'RUS': { center: [100, 60], zoom: 3 },      // Russia spans many time zones
    'FJI': { center: [178, -18], zoom: 6 }      // Fiji crosses date line
  },

  /**
   * Fit map to GeoJSON bounds
   * @param {Object} geojson - GeoJSON FeatureCollection
   * @param {Object} options - Optional settings like minZoom
   */
  fitToBounds(geojson, options = {}) {
    if (!geojson || !geojson.features || geojson.features.length === 0) return;

    // Check if this is a single country with a fixed center
    if (geojson.features.length > 1) {
      const firstFeature = geojson.features[0];
      const parentId = firstFeature.properties?.parent_id;
      if (parentId && this.countryFixedCenters[parentId]) {
        const fixed = this.countryFixedCenters[parentId];
        this.map.flyTo({
          center: fixed.center,
          zoom: options.minZoom || fixed.zoom,
          duration: 1000
        });
        return;
      }
    }

    // Calculate bounds from all features
    const bounds = new maplibregl.LngLatBounds();

    geojson.features.forEach(feature => {
      if (feature.geometry) {
        this.extendBoundsWithGeometry(bounds, feature.geometry);
      }
    });

    if (!bounds.isEmpty()) {
      this.map.fitBounds(bounds, {
        padding: 50,
        duration: 1000,
        maxZoom: options.maxZoom || 10,
        minZoom: options.minZoom || undefined
      });
    }
  },

  /**
   * Extend bounds with geometry coordinates
   * @param {LngLatBounds} bounds - MapLibre bounds object
   * @param {Object} geometry - GeoJSON geometry
   */
  extendBoundsWithGeometry(bounds, geometry) {
    const type = geometry.type;
    const coords = geometry.coordinates;

    if (type === 'Point') {
      bounds.extend(coords);
    } else if (type === 'Polygon') {
      coords[0].forEach(coord => bounds.extend(coord));
    } else if (type === 'MultiPolygon') {
      coords.forEach(polygon => {
        polygon[0].forEach(coord => bounds.extend(coord));
      });
    }
  },

  /**
   * Get current map center and zoom
   * @returns {Object} {center, zoom}
   */
  getView() {
    return {
      center: this.map.getCenter(),
      zoom: this.map.getZoom()
    };
  },

  /**
   * Load city markers for a location (state or county)
   * @param {string} locId - Location loc_id (e.g., "USA-CA" for state, "USA-CA-06037" for county)
   */
  async loadCityOverlay(locId) {
    // Only load if we're in a US location and haven't already loaded for this location
    if (!locId || !locId.startsWith('USA-') || locId === this.currentStateLocId) {
      return;
    }

    console.log(`Loading city overlay for ${locId}`);
    this.currentStateLocId = locId;

    try {
      // Fetch cities for this location
      const response = await fetch(`/geometry/${locId}/places`);
      if (!response.ok) {
        console.log('No city data available for', locId);
        return;
      }

      const result = await response.json();
      if (!result.geojson || !result.geojson.features || result.geojson.features.length === 0) {
        console.log('No cities found for', locId);
        return;
      }

      // Remove existing city layers
      this.clearCityOverlay();

      // Add city source
      this.map.addSource(CONFIG.layers.citySource, {
        type: 'geojson',
        data: result.geojson
      });

      // Add outer glow layer (largest, most transparent)
      this.map.addLayer({
        id: CONFIG.layers.cityCircle + '-glow-outer',
        type: 'circle',
        source: CONFIG.layers.citySource,
        minzoom: CONFIG.layers.cityMinZoom,
        paint: {
          'circle-radius': 16,
          'circle-color': '#00ffff',
          'circle-opacity': 0.15,
          'circle-blur': 1
        }
      });

      // Add middle glow layer
      this.map.addLayer({
        id: CONFIG.layers.cityCircle + '-glow-mid',
        type: 'circle',
        source: CONFIG.layers.citySource,
        minzoom: CONFIG.layers.cityMinZoom,
        paint: {
          'circle-radius': 10,
          'circle-color': '#00ffff',
          'circle-opacity': 0.3,
          'circle-blur': 0.8
        }
      });

      // Add inner glow layer
      this.map.addLayer({
        id: CONFIG.layers.cityCircle + '-glow-inner',
        type: 'circle',
        source: CONFIG.layers.citySource,
        minzoom: CONFIG.layers.cityMinZoom,
        paint: {
          'circle-radius': 6,
          'circle-color': '#66ffff',
          'circle-opacity': 0.5,
          'circle-blur': 0.5
        }
      });

      // Add city circle markers (bright center point)
      this.map.addLayer({
        id: CONFIG.layers.cityCircle,
        type: 'circle',
        source: CONFIG.layers.citySource,
        minzoom: CONFIG.layers.cityMinZoom,
        paint: {
          'circle-radius': 3,
          'circle-color': '#ffffff',
          'circle-opacity': 1
        }
      });

      // Add city labels (bright white text for dark maps)
      this.map.addLayer({
        id: CONFIG.layers.cityLabel,
        type: 'symbol',
        source: CONFIG.layers.citySource,
        minzoom: CONFIG.layers.cityMinZoom + 1,
        layout: {
          'text-field': ['get', 'name'],
          'text-size': 12,
          'text-offset': [0, 1.5],
          'text-anchor': 'top',
          'text-font': ['Open Sans Bold', 'Arial Unicode MS Bold']
        },
        paint: {
          'text-color': '#ffffff',
          'text-halo-color': 'rgba(0, 40, 80, 0.8)',
          'text-halo-width': 2
        }
      });

      // Add click handler for cities
      this.map.on('click', CONFIG.layers.cityCircle, (e) => {
        if (e.features.length > 0) {
          const feature = e.features[0];
          const props = feature.properties;
          const name = props.name || 'Unknown City';
          const html = `<strong>${name}</strong><br>Population: ${props.population ? props.population.toLocaleString() : 'N/A'}`;
          this.showPopup([e.lngLat.lng, e.lngLat.lat], html);
        }
      });

      // Hover cursor for cities
      this.map.on('mouseenter', CONFIG.layers.cityCircle, () => {
        this.map.getCanvas().style.cursor = 'pointer';
      });
      this.map.on('mouseleave', CONFIG.layers.cityCircle, () => {
        this.map.getCanvas().style.cursor = '';
      });

      this.citiesLoaded = true;
      console.log(`Loaded ${result.geojson.features.length} cities for ${locId}`);

    } catch (error) {
      console.log('Error loading cities:', error.message);
    }
  },

  /**
   * Clear city overlay layers
   */
  clearCityOverlay() {
    // Remove label layer
    if (this.map.getLayer(CONFIG.layers.cityLabel)) {
      this.map.removeLayer(CONFIG.layers.cityLabel);
    }
    // Remove center circle
    if (this.map.getLayer(CONFIG.layers.cityCircle)) {
      this.map.removeLayer(CONFIG.layers.cityCircle);
    }
    // Remove glow layers
    if (this.map.getLayer(CONFIG.layers.cityCircle + '-glow-inner')) {
      this.map.removeLayer(CONFIG.layers.cityCircle + '-glow-inner');
    }
    if (this.map.getLayer(CONFIG.layers.cityCircle + '-glow-mid')) {
      this.map.removeLayer(CONFIG.layers.cityCircle + '-glow-mid');
    }
    if (this.map.getLayer(CONFIG.layers.cityCircle + '-glow-outer')) {
      this.map.removeLayer(CONFIG.layers.cityCircle + '-glow-outer');
    }
    // Remove source
    if (this.map.getSource(CONFIG.layers.citySource)) {
      this.map.removeSource(CONFIG.layers.citySource);
    }
    this.citiesLoaded = false;
    this.currentStateLocId = null;
  },

  /**
   * Set the parent outline layer (shows the region you drilled into)
   * @param {Object} geojson - GeoJSON FeatureCollection of the parent region
   */
  setParentOutline(geojson) {
    // Clear existing parent outline
    this.clearParentOutline();

    if (!geojson || !geojson.features || geojson.features.length === 0) {
      return;
    }

    // Add parent source
    this.map.addSource(CONFIG.layers.parentSource, {
      type: 'geojson',
      data: geojson
    });

    // Add subtle fill for parent region (very low opacity, below children)
    this.map.addLayer({
      id: CONFIG.layers.parentFill,
      type: 'fill',
      source: CONFIG.layers.parentSource,
      paint: {
        'fill-color': '#ff7800',
        'fill-opacity': 0.08
      }
    }, CONFIG.layers.fill);  // Insert below the main fill layer

    // Add parent outline stroke (thicker, on top of everything to be visible)
    this.map.addLayer({
      id: CONFIG.layers.parentStroke,
      type: 'line',
      source: CONFIG.layers.parentSource,
      paint: {
        'line-color': '#cc4400',
        'line-width': 4,
        'line-opacity': 0.9
      }
    });  // No 'before' parameter = add on top

    console.log('Parent outline layer added');
  },

  /**
   * Clear the parent outline layer
   */
  clearParentOutline() {
    if (this.map.getLayer(CONFIG.layers.parentStroke)) {
      this.map.removeLayer(CONFIG.layers.parentStroke);
    }
    if (this.map.getLayer(CONFIG.layers.parentFill)) {
      this.map.removeLayer(CONFIG.layers.parentFill);
    }
    if (this.map.getSource(CONFIG.layers.parentSource)) {
      this.map.removeSource(CONFIG.layers.parentSource);
    }
  },

  /**
   * Full memory cleanup - call when switching major views
   */
  cleanup() {
    this.clearLayers();
    this.clearParentOutline();
    this.clearCityOverlay();
    this.currentRegionGeojson = null;
    this.hoveredFeatureId = null;
  }
};

// ============================================================================
// NAVIGATION MANAGER - Hierarchical navigation state
// ============================================================================

const NavigationManager = {
  path: [],  // Array of {loc_id, name, level}
  currentLevel: 'world',
  isNavigating: false,  // Flag to prevent duplicate navigation

  /**
   * Reset navigation to world view
   */
  reset() {
    this.path = [{ loc_id: 'world', name: 'World', level: 'world' }];
    this.currentLevel = 'world';
    this.isNavigating = false;
    this.updateBreadcrumb();
  },

  /**
   * Push a new location onto the navigation path
   * @param {string} locId - Location ID
   * @param {string} name - Display name
   * @param {string} level - Geographic level
   */
  push(locId, name, level) {
    // Prevent duplicate entries - check if last entry has same loc_id
    const lastEntry = this.path[this.path.length - 1];
    if (lastEntry && lastEntry.loc_id === locId) {
      console.log(`Skipping duplicate navigation entry: ${locId}`);
      return;
    }
    this.path.push({ loc_id: locId, name: name, level: level });
    this.currentLevel = level;
    this.updateBreadcrumb();
  },

  /**
   * Navigate up to a specific index in the path
   * @param {number} index - Target index
   */
  async navigateTo(index) {
    if (index < 0 || index >= this.path.length - 1) return;

    // Prevent duplicate navigation
    if (this.isNavigating) {
      console.log('Navigation already in progress, skipping');
      return;
    }
    this.isNavigating = true;

    const target = this.path[index];
    this.path = this.path.slice(0, index + 1);
    this.currentLevel = target.level;
    this.updateBreadcrumb();

    // Clear all overlays when navigating back (memory cleanup)
    MapAdapter.clearParentOutline();
    MapAdapter.clearCityOverlay();

    try {
      if (target.loc_id === 'world') {
        await App.loadCountries();
      } else {
        // Navigate to target's children (no parent outline when going back)
        await App.drillDown(target.loc_id, target.name, true);
      }
    } finally {
      this.isNavigating = false;
    }
  },

  /**
   * Update breadcrumb UI
   */
  updateBreadcrumb() {
    const container = document.getElementById('breadcrumb');
    if (!container) return;

    const crumbs = this.path.map((item, index) => {
      const isLast = index === this.path.length - 1;
      if (isLast) {
        return `<span class="current">${item.name}</span>`;
      } else {
        return `<span onclick="NavigationManager.navigateTo(${index})">${item.name}</span>`;
      }
    });

    container.innerHTML = crumbs.join(' &gt; ');
  },

  /**
   * Get zoom level based on current navigation depth
   * @returns {number} Recommended zoom level
   */
  getZoomForLevel() {
    switch (this.currentLevel) {
      case 'world': return CONFIG.zoom.world;
      case 'country': return CONFIG.zoom.country;
      case 'us_state': return CONFIG.zoom.state;
      case 'state': return CONFIG.zoom.state;
      case 'us_county': return CONFIG.zoom.county;
      case 'county': return CONFIG.zoom.county;
      case 'city': return 10;
      default: return 4;
    }
  }
};

// Make navigateTo available globally for onclick handlers
window.NavigationManager = NavigationManager;

// ============================================================================
// POPUP BUILDER - Generate popup HTML content
// ============================================================================

const PopupBuilder = {
  // Fields to skip in popup display
  skipFields: [
    'geometry', 'coordinates', 'country', 'country_name', 'country_code',
    'name', 'Name', 'Location', 'stusab', 'state', 'name_long',
    'Admin Country Name', 'Sov Country Name', 'postal', 'Admin Country Abbr',
    'Sov Country Abbr', 'name_sort', 'formal_en', 'iso_code', 'continent',
    'Admin Type', 'type', 'population_year', 'gdp_year', 'economy type',
    'income_group', 'UN Region', 'subregion', 'region_wb', 'Longitude',
    'Latitude', 'data_year', 'loc_id', 'parent_id', 'level', 'code', 'abbrev'
  ],

  /**
   * Build popup HTML from feature properties
   * @param {Object} properties - Feature properties
   * @param {Object} sourceData - Optional source metadata
   * @returns {string} HTML content
   */
  build(properties, sourceData = null) {
    const lines = [];

    // Title
    const name = properties.name || properties.country_name ||
                 properties.country || properties.Name || 'Unknown';
    const stateAbbr = properties.stusab || properties.abbrev || '';
    lines.push(`<strong>${name}${stateAbbr ? ', ' + stateAbbr : ''}</strong>`);

    // Debug mode: show coverage info
    if (App.debugMode && properties.coverage !== undefined) {
      lines.push(this.buildHierarchyInfo(properties));
    } else {
      // Normal mode: show data fields
      const relevantFields = this.getRelevantFields(properties);
      const fieldsToShow = relevantFields.length > 0 ? relevantFields :
        Object.keys(properties).filter(k =>
          !this.skipFields.includes(k) &&
          k.toLowerCase() !== 'year' &&
          properties[k] != null &&
          properties[k] !== ''
        );

      for (const key of fieldsToShow.slice(0, 8)) {  // Limit to 8 fields
        const value = properties[key];
        if (value == null || value === '') continue;

        const fieldName = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        const formattedValue = this.formatValue(key, value);
        const year = properties.year || properties.data_year || '';
        const yearSuffix = year ? ` (${year})` : '';

        lines.push(`${fieldName}: ${formattedValue}${yearSuffix}`);
      }

      // Source info
      if (sourceData) {
        lines.push('<br>');
        if (sourceData.sources && sourceData.sources.length > 0) {
          lines.push('<strong>Sources:</strong>');
          for (const source of sourceData.sources.slice(0, 3)) {
            if (source.url && source.url !== 'Unknown') {
              lines.push(`- <a href="${source.url}" target="_blank">${source.name}</a>`);
            } else {
              lines.push(`- ${source.name}`);
            }
          }
        } else if (sourceData.source_name) {
          lines.push(`<strong>Source:</strong> ${sourceData.source_name}`);
        }
      }
    }

    // Hint for drill-down
    lines.push('<br><em style="font-size: 11px; color: #666;">Double-click to drill down</em>');

    return lines.join('<br>');
  },

  /**
   * Build coverage info for debug mode popup
   * @param {Object} properties - Feature properties with coverage data
   * @returns {string} HTML content for coverage info
   */
  buildHierarchyInfo(properties) {
    const actualDepth = properties.actual_depth || 0;
    const expectedDepth = properties.expected_depth || 1;
    const coverage = properties.coverage || 0;
    let levelCounts = properties.level_counts || {};

    // Parse if it's a JSON string (GeoJSON stringifies nested objects)
    if (typeof levelCounts === 'string') {
      try {
        levelCounts = JSON.parse(levelCounts);
      } catch (e) {
        levelCounts = {};
      }
    }

    const lines = [];
    const coveragePct = Math.round(coverage * 100);
    const coverageColor = coverage >= 1 ? '#44aa44' : coverage >= 0.5 ? '#ff9900' : '#ff4444';

    lines.push(`<br><strong style="color: ${coverageColor};">Coverage: ${coveragePct}%</strong>`);
    lines.push(`Depth: ${actualDepth}/${expectedDepth} levels`);

    // Show level counts
    const levelNames = ['country', 'state', 'county', 'place'];
    for (let i = 0; i <= actualDepth && i < levelNames.length; i++) {
      const count = levelCounts[String(i)] || 0;
      if (count > 0) {
        lines.push(`<span style="color: #44aa44;">${levelNames[i]}: ${count.toLocaleString()}</span>`);
      }
    }

    return lines.join('<br>');
  },

  /**
   * Get relevant data fields (numeric, interesting values)
   */
  getRelevantFields(properties) {
    const relevant = [];
    const keywords = ['co2', 'gdp', 'population', 'emission', 'capita', 'total',
                      'methane', 'temperature', 'energy', 'oil', 'gas', 'coal'];

    for (const [key, value] of Object.entries(properties)) {
      if (this.skipFields.includes(key) || value == null || value === '') continue;
      if (key.toLowerCase() === 'year') continue;

      const keyLower = key.toLowerCase();
      const isNumeric = !isNaN(parseFloat(value));
      const isRelevant = keywords.some(kw => keyLower.includes(kw));

      if (isNumeric && isRelevant) {
        relevant.push(key);
      }
    }
    return relevant;
  },

  /**
   * Format a value for display
   */
  formatValue(key, value) {
    const keyLower = key.toLowerCase();
    const numValue = parseFloat(value);

    if (!isNaN(numValue)) {
      if (keyLower.includes('gdp') && !keyLower.includes('per')) {
        if (numValue > 1e9) return `$${(numValue / 1e9).toFixed(2)} billion`;
        if (numValue > 1e6) return `$${(numValue / 1e6).toFixed(2)} million`;
        return `$${numValue.toLocaleString()}`;
      }
      if (keyLower.includes('co2')) {
        if (keyLower.includes('per_capita') || keyLower.includes('percapita')) {
          return `${numValue.toFixed(2)} tonnes/person`;
        }
        return `${numValue.toFixed(2)} million tonnes`;
      }
      if (keyLower.includes('population') || keyLower.includes('pop')) {
        return numValue.toLocaleString();
      }
      if (keyLower.includes('percent') || keyLower.includes('rate')) {
        return `${numValue.toFixed(1)}%`;
      }
      if (numValue > 1000) return numValue.toLocaleString();
      return numValue.toFixed(2);
    }
    return value;
  }
};

// ============================================================================
// CHAT MANAGER - Sidebar chat functionality
// ============================================================================

const ChatManager = {
  history: [],
  sessionId: null,
  elements: {},

  /**
   * Initialize chat manager
   */
  init() {
    this.sessionId = 'sess_' + Date.now() + '_' + Math.random().toString(36).substring(2, 11);

    // Cache DOM elements
    this.elements = {
      sidebar: document.getElementById('sidebar'),
      toggle: document.getElementById('sidebarToggle'),
      close: document.getElementById('closeSidebar'),
      messages: document.getElementById('chatMessages'),
      form: document.getElementById('chatForm'),
      input: document.getElementById('chatInput'),
      sendBtn: document.getElementById('sendBtn')
    };

    this.setupEventListeners();
  },

  /**
   * Setup event listeners
   */
  setupEventListeners() {
    const { sidebar, toggle, close, form, input } = this.elements;

    // Sidebar toggle
    toggle.addEventListener('click', () => {
      sidebar.classList.remove('collapsed');
      toggle.style.display = 'none';
    });

    close.addEventListener('click', () => {
      sidebar.classList.add('collapsed');
      toggle.style.display = 'flex';
    });

    // Auto-resize textarea
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });

    // Enter to send
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        form.dispatchEvent(new Event('submit'));
      }
    });

    // Form submission
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      await this.handleSubmit();
    });
  },

  /**
   * Handle form submission
   */
  async handleSubmit() {
    const { input, sendBtn } = this.elements;
    const query = input.value.trim();
    if (!query) return;

    // Add user message
    this.addMessage(query, 'user');
    input.value = '';
    input.style.height = 'auto';

    // Disable input
    sendBtn.disabled = true;
    input.disabled = true;

    // Show typing indicator
    const indicator = this.showTypingIndicator();

    try {
      const response = await this.sendQuery(query);

      // Handle response based on type (Order Taker model)
      switch (response.type) {
        case 'order':
          // LLM created an order - show in order panel for confirmation
          this.addMessage(response.summary || 'Added to your order. Click "Display on Map" when ready.', 'assistant');
          OrderManager.setOrder(response.order, response.summary);
          break;

        case 'clarify':
          // LLM needs more information
          this.addMessage(response.message || 'Could you be more specific?', 'assistant');
          break;

        case 'data':
          // Direct data response (from confirmed order)
          this.addMessage(response.summary || 'Here is your data.', 'assistant');
          App.displayData(response);
          break;

        case 'chat':
        default:
          // General chat response or legacy format
          if (response.geojson && response.geojson.features && response.geojson.features.length > 0) {
            const message = response.summary || response.message || 'Found data for you.';
            this.addMessage(message, 'assistant');
            App.displayData(response);
          } else {
            const message = response.summary || response.message || 'Could you be more specific?';
            this.addMessage(message, 'assistant');
          }
          break;
      }
    } catch (error) {
      console.error('Chat error:', error);
      this.addMessage('Sorry, something went wrong. Please try again.', 'assistant');
    } finally {
      indicator.remove();
      sendBtn.disabled = false;
      input.disabled = false;
      input.focus();
    }
  },

  /**
   * Send query to API
   */
  async sendQuery(query) {
    this.history.push({ role: 'user', content: query });

    const view = MapAdapter.getView();
    const apiUrl = (typeof API_BASE_URL !== 'undefined' && API_BASE_URL)
      ? `${API_BASE_URL}/chat`
      : '/chat';

    const response = await fetch(apiUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        currentView: {
          clat: view.center.lat,
          clng: view.center.lng,
          czoom: view.zoom
        },
        chatHistory: this.history.slice(-10),
        sessionId: this.sessionId
      })
    });

    if (!response.ok) {
      throw new Error('Failed to get response: ' + response.statusText);
    }

    const data = await response.json();
    this.history.push({ role: 'assistant', content: data.message || data.summary });

    return data;
  },

  /**
   * Add message to chat
   */
  addMessage(text, type, options = {}) {
    const { messages } = this.elements;
    const div = document.createElement('div');
    div.className = `chat-message ${type}`;

    if (options.html) {
      div.innerHTML = text;
    } else if (type === 'assistant') {
      // For assistant messages, render basic formatting:
      // - Convert newlines to <br>
      // - Bold text with **text** or __text__
      // - Numbered lists (1. item)
      // - Bullet lists (- item)
      let formatted = this.escapeHtml(text);

      // Bold: **text** or __text__
      formatted = formatted.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      formatted = formatted.replace(/__(.+?)__/g, '<strong>$1</strong>');

      // Newlines to <br>
      formatted = formatted.replace(/\n/g, '<br>');

      div.innerHTML = formatted;
    } else {
      div.textContent = text;
    }

    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
  },

  /**
   * Escape HTML for safe rendering
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },

  /**
   * Show typing indicator
   */
  showTypingIndicator() {
    const { messages } = this.elements;
    const indicator = document.createElement('div');
    indicator.className = 'typing-indicator';
    indicator.innerHTML = '<span></span><span></span><span></span>';
    messages.appendChild(indicator);
    messages.scrollTop = messages.scrollHeight;
    return indicator;
  }
};

// ============================================================================
// ORDER MANAGER - Order panel for confirming data requests
// ============================================================================

const OrderManager = {
  currentOrder: null,
  elements: {},

  /**
   * Initialize order manager
   */
  init() {
    this.elements = {
      panel: document.getElementById('orderPanel'),
      count: document.getElementById('orderCount'),
      summary: document.getElementById('orderSummary'),
      items: document.getElementById('orderItems'),
      confirmBtn: document.getElementById('orderConfirmBtn'),
      cancelBtn: document.getElementById('orderCancelBtn')
    };

    this.setupEventListeners();
    this.render();
  },

  /**
   * Setup event listeners
   */
  setupEventListeners() {
    const { confirmBtn, cancelBtn } = this.elements;

    confirmBtn.addEventListener('click', () => {
      this.confirmOrder();
    });

    cancelBtn.addEventListener('click', () => {
      this.clearOrder();
    });
  },

  /**
   * Set a new order from the LLM response
   * @param {Object} order - The order object from backend
   * @param {string} summary - Summary text from LLM
   */
  setOrder(order, summary) {
    this.currentOrder = order;
    this.render(summary);
  },

  /**
   * Clear the current order
   */
  clearOrder() {
    this.currentOrder = null;
    this.render();
  },

  /**
   * Remove a specific item from the order
   * @param {number} index - Index of item to remove
   */
  removeItem(index) {
    if (!this.currentOrder || !this.currentOrder.items) return;

    this.currentOrder.items.splice(index, 1);

    if (this.currentOrder.items.length === 0) {
      this.currentOrder = null;
    }

    this.render();
  },

  /**
   * Render the order panel
   * @param {string} summary - Optional summary text
   */
  render(summary = '') {
    const { count, items, confirmBtn, summary: summaryEl } = this.elements;

    // Update summary
    summaryEl.textContent = summary || '';

    // No order - show empty state
    if (!this.currentOrder || !this.currentOrder.items || this.currentOrder.items.length === 0) {
      count.textContent = '(empty)';
      items.innerHTML = '<div style="color: #999; font-size: 12px; text-align: center; padding: 10px;">Ask for data to add items here</div>';
      confirmBtn.disabled = true;
      return;
    }

    // Has order - render items
    const orderItems = this.currentOrder.items;
    count.textContent = `(${orderItems.length} item${orderItems.length > 1 ? 's' : ''})`;
    confirmBtn.disabled = false;

    items.innerHTML = orderItems.map((item, index) => {
      const name = item.metric_label || item.metric || 'Data';
      const region = item.region || 'All';
      const year = item.year || '';
      const source = item.source || '';

      const details = [region, year, source].filter(Boolean).join(' | ');

      return `
        <div class="order-item">
          <div class="order-item-info">
            <div class="order-item-name">${this.escapeHtml(name)}</div>
            <div class="order-item-details">${this.escapeHtml(details)}</div>
          </div>
          <button class="order-item-remove" onclick="OrderManager.removeItem(${index})" title="Remove">x</button>
        </div>
      `;
    }).join('');
  },

  /**
   * Confirm and execute the order
   */
  async confirmOrder() {
    if (!this.currentOrder) return;

    const { confirmBtn } = this.elements;
    confirmBtn.disabled = true;
    confirmBtn.textContent = 'Loading...';

    try {
      const apiUrl = (typeof API_BASE_URL !== 'undefined' && API_BASE_URL)
        ? `${API_BASE_URL}/chat`
        : '/chat';

      const response = await fetch(apiUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          confirmed_order: this.currentOrder
        })
      });

      const data = await response.json();

      if (data.type === 'data' && data.geojson) {
        // Success - display data on map
        ChatManager.addMessage(data.summary || 'Data loaded successfully.', 'assistant');
        App.displayData(data);
        this.clearOrder();
      } else if (data.type === 'error') {
        ChatManager.addMessage(data.message || 'Failed to load data.', 'assistant');
      }
    } catch (error) {
      console.error('Order execution error:', error);
      ChatManager.addMessage('Sorry, something went wrong executing the order.', 'assistant');
    } finally {
      confirmBtn.disabled = false;
      confirmBtn.textContent = 'Display on Map';
    }
  },

  /**
   * Escape HTML to prevent XSS
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
};

// Make OrderManager available globally for onclick handlers
window.OrderManager = OrderManager;

// ============================================================================
// RESIZE MANAGER - Draggable resize handles for sidebar sections
// ============================================================================

const ResizeManager = {
  activeHandle: null,
  startY: 0,
  startHeights: {},

  /**
   * Initialize resize manager
   */
  init() {
    this.setupResizeHandle('resizeInput', 'chatMessages', 'chatInputArea', true);
    this.setupResizeHandle('resizeOrder', 'chatInputArea', 'orderPanel', false);
  },

  /**
   * Setup a resize handle
   * @param {string} handleId - ID of the resize handle element
   * @param {string} aboveId - ID of the element above the handle
   * @param {string} belowId - ID of the element below the handle
   * @param {boolean} aboveFlexible - If true, above element uses flex, else fixed height
   */
  setupResizeHandle(handleId, aboveId, belowId, aboveFlexible) {
    const handle = document.getElementById(handleId);
    const above = document.getElementById(aboveId);
    const below = document.getElementById(belowId);

    if (!handle || !above || !below) return;

    handle.addEventListener('mousedown', (e) => {
      e.preventDefault();
      this.activeHandle = { handle, above, below, aboveFlexible };
      this.startY = e.clientY;
      this.startHeights = {
        above: above.offsetHeight,
        below: below.offsetHeight
      };
      handle.classList.add('active');
      document.body.style.cursor = 'ns-resize';
      document.body.style.userSelect = 'none';
    });

    // Touch support
    handle.addEventListener('touchstart', (e) => {
      e.preventDefault();
      const touch = e.touches[0];
      this.activeHandle = { handle, above, below, aboveFlexible };
      this.startY = touch.clientY;
      this.startHeights = {
        above: above.offsetHeight,
        below: below.offsetHeight
      };
      handle.classList.add('active');
    }, { passive: false });

    // Global mouse/touch move and up handlers
    document.addEventListener('mousemove', (e) => this.handleMove(e.clientY));
    document.addEventListener('mouseup', () => this.handleEnd());
    document.addEventListener('touchmove', (e) => {
      if (this.activeHandle) {
        e.preventDefault();
        this.handleMove(e.touches[0].clientY);
      }
    }, { passive: false });
    document.addEventListener('touchend', () => this.handleEnd());
  },

  /**
   * Handle drag movement
   */
  handleMove(clientY) {
    if (!this.activeHandle) return;

    const { above, below, aboveFlexible } = this.activeHandle;
    const deltaY = clientY - this.startY;

    // Calculate new heights
    let newAboveHeight = this.startHeights.above + deltaY;
    let newBelowHeight = this.startHeights.below - deltaY;

    // Get min heights from CSS
    const aboveMinHeight = parseInt(getComputedStyle(above).minHeight) || 60;
    const belowMinHeight = parseInt(getComputedStyle(below).minHeight) || 60;

    // Enforce minimums
    if (newAboveHeight < aboveMinHeight) {
      newAboveHeight = aboveMinHeight;
      newBelowHeight = this.startHeights.above + this.startHeights.below - aboveMinHeight;
    }
    if (newBelowHeight < belowMinHeight) {
      newBelowHeight = belowMinHeight;
      newAboveHeight = this.startHeights.above + this.startHeights.below - belowMinHeight;
    }

    // Apply heights
    if (aboveFlexible) {
      // For chat messages, set flex-basis instead of height
      above.style.flex = `0 0 ${newAboveHeight}px`;
    } else {
      above.style.height = `${newAboveHeight}px`;
    }
    below.style.height = `${newBelowHeight}px`;
  },

  /**
   * Handle drag end
   */
  handleEnd() {
    if (!this.activeHandle) return;

    this.activeHandle.handle.classList.remove('active');
    this.activeHandle = null;
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  }
};

// ============================================================================
// SETTINGS MANAGER - Settings view and configuration
// ============================================================================

const SettingsManager = {
  elements: {},
  isVisible: false,

  /**
   * Initialize settings manager
   */
  init() {
    this.elements = {
      chatContainer: document.getElementById('chatContainer'),
      settingsView: document.getElementById('settingsView'),
      settingsLink: document.getElementById('settingsLink'),
      backToChat: document.getElementById('backToChat'),
      backupPathInput: document.getElementById('backupPathInput'),
      saveBtn: document.getElementById('saveSettingsBtn'),
      initFoldersBtn: document.getElementById('initFoldersBtn'),
      status: document.getElementById('settingsStatus'),
      currentConfig: document.getElementById('currentConfig'),
      sidebarFooter: document.getElementById('sidebarFooter')
    };

    this.setupEventListeners();
    this.loadSettings();
  },

  /**
   * Setup event listeners
   */
  setupEventListeners() {
    const { settingsLink, backToChat, saveBtn, initFoldersBtn } = this.elements;

    // Toggle to settings view
    settingsLink.addEventListener('click', (e) => {
      e.preventDefault();
      this.showSettings();
    });

    // Back to chat
    backToChat.addEventListener('click', (e) => {
      e.preventDefault();
      this.hideSettings();
    });

    // Save settings
    saveBtn.addEventListener('click', () => {
      this.saveSettings();
    });

    // Initialize folders
    initFoldersBtn.addEventListener('click', () => {
      this.initializeFolders();
    });
  },

  /**
   * Show settings view
   */
  showSettings() {
    const { chatContainer, settingsView, sidebarFooter } = this.elements;
    chatContainer.classList.add('hidden');
    settingsView.classList.add('active');
    sidebarFooter.style.display = 'none';
    this.isVisible = true;
    this.loadSettings();
  },

  /**
   * Hide settings view
   */
  hideSettings() {
    const { chatContainer, settingsView, sidebarFooter } = this.elements;
    chatContainer.classList.remove('hidden');
    settingsView.classList.remove('active');
    sidebarFooter.style.display = 'block';
    this.isVisible = false;
  },

  /**
   * Load current settings from server
   */
  async loadSettings() {
    try {
      const response = await fetch('/settings');
      if (response.ok) {
        const settings = await response.json();
        this.elements.backupPathInput.value = settings.backup_path || '';
        this.updateConfigDisplay(settings);
      }
    } catch (error) {
      console.log('Could not load settings:', error.message);
      this.updateConfigDisplay({ error: 'Could not connect to server' });
    }
  },

  /**
   * Save settings to server
   */
  async saveSettings() {
    const backupPath = this.elements.backupPathInput.value.trim();

    try {
      const response = await fetch('/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backup_path: backupPath })
      });

      const result = await response.json();

      if (response.ok) {
        this.showStatus('Settings saved successfully!', 'success');
        this.updateConfigDisplay(result.settings || { backup_path: backupPath });
      } else {
        this.showStatus(result.error || 'Failed to save settings', 'error');
      }
    } catch (error) {
      this.showStatus('Error: ' + error.message, 'error');
    }
  },

  /**
   * Initialize folder structure at backup path
   */
  async initializeFolders() {
    const backupPath = this.elements.backupPathInput.value.trim();

    if (!backupPath) {
      this.showStatus('Please enter a backup path first', 'error');
      return;
    }

    try {
      const response = await fetch('/settings/init-folders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backup_path: backupPath })
      });

      const result = await response.json();

      if (response.ok) {
        this.showStatus('Folders initialized: ' + result.folders.join(', '), 'success');
        this.loadSettings();
      } else {
        this.showStatus(result.error || 'Failed to initialize folders', 'error');
      }
    } catch (error) {
      this.showStatus('Error: ' + error.message, 'error');
    }
  },

  /**
   * Show status message
   */
  showStatus(message, type) {
    const status = this.elements.status;
    status.textContent = message;
    status.className = 'settings-status ' + type;

    // Auto-hide after 5 seconds
    setTimeout(() => {
      status.className = 'settings-status';
    }, 5000);
  },

  /**
   * Update the current configuration display
   */
  updateConfigDisplay(settings) {
    const { currentConfig } = this.elements;

    if (settings.error) {
      currentConfig.innerHTML = `<span style="color: #dc3545;">${settings.error}</span>`;
      return;
    }

    let html = '';

    if (settings.backup_path) {
      html += `<strong>Backup Path:</strong> ${settings.backup_path}<br>`;

      if (settings.folders_exist) {
        html += '<br><strong>Folder Status:</strong><br>';
        for (const [folder, exists] of Object.entries(settings.folders_exist)) {
          const icon = exists ? '[OK]' : '[Missing]';
          const color = exists ? '#28a745' : '#dc3545';
          html += `<span style="color: ${color};">${icon}</span> ${folder}<br>`;
        }
      }
    } else {
      html = '<em>No backup path configured</em>';
    }

    currentConfig.innerHTML = html;
  }
};

// ============================================================================
// APP - Main application controller
// ============================================================================

const App = {
  currentData: null,
  debugMode: false,  // Toggle with 'D' key - shows hierarchy depth colors

  /**
   * Initialize the application
   */
  async init() {
    console.log('Initializing Map Explorer...');

    // Initialize components
    ChatManager.init();
    OrderManager.init();
    SettingsManager.init();
    ResizeManager.init();

    // Initialize map
    await MapAdapter.init();

    // Setup keyboard handler for debug mode
    this.setupKeyboardHandler();

    // Load initial data
    await this.loadCountries();

    console.log('Map Explorer ready');
    console.log('Press D to toggle debug mode (hierarchy depth colors)');
  },

  /**
   * Setup keyboard handler for debug mode toggle
   */
  setupKeyboardHandler() {
    document.addEventListener('keydown', (e) => {
      // Ignore if typing in an input
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
        return;
      }

      if (e.key.toLowerCase() === 'd') {
        this.toggleDebugMode();
      }
    });
  },

  /**
   * Toggle debug mode (hierarchy depth visualization)
   */
  async toggleDebugMode() {
    this.debugMode = !this.debugMode;
    console.log(`Debug mode: ${this.debugMode ? 'ON' : 'OFF'}`);

    // Only reload if we're at world level showing countries
    if (NavigationManager.currentLevel === 'world') {
      await this.loadCountries();
    }

    // Update fill colors based on debug mode
    MapAdapter.updateDebugColors(this.debugMode);
  },

  /**
   * Load world countries
   */
  async loadCountries() {
    try {
      console.log('Loading countries...');
      // Add debug param if debug mode is on
      const url = this.debugMode
        ? `${CONFIG.api.countries}?debug=true`
        : CONFIG.api.countries;
      const response = await fetch(url);
      const result = await response.json();

      if (result.geojson && result.geojson.features.length > 0) {
        this.currentData = {
          geojson: result.geojson,
          dataset_name: 'World Countries',
          source_name: 'Natural Earth'
        };

        NavigationManager.reset();
        MapAdapter.clearParentOutline();  // Clear parent outline at world level
        MapAdapter.clearCityOverlay();    // Clear city overlay
        MapAdapter.loadGeoJSON(result.geojson, this.debugMode);
        MapAdapter.fitToBounds(result.geojson);

        console.log(`Loaded ${result.count} countries${this.debugMode ? ' (debug mode)' : ''}`);
      }
    } catch (error) {
      console.error('Error loading countries:', error);
    }
  },

  /**
   * Handle single click on a feature
   */
  handleFeatureClick(feature, lngLat) {
    const properties = feature.properties;
    const popupHtml = PopupBuilder.build(properties, this.currentData);
    MapAdapter.showPopup([lngLat.lng, lngLat.lat], popupHtml);

    // Get coordinates for fly-to
    let coords = null;
    if (properties.coordinates) {
      try {
        coords = JSON.parse(properties.coordinates);
      } catch (e) {}
    }

    if (coords && coords.length === 2) {
      const zoom = NavigationManager.getZoomForLevel() + 1;
      MapAdapter.flyTo(coords, zoom);
    }
  },

  /**
   * Handle double-click drill-down
   */
  async handleFeatureDrillDown(feature) {
    const locId = feature.properties.loc_id;
    const name = feature.properties.name || 'Unknown';

    if (locId) {
      MapAdapter.hidePopup();
      await this.drillDown(locId, name);
    }
  },

  /**
   * Drill down into a location
   * @param {string} locId - Location ID
   * @param {string} name - Display name
   * @param {boolean} skipPush - Skip adding to navigation path (used for back navigation)
   */
  async drillDown(locId, name, skipPush = false) {
    // Prevent duplicate navigation (unless this is a back-navigation call)
    if (!skipPush && NavigationManager.isNavigating) {
      console.log('Navigation already in progress, skipping drillDown');
      return;
    }
    if (!skipPush) {
      NavigationManager.isNavigating = true;
    }

    try {
      console.log(`Drilling down: ${locId}`);

      // Before loading children, find the parent feature to use as outline
      let parentGeojson = null;
      if (MapAdapter.currentRegionGeojson && MapAdapter.currentRegionGeojson.features) {
        const parentFeature = MapAdapter.currentRegionGeojson.features.find(
          f => f.properties && f.properties.loc_id === locId
        );
        if (parentFeature) {
          parentGeojson = {
            type: 'FeatureCollection',
            features: [parentFeature]
          };
        }
      }

      const url = CONFIG.api.children.replace('{loc_id}', locId);
      const response = await fetch(url);
      const result = await response.json();

      if (result.geojson && result.geojson.features.length > 0) {
        this.currentData = {
          geojson: result.geojson,
          dataset_name: `${name} - ${result.level}`,
          source_name: 'Geometry'
        };

        if (!skipPush) {
          NavigationManager.push(locId, name, result.level);
        }

        MapAdapter.loadGeoJSON(result.geojson);

        // Set the parent outline (the region we drilled into)
        if (parentGeojson) {
          MapAdapter.setParentOutline(parentGeojson);
        }

        // Zoom closer when drilling into countries (minZoom based on level)
        const zoomOptions = {};
        if (result.level === 'us_state' || result.level === 'state') {
          zoomOptions.minZoom = 4;  // Zoom to at least 4 for states
        } else if (result.level === 'us_county' || result.level === 'county') {
          zoomOptions.minZoom = 6;  // Zoom to at least 6 for counties
        } else if (result.level === 'city') {
          zoomOptions.minZoom = 8;  // Zoom to at least 8 for cities
        }
        MapAdapter.fitToBounds(result.geojson, zoomOptions);

        // Load city overlay based on navigation level
        // Cities are parented to counties, so load when viewing a county
        const locIdParts = locId.split('-');
        if (locIdParts.length === 3 && locIdParts[0] === 'USA') {
          // We're in a county (USA-XX-XXXXX) - load cities for this county
          MapAdapter.loadCityOverlay(locId);
        } else if (result.level === 'us_county' && locId.startsWith('USA-')) {
          // We drilled into a state and see counties - clear any previous city overlay
          MapAdapter.clearCityOverlay();
        } else {
          // Clear city overlay for other cases
          MapAdapter.clearCityOverlay();
        }

        console.log(`Loaded ${result.count} ${result.level} features`);
      } else {
        console.log(`No children found for ${locId}`);
        if (result.message) {
          console.log(result.message);
        }
      }
    } catch (error) {
      console.error('Error drilling down:', error);
    } finally {
      // Clear navigation lock
      if (!skipPush) {
        NavigationManager.isNavigating = false;
      }
    }
  },

  /**
   * Display data from chat query
   */
  displayData(data) {
    this.currentData = data;

    if (data.geojson && data.geojson.type === 'FeatureCollection') {
      MapAdapter.loadGeoJSON(data.geojson);
      MapAdapter.fitToBounds(data.geojson);
    }

    // Collapse sidebar on mobile
    if (window.innerWidth < 500) {
      ChatManager.elements.sidebar.classList.add('collapsed');
      ChatManager.elements.toggle.style.display = 'flex';
    }
  }
};

// ============================================================================
// INITIALIZATION
// ============================================================================

// Start the app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  App.init();
});
