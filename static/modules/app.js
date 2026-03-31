/**
 * App - Main application controller.
 * Orchestrates all modules and handles initialization.
 */

import { CONFIG } from './config.js';
import { GeometryCache } from './cache.js';
import { fetchMsgpack, postMsgpack } from './utils/fetch.js';
import { ViewportLoader, setDependencies as setViewportDeps } from './viewport-loader.js';
import { MapAdapter, setDependencies as setMapDeps } from './map-adapter.js';
import { NavigationManager, setDependencies as setNavDeps } from './navigation.js';
import { PopupBuilder, setDependencies as setPopupDeps } from './popup-builder.js';
import { ChatManager, OrderManager, setDependencies as setChatDeps } from './chat-panel.js';
import { TimeSlider, setDependencies as setTimeDeps } from './time-slider.js';
import { ChoroplethManager, setDependencies as setChoroDeps } from './choropleth.js';
import { ResizeManager, SidebarResizer } from './sidebar.js';
import { SelectionManager, setDependencies as setSelectionDeps } from './selection-manager.js';
import { HurricaneHandler, setDependencies as setHurricaneDeps } from './hurricane-handler.js';
import { OverlaySelector, setDependencies as setOverlayDeps } from './overlay-selector.js';
import { ModelRegistry } from './models/model-registry.js';
import { OverlayController, setDependencies as setOverlayControllerDeps } from './overlay-controller.js';
import { DisasterPopup, setDependencies as setDisasterPopupDeps } from './disaster-popup.js';
import { GeometryModel, setDependencies as setGeometryDeps } from './models/model-geometry.js';
import { AuthManager } from './auth.js';
import { TutorialMode } from './tutorial-mode.js';

// ============================================================================
// APP - Main application controller
// ============================================================================

export const App = {
  currentData: null,
  debugMode: false,  // Toggle with 'D' key - shows hierarchy depth colors
  geometryOverlayActive: false,  // True when geometry overlay (ZCTA, tribal, etc.) is displayed
  mobileNoticeMql: null,
  activeMetricOrderContext: null,
  metricPrefetchHandle: null,

  getNumericAdminLevel(level) {
    if (typeof level === 'number' && !Number.isNaN(level)) return level;
    const match = String(level || '').match(/^admin_(\d+)$/);
    return match ? parseInt(match[1], 10) : null;
  },

  decorateMetricGeojsonWithAdminLevel(data) {
    if (!data?.geojson?.features?.length) return data;
    const adminLevel = this.getNumericAdminLevel(data.geographic_level);
    if (adminLevel == null) return data;

    return {
      ...data,
      geojson: {
        ...data.geojson,
        features: data.geojson.features.map((feature) => ({
          ...feature,
          properties: {
            ...(feature.properties || {}),
            admin_level_num: feature?.properties?.admin_level_num ?? adminLevel
          }
        }))
      }
    };
  },

  /**
   * Merge new multi-year data into existing data (same source).
   * Combines geojson features, year_data, and expands year_range.
   */
  mergeMultiYearData(existing, incoming) {
    if (!existing || !incoming) return incoming;

    // Merge GeoJSON features (by loc_id to avoid duplicates)
    const existingLocIds = new Set(
      existing.geojson?.features?.map(f => f.properties?.loc_id || f.id) || []
    );
    const newFeatures = incoming.geojson?.features?.filter(
      f => !existingLocIds.has(f.properties?.loc_id || f.id)
    ) || [];
    const mergedFeatures = [
      ...(existing.geojson?.features || []),
      ...newFeatures
    ];

    // Merge year_data: {year: {loc_id: {metric: value}}}
    const mergedYearData = { ...(existing.year_data || {}) };
    for (const [year, locData] of Object.entries(incoming.year_data || {})) {
      if (!mergedYearData[year]) {
        mergedYearData[year] = {};
      }
      for (const [locId, metrics] of Object.entries(locData)) {
        if (!mergedYearData[year][locId]) {
          mergedYearData[year][locId] = {};
        }
        Object.assign(mergedYearData[year][locId], metrics);
      }
    }

    // Expand year_range
    const mergedYearRange = {
      min: Math.min(existing.year_range?.min || Infinity, incoming.year_range?.min || Infinity),
      max: Math.max(existing.year_range?.max || -Infinity, incoming.year_range?.max || -Infinity),
      available_years: [
        ...new Set([
          ...(existing.year_range?.available_years || []),
          ...(incoming.year_range?.available_years || [])
        ])
      ].sort((a, b) => a - b)
    };

    // Merge available_metrics
    const mergedMetrics = [
      ...new Set([
        ...(existing.available_metrics || []),
        ...(incoming.available_metrics || [])
      ])
    ];

    // Merge metric_year_ranges
    const mergedMetricYearRanges = {
      ...(existing.metric_year_ranges || {}),
      ...(incoming.metric_year_ranges || {})
    };

    return {
      ...incoming,
      geojson: { type: 'FeatureCollection', features: mergedFeatures },
      year_data: mergedYearData,
      year_range: mergedYearRange,
      available_metrics: mergedMetrics,
      metric_year_ranges: mergedMetricYearRanges,
      count: mergedFeatures.length
    };
  },

  mergeMetricData(existing, incoming) {
    if (!existing || !incoming) return incoming;

    const existingLocIds = new Set(
      existing.geojson?.features?.map(f => f.properties?.loc_id || f.id) || []
    );
    const newFeatures = incoming.geojson?.features?.filter(
      f => !existingLocIds.has(f.properties?.loc_id || f.id)
    ) || [];
    const mergedFeatures = [
      ...(existing.geojson?.features || []),
      ...newFeatures
    ];

    const mergedYearData = { ...(existing.year_data || {}) };
    for (const [year, locData] of Object.entries(incoming.year_data || {})) {
      if (!mergedYearData[year]) {
        mergedYearData[year] = {};
      }
      for (const [locId, metrics] of Object.entries(locData || {})) {
        if (!mergedYearData[year][locId]) {
          mergedYearData[year][locId] = {};
        }
        Object.assign(mergedYearData[year][locId], metrics || {});
      }
    }

    const mergedYearRange = (existing.year_range || incoming.year_range)
      ? {
          min: Math.min(existing.year_range?.min ?? incoming.year_range?.min ?? Infinity, incoming.year_range?.min ?? Infinity),
          max: Math.max(existing.year_range?.max ?? incoming.year_range?.max ?? -Infinity, incoming.year_range?.max ?? -Infinity),
          available_years: [
            ...new Set([
              ...(existing.year_range?.available_years || []),
              ...(incoming.year_range?.available_years || [])
            ])
          ].sort((a, b) => a - b)
        }
      : null;

    const mergedMetrics = [
      ...new Set([
        ...(existing.available_metrics || []),
        ...(incoming.available_metrics || [])
      ])
    ];

    const mergedMetricYearRanges = {
      ...(existing.metric_year_ranges || {}),
      ...(incoming.metric_year_ranges || {})
    };

    const mergedLevels = [
      ...new Set([
        ...(existing.available_geo_levels || []),
        ...(incoming.available_geo_levels || [])
      ])
    ].sort((a, b) => {
      const aNum = parseInt(String(a).replace('admin_', ''), 10);
      const bNum = parseInt(String(b).replace('admin_', ''), 10);
      if (!Number.isNaN(aNum) && !Number.isNaN(bNum)) return aNum - bNum;
      return String(a).localeCompare(String(b));
    });

    return {
      ...existing,
      ...incoming,
      geojson: { type: 'FeatureCollection', features: mergedFeatures },
      year_data: mergedYearData,
      year_range: mergedYearRange,
      available_metrics: mergedMetrics,
      metric_year_ranges: mergedMetricYearRanges,
      available_geo_levels: mergedLevels,
      count: mergedFeatures.length
    };
  },

  getAdminLevelFromLocId(locId) {
    if (!locId) return 0;
    return (locId.match(/-/g) || []).length;
  },

  getFeatureAdminLevel(feature) {
    const explicitLevel = feature?.properties?.admin_level_num;
    if (explicitLevel != null && !Number.isNaN(Number(explicitLevel))) {
      return Number(explicitLevel);
    }
    const locId = feature?.properties?.loc_id || feature?.id;
    return this.getAdminLevelFromLocId(locId);
  },

  filterGeojsonByAdminLevel(geojson, level) {
    if (!geojson?.features || level == null) return geojson;
    return {
      type: 'FeatureCollection',
      features: geojson.features.filter((feature) => {
        return this.getFeatureAdminLevel(feature) === level;
      })
    };
  },

  setMetricOrderContext(order, data, options = {}) {
    const items = order?.items || [];
    const sourceIds = [...new Set(items.map((item) => item?.source_id).filter(Boolean))];
    if (items.length === 0 || sourceIds.length !== 1 || data?.data_type !== 'metrics') {
      this.activeMetricOrderContext = null;
      this.clearMetricPrefetch();
      return;
    }

    const sourceId = data?.source_id || sourceIds[0];
    const availableGeoLevels = (data?.available_geo_levels || [])
      .map((level) => {
        const match = String(level).match(/^admin_(\d+)$/);
        return match ? parseInt(match[1], 10) : null;
      })
      .filter((level) => level != null)
      .sort((a, b) => a - b);

    const currentLevelMatch = String(data?.geographic_level || '').match(/^admin_(\d+)$/);
    let currentLevel = currentLevelMatch ? parseInt(currentLevelMatch[1], 10) : null;
    if (currentLevel == null && data?.geojson?.features?.length) {
      const discoveredLevels = [
        ...new Set(
          data.geojson.features
            .map((feature) => this.getFeatureAdminLevel(feature))
            .filter((level) => level != null && !Number.isNaN(level))
        )
      ].sort((a, b) => a - b);
      if (discoveredLevels.length === 1) {
        currentLevel = discoveredLevels[0];
      } else if (discoveredLevels.length > 1) {
        currentLevel = discoveredLevels[discoveredLevels.length - 1];
      }
    }

    if (!sourceId || availableGeoLevels.length === 0) {
      this.activeMetricOrderContext = null;
      this.clearMetricPrefetch();
      return;
    }

    const existingLoadedLevels = (
      this.activeMetricOrderContext &&
      this.activeMetricOrderContext.sourceId === sourceId
    )
      ? Array.from(this.activeMetricOrderContext.loadedLevels || [])
      : [];

    const loadedLevels = new Set(existingLoadedLevels);
    if (currentLevel != null) {
      loadedLevels.add(currentLevel);
    }

    this.activeMetricOrderContext = {
      order: JSON.parse(JSON.stringify(order)),
      sourceId,
      availableGeoLevels,
      loadedLevels,
      loadingLevels: new Set(),
      loadingPromises: new Map()
    };

    if (options.schedulePrefetch !== false) {
      const highestLoadedLevel = loadedLevels.size > 0 ? Math.max(...loadedLevels) : null;
      this.scheduleNextMetricLevelPrefetch(highestLoadedLevel);
    }
  },

  hasLazyMetricOrder() {
    return !!this.activeMetricOrderContext;
  },

  clearMetricPrefetch() {
    if (this.metricPrefetchHandle == null) return;

    if (typeof window !== 'undefined' && typeof window.cancelIdleCallback === 'function') {
      window.cancelIdleCallback(this.metricPrefetchHandle);
    } else {
      clearTimeout(this.metricPrefetchHandle);
    }
    this.metricPrefetchHandle = null;
  },

  scheduleNextMetricLevelPrefetch(fromLevel = null) {
    const context = this.activeMetricOrderContext;
    if (!context || context.availableGeoLevels.length === 0) return;

    const currentLevel = fromLevel != null
      ? fromLevel
      : (ViewportLoader?.currentAdminLevel ?? null);
    if (currentLevel == null) return;

    const nextLevel = context.availableGeoLevels.find((level) =>
      level > currentLevel &&
      !context.loadedLevels.has(level) &&
      !context.loadingLevels.has(level)
    );
    if (nextLevel == null) return;

    this.clearMetricPrefetch();

    const runPrefetch = () => {
      this.metricPrefetchHandle = null;

      if (!this.activeMetricOrderContext || this.activeMetricOrderContext.sourceId !== context.sourceId) {
        return;
      }

      this.ensureMetricLevelLoaded(nextLevel, { prefetch: true }).catch((error) => {
        console.warn(`Metric prefetch failed for admin_${nextLevel}:`, error.message);
      });
    };

    if (typeof window !== 'undefined' && typeof window.requestIdleCallback === 'function') {
      this.metricPrefetchHandle = window.requestIdleCallback(runPrefetch, { timeout: 1200 });
    } else {
      this.metricPrefetchHandle = window.setTimeout(runPrefetch, 350);
    }
  },

  applyOrderModeLevelFilter(level) {
    if (!this.currentData || this.currentData.data_type !== 'metrics') return;

    if (this.currentData.multi_year && TimeSlider?.baseGeojson) {
      TimeSlider.setAdminLevelFilter(level);
      return;
    }

    if (this.currentData.geojson?.features) {
      const filtered = this.filterGeojsonByAdminLevel(this.currentData.geojson, level);
      MapAdapter?.updateSourceData(filtered);
      const countEl = document.getElementById('totalAreas');
      if (countEl) {
        countEl.textContent = filtered.features.length;
      }
    }
  },

  async ensureMetricLevelLoaded(level, options = {}) {
    const context = this.activeMetricOrderContext;
    if (!context) return false;
    if (context.loadedLevels.has(level)) return true;
    if (context.loadingLevels.has(level)) {
      const existingPromise = context.loadingPromises?.get(level);
      return existingPromise ? existingPromise : false;
    }
    if (!context.availableGeoLevels.includes(level)) return false;

    const geoLevel = `admin_${level}`;
    const nextOrder = JSON.parse(JSON.stringify(context.order));
    nextOrder.items = (nextOrder.items || []).map((item) => ({
      ...item,
      geo_level: geoLevel
    }));

    const apiUrl = (typeof API_BASE_URL !== 'undefined' && API_BASE_URL)
      ? `${API_BASE_URL}/chat`
      : '/chat';

    context.loadingLevels.add(level);

    const loadPromise = (async () => {
      try {
        const response = await postMsgpack(apiUrl, {
          confirmed_order: nextOrder,
          sessionId: ChatManager.sessionId
        });

        console.log(`Lazy metric response for ${geoLevel}:`, {
          type: response?.type,
          geographicLevel: response?.geographic_level,
          featureCount: response?.geojson?.features?.length ?? 0
        });

        if (response?.type === 'already_loaded') {
          context.loadedLevels.add(level);
          if (!options.prefetch) {
            this.scheduleNextMetricLevelPrefetch(level);
          }
          return true;
        }

        if (response?.type === 'error') {
          console.warn(`Lazy metric load failed for ${geoLevel}:`, response.message);
          return false;
        }

        if (response?.geojson?.features) {
          console.log(`Lazy metric load applied for ${geoLevel}: ${response.geojson.features.length} features`);
          this.ingestLazyMetricData(response, nextOrder, {
            schedulePrefetch: !options.prefetch
          });
          context.loadedLevels.add(level);
          if (ViewportLoader?.currentAdminLevel === level) {
            this.applyOrderModeLevelFilter(level);
          }
          if (!options.prefetch) {
            this.scheduleNextMetricLevelPrefetch(level);
          }
          return true;
        }

        console.warn(`Lazy metric response missing geojson features for ${geoLevel}`, response);
      } catch (error) {
        console.warn(`Lazy metric fetch error for ${geoLevel}:`, error.message);
      } finally {
        context.loadingLevels.delete(level);
        context.loadingPromises?.delete(level);
      }

      return false;
    })();

    context.loadingPromises.set(level, loadPromise);
    return loadPromise;
  },

  ingestLazyMetricData(data, order, options = {}) {
    if (data?.source_id) {
      OverlayController?.ingestMetricData(
        data.source_id,
        data.geojson,
        data.year_data,
        data.year_range
      );
    }

    this.displayData(data, { order, lazyLoad: true });
    this.setMetricOrderContext(order, this.currentData, options);
  },

  /**
   * Initialize the application
   */
  async init() {
    console.log('Initializing Map Explorer...');

    // Wire up circular dependencies
    setViewportDeps({ MapAdapter, NavigationManager, App, TimeSlider });
    setMapDeps({ ViewportLoader, NavigationManager, App, PopupBuilder, OverlayController });
    setNavDeps({ MapAdapter, ViewportLoader, App });
    setPopupDeps({ App, ChoroplethManager });
    setChatDeps({ MapAdapter, App, SelectionManager, OverlayController, OverlaySelector });
    setTimeDeps({ MapAdapter, ChoroplethManager });
    setChoroDeps({ MapAdapter });
    setSelectionDeps({ MapAdapter, ChatManager });
    setHurricaneDeps({ TimeSlider, MapAdapter });
    setOverlayDeps({ MapAdapter, ModelRegistry });
    ModelRegistry.setDependencies({ MapAdapter, TimeSlider });
    setOverlayControllerDeps({ MapAdapter, ModelRegistry, OverlaySelector, TimeSlider });
    setDisasterPopupDeps({ MapAdapter });
    setGeometryDeps({ MapAdapter });

    await AuthManager.init();
    this.setupMobileExperienceNotice();

    // Initialize components
    ChatManager.init();
    OrderManager.init();
    ResizeManager.init();
    SidebarResizer.init();
    TutorialMode.init();

    // Initialize TimeSlider early (UI setup only, no data)
    // This ensures the slider is visible and listener system is ready
    // before overlays are enabled
    TimeSlider.initSlider();

    await OverlaySelector.init();
    OverlayController.init();

    // Initialize map
    await MapAdapter.init();

    // Replay any overlays that were restored from localStorage before the map was ready.
    // OverlaySelector.init() restores saved state before MapAdapter.init() runs, so any
    // active overlays fire into a map that doesn't exist yet. Re-trigger them now.
    for (const overlayId of OverlaySelector.activeOverlays) {
      OverlayController.handleOverlayChange(overlayId, true);
    }

    // Shift the map's logical center to account for the sidebar width.
    // The map container covers the full viewport but the sidebar overlays it on the left,
    // so without padding the "center" is visually offset. MapLibre's padding option
    // moves the optical center so features like flyTo and fitBounds land in the visible area.
    const sidebarEl = document.getElementById('sidebar');
    const applyMapPadding = () => {
      const leftPad = sidebarEl.classList.contains('collapsed') ? 0 : sidebarEl.offsetWidth;
      MapAdapter.map.easeTo({ padding: { left: leftPad }, duration: 300 });
    };
    applyMapPadding();
    new MutationObserver(() => applyMapPadding()).observe(sidebarEl, {
      attributes: true,
      attributeFilter: ['class', 'style']
    });

    // Load reference data for popups (non-blocking)
    PopupBuilder.loadAdminLevels();

    // Setup keyboard handler for debug mode
    this.setupKeyboardHandler();

    // Don't load countries at startup - wait for demographics overlay to be enabled
    // This keeps the map clean until user selects what they want to see

    // Initialize viewport-based navigation with current viewport area
    const bounds = MapAdapter.map.getBounds();
    ViewportLoader.currentAdminLevel = ViewportLoader.getAdminLevelForViewport(bounds);
    console.log('Viewport navigation ready (area-based thresholds)');

    // Force initial geometry load if demographics was restored as active.
    // onMoveEnd fires during MapAdapter.init() but onViewportChange only loads on level
    // *changes* - since currentAdminLevel starts at 0 and world zoom maps to 0, no
    // load is ever triggered. Kick it manually here after overlay state is set.
    if (OverlaySelector.getActiveOverlays().includes('demographics')) {
      ViewportLoader.load(ViewportLoader.currentAdminLevel);
    }

    // Initialize admin level buttons
    NavigationManager.initLevelButtons();
    NavigationManager.updateLevelButtons(ViewportLoader.currentAdminLevel);

    // Setup globe toggle checkbox
    this.setupGlobeToggle();

    // Setup satellite toggle checkbox
    this.setupSatelliteToggle();

    console.log('Map Explorer ready');
    console.log('Press D to toggle debug mode (hierarchy depth colors)');
  },

  setupMobileExperienceNotice() {
    const noticeEl = document.getElementById('mobileMapNotice');
    if (!noticeEl) return;

    const applyMobileState = () => {
      const isNarrow = window.innerWidth <= 820;
      const hasTouchLikePointer = window.matchMedia('(pointer: coarse)').matches;
      const isMobileUA = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent || '');
      const limitedMobile = isNarrow && (hasTouchLikePointer || isMobileUA);

      document.body.classList.toggle('mobile-limited', limitedMobile);
      noticeEl.hidden = !limitedMobile;
    };

    this.mobileNoticeMql = window.matchMedia('(pointer: coarse)');
    if (typeof this.mobileNoticeMql.addEventListener === 'function') {
      this.mobileNoticeMql.addEventListener('change', applyMobileState);
    } else if (typeof this.mobileNoticeMql.addListener === 'function') {
      this.mobileNoticeMql.addListener(applyMobileState);
    }

    window.addEventListener('resize', applyMobileState);
    applyMobileState();
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
   * Setup globe/3D toggle checkbox
   */
  setupGlobeToggle() {
    const checkbox = document.getElementById('globeCheckbox');
    if (checkbox) {
      // Restore saved state
      try {
        const saved = localStorage.getItem('countymap_globe_enabled');
        if (saved === 'true') {
          checkbox.checked = true;
          MapAdapter.toggleGlobe(true);
        }
      } catch (e) {}

      checkbox.addEventListener('change', (e) => {
        MapAdapter.toggleGlobe(e.target.checked);
        // Save state
        try {
          localStorage.setItem('countymap_globe_enabled', e.target.checked ? 'true' : 'false');
        } catch (err) {}
      });
    }
  },

  /**
   * Setup satellite view toggle checkbox
   */
  setupSatelliteToggle() {
    const checkbox = document.getElementById('satCheckbox');
    if (checkbox) {
      // Restore saved state
      try {
        const saved = localStorage.getItem('countymap_satellite_enabled');
        if (saved === 'true') {
          checkbox.checked = true;
          MapAdapter.toggleSatellite(true);
        }
      } catch (e) {}

      checkbox.addEventListener('change', (e) => {
        MapAdapter.toggleSatellite(e.target.checked);
        // Save state
        try {
          localStorage.setItem('countymap_satellite_enabled', e.target.checked ? 'true' : 'false');
        } catch (err) {}
      });
    }
  },

  /**
   * Clear map view settings (called by New Chat)
   */
  clearMapViewSettings() {
    try {
      localStorage.removeItem('countymap_globe_enabled');
      localStorage.removeItem('countymap_satellite_enabled');
    } catch (e) {}
    // Reset checkboxes
    const globeCheckbox = document.getElementById('globeCheckbox');
    const satCheckbox = document.getElementById('satCheckbox');
    if (globeCheckbox) {
      globeCheckbox.checked = false;
      MapAdapter.toggleGlobe(false);
    }
    if (satCheckbox) {
      satCheckbox.checked = false;
      MapAdapter.toggleSatellite(false);
    }
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
    // Note: Geometry overlays (ZCTA, tribal) use separate layers, so they can coexist
    // with the main choropleth display. No need to skip.
    try {
      console.log('Loading countries...');

      // Only reset time slider if NO active overlay needs it (OR gate logic)
      const activeOverlays = OverlaySelector?.getActiveOverlays() || [];
      const anyOverlayNeedsSlider = activeOverlays.some(id => {
        const config = OverlaySelector.getOverlayConfig(id);
        return config?.hasYearFilter === true;
      });

      if (!anyOverlayNeedsSlider) {
        TimeSlider.reset();
      }
      ChoroplethManager.reset();

      // Re-enable viewport loading (exit order mode)
      ViewportLoader.orderMode = false;

      // Add debug param if debug mode is on
      const url = this.debugMode
        ? `${CONFIG.api.countries}?debug=true`
        : CONFIG.api.countries;
      const result = await fetchMsgpack(url);

      if (result.geojson && result.geojson.features.length > 0) {
        this.currentData = {
          geojson: result.geojson,
          dataset_name: 'World Countries',
          source_name: 'Natural Earth'
        };

        NavigationManager.reset();
        MapAdapter.clearParentOutline();  // Clear parent outline at world level
        MapAdapter.clearCityOverlay();    // Clear city overlay
        MapAdapter.clearNavigationLayer(); // Clear navigation highlights
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
    const properties = this.getPopupProperties(feature);
    const popupHtml = PopupBuilder.build(properties, this.currentData);
    MapAdapter.showPopup([lngLat.lng, lngLat.lat], popupHtml);
  },

  getPopupProperties(feature) {
    const featureProps = feature?.properties || {};
    const locId = featureProps.loc_id;
    if (!locId || !this.currentData?.geojson?.features) {
      return featureProps;
    }

    const sourceFeature = this.currentData.geojson.features.find((candidate) => {
      const candidateLocId = candidate?.properties?.loc_id || candidate?.id;
      return candidateLocId === locId;
    });

    if (!sourceFeature?.properties) {
      return featureProps;
    }

    return {
      ...sourceFeature.properties,
      ...featureProps
    };
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
      const result = await fetchMsgpack(url);

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
  displayData(data, options = {}) {
    data = this.decorateMetricGeojsonWithAdminLevel(data);

    // Check if we should merge with existing data (same source, multi-year)
    const shouldMerge = this.currentData &&
      this.currentData.data_type === 'metrics' &&
      data.data_type === 'metrics' &&
      this.currentData.source_id === data.source_id;

    if (shouldMerge) {
      console.log(`Merging data: existing ${this.currentData.count} + new ${data.count} features`);
      data = this.mergeMetricData(this.currentData, data);
      console.log(`After merge: ${data.count} total features`);
    }

    this.currentData = data;

    // Suspend viewport loading when displaying order data
    // This prevents viewport API from overwriting our ordered data
    ViewportLoader.orderMode = true;

    // Clear any existing layers first
    MapAdapter.clearHurricaneLayer();
    MapAdapter.clearHurricaneTrack();
    MapAdapter.clearEventLayer();

    // Handle removal orders first (works for all data types)
    // Removal payloads are minimal - just identifiers, not full data
    if (data.action === 'remove') {
      console.log(`Removal order: ${data.data_type}, source: ${data.source_id}`);
      let result = { removed: 0, remaining: 0 };

      if (data.data_type === 'geometry') {
        // Geometry: remove by loc_ids
        let geometryType = data.geographic_level || 'zcta';
        if (data.source_id) {
          const match = data.source_id.match(/geometry_(\w+)/);
          if (match) geometryType = match[1];
        }
        result = OverlayController.removeGeometryData(
          data.source_id,
          { loc_ids: data.loc_ids, regions: data.regions },
          geometryType
        );
      } else if (data.data_type === 'events') {
        // Events: remove by event_ids
        result = OverlayController.removeEventData(
          data.source_id,
          { event_ids: data.event_ids, regions: data.regions }
        );
      } else if (data.data_type === 'metrics') {
        // Metrics: remove column (loc_ids + years + metric)
        result = OverlayController.removeMetricData(
          data.source_id,
          { loc_ids: data.loc_ids, years: data.years, metric: data.metric }
        );
      }

      // Trigger overlay refresh (same as add - turn on overlay, which refreshes from cache)
      if (data.data_type === 'geometry') {
        const geometryTypeToOverlayId = {
          'zcta': 'zip_codes',
          'tribal': 'tribal_areas',
          'watershed': 'watersheds',
          'park': 'parks'
        };
        let geometryType = data.geographic_level || 'zcta';
        if (data.source_id) {
          const match = data.source_id.match(/geometry_(\w+)/);
          if (match) geometryType = match[1];
        }
        const overlayId = geometryTypeToOverlayId[geometryType] || 'zip_codes';
        OverlayController.handleOverlayChange(overlayId, true);
      }

      // Update summary display
      const summaryEl = document.getElementById('queryStatus');
      if (summaryEl) {
        summaryEl.textContent = data.summary || `Removed ${result.removed} items (${result.remaining} remaining)`;
      }
      return;
    }

    if (data.data_type !== 'metrics') {
      this.activeMetricOrderContext = null;
      this.clearMetricPrefetch();
    }

    // Check if this is geometry overlay data (ZCTA, tribal, watersheds, etc.)
    if (data.data_type === 'geometry') {
      // Determine geometry type early
      let geometryType = 'geometry';
      if (data.source_id) {
        const match = data.source_id.match(/geometry_(\w+)/);
        if (match) geometryType = match[1];
      }
      if (geometryType === 'geometry' && data.geographic_level) {
        geometryType = data.geographic_level;
      }

      console.log(`Geometry overlay detected: ${data.source_id}, ${data.geojson?.features?.length || 0} features`);

      // Set geometry overlay flag - prevents loadCountries from overwriting
      App.geometryOverlayActive = true;
      ViewportLoader.orderMode = true;

      TimeSlider.reset();
      ChoroplethManager.reset();

      // Render geometry if we have features (geometryType already computed above)
      if (data.geojson && data.geojson.features && data.geojson.features.length > 0) {
        // Map geometryType to overlay ID
        const geometryTypeToOverlayId = {
          'zcta': 'zip_codes',
          'tribal': 'tribal_areas',
          'watershed': 'watersheds',
          'park': 'parks'
        };
        const overlayId = geometryTypeToOverlayId[geometryType] || 'zip_codes';

        // Store geometry data for OverlayController to render when overlay is enabled
        // This ensures render happens AFTER overlay is toggled ON
        OverlayController.pendingGeometry = {
          geojson: data.geojson,
          geometryType: geometryType,
          sourceId: data.source_id,
          options: { showLabels: false }
        };

        // Enable the overlay - handleOverlayChange will render from pendingGeometry
        // If already active, it will refresh the display
        if (OverlaySelector && !OverlaySelector.isActive(overlayId)) {
          OverlaySelector.setActive(overlayId, true);
        }
        // Always notify - if already on, this triggers a refresh
        OverlayController.handleOverlayChange(overlayId, true);

        console.log(`Geometry queued for render as type: ${geometryType}`);
      }

      // Update summary display
      const summaryEl = document.getElementById('queryStatus');
      if (summaryEl) {
        summaryEl.textContent = data.summary || `${data.geojson?.features?.length || 0} areas`;
      }

      return;
    }

    // Check if this is event mode data (earthquakes, volcanoes, etc.)
    if (data.type === 'events') {
      console.log(`Event data detected: ${data.event_type}, ${data.count} events`);

      TimeSlider.reset();
      ChoroplethManager.reset();

      // Load event layer with appropriate styling
      MapAdapter.loadEventLayer(data.geojson, data.event_type, {
        showFeltRadius: true,
        showDamageRadius: true,
        onEventClick: (props) => {
          console.log('Event clicked:', props);
          // Show detailed popup on click
          const html = MapAdapter._buildEventPopupHtml(props, data.event_type);
          MapAdapter.popup.setHTML(html);
          MapAdapter.popupLocked = true;
        }
      });

      // Fit map to event locations
      MapAdapter.fitToEventBounds(data.geojson);

      // Update summary display
      const summaryEl = document.getElementById('queryStatus');
      if (summaryEl) {
        summaryEl.textContent = data.summary || `${data.count} ${data.event_type} events`;
      }

      return;
    }

    // Check if this is hurricane/storm point data
    const isHurricaneData = data.source_id === 'ibtracs' ||
      data.dataset_name?.toLowerCase().includes('hurricane') ||
      data.dataset_name?.toLowerCase().includes('storm') ||
      data.metric_key === 'storm_count' ||
      (data.geojson?.features?.[0]?.properties?.storm_id);

    if (isHurricaneData && data.geojson?.features?.[0]?.geometry?.type === 'Point') {
      // Hurricane point data - use special hurricane layer with click drill-down
      console.log('Hurricane data detected, using hurricane layer');

      TimeSlider.reset();
      ChoroplethManager.reset();

      // Load hurricane markers with drill-down click handler
      MapAdapter.loadHurricaneLayer(data.geojson, (stormId, stormName) => {
        console.log(`Storm clicked: ${stormId} - ${stormName}`);
        HurricaneHandler.drillDown(stormId, stormName);
      });

      // Fit map to storm locations
      MapAdapter.fitToBounds(data.geojson);

    } else if (data.multi_year && data.year_data && data.year_range) {
      // Multi-year mode: initialize time slider
      console.log('Multi-year data detected, initializing time slider');
      console.log(`Year range: ${data.year_range.min} - ${data.year_range.max}`);
      console.log('DEBUG app.js: metric_year_ranges from response:', data.metric_year_ranges);

      // Auto-enable demographics overlay for demographic data from chat orders
      // This ensures viewport-based admin level filtering works
      const OverlaySelector = window.OverlaySelector;
      if (OverlaySelector && !OverlaySelector.isActive('demographics')) {
        console.log('Auto-enabling demographics overlay for chat order data');
        OverlaySelector.setActive('demographics', true);
      }

      // Hide any existing slider/legend first
      if (!options.lazyLoad) {
        TimeSlider.reset();
        ChoroplethManager.reset();

        // Initialize time slider with the data
        TimeSlider.init(
          data.year_range,
          data.year_data,
          data.geojson,
          data.metric_key,
          data.available_metrics,  // Explicit list of metrics from order
          data.metric_year_ranges  // Per-metric year ranges for slider adjustment
        );

        // Fit map to the data, then apply initial admin level filter
        MapAdapter.fitToBounds(data.geojson);
      } else {
        TimeSlider.updateData(
          data.year_range,
          data.year_data,
          data.geojson,
          data.available_metrics,
          data.metric_year_ranges
        );
      }

      const explicitLevelMatch = String(data.geographic_level || '').match(/^admin_(\d+)$/);
      const loadedAdminLevel = explicitLevelMatch ? parseInt(explicitLevelMatch[1], 10) : null;

      // Set initial admin level filter based on viewport after fit completes
      // Use setTimeout to let fitToBounds animation complete
      setTimeout(() => {
        const bounds = MapAdapter.map?.getBounds();
        if (bounds) {
          const viewportLevel = ViewportLoader.getAdminLevelForViewport(bounds);
          const displayLevel = loadedAdminLevel !== null && viewportLevel > loadedAdminLevel
            ? loadedAdminLevel
            : viewportLevel;
          ViewportLoader.holdOrderModeLevel?.(displayLevel, 1400);
          TimeSlider.setAdminLevelFilter(displayLevel);
        }
      }, 100);

    } else {
      // Single-year mode: hide time slider, display normally
      TimeSlider.reset();
      ChoroplethManager.reset();

      if (data.geojson && data.geojson.type === 'FeatureCollection') {
        const filteredGeojson = this.filterGeojsonByAdminLevel(data.geojson, ViewportLoader.currentAdminLevel);
        if (options.lazyLoad) {
          MapAdapter.updateSourceData(filteredGeojson);
        } else {
          MapAdapter.loadGeoJSON(filteredGeojson);
          MapAdapter.fitToBounds(data.geojson);
          const explicitLevelMatch = String(data.geographic_level || '').match(/^admin_(\d+)$/);
          const loadedAdminLevel = explicitLevelMatch ? parseInt(explicitLevelMatch[1], 10) : ViewportLoader.currentAdminLevel;
          ViewportLoader.holdOrderModeLevel?.(loadedAdminLevel, 1400);
        }

        if (data.data_type === 'metrics' && OverlaySelector && !OverlaySelector.isActive('demographics')) {
          console.log('Auto-enabling demographics overlay for chat order data');
          OverlaySelector.setActive('demographics', true);
        }
      }
    }

    if (data.data_type === 'metrics' && options.order) {
      this.setMetricOrderContext(options.order, data);
    }

    // Collapse sidebar on mobile
    if (window.innerWidth < 500) {
      ChatManager.elements.sidebar.classList.add('collapsed');
      ChatManager.elements.toggle.style.display = 'flex';
    }
  },

  /**
   * Display navigation locations as highlighted overlay
   * Used when user says "show me X" without requesting data
   * @param {Object} geojson - GeoJSON with location geometries
   * @param {Array} locations - Location metadata array
   */
  displayNavigationLocations(geojson, locations) {
    if (!geojson || !geojson.features || geojson.features.length === 0) {
      console.warn('No features to display for navigation');
      return;
    }

    console.log(`Displaying ${geojson.features.length} navigation locations`);

    // Suspend viewport loading while showing navigation locations
    ViewportLoader.orderMode = true;

    // Reset any previous data display state
    TimeSlider.reset();
    ChoroplethManager.reset();

    // Load the navigation locations using selection layer (orange/amber highlighting)
    // This uses the same layer as disambiguation but for a different purpose
    MapAdapter.loadNavigationLayer(geojson);

    // Store reference for popups (minimal data, just location info)
    this.currentData = {
      geojson: geojson,
      dataset_name: 'Navigation',
      source_name: 'Location View',
      isNavigation: true
    };

    // Store locations for click handling
    this.navigationLocations = locations;

    // Set up click handler for navigation layer selection
    this.setupNavigationClickHandler();
  },

  /**
   * Set up click handler for navigation layer
   * Allows user to select one location from multiple candidates
   */
  setupNavigationClickHandler() {
    if (!MapAdapter?.map) return;

    // Remove any existing handler
    if (this._navigationClickHandler) {
      MapAdapter.map.off('click', CONFIG.layers.selectionFill, this._navigationClickHandler);
    }

    // Create click handler
    this._navigationClickHandler = (e) => {
      if (!e.features || e.features.length === 0) return;

      const feature = e.features[0];
      const locId = feature.properties?.loc_id;

      // Find matching location from stored locations
      const location = this.navigationLocations?.find(loc => loc.loc_id === locId);

      if (location) {
        this.handleNavigationSelection(location, feature);
      }
    };

    // Add click handler
    MapAdapter.map.on('click', CONFIG.layers.selectionFill, this._navigationClickHandler);

    // Change cursor on hover
    MapAdapter.map.on('mouseenter', CONFIG.layers.selectionFill, () => {
      MapAdapter.map.getCanvas().style.cursor = 'pointer';
    });
    MapAdapter.map.on('mouseleave', CONFIG.layers.selectionFill, () => {
      MapAdapter.map.getCanvas().style.cursor = '';
    });
  },

  /**
   * Handle selection of a location in navigation mode
   * @param {Object} location - The selected location object
   * @param {Object} feature - The GeoJSON feature that was clicked
   */
  handleNavigationSelection(location, feature) {
    const name = location.matched_term || location.loc_id;
    const country = location.country_name || location.iso3 || '';

    console.log(`Navigation selection: ${name} (${country})`);

    // Add message to chat
    const displayName = country ? `${name} (${country})` : name;
    ChatManager.addMessage(`Selected: ${displayName}. What data would you like to see for this location?`, 'assistant');

    // Update order panel to show just this location
    OrderManager.setNavigationLocations([location]);

    // Clear the navigation layer and show just the selected location
    MapAdapter.clearNavigationLayer();

    // Reload with just the selected feature
    const selectedGeojson = {
      type: 'FeatureCollection',
      features: [feature]
    };
    MapAdapter.loadNavigationLayer(selectedGeojson);

    // Clean up - only keep selected location
    this.navigationLocations = [location];

    // Remove click handler (no longer needed after selection)
    if (this._navigationClickHandler) {
      MapAdapter.map.off('click', CONFIG.layers.selectionFill, this._navigationClickHandler);
      this._navigationClickHandler = null;
    }
  },

  /**
   * Clear navigation mode and return to normal map state
   */
  clearNavigationMode() {
    MapAdapter.clearNavigationLayer();
    this.navigationLocations = null;
    this.activeMetricOrderContext = null;
    this.clearMetricPrefetch();

    if (this._navigationClickHandler && MapAdapter?.map) {
      MapAdapter.map.off('click', CONFIG.layers.selectionFill, this._navigationClickHandler);
      this._navigationClickHandler = null;
    }

    // Clear geometry overlay layers (zcta, tribal, etc.) if active
    if (this.geometryOverlayActive) {
      // Clear all geometry layers via GeometryModel
      GeometryModel.clear();
    }

    // Clear geometry overlay flag and re-enable viewport loading
    this.geometryOverlayActive = false;
    ViewportLoader.orderMode = false;
  }
};

// ============================================================================
// INITIALIZATION
// ============================================================================

// Start the app when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    App.init();
  }, { once: true });
} else {
  App.init();
}

// Export for global access if needed
if (typeof window !== 'undefined') {
  window.App = App;
  window.OverlayController = OverlayController;  // For debugging: OverlayController.getCacheStats()
  window.TimeSlider = TimeSlider;  // For settings to update live timezone
}
