"""
Base utilities for data converters.

This module provides shared functionality to reduce code duplication:
- constants.py: Country codes, water body codes, hazard scales
- geo_utils.py: Spatial join, geometry loading, loc_id generation
- parquet_utils.py: Standardized parquet saving, schema helpers
"""

from .constants import (
    USA_STATE_FIPS,
    USA_STATE_FIPS_REVERSE,
    CAN_PROVINCE_ABBR,
    CAN_PROVINCE_ABBR_REVERSE,
    AUS_STATE_ABBR,
    AUS_STATE_ABBR_REVERSE,
    WATER_BODY_CODES,
    TERRITORIAL_WATERS_DEG,
    HAZARD_CATEGORIES,
    SAFFIR_SIMPSON_SCALE,
    VEI_SCALE,
    DROUGHT_LEVELS,
)

from .geo_utils import (
    usa_fips_to_loc_id,
    can_cduid_to_loc_id,
    aus_lga_to_loc_id,
    load_geometry_parquet,
    get_water_body_loc_id,
    spatial_join_3pass,
    create_point_gdf,
)

from .parquet_utils import (
    save_parquet,
    events_schema,
    aggregates_schema,
    get_output_paths,
)

__all__ = [
    # Constants
    'USA_STATE_FIPS',
    'USA_STATE_FIPS_REVERSE',
    'CAN_PROVINCE_ABBR',
    'CAN_PROVINCE_ABBR_REVERSE',
    'AUS_STATE_ABBR',
    'AUS_STATE_ABBR_REVERSE',
    'WATER_BODY_CODES',
    'TERRITORIAL_WATERS_DEG',
    'HAZARD_CATEGORIES',
    'SAFFIR_SIMPSON_SCALE',
    'VEI_SCALE',
    'DROUGHT_LEVELS',

    # Geo utilities
    'usa_fips_to_loc_id',
    'can_cduid_to_loc_id',
    'aus_lga_to_loc_id',
    'load_geometry_parquet',
    'get_water_body_loc_id',
    'spatial_join_3pass',
    'create_point_gdf',

    # Parquet utilities
    'save_parquet',
    'events_schema',
    'aggregates_schema',
    'get_output_paths',
]
