"""
Meta query detection and handling.
Handles queries about the data itself (what datasets, what columns, etc).
"""


def detect_meta_query(query: str) -> str:
    """
    Detect if the query is asking about the data/metadata itself rather than querying data.
    Returns the type of meta query or None if it's a regular data query.

    Meta query types:
    - 'datasets': What datasets/data do you have?
    - 'coverage': What countries/regions have data? Most data for which countries?
    - 'topics': What topics/subjects can I query?
    - 'years': What years/time periods are available?
    - 'columns': What columns/fields are in a dataset?
    - 'help': General help about the system
    """
    query_lower = query.lower()

    # Dataset availability questions
    dataset_patterns = [
        'what data', 'what datasets', 'which datasets', 'list datasets',
        'available data', 'show me data', 'what files', 'data sources',
        'what sources', 'what information do you have'
    ]
    if any(p in query_lower for p in dataset_patterns):
        return 'datasets'

    # Coverage questions (which countries, most data for)
    coverage_patterns = [
        'most data for', 'which countries', 'what countries', 'coverage',
        'which regions', 'what regions', 'data for which', 'have data for',
        'countries covered', 'geographic coverage', 'where do you have'
    ]
    if any(p in query_lower for p in coverage_patterns):
        return 'coverage'

    # Topic questions
    topic_patterns = [
        'what topics', 'which topics', 'what can i ask', 'what subjects',
        'what kind of data', 'types of data', 'categories', 'what can you tell'
    ]
    if any(p in query_lower for p in topic_patterns):
        return 'topics'

    # Year/time questions
    year_patterns = [
        'what years', 'which years', 'time period', 'date range',
        'how recent', 'latest data', 'oldest data', 'time coverage',
        'years available', 'from what year'
    ]
    if any(p in query_lower for p in year_patterns):
        return 'years'

    # Column questions
    column_patterns = [
        'what columns', 'which columns', 'what fields', 'which fields',
        'available columns', 'data fields', 'what metrics', 'what variables'
    ]
    if any(p in query_lower for p in column_patterns):
        return 'columns'

    # Help questions
    help_patterns = [
        'help', 'how do i', 'how to use', 'what can you do',
        'capabilities', 'instructions', 'guide'
    ]
    if any(p in query_lower for p in help_patterns):
        return 'help'

    return None


def handle_meta_query(meta_type: str, query: str, ultimate_metadata, data_catalog) -> dict:
    """
    Answer meta questions using ultimate_metadata and individual dataset metadata.
    Returns a response dict with 'answer' text and optional 'data' for display.
    """
    if meta_type == 'datasets':
        # List available datasets with descriptions
        datasets_info = []
        if ultimate_metadata and 'datasets' in ultimate_metadata:
            for filename, info in ultimate_metadata['datasets'].items():
                datasets_info.append({
                    'name': filename.replace('.csv', ''),
                    'description': info.get('description', 'No description'),
                    'rows': info.get('row_count', 0),
                    'geographic_level': info.get('geographic_level', 'unknown'),
                    'topics': info.get('topic_tags', [])
                })

        answer = f"I have access to {len(datasets_info)} datasets:\n\n"
        for ds in datasets_info:
            topics = ', '.join(ds['topics']) if ds['topics'] else 'general'
            answer += f"* **{ds['name']}** ({ds['geographic_level']} level, {ds['rows']:,} rows)\n"
            answer += f"  {ds['description']}\n"
            answer += f"  Topics: {topics}\n\n"

        return {'answer': answer, 'type': 'meta', 'data': datasets_info}

    elif meta_type == 'coverage':
        # Analyze which countries/regions have most data
        coverage = {}

        if ultimate_metadata and 'datasets' in ultimate_metadata:
            for filename, info in ultimate_metadata['datasets'].items():
                geo_level = info.get('geographic_level', 'unknown')
                row_count = info.get('row_count', 0)

                if geo_level == 'country':
                    # This dataset has country-level data
                    coverage[filename] = {
                        'level': geo_level,
                        'rows': row_count,
                        'description': info.get('description', '')
                    }

        # Find unique countries from metadata files
        country_data = {}
        for item in data_catalog:
            metadata = item.get('metadata', {})
            if metadata:
                unique_vals = metadata.get('unique_values', {})
                # Check for country_code or country_name unique values
                countries = unique_vals.get('country_code', []) or unique_vals.get('country_name', [])
                if countries:
                    country_data[item['filename']] = len(countries)

        answer = "**Geographic Coverage:**\n\n"
        answer += "**Country-level datasets:**\n"
        for fname, info in coverage.items():
            country_count = country_data.get(fname, 'unknown')
            answer += f"* **{fname.replace('.csv', '')}**: {info['rows']:,} rows, ~{country_count} countries\n"
            answer += f"  {info['description']}\n\n"

        # Most comprehensive dataset
        if country_data:
            best = max(country_data.items(), key=lambda x: x[1])
            answer += f"\n**Most comprehensive country coverage:** {best[0].replace('.csv', '')} with {best[1]} countries"

        return {'answer': answer, 'type': 'meta'}

    elif meta_type == 'topics':
        # List available topics
        topics = set()
        topic_datasets = {}

        if ultimate_metadata and 'datasets' in ultimate_metadata:
            for filename, info in ultimate_metadata['datasets'].items():
                for topic in info.get('topic_tags', []):
                    topics.add(topic)
                    if topic not in topic_datasets:
                        topic_datasets[topic] = []
                    topic_datasets[topic].append(filename.replace('.csv', ''))

        answer = "**Available Topics:**\n\n"
        for topic in sorted(topics):
            datasets = ', '.join(topic_datasets[topic])
            answer += f"* **{topic.title()}**: {datasets}\n"

        answer += "\n\nYou can ask questions like:\n"
        answer += "* 'Show countries with highest GDP'\n"
        answer += "* 'What is the CO2 emissions of China?'\n"
        answer += "* 'List US counties by population'\n"

        return {'answer': answer, 'type': 'meta'}

    elif meta_type == 'years':
        # Show time coverage for each dataset
        year_info = []

        for item in data_catalog:
            metadata = item.get('metadata', {})
            if metadata:
                data_year = metadata.get('data_year')

                if data_year:
                    if isinstance(data_year, dict):
                        # Time series data
                        year_info.append({
                            'dataset': item['filename'].replace('.csv', ''),
                            'type': 'time_series',
                            'start': data_year.get('start'),
                            'end': data_year.get('end'),
                            'latest': data_year.get('latest')
                        })
                    elif data_year != 'Unknown':
                        year_info.append({
                            'dataset': item['filename'].replace('.csv', ''),
                            'type': 'snapshot',
                            'year': data_year
                        })

        answer = "**Time Coverage:**\n\n"
        for yi in year_info:
            if yi['type'] == 'time_series':
                answer += f"* **{yi['dataset']}**: {yi['start']} - {yi['end']} (time series)\n"
            else:
                answer += f"* **{yi['dataset']}**: {yi['year']} (snapshot)\n"

        return {'answer': answer, 'type': 'meta'}

    elif meta_type == 'columns':
        # List queryable columns by dataset
        answer = "**Queryable Data Fields:**\n\n"

        for item in data_catalog[:5]:  # Limit to top 5 datasets
            metadata = item.get('metadata', {})
            if metadata:
                columns = metadata.get('columns', {})
                queryable = [col for col, info in columns.items()
                            if info.get('queryable', True) and info.get('role') == 'data']

                if queryable:
                    answer += f"**{item['filename'].replace('.csv', '')}:**\n"
                    answer += f"  {', '.join(queryable[:10])}"
                    if len(queryable) > 10:
                        answer += f" ... and {len(queryable) - 10} more"
                    answer += "\n\n"

        return {'answer': answer, 'type': 'meta'}

    elif meta_type == 'help':
        answer = """**How to Use This System:**

I can answer geographic data questions. Here are some examples:

**Country-level queries:**
* "Show me the top 10 countries by GDP"
* "What is China's CO2 emissions?"
* "Countries with population over 100 million"

**US-level queries:**
* "Show California counties"
* "What is the median age in Texas counties?"
* "Largest cities in New York"

**Meta questions (about the data):**
* "What datasets do you have?"
* "What years does the data cover?"
* "What topics can I ask about?"

**Tips:**
* I can filter by year: "GDP in 2020"
* I can sort and limit: "Top 5 countries by population"
* I can compare: "CO2 per capita in Europe"
"""
        return {'answer': answer, 'type': 'meta'}

    return {'answer': "I'm not sure how to answer that meta question.", 'type': 'meta'}
