"""
mapmover package - Runtime application logic for the county-map application.

This package provides:
- Geography and regional groupings (geography.py)
- Data loading and catalog management (data_loading.py)
- Geometry enrichment (geometry_enrichment.py)
- Geometry joining (geometry_joining.py)
- Geometry endpoint handlers (geometry_handlers.py)
- Order Taker LLM (order_taker.py)
- Order Executor (order_executor.py)
- Logging and analytics (logging_analytics.py)
- Utility functions (utils.py)
- Constants (constants.py)

Note: Build tools (geometry processing, catalog generation) are in the build/ folder.
"""

# Re-export key functions for convenience
from .constants import (
    state_abbreviations,
    UNIT_MULTIPLIERS,
    TOPIC_KEYWORDS,
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
    initialize_catalog,
    get_data_catalog,
    get_data_folder,
    get_catalog_path,
    load_catalog,
    load_source_metadata,
    get_source_by_topic,
    clear_metadata_cache,
    data_catalog,
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
    load_country_parquet,
    load_global_countries,
    clear_cache,
)

# Order Taker system
from .order_taker import interpret_request
from .order_executor import execute_order

__version__ = "2.0.0"
__all__ = [
    # Constants
    "state_abbreviations",
    "UNIT_MULTIPLIERS",
    "TOPIC_KEYWORDS",
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
    "initialize_catalog",
    "get_data_catalog",
    "get_data_folder",
    "get_catalog_path",
    "load_catalog",
    "load_source_metadata",
    "get_source_by_topic",
    "clear_metadata_cache",
    "data_catalog",
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
    "load_country_parquet",
    "load_global_countries",
    "clear_cache",
    # Order Taker
    "interpret_request",
    "execute_order",
]
