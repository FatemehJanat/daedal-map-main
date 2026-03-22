/**
 * Viewport-based geometry loading.
 * Handles when and what to load based on map viewport changes.
 * This is where loading strategy and performance tuning lives.
 */

import { CONFIG } from './config.js';
import { GeometryCache } from './cache.js';
import { fetchMsgpack, postMsgpack } from './utils/fetch.js';

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
  currentAdminLevel: 0,
  enabled: true,  // Always enabled - viewport is the only navigation mode
  orderMode: false,  // When true, viewport loading is suspended (order data is displayed)
  levelLocked: false,  // When true, admin level doesn't change with zoom
  lockedLevel: null,   // The locked admin level (0-6)
  abortController: null,  // For cancelling stale requests
  requestId: 0,  // Counter to track which request is current
  lastRequestedLevel: null,  // Track the level of the in-flight request
  lastZoom: null,  // Track zoom level to distinguish zoom from pan
  lastRenderedLevel: 0,

  renderViewportFromCache(level = this.currentAdminLevel, bboxOverride = null) {
    if (!MapAdapter?.map) return 0;
    const bounds = MapAdapter.map.getBounds();
    const bboxObject = bboxOverride || {
      west: Number(bounds.getWest().toFixed(3)),
      south: Number(bounds.getSouth().toFixed(3)),
      east: Number(bounds.getEast().toFixed(3)),
      north: Number(bounds.getNorth().toFixed(3))
    };
    const visibleCached = GeometryCache.getForViewport(level, bboxObject);
    if (visibleCached.length > 0 || GeometryCache.isCovered(level, bboxObject)) {
      MapAdapter.loadGeoJSONWithFade({
        type: 'FeatureCollection',
        features: visibleCached
      });
      document.getElementById('totalAreas').textContent = visibleCached.length;
      this.lastRenderedLevel = level;
    }
    return visibleCached.length;
  },

  renderBestAvailableViewport(preferredLevel = this.currentAdminLevel, bboxOverride = null) {
    const tryLevels = [];
    for (let level = preferredLevel; level >= 0; level -= 1) {
      tryLevels.push(level);
    }
    if (!tryLevels.includes(this.lastRenderedLevel)) {
      tryLevels.push(this.lastRenderedLevel);
    }

    for (const level of tryLevels) {
      const count = this.renderViewportFromCache(level, bboxOverride);
      if (count > 0 || GeometryCache.isCovered(level, bboxOverride || {
        west: Number(MapAdapter.map.getBounds().getWest().toFixed(3)),
        south: Number(MapAdapter.map.getBounds().getSouth().toFixed(3)),
        east: Number(MapAdapter.map.getBounds().getEast().toFixed(3)),
        north: Number(MapAdapter.map.getBounds().getNorth().toFixed(3))
      })) {
        return level;
      }
    }
    return null;
  },

  // Viewport area thresholds (in square degrees) for admin level selection
  // These are tunable - smaller areas = deeper admin levels
  // Area roughly corresponds to zoom: zoom 10 ~ 1-2 sq deg, zoom 14 ~ 0.01 sq deg
  //
  // Navigation layers (contiguous, smooth zoom):
  //   0: Countries, 1: States, 2: Counties, 3: Tracts, 4: Block Groups, 5: Blocks
  //
  // Note: admin_level=3+ is USA-only via Census geometry (tracts, blockgroups, blocks).
  // Other countries fall back gracefully to their deepest available geoBoundaries level.
  // Census tracts provide smooth contiguous coverage at the sub-county level.
  areaThresholds: {
    level0: 3000,   // > 3000 sq deg = countries (world/continent view, zoom ~2-4)
    level1: 300,    // > 300 sq deg = states (large country view, zoom ~4-6)
    level2: 30,     // > 30 sq deg = counties (state/region view, zoom ~6-8)
    level3: 0.25,   // > 0.25 sq deg = census tracts (single county view, zoom ~9)
    level4: 0.01,   // > 0.01 sq deg = block groups (city/district view, zoom ~12-13)
    level5: 0.001   // > 0.001 sq deg = blocks (neighborhood, zoom ~14-15)
                    // < 0.001 sq deg = (reserved for future deeper levels)
  },

  /**
   * Calculate viewport area in square degrees
   */
  getViewportArea(bounds) {
    const width = Math.abs(bounds.getEast() - bounds.getWest());
    const height = Math.abs(bounds.getNorth() - bounds.getSouth());
    return width * height;
  },

  expandBboxForIndex(bboxObject, adminLevel) {
    if (!bboxObject) return bboxObject;
    if (adminLevel !== 1 && adminLevel !== 2) {
      return bboxObject;
    }

    const width = Math.max(0.001, bboxObject.east - bboxObject.west);
    const height = Math.max(0.001, bboxObject.north - bboxObject.south);
    const haloFactor = adminLevel === 1 ? 0.12 : 0.08;
    const haloLon = width * haloFactor;
    const haloLat = height * haloFactor;

    return {
      west: Number((bboxObject.west - haloLon).toFixed(3)),
      south: Number((bboxObject.south - haloLat).toFixed(3)),
      east: Number((bboxObject.east + haloLon).toFixed(3)),
      north: Number((bboxObject.north + haloLat).toFixed(3))
    };
  },

  /**
   * Get admin level based on viewport area (smarter than fixed zoom thresholds)
   * Larger viewport = shallower level, smaller viewport = deeper level
   *
   * Navigation levels (contiguous, smooth zoom):
   *   0 = Countries
   *   1 = States/Provinces
   *   2 = Counties
   *   3 = Census Tracts
   *   4 = Block Groups
   *   5 = Blocks
   *
   * Note: GADM admin_level=3 (cities/places) is skipped - it's fragmented.
   * Use overlay system for cities, tribal lands, ZCTAs, watersheds, etc.
   */
  getAdminLevelForViewport(bounds) {
    const area = this.getViewportArea(bounds);

    if (area > this.areaThresholds.level0) return 0;  // Countries
    if (area > this.areaThresholds.level1) return 1;  // States
    if (area > this.areaThresholds.level2) return 2;  // Counties
    if (area > this.areaThresholds.level3) return 3;  // Census Tracts
    if (area > this.areaThresholds.level4) return 4;  // Block Groups
    return 5;  // Blocks (deepest navigation level)
  },

  /**
   * Get the target viewport area for a given admin level
   * Returns a value solidly within the range for that level
   * (biased toward the upper end to account for projection distortion)
   */
  getTargetAreaForAdminLevel(level) {
    switch(level) {
      case 0: return 5000;    // Countries: > 3000 sq deg, target ~5000
      case 1: return 1000;    // States: 300-3000 sq deg, target ~1000
      case 2: return 150;     // Counties: 30-300 sq deg, target ~150 (zoom ~7.5)
      case 3: return 15;      // Census Tracts: 3-30 sq deg, target ~15
      case 4: return 1.5;     // Block Groups: 0.3-3 sq deg, target ~1.5
      case 5: return 0.15;    // Blocks: < 0.3 sq deg, target ~0.15
      default: return 15;     // Fallback to tracts
    }
  },

  /**
   * Calculate zoom level needed to achieve target viewport area at current center
   * Uses the relationship: area scales by ~4x per zoom level (2x each dimension)
   * @param {number} targetArea - Target viewport area in square degrees
   * @returns {number} Zoom level to achieve that area
   */
  getZoomForTargetArea(targetArea) {
    if (!MapAdapter?.map) return 2;

    const bounds = MapAdapter.map.getBounds();
    const currentArea = this.getViewportArea(bounds);
    const currentZoom = MapAdapter.map.getZoom();

    // Each zoom level change roughly quarters/quadruples the viewport area
    // zoom_delta = log2(current_area / target_area) / 2
    // (divide by 2 because area scales with zoom^2)
    const zoomDelta = Math.log2(currentArea / targetArea) / 2;
    const targetZoom = currentZoom + zoomDelta;

    // Clamp to reasonable zoom range
    return Math.max(1, Math.min(18, targetZoom));
  },

  /**
   * Get zoom level for a given admin level based on current viewport
   * Calculates the zoom needed to achieve the target area for that level
   */
  getZoomForAdminLevel(level) {
    const targetArea = this.getTargetAreaForAdminLevel(level);
    return this.getZoomForTargetArea(targetArea);
  },

  /**
   * Toggle level lock on/off
   * When locked, zoom changes don't affect admin level
   */
  toggleLock() {
    if (this.levelLocked) {
      // Unlock
      this.levelLocked = false;
      this.lockedLevel = null;
      console.log('Admin level unlocked - will change with zoom');
    } else {
      // Lock at current level
      this.levelLocked = true;
      this.lockedLevel = this.currentAdminLevel;
      console.log(`Admin level locked at ${this.lockedLevel}`);
    }
    return this.levelLocked;
  },

  /**
   * Set lock state directly
   * @param {boolean} locked - Whether to lock
   * @param {number} level - Level to lock at (optional, uses current if not provided)
   */
  setLock(locked, level = null) {
    this.levelLocked = locked;
    if (locked) {
      this.lockedLevel = level !== null ? level : this.currentAdminLevel;
      console.log(`Admin level locked at ${this.lockedLevel}`);
    } else {
      this.lockedLevel = null;
      console.log('Admin level unlocked');
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
    let missingLocIds = [];
    let requestKey = null;

    // Only abort if the admin level is CHANGING (not just panning within same level)
    // This prevents cancelling slow-loading levels like blocks when user pans
    const levelChanged = this.lastRequestedLevel !== null && this.lastRequestedLevel !== adminLevel;
    if (this.abortController && levelChanged) {
      this.abortController.abort();
      console.log(`Level changed ${this.lastRequestedLevel} -> ${adminLevel}, cancelling previous request`);
    }

    // Track which level we're requesting
    this.lastRequestedLevel = adminLevel;

    // Create new abort controller for this request
    this.abortController = new AbortController();
    const thisRequestId = ++this.requestId;

    const bounds = MapAdapter.map.getBounds();
    const bboxObject = {
      west: Number(bounds.getWest().toFixed(3)),
      south: Number(bounds.getSouth().toFixed(3)),
      east: Number(bounds.getEast().toFixed(3)),
      north: Number(bounds.getNorth().toFixed(3))
    };
    // Round to 3 decimal places (~100m precision) - more than enough for viewport queries
    const bbox = [
      bboxObject.west.toFixed(3),
      bboxObject.south.toFixed(3),
      bboxObject.east.toFixed(3),
      bboxObject.north.toFixed(3)
    ].join(',');
    const indexBboxObject = this.expandBboxForIndex(bboxObject, adminLevel);
    const indexBbox = [
      indexBboxObject.west.toFixed(3),
      indexBboxObject.south.toFixed(3),
      indexBboxObject.east.toFixed(3),
      indexBboxObject.north.toFixed(3)
    ].join(',');

    if (GeometryCache.isCovered(adminLevel, bboxObject)) {
      console.log(`[${thisRequestId}] Level ${adminLevel} viewport already covered, rendering from cache`);
      this.renderViewportFromCache(adminLevel, bboxObject);
      return;
    }

    requestKey = GeometryCache.startInFlight(adminLevel, bboxObject);
    if (requestKey === null) {
      console.log(`[${thisRequestId}] Level ${adminLevel} viewport already in flight, rendering cached subset`);
      this.renderViewportFromCache(adminLevel, bboxObject);
      return;
    }

    try {
      const indexUrl = `/geometry/index?admin_level=${adminLevel}&bbox=${indexBbox}`;
      console.log(`[${thisRequestId}] Fetching geometry index level ${adminLevel}`);
      const indexData = await fetchMsgpack(indexUrl, { signal: this.abortController.signal });
      const requestedLocIds = (indexData.rows || [])
        .map((row) => row.loc_id)
        .filter(Boolean);
      const loadedLocIds = requestedLocIds.filter((locId) => GeometryCache.hasLocId(locId));
      const inFlightLocIds = requestedLocIds.filter((locId) => GeometryCache.isLocIdInFlight(adminLevel, locId));
      missingLocIds = requestedLocIds.filter((locId) =>
        !GeometryCache.hasLocId(locId) && !GeometryCache.isLocIdInFlight(adminLevel, locId)
      );

      if (missingLocIds.length === 0) {
        const visibleCached = GeometryCache.getForViewport(adminLevel, bboxObject);
        const fullyLoaded = inFlightLocIds.length === 0 && loadedLocIds.length === requestedLocIds.length;
        console.log(`[${thisRequestId}] Level ${adminLevel} has no newly missing ids (${loadedLocIds.length} loaded, ${inFlightLocIds.length} in flight)`);
        if (fullyLoaded) {
          GeometryCache.markCoverage(adminLevel, bboxObject);
        }
        if (visibleCached.length > 0 || fullyLoaded || requestedLocIds.length === 0) {
          const renderedLevel = this.renderViewportFromCache(adminLevel, bboxObject);
          if (renderedLevel === 0 && visibleCached.length === 0) {
            this.renderBestAvailableViewport(Math.min(adminLevel - 1, this.lastRenderedLevel), bboxObject);
          }
        }
        return;
      }

      GeometryCache.markLocIdsInFlight(adminLevel, missingLocIds);
      console.log(`[${thisRequestId}] Fetching ${missingLocIds.length} missing geometry ids at level ${adminLevel}`);
      const data = await postMsgpack(
        '/geometry/selection',
        { loc_ids: missingLocIds },
        { signal: this.abortController.signal }
      );

      if (data.features?.length) {
        GeometryCache.add(data.features);
      }

      // Check if this request was superseded by a newer one
      if (thisRequestId !== this.requestId) {
        console.log(`[${thisRequestId}] Discarding stale response (current is ${this.requestId})`);
        if (adminLevel === this.currentAdminLevel) {
          this.renderBestAvailableViewport(adminLevel);
        }
        return;
      }

      // Double-check we're still on the same level (user might have zoomed while parsing)
      if (adminLevel !== this.currentAdminLevel) {
        console.log(`[${thisRequestId}] Level changed during load (was ${adminLevel}, now ${this.currentAdminLevel}), discarding`);
        this.renderBestAvailableViewport(this.currentAdminLevel);
        return;
      }

      const featureCount = data.features?.length || 0;
      console.log(`[${thisRequestId}] Level ${adminLevel} response: ${featureCount} features`);

      if (featureCount > 0) {
        GeometryCache.markCoverage(adminLevel, bboxObject);
        this.renderViewportFromCache(adminLevel, bboxObject);
      } else {
        this.renderBestAvailableViewport(Math.min(adminLevel - 1, this.lastRenderedLevel), bboxObject);
      }
    } catch (err) {
      // Ignore abort errors - they're expected when we cancel requests
      if (err.name === 'AbortError') {
        console.log(`[${thisRequestId}] Request aborted`);
        return;
      }
      console.error('Viewport load failed:', err);
      // Keep displaying cached data - user sees no change
      const cached = GeometryCache.getForViewport(adminLevel, bboxObject);
      if (cached.length === 0) {
        console.warn('No cached data available');
        this.renderBestAvailableViewport(Math.min(adminLevel - 1, this.lastRenderedLevel), bboxObject);
      }
    } finally {
      GeometryCache.clearLocIdsInFlight(adminLevel, missingLocIds);
      GeometryCache.finishInFlight(adminLevel, requestKey);
    }
  },

  /**
   * Handle zoom/move change - check if admin level should change based on viewport area
   */
  onViewportChange() {
    if (!this.enabled || !MapAdapter?.map) return;

    const bounds = MapAdapter.map.getBounds();
    const area = this.getViewportArea(bounds);
    const calculatedLevel = this.getAdminLevelForViewport(bounds);

    // Use locked level if lock is active, otherwise use calculated level
    const newLevel = this.levelLocked ? this.lockedLevel : calculatedLevel;

    // In order mode, filter displayed data by admin level instead of loading new data
    if (this.orderMode) {
      if (newLevel !== this.currentAdminLevel) {
        const lockInfo = this.levelLocked ? ' [LOCKED]' : '';
        console.log(`Order mode: Viewport area ${area.toFixed(0)} sq deg -> Admin level ${newLevel}${lockInfo}`);
        this.currentAdminLevel = newLevel;
        // Tell TimeSlider to filter to this admin level
        TimeSlider?.setAdminLevelFilter(newLevel);
      }
      return;
    }

    // Only load when admin level CHANGES - not on every zoom step
    if (newLevel !== this.currentAdminLevel) {
      const lockInfo = this.levelLocked ? ' [LOCKED]' : '';
      console.log(`Viewport area ${area.toFixed(0)} sq deg -> Admin level ${newLevel}${lockInfo}`);

      this.currentAdminLevel = newLevel;
      this.load(newLevel);

      // Update breadcrumb to show current level
      NavigationManager?.updateLevelDisplay(newLevel);
    }
    // Note: Same-level pan reloads are handled by onMoveEnd, not here
  },

  /**
   * Handle pan/move - reload same level for new viewport area
   * Only triggers on actual panning, not zoom changes
   */
  onPanEnd() {
    if (!this.enabled || !MapAdapter?.map || this.orderMode) return;

    // Reload current level for the new viewport position
    this.load(this.currentAdminLevel);
  },

  /**
   * Handle zoom end - just update lastZoom for tracking
   * The actual level-change logic is handled by onMoveEnd to avoid double-firing
   */
  onZoomEnd() {
    // No-op: moveend handles everything now
    // This method exists for API compatibility but does nothing
  },

  /**
   * Handle move end - detect zoom vs pan and respond appropriately
   * moveend fires for both zoom and pan, so we check if zoom changed
   */
  onMoveEnd() {
    if (!MapAdapter?.map) return;

    // Demographics overlay must be active for any viewport-based loading or filtering
    // Chat orders automatically enable demographics overlay when displaying demographic data
    const OverlaySelector = window.OverlaySelector;
    const activeOverlays = OverlaySelector?.getActiveOverlays?.() || [];
    if (!activeOverlays.includes('demographics')) {
      return;  // Skip if demographics not enabled
    }

    const currentZoom = MapAdapter.map.getZoom();

    // Check if this was a zoom or a pan
    const wasZoom = this.lastZoom === null || Math.abs(currentZoom - this.lastZoom) >= 0.01;

    // Update lastZoom for next comparison
    this.lastZoom = currentZoom;

    // In order mode, filter displayed data by admin level instead of loading new data
    if (this.orderMode) {
      if (wasZoom) {
        this.onViewportChange();  // This will filter the order data by admin level
      }
      return;  // Don't load new data in order mode
    }

    if (wasZoom) {
      // Zoom operation: check if admin level should change
      this.onViewportChange();
    } else {
      // Pure pan - reload same level for new viewport position
      this.onPanEnd();
    }
  }
};
