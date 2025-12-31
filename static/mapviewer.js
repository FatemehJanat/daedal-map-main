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

  // Viewport area thresholds are now in ViewportLoader.areaThresholds
  // Area-based thresholds adapt better to different region sizes than fixed zoom levels

  // Viewport loading settings (tunable)
  viewport: {
    debounceMs: 2000,       // Delay before loading after zoom/pan (2 seconds)
    cacheExpiryMs: 60000,   // Remove features not seen for 60s
    maxFeatures: 50000,     // Hard cap on cached features
    spinnerDelayMs: 2000    // Delay before showing spinner
  },

  // Colors
  colors: {
    // Focal area (center of viewport) - green tones
    focalFill: '#228855',       // Green
    focalFillOpacity: 0.45,
    focalStroke: '#116633',     // Dark green stroke
    // Surrounding areas - blue tones
    fill: '#2266aa',            // Blue
    fillOpacity: 0.35,
    stroke: '#1a5599',          // Dark blue stroke
    strokeWidth: 1,
    // Hover (applies to both)
    fillHover: '#4488cc',       // Lighter blue on hover
    fillHoverOpacity: 0.6,
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
    viewport: '/geometry/viewport',
    chat: '/chat'
  }
};

// ============================================================================
// GEOMETRY CACHE - In-memory cache for viewport-loaded features
// ============================================================================

const GeometryCache = {
  features: new Map(),  // loc_id -> {feature, lastSeen, level}
  maxFeatures: CONFIG.viewport.maxFeatures,
  expiryMs: CONFIG.viewport.cacheExpiryMs,

  /**
   * Add features to cache
   */
  add(features) {
    const now = Date.now();
    for (const f of features) {
      const locId = f.properties?.loc_id;
      if (!locId) continue;

      this.features.set(locId, {
        feature: f,
        lastSeen: now,
        level: f.properties?.admin_level || 0
      });
    }
    this.cleanup();
  },

  /**
   * Remove expired and excess features
   */
  cleanup() {
    const now = Date.now();

    // Remove expired
    for (const [id, entry] of this.features) {
      if (now - entry.lastSeen > this.expiryMs) {
        this.features.delete(id);
      }
    }

    // Cap at max features (remove oldest)
    if (this.features.size > this.maxFeatures) {
      const sorted = [...this.features.entries()]
        .sort((a, b) => a[1].lastSeen - b[1].lastSeen);
      const toRemove = sorted.slice(0, this.features.size - this.maxFeatures);
      for (const [id] of toRemove) {
        this.features.delete(id);
      }
    }
  },

  /**
   * Get cached features for a given admin level
   */
  getForLevel(level) {
    const result = [];
    const now = Date.now();

    for (const [id, entry] of this.features) {
      if (entry.level === level) {
        result.push(entry.feature);
        entry.lastSeen = now;  // Touch on access
      }
    }
    return result;
  },

  /**
   * Clear all cached features
   */
  clear() {
    this.features.clear();
  }
};

// ============================================================================
// VIEWPORT LOADER - Debounced viewport-based geometry loading
// ============================================================================

const ViewportLoader = {
  loadTimeout: null,
  spinnerTimeout: null,
  currentAdminLevel: 0,
  isLoading: false,
  enabled: true,  // Always enabled - viewport is the only navigation mode

  // Viewport area thresholds (in square degrees) for admin level selection
  // These are tunable - smaller areas = deeper admin levels
  areaThresholds: {
    level0: 3000,   // > 3000 sq deg = countries (world/continent view)
    level1: 300,    // > 300 sq deg = states (large country view)
    level2: 30      // > 30 sq deg = counties (state view)
                    // < 30 sq deg = subdivisions (county view)
  },

  /**
   * Calculate viewport area in square degrees
   */
  getViewportArea(bounds) {
    const width = Math.abs(bounds.getEast() - bounds.getWest());
    const height = Math.abs(bounds.getNorth() - bounds.getSouth());
    return width * height;
  },

  /**
   * Get admin level based on viewport area (smarter than fixed zoom thresholds)
   * Larger viewport = shallower level, smaller viewport = deeper level
   */
  getAdminLevelForViewport(bounds) {
    const area = this.getViewportArea(bounds);

    if (area > this.areaThresholds.level0) return 0;  // Countries
    if (area > this.areaThresholds.level1) return 1;  // States
    if (area > this.areaThresholds.level2) return 2;  // Counties
    return 3;  // Subdivisions
  },

  /**
   * Get zoom level for a given admin level (for breadcrumb navigation)
   * These are approximate - actual level depends on viewport area
   */
  getZoomForAdminLevel(level) {
    switch(level) {
      case 0: return 2;    // Countries - zoom out to world
      case 1: return 5;    // States
      case 2: return 8;    // Counties
      default: return 11;  // Subdivisions
    }
  },

  /**
   * Load geometry for current viewport
   */
  async load(adminLevel) {
    if (this.loadTimeout) clearTimeout(this.loadTimeout);

    this.loadTimeout = setTimeout(async () => {
      await this.doLoad(adminLevel);
    }, CONFIG.viewport.debounceMs);
  },

  /**
   * Actually perform the load
   */
  async doLoad(adminLevel) {
    if (!MapAdapter.map) return;

    const bounds = MapAdapter.map.getBounds();
    // Round to 3 decimal places (~100m precision) - more than enough for viewport queries
    const bbox = [
      bounds.getWest().toFixed(3),
      bounds.getSouth().toFixed(3),
      bounds.getEast().toFixed(3),
      bounds.getNorth().toFixed(3)
    ].join(',');

    // Start spinner timer
    this.isLoading = true;
    this.spinnerTimeout = setTimeout(() => {
      if (this.isLoading) {
        document.getElementById('loadingIndicator')?.classList.add('visible');
      }
    }, CONFIG.viewport.spinnerDelayMs);

    try {
      // Add debug param if debug mode is on (for coverage info in popups)
      const debugParam = App.debugMode ? '&debug=true' : '';
      const response = await fetch(
        `${CONFIG.api.viewport}?level=${adminLevel}&bbox=${bbox}${debugParam}`
      );
      const data = await response.json();

      if (data.features && data.features.length > 0) {
        // Add to cache
        GeometryCache.add(data.features);

        // Update map with fade
        MapAdapter.loadGeoJSONWithFade({
          type: 'FeatureCollection',
          features: data.features
        });

        // Update stats
        document.getElementById('totalAreas').textContent = data.features.length;
      }
    } catch (err) {
      console.error('Viewport load failed:', err);
      // Keep displaying cached data - user sees no change
      const cached = GeometryCache.getForLevel(adminLevel);
      if (cached.length === 0) {
        console.warn('No cached data available');
      }
    } finally {
      this.isLoading = false;
      clearTimeout(this.spinnerTimeout);
      document.getElementById('loadingIndicator')?.classList.remove('visible');
    }
  },

  /**
   * Handle zoom/move change - check if admin level should change based on viewport area
   */
  onViewportChange() {
    if (!this.enabled || !MapAdapter.map) return;

    const bounds = MapAdapter.map.getBounds();
    const area = this.getViewportArea(bounds);
    const newLevel = this.getAdminLevelForViewport(bounds);

    if (newLevel !== this.currentAdminLevel) {
      console.log(`Viewport area ${area.toFixed(0)} sq deg -> Admin level ${newLevel}`);
      this.currentAdminLevel = newLevel;
      this.load(newLevel);

      // Update breadcrumb to show current level
      NavigationManager.updateLevelDisplay(newLevel);
    } else {
      // Same level but viewport moved - reload for new area
      this.load(newLevel);
    }
  },

  /**
   * Legacy method - redirects to onViewportChange
   * @deprecated Use onViewportChange instead
   */
  onZoomEnd() {
    this.onViewportChange();
  },

  /**
   * Legacy method - redirects to onViewportChange
   * @deprecated Use onViewportChange instead
   */
  onMoveEnd() {
    this.onViewportChange();
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
  popupLocked: false,  // When true, popup stays visible on mouseleave
  isShowingPopup: false,  // True while showing popup (prevents close event from unlocking)
  handlersSetup: false,  // Track if event handlers have been added
  lastZoom: null,
  citiesLoaded: false,
  currentStateLocId: null,
  currentRegionGeojson: null,  // Store current regions for parent outline
  focusedParentId: null,  // Parent ID of focal area (center of viewport)
  clickTimeout: null,  // Timer to distinguish single vs double click
  pendingClickFeature: null,  // Feature from pending single click

  /**
   * Initialize the map
   */
  init() {
    this.map = new maplibregl.Map({
      container: 'map',
      style: 'https://tiles.openfreemap.org/styles/liberty',
      center: CONFIG.defaultCenter,
      zoom: CONFIG.defaultZoom,
      doubleClickZoom: false  // Disable default double-click zoom
    });

    // Create popup instance
    this.popup = new maplibregl.Popup({
      closeButton: true,
      closeOnClick: false,
      maxWidth: '320px'
    });

    // Unlock popup when close button is clicked (but not when we're just re-showing)
    this.popup.on('close', () => {
      // Only unlock if this is a real close (user clicked X), not a re-show
      if (!this.isShowingPopup) {
        this.popupLocked = false;
      }
    });

    // Enable globe projection when style loads
    this.map.on('style.load', () => {
      this.enableGlobe();
    });

    // Setup zoom-based navigation
    this.map.on('zoomend', () => this.handleZoomChange());
    this.map.on('zoom', () => this.updateZoomDisplay(this.map.getZoom()));

    // Setup viewport-based loading events
    this.map.on('zoomend', () => ViewportLoader.onZoomEnd());
    this.map.on('moveend', () => ViewportLoader.onMoveEnd());

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
   * Handle zoom changes - just update display
   * Navigation is now handled by ViewportLoader.onViewportChange()
   */
  handleZoomChange() {
    const currentZoom = this.map.getZoom();
    this.updateZoomDisplay(currentZoom);
    this.lastZoom = currentZoom;
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

    // Update focused parent based on center of viewport
    this.updateFocusedParent(geojson);

    // Remove existing source and layers
    this.clearLayers();

    // Add source
    this.map.addSource(CONFIG.layers.source, {
      type: 'geojson',
      data: geojson,
      generateId: true
    });

    // Determine fill color based on debug mode or focal coloring
    const fillColor = debugMode
      ? this.getDebugFillColorExpression()
      : this.getFocalFillColorExpression();

    // Determine fill opacity (higher for focal area)
    const fillOpacity = debugMode
      ? [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          CONFIG.colors.fillHoverOpacity,
          CONFIG.colors.fillOpacity
        ]
      : [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          CONFIG.colors.fillHoverOpacity,
          ['==', ['get', 'parent_id'], this.focusedParentId || ''],
          CONFIG.colors.focalFillOpacity,
          CONFIG.colors.fillOpacity
        ];

    // Add fill layer
    this.map.addLayer({
      id: CONFIG.layers.fill,
      type: 'fill',
      source: CONFIG.layers.source,
      paint: {
        'fill-color': fillColor,
        'fill-opacity': fillOpacity
      }
    });

    // Determine stroke color based on focal coloring
    const strokeColor = debugMode
      ? CONFIG.colors.stroke
      : this.getFocalStrokeColorExpression();

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
          strokeColor
        ],
        'line-width': [
          'case',
          ['boolean', ['feature-state', 'hover'], false],
          CONFIG.colors.strokeHoverWidth,
          CONFIG.colors.strokeWidth
        ]
      }
    });

    // Setup event handlers (only once)
    if (!this.handlersSetup) {
      this.setupEventHandlers();
      this.handlersSetup = true;
    }

    // Update stats
    document.getElementById('totalAreas').textContent = geojson.features.length;
  },

  /**
   * Update just the source data without recreating layers.
   * Much faster than loadGeoJSON - use for time slider updates.
   * @param {Object} geojson - GeoJSON FeatureCollection
   */
  updateSourceData(geojson) {
    // Add unique IDs to features for hover state
    geojson.features.forEach((feature, index) => {
      feature.id = index;
    });

    // Get the existing source and update its data
    const source = this.map.getSource(CONFIG.layers.source);
    if (source) {
      source.setData(geojson);
    }
  },

  /**
   * Load GeoJSON with fade transition for smooth layer switching.
   * Used by ViewportLoader for zoom-based layer changes.
   * @param {Object} geojson - GeoJSON FeatureCollection
   */
  loadGeoJSONWithFade(geojson) {
    // Add unique IDs to features for hover state
    geojson.features.forEach((feature, index) => {
      feature.id = index;
    });

    // Update focused parent based on center of viewport
    this.updateFocusedParent(geojson);

    const fillLayer = this.map.getLayer(CONFIG.layers.fill);
    const source = this.map.getSource(CONFIG.layers.source);

    if (fillLayer && source) {
      // Fade out existing layer
      this.map.setPaintProperty(CONFIG.layers.fill, 'fill-opacity', 0);

      setTimeout(() => {
        // Update source data
        source.setData(geojson);

        // Update focal coloring based on new focused parent (skips if debug mode)
        this.updateFocalColors();

        // Fade in new data with appropriate opacity
        if (App.debugMode) {
          // Debug mode: simple opacity, colors handled by getDebugFillColorExpression
          this.map.setPaintProperty(CONFIG.layers.fill, 'fill-opacity', [
            'case',
            ['boolean', ['feature-state', 'hover'], false],
            CONFIG.colors.fillHoverOpacity,
            CONFIG.colors.fillOpacity
          ]);
        } else {
          // Normal mode: focal opacity based on parent_id
          this.map.setPaintProperty(CONFIG.layers.fill, 'fill-opacity', [
            'case',
            ['boolean', ['feature-state', 'hover'], false],
            CONFIG.colors.fillHoverOpacity,
            ['==', ['get', 'parent_id'], this.focusedParentId || ''],
            CONFIG.colors.focalFillOpacity,
            CONFIG.colors.fillOpacity
          ]);
        }
      }, 200);  // Wait for fade out
    } else {
      // No existing layer - just do a normal load
      this.loadGeoJSON(geojson);
    }

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
   * Update the focused parent ID based on the feature at center of viewport
   * @param {Object} geojson - GeoJSON FeatureCollection to search
   */
  updateFocusedParent(geojson) {
    if (!this.map || !geojson || !geojson.features) {
      this.focusedParentId = null;
      return;
    }

    const center = this.map.getCenter();
    const centerLng = center.lng;
    const centerLat = center.lat;

    // Find the feature closest to center (using centroid)
    let closestFeature = null;
    let closestDist = Infinity;

    for (const feature of geojson.features) {
      const props = feature.properties || {};
      const lon = props.centroid_lon;
      const lat = props.centroid_lat;

      if (lon == null || lat == null) continue;

      // Simple euclidean distance (good enough for finding closest)
      const dist = Math.pow(lon - centerLng, 2) + Math.pow(lat - centerLat, 2);
      if (dist < closestDist) {
        closestDist = dist;
        closestFeature = feature;
      }
    }

    // Set the focused parent ID
    if (closestFeature && closestFeature.properties) {
      this.focusedParentId = closestFeature.properties.parent_id || null;
    } else {
      this.focusedParentId = null;
    }
  },

  /**
   * Get MapLibre expression for focal fill color
   * Features matching focusedParentId get green, others get blue
   */
  getFocalFillColorExpression() {
    if (!this.focusedParentId) {
      // No focal parent - use default blue
      return [
        'case',
        ['boolean', ['feature-state', 'hover'], false],
        CONFIG.colors.fillHover,
        CONFIG.colors.fill
      ];
    }

    // Color based on parent_id match
    return [
      'case',
      ['boolean', ['feature-state', 'hover'], false],
      CONFIG.colors.fillHover,
      ['==', ['get', 'parent_id'], this.focusedParentId],
      CONFIG.colors.focalFill,
      CONFIG.colors.fill
    ];
  },

  /**
   * Get MapLibre expression for focal stroke color
   */
  getFocalStrokeColorExpression() {
    if (!this.focusedParentId) {
      return CONFIG.colors.stroke;
    }

    return [
      'case',
      ['==', ['get', 'parent_id'], this.focusedParentId],
      CONFIG.colors.focalStroke,
      CONFIG.colors.stroke
    ];
  },

  /**
   * Update focal coloring based on current focusedParentId
   */
  updateFocalColors() {
    if (!this.map.getLayer(CONFIG.layers.fill)) return;

    // Skip if in debug mode (debug mode has its own coloring via getDebugFillColorExpression)
    if (App.debugMode) return;

    const fillColor = this.getFocalFillColorExpression();
    const strokeColor = this.getFocalStrokeColorExpression();

    this.map.setPaintProperty(CONFIG.layers.fill, 'fill-color', fillColor);
    this.map.setPaintProperty(CONFIG.layers.stroke, 'line-color', [
      'case',
      ['boolean', ['feature-state', 'hover'], false],
      CONFIG.colors.strokeHover,
      strokeColor
    ]);
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

    // Click handler - locks popup and fetches enriched data
    this.map.on('click', fillLayer, async (e) => {
      if (e.features.length > 0) {
        const feature = e.features[0];
        this.popupLocked = true;
        // Show basic popup immediately
        App.handleFeatureHover(feature, e.lngLat);
        // Fetch enriched data and update popup
        const locId = feature.properties.loc_id;
        if (locId) {
          const locationInfo = await LocationInfoCache.fetch(locId);
          if (locationInfo && this.popupLocked) {
            // Update popup with enriched data
            const popupHtml = PopupBuilder.build(feature.properties, App.currentData, locationInfo);
            this.showPopup([e.lngLat.lng, e.lngLat.lat], popupHtml);
          }
        }
      }
    });

    // Click on map (not on feature) - unlock and hide popup
    this.map.on('click', (e) => {
      // Check if click was on a feature (fillLayer click fires first)
      const features = this.map.queryRenderedFeatures(e.point, { layers: [fillLayer] });
      if (features.length === 0 && this.popupLocked) {
        this.popupLocked = false;
        this.hidePopup();
      }
    });

    // Double-click handler for drill-down - DISABLED (using zoom controls instead)
    // this.map.on('dblclick', fillLayer, (e) => {
    //   e.preventDefault();
    //   if (e.features.length > 0) {
    //     const feature = e.features[0];
    //     this.popupLocked = false;
    //     App.handleFeatureDrillDown(feature);
    //   }
    // });

    // Hover handlers - show popup on hover (unless locked)
    this.map.on('mousemove', fillLayer, (e) => {
      if (e.features.length > 0) {
        const feature = e.features[0];

        // Reset previous hover state
        if (this.hoveredFeatureId !== null) {
          this.map.setFeatureState(
            { source: CONFIG.layers.source, id: this.hoveredFeatureId },
            { hover: false }
          );
        }

        // Set new hover state
        this.hoveredFeatureId = feature.id;
        this.map.setFeatureState(
          { source: CONFIG.layers.source, id: this.hoveredFeatureId },
          { hover: true }
        );

        this.map.getCanvas().style.cursor = 'pointer';

        // Show popup on hover (only if not locked to another location)
        if (!this.popupLocked) {
          App.handleFeatureHover(feature, e.lngLat);
        }
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
      // Only hide popup if not locked
      if (!this.popupLocked) {
        this.hidePopup();
      }
    });
  },

  /**
   * Show popup at location
   * @param {Array} lngLat - [longitude, latitude]
   * @param {string} html - Popup HTML content
   */
  showPopup(lngLat, html) {
    // Set flag to prevent close event from unlocking
    this.isShowingPopup = true;
    this.popup
      .setLngLat(lngLat)
      .setHTML(html)
      .addTo(this.map);
    // Clear flag after a short delay (after close event would have fired)
    setTimeout(() => {
      this.isShowingPopup = false;
    }, 50);
  },

  /**
   * Hide popup and unlock
   */
  hidePopup() {
    // Set flag so close event doesn't also try to unlock
    this.isShowingPopup = true;
    this.popup.remove();
    this.popupLocked = false;
    setTimeout(() => {
      this.isShowingPopup = false;
    }, 50);
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
        // Clicking breadcrumb zooms to that level, keeping viewport centered
        return `<span onclick="NavigationManager.zoomToLevel(${index})">${item.name}</span>`;
      }
    });

    container.innerHTML = crumbs.join(' &gt; ');
  },

  /**
   * Update breadcrumb to show current admin level (for viewport-based navigation)
   * @param {number} adminLevel - Current admin level
   */
  updateLevelDisplay(adminLevel) {
    const levelNames = ['World', 'States', 'Counties', 'Subdivisions'];
    const levelName = levelNames[adminLevel] || `Level ${adminLevel}`;

    // Update the path to reflect current level
    if (ViewportLoader.enabled) {
      this.path = [{ loc_id: 'world', name: 'World', level: 'world' }];
      if (adminLevel >= 1) {
        this.path.push({ loc_id: `level_${adminLevel}`, name: levelName, level: `level_${adminLevel}` });
      }
      this.updateBreadcrumb();
    }
  },

  /**
   * Zoom to a specific breadcrumb level (keeps viewport centered)
   * @param {number} index - Index in the path
   */
  zoomToLevel(index) {
    if (index < 0 || index >= this.path.length) return;

    const target = this.path[index];

    // If using viewport-based navigation, just zoom to the target level
    if (ViewportLoader.enabled) {
      const adminLevel = index;  // World=0, States=1, etc.
      const targetZoom = ViewportLoader.getZoomForAdminLevel(adminLevel);
      const center = MapAdapter.map.getCenter();

      MapAdapter.map.flyTo({ center, zoom: targetZoom });
      return;
    }

    // Fall back to legacy drill-down navigation
    this.navigateTo(index);
  },

  /**
   * Get zoom level based on current navigation depth
   * @returns {number} Recommended zoom level
   */
  getZoomForLevel() {
    switch (this.currentLevel) {
      case 'world': return 2;
      case 'country': return 4;
      case 'us_state': return 6;
      case 'state': return 6;
      case 'us_county': return 8;
      case 'county': return 8;
      case 'city': return 10;
      default: return 4;
    }
  }
};

// Make navigateTo available globally for onclick handlers
window.NavigationManager = NavigationManager;

// ============================================================================
// LOCATION INFO CACHE - Cache enriched location data from API
// ============================================================================

const LocationInfoCache = {
  cache: new Map(),
  maxSize: 500,
  expiryMs: 300000,  // 5 minutes

  /**
   * Get cached location info or null if not cached/expired
   */
  get(locId) {
    const entry = this.cache.get(locId);
    if (!entry) return null;
    if (Date.now() - entry.timestamp > this.expiryMs) {
      this.cache.delete(locId);
      return null;
    }
    return entry.data;
  },

  /**
   * Store location info in cache
   */
  set(locId, data) {
    this.cache.set(locId, {
      data: data,
      timestamp: Date.now()
    });
    // Cleanup if over max size
    if (this.cache.size > this.maxSize) {
      const oldest = this.cache.keys().next().value;
      this.cache.delete(oldest);
    }
  },

  /**
   * Fetch location info from API
   */
  async fetch(locId) {
    // Check cache first
    const cached = this.get(locId);
    if (cached) return cached;

    try {
      const response = await fetch(`/geometry/${locId}/info`);
      if (!response.ok) return null;
      const data = await response.json();
      this.set(locId, data);
      return data;
    } catch (error) {
      console.error('Error fetching location info:', error);
      return null;
    }
  }
};

// ============================================================================
// POPUP BUILDER - Generate popup HTML content
// ============================================================================

const PopupBuilder = {
  // Fields to skip in popup display (technical/internal fields)
  skipFields: [
    // Identity fields
    'geometry', 'coordinates', 'loc_id', 'parent_id', 'level', 'code', 'abbrev',
    'name', 'Name', 'Location', 'name_long', 'name_sort', 'formal_en', 'name_local',
    // Country/region name variants
    'country', 'country_name', 'country_code', 'iso_code', 'iso_a3', 'iso_3166_2',
    'Admin Country Name', 'Sov Country Name', 'Admin Country Abbr', 'Sov Country Abbr',
    'stusab', 'state', 'postal', 'continent',
    // Admin/type fields
    'Admin Type', 'type', 'admin_level',
    // Geometry metadata
    'centroid_lon', 'centroid_lat', 'Longitude', 'Latitude',
    'bbox_min_lon', 'bbox_min_lat', 'bbox_max_lon', 'bbox_max_lat',
    'has_polygon', 'timezone',
    // Children counts (shown via enriched info)
    'children_count', 'children_by_level', 'descendants_count', 'descendants_by_level',
    // Categorization
    'population_year', 'gdp_year', 'economy type', 'income_group',
    'UN Region', 'subregion', 'region_wb',
    // Year shown separately
    'data_year'
  ],

  /**
   * Build popup HTML from feature properties
   * @param {Object} properties - Feature properties
   * @param {Object} sourceData - Optional source metadata (from chat query)
   * @param {Object} locationInfo - Optional enriched location info from API
   * @returns {string} HTML content
   */
  build(properties, sourceData = null, locationInfo = null) {
    const lines = [];

    // Title
    const name = properties.name || properties.country_name ||
                 properties.country || properties.Name || 'Unknown';
    const stateAbbr = properties.stusab || properties.abbrev || '';
    lines.push(`<strong>${name}${stateAbbr ? ', ' + stateAbbr : ''}</strong>`);

    // Debug mode: show coverage info
    if (App.debugMode && properties.coverage !== undefined) {
      lines.push(this.buildHierarchyInfo(properties));
    } else if (locationInfo && !locationInfo.error) {
      // Enriched mode: show only location info from API (clean popup)
      lines.push(this.buildLocationInfo(locationInfo));
    } else {
      // Fallback: show data fields from chat query results
      const fieldsToShow = Object.keys(properties).filter(k =>
        !this.skipFields.includes(k) &&
        k.toLowerCase() !== 'year' &&
        properties[k] != null &&
        properties[k] !== ''
      );

      for (const key of fieldsToShow.slice(0, 10)) {
        const value = properties[key];
        if (value == null || value === '') continue;

        const fieldName = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        const formattedValue = this.formatValue(key, value);
        const year = properties.year || properties.data_year || '';
        const yearSuffix = year ? ` (${year})` : '';

        lines.push(`${fieldName}: ${formattedValue}${yearSuffix}`);
      }

      // Source info (from chat query)
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

    // Hint for zoom navigation
    lines.push('<br><em style="font-size: 11px; color: #666;">Zoom in to see sub-layers</em>');

    return lines.join('<br>');
  },

  /**
   * Build location info section from enriched API data
   * @param {Object} info - Location info from /geometry/{loc_id}/info
   * @returns {string} HTML content
   */
  buildLocationInfo(info) {
    const parts = [];

    // Memberships first (G20, BRICS, EU for countries; "Part of: X" for sub-nationals)
    if (info.memberships && info.memberships.length > 0) {
      const first = info.memberships[0];
      // If it already says "Part of:", display as-is; otherwise prefix with "Member of:"
      if (first.startsWith('Part of:')) {
        parts.push(`<span style="color: #666; font-size: 12px;">${first}</span>`);
      } else {
        const memberships = info.memberships.slice(0, 5).join(', ');
        parts.push(`<span style="color: #666; font-size: 12px;">Member of: ${memberships}</span>`);
      }
    }

    // Country-level datasets (shown at country level)
    const datasetCounts = info.dataset_counts || {};
    const countryDatasets = datasetCounts.country || 0;
    if (info.admin_level === 0 && countryDatasets > 0) {
      parts.push(`<span style="color: #666; font-size: 12px;">${countryDatasets} country-level datasets</span>`);
    }

    // Subdivisions - each level on its own line with dataset counts
    if (info.children_count > 0 || info.descendants_count > 0) {
      const subdivisionLines = this.formatSubdivisions(info);
      for (const line of subdivisionLines) {
        parts.push(`<span style="color: #666; font-size: 12px;">${line}</span>`);
      }
    }

    return parts.join('<br>');
  },

  /**
   * Format subdivision counts into array of lines with dataset counts
   * @param {Object} info - Location info with children/descendants counts, level_names, dataset_counts
   * @returns {string[]} Array of formatted lines like ["52 states (20 datasets)", "3,144 counties (3 datasets)"]
   */
  formatSubdivisions(info) {
    // Parse children_by_level and descendants_by_level
    let childrenByLevel = {};
    let descendantsByLevel = {};

    try {
      if (typeof info.children_by_level === 'string') {
        childrenByLevel = JSON.parse(info.children_by_level);
      } else if (info.children_by_level) {
        childrenByLevel = info.children_by_level;
      }
    } catch (e) {}

    try {
      if (typeof info.descendants_by_level === 'string') {
        descendantsByLevel = JSON.parse(info.descendants_by_level);
      } else if (info.descendants_by_level) {
        descendantsByLevel = info.descendants_by_level;
      }
    } catch (e) {}

    // Use country-specific level names from API, or fall back to defaults
    const countryLevelNames = info.level_names || {};
    const defaultNames = { 1: 'states/provinces', 2: 'districts', 3: 'subdivisions', 4: 'localities' };

    // Dataset counts by geographic level (e.g., {"country": 20, "county": 3})
    const datasetCounts = info.dataset_counts || {};

    // Map admin levels to catalog geographic levels
    const levelToGeoLevel = { 0: 'country', 1: 'state', 2: 'county', 3: 'place' };

    const lines = [];

    // Format each level on its own line
    const allLevels = { ...childrenByLevel, ...descendantsByLevel };
    const sortedLevels = Object.keys(allLevels).map(Number).sort((a, b) => a - b);

    for (const level of sortedLevels) {
      const count = descendantsByLevel[level] || childrenByLevel[level] || 0;
      if (count > 0) {
        const levelName = countryLevelNames[level] || defaultNames[level] || `level ${level}`;

        // Get dataset count for this level
        const geoLevel = levelToGeoLevel[level];
        const dsCount = datasetCounts[geoLevel] || 0;

        if (dsCount > 0) {
          lines.push(`${count.toLocaleString()} ${levelName} (${dsCount} datasets)`);
        } else {
          lines.push(`${count.toLocaleString()} ${levelName}`);
        }
      }
    }

    // Limit to first 3 levels
    return lines.slice(0, 3);
  },

  /**
   * Build coverage info for debug mode popup
   * @param {Object} properties - Feature properties with coverage data
   * @returns {string} HTML content for coverage info
   */
  buildHierarchyInfo(properties) {
    const currentLevel = properties.current_admin_level || 0;
    const actualDepth = properties.actual_depth || 0;
    const coverage = properties.coverage || 0;
    const drillableDepth = properties.drillable_depth || 0;
    let levelCounts = properties.level_counts || {};
    let geometryCounts = properties.geometry_counts || {};

    // Parse if it's a JSON string (GeoJSON stringifies nested objects)
    if (typeof levelCounts === 'string') {
      try {
        levelCounts = JSON.parse(levelCounts);
      } catch (e) {
        levelCounts = {};
      }
    }
    if (typeof geometryCounts === 'string') {
      try {
        geometryCounts = JSON.parse(geometryCounts);
      } catch (e) {
        geometryCounts = {};
      }
    }

    const lines = [];
    const levelNames = ['country', 'state', 'county', 'place', 'locality', 'neighborhood'];
    const currentLevelName = levelNames[currentLevel] || `level ${currentLevel}`;

    // Show current admin level
    lines.push(`<br><strong>Admin Level: ${currentLevel} (${currentLevelName})</strong>`);

    // Show coverage percentage
    const coveragePct = Math.round(coverage * 100);
    const coverageColor = coverage >= 1 ? '#44aa44' : coverage >= 0.5 ? '#ff9900' : '#ff4444';
    lines.push(`<strong style="color: ${coverageColor};">Geometry: ${coveragePct}%</strong>`);

    // Show depth info
    lines.push(`Depth: ${actualDepth} levels (drill to level ${drillableDepth})`);

    // Show level counts with geometry availability
    // Iterate over actual keys in levelCounts (may start at admin_level > 0)
    const levels = Object.keys(levelCounts).map(Number).sort((a, b) => a - b);

    for (const level of levels) {
      const count = levelCounts[String(level)] || 0;
      const geomCount = geometryCounts[String(level)] || 0;
      if (count > 0 && level < levelNames.length) {
        const hasGeom = geomCount > 0;
        const color = hasGeom ? '#44aa44' : '#ff9900';
        const geomNote = hasGeom ? '' : ' (no geometry)';
        lines.push(`<span style="color: ${color};">${levelNames[level]}: ${count.toLocaleString()}${geomNote}</span>`);
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
                      'methane', 'temperature', 'energy', 'oil', 'gas', 'coal',
                      'balance', 'account', 'trade', 'export', 'import', 'income',
                      'life', 'mortality', 'birth', 'health', 'age', 'median'];

    for (const [key, value] of Object.entries(properties)) {
      if (this.skipFields.includes(key) || value == null || value === '') continue;
      if (key.toLowerCase() === 'year') continue;

      const keyLower = key.toLowerCase();
      const isNumeric = !isNaN(parseFloat(value));
      const isRelevant = keywords.some(kw => keyLower.includes(kw));
      // Also include fields with our metric_label format (contain parentheses)
      const isLabeledMetric = key.includes('(') && key.includes(')');

      if (isNumeric && (isRelevant || isLabeledMetric)) {
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
          this.addMessage('Added to your order. Click "Display on Map" when ready.', 'assistant');
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
   * Add items from LLM response to the current order (accumulates until Clear)
   * @param {Object} order - The order object from backend
   * @param {string} summary - Summary text from LLM
   */
  setOrder(order, summary) {
    if (!order || !order.items || order.items.length === 0) {
      // Nothing to add
      return;
    }

    if (!this.currentOrder || !this.currentOrder.items) {
      // No existing order - use the new one
      this.currentOrder = order;
    } else {
      // Append new items, but deduplicate by source_id + metric + region
      const existingKeys = new Set(
        this.currentOrder.items.map(item =>
          `${item.source_id || item.source}|${item.metric}|${item.region}`
        )
      );

      const newItems = order.items.filter(item => {
        const key = `${item.source_id || item.source}|${item.metric}|${item.region}`;
        return !existingKeys.has(key);
      });

      if (newItems.length > 0) {
        this.currentOrder.items = this.currentOrder.items.concat(newItems);
        this.currentOrder.summary = summary || this.currentOrder.summary;
      }
    }

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

    // Check if any items are invalid
    const hasInvalid = orderItems.some(item => item._valid === false);
    confirmBtn.disabled = hasInvalid;
    if (hasInvalid) {
      confirmBtn.title = 'Fix invalid items before displaying';
    } else {
      confirmBtn.title = '';
    }

    items.innerHTML = orderItems.map((item, index) => {
      // Show human-readable label only (column name hidden from user)
      const label = item.metric_label || item.metric || 'unknown';
      const region = item.region || 'global';
      // Handle year range (year_start/year_end) vs single year
      let year;
      if (item.year_start && item.year_end) {
        year = `${item.year_start}-${item.year_end}`;
      } else {
        year = item.year || 'latest';
      }
      const isValid = item._valid !== false;
      const error = item._error || '';

      // Format: Label | region | year (source shown in popup, not here)
      const name = label;
      const details = [region, year].filter(Boolean).join(' | ');

      const itemClass = isValid ? 'order-item' : 'order-item order-item-invalid';
      const errorHtml = error ? `<div class="order-item-error">${this.escapeHtml(error)}</div>` : '';

      return `
        <div class="${itemClass}">
          <div class="order-item-info">
            <div class="order-item-name">${this.escapeHtml(name)}</div>
            <div class="order-item-details">${this.escapeHtml(details)}</div>
            ${errorHtml}
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

      console.log('Sending order:', JSON.stringify(this.currentOrder, null, 2));

      const response = await fetch(apiUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          confirmed_order: this.currentOrder
        })
      });

      const data = await response.json();

      console.log('Received response:', {
        type: data.type,
        multi_year: data.multi_year,
        has_year_data: !!data.year_data,
        year_range: data.year_range,
        feature_count: data.geojson?.features?.length
      });

      if (data.type === 'data' && data.geojson) {
        // Success - display data on map
        ChatManager.addMessage(data.summary || 'Data loaded successfully.', 'assistant');
        App.displayData(data);
        // Keep order visible - only Clear button should empty it
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
// TIME SLIDER - Controls year selection for multi-year data
// ============================================================================

const TimeSlider = {
  container: null,
  slider: null,
  yearLabel: null,
  playBtn: null,
  minLabel: null,
  maxLabel: null,
  titleLabel: null,

  // Data state
  yearData: null,      // {year: {loc_id: {metric: value}}}
  baseGeojson: null,   // Geometry without year-specific values
  metricKey: null,     // Which property to color by
  currentYear: null,
  minYear: null,
  maxYear: null,
  availableYears: [],
  isPlaying: false,
  playInterval: null,
  listenersSetup: false,  // Track if event listeners have been added

  /**
   * Initialize time slider with multi-year data
   */
  init(yearRange, yearData, baseGeojson, metricKey) {
    this.yearData = yearData;
    this.baseGeojson = baseGeojson;
    this.metricKey = metricKey;
    this.minYear = yearRange.min;
    this.maxYear = yearRange.max;
    this.availableYears = yearRange.available_years || [];
    this.currentYear = yearRange.max;  // Start at latest year

    // Cache DOM elements
    this.container = document.getElementById('timeSliderContainer');
    this.slider = document.getElementById('timeSlider');
    this.yearLabel = document.getElementById('currentYearLabel');
    this.playBtn = document.getElementById('playBtn');
    this.minLabel = document.getElementById('minYearLabel');
    this.maxLabel = document.getElementById('maxYearLabel');
    this.titleLabel = document.getElementById('sliderTitle');

    // Configure slider
    this.slider.min = this.minYear;
    this.slider.max = this.maxYear;
    this.slider.value = this.currentYear;
    this.minLabel.textContent = this.minYear;
    this.maxLabel.textContent = this.maxYear;
    this.titleLabel.textContent = metricKey || 'Year';

    // Setup event listeners (only once)
    if (!this.listenersSetup) {
      this.setupEventListeners();
      this.listenersSetup = true;
    }

    // Reset play button state
    this.playBtn.textContent = '|>';
    this.playBtn.title = 'Play';

    // Show slider
    this.show();

    // Initialize choropleth with full data range (before first render)
    ChoroplethManager.init(metricKey, yearData, this.availableYears);

    // Load geometry ONCE with initial year data (full loadGeoJSON)
    const initialGeojson = this.buildYearGeojson(this.currentYear);
    MapAdapter.loadGeoJSON(initialGeojson);
    ChoroplethManager.update(initialGeojson, this.metricKey);

    // Update labels
    this.yearLabel.textContent = this.currentYear;
  },

  /**
   * Setup event listeners (called once)
   */
  setupEventListeners() {
    // Slider input (fires while dragging)
    this.slider.addEventListener('input', (e) => {
      const year = parseInt(e.target.value);
      this.setYear(year);
    });

    // Play button
    this.playBtn.addEventListener('click', () => {
      if (this.isPlaying) {
        this.pause();
      } else {
        this.play();
      }
    });
  },

  /**
   * Set current year and update display
   */
  setYear(year) {
    this.currentYear = year;
    this.yearLabel.textContent = year;
    this.slider.value = year;

    // Build GeoJSON for this year and update source data (fast, no layer recreation)
    // The interpolate expression automatically re-evaluates when source data changes
    const geojson = this.buildYearGeojson(year);
    MapAdapter.updateSourceData(geojson);
  },

  /**
   * Build GeoJSON with year-specific values injected
   */
  buildYearGeojson(year) {
    const yearValues = this.yearData[year] || {};

    return {
      type: 'FeatureCollection',
      features: this.baseGeojson.features.map(f => {
        const locId = f.properties.loc_id;
        const locData = yearValues[locId] || {};

        return {
          ...f,
          properties: {
            ...f.properties,
            ...locData,
            year: year
          }
        };
      })
    };
  },

  /**
   * Start playback animation
   */
  play() {
    this.isPlaying = true;
    this.playBtn.textContent = '||';
    this.playBtn.title = 'Pause';

    this.playInterval = setInterval(() => {
      let nextYear = this.currentYear + 1;
      if (nextYear > this.maxYear) {
        nextYear = this.minYear;  // Loop back to start
      }
      this.setYear(nextYear);
    }, 600);  // 600ms per year
  },

  /**
   * Pause playback
   */
  pause() {
    this.isPlaying = false;
    if (this.playBtn) {
      this.playBtn.textContent = '|>';
      this.playBtn.title = 'Play';
    }

    if (this.playInterval) {
      clearInterval(this.playInterval);
      this.playInterval = null;
    }
  },

  /**
   * Show the time slider
   */
  show() {
    if (this.container) {
      this.container.classList.add('visible');
    }
  },

  /**
   * Hide the time slider
   */
  hide() {
    this.pause();  // Stop playing when hiding
    if (this.container) {
      this.container.classList.remove('visible');
    }
  },

  /**
   * Reset/clear time slider
   */
  reset() {
    this.hide();
    this.yearData = null;
    this.baseGeojson = null;
    this.metricKey = null;
  }
};

// ============================================================================
// CHOROPLETH MANAGER - Color scaling and legend for data visualization
// ============================================================================

const ChoroplethManager = {
  metric: null,
  minValue: null,
  maxValue: null,
  colorScale: null,

  // DOM elements
  legend: null,
  legendTitle: null,
  legendGradient: null,
  legendMin: null,
  legendMax: null,

  /**
   * Initialize choropleth with data range
   */
  init(metric, yearData, availableYears) {
    this.metric = metric;

    // Cache DOM elements
    this.legend = document.getElementById('choroplethLegend');
    this.legendTitle = document.getElementById('legendTitle');
    this.legendGradient = document.getElementById('legendGradient');
    this.legendMin = document.getElementById('legendMin');
    this.legendMax = document.getElementById('legendMax');

    // Calculate global min/max across ALL years for consistent scaling
    let allValues = [];
    for (const year of availableYears) {
      const yearValues = yearData[year] || {};
      for (const locId in yearValues) {
        const val = yearValues[locId][metric];
        if (val != null && !isNaN(val)) {
          allValues.push(val);
        }
      }
    }

    if (allValues.length > 0) {
      this.minValue = Math.min(...allValues);
      this.maxValue = Math.max(...allValues);
    } else {
      this.minValue = 0;
      this.maxValue = 100;
    }

    // Create color scale function (for legend only)
    this.colorScale = this.createScale(this.minValue, this.maxValue);

    // Update legend
    this.createLegend(metric);

    // Show legend
    this.legend.classList.add('visible');
  },

  /**
   * Create color scale function (value -> color)
   * Uses viridis-inspired palette (colorblind friendly)
   */
  createScale(min, max) {
    return (value) => {
      if (value == null || isNaN(value)) return '#cccccc';  // Gray for no data

      // Normalize to 0-1
      let t = (value - min) / (max - min);
      t = Math.max(0, Math.min(1, t));  // Clamp to 0-1

      // Viridis-inspired color stops (purple -> blue -> teal -> green -> yellow)
      // Simplified to 5 stops for smooth interpolation
      const colors = [
        { t: 0.0, r: 68, g: 1, b: 84 },     // Dark purple
        { t: 0.25, r: 59, g: 82, b: 139 },  // Blue
        { t: 0.5, r: 33, g: 145, b: 140 },  // Teal
        { t: 0.75, r: 94, g: 201, b: 98 },  // Green
        { t: 1.0, r: 253, g: 231, b: 37 }   // Yellow
      ];

      // Find the two colors to interpolate between
      let c1 = colors[0], c2 = colors[1];
      for (let i = 0; i < colors.length - 1; i++) {
        if (t >= colors[i].t && t <= colors[i + 1].t) {
          c1 = colors[i];
          c2 = colors[i + 1];
          break;
        }
      }

      // Interpolate between c1 and c2
      const localT = (t - c1.t) / (c2.t - c1.t);
      const r = Math.round(c1.r + (c2.r - c1.r) * localT);
      const g = Math.round(c1.g + (c2.g - c1.g) * localT);
      const b = Math.round(c1.b + (c2.b - c1.b) * localT);

      return `rgb(${r}, ${g}, ${b})`;
    };
  },

  /**
   * Create legend display
   */
  createLegend(metric) {
    // Truncate long metric names
    const displayName = metric.length > 25 ? metric.substring(0, 22) + '...' : metric;
    this.legendTitle.textContent = displayName;

    // Create gradient background
    this.legendGradient.style.background =
      'linear-gradient(to right, rgb(68,1,84), rgb(59,82,139), rgb(33,145,140), rgb(94,201,98), rgb(253,231,37))';

    // Format min/max values
    this.legendMin.textContent = this.formatValue(this.minValue);
    this.legendMax.textContent = this.formatValue(this.maxValue);
  },

  /**
   * Format value for display
   */
  formatValue(value) {
    if (value == null) return 'N/A';
    if (Math.abs(value) >= 1e9) return (value / 1e9).toFixed(1) + 'B';
    if (Math.abs(value) >= 1e6) return (value / 1e6).toFixed(1) + 'M';
    if (Math.abs(value) >= 1e3) return (value / 1e3).toFixed(1) + 'K';
    if (Number.isInteger(value)) return value.toString();
    return value.toFixed(2);
  },

  /**
   * Update map colors for current data
   * Uses efficient interpolate expression that reads directly from feature properties
   */
  update(geojson, metric) {
    if (!MapAdapter.map.getLayer(CONFIG.layers.fill)) return;

    // Build interpolate expression that reads metric value from properties
    // This is much faster than case expressions with 200+ conditions
    const colorExpression = this.buildInterpolateExpression(metric);
    MapAdapter.map.setPaintProperty(CONFIG.layers.fill, 'fill-color', colorExpression);
  },

  /**
   * Build MapLibre interpolate expression for data-driven colors
   * Uses viridis color stops and reads value directly from feature properties
   */
  buildInterpolateExpression(metric) {
    const min = this.minValue;
    const max = this.maxValue;

    // Handle edge case where min === max
    if (min === max) {
      return [
        'case',
        ['boolean', ['feature-state', 'hover'], false],
        '#ffffff',
        ['has', metric],
        'rgb(33, 145, 140)',  // Teal for all values
        '#cccccc'  // Gray for no data
      ];
    }

    // Viridis color stops at normalized positions (0 to 1)
    // We interpolate in the actual value domain [min, max]
    const stops = [
      [min, 'rgb(68, 1, 84)'],                                    // 0.0 - Dark purple
      [min + (max - min) * 0.25, 'rgb(59, 82, 139)'],            // 0.25 - Blue
      [min + (max - min) * 0.5, 'rgb(33, 145, 140)'],            // 0.5 - Teal
      [min + (max - min) * 0.75, 'rgb(94, 201, 98)'],            // 0.75 - Green
      [max, 'rgb(253, 231, 37)']                                  // 1.0 - Yellow
    ];

    // Build interpolate expression
    const interpolateExpr = ['interpolate', ['linear'], ['get', metric]];
    for (const [value, color] of stops) {
      interpolateExpr.push(value, color);
    }

    // Wrap in case expression to handle hover and missing data
    return [
      'case',
      ['boolean', ['feature-state', 'hover'], false],
      '#ffffff',  // White on hover
      ['has', metric],
      interpolateExpr,
      '#cccccc'  // Gray for no data
    ];
  },

  /**
   * Hide the legend
   */
  hide() {
    if (this.legend) {
      this.legend.classList.remove('visible');
    }
  },

  /**
   * Reset choropleth manager
   */
  reset() {
    this.hide();
    this.metric = null;
    this.minValue = null;
    this.maxValue = null;
  }
};

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
// SIDEBAR RESIZER - Handles sidebar width resizing
// ============================================================================

const SidebarResizer = {
  isResizing: false,
  startX: 0,
  startWidth: 0,
  minWidth: 300,
  maxWidth: 800,

  /**
   * Initialize sidebar resizer
   */
  init() {
    const handle = document.getElementById('sidebarResizeHandle');
    const sidebar = document.getElementById('sidebar');

    if (!handle || !sidebar) return;

    // Mouse events
    handle.addEventListener('mousedown', (e) => {
      e.preventDefault();
      this.startResize(e.clientX, sidebar, handle);
    });

    // Touch events
    handle.addEventListener('touchstart', (e) => {
      e.preventDefault();
      const touch = e.touches[0];
      this.startResize(touch.clientX, sidebar, handle);
    }, { passive: false });

    // Global move and end handlers
    document.addEventListener('mousemove', (e) => this.handleMove(e.clientX));
    document.addEventListener('mouseup', () => this.handleEnd());
    document.addEventListener('touchmove', (e) => {
      if (this.isResizing) {
        e.preventDefault();
        this.handleMove(e.touches[0].clientX);
      }
    }, { passive: false });
    document.addEventListener('touchend', () => this.handleEnd());

    // Store sidebar reference
    this.sidebar = sidebar;
    this.handle = handle;
  },

  /**
   * Start resizing
   */
  startResize(clientX, sidebar, handle) {
    this.isResizing = true;
    this.startX = clientX;
    this.startWidth = sidebar.offsetWidth;
    handle.classList.add('active');
    document.body.style.cursor = 'ew-resize';
    document.body.style.userSelect = 'none';
  },

  /**
   * Handle drag movement
   */
  handleMove(clientX) {
    if (!this.isResizing) return;

    const deltaX = clientX - this.startX;
    let newWidth = this.startWidth + deltaX;

    // Enforce min/max
    newWidth = Math.max(this.minWidth, Math.min(this.maxWidth, newWidth));

    // Apply new width
    this.sidebar.style.width = newWidth + 'px';
  },

  /**
   * Handle drag end
   */
  handleEnd() {
    if (!this.isResizing) return;

    this.isResizing = false;
    this.handle.classList.remove('active');
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
    SidebarResizer.init();

    // Initialize map
    await MapAdapter.init();

    // Setup keyboard handler for debug mode
    this.setupKeyboardHandler();

    // Load initial data
    await this.loadCountries();

    // Initialize viewport-based navigation with current viewport area
    const bounds = MapAdapter.map.getBounds();
    ViewportLoader.currentAdminLevel = ViewportLoader.getAdminLevelForViewport(bounds);
    console.log('Viewport navigation ready (area-based thresholds)');

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

      // Reset time slider and choropleth when going back to world view
      TimeSlider.reset();
      ChoroplethManager.reset();

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
        // Don't fitToBounds for world view - use CONFIG.defaultCenter instead
        // (fitToBounds on 256 countries averages to 0,0 which is Gulf of Guinea)

        console.log(`Loaded ${result.count} countries${this.debugMode ? ' (debug mode)' : ''}`);
      }
    } catch (error) {
      console.error('Error loading countries:', error);
    }
  },

  /**
   * Handle hover over a feature - show popup
   */
  handleFeatureHover(feature, lngLat) {
    const properties = feature.properties;
    const popupHtml = PopupBuilder.build(properties, this.currentData);
    MapAdapter.showPopup([lngLat.lng, lngLat.lat], popupHtml);
  },

  /**
   * Handle single click on a feature - fly to location
   */
  handleFeatureClick(feature, lngLat) {
    const properties = feature.properties;

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

    // Check if this is multi-year data
    if (data.multi_year && data.year_data && data.year_range) {
      // Multi-year mode: initialize time slider
      console.log('Multi-year data detected, initializing time slider');
      console.log(`Year range: ${data.year_range.min} - ${data.year_range.max}`);

      // Hide any existing slider/legend first
      TimeSlider.reset();
      ChoroplethManager.reset();

      // Initialize time slider with the data
      TimeSlider.init(
        data.year_range,
        data.year_data,
        data.geojson,
        data.metric_key
      );

      // Fit map to the data
      MapAdapter.fitToBounds(data.geojson);

    } else {
      // Single-year mode: hide time slider, display normally
      TimeSlider.reset();
      ChoroplethManager.reset();

      if (data.geojson && data.geojson.type === 'FeatureCollection') {
        MapAdapter.loadGeoJSON(data.geojson);
        MapAdapter.fitToBounds(data.geojson);
      }
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
