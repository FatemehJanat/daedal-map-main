# County Map Project Instructions

## Serialization Standard: MessagePack

This project uses MessagePack (NOT JSON) for all API responses.

### Backend Rules
- NEVER use JSONResponse or json.dumps() for API responses
- ALWAYS use msgpack_response() helper from app.py
- For errors, use msgpack_error()
- For decoding POST request bodies, use decode_request_body()

### Frontend Rules
- NEVER use response.json() or JSON.parse() for API responses
- ALWAYS use fetchMsgpack() or postMsgpack() from utils/fetch.js

### Examples

Backend:
```python
return msgpack_response({"events": data, "count": len(data)})
return msgpack_error("Not found", 404)

body = await decode_request_body(request)
```

Frontend:
```javascript
import { fetchMsgpack, postMsgpack } from './utils/fetch.js';

const data = await fetchMsgpack('/api/earthquakes');
const result = await postMsgpack('/api/settings', { theme: 'dark' });
```

When in doubt read C:\Users\Bryan\Desktop\county-map\docs\CONTEXT.md to help guide you to the right path to understanding.

No coding with emojis, only characters that dont cause encoding issues.

The project is on windows, when doing folder searches and bash commands dont try linux they'll fail everytime.

launch agents in county-map folder, not webtest when you're searching for code