/**
 * Overlay Controller - Orchestrates overlay data loading and rendering.
 * Listens to OverlaySelector changes and fetches/displays data using models.
 *
 * Data flow:
 * 1. Toggle overlay ON -> fetch ALL events from API
 * 2. Cache full dataset
 * 3. Filter by current TimeSlider year and render
 * 4. When TimeSlider changes -> filter cached data and update display
 */

import { TrackAnimator, MultiTrackAnimator, setDependencies as setTrackAnimatorDeps } from './track-animator.js';
import EventAnimator, { AnimationMode, setDependencies as setEventAnimatorDeps } from './event-animator.js';
import { resolveOverlayIdFromPackId, resolveOverlayIdFromSourceId } from './overlay-selector.js';
import { TIME_SYSTEM } from './time-slider.js';
import {
  buildRangeRequestSignature,
  calculateCacheSize,
  dataCache,
  loadedRanges,
  loadedYears,
  overlayLedger,
  recordFullyLoadedRangeClaim,
  recordYearRangeCoverage,
  yearRangeCache
} from './overlay-cache.js';
import {
  clearAllOverlayCaches,
  clearMetricCacheEntry,
  clearOverlayData,
  clearOverlayFilters,
  getActiveFiltersForOverlay,
  getCachedData as getOverlayCachedData,
  getCachedMetricData as getOverlayCachedMetricData,
  getCacheStats as getOverlayCacheStats,
  getLoadedFiltersForOverlay,
  getLoadedYearsForOverlay,
  ingestMetricData as ingestOverlayMetricData,
  isYearLoaded,
  refreshGeometryFromCache as refreshCachedGeometry,
  removeEventData as removeOverlayEventData,
  removeGeometryData as removeOverlayGeometryData,
  removeMetricData as removeOverlayMetricData,
  renderGeometryData as renderOverlayGeometryData,
  seedEventData as seedOverlayEventData,
  updateOverlayFilters
} from './overlay-cache-ops.js';
import { loadRangeData, loadWeatherYearData } from './overlay-data-loader.js';
import {
  addAnimateTrackButton as addHurricaneTrackButton,
  drillDownHurricane as showHurricaneTrackDetail,
  exitTrackDrillDown,
  exitTrackView as exitHurricaneTrackView,
  handleHurricaneDrillDown as runHurricaneDrillDown,
  hideHurricaneOverlay,
  restoreHurricaneOverlay,
  setupTrackPositionClickHandler as bindTrackPositionClickHandler,
  showHurricanePopup,
  stopHurricaneRollingAnimation as stopRollingHurricanes,
  startTrackAnimation as startHurricaneTrackAnimation
} from './overlay-hurricane.js';
import { addGenericExitButton, beginFocusedAnimationSession, selectLinkedAnimationFeatures, routeTimeToFocusAnimation } from './overlay-disaster-common.js';
import {
  exitFireAnimation,
  exitWildfireImpact,
  exitWildfirePerimeter,
  handleFireAnimation as runFireAnimation,
  handleFireProgression as runFireProgression,
  handleWildfireImpact as runWildfireImpact,
  handleWildfirePerimeter as runWildfirePerimeter
} from './overlay-wildfire.js';
import {
  exitFloodAnimation,
  exitFloodImpact,
  handleFloodAnimation as runFloodAnimation,
  handleFloodImpact as runFloodImpact
} from './overlay-flood.js';
import {
  exitTornadoPointAnimation,
  handleTornadoPointAnimation as runTornadoPointAnimation,
  handleTornadoSequence as runTornadoSequence
} from './overlay-tornado.js';
import {
  handleTsunamiRunups as runTsunamiRunups
} from './overlay-tsunami.js';
import {
  handleSequenceChange as runSequenceChange
} from './overlay-earthquake.js';
import {
  exitVolcanoImpact,
  handleVolcanoImpact as runVolcanoImpact
} from './overlay-volcano.js';
import { fetchMsgpack } from './utils/fetch.js';
import { WeatherGridModel, setDependencies as setWeatherGridDeps } from './models/model-weather-grid.js';
import { OceanRasterModel, setDependencies as setOceanRasterDeps } from './models/model-ocean-raster.js';
import { OceanRasterPanel, setDependencies as setOceanRasterPanelDeps } from './ocean-raster-panel.js';
import { GeometryModel } from './models/model-geometry.js';
import { AuroraOverlay } from './overlay-aurora.js';
import { NwsAlertsOverlay } from './overlay-nws-alerts.js';
import { getLivePointOverlay, livePointOverlayFeedId } from './live-point-overlay.js';
import {
  buildOverlayStatusMessage as buildSurfaceOverlayStatusMessage,
  formatSurfaceLabel
} from './shared/surface-messaging.js';

// Dependencies set via setDependencies
let MapAdapter = null;
let ModelRegistry = null;
let OverlaySelector = null;
let TimeSlider = null;
let ChatManager = null;

export function setDependencies(deps) {
  MapAdapter = deps.MapAdapter;
  ModelRegistry = deps.ModelRegistry;
  OverlaySelector = deps.OverlaySelector;
  TimeSlider = deps.TimeSlider;
  ChatManager = deps.ChatManager || null;

  // Wire dependencies to TrackAnimator
  setTrackAnimatorDeps({
    MapAdapter: deps.MapAdapter,
    TimeSlider: deps.TimeSlider,
    TrackModel: deps.ModelRegistry?.getModel?.('track')
  });

  // Wire dependencies to EventAnimator
  setEventAnimatorDeps({
    MapAdapter: deps.MapAdapter,
    TimeSlider: deps.TimeSlider,
    ModelRegistry: deps.ModelRegistry,
    TIME_SYSTEM: TIME_SYSTEM
  });

  // Wire dependencies to WeatherGridModel
  setWeatherGridDeps({
    MapAdapter: deps.MapAdapter
  });

  // Wire dependencies to OceanRasterModel (animated SST basin rasters)
  setOceanRasterDeps({
    MapAdapter: deps.MapAdapter
  });

  // Wire the Ocean Temp Grid control panel
  setOceanRasterPanelDeps({
    OceanRasterModel,
    getCurrentTime: () => TimeSlider?.currentTime,
  });
}

function getLoadedOverlayCount(overlayId) {
  const featureCount = dataCache[overlayId]?.features?.length;
  if (Number.isFinite(featureCount)) {
    return featureCount;
  }
  return null;
}

function buildOverlayStatusMessage(overlayId, isActive) {
  const loadedCount = getLoadedOverlayCount(overlayId);
  const mode = OverlaySelector?.currentLaneMode || 'explore';
  return buildSurfaceOverlayStatusMessage(overlayId, isActive, {
    loadedCount,
    mode
  });
}

function formatCountText(count, singular, plural = '') {
  const safeCount = Number(count);
  if (!Number.isFinite(safeCount) || safeCount < 0) {
    return '';
  }
  const noun = safeCount === 1
    ? singular
    : (plural || `${singular}s`);
  return `${safeCount.toLocaleString()} ${noun}`;
}

const STATUS_MESSAGE_DEDUPE_TTL_MS = 1500;
const recentStatusMessages = new Map();
const OPS_RETAINED_HISTORY_MS = 72 * 60 * 60 * 1000;
const OPS_RETAINED_HISTORY_OVERLAYS = new Set(['earthquakes']);

function shouldSuppressDuplicateStatusMessage(mode, text) {
  const normalizedMode = String(mode || 'explore').trim().toLowerCase() || 'explore';
  const normalizedText = String(text || '').trim();
  if (!normalizedText) {
    return true;
  }
  const now = Date.now();
  const recentKey = `${normalizedMode}::${normalizedText}`;
  for (const [key, lastAt] of recentStatusMessages.entries()) {
    if (now - lastAt > STATUS_MESSAGE_DEDUPE_TTL_MS) {
      recentStatusMessages.delete(key);
    }
  }
  const lastAt = recentStatusMessages.get(recentKey);
  if (Number.isFinite(lastAt) && now - lastAt <= STATUS_MESSAGE_DEDUPE_TTL_MS) {
    return true;
  }
  recentStatusMessages.set(recentKey, now);
  return false;
}

function emitOverlayStatusMessage(overlayId, isActive, options = {}) {
  if (options.suppressStatusMessage) return;
  if (options.categoryBatch) return;
  const mode = OverlaySelector?.currentLaneMode || 'explore';
  let text = null;
  if (
    isActive &&
    mode === 'ops' &&
    typeof OverlayController?.buildOpsFeedSummaryMessage === 'function'
  ) {
    text = OverlayController.buildOpsFeedSummaryMessage(overlayId, [overlayId]);
  }
  if (!text) {
    text = buildOverlayStatusMessage(overlayId, isActive);
  }
  if (!text || !ChatManager?.addMessage) return;
  if (shouldSuppressDuplicateStatusMessage(mode, text)) return;
  ChatManager.addMessage(text, 'assistant', {
    mode
  });
}

function emitCategoryBatchStatusMessage(categoryBatch = {}) {
  const overlayIds = (Array.isArray(categoryBatch.overlayIds) ? categoryBatch.overlayIds : [])
    .map((value) => String(value || '').trim())
    .filter(Boolean);
  if (!overlayIds.length || !ChatManager?.addMessage) return;
  const mode = OverlaySelector?.currentLaneMode || 'explore';
  const messages = overlayIds.map((overlayId) => {
    if (categoryBatch.active && mode === 'ops' && typeof OverlayController?.buildOpsFeedSummaryMessage === 'function') {
      return OverlayController.buildOpsFeedSummaryMessage(overlayId, [overlayId]);
    }
    return buildOverlayStatusMessage(overlayId, Boolean(categoryBatch.active));
  }).filter(Boolean);
  if (!messages.length) return;
  const message = messages.join(' ');
  if (shouldSuppressDuplicateStatusMessage(mode, message)) return;
  ChatManager.addMessage(message, 'assistant', {
    mode
  });
}

function refreshTickerForOverlayState() {
  window.TickerController?.refreshVisibility?.();
}

function isSharedMetricOverlay(overlayId) {
  const config = OverlaySelector?.getOverlayConfig?.(overlayId);
  return config?.model === 'choropleth';
}

/**
 * Gardner-Knopoff window calculation for aftershocks.
 * Returns time window in days based on mainshock magnitude.
 * Formula: 10^(0.5*M - 1.5) days
 * @param {number} magnitude - Mainshock magnitude
 * @returns {number} Time window in days
 */
function gardnerKnopoffTimeWindow(magnitude) {
  return Math.pow(10, 0.5 * magnitude - 1.5);
}

// API endpoints for each overlay type
// Severity filters reduce data volume for initial load:
// - Earthquakes: M5.5+ (significant events)
// - Hurricanes: Cat1+ (named hurricanes only, excludes TD/TS)
// - Tornadoes: EF2+ (significant damage)
// - Wildfires: 100km2+ (major fires)
// - Volcanoes, Tsunamis, Floods: no filter (small datasets)
//
// Year-based lazy loading: Data is fetched per-year as user navigates time.
// On overlay enable: fetch current year
// On TimeSlider change: fetch that year if not cached
const OVERLAY_ENDPOINTS = {
  earthquakes: {
    baseUrl: '/api/earthquakes/geojson',
    params: { min_magnitude: '5.5' },
    eventType: 'earthquake',
    yearField: 'year'
  },
  hurricanes: {
    baseUrl: '/api/storms/tracks/geojson',
    params: { min_category: 'Cat1' },
    trackEndpoint: '/api/storms/{storm_id}/track',
    eventType: 'hurricane',
    yearField: 'year'
  },
  volcanoes: {
    baseUrl: '/api/eruptions/geojson',
    params: { exclude_ongoing: 'true' },
    eventType: 'volcano',
    yearField: 'year'
  },
  wildfires: {
    baseUrl: '/api/wildfires/geojson',
    params: { min_area_km2: '500', include_perimeter: 'true' },  // 500km2 (~193 sq mi) = large fires
    eventType: 'wildfire',
    yearField: 'year'
  },
  tsunamis: {
    baseUrl: '/api/tsunamis/geojson',
    params: {},
    animationEndpoint: '/api/tsunamis/{event_id}/animation',
    eventType: 'tsunami',
    yearField: 'year'
  },
  tornadoes: {
    baseUrl: '/api/tornadoes/geojson',
    params: { min_scale: 'EF2' },
    detailEndpoint: '/api/tornadoes/{event_id}',
    eventType: 'tornado',
    yearField: 'year'
  },
  floods: {
    baseUrl: '/api/floods/geojson',
    params: { include_geometry: 'true' },
    geometryEndpoint: '/api/floods/{event_id}/geometry',
    eventType: 'flood',
    yearField: 'year',
    maxYear: 2019  // Flood data ends at 2019
  },
  drought: {
    baseUrl: '/api/drought/geojson',
    params: { country: 'CAN' },
    eventType: 'drought',
    yearField: 'year',
    minYear: 2019  // Canada drought data starts at 2019
  },
  landslides: {
    baseUrl: '/api/landslides/geojson',
    params: { min_deaths: '1', require_coords: 'true' },
    eventType: 'landslide',
    yearField: 'year'
  },
  // Weather/Climate overlays - grid data format (not GeoJSON)
  // Data available from 1940, but UI defaults to 2000 (earlier data via chat)
  temperature: {
    baseUrl: '/api/weather/grid',
    params: { variable: 'temp_c', tier: 'weekly' },
    isWeatherGrid: true,
    minYear: 1940,
    defaultMinYear: 2000
  },
  humidity: {
    baseUrl: '/api/weather/grid',
    params: { variable: 'humidity', tier: 'weekly' },
    isWeatherGrid: true,
    minYear: 1940,
    defaultMinYear: 2000
  },
  'snow-depth': {
    baseUrl: '/api/weather/grid',
    params: { variable: 'snow_depth_m', tier: 'weekly' },
    isWeatherGrid: true,
    minYear: 1940,
    defaultMinYear: 2000
  },
  'ocean-sst-grid': {
    baseUrl: '/api/climate/grid',
    params: { source: 'ocean_sst', tier: 'daily' },
    climateGrid: {
      variables: ['sst_c'],
      variableOverlayMap: {
        sst_c: 'ocean-sst-grid'
      }
    },
    isWeatherGrid: true,
    minYear: 1982,
    defaultMinYear: 2025
  }
};

/**
 * Event lifecycle configuration for timestamp-based filtering.
 * Each disaster type defines how to calculate start/end times and fade duration.
 * See docs/future/rolling_time.md for full documentation.
 */
const EVENT_LIFECYCLE = {
  earthquake: {
    // Earthquake with expanding "aftershock zone" circle
    // Circle expands over days/weeks based on magnitude (from aftershock data analysis)
    getStartMs: (f) => new Date(f.properties.timestamp).getTime(),
    getEndMs: (f) => {
      // End time = when the expanding circle reaches max radius
      // Based on data: M5.5: ~4d, M6: ~9d, M6.5-7.5: ~20-25d, M8+: ~30d
      const start = new Date(f.properties.timestamp).getTime();
      const mag = f.properties.magnitude || 5;
      // Expansion duration scales with magnitude: ~4 days at M5, ~30 days at M8
      const expansionDays = Math.min(30, 4 * Math.pow(1.5, mag - 5));
      return start + expansionDays * 24 * 60 * 60 * 1000;
    },
    defaultDuration: 7 * 24 * 60 * 60 * 1000,  // 7 days default
    // Quick fade after expansion completes (aftershock sequence ending)
    fadeDuration: 7 * 24 * 60 * 60 * 1000,  // 7 days
    // Aftershock wave speed from data analysis (distance/time of aftershocks):
    // M5-6: ~0.3 km/h (7 km/day), M7-8: ~1-2 km/h (25-50 km/day)
    // Bigger earthquakes = faster expansion (more impressive on map)
    getWaveSpeedKmPerMs: (f) => {
      const mag = f.properties.magnitude || 5;
      // Base: 0.3 km/h at M5, doubles per magnitude unit
      // 0.3 km/h = 0.0833 km/min = 0.00139 km/sec = 0.00000139 km/ms
      const baseSpeed = 0.00000139;  // 0.3 km/h in km/ms
      return baseSpeed * Math.pow(2, mag - 5);
    },
    // Max radius from data (use felt_radius_km, default by magnitude)
    getMaxWaveRadiusKm: (f) => {
      if (f.properties.felt_radius_km) return f.properties.felt_radius_km;
      // Default based on magnitude: M5: ~30km, M6: ~80km, M7: ~180km, M8: ~400km
      const mag = f.properties.magnitude || 5;
      return 30 * Math.pow(2.5, mag - 5);
    }
  },

  hurricane: {
    // Track event - spans start_date to end_date
    getStartMs: (f) => new Date(f.properties.start_date).getTime(),
    getEndMs: (f) => new Date(f.properties.end_date).getTime(),
    defaultDuration: 7 * 24 * 60 * 60 * 1000,  // 7 days if missing
    fadeDuration: 7 * 24 * 60 * 60 * 1000      // 7 days after dissipation
  },

  tsunami: {
    // Propagation event - wave expands to furthest runup location
    // Uses max_runup_dist_km from data (distance to furthest observed runup)
    getStartMs: (f) => new Date(f.properties.timestamp).getTime(),
    getEndMs: (f) => {
      const start = new Date(f.properties.timestamp).getTime();
      // End time = when wave reaches furthest runup
      // Wave speed ~720 km/h, calculate from max distance
      const maxDist = f.properties.max_runup_dist_km || 500;  // Default 500km
      const travelHours = maxDist / 720;
      return start + travelHours * 60 * 60 * 1000;
    },
    defaultDuration: 2 * 60 * 60 * 1000,  // 2 hours default
    fadeDuration: 7 * 24 * 60 * 60 * 1000,  // 7 days
    // Wave speed: ~720 km/h in open ocean
    waveSpeedKmPerMs: 0.0002,  // 720 km/h in km/ms
    // Max radius from data (furthest runup location)
    getMaxWaveRadiusKm: (f) => {
      return f.properties.max_runup_dist_km || 500;  // Default 500km
    }
  },

  volcano: {
    // Volcanic eruption with expanding ash cloud/felt radius
    // Uses actual felt_radius_km from data, VEI calculation as fallback
    getStartMs: (f) => new Date(f.properties.timestamp).getTime(),
    getEndMs: (f) => {
      // If eruption has known duration, use that
      if (f.properties.end_timestamp) {
        return new Date(f.properties.end_timestamp).getTime();
      }
      if (f.properties.duration_days) {
        return new Date(f.properties.timestamp).getTime() +
               f.properties.duration_days * 24 * 60 * 60 * 1000;
      }
      if (f.properties.is_ongoing) {
        return Date.now();  // Still active
      }
      // Expansion time: circle grows to felt_radius over several hours
      // Higher VEI = faster expansion but larger radius, so ~similar duration
      const start = new Date(f.properties.timestamp).getTime();
      const vei = f.properties.VEI || f.properties.vei || 2;
      const maxRadius = f.properties.felt_radius_km || Math.pow(2, vei) * 12.5;
      const speedKmH = 10 * Math.pow(1.6, vei - 2);
      const expansionHours = maxRadius / speedKmH;
      return start + expansionHours * 60 * 60 * 1000;
    },
    defaultDuration: 24 * 60 * 60 * 1000,  // 24 hours default expansion
    fadeDuration: 7 * 24 * 60 * 60 * 1000,   // 7 days fade
    // Ash cloud expansion speed - VEI-based
    // VEI 2: ~10 km/h, VEI 4: ~26 km/h, VEI 6: ~66 km/h
    getWaveSpeedKmPerMs: (f) => {
      const vei = f.properties.VEI || f.properties.vei || 2;
      // Base: 10 km/h at VEI 2, scales with VEI
      const speedKmH = 10 * Math.pow(1.6, vei - 2);
      return speedKmH / 3600000;  // Convert km/h to km/ms
    },
    // Max radius from actual data (felt_radius_km), VEI fallback
    // Data: VEI 2: ~23km, VEI 4: ~105km, VEI 6: ~478km, VEI 7: ~1021km
    getMaxWaveRadiusKm: (f) => {
      if (f.properties.felt_radius_km) return f.properties.felt_radius_km;
      const vei = f.properties.VEI || f.properties.vei || 2;
      return Math.pow(2, vei) * 12.5;  // Fallback calculation
    }
  },

  tornado: {
    // Instant track event
    getStartMs: (f) => new Date(f.properties.timestamp).getTime(),
    getEndMs: (f) => {
      // Estimate from track length: ~1 mile/minute typical speed
      const lengthMi = f.properties.tornado_length_mi || 1;
      return new Date(f.properties.timestamp).getTime() + lengthMi * 60 * 1000;
    },
    defaultDuration: 30 * 60 * 1000,       // 30 minutes
    fadeDuration: 7 * 24 * 60 * 60 * 1000  // 7 days
  },

  wildfire: {
    // Duration event with progression
    getStartMs: (f) => new Date(f.properties.timestamp).getTime(),
    getEndMs: (f) => {
      if (f.properties.duration_days) {
        return new Date(f.properties.timestamp).getTime() +
               f.properties.duration_days * 24 * 60 * 60 * 1000;
      }
      return new Date(f.properties.timestamp).getTime() + 30 * 24 * 60 * 60 * 1000;
    },
    defaultDuration: 30 * 24 * 60 * 60 * 1000,  // 30 days
    fadeDuration: 7 * 24 * 60 * 60 * 1000       // 7 days
  },

  flood: {
    // Duration event
    getStartMs: (f) => new Date(f.properties.timestamp).getTime(),
    getEndMs: (f) => {
      if (f.properties.end_timestamp) {
        return new Date(f.properties.end_timestamp).getTime();
      }
      if (f.properties.duration_days) {
        return new Date(f.properties.timestamp).getTime() +
               f.properties.duration_days * 24 * 60 * 60 * 1000;
      }
      return new Date(f.properties.timestamp).getTime() + 21 * 24 * 60 * 60 * 1000;
    },
    defaultDuration: 21 * 24 * 60 * 60 * 1000,  // 21 days
    fadeDuration: 7 * 24 * 60 * 60 * 1000       // 7 days
  },

  drought: {
    // Monthly snapshot duration event
    getStartMs: (f) => new Date(f.properties.timestamp).getTime(),
    getEndMs: (f) => {
      if (f.properties.end_timestamp) {
        return new Date(f.properties.end_timestamp).getTime();
      }
      if (f.properties.duration_days) {
        return new Date(f.properties.timestamp).getTime() +
               f.properties.duration_days * 24 * 60 * 60 * 1000;
      }
      return new Date(f.properties.timestamp).getTime() + 30 * 24 * 60 * 60 * 1000;
    },
    defaultDuration: 30 * 24 * 60 * 60 * 1000,  // 30 days
    fadeDuration: 0  // No fade between monthly snapshots
  },

  landslide: {
    // Point event with expanding circle based on deaths (intensity)
    // Circle expands quickly, stays visible based on severity
    getStartMs: (f) => new Date(f.properties.timestamp).getTime(),
    getEndMs: (f) => {
      const start = new Date(f.properties.timestamp).getTime();
      // Higher intensity (more deaths) = longer visibility: 3-14 days
      const intensity = f.properties.intensity || 1;
      const durationDays = 3 + 2 * intensity;  // 5 days at intensity 1, 13 days at intensity 5
      return start + durationDays * 24 * 60 * 60 * 1000;
    },
    defaultDuration: 7 * 24 * 60 * 60 * 1000,  // 7 days default
    fadeDuration: 7 * 24 * 60 * 60 * 1000,     // 7 days fade
    // Use felt_radius_km from data for circle sizing
    getMaxWaveRadiusKm: (f) => f.properties.felt_radius_km || 10
  }
};

function parseTimeMs(value) {
  if (value == null || value === '') return null;
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.abs(value) >= 1000000000 ? value : null;
  }
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : null;
}

function firstFiniteNumber(values) {
  for (const value of values) {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) {
      return numeric;
    }
  }
  return null;
}

function resolveFeatureStartMs(props = {}) {
  return parseTimeMs(
    props.start_timestamp ??
    props.start_time ??
    props.start_date ??
    props.timestamp ??
    props.time ??
    null
  );
}

function resolveFeatureDurationMs(props = {}) {
  const durationMs = firstFiniteNumber([props.duration_ms, props.length_ms]);
  if (durationMs != null) return durationMs;

  const durationSeconds = firstFiniteNumber([props.duration_seconds, props.length_seconds]);
  if (durationSeconds != null) return durationSeconds * 1000;

  const durationMinutes = firstFiniteNumber([props.duration_minutes, props.length_minutes, props.duration_mins]);
  if (durationMinutes != null) return durationMinutes * 60 * 1000;

  const durationHours = firstFiniteNumber([props.duration_hours, props.length_hours]);
  if (durationHours != null) return durationHours * 60 * 60 * 1000;

  const durationDays = firstFiniteNumber([props.duration_days, props.length_days]);
  if (durationDays != null) return durationDays * 24 * 60 * 60 * 1000;

  return null;
}

function resolveFeatureFadeMs(props = {}) {
  const fadeMs = firstFiniteNumber([props.fade_ms, props.fade_duration_ms]);
  if (fadeMs != null) return fadeMs;

  const fadeSeconds = firstFiniteNumber([props.fade_seconds]);
  if (fadeSeconds != null) return fadeSeconds * 1000;

  const fadeMinutes = firstFiniteNumber([props.fade_minutes, props.fade_mins]);
  if (fadeMinutes != null) return fadeMinutes * 60 * 1000;

  const fadeHours = firstFiniteNumber([props.fade_hours]);
  if (fadeHours != null) return fadeHours * 60 * 60 * 1000;

  const fadeDays = firstFiniteNumber([props.fade_days]);
  if (fadeDays != null) return fadeDays * 24 * 60 * 60 * 1000;

  return 0;
}

function resolveFeatureEndMs(props = {}, startMs = null) {
  const explicitEnd = parseTimeMs(
    props.end_timestamp ??
    props.end_time ??
    props.end_date ??
    props.finish_timestamp ??
    props.finish_time ??
    null
  );
  if (explicitEnd != null) return explicitEnd;

  if (String(props.is_ongoing || '').trim().toLowerCase() === 'true') {
    return Number.POSITIVE_INFINITY;
  }

  const durationMs = resolveFeatureDurationMs(props);
  if (durationMs != null && startMs != null) {
    return startMs + durationMs;
  }

  return startMs;
}

function resolveFeatureLifecycle(feature) {
  const props = feature?.properties || {};
  const startMs = resolveFeatureStartMs(props);
  if (!Number.isFinite(startMs)) {
    return null;
  }

  const endMs = resolveFeatureEndMs(props, startMs);
  if (endMs == null || Number.isNaN(endMs)) {
    return null;
  }

  return {
    startMs,
    endMs,
    fadeDuration: Math.max(0, resolveFeatureFadeMs(props) || 0)
  };
}

function resolveLegacyFeatureLifecycle(feature, eventType) {
  const config = EVENT_LIFECYCLE[eventType];
  if (!config?.getStartMs || !config?.getEndMs) {
    return null;
  }

  try {
    const startMs = config.getStartMs(feature);
    const endMs = config.getEndMs(feature);
    if (!Number.isFinite(startMs) || Number.isNaN(endMs)) {
      return null;
    }
    return {
      startMs,
      endMs,
      fadeDuration: Math.max(0, config.getFadeDuration?.(feature) || config.fadeDuration || 0)
    };
  } catch (error) {
    return null;
  }
}

function resolveFeatureLifecycleWithFallback(feature, eventType) {
  const explicitLifecycle = resolveFeatureLifecycle(feature);
  const legacyLifecycle = resolveLegacyFeatureLifecycle(feature, eventType);

  if (!explicitLifecycle) {
    return legacyLifecycle;
  }
  if (!legacyLifecycle) {
    return explicitLifecycle;
  }

  const explicitHasExtendedWindow = (
    Number.isFinite(explicitLifecycle.endMs) &&
    explicitLifecycle.endMs !== explicitLifecycle.startMs
  ) || (
    Number.isFinite(explicitLifecycle.fadeDuration) &&
    explicitLifecycle.fadeDuration > 0
  );

  if (explicitHasExtendedWindow) {
    return explicitLifecycle;
  }

  return {
    startMs: explicitLifecycle.startMs,
    endMs: legacyLifecycle.endMs,
    fadeDuration: legacyLifecycle.fadeDuration
  };
}

/**
 * Filter and annotate features by lifecycle state.
 * Adds animation properties for expanding circle effects:
 * - _radiusProgress: 0-1 progress through active+animation period (for expanding circles)
 * - _waveRadiusKm: For tsunamis, the current wave radius in km
 * @param {Array} features - GeoJSON features
 * @param {number} currentMs - Current time in milliseconds
 * @param {string} eventType - Event type key (earthquake, hurricane, etc.)
 * @returns {Array} Filtered features with _opacity, _phase, _radiusProgress properties
 */
function filterByLifecycle(features, currentMs, eventType) {
  const config = EVENT_LIFECYCLE[eventType];
  if (!config) {
    // Fallback: show all features at full opacity
    return features.map(f => ({
      ...f,
      properties: { ...f.properties, _opacity: 1.0, _phase: 'active', _radiusProgress: 1.0 }
    }));
  }

  return features.map(f => {
    const lifecycle = resolveFeatureLifecycleWithFallback(f, eventType);
    if (!lifecycle) {
      return {
        ...f,
        properties: { ...f.properties, _opacity: 1.0, _phase: 'active', _radiusProgress: 1.0 }
      };
    }
    const { startMs, endMs, fadeDuration } = lifecycle;

    const fadeEndMs = endMs + fadeDuration;

    // Not visible yet
    if (currentMs < startMs) return null;

    // Already faded out
    if (currentMs > fadeEndMs) return null;

    // Calculate phase and opacity
    let opacity = 1.0;
    let phase = 'active';
    let radiusProgress = 1.0;

    if (currentMs <= endMs) {
      // In active period - calculate expansion progress
      phase = 'active';
      const activeDuration = Math.max(endMs - startMs, 60000);
      // Animation duration: 10% of active period or 5 days, whichever is smaller
      const animationDuration = Math.min(activeDuration * 0.1, 5 * 24 * 60 * 60 * 1000);
      const elapsed = currentMs - startMs;
      if (elapsed < animationDuration) {
        // Expanding phase - ease out for natural feel
        radiusProgress = easeOutQuad(elapsed / animationDuration);
      } else {
        radiusProgress = 1.0;
      }
    } else {
      // In fade period
      phase = 'fading';
      opacity = 1.0 - (currentMs - endMs) / fadeDuration;
      opacity = Math.max(0, Math.min(1, opacity));  // Clamp 0-1
      radiusProgress = 1.0;  // Full size during fade
    }

    // Build properties with animation data
    const props = {
      ...f.properties,
      _opacity: opacity,
      _phase: phase,
      _radiusProgress: radiusProgress
    };

    // Calculate expanding wave radius based on event type
    const elapsed = currentMs - startMs;

    if (eventType === 'earthquake') {
      // Aftershock zone expansion: ~0.3-3 km/h based on magnitude
      // Data-driven speeds from aftershock distance/time analysis
      const waveSpeed = config.getWaveSpeedKmPerMs?.(f) || config.waveSpeedKmPerMs || 0.00000139;
      const maxRadius = config.getMaxWaveRadiusKm?.(f) || f.properties.felt_radius_km || 300;
      const currentRadius = Math.min(elapsed * waveSpeed, maxRadius);
      props._waveRadiusKm = currentRadius;
      // Also set progress for any layers using it
      props._radiusProgress = maxRadius > 0 ? currentRadius / maxRadius : 1.0;
    }

    if (eventType === 'volcano') {
      // Ash cloud expansion: VEI-based speed (10-100 km/h)
      const waveSpeed = config.getWaveSpeedKmPerMs?.(f) || config.waveSpeedKmPerMs || 0.0000028;
      const maxRadius = config.getMaxWaveRadiusKm?.(f) || 100;
      const currentRadius = Math.min(elapsed * waveSpeed, maxRadius);
      props._waveRadiusKm = currentRadius;
      props._radiusProgress = maxRadius > 0 ? currentRadius / maxRadius : 1.0;
    }

    if (eventType === 'tsunami') {
      // Tsunami waves travel ~720 km/h, expand to furthest runup location
      // All events in events.parquet are sources (runups are in separate file)
      const waveSpeed = config.waveSpeedKmPerMs || 0.0002;  // 720 km/h
      const maxRadius = config.getMaxWaveRadiusKm?.(f) || f.properties.max_runup_dist_km || 500;
      const currentRadius = Math.min(elapsed * waveSpeed, maxRadius);
      props._waveRadiusKm = currentRadius;
      props._radiusProgress = maxRadius > 0 ? currentRadius / maxRadius : 1.0;
    }

    // Hurricane track progressive display - trim LineString based on time progress
    if (eventType === 'hurricane' && f.geometry?.type === 'LineString') {
      const totalDuration = endMs - startMs;
      // Calculate animation progress (0 to 1) based on time within active period
      let animationProgress;
      if (phase === 'active' && totalDuration > 0) {
        animationProgress = Math.min(1, elapsed / totalDuration);
      } else {
        // Fading phase or completed - show full track
        animationProgress = 1.0;
      }
      props._animationProgress = animationProgress;

      // Trim the LineString coordinates to show progressive track
      const coords = f.geometry.coordinates;
      if (coords && coords.length > 1 && animationProgress < 1.0) {
        // Calculate how many points to show (at least 1)
        const numPoints = Math.max(1, Math.ceil(animationProgress * coords.length));
        const trimmedCoords = coords.slice(0, numPoints);

        // Return feature with trimmed geometry
        return {
          type: 'Feature',
          geometry: {
            type: 'LineString',
            coordinates: trimmedCoords
          },
          properties: props
        };
      }
    }

    return {
      ...f,
      properties: props
    };
  }).filter(Boolean);
}

function filterByTemporalWindow(features, minMs, maxMs, eventType) {
  const config = EVENT_LIFECYCLE[eventType];
  if (!config) {
    return features.map(f => ({
      ...f,
      properties: { ...f.properties, _opacity: 1.0, _phase: 'active', _radiusProgress: 1.0 }
    }));
  }

  return features.map(f => {
    const lifecycle = resolveFeatureLifecycleWithFallback(f, eventType);
    if (!lifecycle) {
      return null;
    }
    const { startMs, endMs, fadeDuration } = lifecycle;
    const visibleEndMs = endMs + fadeDuration;
    const overlapsWindow = visibleEndMs >= minMs && startMs <= maxMs;
    if (!overlapsWindow) {
      return null;
    }

    return {
      ...f,
      properties: {
        ...f.properties,
        _opacity: 1.0,
        _phase: 'active',
        _radiusProgress: 1.0,
        _animationProgress: 1.0
      }
    };
  }).filter(Boolean);
}

/**
 * Ease out quadratic - starts fast, slows down
 */
function easeOutQuad(t) {
  return t * (2 - t);
}

function getCurrentUtcYear() {
  return new Date().getUTCFullYear();
}

function getUtcYearRangeMs(year) {
  return {
    start: Date.UTC(year, 0, 1, 0, 0, 0, 0),
    end: Date.UTC(year, 11, 31, 23, 59, 59, 999)
  };
}

function collectOverlayEventTimestamps(overlayId) {
  const features = Array.isArray(dataCache[overlayId]?.features) ? dataCache[overlayId].features : [];
  const timestamps = [];
  for (const feature of features) {
    const lifecycle = resolveFeatureLifecycleWithFallback(feature, OVERLAY_ENDPOINTS[overlayId]?.eventType);
    if (lifecycle?.startMs != null) {
      timestamps.push(lifecycle.startMs);
    }
    if (Number.isFinite(lifecycle?.endMs) && lifecycle.endMs !== lifecycle.startMs) {
      timestamps.push(lifecycle.endMs);
    }
  }
  return timestamps;
}

// Feature flag to enable/disable lifecycle filtering (for gradual rollout)
let useLifecycleFiltering = true;

export const OverlayController = {
  // Currently loading overlays (prevent duplicate requests)
  loading: new Set(),

  // AbortControllers for in-flight fetch requests (overlayId -> AbortController)
  abortControllers: new Map(),
  exactEventFilters: new Map(),

  // Last known TimeSlider year (for change detection)
  lastTimeSliderYear: null,

  // Bound listener function (for cleanup if needed)
  _timeChangeListener: null,

  // Active aftershock sequence scale ID
  activeSequenceScaleId: null,

  // Pending geometry data to render when geography overlay is enabled
  // Format: { geojson, geometryType, options }
  pendingGeometry: null,
  opsSnapshotPayloads: new Map(),
  defaultLoadExecutor: null,

  // Startup/runtime mode flags
  initialized: false,
  exploreRuntimeEnabled: false,
  suppressTimelineAutoShow: false,

  setTimelineAutoShowSuppressed(suppressed, options = {}) {
    this.suppressTimelineAutoShow = Boolean(suppressed);
    if (this.suppressTimelineAutoShow && options.hide && TimeSlider?.hide) {
      TimeSlider.hide();
    }
  },

  showTimelineIfAllowed() {
    if (this.suppressTimelineAutoShow) {
      return;
    }
    TimeSlider?.show?.();
  },

  setDefaultLoadExecutor(executor) {
    this.defaultLoadExecutor = typeof executor === 'function' ? executor : null;
  },

  hasCachedOverlayData(overlayId) {
    if (!overlayId) return false;
    if (dataCache[overlayId]?.features?.length) return true;
    if (dataCache[overlayId]?.years && Object.keys(dataCache[overlayId].years).length) return true;
    if (this.opsSnapshotPayloads.has(overlayId)) return true;
    return false;
  },

  hasCompletedRangeForCurrentFilters(overlayId, endpoint = null) {
    // TASK L2: reads overlayLedger instead of the loadedRanges mirror.
    // claimsFor() only ever returns held (recorded) claims -- in-flight
    // claims live separately in the ledger -- so `claims.length > 0` is the
    // ledger equivalent of the old `ranges.some((range) => !range.loading)`.
    const claims = overlayLedger.claimsFor(overlayId);
    if (!claims.length) return false;
    if (!endpoint) return true;
    const signature = buildRangeRequestSignature(endpoint, overlayId);
    return claims.some((claim) => claim.filters === signature);
  },

  _isOpsMode() {
    return document.body.classList.contains('chat-mode-ops');
  },

  _opsOverlayIdForPayload(payload) {
    const sourceId = String(payload?.source_id || '').trim();
    const eventType = String(payload?.event_type || '').trim();
    if (sourceId === 'hurricanes_ops' || eventType === 'hurricane') return 'hurricanes';
    if (sourceId === 'currency_live_ops') return 'currency';
    if (eventType === 'earthquake') return 'earthquakes';
    if (eventType === 'tsunami') return 'tsunamis';
    if (eventType === 'volcano') return 'volcanoes';
    if (eventType === 'wildfire') return 'wildfires';
    if (eventType === 'tornado') return 'tornadoes';
    if (eventType === 'flood') return 'floods';
    if (eventType === 'landslide') return 'landslides';
    return null;
  },

  _isOpsSnapshotManagedOverlay(overlayId) {
    return [
      'currency',
      'earthquakes',
      'hurricanes',
      'tsunamis',
      'volcanoes',
      'wildfires',
      'tornadoes',
      'floods',
      'landslides'
    ].includes(overlayId);
  },

  getOverlayFeatureCount(overlayId) {
    const normalizedOverlayId = String(overlayId || '').trim();
    if (!normalizedOverlayId) return null;

    if (normalizedOverlayId === 'nws_alerts') {
      const stats = NwsAlertsOverlay?.getDisplayStats?.();
      return Number.isFinite(stats?.visibleCount) ? stats.visibleCount : null;
    }

    if (normalizedOverlayId === 'aurora') {
      const stats = AuroraOverlay?.getDisplayStats?.();
      return Number.isFinite(stats?.visibleCount) ? stats.visibleCount : null;
    }

    const livePointOverlay = getLivePointOverlay(normalizedOverlayId);
    if (livePointOverlay) {
      const stats = livePointOverlay.getDisplayStats?.();
      return Number.isFinite(stats?.visibleCount) ? stats.visibleCount : null;
    }

    const snapshotCount = this.opsSnapshotPayloads.get(normalizedOverlayId)?.geojson?.features?.length;
    if (Number.isFinite(snapshotCount)) {
      return snapshotCount;
    }

    return getLoadedOverlayCount(normalizedOverlayId);
  },

  getOpsSnapshotCount(overlayId) {
    const normalizedOverlayId = String(overlayId || '').trim();
    if (!normalizedOverlayId) return null;
    const payload = this.opsSnapshotPayloads.get(normalizedOverlayId);
    if (!payload || typeof payload !== 'object') return null;

    const directCount = payload.count;
    if (Number.isFinite(directCount)) {
      return directCount;
    }

    const geojsonCount = payload?.geojson?.features?.length;
    if (Number.isFinite(geojsonCount)) {
      return geojsonCount;
    }

    return null;
  },

  _opsFeedIdForOverlay(overlayId) {
    const normalizedOverlayId = String(overlayId || '').trim();
    switch (normalizedOverlayId) {
      case 'earthquakes':
        return 'earthquakes';
      case 'hurricanes':
        return 'hurricanes';
      case 'wildfires':
        return 'wildfires_us_nifc';
      case 'tsunamis':
        return 'tsunamis';
      case 'volcanoes':
        return 'volcanoes';
      case 'currency':
        return 'currency';
      case 'aurora':
        return 'noaa_aurora';
      case 'nws_alerts':
        return 'usa_nws_alerts';
      default:
        return livePointOverlayFeedId(normalizedOverlayId) || normalizedOverlayId || null;
    }
  },

  _getOpsReportFeedSnapshot(overlayId) {
    const feedId = this._opsFeedIdForOverlay(overlayId);
    const feedSnapshots = Array.isArray(ChatManager?.latestOpsReport?.feed_snapshots)
      ? ChatManager.latestOpsReport.feed_snapshots
      : [];
    return feedSnapshots.find((item) => String(item?.feed || '').trim() === feedId) || null;
  },

  _opsWatchHasOverlay(overlayId) {
    const feedId = this._opsFeedIdForOverlay(overlayId);
    const effectiveFeeds = Array.isArray(ChatManager?.latestOpsReport?.effective_feeds)
      ? ChatManager.latestOpsReport.effective_feeds
      : [];
    return effectiveFeeds.some((value) => String(value || '').trim() === feedId);
  },

  _buildFilteredOpsPayload(overlayId, payload) {
    const normalizedOverlayId = String(overlayId || '').trim();
    const sourcePayload = payload && typeof payload === 'object' ? payload : null;
    const sourceFeatures = Array.isArray(sourcePayload?.geojson?.features) ? sourcePayload.geojson.features : [];
    const feedSnapshot = this._getOpsReportFeedSnapshot(normalizedOverlayId);
    const compactSummary = feedSnapshot?.summary && typeof feedSnapshot.summary === 'object'
      ? feedSnapshot.summary
      : {};

    const fullCountFromPayload = Number.isFinite(sourcePayload?.count) ? sourcePayload.count : sourceFeatures.length;
    const isHistoryDefault = String(sourcePayload?.ops_default_view || '').trim() === 'history';
    const windowLabel = String(sourcePayload?.window_label || '').trim();
    const clonePayload = (features, summaryText) => ({
      ...sourcePayload,
      summary: summaryText || sourcePayload?.summary,
      count: features.length,
      geojson: {
        ...(sourcePayload?.geojson || {}),
        features
      }
    });

    if (!sourcePayload) {
      return {
        payload: payload,
        snapshotCount: null,
        visibleCount: null,
        filterDescription: null,
        chatHint: null,
      };
    }

    switch (normalizedOverlayId) {
      case 'earthquakes': {
        const filtered = sourceFeatures.filter((feature) => Number(feature?.properties?.magnitude) >= 4.5);
        const useFilter = filtered.length > 0 && filtered.length < sourceFeatures.length;
        const visibleFeatures = useFilter ? filtered : sourceFeatures;
        return {
          payload: useFilter ? clonePayload(filtered, `Showing ${filtered.length.toLocaleString()} earthquakes at magnitude 4.5+ from the retained Ops window.`) : sourcePayload,
          snapshotCount: isHistoryDefault ? fullCountFromPayload : (Number.isFinite(compactSummary?.event_count) ? compactSummary.event_count : fullCountFromPayload),
          visibleCount: visibleFeatures.length,
          filterDescription: useFilter ? 'magnitude 4.5 and above' : null,
          chatHint: 'Ask chat to raise the threshold, focus on a region, or compare what changed recently.',
          defaultView: isHistoryDefault ? 'history' : 'snapshot',
          currentSnapshotCount: Number.isFinite(compactSummary?.event_count) ? compactSummary.event_count : null,
          windowLabel: windowLabel || null,
        };
      }
      case 'wildfires': {
        const filtered = sourceFeatures.filter((feature) => Number(feature?.properties?.burned_acres) >= 500);
        const useFilter = filtered.length > 0 && filtered.length < sourceFeatures.length;
        const visibleFeatures = useFilter ? filtered : sourceFeatures;
        return {
          payload: useFilter ? clonePayload(filtered, `Showing ${filtered.length.toLocaleString()} wildfire events above 500 acres from the live snapshot.`) : sourcePayload,
          snapshotCount: Number.isFinite(compactSummary?.active_count) ? compactSummary.active_count : fullCountFromPayload,
          visibleCount: visibleFeatures.length,
          filterDescription: useFilter ? '500 acres and above' : null,
          chatHint: 'Ask chat to show all fires, raise the size filter, or focus on the largest fires.',
        };
      }
      case 'volcanoes': {
        const filtered = sourceFeatures.filter((feature) => {
          const value = String(feature?.properties?.is_ongoing || '').trim().toLowerCase();
          return value === 'true' || value === '1' || value === 'yes';
        });
        const useFilter = filtered.length > 0 && filtered.length < sourceFeatures.length;
        const visibleFeatures = useFilter ? filtered : sourceFeatures;
        return {
          payload: useFilter ? clonePayload(filtered, `Showing ${filtered.length.toLocaleString()} ongoing volcano events from the retained Ops window.`) : sourcePayload,
          snapshotCount: isHistoryDefault ? fullCountFromPayload : (Number.isFinite(compactSummary?.event_count) ? compactSummary.event_count : fullCountFromPayload),
          visibleCount: visibleFeatures.length,
          filterDescription: useFilter ? 'ongoing events only' : null,
          chatHint: 'Ask chat to include lower-activity volcanoes, filter by region, or show the strongest events.',
          defaultView: isHistoryDefault ? 'history' : 'snapshot',
          currentSnapshotCount: Number.isFinite(compactSummary?.event_count) ? compactSummary.event_count : null,
          windowLabel: windowLabel || null,
        };
      }
      case 'hurricanes':
        return {
          payload: sourcePayload,
          snapshotCount: isHistoryDefault ? fullCountFromPayload : (Number.isFinite(compactSummary?.storm_count) ? compactSummary.storm_count : fullCountFromPayload),
          visibleCount: sourceFeatures.length,
          filterDescription: null,
          chatHint: 'Ask chat to focus on one storm, compare tracks, or show only the strongest storms.',
          defaultView: isHistoryDefault ? 'history' : 'snapshot',
          currentSnapshotCount: Number.isFinite(compactSummary?.storm_count) ? compactSummary.storm_count : null,
          windowLabel: windowLabel || null,
        };
      case 'tsunamis':
        return {
          payload: sourcePayload,
          snapshotCount: isHistoryDefault ? fullCountFromPayload : (Number.isFinite(compactSummary?.event_count) ? compactSummary.event_count : fullCountFromPayload),
          visibleCount: sourceFeatures.length,
          filterDescription: null,
          chatHint: 'Ask chat for recent tsunami history, linked earthquake events, or the last 72 hours of activity.',
          defaultView: isHistoryDefault ? 'history' : 'snapshot',
          currentSnapshotCount: Number.isFinite(compactSummary?.event_count) ? compactSummary.event_count : null,
          windowLabel: windowLabel || null,
        };
      case 'currency':
        return {
          payload: sourcePayload,
          snapshotCount: Number.isFinite(compactSummary?.rate_count) ? compactSummary.rate_count : fullCountFromPayload,
          visibleCount: sourceFeatures.length,
          filterDescription: null,
          chatHint: 'Ask chat to focus on one region, list the biggest movers, or compare currencies.',
        };
      default:
        return {
          payload: sourcePayload,
          snapshotCount: fullCountFromPayload,
          visibleCount: sourceFeatures.length,
          filterDescription: null,
          chatHint: null,
        };
    }
  },

  buildOpsFeedSummaryMessage(feedId, overlayIds = []) {
    const normalizedFeedId = String(feedId || '').trim();
    const normalizedOverlayIds = (Array.isArray(overlayIds) ? overlayIds : [])
      .map((value) => String(value || '').trim())
      .filter(Boolean);
    const primaryOverlayId = normalizedOverlayIds[0] || '';
    const preparedPayload = this._buildFilteredOpsPayload(primaryOverlayId, this.opsSnapshotPayloads.get(primaryOverlayId));
    const feedSnapshot = this._getOpsReportFeedSnapshot(primaryOverlayId);
    const compactSummary = feedSnapshot?.summary && typeof feedSnapshot.summary === 'object'
      ? feedSnapshot.summary
      : {};
    const snapshotCount = Number.isFinite(preparedPayload?.snapshotCount)
      ? preparedPayload.snapshotCount
      : (this.getOpsSnapshotCount(primaryOverlayId) ?? this.getOverlayFeatureCount(primaryOverlayId));
    const currentSnapshotFallback = preparedPayload?.defaultView === 'history' ? null : snapshotCount;
    const currentSnapshotCount = Number.isFinite(preparedPayload?.currentSnapshotCount)
      ? preparedPayload.currentSnapshotCount
      : currentSnapshotFallback;
    const visibleCount = Number.isFinite(preparedPayload?.visibleCount)
      ? preparedPayload.visibleCount
      : snapshotCount;
    const chatHint = String(preparedPayload?.chatHint || '').trim();
    const windowLabel = String(preparedPayload?.windowLabel || 'the retained Ops window').trim();
    const countText = (singular, plural = '') => formatCountText(snapshotCount, singular, plural);
    const currentCountText = (singular, plural = '') => formatCountText(currentSnapshotCount, singular, plural);
    const withHint = (message) => chatHint ? `${message} ${chatHint}` : message;

    switch (primaryOverlayId) {
      case 'earthquakes': {
        if (preparedPayload?.defaultView === 'history') {
          if (!Number.isFinite(snapshotCount) || snapshotCount <= 0) {
            return 'No earthquakes are visible in the retained Ops window right now. Ask chat to lower the threshold, focus on a region, or check the current snapshot.';
          }
          const currentText = Number.isFinite(currentSnapshotCount)
            ? ` Current snapshot: ${currentCountText('earthquake')}.`
            : '';
          return withHint(`Earthquakes default to recent history. Showing ${countText('earthquake')} from ${windowLabel}.${currentText}`);
        }
        if (!Number.isFinite(snapshotCount) || snapshotCount <= 0) {
          return 'There are 0 earthquakes active now in the current earthquake snapshot. Ask chat for recent quake history, raise or lower the threshold, or focus on a region.';
        }
        const snapshotText = countText('earthquake');
        if (preparedPayload?.filterDescription && visibleCount < snapshotCount) {
          return withHint(`There ${snapshotCount === 1 ? 'is' : 'are'} ${snapshotText} in the current earthquake snapshot. Showing ${visibleCount.toLocaleString()} earthquakes at ${preparedPayload.filterDescription} to keep the map readable.`);
        }
        return withHint(`There ${snapshotCount === 1 ? 'is' : 'are'} ${snapshotText} in the current earthquake snapshot. Showing all of them now.`);
      }
      case 'hurricanes': {
        if (preparedPayload?.defaultView === 'history') {
          if (!Number.isFinite(snapshotCount) || snapshotCount <= 0) {
            return 'No recent storm tracks are visible in the retained Ops window right now. Ask chat to check the current snapshot, one basin, or recent storm history.';
          }
          const currentText = Number.isFinite(currentSnapshotCount)
            ? ` Current snapshot: ${currentCountText('active storm')}.`
            : '';
          return withHint(`Hurricanes default to recent history. Showing ${countText('storm track')} from ${windowLabel}.${currentText}`);
        }
        if (!Number.isFinite(snapshotCount) || snapshotCount <= 0) {
          return 'There are 0 active storms in the current hurricane snapshot. Ask chat about recent storm history, one basin, or the strongest recent storms.';
        }
        return withHint(`There ${snapshotCount === 1 ? 'is' : 'are'} ${countText('active storm')} in the current hurricane snapshot. Showing all active storm tracks now.`);
      }
      case 'wildfires': {
        if (!Number.isFinite(snapshotCount) || snapshotCount <= 0) {
          return 'There are 0 active wildfires in the current wildfire snapshot. Ask chat for recent fire history, a region focus, or the biggest recent fires.';
        }
        if (preparedPayload?.filterDescription && visibleCount < snapshotCount) {
          return withHint(`There ${snapshotCount === 1 ? 'is' : 'are'} ${countText('wildfire')} in the current wildfire snapshot. Showing ${visibleCount.toLocaleString()} fires at ${preparedPayload.filterDescription} to keep the map readable.`);
        }
        return withHint(`There ${snapshotCount === 1 ? 'is' : 'are'} ${countText('wildfire')} in the current wildfire snapshot. Showing all of them now.`);
      }
      case 'tsunamis': {
        if (preparedPayload?.defaultView === 'history') {
          if (!Number.isFinite(snapshotCount) || snapshotCount <= 0) {
            return 'No tsunami events are visible in the retained Ops window right now. Ask chat for linked earthquake events or the current snapshot.';
          }
          const currentText = Number.isFinite(currentSnapshotCount)
            ? ` Current snapshot: ${currentCountText('active tsunami event')}.`
            : '';
          return withHint(`Tsunamis default to recent history. Showing ${countText('tsunami event')} from ${windowLabel}.${currentText}`);
        }
        if (!Number.isFinite(snapshotCount) || snapshotCount <= 0) {
          return 'There are 0 active tsunami events in the current tsunami snapshot. Ask chat for recent tsunami history, linked earthquake events, or the last 72 hours of activity.';
        }
        return withHint(`There ${snapshotCount === 1 ? 'is' : 'are'} ${countText('tsunami event')} in the current tsunami snapshot. Showing all current events now.`);
      }
      case 'volcanoes': {
        if (preparedPayload?.defaultView === 'history') {
          if (!Number.isFinite(snapshotCount) || snapshotCount <= 0) {
            return 'No volcano events are visible in the retained Ops window right now. Ask chat for a region filter or the current snapshot.';
          }
          const currentText = Number.isFinite(currentSnapshotCount)
            ? ` Current snapshot: ${currentCountText('active volcano event')}.`
            : '';
          return withHint(`Volcanoes default to recent history. Showing ${countText('volcano event')} from ${windowLabel}.${currentText}`);
        }
        const ongoingCount = Number.isFinite(compactSummary?.ongoing_count) ? compactSummary.ongoing_count : null;
        if ((!Number.isFinite(snapshotCount) || snapshotCount <= 0) && (!Number.isFinite(ongoingCount) || ongoingCount <= 0)) {
          return 'There are 0 active volcano events in the current snapshot. Ask chat for recent volcano history, a region filter, or stronger recent eruptions.';
        }
        if (preparedPayload?.filterDescription && visibleCount < snapshotCount) {
          return withHint(`There ${snapshotCount === 1 ? 'is' : 'are'} ${countText('volcano event')} in the current volcano snapshot. Showing ${visibleCount.toLocaleString()} ${visibleCount === 1 ? 'ongoing event' : 'ongoing events'} first.`);
        }
        return withHint(`There ${snapshotCount === 1 ? 'is' : 'are'} ${countText('volcano event')} in the current volcano snapshot. Showing all current events now.`);
      }
      case 'nws_alerts': {
        const stats = NwsAlertsOverlay?.getDisplayStats?.() || {};
        if (!Number.isFinite(stats?.snapshotCount) || stats.snapshotCount <= 0) {
          return 'There are 0 active NWS alerts right now. Ask chat to focus on one state, explain the alert mix, or summarize what changed recently.';
        }
        return `There ${stats.snapshotCount === 1 ? 'is' : 'are'} ${formatCountText(stats.snapshotCount, 'active NWS alert')} in the live snapshot. Showing all current Extreme and Severe alerts now. Ask chat to focus on one state, explain the alert mix, or summarize what changed recently.`;
      }
      case 'currency': {
        if (!Number.isFinite(snapshotCount) || snapshotCount <= 0) {
          return 'Currency feed active now, but the current FX snapshot has no visible country values. Ask chat to focus on one region, compare currencies, or list the biggest movers.';
        }
        return `Currency feed active now. Tracking ${snapshotCount.toLocaleString()} rates across ${visibleCount.toLocaleString()} countries in the current snapshot. Showing all countries now. ${preparedPayload.chatHint}`;
      }
      case 'aurora': {
        const stats = AuroraOverlay?.getDisplayStats?.() || {};
        if (!Number.isFinite(stats?.snapshotCount) || stats.snapshotCount <= 0) {
          return 'Aurora feed active now, but no visible aurora cells are in the current forecast. Ask chat to summarize tonight\'s outlook or focus on one region.';
        }
        if (stats?.usingStrongBand && Number.isFinite(stats?.visibleCount) && stats.visibleCount < stats.snapshotCount) {
          return `Aurora feed active now. There are ${stats.snapshotCount.toLocaleString()} visible forecast cells in the current snapshot. Showing ${stats.visibleCount.toLocaleString()} cells at ${stats.filterDescription} first for readability. Ask chat to widen the band, focus on North America, or summarize tonight's outlook.`;
        }
        return `Aurora feed active now. Showing ${stats.snapshotCount.toLocaleString()} visible forecast cells from the current outlook. Ask chat to focus on North America or summarize tonight's outlook.`;
      }
      case 'ocean-sst-grid': {
        const gridDate = String(compactSummary?.grid_date || '').trim();
        const product = String(compactSummary?.product || 'NOAA OISST').trim();
        const dateText = gridDate ? ` Latest live collector grid date: ${gridDate}.` : '';
        return `Ocean temperature feed active. Showing the prepared ocean SST grid overlay for map display.${dateText} Source: ${product}. Ask chat to compare basins, switch to anomalies, or explain recent SST context.`;
      }
      default: {
        const label = formatSurfaceLabel(primaryOverlayId || normalizedFeedId || 'feed');
        const genericCountText = formatCountText(snapshotCount, 'item');
        return genericCountText
          ? `${label} feed active now. Current snapshot includes ${genericCountText}.`
          : `${label} feed active now. Current snapshot is on the map.`;
      }
    }
  },

  setOpsSnapshotPayloads(displayPayloads = []) {
    const previousOverlayIds = new Set(this.opsSnapshotPayloads.keys());
    this.opsSnapshotPayloads.clear();
    for (const payload of displayPayloads || []) {
      const overlayId = this._opsOverlayIdForPayload(payload);
      if (!overlayId) continue;
      this.opsSnapshotPayloads.set(overlayId, payload);
    }

    MapAdapter?.refreshRouteFocusPopupFromSnapshot?.();

    if (!this._isOpsMode()) {
      return;
    }

    const activeOverlays = OverlaySelector?.getActiveOverlays?.() || [];
    const managedOverlayIds = new Set([
      ...previousOverlayIds,
      ...this.opsSnapshotPayloads.keys(),
      'earthquakes',
      'hurricanes',
      'wildfires',
      'tsunamis',
      'volcanoes',
      'currency',
      'tornadoes',
      'floods',
      'landslides',
    ]);

    for (const overlayId of managedOverlayIds) {
      if (!this._isOpsSnapshotManagedOverlay(overlayId)) continue;
      const isActive = activeOverlays.includes(overlayId);
      const hasSnapshot = this.opsSnapshotPayloads.has(overlayId);
      if (!isActive || !hasSnapshot) {
        this.hideOverlay(overlayId);
      }
    }

    for (const overlayId of activeOverlays) {
      if (this.opsSnapshotPayloads.has(overlayId)) {
        this.renderOpsSnapshotOverlay(overlayId);
      }
    }
  },

  renderOpsSnapshotOverlay(overlayId) {
    const payload = this.opsSnapshotPayloads.get(overlayId);
    const endpoint = OVERLAY_ENDPOINTS[overlayId];
    const preparedPayload = this._buildFilteredOpsPayload(overlayId, payload);
    const displayPayload = preparedPayload?.payload;
    if (!displayPayload?.geojson?.features?.length) {
      return false;
    }

    if (displayPayload?.data_type === 'metrics' || overlayId === 'currency') {
      const App = window.App || null;
      if (!App?.displayMapPayload) {
        return false;
      }
      App.displayMapPayload(displayPayload, {
        origin: 'ops',
        preserveExistingRuntimeLayers: true
      });
      App.syncMetricOverlayVisibility?.();
      console.log(`OverlayController: Rendered Ops snapshot overlay ${overlayId} (${displayPayload.geojson.features.length} features)`);
      return true;
    }

    if (!endpoint) {
      return false;
    }

    TimeSlider?.hide?.();
    this._cleanupOverlayAnimations(overlayId);

    const rendered = ModelRegistry?.render(displayPayload.geojson, endpoint.eventType, {
      onEventClick: (props) => this.handleEventClick(overlayId, props)
    });
    if (rendered) {
      console.log(`OverlayController: Rendered Ops snapshot overlay ${overlayId} (${displayPayload.geojson.features.length} features)`);
      return true;
    }
    return false;
  },

  _usesOpsRetainedHistoryWindow(overlayId) {
    return this._isOpsMode()
      && OPS_RETAINED_HISTORY_OVERLAYS.has(String(overlayId || '').trim());
  },

  _getOpsRetainedHistoryWindow() {
    const FIVE_MIN = 5 * 60 * 1000;
    const endMs = Math.floor(Date.now() / FIVE_MIN) * FIVE_MIN;
    return {
      startMs: endMs - OPS_RETAINED_HISTORY_MS,
      endMs
    };
  },

  _filterOpsRetainedHistoryFeatures(overlayId, features, endpoint) {
    if (!this._usesOpsRetainedHistoryWindow(overlayId) || !Array.isArray(features) || !features.length) {
      return features;
    }

    const { startMs, endMs } = this._getOpsRetainedHistoryWindow();
    const filteredFeatures = features.filter((feature) => {
      const lifecycle = resolveFeatureLifecycleWithFallback(feature, endpoint?.eventType);
      const featureStartMs = Number(lifecycle?.startMs);
      const featureEndMs = Number.isFinite(Number(lifecycle?.endMs))
        ? Number(lifecycle.endMs)
        : featureStartMs;
      if (!Number.isFinite(featureStartMs)) {
        return true;
      }
      return featureEndMs >= startMs && featureStartMs <= endMs;
    });

    if (filteredFeatures.length !== features.length) {
      console.log(
        `OverlayController: Ops retained-window filtered ${features.length} -> ${filteredFeatures.length} ${overlayId}`
      );
    }
    return filteredFeatures;
  },

  renderOpsCurrentOverlayData(overlayId) {
    const endpoint = OVERLAY_ENDPOINTS[overlayId];
    const cachedData = dataCache[overlayId];
    const features = Array.isArray(cachedData?.features) ? cachedData.features : [];
    if (!endpoint || !features.length) {
      return false;
    }

    TimeSlider?.hide?.();
    this._cleanupOverlayAnimations(overlayId);

    const exactEventId = String(this.exactEventFilters.get(overlayId) || '').trim();
    const retainedFeatures = this._filterOpsRetainedHistoryFeatures(overlayId, features, endpoint);
    const displayFeatures = exactEventId
      ? retainedFeatures.filter((feature) => {
          const props = feature?.properties || {};
          return String(props.event_id || props.storm_id || feature?.id || '').trim() === exactEventId;
        })
      : retainedFeatures;

    const displayGeojson = {
      ...cachedData,
      type: 'FeatureCollection',
      features: displayFeatures
    };

    const rendered = ModelRegistry?.render(displayGeojson, endpoint.eventType, {
      onEventClick: (props) => this.handleEventClick(overlayId, props)
    });
    if (rendered) {
      console.log(`OverlayController: Rendered Ops current snapshot ${overlayId} (${displayFeatures.length} features)`);
      return true;
    }
    return false;
  },

  _findOpsSnapshotFeature(payload, focus = {}) {
    const features = Array.isArray(payload?.geojson?.features) ? payload.geojson.features : [];
    if (!features.length) return null;

    const eventId = String(focus?.event_id || '').trim();
    if (eventId) {
      const exactMatch = features.find((feature) => {
        const props = feature?.properties || {};
        return String(props.event_id || props.storm_id || feature?.id || '').trim() === eventId;
      });
      if (exactMatch) return exactMatch;
    }

    const focusLon = Number(focus?.lon);
    const focusLat = Number(focus?.lat);
    if (Number.isFinite(focusLon) && Number.isFinite(focusLat)) {
      let nearestFeature = null;
      let nearestDistance = Number.POSITIVE_INFINITY;
      for (const feature of features) {
        const coords = feature?.geometry?.coordinates;
        if (!Array.isArray(coords) || coords.length < 2) continue;
        const lon = Number(coords[0]);
        const lat = Number(coords[1]);
        if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
        const distance = ((lon - focusLon) ** 2) + ((lat - focusLat) ** 2);
        if (distance < nearestDistance) {
          nearestDistance = distance;
          nearestFeature = feature;
        }
      }
      if (nearestFeature) return nearestFeature;
    }

    return null;
  },

  resolveRouteFocusSnapshotTarget(focus = {}) {
    const eventType = String(focus?.event_type || '').trim().toLowerCase();
    const overlayId = this._opsOverlayIdForPayload({
      source_id: focus?.source_id,
      event_type: eventType
    });
    if (!overlayId) return null;
    const payload = this.opsSnapshotPayloads.get(overlayId);
    if (!payload) return null;
    const feature = this._findOpsSnapshotFeature(payload, focus);
    if (!feature) return null;
    const props = feature?.properties && typeof feature.properties === 'object'
      ? { ...feature.properties }
      : {};
    const coords = Array.isArray(feature?.geometry?.coordinates) && feature.geometry.coordinates.length >= 2
      ? [Number(feature.geometry.coordinates[0]), Number(feature.geometry.coordinates[1])]
      : [Number(focus?.lon), Number(focus?.lat)];
    if (!Number.isFinite(coords[0]) || !Number.isFinite(coords[1])) return null;
    return {
      overlayId,
      eventType,
      props,
      coords
    };
  },

  /**
   * Initialize the overlay controller.
   * Registers as listener to OverlaySelector and TimeSlider.
   */
  init(options = {}) {
    if (!OverlaySelector) {
      console.warn('OverlayController: OverlaySelector not available');
      return;
    }
    if (this.initialized) {
      if (options.enableExploreRuntime) {
        this.enableExploreRuntime();
      }
      return;
    }

    // Listen for overlay toggle events
    OverlaySelector.addListener((overlayId, isActive, options = {}) => {
      this.handleOverlayChange(overlayId, isActive, options);
      const batch = options?.categoryBatch;
      if (batch && Array.isArray(batch.overlayIds)) {
        const lastOverlayId = batch.overlayIds[batch.overlayIds.length - 1];
        if (overlayId === lastOverlayId) {
          emitCategoryBatchStatusMessage(batch);
        }
      }
    });

    // Listen for TimeSlider changes (decoupled via listener pattern)
    if (TimeSlider) {
      this._timeChangeListener = (time, source) => {
        this.handleTimeChange(time, source);
      };
      TimeSlider.addChangeListener(this._timeChangeListener);
      console.log('OverlayController: Registered TimeSlider listener');
    }

    if (options.enableExploreRuntime !== false) {
      this.enableExploreRuntime();
    }
    this.initialized = true;
    console.log('OverlayController initialized');
  },

  enableExploreRuntime() {
    if (this.exploreRuntimeEnabled) return;
    this.exploreRuntimeEnabled = true;

    // Setup aftershock sequence listener
    this.setupSequenceListener();

    // Setup cross-event linking (volcano<->earthquake)
    this.setupCrossLinkListeners();

    // Setup track drill-down listener for hurricanes
    this.setupTrackDrillDownListener();

    // Listen for live mode events to refresh overlay data
    window.addEventListener('live-data-poll', () => {
      this.refreshLiveOverlays();
    });
    window.addEventListener('live-lock-engaged', () => {
      this.refreshLiveOverlays();
    });
  },

  /**
   * Setup listener for hurricane track drill-down.
   */
  setupTrackDrillDownListener() {
    document.addEventListener('track-drill-down', async (e) => {
      const { stormId, stormName, eventType, props } = e.detail;
      console.log(`OverlayController: Track drill-down for ${stormName} (${stormId})`);
      await this.handleHurricaneDrillDown(stormId, stormName, props);
    });
    console.log('OverlayController: Registered track drill-down listener');
  },

  /**
   * Setup listener for aftershock sequence selection.
   * When user clicks "View sequence" on an earthquake, adds a 6h granularity tab.
   */
  setupSequenceListener() {
    const model = ModelRegistry?.getModel('point-radius');
    if (model?.onSequenceChange) {
      model.onSequenceChange((sequenceId, eventId) => {
        this.handleSequenceChange(sequenceId, eventId);
      });
      console.log('OverlayController: Registered sequence change listener');
    }
  },

  /**
   * Setup listeners for cross-event linking (volcano<->earthquake).
   */
  setupCrossLinkListeners() {
    const model = ModelRegistry?.getModel('point-radius');
    if (!model) return;

    // Volcano -> Earthquakes: when user searches from a volcano popup
    if (model.onVolcanoEarthquakes) {
      model.onVolcanoEarthquakes((data) => {
        this.handleVolcanoEarthquakes(data);
      });
      console.log('OverlayController: Registered volcano->earthquake cross-link listener');
    }

    // Earthquake -> Volcanoes: when user searches from an earthquake popup
    if (model.onNearbyVolcanoes) {
      model.onNearbyVolcanoes((data) => {
        this.handleNearbyVolcanoes(data);
      });
      console.log('OverlayController: Registered earthquake->volcano cross-link listener');
    }

    if (model.onVolcanoHistory) {
      model.onVolcanoHistory((data) => {
        this.handleVolcanoHistory(data);
      });
      console.log('OverlayController: Registered volcano history listener');
    }

    // Tsunami -> Runups: when user clicks "View runups" on a tsunami
    if (model.onTsunamiRunups) {
      model.onTsunamiRunups((data) => {
        this.handleTsunamiRunups(data);
      });
      console.log('OverlayController: Registered tsunami runups animation listener');
    }

    if (model.onRelatedChain) {
      model.onRelatedChain((data) => {
        this.handleRelatedChain(data);
      });
      console.log('OverlayController: Registered linked disaster chain listener');
    }

    // Wildfire -> Animation: when user clicks "View fire progression"
    if (model.onFireAnimation) {
      model.onFireAnimation((data) => {
        this.handleFireAnimation(data);
      });
      console.log('OverlayController: Registered fire animation listener');
    }

    // Wildfire -> Progression: when daily progression data is available
    if (model.onFireProgression) {
      model.onFireProgression((data) => {
        this.handleFireProgression(data);
      });
      console.log('OverlayController: Registered fire progression listener');
    }

    // Tornado -> Sequence: when user clicks a tornado that's part of a sequence
    if (model.onTornadoSequence) {
      model.onTornadoSequence((data) => {
        this.handleTornadoSequence(data);
      });
      console.log('OverlayController: Registered tornado sequence listener');
    }

    // Tornado -> Point Animation: for tornadoes without track data
    if (model.onTornadoPointAnimation) {
      model.onTornadoPointAnimation((data) => {
        this.handleTornadoPointAnimation(data);
      });
      console.log('OverlayController: Registered tornado point animation listener');
    }

    // Flood -> Animation: when user clicks "View flood" on a flood event
    if (model.onFloodAnimation) {
      model.onFloodAnimation((data) => {
        this.handleFloodAnimation(data);
      });
      console.log('OverlayController: Registered flood animation listener');
    }

    // Volcano -> Impact: when user clicks "Impact" on a volcano event
    if (model.onVolcanoImpact) {
      model.onVolcanoImpact((data) => {
        this.handleVolcanoImpact(data);
      });
      console.log('OverlayController: Registered volcano impact animation listener');
    }

    // Wildfire -> Impact: fallback when no progression data (area circle)
    if (model.onWildfireImpact) {
      model.onWildfireImpact((data) => {
        this.handleWildfireImpact(data);
      });
      console.log('OverlayController: Registered wildfire impact animation listener');
    }

    // Wildfire -> Perimeter: single shape fade-in (second preference)
    if (model.onWildfirePerimeter) {
      model.onWildfirePerimeter((data) => {
        this.handleWildfirePerimeter(data);
      });
      console.log('OverlayController: Registered wildfire perimeter animation listener');
    }

    // Flood -> Impact: fallback when no geometry data (area circle)
    if (model.onFloodImpact) {
      model.onFloodImpact((data) => {
        this.handleFloodImpact(data);
      });
      console.log('OverlayController: Registered flood impact animation listener');
    }
  },

  /**
   * Handle earthquakes found near a volcano.
   * Uses the same animation system as aftershock sequences.
   */
  handleVolcanoEarthquakes(data) {
    const { features, volcanoName, volcanoLat, volcanoLon } = data;
    const session = beginFocusedAnimationSession(this, ['earthquakes'], {
      entryDurationMs: 1500
    });
    console.log(`OverlayController: Displaying ${features.length} earthquakes triggered by ${volcanoName}`);

    if (features.length === 0) return;

    // Convert API features to GeoJSON format
    const seqEvents = features.map(f => ({
      type: 'Feature',
      geometry: f.geometry,
      properties: f.properties
    }));

    // Find the largest earthquake to use as "mainshock" for animation centering
    let mainshock = seqEvents[0];
    for (const event of seqEvents) {
      if ((event.properties.magnitude || 0) > (mainshock.properties.magnitude || 0)) {
        mainshock = event;
      }
    }

    // Handle case where all events have same timestamp or no valid times
    let minTime = Infinity, maxTime = -Infinity;
    for (const event of seqEvents) {
      const t = new Date(event.properties.timestamp || event.properties.time).getTime();
      if (!isNaN(t)) {
        if (t < minTime) minTime = t;
        if (t > maxTime) maxTime = t;
      }
    }

    if (minTime === Infinity || maxTime === -Infinity || minTime === maxTime) {
      // Just display statically without animation
      const geojson = { type: 'FeatureCollection', features: seqEvents };
      const model = ModelRegistry?.getModel('point-radius');
      if (model) {
        model.update(geojson);
        const maplibre = window.maplibregl || maplibregl;
        const bounds = new maplibre.LngLatBounds();
        bounds.extend([volcanoLon, volcanoLat]);
        for (const f of seqEvents) {
          if (f.geometry?.coordinates) bounds.extend(f.geometry.coordinates);
        }
        if (!bounds.isEmpty()) {
          MapAdapter.map.fitBounds(bounds, { padding: 50, maxZoom: 10 });
        }
      }
      console.log(`OverlayController: Showing ${seqEvents.length} earthquakes statically (no time range)`);
      return;
    }

    // Stop any active animation
    if (EventAnimator.getIsActive()) {
      EventAnimator.stop();
    }

    // Clear normal earthquake display
    const model = ModelRegistry?.getModelForType('earthquake');
    if (model?.clear) {
      model.clear();
    }

    // Create mainshock at volcano location
    const volcanoMainshock = {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [volcanoLon, volcanoLat] },
      properties: {
        ...mainshock.properties,
        is_volcano_origin: true,
        volcano_name: volcanoName
      }
    };

    // Determine granularity based on time range
    const timeRange = maxTime - minTime;
    const stepHours = Math.max(1, Math.ceil((timeRange / (60 * 60 * 1000)) / 200));
    let granularityLabel = '6h';
    if (stepHours < 2) granularityLabel = '1h';
    else if (stepHours < 4) granularityLabel = '2h';
    else if (stepHours < 8) granularityLabel = '6h';
    else if (stepHours < 16) granularityLabel = '12h';
    else if (stepHours < 36) granularityLabel = 'daily';
    else granularityLabel = '2d';

    // Start unified EventAnimator with earthquake mode
    EventAnimator.start({
      id: `volcano-${volcanoName.replace(/\s+/g, '-').substring(0, 12)}`,
      label: `${volcanoName} quakes`,
      mode: AnimationMode.EARTHQUAKE,
      events: seqEvents,
      mainshock: volcanoMainshock,
      eventType: 'earthquake',
      timeField: 'timestamp',
      granularity: granularityLabel,
      renderer: 'point-radius',
      onExit: () => {
        console.log('OverlayController: Volcano earthquake sequence exited');
        session.restore();
      }
    });

    console.log(`OverlayController: Started volcano earthquake animation with ${seqEvents.length} events`);
  },

  /**
   * Handle volcanoes found near an earthquake.
   * Shows volcano markers temporarily on the map.
   */
  handleNearbyVolcanoes(data) {
    const { features, earthquakeLat, earthquakeLon } = data;
    console.log(`OverlayController: Displaying ${features.length} nearby volcanoes`);

    if (features.length === 0) {
      console.log('OverlayController: No volcanoes to display');
      return;
    }

    // Log found volcanoes - the popup already displays names
    const names = features.map(f => f.properties.volcano_name).join(', ');
    console.log(`OverlayController: Found volcanoes: ${names}`);
    console.log(`OverlayController: Earthquake at [${earthquakeLon}, ${earthquakeLat}]`);

    // Fit map to show the earthquake and nearby volcanoes
    // Use window.maplibregl for ES module compatibility
    const maplibre = window.maplibregl || maplibregl;
    const bounds = new maplibre.LngLatBounds();
    bounds.extend([earthquakeLon, earthquakeLat]);

    for (const f of features) {
      const coords = f.geometry?.coordinates;
      if (coords && coords.length >= 2) {
        console.log(`OverlayController: Adding volcano at [${coords[0]}, ${coords[1]}]`);
        bounds.extend(coords);
      }
    }

    if (!bounds.isEmpty()) {
      console.log(`OverlayController: Fitting bounds`, bounds.toArray());
      MapAdapter.map.fitBounds(bounds, { padding: 80, maxZoom: 8, duration: 1500 });
    } else {
      console.warn('OverlayController: Bounds are empty, cannot zoom');
    }
  },

  /**
   * Handle tsunami runups animation.
   * Uses EventAnimator with RADIAL mode to show wave propagation.
   * Similar to earthquake sequences: zoom to center, start animation,
   * slowly zoom out with expanding wave radius, reveal runups progressively.
   * @param {Object} data - { geojson, eventId, runupCount }
   */
  handleTsunamiRunups(data) {
    runTsunamiRunups(this, data, { EventAnimator, MapAdapter, TimeSlider, dataCache, yearRangeCache });
  },

  handleRelatedChain(data) {
    const sourceFeature = data?.source;
    const rawFeatures = Array.isArray(data?.features) ? data.features : [];
    const rawLinks = Array.isArray(data?.links) ? data.links : [];
    if (!sourceFeature || rawFeatures.length < 2) {
      console.warn('OverlayController: Related chain missing source or related features');
      return;
    }

    const overlaysToRestore = (OverlaySelector?.getActiveOverlays?.() || []).filter(id => id !== 'demographics' && OVERLAY_ENDPOINTS[id]);
    const session = beginFocusedAnimationSession(this, overlaysToRestore, {
      entryDurationMs: 1500
    });

    const typeColors = {
      earthquake: '#ff6b6b',
      tsunami: '#4dd0e1',
      volcano: '#feb24c',
      hurricane: '#9c27b0',
      tornado: '#32cd32',
      wildfire: '#ff6600',
      flood: '#0066cc',
      landslide: '#8b4513',
      generic: '#90caf9'
    };

    const sourceTimestampRaw = sourceFeature.properties?.timestamp;
    const parsedSourceTime = sourceTimestampRaw ? new Date(sourceTimestampRaw).getTime() : NaN;
    const baseTime = Number.isNaN(parsedSourceTime) ? Date.now() : parsedSourceTime;

    const normalizedFeatures = rawFeatures.map((feature, index) => {
      const props = { ...(feature.properties || {}) };
      const eventType = props.event_type || 'generic';
      const isSource = props.loc_id === sourceFeature.properties?.loc_id || index === 0;
      const parsedDepth = Number(props.chain_depth);
      const depth = Number.isFinite(parsedDepth) ? parsedDepth : (isSource ? 0 : 1);
      const rawTime = props.timestamp ? new Date(props.timestamp).getTime() : NaN;
      const effectiveTime = Number.isNaN(rawTime) ? (baseTime + depth * 12 * 60 * 60 * 1000) : rawTime;
      props.chain_color = isSource ? '#ffffff' : (typeColors[eventType] || typeColors.generic);
      props.chain_radius = isSource ? 10 : 7;
      props.chain_width = isSource ? 2.4 : 1.8;
      props.initial_view_radius_km = isSource ? 260 : (props.initial_view_radius_km ?? 0);
      props.felt_radius_km = props.felt_radius_km ?? 0;
      props.damage_radius_km = props.damage_radius_km ?? 0;
      props.timestamp = props.timestamp || sourceFeature.properties?.timestamp || null;
      props.chain_timestamp = new Date(effectiveTime).toISOString();
      props.event_id = props.event_id || props.loc_id;
      return {
        ...feature,
        properties: props
      };
    });

    const selectedChain = selectLinkedAnimationFeatures(normalizedFeatures, {
      anchorFeatureId: sourceFeature.properties?.loc_id || sourceFeature.properties?.event_id || null,
      timeField: 'chain_timestamp'
    });
    const selectedFeatures = selectedChain.selectedFeatures;
    const selectedLocIds = new Set(
      selectedFeatures
        .map(feature => String(feature?.properties?.loc_id || '').trim())
        .filter(Boolean)
    );

    const featureByLocId = new Map(
      selectedFeatures
        .filter(feature => feature?.properties?.loc_id)
        .map(feature => [feature.properties.loc_id, feature])
    );

    const chainLinks = rawLinks
      .map(link => {
        const parentFeature = featureByLocId.get(link.parent_loc_id);
        const childFeature = featureByLocId.get(link.child_loc_id);
        if (!parentFeature || !childFeature) {
          return null;
        }
        return {
          parent_event_id: link.parent_event_id || parentFeature.properties?.event_id,
          child_event_id: link.child_event_id || childFeature.properties?.event_id,
          link_type: link.link_type,
          direction: link.direction
        };
      })
      .filter(Boolean)
      .filter(link => selectedLocIds.has(String(link.parent_loc_id || '').trim()) && selectedLocIds.has(String(link.child_loc_id || '').trim()));

    const sourceEventId = sourceFeature.properties?.event_id || sourceFeature.properties?.loc_id;
    const sourceLabel = sourceFeature.properties?.event_type || 'event';

    if (EventAnimator.getIsActive()) {
      EventAnimator.stop();
    }

    EventAnimator.start({
      id: `chain-${String(sourceEventId).replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 20)}`,
      label: `${sourceLabel} chain`,
      mode: AnimationMode.CHAIN,
      events: selectedFeatures,
      mainshock: selectedChain.anchorFeature || selectedFeatures[0],
      chainLinks,
      eventType: 'generic_event',
      timeField: 'chain_timestamp',
      granularity: '12h',
      renderer: 'point-radius',
      onExit: () => {
        session.restore();
      }
    });
  },

  /**
   * Handle tornado sequence animation.
   * Uses EventAnimator with TORNADO_SEQUENCE mode for progressive track drawing.
   * @param {Object} data - { geojson, seedEventId, sequenceCount }
   */
  handleTornadoSequence(data) {
    runTornadoSequence(this, data, {
      EventAnimator,
      MapAdapter,
      TimeSlider,
      dataCache,
      yearRangeCache,
      onFallbackPointAnimation: (payload) => this.handleTornadoPointAnimation(payload)
    });
  },

  /**
   * Handle point-only tornado animation.
   * For tornadoes without track data - zooms in, shows circle based on EF scale,
   * with TimeSlider-driven animation showing the tornado's duration.
   * @param {Object} data - { eventId, latitude, longitude, scale, timestamp }
   */
  handleTornadoPointAnimation(data) {
    runTornadoPointAnimation(this, data, { MapAdapter, TimeSlider });
  },

  /**
   * Exit tornado point animation and cleanup.
   * @private
   */
  _exitTornadoPointAnimation() {
    exitTornadoPointAnimation(this, { MapAdapter, TimeSlider });
  },

  /**
   * Handle flood animation - shows flood polygon with opacity fade over duration.
   * At flood start time, outline appears. Over the duration, opacity increases.
   * @param {Object} data - { geometry, eventId, durationDays, startTime, endTime, latitude, longitude, eventName }
   */
  handleFloodAnimation(data) {
    runFloodAnimation(this, data, { MapAdapter, TimeSlider, ModelRegistry, dataCache });
  },

  /**
   * Handle volcano impact radius animation.
   * Shows felt and damage radii expanding from the volcano center.
   */
  handleVolcanoImpact(data) {
    runVolcanoImpact(this, data, { MapAdapter });
  },

  /**
   * Exit volcano impact animation and cleanup.
   * @private
   */
  _exitVolcanoImpact() {
    exitVolcanoImpact(this, { MapAdapter });
  },

  /**
   * Handle wildfire impact animation (area circle fallback).
   * Shows a circle representing the burned area.
   */
  handleWildfireImpact(data) {
    runWildfireImpact(this, data, { MapAdapter, ModelRegistry, dataCache });
  },

  _exitWildfireImpact(skipRestore = false) {
    exitWildfireImpact(this, { MapAdapter, ModelRegistry, dataCache }, skipRestore);
  },

  /**
   * Handle wildfire perimeter animation (single shape fade-in).
   * Shows the fire perimeter polygon fading in.
   */
  handleWildfirePerimeter(data) {
    runWildfirePerimeter(this, data, { MapAdapter, ModelRegistry, dataCache });
  },

  _exitWildfirePerimeter(skipRestore = false) {
    exitWildfirePerimeter(this, { MapAdapter, ModelRegistry, dataCache }, skipRestore);
  },

  /**
   * Handle flood impact animation (area circle fallback).
   * Shows a circle representing the flooded area.
   */
  handleFloodImpact(data) {
    runFloodImpact(this, data, { MapAdapter, ModelRegistry, dataCache });
  },

  _exitFloodImpact(skipRestore = false) {
    exitFloodImpact(this, { MapAdapter, ModelRegistry, dataCache }, skipRestore);
  },

  /**
   * Generic exit button helper.
   * @private
   */
  _addGenericExitButton(id, text, color, onExit) {
    addGenericExitButton(id, text, color, onExit);
  },

  /**
   * Exit flood animation and cleanup.
   * @private
   */
  _exitFloodAnimation(skipRestore = false) {
    exitFloodAnimation(this, { MapAdapter, TimeSlider, ModelRegistry, dataCache }, skipRestore);
  },

  /**
   * Handle wildfire animation - animates perimeter polygon opacity over fire duration.
   * Simple Option A: Fade in final perimeter from 0% to 100% over duration_days.
   */
  handleFireAnimation(data) {
    runFireAnimation(this, data, { MapAdapter, TimeSlider, ModelRegistry, dataCache });
  },

  /**
   * Handle fire progression animation with daily snapshots.
   * Shows actual fire spread day-by-day using pre-computed perimeters.
   * @param {Object} data - {snapshots, eventId, totalDays, startTime, latitude, longitude}
   */
  handleFireProgression(data) {
    runFireProgression(this, data, { MapAdapter, TimeSlider, ModelRegistry, dataCache });
  },

  /**
   * Exit fire animation and cleanup.
   * @private
   */
  _exitFireAnimation(skipRestore = false) {
    exitFireAnimation(this, { MapAdapter, TimeSlider, ModelRegistry, dataCache }, skipRestore);
  },

  /**
   * Hide hurricane overlay to focus on a single track animation.
   * Clears the track model layers but preserves the cached data.
   * @private
   */
  _hideHurricaneOverlay() {
    hideHurricaneOverlay({ modelRegistry: ModelRegistry });
  },

  /**
   * Restore hurricane overlay after exiting track drill-down.
   * @private
   */
  _restoreHurricaneOverlay() {
    restoreHurricaneOverlay(this, { dataCache });
  },

  /**
   * Handle hurricane track drill-down animation.
   * Fetches detailed track data and shows animated path.
   * @param {string} stormId - Storm ID
   * @param {string} stormName - Storm name
   * @param {Object} props - Storm properties
   */
  async handleHurricaneDrillDown(stormId, stormName, props) {
    await runHurricaneDrillDown(this, stormId, stormName, {
      mapAdapter: MapAdapter,
      overlayEndpoints: OVERLAY_ENDPOINTS,
      fetcher: fetchMsgpack,
      modelRegistry: ModelRegistry,
      timeSlider: TimeSlider,
      dataCache,
      addExitButton: addGenericExitButton
    });
  },

  /**
   * Cleanup any stray MultiTrackAnimator animations when overlay is disabled.
   * Note: Rolling mode is deprecated - progressive tracks now handled by filterByLifecycle.
   */
  stopHurricaneRollingAnimation() {
    stopRollingHurricanes();
  },

  /**
   * Exit track drill-down and restore hurricane overlay.
   * @private
   */
  _exitTrackDrillDown() {
    exitTrackDrillDown(this, { modelRegistry: ModelRegistry, timeSlider: TimeSlider, dataCache });
  },

  /**
   * Handle aftershock sequence selection/deselection.
   * Fetches full sequence data from API (not filtered by magnitude).
   * Uses unified EventAnimator with EARTHQUAKE mode.
   * @param {string|null} sequenceId - Sequence ID or null to clear
   * @param {string|null} eventId - Optional mainshock event_id for accurate aftershock query
   */
  async handleSequenceChange(sequenceId, eventId = null) {
    await runSequenceChange(this, sequenceId, eventId, {
      EventAnimator,
      ModelRegistry,
      OverlaySelector,
      OVERLAY_ENDPOINTS,
      TimeSlider,
      dataCache,
      yearRangeCache,
      gardnerKnopoffTimeWindow,
      fetchMsgpack
    });
  },

  // Track last timestamp for lifecycle filtering (to avoid redundant renders)
  lastTimeSliderTimestamp: null,

  /**
   * Handle TimeSlider change event from listener.
   * @param {number} time - Current time (year or timestamp)
   * @param {string} source - What triggered: 'slider' | 'playback' | 'api'
   */
  handleTimeChange(time, source) {
    // If a focused animation session (EventAnimator or TrackAnimator) is active,
    // route the time change to it instead of doing normal year-based filtering.
    // EventAnimator has no listener of its own, so it needs setTime() forwarded;
    // TrackAnimator already listens to TimeSlider directly and just needs us to
    // step aside.
    // Note: Don't check time value - pre-1970 events have negative timestamps
    if (routeTimeToFocusAnimation(time, EventAnimator, TrackAnimator)) {
      return;
    }

    // Determine if this is a timestamp (for lifecycle filtering)
    const isTimestamp = Math.abs(time) >= 50000;
    const forceRerender = source === 'bounds';

    if (useLifecycleFiltering && isTimestamp) {
      // Timestamp lane: lifecycle filtering at the continuous playhead.
      // Throttle updates to avoid excessive re-renders (render every ~6 hours of slider time)
      const SIX_HOURS_MS = 6 * 60 * 60 * 1000;
      if (forceRerender ||
          this.lastTimeSliderTimestamp === null ||
          Math.abs(time - this.lastTimeSliderTimestamp) >= SIX_HOURS_MS) {
        this.lastTimeSliderTimestamp = time;
        this.onTimeChangeTimestamp(time);
      }
    } else {
      // Year lane (deliberate, not legacy): |time| < 50000 means a bare year
      // integer, the format year-granularity and very old history datasets
      // (pre-epoch events) still flow through. Keep this lane; ms timestamps
      // cannot represent that data cleanly.
      const year = this.getYearFromTime(time);
      if (forceRerender || year !== this.lastTimeSliderYear) {
        this.lastTimeSliderYear = year;
        this.onTimeChange(year);
      }
    }
  },

  /**
   * Convert time to year (handles both year int and timestamp ms).
   * Uses same detection as TimeSlider: |value| < 50000 = year, else timestamp.
   * @param {number} time - Time value
   * @returns {number} Year
   */
  getYearFromTime(time) {
    if (!time && time !== 0) return null;
    // If absolute value is small, it's a year (-50000 to 50000)
    // Otherwise it's a timestamp (handles both positive and negative)
    if (Math.abs(time) < 50000) {
      return time;
    }
    // It's a timestamp - convert to year
    return new Date(time).getUTCFullYear();
  },

  /**
   * Get current year from TimeSlider.
   * TimeSlider.currentTime is always stored as timestamp (ms) internally.
   * @returns {number|null}
   */
  getCurrentYear() {
    if (!TimeSlider?.currentTime) return null;

    // currentTime is always a timestamp since Phase 8 unification
    // Use TimeSlider's helper if available, otherwise convert directly
    if (TimeSlider.timestampToYear) {
      return TimeSlider.timestampToYear(TimeSlider.currentTime);
    }
    return new Date(TimeSlider.currentTime).getUTCFullYear();
  },

  /**
   * Get current timestamp from TimeSlider.
   * @returns {number|null}
   */
  getCurrentTimestamp() {
    return TimeSlider?.currentTime || null;
  },

  captureViewState() {
    const camera = MapAdapter?.map
      ? {
          center: {
            lng: Number(MapAdapter.map.getCenter().lng),
            lat: Number(MapAdapter.map.getCenter().lat)
          },
          zoom: Number(MapAdapter.map.getZoom()),
          bearing: Number(MapAdapter.map.getBearing()),
          pitch: Number(MapAdapter.map.getPitch())
        }
      : null;

    return {
      timestamp: this.getCurrentTimestamp(),
      year: this.getCurrentYear(),
      camera,
      activeOverlayIds: this.captureFocusedOverlayIds()
    };
  },

  captureFocusedOverlayIds(preferredOverlayIds = []) {
    const current = Array.isArray(OverlaySelector?.getActiveOverlays?.())
      ? OverlaySelector.getActiveOverlays().filter((id) => id !== 'demographics')
      : [];
    const merged = [...current];
    for (const overlayId of Array.isArray(preferredOverlayIds) ? preferredOverlayIds : []) {
      if (!overlayId || overlayId === 'demographics' || merged.includes(overlayId)) continue;
      merged.push(overlayId);
    }
    return merged;
  },

  enterFocusedOverlayMode(viewState = null, overlayIds = []) {
    const restoreOverlayIds = Array.isArray(overlayIds)
      ? overlayIds.filter(Boolean)
      : [];
    const hiddenOverlayIds = [];

    for (const overlayId of restoreOverlayIds) {
      hiddenOverlayIds.push(overlayId);
      this.hideOverlay(overlayId);
    }

    this._focusedOverlaySnapshot = {
      viewState,
      hiddenOverlayIds
    };

    return this._focusedOverlaySnapshot;
  },

  restoreViewState(viewState, overlayIds = []) {
    const snapshotOverlayIds = Array.isArray(viewState?.activeOverlayIds)
      ? viewState.activeOverlayIds.filter(Boolean)
      : [];
    const fallbackOverlayIds = Array.isArray(overlayIds)
      ? overlayIds.filter(Boolean)
      : [];
    const restoreOverlayIds = snapshotOverlayIds.length > 0
      ? snapshotOverlayIds
      : fallbackOverlayIds;

    this.recalculateTimeRange();

    if (TimeSlider) {
      if (this.suppressTimelineAutoShow) {
        TimeSlider.hide?.();
      } else if (TimeSlider.scales?.find(s => s.id === 'primary')) {
        TimeSlider.setActiveScale('primary');
        if (viewState?.timestamp != null && TimeSlider.setTime) {
          TimeSlider.setTime(viewState.timestamp, 'api');
        }
      }
      if (!this.suppressTimelineAutoShow && Object.keys(yearRangeCache).length > 0) {
        this.showTimelineIfAllowed();
      }
    }

    for (const overlayId of restoreOverlayIds) {
      if (!dataCache[overlayId]) continue;
      if (this._isOpsMode() && this._isOpsSnapshotManagedOverlay(overlayId)) {
        this.renderCurrentData(overlayId);
        continue;
      }
      if (viewState?.timestamp != null) {
        this.renderFilteredData(overlayId, viewState.timestamp, { useTimestamp: true });
      } else if (viewState?.year != null) {
        this.renderFilteredData(overlayId, viewState.year);
      }
    }

    if (viewState?.camera && MapAdapter?.map?.easeTo) {
      const { center, zoom, bearing, pitch } = viewState.camera;
      if (Number.isFinite(center?.lng) && Number.isFinite(center?.lat)) {
        MapAdapter.map.easeTo({
          center: [center.lng, center.lat],
          zoom: Number.isFinite(zoom) ? zoom : MapAdapter.map.getZoom(),
          bearing: Number.isFinite(bearing) ? bearing : MapAdapter.map.getBearing(),
          pitch: Number.isFinite(pitch) ? pitch : MapAdapter.map.getPitch(),
          duration: 900,
          essential: true
        });
      }
    }

    this._focusedOverlaySnapshot = null;
  },

  /**
   * Render overlay with current time using appropriate filtering mode.
   * Uses lifecycle filtering if enabled, otherwise falls back to year-based.
   * @param {string} overlayId - Overlay ID
   */
  renderCurrentData(overlayId) {
    if (this._isOpsMode() && this._isOpsSnapshotManagedOverlay(overlayId)) {
      if (this.renderOpsCurrentOverlayData(overlayId)) {
        return;
      }
    }

    if (useLifecycleFiltering) {
      const timestamp = this.getCurrentTimestamp();
      if (timestamp) {
        this.renderFilteredData(overlayId, timestamp, { useTimestamp: true });
      }
    } else {
      const year = this.getCurrentYear();
      this.renderFilteredData(overlayId, year);
    }
  },

  /**
   * Handle TimeSlider year change - update all active overlays.
   * Year lane: reached when the slider emits bare year integers
   * (year-granularity and very old / pre-epoch history data). This is a
   * deliberate second input format, not a legacy leftover.
   * Auto-fetches data for the year if not already cached.
   * @param {number} year - New year
   */
  onTimeChange(year) {
    const activeOverlays = OverlaySelector?.getActiveOverlays() || [];

    for (const overlayId of activeOverlays) {
      if (overlayId === 'demographics') continue;

      // Handle weather grid overlays
      const overlayConfig = OverlaySelector?.getOverlayConfig(overlayId);
      if (overlayConfig?.model === 'weather-grid') {
        this.reloadWeatherGridForYear(overlayId, overlayConfig, year);
        continue;
      }

      const endpoint = OVERLAY_ENDPOINTS[overlayId];
      if (!endpoint || !endpoint.yearField) continue;

      // Auto-fetch data for the year if not cached, then render
      this.loadAndRenderYear(overlayId, year);
    }
  },

  /**
   * Load data for a specific year if not cached, then render.
   * @param {string} overlayId - Overlay ID
   * @param {number} year - Year to load
   */
  async loadAndRenderYear(overlayId, year) {
    // Coverage derived from loadedRanges (see isYearLoaded in overlay-cache-ops.js)
    const yearAlreadyLoaded = isYearLoaded(overlayId, year);

    if (!yearAlreadyLoaded) {
      console.log(`OverlayController: AUTO-FETCHING ${overlayId} for year ${year} (legacy handler)`);
      const { start: yearStart, end: yearEnd } = getUtcYearRangeMs(year);
      await loadRangeData(overlayId, yearStart, yearEnd, OVERLAY_ENDPOINTS[overlayId]);
    }

    // Render the data for this year
    if (dataCache[overlayId]) {
      if (useLifecycleFiltering && TimeSlider?.currentTime) {
        this.renderFilteredData(overlayId, TimeSlider.currentTime, { useTimestamp: true });
      } else {
        this.renderFilteredData(overlayId, year);
      }
    }
  },

  /**
   * Reload weather grid data for a specific year.
   * Called when time slider year changes.
   * @param {string} overlayId - Overlay ID
   * @param {Object} config - Overlay config
   * @param {number} year - Year to load
   */
  async reloadWeatherGridForYear(overlayId, config, year) {
    // Check if already cached
    const alreadyCached = loadedYears[overlayId]?.has(year);

    if (alreadyCached) {
      console.log(`OverlayController: Using cached weather ${overlayId} for year ${year}`);
    } else {
      // Load via the cache system (year boundaries for weather grid)
      const { start: yearStart, end: yearEnd } = getUtcYearRangeMs(year);
      await loadRangeData(overlayId, yearStart, yearEnd, OVERLAY_ENDPOINTS[overlayId]);
    }

    // Get cached data and pass to display model
    const cachedData = dataCache[overlayId];
    if (cachedData?.years?.[year]) {
      // Display from cache (instances are created automatically)
      WeatherGridModel.displayFromCache(
        overlayId,
        cachedData.years[year],
        cachedData.colorScale,
        cachedData.grid
      );

      // Render at current time slider position
      if (TimeSlider?.currentTime) {
        WeatherGridModel.renderAtTimestamp(overlayId, TimeSlider.currentTime);
      }

      console.log(`OverlayController: Weather grid ${overlayId} displayed for ${year}`);
    }
  },

  /**
   * Handle TimeSlider timestamp change - update all active overlays with lifecycle filtering.
   * NEW: Timestamp-based filtering (used when useLifecycleFiltering is true)
   * Also handles hurricane rolling animation (progressive track drawing during active period).
   * Auto-fetches data for the year if not already cached.
   * @param {number} timestamp - Current timestamp in milliseconds
   */
  onTimeChangeTimestamp(timestamp) {
    const activeOverlays = OverlaySelector?.getActiveOverlays() || [];
    const year = this.getYearFromTime(timestamp);

    for (const overlayId of activeOverlays) {
      if (overlayId === 'demographics') continue;

      // Handle weather grid overlays
      const overlayConfig = OverlaySelector?.getOverlayConfig(overlayId);
      if (overlayConfig?.model === 'weather-grid') {
        if (WeatherGridModel.hasInstance(overlayId)) {
          const range = WeatherGridModel.getTimestampRange(overlayId);
          if (range && (timestamp < range.min || timestamp > range.max)) {
            this.reloadWeatherGridForYear(overlayId, overlayConfig, year);
          } else {
            WeatherGridModel.renderAtTimestamp(overlayId, timestamp);
          }
        }
        continue;
      }

      // Handle ocean raster overlays. ocean_sst has two linked scenes (recent
      // weekly / full history monthly, see loadOceanRasterOverlay); when the
      // slider moves outside the loaded range, fetch the other tier and MERGE
      // it into the same instance as one continuous timeline (repeat calls
      // while the fetch is in flight are no-ops in the model).
      if (overlayConfig?.model === 'ocean-raster') {
        if (OceanRasterModel.hasInstance(overlayId)) {
          const range = OceanRasterModel.getTimestampRange(overlayId);
          if (range && (timestamp < range.min || timestamp > range.max)) {
            const nextTier = timestamp < range.min ? 'history' : 'recent';
            this.loadOceanRasterOverlay(overlayId, overlayConfig, { tier: nextTier, resetTimeRange: false })
              .then(() => OceanRasterModel.renderAtTimestamp(overlayId, TimeSlider?.currentTime ?? timestamp));
          } else {
            OceanRasterModel.renderAtTimestamp(overlayId, timestamp);
          }
        }
        continue;
      }

      const endpoint = OVERLAY_ENDPOINTS[overlayId];
      if (!endpoint) continue;

      // Track last loaded year per overlay to avoid duplicate fetches
      if (!this._lastLoadedYear) this._lastLoadedYear = {};

      // Check if we need to load this year's data
      const yearKey = `${overlayId}_${year}`;
      const yearAlreadyLoaded = isYearLoaded(overlayId, year);
      const currentlyLoading = this._loadingYears?.has(yearKey);

      console.log(`OverlayController: ${overlayId} year=${year}, loaded=${yearAlreadyLoaded}, loading=${currentlyLoading}`);

      if (!yearAlreadyLoaded && !currentlyLoading) {
        // Track that we're loading this year
        if (!this._loadingYears) this._loadingYears = new Set();
        this._loadingYears.add(yearKey);

        console.log(`OverlayController: AUTO-FETCHING ${overlayId} for year ${year}`);
        // Auto-fetch data for this year, then render
        this.loadYearAndRender(overlayId, year, timestamp).finally(() => {
          this._loadingYears?.delete(yearKey);
        });
      } else if (dataCache[overlayId]) {
        // Render from cache
        this.renderFilteredData(overlayId, timestamp, { useTimestamp: true });

      }
    }
  },

  /**
   * Load a year's data and render.
   * Used for lazy loading when user navigates to a year not yet cached.
   * @param {string} overlayId - Overlay ID
   * @param {number} year - Year to load
   * @param {number} timestamp - Optional timestamp for lifecycle filtering
   */
  async loadYearAndRender(overlayId, year, timestamp = null) {
    const endpoint = OVERLAY_ENDPOINTS[overlayId];
    if (!endpoint) return;

    console.log(`OverlayController: Auto-fetching ${overlayId} for year ${year}`);

    // Load the year data (year boundaries)
    const { start: yearStart, end: yearEnd } = getUtcYearRangeMs(year);
    const loaded = await loadRangeData(overlayId, yearStart, yearEnd, OVERLAY_ENDPOINTS[overlayId]);

    // Check if overlay is still active
    const activeOverlays = OverlaySelector?.getActiveOverlays() || [];
    if (!activeOverlays.includes(overlayId)) return;

    // After loading, always render with CURRENT time (not the timestamp that triggered load)
    // This fixes gaps during fast playback where animation moves while data is loading
    if (useLifecycleFiltering && TimeSlider?.currentTime) {
      const currentTimestamp = TimeSlider.currentTime;
      this.renderFilteredData(overlayId, currentTimestamp, { useTimestamp: true });

    } else if (timestamp && useLifecycleFiltering) {
      this.renderFilteredData(overlayId, timestamp, { useTimestamp: true });
    } else {
      // Year-based rendering
      this.renderFilteredData(overlayId, year);
    }

    if (loaded) {
      console.log(`OverlayController: Loaded and rendered ${overlayId} for year ${year}`);
    }
  },

  /**
   * Load an explicit time range for an overlay and render from cache.
   * Used by metadata-driven default loads that should use the native overlay
   * endpoint instead of a confirmed-order response path.
   * @param {string} overlayId - Overlay ID
   * @param {number} startMs - Start timestamp in milliseconds
   * @param {number} endMs - End timestamp in milliseconds
   * @param {object} options - Optional request overrides
   * @param {object|null} options.params - Query parameter overrides
   * @returns {Promise<boolean>}
   */
  async loadOverlayRange(overlayId, startMs, endMs, options = {}) {
    const endpointBase = OVERLAY_ENDPOINTS[overlayId];
    if (!endpointBase) return false;

    const endpoint = options.params
      ? {
          ...endpointBase,
          params: {
            ...(endpointBase.params || {}),
            ...options.params
          }
        }
      : endpointBase;

    const loaded = await loadRangeData(overlayId, startMs, endMs, endpoint);
    const hasCachedData = Boolean(dataCache[overlayId]?.features?.length);

    if (hasCachedData) {
      this.recalculateTimeRange();
      this.showTimelineIfAllowed();
      if (OverlaySelector?.isActive?.(overlayId)) {
        this.renderCurrentData(overlayId);
      }
    }

    return Boolean(loaded || hasCachedData);
  },

  /**
   * Handle overlay toggle event.
   * @param {string} overlayId - Overlay ID (e.g., 'earthquakes')
   * @param {boolean} isActive - Whether overlay is now active
   */
  async handleOverlayChange(overlayId, isActive, options = {}) {
    console.log(`OverlayController: ${overlayId} ${isActive ? 'ON' : 'OFF'}`);

    // Live forecast/observation overlays are driven by their own modules
    // (no catalog data, no TimeSlider). Route and stop here.
    if (overlayId === 'aurora') {
      await AuroraOverlay.setEnabled(isActive);
      refreshTickerForOverlayState();
      emitOverlayStatusMessage(overlayId, isActive, options);
      return;
    }
    if (overlayId === 'nws_alerts') {
      await NwsAlertsOverlay.setEnabled(isActive);
      refreshTickerForOverlayState();
      emitOverlayStatusMessage(overlayId, isActive, options);
      return;
    }
    // Reusable live point feeds (ocean buoys, weather stations, sensors): one
    // generic overlay per registered config (live-point-overlay.js).
    const livePointOverlay = getLivePointOverlay(overlayId);
    if (livePointOverlay) {
      await livePointOverlay.setEnabled(isActive);
      refreshTickerForOverlayState();
      emitOverlayStatusMessage(overlayId, isActive, options);
      return;
    }

    if (this._isOpsMode() && this._isOpsSnapshotManagedOverlay(overlayId)) {
      if (isActive && this.opsSnapshotPayloads.has(overlayId)) {
        this.renderOpsSnapshotOverlay(overlayId);
        emitOverlayStatusMessage(overlayId, true, options);
        return;
      }
      if (isActive && this._opsWatchHasOverlay(overlayId) && this.hasCachedOverlayData(overlayId)) {
        this.renderCurrentData(overlayId);
        emitOverlayStatusMessage(overlayId, true, options);
        return;
      }
      if (
        isActive &&
        this.defaultLoadExecutor &&
        options.allowDefaultLoad !== false &&
        !this.hasCachedOverlayData(overlayId)
      ) {
        const handledByDefaultLoad = await this.defaultLoadExecutor(overlayId, {
          lane: OverlaySelector?.currentLaneMode || 'explore'
        });
        if (handledByDefaultLoad) {
          refreshTickerForOverlayState();
          emitOverlayStatusMessage(overlayId, true, options);
          return;
        }
      }
      if (!isActive) {
        this.hideOverlay(overlayId);
        emitOverlayStatusMessage(overlayId, false, options);
        return;
      }
    }

    // Demographics controls choropleth visibility AND loads countries
    // Note: Can coexist with geometry overlays (separate layer systems)
    // Metric choropleth toggles (demographics, currency) share one choropleth
    // layer. Toggling one off must not hide another that is still on, so
    // visibility tracks whether ANY metric overlay is active.
    if (isSharedMetricOverlay(overlayId)) {
      // Demographics loads the country geometry on first activate; currency
      // and other choropleth overlays ride the same shared choropleth layer.
      if (overlayId === 'demographics' && isActive) {
        const choroplethLayerExists = MapAdapter?.map?.getLayer('regions-fill');
        if (!choroplethLayerExists) {
          const App = window.App;
          if (App && typeof App.loadCountries === 'function') {
            console.log('OverlayController: Loading countries for demographics overlay');
            await App.loadCountries();
          }
        }
      }
      if (
        overlayId !== 'demographics' &&
        isActive &&
        options.allowDefaultLoad !== false &&
        !this.hasCachedOverlayData(overlayId)
      ) {
        let handledByDefaultLoad = false;
        if (this.defaultLoadExecutor) {
          handledByDefaultLoad = await this.defaultLoadExecutor(overlayId, {
            lane: OverlaySelector?.currentLaneMode || 'explore'
          });
        } else if (ChatManager?.runDefaultLoad) {
          handledByDefaultLoad = await ChatManager.runDefaultLoad(
            { overlayId },
            {
              mode: OverlaySelector?.currentLaneMode || 'explore',
              suppressResultMessage: true
            }
          );
        }
        if (handledByDefaultLoad) {
          refreshTickerForOverlayState();
          emitOverlayStatusMessage(overlayId, true, options);
          return;
        }
      }
      const activeOverlays = OverlaySelector?.getActiveOverlays?.() || [];
      const anyMetricActive = activeOverlays.some((id) => isSharedMetricOverlay(id));
      if (MapAdapter) {
        MapAdapter.setChoroplethVisible(anyMetricActive);
      }
      refreshTickerForOverlayState();
      emitOverlayStatusMessage(overlayId, isActive, options);
      return;
    }

    // Geography overlay controls geometry layers (ZCTA, tribal, watersheds, etc.)
    // These are rendered via GeometryModel with type-specific layers
    // Handle both the category toggle ('geography') and individual toggles ('zip_codes', etc.)
    // Note: Can coexist with demographics (separate layer systems)
    const geometryOverlayIds = ['geography', 'zip_codes', 'tribal_areas', 'watersheds', 'parks'];
    if (geometryOverlayIds.includes(overlayId)) {
      if (MapAdapter?.map) {
        if (isActive) {
          // If there's pending geometry data, store it in cache first
          if (this.pendingGeometry) {
            const { geojson, geometryType, sourceId, options } = this.pendingGeometry;
            console.log(`OverlayController: Storing pending geometry (${geometryType}, ${geojson.features?.length || 0} features)`);
            this.renderGeometryData(sourceId, geojson, geometryType, options);
            this.pendingGeometry = null;
          }
          // Render all geometry from cache
          this.refreshGeometryFromCache();
          // Show all geometry layers
          const geometryTypes = ['zcta', 'tribal', 'watershed', 'park', 'geometry'];
          for (const geoType of geometryTypes) {
            const fillId = `${geoType}-geometry-fill`;
            const strokeId = `${geoType}-geometry-stroke`;
            const labelId = `${geoType}-geometry-label`;
            if (MapAdapter.map.getLayer(fillId)) {
              MapAdapter.map.setLayoutProperty(fillId, 'visibility', 'visible');
            }
            if (MapAdapter.map.getLayer(strokeId)) {
              MapAdapter.map.setLayoutProperty(strokeId, 'visibility', 'visible');
            }
            if (MapAdapter.map.getLayer(labelId)) {
              MapAdapter.map.setLayoutProperty(labelId, 'visibility', 'visible');
            }
          }
          console.log(`OverlayController: Geography layers shown`);
        } else {
          // Hide all geometry layers
          const geometryTypes = ['zcta', 'tribal', 'watershed', 'park', 'geometry'];
          for (const geoType of geometryTypes) {
            const fillId = `${geoType}-geometry-fill`;
            const strokeId = `${geoType}-geometry-stroke`;
            const labelId = `${geoType}-geometry-label`;
            if (MapAdapter.map.getLayer(fillId)) {
              MapAdapter.map.setLayoutProperty(fillId, 'visibility', 'none');
            }
            if (MapAdapter.map.getLayer(strokeId)) {
              MapAdapter.map.setLayoutProperty(strokeId, 'visibility', 'none');
            }
            if (MapAdapter.map.getLayer(labelId)) {
              MapAdapter.map.setLayoutProperty(labelId, 'visibility', 'none');
            }
          }
          console.log(`OverlayController: Geography layers hidden`);
        }
      }
      refreshTickerForOverlayState();
      emitOverlayStatusMessage(overlayId, isActive, options);
      return;
    }

    // Weather grid overlays (temperature, humidity, snow-depth)
    const overlayConfig = OverlaySelector?.getOverlayConfig(overlayId);
    if (overlayConfig?.model === 'weather-grid') {
      if (isActive) {
        await this.loadWeatherGridOverlay(overlayId, overlayConfig);
      } else {
        this.clearWeatherGridOverlay(overlayId);
      }
      refreshTickerForOverlayState();
      emitOverlayStatusMessage(overlayId, isActive, options);
      return;
    }

    // Ocean raster overlays (animated SST basin grids)
    if (overlayConfig?.model === 'ocean-raster') {
      if (isActive) {
        await this.loadOceanRasterOverlay(overlayId, overlayConfig);
      } else {
        this.clearOceanRasterOverlay(overlayId);
      }
      refreshTickerForOverlayState();
      emitOverlayStatusMessage(overlayId, isActive, options);
      return;
    }

    if (isActive) {
      if (
        this.defaultLoadExecutor &&
        options.allowDefaultLoad !== false &&
        !this.hasCachedOverlayData(overlayId)
      ) {
        const handledByDefaultLoad = await this.defaultLoadExecutor(overlayId, {
          lane: OverlaySelector?.currentLaneMode || 'explore'
        });
        if (handledByDefaultLoad) {
          refreshTickerForOverlayState();
          emitOverlayStatusMessage(overlayId, true, options);
          return;
        }
      }
      await this.loadOverlay(overlayId);
      refreshTickerForOverlayState();
      emitOverlayStatusMessage(overlayId, true, options);
    } else {
      this.hideOverlay(overlayId);
      refreshTickerForOverlayState();
      emitOverlayStatusMessage(overlayId, false, options);
    }
  },

  /**
   * Load and display a weather grid overlay.
   * @param {string} overlayId - Overlay ID (temperature, humidity, snow-depth)
   * @param {Object} config - Overlay configuration from OverlaySelector
   */
  async loadWeatherGridOverlay(overlayId, config) {
    // Determine year based on current time slider position
    let year = getCurrentUtcYear();

    if (TimeSlider?.currentTime) {
      const currentDate = new Date(TimeSlider.currentTime);
      year = currentDate.getUTCFullYear();
    }

    console.log(`OverlayController: Loading weather grid ${overlayId} for year ${year}`);

    // Load data via cache system (year boundaries for weather grid)
    const { start: yearStart, end: yearEnd } = getUtcYearRangeMs(year);
    await loadRangeData(overlayId, yearStart, yearEnd, OVERLAY_ENDPOINTS[overlayId]);

    // Get cached data and display (instances are created automatically)
    const cachedData = dataCache[overlayId];
    if (cachedData?.years?.[year]) {
      WeatherGridModel.displayFromCache(
        overlayId,
        cachedData.years[year],
        cachedData.colorScale,
        cachedData.grid
      );

      // Set TimeSlider to default range (2000-present, data exists back to 1940 via chat)
      if (TimeSlider && !this.suppressTimelineAutoShow) {
        const minDate = new Date(Date.UTC(2000, 0, 1));  // Jan 1, 2000 (default view)
        const maxDate = new Date();  // Now
        TimeSlider.setTimeRange({
          min: minDate.getTime(),
          max: maxDate.getTime(),
          granularity: 'timestamp',
          available: null
        });
        this.showTimelineIfAllowed();

        // Position slider at start of loaded data
        const yearData = cachedData.years[year];
        if (yearData?.timestamps?.length > 0) {
          TimeSlider.setTime(yearData.timestamps[yearData.timestamps.length - 1]);
        }
      }

      console.log(`OverlayController: Weather grid ${overlayId} loaded for year ${year}`);
    } else {
      console.error(`OverlayController: Failed to load weather grid ${overlayId}`);
    }
  },

  /**
   * Clear a weather grid overlay.
   * @param {string} overlayId - Overlay ID
   */
  clearWeatherGridOverlay(overlayId) {
    WeatherGridModel.hide(overlayId);
    console.log(`OverlayController: Cleared weather grid ${overlayId}`);
  },

  /**
   * Load and display an animated ocean SST basin raster overlay.
   * ocean_sst ships two linked scenes of one pack, the same way weather has
   * hourly/weekly/monthly tiers: "recent" is the smooth weekly bundle
   * (2025-07-01+, the default on enable); "history" is the full 1982-2026
   * monthly archive, fetched on demand when the slider moves outside the
   * loaded range (see onTimeChangeTimestamp). The tiers MERGE into one
   * instance with a union timeline -- monthly frames through the archive,
   * weekly frames where the recent bundle covers -- and the model renders
   * the finest cadence available at each moment, so playback density rises
   * naturally as the playhead enters the recent window.
   * @param {string} overlayId - Overlay ID (e.g. 'ocean-sst-grid')
   * @param {object} config - Overlay config
   * @param {object} [options]
   * @param {'recent'|'history'} [options.tier='recent'] - Which linked scene to load
   * @param {boolean} [options.resetTimeRange] - Reset the slider to the default
   *   latest-year window; defaults to true for 'recent' and false for
   *   'history' so an on-demand merge doesn't move the user's playhead.
   */
  async loadOceanRasterOverlay(overlayId, config, options = {}) {
    const tier = options.tier === 'history' ? 'history' : 'recent';
    const resetTimeRange = options.resetTimeRange !== undefined ? options.resetTimeRange : tier === 'recent';

    const sourceId = config?.rasterSource || 'ocean_sst';
    const laneMode = OverlaySelector?.currentLaneMode || 'explore';
    const variable = config?.rasterVariable || 'sst_c';

    let basins;
    let cadence;
    if (tier === 'history') {
      const historyBasinsByLane = config?.rasterHistoryBasinsByLane || {};
      const historyCadenceByLane = config?.rasterHistoryCadenceByLane || {};
      basins = historyBasinsByLane[laneMode] || config?.rasterHistoryBasins || ['OCEAN'];
      cadence = historyCadenceByLane[laneMode] || config?.rasterHistoryCadence || 'monthly';
    } else {
      const basinsByLane = config?.rasterBasinsByLane || {};
      const cadenceByLane = config?.rasterCadenceByLane || {};
      basins = basinsByLane[laneMode] || config?.rasterBasins || ['XOP'];
      cadence = cadenceByLane[laneMode] || config?.rasterCadence || 'monthly';
    }

    console.log(`OverlayController: Loading ocean raster ${overlayId} lane=${laneMode} tier=${tier} basins=${basins.join(',')} var=${variable}`);
    const ok = await OceanRasterModel.load(overlayId, sourceId, basins, variable);
    if (!ok) {
      console.error(`OverlayController: Failed to load ocean raster ${overlayId}`);
      return;
    }

    const timestamps = OceanRasterModel.getTimestamps(overlayId);
    const range = OceanRasterModel.getTimestampRange(overlayId);
    if (TimeSlider && range && !this.suppressTimelineAutoShow) {
      if (resetTimeRange) {
        // Default view: the latest year of the prepared window; the full
        // prepared span stays available so chat can ask for more time.
        const latest = range.max;
        const defaultMin = Math.max(range.min, latest - 365.25 * 24 * 3600 * 1000);
        const visibleTimestamps = timestamps.filter(
          (timestamp) => timestamp >= defaultMin && timestamp <= latest
        );
        TimeSlider.setTimeRange({
          min: defaultMin,
          max: latest,
          granularity: cadence,
          available: visibleTimestamps.length ? visibleTimestamps : timestamps,
        });
        this.showTimelineIfAllowed();
        if (timestamps.length) TimeSlider.setTime(timestamps[timestamps.length - 1]);
      } else {
        // Tier-cascade reload: widen the slider bounds to the newly loaded
        // bundle's full range without moving the current playhead.
        TimeSlider.setTimeRange({
          min: range.min,
          max: range.max,
          granularity: cadence,
          available: timestamps,
        });
        this.showTimelineIfAllowed();
      }
    }
    OceanRasterPanel.show(overlayId);
    console.log(`OverlayController: Ocean raster ${overlayId} loaded tier=${tier} (${timestamps.length} frames)`);
  },

  /**
   * Clear an ocean raster overlay.
   * @param {string} overlayId - Overlay ID
   */
  clearOceanRasterOverlay(overlayId) {
    OceanRasterPanel.hide();
    OceanRasterModel.cleanup(overlayId);
    console.log(`OverlayController: Cleared ocean raster ${overlayId}`);
  },

  /**
   * Load and display an overlay.
   * Uses year-based lazy loading: only loads current year initially.
   * Additional years are loaded on-demand as user navigates time.
   * @param {string} overlayId - Overlay ID
   */
  async loadOverlay(overlayId) {
    const endpoint = OVERLAY_ENDPOINTS[overlayId];
    if (!endpoint) {
      console.warn(`OverlayController: No endpoint for overlay: ${overlayId}`);
      return;
    }

    // Prevent duplicate loads
    if (this.loading.has(overlayId)) {
      console.log(`OverlayController: Already loading ${overlayId}`);
      return;
    }

    // Abort any existing request for this overlay
    if (this.abortControllers.has(overlayId)) {
      this.abortControllers.get(overlayId).abort();
    }

    // Create new AbortController for this request
    const abortController = new AbortController();
    this.abortControllers.set(overlayId, abortController);

    this.loading.add(overlayId);

    try {
      // If range already loaded (cache exists), just re-render without fetching
      // This handles re-enable after hide (0 features is still "loaded")
      if (this.hasCompletedRangeForCurrentFilters(overlayId, endpoint)) {
        console.log(`OverlayController: ${overlayId} already loaded, re-rendering from cache`);
        this.loading.delete(overlayId);
        this.renderCurrentData(overlayId);

        // If live mode is active, immediately fetch delta to catch up
        if (TimeSlider?.isLiveMode) {
          const FIVE_MIN = 5 * 60 * 1000;
          const now = Math.floor(Date.now() / FIVE_MIN) * FIVE_MIN;
          const ranges = loadedRanges[overlayId].filter(r => !r.loading);
          const lastEnd = Math.max(...ranges.map(r => r.end));
          if (now > lastEnd) {
            console.log(`OverlayController: ${overlayId} catching up delta in live mode`);
            loadRangeData(overlayId, lastEnd, now, OVERLAY_ENDPOINTS[overlayId]).then(loaded => {
              if (loaded) this.renderCurrentData(overlayId);
            });
          }
        }
        return;
      }

      // Load initial retained data. Ops event-history overlays use the feed-retention window.
      // Round to 5-minute intervals to prevent duplicate fetches from ms drift
      const FIVE_MIN = 5 * 60 * 1000;
      const now = Math.floor(Date.now() / FIVE_MIN) * FIVE_MIN;
      const initialWindowMs = this._usesOpsRetainedHistoryWindow(overlayId)
        ? OPS_RETAINED_HISTORY_MS
        : 30 * 24 * 60 * 60 * 1000;
      const initialWindowLabel = this._usesOpsRetainedHistoryWindow(overlayId)
        ? 'Ops retained history'
        : 'past 30 days';
      const initialWindowStart = now - initialWindowMs;

      // Respect maxYear constraint (e.g., floods end at 2019)
      let endMs = now;
      let startMs = initialWindowStart;
      if (endpoint.maxYear) {
        const maxEndMs = new Date(endpoint.maxYear, 11, 31).getTime();
        if (endMs > maxEndMs) {
          endMs = maxEndMs;
          startMs = endMs - initialWindowMs;
        }
      }

      console.log(`OverlayController: Loading ${overlayId} (${initialWindowLabel})`);

      // Load the range data
      const loaded = await loadRangeData(overlayId, startMs, endMs, endpoint, abortController.signal);

      // Check if overlay was disabled while we were fetching
      const activeOverlays = OverlaySelector?.getActiveOverlays() || [];
      if (!activeOverlays.includes(overlayId)) {
        console.log(`OverlayController: ${overlayId} was disabled during fetch, discarding data`);
        return;
      }

      // Initialize TimeSlider for this overlay
      if (endpoint.yearField && TimeSlider && !this.suppressTimelineAutoShow) {
        const currentYear = getCurrentUtcYear();
        const minYear = 2000;
        const maxYear = currentYear;

        // yearRangeCache[overlayId] is written by loadRangeData itself (via
        // recordYearRangeCoverage) on a successful fetch above -- no need to
        // initialize it here as well.

        TimeSlider.setTimeRange({
          min: minYear,
          max: maxYear,
          granularity: 'yearly',
          available: null
        });
        this.showTimelineIfAllowed();
        console.log(`OverlayController: TimeSlider range ${minYear}-${maxYear}, loaded past 30 days`);
      }

      // Render with current time (uses lifecycle filtering if enabled)
      this.renderCurrentData(overlayId);

    } catch (error) {
      if (error.name === 'AbortError') {
        console.log(`OverlayController: Fetch aborted for ${overlayId}`);
        return;
      }
      console.error(`OverlayController: Failed to load ${overlayId}:`, error);
      this.showError(overlayId, error.message);
    } finally {
      this.loading.delete(overlayId);
      this.abortControllers.delete(overlayId);
    }
  },

  /**
   * Filter cached data and render.
   * Supports both year-based filtering (legacy) and timestamp-based lifecycle filtering (new).
   * @param {string} overlayId - Overlay ID
   * @param {number|null} yearOrTimestamp - Year or timestamp to filter by
   * @param {object} options - Optional settings
   * @param {boolean} options.useTimestamp - If true, treat value as timestamp for lifecycle filtering
   */
  renderFilteredData(overlayId, yearOrTimestamp, options = {}) {
    const endpoint = OVERLAY_ENDPOINTS[overlayId];
    const cachedData = dataCache[overlayId];

    if (!endpoint || !cachedData) return;

    const activeAnimatorType = String(
      EventAnimator?.config?.rendererOptions?.eventType
      || EventAnimator?.config?.eventType
      || ''
    ).trim();
    if (EventAnimator?.getIsActive?.() && activeAnimatorType && activeAnimatorType === endpoint.eventType) {
      console.log(`OverlayController: Skipping base render for ${overlayId} while focused ${activeAnimatorType} animation is active`);
      return;
    }

    let filteredGeojson;
    const useTimestamp = options.useTimestamp && useLifecycleFiltering;

    if (useTimestamp && yearOrTimestamp) {
      const currentMs = yearOrTimestamp;
      const hasTemporalBounds = Boolean(TimeSlider?.hasActiveTrimBounds?.());
      const bounds = hasTemporalBounds ? TimeSlider.getEffectiveBounds?.() : null;
      const filtered = hasTemporalBounds && Number.isFinite(bounds?.min) && Number.isFinite(bounds?.max)
        ? filterByTemporalWindow(
            cachedData.features,
            bounds.min,
            bounds.max,
            endpoint.eventType
          )
        : filterByLifecycle(
            cachedData.features,
            currentMs,
            endpoint.eventType
          );

      filteredGeojson = {
        type: 'FeatureCollection',
        features: filtered
      };
      if (hasTemporalBounds && Number.isFinite(bounds?.min) && Number.isFinite(bounds?.max)) {
        const minStr = new Date(bounds.min).toISOString().split('T')[0];
        const maxStr = new Date(bounds.max).toISOString().split('T')[0];
        console.log(`OverlayController: Temporal window filtered ${cachedData.features.length} -> ${filtered.length} for ${minStr} to ${maxStr}`);
      } else {
        const dateStr = new Date(currentMs).toISOString().split('T')[0];
        console.log(`OverlayController: Lifecycle filtered ${cachedData.features.length} -> ${filtered.length} for ${dateStr}`);
      }
    } else if (endpoint.yearField && yearOrTimestamp) {
      // LEGACY: Year-based filtering
      const yearNum = parseInt(yearOrTimestamp);
      const filtered = cachedData.features.filter(f => {
        const propYear = f.properties[endpoint.yearField];
        if (propYear == null) return false;
        return parseInt(propYear) === yearNum;
      });
      filteredGeojson = {
        type: 'FeatureCollection',
        features: filtered
      };
      console.log(`OverlayController: Filtered ${cachedData.features.length} -> ${filtered.length} for year ${yearNum}`);
    } else {
      filteredGeojson = cachedData;
    }

    const exactEventId = String(this.exactEventFilters.get(overlayId) || '').trim();
    if (exactEventId) {
      filteredGeojson = {
        ...filteredGeojson,
        features: (Array.isArray(filteredGeojson?.features) ? filteredGeojson.features : []).filter((feature) => {
          const props = feature?.properties || {};
          return String(props.event_id || props.storm_id || feature?.id || '').trim() === exactEventId;
        })
      };
      console.log(`OverlayController: Applied exact-event filter for ${overlayId} -> ${filteredGeojson.features.length} feature(s)`);
    }

    // Render using appropriate model
    const rendered = ModelRegistry?.render(filteredGeojson, endpoint.eventType, {
      onEventClick: (props) => this.handleEventClick(overlayId, props)
    });

    if (rendered) {
      const timeStr = useTimestamp
        ? ` at ${new Date(yearOrTimestamp).toISOString().split('T')[0]}`
        : (yearOrTimestamp ? ` for ${yearOrTimestamp}` : ' (all years)');
      console.log(`OverlayController: Rendered ${filteredGeojson.features?.length || 0} ${overlayId}${timeStr}`);
    }
  },

  /**
   * Clear an overlay from the map.
   * @param {string} overlayId - Overlay ID
   */
  /**
   * Hide overlay from map without clearing cache.
   * Called when overlay is toggled off - data stays in cache for re-enable.
   * @param {string} overlayId - Overlay ID
   */
  hideOverlay(overlayId) {
    this.clearExactEventFilter?.(overlayId);

    if (isSharedMetricOverlay(overlayId)) {
      const activeOverlays = OverlaySelector?.getActiveOverlays?.() || [];
      const anyMetricActive = activeOverlays.some((id) => isSharedMetricOverlay(id));
      MapAdapter?.setChoroplethVisible?.(anyMetricActive);
      console.log(`OverlayController: Hidden ${overlayId} (choropleth visibility updated)`);
      return;
    }

    const endpoint = OVERLAY_ENDPOINTS[overlayId];
    if (!endpoint) return;

    // Abort any in-flight fetch request for this overlay
    if (this.abortControllers.has(overlayId)) {
      this.abortControllers.get(overlayId).abort();
      this.abortControllers.delete(overlayId);
      console.log(`OverlayController: Aborted pending fetch for ${overlayId}`);
    }
    this.loading.delete(overlayId);

    // Stop any active animations/drill-downs for this overlay
    this._cleanupOverlayAnimations(overlayId);

    // Clear visual layers from map (but keep dataCache intact)
    const model = ModelRegistry?.getModelForType(endpoint.eventType);
    if (model) {
      if (model.clearType) {
        model.clearType(endpoint.eventType);
      } else if (model.clear) {
        model.clear();
      }
    }

    // Also clear polygon layers for split-render types
    const eventType = endpoint.eventType;
    if (eventType === 'wildfire' || eventType === 'flood') {
      const polygonModel = ModelRegistry?.getModel('polygon');
      if (polygonModel?.isTypeActive?.(eventType)) {
        polygonModel.clearType(eventType);
      }
    }

    // Hide popup if showing this overlay's data
    if (MapAdapter?.popup?.isOpen?.()) {
      MapAdapter.hidePopup();
      MapAdapter.popupLocked = false;
    }

    // Recalculate TimeSlider range from remaining active overlays
    this.recalculateTimeRange();

    console.log(`OverlayController: Hidden ${overlayId} (cache preserved)`);
  },

  /**
   * Clear overlay completely - removes from map AND deletes cache.
   * Called from Loaded tab "Clear" button.
   * @param {string} overlayId - Overlay ID
   */
  clearOverlay(overlayId) {
    // First hide from map
    this.hideOverlay(overlayId);

    // Then clear caches
    delete dataCache[overlayId];
    delete yearRangeCache[overlayId];
    delete loadedYears[overlayId];
    overlayLedger.clearSource(overlayId);
    delete loadedRanges[overlayId];

    // Dispatch cache update for Loaded tab
    window.dispatchEvent(new CustomEvent('overlayCacheUpdated', { detail: calculateCacheSize() }));

    console.log(`OverlayController: Cleared ${overlayId} (cache deleted)`);
  },

  /**
   * Cleanup any active animations or drill-down layers for a specific overlay.
   * Called when an overlay is toggled off to prevent orphaned layers on the map.
   * @private
   * @param {string} overlayId - Overlay ID being disabled
   */
  _cleanupOverlayAnimations(overlayId) {
    // When called from clearOverlay, skip restore since the overlay is being disabled
    const skipRestore = true;

    switch (overlayId) {
      case 'hurricanes':
        this.stopHurricaneRollingAnimation();
        break;

      case 'wildfires':
        // Exit any active wildfire animations (skip restore - overlay is being disabled)
        if (this._wildfireImpactState) this._exitWildfireImpact(skipRestore);
        if (this._wildfirePerimeterState) this._exitWildfirePerimeter(skipRestore);
        if (this._fireAnimState) this._exitFireAnimation(skipRestore);
        break;

      case 'floods':
        // Exit any active flood animations (skip restore - overlay is being disabled)
        if (this._floodAnimState) this._exitFloodAnimation(skipRestore);
        if (this._floodImpactState) this._exitFloodImpact(skipRestore);
        break;

      case 'volcanoes':
        // Exit volcano impact radius animation
        if (this._volcanoImpactState) this._exitVolcanoImpact();
        break;

      case 'tornadoes':
        // Exit tornado point animation
        if (this._tornadoPointAnimState) this._exitTornadoPointAnimation();
        // Also stop EventAnimator if running a tornado sequence
        if (EventAnimator.getIsActive() && EventAnimator.config?.rendererOptions?.eventType === 'tornado') {
          EventAnimator.stop();
        }
        break;

      case 'earthquakes':
        // Stop EventAnimator if running an aftershock sequence
        if (EventAnimator.getIsActive() && EventAnimator.config?.rendererOptions?.eventType === 'earthquake') {
          EventAnimator.stop();
        }
        break;

      case 'tsunamis':
        // Stop EventAnimator if running a tsunami wave animation
        if (EventAnimator.getIsActive() && EventAnimator.config?.rendererOptions?.eventType === 'tsunami') {
          EventAnimator.stop();
        }
        break;
    }
  },

  /**
   * Recalculate TimeSlider range as the UNION of time coverage across ALL
   * active overlays -- event timestamps, frame-stack raster timelines (ocean
   * grid), and year-keyed overlays together. Loading a narrower dataset must
   * never contract the slider below what another active overlay covers: the
   * slider spans the union, and each overlay simply has nothing to show
   * outside its own coverage (ocean animates from 1982 while earthquakes
   * only appear from their first loaded year).
   * This is a coverage query -- once the shared coverage ledger exists
   * (METRIC_DIFF_LOADING_PLAN.md), it becomes a ledger lookup.
   * Also called when an overlay is disabled, to contract the range.
   */
  recalculateTimeRange() {
    if (!TimeSlider) return;

    const activeOverlayIds = OverlaySelector?.getActiveOverlays?.() || [];
    const timestamps = [];
    const years = new Set();

    for (const overlayId of activeOverlayIds) {
      // Event overlays: real event timestamps from the cache
      timestamps.push(...collectOverlayEventTimestamps(overlayId));

      // Frame-stack rasters (ocean grid): the merged bundle timeline
      if (OceanRasterModel.hasInstance(overlayId)) {
        timestamps.push(...OceanRasterModel.getTimestamps(overlayId));
      }

      // Year-keyed overlays (weather grid, event year ranges)
      const yearRange = yearRangeCache[overlayId];
      if (yearRange) {
        for (const year of yearRange.available || []) years.add(year);
        if (Number.isFinite(yearRange.min)) years.add(yearRange.min);
        if (Number.isFinite(yearRange.max)) years.add(yearRange.max);
      }
    }

    if (timestamps.length === 0 && years.size > 0) {
      // Pure year-keyed overlays: keep the year lane (bare year integers)
      const sortedYears = Array.from(years).sort((a, b) => a - b);
      TimeSlider.setTimeRange({
        min: sortedYears[0],
        max: sortedYears[sortedYears.length - 1],
        granularity: 'yearly',
        available: sortedYears,
        replace: true  // Allow contracting the range
      });
      console.log(`OverlayController: Recalculated yearly timeline ${sortedYears[0]}-${sortedYears[sortedYears.length - 1]}`);
      return;
    }

    if (timestamps.length === 0) {
      console.log('OverlayController: No active overlays with time coverage, TimeSlider range unchanged');
      return;
    }

    // Mixed or timestamp coverage: fold year coverage in as Jan 1 timestamps
    // so one continuous timeline spans every active overlay.
    for (const year of years) {
      timestamps.push(Date.UTC(year, 0, 1));
    }

    const sortedTimestamps = [...new Set(timestamps)]
      .filter((value) => Number.isFinite(value))
      .sort((a, b) => a - b);

    TimeSlider.setTimeRange({
      min: sortedTimestamps[0],
      max: sortedTimestamps[sortedTimestamps.length - 1],
      granularity: 'timestamp',
      available: sortedTimestamps,
      replace: true
    });
    console.log(`OverlayController: Recalculated union timeline with ${sortedTimestamps.length} points across ${activeOverlayIds.length} overlays`);
  },

  /**
   * Handle click on an event feature.
   * @param {string} overlayId - Overlay ID
   * @param {Object} props - Feature properties
   * @param {Array} coords - Optional coordinates [lng, lat] for popup placement
   */
  handleEventClick(overlayId, props, coords = null) {
    console.log(`OverlayController: Clicked ${overlayId} event:`, props);

    // For hurricanes, show popup with View Track button
    if (overlayId === 'hurricanes' && props.storm_id) {
      this._showHurricanePopup(props, coords);
    }
  },

  /**
   * Show popup for hurricane track with View Track button.
   * @private
   */
  _showHurricanePopup(props, coords) {
    showHurricanePopup(props, coords, {
      map: MapAdapter?.map,
      onViewTrack: (stormId, stormName) => this.drillDownHurricane(stormId, stormName)
    });
  },

  /**
   * Drill down into a hurricane track for animation.
   * Uses global IBTrACS API endpoint.
   * @param {string} stormId - Storm ID (e.g., "2005236N23285" for Katrina)
   * @param {string} stormName - Storm name
   */
  async drillDownHurricane(stormId, stormName) {
    try {
      await showHurricaneTrackDetail(stormId, stormName, {
        fetcher: fetchMsgpack,
        hideHurricaneOverlay: () => this._hideHurricaneOverlay(),
        modelRegistry: ModelRegistry,
        onAddAnimateTrackButton: (nextStormId, nextStormName, positions) => this._addAnimateTrackButton(nextStormId, nextStormName, positions),
        onSetCurrentTrackData: (trackData) => {
          this._currentTrackData = trackData;
        },
        onSetupTrackPositionClickHandler: (trackModel) => this._setupTrackPositionClickHandler(trackModel)
      });
    } catch (error) {
      console.error(`OverlayController: Failed to load hurricane track:`, error);
    }
  },

  /**
   * Add track control buttons (Animate Track + Back to Storms).
   * Positioned at top center to avoid overlapping TimeSlider.
   * @private
   */
  _addAnimateTrackButton(stormId, stormName, positions) {
    addHurricaneTrackButton(stormId, stormName, positions, {
      onExitTrackView: () => this._exitTrackView(),
      onStartTrackAnimation: (nextStormId, nextStormName, nextPositions) => this._startTrackAnimation(nextStormId, nextStormName, nextPositions)
    });
  },

  /**
   * Exit track view and return to yearly storm overview.
   * @private
   */
  _exitTrackView() {
    exitHurricaneTrackView({
      modelRegistry: ModelRegistry,
      onRestoreHurricaneOverlay: () => this._restoreHurricaneOverlay(),
      onSetCurrentTrackData: (trackData) => {
        this._currentTrackData = trackData;
      }
    });
  },

  /**
   * Start track animation using TrackAnimator.
   * @private
   */
  _startTrackAnimation(stormId, stormName, positions) {
    startHurricaneTrackAnimation(stormId, stormName, positions, {
      modelRegistry: ModelRegistry,
      onReloadTrack: (nextStormId, nextStormName) => this.drillDownHurricane(nextStormId, nextStormName)
    });
  },

  /**
   * Setup click handler for track position dots.
   * Shows wind radii and popup when clicking on a position.
   * @private
   */
  _setupTrackPositionClickHandler(trackModel) {
    bindTrackPositionClickHandler(trackModel, {
      map: MapAdapter?.map,
      currentHandler: this._trackPositionClickHandler,
      onSetHandler: (handler) => {
        this._trackPositionClickHandler = handler;
      }
    });
  },

  /**
   * Refresh all active overlays (e.g., when time changes).
   */
  async refreshActive() {
    const activeOverlays = OverlaySelector?.getActiveOverlays() || [];

    for (const overlayId of activeOverlays) {
      if (overlayId !== 'demographics' && OVERLAY_ENDPOINTS[overlayId]) {
        await this.loadOverlay(overlayId);
      }
    }
  },

  /**
   * Show error notification for failed overlay load.
   * @param {string} overlayId - Overlay ID
   * @param {string} message - Error message
   */
  showError(overlayId, message) {
    // For now, just console error
    // TODO: Add toast notification UI
    console.error(`Failed to load ${overlayId}: ${message}`);
  },

  /**
   * Get cached data for an overlay.
   * @param {string} overlayId - Overlay ID
   * @returns {Object|null} Cached GeoJSON or null
   */
  getCachedData(overlayId) {
    return getOverlayCachedData(overlayId);
  },

  setExactEventFilter(overlayId, eventId) {
    const normalizedOverlayId = String(overlayId || '').trim();
    const normalizedEventId = String(eventId || '').trim();
    if (!normalizedOverlayId) return;
    if (!normalizedEventId) {
      this.exactEventFilters.delete(normalizedOverlayId);
      return;
    }
    this.exactEventFilters.set(normalizedOverlayId, normalizedEventId);
  },

  clearExactEventFilter(overlayId) {
    const normalizedOverlayId = String(overlayId || '').trim();
    if (!normalizedOverlayId) return;
    this.exactEventFilters.delete(normalizedOverlayId);
  },

  /**
   * Re-render all active overlays from cache (no data fetching).
   * Use after map style changes that clear layers but shouldn't reload data.
   */
  rerenderFromCache() {
    const activeOverlays = OverlaySelector?.getActiveOverlays() || [];

    for (const overlayId of activeOverlays) {
      if (overlayId === 'demographics') continue;
      if (!dataCache[overlayId]) continue;

      const endpoint = OVERLAY_ENDPOINTS[overlayId];
      if (!endpoint) continue;

      // Projection/style switches can leave the map in an in-between state
      // where a source still exists but its custom layers were dropped. Force a
      // visual rebuild from cache instead of relying on model.update/setData.
      const model = ModelRegistry?.getModelForType(endpoint.eventType);
      if (model) {
        if (model.clearType) {
          model.clearType(endpoint.eventType);
        } else if (model.clear) {
          model.clear();
        }
      }

      // Split-render event types own a secondary polygon model on top of the
      // point/event model. Clear that too so the cached render fully rebuilds.
      if (endpoint.eventType === 'wildfire' || endpoint.eventType === 'flood') {
        const polygonModel = ModelRegistry?.getModel('polygon');
        if (polygonModel?.clearType) {
          polygonModel.clearType(endpoint.eventType);
        }
      }

      // Use current time slider state to render
      if (useLifecycleFiltering && TimeSlider?.currentTime) {
        this.renderFilteredData(overlayId, TimeSlider.currentTime, { useTimestamp: true });
      } else {
        const year = TimeSlider?.currentTime ? this.getYearFromTime(TimeSlider.currentTime) : getCurrentUtcYear();
        this.renderFilteredData(overlayId, year);
      }
    }

    console.log('OverlayController: Re-rendered overlays from cache');
  },

  /**
   * Clear all overlay caches.
   */
  clearCache() {
    clearAllOverlayCaches();
  },

  /**
   * Get loaded years for an overlay.
   * @param {string} overlayId - Overlay ID
   * @returns {Array} Array of loaded years
   */
  getLoadedYears(overlayId) {
    return getLoadedYearsForOverlay(overlayId);
  },

  /**
   * Get the filter thresholds that were used when loading data.
   * This tells chat what data is actually in cache vs what's currently displayed.
   * Example: loaded M5.0+ but displaying M6.0+ - can filter to M5.5+ from cache.
   * @param {string} overlayId - Overlay ID
   * @returns {Object} Filter thresholds used at load time
   */
  getLoadedFilters(overlayId) {
    return getLoadedFiltersForOverlay(overlayId);
  },

  /**
   * Get cache statistics for monitoring memory usage.
   * Call from console: OverlayController.getCacheStats()
   * @returns {Object} Cache statistics
   */
  getCacheStats() {
    return getOverlayCacheStats(OVERLAY_ENDPOINTS);
  },

  /**
   * Get current filter settings for an overlay.
   * Returns active overrides merged with defaults from OVERLAY_ENDPOINTS.
   * @param {string} overlayId - Overlay ID
   * @returns {Object} Current filter settings
   */
  getActiveFilters(overlayId) {
    return getActiveFiltersForOverlay(overlayId, OVERLAY_ENDPOINTS);
  },

  /**
   * Update filter settings for an overlay.
   * Triggers cache clear and data reload.
   * @param {string} overlayId - Overlay ID
   * @param {Object} newFilters - New filter values to apply
   */
  updateFilters(overlayId, newFilters) {
    updateOverlayFilters(overlayId, newFilters, OVERLAY_ENDPOINTS);
  },

  /**
   * Clear filter overrides for an overlay (revert to defaults).
   * @param {string} overlayId - Overlay ID
   */
  clearFilters(overlayId) {
    clearOverlayFilters(overlayId);
  },

  /**
   * Reload an overlay with current filter settings.
   * Clears cache and refetches data.
   * @param {string} overlayId - Overlay ID
   */
  async reloadOverlay(overlayId) {
    if (!OVERLAY_ENDPOINTS[overlayId]) {
      console.warn(`Unknown overlay: ${overlayId}`);
      return;
    }

    console.log(`OverlayController: Reloading ${overlayId} with filters:`, this.getActiveFilters(overlayId));

    const preservedRanges = Array.isArray(loadedRanges[overlayId])
      ? loadedRanges[overlayId]
        .filter((range) => range && !range.loading && Number.isFinite(range.start) && Number.isFinite(range.end))
        .map((range) => ({ start: range.start, end: range.end }))
      : [];

    // Clear cache for this overlay
    clearOverlayData(overlayId);

    // Check if overlay is currently active
    const isActive = OverlaySelector?.getActiveOverlays()?.includes(overlayId);
    if (!isActive) {
      console.log(`OverlayController: ${overlayId} not active, skipping reload`);
      return;
    }

    if (preservedRanges.length > 0) {
      console.log(`OverlayController: Restoring ${overlayId} across ${preservedRanges.length} cached range(s)`);
      for (const range of preservedRanges) {
        await loadRangeData(overlayId, range.start, range.end, OVERLAY_ENDPOINTS[overlayId]);
      }
      this.renderCurrentData(overlayId);
      return;
    }

    // Reload the overlay
    await this.loadOverlay(overlayId);
  },

  /**
   * Refresh all active overlays with new data since last fetch.
   * Called by live-data-poll (every 5 min) and live-lock-engaged events.
   * Only fetches the delta (from last loaded end to now), not the full 30 days.
   */
  async refreshLiveOverlays() {
    const activeOverlays = OverlaySelector?.getActiveOverlays() || [];
    if (activeOverlays.length === 0) return;

    const FIVE_MIN = 5 * 60 * 1000;
    const now = Math.floor(Date.now() / FIVE_MIN) * FIVE_MIN;

    console.log(`OverlayController: Live refresh for ${activeOverlays.length} overlays`);

    for (const overlayId of activeOverlays) {
      const endpoint = OVERLAY_ENDPOINTS[overlayId];
      if (!endpoint || endpoint.isWeatherGrid) continue;

      // Skip if no ranges loaded yet (overlay hasn't done initial load)
      const ranges = loadedRanges[overlayId];
      if (!ranges || ranges.length === 0) continue;

      // Find the latest end time across all loaded ranges
      const lastEnd = Math.max(...ranges.filter(r => !r.loading).map(r => r.end));
      if (now <= lastEnd) {
        // Already up to date (within same 5-min window)
        continue;
      }

      console.log(`OverlayController: Refreshing ${overlayId} delta (${new Date(lastEnd).toISOString()} to ${new Date(now).toISOString()})`);

      try {
        const loaded = await loadRangeData(overlayId, lastEnd, now, endpoint);
        if (loaded !== false) {
          this.renderCurrentData(overlayId);
        }
      } catch (err) {
        console.warn(`OverlayController: Live refresh failed for ${overlayId}:`, err.message);
      }
    }
  },

  /**
   * Ingest order result data into the overlay cache.
   * Called by the order/chat system when a disaster data order completes.
   * Merges the GeoJSON features into existing cache and re-renders.
   * @param {string} overlayId - Overlay ID (e.g., 'earthquakes', 'hurricanes')
   * @param {Object} geojson - GeoJSON FeatureCollection from the order result
   * @param {Object} rangeMeta - Optional range metadata {start, end} in ms
   */
  ingestOrderResult(overlayId, geojson, rangeMeta = null, responseMeta = null) {
    if (!geojson?.features || !OVERLAY_ENDPOINTS[overlayId]) {
      console.warn(`OverlayController: Cannot ingest - invalid data or unknown overlay: ${overlayId}`);
      return;
    }

    const expectedOverlayId =
      resolveOverlayIdFromSourceId(responseMeta?.source_id || responseMeta?.layer_source_id || '')
      || resolveOverlayIdFromPackId(responseMeta?.pack_id || responseMeta?.layer_pack_id || '');
    if (expectedOverlayId && expectedOverlayId !== overlayId) {
      console.warn(
        `OverlayController: Rejecting cross-overlay ingest for ${overlayId}; payload belongs to ${expectedOverlayId}`,
        {
          source_id: responseMeta?.source_id || responseMeta?.layer_source_id || null,
          pack_id: responseMeta?.pack_id || responseMeta?.layer_pack_id || null
        }
      );
      return;
    }

    // Initialize cache if needed
    if (!dataCache[overlayId]) {
      dataCache[overlayId] = { type: 'FeatureCollection', features: [] };
    }

    // Merge new features (dedup by event_id)
    const existingIds = new Set(
      dataCache[overlayId].features
        .map(f => f.properties?.event_id || f.properties?.storm_id || f.id)
        .filter(Boolean)
    );

    const newFeatures = geojson.features.filter(f => {
      const id = f.properties?.event_id || f.properties?.storm_id || f.id;
      return !id || !existingIds.has(id);
    });

    if (newFeatures.length > 0) {
      dataCache[overlayId].features.push(...newFeatures);
      console.log(`OverlayController: Ingested ${newFeatures.length} ${overlayId} features from order (total: ${dataCache[overlayId].features.length})`);
    } else {
      console.log(`OverlayController: Order result had no new ${overlayId} features (all duplicates)`);
    }

    // Track the loaded range if metadata provided. Order results are handed
    // over already-fetched in full for [start, end], so mark the whole span
    // loaded (yearsFullyLoaded) rather than applying loadRangeData's
    // 6-month partial-year threshold. Year coverage is derived from this on
    // read (see isYearLoaded / getLoadedYearsForOverlay in
    // overlay-cache-ops.js) -- no separate loadedYears write needed.
    if (rangeMeta && rangeMeta.start && rangeMeta.end) {
      if (!loadedRanges[overlayId]) {
        loadedRanges[overlayId] = [];
      }
      loadedRanges[overlayId].push({
        start: rangeMeta.start,
        end: rangeMeta.end,
        loading: false,
        yearsFullyLoaded: true
      });
      recordYearRangeCoverage(overlayId, rangeMeta.start, rangeMeta.end);
      // TASK L2: mirror onto the ledger with filters '' -- this entry never
      // set filterSignature (falls back to '' in the old (range.filterSignature
      // || '') checks), so recordFullyLoadedRangeClaim with '' reproduces
      // that exact fallback, including the edge case where an endpoint's
      // real signature is also '' (e.g. tsunamis' empty default params).
      recordFullyLoadedRangeClaim(overlayId, rangeMeta.start, rangeMeta.end, '');
    }

    // Update cache size
    const cacheSize = calculateCacheSize();
    window.dispatchEvent(new CustomEvent('overlayCacheUpdated', { detail: cacheSize }));

    // Re-render if overlay is active
    const activeOverlays = OverlaySelector?.getActiveOverlays() || [];
    if (activeOverlays.includes(overlayId)) {
      this.recalculateTimeRange();
      this.showTimelineIfAllowed();
      this.renderCurrentData(overlayId);
    }
  },

  /**
   * Ingest metrics/choropleth data from order system into cache.
   * Called by the chat system when a metrics order completes.
   * @param {string} sourceId - Source ID (e.g., 'owid_co2', 'census_population')
   * @param {Object} geojson - GeoJSON FeatureCollection from the order result
   * @param {Object} timeData - Optional temporal cell map keyed by time
   * @param {Object} timeRange - Optional temporal metadata {min, max, available, granularity}
   */
  ingestMetricData(sourceId, geojson, timeData = null, timeRange = null, meta = {}) {
    ingestOverlayMetricData(sourceId, geojson, timeData, timeRange, meta);
  },

  /**
   * Get cached metric data for a source.
   * @param {string} sourceId - Source ID
   * @returns {Object|null} Cached data or null if not cached
   */
  getCachedMetricData(sourceId) {
    return getOverlayCachedMetricData(sourceId);
  },

  /**
   * Clear metric data for a source from cache.
   * @param {string} sourceId - Source ID to clear
   */
  clearMetricCache(sourceId) {
    clearMetricCacheEntry(sourceId);
  },

  // -------------------------------------------------------------------------
  // Geometry Cache (for geometry orders - ZCTA, tribal, watersheds, etc.)
  // Deduplicates by loc_id, similar to event_id dedup for events.
  // -------------------------------------------------------------------------
  // Geometry Order Rendering
  // Note: Backend SessionCache handles deduplication. Frontend just renders.
  // -------------------------------------------------------------------------

  /**
   * Render geometry data from a chat order (ZCTA, tribal, etc.)
   * Backend SessionCache handles deduplication - frontend just renders.
   * @param {string} sourceId - Source ID (e.g., 'geometry_zcta')
   * @param {Object} geojson - GeoJSON FeatureCollection from the order result
   * @param {string} geometryType - Geometry type for rendering ('zcta', 'tribal', etc.)
   * @param {Object} options - Render options (showLabels, etc.)
   * @returns {number} Number of features rendered
   */
  renderGeometryData(sourceId, geojson, geometryType = 'zcta', options = {}) {
    return renderOverlayGeometryData(sourceId, geojson, geometryType, options);
  },

  /**
   * Refresh geometry display from cache.
   * Called when overlay is turned on or when new data arrives while overlay is already on.
   */
  refreshGeometryFromCache() {
    refreshCachedGeometry();
  },

  /**
   * Remove geometry features from cache and re-render.
   * Supports two removal modes (backend-driven preferred):
   * 1. loc_ids: Exact list from backend (keeps caches in sync)
   * 2. regions: Prefix-based removal (fallback)
   *
   * @param {string} sourceId - Source ID (e.g., 'geometry_zcta')
   * @param {Object} criteria - Removal criteria
   * @param {Array} [criteria.loc_ids] - Specific loc_ids to remove (preferred, from backend)
   * @param {Array} [criteria.regions] - Regions to remove by prefix (e.g., ['USA-FL'])
   * @param {string} geometryType - Geometry type for rendering ('zcta', 'tribal', etc.)
   * @returns {Object} { removed: number, remaining: number }
   */
  removeGeometryData(sourceId, criteria, geometryType = 'zcta') {
    return removeOverlayGeometryData(sourceId, criteria, geometryType);
  },

  /**
   * Remove event data from cache by event_ids.
   * Like removing rows from a feature collection.
   *
   * @param {string} sourceId - Source ID (e.g., 'earthquakes_usgs')
   * @param {Object} criteria - Removal criteria
   * @param {Array} [criteria.event_ids] - Specific event_ids to remove
   * @param {Array} [criteria.regions] - Regions to remove by loc_id prefix
   * @returns {Object} { removed: number, remaining: number }
   */
  removeEventData(sourceId, criteria) {
    return removeOverlayEventData(sourceId, criteria);
  },

  /**
   * Route a chat-order events result through the shared overlay system so it
   * gets the same lifecycle animation and timeline as a toggled overlay --
   * chat results and overlay toggles are ONE display path, not two.
   * Seeds the overlay cache with the returned features, activates the
   * overlay, and renders at the current playhead.
   *
   * @param {string} overlayId - Resolved overlay id (e.g. 'earthquakes')
   * @param {Object} geojson - FeatureCollection from the order response
   * @param {Object|null} timeRange - {min, max} ms range from the response
   * @returns {boolean} true if the overlay path handled the display
   */
  applyEventOrderResult(overlayId, geojson, timeRange = null) {
    const normalizedOverlayId = String(overlayId || '').trim();
    if (!normalizedOverlayId || !OVERLAY_ENDPOINTS[normalizedOverlayId]) return false;
    if (!Array.isArray(geojson?.features) || !geojson.features.length) return false;

    const seeded = seedOverlayEventData(normalizedOverlayId, geojson, timeRange);
    console.log(`OverlayController: Seeded ${seeded} ${normalizedOverlayId} features from chat order`);

    if (OverlaySelector && !OverlaySelector.isActive(normalizedOverlayId)) {
      OverlaySelector.showOverlay?.(normalizedOverlayId);
      OverlaySelector.setActive(normalizedOverlayId, true);
    }

    this.recalculateTimeRange();
    this.showTimelineIfAllowed();
    this.renderCurrentData(normalizedOverlayId);
    return true;
  },

  /**
   * Remove metric data from cache - like deleting a column from a spreadsheet.
   * Removes all values for a specific metric, optionally filtered by region/years.
   *
   * @param {string} sourceId - Source ID (e.g., 'census')
   * @param {Object} criteria - Removal criteria
   * @param {Array} [criteria.loc_ids] - Specific loc_ids to remove from
   * @param {Array} [criteria.years] - Specific years to remove from
   * @param {string} [criteria.metric] - Metric column to remove
   * @returns {Object} { removed: number, remaining: number }
   */
  removeMetricData(sourceId, criteria) {
    return removeOverlayMetricData(sourceId, criteria);
  },

  /**
   * Clear geometry display for a specific type.
   * @param {string} geometryType - Geometry type for layer cleanup (zcta, tribal, etc.)
   */
  clearGeometryDisplay(geometryType = 'zcta') {
    GeometryModel.clearType(geometryType);
    console.log(`OverlayController: Cleared ${geometryType} geometry display`);
  },

  handleVolcanoHistory(data) {
    const { features, volcanoName, volcanoLat, volcanoLon, radiusKm } = data;
    console.log(`OverlayController: Displaying ${features.length} historical eruptions for ${volcanoName}`);

    if (!Array.isArray(features) || features.length === 0) {
      console.log('OverlayController: No eruption history to display');
      return;
    }

    const returnViewState = this.captureViewState();
    const geojson = {
      type: 'FeatureCollection',
      features: features.map((feature) => ({
        type: 'Feature',
        geometry: feature.geometry,
        properties: {
          ...(feature.properties || {})
        }
      }))
    };

    const model = ModelRegistry?.getModel('point-radius');
    if (model) {
      model.update(geojson, 'volcano');
    }

    const maplibre = window.maplibregl || maplibregl;
    const bounds = new maplibre.LngLatBounds();
    if (Number.isFinite(volcanoLon) && Number.isFinite(volcanoLat)) {
      bounds.extend([volcanoLon, volcanoLat]);
    }
    for (const feature of geojson.features) {
      const coords = feature?.geometry?.coordinates;
      if (Array.isArray(coords) && coords.length >= 2) {
        bounds.extend(coords);
      }
    }

    if (!bounds.isEmpty()) {
      MapAdapter.map.fitBounds(bounds, { padding: 80, maxZoom: 9, duration: 1500 });
    }

    addGenericExitButton(
      'volcano-history-exit-btn',
      'Exit History View',
      '#feb24c',
      () => {
        document.getElementById('volcano-history-exit-btn')?.remove();
        this.restoreViewState(returnViewState, ['volcanoes']);
      }
    );

    console.log(`OverlayController: Loaded volcano history view for ${volcanoName} within ${radiusKm}km`);
  },
};
