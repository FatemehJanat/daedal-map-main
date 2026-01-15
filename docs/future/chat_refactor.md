# Chat Architecture Refactor Plan

## Problem Statement

The preprocessor makes "hard decisions" too early, bypassing the LLM for queries that need contextual understanding.

**Example failure case:**
```
User: "show me data from the australian bureau of statistics"
Expected: Show ABS data sources
Actual: Navigates to Bureau County, Illinois
```

The word "bureau" matched a location name before the full context ("Australian Bureau of Statistics" = data source) could be evaluated.

---

## Current Architecture (Problematic)

```
User Query
    |
    v
Preprocessor (HARD DECISIONS)
    |
    +---> Navigation patterns match? --> EARLY RETURN (no LLM)
    +---> Disambiguation needed? -----> EARLY RETURN (no LLM)
    +---> Show borders? --------------> EARLY RETURN (no LLM)
    |
    v (only if no early return)
Build hints dict
    |
    v
Tier 3/4 Context (inject hints into system message)
    |
    v
LLM Call (order_taker.py)
```

### Where Hard Decisions Happen

| Decision | Location | Problem |
|----------|----------|---------|
| Navigation | `preprocessor.py:1627-1656` | Pattern `^show me\b` triggers before source detection |
| Disambiguation | `preprocessor.py:1690-1698` | Returns to user, skips LLM entirely |
| Location match | `preprocessor.py:1667` | Single match returned, alternatives discarded |
| Source match | `preprocessor.py:1322-1328` | Only longest match kept, alternatives discarded |

### The Specific Bug Flow

1. Query: "show me data from the australian bureau of statistics"
2. `detect_navigation_intent()` runs first (line 1627)
3. Pattern `^show me\b(?!.*data|.*from)` - negative lookahead should exclude this!
4. BUT `extract_multiple_locations()` is called from navigation flow
5. "bureau" matches Bureau County, IL in viewport location lookup
6. Navigation returns with Bureau County before source detection runs

The filtering logic at lines 1671-1676 that should clear "bureau" (because it's part of "Australian Bureau of Statistics") only runs if we DON'T take the navigation early return path.

---

## Proposed Architecture (Candidate-Based)

```
User Query
    |
    v
Preprocessor (CONTEXT GATHERER - no hard decisions)
    |
    +---> Gather location candidates with confidence scores
    +---> Gather source candidates with confidence scores
    +---> Gather intent candidates with confidence scores
    +---> Gather time/topic/region signals
    |
    v
Build candidates dict (ALL possibilities, scored)
    |
    v
Tier 3/4 Context (inject ALL candidates into system message)
    |
    v
LLM Call (LLM DECIDES which interpretation is correct)
    |
    v
Post-LLM routing (navigate, disambiguate, or execute order)
```

### Key Principle

**Disambiguation should happen IN the LLM, not BEFORE it.**

The LLM has full context:
- Complete user query
- Chat history
- All candidate interpretations with scores
- Knowledge of what "Australian Bureau of Statistics" is

The preprocessor only sees:
- Pattern matches
- Keyword matches
- No semantic understanding

---

## Implementation Plan

### Phase 1: Refactor Detection Functions to Return Candidates

Currently each detection function returns a single match. Refactor to return ALL matches with confidence scores.

**Files to modify:**
- `mapmover/preprocessor.py`

**Changes:**

#### 1.1 detect_source_from_query() - Return multiple candidates

```python
# BEFORE (line 1322-1328):
best_match = max(source_matches, key=lambda x: x["match_length"])
return best_match

# AFTER:
return {
    "candidates": sorted(source_matches, key=lambda x: -x["confidence"]),
    "best": source_matches[0] if source_matches else None
}
```

Confidence scoring:
- Full source_name match: 1.0
- Partial name (>4 chars): 0.7
- source_id match: 0.9
- Boost if query contains "data", "statistics", "source": +0.1

#### 1.2 extract_country_from_query() - Return multiple candidates

```python
# BEFORE: Returns first match, sets ambiguous flag
# AFTER: Return all candidates with scores

return {
    "candidates": [
        {"term": "Australia", "iso3": "AUS", "confidence": 0.95, "type": "country"},
        {"term": "bureau", "iso3": "USA-IL-xxx", "confidence": 0.3, "type": "viewport_match"}
    ],
    "best": candidates[0] if candidates else None
}
```

Confidence scoring:
- Exact country name: 1.0
- Capital city: 0.9
- Viewport location (county): 0.5
- Partial word match: 0.3
- Penalize if term is substring of detected source: -0.5

#### 1.3 detect_navigation_intent() - Return confidence, not boolean

```python
# BEFORE:
return {"is_navigation": True, "pattern": matched_pattern}

# AFTER:
return {
    "confidence": 0.8,  # Strong pattern match
    "pattern": matched_pattern,
    "competing_intents": [
        {"type": "data_request", "confidence": 0.9, "reason": "contains 'data from'"},
        {"type": "source_lookup", "confidence": 0.85, "reason": "mentions source name"}
    ]
}
```

---

### Phase 2: Remove Early Returns

Remove all early returns that bypass the LLM. Instead, pass intent candidates to LLM.

**Current early returns to remove:**

| Line | Pattern | Replace With |
|------|---------|--------------|
| 606-636 | show_borders early return | Pass `intent: show_borders (0.9)` to LLM |
| 688-711 | navigation early return | Pass `intent: navigation (0.8)` to LLM |
| 697-711 | disambiguation early return | Pass `disambiguation_needed: true, options: [...]` to LLM |

**New flow:**

```python
def preprocess_query(query, viewport=None):
    candidates = {
        "intents": [],      # navigation, data_request, reference_lookup, etc.
        "locations": [],    # All location matches with scores
        "sources": [],      # All source matches with scores
        "topics": [],       # Extracted topics
        "regions": [],      # Regional groupings
        "time": {},         # Time patterns
    }

    # Gather ALL candidates (no early returns)
    candidates["sources"] = detect_source_candidates(query)
    candidates["locations"] = detect_location_candidates(query, viewport)
    candidates["intents"] = detect_intent_candidates(query, candidates)
    candidates["topics"] = extract_topics(query)
    candidates["regions"] = resolve_regions(query)
    candidates["time"] = detect_time_patterns(query)

    # Cross-reference to adjust scores
    candidates = adjust_scores_with_context(candidates)

    return candidates
```

---

### Phase 3: Enhanced Tier 3 Context

Modify `build_tier3_context()` to present ALL candidates to the LLM.

**New context format:**

```
[INTERPRETATION CANDIDATES]

Possible intents (pick most likely based on full query):
- data_request (0.9): Query contains "data from", mentions source
- navigation (0.3): Query starts with "show me"

Possible locations:
- Australia (0.95): Country name mentioned
- Bureau County, IL (0.3): Word "bureau" matched viewport location
  NOTE: "bureau" is part of source name "Australian Bureau of Statistics"

Possible data sources:
- abs_population (0.95): "Australian Bureau of Statistics" matched
  Metrics: population, births, deaths, migration...

Based on the full query context, determine which interpretation is correct.
If data_request: return JSON order
If navigation: return {"action": "navigate", "location": "..."}
If ambiguous: ask user to clarify
```

---

### Phase 4: Post-LLM Routing

After LLM responds, route based on response type.

**New response types:**

```python
# LLM can now return:
{
    "type": "order",        # Data request - execute order
    "order": {...}
}

{
    "type": "navigate",     # Navigation - zoom to location
    "location": {"iso3": "AUS", "name": "Australia"}
}

{
    "type": "disambiguate", # Needs clarification
    "question": "Did you mean Bureau County, IL or the Australian Bureau of Statistics data source?",
    "options": [...]
}

{
    "type": "chat",         # General response
    "message": "..."
}
```

**app.py changes:**

```python
result = interpret_request(query, chat_history, candidates=candidates)

if result["type"] == "navigate":
    # Handle navigation (was previously early return)
    return handle_navigation(result["location"])
elif result["type"] == "disambiguate":
    # Handle disambiguation (was previously early return)
    return handle_disambiguation(result)
elif result["type"] == "order":
    # Existing order flow
    return handle_order(result)
else:
    # Chat response
    return {"type": "chat", "message": result["message"]}
```

---

## Files to Modify

### Primary Changes

| File | Changes |
|------|---------|
| `mapmover/preprocessor.py` | Refactor detection functions to return candidates, remove early returns |
| `mapmover/order_taker.py` | Update system prompt for candidate-based interpretation, add new response types |
| `app.py` | Remove early return handlers, add post-LLM routing |

### Secondary Changes

| File | Changes |
|------|---------|
| `mapmover/postprocessor.py` | Handle new response types |
| `static/app.js` | Handle new response types from backend |

---

## Confidence Scoring Rules

### Intent Scoring

| Signal | Score Adjustment |
|--------|------------------|
| Query contains "data", "statistics", "show me data" | +0.3 for data_request |
| Query starts with navigation pattern | +0.5 for navigation |
| Query contains source name | +0.4 for data_request |
| Query is question format ("what is", "where is") | +0.3 for reference_lookup |
| Chat history shows data context | +0.2 for data_request |

### Location Scoring

| Match Type | Base Score |
|------------|------------|
| Exact country name | 1.0 |
| Capital city | 0.9 |
| Admin1 (state/province) | 0.8 |
| Admin2 (county) in viewport | 0.5 |
| Partial word match | 0.3 |

| Adjustment | Score Change |
|------------|--------------|
| Term is part of detected source name | -0.5 |
| Term is part of topic keyword | -0.3 |
| Multiple locations with same name | each gets 1/n penalty |

### Source Scoring

| Match Type | Base Score |
|------------|------------|
| Full source_name match | 1.0 |
| source_id match | 0.9 |
| Partial name (>8 chars) | 0.7 |
| Partial name (4-8 chars) | 0.5 |

---

## Migration Strategy

### Phase A: Add candidate gathering (non-breaking)

1. Add new `*_candidates()` functions alongside existing functions
2. Log candidates for debugging
3. Keep existing early returns working

### Phase B: Update LLM context (non-breaking)

1. Add candidates to Tier 3 context
2. LLM sees both old hints AND new candidates
3. Monitor LLM responses for quality

### Phase C: Remove early returns (breaking)

1. Remove navigation early return
2. Remove disambiguation early return
3. Add post-LLM routing
4. Full testing of edge cases

---

## Testing Scenarios

### Must Pass

| Query | Expected Behavior |
|-------|-------------------|
| "show me data from the australian bureau of statistics" | Return ABS source, NOT navigate to Bureau County |
| "show me bureau county" | Navigate to Bureau County, IL |
| "what data do you have for australia" | List ABS sources available |
| "show me california" | Navigate to California |
| "show me california population" | Return population data for California |
| "washington" | Ask: "Did you mean Washington state, DC, or one of the 30+ Washington counties?" |

### Edge Cases

| Query | Challenge | Expected |
|-------|-----------|----------|
| "world bank data for europe" | "world" could match locations | Data request, not navigation |
| "show me the capital of france" | "capital" pattern vs "france" location | Reference lookup for capital |
| "census data" | Generic source name | Ask which census (US, Canada, Australia?) |

---

## Order Context Reference Pattern

### Problem: "Show me the same data for Poland"

When user has an existing order and requests "the same" for a different location:

```
User: "what eurostat data do you have for spain"
Bot: Lists 9 metrics (Births, Deaths, GDP, etc.) from 2000-2024

User: "show me all metrics"
Bot: Added to order. [Spain, eurostat_demo, all metrics, 2000-2024]

User: "show me the same data for poland"
Bot: Should ask: "Would you like to add to your current order or start a new order?"
```

### Detection Signals

**Reference patterns** (indicate "duplicate with changes"):
- "same data for {location}"
- "same thing for {location}"
- "do that for {location}"
- "also for {location}"
- "and for {location}"
- "{location} too"
- "repeat for {location}"

**Context required:**
- Previous order exists in chat history or active order state
- New location is different from previous order's location

### Clarification Question

When detected, ask:

```
{
    "type": "clarify",
    "question": "Would you like to add Poland to your current order or start a new order?",
    "options": [
        {"label": "Add to order", "action": "append", "description": "View Spain and Poland together"},
        {"label": "New order", "action": "replace", "description": "Replace Spain with Poland"}
    ]
}
```

### Implementation Approaches

#### Approach 1: Order State Tracking

Track active order in session state:

```python
# Session state
active_order = {
    "locations": ["ESP"],
    "source_id": "eurostat_demo",
    "metrics": ["births", "deaths", "gdp_million_eur", ...],
    "year_start": 2000,
    "year_end": 2024
}

# When "same for poland" detected:
def handle_reference_pattern(query, active_order):
    new_location = extract_location(query)  # "POL"

    if active_order:
        return {
            "type": "clarify_order_action",
            "question": "Would you like to add to your current order or start a new order?",
            "options": [
                {"label": "Add to order", "action": "append"},
                {"label": "New order", "action": "replace"}
            ],
            "pending_location": new_location,
            "existing_order": active_order
        }
```

#### Approach 2: LLM Context Injection

Pass order context to LLM, let it decide:

```
[ORDER CONTEXT]
Active order:
- Location: Spain (ESP)
- Source: eurostat_demo
- Metrics: births, deaths, gdp_million_eur, gdp_per_capita_eur, ...
- Years: 2000-2024
- Status: Ready to display

User query: "show me the same data for poland"

This appears to be a request to duplicate the current order for a different location.
Ask user: "Would you like to add Poland to your current order or start a new order?"
```

#### Approach 3: Frontend Order Manager

Let frontend track orders and handle duplication:

```javascript
// Frontend order state
const orderManager = {
    current: {
        locations: ["ESP"],
        source: "eurostat_demo",
        metrics: [...],
        years: [2000, 2024]
    },

    handleDuplicateRequest(newLocation) {
        // Show modal: "Add to order" vs "New order"
        showOrderActionModal({
            question: "Would you like to add Poland to your current order or start a new order?",
            onAdd: () => this.appendLocation(newLocation),
            onNew: () => this.createNewOrder(newLocation)
        });
    }
};
```

### Response Handling

**If "Add to order":**
```python
# Append location to existing order
active_order["locations"].append("POL")
return {
    "type": "order_updated",
    "message": "Added Poland to your order. You now have Spain and Poland.",
    "order": active_order
}
```

**If "New order":**
```python
# Create new order with same parameters but new location
new_order = {
    **active_order,
    "locations": ["POL"]
}
return {
    "type": "order",
    "message": "Created new order for Poland with the same metrics.",
    "order": new_order
}
```

### Related Patterns

| Pattern | Example | Clarification Needed? |
|---------|---------|----------------------|
| "same for X" | "same data for Poland" | Yes - add or replace |
| "also for X" | "also for Germany" | No - implies add |
| "instead for X" | "show Poland instead" | No - implies replace |
| "compare X and Y" | "compare Spain and Poland" | No - implies add both |

### Confidence Scoring

| Signal | Score for "duplicate_order" intent |
|--------|-----------------------------------|
| "same" + location | 0.9 |
| "also" + location | 0.8 |
| Active order exists | +0.2 |
| No active order | -0.5 (can't duplicate nothing) |
| Location is different from order | +0.1 |
| Location is same as order | -0.3 (why duplicate?) |

---

## Success Metrics

1. **Accuracy**: "australian bureau of statistics" query returns ABS data 100% of time
2. **No regressions**: Existing navigation queries still work
3. **LLM cost**: May increase slightly (more context), but fewer user frustrations
4. **Latency**: Should remain similar (preprocessing is fast, LLM is the bottleneck)

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| LLM hallucinations with more context | Strict response schema validation |
| Increased token usage | Limit candidates to top 3 per category |
| Breaking existing behavior | Phased migration with feature flags |
| Performance regression | Cache candidate scoring |

---

## Overlay Context Integration (Merged from disaster_integration)

Now that overlay state and cache stats are passed to the chat system, the LLM can make context-aware decisions about data sources.

### Active Overlay Context in Tier 3

The preprocessor now receives:
- `activeOverlays`: {type, filters, allActive}
- `cacheStats`: {overlayId: {count, years, minMag, maxMag, ...}}

This should be included in the LLM context so it can make intelligent routing decisions.

### Context-Aware Response Types

| Active Overlay | Query Topic | LLM Decision | Response |
|---------------|-------------|--------------|----------|
| earthquakes | earthquakes | Use events cache | Answer from cache, no DB query needed |
| demographics | earthquakes | Use aggregates | "Showing earthquake impact stats by county" |
| none | earthquakes | Suggest overlay | "Enable the Earthquakes overlay to see events on the map" |
| earthquakes | volcanoes | Overlay mismatch | "You're asking about volcanoes but have earthquakes active. Switch overlay?" |

### LLM Context Format

```
[OVERLAY CONTEXT]
Active overlay: earthquakes
Current filters: magnitude >= 5.5, years 2010-2024
Cache status: 1,247 events loaded (mag 5.5-9.1)

If user asks about displayed events, reference the cache stats above.
If user asks about a different disaster type, suggest switching overlays.
If no overlay is active and user asks about disasters, suggest enabling one.
```

### Filter Intent Integration

Filter intents (read_filters, change_filters) are now detected by preprocessor and included in candidates:

```python
candidates["filter_intent"] = {
    "type": "read_filters",  # or "change_filters"
    "overlay": "earthquakes",
    "confidence": 0.9,
    "parsed_values": {"minMagnitude": 3.0, "maxMagnitude": 5.0}  # if change
}
```

The LLM decides whether to:
1. Answer from cache (filter read)
2. Return filter_update response (filter change)
3. Ask for clarification (ambiguous filter request)

---

## Phase 5: Disaster Location Filtering (NEW - 2026-01-12)

This section documents the critical gap in chat-disaster integration: **location-based filtering**.

### The Core Problem

The entire system is missing location-based disaster filtering. Users cannot ask:
- "Show me earthquakes in California"
- "Tornadoes in Texas counties"
- "Which fires affected North Africa"
- "How many floods were in Indonesia"

Even though disaster data has `loc_id` columns (tornadoes have county-level loc_ids like `USA-TX-48451`), there's no way to filter by location anywhere in the stack.

### Current State: Severity Filters Only

| Component | Has Severity Filters | Has Location Filters |
|-----------|---------------------|----------------------|
| API Endpoints | YES (magnitude, scale, VEI, area) | NO |
| Overlay Controller | YES (buildYearUrl) | NO |
| Preprocessor | YES (detect_filter_intent) | NO |
| Chat Panel | YES (applyFilterUpdate) | NO |

### Disaster loc_id Status

| Dataset | Has loc_id | Granularity | Can Filter By Location |
|---------|-----------|-------------|------------------------|
| Tornadoes | YES | County (USA-TX-48451) | NO - API doesn't accept it |
| Earthquakes | YES | Country only (USA, JPN) | NO |
| Volcanoes | YES | Country only (GRC, TZA) | NO |
| Tsunamis | YES | Ocean codes (XOO, XOI) | NO |
| Tropical Storms | YES | Ocean codes (XOI, XOP) | NO |
| Floods | Column exists, ALL NULL | None | NO - needs loc_id assignment |
| Wildfires | NO column | None | NO - needs loc_id assignment |

**Key insight**: Tornadoes have proper county-level loc_ids and could support fast location queries, but the infrastructure to use them doesn't exist.

### Performance Implication

**With loc_ids (fast path):**
```python
# "Tornadoes in Texas" - instant string filter
df[df['loc_id'].str.startswith('USA-TX')]  # ~50ms
```

**Without loc_ids (slow path):**
```python
# Point-in-polygon for every event against geometry
for fire in fires:  # 106K fires
    for county in texas_counties:  # 254 counties
        if county.contains(Point(fire.lon, fire.lat)):  # EXPENSIVE
```

---

### Issue 1: API Endpoints Don't Accept Location Params

**app.py - All disaster endpoints missing loc_id:**

| Endpoint | Current Params | Missing |
|----------|---------------|---------|
| `/api/earthquakes/geojson` | year, min_magnitude, limit | loc_id, loc_prefix, state |
| `/api/tornadoes/geojson` | year, min_year, min_scale | loc_id, loc_prefix, state |
| `/api/wildfires/geojson` | year, min_area_km2 | loc_id, loc_prefix, country |
| `/api/hurricanes/storms` | year, us_landfall | loc_id, state |
| `/api/floods/geojson` | year, include_geometry | loc_id, country |
| `/api/eruptions/geojson` | year, min_vei | loc_id, country |
| `/api/tsunamis/geojson` | year, cause | loc_id, country |

**Required change:**
```python
@app.get("/api/tornadoes/geojson")
async def get_tornadoes_geojson(
    year: int = None,
    min_scale: str = None,
    loc_id: str = None,      # NEW: exact match "USA-TX-48201"
    loc_prefix: str = None   # NEW: prefix match "USA-TX" for all Texas
):
    df = pd.read_parquet(events_path)

    # NEW: Location filtering
    if loc_id:
        df = df[df['loc_id'] == loc_id]
    elif loc_prefix:
        df = df[df['loc_id'].str.startswith(loc_prefix)]
```

---

### Issue 2: Preprocessor Only Detects Severity Filters

**preprocessor.py:1270-1331** - `detect_filter_intent()` handles:
- minMagnitude/maxMagnitude (earthquakes)
- minVei (volcanoes)
- minCategory (hurricanes)
- minScale (tornadoes)
- minAreaKm2 (wildfires)

**Missing:** No detection for location filters.

**Pattern examples not detected:**
- "earthquakes in California" -> should extract loc_prefix: "USA-CA"
- "tornadoes in Harris County Texas" -> should extract loc_id: "USA-TX-48201"
- "fires in Australia" -> should extract loc_prefix: "AUS"

**Required change:**
```python
def detect_location_filter_intent(query, active_overlays):
    """
    Detect location-based filter requests for disaster overlays.

    Returns:
        {
            "overlay": "earthquakes",
            "location_filter": {
                "loc_id": "USA-CA-6037",      # Exact match
                "loc_prefix": "USA-CA",        # Prefix match
                "country": "USA"               # Country filter
            }
        }
    """
    # Pattern: "{disaster} in {location}"
    # Pattern: "{location} {disaster}"
    # Pattern: "{disaster} near {city}"
```

---

### Issue 3: Overlay Controller Can't Apply Location Filters

**overlay-controller.js:435-476** - `buildYearUrl()` only sends severity params:
```javascript
if (overrides.minMagnitude !== undefined) {
  effectiveParams.min_magnitude = String(overrides.minMagnitude);
}
// ... minCategory, minScale, minAreaKm2, minVei
// NO loc_id, loc_prefix, or geographic params
```

**Required change:**
```javascript
// Add to buildYearUrl():
if (overrides.locId) {
  effectiveParams.loc_id = overrides.locId;
}
if (overrides.locPrefix) {
  effectiveParams.loc_prefix = overrides.locPrefix;
}
if (overrides.bbox) {
  effectiveParams.bbox = overrides.bbox.join(',');
}
```

**Also missing from getActiveFilters() (line 4290-4314):**
- minVei not returned (bug)
- No location filter state returned

---

### Issue 4: Chat Panel Doesn't Send Location Context for Disasters

**chat-panel.js:370-414** - `sendQuery()` sends:
- query text
- viewport bounds (general)
- activeOverlays (type + severity filters only)
- cacheStats (counts, years, magnitude ranges)

**Missing:** No explicit location filter for disaster queries.

**Required change to applyFilterUpdate():**
```javascript
applyFilterUpdate(response) {
  const overlay = response.overlay;
  const filters = response.filters;

  // Existing severity filters
  if (filters.clear) {
    OverlayController.clearFilters(overlay);
  } else {
    OverlayController.updateFilters(overlay, filters);
  }

  // NEW: Location filters
  if (response.location_filter) {
    OverlayController.updateFilters(overlay, {
      locId: response.location_filter.loc_id,
      locPrefix: response.location_filter.loc_prefix
    });
  }

  OverlayController.reloadOverlay(overlay);
}
```

---

### Issue 5: Early Returns Bypass Location+Disaster Combination

**preprocessor.py:1732-1764** - Navigation early returns prevent combining location with disaster context:

```python
# Line 1764: Location extraction only if NOT navigation
if not navigation and not disambiguation:
    location_result = extract_country_from_query(query, viewport=viewport)
```

Queries like "show me California earthquakes" might:
1. Trigger navigation path (matches "show me")
2. Extract "California" as navigation target
3. Never connect it to "earthquakes" filter context

**Required change:** Don't early-return for navigation when disaster keywords present. Instead, pass both location AND disaster context to LLM for proper interpretation.

---

### Issue 6: Missing Cross-Reference Between Location and Overlay

**Current flow:**
1. Preprocessor detects "California" -> location candidate
2. Preprocessor detects "earthquakes" -> topic candidate
3. These are NOT connected

**Required flow:**
1. Preprocessor detects "California" -> location candidate
2. Preprocessor detects "earthquakes" -> maps to overlay
3. Preprocessor connects them: "filter earthquakes overlay to California"
4. Returns: `{overlay: "earthquakes", location_filter: {loc_prefix: "USA-CA"}}`

---

### Implementation Plan

#### Phase 5.1: Add loc_id to API endpoints (Backend)

Files: `app.py`

For each disaster endpoint:
1. Add `loc_id: str = None` parameter
2. Add `loc_prefix: str = None` parameter
3. Add filtering logic before returning GeoJSON

Priority order (based on loc_id quality):
1. Tornadoes - has county-level loc_ids
2. Earthquakes - has country-level loc_ids
3. Volcanoes - has country-level loc_ids
4. Tsunamis - has ocean codes
5. Hurricanes - has ocean codes
6. Floods - needs loc_id assignment first
7. Wildfires - needs loc_id assignment first

#### Phase 5.2: Add location filter detection (Preprocessor)

Files: `mapmover/preprocessor.py`

1. Create `detect_location_filter_intent(query, active_overlays)`
2. Add patterns for "{disaster} in {location}"
3. Connect location detection to overlay context
4. Return combined filter intent

#### Phase 5.3: Wire location filters through overlay controller (Frontend)

Files: `static/modules/overlay-controller.js`

1. Add `locId`, `locPrefix` to `buildYearUrl()`
2. Add location filters to `getActiveFilters()`
3. Fix missing `minVei` in `getActiveFilters()`

#### Phase 5.4: Update chat response handling (Frontend)

Files: `static/modules/chat-panel.js`

1. Add `location_filter` handling to `applyFilterUpdate()`
2. Include location scope in `getCacheStats()`
3. Pass location context with disaster queries

#### Phase 5.5: Add filter_update response for locations (Backend)

Files: `app.py` - `handle_filter_intent()`

1. Handle location filter intents
2. Return `filter_update` response with `location_filter` field
3. Build confirmation messages ("Filtering earthquakes to California...")

---

### Test Cases

Once implemented, these queries should work:

| Query | Expected Behavior |
|-------|-------------------|
| "earthquakes in California" | Filter earthquakes overlay to loc_prefix USA-CA |
| "tornadoes in Harris County Texas" | Filter to loc_id USA-TX-48201 |
| "show me Texas tornadoes" | Same as above with USA-TX prefix |
| "which fires affected Australia" | Filter wildfires to loc_prefix AUS |
| "how many floods in Indonesia" | Count floods with loc_prefix IDN |
| "clear location filter" | Remove loc_id/loc_prefix constraints |
| "magnitude 6+ in Japan" | Combine severity + location filters |

---

### Dependencies

Before Phase 5 can be fully effective:

1. **Wildfires need loc_ids** - Currently no loc_id column
2. **Floods need loc_ids** - Column exists but all NULL
3. **Earthquakes could be improved** - Only country-level, could add state/county
4. **Tropical storms need land loc_ids** - Only ocean codes currently

The user is building a converter for fires and floods that will add loc_ids. Once that's complete, all disaster types can support location filtering.

---

## Brainstorm: Open Questions

### 1. How aggressive should candidate pruning be?

Current plan: Keep top 3 candidates per category. But should we:
- Keep ALL candidates and let LLM see everything?
- Prune more aggressively (top 2) to reduce token cost?
- Use different thresholds per category?

### 2. Should disambiguation happen client-side or server-side?

Options:
- **Server-side (current plan)**: LLM returns disambiguate response, frontend shows options
- **Client-side**: Frontend detects ambiguous terms, shows picker before sending query
- **Hybrid**: Simple disambiguations client-side, complex ones via LLM

### 3. How to handle multi-intent queries?

Example: "show me earthquakes in California and navigate to Los Angeles"
- Two intents: data_request + navigation
- Execute both? Prioritize one? Ask user?

### 4. What's the right confidence threshold?

When should LLM proceed vs ask for clarification?
- High confidence (>0.8): Proceed with best interpretation
- Medium (0.5-0.8): Include alternatives in response
- Low (<0.5): Ask user to clarify

### 5. Order state: Session vs Frontend?

For "same data for Poland" pattern:
- **Session state**: Backend tracks active order, survives refresh
- **Frontend state**: OrderManager tracks, lost on refresh
- **Chat history**: LLM infers from conversation, no explicit state

---

## Decision Points for User

1. **Scope**: Full refactor vs. targeted fix for source-vs-location conflict?
2. **LLM cost**: Accept slightly higher token usage for better accuracy?
3. **Timeline**: Phased migration or big-bang rewrite?
4. **Overlay integration**: Let LLM handle overlay mismatch guidance?
5. **Candidate limit**: Top 3 per category, or different strategy?

---

## Phase 6: Demographics Overlay Integration (NEW - 2026-01-14)

This section documents the gap between chat-based demographics requests and the overlay system.

### The Core Problem

Demographics data from chat displays directly on the map regardless of overlay state. The user cannot:
- Control when demographics data appears (should require Demographics overlay enabled)
- Drill into sub-regions (e.g., Australia -> states -> counties)
- Clear demographics display by toggling overlay off

### Current State: Chat Bypasses Overlay System

| Component | Behavior | Problem |
|-----------|----------|---------|
| OrderManager.confirmOrder() | Calls App.displayData() directly | Ignores overlay state |
| App.displayData() | Renders to map immediately | No overlay check |
| ViewportLoader | Suspended during order mode | No drill-down loading |
| Demographics overlay toggle | Has no effect on chat data | Disconnect |

### Observed Bug Flow

1. User asks "show me births and deaths for Australia"
2. Chat creates order with 2 items (births, deaths)
3. User clicks "Display on Map"
4. Data renders to map immediately
5. Demographics overlay is NOT enabled
6. User cannot zoom into states/territories
7. User cannot toggle off the display

### Expected Behavior

| User Action | Expected Result |
|-------------|-----------------|
| Confirm demographics order | Enable Demographics overlay automatically |
| Toggle Demographics OFF | Clear demographics choropleth from map |
| Zoom into Australia | Load state-level data (drill-down) |
| Toggle Demographics ON (no order) | Show last ordered data or prompt for query |

### Root Cause Analysis

**app.js:338-455** - `displayData()` has no overlay awareness:

```javascript
displayData(data) {
  this.currentData = data;
  ViewportLoader.orderMode = true;  // Suspends viewport loading
  // ... renders directly, never checks overlay state
}
```

**chat-panel.js:835-846** - `confirmOrder()` renders without overlay:

```javascript
if (data.type === 'data' && data.geojson) {
  App?.displayData(data);  // Direct render, no overlay enable
}
```

**overlay-controller.js** - Demographics overlay exists but is disconnected from chat:

```javascript
// Demographics overlay config exists
// But chat data doesn't flow through it
```

---

### Implementation Plan

#### Phase 6.1: Enable Overlay on Demographics Order

**Files:** `static/modules/chat-panel.js`, `static/modules/app.js`

When confirming a demographics order:
1. Detect if order is demographics-related (source_id matches demographic sources)
2. Enable Demographics overlay via OverlaySelector
3. Store current order data in overlay state
4. Render through overlay system, not direct displayData()

```javascript
// chat-panel.js - confirmOrder()
if (data.type === 'data' && data.geojson) {
  const isDemographics = this.isDemographicsOrder(this.currentOrder);

  if (isDemographics) {
    // Enable overlay and let it handle display
    OverlaySelector.enableOverlay('demographics');
    DemographicsOverlay.setOrderData(data);
  } else {
    // Non-demographic data (events, etc.)
    App?.displayData(data);
  }
}
```

#### Phase 6.2: Create Demographics Overlay Controller

**Files:** New `static/modules/demographics-overlay.js` or extend `overlay-controller.js`

Demographics overlay should:
1. Store current order data
2. Render choropleth when enabled
3. Clear choropleth when disabled
4. Support drill-down via ViewportLoader

```javascript
const DemographicsOverlay = {
  currentData: null,

  setOrderData(data) {
    this.currentData = data;
    if (OverlaySelector.isEnabled('demographics')) {
      this.render();
    }
  },

  onEnable() {
    if (this.currentData) {
      this.render();
    } else {
      // Prompt user to request data via chat
      ChatManager.addMessage('Ask for demographic data to display.', 'system');
    }
  },

  onDisable() {
    ChoroplethManager.reset();
    TimeSlider.reset();
  },

  render() {
    // Use existing displayData flow but through overlay
    App.displayData(this.currentData);
  }
};
```

#### Phase 6.3: Enable Drill-Down for Demographics

**Files:** `static/modules/viewport-loader.js`, `app.py`

Currently `ViewportLoader.orderMode = true` suspends all viewport loading. Instead:

1. Keep viewport loading active for demographics
2. When zooming, fetch child region data for current metric
3. Merge child data into TimeSlider state

```javascript
// viewport-loader.js
async loadViewport(bounds) {
  // Don't skip if demographics overlay is active
  if (this.orderMode && !OverlaySelector.isEnabled('demographics')) {
    return;
  }

  if (OverlaySelector.isEnabled('demographics') && DemographicsOverlay.currentData) {
    // Load child regions for current order
    const order = DemographicsOverlay.currentData;
    const childData = await this.fetchChildRegions(bounds, order);
    TimeSlider.mergeData(childData);
  }
}
```

**Backend support needed:**

```python
@app.post("/api/demographics/drill")
async def demographics_drill(request: Request):
    """
    Fetch child region data for current order.
    Called when user zooms into a region.
    """
    body = await decode_request_body(request)
    parent_loc_id = body.get('parent_loc_id')
    metrics = body.get('metrics')
    years = body.get('years')

    # Get children of parent
    children = get_child_regions(parent_loc_id)

    # Fetch data for children
    data = fetch_demographics_data(children, metrics, years)

    return msgpack_response(data)
```

---

### Test Cases

| Query | Expected Behavior |
|-------|-------------------|
| "births for Australia" + Display | Demographics overlay enables, Australia choropleth shows |
| Toggle Demographics OFF | Choropleth clears |
| Toggle Demographics ON | Previous data re-renders |
| Zoom into Australia | States load with same metric |
| "deaths for Texas" | Demographics enables, Texas shows, zoom shows counties |
| Clear order | Demographics overlay disables (or shows prompt) |

---

### Dependencies

1. **OverlaySelector API** - Need `enableOverlay(id)` and `isEnabled(id)` methods
2. **TimeSlider.mergeData()** - Need ability to add child region data
3. **Backend drill endpoint** - New API for fetching child data
4. **Order-to-overlay mapping** - Detect which orders are demographics vs events

---

### Related Issues

1. **Order panel flash/disappear** - OrderManager renders then something clears it
   - Likely race condition with overlay state
   - Fix: Ensure order display is stable before overlay toggle

2. **'event-circle' layer error** - Disaster click handler queries missing layer
   - Quick fix: Guard with layer existence check
   - Location: `map-adapter.js:707`

---

*Last Updated: 2026-01-14*
*Merged overlay context integration from chat_disaster_integration.md*
*Added Phase 5: Disaster Location Filtering - comprehensive analysis of loc_id filtering gaps*
*Added Phase 6: Demographics Overlay Integration - chat-overlay disconnect and drill-down*
