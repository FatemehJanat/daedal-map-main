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

## Decision Points for User

1. **Scope**: Full refactor vs. targeted fix for source-vs-location conflict?
2. **LLM cost**: Accept slightly higher token usage for better accuracy?
3. **Timeline**: Phased migration or big-bang rewrite?

---

*Last Updated: 2026-01-07*
