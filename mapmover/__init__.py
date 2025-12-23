"""
mapmover package - Core application logic for the county-map application.

This package provides:
- Geography and regional groupings (geography.py)
- Data loading and catalog management (data_loading.py)
- Geometry enrichment (geometry_enrichment.py)
- Geometry joining (geometry_joining.py)
- Geometry endpoint handlers (geometry_handlers.py)
- Order Taker LLM (order_taker.py) - Phase 1B
- Order Executor (order_executor.py) - Phase 1B
- Metadata generator (metadata_generator.py)
- Catalog builder (catalog_builder.py)
- Logging and analytics (logging_analytics.py)
- Utility functions (utils.py)
- Constants (constants.py)
"""

# Re-export key functions for convenience
from .constants import (
    state_abbreviations,
    UNIT_MULTIPLIERS,
    GEOMETRY_ONLY_DATASETS,
    ESSENTIAL_COLUMNS,
    TOPIC_COLUMNS,
)

from .utils import (
    convert_unit,
    state_from_abbr,
    normalize,
    parse_year_value,
    clean_nans,
    apply_unit_multiplier,
)

from .geography import (
    load_conversions,
    get_conversions_data,
    get_countries_in_region,
    get_country_names_from_codes,
    get_limited_geometry_countries,
    get_fallback_coordinates,
    get_region_patterns,
    get_supported_regions_text,
    CONVERSIONS_DATA,
)

from .data_loading import (
    load_ultimate_metadata,
    get_primary_datasets,
    get_fallback_datasets,
    get_columns_for_query,
    load_csv_smart,
    rank_datasets,
    initialize_catalog,
    get_data_catalog,
    get_ultimate_metadata,
    find_fallback_dataset,
    data_catalog,
    ultimate_metadata,
)

from .logging_analytics import (
    log_missing_geometry,
    log_error_to_cloud,
    log_missing_region_to_cloud,
    logger,
)

from .geometry_enrichment import (
    get_geometry_lookup,
    get_country_coordinates,
    enrich_with_geometry,
    detect_missing_geometry,
    get_geometry_source,
    COUNTRY_NAME_ALIASES,
)

from .geometry_joining import (
    detect_join_key,
    auto_join_geometry,
)

from .geometry_handlers import (
    get_countries_geometry,
    get_location_children,
    get_location_places,
    get_location_info,
    load_country_depth,
    load_country_parquet,
    load_global_countries,
    clear_cache,
)

# Phase 1B: Order Taker system
from .order_taker import interpret_request
from .order_executor import execute_order

__version__ = "2.0.0"
__all__ = [
    # Constants
    "state_abbreviations",
    "UNIT_MULTIPLIERS",
    "GEOMETRY_ONLY_DATASETS",
    "ESSENTIAL_COLUMNS",
    "TOPIC_COLUMNS",
    # Utils
    "convert_unit",
    "state_from_abbr",
    "normalize",
    "parse_year_value",
    "clean_nans",
    "apply_unit_multiplier",
    # Geography
    "load_conversions",
    "get_conversions_data",
    "get_countries_in_region",
    "get_country_names_from_codes",
    "get_limited_geometry_countries",
    "get_fallback_coordinates",
    "get_region_patterns",
    "get_supported_regions_text",
    "CONVERSIONS_DATA",
    # Data loading
    "load_ultimate_metadata",
    "get_primary_datasets",
    "get_fallback_datasets",
    "get_columns_for_query",
    "load_csv_smart",
    "rank_datasets",
    "initialize_catalog",
    "get_data_catalog",
    "get_ultimate_metadata",
    "find_fallback_dataset",
    "data_catalog",
    "ultimate_metadata",
    # Logging
    "log_missing_geometry",
    "log_error_to_cloud",
    "log_missing_region_to_cloud",
    "logger",
    # Geometry
    "get_geometry_lookup",
    "enrich_with_geometry",
    "detect_missing_geometry",
    "get_geometry_source",
    "COUNTRY_NAME_ALIASES",
    # Geometry handlers
    "get_countries_geometry",
    "get_location_children",
    "get_location_places",
    "get_location_info",
    "load_country_depth",
    "load_country_parquet",
    "load_global_countries",
    "clear_cache",
    # Order Taker (Phase 1B)
    "interpret_request",
    "execute_order",
]
