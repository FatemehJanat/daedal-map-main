# Chat System

The chat interface uses a "fast food kiosk" model where one LLM interprets user requests, builds orders, and guides users to available data.

**Status**: Phase 1B Complete - Backend + Order Panel UI implemented

---

## Architecture Overview

```
+------------------+     +------------------+     +------------------+
|   Order Taker    | --> |   Order Screen   | --> |   Order Filler   |
|      (LLM)       |     |   (User View)    |     |  (Python code)   |
+------------------+     +------------------+     +------------------+
        |                        |                        |
  Talk to user             Shows order              Creates "empty boxes"
  Read from catalog        User can edit            Fills from each source
  Suggest options          Delete with X            Joins by loc_id
  Add to order             [Display] button         Builds GeoJSON
```

**Key files**:
- [mapmover/order_taker.py](mapmover/order_taker.py) - LLM interprets requests
- [mapmover/order_executor.py](mapmover/order_executor.py) - Executes orders against parquet
- [mapmover/chat_handlers.py](mapmover/chat_handlers.py) - Chat endpoint logic
- [mapmover/llm.py](mapmover/llm.py) - LLM initialization, prompts, parsing

---

## Order Taker LLM

**Role**: Help users discover and select data. Guide them to what's available.

**Model**: gpt-4o-mini

**Input**:
- User message
- Master catalog (read from catalog.json dynamically)
- Current order

**Output**:
- Structured order item to add, OR
- Clarifying question with suggestions from catalog

### Catalog Integration

The LLM reads from `county-map-data/catalog.json` which contains:
- All datasets with descriptions
- All indicators with keywords and synonyms
- Geographic coverage per dataset
- Year ranges
- Topic tags

```python
# Load catalog dynamically - NOT hardcoded
catalog = load_catalog("county-map-data/catalog.json")

prompt = f"""
You are a data guide. Help users find and select data from our catalog.

CATALOG (what we have):
{format_catalog_for_llm(catalog)}

YOUR JOB:
1. Understand what the user is looking for (even if vague)
2. Search the catalog for matches or related data
3. If exact match: add to order, suggest related data
4. If close match: offer options from what we have
5. If no match: explain what topics/regions we DO cover
6. Always guide toward actionable next steps

ASSUME: Users don't know exactly what they want. Help them explore.

Current order: {current_order}
"""
```

---

## Example Conversations

### Vague request - guide to options
```
User: "I want to know about water"

Bot: "I have several water-related datasets:

     Environmental:
     - Rainfall data (142 countries, 1990-2023)
     - Flood risk zones (85 countries)

     Infrastructure:
     - Access to clean water % (WHO, 198 countries)
     - Sanitation coverage (WHO, 198 countries)

     What aspect interests you? And which part of the world?"

Order: unchanged (guiding user)
```

### No exact match - suggest alternatives
```
User: "Show me unemployment rates"

Bot: "I don't have unemployment data yet.

     For economic indicators, I have:
     - GDP and GDP per capita (217 countries)
     - Trade balance (195 countries)
     - Population (for labor force context)

     For US specifically, I have county-level:
     - Population and demographics
     - Age distribution (working age population)

     Would any of these help with your analysis?"

Order: unchanged (offering alternatives)
```

### Good match - add and suggest more
```
User: "GDP for European countries"

Bot: "Added to your order:
     - GDP, Europe (27 countries), 2024

     Related data you might want:
     - Population (to calculate per capita)
     - CO2 emissions (economic/environmental correlation)
     - Life expectancy (development indicator)

     Say 'add population' or 'show me what else you have for Europe'"

Order updated: [{metric: "gdp", region: "Europe", year: 2024, source: "owid_co2"}]
```

---

## Response Limits

**Rule: 3-5 suggestions max per response**

If too many matches, go more general and ask for narrowing:

### Tiered Response Logic

```
If matches > 10:
    Respond with category summaries
    Ask user to narrow by topic or region

If matches 5-10:
    Show top 5 most relevant
    Mention "and X more in [category]"

If matches < 5:
    Show all matches with details
```

---

## Order Format

Simple JSON structure that lives in the UI (not in LLM context):

```json
{
  "items": [
    {
      "id": "item_1",
      "metric": "gdp",
      "metric_label": "GDP",
      "region": "Europe",
      "region_type": "group",
      "year": 2024,
      "source": "owid_co2",
      "added_at": "2025-12-21T20:30:00Z"
    },
    {
      "id": "item_2",
      "metric": "population",
      "metric_label": "Population",
      "region": "Europe",
      "region_type": "group",
      "year": 2024,
      "source": "owid_co2",
      "added_at": "2025-12-21T20:30:15Z"
    }
  ]
}
```

---

## Order Panel UI

```
YOUR ORDER:
+-----------------------------------------+
| GDP                                     |
| Europe | 2024 | owid_co2           [x]  |
+-----------------------------------------+
| Population                              |
| Europe | 2024 | owid_co2           [x]  |
+-----------------------------------------+
| Life Expectancy                         |
| Europe | 2023 | who_health         [x]  |
+-----------------------------------------+

[Clear All]                    [Display -->]
```

**User actions**:
- Click [x] to remove an item
- Click [Display] to execute order (fills boxes, builds GeoJSON)
- Click [Clear All] to start over

---

## Order Filler: The "Empty Box" Model

**Key insight**: The loc_id system gives us a clean unification key. This enables cross-dataset joins without complex SQL.

### How It Works

```
Order:
[
  {metric: "gdp", region: "Europe", year: 2024, source: "owid_co2"},
  {metric: "life_expectancy", region: "Europe", year: 2024, source: "who_health"},
  {metric: "co2", region: "Europe", year: 2024, source: "owid_co2"}
]

Step 1: Expand region to loc_ids
  "Europe" -> [DEU, FRA, GBR, ITA, ESP, POL, NLD, ...]

Step 2: Create empty boxes (one per location)
  {
    "DEU": {},
    "FRA": {},
    "GBR": {},
    ...
  }

Step 3: Process each order item, fill boxes

  Item 1 (gdp from owid_co2):
    -> Query owid_co2 parquet, filter year=2024, filter to Europe loc_ids
    -> For each row: boxes[loc_id]["gdp"] = value

  Item 2 (life_expectancy from who_health):
    -> Query who_health parquet, filter year=2024, filter to Europe loc_ids
    -> For each row: boxes[loc_id]["life_expectancy"] = value

  Item 3 (co2 from owid_co2):
    -> Query owid_co2 parquet, filter year=2024, filter to Europe loc_ids
    -> For each row: boxes[loc_id]["co2"] = value

Step 4: Result - boxes filled with data from multiple sources
  {
    "DEU": {"gdp": 4.2T, "life_expectancy": 81.2, "co2": 674.8},
    "FRA": {"gdp": 2.9T, "life_expectancy": 82.5, "co2": 326.1},
    "GBR": {"gdp": 3.1T, "life_expectancy": 81.0, "co2": 341.5},
    ...
  }

Step 5: Join with geometry, convert to GeoJSON features
```

### Why This Works

1. **loc_id is the universal key** - All datasets use loc_id, so merging is trivial
2. **Each item processed independently** - No complex multi-table JOINs
3. **Partial success is fine** - If WHO is missing data for one country, others still show
4. **Easy to debug** - Can see exactly which box has which fields filled
5. **Cross-dataset joins are free** - Just fill the same box from different sources

### Handling Missing Data

```
Box for a country with partial data:
{
  "SOM": {"gdp": 8.1B, "co2": 0.7}  // life_expectancy missing (no WHO data)
}

Popup shows:
  Somalia
  GDP: $8.1B
  CO2: 0.7 Mt
  Life Expectancy: --
```

The box model handles gaps gracefully - empty fields just show as missing.

---

## Order Limits (Map Display vs Export)

### Chat Order (Map Display)
- **Purpose**: Visual exploration on the map
- **Limit**: ~5-10 metrics per location (popup readability)
- **Output**: GeoJSON with properties for map rendering
- **User**: Anyone using the public interface

### Admin Export (Dataset Builder)
- **Purpose**: Data extraction for analysis
- **Limit**: None - export as much as needed
- **Output**: CSV, Parquet, JSON files
- **User**: Admin via dashboard (not public)
- **Location**: See [ADMIN_DASHBOARD.md](ADMIN_DASHBOARD.md) Page 5: Dataset Builder

---

## Prompt Optimization Strategy

As the catalog grows (6 sources now, potentially 200+), we use a tiered context system to keep prompts efficient.

### The Four Tiers

| Tier | Purpose | Token Cost | When Applied |
|------|---------|------------|--------------|
| 1 | System prompt (cached) | ~2,500 | Once per session |
| 2 | Preprocessing | 0 | Every query |
| 3 | Just-in-time context | ~1,000 | Every query |
| 4 | Reference documents | ~500 | When topic detected |

### Tier 1: Lightweight System Prompt (Always Loaded)

**Size**: ~2,000-3,000 tokens
**Frequency**: Once per session, cached

Contains condensed, high-level information:

```python
def build_system_prompt():
    # Condensed region list (just names, not full mappings)
    regions_available = {
        "Africa": "54 countries",
        "Europe": "53 countries",
        "EU": "27 countries",
        # ... ~50 total regions
    }

    # Ultra-condensed catalog summaries
    sources_summary = [
        {"id": "census_agesex", "summary": "USA counties. 2019-2024. Age demographics."},
        {"id": "imf_bop", "summary": "195 countries. 2005-2022. Trade, finance."},
    ]

    system_prompt = f"""You are a geographic data assistant...
Available regions: {list(regions_available.keys())}
Total data sources: {len(sources_summary)}
Condensed source list: {sources_summary}
"""
    return system_prompt
```

### Tier 2: Preprocessing Layer (Outside LLM)

**Size**: 0 tokens to LLM
**Frequency**: Every query

Resolves locations and filters catalog BEFORE the LLM sees anything:

```python
class QueryPreprocessor:
    def preprocess_query(self, user_query):
        # 1. Extract location mentions from query
        locations_mentioned = self.extract_locations(user_query)

        # 2. Resolve to country codes using conversions.json
        resolved_countries = self.resolve_locations(locations_mentioned)

        # 3. Filter catalog to relevant sources
        relevant_sources = self.filter_catalog(user_query, resolved_countries)

        return {
            "original_query": user_query,
            "locations_found": locations_mentioned,
            "country_codes": resolved_countries,
            "relevant_sources": relevant_sources  # 2-10 instead of 200
        }
```

**Reference Files Used** (see [GEOMETRY.md](GEOMETRY.md) for details):

| File | Preprocessing Use |
|------|-------------------|
| `conversions.json` | Regional groupings, region_aliases ("Europe" -> country codes) |
| `reference/query_synonyms.json` | Metric synonyms ("gdp" = "economic output"), time synonyms ("latest" = "most recent") |
| `reference/admin_levels.json` | Admin level synonyms ("states" = "provinces" = "regions") |
| `reference/iso_codes.json` | Country name/code resolution |

### Tier 3: Just-In-Time Context Injection (Query-Specific)

**Size**: 500-1,500 tokens
**Frequency**: Every query

Only inject relevant details for this specific query:

```python
def build_user_prompt(user_query, preprocessed):
    prompt = f"""User query: "{user_query}"

Context resolved via preprocessing:
- Location: {preprocessed['locations_found']}
- Resolved to: {len(preprocessed['country_codes'])} countries
- Found {len(preprocessed['relevant_sources'])} relevant data sources

Available sources for this query:
{preprocessed['relevant_sources']}
"""
    return prompt
```

### Tier 4: Topic Reference Documents

For specialized datasets (SDGs, IMF codes, WHO classifications), reference documents provide domain knowledge:

```
county-map-data/data/
  un_sdg_01/
    all_countries.parquet
    metadata.json
    reference.json          # Goal 1 context, targets, description
```

**reference.json** example:
```json
{
  "source_context": "United Nations SDG Framework",
  "goal": {
    "number": 1,
    "name": "No Poverty",
    "full_title": "End poverty in all its forms everywhere",
    "description": "Goal 1 calls for an end to poverty...",
    "targets": [
      {"id": "1.1", "text": "Eradicate extreme poverty..."}
    ]
  }
}
```

#### Implementation Notes: Meta Questions via Reference Loading

**Currently working** (catalog-based, no reference files needed):
- "What data do you have?" - lists all sources from catalog
- "What data do you have for Europe?" - filters by coverage
- "What CO2/population data is available?" - topic search
- "Tell me about source X" - shows metrics from that source
- "How many metrics does SDG 7 have?" - counts from catalog

**Not yet working** (requires Tier 4 reference loading):
- "Tell me about SDG 7" / "What does SDG 7 mean?" - reference.json has goal description
- "What are the SDG 7 targets?" - reference.json has targets array
- "Where does your data come from?" - source URLs in metadata.json
- "When was this data last updated?" - last_updated in metadata.json

**Detection triggers** (preprocessing layer):
```python
# Detect topic reference questions
topic_patterns = [
    r"tell me about (sdg|goal)\s*(\d+)",
    r"what (does|is) (sdg|goal)\s*(\d+)",
    r"explain (sdg|goal)\s*(\d+)",
    r"what are the targets for",
]

# Detect source metadata questions
source_patterns = [
    r"where does .* come from",
    r"what is the source (of|for)",
    r"when was .* updated",
    r"who provides .* data",
]
```

**Loading strategy**:
1. Preprocessing detects topic/source question pattern
2. Load only the relevant reference.json (e.g., un_sdg_07/reference.json)
3. Inject ~200-500 tokens of context into Tier 3 prompt
4. LLM answers from actual reference data, not training data

**File locations**:
- `county-map-data/data/{source_id}/reference.json` - topic context, targets
- `county-map-data/data/{source_id}/metadata.json` - source URL, last updated

### Token Usage Comparison

**Naive Approach (Load Everything)**: ~25,100 tokens per query
- Full conversions.json: 10,000 tokens
- Full catalog.json: 15,000 tokens
- User query: 100 tokens

**Optimized Approach (Four-Tier)**: ~3,600 tokens per query
- System prompt (cached): 2,500 tokens
- Preprocessing: 0 tokens
- User prompt: 1,100 tokens

**Result**: 85-90% reduction in token usage

---

## Chat Endpoint Flow

```python
@app.post("/chat")
async def chat(message: str, current_order: list):
    # LLM 1: Order Taker
    response = order_taker_llm(message, current_order, data_catalog)
    return {
        "reply": response.text,
        "add_to_order": response.new_items,
        "remove_from_order": []
    }

@app.post("/display")
async def display(order: dict):
    # Empty box filler - deterministic Python, no LLM
    geojson = fill_boxes_and_build_geojson(order["items"])
    return geojson
```

---

## Display Table (Persistence Layer)

The Order Filler produces a **Display Table** - a denormalized view that the map reads from.

### The Flow

```
+------------------+     +------------------+     +------------------+
|   Order Panel    | --> |  Order Filler    | --> |  Display Table   |
|   (JS memory)    |     |  (Python/API)    |     |  (localStorage)  |
+------------------+     +------------------+     +------------------+
        |                        |                        |
  Ephemeral               Fills boxes              Persisted locally
  Gone on refresh         Adds geometry            Survives refresh
  User builds here        Returns table            Map reads from here
```

### What Gets Stored

**Order (memory only)** - disappears on page refresh
**Display Table (localStorage)** - survives refresh

```javascript
localStorage.setItem("displayTable", JSON.stringify({
  columns: ["loc_id", "name", "year", "gdp", "life_expectancy"],
  rows: [
    {loc_id: "DEU", name: "Germany", year: 2024, gdp: 4.2e12, life_expectancy: 81.2, geometry: {...}},
    {loc_id: "FRA", name: "France", year: 2024, gdp: 2.9e12, life_expectancy: 82.5, geometry: {...}},
  ],
  metadata: {
    created: "2025-12-22T10:30:00Z",
    sources: ["owid_co2", "who_health"]
  }
}));
```

### Benefits

| Benefit | How |
|---------|-----|
| **Refresh survival** | Display table persists in localStorage |
| **Fast re-render** | Map reads local data, no API call |
| **Easy export** | Table IS the export format (CSV/JSON) |
| **Offline viewing** | Once loaded, works without server |
| **Debug friendly** | Can inspect table in dev tools |

---

## Future Enhancement: Viewport Context

Pass the current map viewport to chat so the LLM understands "here":

```javascript
const viewportContext = {
  bbox: MapAdapter.map.getBounds().toArray(),
  zoom: MapAdapter.map.getZoom(),
  adminLevel: MapAdapter.currentAdminLevel,
  visibleCountries: getVisibleCountryISOs()
};

fetch('/chat', {
  body: JSON.stringify({
    message: userMessage,
    viewport: viewportContext
  })
});
```

**Without viewport context:**
- User: "Show me population here"
- LLM: "Where would you like to see population data?"

**With viewport context:**
- User zooms to France, then asks "Show me population here"
- LLM: "Here's population data for France..."

---

## Prompt Design Principles

1. **Assume ignorance**: User doesn't know what's available
2. **Be a guide**: Suggest, clarify, offer options
3. **Show coverage**: "For X region, I have Y and Z"
4. **Admit gaps**: "I don't have X, but I have related Y"
5. **Suggest connections**: "You might also want..."
6. **Keep it actionable**: Every response should have a clear next step
7. **Limit suggestions**: Max 3-5 items per response, go general if too many

---

## Future Enhancements

### Derived Fields / Calculated Metrics

Enable computed fields without hardcoded formulas:

- Rule-based derivation system (not hardcoded formulas)
- "Per capita" pattern -> divide by population
- "Percentage of total" -> sum filtered set, divide each by total
- "Growth rate" -> compare to previous year
- LLM prompt updates to recognize derived field requests
- Caching for expensive calculations

**Example queries:**
- "GDP per capita for African countries" -> gdp / population
- "CO2 emissions by percentage for G7" -> each / sum(all G7)
- "Population growth rate 2020-2023" -> (2023 - 2020) / 2020

**Scope rules:**
- Percentage denominator = filtered set total (user's current selection)
- User can specify "percentage of world total" for global denominator

### Query Caching

- Cache frequent queries (Redis or in-memory)
- Cache geometry (rarely changes)
- Invalidate on data updates

### Vector Search Layer

Semantic search over external content:

- Web scraper for supplier sites / documentation
- Vector database (ChromaDB local, Pinecone cloud)
- "Where can I buy solar panels in Texas?" -> relevant links

### Direct Data Queries

Enable the chat to answer data questions directly from parquet files:

**Simplified v1 approach:**
- LLM answers from training data first (often accurate enough)
- Offers "Would you like an exact answer from the database?" follow-up
- Falls back to "I don't know, would you like me to check?" if unsure
- User confirmation triggers actual data query

**Full implementation (v2):**
- Add a "query" response type that executes against parquet
- Example flow:
  1. User: "What's the largest GDP?"
  2. LLM returns: `{"type": "query", "source": "owid_co2", "metric": "gdp", "sort": "desc", "limit": 1}`
  3. Backend executes query, returns: `[{"loc_id": "USA", "name": "United States", "gdp": 26700000000000}]`
  4. LLM formats: "The United States has the highest GDP at $26.7 trillion (2023 data from OWID)."

### Catalog Token Optimization

Current approach loads full catalog (~2,500 tokens) for good conversation quality. As catalog grows beyond 50+ sources, may need:
- Topic-based filtering (only show relevant sources to LLM)
- Tiered catalog (summaries first, details on request)
- Embedding-based semantic search for source discovery
- See [PROMPT_OPTIMIZATION_PLAN.md](PROMPT_OPTIMIZATION_PLAN.md) for architecture

### Growth Rate Calculations

Open question on formula approach for derived growth metrics:
- Simple percentage: (end - start) / start * 100
- CAGR (Compound Annual Growth Rate): ((end/start)^(1/years) - 1) * 100
- Year-over-year series: separate growth value per year

### Chat Pagination & Clickable Actions

For sources with many metrics (28+), need better discovery UX:
- **Grouped display**: Show metrics by category first, then expand
- **Pagination**: "Showing 1-10 of 28. Say 'more' for next page"
- **Clickable actions** (v2): Response includes action buttons
  ```json
  {
    "reply": "OWID has 28 metrics. Here are 1-10: [...]",
    "actions": [
      {"label": "Show More", "trigger": "show more OWID metrics"},
      {"label": "Show All", "trigger": "show all OWID metrics"}
    ]
  }
  ```
- v1: Explicit "more" command works with current architecture

### Calculated Score for Overloaded Popups
If a request asks for too many data points (10+?) and the window cannot display properly, have a live calculated score.
Potentially implement by having a checkbox beside Display button to show "aggregate score".

The functionality would take all the data points, turn them all into %'s (relative to the min/max of other locations in the query)
and then display that % in the popup instead of overloading it with a ton of individual datapoints. 

---

## Related Files

| File | Purpose |
|------|---------|
| `mapmover/conversions.json` | Regional groupings (56), region aliases for preprocessing |
| `mapmover/reference/` | Modular reference data for query preprocessing |
| [GEOMETRY.md](GEOMETRY.md) | Reference file documentation, loc_id spec |
| [DATA_PIPELINE.md](DATA_PIPELINE.md) | Data source catalog |
| `county-map-data/catalog.json` | Master catalog for LLM context |

---

*Last Updated: 2025-12-31*
