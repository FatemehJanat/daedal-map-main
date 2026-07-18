from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any
import re

import pandas as pd

from .data_loading import get_source_path, load_catalog, load_source_metadata
from .duckdb_helpers import parquet_available, parquet_columns, path_to_uri, quote_ident, run_df
from .paths import DATA_ROOT
from .runtime.aggregate_primitives import resolve_aggregate_admin2_dir


DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


@dataclass(frozen=True)
class ApiMetricSpec:
    metric_id: str
    column: str
    description: str


@dataclass(frozen=True)
class ApiSourceSpec:
    source_id: str
    pack_id: str
    parquet_name: str
    query_mode: str
    location_field: str
    time_field: str | None
    time_granularity: str | None
    metrics: dict[str, ApiMetricSpec]
    filterable_fields: set[str]
    sortable_fields: set[str]
    location_filter_mode: str = "hierarchical_loc_id"
    location_lookup_field: str | None = None
    default_limit: int = DEFAULT_LIMIT
    max_limit: int = MAX_LIMIT
    metadata_source_id: str | None = None


CURRENCY_SOURCE_SPEC = ApiSourceSpec(
    source_id="fx_usd_historical",
    pack_id="currency",
    parquet_name="data.parquet",
    query_mode="single_source",
    location_field="loc_id",
    time_field="date",
    time_granularity="date",
    metrics={
        "local_per_usd": ApiMetricSpec(
            metric_id="local_per_usd",
            column="local_per_usd",
            description="Local currency units per one USD",
        ),
    },
    filterable_fields={"loc_id", "date"},
    sortable_fields={"loc_id", "date", "local_per_usd"},
    location_filter_mode="hierarchical_loc_id",
)


SUPPORTED_DYNAMIC_SOURCES: dict[str, dict[str, Any]] = {
    "fx_usd_historical": {
        "pack_id": "currency",
        "parquet_name": "data.parquet",
        "query_mode": "single_source",
        "location_field": "loc_id",
        "time_field": "date",
        "time_granularity": "date",
        "default_limit": DEFAULT_LIMIT,
        "max_limit": MAX_LIMIT,
    },
    "fx_usd_historical_weekly": {
        "pack_id": "currency",
        "parquet_name": "data.parquet",
        "query_mode": "single_source",
        "location_field": "loc_id",
        "time_field": "date",
        "time_granularity": "weekly",
        "default_limit": DEFAULT_LIMIT,
        "max_limit": MAX_LIMIT,
    },
    "fx_usd_historical_monthly": {
        "pack_id": "currency",
        "parquet_name": "data.parquet",
        "query_mode": "single_source",
        "location_field": "loc_id",
        "time_field": "date",
        "time_granularity": "monthly",
        "default_limit": DEFAULT_LIMIT,
        "max_limit": MAX_LIMIT,
    },
    "world_factbook": {
        "pack_id": "world_factbook",
        "parquet_name": "all_countries.parquet",
        "query_mode": "single_source",
        "location_field": "loc_id",
        "time_field": "year",
        "time_granularity": "yearly",
        "default_limit": DEFAULT_LIMIT,
        "max_limit": MAX_LIMIT,
    },
    "world_factbook_static": {
        "pack_id": "world_factbook",
        "parquet_name": "all_countries.parquet",
        "query_mode": "single_source_static",
        "location_field": "loc_id",
        "time_field": None,
        "time_granularity": None,
        "default_limit": DEFAULT_LIMIT,
        "max_limit": MAX_LIMIT,
    },
    "worldpop": {
        "pack_id": "worldpop",
        "parquet_name": "population.parquet",
        "query_mode": "single_source",
        "location_field": "loc_id",
        "time_field": "timestamp",
        "time_granularity": "yearly",
        "default_limit": 200,
        "max_limit": 5000,
    },
    "distributed_manufacturing": {
        "pack_id": "distributed_manufacturing",
        "parquet_name": "locations.parquet",
        "query_mode": "single_source_static",
        "location_field": "loc_id",
        "time_field": None,
        "time_granularity": None,
        "default_limit": 100,
        "max_limit": 1000,
    },
    "cbp": {
        "pack_id": "usa_industrial_activity",
        "parquet_name": "USA.parquet",
        "query_mode": "single_source",
        "location_field": "loc_id",
        "time_field": "timestamp",
        "time_granularity": "yearly",
        "default_limit": DEFAULT_LIMIT,
        "max_limit": MAX_LIMIT,
    },
    "lodes": {
        "pack_id": "usa_industrial_activity",
        "parquet_name": "USA_tract.parquet",
        "query_mode": "single_source",
        "location_field": "loc_id",
        "time_field": "timestamp",
        "time_granularity": "yearly",
        "default_limit": DEFAULT_LIMIT,
        "max_limit": MAX_LIMIT,
    },
    "susb": {
        "pack_id": "usa_industrial_activity",
        "parquet_name": "USA_county_naics.parquet",
        "query_mode": "single_source",
        "location_field": "loc_id",
        "time_field": "timestamp",
        "time_granularity": "yearly",
        "default_limit": DEFAULT_LIMIT,
        "max_limit": MAX_LIMIT,
    },
    "owid_co2": {
        "pack_id": "owid",
        "parquet_name": "owid_co2.parquet",
        "query_mode": "single_source",
        "location_field": "loc_id",
        "time_field": "year",
        "time_granularity": "yearly",
        "default_limit": DEFAULT_LIMIT,
        "max_limit": MAX_LIMIT,
    },
    "un_wpp": {
        "pack_id": "un_wpp",
        "parquet_name": "un_wpp.parquet",
        "query_mode": "single_source",
        "location_field": "loc_id",
        "time_field": "year",
        "time_granularity": "yearly",
        "default_limit": DEFAULT_LIMIT,
        "max_limit": MAX_LIMIT,
    },
    "earthquakes_events": {
        "pack_id": "earthquakes",
        "parquet_name": "events.parquet",
        "query_mode": "single_source_events",
        "location_field": "loc_id",
        "time_field": "timestamp",
        "time_granularity": "timestamp",
        "default_limit": 100,
        "max_limit": 500,
    },
    "volcanoes_events": {
        "pack_id": "volcanoes",
        "parquet_name": "events.parquet",
        "query_mode": "single_source_events",
        "location_field": "loc_id",
        "time_field": "year",
        "time_granularity": "yearly",
        "default_limit": 100,
        "max_limit": 500,
    },
    "tsunamis_events": {
        "pack_id": "tsunamis",
        "parquet_name": "events.parquet",
        "query_mode": "single_source_events",
        "location_field": "loc_id",
        "time_field": "year",
        "time_granularity": "yearly",
        "default_limit": 100,
        "max_limit": 500,
    },
    "hurricanes": {
        "pack_id": "hurricanes",
        "parquet_name": "events.parquet",
        "query_mode": "single_source_events",
        "location_field": "loc_id",
        "time_field": "timestamp",
        "time_granularity": "timestamp",
        "default_limit": 100,
        "max_limit": 1000,
    },
    "global_fire_atlas": {
        "pack_id": "wildfires",
        "parquet_name": "events.parquet",
        "query_mode": "single_source_events",
        "location_field": "loc_id",
        "time_field": "timestamp",
        "time_granularity": "timestamp",
        "default_limit": 100,
        "max_limit": 500,
    },
    "wildfires_usa": {
        "pack_id": "wildfires",
        "parquet_name": "fires_enriched.parquet",
        "query_mode": "single_source_events",
        "location_field": "loc_id",
        "time_field": "timestamp",
        "time_granularity": "timestamp",
        "default_limit": 100,
        "max_limit": 500,
    },
    "can_wildfires": {
        "pack_id": "wildfires",
        "parquet_name": "fires_enriched.parquet",
        "query_mode": "single_source_events",
        "location_field": "loc_id",
        "time_field": "timestamp",
        "time_granularity": "timestamp",
        "default_limit": 100,
        "max_limit": 500,
    },
    "wildfire_aggregates": {
        "pack_id": "wildfires",
        "parquet_name": "yearly.parquet",
        "query_mode": "single_source",
        "location_field": "loc_id",
        "time_field": "year",
        "time_granularity": "yearly",
        "default_limit": 100,
        "max_limit": 1000,
    },
    "flood_aggregates": {
        "pack_id": "floods",
        "parquet_name": "yearly.parquet",
        "query_mode": "single_source",
        "location_field": "loc_id",
        "time_field": "year",
        "time_granularity": "yearly",
        "default_limit": 100,
        "max_limit": 1000,
    },
    "tornado_aggregates": {
        "pack_id": "tornadoes",
        "parquet_name": "yearly.parquet",
        "query_mode": "single_source",
        "location_field": "loc_id",
        "time_field": "year",
        "time_granularity": "yearly",
        "default_limit": 100,
        "max_limit": 1000,
    },
    "earthquake_aggregates": {
        "pack_id": "earthquakes",
        "parquet_name": "yearly.parquet",
        "query_mode": "single_source",
        "location_field": "loc_id",
        "time_field": "year",
        "time_granularity": "yearly",
        "default_limit": 100,
        "max_limit": 1000,
    },
    "tsunami_aggregates": {
        "pack_id": "tsunamis",
        "parquet_name": "yearly.parquet",
        "query_mode": "single_source",
        "location_field": "loc_id",
        "time_field": "year",
        "time_granularity": "yearly",
        "default_limit": 100,
        "max_limit": 1000,
    },
    "volcano_aggregates": {
        "pack_id": "volcanoes",
        "parquet_name": "yearly.parquet",
        "query_mode": "single_source",
        "location_field": "loc_id",
        "time_field": "year",
        "time_granularity": "yearly",
        "default_limit": 100,
        "max_limit": 1000,
    },
    "floods": {
        "pack_id": "floods",
        "parquet_name": "events.parquet",
        "query_mode": "single_source_events",
        "location_field": "loc_id",
        "time_field": "timestamp",
        "time_granularity": "timestamp",
        "default_limit": 100,
        "max_limit": 500,
    },
    "tornadoes": {
        "pack_id": "tornadoes",
        "parquet_name": "events.parquet",
        "query_mode": "single_source_events",
        "location_field": "loc_id",
        "time_field": "timestamp",
        "time_granularity": "timestamp",
        "default_limit": 100,
        "max_limit": 500,
    },
}

# UN SDG sources 01-17 share the same parquet shape; entries are generated to avoid repetition
for _sdg_i in range(1, 18):
    SUPPORTED_DYNAMIC_SOURCES[f"{_sdg_i:02d}"] = {
        "pack_id": "un_sdg",
        "parquet_name": "all_countries.parquet",
        "query_mode": "single_source",
        "location_field": "loc_id",
        "time_field": "year",
        "time_granularity": "yearly",
        "default_limit": DEFAULT_LIMIT,
        "max_limit": MAX_LIMIT,
    }
del _sdg_i

# World Bank WDI category sources share the same yearly country-panel shape; each
# source stores its parquet as "<source_id>.parquet" under global/<source_id>/.
for _wb_source in (
    "wb_economy",
    "wb_environment",
    "wb_health",
    "wb_education",
    "wb_debt",
    "wb_infrastructure",
    "wb_social",
):
    SUPPORTED_DYNAMIC_SOURCES[_wb_source] = {
        "pack_id": "world_bank_wdi",
        "parquet_name": f"{_wb_source}.parquet",
        "query_mode": "single_source",
        "location_field": "loc_id",
        "time_field": "year",
        "time_granularity": "yearly",
        "default_limit": DEFAULT_LIMIT,
        "max_limit": MAX_LIMIT,
    }
del _wb_source

# NRI hazard member sources share the same county-static shape; each source
# stores one USA.parquet under countries/USA/<source_id>/.
for _nri_source in (
    "nri_avalanche",
    "nri_coastal_flood",
    "nri_cold_wave",
    "nri_drought",
    "nri_earthquake",
    "nri_extreme_heat",
    "nri_hail",
    "nri_hurricane",
    "nri_ice_storm",
    "nri_inland_flood",
    "nri_landslide",
    "nri_lightning",
    "nri_strong_wind",
    "nri_tornado",
    "nri_tsunami",
    "nri_volcano",
    "nri_wildfire",
    "nri_winter_weather",
):
    SUPPORTED_DYNAMIC_SOURCES[_nri_source] = {
        "pack_id": "nri",
        "parquet_name": "USA.parquet",
        "query_mode": "single_source_static",
        "location_field": "loc_id",
        "time_field": None,
        "time_granularity": None,
        "default_limit": 100,
        "max_limit": 1000,
    }
del _nri_source

# OWID topic sources share the same yearly country-panel shape and all belong to the
# single "owid" pack (alongside owid_co2 above), mirroring how un_sdg's "01".."17"
# entries belong to one pack. Each source's parquet is nested under
# global/owid/<base>/core/ (not the flat global/<source_id>/ layout used by wb_*
# above). The catalog's "path" field for each "<base>_core" source_id resolves to that
# nested core/ directory, so only the parquet filename needs to be specified here.
for _owid_core_base in (
    "owid_climate_emissions",
    "owid_education",
    "owid_energy",
    "owid_food_agriculture_nutrition",
    "owid_governance_conflict",
    "owid_health_mortality_disease",
    "owid_labor_gender",
    "owid_land_biodiversity",
    "owid_population_demography",
    "owid_poverty_inequality_income",
    "owid_water_sanitation",
):
    _owid_core_source_id = f"{_owid_core_base}_core"
    SUPPORTED_DYNAMIC_SOURCES[_owid_core_source_id] = {
        "pack_id": "owid",
        "parquet_name": f"{_owid_core_base}_core.parquet",
        "query_mode": "single_source",
        "location_field": "loc_id",
        "time_field": "year",
        "time_granularity": "yearly",
        "default_limit": DEFAULT_LIMIT,
        "max_limit": MAX_LIMIT,
    }
del _owid_core_base, _owid_core_source_id


API_SOURCE_SPECS: dict[str, ApiSourceSpec] = {
    CURRENCY_SOURCE_SPEC.source_id: CURRENCY_SOURCE_SPEC,
}

MIXED_TEMPORAL_TRANSITION_YEARS: dict[str, int | None] = {}
PLAIN_YEAR_RE = re.compile(r"^-?\d{1,6}$")


def _coerce_year_token(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value == int(value) else None
    text = str(value).strip()
    if not text:
        return None
    if PLAIN_YEAR_RE.match(text):
        try:
            return int(text)
        except ValueError:
            return None
    if len(text) >= 4 and text[:4].lstrip("-").isdigit():
        try:
            return int(text[:4])
        except ValueError:
            return None
    return None


def _extract_requested_year_bounds(time_filter: dict[str, Any] | None) -> tuple[int | None, int | None]:
    if not isinstance(time_filter, dict):
        return None, None
    exact_value = time_filter.get("value")
    start_value = time_filter.get("start")
    end_value = time_filter.get("end")
    if exact_value is None and "year" in time_filter:
        exact_value = time_filter.get("year")
    if start_value is None and "year_start" in time_filter:
        start_value = time_filter.get("year_start")
    if end_value is None and "year_end" in time_filter:
        end_value = time_filter.get("year_end")
    if exact_value is not None:
        exact_year = _coerce_year_token(exact_value)
        return exact_year, exact_year
    return _coerce_year_token(start_value), _coerce_year_token(end_value)


def _compute_contiguous_timestamp_suffix_start(parquet_path: Path) -> int | None:
    try:
        df = pd.read_parquet(parquet_path, columns=["year", "timestamp"])
    except Exception:
        return None
    if df.empty or "year" not in df.columns or "timestamp" not in df.columns:
        return None
    years = pd.to_numeric(df["year"], errors="coerce")
    timestamps = pd.to_datetime(df["timestamp"], errors="coerce")
    coverage = pd.DataFrame({"year": years, "has_timestamp": timestamps.notna()}).dropna(subset=["year"])
    if coverage.empty:
        return None
    grouped = coverage.groupby("year")["has_timestamp"].agg(["count", "sum"])
    full_years = sorted(int(idx) for idx, row in grouped.iterrows() if int(row["count"]) == int(row["sum"]))
    if not full_years:
        return None
    suffix_start = full_years[-1]
    previous = full_years[-1]
    for year in reversed(full_years[:-1]):
        if year == previous - 1:
            suffix_start = year
            previous = year
            continue
        break
    return int(suffix_start)


def _build_metric_specs_from_metadata(metadata: dict[str, Any] | None) -> dict[str, ApiMetricSpec]:
    metrics = metadata.get("metrics") if isinstance(metadata, dict) else {}
    if not isinstance(metrics, dict):
        return {}

    built: dict[str, ApiMetricSpec] = {}
    for metric_id, metric_info in metrics.items():
        metric_key = str(metric_id).strip()
        if not metric_key:
            continue
        description = ""
        if isinstance(metric_info, dict):
            description = (
                str(metric_info.get("description") or "").strip()
                or str(metric_info.get("name") or "").strip()
                or str(metric_info.get("unit") or "").strip()
            )
        else:
            description = str(metric_info).strip()
        built[metric_key] = ApiMetricSpec(
            metric_id=metric_key,
            column=metric_key,
            description=description,
        )
    return built


def _build_dynamic_source_spec(source_id: str) -> ApiSourceSpec | None:
    source_defaults = SUPPORTED_DYNAMIC_SOURCES.get(source_id)
    if source_defaults is None:
        return None

    metadata_source_id = str(source_defaults.get("metadata_source_id") or source_id)
    metadata = load_source_metadata(metadata_source_id) or {}
    metrics = _build_metric_specs_from_metadata(metadata)
    if str(source_defaults.get("query_mode") or "").strip() == "single_source_events":
        metrics.setdefault(
            "event_count",
            ApiMetricSpec(
                metric_id="event_count",
                column="event_count",
                description="Count of events matching the applied filters",
            ),
        )
    location_field = str(source_defaults["location_field"])
    temporal_coverage = metadata.get("temporal_coverage") if isinstance(metadata.get("temporal_coverage"), dict) else {}
    time_field = temporal_coverage.get("field") or source_defaults.get("time_field")
    time_granularity = normalize_time_granularity(
        temporal_coverage.get("granularity") or source_defaults.get("time_granularity")
    )
    source_path = Path(get_source_path(source_id))
    parquet_name = str(source_defaults["parquet_name"])
    primary_candidate = source_path / parquet_name
    wrapper_aggregate_path = None
    if source_path.name.lower() == "aggregates" and source_path.parent.name.lower() == "sources":
        aggregate_dir = resolve_aggregate_admin2_dir(source_path, data_root=DATA_ROOT)
        wrapper_aggregate_path = aggregate_dir / parquet_name

    local_pack_path = DATA_ROOT / "global" / str(source_defaults["pack_id"]) / parquet_name
    if wrapper_aggregate_path is not None and (wrapper_aggregate_path.exists() or parquet_available(wrapper_aggregate_path)):
        parquet_path = wrapper_aggregate_path
    elif primary_candidate.exists() or parquet_available(primary_candidate):
        parquet_path = primary_candidate
    elif local_pack_path.exists():
        parquet_path = local_pack_path
    else:
        parquet_path = wrapper_aggregate_path or None
    available_cols: set[str] = set()
    if isinstance(parquet_path, Path) and parquet_path.exists():
        try:
            available_cols = parquet_columns(parquet_path)
        except Exception:
            available_cols = set()
    elif parquet_path and parquet_available(parquet_path):
        available_cols = parquet_columns(parquet_path)
    normalized_time_field = str(time_field or "").strip() or None
    if normalized_time_field and normalized_time_field not in available_cols:
        fallback_time_field = None
        if "year" in available_cols and normalize_time_granularity(time_granularity) == "yearly":
            fallback_time_field = "year"
        elif "timestamp" in available_cols:
            fallback_time_field = "timestamp"
        elif "date" in available_cols:
            fallback_time_field = "date"
        if fallback_time_field:
            normalized_time_field = fallback_time_field
        else:
            normalized_time_field = None
    if not time_granularity and str(time_field or "").strip().lower() == "timestamp":
        time_granularity = "timestamp"
    location_filter_mode = str(
        metadata.get("location_filter_mode")
        or source_defaults.get("location_filter_mode")
        or "hierarchical_loc_id"
    ).strip()
    location_lookup_field_raw = metadata.get("location_lookup_field") or source_defaults.get("location_lookup_field")
    location_lookup_field = str(location_lookup_field_raw).strip() if location_lookup_field_raw else None

    filterable_fields = {location_field}
    sortable_fields = {location_field}
    if normalized_time_field:
        filterable_fields.add(normalized_time_field)
        sortable_fields.add(normalized_time_field)
    metadata_filterable = metadata.get("filterable_fields") if isinstance(metadata.get("filterable_fields"), list) else []
    for field in metadata_filterable:
        field_name = str(field).strip()
        if field_name:
            filterable_fields.add(field_name)
    # Auto-promote dimension columns to filterable fields. Sources that declare
    # a `dimensions` block (e.g. fairfax_lst's geo_level) want those columns
    # available as filters without having to repeat them in filterable_fields.
    metadata_dimensions = metadata.get("dimensions") if isinstance(metadata.get("dimensions"), dict) else {}
    for dim_key, dim_spec in metadata_dimensions.items():
        if isinstance(dim_spec, dict):
            column = str(dim_spec.get("column") or dim_key).strip()
            if column:
                filterable_fields.add(column)
    metadata_sortable = metadata.get("sortable_fields") if isinstance(metadata.get("sortable_fields"), list) else []
    for field in metadata_sortable:
        field_name = str(field).strip()
        if field_name:
            sortable_fields.add(field_name)
    sortable_fields.update(metrics.keys())

    return ApiSourceSpec(
        source_id=source_id,
        pack_id=str(metadata.get("pack_id") or source_defaults["pack_id"]),
        parquet_name=str(source_defaults["parquet_name"]),
        query_mode=str(source_defaults["query_mode"]),
        location_field=location_field,
        time_field=normalized_time_field,
        time_granularity=str(time_granularity) if time_granularity else None,
        metrics=metrics,
        filterable_fields=filterable_fields,
        sortable_fields=sortable_fields,
        location_filter_mode=location_filter_mode,
        location_lookup_field=location_lookup_field,
        default_limit=int(metadata.get("default_limit") or source_defaults["default_limit"]),
        max_limit=int(metadata.get("max_limit") or source_defaults["max_limit"]),
        metadata_source_id=metadata_source_id,
    )


def is_temporal_time_field(spec: ApiSourceSpec) -> bool:
    time_field = str(spec.time_field or "").strip().lower()
    if time_field in {"timestamp", "datetime", "date"}:
        return True
    return str(spec.time_granularity or "").strip().lower() in {
        "date",
        "daily",
        "weekly",
        "monthly",
        "event",
        "timestamp",
        "datetime",
    }


def normalize_time_value_for_response(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def get_api_source_spec(source_id: str) -> ApiSourceSpec | None:
    normalized_source_id = str(source_id or "").strip()
    cached = API_SOURCE_SPECS.get(normalized_source_id)
    if cached is not None:
        return cached
    built = _build_dynamic_source_spec(normalized_source_id)
    if built is not None:
        API_SOURCE_SPECS[normalized_source_id] = built
    return built


def get_mixed_temporal_transition_year(spec: ApiSourceSpec) -> int | None:
    cached = MIXED_TEMPORAL_TRANSITION_YEARS.get(spec.source_id, None)
    if spec.source_id in MIXED_TEMPORAL_TRANSITION_YEARS:
        return cached

    if normalize_time_granularity(spec.time_granularity) != "yearly":
        MIXED_TEMPORAL_TRANSITION_YEARS[spec.source_id] = None
        return None

    metadata = load_source_metadata(spec.metadata_source_id or spec.source_id) or {}
    if not metadata:
        local_metadata_path = (
            DATA_ROOT
            / "global"
            / "disasters"
            / spec.pack_id
            / "sources"
            / (spec.metadata_source_id or spec.source_id)
            / "metadata.json"
        )
        if local_metadata_path.exists():
            try:
                metadata = json.loads(local_metadata_path.read_text(encoding="utf-8"))
            except Exception:
                metadata = {}
    temporal_precision = metadata.get("temporal_precision") if isinstance(metadata.get("temporal_precision"), dict) else {}
    timestamp_coverage = temporal_precision.get("timestamp_coverage") if isinstance(temporal_precision, dict) else {}
    metadata_transition_year = _coerce_year_token(
        timestamp_coverage.get("complete_from_year") if isinstance(timestamp_coverage, dict) else None
    )
    if metadata_transition_year is not None:
        MIXED_TEMPORAL_TRANSITION_YEARS[spec.source_id] = metadata_transition_year
        return metadata_transition_year

    parquet_path = get_source_parquet_path(spec)
    try:
        available_cols = parquet_columns(parquet_path)
    except Exception:
        MIXED_TEMPORAL_TRANSITION_YEARS[spec.source_id] = None
        return None
    if "year" not in available_cols or "timestamp" not in available_cols:
        MIXED_TEMPORAL_TRANSITION_YEARS[spec.source_id] = None
        return None

    try:
        transition_year = _compute_contiguous_timestamp_suffix_start(parquet_path)
    except Exception:
        transition_year = None
    MIXED_TEMPORAL_TRANSITION_YEARS[spec.source_id] = transition_year
    return transition_year


def resolve_effective_time_spec(spec: ApiSourceSpec, time_filter: dict[str, Any] | None) -> ApiSourceSpec:
    if normalize_time_granularity(spec.time_granularity) != "yearly":
        return spec

    requested_granularity = normalize_time_granularity(
        time_filter.get("granularity") if isinstance(time_filter, dict) else None
    )
    if requested_granularity == "yearly":
        return spec

    transition_year = get_mixed_temporal_transition_year(spec)
    if transition_year is None:
        return spec

    requested_start_year, requested_end_year = _extract_requested_year_bounds(time_filter)
    if requested_start_year is None and requested_end_year is None:
        return spec

    lower_bound_year = requested_start_year if requested_start_year is not None else requested_end_year
    upper_bound_year = requested_end_year if requested_end_year is not None else requested_start_year
    if lower_bound_year is None or upper_bound_year is None:
        return spec
    if lower_bound_year < transition_year or upper_bound_year < transition_year:
        return spec

    return replace(spec, time_field="timestamp", time_granularity="timestamp")


def get_pack_source_ids(pack_id: str) -> list[str]:
    normalized_pack_id = str(pack_id or "").strip()
    if not normalized_pack_id:
        return []
    catalog = load_catalog()
    source_ids = []
    for source in catalog.get("sources", []):
        if str(source.get("pack_id") or "").strip() == normalized_pack_id:
            source_id = str(source.get("source_id") or "").strip()
            if source_id and source_id != "world_factbook_overlap":
                source_ids.append(source_id)
    return sorted(set(source_ids))


def _get_api_ready_pack_source_ids(pack_id: str) -> list[str]:
    source_ids: list[str] = []
    catalog = load_catalog()
    normalized_pack_id = str(pack_id or "").strip()
    for source in catalog.get("sources", []):
        if str(source.get("pack_id") or "").strip() != normalized_pack_id:
            continue
        if not bool(source.get("api_ready")):
            continue
        source_id = str(source.get("source_id") or "").strip()
        if source_id and get_api_source_spec(source_id) is not None:
            source_ids.append(source_id)
    return sorted(set(source_ids))


def normalize_time_granularity(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    alias_map = {
        "event": "timestamp",
        "events": "timestamp",
        "day": "daily",
        "daily": "daily",
        "date": "daily",
        "week": "weekly",
        "weekly": "weekly",
        "month": "monthly",
        "monthly": "monthly",
        "year": "yearly",
        "yearly": "yearly",
        "timestamp": "timestamp",
        "datetime": "timestamp",
    }
    return alias_map.get(normalized, normalized)


def resolve_pack_sources_for_metrics(pack_id: str, metrics: list[str]) -> dict[str, Any]:
    normalized_pack_id = str(pack_id or "").strip()
    normalized_metrics = [str(metric).strip() for metric in (metrics or []) if str(metric).strip()]
    if not normalized_pack_id or not normalized_metrics:
        return {
            "pack_id": normalized_pack_id,
            "requested_metrics": normalized_metrics,
            "resolution": "invalid_request",
            "selected_source_id": None,
            "required_sources": [],
            "metrics_by_source": {},
            "unknown_metrics": normalized_metrics,
        }

    candidate_sources = _get_api_ready_pack_source_ids(normalized_pack_id)
    if not candidate_sources:
        return {
            "pack_id": normalized_pack_id,
            "requested_metrics": normalized_metrics,
            "resolution": "unknown_pack_sources",
            "selected_source_id": None,
            "required_sources": [],
            "metrics_by_source": {},
            "unknown_metrics": normalized_metrics,
        }
    per_source_metadata: dict[str, dict[str, Any]] = {}
    per_source_metric_keys: dict[str, set[str]] = {}
    metric_to_sources: dict[str, list[str]] = {}
    for source_id in candidate_sources:
        metadata = load_source_metadata(source_id) or {}
        per_source_metadata[source_id] = metadata
        # Use the resolved source spec's metrics, which include synthetic metrics
        # such as event_count injected for event sources. Reading raw
        # metadata["metrics"] here misses them, so a pack-path query for
        # event_count was wrongly rejected as metric_not_available even though
        # the source-path validate_metrics accepts it.
        spec = get_api_source_spec(source_id)
        if spec is not None and spec.metrics:
            metric_keys = {str(key).strip() for key in spec.metrics.keys() if str(key).strip()}
        else:
            metrics_map = metadata.get("metrics") if isinstance(metadata.get("metrics"), dict) else {}
            metric_keys = {str(key).strip() for key in metrics_map.keys() if str(key).strip()}
        per_source_metric_keys[source_id] = metric_keys
        for metric_key in metric_keys:
            metric_to_sources.setdefault(metric_key, []).append(source_id)

    unknown_metrics = [metric for metric in normalized_metrics if metric not in metric_to_sources]
    if unknown_metrics:
        return {
            "pack_id": normalized_pack_id,
            "requested_metrics": normalized_metrics,
            "resolution": "unknown_metrics",
            "selected_source_id": None,
            "required_sources": [],
            "metrics_by_source": {},
            "unknown_metrics": unknown_metrics,
        }

    source_scores: list[tuple[float, str]] = []
    for source_id in candidate_sources:
        metadata = per_source_metadata.get(source_id) or {}
        metric_keys = per_source_metric_keys.get(source_id, set())
        if any(metric not in metric_keys for metric in normalized_metrics):
            continue
        metrics_map = metadata.get("metrics") if isinstance(metadata.get("metrics"), dict) else {}
        score = 0.0
        for metric in normalized_metrics:
            metric_info = metrics_map.get(metric)
            if isinstance(metric_info, dict):
                density = metric_info.get("density")
                if isinstance(density, (int, float)):
                    score += float(density)
        source_scores.append((score, source_id))

    if source_scores:
        source_scores.sort(key=lambda item: (-item[0], item[1]))
        return {
            "pack_id": normalized_pack_id,
            "requested_metrics": normalized_metrics,
            "resolution": "single_source",
            "selected_source_id": source_scores[0][1],
            "required_sources": [source_scores[0][1]],
            "metrics_by_source": {source_scores[0][1]: normalized_metrics},
            "unknown_metrics": [],
        }

    metrics_by_source: dict[str, list[str]] = {}
    for metric in normalized_metrics:
        candidate_metric_sources = metric_to_sources.get(metric, [])
        ranked_sources: list[tuple[float, str]] = []
        for source_id in candidate_metric_sources:
            metadata = per_source_metadata.get(source_id) or {}
            metric_info = (metadata.get("metrics") or {}).get(metric)
            density = None
            if isinstance(metric_info, dict):
                density = metric_info.get("density")
            ranked_sources.append((float(density) if isinstance(density, (int, float)) else -1.0, source_id))
        ranked_sources.sort(key=lambda item: (-item[0], item[1]))
        chosen_source = ranked_sources[0][1]
        metrics_by_source.setdefault(chosen_source, []).append(metric)

    required_sources = sorted(metrics_by_source.keys())
    return {
        "pack_id": normalized_pack_id,
        "requested_metrics": normalized_metrics,
        "resolution": "multi_source_required",
        "selected_source_id": None,
        "required_sources": required_sources,
        "metrics_by_source": metrics_by_source,
        "unknown_metrics": [],
    }


def _resolve_default_pack_source(
    pack_id: str,
    *,
    requested_granularity: str | None = None,
) -> dict[str, Any]:
    normalized_pack_id = str(pack_id or "").strip()
    normalized_granularity = normalize_time_granularity(requested_granularity)

    if normalized_pack_id == "currency":
        granularity_to_source = {
            "daily": "fx_usd_historical",
            "weekly": "fx_usd_historical_weekly",
            "monthly": "fx_usd_historical_monthly",
        }
        selected_source_id = granularity_to_source.get(normalized_granularity or "daily")
        spec = get_api_source_spec(selected_source_id) if selected_source_id else None
        if spec is None:
            return {
                "pack_id": normalized_pack_id,
                "requested_metrics": [],
                "resolution": "unsupported_granularity",
                "selected_source_id": None,
                "required_sources": [],
                "metrics_by_source": {},
                "unknown_metrics": [],
                "requested_granularity": normalized_granularity,
                "supported_granularities": sorted(granularity_to_source.keys()),
            }
        return {
            "pack_id": normalized_pack_id,
            "requested_metrics": [],
            "resolution": "default_source",
            "selected_source_id": selected_source_id,
            "required_sources": [selected_source_id],
            "metrics_by_source": {selected_source_id: []},
            "unknown_metrics": [],
            "requested_granularity": normalized_granularity,
            "supported_granularities": sorted(granularity_to_source.keys()),
        }

    candidate_sources = _get_api_ready_pack_source_ids(normalized_pack_id)
    if not candidate_sources:
        return {
            "pack_id": normalized_pack_id,
            "requested_metrics": [],
            "resolution": "unknown_pack_sources",
            "selected_source_id": None,
            "required_sources": [],
            "metrics_by_source": {},
            "unknown_metrics": [],
            "requested_granularity": normalized_granularity,
        }

    if len(candidate_sources) == 1:
        selected_source_id = candidate_sources[0]
        return {
            "pack_id": normalized_pack_id,
            "requested_metrics": [],
            "resolution": "default_source",
            "selected_source_id": selected_source_id,
            "required_sources": [selected_source_id],
            "metrics_by_source": {selected_source_id: []},
            "unknown_metrics": [],
            "requested_granularity": normalized_granularity,
        }

    ranked_sources: list[tuple[int, str]] = []
    for source_id in candidate_sources:
        spec = get_api_source_spec(source_id)
        if spec is None:
            continue
        score = {
            "single_source_events": 40,
            "single_source": 30,
            "single_source_static": 20,
        }.get(str(spec.query_mode or "").strip(), 0)
        ranked_sources.append((score, source_id))

    ranked_sources.sort(key=lambda item: (-item[0], item[1]))
    if not ranked_sources:
        return {
            "pack_id": normalized_pack_id,
            "requested_metrics": [],
            "resolution": "unknown_pack_sources",
            "selected_source_id": None,
            "required_sources": [],
            "metrics_by_source": {},
            "unknown_metrics": [],
            "requested_granularity": normalized_granularity,
        }

    best_score = ranked_sources[0][0]
    best_sources = [source_id for score, source_id in ranked_sources if score == best_score]
    if len(best_sources) != 1:
        return {
            "pack_id": normalized_pack_id,
            "requested_metrics": [],
            "resolution": "ambiguous_default_source",
            "selected_source_id": None,
            "required_sources": sorted(best_sources),
            "metrics_by_source": {},
            "unknown_metrics": [],
            "requested_granularity": normalized_granularity,
        }

    selected_source_id = best_sources[0]
    return {
        "pack_id": normalized_pack_id,
        "requested_metrics": [],
        "resolution": "default_source",
        "selected_source_id": selected_source_id,
        "required_sources": [selected_source_id],
        "metrics_by_source": {selected_source_id: []},
        "unknown_metrics": [],
        "requested_granularity": normalized_granularity,
    }


def resolve_pack_source_for_query(
    pack_id: str,
    metrics: list[str],
    *,
    requested_granularity: str | None = None,
) -> dict[str, Any]:
    normalized_metrics = [str(metric).strip() for metric in (metrics or []) if str(metric).strip()]
    if not normalized_metrics:
        return _resolve_default_pack_source(
            pack_id,
            requested_granularity=requested_granularity,
        )

    base = resolve_pack_sources_for_metrics(pack_id, metrics)
    if base.get("resolution") != "single_source":
        base["requested_granularity"] = normalize_time_granularity(requested_granularity)
        return base

    normalized_pack_id = str(pack_id or "").strip()
    normalized_granularity = normalize_time_granularity(requested_granularity)
    base["requested_granularity"] = normalized_granularity
    if normalized_pack_id != "currency" or not normalized_granularity:
        return base

    granularity_to_source = {
        "daily": "fx_usd_historical",
        "weekly": "fx_usd_historical_weekly",
        "monthly": "fx_usd_historical_monthly",
    }
    selected_source_id = granularity_to_source.get(normalized_granularity)
    if not selected_source_id:
        base["resolution"] = "unsupported_granularity"
        base["selected_source_id"] = None
        base["required_sources"] = []
        base["metrics_by_source"] = {}
        base["supported_granularities"] = sorted(granularity_to_source.keys())
        return base

    spec = get_api_source_spec(selected_source_id)
    if spec is None:
        base["resolution"] = "unsupported_granularity"
        base["selected_source_id"] = None
        base["required_sources"] = []
        base["metrics_by_source"] = {}
        base["supported_granularities"] = sorted(granularity_to_source.keys())
        return base

    base["selected_source_id"] = selected_source_id
    base["required_sources"] = [selected_source_id]
    base["metrics_by_source"] = {selected_source_id: [str(metric).strip() for metric in (metrics or []) if str(metric).strip()]}
    base["supported_granularities"] = sorted(granularity_to_source.keys())
    return base


def get_source_parquet_path(spec: ApiSourceSpec) -> Path:
    local_parquet_path = getattr(spec, "local_parquet_path", None)
    if local_parquet_path:
        return Path(local_parquet_path)

    source_dir = Path(get_source_path(spec.source_id))
    primary_path = source_dir / spec.parquet_name
    if primary_path.exists():
        return primary_path

    if source_dir.name.lower() == "aggregates" and source_dir.parent.name.lower() == "sources":
        aggregate_dir = resolve_aggregate_admin2_dir(source_dir, data_root=DATA_ROOT)
        aggregate_primary_path = aggregate_dir / spec.parquet_name
        if aggregate_primary_path.exists():
            return aggregate_primary_path
        if str(spec.parquet_name or "").strip().lower() == "yearly.parquet":
            return aggregate_primary_path

    if spec.metadata_source_id and spec.metadata_source_id != spec.source_id:
        metadata_source_dir = Path(get_source_path(spec.metadata_source_id))
        metadata_primary_path = metadata_source_dir / spec.parquet_name
        if metadata_primary_path.exists():
            return metadata_primary_path

    disaster_source_path = DATA_ROOT / "global" / "disasters" / spec.pack_id / "sources" / spec.source_id / spec.parquet_name
    if disaster_source_path.exists():
        return disaster_source_path
    if spec.metadata_source_id and spec.metadata_source_id != spec.source_id:
        disaster_metadata_path = (
            DATA_ROOT / "global" / "disasters" / spec.pack_id / "sources" / spec.metadata_source_id / spec.parquet_name
        )
        if disaster_metadata_path.exists():
            return disaster_metadata_path

    # API sources may execute from a pack-shaped folder before local catalog.json
    # is present. Prefer a direct pack fallback over assuming source_id == folder.
    pack_path = DATA_ROOT / "global" / spec.pack_id / spec.parquet_name
    if pack_path.exists():
        return pack_path

    return primary_path


def get_api_source_columns(spec: ApiSourceSpec) -> set[str]:
    parquet_path = get_source_parquet_path(spec)
    return parquet_columns(parquet_path)


def get_api_source_time_bounds(spec: ApiSourceSpec) -> tuple[Any | None, Any | None]:
    if not spec.time_field:
        return None, None
    parquet_path = get_source_parquet_path(spec)
    available_cols = parquet_columns(parquet_path)
    if spec.time_field not in available_cols:
        return None, None

    time_col = quote_ident(spec.time_field)
    df = run_df(
        f"SELECT MIN({time_col}) AS min_value, MAX({time_col}) AS max_value FROM read_parquet(?)",
        [path_to_uri(parquet_path)],
    )
    if df.empty:
        return None, None

    row = df.iloc[0]
    min_value = row.get("min_value")
    max_value = row.get("max_value")
    if is_temporal_time_field(spec):
        return (
            normalize_time_value_for_response(min_value),
            normalize_time_value_for_response(max_value),
        )
    return (
        int(min_value) if min_value is not None else None,
        int(max_value) if max_value is not None else None,
    )


def api_source_ready(spec: ApiSourceSpec) -> bool:
    parquet_path = get_source_parquet_path(spec)
    return parquet_available(parquet_path)


def execute_dataset_query(
    spec: ApiSourceSpec,
    *,
    select_columns: list[str],
    exact_filters: dict[str, Any] | None = None,
    in_filters: dict[str, list[Any]] | None = None,
    hierarchical_prefix_filters: dict[str, list[str]] | None = None,
    compare_filters: list[tuple[str, str, Any]] | None = None,
    sort_items: list[tuple[str, str]] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    from .duckdb_helpers import _normalize_ts_for_duckdb

    parquet_path = get_source_parquet_path(spec)
    available_cols = parquet_columns(parquet_path)
    synthetic_event_count = "event_count" in {spec.metrics[column].column for column in spec.metrics if column == "event_count"}
    requested_event_count_only = (
        synthetic_event_count
        and len(select_columns) >= 1
        and "event_count" in [col for col in select_columns if col == "event_count"]
    )
    selected = [col for col in select_columns if col in available_cols]
    if not selected and not requested_event_count_only:
        return []

    groupable_selected = [col for col in selected if col in available_cols]
    where_parts: list[str] = []
    params: list[Any] = [path_to_uri(parquet_path)]
    having_parts: list[str] = []
    having_params: list[Any] = []

    for col, value in (exact_filters or {}).items():
        if col in available_cols and value is not None:
            if col == spec.time_field and is_temporal_time_field(spec):
                where_parts.append(f"CAST({quote_ident(col)} AS TIMESTAMP) = CAST(? AS TIMESTAMP)")
                params.append(_normalize_ts_for_duckdb(str(value)))
            else:
                where_parts.append(f"{quote_ident(col)} = ?")
                params.append(value)

    for col, values in (in_filters or {}).items():
        normalized_values = [value for value in (values or []) if value is not None]
        if col in available_cols and normalized_values:
            normalized_upper_values = [str(value).upper() for value in normalized_values]
            placeholders = ", ".join("?" for _ in normalized_upper_values)
            where_parts.append(f"upper({quote_ident(col)}) IN ({placeholders})")
            params.extend(normalized_upper_values)

    for col, prefixes in (hierarchical_prefix_filters or {}).items():
        normalized_prefixes = [str(value).strip() for value in (prefixes or []) if str(value).strip()]
        if col not in available_cols or not normalized_prefixes:
            continue
        exact_or_descendant_parts: list[str] = []
        for prefix in normalized_prefixes:
            prefix_upper = prefix.upper()
            exact_or_descendant_parts.append(f"upper({quote_ident(col)}) = ?")
            params.append(prefix_upper)
            exact_or_descendant_parts.append(f"starts_with(upper({quote_ident(col)}), ?)")
            params.append(f"{prefix_upper}-")
        where_parts.append("(" + " OR ".join(exact_or_descendant_parts) + ")")

    for col, op, value in (compare_filters or []):
        if value is None:
            continue
        if op not in {"=", "!=", ">", ">=", "<", "<="}:
            continue
        if col == "event_count":
            having_parts.append(f"COUNT(*) {op} ?")
            having_params.append(value)
        elif col == spec.time_field and col in available_cols and is_temporal_time_field(spec):
            where_parts.append(f"CAST({quote_ident(col)} AS TIMESTAMP) {op} CAST(? AS TIMESTAMP)")
            params.append(_normalize_ts_for_duckdb(str(value)))
        elif col in available_cols:
            where_parts.append(f"{quote_ident(col)} {op} ?")
            params.append(value)

    order_parts: list[str] = []
    for sort_field, sort_direction in (sort_items or []):
        direction = "DESC" if str(sort_direction).lower() == "desc" else "ASC"
        if sort_field == "event_count":
            order_parts.append(f"event_count {direction} NULLS LAST")
        elif sort_field and sort_field in available_cols:
            order_parts.append(f"{quote_ident(sort_field)} {direction} NULLS LAST")

    if requested_event_count_only:
        parquet_uri = params[0]
        where_params = params[1:]
        group_by_columns = [col for col in groupable_selected if col != "event_count"]
        select_parts: list[str] = []
        group_by_ordinals: list[str] = []
        event_count_params: list[Any] = []
        group_index = 1
        for col in group_by_columns:
            if col == spec.location_field and (hierarchical_prefix_filters or {}).get(col):
                prefixes = [str(value).strip().upper() for value in (hierarchical_prefix_filters or {}).get(col, []) if str(value).strip()]
                if prefixes:
                    case_parts = ["CASE"]
                    for prefix in prefixes:
                        case_parts.append(f"WHEN upper({quote_ident(col)}) = ? OR starts_with(upper({quote_ident(col)}), ?) THEN ?")
                        event_count_params.extend([prefix, f"{prefix}-", prefix])
                    case_parts.append(f"ELSE upper({quote_ident(col)}) END AS {quote_ident(col)}")
                    select_parts.append(" ".join(case_parts))
                    group_by_ordinals.append(str(group_index))
                    group_index += 1
                    continue
            select_parts.append(quote_ident(col))
            group_by_ordinals.append(str(group_index))
            group_index += 1
        select_parts.append("COUNT(*) AS event_count")
        sql = f"SELECT {', '.join(select_parts)} FROM read_parquet(?)"
        aggregate_params: list[Any] = [*event_count_params, parquet_uri, *where_params]
        if where_parts:
            sql += " WHERE " + " AND ".join(where_parts)
        if group_by_columns:
            sql += " GROUP BY " + ", ".join(group_by_ordinals)
        if having_parts:
            sql += " HAVING " + " AND ".join(having_parts)
            aggregate_params.extend(having_params)
        if order_parts:
            sql += " ORDER BY " + ", ".join(order_parts)
        if limit is not None and limit > 0:
            sql += " LIMIT ?"
            aggregate_params.append(limit)
        df = run_df(sql, aggregate_params)
        if df.empty:
            return []
        return df.to_dict("records")

    select_expr = ", ".join(quote_ident(col) for col in selected)
    sql = f"SELECT {select_expr} FROM read_parquet(?)"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    if order_parts:
        sql += " ORDER BY " + ", ".join(order_parts)

    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)

    df = run_df(sql, params)
    if df.empty:
        return []
    return df.to_dict("records")
