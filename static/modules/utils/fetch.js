/**
 * MessagePack fetch utilities
 * All API calls should use these instead of raw fetch()
 *
 * MessagePack library loaded via CDN, available as window.MessagePack
 */

import { getAccessToken, getStorageNamespace } from '../auth.js';

// Get MessagePack from global scope (loaded via CDN)
const msgpack = window.MessagePack || {};
let activeRequestCount = 0;
let loadingIndicatorTimer = null;
const activeLoadingLabels = [];

// localStorage key for tracking API calls for session recovery
const API_CALLS_KEY = 'countymap_api_calls';

// localStorage key for tracking executed orders for session recovery
const ORDERS_KEY = 'countymap_executed_orders';

// API paths that should be tracked for recovery (data endpoints)
const TRACKED_API_PATTERNS = [
  '/api/earthquakes/',
  '/api/storms/',
  '/api/volcanoes/',
  '/api/wildfires/',
  '/api/tornadoes/',
  '/api/tsunamis/',
  '/api/floods/',
  '/api/climate/'
];

function namespacedKey(baseKey) {
  return `${baseKey}:${getStorageNamespace()}`;
}

function buildAuthHeaders() {
  const token = getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function getGlobalLoadingIndicator() {
  return document.getElementById('loadingIndicator');
}

function getGlobalLoadingText() {
  return document.querySelector('#loadingIndicator .map-loading-text');
}

function inferLoadingLabel(url, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();

  if (url.includes('/geometry/index')) {
    const levelMatch = url.match(/admin_level=(\d+)/);
    const level = levelMatch ? Number(levelMatch[1]) : null;
    if (level === 0) return 'Loading countries...';
    if (level === 1) return 'Loading states...';
    if (level === 2) return 'Loading counties...';
    if (level === 3) return 'Loading local areas...';
    return 'Loading map index...';
  }
  if (url.includes('/geometry/selection')) return 'Loading map shapes...';
  if (url.includes('/geometry/countries')) return 'Loading countries...';
  if (url.includes('/geometry/viewport')) return 'Loading map view...';
  if (url.includes('/api/earthquakes/')) return 'Loading earthquakes...';
  if (url.includes('/api/storms/')) return 'Loading storms...';
  if (url.includes('/api/eruptions/') || url.includes('/api/volcanoes/')) return 'Loading volcanoes...';
  if (url.includes('/api/wildfires/')) return 'Loading wildfires...';
  if (url.includes('/api/tornadoes/')) return 'Loading tornadoes...';
  if (url.includes('/api/tsunamis/')) return 'Loading tsunamis...';
  if (url.includes('/api/floods/')) return 'Loading floods...';
  if (url.includes('/api/weather/') || url.includes('/api/climate/')) return 'Loading climate data...';
  if (url.includes('/api/catalog/')) return 'Loading catalog...';
  if (url.includes('/reference/')) return 'Loading references...';
  if (url.includes('/chat')) return 'Thinking...';
  if (method === 'POST') return 'Sending request...';
  return 'Loading data...';
}

function syncGlobalLoadingIndicator() {
  const indicator = getGlobalLoadingIndicator();
  const text = getGlobalLoadingText();
  if (!indicator) return;
  if (text) {
    text.textContent = activeLoadingLabels.length > 0
      ? activeLoadingLabels[activeLoadingLabels.length - 1]
      : 'Loading data...';
  }
  if (activeRequestCount > 0) {
    if (loadingIndicatorTimer == null) {
      loadingIndicatorTimer = window.setTimeout(() => {
        if (activeRequestCount > 0) {
          indicator.classList.add('visible');
          indicator.setAttribute('aria-hidden', 'false');
        }
        loadingIndicatorTimer = null;
      }, 150);
    }
  } else {
    if (loadingIndicatorTimer != null) {
      window.clearTimeout(loadingIndicatorTimer);
      loadingIndicatorTimer = null;
    }
    indicator.classList.remove('visible');
    indicator.setAttribute('aria-hidden', 'true');
  }
}

/**
 * Check if a URL should be tracked for session recovery.
 */
function shouldTrackCall(url) {
  return TRACKED_API_PATTERNS.some(pattern => url.includes(pattern));
}

/**
 * Log an API call to localStorage for session recovery.
 * Recovery replay is currently disabled as part of chat/session simplification.
 */
function logApiCall(url) {
  void url;
}

/**
 * Get all logged API calls for session recovery.
 */
export function getApiCallsForRecovery() {
  return [];
}

/**
 * Clear logged API calls (called by New Chat).
 */
export function clearApiCalls() {
  try {
    localStorage.removeItem(namespacedKey(API_CALLS_KEY));
  } catch (e) {
    // Ignore
  }
}

/**
 * Log an executed order for session recovery.
 * Stores only the order (request) data, not the response.
 * @param {Object} order - The order that was executed
 */
export function logExecutedOrder(order) {
  void order;
}

/**
 * Get all logged executed orders for session recovery.
 * @returns {Array} Array of {order, summary, timestamp} records
 */
export function getExecutedOrdersForRecovery() {
  return [];
}

/**
 * Clear logged executed orders (called by New Chat).
 */
export function clearExecutedOrders() {
  try {
    localStorage.removeItem(namespacedKey(ORDERS_KEY));
  } catch (e) {
    // Ignore
  }
}

/**
 * Fetch data from API endpoint with MessagePack decoding.
 * @param {string} url - API endpoint
 * @param {object} options - fetch options (optional)
 * @returns {Promise<any>} Decoded response data
 */
export async function fetchMsgpack(url, options = {}) {
  // Log data API calls for session recovery
  if (shouldTrackCall(url)) {
    logApiCall(url);
  }

  const loadingLabel = inferLoadingLabel(url, options);
  activeRequestCount += 1;
  activeLoadingLabels.push(loadingLabel);
  syncGlobalLoadingIndicator();

  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        'Accept': 'application/msgpack',
        ...buildAuthHeaders(),
        ...options.headers,
      }
    });

    if (!response.ok) {
      let errorMsg = 'Request failed';
      try {
        const buffer = await response.arrayBuffer();
        const decoded = msgpack.decode(new Uint8Array(buffer));
        errorMsg = decoded.error || errorMsg;
      } catch (e) {
        errorMsg = response.statusText;
      }
      throw new Error(errorMsg);
    }

    const buffer = await response.arrayBuffer();
    return msgpack.decode(new Uint8Array(buffer));
  } finally {
    activeRequestCount = Math.max(0, activeRequestCount - 1);
    const labelIndex = activeLoadingLabels.lastIndexOf(loadingLabel);
    if (labelIndex >= 0) {
      activeLoadingLabels.splice(labelIndex, 1);
    }
    syncGlobalLoadingIndicator();
  }
}

/**
 * POST data to API endpoint with MessagePack encoding/decoding.
 * @param {string} url - API endpoint
 * @param {object} data - Data to send
 * @param {object} options - Additional fetch options
 * @returns {Promise<any>} Decoded response data
 */
export async function postMsgpack(url, data, options = {}) {
  return fetchMsgpack(url, {
    ...options,
    method: 'POST',
    headers: {
      'Content-Type': 'application/msgpack',
      ...buildAuthHeaders(),
      ...options.headers,
    },
    body: msgpack.encode(data)
  });
}

/**
 * GET request with query params and MessagePack response.
 * @param {string} url - Base URL
 * @param {object} params - Query parameters
 * @returns {Promise<any>} Decoded response data
 */
export async function getMsgpack(url, params = {}) {
  const queryString = new URLSearchParams(params).toString();
  const fullUrl = queryString ? `${url}?${queryString}` : url;
  return fetchMsgpack(fullUrl);
}
