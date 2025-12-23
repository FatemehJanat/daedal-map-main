"""
Build catalog.json from all metadata.json files.

Usage:
    from mapmover.catalog_builder import build_catalog
    build_catalog()

Or run directly:
    python -m mapmover.catalog_builder
"""

import json
from pathlib import Path
from datetime import date

DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/data")
CATALOG_PATH = DATA_DIR.parent / "catalog.json"


def _build_coverage_description(geo: dict) -> str:
    """Build human-readable coverage description for LLM context."""
    if not geo:
        return "Unknown coverage"

    coverage_type = geo.get("type", "unknown")
    country_codes = geo.get("country_codes", [])
    n_countries = geo.get("countries", 0)
    regions = geo.get("regions", [])
    region_coverage = geo.get("region_coverage", {})

    # Single country
    if coverage_type == "country" and country_codes:
        country = country_codes[0]
        return f"{country} only"

    # Global coverage
    if coverage_type == "global":
        parts = []
        for region in ["Africa", "Americas", "Asia", "Europe", "Oceania"]:
            if region in region_coverage:
                rc = region_coverage[region]
                parts.append(f"{region}: {rc['count']}/{rc['total']} countries")
        if parts:
            return f"Global ({n_countries} countries) - " + ", ".join(parts)
        return f"Global ({n_countries} countries)"

    # Regional coverage
    if regions:
        parts = []
        for region in regions:
            if region in region_coverage:
                rc = region_coverage[region]
                parts.append(f"{region}: {rc['count']} countries")
            else:
                parts.append(region)
        return ", ".join(parts)

    return f"{n_countries} countries"


def build_catalog(data_dir: Path = None, output_path: Path = None):
    """
    Scan all metadata.json files and build catalog.json.

    Args:
        data_dir: Directory containing source folders. Defaults to DATA_DIR.
        output_path: Path for catalog.json. Defaults to CATALOG_PATH.

    Returns:
        The catalog dict.
    """
    data_dir = data_dir or DATA_DIR
    output_path = output_path or CATALOG_PATH

    sources = []

    for source_dir in sorted(data_dir.iterdir()):
        if not source_dir.is_dir():
            continue

        meta_path = source_dir / "metadata.json"
        if not meta_path.exists():
            print(f"SKIP: {source_dir.name} (no metadata.json)")
            continue

        print(f"Adding: {source_dir.name}")

        with open(meta_path, encoding='utf-8') as f:
            metadata = json.load(f)

        # Extract summary for catalog (not full metadata)
        geo = metadata.get("geographic_coverage", {})

        # Build a clear coverage description for LLM
        coverage_desc = _build_coverage_description(geo)

        sources.append({
            "source_id": metadata.get("source_id"),
            "source_name": metadata.get("source_name"),
            "category": metadata.get("category"),
            "topic_tags": metadata.get("topic_tags", []),
            "keywords": metadata.get("keywords", []),
            "geographic_level": metadata.get("geographic_level"),
            "geographic_coverage": geo,
            "coverage_description": coverage_desc,  # Human-readable for LLM
            "temporal_coverage": metadata.get("temporal_coverage", {}),
            "update_schedule": metadata.get("update_schedule", "unknown"),
            "expected_next_update": metadata.get("expected_next_update", "unknown"),
            "llm_summary": metadata.get("llm_summary", "")
        })

    # Build catalog
    catalog = {
        "catalog_version": "1.0",
        "last_updated": date.today().isoformat(),
        "total_sources": len(sources),
        "sources": sources
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(catalog, f, indent=2)

    print(f"\nCatalog saved: {output_path}")
    print(f"Total sources: {len(sources)}")

    return catalog


if __name__ == "__main__":
    build_catalog()
