/**
 * App - Main application controller.
 * Orchestrates all modules and handles initialization.
 */

import { CONFIG } from './config.js';
import { GeometryCache, LocationInfoCache } from './cache.js';
import { cancelActiveRequests, fetchMsgpack, postMsgpack } from './utils/fetch.js';
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
import { RasterPanel } from './raster-panel.js';
import { setDependencies as setSceneRasterDeps } from './scene-raster-model.js';
import { loadPublicPackCatalog } from './shared/catalog-cache.js';
import { restoreChatState } from './chat/session.js';

const CHAT_MAP_LANES = ['explore', 'research', 'ops'];
const DISPLAY_GEOMETRY_TYPES = new Set(['zcta', 'tribal', 'watershed', 'park']);
const DISPLAY_SOURCE_EVENT_TYPE_HINTS = [
  ['earthquakes', 'earthquake'],
  ['earthquake', 'earthquake'],
  ['usgs', 'earthquake'],
  ['hurricanes', 'hurricane'],
  ['hurricane', 'hurricane'],
  ['storm', 'hurricane'],
  ['ibtracs', 'hurricane'],
  ['volcano', 'volcano'],
  ['eruption', 'volcano'],
  ['wildfire', 'wildfire'],
  ['fire', 'wildfire'],
  ['tsunami', 'tsunami'],
  ['tornado', 'tornado'],
  ['flood', 'flood'],
  ['drought', 'drought'],
  ['landslide', 'landslide']
];

function getStartupChatMode() {
  const restored = restoreChatState();
  const mode = String(restored?.activeMode || '').trim().toLowerCase();
  return CHAT_MAP_LANES.includes(mode) ? mode : 'explore';
}

function normalizeChatMapLane(lane) {
  return CHAT_MAP_LANES.includes(lane) ? lane : 'explore';
}

function cloneSerializable(value) {
  if (value == null) return value;
  if (typeof structuredClone === 'function') {
    try {
      return structuredClone(value);
    } catch (e) {}
  }
  try {
    return JSON.parse(JSON.stringify(value));
  } catch (e) {
    return value;
  }
}

// ============================================================================
// APP - Main application controller
// ============================================================================

export const App = {
  currentData: null,
  currentCanvasMode: 'explore',
  debugMode: false,  // Toggle with 'D' key - shows hierarchy depth colors
  geometryOverlayActive: false,  // True when geometry overlay (ZCTA, tribal, etc.) is displayed
  mobileNoticeMql: null,
  activeMetricOrderContext: null,
  metricPrefetchHandle: null,
  pendingCanvasMode: null,
  _researchDisplayClickHandler: null,
  _researchDisplayHoverHandler: null,
  _researchDisplayLeaveHandler: null,
  _popupTimeChangeListener: null,
  publicPackCatalog: [],
  publicPackCatalogLoadedAt: 0,
  publicPackCatalogSource: '',
  mapViews: new Map(),
  uiFullscreen: false,
  laneMapBindings: {
    explore: 'view-explore-primary',
    research: 'view-research-workspace',
    ops: 'view-ops-watch'
  },
  activeMapViewId: null,
  activeMapLane: 'explore',

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
          if (this.activeMetricOrderContext?.sourceId === context.sourceId) {
            this.activeMetricOrderContext.loadedLevels.add(level);
          }
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
          // Mark the level as loaded before ingest/display rebuilds the order
          // context, otherwise empty/partial lazy responses can keep scheduling
          // the same admin level again.
          context.loadedLevels.add(level);
          if (this.activeMetricOrderContext?.sourceId === context.sourceId) {
            this.activeMetricOrderContext.loadedLevels.add(level);
          }
          this.ingestLazyMetricData(response, nextOrder, {
            schedulePrefetch: !options.prefetch
          });
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

    this.displayMapPayload(data, { order, lazyLoad: true });
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
    setSceneRasterDeps({ MapAdapter });

    await AuthManager.init();
    Promise.resolve(this.preloadPublicPackCatalog()).catch((error) => {
      console.warn('Could not warm public pack catalog during app startup:', error);
    });
    this.setupMobileExperienceNotice();
    this.initializeMapViews();
    this.setupFullscreenToggle();
    this.setupLoadingIndicatorControls();

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
    if (!this._popupTimeChangeListener) {
      this._popupTimeChangeListener = () => {
        MapAdapter.refreshLockedPopup?.();
      };
      TimeSlider.addChangeListener(this._popupTimeChangeListener);
    }

    const startupMode = getStartupChatMode();
    const researchStartup = startupMode === 'research';
    await OverlaySelector.init({ restoreState: !researchStartup });
    OverlayController.init({ enableExploreRuntime: !researchStartup });

    // Initialize map
    await MapAdapter.init();

    this.activateLaneMapView(startupMode, { force: true });
    if (startupMode === 'research') {
      Promise.resolve(ChatManager.refreshResearchCorpusOptions?.()).catch((error) => {
        console.warn('Could not refresh Research corpus options after map init:', error);
      });
      Promise.resolve(ChatManager.refreshResearchManifest?.()).catch((error) => {
        console.warn('Could not refresh Research manifest after map init:', error);
      });
    }

    // Replay any overlays that were restored from localStorage before the map was ready.
    // OverlaySelector.init() restores saved state before MapAdapter.init() runs, so any
    // active overlays fire into a map that doesn't exist yet. Re-trigger them now.
    if (!researchStartup) {
      for (const overlayId of OverlaySelector.activeOverlays) {
        OverlayController.handleOverlayChange(overlayId, true);
      }
    }

    // Shift the map's logical center to account for the sidebar width.
    // The map container covers the full viewport but the sidebar overlays it on the left,
    // so without padding the "center" is visually offset. MapLibre's padding option
    // moves the optical center so features like flyTo and fitBounds land in the visible area.
    const sidebarEl = document.getElementById('sidebar');
    this.applySidebarPadding();
    new MutationObserver(() => this.applySidebarPadding()).observe(sidebarEl, {
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
    if (!researchStartup && OverlaySelector.getActiveOverlays().includes('demographics')) {
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

  ensureMapView(viewId, seedState = {}) {
    const id = String(viewId || '').trim();
    if (!id) return null;
    const existing = this.mapViews.get(id);
    if (existing) {
      existing.state = {
        ...existing.state,
        ...cloneSerializable(seedState)
      };
      return existing;
    }
    const view = {
      id,
      state: {
        canvasMode: 'explore',
        camera: null,
        ...cloneSerializable(seedState)
      }
    };
    this.mapViews.set(id, view);
    return view;
  },

  initializeMapViews() {
    this.ensureMapView('view-explore-primary', { canvasMode: 'explore' });
    this.ensureMapView('view-research-workspace', { canvasMode: 'research' });
    this.ensureMapView('view-ops-watch', { canvasMode: 'ops' });
  },

  listMapViews() {
    return Array.from(this.mapViews.values()).map((view) => ({
      id: view.id,
      state: cloneSerializable(view.state)
    }));
  },

  getLaneMapBinding(lane) {
    return this.laneMapBindings[normalizeChatMapLane(lane)] || this.laneMapBindings.explore;
  },

  bindLaneToMapView(lane, viewId, options = {}) {
    const normalizedLane = normalizeChatMapLane(lane);
    const resolvedViewId = String(viewId || '').trim();
    if (!resolvedViewId) return null;
    this.ensureMapView(resolvedViewId, {
      canvasMode: normalizedLane === 'research' ? 'research' : normalizedLane === 'ops' ? 'ops' : 'explore'
    });
    this.laneMapBindings[normalizedLane] = resolvedViewId;
    if (options.activate && ChatManager?.mode === normalizedLane) {
      this.activateLaneMapView(normalizedLane, { force: true });
    }
    return resolvedViewId;
  },

  configureLaneMapBindings(bindings = {}, options = {}) {
    for (const lane of CHAT_MAP_LANES) {
      if (!bindings[lane]) continue;
      this.bindLaneToMapView(lane, bindings[lane], { activate: false });
    }
    if (options.activateCurrent !== false && ChatManager?.mode) {
      this.activateLaneMapView(ChatManager.mode, { force: true });
    }
  },

  captureCurrentMapViewState() {
    const camera = MapAdapter?.map
      ? (() => {
          const view = MapAdapter.getView?.();
          if (!view?.center) return null;
          return {
            center: {
              lng: Number(view.center.lng),
              lat: Number(view.center.lat)
            },
            zoom: Number(view.zoom)
          };
        })()
      : null;

    return {
      canvasMode: this.currentCanvasMode || normalizeChatMapLane(this.pendingCanvasMode),
      camera,
      surfaceState: this.captureCurrentSurfaceState()
    };
  },

  captureTimeSliderState() {
    if (!TimeSlider) return null;
    const isVisible = Boolean(TimeSlider.container?.classList?.contains('visible'));
    if (TimeSlider.currentTime == null && !isVisible) return null;
    return {
      visible: isVisible,
      currentTime: TimeSlider.currentTime,
      boundMinTime: TimeSlider.boundMinTime,
      boundMaxTime: TimeSlider.boundMaxTime,
      speedSliderValue: TimeSlider.speedSliderValue,
      activeScaleId: TimeSlider.activeScaleId || null,
      isLiveMode: Boolean(TimeSlider.isLiveMode),
      isLiveLocked: Boolean(TimeSlider.isLiveLocked)
    };
  },

  applyTimeSliderState(timeSliderState = null) {
    if (!timeSliderState || !TimeSlider) return;
    if (typeof timeSliderState.speedSliderValue === 'number' && TimeSlider.setSpeedFromSlider) {
      TimeSlider.setSpeedFromSlider(timeSliderState.speedSliderValue);
      if (TimeSlider.speedSlider) {
        TimeSlider.speedSlider.value = String(timeSliderState.speedSliderValue);
      }
    }
    if (timeSliderState.boundMinTime != null || timeSliderState.boundMaxTime != null) {
      TimeSlider.setTrimBounds?.(timeSliderState.boundMinTime ?? null, timeSliderState.boundMaxTime ?? null);
    } else {
      TimeSlider.resetTrimBounds?.();
    }
    if (timeSliderState.activeScaleId && TimeSlider.activeScaleId !== timeSliderState.activeScaleId) {
      TimeSlider.setActiveScale?.(timeSliderState.activeScaleId);
    }
    if (timeSliderState.currentTime != null) {
      TimeSlider.setTime?.(timeSliderState.currentTime, 'api');
    }
    if (timeSliderState.visible) {
      TimeSlider.show?.();
      TimeSlider.refreshDisplay?.();
    } else {
      TimeSlider.hide?.();
    }
  },

  captureCurrentSurfaceState() {
    const surfaceState = {};

    if (this.currentCanvasMode === 'explore') {
      if (this.currentData && (this.currentData.data_type || this.currentData.type || this.currentData.geojson?.features?.length)) {
        surfaceState.dataPayload = cloneSerializable(this.currentData);
      }
      const timeSliderState = this.captureTimeSliderState();
      if (timeSliderState) {
        surfaceState.timeSlider = timeSliderState;
      }
    }

    const rasterState = RasterPanel.getState?.();
    if (rasterState?.source_id || rasterState?.visible) {
      if (rasterState.clip_mode === 'selection') {
        rasterState.loc_ids = Array.isArray(this.currentResearchDisplay?.loc_ids)
          ? [...this.currentResearchDisplay.loc_ids]
          : [];
      }
      surfaceState.raster = rasterState;
    }

    return Object.keys(surfaceState).length ? surfaceState : null;
  },

  restoreSurfaceState(surfaceState = null, options = {}) {
    const lane = normalizeChatMapLane(options.lane);
    const restored = surfaceState && typeof surfaceState === 'object' ? surfaceState : {};

    RasterPanel.hide?.();
    if (lane !== 'explore') {
      TimeSlider.hide?.();
    }

    if (lane === 'explore') {
      const dataPayload = restored.dataPayload && typeof restored.dataPayload === 'object'
        ? cloneSerializable(restored.dataPayload)
        : null;
      if (dataPayload) {
        this.renderStandardDataPayload(dataPayload, { restoringViewState: true });
      }
      if (restored.timeSlider) {
        this.applyTimeSliderState(restored.timeSlider);
      } else if (!dataPayload) {
        TimeSlider.show?.();
      }
      if (!dataPayload && restored.timeSlider && OverlayController?.rerenderFromCache) {
        OverlayController.rerenderFromCache();
      }
    }

    if (restored.raster?.visible) {
      const rasterState = { ...restored.raster };
      if (rasterState.clip_mode === 'selection' && Array.isArray(rasterState.loc_ids) && rasterState.loc_ids.length) {
        RasterPanel.showSelectionClips?.(rasterState);
      } else {
        RasterPanel.showScene?.(rasterState);
      }
    }
  },

  clearVisibleMapSurface(options = {}) {
    const preserveOverlayState = options.preserveOverlayState !== false;

    if (preserveOverlayState && OverlaySelector?.getActiveOverlays && OverlayController?.hideOverlay) {
      const activeOverlays = OverlaySelector.getActiveOverlays() || [];
      for (const overlayId of activeOverlays) {
        if (!overlayId || overlayId === 'demographics') continue;
        try {
          OverlayController.hideOverlay(overlayId);
        } catch (error) {
          console.warn(`Could not hide overlay during lane switch: ${overlayId}`, error);
        }
      }
    }

    TimeSlider.hide?.();
    RasterPanel.hide?.();
    ChoroplethManager.reset?.();
    MapAdapter.setChoroplethVisible?.(false);
    MapAdapter.cleanup?.();
    this.clearResearchDisplayInteractions();
    this.navigationLocations = null;
    this.currentData = null;
    this.currentResearchDisplay = null;
    this.currentResearchLayerOptions = null;
  },

  saveActiveMapViewState() {
    if (!this.activeMapViewId) return;
    const view = this.ensureMapView(this.activeMapViewId);
    if (!view) return;
    view.state = this.captureCurrentMapViewState();
  },

  applyCanvasMode(mode) {
    const normalizedMode = normalizeChatMapLane(mode);
    if (normalizedMode === 'research') {
      this.enterResearchCanvasMode();
      return;
    }
    if (normalizedMode === 'ops') {
      this.enterOpsCanvasMode();
      return;
    }
    this.leaveResearchCanvasMode();
    this.leaveOpsCanvasMode();
  },

  applyMapViewState(mapViewState = {}, options = {}) {
    const state = cloneSerializable(mapViewState) || {};
    this.applyCanvasMode(state.canvasMode || 'explore');

    if (options.lane === 'research') {
      const laneDisplay = ChatManager?.getResearchDisplayForMode?.('research');
      if (laneDisplay) {
        const display = {
          ...laneDisplay,
          fit: false
        };
        this.displayMapPayload({ display }, { origin: 'research' });
      }
    }

    if (state.camera && MapAdapter?.map) {
      MapAdapter.map.jumpTo({
        center: [state.camera.center.lng, state.camera.center.lat],
        zoom: state.camera.zoom
      });
    }

    if (options.lane === 'research' && !state.surfaceState?.raster) {
      RasterPanel.hide?.();
    }
    this.restoreSurfaceState(state.surfaceState, options);
  },

  activateLaneMapView(lane, options = {}) {
    const normalizedLane = normalizeChatMapLane(lane);
    if (normalizedLane !== 'research') {
      OverlayController.enableExploreRuntime?.();
    }
    const targetViewId = this.getLaneMapBinding(normalizedLane);
    const targetView = this.ensureMapView(targetViewId, {
      canvasMode: normalizedLane === 'research' ? 'research' : normalizedLane === 'ops' ? 'ops' : 'explore'
    });

    if (!MapAdapter?.map) {
      this.pendingCanvasMode = targetView?.state?.canvasMode || normalizedLane;
      this.activeMapViewId = targetViewId;
      this.activeMapLane = normalizedLane;
      return targetViewId;
    }

    if (this.activeMapViewId && this.activeMapViewId !== targetViewId) {
      this.saveActiveMapViewState();
    } else if (
      this.activeMapViewId === targetViewId &&
      this.activeMapLane === normalizedLane &&
      options.force !== true
    ) {
      return targetViewId;
    }

    this.activeMapViewId = targetViewId;
    this.activeMapLane = normalizedLane;
    this.clearVisibleMapSurface({ preserveOverlayState: true });
    this.applyMapViewState(targetView.state, { lane: normalizedLane });
    return targetViewId;
  },

  buildResearchDisplayMemory(display = null) {
    if (!display) {
      return null;
    }
    const locIds = Array.isArray(display.loc_ids)
      ? display.loc_ids.map(locId => String(locId || '').trim()).filter(Boolean)
      : [];
    const memory = {
      source_id: display.source_id || null,
      action: display.action || null,
      loc_id_count: locIds.length,
      loc_ids: locIds.slice(0, 50),
      feature_count: Array.isArray(display?.geojson?.features) ? display.geojson.features.length : 0,
      context_visibility: display.context_visibility || null,
      style: display?.style ? cloneSerializable(display.style) : null,
    };
    const buildingLegend = this.buildResearchBuildingLegend(display);
    if (buildingLegend) {
      memory.building_legend = buildingLegend;
    }
    return memory;
  },

  buildResearchBuildingLegend(display = null) {
    if (String(display?.source_id || '').trim() !== 'fairfax_buildings') {
      return null;
    }
    const {
      defaultTypeColors,
      defaultFallbackColor,
      typeLabels
    } = this.getResearchBuildingTypeMetadata();
    const overrideColors = display?.style?.buildingTypeColors || {};
    return {
      source_id: display?.source_id || 'fairfax_buildings',
      typeColors: { ...defaultTypeColors, ...overrideColors },
      defaultColor: defaultFallbackColor,
      typeLabels: { ...typeLabels },
      locIdCount: Array.isArray(display?.loc_ids) ? display.loc_ids.length : 0,
      featureCount: Array.isArray(display?.geojson?.features) ? display.geojson.features.length : 0
    };
  },

  getCurrentResearchDisplayMemory() {
    return this.buildResearchDisplayMemory(this.currentResearchDisplay);
  },

  getCurrentResearchBuildingLegend() {
    return this.buildResearchBuildingLegend(this.currentResearchDisplay);
  },

  getCurrentResearchDisplayLayers() {
    return ChatManager?.getResearchDisplayLayersForMode?.('research') || [];
  },

  updateResearchDisplayStyle(styleUpdates = {}) {
    const currentLayers = this.getCurrentResearchDisplayLayers();
    if (!currentLayers.length) {
      return false;
    }
    const currentDisplay = currentLayers[currentLayers.length - 1];
    if (!currentDisplay?.geojson?.features?.length) return false;
    const mergedDisplay = {
      ...currentDisplay,
      style: {
        ...(currentDisplay.style || {}),
        ...styleUpdates,
        buildingTypeColors: {
          ...((currentDisplay.style || {}).buildingTypeColors || {}),
          ...((styleUpdates || {}).buildingTypeColors || {})
        }
      }
    };
    const nextLayers = [...currentLayers.slice(0, -1), mergedDisplay];
    this.currentResearchDisplay = mergedDisplay;
    ChatManager?.setResearchDisplayLayersForMode?.('research', nextLayers);
    this.currentResearchLayerOptions = this.getResearchLayerOptions(mergedDisplay);
    this.renderResearchDisplayLayers(nextLayers);
    this.setupResearchDisplayInteractions();
    return true;
  },

  applySidebarPadding() {
    if (!MapAdapter?.map) return;
    // Keep the geographic focal point anchored to the true screen center.
    // The sidebar overlays the map rather than redefining the map's logical center.
    MapAdapter.map.easeTo({
      padding: { top: 0, right: 0, bottom: 0, left: 0 },
      duration: 0
    });
  },

  setUiFullscreen(enabled) {
    this.uiFullscreen = Boolean(enabled);
    document.body.classList.toggle('map-ui-fullscreen', this.uiFullscreen);
    const btn = document.getElementById('fullscreenUiToggle');
    if (btn) {
      btn.textContent = this.uiFullscreen ? 'Exit Fullscreen' : 'Fullscreen';
      btn.setAttribute('aria-pressed', this.uiFullscreen ? 'true' : 'false');
      btn.title = this.uiFullscreen ? 'Show chat and map controls' : 'Hide chat and map controls';
    }
    this.applySidebarPadding();
  },

  setupFullscreenToggle() {
    const btn = document.getElementById('fullscreenUiToggle');
    if (!btn) return;
    btn.addEventListener('click', () => {
      this.setUiFullscreen(!this.uiFullscreen);
    });
    this.setUiFullscreen(false);
  },

  setupLoadingIndicatorControls() {
    const btn = document.getElementById('cancelLoadingButton');
    if (!btn) return;
    btn.addEventListener('click', () => {
      cancelActiveRequests();
      ViewportLoader.abortController?.abort?.();
      for (const controller of OverlayController?.abortControllers?.values?.() || []) {
        controller.abort();
      }
    });
  },

  async preloadPublicPackCatalog({ forceRefresh = false } = {}) {
    try {
      const result = await loadPublicPackCatalog({ forceRefresh });
      this.publicPackCatalog = Array.isArray(result?.packs) ? result.packs : [];
      this.publicPackCatalogLoadedAt = Date.now();
      this.publicPackCatalogSource = result?.source || '';
      window.dispatchEvent(new CustomEvent('daedalmap:public-pack-catalog-loaded', {
        detail: {
          count: this.publicPackCatalog.length,
          source: this.publicPackCatalogSource,
          loadedAt: this.publicPackCatalogLoadedAt
        }
      }));
      return this.publicPackCatalog;
    } catch (error) {
      console.warn('Could not preload public pack catalog for app surface:', error);
      return this.publicPackCatalog;
    }
  },

  getPublicPackCatalog() {
    return Array.isArray(this.publicPackCatalog) ? this.publicPackCatalog : [];
  },

  getPublicPackCatalogEntry(packId) {
    const normalizedPackId = String(packId || '').trim();
    if (!normalizedPackId) return null;
    return this.getPublicPackCatalog().find((pack) => pack && pack.pack_id === normalizedPackId) || null;
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
    if (ChatManager?.mode === 'research') {
      return;
    }
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
   * Shared map display entry point for all chat lanes.
   * Reuses Explore's mature display path whenever the payload can be
   * expressed as a standard order/event/geometry result, and falls back
   * to Research-style subset highlighting for display-only selections.
   */
  displayMapPayload(payload, options = {}) {
    if (!payload || typeof payload !== 'object') return;
    this.renderStandardDataPayload(payload, options);
  },

  clearOpsDirectDisplayState(options = {}) {
    const resetMetrics = options.resetMetrics !== false;
    MapAdapter.clearHurricaneLayer?.();
    MapAdapter.clearHurricaneTrack?.();
    MapAdapter.clearEventLayer?.();
    MapAdapter.clearNavigationLayer?.();
    MapAdapter.clearResearchDisplayLayers?.();
    this.clearResearchDisplayInteractions?.();
    if (resetMetrics) {
      TimeSlider.reset?.();
      ChoroplethManager.reset?.();
      this.currentData = null;
      this.activeMetricOrderContext = null;
      this.clearMetricPrefetch?.();
    }
  },

  renderResearchDisplayLayers(displays = []) {
    const validDisplays = (displays || []).filter(display => display?.geojson?.features?.length);
    MapAdapter.clearParentOutline?.();
    MapAdapter.clearNavigationLayer?.();
    if (!validDisplays.length) {
      MapAdapter.clearResearchDisplayLayers?.();
      return;
    }
    const layers = validDisplays.map((display, index) => ({
      id: `research-${index}`,
      geojson: display.geojson,
      options: this.getResearchLayerOptions(display),
      label: display?.label || display?.title || display?.source_id || `Research layer ${index + 1}`
    }));
    MapAdapter.loadResearchDisplayLayers?.(layers);
  },

  renderStandardDataPayload(data, options = {}) {
    data = this.decorateMetricGeojsonWithAdminLevel(data);

    // When restoring a saved view (lane switch), the camera was already restored
    // via jumpTo in applyMapViewState. Skip all fit calls so the camera stays
    // exactly where the user left it, instead of being overridden by a fresh
    // bbox of whatever data layer is being re-rendered.
    const skipFit = options.restoringViewState === true;

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

    if (!options.preserveExistingRuntimeLayers) {
      // Clear any existing layers first
      MapAdapter.clearHurricaneLayer();
      MapAdapter.clearHurricaneTrack();
      MapAdapter.clearEventLayer();
      // The corpus-load focus overlay (e.g. the USA outline drawn when a Research
      // corpus is first activated) is a navigation layer. Any new data payload
      // supersedes that focus context, so clear it before rendering.
      MapAdapter.clearNavigationLayer?.();
    }

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
        // Map geometryType to known overlay ID. Only the geometry types with a
        // dedicated overlay control go through OverlayController; everything
        // else (attribute-overlay datasets like usa_opportunity_zones, ad-hoc
        // tract highlights) renders directly via the shared ad-hoc geometry
        // layer renderer so hover/click/popup work without requiring a
        // registered overlay slot. See MAPPING.md "Queryable Geometry Overlays".
        const geometryTypeToOverlayId = {
          'zcta': 'zip_codes',
          'tribal': 'tribal_areas',
          'watershed': 'watersheds',
          'park': 'parks'
        };
        const knownOverlayId = geometryTypeToOverlayId[geometryType];

        if (knownOverlayId) {
          OverlayController.pendingGeometry = {
            geojson: data.geojson,
            geometryType: geometryType,
            sourceId: data.source_id,
            options: { showLabels: false }
          };
          if (OverlaySelector && !OverlaySelector.isActive(knownOverlayId)) {
            OverlaySelector.setActive(knownOverlayId, true);
          }
          OverlayController.handleOverlayChange(knownOverlayId, true);
          console.log(`Geometry queued for render as type: ${geometryType}`);
        } else {
          // Ad-hoc geometry overlay (OZ tracts, designation lists, etc.):
          // render directly with hover/click/popup. Same layer system that
          // serves Research analytical layers today; not lane-specific.
          const layer = {
            id: `geometry-${data.source_id || geometryType}`,
            geojson: data.geojson,
            options: {},
            label: data.source_id || geometryType || 'Geometry layer'
          };
          MapAdapter.loadResearchDisplayLayers?.([layer]);
          this.setupResearchDisplayInteractions?.();
          if (data.fit !== false && !skipFit) {
            MapAdapter.fitToBounds(data.geojson);
          }
          console.log(`Ad-hoc geometry rendered: source=${data.source_id} level=${geometryType} features=${data.geojson.features.length}`);
        }
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
          // Route event clicks through the shared disaster popup system.
          const coords = props?.lon != null && props?.lat != null
            ? [Number(props.lon), Number(props.lat)]
            : props?.longitude != null && props?.latitude != null
              ? [Number(props.longitude), Number(props.latitude)]
              : props?.lng != null && props?.lat != null
                ? [Number(props.lng), Number(props.lat)]
                : null;
          if (coords && Number.isFinite(coords[0]) && Number.isFinite(coords[1])) {
            DisasterPopup.show(coords, props, data.event_type);
          }
        }
      });

      // Fit map to event locations
      if (!skipFit) MapAdapter.fitToEventBounds(data.geojson);

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

    if (isHurricaneData && data.geojson?.features?.length) {
      // Hurricane point or track data - use shared hurricane layer path
      console.log('Hurricane data detected, using hurricane layer');

      TimeSlider.reset();
      ChoroplethManager.reset();

      // Load hurricane markers with drill-down click handler
      MapAdapter.loadHurricaneLayer(data.geojson, (stormId, stormName) => {
        console.log(`Storm clicked: ${stormId} - ${stormName}`);
        HurricaneHandler.drillDown(stormId, stormName);
      });

      // Fit map to storm locations
      if (!skipFit) MapAdapter.fitToBounds(data.geojson);

    } else if (data.multi_year && data.year_data && data.year_range) {
      // Multi-year mode: initialize time slider
      console.log('Multi-year data detected, initializing time slider');
      console.log(`Year range: ${data.year_range.min} - ${data.year_range.max}`);
      console.log('DEBUG app.js: metric_year_ranges from response:', data.metric_year_ranges);

      // Auto-enable demographics overlay for demographic data from chat orders
      // This ensures viewport-based admin level filtering works
      const OverlaySelector = window.OverlaySelector;
      if (ChatManager?.mode !== 'research' && OverlaySelector && !OverlaySelector.isActive('demographics')) {
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
        if (!skipFit) MapAdapter.fitToBounds(data.geojson);
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
          const displayLevel = loadedAdminLevel !== null
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
        const explicitLevelMatch = String(data.geographic_level || '').match(/^admin_(\d+)$/);
        const loadedAdminLevel = explicitLevelMatch ? parseInt(explicitLevelMatch[1], 10) : ViewportLoader.currentAdminLevel;
        const displayGeojson = options.skipAdminLevelFilter
          ? data.geojson
          : (() => {
              const filteredGeojson = this.filterGeojsonByAdminLevel(data.geojson, loadedAdminLevel);
              return filteredGeojson?.features?.length ? filteredGeojson : data.geojson;
            })();
        if (options.lazyLoad) {
          MapAdapter.updateSourceData(displayGeojson);
        } else {
          MapAdapter.loadGeoJSON(displayGeojson);
          if (!skipFit) MapAdapter.fitToBounds(data.geojson);
          if (!options.skipOrderModeLevelHold) {
            ViewportLoader.holdOrderModeLevel?.(loadedAdminLevel, 1400);
          }
        }

        if (ChatManager?.mode !== 'research' && data.data_type === 'metrics' && OverlaySelector && !OverlaySelector.isActive('demographics')) {
          console.log('Auto-enabling demographics overlay for chat order data');
          OverlaySelector.setActive('demographics', true);
        }
      }
    }

    if (data.data_type === 'metrics' && options.order) {
      this.setMetricOrderContext(options.order, data);
    }

    const hasRasterCapability = Boolean(
      (Array.isArray(data.scene_periods) && data.scene_periods.length > 0) ||
      (Array.isArray(data.raster_clip_levels) && data.raster_clip_levels.length > 0)
    );
    if (data.data_type === 'metrics' && hasRasterCapability && String(data.source_id || '').trim()) {
      RasterPanel.init(String(data.source_id || '').trim());
    } else if (!hasRasterCapability) {
      RasterPanel.hide?.();
    }

    // Collapse sidebar on mobile
    if (window.innerWidth < 500) {
      ChatManager.elements.sidebar.classList.add('collapsed');
      ChatManager.syncSidebarToggleVisibility?.();
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

  focusResearchGeojson(geojson) {
    if (!geojson?.features?.length || !MapAdapter?.map) return;
    MapAdapter.clearNavigationLayer?.();
    MapAdapter.clearResearchDisplayLayers?.();
    this.clearResearchDisplayInteractions();
    this.navigationLocations = null;
    this.currentData = {
      geojson,
      dataset_name: 'Research Focus',
      source_name: 'Research Focus',
      isNavigation: true
    };
    MapAdapter.loadNavigationLayer(geojson, {
      fillOpacity: 0,
      strokeColor: '#ffd38a',
      strokeWidth: 2.2
    });
    MapAdapter.fitToBounds(geojson);
  },

  enterResearchCanvasMode() {
    this.currentCanvasMode = 'research';
    this.pendingCanvasMode = 'research';
    if (!MapAdapter?.map) return;
    RasterPanel.hide?.();
    this.navigationLocations = null;
    this.currentData = null;
    this.activeMetricOrderContext = null;
    this.clearMetricPrefetch();
    this.currentResearchDisplay = null;
    this.currentResearchLayerOptions = null;

    TimeSlider.hide?.();
    ChoroplethManager.reset?.();
    MapAdapter.setChoroplethVisible?.(false);

    MapAdapter.clearLayers?.();
    MapAdapter.clearParentOutline?.();
    MapAdapter.clearCityOverlay?.();
    MapAdapter.clearNavigationLayer?.();
    MapAdapter.clearResearchDisplayLayers?.();
    this.clearResearchDisplayInteractions();
    ViewportLoader.orderMode = true;
  },

  leaveResearchCanvasMode() {
    if (this.currentCanvasMode === 'research') {
      this.currentCanvasMode = 'explore';
    }
    this.pendingCanvasMode = 'explore';
    if (!MapAdapter?.map) return;
    ViewportLoader.orderMode = false;
    MapAdapter.setChoroplethVisible?.(OverlaySelector?.isActive?.('demographics') === true);
    this.clearResearchDisplayInteractions();
    this.currentResearchDisplay = null;
    this.currentResearchLayerOptions = null;
    MapAdapter.clearResearchDisplayLayers?.();
  },

  enterOpsCanvasMode() {
    this.currentCanvasMode = 'ops';
    this.pendingCanvasMode = 'ops';
    if (!MapAdapter?.map) return;
    TimeSlider.hide?.();
    RasterPanel.hide?.();
    this.navigationLocations = null;
    this.currentData = null;
    this.activeMetricOrderContext = null;
    this.clearMetricPrefetch();
    this.currentResearchDisplay = null;
    this.currentResearchLayerOptions = null;

    MapAdapter.clearParentOutline?.();
    MapAdapter.clearCityOverlay?.();
    MapAdapter.clearNavigationLayer?.();
    MapAdapter.clearResearchDisplayLayers?.();
    this.clearResearchDisplayInteractions();
    ViewportLoader.orderMode = true;
  },

  leaveOpsCanvasMode() {
    if (this.currentCanvasMode === 'ops') {
      this.currentCanvasMode = 'explore';
    }
    if (this.pendingCanvasMode === 'ops') {
      this.pendingCanvasMode = 'explore';
    }
    if (!MapAdapter?.map) return;
    if (ViewportLoader.orderMode) {
      ViewportLoader.orderMode = false;
    }
    this.clearResearchDisplayInteractions();
    MapAdapter.clearResearchDisplayLayers?.();
  },

  getResearchLayerOptions(display) {
    const style = display?.style || {};
    const baseOptions = this.getResearchSimpleLayerOptions(style);
    if (String(display?.source_id || '').trim() !== 'fairfax_buildings') {
      return baseOptions;
    }
    return {
      ...this.getResearchBuildingLayerOptions(style),
      ...baseOptions
    };
  },

  getResearchSimpleLayerOptions(style = {}) {
    const fillColor = style.fill_color || style.fillColor || null;
    const strokeColor = style.stroke_color || style.strokeColor || null;
    const options = {};
    if (fillColor) {
      options.fillColor = fillColor;
      options.fillOpacity = 0.22;
    }
    if (strokeColor) {
      options.strokeColor = strokeColor;
      options.strokeWidth = 2.4;
    }
    return options;
  },

  getResearchBuildingTypeMetadata() {
    return {
      defaultTypeColors: {
        SFR: '#ef4444',
        C: '#3b82f6',
        MU: '#2563eb',
        MG: '#f59e0b',
        P: '#10b981'
      },
      defaultFallbackColor: '#f97316',
      typeLabels: {
        SFR: 'Residential',
        C: 'Commercial',
        MU: 'Mixed-use',
        MG: 'Transportation / Parking',
        P: 'Public / Civic',
        I: 'Industrial'
      }
    };
  },

  getResearchBuildingLayerOptions(style = {}) {
    const {
      defaultTypeColors,
      defaultFallbackColor
    } = this.getResearchBuildingTypeMetadata();
    const overrideColors = style?.buildingTypeColors || {};
    const typeColors = { ...defaultTypeColors, ...overrideColors };
    const fillExpression = [
      'match',
      ['coalesce', ['get', 'TYPE'], '']
    ];
    Object.entries(typeColors).forEach(([typeCode, color]) => {
      fillExpression.push(typeCode, color);
    });
    fillExpression.push(defaultFallbackColor);
    return {
      fillColorExpression: fillExpression,
      fillOpacity: [
        'case',
        ['boolean', ['feature-state', 'hover'], false],
        0.9,
        0.72
      ],
      strokeColor: '#ffe0b2',
      strokeWidth: [
        'case',
        ['boolean', ['feature-state', 'hover'], false],
        2.6,
        1.4
      ]
    };
  },

  setupResearchDisplayInteractions() {
    if (!MapAdapter?.map) return;
    this.clearResearchDisplayInteractions();
    const interactiveLayerIds = MapAdapter.getResearchDisplayFillLayerIds?.() || [CONFIG.layers.selectionFill];

    this._researchDisplayHoverHandler = (e) => {
      if (!e.features?.length || MapAdapter.popupLocked) return;
      const feature = e.features[0];
      MapAdapter.map.getCanvas().style.cursor = 'pointer';
      this.handleFeatureHover(feature, e.lngLat);
    };

    this._researchDisplayLeaveHandler = () => {
      if (!MapAdapter?.map) return;
      MapAdapter.map.getCanvas().style.cursor = '';
      if (!MapAdapter.popupLocked) {
        MapAdapter.hidePopup?.();
      }
    };

    this._researchDisplayClickHandler = async (e) => {
      if (!e.features?.length) return;
      const feature = e.features[0];
      const popupProperties = this.getPopupProperties(feature);
      MapAdapter.popupLocked = true;
      MapAdapter.setPopupFocusOverride?.(popupProperties);
      MapAdapter.setSelectedPopupContext?.({
        kind: 'geometry',
        properties: popupProperties
      });
      this.handleFeatureHover(feature, e.lngLat);
      const locationInfo = popupProperties?.loc_id ? await LocationInfoCache.fetch(popupProperties.loc_id) : null;
      if (MapAdapter.popupLocked) {
        MapAdapter.updateSelectedPopupLocationInfo?.(locationInfo || {});
        const popupHtml = PopupBuilder.build(popupProperties, this.currentData, locationInfo || {});
        MapAdapter.showPopup([e.lngLat.lng, e.lngLat.lat], popupHtml);
        MapAdapter.setupPopupTabHandlers?.();
      }
    };

    this._researchDisplayInteractiveLayerIds = interactiveLayerIds.filter(Boolean);
    for (const layerId of this._researchDisplayInteractiveLayerIds) {
      if (!MapAdapter.map.getLayer(layerId)) continue;
      MapAdapter.map.on('mousemove', layerId, this._researchDisplayHoverHandler);
      MapAdapter.map.on('mouseleave', layerId, this._researchDisplayLeaveHandler);
      MapAdapter.map.on('click', layerId, this._researchDisplayClickHandler);
    }
  },

  clearResearchDisplayInteractions() {
    if (!MapAdapter?.map) return;
    const layerIds = this._researchDisplayInteractiveLayerIds || [CONFIG.layers.selectionFill];
    for (const layerId of layerIds) {
      if (this._researchDisplayHoverHandler) {
        MapAdapter.map.off('mousemove', layerId, this._researchDisplayHoverHandler);
      }
      if (this._researchDisplayLeaveHandler) {
        MapAdapter.map.off('mouseleave', layerId, this._researchDisplayLeaveHandler);
      }
      if (this._researchDisplayClickHandler) {
        MapAdapter.map.off('click', layerId, this._researchDisplayClickHandler);
      }
    }
    this._researchDisplayInteractiveLayerIds = [];
    this._researchDisplayHoverHandler = null;
    this._researchDisplayLeaveHandler = null;
    this._researchDisplayClickHandler = null;
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
