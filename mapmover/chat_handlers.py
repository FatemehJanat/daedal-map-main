"""
Chat endpoint handlers.
Handles chat intent detection, data fetching, and conversational responses.
"""

import json
import logging
import re
import traceback
from fastapi.responses import JSONResponse
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage

from .utils import state_from_abbr, apply_unit_multiplier, clean_nans, parse_year_value
from .geography import get_countries_in_region, get_country_names_from_codes, get_region_patterns, get_supported_regions_text, get_limited_geometry_countries
from .logging_analytics import log_conversation, log_missing_geometry, log_error_to_cloud
from .data_loading import get_data_catalog, get_ultimate_metadata
from .meta_queries import detect_meta_query, handle_meta_query
from .map_state import get_map_state, clear_map_state, build_incremental_response, add_source_to_state
from .response_builder import build_response
from .geometry_joining import auto_join_geometry
from .geometry_enrichment import detect_missing_geometry
from .llm import choose_database, get_chain

logger = logging.getLogger("mapmover")


def preview_data_availability(query_text):
    """
    Preview how much data is available for a potential query.
    Returns a dict with counts. This is a LIGHTWEIGHT check - no geometry joins.
    Geometry join reliability is guaranteed by data ingestion standardization.
    Used to inform user BEFORE they confirm a query.
    """
    try:
        # Parse the query to understand what data is being requested
        query_lower = query_text.lower()

        # Detect region - dynamically loaded from conversions.json
        region_filter = None
        region_patterns = get_region_patterns()

        # Sort patterns by length (longest first) to match "south america" before "america"
        sorted_patterns = sorted(region_patterns.keys(), key=len, reverse=True)
        for pattern in sorted_patterns:
            if pattern in query_lower:
                region_filter = region_patterns[pattern]
                logger.debug(f"Preview detected region: '{pattern}' -> '{region_filter}'")
                break

        # Detect year
        year_filter = None
        year_match = re.search(r'\b(19|20)\d{2}\b', query_text)
        if year_match:
            year_filter = {"type": "single", "year": int(year_match.group())}

        # Detect topic to choose database
        topic_keywords = {
            'gdp': 'gdp',
            'co2': 'co2',
            'emission': 'co2',
            'population': 'population',
            'income': 'gdp'
        }
        detected_topic = None
        for keyword, topic in topic_keywords.items():
            if keyword in query_lower:
                detected_topic = topic
                break

        if not detected_topic:
            return {"status": "unknown", "message": "Could not determine topic"}

        # Choose the appropriate database (CSVs are already loaded in memory)
        lookup_df, selected_filename = choose_database(query_text)
        if lookup_df is None or len(lookup_df) == 0:
            return {"status": "no_data", "message": "No dataset found"}

        # Apply region filter if present
        total_in_region = 0
        if region_filter:
            country_codes = get_countries_in_region(region_filter, query=query_text, dataset=selected_filename)
            if country_codes:
                total_in_region = len(country_codes)
                # Find country code column
                code_cols = [c for c in lookup_df.columns if 'country_code' in c.lower() or 'iso' in c.lower()]
                if code_cols:
                    lookup_df = lookup_df[lookup_df[code_cols[0]].isin(country_codes)].copy()

        # Apply year filter
        if year_filter and year_filter.get("type") == "single":
            year_val = year_filter.get("year")
            # Look for year column
            year_cols = [c for c in lookup_df.columns if 'year' in c.lower()]
            if year_cols:
                year_col = year_cols[0]
                lookup_df = lookup_df[lookup_df[year_col].apply(lambda x: parse_year_value(x) == year_val)].copy()

        # Count unique countries/places
        name_cols = [c for c in lookup_df.columns if 'country' in c.lower() and 'name' in c.lower()]
        if not name_cols:
            name_cols = [c for c in lookup_df.columns if 'country' in c.lower()]

        unique_count = len(lookup_df[name_cols[0]].unique()) if name_cols and len(lookup_df) > 0 else len(lookup_df)

        # Check for data in the topic column
        topic_col = None
        for col in lookup_df.columns:
            if detected_topic in col.lower():
                topic_col = col
                break

        data_with_values = 0
        if topic_col:
            data_with_values = lookup_df[topic_col].notna().sum()

        # Check geometry availability using limited_geometry_countries list
        limited_geom_codes = get_limited_geometry_countries()
        code_cols = [c for c in lookup_df.columns if 'country_code' in c.lower() or 'iso' in c.lower()]

        limited_geometry_count = 0
        limited_geometry_names = []

        if code_cols and len(lookup_df) > 0:
            code_col = code_cols[0]
            unique_codes = lookup_df[code_col].dropna().unique()
            for code in unique_codes:
                if code in limited_geom_codes:
                    limited_geometry_count += 1
                    # Get name for this code
                    names = get_country_names_from_codes([code])
                    if names:
                        limited_geometry_names.append(names[0])

        with_full_geometry = unique_count - limited_geometry_count

        # Build result
        result = {
            "status": "ok",
            "total_requested": total_in_region if region_filter else "all",
            "data_found": unique_count,
            "with_values": data_with_values,
            "with_geometry": with_full_geometry,
            "limited_geometry_count": limited_geometry_count,
            "limited_geometry_names": limited_geometry_names[:5],  # Limit to 5 names
            "dataset": selected_filename,
            "year": year_filter.get("year") if year_filter else None,
            "region": region_filter
        }

        return result

    except Exception as e:
        logger.error(f"Preview error: {e}")
        return {"status": "error", "message": str(e)}


async def generate_helpful_no_results_message(query, lookup_df, selected_filename, selected_file_metadata, year_filter):
    """
    Generate a friendly, helpful message when no results are found.
    Suggests alternatives based on available data.
    """
    suggestions = []

    # Check for year-related issues
    if year_filter and "Year" in lookup_df.columns:
        raw_years = lookup_df["Year"].dropna().unique()
        parsed_years = [parse_year_value(y) for y in raw_years]
        available_years = sorted([y for y in parsed_years if y is not None])
        if available_years:
            requested_year = None
            if year_filter.get("type") == "single":
                requested_year = year_filter.get("year")
            elif year_filter.get("type") == "range":
                requested_year = f"{year_filter.get('start')}-{year_filter.get('end')}"

            if requested_year:
                latest_year = available_years[-1]
                earliest_year = available_years[0]

                # Year not in range
                if year_filter.get("type") == "single":
                    req_yr = int(year_filter.get("year", 0))
                    if req_yr < earliest_year or req_yr > latest_year:
                        suggestions.append(f"I don't have data for {req_yr}. My data covers {earliest_year} to {latest_year}. Would you like to see the latest year ({latest_year}) instead?")

    # Check what columns/metrics are available
    if selected_file_metadata:
        available_columns = selected_file_metadata.get("numeric_columns", [])
        if available_columns:
            sample_cols = available_columns[:5]
            suggestions.append(f"This dataset includes: {', '.join(sample_cols)}. Would you like to explore any of these?")

        # Geographic level mismatch
        geo_level = selected_file_metadata.get("geographic_level", "")
        if geo_level:
            suggestions.append(f"This dataset covers {geo_level}-level data.")

    # Check if we have related datasets
    if "country" in query.lower() or "countries" in query.lower():
        suggestions.append("For country-level data, I have information on GDP, population, CO2 emissions, and more. Try 'show me GDP for all countries'.")
    elif "county" in query.lower() or "counties" in query.lower():
        suggestions.append("For US counties, I have demographic and census data. Try 'show me population of Texas counties'.")
    elif "state" in query.lower() or "states" in query.lower():
        suggestions.append("For US states, try asking about specific metrics like population or demographics.")

    # Build the response
    if suggestions:
        return f"I couldn't find exact matches for that query. {suggestions[0]}"
    else:
        return "I couldn't find data matching your request. Could you try being more specific? For example, mention a country name, a specific year, or a metric like GDP or population."


def generate_friendly_error_message(error_type, context=None):
    """
    Convert technical errors into friendly, conversational messages.
    """
    error_messages = {
        "json_parse": "I had a bit of trouble understanding that request. Could you rephrase it? Try something like 'show me the top 10 countries by GDP' or 'population of California counties'.",
        "no_database": "I'm not sure which dataset to use for that. Could you be more specific about what you're looking for? I have country data (GDP, emissions, population) and US census data.",
        "column_not_found": f"I don't have a column called '{context}' in this dataset. Let me know what metric you're interested in and I can suggest alternatives.",
        "geographic_mismatch": "That geographic level might not be available in this dataset. Try asking about countries, US states, or US counties specifically.",
        "timeout": "That query is taking longer than expected. Try narrowing it down - maybe fewer countries or a specific region?",
        "general": "Something went wrong on my end. Could you try that again? If it keeps happening, try simplifying your request."
    }

    return error_messages.get(error_type, error_messages["general"])


def generate_chat_summary(query, response_data, filename, count, filter_spec, sort_spec, region_filter=None):
    """Generate a conversational summary of the results."""
    parts = []

    # Describe what we found
    if count == 1:
        parts.append(f"I found 1 result")
    else:
        parts.append(f"I found {count} results")

    # Add region context if filtered
    if region_filter:
        parts.append(f"in {region_filter}")

    # Add context about the data
    if sort_spec and sort_spec.get("limit"):
        parts.append(f"showing the top {sort_spec['limit']}")

    if sort_spec and sort_spec.get("sort_by"):
        order = "highest" if sort_spec.get("sort_order", "desc") == "desc" else "lowest"
        parts.append(f"by {order} {sort_spec['sort_by']}")

    if filter_spec and filter_spec.get("column"):
        parts.append(f"filtered by {filter_spec['column']}")

    summary = " ".join(parts) + "."

    # Add note about missing geometry if any
    missing_count = response_data.get("missing_geometry_count", 0)
    missing_names = response_data.get("missing_geometry", [])
    if missing_count > 0:
        if missing_count <= 5 and missing_names:
            summary += f" Note: {missing_count} locations missing map boundaries ({', '.join(missing_names[:3])})."
        else:
            summary += f" Note: {missing_count} locations could not be displayed (missing map boundaries)."

    return summary


def get_helpful_response(query):
    """Generate helpful responses for conversational queries."""
    query_lower = query.lower()

    if "what data" in query_lower or "what can" in query_lower:
        return """I can help you explore geographic data including:

- **Country data**: GDP, population, CO2 emissions, energy consumption
- **US States**: Population, land area, demographics
- **US Counties**: Population, area, census data

Try asking something like:
- "Show me countries with the highest CO2 emissions"
- "What's the population of Texas counties?"
- "Compare GDP across European nations"
"""

    if "how" in query_lower:
        return """Here's how to use this map explorer:

1. **Ask a question** about geographic data you want to see
2. **Review the results** - I'll tell you what I found
3. **Click 'Show on Map'** to visualize the data
4. **Ask follow-ups** to refine your search

Example queries:
- "Top 10 countries by population"
- "Counties in California"
- "Countries with GDP over 1 trillion"
"""

    # Default helpful response
    return """I'm here to help you explore geographic data! You can ask me about:

- Countries (GDP, population, emissions, etc.)
- US States and Counties
- Comparisons and rankings

What would you like to explore?"""


async def fetch_and_return_data(query, current_view, display_immediately=False, endpoint="chat", session_id=None):
    """
    Fetch data using the existing query parsing pipeline.

    Args:
        query: The user's query string
        current_view: Dict with map view (clat, clng, czoom)
        display_immediately: Whether to display results immediately
        endpoint: Which endpoint called this ('chat' or 'location')
        session_id: Session identifier for conversation logging
    """
    region_filter = None  # Initialize for error handling

    try:
        data_catalog = get_data_catalog()
        chain = get_chain()

        # Choose database
        lookup_df, selected_filename = choose_database(query)
        logger.debug(f"Dataset: '{selected_filename}' ({len(lookup_df)} rows)")

        # Get metadata
        selected_file_metadata = None
        for cat_item in data_catalog:
            if cat_item["filename"] == selected_filename:
                selected_file_metadata = cat_item.get("metadata")
                break

        # Parse query with existing chain
        response = chain.invoke({
            "query": query,
            "lat": current_view.get('clat', 0),
            "lng": current_view.get('clng', 0),
            "zoom": current_view.get('czoom', 5)
        })
        logger.debug(f"Query LLM: '{query[:80]}...'")
        logger.debug(f"Query response: {response.strip()[:200]}...")
        raw = json.loads(response.strip())

        # Extract places
        cleaned = []
        county_list = raw.get("place") or []
        if county_list:
            for pair in county_list:
                if isinstance(pair, list) and len(pair) == 2:
                    county, state = pair
                    cleaned.append({
                        "place": county.strip(),
                        "state": state_from_abbr(state.strip())
                    })

        # Extract filters
        filter_spec = raw.get("filter")
        if filter_spec:
            # Handle numerical multipliers (billion, million, etc.) - uses shared helper
            apply_unit_multiplier(filter_spec)

        year_filter = raw.get("year_filter")
        region_filter = raw.get("region_filter")
        logger.debug(f"Parsed: region={region_filter}, year={year_filter}")
        sort_spec = None
        if raw.get("sort_by") or raw.get("limit"):
            sort_spec = {
                "sort_by": raw.get("sort_by"),
                "sort_order": raw.get("sort_order", "desc"),
                "limit": raw.get("limit")
            }

        # Apply region filter if present (filter to countries in region)
        if region_filter:
            country_codes = get_countries_in_region(region_filter, query=query, dataset=selected_filename)
            logger.debug(f"Region '{region_filter}': {len(country_codes) if country_codes else 0} countries")
            if country_codes:
                # Get country names from codes
                country_names = get_country_names_from_codes(country_codes)
                logger.debug(f"Filtering to {len(country_codes)} countries in {region_filter}")

                # Find country code or name column in the dataframe
                code_cols = [c for c in lookup_df.columns if 'country_code' in c.lower() or 'iso' in c.lower()]
                name_cols = [c for c in lookup_df.columns if 'country' in c.lower() and 'name' in c.lower()]

                original_rows = len(lookup_df)

                if code_cols:
                    # Filter by country code
                    code_col = code_cols[0]
                    lookup_df = lookup_df[lookup_df[code_col].isin(country_codes)].copy()
                    logger.debug(f"Filtered: {original_rows} -> {len(lookup_df)} rows")
                elif name_cols:
                    # Filter by country name
                    name_col = name_cols[0]
                    # Case-insensitive match
                    country_names_lower = [n.lower() for n in country_names]
                    lookup_df = lookup_df[lookup_df[name_col].str.lower().isin(country_names_lower)].copy()
                    logger.debug(f"Filtered: {original_rows} -> {len(lookup_df)} rows")
                else:
                    # Try 'country' column directly
                    if 'country' in lookup_df.columns:
                        country_names_lower = [n.lower() for n in country_names]
                        lookup_df = lookup_df[lookup_df['country'].str.lower().isin(country_names_lower)].copy()
                        logger.debug(f"Filtered: {original_rows} -> {len(lookup_df)} rows")

        # Note: Aggregate rows (World, Africa, Asia, etc.) are now removed during data ingestion
        # in prepare_data.py remove_aggregate_rows() - no need for runtime filtering

        # Build response
        interest = raw.get("interest")
        logger.debug(f"Building response: {len(lookup_df)} rows")
        response_data = build_response(cleaned, lookup_df, filter_spec, selected_file_metadata, year_filter, sort_spec, interest)

        # Handle geometry fallback
        if detect_missing_geometry(lookup_df) and selected_file_metadata:
            joined_df = auto_join_geometry(lookup_df, selected_filename, selected_file_metadata, data_catalog)
            if not detect_missing_geometry(joined_df):
                response_data = build_response(cleaned, joined_df, filter_spec, selected_file_metadata, year_filter, sort_spec, interest)

        # Check results
        result_count = len(response_data.get("geojson", {}).get("features", []))

        # Log any missing geometries for tracking
        missing_geo = response_data.get("missing_geometry", [])
        if missing_geo:
            log_missing_geometry(
                country_names=missing_geo,
                query=query,
                dataset=selected_filename,
                region=region_filter
            )

        if result_count > 0:
            summary = generate_chat_summary(query, response_data, selected_filename, result_count, filter_spec, sort_spec, region_filter)

            # Clean NaN values (uses shared helper)
            cleaned_response = clean_nans(response_data)
            cleaned_response["summary"] = summary
            cleaned_response["message"] = summary
            cleaned_response["displayImmediately"] = display_immediately
            cleaned_response["dataset_name"] = selected_filename

            # Update map state for incremental modifications
            features = cleaned_response.get("geojson", {}).get("features", [])
            if features:
                from .map_state import _current_map_state
                _current_map_state["features"] = features
                _current_map_state["dataset"] = selected_filename
                _current_map_state["region"] = region_filter
                # Extract year from year_filter
                if year_filter and year_filter.get("type") == "single":
                    _current_map_state["year"] = year_filter.get("year")
                # Track which data fields are shown
                if interest:
                    _current_map_state["data_fields"] = [interest]
                    # Track source for this field
                    add_source_to_state(selected_filename, interest)
                # Extract country codes from features
                codes = [f.get("properties", {}).get("country_code") for f in features if f.get("properties", {}).get("country_code")]
                _current_map_state["country_codes"] = codes
                logger.debug(f"Map state: {len(features)} features")

            if selected_file_metadata:
                cleaned_response["source_name"] = selected_file_metadata.get("source_name", "Unknown")
                cleaned_response["source_url"] = selected_file_metadata.get("source_url", "")

            # Include all sources in response
            from .map_state import _current_map_state
            cleaned_response["sources"] = _current_map_state.get("sources", [])

            # Log conversation with session tracking
            log_conversation(
                session_id=session_id,
                query=query,
                response_text=summary,
                intent="fetch_data",
                dataset_selected=selected_filename,
                results_count=result_count,
                endpoint=endpoint
            )

            return JSONResponse(content=cleaned_response)
        else:
            # Generate a helpful, conversational message about why no results
            helpful_message = await generate_helpful_no_results_message(
                query, lookup_df, selected_filename, selected_file_metadata, year_filter
            )
            return JSONResponse(content={
                "message": helpful_message,
                "geojson": {"type": "FeatureCollection", "features": []},
                "needsMoreInfo": True
            })

    except json.JSONDecodeError:
        return JSONResponse(content={
            "message": generate_friendly_error_message("json_parse"),
            "geojson": {"type": "FeatureCollection", "features": []},
            "needsMoreInfo": True
        })
    except Exception as e:
        logger.error(f"Data fetch error: {e}")
        traceback.print_exc()

        # Log error to Supabase for centralized tracking
        log_error_to_cloud(
            error_type=type(e).__name__,
            error_message=str(e),
            query=query,
            tb=traceback.format_exc(),
            metadata={"function": "fetch_and_return_data", "region": region_filter}
        )

        # Provide friendly message instead of technical error
        error_str = str(e).lower()
        if "column" in error_str or "key" in error_str:
            friendly_msg = generate_friendly_error_message("column_not_found", str(e))
        elif "timeout" in error_str:
            friendly_msg = generate_friendly_error_message("timeout")
        else:
            friendly_msg = generate_friendly_error_message("general")

        return JSONResponse(content={
            "message": friendly_msg,
            "geojson": {"type": "FeatureCollection", "features": []},
            "needsMoreInfo": True
        })


async def determine_chat_intent(query, history_context):
    """
    Conversation LLM that helps users explore data before querying.

    Returns either:
    - {"intent": "chat", "response": "..."} - just respond, no data fetch
    - {"intent": "fetch_data", "response": "...", "data_query": "..."} - fetch data with cleaned query
    - {"intent": "modify_data", "response": "...", "modify_action": "..."} - modify existing map
    - {"intent": "clarify", "response": "..."} - need more information
    - {"intent": "meta", "response": "..."} - asking about available data
    """
    data_catalog = get_data_catalog()

    # PRE-VALIDATION: Check if query contains specifics that warrant data preview
    combined_context = (history_context + " " + query).lower()

    # Check if we have enough specifics to do a preview (topic + region or year)
    has_topic = any(t in combined_context for t in ['gdp', 'co2', 'emission', 'population', 'income'])
    has_region = any(r in combined_context for r in ['africa', 'europe', 'asia', 'americas', 'eu', 'g7', 'g20', 'nato'])
    has_year = bool(re.search(r'\b(19|20)\d{2}\b', combined_context))

    # Pre-validate if user is providing specifics (not just exploring)
    preview_context = ""
    if has_topic and (has_region or has_year):
        # Build a query string from context for preview
        preview_query = combined_context
        preview_result = preview_data_availability(preview_query)

        if preview_result.get("status") == "ok":
            found = preview_result.get("data_found", 0)
            with_geom = preview_result.get("with_geometry", found)
            limited_count = preview_result.get("limited_geometry_count", 0)
            limited_names = preview_result.get("limited_geometry_names", [])
            year = preview_result.get("year")
            region = preview_result.get("region")

            if found > 0:
                # Build context string for LLM
                preview_parts = [f"DATA PREVIEW: Found {found} locations"]
                if year:
                    preview_parts.append(f"for year {year}")
                if region:
                    preview_parts.append(f"in {region}")

                # Add info about limited geometry countries
                if limited_count > 0:
                    preview_parts.append(f"({with_geom} with full map boundaries, {limited_count} small nations as points)")
                    if limited_names:
                        preview_parts.append(f"Small nations: {', '.join(limited_names[:3])}")

                preview_context = "\n" + " ".join(preview_parts) + "\n"
                logger.debug(f"Preview context: {preview_context.strip()}")

    # Build available data context from actual catalog - optimized for LLM comprehension
    available_topics = []
    dataset_summaries = []

    # Priority keywords for identifying important data columns (not metadata/identifiers)
    priority_data_terms = {'gdp', 'co2', 'emission', 'population', 'income', 'health',
                          'mortality', 'energy', 'temperature', 'methane', 'trade'}

    for item in data_catalog:
        if item.get("metadata") and not item.get("is_geometry_only"):
            meta = item["metadata"]
            filename = item.get("filename", "Unknown")
            topics = meta.get("topic_tags", [])
            level = meta.get("geographic_level", "")

            if topics:
                available_topics.extend(topics)

            # Use pre-generated LLM summary if available (from ETL pipeline)
            llm_summary = meta.get("llm_summary", "")

            # Extract year range from data_year (the actual field used by ETL)
            year_str = ""
            data_year = meta.get("data_year", {})
            if isinstance(data_year, dict) and data_year.get("type") == "time_series":
                start_yr = data_year.get("start", "")
                end_yr = data_year.get("end", "")
                if start_yr and end_yr:
                    year_str = f"Years: {start_yr}-{end_yr}"
            elif isinstance(data_year, str) and data_year != "Unknown":
                year_str = f"Year: {data_year}"

            # If we have a good LLM summary, use it directly
            if llm_summary and len(llm_summary) > 20:
                summary = f"{filename}: {llm_summary}"
            else:
                # Fallback: build summary from metadata
                columns_info = meta.get("columns", {})
                priority_cols = []
                other_cols = []

                skip_patterns = ['year', 'rank', 'latitude', 'longitude', 'lat', 'lng', 'lon',
                               'code', 'id', 'fips', 'index']

                for col, info in columns_info.items():
                    if not isinstance(info, dict):
                        continue
                    role = info.get("role", "")
                    col_type = info.get("type", "")
                    col_lower = col.lower()

                    if role != "data" or col_type != "float":
                        continue

                    if any(skip in col_lower for skip in skip_patterns):
                        continue

                    if any(term in col_lower for term in priority_data_terms):
                        if 'per_capita' in col_lower or 'per capita' in col_lower:
                            priority_cols.append(col)
                        else:
                            priority_cols.insert(0, col)
                    else:
                        other_cols.append(col)

                key_cols = (priority_cols + other_cols)[:6]
                cols_str = ", ".join(key_cols) if key_cols else ""

                summary_parts = [f"{filename} ({level} level)"]
                if year_str:
                    summary_parts.append(year_str)
                if cols_str:
                    summary_parts.append(f"Data: {cols_str}")

                summary = " | ".join(summary_parts)

            dataset_summaries.append(f"- {summary}")

    available_topics = list(set(available_topics))[:15]
    datasets_text = "\n".join(dataset_summaries[:6]) if dataset_summaries else "Various geographic datasets"

    # Get supported regions dynamically from conversions.json
    supported_regions_text = get_supported_regions_text()

    # Get current map state for context
    map_state = get_map_state()
    map_context = ""
    country_names_on_map = []
    if map_state["features"]:
        region_text = map_state["region"] or "selected countries"
        fields_text = ", ".join(map_state["data_fields"]) if map_state["data_fields"] else "geometry only"
        year_text = f" for {map_state['year']}" if map_state["year"] else ""
        # Get country names for context
        country_names_on_map = [f.get("properties", {}).get("country_name", "") for f in map_state["features"][:10]]
        country_names_on_map = [n for n in country_names_on_map if n]
        names_text = f" ({', '.join(country_names_on_map[:5])}{'...' if len(country_names_on_map) > 5 else ''})" if country_names_on_map else ""
        map_context = f"\nCURRENT MAP: Showing {len(map_state['features'])} {region_text}{year_text}{names_text}. Data fields: {fields_text}\n"

    # System prompt
    system_prompt = f"""You are a helpful assistant for a geographic data explorer.

YOUR AVAILABLE DATA:
{datasets_text}

SUPPORTED REGIONS:
{supported_regions_text}
{preview_context}{map_context}
YOUR ROLE:
1. Help users discover what data is available
2. Guide them to refine their query (year, region, top N)
3. When you have DATA PREVIEW info, use it to give SPECIFIC counts in your confirmation
4. When the user wants to MODIFY existing map data (add/remove fields, change region/year), use MODIFY:

CONVERSATION FLOW:
- When user asks about data -> Tell them what's available, ask about year preference
- When user gives specifics (year, region) and you have DATA PREVIEW -> Use the exact count in your confirmation
- When user says yes/ok/sure/show it AND no map exists -> Output QUERY:
- When CURRENT MAP exists and user wants ANY changes -> Output MODIFY: with the action
- When user says "same locations" or "same countries" or refers to existing map -> Use MODIFY: to add/change data

IMPORTANT - WHEN CURRENT MAP EXISTS:
If CURRENT MAP shows data and user wants to:
- Add more data fields -> MODIFY: add_field [fieldname]
- Remove data fields -> MODIFY: remove_field [fieldname]
- Change the region -> MODIFY: change_region [region]
- Change the year -> MODIFY: change_year [year]
- See same locations with different data -> MODIFY: add_field [new], remove_field [old]
- Keep same locations, different metric -> MODIFY: add_field [new]

DO NOT use QUERY: when CURRENT MAP exists unless user explicitly wants completely different locations.

MODIFICATION EXAMPLES (when CURRENT MAP shows existing data):
- "also show population" -> MODIFY: add_field population
- "add population" -> MODIFY: add_field population
- "remove co2" -> MODIFY: remove_field co2
- "now show Asia instead" -> MODIFY: change_region Asia
- "show 2020 instead" -> MODIFY: change_year 2020
- "show me CO2 instead of GDP" -> MODIFY: remove_field gdp, add_field co2
- "add emissions data" -> MODIFY: add_field co2
- "same locations with population" -> MODIFY: add_field population
- "yes" (after asking about adding data to existing map) -> MODIFY: add_field [whatever was discussed]

CRITICAL RULES:
- If DATA PREVIEW is available, USE THE EXACT NUMBERS in your confirmation
- Mention any missing data (if DATA PREVIEW shows missing geometry, tell the user)
- ALWAYS include the year in your confirmation
- ALWAYS include the region if one was mentioned
- When outputting QUERY:, include ALL details: topic, region, year, limit
- When CURRENT MAP exists, PREFER MODIFY: over QUERY: unless user wants completely new locations

OUTPUT FORMAT:
- For conversation: Just respond naturally with specific confirmations using DATA PREVIEW numbers
- When user confirms and you're ready to show NEW data (no existing map): Start with "QUERY:"
  Examples:
  - "QUERY: GDP for African countries in 2022"
  - "QUERY: top 10 countries by GDP in 2022"
- When modifying existing map: Start with "MODIFY:" followed by action
  Examples:
  - "MODIFY: add_field population"
  - "MODIFY: remove_field co2"
  - "MODIFY: change_region South America"
  - "MODIFY: change_year 2021"

Be conversational. Use exact counts from DATA PREVIEW when available."""

    # Build message history from context
    messages = []
    if history_context:
        # Parse history into messages
        lines = history_context.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('User:'):
                messages.append(HumanMessage(content=line[5:].strip()))
            elif line.startswith('Assistant:'):
                messages.append(AIMessage(content=line[10:].strip()))

    # Create chat prompt with message history
    conversation_prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{query}")
    ])

    try:
        conversation_llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.4,
            max_tokens=200
        )

        conversation_chain = conversation_prompt | conversation_llm
        response = conversation_chain.invoke({
            "query": query,
            "history": messages
        })

        # ChatOpenAI returns a message object, extract content
        response_text = response.content.strip() if hasattr(response, 'content') else str(response).strip()
        logger.debug(f"Conversation LLM response: {response_text[:200]}...")

        # Parse the CHAT/QUERY format - handle multiline and malformed responses
        lines = response_text.split('\n')

        chat_content = None
        query_content = None
        modify_content = None

        for line in lines:
            line = line.strip()
            if line.startswith("QUERY:"):
                potential_query = line.replace("QUERY:", "").strip()
                # Filter out invalid queries like "None", empty, or very short
                if potential_query and potential_query.lower() not in ["none", "null", "n/a", ""] and len(potential_query) > 2:
                    query_content = potential_query
                    break  # Take the first valid QUERY
            elif line.startswith("MODIFY:"):
                potential_modify = line.replace("MODIFY:", "").strip()
                if potential_modify:
                    modify_content = potential_modify
                    break  # Take the first valid MODIFY
            elif line.startswith("CHAT:"):
                potential_chat = line.replace("CHAT:", "").strip()
                if potential_chat:
                    chat_content = potential_chat
                    # Don't break - keep looking for QUERY/MODIFY which take priority

        # When CURRENT MAP exists, MODIFY takes priority over QUERY
        map_state = get_map_state()
        has_map_data = len(map_state.get("features", [])) > 0

        if modify_content:
            # MODIFY always takes priority when present
            return {
                "intent": "modify_data",
                "response": f"Updating the map...",
                "modify_action": modify_content,
                "display_immediately": True
            }
        elif query_content:
            # If map has data, check if this query is for the same region/data
            if has_map_data:
                current_region = map_state.get("region", "").lower() if map_state.get("region") else ""
                current_fields = [f.lower() for f in map_state.get("data_fields", [])]
                query_lower = query_content.lower()

                # Check if query mentions a NEW topic we don't have
                new_topics = []
                topic_keywords = ["gdp", "population", "co2", "emission", "temperature", "energy"]
                for topic in topic_keywords:
                    if topic in query_lower and topic not in " ".join(current_fields):
                        new_topics.append(topic)

                # If asking for new topic on same region, convert to MODIFY: add_field
                if new_topics and current_region and current_region in query_lower:
                    modify_action = ", ".join([f"add_field {t}" for t in new_topics])
                    logger.debug(f"Converted QUERY to MODIFY: {modify_action}")
                    return {
                        "intent": "modify_data",
                        "response": f"Adding {', '.join(new_topics)} to the map...",
                        "modify_action": modify_action,
                        "display_immediately": True
                    }

            # Otherwise, proceed with QUERY as new data request
            return {
                "intent": "fetch_data",
                "response": f"Looking up {query_content}...",
                "data_query": query_content,
                "display_immediately": True
            }
        elif chat_content:
            return {
                "intent": "chat",
                "response": chat_content
            }
        else:
            # No valid prefix at line start - try to find CHAT: or QUERY: anywhere in response
            # Look for QUERY: anywhere (but not "QUERY: None")
            query_match = re.search(r'QUERY:\s*([^Q][^\n]{3,})', response_text)
            if query_match:
                potential_query = query_match.group(1).strip()
                if potential_query.lower() not in ["none", "null", "n/a"]:
                    return {
                        "intent": "fetch_data",
                        "response": f"Looking up {potential_query}...",
                        "data_query": potential_query,
                        "display_immediately": True
                    }

            # Look for CHAT: anywhere
            chat_match = re.search(r'CHAT:\s*(.+)', response_text)
            if chat_match:
                return {
                    "intent": "chat",
                    "response": chat_match.group(1).strip()
                }

            # Still nothing - clean up and use raw response
            clean_response = response_text
            for prefix in ["CHAT:", "QUERY:", "-> CHAT:", "-> QUERY:", "MODIFY:"]:
                clean_response = clean_response.replace(prefix, "").strip()

            # Trust the LLM response - return it as chat
            final_response = clean_response if clean_response and len(clean_response) > 10 else "I can help you explore geographic data. What topic interests you?"
            return {
                "intent": "chat",
                "response": final_response
            }

    except Exception as e:
        logger.error(f"Conversation LLM error: {e}")
        # On LLM error, return a helpful chat response
        return {
            "intent": "chat",
            "response": "I can help you explore geographic data like GDP, population, and CO2 emissions for countries and regions. What would you like to know?"
        }


async def handle_modify_request(modify_action: str, current_view: dict, session_id: str = None):
    """
    Handle requests to modify existing map data incrementally.

    Parse modify_action strings like:
    - "add_field population"
    - "remove_field co2"
    - "change_region Asia"
    - "change_year 2020"
    - "add_field cement_co2, add_field coal_co2"
    """
    try:
        map_state = get_map_state()

        if not map_state["features"]:
            return JSONResponse(content={
                "message": "No data currently displayed. Please start with a query like 'GDP for European countries in 2022'.",
                "geojson": {"type": "FeatureCollection", "features": []},
                "needsMoreInfo": True
            })

        # Parse the action(s) - may contain multiple comma-separated actions
        actions = [a.strip() for a in modify_action.split(",")]

        messages = []
        current_dataset = map_state["dataset"] or "owid-co2-data.csv"

        for action in actions:
            action_lower = action.lower()

            if action_lower.startswith("add_field"):
                field = action.replace("add_field", "").replace("add field", "").strip()
                if field:
                    # Map common names to actual column names
                    field_mapping = {
                        "population": "population",
                        "co2": "co2",
                        "emissions": "co2",
                        "gdp": "gdp",
                        "cement": "cement_co2",
                        "cement_co2": "cement_co2",
                        "cement co2": "cement_co2",
                        "coal": "coal_co2",
                        "coal_co2": "coal_co2",
                        "coal co2": "coal_co2",
                        "temperature": "temperature_change_from_co2"
                    }
                    actual_field = field_mapping.get(field.lower(), field)

                    result = build_incremental_response(
                        action="add_field",
                        field=actual_field,
                        dataset=current_dataset,
                        year=map_state["year"]
                    )
                    messages.append(f"Added {field}")
                    logger.debug(f"Added field '{actual_field}'")

            elif action_lower.startswith("remove_field") or action_lower.startswith("remove field"):
                field = action.replace("remove_field", "").replace("remove field", "").strip()
                if field:
                    result = build_incremental_response(action="remove_field", field=field)
                    messages.append(f"Removed {field}")
                    logger.debug(f"Removed field '{field}'")

            elif action_lower.startswith("change_region") or action_lower.startswith("change region"):
                region = action.replace("change_region", "").replace("change region", "").strip()
                if region:
                    result = build_incremental_response(
                        action="change_region",
                        region=region,
                        year=map_state["year"]
                    )
                    messages.append(f"Changed to {region}")
                    logger.debug(f"Changed region to '{region}'")

            elif action_lower.startswith("change_year") or action_lower.startswith("change year"):
                year_str = action.replace("change_year", "").replace("change year", "").strip()
                try:
                    year = int(year_str)
                    result = build_incremental_response(action="change_year", year=year)
                    messages.append(f"Changed to {year}")
                    logger.debug(f"Changed year to {year}")
                except ValueError:
                    messages.append(f"Invalid year: {year_str}")

        # Get final state
        final_state = get_map_state()
        feature_count = len(final_state["features"])
        fields_text = ", ".join(final_state["data_fields"]) if final_state["data_fields"] else "no data"

        summary = f"Updated: {', '.join(messages)}. Now showing {feature_count} countries with {fields_text}."

        # Log the modify action
        log_conversation(
            session_id=session_id,
            query=modify_action,
            response_text=summary,
            intent="modify_data",
            dataset_selected=current_dataset,
            results_count=feature_count,
            endpoint="chat"
        )

        return JSONResponse(content={
            "message": summary,
            "summary": summary,
            "geojson": {
                "type": "FeatureCollection",
                "features": final_state["features"]
            },
            "count": feature_count,
            "data_fields": final_state["data_fields"],
            "displayImmediately": True
        })

    except Exception as e:
        logger.error(f"Modify request error: {e}")
        traceback.print_exc()
        return JSONResponse(content={
            "message": f"Error updating map: {str(e)}",
            "geojson": {"type": "FeatureCollection", "features": []},
            "error": str(e)
        })
