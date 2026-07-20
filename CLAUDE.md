# County Map - Public Repo Instructions

Rules for working inside `county-map/`, the public application repo. This file
holds durable rules only, not a map of the codebase.

**For architecture, request lifecycle, and which doc owns what, read
[docs/CONTEXT.md](docs/CONTEXT.md) first.** That is the start-here router and
it stays current. Do not use this file for orientation.

---

## This repo is public

Everything here is world-readable. Data processing scripts, internal planning,
business docs, and operational runbooks belong in the private repo, not here.

---

## Serialization: MessagePack, not JSON

All API responses use MessagePack.

Backend:

- never `JSONResponse` or `json.dumps()` for API responses
- use `msgpack_response()` from `app.py`, and `msgpack_error()` for errors
- decode POST bodies with `decode_request_body()`

```python
return msgpack_response({"events": data, "count": len(data)})
return msgpack_error("Not found", 404)

body = await decode_request_body(request)
```

Frontend:

- never `response.json()` or `JSON.parse()` for API responses
- use `fetchMsgpack()` / `postMsgpack()` from `utils/fetch.js`

```javascript
import { fetchMsgpack, postMsgpack } from './utils/fetch.js';

const data = await fetchMsgpack('/api/earthquakes');
const result = await postMsgpack('/api/settings', { theme: 'dark' });
```

---

## Encoding

Plain alphanumerics and basic punctuation only - in code, comments, docs, and
commit messages. No emoji, box-drawing, arrows, checkmarks, or smart quotes.
They cause encoding failures on this Windows setup.

---

## Windows environment

Development happens on Windows. Prefer the dedicated tools over shell commands
for file work - they handle Windows paths without quoting problems:

1. **Glob** - find files by pattern
2. **Read** - read a file
3. **Grep** - search file contents
4. **Shell** - only when no tool fits

Do not use `ls`, `find`, or `cat` against Windows-style paths, and do not mix
PowerShell and Bash syntax in one command. PowerShell has no `&&`; chain with
`;`.

When searching for application code, search within this repo rather than
sibling build or test folders.
