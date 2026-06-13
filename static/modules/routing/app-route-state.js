/**
 * App route state -- single authority for URL <-> lane mapping.
 *
 * Phase 1/2 scope: the active lane (explore / research / ops) lives in the URL
 * path with small route-intent params. Phase 3 adds a versioned full-share
 * `state` payload. This module is the only place that reads window.location for
 * routing or writes browser history, so routing logic does not fragment across
 * lane controllers, auth, and pack/share loaders.
 *
 * Parses the URL once into a normalized RouteIntent; owns pushState /
 * replaceState and the popstate listener. Query params (?pack=, etc.) are
 * parsed but unused until Phase 2.
 */

const LANES = ['explore', 'research', 'ops'];
const DEFAULT_LANE = 'explore';
const ROUTE_INTENT_PARAMS = ['pack', 'packs', 'source', 'feed', 'event_id', 'storm_id', 'q', 'state'];
const SHARE_STATE_VERSION = 1;

const LANE_TITLES = {
  explore: 'Explore - DaedalMap',
  research: 'Research - DaedalMap',
  ops: 'Ops - DaedalMap',
};

/**
 * Normalize an arbitrary value to a known lane, or '' if it is not one.
 * @param {string} value
 * @returns {string}
 */
export function normalizeLane(value) {
  const v = String(value || '').trim().toLowerCase();
  return LANES.includes(v) ? v : '';
}

/**
 * Set document.title to match the active lane so analytics (GA pageTitle /
 * Realtime) and the browser tab distinguish lanes, not just the URL path. Pass a
 * pack_id / source_id to identify the loaded entity, e.g.
 * "earthquakes - Explore - DaedalMap" -- this is how GA tells an app pack *load*
 * apart from a www pack-page *visit* ("Earthquakes Data Pack - DaedalMap").
 * @param {string} lane
 * @param {string} [entityId] raw pack_id or source_id
 */
export function setLaneTitle(lane, entityId) {
  if (typeof document === 'undefined') return;
  const base = LANE_TITLES[normalizeLane(lane) || DEFAULT_LANE] || document.title;
  const id = String(entityId || '').trim();
  document.title = id ? `${id} - ${base}` : base;
}

/**
 * Reflect the loaded pack/source in the URL so GA sees a distinct pageview
 * (`/explore?pack=earthquakes`) and the link is shareable. Uses replaceState so
 * loading a pack does not spam browser history; the history change still fires a
 * GA page_view that captures the new path + title. Source wins over pack when
 * both are given (the more specific intent). No-op when the URL already matches
 * (e.g. a deep-link entry that already carries the param).
 * @param {string} lane
 * @param {{packId?: string, sourceId?: string, feedId?: string, eventId?: string}} [entity]
 */
export function writeEntityParam(lane, { packId = '', sourceId = '', feedId = '', eventId = '' } = {}) {
  if (typeof window === 'undefined') return;
  const target = '/' + (normalizeLane(lane) || DEFAULT_LANE);
  const pack = String(packId || '').trim();
  const source = String(sourceId || '').trim();
  const feed = String(feedId || '').trim();
  const event = String(eventId || '').trim();
  const params = new URLSearchParams();
  if (source) params.set('source', source);
  else if (feed) params.set('feed', feed);
  else if (pack) params.set('pack', pack);
  if (event) params.set('event_id', event);
  const qs = params.toString();
  const nextSearch = qs ? `?${qs}` : '';
  const currentPath = (window.location.pathname || '/').replace(/\/+$/, '') || '/';
  if (currentPath === target && (window.location.search || '') === nextSearch) return;
  window.history.replaceState({ lane }, '', target + nextSearch + (window.location.hash || ''));
}

function bytesToBase64(bytes) {
  let binary = '';
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
}

function base64ToBytes(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function toBase64Url(value) {
  return String(value || '').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function fromBase64Url(value) {
  const normalized = String(value || '').replace(/-/g, '+').replace(/_/g, '/');
  const padding = normalized.length % 4;
  return normalized + (padding ? '='.repeat(4 - padding) : '');
}

function normalizeCameraState(camera = null) {
  if (!camera || typeof camera !== 'object') return null;
  const result = {};
  if (Array.isArray(camera.bbox) && camera.bbox.length === 4) {
    result.bbox = camera.bbox.map((value) => Number(value));
  } else if (
    camera.center
    && typeof camera.center === 'object'
    && Number.isFinite(Number(camera.center.lng))
    && Number.isFinite(Number(camera.center.lat))
  ) {
    result.center = {
      lng: Number(camera.center.lng),
      lat: Number(camera.center.lat)
    };
  }
  if (Number.isFinite(Number(camera.zoom))) result.zoom = Number(camera.zoom);
  if (Number.isFinite(Number(camera.bearing))) result.bearing = Number(camera.bearing);
  if (Number.isFinite(Number(camera.pitch))) result.pitch = Number(camera.pitch);
  return Object.keys(result).length ? result : null;
}

function normalizeLoadEntry(entry = null) {
  if (!entry || typeof entry !== 'object') return null;
  const kind = String(entry.kind || '').trim().toLowerCase();
  if (kind === 'source') {
    const sourceId = String(entry.source_id || '').trim();
    if (!sourceId) return null;
    const normalized = { kind: 'source', source_id: sourceId };
    const packId = String(entry.pack_id || '').trim();
    const mode = String(entry.mode || entry.data_type || '').trim();
    if (packId) normalized.pack_id = packId;
    if (mode) normalized.mode = mode;
    if (entry.filters && typeof entry.filters === 'object' && !Array.isArray(entry.filters)) {
      normalized.filters = entry.filters;
    }
    return normalized;
  }
  if (kind === 'feed') {
    const feedId = String(entry.feed_id || '').trim();
    if (!feedId) return null;
    const normalized = { kind: 'feed', feed_id: feedId };
    const historyWindow = String(entry.history_window || '').trim();
    if (historyWindow) normalized.history_window = historyWindow;
    if (entry.filters && typeof entry.filters === 'object' && !Array.isArray(entry.filters)) {
      normalized.filters = entry.filters;
    }
    return normalized;
  }
  return null;
}

export function normalizeShareState(raw = null) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const lane = normalizeLane(raw.lane);
  if (!lane) return null;
  const normalized = {
    v: Number(raw.v) || SHARE_STATE_VERSION,
    lane,
    camera: normalizeCameraState(raw.camera),
    overlays: Array.isArray(raw.overlays)
      ? raw.overlays.map((value) => String(value || '').trim()).filter(Boolean)
      : [],
    loads: Array.isArray(raw.loads)
      ? raw.loads.map((entry) => normalizeLoadEntry(entry)).filter(Boolean)
      : []
  };
  if (lane === 'explore' && raw.time && typeof raw.time === 'object') {
    const timeMode = String(raw.time.mode || '').trim().toLowerCase();
    if (timeMode === 'range') {
      const start = String(raw.time.start || '').trim();
      const end = String(raw.time.end || '').trim();
      if (start || end) {
        normalized.time = { mode: 'range' };
        if (start) normalized.time.start = start;
        if (end) normalized.time.end = end;
      }
    }
  }
  if (lane === 'ops') {
    normalized.live = raw.live !== false;
    const historyWindow = String(raw.history_window || '').trim();
    normalized.history_window = historyWindow || '72h';
  }
  if (raw.focus && typeof raw.focus === 'object' && !Array.isArray(raw.focus)) {
    const focusType = String(raw.focus.type || '').trim().toLowerCase();
    if (focusType) {
      normalized.focus = { type: focusType };
      if (raw.focus.event_id) normalized.focus.event_id = String(raw.focus.event_id).trim();
      if (raw.focus.loc_id) normalized.focus.loc_id = String(raw.focus.loc_id).trim();
      if (raw.focus.source_id) normalized.focus.source_id = String(raw.focus.source_id).trim();
      if (raw.focus.feed_id) normalized.focus.feed_id = String(raw.focus.feed_id).trim();
    }
  }
  return normalized;
}

export function encodeShareStateParam(shareState) {
  const normalized = normalizeShareState(shareState);
  if (!normalized) return '';
  const json = JSON.stringify(normalized);
  const bytes = new TextEncoder().encode(json);
  return toBase64Url(bytesToBase64(bytes));
}

export function decodeShareStateParam(value) {
  const encoded = String(value || '').trim();
  if (!encoded) return null;
  try {
    const bytes = base64ToBytes(fromBase64Url(encoded));
    const json = new TextDecoder().decode(bytes);
    return normalizeShareState(JSON.parse(json));
  } catch (_error) {
    return null;
  }
}

export function buildShareStateUrl(shareState, { absolute = false } = {}) {
  const normalized = normalizeShareState(shareState);
  if (!normalized) return '';
  const lane = normalized.lane || DEFAULT_LANE;
  const encoded = encodeShareStateParam(normalized);
  const path = '/' + lane;
  const url = `${path}?state=${encoded}`;
  if (!absolute || typeof window === 'undefined') return url;
  return new URL(url, window.location.origin).toString();
}

/**
 * Parse the current URL into a normalized route intent. Phase 1 only resolves
 * the lane from the first path segment; the remaining fields are placeholders
 * the later phases fill in.
 * @param {Location} [loc]
 * @returns {{lane: string|null, pack_id: string|null, pack_ids: string[], source_id: string|null, feed_id: string|null, event_id: string|null, exact_id_key: string|null,
 *   prefill_query: string|null, share_state: object|null, requires_auth: boolean, invalid_reason: string|null}}
 */
export function parseRouteIntent(loc = window.location) {
  const segment = String(loc.pathname || '/').replace(/^\/+/, '').split('/')[0];
  const lane = normalizeLane(segment);
  const params = new URLSearchParams(loc.search || '');
  const pick = (key) => {
    const v = String(params.get(key) || '').trim();
    return v || null;
  };
  const pickList = (key) => {
    const values = [];
    const seen = new Set();
    for (const part of String(params.get(key) || '').split(',')) {
      const value = String(part || '').trim();
      if (!value || seen.has(value)) continue;
      seen.add(value);
      values.push(value);
    }
    return values;
  };
  const genericEventId = pick('event_id');
  const stormId = pick('storm_id');
  const normalizedExactId = genericEventId || stormId || null;
  const exactIdKey = genericEventId ? 'event_id' : (stormId ? 'storm_id' : null);
  return {
    lane: lane || null,
    pack_id: pick('pack'),         // Explore deep link: ?pack=<pack_id>
    pack_ids: pickList('packs'),   // Research deep link: ?packs=<pack_id_1>,<pack_id_2>
    source_id: pick('source'),     // optional ?source=<source_id>
    feed_id: pick('feed'),         // Ops deep link: ?feed=<collector_name>
    event_id: normalizedExactId,   // Exact event deep link: ?event_id=<stable_event_id> or native alias like ?storm_id=
    exact_id_key: exactIdKey,
    prefill_query: pick('q'),      // display-only: ?q=<text> (never auto-sent)
    share_state: decodeShareStateParam(pick('state')),
    requires_auth: false,          // resolved by the auth layer, not here
    invalid_reason: segment && !lane ? 'unknown_path_segment' : null,
  };
}

/**
 * Returns true when the current app URL is the shared shell route rather than a
 * lane-specific deep link. '/' and query-only variants remain the shared shell.
 * @param {Location} [loc]
 * @returns {boolean}
 */
export function isSharedShellRoute(loc = window.location) {
  const intent = parseRouteIntent(loc);
  return !intent.lane;
}

/**
 * Initial lane on boot. Precedence: URL > default. Does not touch browser
 * history.
 * @param {string} [_savedLane]
 * @returns {string}
 */
export function getInitialLane(_savedLane) {
  const intent = parseRouteIntent();
  return intent.lane || DEFAULT_LANE;
}

/**
 * Write the lane into the URL path, preserving query + hash. No-op when the URL
 * already matches -- which is what makes popstate-driven switches loop-free
 * (the browser changes the URL before firing popstate, so the writer sees a
 * match and does nothing).
 * @param {string} lane
 * @param {{replace?: boolean}} [opts]
 */
export function writeLane(lane, { replace = false, preserveQuery = false } = {}) {
  const target = '/' + (normalizeLane(lane) || DEFAULT_LANE);
  const current = (window.location.pathname || '/').replace(/\/+$/, '') || '/';
  const params = new URLSearchParams(window.location.search || '');
  if (!preserveQuery) {
    for (const key of ROUTE_INTENT_PARAMS) {
      params.delete(key);
    }
  }
  const nextSearch = params.toString();
  const url = target + (nextSearch ? `?${nextSearch}` : '') + window.location.hash;
  if (current === target && (window.location.search || '') === (nextSearch ? `?${nextSearch}` : '')) return;
  if (replace) {
    window.history.replaceState({ lane }, '', url);
  } else {
    window.history.pushState({ lane }, '', url);
  }
}

/**
 * Reflect the resolved boot lane in the URL without adding a history entry.
 * The shared shell now intentionally stays at '/', so boot normalization only
 * preserves lane-specific entry URLs and leaves the shared shell untouched.
 * @param {string} resolvedLane
 */
export function normalizeBootUrl(resolvedLane) {
  const intent = parseRouteIntent();
  if (!intent.lane) return;
  const lane = normalizeLane(resolvedLane) || DEFAULT_LANE;
  if (intent.lane !== lane) {
    writeLane(lane, { replace: true, preserveQuery: true });
  }
}

/**
 * Subscribe to back/forward navigation. The callback receives the lane parsed
 * from the new URL.
 * @param {(lane: string, intent: object) => void} cb
 */
export function onRouteChange(cb) {
  window.addEventListener('popstate', () => {
    const intent = parseRouteIntent();
    cb(intent.lane || DEFAULT_LANE, intent);
  });
}
