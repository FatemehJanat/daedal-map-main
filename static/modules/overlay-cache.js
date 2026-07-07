/**
 * Shared overlay cache state and cache-related helpers.
 */

import { createLedger, SEEDED_FILTERS } from './coverage-ledger.js';

export { SEEDED_FILTERS };

// Single coverage-ledger instance for the whole app (Task L2). Event overlay
// coverage bookkeeping (overlay-cache-ops.js, overlay-data-loader.js,
// overlay-controller.js) all read/write this same ledger so a claim recorded
// by one is visible to the others. See "Task L2: retrofit event overlays
// onto the ledger" in
// county-map-private/docs/future/coverage_ledger_implementation.md.
export const overlayLedger = createLedger();

/**
 * Build a range-shaped event claim: source=overlayId, metrics '*' (events
 * have no per-metric fetch granularity), geoLevel null (source-native),
 * scope 'all' (no region/loc_id scoping for events yet). filters is the
 * real buildRangeRequestSignature() output for a genuine fetch, or a
 * sentinel (SEEDED_FILTERS, or '' to mirror a pre-retrofit undefined
 * filterSignature) for data merged in without a fetch signature.
 * @param {string} overlayId
 * @param {number} startMs
 * @param {number} endMs
 * @param {string} [filters]
 * @returns {object} unnormalized claim (coverage-ledger normalizes on use)
 */
export function buildEventRangeClaim(overlayId, startMs, endMs, filters = '') {
  return {
    source: overlayId,
    metrics: '*',
    geoLevel: null,
    scope: { kind: 'all' },
    time: { kind: 'range', min: startMs, max: endMs },
    filters
  };
}

/**
 * Build a years-shaped event claim covering every calendar year touched by
 * [startMs, endMs] (inclusive of partial edge years). The ledger covers a
 * 'years' claim's years unconditionally -- no six-month threshold -- which
 * is what the legacy yearsFullyLoaded flag on seeded/order-ingested
 * loadedRanges entries meant (data handed over already-complete for its
 * span, unlike loadRangeData's real windowed fetches).
 * @param {string} overlayId
 * @param {number} startMs
 * @param {number} endMs
 * @param {string} filters
 * @returns {object} unnormalized claim
 */
export function buildEventYearsClaim(overlayId, startMs, endMs, filters) {
  const startYear = new Date(startMs).getUTCFullYear();
  const endYear = new Date(endMs).getUTCFullYear();
  const years = [];
  for (let y = startYear; y <= endYear; y++) years.push(y);
  return {
    source: overlayId,
    metrics: '*',
    geoLevel: null,
    scope: { kind: 'all' },
    time: { kind: 'years', years },
    filters
  };
}

/**
 * Record both claim shapes for event data handed over already-fetched-in-
 * full for [startMs, endMs] (seedEventData, ingestOrderResult): a 'years'
 * claim so isYearLoaded/getYearsCoveredByRanges (ledger.yearsCovered) treat
 * every touched year as loaded unconditionally, and a 'range' claim so
 * hasCompletedRangeForCurrentFilters / loadRangeData's covered-range dedup
 * see the same interval+filter match a real fetch at that filters value
 * would have produced (matters when filters === '' happens to equal an
 * endpoint's actual signature, e.g. tsunamis' empty default params -- see
 * the legacy fallback in ingestOrderResult).
 * @param {string} overlayId
 * @param {number} startMs
 * @param {number} endMs
 * @param {string} filters
 */
export function recordFullyLoadedRangeClaim(overlayId, startMs, endMs, filters) {
  overlayLedger.record(buildEventYearsClaim(overlayId, startMs, endMs, filters));
  overlayLedger.record(buildEventRangeClaim(overlayId, startMs, endMs, filters));
}

// Cache for loaded overlay data (full unfiltered datasets)
export const dataCache = {};

// Cache for metrics/choropleth data from order system.
// Canonical temporal shape is time_data/time_range. Legacy year_* mirrors may
// still appear during the migration but should be removed in a cleanup pass.
// sourceId -> { geojson, time_data, time_range, loadedAt }
export const metricCache = {};

// Track which time ranges have been loaded per overlay.
// TASK L2: this is now a thin MIRROR, not the coverage source of truth --
// coverage decisions (isYearLoaded, getYearsCoveredByRanges,
// hasCompletedRangeForCurrentFilters) read overlayLedger instead (see
// overlay-cache-ops.js / overlay-controller.js). loadedRanges is kept
// because a few call sites still need the raw {start, end} numbers rather
// than a coverage boolean: the live-mode delta catch-up read in
// OverlayController.loadOverlay/refreshLiveOverlays (max(range.end) across
// completed ranges) and reloadOverlay's preserved-ranges refetch list.
// Each entry is {start, end, loading, filterSignature} (millisecond
// timestamps); every writer of this mirror also writes a matching claim to
// overlayLedger in the same call.
export const loadedRanges = {};

// Weather-grid year cache: per-overlay Set of years fetched.
// Weather grid has no range fetches (one API call per year per variable, see
// loadWeatherYearData in overlay-data-loader.js), so it keeps its own
// year-keyed bookkeeping instead of being forced onto loadedRanges. Range-
// backed overlays (earthquakes, hurricanes, etc.) no longer write this --
// their year coverage is derived from loadedRanges (see isYearLoaded /
// getLoadedYearsForOverlay in overlay-cache-ops.js).
export const loadedYears = {};

// Cache year ranges per overlay (for recalculating combined range when
// overlays change, and for grid overlays whose fallback range calc in
// recalculateTimeRange has no per-feature timestamps to read).
// All range-shaped writers (loadRangeData, seedEventData, ingestOrderResult)
// go through the single recordYearRangeCoverage() helper below. Weather grid
// is the one exception: it writes per-year in loadWeatherYearData alongside
// loadedYears, since it has no range to derive a span from (see note above).
export const yearRangeCache = {};

// Active filter overrides per overlay (for chat-based filter modifications)
export const activeFilters = {};

// Track filters that were used when data was loaded
export const loadedFilters = {};

// All climate variables to fetch together (optimization: one API call for all)
export const CLIMATE_VARIABLES = [
  'temp_c', 'humidity', 'snow_depth_m',
  'precipitation_mm', 'cloud_cover_pct', 'pressure_hpa',
  'solar_radiation', 'soil_temp_c', 'soil_moisture'
];

export const CLIMATE_OVERLAY_MAP = {
  'temperature': 'temp_c',
  'humidity': 'humidity',
  'snow-depth': 'snow_depth_m',
  'precipitation': 'precipitation_mm',
  'cloud-cover': 'cloud_cover_pct',
  'pressure': 'pressure_hpa',
  'solar-radiation': 'solar_radiation',
  'soil-temp': 'soil_temp_c',
  'soil-moisture': 'soil_moisture'
};

export const VARIABLE_OVERLAY_MAP = {
  'temp_c': 'temperature',
  'humidity': 'humidity',
  'snow_depth_m': 'snow-depth',
  'precipitation_mm': 'precipitation',
  'cloud_cover_pct': 'cloud-cover',
  'pressure_hpa': 'pressure',
  'solar_radiation': 'solar-radiation',
  'soil_temp_c': 'soil-temp',
  'soil_moisture': 'soil-moisture'
};

function normalizeFilterOverrideEntries(overrides = {}) {
  const normalized = {};

  if (overrides.minMagnitude !== undefined) {
    normalized.min_magnitude = String(overrides.minMagnitude);
  }
  if (overrides.maxMagnitude !== undefined) {
    normalized.max_magnitude = String(overrides.maxMagnitude);
  }
  if (overrides.minCategory !== undefined) {
    normalized.min_category = `Cat${overrides.minCategory}`;
  }
  if (overrides.minScale !== undefined) {
    normalized.min_scale = `EF${overrides.minScale}`;
  }
  if (overrides.minAreaKm2 !== undefined) {
    normalized.min_area_km2 = String(overrides.minAreaKm2);
  }
  if (overrides.minVei !== undefined) {
    normalized.min_vei = String(overrides.minVei);
  }
  if (overrides.minHeightM !== undefined) {
    normalized.min_height_m = String(overrides.minHeightM);
  }
  if (overrides.minSeverity !== undefined) {
    normalized.min_severity = String(overrides.minSeverity);
  }
  if (overrides.locPrefix !== undefined) {
    normalized.loc_prefix = overrides.locPrefix;
  }
  if (overrides.affectedLocId !== undefined) {
    normalized.affected_loc_id = overrides.affectedLocId;
  }

  return normalized;
}

export function buildEffectiveRangeParams(endpoint, overlayId = null) {
  const defaultParams = endpoint?.params || {};
  const overrides = overlayId ? (activeFilters[overlayId] || {}) : {};
  return {
    ...defaultParams,
    ...normalizeFilterOverrideEntries(overrides)
  };
}

export function buildRangeRequestSignature(endpoint, overlayId = null) {
  const params = buildEffectiveRangeParams(endpoint, overlayId);
  const parts = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .sort(([a], [b]) => String(a).localeCompare(String(b)))
    .map(([key, value]) => `${key}=${String(value)}`);
  return parts.join('&');
}

/**
 * Calculate total cache size - exact bytes via JSON serialization.
 * @returns {{ totalFeatures: number, bytes: number, sizeMB: string, perOverlay: Object }}
 */
export function calculateCacheSize() {
  let totalFeatures = 0;
  let totalBytes = 0;
  const perOverlay = {};

  for (const overlayId of Object.keys(dataCache)) {
    const features = dataCache[overlayId]?.features || [];
    if (features.length > 0) {
      const bytes = new Blob([JSON.stringify(features)]).size;
      perOverlay[overlayId] = { features: features.length, bytes, type: 'events' };
      totalFeatures += features.length;
      totalBytes += bytes;
    }
  }

  for (const sourceId of Object.keys(metricCache)) {
    const cached = metricCache[sourceId];
    const features = cached?.geojson?.features || [];
    const timeData = cached?.time_data || cached?.year_data || {};
    if (features.length > 0 || Object.keys(timeData).length > 0) {
      const dataToSize = { features, time_data: timeData };
      const bytes = new Blob([JSON.stringify(dataToSize)]).size;
      perOverlay[sourceId] = { features: features.length, bytes, type: 'metrics' };
      totalFeatures += features.length;
      totalBytes += bytes;
    }
  }

  const sizeMB = (totalBytes / (1024 * 1024)).toFixed(2);
  return { totalFeatures, bytes: totalBytes, sizeMB, perOverlay };
}

/**
 * UTC year boundaries in milliseconds. Exported utility for callers that
 * need to agree on what "year N" spans; the ledger (coverage-ledger.js)
 * has its own equivalent internal yearBounds() as of Task L2, since it must
 * stay a zero-import pure module.
 * @param {number} year
 * @returns {{start: number, end: number}}
 */
export function getUtcYearRangeMs(year) {
  return {
    start: Date.UTC(year, 0, 1, 0, 0, 0, 0),
    end: Date.UTC(year, 11, 31, 23, 59, 59, 999)
  };
}

/**
 * Single writer for yearRangeCache: widen an overlay's cached min/max/available
 * years to cover [startMs, endMs]. Called from loadRangeData, seedEventData,
 * and ingestOrderResult -- the three places that learn about a newly-covered
 * span. Weather grid does not use this (see yearRangeCache comment above).
 * @param {string} overlayId
 * @param {number} startMs
 * @param {number} endMs
 */
export function recordYearRangeCoverage(overlayId, startMs, endMs) {
  const startYear = new Date(startMs).getUTCFullYear();
  const endYear = new Date(endMs).getUTCFullYear();

  if (!yearRangeCache[overlayId]) {
    yearRangeCache[overlayId] = { min: startYear, max: endYear, available: [] };
  }
  const cache = yearRangeCache[overlayId];
  cache.min = Math.min(cache.min, startYear);
  cache.max = Math.max(cache.max, endYear);
  for (let y = startYear; y <= endYear; y++) {
    if (!cache.available.includes(y)) {
      cache.available.push(y);
    }
  }
  cache.available.sort((a, b) => a - b);
}

/**
 * Build URL for fetching data within a time range.
 * @param {Object} endpoint - Endpoint config from OVERLAY_ENDPOINTS
 * @param {number} startMs - Start timestamp in milliseconds
 * @param {number} endMs - End timestamp in milliseconds
 * @param {string | null} overlayId - Overlay ID for looking up active filters
 * @returns {string}
 */
export function buildRangeUrl(endpoint, startMs, endMs, overlayId = null) {
  const url = new URL(endpoint.baseUrl, window.location.origin);
  const effectiveParams = buildEffectiveRangeParams(endpoint, overlayId);

  for (const [key, value] of Object.entries(effectiveParams)) {
    url.searchParams.set(key, value);
  }

  url.searchParams.set('start', String(startMs));
  url.searchParams.set('end', String(endMs));
  return url.toString();
}
