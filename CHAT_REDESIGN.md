# Chat Redesign - Fast Food Kiosk Model

Simplify the dual-LLM architecture by separating concerns with a visible "order" in between.

**Status**: Phase 1B Complete - Backend + Order Panel UI implemented

---

## Current Problems

1. LLM tries to understand when user is "done" with their request
2. LLM has to handle corrections, removals, modifications inline
3. User can't see exactly what will be displayed until it happens
4. Two LLMs are tightly coupled - hard to debug which one failed
5. Complex prompt engineering to handle all edge cases

---

## New Model: Fast Food Kiosk

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

---

## UI Layout

```
+-----------------------------------------------------------------------+
|                                                                       |
|   [Chat Panel]                    [Order Panel]         [Map]         |
|   +-----------------------+       +---------------+                   |
|   | User: Show me GDP     |       | YOUR ORDER:   |                   |
|   |       for Europe      |       |               |                   |
|   |                       |       | - GDP         |                   |
|   | Bot: I found GDP in   |       |   Europe      |                   |
|   |      OWID dataset.    |       |   2023    [x] |                   |
|   |      Years 1990-2024. |       |               |                   |
|   |      Added to order.  |       | - Population  |                   |
|   |                       |       |   Europe      |                   |
|   | User: Add population  |       |   2023    [x] |                   |
|   |       too             |       |               |                   |
|   |                       |       +---------------+                   |
|   | Bot: Added population |       | [Display]     |                   |
|   |      to order.        |       +---------------+                   |
|   +-----------------------+                                           |
|                                                                       |
+-----------------------------------------------------------------------+
```

---

## LLM 1: Order Taker (Data Guide)

**Role**: Help users discover and select data. Guide them to what's available.

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

### Catalog Search Behavior

The LLM should search the catalog by:
- **Keywords**: "water" matches datasets tagged with water, rainfall, flooding
- **Synonyms**: "income" matches GDP, earnings, wages
- **Topics**: "health" shows all health-related indicators
- **Regions**: "Africa" shows what coverage we have for Africa

### Example Conversations

**Vague request - guide to options**:
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

**No exact match - suggest alternatives**:
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

**Partial match - clarify scope**:
```
User: "Health data for California"

Bot: "I have health data at two levels:

     Country-level (WHO):
     - Life expectancy, mortality, immunization
     - Covers USA as a whole, 2015-2024

     County-level (Census):
     - Demographics and age distribution
     - All 58 California counties, 2020-2024

     Did you want country-level health stats, or county-level demographics?"

Order: unchanged (clarifying)
```

**Good match - add and suggest more**:
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

**User exploring - keep it high-level**:
```
User: "What do you have for Africa?"

Bot: "For Africa (54 countries), I have:

     - Economic data (GDP, trade, population)
     - Health statistics (life expectancy, mortality)
     - Environmental metrics (CO2, energy)

     Note: Country-level only, no sub-national data yet.

     Which area interests you?"

Order: unchanged (guiding to narrow down)
```

### Response Limits

**Rule: 3-5 suggestions max per response**

If too many matches, go more general and ask for narrowing:

**Too broad - be general**:
```
User: "What do you have?"

Bot: "I have data across several categories:

     - Economic (GDP, trade, population)
     - Health (life expectancy, mortality)
     - Environmental (CO2 emissions, energy)
     - Demographics (US county-level)

     What topic interests you? Or name a region to see what's available there."

(NOT a list of 50 indicators)
```

**Medium broad - show categories for region**:
```
User: "What do you have for Africa?"

Bot: "For Africa, I have data in these areas:

     - Economic indicators (OWID)
     - Health statistics (WHO)
     - Trade data (IMF)

     Which category? Or ask about a specific metric like 'GDP' or 'life expectancy'."

(NOT a full list of every indicator per source)
```

**Narrow enough - show specifics**:
```
User: "Health data for Africa"

Bot: "For African health data (WHO, 2015-2024), I have:

     - Life expectancy at birth
     - Infant mortality rate
     - Immunization coverage
     - Maternal mortality ratio
     - Disease prevalence

     Which indicator would you like to see?"

(Specific list because scope is narrow enough)
```

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

### Prompt Design Principles

1. **Assume ignorance**: User doesn't know what's available
2. **Be a guide**: Suggest, clarify, offer options
3. **Show coverage**: "For X region, I have Y and Z"
4. **Admit gaps**: "I don't have X, but I have related Y"
5. **Suggest connections**: "You might also want..."
6. **Keep it actionable**: Every response should have a clear next step
7. **Limit suggestions**: Max 3-5 items per response, go general if too many

---

## Order Limits (Map Display vs Export)

The chat "order" system has practical limits because data must fit in map popups:

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

**Note:** These are completely separate interfaces with different prompts. The frontend map chat and admin dashboard chat have no interaction between them.

### Order Size Guidance

**Chat orders** - keep small for visual clarity:
```
Reasonable:
- 3 metrics for 30 countries = good popup
- 1 metric for 200 countries = good choropleth
- 5 metrics for 50 US states = manageable

Too much for map:
- 20 metrics for 200 countries = popup overload
- 10 years of monthly data = use time slider instead
```

**Admin exports** - no practical limit:
```
Fine for export:
- All 185 indicators for all countries 1990-2024
- Every US county with every census metric
- Custom joins across multiple datasets
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

### No LLM Needed Here

This is deterministic Python code, not an LLM task:

```python
def fill_boxes(order_items):
    # Step 1: Determine all target loc_ids from order
    target_loc_ids = set()
    for item in order_items:
        target_loc_ids.update(expand_region(item["region"]))

    # Step 2: Create empty boxes
    boxes = {loc_id: {} for loc_id in target_loc_ids}

    # Step 3: Process each order item
    for item in order_items:
        df = load_parquet(f"county-map-data/data/{item['source']}/")
        df = df[df["year"] == item["year"]]
        df = df[df["loc_id"].isin(target_loc_ids)]

        # Fill boxes
        for _, row in df.iterrows():
            if row["loc_id"] in boxes:
                boxes[row["loc_id"]][item["metric"]] = row[item["metric"]]

    # Step 4: Convert to GeoJSON
    return boxes_to_geojson(boxes)
```

**LLM only needed if**:
- Derived calculations ("GDP per capita" = gdp / population)
- Ambiguous display preferences
- Complex aggregations

---

## Display Table (Persistence Layer)

The Order Filler produces a **Display Table** - a denormalized view of all requested data that the map reads from.

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

**Order (memory only)** - disappears on page refresh:
```javascript
window.currentOrder = [
  {metric: "gdp", region: "Europe", year: 2024, source: "owid_co2"},
  {metric: "life_expectancy", region: "Europe", year: 2024, source: "who_health"}
];
```

**Display Table (localStorage)** - survives refresh:
```javascript
localStorage.setItem("displayTable", JSON.stringify({
  columns: ["loc_id", "name", "year", "gdp", "life_expectancy"],
  rows: [
    {loc_id: "DEU", name: "Germany", year: 2024, gdp: 4.2e12, life_expectancy: 81.2, geometry: {...}},
    {loc_id: "FRA", name: "France", year: 2024, gdp: 2.9e12, life_expectancy: 82.5, geometry: {...}},
  ],
  metadata: {
    created: "2025-12-22T10:30:00Z",
    sources: ["owid_co2", "who_health"],
    order: [...] // Original order for reference
  }
}));
```

### Why This Model

| Benefit | How |
|---------|-----|
| **Refresh survival** | Display table persists in localStorage |
| **Fast re-render** | Map reads local data, no API call |
| **Easy export** | Table IS the export format (CSV/JSON) |
| **Offline viewing** | Once loaded, works without server |
| **Debug friendly** | Can inspect table in dev tools |

### Display Table Schema

The table is essentially a GeoDataFrame in JSON:

```
+--------+----------+------+---------+------------------+-----------+
| loc_id | name     | year | gdp     | life_expectancy  | geometry  |
+--------+----------+------+---------+------------------+-----------+
| DEU    | Germany  | 2024 | 4.2T    | 81.2             | [polygon] |
| FRA    | France   | 2024 | 2.9T    | 82.5             | [polygon] |
| GBR    | UK       | 2024 | 3.1T    | 81.0             | [polygon] |
+--------+----------+------+---------+------------------+-----------+
```

- **Rows** = one per location (loc_id is key)
- **Columns** = all metrics from all data sources + geometry
- **Schema** = dynamic, based on order items

### Export is Trivial

```javascript
function exportToCSV() {
  const table = JSON.parse(localStorage.getItem("displayTable"));
  const header = table.columns.filter(c => c !== "geometry").join(",");
  const rows = table.rows.map(row =>
    table.columns.filter(c => c !== "geometry").map(col => row[col] ?? "").join(",")
  );
  return [header, ...rows].join("\n");
}
```

### Page Load Behavior

```javascript
// On page load
const savedTable = localStorage.getItem("displayTable");
if (savedTable) {
  // Restore previous view
  const table = JSON.parse(savedTable);
  renderMapFromTable(table);
  showNotification("Restored previous view");
} else {
  // Show default (countries only, no data)
  loadDefaultView();
}
```

---

## Benefits

| Before | After |
|--------|-------|
| LLM guesses when user is done | User clicks [Display] when ready |
| LLM handles corrections inline | User clicks [x] to remove |
| User can't see pending request | Order panel shows everything |
| Complex state in LLM context | State lives in UI (order JSON) |
| Hard to debug which LLM failed | Clear separation of concerns |
| LLMs tightly coupled | Order JSON is the contract |

---

## Conversation Examples

**Simple request**:
```
User: GDP for Europe 2020
Bot: Added to order: GDP, Europe, 2020
[Order shows: GDP | Europe | 2020]
User: [clicks Display]
[Map shows GDP choropleth for Europe]
```

**Building up an order**:
```
User: I want to compare Europe and Asia
Bot: Compare what metric? I have GDP, population, CO2, life expectancy...

User: GDP and population
Bot: Added to order:
     - GDP, Europe, 2024
     - GDP, Asia, 2024
     - Population, Europe, 2024
     - Population, Asia, 2024

[Order shows 4 items]
User: Actually remove Asia
[User clicks x on the 2 Asia items]
[Order shows 2 items: GDP Europe, Population Europe]
User: [clicks Display]
```

**Correction flow**:
```
User: Show me Texas counties
Bot: Added: Population, Texas counties, 2024

User: Wait I meant California
[User clicks x on Texas item]
User: California counties
Bot: Added: Population, California counties, 2024
```

---

## Implementation Notes

### State Management

Order lives in frontend (JavaScript), not in LLM context:

```javascript
let currentOrder = {
  items: []
};

function addToOrder(item) {
  item.id = generateId();
  item.added_at = new Date().toISOString();
  currentOrder.items.push(item);
  renderOrderPanel();
}

function removeFromOrder(itemId) {
  currentOrder.items = currentOrder.items.filter(i => i.id !== itemId);
  renderOrderPanel();
}

function submitOrder() {
  fetch('/display', {
    method: 'POST',
    body: JSON.stringify(currentOrder)
  }).then(response => {
    // Update map with GeoJSON
  });
}
```

### Chat Endpoint Changes

**Before**: `/chat` returns GeoJSON directly

**After**:
- `/chat` returns order items to add (or clarification)
- `/display` takes order JSON, returns GeoJSON

```python
@app.post("/chat")
async def chat(message: str, current_order: list):
    # LLM 1: Order Taker
    response = order_taker_llm(message, current_order, data_catalog)
    return {
        "reply": response.text,
        "add_to_order": response.new_items,  # List of items to add
        "remove_from_order": []  # Optional: items to remove
    }

@app.post("/display")
async def display(order: dict):
    # Empty box filler - deterministic Python, no LLM
    geojson = fill_boxes_and_build_geojson(order["items"])
    return geojson
```

---

## Migration Path

1. Add order panel UI (HTML/CSS)
2. Add order state management (JavaScript)
3. Split `/chat` endpoint to return order items
4. Create `/display` endpoint with empty box filler
5. Update LLM prompt to focus on order-taking (data guide role)
6. Test with simple single-source queries
7. Test cross-dataset joins (the key feature)
8. Migrate complex queries

---

*Last Updated: 2025-12-22*
