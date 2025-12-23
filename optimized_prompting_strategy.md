# Optimized Prompting Flow for Geographic Data Chat System

## Overview

This document outlines the strategy for efficiently managing context in LLM prompts when working with large reference files (conversions.json, catalog.json) that grow over time. The goal is to provide maximum understanding while minimizing token usage and latency.

## The Problem

As the system grows, you'll have:
- **conversions.json**: ~40-50 KB (9,000-11,000 tokens) containing country codes and regional groupings
- **catalog.json**: Growing from 6 to potentially 200+ data sources (5,000-20,000+ tokens)

Loading these entirely into every prompt would:
- Consume 15,000-30,000 tokens per query
- Increase latency and cost
- Waste context window on irrelevant information
- Most information unused for any given query

## The Solution: Three-Tier Context System

### Tier 1: Lightweight System Prompt (Always Loaded)
**Size: ~2,000-3,000 tokens**
**Frequency: Once per session, cached**

Contains condensed, high-level information:

```python
def build_system_prompt():
    """Create lightweight system prompt with essential context"""
    
    # Condensed region list (just names, not full mappings)
    regions_available = {
        "Africa": "54 countries",
        "Sub-Saharan Africa": "48 countries",
        "East Africa": "18 countries",
        "Asia": "51 countries",
        "Europe": "53 countries",
        "Americas": "35 countries",
        "EU": "27 countries",
        "ASEAN": "10 countries",
        "OECD": "38 countries",
        # ... ~50 total regions
    }
    
    # Ultra-condensed catalog summaries
    sources_summary = [
        {
            "id": "census_agesex",
            "summary": "USA counties. 2019-2024. Age demographics.",
            "category": "demographic"
        },
        {
            "id": "imf_bop",
            "summary": "195 countries. 2005-2022. Trade, finance.",
            "category": "economic"
        },
        # ... all sources in one-line format
    ]
    
    system_prompt = f"""You are a geographic data assistant with access to global datasets.

Available regions: {list(regions_available.keys())}
Total data sources: {len(sources_summary)} across categories: demographic, economic, environmental, health

When a user asks about data:
1. Identify location (country, region, or grouping)
2. Identify topic (GDP, poverty, emissions, health, etc.)
3. Identify time period
4. Request specific dataset details via context injection

Condensed source list:
{json.dumps(sources_summary, indent=2)}

Note: Full location mappings and detailed dataset info are resolved via preprocessing.
"""
    
    return system_prompt
```

**Result:** System prompt uses ~2,000 tokens and gives LLM awareness of what exists without overwhelming detail.

### Tier 2: Preprocessing Layer (Outside LLM)
**Size: 0 tokens to LLM**
**Frequency: Every query**

Resolves locations and filters catalog BEFORE the LLM sees anything:

```python
class QueryPreprocessor:
    """Handles location resolution and catalog filtering outside LLM"""
    
    def __init__(self):
        # Load full files (NOT sent to LLM)
        with open('conversions.json') as f:
            self.locations = json.load(f)
        with open('catalog.json') as f:
            self.catalog = json.load(f)
    
    def preprocess_query(self, user_query):
        """Extract and resolve everything before LLM sees it"""
        
        # 1. Extract location mentions from query
        locations_mentioned = self.extract_locations(user_query)
        # e.g., "Africa" found in query
        
        # 2. Resolve to country codes using conversions.json
        resolved_countries = []
        for loc in locations_mentioned:
            if loc in self.locations['region_aliases']:
                region_key = self.locations['region_aliases'][loc]
                codes = self.locations['regional_groupings'][region_key]['countries']
                resolved_countries.extend(codes)
        # Result: ["DZA", "AGO", "BEN", ... 54 countries]
        
        # 3. Filter catalog to relevant sources
        relevant_sources = self.filter_catalog_by_coverage_and_topic(
            query=user_query,
            countries=resolved_countries
        )
        # Result: 2-5 relevant sources instead of all 200
        
        return {
            "original_query": user_query,
            "locations_found": locations_mentioned,
            "country_codes": resolved_countries,
            "relevant_sources": relevant_sources
        }
```

**Key Functions:**

```python
def extract_locations(self, query):
    """Find location references in query text"""
    locations = []
    query_lower = query.lower()
    
    # Check for region names
    for alias in self.locations['region_aliases'].keys():
        if alias.lower() in query_lower:
            locations.append(alias)
    
    # Check for country names
    for code, name in self.locations['iso_country_codes'].items():
        if name.lower() in query_lower:
            locations.append(name)
    
    return locations

def resolve_location(self, location_name):
    """Convert any location reference to country codes"""
    
    # Check if it's a region
    if location_name in self.locations['region_aliases']:
        region_key = self.locations['region_aliases'][location_name]
        return self.locations['regional_groupings'][region_key]['countries']
    
    # Check if it's a country
    for code, name in self.locations['iso_country_codes'].items():
        if name.lower() == location_name.lower():
            return [code]
    
    return []

def filter_catalog(self, query, countries):
    """Find only relevant data sources"""
    relevant = []
    query_lower = query.lower()
    
    for source in self.catalog['sources']:
        # Check geographic coverage
        coverage = source['geographic_coverage']
        
        # Filter by geography
        if countries:
            if coverage['type'] == 'global':
                relevant.append(source)
            elif any(c in coverage.get('country_codes_all', []) for c in countries):
                relevant.append(source)
        
        # Also check topic relevance
        if any(kw in query_lower for kw in source['keywords']):
            if source not in relevant:
                relevant.append(source)
    
    return relevant
```

**Result:** Preprocessing resolves locations and filters catalog to 2-10 relevant sources, using 0 LLM tokens.

### Tier 3: Just-In-Time Context Injection (Query-Specific)
**Size: 500-1,500 tokens**
**Frequency: Every query**

Only inject relevant details for this specific query:

```python
def build_user_prompt(user_query, preprocessed):
    """Create prompt with only relevant context"""
    
    # Build minimal, focused context
    context = {
        "query": user_query,
        "resolved_locations": {
            "mentioned": preprocessed['locations_found'],
            "resolved_to": f"{len(preprocessed['country_codes'])} countries",
            "sample_countries": preprocessed['country_codes'][:10]  # First 10 only
        },
        "relevant_sources": [
            {
                "id": s['source_id'],
                "name": s['source_name'],
                "summary": s['llm_summary'],  # Use existing condensed field
                "coverage": f"{s['geographic_coverage']['countries']} countries",
                "years": f"{s['temporal_coverage']['start']}-{s['temporal_coverage']['end']}",
                "category": s['category']
            }
            for s in preprocessed['relevant_sources']
        ]
    }
    
    prompt = f"""User query: "{user_query}"

Context resolved via preprocessing:
- Location mentioned: {preprocessed['locations_found']}
- Resolved to: {len(preprocessed['country_codes'])} countries ({', '.join(preprocessed['country_codes'][:5])}...)
- Found {len(preprocessed['relevant_sources'])} relevant data sources

Available sources for this query:
{json.dumps(context['relevant_sources'], indent=2)}

Your task:
1. Identify which source(s) best answer the query
2. Extract structured intent:
   - primary_source_id: which dataset to use
   - countries: specific country codes to query
   - years: time range to retrieve
   - visualization_type: how to display (time_series, choropleth, comparison)

Respond in JSON format.
"""
    
    return prompt
```

**Result:** User prompt uses only ~1,000 tokens with highly relevant, focused context.

## Complete Pipeline

```python
class OptimizedGeographicRAG:
    """Full pipeline with three-tier context management"""
    
    def __init__(self):
        # Initialize preprocessing (loads full files)
        self.preprocessor = QueryPreprocessor()
        
        # Initialize LLM
        self.llm = anthropic.Anthropic()
        
        # Build system prompt ONCE
        self.system_prompt = build_system_prompt()
    
    def process_query(self, user_query):
        """Process query with optimized context"""
        
        # TIER 2: Preprocess (0 tokens to LLM)
        preprocessed = self.preprocessor.preprocess_query(user_query)
        
        # Early exit if no relevant data
        if not preprocessed['relevant_sources']:
            return {
                "error": "No data available",
                "message": f"No datasets found for {preprocessed['locations_found']} on this topic"
            }
        
        # TIER 3: Build focused user prompt (500-1500 tokens)
        user_prompt = build_user_prompt(user_query, preprocessed)
        
        # Call LLM with TIER 1 (system) + TIER 3 (user)
        response = self.llm.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            system=self.system_prompt,  # ~2K tokens, cached
            messages=[{
                "role": "user",
                "content": user_prompt  # ~1K tokens, focused
            }]
        )
        
        # Parse and execute
        intent = json.loads(response.content[0].text)
        return self.execute_query(intent, preprocessed)
```

## Token Usage Comparison

### Example Query: "How has poverty changed in Sub-Saharan Africa since 2000?"

**❌ Naive Approach (Load Everything)**
```
System prompt: 0 tokens

User prompt:
  - Full conversions.json: 10,000 tokens
  - Full catalog.json (200 sources): 15,000 tokens
  - User query: 100 tokens

TOTAL: 25,100 tokens per query
```

**✅ Optimized Approach (Three-Tier)**
```
System prompt (cached, one-time):
  - Region list summary: 500 tokens
  - Source summaries: 1,500 tokens
  - Instructions: 500 tokens
  Subtotal: 2,500 tokens

Preprocessing (0 tokens to LLM):
  - Resolve "Sub-Saharan Africa" → 48 country codes
  - Filter catalog → 2 relevant sources (economic category)

User prompt (per query):
  - Query + resolved context: 300 tokens
  - 2 relevant source details: 600 tokens
  - Instructions: 200 tokens
  Subtotal: 1,100 tokens

TOTAL: 3,600 tokens per query
86% reduction in token usage
```

## Scaling Strategy

### As Catalog Grows to 200+ Sources

**Option 1: Category-Based Pre-Filtering**
```python
# In preprocessing, narrow by category first
category_keywords = {
    'economic': ['poverty', 'gdp', 'trade', 'finance', 'income'],
    'health': ['disease', 'mortality', 'healthcare', 'medical'],
    'environmental': ['emissions', 'climate', 'pollution', 'energy'],
    'demographic': ['population', 'age', 'census', 'migration']
}

def identify_category(query):
    query_lower = query.lower()
    for category, keywords in category_keywords.items():
        if any(kw in query_lower for kw in keywords):
            return category
    return None

# Filter catalog to just that category before showing to LLM
category = identify_category(user_query)
relevant_sources = [s for s in catalog if s['category'] == category]
```

**Option 2: Semantic Search on Catalog**
```python
# One-time: Generate embeddings for each source
source_embeddings = []
for source in catalog['sources']:
    text = f"{source['source_name']} {' '.join(source['keywords'])} {' '.join(source['topic_tags'])}"
    embedding = embedding_model.encode(text)
    source_embeddings.append(embedding)

# At query time: Find top 5 most relevant
def find_relevant_sources(query, top_k=5):
    query_embedding = embedding_model.encode(query)
    similarities = np.dot(source_embeddings, query_embedding)
    top_indices = np.argsort(similarities)[-top_k:][::-1]
    return [catalog['sources'][i] for i in top_indices]

# Only show top 5 to LLM
```

**Option 3: Hierarchical Catalog in System Prompt**
```python
# System prompt: Only category summaries
system_catalog = {
    "economic": "45 datasets: GDP, trade, poverty, employment, finance",
    "environmental": "23 datasets: emissions, climate, resources, pollution",
    "health": "31 datasets: mortality, disease, healthcare, nutrition",
    "demographic": "18 datasets: population, migration, age, census"
}

# LLM identifies category
# Then inject only that category's sources in follow-up
```

## Token Budget Projections

**Current (6 sources):**
- System: 2,000 tokens
- User: 1,000 tokens
- **Total: 3,000 tokens/query**

**With 50 sources:**
- System: 3,500 tokens (50 one-line summaries)
- User: 1,200 tokens (3-5 relevant sources)
- **Total: 4,700 tokens/query**

**With 200 sources:**
- System: 8,000 tokens (200 one-line summaries)
- User: 1,500 tokens (5-10 relevant sources after filtering)
- **Total: 9,500 tokens/query**

Even at 200 sources, you're using <10K tokens vs 30K+ with naive approach.

## Implementation Checklist

### Phase 1: Basic Preprocessing
- [ ] Create QueryPreprocessor class
- [ ] Implement location extraction from query text
- [ ] Implement location resolution (name → country codes)
- [ ] Implement basic catalog filtering by geography
- [ ] Test with sample queries

### Phase 2: System Prompt Optimization
- [ ] Build condensed system prompt generator
- [ ] Use `llm_summary` field from catalog (already exists!)
- [ ] Create region list summary
- [ ] Test system prompt size (~2K tokens)

### Phase 3: Dynamic User Prompt
- [ ] Build user prompt generator
- [ ] Format preprocessed results for LLM
- [ ] Test with various query types
- [ ] Measure token usage

### Phase 4: Integration
- [ ] Combine all three tiers in main pipeline
- [ ] Add error handling for edge cases
- [ ] Implement caching for system prompt
- [ ] Add logging for token usage monitoring

### Phase 5: Scaling Enhancements
- [ ] Implement category-based filtering
- [ ] Add semantic search on catalog (optional)
- [ ] Build hierarchical catalog option
- [ ] Test with 50+ data sources

## Best Practices

### DO:
✅ Load conversions.json and catalog.json in preprocessing layer
✅ Use existing `llm_summary` fields in catalog (already optimized!)
✅ Filter catalog to 2-10 relevant sources before LLM
✅ Cache system prompt across queries
✅ Show country codes, not full region definitions, to LLM
✅ Use semantic search for catalog when you have 50+ sources

### DON'T:
❌ Load full conversions.json into any prompt
❌ Load full catalog.json into any prompt
❌ Show all 200 sources to LLM every time
❌ Repeat location resolution inside LLM
❌ Include irrelevant sources in user prompt

## Monitoring and Optimization

Track these metrics to optimize over time:

```python
class PromptMetrics:
    def log_query(self, query_data):
        return {
            "system_prompt_tokens": 2500,
            "user_prompt_tokens": 1200,
            "total_tokens": 3700,
            "sources_filtered": 185,  # Out of 200
            "sources_shown": 5,       # To LLM
            "preprocessing_time_ms": 15,
            "llm_time_ms": 800,
            "total_time_ms": 815
        }
```

**Optimization triggers:**
- If user_prompt > 2,000 tokens → increase filtering strictness
- If sources_shown > 10 → use semantic search
- If preprocessing_time > 50ms → optimize location extraction
- If hit rate < 80% → improve filtering logic

## Example Queries

### Query 1: Regional + Topic
**Input:** "How has poverty changed in Sub-Saharan Africa since 2000?"

**Preprocessing:**
- Extract: "Sub-Saharan Africa", "poverty"
- Resolve: SSA → 48 country codes
- Filter catalog: 2 sources (poverty-related with SSA coverage)

**System prompt:** 2,000 tokens
**User prompt:** 1,100 tokens (query + 48 countries + 2 sources)
**Total:** 3,100 tokens

### Query 2: Specific Country + Multiple Topics
**Input:** "Compare GDP and emissions for Kenya from 2010-2020"

**Preprocessing:**
- Extract: "Kenya", "GDP", "emissions"
- Resolve: Kenya → ["KEN"]
- Filter catalog: 2 sources (economic, environmental with Kenya coverage)

**System prompt:** 2,000 tokens
**User prompt:** 900 tokens (query + 1 country + 2 sources)
**Total:** 2,900 tokens

### Query 3: Complex Regional Query
**Input:** "Show me health indicators for all ASEAN countries"

**Preprocessing:**
- Extract: "ASEAN", "health"
- Resolve: ASEAN → 10 country codes
- Filter catalog: 3 sources (health category with ASEAN coverage)

**System prompt:** 2,000 tokens
**User prompt:** 1,000 tokens (query + 10 countries + 3 sources)
**Total:** 3,000 tokens

## Conclusion

The three-tier approach provides:
- **85-90% reduction in token usage** vs naive approach
- **Faster response times** from smaller prompts
- **Better relevance** by showing only pertinent information
- **Scalability** to 200+ data sources without degradation
- **Lower costs** from reduced token consumption

The key insight: conversions.json and catalog.json are **reference databases for your code**, not **context for the LLM**. Use preprocessing to extract only what's needed, then inject minimal, focused context into each prompt.
