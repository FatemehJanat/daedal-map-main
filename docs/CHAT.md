# Chat System

The chat interface uses a "fast food kiosk" model where one LLM interprets user requests, builds orders, and guides users to available data.

**Status**: Phase 2 Complete - Preprocessing, Postprocessing, Derived Fields, Navigation Mode

---

## Architecture Overview

```
+------------------+     +------------------+     +------------------+
|   Preprocessor   | --> |   Order Taker    | --> |   Postprocessor  |
|   (Python code)  |     |      (LLM)       |     |   (Python code)  |
+------------------+     +------------------+     +------------------+
        |                        |                        |
  Extract hints            Talk to user              Validate items
  Resolve locations        Read from catalog         Expand derived fields
  Detect patterns          Suggest options           Build display items
  Load references          Add to order              Return validation
        |                        |                        |
        v                        v                        v
+------------------+     +------------------+     +------------------+
|   Tier 3/4       | --> |   Order Screen   | --> |   Order Filler   |
|   Context        |     |   (User View)    |     |  (Python code)   |
+------------------+     +------------------+     +------------------+
                                 |                        |
                           Shows order              Creates "empty boxes"
                           User can edit            Fills from each source
                           Delete with X            Calculates derived fields
                           [Display] button         Builds GeoJSON
```

**Key files**:
- [mapmover/preprocessor.py](../mapmover/preprocessor.py) - Topic extraction, region resolution, pattern detection
- [mapmover/order_taker.py](../mapmover/order_taker.py) - LLM interprets requests with context injection
- [mapmover/postprocessor.py](../mapmover/postprocessor.py) - Validation, derived field expansion
- [mapmover/order_executor.py](../mapmover/order_executor.py) - Executes orders, calculates derived fields

---

## Tiered Context System (Prompt Optimization)

The chat uses a four-tier context system to minimize token usage while maintaining conversation quality.

### Tier 1: System Prompt (~2,500 tokens, cached)

Contains condensed, high-level information loaded once per session:
- Role description and output format
- Robust catalog (source names, categories, topic tags, key metrics)
- Region list (names only, not full country code mappings)

### Tier 2: Preprocessor (0 LLM tokens)

Pure Python processing BEFORE the LLM call:

```python
# mapmover/preprocessor.py
def preprocess_query(query, viewport=None):
    return {
        "topics": extract_topics(query),           # ["economy", "health"]
        "regions": resolve_regions(query),          # "Europe" -> 27 country codes
        "location": extract_country_from_query(query, viewport),  # City -> country
        "time": detect_time_patterns(query),        # "trend", "2020-2023"
        "reference_lookup": detect_reference_lookup(query),  # SDG, capitals, languages
        "navigation": detect_navigation_intent(query),  # "show me Paris"
        "disambiguation": check_ambiguous_locations(query, viewport),  # Multiple matches
    }
```

### Tier 3: Just-in-Time Context (~500-1000 tokens)

Query-specific context injected into the LLM prompt:
- Resolved regions with country counts
- Detected time patterns
- Viewport admin level (what the user is currently viewing)
- **Country data summary** from index.json (what datasets are available)
- **Metric column hints** - exact column names for relevant sources

**Metric Hints Injection** (added 2026-01):

When a location or topic is detected, the preprocessor injects available data sources with exact column names:

```
[COUNTRY DATA SUMMARY: Australia sub-national data: 2 datasets. Demographics: 547 LGAs
with population estimates (2001-2024)...]

[AVAILABLE DATA SOURCES for this query - USE THESE EXACT METRIC NAMES:]
- Australian Bureau of Statistics (abs_population): metrics=[total_pop]
- Bureau of Meteorology (bom_cyclones): metrics=[season, total_cyclones...]
```

**Source selection logic** (`get_relevant_sources_with_metrics()`):
- **Location specified**: Include ALL sources for that country + topic-matched global sources
- **Topic only**: Include ANY source (country or global) that matches the topic keywords
- **Both**: Country sources first, then topic-matched global sources

This bidirectional flow means users can ask "earthquake data for Canada" OR "earthquake data" then "for Canada" and get the same results.

### Tier 4: Reference Documents (on-demand)

Loaded only when specific topics are detected:

| Trigger Keywords | Reference File | Example Query |
|-----------------|----------------|---------------|
| "SDG 7", "goal 7" | `un_sdg_07/reference.json` | "What is SDG 7?" |
| "capital of X" | `country_metadata.json` | "What's the capital of China?" |
| "currency", "money in" | `currencies_scraped.json` | "What currency does Japan use?" |
| "language", "speak in" | `languages_scraped.json` | "What languages are spoken in Switzerland?" |
| "economy of X" | `world_factbook_text.json` | "Tell me about Japan's economy" |
| "trade partners" | `world_factbook_text.json` | "Who does Brazil trade with?" |

### Token Usage Comparison

| Approach | Tokens per Query |
|----------|------------------|
| Naive (load everything) | ~25,000 |
| Optimized (four-tier) | ~3,500-4,000 |
| **Reduction** | **~85%** |

---

## Preprocessor Features

### Topic Extraction

Keywords mapped to source categories:
```python
TOPIC_KEYWORDS = {
    "economy": ["gdp", "economic", "income", "wealth", "poverty", "trade"],
    "health": ["health", "disease", "mortality", "life expectancy", "hospital"],
    "environment": ["co2", "carbon", "emissions", "climate", "pollution"],
    "demographics": ["population", "age", "birth", "death", "migration"],
    "hazard": ["earthquake", "volcano", "hurricane", "cyclone", "wildfire", "flood", "tsunami"],
    "development": ["sdg", "sustainable", "development goal"],
}
```

### Region Resolution

Expands region names to country codes using `conversions.json`:
- "Europe" -> 53 countries (or EU -> 27)
- "G7" -> USA, CAN, GBR, FRA, DEU, ITA, JPN
- "Africa" -> 54 countries

### Time Pattern Detection

Detects temporal intent:
```python
# Patterns detected:
- "trend" / "over time" / "historical" -> is_time_series: True
- "from 2015 to 2020" -> year_start: 2015, year_end: 2020
- "in 2023" -> year: 2023
- "latest" / "recent" -> year: None (executor uses most recent)
```

### Location Resolution (City -> Country)

Hierarchical lookup with viewport awareness:
1. Direct country name match (from reference file)
2. Capital city match (from reference file)
3. Viewport-based location match (from geometry parquet files)

```python
# "Paris" -> resolves to France (FRA)
# "Vancouver" with viewport over Canada -> CAN-BC
# "Vancouver" with viewport over USA -> USA-WA
```

### Disambiguation Detection

When multiple locations match a query:
```python
# User: "Show me data for Vancouver"
# Preprocessor detects:
{
    "disambiguation": {
        "needed": True,
        "query_term": "vancouver",
        "options": [
            {"loc_id": "CAN-BC", "country_name": "Canada", "matched_term": "Vancouver"},
            {"loc_id": "USA-WA", "country_name": "United States", "matched_term": "Vancouver"}
        ]
    }
}
```

Frontend enters "selection mode" - highlights candidates on map, user clicks to select.

### Navigation Intent Detection

Detects "show me X" patterns for zooming without data request:

```python
NAVIGATION_PATTERNS = [
    r"^show me\b",
    r"^where is\b",
    r"^zoom to\b",
    r"^go to\b",
    r"^take me to\b",
]

# "show me Simpson and Woodford counties"
# -> Zooms map, highlights locations, prepares empty order for data
```

---

## Postprocessor Features

### Validation Against Catalog

After LLM outputs an order, postprocessor validates each item:

```python
def validate_item(item, catalog):
    # Check source exists
    # Check metric exists in source
    # Add metric_label for display
    # Return with _valid: True/False and _error if invalid
```

### Derived Field Expansion

Simple flags expanded to full specifications:

**Input** (from LLM):
```json
{"source_id": "owid_co2", "metric": "gdp", "region": "EU", "derived": "per_capita"}
```

**Output** (after postprocessor):
```json
[
  {"source_id": "owid_co2", "metric": "gdp", "region": "EU", "for_derivation": true},
  {"source_id": "owid_co2", "metric": "population", "region": "EU", "for_derivation": true},
  {"type": "derived_result", "numerator": "gdp", "denominator": "population", "label": "GDP Per Capita"}
]
```

**Expansion shortcuts**:
```python
DERIVED_EXPANSIONS = {
    "per_capita": {"denominator": "population", "denominator_source": "owid_co2"},
    "density": {"denominator": "area_sq_km", "denominator_source": "world_factbook_static"},
    "per_1000": {"denominator": "population", "multiplier": 1000},
}
```

### Cross-Source Derived Fields

Supports combining metrics from different sources:

```json
{
  "type": "derived",
  "numerator": {"source_id": "owid_co2", "metric": "gdp"},
  "denominator": {"source_id": "imf_bop", "metric": "exports"},
  "region": "EU"
}
```

### Order Panel Display

- Items with `for_derivation: true` are hidden from order panel
- Derived items show as: "GDP Per Capita (calculated)"
- User sees clean order, not internal mechanics

---

## Order Executor: Derived Field Calculation

After fetching all data into boxes:

```python
def apply_derived_fields(boxes, derived_specs, year):
    warnings = []
    for loc_id, metrics in boxes.items():
        for spec in derived_specs:
            num = metrics.get(spec["numerator"])
            denom = get_denominator_value(metrics, spec["denominator"], loc_id, year)

            if denom is None or denom == 0:
                warnings.append(f"{loc_id}: {spec['denominator']} unavailable")
                continue

            result = num / denom
            if spec.get("multiplier"):
                result *= spec["multiplier"]

            label = spec.get("label", f"{spec['numerator']}/{spec['denominator']}")
            metrics[f"{label} (calculated)"] = result
    return warnings
```

### Canonical Sources for Denominators

```python
CANONICAL_SOURCES = {
    "population": "owid_co2",         # Country population
    "area_sq_km": "world_factbook_static",  # Static area data
}

def lookup_canonical_value(metric, loc_id, year):
    # Check canonical sources when metric not already in box
    if metric == "population" and len(loc_id) == 3:
        return lookup_owid_population(loc_id, year)
    # ...
```

---

## Navigation Mode

For "show me X" queries without data requests:

### Backend Response
```python
# type: "navigate" response
{
    "type": "navigate",
    "message": "Showing 2 locations: Simpson, Woodford. What data would you like to see?",
    "locations": [{"loc_id": "...", "matched_term": "Simpson", ...}],
    "loc_ids": ["USA-KY-21213", "USA-KY-21239"]
}
```

### Frontend Behavior
1. Fetches geometries for all locations
2. Calculates bounding box around all features
3. Fits map to bounds with padding
4. Highlights locations with orange/amber selection colors
5. Order panel shows locations with "Add Data First" button

### Use Case
Original motivation: FEMA disaster declarations like:
> "FEMA denied public assistance to Simpson and Woodford counties"

User can say "show me Simpson and Woodford counties" to see them on the map, then ask for specific data.

---

## Disambiguation Mode (Selection Mode)

When multiple locations match a query name (e.g., "Vancouver" or "Washington County"):

### Singular vs Plural Suffix Detection

The system distinguishes user intent by the suffix used:

| Query | Suffix Type | Intent | Response Type |
|-------|-------------|--------|---------------|
| "show me washington county" | Singular | Want ONE | `disambiguate` |
| "show me washington counties" | Plural | Want ALL | `navigate` |
| "show me texas counties" | Plural (drill) | Children | `drilldown` |

**Implementation**: `extract_multiple_locations()` in `preprocessor.py` tracks `suffix_type` ('singular' or 'plural') and sets `needs_disambiguation` when singular suffix finds multiple matches.

### Backend Response
```python
{
    "type": "disambiguate",
    "message": "I found 31 locations matching 'washington county'. Please click on the one you meant:",
    "options": [
        {"loc_id": "USA-AL-01129", "country_name": "United States", "matched_term": "washington"},
        {"loc_id": "USA-AR-05143", "country_name": "United States", "matched_term": "washington"},
        # ... 29 more Washington Counties
    ]
}
```

### Frontend Behavior (SelectionManager)
1. Freezes map (disables pan/zoom/click)
2. Dims existing map layers
3. Fetches and highlights candidate locations
4. Shows instruction overlay with parent context (e.g., "washington (AL)", "washington (AR)")
5. User clicks location to select, or clicks away to cancel
6. On selection, retries original query with resolved `loc_id`
7. Stores options in `lastDisambiguationOptions` for "show them all" follow-up

---

## Show Borders Follow-up

After disambiguation lists multiple locations, users can display all of them on the map without picking one. See [MAPPING.md](MAPPING.md) for visualization details.

### Trigger Phrases

```python
SHOW_BORDERS_PATTERNS = [
    r"^(?:just\s+)?show\s+(?:me\s+)?(?:them|all|all\s+of\s+them)\b",
    r"^display\s+(?:them|all|all\s+of\s+them)\b",
    r"^(?:put|display|show)\s+(?:them\s+)?(?:all\s+)?on\s+(?:the\s+)?map\b",
    r"^(?:just\s+)?the\s+(?:borders?|geometr(?:y|ies)|locations?)\b",
]
```

Examples: "just show me them", "display them all", "show all of them on the map"

### Flow

```
User: "show me washington county"
Bot: "I found 31 locations matching 'washington county'. Please click..."
     [Options stored in lastDisambiguationOptions]

User: "just show me them"
      [detect_show_borders_intent() matches pattern]
      [Backend receives previous_disambiguation_options from frontend]
      [fetch_geometries_by_loc_ids() loads all 31 geometries]

Bot: "Showing 31 locations on the map. Click any location to see data options."
     [Map displays all Washington Counties highlighted]
```

### Backend Implementation

```python
# app.py - chat endpoint
if hints.get("show_borders"):
    previous_options = body.get("previous_disambiguation_options", [])
    if previous_options:
        loc_ids = [opt.get("loc_id") for opt in previous_options]
        geojson = fetch_geometries_by_loc_ids(loc_ids)
        return {"type": "navigate", "geojson": geojson, ...}
```

### Frontend Integration

```javascript
// chat-panel.js
ChatManager.lastDisambiguationOptions = null;  // Stored on disambiguate response

// Passed with each query
body: JSON.stringify({
    query,
    previous_disambiguation_options: this.lastDisambiguationOptions || []
})
```

---

## Chat Endpoint Flow

```python
@app.post("/chat")
async def chat(request):
    # Step 1: Preprocess query
    hints = preprocess_query(query, viewport)

    # Step 2: Check for navigation intent (no LLM needed)
    if hints.get("navigation", {}).get("is_navigation"):
        return {"type": "navigate", "locations": hints["navigation"]["locations"]}

    # Step 3: Check for disambiguation needed (no LLM needed)
    if hints.get("disambiguation", {}).get("needed"):
        return {"type": "disambiguate", "options": hints["disambiguation"]["options"]}

    # Step 4: LLM interprets request with context
    result = interpret_request(query, chat_history, hints=hints)

    # Step 5: Postprocess order
    if result["type"] == "order":
        processed = postprocess_order(result["order"], hints)
        display_items = get_display_items(processed["items"], processed["derived_specs"])
        return {"type": "order", "order": {...}, "full_order": processed}

    return result

@app.post("/display")  # When user clicks "Display on Map"
async def display(order):
    # Order executor fills boxes and calculates derived fields
    geojson = execute_order(order)
    return geojson
```

---

## LLM Message Assembly Order

The order of messages sent to the LLM is critical for ensuring current context takes priority over historical conversations.

### Message Structure

```
[1] SYSTEM: Main prompt (Tier 1 - catalog, regions, rules)
[2] SYSTEM: [CURRENT CONTEXT] Tier 3 + Tier 4  <-- BEFORE history
[3-6] Chat history (last 4 messages)
[7] USER: Current query
```

### Why Context Before History

Previous issue: When a user discussed USA data, then asked about Australia, the LLM would sometimes use USA context because chat history came AFTER the tier3 context.

**Fix (2026-01)**: Move tier3/tier4 context BEFORE chat history with explicit header:

```python
# order_taker.py - interpret_request()
messages = [{"role": "system", "content": system_prompt}]

# Tier 3/4 context BEFORE chat history
if hints:
    tier3_context = build_tier3_context(hints)
    tier4_context = build_tier4_context(hints)
    if tier3_context or tier4_context:
        messages.append({
            "role": "system",
            "content": "[CURRENT CONTEXT - USE THIS FOR THE CURRENT QUERY]\n" +
                       "\n".join(filter(None, [tier3_context, tier4_context]))
        })

# Chat history AFTER current context
if chat_history:
    for msg in chat_history[-4:]:
        messages.append({"role": msg.get("role"), "content": msg.get("content")})

messages.append({"role": "user", "content": user_query})
```

### Tier 3 Context Contents

Built by `build_tier3_context(hints)` based on preprocessor analysis:

```
[CURRENT CONTEXT - USE THIS FOR THE CURRENT QUERY]
[VIEWPORT: User is viewing at countries level]
[LOCATION: Australia (loc_id=AUS)]
User wants data from 2010 to 2024

[CRITICAL - EXACT METRIC NAMES REQUIRED:]
You MUST use these EXACT column names. Do NOT use aliases like 'total_population' - use:
- abs_population: ["total_pop", "births", "deaths", "natural_increase", "internal_arrivals", ...]
- owid_co2: ["co2", "population", "gdp", ...]
```

### Viewport Inference Rules

The viewport context only infers country when ALL conditions are met:
1. User did NOT explicitly mention a location in their query
2. Zoom level >= 3 (not at global overview)
3. Single country visible in viewport bounds

```python
# preprocessor.py - build_tier3_context()
if not explicit_location and viewport.get("bounds") and zoom_level >= 3:
    countries_in_view = get_countries_in_viewport(viewport["bounds"])
    if len(countries_in_view) == 1:
        # Add inferred location context
```

This prevents inferring "USA" when viewing global overview with USA roughly centered.

---

## Time Pattern Detection and Injection

### Detection Patterns

```python
TIME_PATTERNS = {
    "year_range": [
        r"from\s+(\d{4})\s+to\s+(\d{4})",      # "from 2010 to 2020"
        r"between\s+(\d{4})\s+and\s+(\d{4})",   # "between 2015 and 2024"
    ],
    "year_to_now": [
        r"from\s+(\d{4})\s+(?:to|until)\s+(?:now|present|today|current)",
        # "from 2010 to now", "2015 to present"
    ],
    "trend_indicators": [
        r"\ball\s+(?:the\s+)?years?\b",         # "all years", "all the years"
        r"\btrend\b", r"\bover time\b",
        r"\bhistor(?:y|ical)\b",
    ],
    "last_n_years": [r"last\s+(\d+)\s+years?"], # "last 5 years"
    "since_year": [r"since\s+(\d{4})"],          # "since 2015"
}
```

### Postprocessor Year Injection

When the LLM leaves `year: null` and preprocessor detected a time pattern, postprocessor injects:

```python
# postprocessor.py - postprocess_order()
time_hints = hints.get("time", {})
if time_hints.get("is_time_series"):
    for item in items:
        if item.get("year") is None and not item.get("year_start"):
            # Case 1: Specific range detected (e.g., "from 2010 to now")
            if time_hints.get("year_start") and time_hints.get("year_end"):
                item["year_start"] = time_hints["year_start"]
                item["year_end"] = time_hints["year_end"]

            # Case 2: Trend detected but no specific years (e.g., "all years")
            # Look up source metadata for actual available range
            elif time_hints.get("pattern_type") == "trend" and item.get("source_id"):
                metadata = load_source_metadata(item["source_id"])
                if metadata:
                    temp = metadata.get("temporal_coverage", {})
                    item["year_start"] = temp.get("start")
                    item["year_end"] = temp.get("end")
```

This means "all the years you have" for abs_population automatically gets 2001-2024 from metadata.

---

## Wildcard Metric Expansion

### Problem

The LLM only sees a limited number of metrics in its context (to avoid token bloat). When user asks for "all Australian data", the LLM could only output items for the 5 metrics it knew about.

### Solution

LLM can use `"metric": "*"` to mean "all metrics from this source". The postprocessor expands it using full metadata access.

### LLM Prompt

```
WILDCARD METRICS:
Use "metric": "*" when user asks for "all data", "everything", or "all metrics" from a source.
Example: {"source_id": "abs_population", "metric": "*", "region": "australia"}
This will be expanded to include ALL metrics from that source.
```

### Postprocessor Expansion

```python
# postprocessor.py - expand_wildcard_metrics()
def expand_wildcard_metrics(items: list) -> list:
    for item in items:
        if item.get("metric") in ("*", "all", "all_metrics"):
            source_id = item.get("source_id")
            metadata = load_source_metadata(source_id)

            # Create one item per metric in the source
            for metric_key in metadata.get("metrics", {}):
                expanded.append({
                    "source_id": source_id,
                    "metric": metric_key,
                    "region": item.get("region"),
                    "year": item.get("year"),
                    # ... other properties
                })
```

### Example Flow

```
User: "Show me all Australian population data"
LLM outputs: {"source_id": "abs_population", "metric": "*", "region": "australia"}
Postprocessor: Loads abs_population metadata, expands to 11 items:
  - total_pop, births, deaths, natural_increase
  - internal_arrivals, internal_departures, internal_net
  - overseas_arrivals, overseas_departures, overseas_net
  - area_km2
```

This keeps the LLM prompt small while giving full access through the postprocessor.

---

## Order Format

```json
{
  "items": [
    {
      "source_id": "owid_co2",
      "metric": "gdp",
      "metric_label": "GDP (USD)",
      "region": "Europe",
      "year": 2024,
      "_valid": true
    },
    {
      "type": "derived",
      "metric": "GDP Per Capita",
      "metric_label": "GDP Per Capita (calculated)",
      "_is_derived": true
    }
  ],
  "derived_specs": [
    {"numerator": "gdp", "denominator": "population", "label": "GDP Per Capita"}
  ]
}
```

---

## Reference File Loading

### Reference Types

| Type | File | Content |
|------|------|---------|
| SDG Goals | `un_sdg_XX/reference.json` | Goal name, targets, description |
| Capitals | `reference/country_metadata.json` | Capital cities |
| Currencies | `reference/currencies_scraped.json` | Currency codes and names |
| Languages | `reference/languages_scraped.json` | Official/spoken languages |
| Timezones | `reference/timezones_scraped.json` | UTC offsets, DST |
| Country Info | `reference/world_factbook_text.json` | Background, economy, government, trade |

### Detection and Loading

```python
def detect_reference_lookup(query):
    # SDG pattern
    if re.search(r'sdg\s*(\d+)|goal\s*(\d+)', query.lower()):
        return {"type": "sdg", "file": f"un_sdg_{num}/reference.json"}

    # Country-specific patterns
    if any(kw in query.lower() for kw in ["capital of", "currency", "language"]):
        # Load specific country data from reference files
        return {"type": "currency", "country_data": {...}}
```

### Context Injection

```python
def build_tier4_context(hints):
    ref_lookup = hints.get("reference_lookup")
    if ref_lookup and ref_lookup.get("country_data"):
        # Return formatted answer for LLM to use
        return f"[REFERENCE ANSWER: {ref_lookup['country_data']['formatted']}]"
```

---

## Order Filler: The "Empty Box" Model

**Key insight**: The loc_id system gives us a clean unification key. This enables cross-dataset joins without complex SQL.

### How It Works

```
Order:
[
  {metric: "gdp", region: "Europe", year: 2024, source: "owid_co2"},
  {metric: "life_expectancy", region: "Europe", year: 2024, source: "who_health"}
]

Step 1: Expand region to loc_ids
  "Europe" -> [DEU, FRA, GBR, ITA, ESP, ...]

Step 2: Create empty boxes
  {"DEU": {}, "FRA": {}, "GBR": {}, ...}

Step 3: Fill boxes from each source
  Item 1: boxes[loc_id]["gdp"] = value
  Item 2: boxes[loc_id]["life_expectancy"] = value

Step 4: Apply derived field calculations
  boxes[loc_id]["GDP Per Capita (calculated)"] = gdp / population

Step 5: Join with geometry, convert to GeoJSON
```

### Handling Missing Data

```
Box for a country with partial data:
{
  "SOM": {"gdp": 8.1B, "co2": 0.7}  // life_expectancy missing
}

Popup shows:
  Somalia
  GDP: $8.1B
  CO2: 0.7 Mt
  Life Expectancy: N/A
```

---

## Design Decisions

Key decisions made during implementation of the chat system:

| Question | Decision |
|----------|----------|
| Derived field naming | "GDP Per Capita (calculated): $45K" - include indicator in label |
| Missing data | Show warning, omit derived field for that location |
| Preprocessor approach | Start gentle, mostly pass to LLM, build specificity over time |
| Scope | Flexible system - any metric / any metric, not just per capita |
| LLM output format | Simple flag (`derived: "per_capita"`), postprocessor expands |
| Cross-source derivations | Use nested objects: `{"source_id": "x", "metric": "y"}` |
| Auto-add dependencies | Add with `for_derivation: true` flag, hidden from order panel |
| Reference lookups | Tier 4 on-demand context injection for SDG, capitals, languages |
| Catalog in prompt | Keep robust (~2,500 tokens) for good conversation UX |
| Validation approach | Inline after each LLM response, no explicit Verify button |
| Growth rate calculation | Deferred to future enhancement |

---

## Session Memory and Context

### Current State

The chat system maintains conversation context through multiple mechanisms:

**Frontend (chat-panel.js)**:
```javascript
ChatManager = {
  history: [],                      // In-memory message history
  sessionId: null,                  // Generated per page load
  lastDisambiguationOptions: null,  // Stored for "show them all" follow-up
}
```

**What gets sent to backend**:
- `chatHistory: this.history.slice(-10)` - Last 10 messages
- `sessionId` - Unique per page load
- `previous_disambiguation_options` - For show borders follow-up

**Backend (order_taker.py)**:
- Uses `chat_history[-4:]` - Only last 4 messages sent to LLM
- No server-side session storage

### Lifecycle

| Event | Effect |
|-------|--------|
| Page load | New sessionId generated, history cleared |
| Page reload | All context lost |
| Tab close | All context lost |
| Query sent | Added to history array |
| Disambiguation | Options stored in `lastDisambiguationOptions` |

### Future: Unified sessionStorage Persistence

**UX Principle**: If the system "remembers" context, the UI must reflect it. All state must persist together or not at all.

**Target behavior**:
- Page refresh: State persists (chat visible, order intact)
- Tab close: State clears (fresh start)

**State to persist (unified)**:

```javascript
// sessionStorage key: 'mapviewer_session'
{
  // ChatManager state
  "chat": {
    "history": [...],                    // Message history (visible in chat)
    "sessionId": "sess_...",             // Session identifier
    "lastDisambiguationOptions": [...]   // For "show them all" follow-up
  },

  // OrderManager state
  "order": {
    "currentOrder": {...},               // Active order items
    "navigationLocations": [...]         // "Show me X" locations
  },

  // Session context (for preprocessor hints)
  "context": {
    "accessed_datasets": ["abs_population", "owid_co2"],
    "recent_locations": ["AUS", "AUS-NSW"],
    "recent_metrics": ["total_pop", "gdp"]
  }
}
```

**Implementation approach**:

```javascript
// chat-panel.js - Unified session persistence
const SESSION_KEY = 'mapviewer_session';

function saveSession() {
  const state = {
    chat: {
      history: ChatManager.history,
      sessionId: ChatManager.sessionId,
      lastDisambiguationOptions: ChatManager.lastDisambiguationOptions
    },
    order: {
      currentOrder: OrderManager.currentOrder
    },
    context: ChatManager.sessionContext || {}
  };
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(state));
}

function restoreSession() {
  const saved = sessionStorage.getItem(SESSION_KEY);
  if (!saved) return false;

  const state = JSON.parse(saved);

  // Restore chat (including re-rendering messages)
  ChatManager.history = state.chat?.history || [];
  ChatManager.sessionId = state.chat?.sessionId;
  ChatManager.lastDisambiguationOptions = state.chat?.lastDisambiguationOptions;
  ChatManager.sessionContext = state.context || {};
  ChatManager.renderHistory();  // Re-display messages

  // Restore order panel
  if (state.order?.currentOrder) {
    OrderManager.currentOrder = state.order.currentOrder;
    OrderManager.render();
  }

  return true;
}

// In init():
if (!restoreSession()) {
  this.sessionId = 'sess_' + Date.now() + '_' + Math.random().toString(36).substring(2, 11);
}

// Call saveSession() after any state change
```

**Benefits of unified persistence**:
- "Show me more data" -> knows which datasets were just accessed
- "Compare to last year" -> knows which metrics/locations are active
- "What else for Australia?" -> remembers recent location context
- Reduced repeated explanations from LLM
- **Consistent UX** - what user sees matches what system remembers


Error to avoid, talking about australian data made a jump to Has in albania when "show me how australias population has changed over the years" was sent. 

Track recent locations in session context
Boost matching priority for countries in recent context
Or prompt "Did you mean the district Has in Albania?" when context suggests otherwise

The chat remmebering context will know when a location jump is out of place and needs to be confirmed. 
---

## Overlay-Based Intent Detection (TODO)

The overlay selector on the right side provides intent hints to help the preprocessor and LLM understand what data mode the user wants.

### Overlay State as Context

Active overlays should be passed to the preprocessor and included in LLM context:

```python
# preprocessor.py - include in hints
hints["active_overlays"] = ["demographics", "volcanoes"]  # From frontend

# order_taker.py - include in tier 3 context
if hints.get("active_overlays"):
    context += f"\n[ACTIVE OVERLAYS: {', '.join(hints['active_overlays'])}]"
```

### Intent Resolution Logic

| Active Overlay | User Query | Intent | Data Source |
|---------------|------------|--------|-------------|
| demographics | "show me earthquake impacts" | Aggregates | County aggregate data (deaths, damage) |
| earthquakes | "show me earthquake impacts" | Events | events.parquet (point+radius display) |
| volcanoes | "show me volcanic eruptions" | Events | eruptions.parquet |
| volcanoes | "show me the volcanoes" | Static locations | locations.parquet |
| demographics + volcanoes | "volcanoes near Seattle" | Events | eruptions.parquet (overlay is more specific) |

### Query Keyword Mapping

```python
# Different keywords suggest different data modes
EVENT_KEYWORDS = ["eruption", "event", "happened", "occurred", "when did"]
LOCATION_KEYWORDS = ["where are", "locations", "map of", "the volcanoes", "active volcanoes"]
AGGREGATE_KEYWORDS = ["impact", "damage", "deaths", "affected", "counties hit"]

# "show me volcanic eruptions" -> events file
# "show me the volcanoes" -> locations file
# "show me counties affected by volcanoes" -> aggregates
```

### Chat Guidance Responses

When user intent is unclear or overlays don't match the query, the chat should guide:

```python
GUIDANCE_RESPONSES = {
    "no_disaster_overlay": "To see disaster events on the map, please enable an overlay (Earthquakes, Hurricanes, Volcanoes, or Wildfires) on the right panel.",

    "want_aggregates": "If you want to see county-level impacts and statistics, please enable the Demographics overlay.",

    "suggest_overlay": "I see you're asking about earthquakes. Enable the Earthquakes overlay to see events on the map, or keep Demographics to see county impact statistics.",

    "overlay_mismatch": "You're asking about hurricanes but have the Earthquakes overlay active. Would you like me to suggest switching overlays?",
}
```

### Example Chat Flows

**User has Demographics only:**
```
User: "Show me volcanic eruptions in Alaska"
Bot: "To see volcanic eruptions as map events, please enable the Volcanoes overlay on the right.
      With Demographics, I can show you counties affected by volcanic activity instead."
```

**User has Volcanoes overlay:**
```
User: "Show me volcanic eruptions in Alaska"
Bot: [Displays eruption events on map with VEI-based coloring and radius circles]
```

**User asks about static locations:**
```
User: "Where are the volcanoes in the Pacific Northwest?"
Bot: [Uses locations.parquet to show volcano markers, not eruption events]
```

### Implementation Notes

1. **Frontend**: Pass `activeOverlays` array with each chat request
2. **Preprocessor**: Add overlay state to hints, use for intent classification
3. **LLM Context**: Include overlay state so LLM can provide relevant guidance
4. **Postprocessor**: Route to correct data source based on overlay + query analysis
5. **Response Templates**: Add helpful guidance messages when intent is unclear

### File Changes Needed

| File | Changes |
|------|---------|
| static/modules/chat-panel.js | Send `activeOverlays` from OverlaySelector with each query |
| mapmover/preprocessor.py | Add `detect_disaster_intent()` using overlay context |
| mapmover/order_taker.py | Include overlay state in tier 3 context |
| mapmover/postprocessor.py | Route to events vs locations vs aggregates based on intent |

---

## Future Enhancements

### Growth Rate Calculations

Open question on formula approach:
- Simple percentage: (end - start) / start * 100
- CAGR: ((end/start)^(1/years) - 1) * 100
- Year-over-year series

### Direct Data Queries

Enable chat to answer data questions directly:
- "What's the largest GDP?" -> Query parquet, return answer
- v1: LLM answers from training data, offers "check database?" follow-up
- v2: Add "query" response type for direct parquet queries

### Chat Pagination & Clickable Actions

For sources with many metrics (28+):
- Grouped display by category
- Pagination: "Showing 1-10 of 28. Say 'more' for next page"
- v2: Response includes action buttons user can click

### Calculated Score for Overloaded Popups

When too many data points requested (10+):
- Aggregate into percentile score
- Each metric normalized to 0-100% based on min/max in selection
- Optional checkbox beside Display button

---

## Related Files

| File | Purpose |
|------|---------|
| `mapmover/preprocessor.py` | Query preprocessing, pattern detection, show borders intent |
| `mapmover/postprocessor.py` | Order validation, derived field expansion |
| `mapmover/order_taker.py` | LLM interpretation with context |
| `mapmover/order_executor.py` | Execute orders, derived calculations |
| `mapmover/data_loading.py` | `fetch_geometries_by_loc_ids()` for show borders |
| `mapmover/conversions.json` | Regional groupings (56 regions) |
| `mapmover/reference/` | Reference data for Tier 4 context |
| `static/modules/chat-panel.js` | Frontend chat, order UI, disambiguation storage |
| `static/modules/selection-manager.js` | Disambiguation selection mode |
| [MAPPING.md](MAPPING.md) | Show Borders visualization, map rendering |
| [GEOMETRY.md](GEOMETRY.md) | loc_id specification |
| [DATA_PIPELINE.md](DATA_PIPELINE.md) | Data source catalog |

---

*Last Updated: 2026-01-08 - Added overlay-based intent detection notes (TODO), wildcard metric expansion, LLM message ordering*
