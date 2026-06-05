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
 * @param {{packId?: string, sourceId?: string}} [entity]
 */
export function writeEntityParam(lane, { packId = '', sourceId = '' } = {}) {
  if (typeof window === 'undefined') return;
  const target = '/' + (normalizeLane(lane) || DEFAULT_LANE);
  const pack = String(packId || '').trim();
  const source = String(sourceId || '').trim();
  const params = new URLSearchParams();
  if (source) params.set('source', source);
  else if (pack) params.set('pack', pack);
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
 * @returns {{lane: string|null, pack_id: string|null, source_id: string|null,
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
  return {
    lane: lane || null,
    pack_id: pick('pack'),         // Explore deep link: ?pack=<pack_id>
    source_id: pick('source'),     // optional ?source=<source_id>
    feed_id: pick('feed'),         // Ops deep link: ?feed=<collector_name>
    prefill_query: pick('q'),      // display-only: ?q=<text> (never auto-sent)
    requires_auth: false,          // resolved by the auth layer, not here
    invalid_reason: segment && !lane ? 'unknown_path_segment' : null,
  };
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
export function writeLane(lane, { replace = false } = {}) {
  const target = '/' + (normalizeLane(lane) || DEFAULT_LANE);
  const current = (window.location.pathname || '/').replace(/\/+$/, '') || '/';
  if (current === target) return;
  const url = target + window.location.search + window.location.hash;
  if (replace) {
    window.history.replaceState({ lane }, '', url);
  } else {
    window.history.pushState({ lane }, '', url);
  }
}

/**
 * Reflect the resolved boot lane in the URL without adding a history entry.
 * Root '/' is a doorway, not a destination: it always canonicalizes to the
 * resolved lane (/explore, /research, or /ops) so each lane has exactly one
 * URL -- which keeps per-lane analytics and share links clean. Uses
 * replaceState so the doorway does not pollute history.
 * @param {string} resolvedLane
 */
export function normalizeBootUrl(resolvedLane) {
  const intent = parseRouteIntent();
  if (intent.lane) return; // URL already carries a valid lane; leave it
  const lane = normalizeLane(resolvedLane) || DEFAULT_LANE;
  writeLane(lane, { replace: true });
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
