# MessagePack Migration Plan

Migration from JSON to MessagePack serialization for all API endpoints.

---

## Goals

1. Replace JSON serialization with MessagePack across all API responses
2. Establish project conventions that make MessagePack the default
3. Ensure Claude (and developers) write new code with MessagePack automatically

**Expected gains:**
- 2-5x faster serialization (JSON ~350ms total -> MessagePack ~100ms)
- 30-50% smaller payload sizes for geometry data
- Better handling of binary data if needed in future

---

## Dependencies

### Backend (Python)

Add to `requirements.txt`:
```
msgpack>=1.0.0  # MessagePack serialization (2-5x faster, 30-50% smaller)
```

**Status: DONE** - Added on line 18 of requirements.txt

Note: Already have `orjson` for fast JSON - msgpack replaces this use case.

### Frontend (JavaScript)

Use CDN in templates/index.html (line 2012, before app.js):
```html
<script src="https://unpkg.com/@msgpack/msgpack"></script>
<script type="module" src="/static/modules/app.js"></script>
```

**Decision: CDN** - No build process needed, simpler integration.

---

## Phase 1: Create Helper Functions

### Backend Helper (app.py)

Add after imports (around line 30):

```python
import msgpack
from fastapi import Response

def msgpack_response(data: dict, status_code: int = 200) -> Response:
    """Standard MessagePack response for all API endpoints.

    Usage:
        return msgpack_response({"data": result, "count": len(result)})
    """
    return Response(
        content=msgpack.packb(data, use_bin_type=True),
        media_type="application/msgpack",
        status_code=status_code
    )

def msgpack_error(message: str, status_code: int = 500) -> Response:
    """Standard error response in MessagePack format."""
    return msgpack_response({"error": message}, status_code)
```

### Frontend Helper (static/modules/utils/fetch.js)

Create new utility module:

```javascript
/**
 * MessagePack fetch utilities
 * All API calls should use these instead of raw fetch()
 */

// MessagePack library loaded via CDN, available as window.MessagePack
const { decode, encode } = window.MessagePack || {};

/**
 * Fetch data from API endpoint with MessagePack decoding.
 * @param {string} url - API endpoint
 * @param {object} options - fetch options (optional)
 * @returns {Promise<any>} Decoded response data
 */
export async function fetchMsgpack(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: {
            'Accept': 'application/msgpack',
            ...options.headers,
        }
    });

    if (!response.ok) {
        let errorMsg = 'Request failed';
        try {
            const buffer = await response.arrayBuffer();
            const decoded = decode(new Uint8Array(buffer));
            errorMsg = decoded.error || errorMsg;
        } catch (e) {
            errorMsg = response.statusText;
        }
        throw new Error(errorMsg);
    }

    const buffer = await response.arrayBuffer();
    return decode(new Uint8Array(buffer));
}

/**
 * POST data to API endpoint with MessagePack encoding/decoding.
 * @param {string} url - API endpoint
 * @param {object} data - Data to send
 * @returns {Promise<any>} Decoded response data
 */
export async function postMsgpack(url, data) {
    return fetchMsgpack(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/msgpack',
        },
        body: encode(data)
    });
}
```

---

## Phase 2: Backend Migration

### Scope

**41 endpoints** in app.py (verified via grep):

| Line | Endpoint | Type |
|------|----------|------|
| 113 | /health | GET |
| 121 | / | GET (HTML) |
| 130 | /geometry/countries | GET |
| 144 | /geometry/{loc_id}/children | GET |
| 161 | /geometry/{loc_id}/places | GET |
| 174 | /geometry/{loc_id}/info | GET |
| 188 | /geometry/viewport | GET |
| 222 | /geometry/cache/clear | POST |
| 233 | /geometry/selection | POST |
| 258 | /api/hurricane/track/{storm_id} | GET |
| 326 | /api/hurricane/storms | GET |
| 377 | /api/hurricane/storms/geojson | GET |
| 457 | /api/earthquakes/geojson | GET |
| 533 | /api/earthquakes/sequence/{sequence_id} | GET |
| 610 | /api/earthquakes/aftershocks/{event_id} | GET |
| 700 | /api/volcanoes/geojson | GET |
| 749 | /api/eruptions/geojson | GET |
| 843 | /api/tsunamis/geojson | GET |
| 912 | /api/tsunamis/{event_id}/runups | GET |
| 1003 | /api/tsunamis/{event_id}/animation | GET |
| 1095 | /api/events/nearby-earthquakes | GET |
| 1227 | /api/events/nearby-volcanoes | GET |
| 1365 | /api/events/nearby-tsunamis | GET |
| 1495 | /api/wildfires/geojson | GET |
| 1619 | /api/wildfires/{event_id}/perimeter | GET |
| 1687 | /api/wildfires/{event_id}/progression | GET |
| 1778 | /api/floods/geojson | GET |
| 1884 | /api/floods/{event_id}/geometry | GET |
| 1911 | /api/tornadoes/geojson | GET |
| 2030 | /api/tornadoes/{event_id} | GET |
| 2130 | /api/tornadoes/{event_id}/sequence | GET |
| 2244 | /api/storms/geojson | GET |
| 2335 | /api/storms/{storm_id}/track | GET |
| 2399 | /api/storms/tracks/geojson | GET |
| 2491 | /api/storms/list | GET |
| 2548 | /reference/admin-levels | GET |
| 2569 | /settings | GET |
| 2583 | /settings | POST |
| 2609 | /settings/init-folders | POST |
| 2641 | /chat | POST |

**135 JSONResponse calls** to replace (verified via grep)

### Approach

1. Add msgpack import and helper functions to top of app.py
2. Find/replace pattern for each endpoint:

```python
# FROM:
return JSONResponse(content={"data": result})

# TO:
return msgpack_response({"data": result})
```

3. For error responses:

```python
# FROM:
return JSONResponse(content={"error": str(e)}, status_code=500)

# TO:
return msgpack_error(str(e), 500)
```

4. For POST endpoints (geometry/selection, settings, chat), add request body decoding:

```python
# FROM:
body = await request.json()

# TO:
body_bytes = await request.body()
body = msgpack.unpackb(body_bytes, raw=False)
```

### Endpoint Categories

| Category | Count | Complexity |
|----------|-------|------------|
| Geometry endpoints | 7 | Simple replacement |
| Hurricane/Storm endpoints | 7 | Simple replacement |
| Earthquake endpoints | 3 | Simple replacement |
| Volcano endpoints | 2 | Simple replacement |
| Tsunami endpoints | 3 | Simple replacement |
| Wildfire endpoints | 3 | Simple replacement |
| Flood endpoints | 2 | Simple replacement |
| Tornado endpoints | 3 | Simple replacement |
| Nearby events endpoints | 3 | Simple replacement |
| Settings endpoints | 3 | Bidirectional (POST) |
| Chat endpoint | 1 | Bidirectional (POST) |
| Reference/Health | 3 | Simple replacement |

---

## Phase 3: Frontend Migration

### Scope

**22 JS modules** in static/modules/ (verified via glob):

```
sidebar.js
choropleth.js
popup-builder.js
chat-panel.js
navigation.js
selection-manager.js
viewport-loader.js
overlay-selector.js
hurricane-handler.js
config.js
time-slider.js
models/model-registry.js
event-animator.js
cache.js
map-adapter.js
track-animator.js
app.js
overlay-controller.js
disaster-popup.js
models/model-point-radius.js
models/model-track.js
models/model-polygon.js
```

### Files to Update (needs fetch() audit)

| File | Likely fetch() calls | POST calls | Notes |
|------|----------------------|------------|-------|
| overlay-controller.js | 10+ | 0 | Main data loading |
| models/model-point-radius.js | 5+ | 0 | Event data fetching |
| chat-panel.js | 2+ | 1+ | Has POST to /chat |
| viewport-loader.js | 1+ | 0 | Geometry loading |
| app.js | 2+ | 0 | Initial setup |
| cache.js | 1+ | 0 | Data caching |
| selection-manager.js | 1+ | 1 | POST to /geometry/selection |
| sidebar.js | 3+ | 1+ | Settings POST |
| map-adapter.js | 1+ | 0 | |
| popup-builder.js | 1+ | 0 | May have JSON.parse() |
| hurricane-handler.js | 2+ | 0 | Storm track loading |
| track-animator.js | 1+ | 0 | Track data |
| event-animator.js | 1+ | 0 | Animation data |

### Approach

1. Create utils/fetch.js with helper functions
2. Update each module to import helpers:

```javascript
// Add to top of each module
import { fetchMsgpack, postMsgpack } from './utils/fetch.js';
```

3. Replace fetch patterns:

```javascript
// FROM:
const response = await fetch(url);
const data = await response.json();

// TO:
const data = await fetchMsgpack(url);
```

4. Replace POST patterns:

```javascript
// FROM:
const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
});
const data = await response.json();

// TO:
const data = await postMsgpack(url, payload);
```

---

## Phase 4: Project Convention Updates

### CLAUDE.md Updates

Add to project CLAUDE.md:

```markdown
## Serialization Standard: MessagePack

This project uses MessagePack (NOT JSON) for all API responses.

### Backend Rules
- NEVER use JSONResponse or json.dumps() for API responses
- ALWAYS use msgpack_response() helper from app.py
- For errors, use msgpack_error()

### Frontend Rules
- NEVER use response.json() or JSON.parse() for API responses
- ALWAYS use fetchMsgpack() or postMsgpack() from utils/fetch.js

### Examples

Backend:
    return msgpack_response({"events": data, "count": len(data)})

Frontend:
    const data = await fetchMsgpack('/api/earthquakes');
```

### Remove JSON Patterns

After migration complete:
1. Remove `from fastapi.responses import JSONResponse` from app.py
2. Add comment at top of app.py noting MessagePack standard

---

## Phase 5: Testing

### Backend Tests

1. Verify each endpoint returns correct Content-Type header
2. Verify response can be decoded with msgpack.unpackb()
3. Verify data structure matches previous JSON structure

### Frontend Tests

1. Load each overlay type and verify data displays
2. Test POST operations (settings save, chat)
3. Check browser console for decode errors

### Integration Tests

1. Full user flow: load map -> select region -> view data
2. Verify no regressions in functionality
3. Performance comparison (optional): measure response times before/after

---

## Rollback Plan

If issues discovered after deployment:

1. Keep JSONResponse import commented (not deleted) during testing period
2. Helper functions can be modified to return JSON temporarily:

```python
def msgpack_response(data, status_code=200):
    # TEMPORARY ROLLBACK - uncomment to revert to JSON
    # return JSONResponse(content=data, status_code=status_code)
    return Response(
        content=msgpack.packb(data, use_bin_type=True),
        media_type="application/msgpack",
        status_code=status_code
    )
```

---

## Migration Order

Recommended sequence:

1. [x] Add msgpack to requirements.txt
2. [ ] Add MessagePack CDN to templates/index.html (line 2012)
3. [ ] Create utils/fetch.js with helper functions
4. [ ] Add msgpack_response helpers to app.py
5. [ ] Migrate ONE simple endpoint + ONE frontend consumer as proof of concept
6. [ ] Migrate remaining backend endpoints (batch work)
7. [ ] Migrate remaining frontend modules (batch work)
8. [ ] Update CLAUDE.md with conventions
9. [ ] Remove JSONResponse import
10. [ ] Test full application

---

## Decisions Made

- [x] **CDN for frontend** - Use unpkg CDN, no build process needed
- [x] **No JSON fallback** - Clean migration, use browser DevTools for debugging

---

## References

- MessagePack spec: https://msgpack.org/
- Python msgpack: https://github.com/msgpack/msgpack-python
- JS msgpack: https://github.com/msgpack/msgpack-javascript
- Performance context: docs/future/native_refactor.md

---

*Created: 2026-01-11*
*Updated: 2026-01-14*
*Status: COMPLETE*

## Migration Summary

Completed:
- Backend: 61 endpoints converted to msgpack_response()
- Frontend: All active modules use fetchMsgpack/postMsgpack utilities
- Helper functions in app.py (msgpack_response, msgpack_error, decode_request_body)
- Utility module at static/modules/utils/fetch.js
- CDN script loaded in index.html
- Legacy mapviewer.js deleted (was not in use)
- Unused JSONResponse import removed from app.py
