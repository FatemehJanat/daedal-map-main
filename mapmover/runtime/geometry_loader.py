from __future__ import annotations

from pathlib import Path
from typing import Any

from ..duckdb_helpers import is_cloud_mode, parquet_columns
from ..foundation_helpers import load_country_crosswalk
from ..paths import COUNTRIES_DIR, GEOMETRY_DIR
from .read_posture import prefer_local_geometry_reads


def parquet_accessible(path: Path | None) -> bool:
    """Return True when a parquet path exists locally or is cloud-readable."""
    if path is None:
        return False
    if prefer_local_geometry_reads():
        return path.exists()
    if not is_cloud_mode():
        return path.exists()
    try:
        cols = parquet_columns(path)
        return bool(cols)
    except Exception:
        return False


def resolve_country_geometry_source(iso3: str, *, admin_level: int | None = None) -> dict[str, Any]:
    """
    Resolve the canonical geometry-loading source for a country request.

    Returned dict keys:
    - `parquet_file`: selected parquet path or None
    - `crosswalk`: loaded crosswalk dict or None
    - `uses_crosswalk`: whether runtime loc_ids must bridge to geometry ids
    - `source_kind`: `country_county`, `country_base`, `crosswalk_base`,
      `global_base`, or `missing`
    """
    iso3 = str(iso3 or "").strip().upper()
    if not iso3:
        return {
            "parquet_file": None,
            "crosswalk": None,
            "uses_crosswalk": False,
            "source_kind": "missing",
        }

    country_geom_file = COUNTRIES_DIR / iso3 / "geometry.parquet"
    county_geom_file = COUNTRIES_DIR / iso3 / "geometry" / "county.parquet"
    global_geom_file = GEOMETRY_DIR / f"{iso3}.parquet"
    crosswalk = load_country_crosswalk(iso3)

    if admin_level == 2 and parquet_accessible(county_geom_file):
        return {
            "parquet_file": county_geom_file,
            "crosswalk": None,
            "uses_crosswalk": False,
            "source_kind": "country_county",
        }

    if parquet_accessible(country_geom_file):
        return {
            "parquet_file": country_geom_file,
            "crosswalk": None,
            "uses_crosswalk": False,
            "source_kind": "country_base",
        }

    if crosswalk and parquet_accessible(global_geom_file):
        return {
            "parquet_file": global_geom_file,
            "crosswalk": crosswalk,
            "uses_crosswalk": True,
            "source_kind": "crosswalk_base",
        }

    if parquet_accessible(global_geom_file):
        return {
            "parquet_file": global_geom_file,
            "crosswalk": None,
            "uses_crosswalk": False,
            "source_kind": "global_base",
        }

    return {
        "parquet_file": None,
        "crosswalk": crosswalk if isinstance(crosswalk, dict) else None,
        "uses_crosswalk": False,
        "source_kind": "missing",
    }
