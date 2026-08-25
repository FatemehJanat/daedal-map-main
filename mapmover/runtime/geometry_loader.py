from __future__ import annotations

from pathlib import Path
from typing import Any

from ..duckdb_helpers import is_cloud_mode, parquet_columns
from ..foundation_helpers import load_country_crosswalk
from ..paths import COUNTRY_GEOMETRY_DIR, GEOMETRY_DIR
from .read_posture import prefer_local_geometry_reads
from ..runtime_config import force_remote_data_reads


def parquet_accessible(path: Path | None) -> bool:
    """Return True when a parquet path exists locally or is cloud-readable."""
    if path is None:
        return False
    if path.exists() and not force_remote_data_reads():
        return True
    if prefer_local_geometry_reads():
        return False
    if not is_cloud_mode():
        return False
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
    - `source_kind`: `authority_spine`, `country_base`, `crosswalk_base`,
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

    country_root = COUNTRY_GEOMETRY_DIR / iso3
    authority_spine_file = country_root / "admin_spine" / "admin_0_3.parquet"
    country_geom_file = country_root / "geometry.parquet"
    global_geom_file = GEOMETRY_DIR / f"{iso3}.parquet"
    crosswalk = load_country_crosswalk(iso3)

    # The released country admin spine is the authority for Admin0-3.  This
    # convention is shared by AUS, CAN, USA, and future country programs; do
    # not add country-specific county or state banks ahead of it.
    if (admin_level is None or 0 <= admin_level <= 3) and parquet_accessible(authority_spine_file):
        return {
            "parquet_file": authority_spine_file,
            "crosswalk": None,
            "uses_crosswalk": False,
            "source_kind": "authority_spine",
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
