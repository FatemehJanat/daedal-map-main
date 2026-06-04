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
  return {
    lane: lane || null,
    pack_id: null,        // Phase 2: read from ?pack=
    source_id: null,      // Phase 2: read from ?source=
    prefill_query: null,  // Phase 2: read from ?q= (display-only)
    requires_auth: false, // resolved by the auth layer, not here
    invalid_reason: segment && !lane ? 'unknown_path_segment' : null,
  };
}

/**
 * Initial lane on boot. Precedence: URL > saved state > default. Does not touch
 * browser history.
 * @param {string} [savedLane]
 * @returns {string}
 */
export function getInitialLane(savedLane) {
  const intent = parseRouteIntent();
  return intent.lane || normalizeLane(savedLane) || DEFAULT_LANE;
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
