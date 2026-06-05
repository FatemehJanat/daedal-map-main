"""Shared source path and parquet-loading helpers extracted from the executor."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import os

from mapmover.catalog_surface import get_catalog_surface_override


def _allow_local_source_fallback() -> bool:
    override = get_catalog_surface_override()
    if override in {"published", "wip"}:
        return override == "wip"
    raw = str(os.environ.get("USE_WIP_CATALOG", "")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def get_source_path(
    source_id: str,
    *,
    load_catalog_func,
    data_root: Path,
) -> Path:
    """Get the full local/cache path to a source directory using catalog metadata."""
    catalog = load_catalog_func() or {}
    for source in catalog.get("sources", []):
        if source.get("source_id") == source_id:
            source_path = source.get("path", f"global/{source_id}")
            return data_root / source_path
    return data_root / "global" / source_id


def candidate_parquet_paths(source_dir: Path, metadata: dict) -> list[Path]:
    """Return ordered parquet candidates for a source."""
    candidates: list[Path] = []
    seen: set[str] = set()

    def _add_candidate(name: str | None) -> None:
        filename = str(name or "").strip()
        if not filename or not filename.endswith(".parquet"):
            return
        if filename in seen:
            return
        seen.add(filename)
        candidates.append(source_dir / filename)

    files_section = metadata.get("files")
    if isinstance(files_section, dict):
        for info in files_section.values():
            if not isinstance(info, dict):
                continue
            _add_candidate(info.get("name") or info.get("filename"))

    primary_files = metadata.get("primary_files")
    if isinstance(primary_files, list):
        for entry in primary_files:
            _add_candidate(entry)

    for key in ("primary_file", "parquet_file", "data_file", "data_filename", "filename", "file_name"):
        _add_candidate(metadata.get(key))

    coverage = metadata.get("geographic_coverage", {}) or {}
    country_code = str(coverage.get("country", "")).strip().upper()
    if country_code:
        _add_candidate(f"{country_code}.parquet")

    source_parts = source_dir.parts
    if "countries" in source_parts:
        try:
            countries_idx = source_parts.index("countries")
            inferred_country = source_parts[countries_idx + 1].upper()
            _add_candidate(f"{inferred_country}.parquet")
        except Exception:
            pass

    for fallback_name in ("all_countries.parquet", "GLOBAL.parquet", "data.parquet"):
        _add_candidate(fallback_name)

    return candidates


def load_source_data(
    source_id: str,
    *,
    year: int | None = None,
    loc_id_prefix: str | None = None,
    get_source_path_func,
    load_source_metadata_func,
    candidate_parquet_paths_func,
    is_cloud_mode_func,
    path_to_uri_func,
    select_rows_func,
    logger,
) -> tuple[pd.DataFrame, dict]:
    """Load parquet and metadata for a source with optional pushed-down filters."""
    source_dir = get_source_path_func(source_id)
    metadata = load_source_metadata_func(source_id)
    if metadata is None:
        raise ValueError(f"Could not load metadata for {source_id}")

    exact_filters = {}
    starts_with_filters = {}
    if year is not None:
        exact_filters["year"] = year
    if loc_id_prefix:
        starts_with_filters["loc_id"] = loc_id_prefix

    parquet_candidates = candidate_parquet_paths_func(source_dir, metadata)
    if is_cloud_mode_func():
        if not parquet_candidates:
            raise ValueError(f"Cannot determine parquet path for {source_id} in S3 mode")

        last_df = pd.DataFrame()
        for parquet_path in parquet_candidates:
            if _allow_local_source_fallback() and parquet_path.exists():
                logger.info(
                    f"[S3->LOCAL] load_source_data({source_id}): using local fallback={parquet_path} year={year} prefix={loc_id_prefix}"
                )
            else:
                uri = path_to_uri_func(parquet_path)
                logger.info(f"[S3] load_source_data({source_id}): trying uri={uri} year={year} prefix={loc_id_prefix}")
            df = select_rows_func(
                parquet_path,
                exact_filters=exact_filters or None,
                starts_with_filters=starts_with_filters or None,
            )
            logger.info(f"[S3] load_source_data({source_id}): candidate={parquet_path.name} rows={len(df)}")
            last_df = df
            if not df.empty:
                return df, metadata
        df = last_df
    else:
        parquet_files = list(source_dir.glob("*.parquet"))
        if not parquet_files:
            raise ValueError(f"No parquet file found for {source_id} in {source_dir}")

        parquet_path = None
        for candidate in parquet_candidates:
            if candidate.exists():
                parquet_path = candidate
                break
        if parquet_path is None:
            parquet_path = parquet_files[0]

        df = select_rows_func(
            parquet_path,
            exact_filters=exact_filters or None,
            starts_with_filters=starts_with_filters or None,
        )
        if df.empty and not exact_filters and not starts_with_filters:
            df = pd.read_parquet(parquet_path)

    return df, metadata
