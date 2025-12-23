"""
Order Executor - executes confirmed orders against parquet data.
No LLM calls - direct data operations.

This module takes a structured order from the Order Taker and:
1. Loads the appropriate parquet data file
2. Filters by year, region, metrics
3. Joins with geometry data
4. Returns GeoJSON response
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


def get_region_countries(region: str) -> list:
    """Get country codes for a region from conversions.json."""
    with open(CONVERSIONS_PATH, encoding='utf-8') as f:
        conversions = json.load(f)

    # Map region names to grouping keys
    region_map = {
        "europe": "WHO_European_Region",
        "asia": "Asia",
        "africa": "African_Union",
        "americas": "WHO_Region_of_the_Americas",
        "oceania": "Oceania",
        "eu": "European_Union",
        "g7": "G7",
        "g20": "G20",
        "nato": "NATO",
        "brics": "BRICS"
    }

    key = region_map.get(region.lower())
    if key and key in conversions.get("regional_groupings", {}):
        return conversions["regional_groupings"][key].get("countries", [])

    return []


def execute_order(order: dict) -> dict:
    """
    Execute a confirmed order and return GeoJSON response.

    Args:
        order: {source_id, metrics, region, year, sort, summary}

    Returns:
        {type, geojson, summary, count, source}
    """
    source_id = order["source_id"]
    metrics = order.get("metrics", [])
    region = order.get("region")
    year = order.get("year")
    sort_spec = order.get("sort")

    # Load data
    df, metadata = load_source_data(source_id)

    # Filter by year
    if year and "year" in df.columns:
        df = df[df["year"] == year]
    elif "year" in df.columns:
        # Use latest year
        df = df[df["year"] == df["year"].max()]

    # Filter by region (for country-level data)
    if region and region.lower() != "global":
        countries = get_region_countries(region)
        if countries and "loc_id" in df.columns:
            # Extract country code from loc_id (first part before dash)
            df["_country_code"] = df["loc_id"].str.split("-").str[0]
            df = df[df["_country_code"].isin(countries)]
            df = df.drop(columns=["_country_code"])

    # Select columns
    keep_cols = ["loc_id"]
    if "year" in df.columns:
        keep_cols.append("year")

    # Add requested metrics (fuzzy match column names)
    for metric in metrics:
        matched = [c for c in df.columns if metric.lower() in c.lower()]
        if matched:
            keep_cols.extend(matched[:1])  # First match only

    # If no metrics specified, keep all numeric columns (up to 5)
    if len(keep_cols) <= 2:
        numeric_cols = df.select_dtypes(include=['float64', 'int64', 'Float64', 'Int64']).columns
        keep_cols.extend([c for c in numeric_cols if c not in keep_cols][:5])

    # Ensure we only keep columns that exist
    keep_cols = [c for c in keep_cols if c in df.columns]
    df = df[keep_cols].drop_duplicates(subset=["loc_id"])

    # Apply sort
    if sort_spec:
        sort_col = sort_spec.get("by")
        if sort_col:
            matched = [c for c in df.columns if sort_col.lower() in c.lower()]
            if matched:
                ascending = sort_spec.get("order", "desc") == "asc"
                df = df.sort_values(matched[0], ascending=ascending, na_position='last')
                if sort_spec.get("limit"):
                    df = df.head(sort_spec["limit"])

    # Get geometry based on geographic level
    geo_level = metadata.get("geographic_level", "country")

    if geo_level == "country":
        # Use global.csv for country geometries
        geometry_df = load_global_countries()
        if geometry_df is not None:
            # Merge on loc_id
            df = df.merge(
                geometry_df[["loc_id", "name", "geometry"]],
                on="loc_id",
                how="left"
            )
    else:
        # For sub-national data (state, county), we need to load per-country parquet
        # Group by country and load each parquet
        if "loc_id" in df.columns:
            df["_iso3"] = df["loc_id"].str.split("-").str[0]
            countries = df["_iso3"].unique()

            geometry_rows = []
            for iso3 in countries:
                country_geom = load_country_parquet(iso3)
                if country_geom is not None:
                    geometry_rows.append(
                        country_geom[["loc_id", "name", "geometry"]]
                    )

            if geometry_rows:
                all_geometry = pd.concat(geometry_rows, ignore_index=True)
                df = df.drop(columns=["_iso3"])
                df = df.merge(all_geometry, on="loc_id", how="left")
            else:
                df = df.drop(columns=["_iso3"])

    # Build GeoJSON
    features = []
    for _, row in df.iterrows():
        geom_str = row.get("geometry")
        if pd.isna(geom_str) or not geom_str:
            continue

        try:
            geom = json.loads(geom_str) if isinstance(geom_str, str) else geom_str
        except (json.JSONDecodeError, TypeError):
            continue

        # Build properties from all columns except geometry
        properties = {}
        for col in df.columns:
            if col != "geometry":
                val = row.get(col)
                if pd.notna(val):
                    # Handle numpy types
                    if hasattr(val, 'item'):
                        val = val.item()
                    properties[col] = val

        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": properties
        })

    return {
        "type": "success",
        "geojson": {
            "type": "FeatureCollection",
            "features": features
        },
        "summary": order.get("summary", f"Showing {len(features)} locations"),
        "count": len(features),
        "source": {
            "id": source_id,
            "name": metadata.get("source_name", source_id)
        }
    }
