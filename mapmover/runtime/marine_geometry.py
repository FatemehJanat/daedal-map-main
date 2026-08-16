"""Marine geometry resolution for the EEZ / water-body overlay families.

The admin geometry loader (geometry_loader.py) resolves country/admin loc_ids to
the GeoBoundaries banks. Water-body and EEZ ids are ordinary ``loc_id`` values
from sibling geometry families; this module only routes those ids to their
geometry banks:

  - EEZ-<ISO3> / EEZ-MRGID-<n>  -> geometry/marine/eez.parquet
  - X* water-body aggregate codes (XOP..) -> geometry/marine/water_bodies.parquet
  - IHO1953-<n> reviewed IHO-1953 named waters -> iho1953_sea_areas.parquet

The MRGID-<n> legacy named-water bank (Marine Regions / VLIZ IHO Sea Areas) was
removed on 2026-08-16. It was licence-unreviewed, so its routing was already
inert, and the reviewed IHO-1953 bank supersedes it with wider coverage.

This is the geometry counterpart to the shared grid helper's classification
(is_eez_loc_id / is_water_body_loc_id): given marine loc_ids, return their
polygons so a metrics source aggregated onto marine zones (e.g. ocean_sst) can
render. It is shared across the whole ocean family (SST, CoralTemp, DHW, etc.),
not specific to one pack.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from ..duckdb_helpers import parquet_available, select_columns_from_parquet
from ..paths import GEOMETRY_DIR
from .geography_reference import is_eez_loc_id, is_named_water_loc_id, is_water_body_loc_id

MARINE_DIR = GEOMETRY_DIR / "marine"
EEZ_PATH = MARINE_DIR / "eez.parquet"
WATER_BODIES_PATH = MARINE_DIR / "water_bodies.parquet"
IHO1953_NAMED_WATER_PATH = MARINE_DIR / "iho1953_sea_areas.parquet"
GEOMETRY_CATALOG_PATH = GEOMETRY_DIR / "geometry_catalog.json"

_MARINE_COLUMNS = ["loc_id", "name", "geometry", "centroid_lon", "centroid_lat"]


def is_marine_loc_id(loc_id: str | None) -> bool:
    """True for either marine overlay family or canonical named water."""
    return is_eez_loc_id(loc_id) or is_water_body_loc_id(loc_id) or is_named_water_loc_id(loc_id)


def _catalog_approves_geometry(path: Path) -> bool:
    """Do not expose candidate sea geometry until catalog review is explicit."""
    try:
        catalog = json.loads(GEOMETRY_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    try:
        rel_path = path.relative_to(GEOMETRY_DIR).as_posix()
    except ValueError:
        rel_path = path.as_posix()
    for bank in catalog.get("geometry_banks") or []:
        if not isinstance(bank, dict):
            continue
        if str(bank.get("geometry_path") or "").replace("\\", "/") != rel_path:
            continue
        return (
            bank.get("license_review_status") == "approved"
            and bank.get("usable_for_derivation") is True
        )
    return False


def named_water_bank_approved(loc_id: str | None = None) -> bool:
    """True if the bank owning this named-water namespace is reviewed."""
    return _catalog_approves_geometry(IHO1953_NAMED_WATER_PATH)


def marine_bank_for_loc_id(loc_id: str | None) -> Optional[Path]:
    """Return the marine geometry bank that owns this loc_id, or None."""
    if is_eez_loc_id(loc_id):
        return EEZ_PATH
    if is_named_water_loc_id(loc_id):
        return IHO1953_NAMED_WATER_PATH if named_water_bank_approved(loc_id) else None
    if is_water_body_loc_id(loc_id):
        return WATER_BODIES_PATH
    return None


def has_marine_geometry() -> bool:
    """True when at least one marine bank is readable (local or cloud)."""
    return (
        parquet_available(EEZ_PATH)
        or parquet_available(WATER_BODIES_PATH)
        or (named_water_bank_approved("IHO1953-0") and parquet_available(IHO1953_NAMED_WATER_PATH))
    )


def resolve_marine_geometry_source(loc_id: str | None) -> dict:
    """Mirror geometry_loader.resolve_country_geometry_source for marine loc_ids.

    Keys: `parquet_file` (path or None), `source_kind` (`marine_bank`/`missing`),
    `marine_kind` (`marine_eez`/`water_body`/`named_water`/None).
    """
    bank = marine_bank_for_loc_id(loc_id)
    if bank is None:
        return {"parquet_file": None, "source_kind": "missing", "marine_kind": None}
    accessible = parquet_available(bank)
    return {
        "parquet_file": bank if accessible else None,
        "source_kind": "marine_bank" if accessible else "missing",
        "marine_kind": (
            "marine_eez" if is_eez_loc_id(loc_id)
            else "named_water" if is_named_water_loc_id(loc_id)
            else "water_body"
        ),
    }


def _read_bank(path: Path, want: Optional[set], columns: Optional[list[str]] = None) -> pd.DataFrame:
    selected_columns = [column for column in (columns or _MARINE_COLUMNS) if column in _MARINE_COLUMNS]
    if "loc_id" not in selected_columns:
        selected_columns.insert(0, "loc_id")
    if not parquet_available(path):
        return pd.DataFrame(columns=selected_columns)
    try:
        df = select_columns_from_parquet(path, selected_columns)
    except Exception:
        df = None
    if df is None or df.empty:
        try:
            df = pd.read_parquet(path, columns=selected_columns)
        except Exception:
            return pd.DataFrame(columns=selected_columns)
    if want is not None and "loc_id" in df.columns:
        df = df[df["loc_id"].isin(want)]
    return df


def load_marine_geometry(loc_ids: Optional[Iterable[str]] = None, *, columns: Optional[list[str]] = None) -> pd.DataFrame:
    """Load marine geometry rows for the given loc_ids (or all marine geometry).

    Returns columns [loc_id, name, geometry, centroid_lon, centroid_lat]. Only
    the bank(s) actually referenced by the requested loc_ids are read, so an
    EEZ-only query never touches the water-body bank and vice versa. Callers
    that only need availability metadata can omit the heavy geometry column.
    """
    want = {str(x).strip() for x in loc_ids} if loc_ids is not None else None
    need_eez = want is None or any(is_eez_loc_id(x) for x in want)
    need_wb = want is None or any(is_water_body_loc_id(x) for x in want)
    need_named_water = want is None or any(is_named_water_loc_id(x) for x in want)

    frames = []
    if need_eez:
        frames.append(_read_bank(EEZ_PATH, want, columns=columns))
    if need_wb:
        frames.append(_read_bank(WATER_BODIES_PATH, want, columns=columns))
    if need_named_water and named_water_bank_approved("IHO1953-0"):
        frames.append(_read_bank(IHO1953_NAMED_WATER_PATH, want, columns=columns))
    if not frames:
        return pd.DataFrame(columns=columns or _MARINE_COLUMNS)
    return pd.concat(frames, ignore_index=True).reset_index(drop=True)
