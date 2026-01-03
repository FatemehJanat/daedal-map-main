"""
Order Executor - executes confirmed orders against parquet data.
No LLM calls - direct data operations.

Implements the "Empty Box" model from CHAT_REDESIGN.md:
1. Expand regions to loc_ids
2. Create empty boxes for each location
3. Process each order item independently (may be from different sources)
4. Fill boxes with values from each source
5. Join with geometry
6. Return GeoJSON with all filled properties
"""

import pandas as pd
import json
from pathlib import Path
from typing import Optional

from .geometry_handlers import (
    load_global_countries,
    load_country_parquet,
    df_to_geojson,
)

DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/data")
CONVERSIONS_PATH = Path(__file__).parent / "conversions.json"
REFERENCE_DIR = Path(__file__).parent / "reference"

# Cache conversions to avoid repeated file reads
_conversions_cache = None
_iso_codes_cache = None
_usa_admin_cache = None


def _load_conversions() -> dict:
    """Load conversions.json with caching."""
    global _conversions_cache
    if _conversions_cache is None:
        with open(CONVERSIONS_PATH, encoding='utf-8') as f:
            _conversions_cache = json.load(f)
    return _conversions_cache


def _load_iso_codes() -> dict:
    """Load reference/iso_codes.json with caching."""
    global _iso_codes_cache
    if _iso_codes_cache is None:
        iso_path = REFERENCE_DIR / "iso_codes.json"
        if iso_path.exists():
            with open(iso_path, encoding='utf-8') as f:
                _iso_codes_cache = json.load(f)
        else:
            _iso_codes_cache = {}
    return _iso_codes_cache


def _load_usa_admin() -> dict:
    """Load reference/usa_admin.json with caching."""
    global _usa_admin_cache
    if _usa_admin_cache is None:
        usa_path = REFERENCE_DIR / "usa_admin.json"
        if usa_path.exists():
            with open(usa_path, encoding='utf-8') as f:
                _usa_admin_cache = json.load(f)
        else:
            _usa_admin_cache = {}
    return _usa_admin_cache


def load_source_data(source_id: str) -> tuple:
    """
    Load parquet and metadata for a source.

    Returns:
        tuple: (DataFrame, metadata dict)
    """
    source_dir = DATA_DIR / source_id

    # Find parquet file - prefer all_countries.parquet or USA.parquet
    parquet_files = list(source_dir.glob("*.parquet"))
    if not parquet_files:
        raise ValueError(f"No parquet file found for {source_id}")

    # Prefer specific files over generic names
    parquet_path = parquet_files[0]
    for name in ["all_countries.parquet", "USA.parquet"]:
        candidate = source_dir / name
        if candidate.exists():
            parquet_path = candidate
            break

    df = pd.read_parquet(parquet_path)

    # Load metadata
    meta_path = source_dir / "metadata.json"
    with open(meta_path, encoding='utf-8') as f:
        metadata = json.load(f)

    return df, metadata


def expand_region(region: str) -> set:
    """
    Expand a region name to a set of country codes (ISO3).

    Supports:
    - Region aliases (e.g., "europe" -> WHO_European_Region countries)
    - Direct grouping names (e.g., "European_Union")
    - Single country names (returns that country code)
    - "global" or null -> empty set (means no filtering)

    Returns:
        set: Country codes (ISO3), or empty set for global/all
    """
    if not region or region.lower() in ("global", "all", "world"):
        return set()

    conversions = _load_conversions()
    region_lower = region.lower()

    # Check region_aliases first (maps friendly names to grouping keys)
    region_aliases = conversions.get("region_aliases", {})
    for alias, grouping_key in region_aliases.items():
        if alias.lower() == region_lower:
            grouping = conversions.get("regional_groupings", {}).get(grouping_key, {})
            return set(grouping.get("countries", []))

    # Check direct grouping names
    regional_groupings = conversions.get("regional_groupings", {})
    for key, grouping in regional_groupings.items():
        if key.lower() == region_lower or key.lower().replace("_", " ") == region_lower:
            return set(grouping.get("countries", []))

    # Check if it's a country name -> return its ISO3 code
    iso_data = _load_iso_codes()
    iso3_to_name = iso_data.get("iso3_to_name", {})
    for code, name in iso3_to_name.items():
        if name.lower() == region_lower:
            return {code}

    # Check if it's already an ISO3 code
    if region.upper() in iso3_to_name:
        return {region.upper()}

    # Check US state abbreviations for state-level queries
    usa_admin = _load_usa_admin()
    state_abbrevs = usa_admin.get("state_abbreviations", {})
    for abbrev, name in state_abbrevs.items():
        if name.lower() == region_lower or abbrev.lower() == region_lower:
            # Return special marker for US state filtering
            return {f"USA-{abbrev}"}

    return set()


def find_metric_column(df: pd.DataFrame, metric: str) -> Optional[str]:
    """
    Find matching column name for a metric (fuzzy match).

    Returns:
        Column name or None if not found
    """
    metric_lower = metric.lower().replace("_", " ").replace("-", " ")
    metric_words = set(metric_lower.split())

    # Exact match first (normalized)
    for col in df.columns:
        col_norm = col.lower().replace("_", " ").replace("-", " ")
        if col_norm == metric_lower:
            return col

    # Metric contained in column name
    for col in df.columns:
        col_norm = col.lower().replace("_", " ").replace("-", " ")
        if metric_lower in col_norm:
            return col

    # Column name contained in metric (reverse)
    for col in df.columns:
        if col in ("loc_id", "year"):
            continue
        col_norm = col.lower().replace("_", " ").replace("-", " ")
        if col_norm in metric_lower:
            return col

    # Word overlap - at least 2 words match
    if len(metric_words) >= 2:
        for col in df.columns:
            if col in ("loc_id", "year"):
                continue
            col_words = set(col.lower().replace("_", " ").replace("-", " ").split())
            overlap = metric_words & col_words
            if len(overlap) >= 2:
                return col

    # Single significant word match (last resort)
    significant_words = metric_words - {"of", "the", "a", "an", "for", "in", "on", "to"}
    for col in df.columns:
        if col in ("loc_id", "year"):
            continue
        col_words = set(col.lower().replace("_", " ").replace("-", " ").split())
        if significant_words & col_words:
            return col

    return None


def execute_order(order: dict) -> dict:
    """
    Execute a confirmed order and return GeoJSON response.

    Implements the "Empty Box" model:
    1. Expand all regions to loc_ids
    2. Create empty boxes for each target location
    3. Process each item, fill boxes with values
    4. Join with geometry
    5. Build GeoJSON

    Supports multi-year mode when year_start/year_end provided:
    - Returns base geometry + year_data dict for efficient time slider

    Args:
        order: {items: [{source_id, metric, region, year, year_start, year_end, sort}, ...], summary: str}

    Returns:
        Single year: {type, geojson, summary, count, sources}
        Multi-year: {type, geojson, year_data, year_range, multi_year, summary, count, sources}
    """
    items = order.get("items", [])
    summary = order.get("summary", "")

    if not items:
        return {
            "type": "error",
            "message": "No items in order",
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0
        }

    # Check if any item uses year range (multi-year mode)
    multi_year_mode = any(
        item.get("year_start") and item.get("year_end")
        for item in items
    )

    # Step 1: Determine all target loc_ids and collect metadata
    target_countries = set()
    geo_levels = set()
    sources_used = {}

    for item in items:
        region = item.get("region")
        countries = expand_region(region)
        if countries:
            target_countries.update(countries)

        # Track sources
        source_id = item.get("source_id")
        if source_id and source_id not in sources_used:
            try:
                _, metadata = load_source_data(source_id)
                sources_used[source_id] = metadata
                geo_levels.add(metadata.get("geographic_level", "country"))
            except Exception:
                pass

    # For multi-year: year_data[year][loc_id] = {metric: value}
    # For single-year: boxes[loc_id] = {metric: value}
    year_data = {} if multi_year_mode else None
    boxes = {} if not multi_year_mode else None
    all_years = set()
    metric_key = None  # Track the metric label for frontend
    requested_year_start = None  # Track requested range for comparison
    requested_year_end = None

    # Step 3: Process each order item
    for item in items:
        source_id = item.get("source_id")
        metric = item.get("metric")
        region = item.get("region")
        year = item.get("year")
        year_start = item.get("year_start")
        year_end = item.get("year_end")
        sort_spec = item.get("sort")

        # Track requested range for comparison with actual data
        if year_start and year_end:
            requested_year_start = year_start
            requested_year_end = year_end

        if not source_id:
            continue

        try:
            df, metadata = load_source_data(source_id)
        except Exception as e:
            print(f"Error loading {source_id}: {e}")
            continue

        # Find the metric column first (needed for smart year filtering)
        if metric:
            metric_col = find_metric_column(df, metric)
        else:
            numeric_cols = df.select_dtypes(include=['float64', 'int64', 'Float64', 'Int64']).columns
            metric_col = numeric_cols[0] if len(numeric_cols) > 0 else None

        # Store metric label for frontend
        if metric_col and not metric_key:
            metric_key = item.get("metric_label", metric_col)

        # Filter by year (different logic for single vs range)
        if year_start and year_end and "year" in df.columns:
            # Multi-year range mode
            df = df[(df["year"] >= year_start) & (df["year"] <= year_end)]
        elif year and "year" in df.columns:
            # Single year mode
            df = df[df["year"] == year]
        elif "year" in df.columns:
            # Use latest year that has data for this metric
            if metric_col and metric_col in df.columns:
                years_with_data = df[df[metric_col].notna()]["year"].unique()
                if len(years_with_data) > 0:
                    df = df[df["year"] == max(years_with_data)]
                else:
                    df = df[df["year"] == df["year"].max()]
            else:
                df = df[df["year"] == df["year"].max()]

        # Filter by region
        region_codes = expand_region(region)
        if region_codes and "loc_id" in df.columns:
            # Check for US state filtering (loc_ids starting with USA-)
            us_state_prefixes = [c for c in region_codes if c.startswith("USA-")]
            country_codes = [c for c in region_codes if not c.startswith("USA-")]

            if us_state_prefixes:
                # Filter to US locations matching state prefix
                mask = df["loc_id"].str.startswith(tuple(us_state_prefixes))
                df = df[mask]
            elif country_codes:
                # Filter to country-level or sub-national within those countries
                df["_country_code"] = df["loc_id"].str.split("-").str[0]
                df = df[df["_country_code"].isin(country_codes)]
                df = df.drop(columns=["_country_code"])

        # Apply sort/limit if specified (only for single-year mode)
        if sort_spec and not multi_year_mode:
            sort_col = sort_spec.get("by")
            if sort_col:
                matched_col = find_metric_column(df, sort_col)
                if matched_col:
                    ascending = sort_spec.get("order", "desc") == "asc"
                    df = df.sort_values(matched_col, ascending=ascending, na_position='last')
                    if sort_spec.get("limit"):
                        df = df.head(sort_spec["limit"])

        # metric_col already found above for year filtering
        if not metric_col:
            continue

        # Fill data structures
        label = item.get("metric_label", metric_col)

        for _, row in df.iterrows():
            loc_id = row.get("loc_id")
            if not loc_id:
                continue

            val = row.get(metric_col)
            if pd.notna(val):
                if hasattr(val, 'item'):
                    val = val.item()

                if multi_year_mode:
                    # Multi-year: organize by year -> loc_id
                    row_year = int(row.get("year")) if "year" in df.columns else 0
                    all_years.add(row_year)

                    if row_year not in year_data:
                        year_data[row_year] = {}
                    if loc_id not in year_data[row_year]:
                        year_data[row_year][loc_id] = {}

                    year_data[row_year][loc_id][label] = val
                else:
                    # Single year: organize by loc_id
                    if loc_id not in boxes:
                        boxes[loc_id] = {"year": row.get("year")} if "year" in df.columns else {}

                    boxes[loc_id][label] = val

    # Step 4: Join with geometry
    # Determine geographic level from sources
    primary_level = "country" if "country" in geo_levels else list(geo_levels)[0] if geo_levels else "country"

    if primary_level == "country":
        geometry_df = load_global_countries()
    else:
        # Load geometry for all relevant countries
        iso3_codes = set()
        loc_ids_to_check = boxes.keys() if boxes else set()
        if year_data:
            for year_locs in year_data.values():
                loc_ids_to_check = loc_ids_to_check | set(year_locs.keys())

        for loc_id in loc_ids_to_check:
            iso3 = loc_id.split("-")[0] if "-" in loc_id else loc_id
            iso3_codes.add(iso3)

        geometry_rows = []
        for iso3 in iso3_codes:
            country_geom = load_country_parquet(iso3)
            if country_geom is not None:
                geometry_rows.append(country_geom[["loc_id", "name", "geometry"]])

        geometry_df = pd.concat(geometry_rows, ignore_index=True) if geometry_rows else None

    # Step 5: Build GeoJSON features
    features = []

    if geometry_df is not None:
        geom_lookup = geometry_df.set_index("loc_id")[["name", "geometry"]].to_dict("index")

        if multi_year_mode:
            # Multi-year: build base geometry features (no year-specific data)
            # Collect all loc_ids across all years
            all_loc_ids = set()
            for year_locs in year_data.values():
                all_loc_ids.update(year_locs.keys())

            for loc_id in all_loc_ids:
                geom_data = geom_lookup.get(loc_id)
                if not geom_data:
                    continue

                geom_str = geom_data.get("geometry")
                if pd.isna(geom_str) or not geom_str:
                    continue

                try:
                    geom = json.loads(geom_str) if isinstance(geom_str, str) else geom_str
                except (json.JSONDecodeError, TypeError):
                    continue

                # Base properties (no year-specific values - those come from year_data)
                properties = {"loc_id": loc_id, "name": geom_data.get("name", loc_id)}

                features.append({
                    "type": "Feature",
                    "geometry": geom,
                    "properties": properties
                })
        else:
            # Single year: include values in properties
            for loc_id, props in boxes.items():
                geom_data = geom_lookup.get(loc_id)
                if not geom_data:
                    continue

                geom_str = geom_data.get("geometry")
                if pd.isna(geom_str) or not geom_str:
                    continue

                try:
                    geom = json.loads(geom_str) if isinstance(geom_str, str) else geom_str
                except (json.JSONDecodeError, TypeError):
                    continue

                # Build properties
                properties = {"loc_id": loc_id, "name": geom_data.get("name", loc_id)}
                properties.update(props)

                features.append({
                    "type": "Feature",
                    "geometry": geom,
                    "properties": properties
                })

    # Build source info for response (include URL if available)
    source_info = [
        {
            "id": sid,
            "name": meta.get("source_name", sid),
            "url": meta.get("source_url", "")
        }
        for sid, meta in sources_used.items()
    ]

    # Build response
    response = {
        "type": "success",
        "geojson": {
            "type": "FeatureCollection",
            "features": features
        },
        "summary": summary or f"Showing {len(features)} locations",
        "count": len(features),
        "sources": source_info
    }

    # Add multi-year data if applicable
    if multi_year_mode and year_data:
        sorted_years = sorted(all_years)
        actual_min = sorted_years[0] if sorted_years else 0
        actual_max = sorted_years[-1] if sorted_years else 0

        response["multi_year"] = True
        response["year_data"] = year_data
        response["year_range"] = {
            "min": actual_min,
            "max": actual_max,
            "available_years": sorted_years
        }
        response["metric_key"] = metric_key

        # Add data note if year range differs from requested
        data_notes = []
        if requested_year_start and requested_year_end:
            if actual_min != requested_year_start or actual_max != requested_year_end:
                data_notes.append(f"Note: Data available for {actual_min}-{actual_max} (requested {requested_year_start}-{requested_year_end})")
            # Check for sparse years
            expected_years = set(range(actual_min, actual_max + 1))
            missing_years = expected_years - all_years
            if missing_years:
                data_notes.append(f"Some years have no data: {sorted(missing_years)[:5]}{'...' if len(missing_years) > 5 else ''}")
        if data_notes:
            response["data_note"] = " | ".join(data_notes)

    return response
