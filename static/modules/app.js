/**
 * App - Main application controller.
 * Orchestrates all modules and handles initialization.
 */

import { CONFIG } from './config.js';
import { GeometryCache } from './cache.js';
import { ViewportLoader, setDependencies as setViewportDeps } from './viewport-loader.js';
import { MapAdapter, setDependencies as setMapDeps } from './map-adapter.js';
import { NavigationManager, setDependencies as setNavDeps } from './navigation.js';
import { PopupBuilder, setDependencies as setPopupDeps } from './popup-builder.js';
import { ChatManager, OrderManager, setDependencies as setChatDeps } from './chat-panel.js';
import { TimeSlider, setDependencies as setTimeDeps } from './time-slider.js';
import { ChoroplethManager, setDependencies as setChoroDeps } from './choropleth.js';
import { ResizeManager, SidebarResizer, SettingsManager } from './sidebar.js';

// ============================================================================
// APP - Main application controller
// ============================================================================

export const App = {
  currentData: null,
  debugMode: false,  // Toggle with 'D' key - shows hierarchy depth colors

  /**
   * Initialize the application
   */
  async init() {
    console.log('Initializing Map Explorer...');

    // Wire up circular dependencies
    setViewportDeps({ MapAdapter, NavigationManager, App });
    setMapDeps({ ViewportLoader, NavigationManager, App, PopupBuilder });
    setNavDeps({ MapAdapter, ViewportLoader, App });
    setPopupDeps({ App });
    setChatDeps({ MapAdapter, App });
    setTimeDeps({ MapAdapter, ChoroplethManager });
    setChoroDeps({ MapAdapter });

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

      // Re-enable viewport loading (exit order mode)
      ViewportLoader.orderMode = false;

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

    // Suspend viewport loading when displaying order data
    // This prevents viewport API from overwriting our ordered data
    ViewportLoader.orderMode = true;

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

// Export for global access if needed
if (typeof window !== 'undefined') {
  window.App = App;
}
