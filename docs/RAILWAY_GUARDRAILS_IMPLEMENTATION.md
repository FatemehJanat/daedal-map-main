# Railway Data Guardrails

## Goal

Protect hosted runtime stability, bandwidth, and request latency from oversized data pulls such as:

- "give me all the data"
- very large disaster drill-downs
- repeated large overlay range loads
- geometry requests that return too many features at once

The primary safety boundary is Railway, not the browser cache. A user slowly filling their own browser cache is acceptable if server-side egress and per-request work remain bounded.

## Core Principle

Guardrails should be enforced in this order:

1. Per-request response cap
2. Per-request feature-count cap
3. Per-session cumulative byte cap
4. Frontend soft warnings and session UX

If Railway is protected, client-side cache growth is mostly a user-experience issue rather than an infrastructure risk.

## What Exists Today

### Frontend

- MessagePack fetch wrapper:
  - `static/modules/utils/fetch.js`
  - All API reads flow through `fetchMsgpack()`.
- Overlay range loading:
  - `static/modules/overlay-data-loader.js`
  - Heavy overview/event loads come through `loadRangeData()`.
- Overlay cache byte estimation:
  - `static/modules/overlay-cache.js`
  - `calculateCacheSize()` computes approximate exact bytes from JSON serialization.
- Session ID lifecycle:
  - `static/modules/chat/session.js`
  - Session IDs persist across browser refresh/recovery.
- Auth namespace:
  - `static/modules/auth.js`
  - Guest vs authenticated storage namespaces already exist.

### Backend

- Session-scoped cache manager:
  - `mapmover/session_cache.py`
  - Tracks sent data keys, cached results, and recovery state.
- Session namespace builder:
  - `mapmover/auth_context.py`
  - Authenticated users already get user-scoped backend session keys.
- Shared msgpack response helper:
  - `mapmover/routes/disasters/helpers.py`
  - Common disaster endpoints return through `msgpack_response()`.
- Session/admin endpoints:
  - `mapmover/routes/system.py`
  - Session clear/status/inventory already exist.
- Chat rate limiting:
  - `mapmover/routes/chat.py`
  - Request-count rate limiting exists for chat, but not byte-based limits.

## Important Current Gap

There is no reliable backend-visible per-session byte accounting for most data GETs.

Why:

- `fetchMsgpack()` does not currently send `sessionId` on ordinary GET requests.
- Overlay range URLs built in `static/modules/overlay-cache.js` do not include session metadata.
- Many heavy endpoints are plain GETs:
  - `/api/*/geojson`
  - `/api/*/sequence`
  - `/api/*/animation`
  - `/geometry/*`

Result:

- The backend can enforce chat limits by user/IP.
- The backend cannot yet enforce a strict "1 GB per frontend session" rule across all heavy data traffic.

## Recommended Architecture

### Layer 1: Hard Per-Request Guardrail

This is the most important protection.

Guard conditions:

- Max serialized response bytes
- Max feature count
- Optional route-specific hard caps for expensive endpoint families

Behavior:

- Abort before returning oversized payloads
- Return a structured MessagePack error with guidance:
  - narrow time range
  - narrow region
  - increase severity threshold

### Layer 2: Hard Per-Session Byte Budget

Once session identity is available on all data requests:

- Track bytes served per backend session
- Reject requests that would exceed budget
- Expose usage to frontend for messaging

Suggested semantics:

- `bytes_served_total`
- `bytes_served_by_source`
- `requests_blocked_by_quota`

### Layer 3: Frontend Soft Guardrail

Useful even before full backend enforcement:

- Count actual `arrayBuffer().byteLength` in `fetchMsgpack()`
- Keep running total in localStorage under existing session namespace
- Warn near threshold
- Refuse obviously oversized requests before dispatch

This improves UX but should not be trusted as the main safety layer.

## Exact Change Points

### 1. Shared frontend request accounting

Primary file:

- `static/modules/utils/fetch.js`

Additions:

- Read current frontend session ID in the fetch layer
- Send session metadata with all requests
  - recommended header: `X-Session-Id`
- Record actual response bytes using `buffer.byteLength`
- Maintain cumulative per-session byte usage in localStorage
- Optionally expose helper functions:
  - `getSessionTransferUsage()`
  - `clearSessionTransferUsage()`
  - `wouldExceedSessionBudget(nextBytesEstimate)`

Why here:

- Nearly all runtime data requests already flow through `fetchMsgpack()`
- This is the narrowest frontend choke point

Dependency note:

- `fetch.js` currently imports auth helpers only.
- To attach session IDs cleanly, either:
  - add a small getter export in `static/modules/chat/session.js`, or
  - add a tiny shared session accessor module to avoid circular imports.

### 2. Overlay range request identity propagation

Primary files:

- `static/modules/overlay-cache.js`
- `static/modules/overlay-data-loader.js`

Needed changes:

- Ensure overlay range requests carry session identity
- Best approach: let `fetchMsgpack()` inject session header centrally
- Optional: add query metadata for logging/debugging only, but prefer header

Why:

- Overlay range loads are one of the main "get everything" pathways
- They are currently session-blind from the backend's perspective

### 3. Backend session byte accounting

Primary file:

- `mapmover/session_cache.py`

Recommended additions to `SessionCache`:

- `bytes_served_total: int`
- `bytes_served_by_source: Dict[str, int]`
- `response_count: int`
- `blocked_request_count: int`

Recommended methods:

- `register_bytes_served(byte_count: int, source_id: str | None = None)`
- `can_serve_bytes(next_bytes: int, limit_bytes: int) -> bool`
- `remaining_byte_budget(limit_bytes: int) -> int`

Recommended additions to session status endpoints:

- include served-byte stats in:
  - `/api/session/{session_id}/status`
  - `/api/cache/inventory/{session_id}`

Why here:

- This is the existing authoritative per-session backend state

### 4. Session ID extraction on backend GETs

Primary candidates:

- new shared helper near `mapmover/auth_context.py`
- or request utility added in `mapmover/routes/system.py` / shared route helpers

Need:

- Read frontend session ID from:
  - `X-Session-Id` header
  - fallback query param only if needed for debugging/backward compatibility
- Combine with authenticated user via `build_session_cache_key()`

Recommended helper:

- `get_request_session_cache_key(request: Request) -> str`

Why:

- Current session ID handling is strong in chat POSTs, weak in normal data GETs

### 5. Shared response-size enforcement

Primary file:

- `mapmover/routes/disasters/helpers.py`

Recommended evolution:

- keep `msgpack_response()`
- add a quota-aware variant that:
  - serializes payload once
  - checks `len(packed_bytes)`
  - checks per-session quota
  - returns normal response or structured quota error

Example shape:

- `msgpack_response_guarded(request, data, *, source_id=None, max_bytes=None, max_features=None)`

Why here:

- Many disaster routes already return through this helper
- It is the best central insertion point for disaster API families

Limitation:

- Geometry and some system routes also use MessagePack but not always through the same file
- The helper pattern should be extended consistently to geometry routes too

### 6. Geometry hard caps

Primary file:

- `mapmover/routes/geometry.py`

High-risk endpoints:

- `/geometry/countries`
- `/geometry/viewport`
- `/geometry/selection`
- `/geometry/{loc_id}/children`

Needed:

- explicit feature caps
- explicit byte caps
- probably stricter thresholds than disaster point endpoints

Why:

- Geometry payloads can become very large and expensive quickly

### 7. Disaster overview endpoint caps

Primary files:

- `mapmover/routes/disasters/earthquakes.py`
- `mapmover/routes/disasters/hurricanes.py`
- `mapmover/routes/disasters/volcanoes.py`
- `mapmover/routes/disasters/tsunamis.py`
- `mapmover/routes/disasters/tornadoes.py`
- `mapmover/routes/disasters/wildfires.py`
- `mapmover/routes/disasters/floods.py`
- `mapmover/routes/disasters/landslides.py`
- `mapmover/routes/disasters/drought.py`

High-risk route family:

- `GET /api/*/geojson`

Needed:

- route-level max features
- route-level max packed bytes
- fail early after feature construction if exceeding hard cap
- optionally apply DB-level limits before full materialization where appropriate

Special note:

- `earthquakes.py` already supports `limit`, but normal overlay calls do not consistently pass one
- endpoints should not rely on caller restraint alone

### 8. Disaster drill-down caps

Primary files:

- `mapmover/routes/disasters/earthquakes.py`
- `mapmover/routes/disasters/tsunamis.py`
- `mapmover/routes/disasters/tornadoes.py`
- `mapmover/routes/disasters/wildfires.py`
- `mapmover/routes/disasters/floods.py`
- `mapmover/routes/disasters/related.py`

High-risk route family:

- `/api/earthquakes/aftershocks/{event_id}`
- `/api/earthquakes/sequence/{sequence_id}`
- `/api/tsunamis/{event_id}/animation`
- `/api/tornadoes/{event_id}/sequence`
- `/api/events/related/{loc_id}`
- wildfire/flood geometry/progression endpoints

Needed:

- strict route-specific feature caps
- count-first metadata endpoints where useful
- load-confirm UX on frontend

Status:

- Popup-side confirm flow now exists for the disaster popup
- backend still needs hard limits so direct or accidental large loads cannot bypass the UI

### 9. Count-first endpoints for heavy drill-downs

Primary candidate files:

- `mapmover/routes/disasters/earthquakes.py`
- `mapmover/routes/disasters/related.py`
- `mapmover/routes/disasters/tornadoes.py`
- `mapmover/routes/disasters/tsunamis.py`

Recommended pattern:

- lightweight metadata endpoints:
  - count
  - estimated bytes
  - safe-to-load boolean
  - warning string

Examples:

- `/api/earthquakes/aftershocks/{event_id}/summary`
- `/api/events/related/{loc_id}/summary`

Why:

- lets popup UI make a cheap decision before launching a huge transfer
- prevents freezes caused by very large sequences

### 10. Chat/order guardrails

Primary files:

- `mapmover/routes/chat.py`
- `mapmover/order_executor.py`

Needed:

- detect obviously too-broad generated orders before execution
- reject or rewrite requests that imply whole-world or whole-history pulls
- include quota/cap aware response text back to the assistant UI

Why:

- Even with route caps, the chat layer is the earliest point to steer the user toward narrower requests

### 11. Frontend UX and observability

Primary files:

- `static/modules/chat-panel.js`
- `static/modules/overlay-data-loader.js`
- `static/modules/utils/fetch.js`

Needed:

- show current session transfer usage in debug/help/settings surfaces
- clearer quota-blocked error messages
- optional warning around 70% and 90% of session budget
- surface cap failures distinctly from generic network errors

## Recommended Threshold Model

These values should be config-driven, not hardcoded.

Suggested config categories:

- `MAX_RESPONSE_BYTES`
- `MAX_SESSION_BYTES`
- `MAX_FEATURES_EVENTS_OVERVIEW`
- `MAX_FEATURES_GEOMETRY`
- `MAX_FEATURES_SEQUENCE`
- `MAX_FEATURES_RELATED`

Recommended policy style:

- stricter in cloud mode
- looser in local mode
- possibly looser for authenticated accounts than guest mode

Best location:

- runtime config or env-backed config layer

## Best Enforcement Strategy

### Phase 1

Implement immediately:

- frontend byte accounting in `fetch.js`
- backend request session ID propagation
- backend per-request hard byte cap
- backend per-request hard feature cap

This protects Railway fastest.

### Phase 2

Add:

- backend per-session cumulative byte cap
- session status reporting for bytes served
- better quota UX in popup/chat

### Phase 3

Add:

- count-summary endpoints for heavy drill-downs
- order planner refusals for huge global requests
- per-user differentiated quotas

## Specific High-Risk Paths To Prioritize

1. `static/modules/overlay-data-loader.js`
   - broad overlay range loads

2. `mapmover/routes/disasters/earthquakes.py`
   - very large event sets and aftershock sequences

3. `mapmover/routes/geometry.py`
   - potentially huge geometry payloads

4. `mapmover/routes/disasters/hurricanes.py`
   - track and positions payloads

5. `mapmover/routes/disasters/wildfires.py`
   - perimeter/progression geometry can spike

6. `mapmover/routes/chat.py`
   - earliest user-facing narrowing point

## Key Conclusion

The right place to protect the system is the server response path, not the browser cache.

The most important missing capability right now is consistent session identity on ordinary data GETs. Once that is added, the codebase already has enough session and cache infrastructure to support a real per-session byte budget cleanly.

Until then, the highest-value protection is:

- hard per-request response caps
- hard route-level feature caps
- frontend soft accounting for UX
