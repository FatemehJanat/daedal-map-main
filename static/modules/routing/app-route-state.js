/**
 * App route state -- single authority for URL <-> lane mapping.
 *
 * Phase 1 scope: the active lane (explore / research / ops) lives in the URL
 * path. One SPA, warm runtime -- no reload on switch. This module is the only
 * place that reads window.location for routing or writes browser history, so
 * routing logic does not fragment across lane controllers, auth, and (later)
 * pack loaders.
 *
 * Parses the URL once into a normalized RouteIntent; owns pushState /
 * replaceState and the popstate listener. Query params (?pack=, etc.) are
 * parsed but unused until Phase 2.
 */

const LANES = ['explore', 'research', 'ops'];
const DEFAULT_LANE = 'explore';
const ROUTE_INTENT_PARAMS = ['pack', 'packs', 'source', 'feed', 'event_id', 'storm_id', 'q'];

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

/**
 * Parse the current URL into a normalized route intent. Phase 1 only resolves
 * the lane from the first path segment; the remaining fields are placeholders
 * the later phases fill in.
 * @param {Location} [loc]
 * @returns {{lane: string|null, pack_id: string|null, pack_ids: string[], source_id: string|null, feed_id: string|null, event_id: string|null, exact_id_key: string|null,
 *   prefill_query: string|null, requires_auth: boolean, invalid_reason: string|null}}
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
