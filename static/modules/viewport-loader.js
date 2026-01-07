/**
 * Viewport-based geometry loading.
 * Handles when and what to load based on map viewport changes.
 * This is where loading strategy and performance tuning lives.
 */

import { CONFIG } from './config.js';
import { GeometryCache } from './cache.js';

// These will be set by app.js to avoid circular dependencies
let MapAdapter = null;
let NavigationManager = null;
let App = null;
let TimeSlider = null;

export function setDependencies(deps) {
  MapAdapter = deps.MapAdapter;
  NavigationManager = deps.NavigationManager;
  App = deps.App;
  TimeSlider = deps.TimeSlider;
}

// ============================================================================
// VIEWPORT LOADER - Debounced viewport-based geometry loading
// ============================================================================

export const ViewportLoader = {
  loadTimeout: null,
  spinnerTimeout: null,
  currentAdminLevel: 0,
  isLoading: false,
  enabled: true,  // Always enabled - viewport is the only navigation mode
  orderMode: false,  // When true, viewport loading is suspended (order data is displayed)

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
   * Uses short debounce (300ms) to batch rapid viewport changes
   */
  async load(adminLevel) {
    if (this.loadTimeout) clearTimeout(this.loadTimeout);

    // Short debounce to batch rapid changes, but responsive enough to feel instant
    this.loadTimeout = setTimeout(async () => {
      await this.doLoad(adminLevel);
    }, 300);
  },

  /**
   * Actually perform the load
   */
  async doLoad(adminLevel) {
    if (!MapAdapter?.map) return;

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
      const debugParam = App?.debugMode ? '&debug=true' : '';
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
    if (!this.enabled || !MapAdapter?.map) return;

    const bounds = MapAdapter.map.getBounds();
    const area = this.getViewportArea(bounds);
    const newLevel = this.getAdminLevelForViewport(bounds);

    // In order mode, filter displayed data by admin level instead of loading new data
    if (this.orderMode) {
      if (newLevel !== this.currentAdminLevel) {
        console.log(`Order mode: Viewport area ${area.toFixed(0)} sq deg -> Admin level ${newLevel}`);
        this.currentAdminLevel = newLevel;
        // Tell TimeSlider to filter to this admin level
        TimeSlider?.setAdminLevelFilter(newLevel);
      }
      return;
    }

    if (newLevel !== this.currentAdminLevel) {
      console.log(`Viewport area ${area.toFixed(0)} sq deg -> Admin level ${newLevel}`);
      this.currentAdminLevel = newLevel;
      this.load(newLevel);

      // Update breadcrumb to show current level
      NavigationManager?.updateLevelDisplay(newLevel);
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
