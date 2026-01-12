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
msgpack>=1.0.0
```

Note: Already have `orjson` for fast JSON - msgpack replaces this use case.

### Frontend (JavaScript)

Add via npm or CDN:
```bash
npm install @msgpack/msgpack
```

Or use CDN in index.html:
```html
<script src="https://unpkg.com/@msgpack/msgpack"></script>
```

---

## Phase 1: Create Helper Functions

### Backend Helper (app.py)

Create standardized response functions that all endpoints will use:

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

Create new utility module for MessagePack fetch operations:

```javascript
// MessagePack fetch utilities
// All API calls should use these instead of raw fetch()

import { decode, encode } from '@msgpack/msgpack';

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
            // Response wasn't msgpack, use status text
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

- 40 API endpoints in app.py
- All currently return `JSONResponse(content=...)`

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

4. For POST endpoints, add request body decoding:

```python
# FROM:
body = await request.json()

# TO:
import msgpack
body_bytes = await request.body()
body = msgpack.unpackb(body_bytes, raw=False)
```

### Endpoint Categories

| Category | Count | Complexity |
|----------|-------|------------|
| Geometry endpoints | 5 | Simple replacement |
| Event endpoints (earthquake, volcano, etc.) | 20+ | Simple replacement |
| Settings endpoints | 3 | Bidirectional (POST) |
| Chat endpoint | 1 | Bidirectional (POST) |
| Reference endpoints | 2 | Simple replacement |

---

## Phase 3: Frontend Migration

### Scope

- 34 fetch() calls across 12 modules
- 6 JSON.stringify() calls for POST requests
- 4 JSON.parse() calls for nested data

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

### Files to Update

| File | fetch() calls | POST calls | Notes |
|------|---------------|------------|-------|
| model-point-radius.js | ~20 | 0 | Largest file |
| overlay-controller.js | 3 | 0 | |
| chat-panel.js | 5 | 1+ | Has POST |
| viewport-loader.js | 1 | 0 | |
| app.js | 2 | 0 | |
| cache.js | 1 | 0 | |
| selection-manager.js | 1 | 1 | Has POST |
| sidebar.js | 3 | 1+ | Has POST |
| map-adapter.js | 1 | 0 | |
| popup-builder.js | 1 | 0 | Has JSON.parse() |
| hurricane-handler.js | 1 | 0 | |

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

1. Add dependencies (msgpack Python, @msgpack/msgpack JS)
2. Create helper functions (both backend and frontend)
3. Migrate ONE simple endpoint + ONE frontend consumer as proof of concept
4. Migrate remaining backend endpoints (batch work)
5. Migrate remaining frontend modules (batch work)
6. Update CLAUDE.md with conventions
7. Remove JSONResponse import
8. Test full application

---

## Open Questions

- [ ] CDN vs npm for frontend msgpack library?
- [ ] Keep JSON fallback for debugging/curl testing?
- [ ] Add Accept header negotiation for gradual rollout?

---

## References

- MessagePack spec: https://msgpack.org/
- Python msgpack: https://github.com/msgpack/msgpack-python
- JS msgpack: https://github.com/msgpack/msgpack-javascript
- Performance context: docs/future/native_refactor.md

---

*Created: 2026-01-11*
*Status: Planning*
