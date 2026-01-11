# Data Import Reference

Quick reference for importing new data sources using the unified converter system.

For detailed documentation see:
- [data_pipeline.md](data_pipeline.md) - Full pipeline documentation (schemas, metadata, folder structure)
- [DISASTER_DISPLAY.md](DISASTER_DISPLAY.md) - Disaster event visualization and animation
- [GEOMETRY.md](GEOMETRY.md) - Geometry system, loc_id specification

---

## Data Architecture Philosophy

All data in this system is designed to be **interoperable**. Conceptually, everything fits into one unified table:

```
| loc_id        | year | pop    | gdp    | earthquakes | drought_weeks | ... |
|---------------|------|--------|--------|-------------|---------------|-----|
| USA-CA-6037   | 2020 | 10.0M  | 500B   | 12          | 8             | ... |
| USA-CA-6037   | 2021 | 9.8M   | 520B   | 8           | 15            | ... |
| CAN-ON-35001  | 2020 | 50000  | 2B     | 0           | NULL          | ... |
| AUS-NSW-10050 | 2020 | 25000  | 1B     | 1           | NULL          | ... |
```

**Key principle**: `(loc_id, year)` is the universal join key. All metrics are columns.

**Note on loc_id sources**: Some countries have multiple loc_id systems:
- **Country-specific**: Official boundaries (ABS LGAs, StatsCan CSDs, NUTS regions) stored in `countries/{ISO}/geometry.parquet`
- **Crosswalk files**: Map alternate loc_ids to GADM loc_ids via `countries/{ISO}/crosswalk.json`
- **GADM fallback**: Global boundaries in `geometry/{ISO}.parquet`

**Three-tier geometry fallback system**:
1. **Direct match in country geometry**: loc_id matches `countries/{ISO}/geometry.parquet` -> use it
2. **Crosswalk translation**: loc_id in `crosswalk.json` -> translate to GADM loc_id -> use `geometry/{ISO}.parquet`
3. **Direct GADM fallback**: loc_id is already GADM-style -> use `geometry/{ISO}.parquet` directly

This means loc_ids may differ between sources, but the system resolves them to geometry automatically.

This enables:
- **Column portability**: Move population from census to geometry file
- **Dataset merging**: Combine drought aggregates with rainfall aggregates
- **Custom exports**: Future admin dashboard lets users pick locations + years + metrics
- **No overlaps**: loc_id ensures uniqueness across all 400K+ GADM locations

---

## New Source Checklist

When importing a new data source, verify these requirements:

| Check | Requirement | Why |
|-------|-------------|-----|
| 1. loc_id match | All location codes use `{ISO3}[-{admin1}[-{admin2}]]` format | Universal join key |
| 2. Long format | Time-series uses rows (loc_id, year, metric), NOT columns (loc_id, metric_2020, metric_2021) | Enables time slider, joins |
| 3. Column analysis | Decide which metrics to keep, rename, or combine | Clean schema |
| 4. No duplicates | One row per (loc_id, year) in aggregates | Clean joins |
| 5. Null handling | Missing data as NULL, not 0 or special values | Accurate analysis |
| 6. No redundant cols | Remove state, county, name, FIPS columns | Derivable from loc_id |
| 7. Source registry | Add to `build/catalog/source_registry.py` with URL, license, description | Clickable source links in UI |

**IMPORTANT: Source Registry Entry**

Every new source MUST be registered in `build/catalog/source_registry.py` before running the metadata generator. The registry provides:
- `source_name` - Human-readable name shown in UI
- `source_url` - Clickable link to original data source
- `license` - Data license information
- `description` - Brief description of the dataset
- `category` - Data category (hazard, demographic, environment, etc.)
- `topic_tags` / `keywords` - For search and discovery

Without a registry entry, metadata will have empty/default values and source links won't work in the UI.

**Important: Column Rules**

Output parquet should ONLY contain:
- `loc_id` - Location identifier
- `year` - Time dimension
- `[numeric metrics]` - Data columns

Do NOT include:
- `state`, `county`, `name` - Derivable from loc_id (e.g., `USA-NC-001` -> state is `NC`)
- `STCOFIPS`, `GEOID`, `fips` - Redundant with loc_id
- `STATE`, `COUNTY`, `region` - Stored in geometry, not data

**Exception**: Event data (earthquakes, hurricanes) uses different schema with `event_id`, `timestamp`, etc. See [Unified Event Schema](data_pipeline.md#event-data-format) for required columns and naming conventions.

---

## Adding a New Source

**Step 1: Find a similar existing converter to copy**

Before creating anything new, identify which existing converter best matches your data:

| If your data has... | Copy this converter |
|---------------------|---------------------|
| Point events with lat/lon (earthquakes, incidents) | `convert_usgs_earthquakes.py` or `convert_canada_earthquakes.py` |
| Track/trajectory data (storms, paths) | `convert_hurdat2.py` |
| Multiple related tables (locations + events) | `convert_volcano.py` or `convert_tsunami.py` |
| Polygon/perimeter data (fire boundaries, zones) | `convert_mtbs.py` |
| Pre-aggregated statistics (no events file) | Create minimal converter (see below) |

**Step 2: Modify the copy for your source**

1. Copy the chosen converter to `data_converters/converters/convert_{source}.py`
2. Update configuration paths (`RAW_DATA_DIR`, `OUTPUT_DIR`, `SOURCE_ID`)
3. Modify `load_raw_data()` for your input format
4. Adjust column mappings in `create_events_dataframe()` and `create_aggregates()`
5. Update statistics/metadata sections

**Step 3: Register and finalize**

1. Register in `build/catalog/source_registry.py` for auto-finalization
2. Run converter to generate parquet files
3. Verify output with `finalize_source`

---

## Base Utilities

All converters import from `data_converters/base/`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_converters.base import (
    # Constants
    USA_STATE_FIPS,          # {'01': 'AL', '02': 'AK', ...}
    CAN_PROVINCE_ABBR,       # {'10': 'NL', '11': 'PE', ...}
    TERRITORIAL_WATERS_DEG,  # 0.2 (~12 nautical miles)

    # Geo utilities
    load_geometry_parquet,   # Load county/division boundaries
    spatial_join_3pass,      # Full 3-pass geocoding
    create_point_gdf,        # Create GeoDataFrame from lat/lon
    get_water_body_loc_id,   # Assign ocean/sea codes

    # Parquet utilities
    save_parquet,            # Standardized parquet saving
)
from build.catalog.finalize_source import finalize_source
```

---

## Admin Levels

All data uses standardized admin levels that work across all countries:

| Level | Description | Examples |
|-------|-------------|----------|
| admin_0 | Country | USA, CAN, AUS, DEU |
| admin_1 | State/Province/Region | USA-CA, CAN-BC, AUS-NSW, DEU-BY |
| admin_2 | County/District/LGA | USA-CA-6037, CAN-BC-5915, AUS-NSW-10050 |

This standardization means:
- **No country-specific terminology** in code (not "county", "LGA", "CSD", "NUTS3")
- **Consistent API** - `admin_level=2` works everywhere
- **Scalable** - Works for any country without code changes

---

## loc_id Format

All locations use standardized loc_id format based on admin levels:

| Admin Level | Format | Example |
|-------------|--------|---------|
| admin_0 | `{ISO3}` | `USA`, `CAN`, `AUS` |
| admin_1 | `{ISO3}-{code}` | `USA-CA`, `CAN-BC`, `AUS-NSW` |
| admin_2 | `{ISO3}-{code}-{code}` | `USA-CA-6037`, `CAN-BC-5915` |
| Water | `X{code}` | `XOP` (Pacific), `XOA` (Atlantic) |

**Water Body Codes:**
- `XOP` - Pacific Ocean
- `XOA` - Atlantic Ocean
- `XON` - Arctic Ocean
- `XOI` - Indian Ocean
- `XSG` - Gulf of Mexico / Gulf of St. Lawrence
- `XSC` - Caribbean Sea
- `XSH` - Hudson Bay
- `XSB` - Bering Sea

---

## Geometry File Standards

When creating country-specific geometry files in `countries/{ISO}/geometry.parquet`, use the **same column names** as the GADM files in `geometry/{ISO}.parquet`:

**Required columns (must match exactly):**

| Column | Type | Description |
|--------|------|-------------|
| `loc_id` | string | Location identifier (e.g., `AUS-NSW-10050`) |
| `name` | string | Human-readable name |
| `admin_level` | int | Admin level (0=country, 1=state, 2=county) |
| `parent_id` | string | Parent location's loc_id |
| `geometry` | string | GeoJSON string (e.g., `{"type": "Polygon", ...}`) |

**IMPORTANT**:
- Use `parent_id`, NOT `parent_loc_id`. This ensures consistent column naming across all geometry sources and prevents join failures.
- Use **GeoJSON strings**, NOT WKB bytes. WKB bytes cause JSON serialization errors at runtime.

**Optional columns (included in GADM files):**
- `centroid_lon`, `centroid_lat` - Centroid coordinates
- `bbox_min_lon`, `bbox_min_lat`, `bbox_max_lon`, `bbox_max_lat` - Bounding box
- `children_count`, `descendants_count` - Hierarchy counts
- `has_polygon` - Boolean for geometry presence

**Geometry Priority (3-tier fallback):**
The system resolves geometry in this order:
1. `countries/{ISO}/geometry.parquet` - Country-specific (preferred, matches data loc_ids like NUTS, ABS LGA)
2. `countries/{ISO}/crosswalk.json` - If present, translates loc_id to GADM format, then uses GADM geometry
3. `geometry/{ISO}.parquet` - GADM fallback (global coverage)

This allows:
- Country-specific sources (ABS, StatsCan, Eurostat) to use their official boundaries
- Data with alternate loc_id systems (NUTS codes) to map to GADM geometry via crosswalk
- Fallback to GADM for countries without custom geometry

---

## Geometry Simplification Requirements

**All geometry MUST be simplified before import.** Raw geometry files (TIGER, GADM, etc.) contain far more detail than needed for web display and cause:
- Slow JSON parsing in `df_to_geojson()` (each geometry is parsed from JSON string)
- Large file sizes and slow network transfers
- Slow frontend rendering

### Required Tolerances by Admin Level

| Level | Admin | Tolerance | Precision | Use Case |
|-------|-------|-----------|-----------|----------|
| Countries | 0 | 0.01 | ~1 km | World map view |
| States/Regions | 1 | 0.001 | ~100 m | Country zoom |
| Counties | 2 | 0.001 | ~100 m | State zoom |
| ZCTAs | 3 | 0.0001 | ~10 m | County zoom |
| Census Tracts | 4 | 0.0001 | ~10 m | City zoom |
| Block Groups | 5 | 0.00005 | ~5 m | Neighborhood zoom |
| Blocks | 6 | 0.00001 | ~1 m | Street zoom |

### Simplification Code

Using shapely (recommended):

```python
from shapely import simplify
from shapely.geometry import shape, mapping
import json

def simplify_geometry(geom_json, tolerance):
    """Simplify a GeoJSON geometry string."""
    geom = shape(json.loads(geom_json))
    simplified = simplify(geom, tolerance, preserve_topology=True)
    return json.dumps(mapping(simplified))

# Apply to DataFrame
TOLERANCE = 0.0001  # Set based on admin level
df['geometry'] = df['geometry'].apply(lambda g: simplify_geometry(g, TOLERANCE))
```

Using geopandas:

```python
import geopandas as gpd

gdf = gpd.read_file("raw_geometry.shp")
gdf['geometry'] = gdf['geometry'].simplify(tolerance=0.0001, preserve_topology=True)
```

### Size Impact Examples

| Level | Before | After | Reduction |
|-------|--------|-------|-----------|
| Countries (0.01) | 31 MB | 7.8 MB | 75% |
| Counties (0.001) | 63 MB | 30 MB | 53% |
| Blocks (0.00001) | 351 MB | ~200 MB | ~43% |

### Verification

After simplification, verify the geometry still looks correct at the intended zoom level. Over-simplified geometry will have jagged edges or missing details.

**See also**: [GEOMETRY.md](GEOMETRY.md#geometry-simplification) for detailed size impact analysis.

**Crosswalk file format** (`countries/{ISO}/crosswalk.json`):
```json
{
  "source_system": "nuts",
  "target_system": "gadm",
  "mappings": {
    "FRA-FR1": "FRA-IF",
    "FRA-FRB": "FRA-CE"
  }
}
```

---

## Standard Converter Structure

Every converter follows this pattern:

```python
"""
Convert {SOURCE} data to parquet format.

Creates output files:
1. events.parquet - Individual events
2. {COUNTRY}.parquet - Region-year aggregated statistics

Uses unified base utilities for spatial join and water body assignment.

Usage:
    python convert_{source}.py
"""

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/{source}")
GEOMETRY_PATH = Path("C:/Users/Bryan/Desktop/county-map-data/geometry/{COUNTRY}.parquet")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/{COUNTRY}/{source_id}")
SOURCE_ID = "{source_id}"


def load_geometry():
    """Load boundaries using base utility."""
    return load_geometry_parquet(GEOMETRY_PATH, admin_level=2, geometry_format='geojson')


def load_raw_data():
    """Load source-specific raw data."""
    # Custom parsing logic here
    pass


def process_events(df, geometry_gdf):
    """Process events with spatial join."""
    # Create point geometries
    gdf = create_point_gdf(df, lat_col='latitude', lon_col='longitude')

    # 3-pass spatial join
    gdf = spatial_join_3pass(
        gdf,
        geometry_gdf,
        loc_id_col='loc_id',
        water_body_region='usa'  # or 'canada', 'global'
    )
    return gdf


def create_events_dataframe(gdf):
    """Create standardized events DataFrame."""
    # Select and rename columns
    pass


def create_aggregates(events):
    """Create region-year aggregates."""
    # Group by loc_id, year and aggregate
    pass


def main():
    print("=" * 60)
    print("{Source} Converter")
    print("=" * 60)

    # Load geometry
    geometry_gdf = load_geometry()

    # Load and process data
    df = load_raw_data()
    gdf = process_events(df, geometry_gdf)

    # Create outputs
    events = create_events_dataframe(gdf)
    aggregates = create_aggregates(events)

    # Save outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    events_path = OUTPUT_DIR / "events.parquet"
    save_parquet(events, events_path, description="events")

    agg_path = OUTPUT_DIR / f"{COUNTRY}.parquet"
    save_parquet(aggregates, agg_path, description="aggregates")

    # Finalize
    print("\n" + "=" * 60)
    print("Finalizing source...")
    print("=" * 60)

    try:
        finalize_source(
            parquet_path=str(agg_path),
            source_id=SOURCE_ID,
            events_parquet_path=str(events_path)
        )
    except ValueError as e:
        print(f"  Note: {e}")
        print(f"  Add '{SOURCE_ID}' to source_registry.py to enable auto-finalization")

    print("\n" + "=" * 60)
    print("COMPLETE!")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

## 3-Pass Spatial Join

The `spatial_join_3pass()` function handles all geocoding:

1. **Pass 1: Point-in-polygon** - Strict match for points inside boundaries
2. **Pass 2: Nearest neighbor** - Match coastal points within territorial waters (0.2 deg / ~12nm)
3. **Pass 3: Water body codes** - Assign ocean/sea codes for offshore points

```python
gdf = spatial_join_3pass(
    points_gdf,              # GeoDataFrame with point geometries
    polygons_gdf,            # GeoDataFrame with boundaries (must have loc_id)
    loc_id_col='loc_id',     # Column name for location ID
    territorial_waters_deg=0.2,  # Distance threshold for pass 2
    water_body_region='usa', # 'usa', 'canada', 'australia', 'global'
    verbose=True             # Print progress
)
```

---

## Output File Structure

```
countries/{COUNTRY}/{source_id}/
    events.parquet       # Individual events (optional)
    {COUNTRY}.parquet    # Region-year aggregates (required)
    metadata.json        # Auto-generated by finalize_source
```

**events.parquet** - Individual records (optional for pre-aggregated data):

> **IMPORTANT**: All event files MUST follow the [Unified Event Schema](data_pipeline.md#event-data-format) for live/historical compatibility.

**Required core columns** (use these exact names):
- `event_id` - Unique identifier for the event
- `timestamp` - Event datetime (NOT `time`, `event_date`, or `ignition_date`)
- `latitude` - Event latitude (NOT `lat` or `centroid_lat`)
- `longitude` - Event longitude (NOT `lon` or `centroid_lon`)
- `event_type` - Event category string (e.g., `earthquake`, `hurricane`, `wildfire`)
- `loc_id` - Assigned location code or water body code

Type-specific severity columns:
- Earthquakes: `magnitude`, `depth_km`, `felt_radius_km`, `damage_radius_km`, `place`
  - Aftershock sequence columns (see below): `mainshock_id`, `sequence_id`, `is_mainshock`, `aftershock_count`
- Hurricanes/Cyclones: `wind_kt`, `pressure_mb`, `category`, `r34_ne`/`r50_ne`/`r64_ne` (wind radii)
- Wildfires: `burned_acres`, `perimeter` (GeoJSON string)
- Volcanoes: `VEI`, `volcano_number`, `volcano_name`, `activity_type`, `activity_area`
  - Duration columns (see below): `end_year`, `end_timestamp`, `duration_days`, `is_ongoing`, `eruption_id`
- Tsunamis: `max_water_height_m`, `runup_m`

Aftershock sequence columns (earthquakes only):
- `mainshock_id` - USGS event ID of the mainshock this event is an aftershock of (NULL if this IS the mainshock)
- `sequence_id` - Shared ID for all events in a sequence (e.g., `SEQ000001`), enables grouping
- `is_mainshock` - Boolean, true if this event has detected aftershocks
- `aftershock_count` - Number of aftershocks (mainshocks only, 0 for non-mainshocks)

Aftershock detection uses Gardner-Knopoff (1974) empirical windows:
- Time window: `10^(0.5*M - 1.5)` days (e.g., M7 = 10 days, M8 = 32 days)
- Distance window: `10^(0.5*M - 0.5)` km (e.g., M7 = 100 km, M8 = 316 km)
- Only M5.5+ earthquakes are considered as potential mainshocks

Volcano duration columns (for continuous eruptions):
- `end_year` - Year eruption ended (int, null if ongoing)
- `end_timestamp` - End datetime (for precise duration calculation)
- `duration_days` - Duration in days (calculated from start to end)
- `is_ongoing` - Boolean, true if eruption has no end date or ended this year
- `eruption_id` - Smithsonian eruption number (for future episode grouping)
- `activity_area` - Specific vent/area (e.g., "East rift zone (Puu O'o), Halemaumau")

Example: Kilauea 1983-2018 has `duration_days=13029` (~35.7 years), `activity_area="East rift zone (Puu O'o), Halemaumau"`

Cross-event linking columns (for disaster chains):
- `parent_event_id` - Links to triggering event (e.g., earthquake triggers tsunami)
- `link_type` - Relationship type: `aftershock`, `triggered`, `caused_by`

**Cross-Event Time Windows:**
- Earthquake aftershocks: 0-90 days after, within rupture length
- Volcano -> earthquakes: 30 days before to 60 days after eruption
- Earthquake -> tsunami: 0-24 hours after, coastal areas
- Earthquake -> volcano: 60 days before (eruption precedes quake)

Optional geometry column:
- `perimeter` - GeoJSON string for polygon events (wildfires, floods)

### Tropical Storm Schema (IBTrACS)

Tropical storms use a two-table structure for efficient yearly overview + drill-down animation:

**storms.parquet** - Storm metadata (one row per storm):

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `storm_id` | string | Yes | Unique storm identifier (e.g., `2005236N23285` for Katrina) |
| `name` | string | No | Storm name (e.g., `KATRINA`, `MARIA`) |
| `year` | int | Yes | Season year |
| `basin` | string | Yes | Basin code: `NA`, `EP`, `WP`, `SI`, `SP`, `NI`, `SA` |
| `subbasin` | string | No | Sub-basin code (e.g., `GM` for Gulf of Mexico) |
| `source_agency` | string | No | Primary tracking agency (NHC, JTWC, JMA, etc.) |
| `start_date` | datetime | Yes | First track position timestamp |
| `end_date` | datetime | Yes | Last track position timestamp |
| `max_wind_kt` | float | No | Maximum sustained wind (knots) |
| `min_pressure_mb` | float | No | Minimum central pressure (millibars) |
| `max_category` | string | Yes | Saffir-Simpson category: `TD`, `TS`, `Cat1`-`Cat5` |
| `num_positions` | int | Yes | Number of 6-hourly track positions |
| `made_landfall` | bool | Yes | Whether storm made landfall |
| `track_coords` | string | Yes | **Precalculated**: JSON array of `[[lon,lat],...]` for GeoJSON LineString |
| `bbox` | string | Yes | **Precalculated**: JSON `[minLon, minLat, maxLon, maxLat]` for spatial queries |
| `has_wind_radii` | bool | Yes | **Precalculated**: True if any position has r34/r50/r64 data |

**positions.parquet** - Track positions (6-hourly, for animation drill-down):

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `event_id` | string | Yes | Position ID: `{storm_id}_{index}` |
| `storm_id` | string | Yes | Parent storm ID |
| `timestamp` | datetime | Yes | Position timestamp (6-hourly intervals) |
| `latitude` | float | Yes | Position latitude |
| `longitude` | float | Yes | Position longitude |
| `wind_kt` | float | No | Sustained wind speed (knots) |
| `pressure_mb` | float | No | Central pressure (millibars) |
| `category` | string | No | Category at this position: `TD`, `TS`, `Cat1`-`Cat5` |
| `basin` | string | No | Basin code |
| `source_agency` | string | No | Agency providing this observation |
| `status` | string | No | Storm status (e.g., `HU`, `TS`, `EX`) |
| `loc_id` | string | Yes | Water body code (e.g., `XOA`, `XSG`) |
| `r34_ne/se/sw/nw` | int | No | 34kt wind radius by quadrant (nautical miles) |
| `r50_ne/se/sw/nw` | int | No | 50kt wind radius by quadrant (nautical miles) |
| `r64_ne/se/sw/nw` | int | No | 64kt wind radius by quadrant (nautical miles) |

**Precalculated fields rationale:**
- `track_coords`: Eliminates join with positions table for yearly track display. API reads directly from storms table and builds GeoJSON LineString without aggregation.
- `bbox`: Enables fast spatial filtering (e.g., "storms affecting Florida") without loading all coordinates.
- `has_wind_radii`: UI can show/hide "View Wind Radii" button without querying positions table.

**Basin codes:**
- `NA` - North Atlantic (NHC)
- `EP` - East Pacific (NHC)
- `WP` - West Pacific (JTWC/JMA)
- `SI` - South Indian (Reunion/BOM)
- `SP` - South Pacific (BOM/Fiji)
- `NI` - North Indian (IMD)
- `SA` - South Atlantic (rare)

### Tsunami Schema (NOAA NCEI)

**Source:** [NOAA NCEI Global Historical Tsunami Database](https://www.ncei.noaa.gov/products/natural-hazards/tsunamis-earthquakes-volcanoes/tsunamis)
- DOI: 10.7289/V5PN93H7
- Coverage: 2100 BC to present (2,400+ events globally)
- Update: Continuous (as events occur)
- License: Public Domain (U.S. Government)

**HaZEL Search Tool:** https://www.ngdc.noaa.gov/hazel/view/hazards/tsunami/event-search

Tsunamis use a two-table structure: source events + runup observations. Unlike hurricanes (sequential track), tsunamis radiate outward from a source to multiple coastal points.

**events.parquet** - Tsunami source events (earthquake/landslide epicenters):

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `event_id` | string | Yes | Unique event identifier (e.g., `TS005413` for 2011 Tohoku) |
| `timestamp` | datetime | Yes | Event datetime (source earthquake/landslide time) |
| `year` | int | Yes | Event year (for filtering) |
| `latitude` | float | Yes | Source latitude (earthquake epicenter) |
| `longitude` | float | Yes | Source longitude |
| `cause` | string | Yes | Cause type: `Earthquake`, `Landslide`, `Volcano`, `Meteorological` |
| `cause_code` | int | No | NCEI cause code (1=Earthquake, 2=Questionable, etc.) |
| `country` | string | No | Source country name |
| `location` | string | No | Source location description |
| `eq_magnitude` | float | No | Triggering earthquake magnitude (if caused by earthquake) |
| `max_water_height_m` | float | No | Maximum observed water height (meters) at any runup |
| `intensity` | float | No | Tsunami intensity (Soloviev-Imamura scale) |
| `num_runups` | int | No | Number of runup observations |
| `deaths` | int | No | Total deaths (actual or estimated) |
| `deaths_order` | int | No | Deaths magnitude order (0=0, 1=1-10, 2=11-100, etc.) |
| `damage_millions` | float | No | Damage in millions USD |
| `damage_order` | int | No | Damage magnitude order |
| `loc_id` | string | Yes | Source location code or water body code |
| `parent_event_id` | string | No | Links to triggering earthquake (for cross-event chains) |

**runups.parquet** - Runup observations (where waves were measured/observed):

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `runup_id` | string | Yes | Unique runup identifier |
| `event_id` | string | Yes | Parent tsunami event ID (strip TS prefix for NCEI match) |
| `timestamp` | datetime | No | Arrival time at this location (often estimated) |
| `year` | int | Yes | Year (for filtering) |
| `latitude` | float | Yes | Observation latitude |
| `longitude` | float | Yes | Observation longitude |
| `country` | string | No | Observation country |
| `location` | string | No | Location name (e.g., "HILO, HAWAII, HI") |
| `water_height_m` | float | No | Maximum water height observed (meters) |
| `horizontal_inundation_m` | float | No | How far inland water reached (meters) |
| `dist_from_source_km` | float | No | Distance from source epicenter (km) |
| `arrival_travel_time_min` | int | No | Travel time from source (minutes) |
| `deaths` | int | No | Deaths at this location |
| `deaths_order` | int | No | Deaths magnitude order |
| `damage_order` | int | No | Damage magnitude order |
| `loc_id` | string | Yes | Location code or water body code |

**Animation/Display Logic:**
- Source event displays like earthquake (point with magnitude sizing)
- Click "View Runups" to show coastal observation points
- Runups can be animated by estimated arrival time: `dist_from_source_km / 700` hours (tsunami speed ~700 km/h in deep ocean)
- Lines can be drawn from source to runup points (radial propagation pattern)

**Cross-Event Linking:**
Tsunamis are typically triggered by earthquakes. Use `parent_event_id` to link:
- Time window: 0-24 hours after earthquake
- Spatial: Coastal areas near earthquake epicenter
- Earthquake M7.5+ in oceanic/subduction zones are primary triggers

**{COUNTRY}.parquet** - Region-year aggregates (required):
- `loc_id` - Location code
- `year` - Year
- Aggregated statistics (counts, sums, means, etc.)

**IMPORTANT: Use Long Format for Time-Series Data**

All time-series data MUST use long format (one row per location-year), NOT wide format (year as columns):

```
CORRECT (Long Format):
loc_id          year    total_pop
USA-CA-6037     2020    10014009
USA-CA-6037     2021    9829544
USA-CA-6037     2022    9721138

WRONG (Wide Format):
loc_id          pop_2020    pop_2021    pop_2022
USA-CA-6037     10014009    9829544     9721138
```

Long format enables:
- Consistent time slider functionality across all datasets
- Easy filtering by year range
- Uniform data loading in frontend
- Simpler aggregation queries

---

## Hierarchical Aggregation

When source data is only available at a detailed level (e.g., admin_2 LGAs), **auto-aggregate up to parent levels** for better visualization at country/state scale.

> **See also**: [data_pipeline.md - Hierarchical Aggregation Scripts](data_pipeline.md#hierarchical-aggregation-scripts) for NUTS hierarchy details and the `aggregate_eurostat_to_country.py` script.

### Why Aggregate?

Without aggregation:
- User asks for "Australia population" -> gets 547 tiny LGAs
- Choropleth dominated by one outlier (Brisbane ~1.4M), everything else dull blue
- Hard to see state-level patterns

With aggregation:
- Same query -> shows 8 states with meaningful variation
- User can drill down to LGAs if needed
- Better UX at every zoom level

### Aggregation Pattern

When your source data has only one admin level, create parent levels:

```python
def aggregate_to_parent_levels(df, geometry_df):
    """
    Aggregate admin_2 data up to admin_1 and admin_0 levels.

    Args:
        df: DataFrame with loc_id, year, and metric columns
        geometry_df: DataFrame with loc_id, parent_id, admin_level

    Returns:
        Combined DataFrame with all admin levels
    """
    all_levels = [df.copy()]  # Start with original data

    # Build parent lookup from geometry
    parent_lookup = geometry_df.set_index('loc_id')['parent_id'].to_dict()

    # Identify numeric columns to aggregate (exclude loc_id, year)
    metric_cols = [c for c in df.columns if c not in ['loc_id', 'year']]

    # Aggregate to admin_1 (states)
    df_with_parent = df.copy()
    df_with_parent['parent_id'] = df_with_parent['loc_id'].map(parent_lookup)

    admin1 = df_with_parent.groupby(['parent_id', 'year'])[metric_cols].sum().reset_index()
    admin1 = admin1.rename(columns={'parent_id': 'loc_id'})
    all_levels.append(admin1)

    # Aggregate to admin_0 (country)
    # Extract country code from loc_id (e.g., "AUS-NSW" -> "AUS")
    admin1['country'] = admin1['loc_id'].str.split('-').str[0]
    admin0 = admin1.groupby(['country', 'year'])[metric_cols].sum().reset_index()
    admin0 = admin0.rename(columns={'country': 'loc_id'})
    all_levels.append(admin0)

    return pd.concat(all_levels, ignore_index=True)
```

### Geometry Aggregation

Parent-level geometry is created by dissolving child polygons:

```python
def create_parent_geometry(geometry_gdf):
    """
    Dissolve admin_2 polygons into admin_1 and admin_0.

    Args:
        geometry_gdf: GeoDataFrame with geometry, loc_id, parent_id

    Returns:
        Combined GeoDataFrame with all admin levels
    """
    from shapely.ops import unary_union

    all_levels = [geometry_gdf.copy()]

    # Dissolve to admin_1 (group by parent_id)
    admin1_groups = geometry_gdf.groupby('parent_id')
    admin1_records = []
    for parent_id, group in admin1_groups:
        dissolved = unary_union(group.geometry.tolist())
        admin1_records.append({
            'loc_id': parent_id,
            'name': get_state_name(parent_id),  # Lookup state name
            'admin_level': 1,
            'parent_id': parent_id.split('-')[0],  # Country code
            'geometry': dissolved
        })
    admin1_gdf = gpd.GeoDataFrame(admin1_records, crs=geometry_gdf.crs)
    all_levels.append(admin1_gdf)

    # Dissolve to admin_0 (whole country)
    country_code = geometry_gdf['loc_id'].str.split('-').str[0].iloc[0]
    country_geom = unary_union(geometry_gdf.geometry.tolist())
    admin0_gdf = gpd.GeoDataFrame([{
        'loc_id': country_code,
        'name': get_country_name(country_code),
        'admin_level': 0,
        'parent_id': None,
        'geometry': country_geom
    }], crs=geometry_gdf.crs)
    all_levels.append(admin0_gdf)

    return pd.concat(all_levels, ignore_index=True)
```

### Aggregation Rules by Metric Type

> **See**: [data_pipeline.md - Aggregation Rules](data_pipeline.md#aggregation-rules-by-metric-type) for the complete 9-row table covering counts, rates, per-capita, density, averages, indices, categorical, min/max, and medians - plus common mistakes and when NOT to aggregate.
>
> **See also**: [data_pipeline.md - Disaggregation Rules](data_pipeline.md#disaggregation-rules-scaling-down) for how data transforms when scaling DOWN (e.g., "What is the flood risk at my house?" when only county-level data exists). Covers inheritance patterns, when disaggregation works well vs. is misleading, and UI transparency guidelines.

### Complete Example

```python
# In converter main():
def main():
    # Load source data (admin_2 only)
    gdf = load_geopackage()

    # Process to long format
    df = process_data(gdf)  # Creates admin_2 rows

    # Extract geometry
    geom_gdf = extract_geometry(gdf)  # admin_2 polygons

    # === NEW: Aggregate to parent levels ===
    df = aggregate_to_parent_levels(df, geom_gdf)
    geom_gdf = create_parent_geometry(geom_gdf)

    # Save outputs (now includes all admin levels)
    save_parquet(df, OUTPUT_DIR / "AUS.parquet", "population data")
    save_parquet(geom_gdf, COUNTRY_DIR / "geometry.parquet", "geometry")
```

### Output Verification

After aggregation, verify all levels exist:

```python
# Check data levels
print(df.groupby(df['loc_id'].str.count('-'))['loc_id'].nunique())
# 0 dashes (AUS): 1 location
# 1 dash (AUS-NSW): 8 states
# 2 dashes (AUS-NSW-10050): 547 LGAs

# Check geometry levels
print(geom_df.groupby('admin_level').size())
# admin_level 0: 1
# admin_level 1: 8
# admin_level 2: 547
```

---

## Existing Converters

### Event-Based Data (has events.parquet)

| Source | File | Input Format | Geocoding | Best For |
|--------|------|--------------|-----------|----------|
| USGS Global Earthquakes | `convert_global_earthquakes.py` | CSV | Water body assignment | Global events with aftershock detection |
| USGS US Earthquakes | `convert_usgs_earthquakes.py` | CSV | 3-pass spatial join | US-only point events |
| Canada Earthquakes | `convert_canada_earthquakes.py` | CSV | 3-pass spatial join | Canadian data |
| IBTrACS Global Storms | `convert_ibtracs.py` | CSV | Water body assignment | Global tropical storms with precalculated tracks |
| HURDAT2 Hurricanes | `convert_hurdat2.py` | Custom text | Point-in-polygon + water | Track/trajectory data (Atlantic/Pacific only) |
| NOAA Tsunamis | `convert_tsunami.py` | JSON | 3-pass spatial join | Multiple related tables |
| Smithsonian Global Volcanoes | `convert_global_volcanoes.py` | TSV | Water body assignment | Global eruptions with VEI |
| Smithsonian Volcanoes | `convert_volcano.py` | GeoJSON | Point + water bodies | Location + events |
| MTBS Wildfires | `convert_mtbs.py` | Shapefile (zip) | Centroid + nearest | Polygon geometries |

### Live Data APIs (for periodic updates)

| Source | API/Feed | Update Frequency | Coverage | Downloader |
|--------|----------|------------------|----------|------------|
| USGS Earthquakes | https://earthquake.usgs.gov/fdsnws/event/1/ | Real-time | Global M2.5+ | `download_usgs_earthquakes.py` |
| Smithsonian Volcanoes | https://volcano.si.edu/geoserver/GVP-VOTW/ows (WFS) | Weekly | Global Holocene | `download_volcano.py` |
| IBTrACS Storms | https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/ | Monthly | Global 1842-present | `download_ibtracs.py` |
| NOAA Hurricanes | https://www.nhc.noaa.gov/gis/ | 6-hourly | Atlantic/Pacific | `download_hurdat2.py` |
| NOAA Tsunamis | https://www.ngdc.noaa.gov/hazard/tsu_db.shtml | As events | Global historical | `download_tsunami.py` |
| NASA FIRMS (Fires) | https://firms.modaps.eosdis.nasa.gov/api/ | 12 hours | Global active | (planned) |

**Magnitude thresholds for storage:**
- M2.5+: Full archive (USGS comprehensive catalog, ~15K/year globally)
- M4.5+: Display preload threshold (detected anywhere, ~1.5K/year)
- M5.0+: Significant events only (~1K/year)

### Pre-Aggregated Data (aggregates only)

For data that comes pre-aggregated by region (census data, economic stats, etc.):

```python
"""Minimal converter for pre-aggregated data."""

def load_raw_data():
    """Load and map to loc_id format."""
    df = pd.read_csv(INPUT_FILE)
    # Map existing region codes to loc_id format
    df['loc_id'] = df['fips'].apply(lambda x: f"USA-{state}-{x}")
    return df

def main():
    df = load_raw_data()

    # Select/rename columns for output
    output = df[['loc_id', 'year', 'value_col1', 'value_col2']].copy()

    # Save aggregate only (no events file)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    save_parquet(output, OUTPUT_DIR / "USA.parquet", description="aggregates")

    finalize_source(
        parquet_path=str(OUTPUT_DIR / "USA.parquet"),
        source_id=SOURCE_ID
        # Note: no events_parquet_path for pre-aggregated data
    )
```

---

## Quick Reference

**Load geometry:**
```python
gdf = load_geometry_parquet(path, admin_level=2, geometry_format='geojson')
```

**Create points:**
```python
gdf = create_point_gdf(df, lat_col='latitude', lon_col='longitude')
```

**Get water body code:**
```python
code = get_water_body_loc_id(lat, lon, region='usa')
```

**Save parquet:**
```python
save_parquet(df, path, description="county-year aggregates")
```

**Finalize:**
```python
finalize_source(parquet_path, source_id, events_parquet_path)
```

---

## Related Documentation

| File | Purpose |
|------|---------|
| [data_pipeline.md](data_pipeline.md) | Full pipeline documentation, metadata schema, all datasets |
| [GEOMETRY.md](GEOMETRY.md) | loc_id specification, geometry structure, water body codes |
| [MAPPING.md](MAPPING.md) | Frontend map rendering and display |

---

*Last Updated: 2026-01-09 - Added Tsunami schema (NOAA NCEI) with events + runups tables, radial propagation display model*
