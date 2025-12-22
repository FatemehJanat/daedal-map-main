"""
Data loading, catalog management, and metadata functions.
Handles loading CSV files, managing the data catalog, and metadata lookups.
"""

import os
import json
import pandas as pd
from pathlib import Path

from .constants import GEOMETRY_ONLY_DATASETS, ESSENTIAL_COLUMNS, TOPIC_COLUMNS

# Base directory for file paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Global data catalog and ultimate metadata
data_catalog = []
ultimate_metadata = {}


def detect_delimiter(filepath):
    """Detect the delimiter used in a CSV file."""
    with open(filepath, newline='', encoding='utf-8') as f:
        first_line = f.readline()
        candidates = [',', ';', '\t', '|', ':']
        counts = {d: first_line.count(d) for d in candidates}
        return max(counts, key=counts.get)


def load_metadata(csv_filename, folder="data_pipeline/data_cleaned", metadata_folder="data_pipeline/metadata"):
    """Load metadata JSON file if it exists for a given CSV file."""
    base_name = os.path.splitext(csv_filename)[0]
    metadata_path = os.path.join(metadata_folder, f"{base_name}_metadata.json")

    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load metadata from {metadata_path}: {e}")
            return None
    return None


def checkdatabases():
    """Scan data directory for CSV files and build file info list."""
    fileinfo = []
    folder = "data_pipeline/data_cleaned"

    if not os.path.exists(folder):
        print(f"Warning: Data folder not found at {folder}")
        return []

    files = os.listdir(folder)
    csv_files = [f for f in files if f.lower().endswith('.csv')]

    for filename in csv_files:
        filepath = os.path.join(folder, filename)
        try:
            delimiter = detect_delimiter(filepath)
            df = pd.read_csv(filepath, delimiter=delimiter, nrows=0)

            # Load metadata if available
            metadata = load_metadata(filename, folder)

            fileinfo.append({
                "path": filepath,
                "delimiter": delimiter,
                "headers": df.columns.tolist(),
                "metadata": metadata
            })
        except Exception as e:
            print(f"Failed to process {filepath}: {e.__class__.__name__}: {e}")

    return fileinfo


def load_ultimate_metadata():
    """Load ultimate metadata from JSON file if it exists."""
    metadata_path = BASE_DIR / "data_pipeline" / "metadata" / "ultimate_metadata.json"
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load ultimate_metadata.json: {e}")
    return {}


def get_primary_datasets():
    """
    Get primary dataset mappings from ultimate_metadata.
    Falls back to hardcoded defaults if ultimate_metadata not available.
    """
    global ultimate_metadata

    # Default mappings (fallback if ultimate_metadata not loaded)
    defaults = {
        'gdp': 'owid-co2-data.csv',
        'co2': 'owid-co2-data.csv',
        'emissions': 'owid-co2-data.csv',
        'climate': 'owid-co2-data.csv',
        'energy': 'owid-co2-data.csv',
        'country': 'owid-co2-data.csv',
        'demographics': 'cc-est2024-agesex-all.csv',
        'age': 'cc-est2024-agesex-all.csv',
        'census': 'cc-est2024-agesex-all.csv',
    }

    # If ultimate_metadata has primary_sources, use them to build mappings
    if ultimate_metadata and 'primary_sources' in ultimate_metadata:
        primary_sources = ultimate_metadata['primary_sources']
        result = defaults.copy()

        # Map primary sources to topics
        for topic, filename in primary_sources.items():
            if filename:  # Skip null entries
                result[topic] = filename
                # Add related topic mappings
                if topic == 'gdp':
                    result['economics'] = filename
                elif topic == 'co2':
                    result['emissions'] = filename
                    result['climate'] = filename
                    result['carbon'] = filename
                elif topic == 'population':
                    result['people'] = filename
                elif topic == 'demographics':
                    result['age'] = filename
                    result['census'] = filename
                elif topic == 'health':
                    result['medical'] = filename
                    result['disease'] = filename

        return result

    return defaults


def get_fallback_datasets():
    """
    Get fallback dataset configurations from ultimate_metadata.
    Falls back to hardcoded defaults if ultimate_metadata not available.
    """
    global ultimate_metadata

    # Default fallback configurations
    defaults = {
        'Populated Places.csv': {
            'topics': ['population', 'cities', 'places'],
            'geographic_level': 'city',
            'caveats': 'Population data may be outdated or have quality issues',
        },
        'Countries.csv': {
            'topics': ['country', 'geography'],
            'geographic_level': 'country',
            'caveats': 'Snapshot data only, not time-series',
        },
        'usplaces.csv': {
            'topics': ['area', 'land', 'water', 'us places', 'cities', 'towns'],
            'geographic_level': 'place',
            'caveats': 'US only, limited to area measurements',
        },
    }

    # If ultimate_metadata has fallback_sources, merge with defaults
    if ultimate_metadata and 'fallback_sources' in ultimate_metadata:
        fallback_sources = ultimate_metadata['fallback_sources']
        for topic, filename in fallback_sources.items():
            if filename and filename not in defaults:
                # Add new fallback from ultimate_metadata
                defaults[filename] = {
                    'topics': [topic],
                    'geographic_level': 'unknown',
                    'caveats': 'Alternative data source',
                }

    return defaults


def get_columns_for_query(all_columns: list, query: str, metadata: dict = None) -> list:
    """
    Determine which columns to load based on the query.
    Returns a list of column names to load (subset of all_columns).

    Strategy:
    1. Always include essential columns (identifiers, geography, time)
    2. Include topic-specific columns based on query keywords
    3. If no specific topic detected, include common data columns
    """
    query_lower = query.lower()
    columns_to_load = set()

    # Always include essential columns that exist in this dataset
    for col in all_columns:
        col_lower = col.lower()
        if col_lower in ESSENTIAL_COLUMNS or any(ess in col_lower for ess in ['name', 'code', 'year']):
            columns_to_load.add(col)

    # Detect topics in query and add relevant columns
    topics_found = []
    for topic, topic_cols in TOPIC_COLUMNS.items():
        if topic in query_lower:
            topics_found.append(topic)
            for col in all_columns:
                col_lower = col.lower()
                if any(tc in col_lower for tc in topic_cols):
                    columns_to_load.add(col)

    # If no specific topics found, include columns mentioned in metadata keywords
    if not topics_found and metadata:
        keywords = metadata.get('keywords', [])
        for col in all_columns:
            col_lower = col.lower()
            # Include if column matches a keyword from metadata
            if any(kw in col_lower for kw in keywords[:20]):
                columns_to_load.add(col)

    # If still very few columns, fall back to loading more
    # (some queries might need columns we didn't anticipate)
    if len(columns_to_load) < 5:
        # Add first 20 columns as fallback
        for col in all_columns[:20]:
            columns_to_load.add(col)

    return list(columns_to_load)


def load_csv_smart(filepath: str, delimiter: str, query: str = "", metadata: dict = None) -> pd.DataFrame:
    """
    Load a CSV with only the columns needed for the query.
    Significantly reduces memory usage for large datasets.

    For owid-co2-data.csv: 79 cols -> ~10-15 cols = ~85% memory reduction
    """
    try:
        # First, read just the header to get column names
        header_df = pd.read_csv(filepath, delimiter=delimiter, nrows=0)
        all_columns = list(header_df.columns)

        # Determine which columns to load
        if query:
            columns_to_load = get_columns_for_query(all_columns, query, metadata)
        else:
            # No query context - load all columns
            columns_to_load = all_columns

        # Load only selected columns
        df = pd.read_csv(filepath, delimiter=delimiter, usecols=columns_to_load, dtype=str)

        return df

    except Exception as e:
        # Fallback to loading all columns if smart loading fails
        print(f"Smart loading failed, falling back to full load: {e}")
        return pd.read_csv(filepath, delimiter=delimiter, dtype=str)


def rank_datasets(catalog):
    """
    Rank and filter datasets by quality and comprehensiveness.
    Returns catalog sorted by priority (best datasets first).
    """
    ranked = []

    for item in catalog:
        filename = item.get('filename', '')
        metadata = item.get('metadata', {})
        row_count = metadata.get('row_count', 0) if metadata else 0
        topic_tags = metadata.get('topic_tags', []) if metadata else []

        # Skip geometry-only datasets from being primary data sources
        if filename in GEOMETRY_ONLY_DATASETS:
            item['is_geometry_only'] = True
            item['priority_score'] = -1  # Low priority for data queries
        else:
            item['is_geometry_only'] = False

            # Calculate priority score based on:
            # 1. Row count (more data = more comprehensive)
            # 2. Number of topic tags (more specific = better)
            # 3. Is it a primary dataset for any topic?
            score = 0

            # Row count scoring (log scale to avoid huge datasets dominating)
            if row_count > 50000:
                score += 100
            elif row_count > 10000:
                score += 75
            elif row_count > 1000:
                score += 50
            else:
                score += 10

            # Topic specificity bonus
            if topic_tags and topic_tags != ['general']:
                score += len(topic_tags) * 10

            # Primary dataset bonus
            keywords = metadata.get('keywords', []) if metadata else []
            primary_datasets = get_primary_datasets()
            for kw in keywords[:5]:  # Check top 5 keywords
                if kw in primary_datasets and primary_datasets[kw] == filename:
                    score += 50  # Big bonus for being the primary source

            item['priority_score'] = score

        ranked.append(item)

    # Sort by priority score (highest first), but keep geometry datasets at end
    ranked.sort(key=lambda x: x.get('priority_score', 0), reverse=True)

    return ranked


def initialize_catalog():
    """Initialize the data catalog by scanning CSV files."""
    global data_catalog, ultimate_metadata

    # Load ultimate metadata first (for primary/fallback dataset configuration)
    ultimate_metadata = load_ultimate_metadata()
    if ultimate_metadata:
        print(f"Loaded ultimate_metadata.json (version {ultimate_metadata.get('version', 'unknown')})")
        primary_sources = ultimate_metadata.get('primary_sources', {})
        print(f"  Primary sources: {', '.join(f'{k}={v}' for k, v in primary_sources.items() if v)}")
    else:
        print("Warning: ultimate_metadata.json not found, using default configurations")

    # Build data catalog by scanning all CSVs in data_pipeline/data_cleaned/ folder
    try:
        fileinfo = checkdatabases()
        data_catalog = []

        for file in fileinfo:
            # Get sample rows to help LLM understand the data
            try:
                df_sample = pd.read_csv(file["path"], delimiter=file["delimiter"], nrows=3)
                sample_rows = df_sample.to_dict('records')
            except:
                sample_rows = []

            data_catalog.append({
                "filename": os.path.basename(file["path"]),
                "path": file["path"],
                "delimiter": file["delimiter"],
                "headers": file["headers"],
                "sample_rows": sample_rows,
                "metadata": file.get("metadata")  # Include metadata if available
            })

        # Rank and sort datasets by quality/comprehensiveness
        data_catalog = rank_datasets(data_catalog)

        print(f"Data catalog initialized with {len(data_catalog)} files (ranked by priority):")
        for item in data_catalog:
            score = item.get('priority_score', 0)
            geo_only = " [GEOMETRY ONLY]" if item.get('is_geometry_only') else ""
            print(f"  - {item['filename']}: {len(item['headers'])} columns, score={score}{geo_only}")

    except Exception as e:
        print(f"Failed to build data catalog: {e}")


def get_data_catalog():
    """Get the current data catalog."""
    return data_catalog


def get_ultimate_metadata():
    """Get the ultimate metadata."""
    return ultimate_metadata


def find_fallback_dataset(query_topic: str, geographic_level: str = None):
    """
    Find a fallback dataset that can serve as backup for a given topic.
    Returns tuple of (catalog_item, fallback_info) or (None, None) if no fallback available.
    """
    global data_catalog

    query_topic_lower = query_topic.lower() if query_topic else ""

    for filename, fallback_info in get_fallback_datasets().items():
        # Check if query topic matches any of the fallback's topics
        topics = fallback_info.get('topics', [])
        if any(topic in query_topic_lower for topic in topics):
            # If geographic level specified, check it matches
            if geographic_level and fallback_info.get('geographic_level') != geographic_level:
                continue

            # Find the catalog item for this fallback
            for item in data_catalog:
                if item['filename'] == filename:
                    return item, fallback_info

    return None, None
