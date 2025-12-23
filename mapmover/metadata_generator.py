"""
Metadata generator for data sources.
Reads parquet file, auto-detects fields, outputs metadata dict.

Usage:
    from mapmover.metadata_generator import generate_metadata

    metadata = generate_metadata(
        parquet_path="path/to/data.parquet",
        source_info={
            "source_id": "owid_co2",
            "source_name": "Our World in Data",
            "source_url": "...",
            "license": "CC-BY",
            "description": "...",
            "category": "environmental",
            "topic_tags": ["climate", "emissions"],
            "keywords": ["carbon", "pollution"]
        },
        metric_info={
            "gdp": {"name": "GDP", "unit": "USD", "keywords": ["economy"]},
            "co2": {"name": "CO2 emissions", "unit": "million tonnes"}
        }
    )
"""

import pandas as pd
import json
from pathlib import Path
from datetime import date

# Load region mappings from conversions.json
_CONVERSIONS_PATH = Path(__file__).parent / "conversions.json"
_CONVERSIONS = None

def _load_conversions():
    """Load conversions.json once and cache it."""
    global _CONVERSIONS
    if _CONVERSIONS is None:
        with open(_CONVERSIONS_PATH, encoding='utf-8') as f:
            _CONVERSIONS = json.load(f)
    return _CONVERSIONS

def _get_region_countries(region_name: str) -> list:
    """Get country codes for a region from conversions.json."""
    conversions = _load_conversions()
    groupings = conversions.get("regional_groupings", {})

    # Map simple region names to grouping keys
    region_map = {
        "Europe": "WHO_European_Region",
        "Asia": "Asia",
        "Africa": "African_Union",
        "Americas": "WHO_Region_of_the_Americas",
        "Oceania": "Oceania"
    }

    key = region_map.get(region_name, region_name)
    if key in groupings:
        return groupings[key].get("countries", [])
    return []

# Build REGIONS dict from conversions.json
def _build_regions_dict() -> dict:
    """Build the REGIONS lookup dict from conversions.json."""
    return {
        "Europe": _get_region_countries("Europe"),
        "Asia": _get_region_countries("Asia"),
        "Africa": _get_region_countries("Africa"),
        "Americas": _get_region_countries("Americas"),
        "Oceania": _get_region_countries("Oceania")
    }


def generate_metadata(
    parquet_path: str,
    source_info: dict,
    metric_info: dict = None
) -> dict:
    """
    Generate metadata for a data source.

    Args:
        parquet_path: Path to parquet file
        source_info: Manual source information (id, name, url, description, etc.)
        metric_info: Optional manual metric definitions (name, unit, keywords)

    Returns:
        Complete metadata dict
    """
    df = pd.read_parquet(parquet_path)
    path = Path(parquet_path)

    # Auto-detect fields
    geo_coverage = _detect_geographic_coverage(df)
    temp_coverage = _detect_temporal_coverage(df)
    metrics = _detect_metrics(df, metric_info or {})

    return {
        # Manual source info
        "source_id": source_info["source_id"],
        "source_name": source_info["source_name"],
        "source_url": source_info.get("source_url", ""),
        "license": source_info.get("license", "Unknown"),
        "description": source_info.get("description", ""),
        "category": source_info.get("category", "general"),
        "topic_tags": source_info.get("topic_tags", []),
        "keywords": source_info.get("keywords", []),

        # Auto-detected
        "last_updated": date.today().isoformat(),
        "geographic_level": _detect_geographic_level(df),
        "geographic_coverage": geo_coverage,
        "temporal_coverage": temp_coverage,
        "row_count": len(df),
        "file_size_mb": round(path.stat().st_size / 1024 / 1024, 2),
        "data_completeness": _calculate_completeness(df),

        # Update schedule (manual - passed through from source_info)
        "update_schedule": source_info.get("update_schedule", "unknown"),
        "expected_next_update": source_info.get("expected_next_update", "unknown"),

        # Metrics
        "metrics": metrics,

        # LLM summary (auto-generated if not provided)
        "llm_summary": source_info.get("llm_summary") or _generate_summary(
            geo_coverage, temp_coverage, metrics
        )
    }


def _detect_geographic_level(df) -> str:
    """Detect admin level from loc_id format."""
    if 'loc_id' not in df.columns:
        return "unknown"

    sample = df['loc_id'].dropna().head(100).tolist()
    if not sample:
        return "unknown"

    max_dashes = max(str(s).count('-') for s in sample)

    return {0: "country", 1: "state", 2: "county"}.get(max_dashes, "other")


def _detect_geographic_coverage(df) -> dict:
    """Analyze loc_ids to determine coverage."""
    if 'loc_id' not in df.columns:
        return {"type": "unknown", "countries": 0, "regions": [], "admin_levels": [], "country_codes": []}

    loc_ids = df['loc_id'].dropna().unique()

    # Extract country codes and admin levels
    country_codes = set()
    admin_levels = set()
    for loc_id in loc_ids:
        loc_str = str(loc_id)
        parts = loc_str.split('-')
        country_codes.add(parts[0])
        admin_levels.add(len(parts) - 1)

    # Detect regions and count countries per region
    regions_dict = _build_regions_dict()
    region_coverage = {}
    for region, codes in regions_dict.items():
        covered = [c for c in codes if c in country_codes]
        if covered:
            region_coverage[region] = {
                "count": len(covered),
                "total": len(codes),
                "countries": sorted(covered)[:10]  # First 10 for display
            }

    # Determine type
    n_countries = len(country_codes)
    if n_countries > 50:
        coverage_type = "global"
    elif n_countries == 1:
        coverage_type = "country"
    else:
        coverage_type = "regional"

    # Sort country codes for display (limit to 30 for catalog)
    sorted_codes = sorted(country_codes)

    return {
        "type": coverage_type,
        "countries": n_countries,
        "country_codes": sorted_codes[:30],  # First 30 for display
        "country_codes_all": sorted_codes,    # Full list for reference
        "regions": sorted(region_coverage.keys()),
        "region_coverage": region_coverage,   # Detailed per-region info
        "admin_levels": sorted(admin_levels)
    }


def _detect_temporal_coverage(df) -> dict:
    """Extract year range."""
    if 'year' not in df.columns:
        return {"start": None, "end": None, "frequency": "unknown"}

    years = df['year'].dropna()
    if len(years) == 0:
        return {"start": None, "end": None, "frequency": "unknown"}

    return {
        "start": int(years.min()),
        "end": int(years.max()),
        "frequency": "annual"
    }


def _detect_metrics(df, overrides: dict) -> dict:
    """Detect numeric columns as metrics."""
    exclude = {'year', 'loc_id', 'country_code', 'country_name', 'state', 'county'}

    metrics = {}
    for col in df.columns:
        if col.lower() in exclude:
            continue
        if df[col].dtype not in ['float64', 'int64', 'Float64', 'Int64']:
            continue

        if col in overrides:
            metrics[col] = overrides[col]
        else:
            metrics[col] = {
                "name": col.replace("_", " ").title(),
                "unit": _guess_unit(col),
                "aggregation": _guess_aggregation(col),
                "keywords": []
            }

    return metrics


def _guess_unit(col: str) -> str:
    """Guess unit from column name."""
    col = col.lower()
    if 'per_capita' in col:
        return "per person"
    if 'percent' in col or 'pct' in col or 'rate' in col:
        return "percentage"
    if 'pop' in col:
        return "count"
    if 'gdp' in col:
        return "USD"
    if 'co2' in col or 'emission' in col:
        return "million tonnes"
    if 'energy' in col:
        return "TWh"
    if 'temperature' in col:
        return "degrees C"
    if 'life_expectancy' in col or 'expectancy' in col:
        return "years"
    if 'mortality' in col:
        return "per 1000"
    return "unknown"


def _guess_aggregation(col: str) -> str:
    """Guess aggregation method from column name."""
    col = col.lower()
    if 'per_capita' in col or 'rate' in col or 'percent' in col or 'pct' in col:
        return "avg"
    if 'median' in col:
        return "avg"
    return "sum"


def _calculate_completeness(df) -> float:
    """Calculate data completeness (non-null ratio)."""
    if df.size == 0:
        return 0.0
    return round(df.count().sum() / df.size, 2)


def _generate_summary(geo, temp, metrics) -> str:
    """Auto-generate summary for LLM context."""
    parts = []

    # Coverage
    if geo.get("countries"):
        parts.append(f"{geo['countries']} countries")

    # Time range
    if temp.get("start") and temp.get("end"):
        parts.append(f"{temp['start']}-{temp['end']}")

    # Key metrics (first 5)
    if metrics:
        names = [m.get("name", k) for k, m in list(metrics.items())[:5]]
        parts.append(", ".join(names))

    return ". ".join(parts) + "." if parts else ""
