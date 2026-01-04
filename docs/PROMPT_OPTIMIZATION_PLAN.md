# Plan: Prompt Optimization + Derived Fields

**STATUS: COMPLETED** (2026-01-03)

All features implemented:
- Preprocessor (preprocessor.py) - topic extraction, region resolution, time patterns, reference lookups, navigation, disambiguation
- Postprocessor (postprocessor.py) - validation, derived field expansion
- Derived field calculation in order_executor.py
- Tiered context system in order_taker.py
- Navigation mode and selection mode in frontend

## Overview

Two connected features that share a preprocessing layer:
1. **Prompt Optimization** - Tiered context system with pre/postprocessors
2. **Derived Fields** - Flexible metric calculations (per capita, ratios, etc.)

---

## Architecture: Pre/Post Processor Flow

```
User Query
    |
    v
[Preprocessor] -----> extract topics, resolve regions, detect time patterns
    |
    v
[Order Taker LLM] --> interprets intent, outputs order with derived flags
    |
    v
[Postprocessor] ----> validates items, expands derived fields, adds source items
    |
    v
[Order Window] -----> user sees validated order (derived items hidden appropriately)
    |
    v
[Order Executor] ---> fetches data, calculates derived values, builds GeoJSON
```

---

## Part 1: Prompt Optimization (Tiered Context)

### Tier 1: System Prompt (~2,500 tokens, cached)
- Role description and output format
- **Robust catalog** - source names, categories, topic tags, key metrics
- Region list (names only, not full country codes)
- Enough for LLM to guide conversation well

### Tier 2: Preprocessor (0 LLM tokens)
- Extract topics from query using keyword matching
- Resolve regions ("Europe" -> country codes)
- Detect time patterns ("trend", "over time")
- Pass hints to LLM context

### Tier 3: Just-in-Time Context (~500-1000 tokens)
- Preprocessed hints (resolved regions, detected patterns)
- Any additional context needed for specific query

### Tier 4: Reference Documents (on-demand)
- Load reference.json when user asks "what is SDG 7?"
- Inject goal descriptions, targets
- ~200-500 tokens when triggered

**Reference Lookup Pattern:**

| Trigger Keywords | Reference File | Example Query |
|-----------------|----------------|---------------|
| "SDG 7", "goal 7" | `county-map-data/data/un_sdg_07/reference.json` | "What is SDG 7?" |
| "capital of X" | `mapmover/reference/country_metadata.json` | "What's the capital of China?" |
| "currency", "money in" | `mapmover/reference/country_metadata.json` | "What currency does Japan use?" |
| "language", "speak in" | `mapmover/reference/languages.json` | "What languages are spoken in Switzerland?" |

**Preprocessor detection:**
```python
def detect_reference_lookup(query):
    # SDG pattern
    sdg_match = re.search(r'SDG\s*(\d+)|goal\s*(\d+)', query, re.I)
    if sdg_match:
        num = sdg_match.group(1) or sdg_match.group(2)
        return {"type": "sdg", "file": f"un_sdg_{num.zfill(2)}/reference.json"}

    # Country metadata patterns
    if any(kw in query.lower() for kw in ["capital of", "currency", "timezone"]):
        return {"type": "country_meta", "file": "reference/country_metadata.json"}

    # Language patterns
    if any(kw in query.lower() for kw in ["language", "speak", "spoken"]):
        return {"type": "languages", "file": "reference/languages.json"}

    return None
```

**Flow:** Preprocessor detects reference topic -> loads file -> injects as context -> LLM answers as `chat` type.

### Token Budget

| Component | Tokens | Notes |
|-----------|--------|-------|
| Tier 1 System Prompt | ~2,500 | Cached, includes robust catalog |
| Tier 3 JIT Context | ~500-1000 | Per-query |
| User query + history | ~500 | Last 4 messages |
| **Total per query** | **~3,500-4,000** | Down from ~25,000 |

**Result**: ~80-85% reduction while maintaining conversation quality.

---

## Part 2: Derived Fields (Flexible System)

### Design Philosophy
- **Any two metrics can be combined** - not just per capita
- **LLM detects intent simply** - outputs `derived: "per_capita"` flag
- **Postprocessor expands** - knows formulas, adds source items
- **Executor calculates** - performs actual math after data fetch

### LLM Output Format

LLM outputs simple intent:
```json
{
  "items": [{
    "source_id": "owid_co2",
    "metric": "gdp",
    "region": "EU",
    "year": 2023,
    "derived": "per_capita"
  }]
}
```

For arbitrary ratios (cross-source supported):
```json
{
  "items": [{
    "type": "derived",
    "numerator": {"source_id": "owid_co2", "metric": "gdp"},
    "denominator": {"source_id": "owid_co2", "metric": "co2"},
    "region": "EU",
    "year": 2023
  }]
}
```

Cross-source example (GDP from OWID / Exports from IMF):
```json
{
  "items": [{
    "type": "derived",
    "numerator": {"source_id": "owid_co2", "metric": "gdp"},
    "denominator": {"source_id": "imf_bop", "metric": "exports"},
    "region": "EU",
    "year": 2023
  }]
}
```

### Postprocessor Expansion

Postprocessor sees `derived: "per_capita"` and expands to:
```json
{
  "items": [
    {"source_id": "owid_co2", "metric": "gdp", "region": "EU", "for_derivation": true},
    {"source_id": "owid_co2", "metric": "population", "region": "EU", "for_derivation": true},
    {"type": "derived_result", "numerator": "gdp", "denominator": "population", "label": "GDP Per Capita"}
  ]
}
```

Cross-source derivation expansion:
```json
// LLM outputs:
{"type": "derived", "numerator": {"source_id": "owid_co2", "metric": "gdp"},
 "denominator": {"source_id": "imf_bop", "metric": "exports"}, "region": "EU"}

// Postprocessor expands to 3 order items:
[
  {"source_id": "owid_co2", "metric": "gdp", "region": "EU", "for_derivation": true},
  {"source_id": "imf_bop", "metric": "exports", "region": "EU", "for_derivation": true},
  {"type": "derived_result", "numerator": "gdp", "denominator": "exports", "label": "GDP/Exports"}
]
```

**Expansion lookup table:**
```python
DERIVED_EXPANSIONS = {
    "per_capita": {"denominator": "population", "label_suffix": "Per Capita"},
    "density": {"denominator": "area_sq_km", "label_suffix": "Density"},
    "per_1000": {"denominator": "population", "multiplier": 1000, "label_suffix": "Per 1000"},
}
```

### Order Panel Display

- Items with `for_derivation: true` are hidden from order panel
- Derived item shows as: "GDP Per Capita (Derived)" or "GDP/CO2 (Derived)"
- User sees clean order, not the internal mechanics

### Executor Calculation

After fetching all data into boxes:
```python
def apply_derived_fields(boxes, derived_specs, year):
    warnings = []
    for loc_id, metrics in boxes.items():
        for spec in derived_specs:
            num = metrics.get(spec["numerator"])
            denom = get_denominator_value(metrics, spec["denominator"], loc_id, year)

            if num is None:
                continue  # Skip silently
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

### Canonical Sources for Common Denominators

```python
def get_denominator_value(metrics, denom_name, loc_id, year):
    # Check if already in metrics (user requested it too)
    if denom_name in metrics:
        return metrics[denom_name]

    # Canonical sources for common denominators
    if denom_name == "population":
        if len(loc_id) == 3:  # Country code
            return lookup_owid_population(loc_id, year)
        elif loc_id.startswith("USA-"):  # US county
            return lookup_census_population(loc_id, year)

    if denom_name == "area_sq_km":
        return lookup_static_area(loc_id)

    return None
```

### Response Format

```json
{
  "properties": {
    "GDP": 4200000000000,
    "Population": 83000000,
    "GDP Per Capita (calculated)": 50602
  }
}
```

Popup displays: "GDP Per Capita (calculated): $50,602"

If denominator unavailable: warning in response, derived field omitted for that location.

---

## Part 3: Validation Flow

### Inline Validation (Postprocessor)

After LLM outputs order, postprocessor:
1. Validates each item exists in catalog
2. Expands derived fields
3. Returns validation results inline to chat

**Chat response includes:**
- "GDP for Europe: Found in owid_co2"
- "Unemployment for Europe: Not found. Did you mean labor_force?"

### No Explicit "Verify" Button Needed

- Validation happens automatically after each LLM response
- User sees results immediately in chat
- Invalid items get suggestions
- "Display on Map" executes validated order

---

## Files to Create/Modify

| File | Changes |
|------|---------|
| `mapmover/preprocessor.py` | NEW - topic extraction, region resolution, pattern detection |
| `mapmover/postprocessor.py` | NEW - validation, derived field expansion |
| `mapmover/order_taker.py` | Use preprocessor output, simplified prompts |
| `mapmover/order_executor.py` | Apply derived field calculations |
| `mapmover/data_loading.py` | Add canonical source lookups (population, area) |
| `app.py` | Wire pre/postprocessors into /chat endpoint |

---

## Implementation Order

### Phase 1: Preprocessor
- Create preprocessor.py
- Topic extraction from query keywords
- Region resolution (leverage existing conversions.json)
- Time pattern detection ("trend", "from X to Y")
- Reference lookup detection (SDG, capitals, languages, etc.)
- Wire into app.py before LLM call

### Phase 2: Postprocessor
- Create postprocessor.py
- Validation against catalog
- Derived field expansion (per_capita, density, arbitrary ratios)
- Wire into app.py after LLM call

### Phase 3: Derived Field Calculation
- Add calculation logic to order_executor.py
- Canonical source lookups (population from owid_co2, area from static)
- Response format with "(calculated)" suffix
- Warning collection for missing denominators

### Phase 4: Prompt Optimization
- Refactor build_system_prompt() to use Tier 1 condensed format
- Inject preprocessor hints as Tier 3 context
- Test token usage before/after

### Phase 5: Integration & Testing
- End-to-end test: "GDP per capita for Europe"
- Test: "GDP to CO2 ratio for G7"
- Test: validation of non-existent metrics
- Verify token reduction

---

## Decisions Made

| Question | Decision |
|----------|----------|
| Derived field naming | "GDP Per Capita (calculated): $45K" - include indicator |
| Missing data | Show warning, omit derived field for that location |
| Preprocessor approach | Start gentle, mostly pass to LLM, build specificity over time |
| Scope | Flexible system - any metric / any metric, not just per capita |
| LLM output format | Simple flag (`derived: "per_capita"`), postprocessor expands |
| Cross-source derivations | Use nested objects: `{"source_id": "x", "metric": "y"}` for numerator/denominator |
| Auto-add dependencies | Add with `for_derivation: true` flag, hidden from order panel |
| Reference lookups | Tier 4 on-demand context injection for SDG, capitals, languages, etc. |
| Catalog in prompt | Keep robust (~2,500 tokens) for good conversation UX |
| Validation approach | Inline after each LLM response, no explicit Verify button |
| Growth rate calculation | Defer to future enhancement |

---

## Related Fixes

### Popup Missing Data Display
Currently popups hide fields with no data. Should show:
```
Life Expectancy: N/A
```
Instead of omitting the field entirely.

### Direct Data Queries (Simplified v1)
- LLM answers from training data first
- Offers "Would you like an exact answer?" follow-up
- Falls back to "I don't know, would you like me to check?" if unsure
- Triggers data query against parquet when user confirms

---

*Created: 2026-01-03*
*Updated: 2026-01-03* - Added cross-source derivations, reference lookup pattern
