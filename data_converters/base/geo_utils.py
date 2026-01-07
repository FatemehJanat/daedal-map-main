"""
Shared geospatial utilities for data converters.

Includes:
- Geometry loading from parquet
- 3-pass spatial join (point-in-polygon, nearest neighbor, water body)
- Water body assignment
- loc_id generation
"""
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, shape
from shapely import wkb
import json

from .constants import (
    USA_STATE_FIPS,
    CAN_PROVINCE_ABBR,
    AUS_STATE_ABBR,
    TERRITORIAL_WATERS_DEG,
)


# =============================================================================
# loc_id Generation
# =============================================================================

def usa_fips_to_loc_id(fips_code):
    """Convert 5-digit USA FIPS code to loc_id format.

    Args:
        fips_code: 5-digit FIPS code (str or int)

    Returns:
        loc_id string like 'USA-CA-06037' or None if invalid
    """
    fips_str = str(fips_code).zfill(5)
    state_fips = fips_str[:2]
    state_abbr = USA_STATE_FIPS.get(state_fips)

    if not state_abbr:
        return None

    return f"USA-{state_abbr}-{int(fips_str)}"


def can_cduid_to_loc_id(cduid, pruid=None):
    """Convert Canada Census Division UID to loc_id format.

    Args:
        cduid: 4-digit Census Division UID (first 2 = province)
        pruid: Optional province UID (derived from cduid if not provided)

    Returns:
        loc_id string like 'CAN-BC-5915'
    """
    cduid_str = str(cduid)
    if pruid is None:
        pruid = cduid_str[:2]

    abbr = CAN_PROVINCE_ABBR.get(str(pruid), pruid)
    return f"CAN-{abbr}-{cduid_str}"


def aus_lga_to_loc_id(lga_code, state_code):
    """Convert Australia LGA code to loc_id format.

    Args:
        lga_code: LGA code
        state_code: State code (1-9)

    Returns:
        loc_id string like 'AUS-NSW-12345'
    """
    abbr = AUS_STATE_ABBR.get(int(state_code), 'XX')
    return f"AUS-{abbr}-{lga_code}"


# =============================================================================
# Geometry Loading
# =============================================================================

def load_geometry_parquet(geometry_path, admin_level=2, geometry_format='wkb'):
    """Load geometry from parquet file.

    Args:
        geometry_path: Path to geometry.parquet file
        admin_level: Filter to this admin level (default 2 = county/division)
        geometry_format: 'wkb' (binary) or 'geojson' (dict/string)

    Returns:
        GeoDataFrame with geometry column
    """
    print(f"Loading geometry from {geometry_path}...")

    df = pd.read_parquet(geometry_path)

    # Filter by admin level if specified
    if admin_level is not None and 'admin_level' in df.columns:
        df = df[df['admin_level'] == admin_level].copy()

    # Parse geometry based on format
    if geometry_format == 'wkb':
        df['geometry'] = df['geometry'].apply(
            lambda g: wkb.loads(g) if g is not None else None
        )
    elif geometry_format == 'geojson':
        def parse_geojson(g):
            if g is None:
                return None
            if isinstance(g, str):
                return shape(json.loads(g))
            return shape(g)
        df['geometry'] = df['geometry'].apply(parse_geojson)

    # Drop rows with no geometry
    df = df[df['geometry'].notna()].copy()

    gdf = gpd.GeoDataFrame(df, geometry='geometry', crs="EPSG:4326")

    print(f"  Loaded {len(gdf)} features (admin_level={admin_level})")
    return gdf


# =============================================================================
# Water Body Assignment
# =============================================================================

def get_water_body_loc_id(lat, lon, region='global'):
    """Assign water body loc_id for offshore points.

    Uses ISO 3166-1 X-prefix codes for water bodies.

    Args:
        lat: Latitude
        lon: Longitude
        region: 'global', 'usa', 'canada', 'australia' for region-specific logic

    Returns:
        Water body code like 'XOP' (Pacific), 'XOA' (Atlantic), etc.
    """
    # Arctic Ocean (north of Arctic Circle)
    if lat > 66.5:
        return "XON"  # Arctic Ocean

    # Canada-specific water bodies
    if region in ('canada', 'global'):
        # Hudson Bay
        if -95 < lon < -75 and 50 < lat < 70:
            return "XSH"

        # Labrador Sea
        if -65 < lon < -45 and 50 < lat < 65:
            return "XSL"

        # Beaufort Sea
        if -145 < lon < -110 and lat > 65:
            return "XSE"

        # Gulf of St. Lawrence
        if -70 < lon < -55 and 45 < lat < 52:
            return "XSG"

    # USA-specific water bodies
    if region in ('usa', 'global'):
        # Gulf of Mexico
        if -98 < lon < -80 and 18 < lat < 31:
            return "XSG"

        # Caribbean Sea
        if -90 < lon < -60 and 8 < lat < 22:
            return "XSC"

        # Bering Sea
        if lon < -160 and lat > 50:
            return "XSB"

    # Australia-specific water bodies
    if region in ('australia', 'global'):
        # Tasman Sea
        if 145 < lon < 180 and -50 < lat < -30:
            return "XST"

        # Coral Sea
        if 145 < lon < 165 and -25 < lat < -10:
            return "XSR"

        # Arafura Sea
        if 130 < lon < 145 and -15 < lat < -5:
            return "XSA"

    # Major oceans
    # Pacific Ocean (roughly west of Americas, east of Asia/Australia)
    if lon < -100 or lon > 150:
        return "XOP"

    # Atlantic Ocean (between Americas and Europe/Africa)
    if -100 < lon < 0:
        if lat > 0:
            return "XOA"  # North Atlantic
        else:
            return "XOA"  # South Atlantic

    # Indian Ocean
    if 20 < lon < 150 and lat < 30:
        return "XOI"

    # Default
    return "XOO"  # Unknown Ocean


# =============================================================================
# 3-Pass Spatial Join
# =============================================================================

def spatial_join_3pass(
    points_gdf,
    polygons_gdf,
    loc_id_col='loc_id',
    territorial_waters_deg=TERRITORIAL_WATERS_DEG,
    water_body_region='global',
    verbose=True
):
    """Perform 3-pass spatial join to assign points to administrative units.

    Pass 1: Strict point-in-polygon matching
    Pass 2: Nearest neighbor within territorial waters
    Pass 3: Assign water body codes for remaining offshore points

    Args:
        points_gdf: GeoDataFrame with point geometries
        polygons_gdf: GeoDataFrame with polygon geometries and loc_id column
        loc_id_col: Name of loc_id column in polygons_gdf
        territorial_waters_deg: Distance threshold for nearest neighbor (default 0.2 deg ~12nm)
        water_body_region: Region for water body assignment ('global', 'usa', 'canada', 'australia')
        verbose: Print progress messages

    Returns:
        GeoDataFrame with loc_id column added
    """
    if verbose:
        print("  Performing 3-pass spatial join...")

    # Make a copy to avoid modifying original
    result_gdf = points_gdf.copy()

    # === PASS 1: Strict "within" spatial join ===
    if verbose:
        print("    Pass 1: Point-in-polygon matching...")

    result_gdf = gpd.sjoin(
        result_gdf,
        polygons_gdf[[loc_id_col, 'geometry']],
        how='left',
        predicate='within'
    )

    pass1_matched = result_gdf[loc_id_col].notna().sum()
    if verbose:
        print(f"      Matched: {pass1_matched:,}")

    # === PASS 2: Nearest neighbor for unmatched within territorial waters ===
    unmatched_mask = result_gdf[loc_id_col].isna()
    if unmatched_mask.any():
        if verbose:
            print(f"    Pass 2: Nearest neighbor for {unmatched_mask.sum():,} unmatched...")

        unmatched_indices = result_gdf[unmatched_mask].index.tolist()
        unmatched_gdf = result_gdf.loc[unmatched_indices].copy()
        unmatched_gdf = unmatched_gdf.drop(columns=[loc_id_col, 'index_right'], errors='ignore')

        # Find nearest polygon
        nearest = gpd.sjoin_nearest(
            unmatched_gdf,
            polygons_gdf[[loc_id_col, 'geometry']],
            how='left',
            distance_col='dist_to_polygon'
        )

        # Assign loc_id for points within territorial waters
        within_territorial = nearest['dist_to_polygon'] <= territorial_waters_deg
        pass2_matched = within_territorial.sum()

        # Update using dictionary to avoid index issues
        updates = nearest[within_territorial][[loc_id_col]].to_dict()[loc_id_col]
        for orig_idx, loc_id_val in updates.items():
            result_gdf.at[orig_idx, loc_id_col] = loc_id_val

        if verbose:
            print(f"      Matched (within territorial waters): {pass2_matched:,}")

    # === PASS 3: Assign water body codes for offshore points ===
    still_unmatched_mask = result_gdf[loc_id_col].isna()
    if still_unmatched_mask.any():
        if verbose:
            print(f"    Pass 3: Assigning water body codes for {still_unmatched_mask.sum():,} offshore...")

        # Need lat/lon columns - try common names
        lat_col = None
        lon_col = None
        for lat_name in ['latitude', 'lat', 'LAT', 'Latitude']:
            if lat_name in result_gdf.columns:
                lat_col = lat_name
                break
        for lon_name in ['longitude', 'lon', 'LON', 'Longitude', 'long']:
            if lon_name in result_gdf.columns:
                lon_col = lon_name
                break

        if lat_col and lon_col:
            result_gdf.loc[still_unmatched_mask, loc_id_col] = \
                result_gdf.loc[still_unmatched_mask].apply(
                    lambda row: get_water_body_loc_id(row[lat_col], row[lon_col], water_body_region),
                    axis=1
                )
        else:
            # Fall back to geometry centroid
            result_gdf.loc[still_unmatched_mask, loc_id_col] = \
                result_gdf.loc[still_unmatched_mask].apply(
                    lambda row: get_water_body_loc_id(
                        row.geometry.y if row.geometry else 0,
                        row.geometry.x if row.geometry else 0,
                        water_body_region
                    ),
                    axis=1
                )

    # Print summary
    if verbose:
        land_match = result_gdf[loc_id_col].str.match(r'^(USA|CAN|AUS|[A-Z]{3})-', na=False).sum()
        water_match = result_gdf[loc_id_col].str.startswith('X', na=False).sum()
        total = len(result_gdf)
        print(f"    Summary: {land_match:,} land ({land_match/total*100:.1f}%), "
              f"{water_match:,} water ({water_match/total*100:.1f}%)")

    # Clean up join artifacts
    result_gdf = result_gdf.drop(columns=['index_right'], errors='ignore')

    return result_gdf


# =============================================================================
# Point Creation
# =============================================================================

def create_point_gdf(df, lat_col='latitude', lon_col='longitude', crs="EPSG:4326"):
    """Create GeoDataFrame with point geometries from lat/lon columns.

    Args:
        df: DataFrame with lat/lon columns
        lat_col: Name of latitude column
        lon_col: Name of longitude column
        crs: Coordinate reference system (default WGS84)

    Returns:
        GeoDataFrame with point geometry
    """
    geometry = [Point(xy) for xy in zip(df[lon_col], df[lat_col])]
    return gpd.GeoDataFrame(df, geometry=geometry, crs=crs)
