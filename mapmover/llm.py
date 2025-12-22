"""
LLM initialization and database selection.
Handles OpenAI/LangChain setup and intelligent dataset selection.
"""

import json
import logging
import os
import re
from dotenv import load_dotenv
from langchain_openai import OpenAI
from langchain_core.prompts import PromptTemplate

from .data_loading import get_data_catalog, load_csv_smart, get_primary_datasets

# Load environment variables (ensures OPENAI_API_KEY is available)
load_dotenv()

logger = logging.getLogger("mapmover")


# Initialize LLM and prompt once
llm = OpenAI(
    model="gpt-3.5-turbo-instruct",
    temperature=0.5,
    max_tokens=2048
)

prompt = PromptTemplate.from_template(
    """You are a geography query parser. Extract structured data from user questions.

MAP VIEW CONTEXT (use this to disambiguate place names and determine scale):
- Center: {lat}, {lng}
- Zoom level: {zoom}

ZOOM LEVEL INTERPRETATION:
- zoom 1-5: Continental/national view -> interpret ambiguous places as countries/states
- zoom 6-8: State/regional view -> interpret ambiguous places as states/counties
- zoom 9-12: Metro/city view -> interpret places as cities/specific counties
- zoom 13+: Local view -> interpret places as neighborhoods/specific locations

PLACE NAME DISAMBIGUATION:
- "New York" at zoom 3-7 -> New York State
- "New York" at zoom 8-12 centered near NYC (40.7N, 74W) -> New York City/County
- "Washington" at zoom 5 -> Washington State
- "Washington" at zoom 10 centered near DC (38.9N, 77W) -> Washington DC
- "Paris" at zoom 5 centered on Europe -> Paris, France
- "Paris" at zoom 8 centered on Texas (33N, 95W) -> Paris, Texas

CRITICAL: You MUST return valid JSON with ALL required fields.

Required JSON fields:
{{
  "interest": "what user wants to know about",
  "scale": "geographic level (city/county/state/country)",
  "country": "country name or USA",
  "place": [["Place1", "ST"], ["Place2", "ST"]],
  "region_filter": null OR "Europe" OR "EU" OR "Africa" OR "G7" OR "ASEAN" etc.,
  "filter": null OR {{"column": "Column Name", "operator": ">", "value": 100, "unit": "km2"}},
  "sort_by": null OR "column_name",
  "sort_order": null OR "asc" OR "desc",
  "limit": null OR number
}}

REGION FILTER RULES:
- If query mentions a region/continent like "Europe", "Africa", "Asia", "Americas" -> region_filter: "Europe" etc.
- If query mentions a group like "EU", "G7", "G20", "NATO", "ASEAN", "Arab League" -> region_filter: that group name
- If query says "European countries" or "countries in Europe" -> region_filter: "Europe"
- If query says "South American countries" or "countries in South America" -> region_filter: "South America"
- If NO region/continent/group mentioned -> region_filter: null
- Use the EXACT region name as shown (case-sensitive): "South America" not "south america"
- Supported continents/sub-regions: Europe, Africa, Americas, South America, North America, Central America, Latin America, Caribbean, South East Asia, Western Pacific, Eastern Mediterranean
- Supported groups: EU, European Union, G7, G20, NATO, ASEAN, Arab League, African Union, BRICS, Nordic Countries, Baltic States, Pacific Islands, Gulf Cooperation Council, Maghreb, Benelux, Commonwealth

SORTING AND LIMITING RULES:
- If query asks for "top N largest/highest/biggest" -> sort_order: "desc", limit: N, sort_by: relevant column
- If query asks for "top N smallest/lowest" -> sort_order: "asc", limit: N, sort_by: relevant column
- If query asks for "bottom N" -> sort_order: "asc", limit: N, sort_by: relevant column
- For "largest GDP" -> sort_by: "gdp" or similar economic column
- For "highest population" -> sort_by: "population" or "pop_est"
- For "most emissions" -> sort_by: "co2" or "emissions"
- Extract the NUMBER (5 in "top 5") -> limit
- If NO sorting/limiting requested -> sort_by: null, sort_order: null, limit: null

FILTER DETECTION RULES (for non-year columns):
- If query has "greater than", "more than", "over", "above" -> operator: ">"
- If query has "less than", "under", "below" -> operator: "<"
- If query mentions "water area" -> column: "Water Area"
- If query mentions "land area" -> column: "Land Area"
- Extract the NUMBER from the query -> value
- Extract the UNIT (km2, mi2, acres, etc.) -> unit
- If NO numerical comparison exists -> filter: null
- IMPORTANT: NEVER use filter for years! Always use year_filter instead.

YEAR FILTER RULES (separate from filter):
- ALWAYS use year_filter for temporal queries, NEVER use filter with "Year" column
- If NO year mentioned -> year_filter: {{"type": "latest"}}
- If specific year (e.g., "in 2020", "2020 population") -> year_filter: {{"type": "single", "year": 2020}}
- If year range (e.g., "2015 to 2023", "between 2015-2023") -> year_filter: {{"type": "range", "start": 2015, "end": 2023}}
- If comparison (e.g., "2020 vs 2023") -> year_filter: {{"type": "comparison", "years": [2020, 2023]}}
- Extract ONLY the numeric year (2020, not "January 2020" - ignore month/day)

Examples:

Query: "show me all the counties in new york" (zoom: 7, center: 42N, 76W)
Output: {{"interest": "counties", "scale": "county", "country": "USA", "place": [["Albany", "NY"], ["Bronx", "NY"], ["Kings", "NY"]], "filter": null, "year_filter": {{"type": "latest"}}, "sort_by": null, "sort_order": null, "limit": null}}

Query: "show me counties in california with water area greater than 500 km2" (zoom: 6)
Output: {{"interest": "water area", "scale": "county", "country": "USA", "place": [["Los Angeles", "CA"], ["San Diego", "CA"]], "filter": {{"column": "Water Area", "operator": ">", "value": 500, "unit": "km2"}}, "year_filter": {{"type": "latest"}}, "sort_by": null, "sort_order": null, "limit": null}}

Query: "what are the top 5 largest gdp countries"
Output: {{"interest": "gdp", "scale": "country", "country": "all", "place": [], "filter": null, "year_filter": {{"type": "latest"}}, "sort_by": "gdp", "sort_order": "desc", "limit": 5}}

Query: "show me the 10 smallest countries by population"
Output: {{"interest": "population", "scale": "country", "country": "all", "place": [], "filter": null, "year_filter": {{"type": "latest"}}, "sort_by": "population", "sort_order": "asc", "limit": 10}}

Query: "top 3 countries with highest CO2 emissions"
Output: {{"interest": "co2 emissions", "scale": "country", "country": "all", "place": [], "filter": null, "year_filter": {{"type": "latest"}}, "sort_by": "co2", "sort_order": "desc", "limit": 3}}

Query: "life expectancy in Canada in 2020"
Output: {{"interest": "life expectancy", "scale": "country", "country": "all", "place": [["Canada", ""]], "filter": null, "year_filter": {{"type": "single", "year": 2020}}, "sort_by": null, "sort_order": null, "limit": null}}

Query: "how did population change in Brazil between 2015 and 2023"
Output: {{"interest": "population", "scale": "country", "country": "all", "place": [["Brazil", ""]], "region_filter": null, "filter": null, "year_filter": {{"type": "range", "start": 2015, "end": 2023}}, "sort_by": null, "sort_order": null, "limit": null}}

Query: "show me data for all countries in Europe" (region filter example)
Output: {{"interest": "data", "scale": "country", "country": "all", "place": [], "region_filter": "Europe", "filter": null, "year_filter": {{"type": "latest"}}, "sort_by": null, "sort_order": null, "limit": null}}

Query: "top 5 G7 countries by GDP" (region filter with sort)
Output: {{"interest": "gdp", "scale": "country", "country": "all", "place": [], "region_filter": "G7", "filter": null, "year_filter": {{"type": "latest"}}, "sort_by": "gdp", "sort_order": "desc", "limit": 5}}

Now parse this query: {query}

Return ONLY valid JSON, no explanations:"""
)

chain = prompt | llm


def choose_database(user_query: str):
    """
    Uses LLM to intelligently select which CSV file(s) to query based on user's question
    and the available data catalog.
    """
    data_catalog = get_data_catalog()

    if not data_catalog:
        raise Exception("Data catalog is empty. No CSV files found in data_pipeline/data_cleaned/ folder.")

    # Filter out geometry-only datasets - they should only be used for joining, not as primary data sources
    queryable_catalog = [item for item in data_catalog if not item.get('is_geometry_only', False)]

    if not queryable_catalog:
        raise Exception("No queryable datasets found (all are geometry-only).")

    # Build catalog description for LLM (optimized for token efficiency)
    # Use filtered catalog indices that map back to original
    catalog_desc = ""
    index_map = {}  # Maps LLM index -> actual data_catalog index

    for display_idx, item in enumerate(queryable_catalog):
        # Find original index in data_catalog
        original_idx = data_catalog.index(item)
        index_map[display_idx] = original_idx

        metadata = item.get('metadata', {})

        # Get most distinctive keywords - prioritize domain-specific terms
        keywords = metadata.get('keywords', [])
        # Filter out generic/common terms but keep important economic/health/environmental indicators
        generic_terms = {'name', 'year', 'code', 'people', 'pop', 'residents', 'location',
                        'aggregate', 'sum', 'total', 'abs', 'avg', 'capita', 'concentration',
                        'density', 'per', 'from', 'change', 'degrees', 'of', 'and', 'or', 'the'}
        # Take more keywords but filter generics to get specific terms like 'co2', 'health', 'gdp', etc.
        distinctive = [k for k in keywords[:40] if k not in generic_terms][:12]

        # Use filename without extension as primary identifier
        fname = item['filename'].replace('.csv', '')
        geo = metadata.get('geographic_level', 'unknown')
        desc = metadata.get('description', '')

        # Add priority indicator based on score
        priority_score = item.get('priority_score', 0)
        if priority_score >= 150:
            data_indicator = "[PRIMARY SOURCE]"
        elif priority_score >= 75:
            data_indicator = "[COMPREHENSIVE]"
        else:
            data_indicator = ""

        catalog_desc += f"{display_idx}. {fname} ({geo}) {data_indicator}: {', '.join(distinctive)} | {desc[:80]}\n"

    # Improved prompt for dataset selection
    selection_prompt = PromptTemplate.from_template(
        """Select the dataset index that best matches this query. Reply with ONLY a JSON object.

Query: "{query}"

Datasets:
{catalog}

SELECTION RULES:
1. Match the DATA SUBJECT in the query (gdp, co2, population, health) to dataset keywords
2. Ignore modifiers like "top", "largest", "lowest", "European" - focus on the DATA TYPE
3. PREFER datasets marked [PRIMARY SOURCE] - they are the best source for their topics
4. The FIRST keywords listed are the primary indicators for each dataset

Reply format: {{"file_index": NUMBER}}"""
    )

    # Use a lighter LLM configuration for file selection to avoid token limits
    selection_llm = OpenAI(
        model="gpt-3.5-turbo-instruct",
        temperature=0.0,  # More deterministic
        max_tokens=30  # Much smaller - only need a number
    )
    selection_chain = selection_prompt | selection_llm

    try:
        # Debug: show catalog being sent to LLM
        logger.debug(f"=== Database Selection for query: {user_query} ===")
        logger.debug(f"Catalog sent to LLM:\n{catalog_desc}")

        response = selection_chain.invoke({
            "catalog": catalog_desc,
            "query": user_query
        })

        logger.debug(f"LLM selection response: {response}")

        # Try to extract JSON if there's extra text
        response_text = response.strip()

        # Method 1: Try to find JSON in response
        if '{' in response_text:
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            response_text = response_text[json_start:json_end]
            selection = json.loads(response_text)
        else:
            # Method 2: Try to extract a number from the response
            numbers = re.findall(r'\b(\d+)\b', response_text)
            if numbers:
                # Take the first number that's a valid index
                for num_str in numbers:
                    num = int(num_str)
                    if 0 <= num < len(queryable_catalog):
                        logger.debug(f"Extracted index {num} from non-JSON response")
                        selection = {"file_index": num}
                        break
                else:
                    raise ValueError("No valid index found in response")
            else:
                raise ValueError("No JSON or number found in response")

        # Get the LLM's selected index and map it back to the original catalog
        llm_index = selection.get("file_index", 0)

        # Validate and map the index
        if llm_index in index_map:
            file_index = index_map[llm_index]
        else:
            # If invalid index, default to first queryable dataset
            logger.warning(f"LLM returned invalid index {llm_index}, using first queryable dataset")
            file_index = index_map.get(0, 0)

        reason = selection.get("reason", "No reason provided")

        logger.debug(f"Selected: {data_catalog[file_index]['filename']} - {reason}")

        # Load the selected file with smart column selection
        selected_file = data_catalog[file_index]
        df = load_csv_smart(
            selected_file["path"],
            selected_file["delimiter"],
            query=user_query,
            metadata=selected_file.get("metadata")
        )

        return df, selected_file["filename"]

    except Exception as e:
        print(f"Error in choose_database: {e}")
        # Fallback to first queryable file (highest priority)
        fallback = queryable_catalog[0] if queryable_catalog else data_catalog[0]
        print(f"Falling back to: {fallback['filename']}")
        df = load_csv_smart(
            fallback["path"],
            fallback["delimiter"],
            query=user_query,
            metadata=fallback.get("metadata")
        )
        return df, fallback["filename"]


def get_chain():
    """Get the query parsing chain."""
    return chain


def get_llm():
    """Get the base LLM instance."""
    return llm
