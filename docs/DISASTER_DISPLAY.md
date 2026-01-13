# Disaster Display System

**Authoritative reference for disaster data schemas, display models, and API endpoints.**

This document contains:
- **Complete Parquet Schemas** - All disaster event column definitions (earthquake, hurricane, tsunami, volcano, tornado, wildfire, flood)
- **Display Models** - Point+Radius, Track, Polygon rendering
- **API Endpoints** - GeoJSON and drill-down endpoints
- **Popup System** - Unified popup with sequence/related actions

**Related docs:**
- [MAPPING.md](MAPPING.md) - Time slider, animation behavior, choropleth system
- [data_pipeline.md](data_pipeline.md) - Folder structure, metadata schemas, routing
- [data_import.md](data_import.md) - Quick reference for creating converters
- [GEOMETRY.md](GEOMETRY.md) - loc_id specification, water body codes

---

## Disaster Types at a Glance

| Type | Global Source | Live API | Animation | Year Range | Display Model |
|------|---------------|----------|-----------|------------|---------------|
| **Earthquakes** | USGS Global Catalog | Yes (real-time) | Aftershock sequences | 1900-present | Point + Radius |
| **Tropical Storms** | NOAA IBTrACS | Yes (6h updates) | Track progression | 1842-present | Track/Trail |
| **Tsunamis** | NOAA NCEI | Yes (as events) | Wave propagation | 2100 BC-present | Radial |
| **Volcanoes** | Smithsonian GVP | Yes (weekly) | Static (with duration) | Holocene | Point + Radius |
| **Wildfires** | Global Fire Atlas | Zenodo (periodic) | Daily progression | 2002-2024 | Polygon |
| **Drought** | US Drought Monitor | Yes (weekly) | Weekly snapshots | 2000-present | Choropleth |
| **Tornadoes** | NOAA Storm Events | Yes (monthly) | Track drill-down | 1950-present | Point + Track |
| **Floods** | (future) | - | - | - | Polygon |

**Display Models:**
- **Point + Radius**: Static points with magnitude-based circles (felt/damage radius)
- **Track/Trail**: Progressive line drawing with current position marker
- **Radial**: Expanding wave from source to observation points
- **Polygon**: Area boundaries that change over time
- **Choropleth**: County-level shading by severity

---

## Global Data Sources

All disaster data uses **global sources only** - no country-specific duplicates.

| Type | Source | Data Path | Live Update URL | Coverage |
|------|--------|-----------|-----------------|----------|
| **Earthquakes** | USGS Earthquake Catalog | `global/usgs_earthquakes/` | https://earthquake.usgs.gov/fdsnws/event/1/query | 1900-present, M2.5+ global |
| **Tropical Storms** | NOAA IBTrACS v04r01 | `global/tropical_storms/` | https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/ | 1842-present, all basins |
| **Tsunamis** | NOAA NCEI Historical Tsunami Database | `global/tsunamis/` | https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/tsunamis/ | 2100 BC-present, global |
| **Volcanoes** | Smithsonian Global Volcanism Program | `global/smithsonian_volcanoes/` | https://volcano.si.edu/database/webservices.cfm | Holocene epoch, 1,400+ volcanoes |
| **Wildfires** | Global Fire Atlas (NASA/ORNL) | `global/wildfires/` | [Zenodo](https://zenodo.org/records/11400062) | 2002-2024, 13.3M fires |

### Data Files Per Source

**Earthquakes** - `global/usgs_earthquakes/`
- `events.parquet` - Individual events (306K+ rows)
- `GLOBAL.parquet` - Country-year aggregates
- Schema: event_id, timestamp, latitude, longitude, magnitude, depth_km, felt_radius_km, damage_radius_km, place, loc_id
- Aftershock columns: mainshock_id, sequence_id, is_mainshock, aftershock_count

**Tropical Storms** - `global/tropical_storms/`
- `storms.parquet` - Storm metadata (13,541 storms)
- `positions.parquet` - 6-hourly track positions (722,507 rows)
- Schema: storm_id, timestamp, latitude, longitude, wind_kt, pressure_mb, category, basin
- Wind radii: r34_ne/se/sw/nw, r50_*, r64_*

**Tsunamis** - `global/tsunamis/`
- `events.parquet` - Source events/epicenters (2,619 events)
- `runups.parquet` - Coastal observation points (33,623 runups)
- Schema: event_id, timestamp, latitude, longitude, eq_magnitude, cause, max_water_height_m
- Runup schema: runup_id, event_id, dist_from_source_km, water_height_m

**Volcanoes** - `global/smithsonian_volcanoes/`
- `events.parquet` - Eruption events (11,079 eruptions)
- `volcanoes.parquet` - Volcano locations (1,400+ volcanoes)
- Schema: event_id, timestamp, latitude, longitude, VEI, volcano_name, activity_type
- Duration columns: end_year, end_timestamp, duration_days, is_ongoing, eruption_id

**Wildfires** - `global/wildfires/`
- `fires.parquet` - Fire events with perimeters (13.3M fires)
- `fire_progression_{year}.parquet` - Daily burn polygons for animation
- Schema: fire_id, start/end dates, size (km2), duration, spread speed/direction
- Progression schema: event_id, date, day_num, area_km2, perimeter (GeoJSON)

---

## Complete Parquet Schemas

This section contains the authoritative schema definitions for all disaster parquet files. For converter implementation details, see [data_import.md](data_import.md).

### Core Event Columns (Required for ALL types)

All event parquet files MUST have these columns:

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `event_id` | string | Yes | Unique identifier for the event |
| `timestamp` | datetime64 | Yes | Event time (UTC, ISO 8601) |
| `latitude` | float64 | Yes | Event latitude (WGS84) |
| `longitude` | float64 | Yes | Event longitude (WGS84) |
| `event_type` | string | Yes | Event category |
| `loc_id` | string | Yes | Location code or water body code |
| `year` | int32 | No | Extracted from timestamp for filtering |

### Earthquake Schema

**File:** `global/usgs_earthquakes/events.parquet` (1,053,285 events)

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `magnitude` | float32 | Yes | Earthquake magnitude |
| `depth_km` | float32 | No | Depth in kilometers |
| `felt_radius_km` | float32 | No | Approximate felt radius based on magnitude |
| `damage_radius_km` | float32 | No | Approximate damage radius based on magnitude |
| `place` | string | No | Location description from USGS |
| `mainshock_id` | string | No | Event ID of mainshock (NULL if this IS the mainshock) |
| `sequence_id` | string | No | Shared ID for all events in a sequence |
| `is_mainshock` | bool | No | True if this event has detected aftershocks |
| `aftershock_count` | int32 | No | Number of aftershocks (mainshocks only) |

**Aftershock detection** uses Gardner-Knopoff (1974) empirical windows:
- Time window: `10^(0.5*M - 1.5)` days (e.g., M7 = 10 days, M8 = 32 days)
- Distance window: `10^(0.5*M - 0.5)` km (e.g., M7 = 100 km, M8 = 316 km)
- Only M5.5+ earthquakes are considered as potential mainshocks

### Tropical Storm Schema (Two-Table)

Tropical storms use a two-table structure for efficient yearly overview + drill-down animation.

**storms.parquet** (13,541 storms) - Storm metadata:

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
| `track_coords` | string | Yes | Precalculated JSON array of `[[lon,lat],...]` for GeoJSON LineString |
| `bbox` | string | Yes | Precalculated JSON `[minLon, minLat, maxLon, maxLat]` for spatial queries |
| `has_wind_radii` | bool | Yes | Precalculated flag if any position has r34/r50/r64 data |

**positions.parquet** (722,507 positions) - 6-hourly track positions for animation:

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `event_id` | string | Yes | Position ID: `{storm_id}_{index}` |
| `storm_id` | string | Yes | Parent storm ID |
| `timestamp` | datetime | Yes | Position timestamp (6-hourly intervals) |
| `latitude` | float | Yes | Position latitude |
| `longitude` | float | Yes | Position longitude |
| `wind_kt` | float | No | Sustained wind speed (knots) |
| `pressure_mb` | float | No | Central pressure (millibars) |
| `category` | string | No | Category at this position |
| `basin` | string | No | Basin code |
| `source_agency` | string | No | Agency providing this observation |
| `status` | string | No | Storm status (e.g., `HU`, `TS`, `EX`) |
| `loc_id` | string | Yes | Water body code (e.g., `XOA`, `XSG`) |
| `r34_ne/se/sw/nw` | int | No | 34kt wind radius by quadrant (nautical miles) |
| `r50_ne/se/sw/nw` | int | No | 50kt wind radius by quadrant |
| `r64_ne/se/sw/nw` | int | No | 64kt wind radius by quadrant |

### Tsunami Schema (Two-Table)

Tsunamis use a two-table structure: source events + runup observations. Unlike hurricanes (sequential track), tsunamis radiate outward from a source to multiple coastal points.

**events.parquet** (2,619 events) - Tsunami source events:

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
| `runup_count` | int | No | Number of runup observations |
| `deaths` | int | No | Total deaths (actual or estimated) |
| `deaths_order` | int | No | Deaths magnitude order (0=0, 1=1-10, 2=11-100, etc.) |
| `damage_millions` | float | No | Damage in millions USD |
| `damage_order` | int | No | Damage magnitude order |
| `loc_id` | string | Yes | Source location code or water body code |
| `parent_event_id` | string | No | Links to triggering earthquake (for cross-event chains) |

**runups.parquet** (33,623 runups) - Where waves were measured/observed:

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `runup_id` | string | Yes | Unique runup identifier |
| `event_id` | string | Yes | Parent tsunami event ID |
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
| `loc_id` | string | Yes | Location code or water body code |

### Volcano Schema

**File:** `global/smithsonian_volcanoes/events.parquet` (11,079 eruptions)

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `event_id` | string | Yes | Unique eruption identifier |
| `eruption_id` | int32 | No | Smithsonian eruption number |
| `VEI` | int32 | No | Volcanic Explosivity Index (0-8) |
| `volcano_number` | int32 | No | Smithsonian volcano number |
| `volcano_name` | string | No | Volcano name |
| `activity_type` | string | No | Type of activity (e.g., `Explosive`, `Effusive`) |
| `activity_area` | string | No | Specific vent/area (e.g., "East rift zone") |
| `end_year` | int32 | No | Year eruption ended (null if ongoing) |
| `end_timestamp` | datetime | No | End datetime (for duration calculation) |
| `duration_days` | int32 | No | Duration in days (calculated) |
| `is_ongoing` | bool | No | True if eruption has no end date |
| `felt_radius_km` | float32 | No | Approximate felt radius based on VEI |
| `damage_radius_km` | float32 | No | Approximate damage radius based on VEI |

Example: Kilauea 1983-2018 has `duration_days=13029` (~35.7 years), `activity_area="East rift zone (Puu O'o), Halemaumau"`

### Tornado Schema

**File:** `global/tornadoes/events.parquet` (~79,000 events)

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `event_id` | int64 | Yes | NOAA event ID |
| `timestamp` | datetime | Yes | Event datetime |
| `event_type` | string | Yes | Event type (e.g., `Tornado`) |
| `latitude` | float | Yes | Start point latitude |
| `longitude` | float | Yes | Start point longitude |
| `end_latitude` | float | No | End point latitude (for track) |
| `end_longitude` | float | No | End point longitude (for track) |
| `felt_radius_km` | float | No | Broader impact zone based on track length |
| `damage_radius_km` | float | No | Actual tornado damage width (from tornado_width_yd) |
| `magnitude` | float | No | Event magnitude (varies by type) |
| `magnitude_type` | string | No | Magnitude unit type |
| `tornado_scale` | string | No | EF0-EF5 or legacy F0-F5 scale |
| `tornado_length_mi` | float | No | Track length in miles |
| `tornado_width_yd` | int | No | Track width in yards |
| `deaths_direct` | int | No | Direct fatalities |
| `deaths_indirect` | int | No | Indirect fatalities |
| `injuries_direct` | int | No | Direct injuries |
| `injuries_indirect` | int | No | Indirect injuries |
| `damage_property` | int64 | No | Property damage in USD |
| `damage_crops` | int64 | No | Crop damage in USD |
| `location` | string | No | Location description |
| `loc_id` | string | Yes | Location code (county FIPS or water body) |
| `sequence_id` | string | No | Tornado sequence ID (links same storm system) |
| `sequence_position` | int | No | Position in sequence (1, 2, 3...) |
| `sequence_count` | int | No | Total tornadoes in this sequence |

**Tornado Dual Radii Calculation:**
- `damage_radius_km` = `tornado_width_yd * 0.0009144 / 2` (half-width in km from yards)
- `felt_radius_km` = `tornado_length_mi * 1.60934 / 2` (half-length in km from miles)
- If `tornado_width_yd` unavailable: default damage radius by EF scale (EF0=8m, EF1=25m, EF2=80m, EF3=200m, EF4=500m, EF5=1200m)
- If `tornado_length_mi` unavailable: default felt radius = 5 km

**Tornado Sequence Linking:**
- Time window: 3 hours between consecutive tornadoes
- Distance threshold: 50 km from end of one tornado to start of next
- Chain direction: Follows storm movement chronologically

### Wildfire Schema

**Files:**
- `global/wildfires/by_year/fires_{year}.parquet` - Raw fire events (13.3M fires total)
- `global/wildfires/by_year_enriched/fires_{year}_enriched.parquet` - With loc_id columns
- `global/wildfires/fire_progression_{year}.parquet` - Daily progression with loc_id

**fires_{year}_enriched.parquet** - Enriched fire events with location data:

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `event_id` | string | Yes | Unique fire identifier |
| `timestamp` | datetime | Yes | Fire start date |
| `latitude` | float | Yes | Fire centroid latitude |
| `longitude` | float | Yes | Fire centroid longitude |
| `burned_acres` | float32 | No | Total burned area in acres |
| `area_km2` | float32 | No | Total burned area in km2 |
| `duration_days` | int32 | No | Fire duration in days |
| `land_cover` | string | No | Dominant land cover type |
| `source` | string | No | Data source (e.g., "Global Fire Atlas") |
| `has_progression` | bool | No | True if progression data available |
| `perimeter` | string | No | GeoJSON polygon of final fire boundary |
| `loc_id` | string | Yes | Location code (e.g., "USA-CA-FIRE-12345") |
| `parent_loc_id` | string | Yes | Parent admin unit (e.g., "USA-CA") |
| `sibling_level` | int | Yes | Admin level where fire becomes a sibling (1-3) |
| `iso3` | string | Yes | Country code (e.g., "USA") |
| `loc_confidence` | float | Yes | Confidence score of location assignment (0-1) |

**fire_progression_{year}.parquet** - Daily burn snapshots with location data:

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `event_id` | string | Yes | Parent fire ID |
| `date` | date | Yes | Date of this snapshot |
| `day_num` | int | Yes | Day number from fire start (1-based) |
| `area_km2` | float | Yes | Cumulative burned area to this date |
| `perimeter` | string | Yes | GeoJSON polygon of burn area |
| `loc_id` | string | Yes | Location code (joined from enriched fires) |
| `parent_loc_id` | string | Yes | Parent admin unit |
| `sibling_level` | int | Yes | Admin level where fire becomes a sibling |
| `iso3` | string | Yes | Country code |
| `loc_confidence` | float | Yes | Confidence score of location assignment |

### Flood Schema

**Files:**
- `global/floods/events.parquet` - Raw flood events (4,825 events, 1985-2019)
- `global/floods/events_with_geometry.parquet` - Events with merged perimeter column
- `global/floods/events_enriched.parquet` - With loc_id columns (use this for display)
- `global/floods/geometries/{dfo_id}.geojson` - Individual flood perimeter files

**events_enriched.parquet** - Enriched flood events with location data:

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `event_id` | string | Yes | Unique flood identifier |
| `timestamp` | datetime | Yes | Flood start date |
| `end_timestamp` | datetime | No | Flood end date |
| `year` | int | Yes | Event year |
| `latitude` | float | Yes | Flood centroid latitude |
| `longitude` | float | Yes | Flood centroid longitude |
| `country` | string | No | Primary affected country |
| `area_km2` | float | No | Affected area in km2 |
| `duration_days` | int | No | Flood duration in days |
| `severity` | string | No | Severity level (e.g., "Large", "Very Large") |
| `deaths` | int | No | Death toll |
| `displaced` | int | No | Number displaced |
| `damage_usd` | float | No | Damage in USD |
| `source` | string | No | Data source |
| `dfo_id` | string | No | DFO Flood Observatory ID |
| `glide_index` | string | No | GLIDE index |
| `has_geometry` | bool | No | True if polygon geometry available |
| `has_progression` | bool | No | True if progression data available |
| `perimeter` | string | No | GeoJSON polygon of flood extent |
| `loc_id` | string | Yes | Location code (e.g., "USA-LA-FLOOD-1234") |
| `parent_loc_id` | string | Yes | Parent admin unit (e.g., "USA-LA") |
| `sibling_level` | int | Yes | Admin level where flood becomes a sibling (1-3) |
| `iso3` | string | Yes | Country code (e.g., "USA") |
| `loc_confidence` | float | Yes | Confidence score of location assignment (0-1) |

### Cross-Event Linking Columns

For linking disaster chains (e.g., earthquake triggers tsunami):

| Column | Type | Description |
|--------|------|-------------|
| `parent_event_id` | string | Links to triggering event |
| `link_type` | string | Relationship: `aftershock`, `triggered`, `caused_by` |
| `sequence_id` | string | Groups related events of same type |

**Cross-Event Time Windows:**
- Earthquake aftershocks: 0-90 days after, within rupture length
- Volcano -> earthquakes: 30 days before to 60 days after eruption
- Earthquake -> tsunami: 0-24 hours after, coastal areas
- Earthquake -> volcano: 60 days before (eruption precedes quake)

### Impact Radius Formulas

All point+radius events MUST pre-calculate `felt_radius_km` and `damage_radius_km` in the converter. The frontend displays these as concentric circles (felt=outer/lighter, damage=inner/bolder).

**Earthquake Radii** (based on empirical seismological attenuation models):

```python
def calculate_felt_radius(magnitude, depth_km=None):
    """Felt radius (MMI II-III) where shaking is noticeable."""
    # Formula: R = 10^(0.44 * M - 0.29)
    radius = 10 ** (0.44 * magnitude - 0.29)
    # Depth correction: deeper quakes have smaller felt areas
    if depth_km > 300:
        radius *= 0.5  # Deep focus - 50% reduction
    elif depth_km > 70:
        radius *= 0.7  # Intermediate - 30% reduction
    return radius

def calculate_damage_radius(magnitude, depth_km=None):
    """Damage radius (MMI VI+) where structural damage possible."""
    if magnitude < 5.0:
        return 0.0  # Only M5+ causes structural damage
    # Formula: R = 10^(0.32 * M - 0.78)
    radius = 10 ** (0.32 * magnitude - 0.78)
    # Depth correction
    if depth_km > 300:
        radius *= 0.3
    elif depth_km > 70:
        radius *= 0.5
    return radius
```

**Volcano Radii** (based on VEI logarithmic scale):

```python
def calculate_felt_radius_km(vei):
    """Felt radius (ash fall, effects noticed)."""
    # Formula: R = 5 * 10^(VEI * 0.33)
    return 5 * (10 ** (vei * 0.33))

def calculate_damage_radius_km(vei):
    """Damage radius (pyroclastic flows, heavy ashfall)."""
    # Formula: R = 1 * 10^(VEI * 0.3)
    return 1 * (10 ** (vei * 0.3))
```

### Live Data APIs

Sources for real-time and periodic data updates:

| Source | API/Feed | Update Frequency | Coverage |
|--------|----------|------------------|----------|
| **USGS Earthquakes** | https://earthquake.usgs.gov/fdsnws/event/1/ | Real-time (minutes) | Global M2.5+ |
| **Smithsonian Volcanoes** | https://volcano.si.edu/geoserver/GVP-VOTW/ows (WFS) | Weekly | Global Holocene |
| **NOAA IBTrACS** | https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/ | Monthly | Global 1842-present |
| **NOAA Hurricanes** | https://www.nhc.noaa.gov/gis/ | 6-hourly during season | Atlantic/Pacific |
| **NOAA Tsunamis** | https://www.ngdc.noaa.gov/hazard/tsu_db.shtml | As events occur | Global historical |
| **NASA FIRMS (Fires)** | https://firms.modaps.eosdis.nasa.gov/api/ | Every 12 hours | Global active fires |
| **NOAA Storm Events** | https://www.ncdc.noaa.gov/stormevents/ftp.jsp | Monthly | US only |

**Magnitude Thresholds for Storage:**

| Magnitude | Detection | Events/Year (Global) | Storage Recommendation |
|-----------|-----------|----------------------|------------------------|
| M0-2 | Local only | Millions | Too many, skip |
| **M2.5+** | USGS catalog | ~15,000 | Full archive |
| M3.0+ | Good global | ~12,000 | Display threshold |
| **M4.5+** | Detected anywhere | ~1,500 | Preload threshold |
| M5.0+ | Always detected | ~1,000 | Significant events |

---

## Earthquakes

### Display: Point + Radius

Two concentric circles - felt radius (outer, where shaking noticeable) and damage radius (inner, where structural damage possible).

**Radius Formulas:**
```python
felt_radius = 10 ** (0.44 * magnitude - 0.29)
damage_radius = 10 ** (0.32 * magnitude - 0.78)  # Only M5+
# Depth correction: deep (>300km) = 50% reduction, intermediate (>70km) = 30% reduction
```

| Magnitude | Felt Radius | Damage Radius |
|-----------|-------------|---------------|
| M4.0 | ~30 km | 0 km |
| M5.0 | ~80 km | ~7 km |
| M6.0 | ~220 km | ~14 km |
| M7.0 | ~620 km | ~29 km |
| M8.0 | ~1700 km | ~60 km |

### Aftershock Sequences

Click earthquake to animate sequence:
- Mainshock appears with expanding circle
- Aftershocks appear at their timestamps
- "Spiderweb" lines connect mainshock to aftershocks

**Gardner-Knopoff Windows:**
- Time: `10^(0.5*M - 1.5)` days (M7 = ~10 days)
- Distance: `10^(0.5*M - 0.5)` km (M7 = ~100 km)

**Converter:** `convert_global_earthquakes.py`

---

## Tropical Storms

### Display: Track/Trail

Animated tracks showing storm path:
1. **Yearly view**: Full track lines colored by max category
2. **Drill-down**: Progressive drawing with current position marker
3. **Wind radii**: Optional circles at 34/50/64 kt extent

### Category Colors (Saffir-Simpson)

| Category | Wind (kt) | Color |
|----------|-----------|-------|
| TD | < 34 | Gray |
| TS | 34-63 | Blue |
| Cat 1 | 64-82 | Yellow |
| Cat 2 | 83-95 | Orange |
| Cat 3 | 96-112 | Light Red |
| Cat 4 | 113-136 | Red |
| Cat 5 | > 136 | Dark Red |

### Basin Codes

NA (North Atlantic), EP (East Pacific), WP (West Pacific), SI (South Indian), SP (South Pacific), NI (North Indian)

**Converter:** `convert_ibtracs.py`

---

## Tsunamis

### Display: Radial Propagation

Expanding wave from source to coastal observations:
1. Source event marker (earthquake epicenter)
2. Expanding wave circle at ~700 km/h
3. Runup points appear as wave reaches them

### Animation Settings

- Granularity: 12 minutes (smooth wave)
- Playback: 200ms intervals (1 sec = 1 hour real-time)
- 5% visibility buffer so runups appear after wave front

**Converter:** `convert_tsunami.py`

---

## Volcanoes

### Display: Point + Radius

VEI-based impact circles:

| VEI | Felt Radius | Damage Radius | Example |
|-----|-------------|---------------|---------|
| 0 | ~5 km | ~1 km | Effusive lava |
| 2 | ~23 km | ~4 km | Minor eruption |
| 4 | ~105 km | ~16 km | Cataclysmic |
| 5 | ~224 km | ~32 km | Mt St Helens 1980 |
| 6 | ~478 km | ~63 km | Pinatubo 1991 |

### Continuous Eruptions

Duration columns track multi-year eruptions (e.g., Kilauea 1983-2018 = 35 years):
- `end_year`, `end_timestamp`, `duration_days`, `is_ongoing`

### Cross-Event Linking

Volcanoes link to nearby earthquakes (30 days before to 60 days after, 150km radius).

**Converter:** `convert_global_volcanoes.py`

---

## Wildfires

### Display: Polygon + Daily Progression

Fire perimeter polygons that grow over time:
1. **Static**: Final perimeter (or point if no perimeter data)
2. **Drill-down**: Daily snapshots of cumulative burn area

### Fire Progression Processing

The converter extracts daily burn polygons from day_of_burn rasters:

| Min Size Filter | Fires (23 years) | Processing Time |
|-----------------|------------------|-----------------|
| >= 10 km2 | ~1.3M | ~12 hours |
| >= 25 km2 | ~473K | ~4.4 hours |
| >= 50 km2 | ~196K | ~1.8 hours |
| >= 100 km2 | ~75K | ~42 minutes |

```bash
python convert_fire_progression.py --all --min-size 25  # Recommended
```

Processes years in reverse order (newest first), skips completed years.

### Alternative Fire Sources

| Source | Coverage | Use Case |
|--------|----------|----------|
| NASA FIRMS | Global, <3h latency | Live heatmap |
| MTBS | USA only, 1984+ | Higher precision USA |
| CNFDB | Canada, 1946+ | Canadian fires |

**Converter:** `convert_global_fire_atlas.py`, `convert_fire_progression.py`

---

## Tornadoes

### Display: Point + Track Drill-down

USA tornadoes from NOAA Storm Events database (1950-present). No reliable global tornado database exists - ~75% of recorded tornadoes occur in the USA.

**Overview Mode:**
- Points colored by Enhanced Fujita (EF) or legacy Fujita (F) scale
- Point size scales with tornado intensity
- Impact radius circle shows damage path width

**Drill-down Mode:**
- Click tornado to view track
- Track line connects start and end points
- Green marker = start point, Red marker = end point
- Impact corridor shown along track

### EF Scale Colors

| Scale | Wind (mph) | Color | Damage |
|-------|------------|-------|--------|
| EF0 | 65-85 | Pale Green | Light |
| EF1 | 86-110 | Lime Green | Moderate |
| EF2 | 111-135 | Gold | Significant |
| EF3 | 136-165 | Dark Orange | Severe |
| EF4 | 166-200 | Orange-Red | Devastating |
| EF5 | >200 | Dark Red | Incredible |

### Data Files

**NOAA Storm Events** - `countries/USA/noaa_storms/`
- `events.parquet` - All storm events including tornadoes (1.2M events, 79K tornadoes)
- Schema: event_id, timestamp, latitude, longitude, end_latitude, end_longitude, tornado_scale, tornado_length_mi, tornado_width_yd
- Damage/casualty columns: deaths_direct, injuries_direct, damage_property

**Converter:** `data_converters/utilities/build_noaa_events.py`

---

## Frontend Architecture

### Display Models

| Model | File | Disasters |
|-------|------|-----------|
| Point+Radius | model-point-radius.js | Earthquakes, Volcanoes, Tornadoes |
| Track/Trail | model-track.js | Hurricanes, Cyclones |
| Polygon/Area | model-polygon.js | Wildfires, Floods |
| Choropleth | choropleth.js | Drought, Aggregates |
| Radial | event-animator.js | Tsunamis |

### Key Files

| File | Purpose |
|------|---------|
| `models/model-point-radius.js` | Earthquake, volcano, tornado rendering |
| `models/model-track.js` | Hurricane track rendering |
| `models/model-polygon.js` | Wildfire polygon rendering |
| `models/model-registry.js` | Routes event types to models |
| `event-animator.js` | Unified animation controller (earthquakes, tsunamis, wildfires, tornadoes) |
| `track-animator.js` | Hurricane track animation |
| `overlay-selector.js` | UI checkbox panel |
| `overlay-controller.js` | Data loading orchestration |
| `time-slider.js` | Time controls, multi-scale tabs |

### Overlay Selector

```
+------------------+
| Overlays      [x]|
+------------------+
| v Disasters      |
|   [x] Earthquakes|
|   [ ] Hurricanes |
|   [ ] Wildfires  |
|   [ ] Volcanoes  |
|   [ ] Tsunamis   |
|   [ ] Tornadoes  |
+------------------+
```

### Rolling Window + Fade

See mapping.md for more details
Events use a visibility window that scales with speed:

| Speed | Window | Effect |
|-------|--------|--------|
| 6h/sec | 24 hours | 4 data points visible |
| 1d/sec | 7 days | 1 week of events |
| 1yr/sec | 1 year | Full year visible |

Events fade from full opacity to 0 as they leave the window.

---

## API Endpoints

### GeoJSON Endpoints

| Endpoint | Parameters |
|----------|------------|
| `/api/earthquakes/geojson` | year, min_magnitude |
| `/api/storms/geojson` | year, basin |
| `/api/storms/{storm_id}/track` | - |
| `/api/volcanoes/geojson` | - |
| `/api/eruptions/geojson` | year |
| `/api/wildfires/geojson` | year |
| `/api/tsunamis/geojson` | year |
| `/api/tornadoes/geojson` | year, min_scale |

### Drill-Down Endpoints

| Endpoint | Returns |
|----------|---------|
| `/api/earthquakes/{id}/aftershocks` | Aftershock sequence |
| `/api/tsunamis/{id}/runups` | Coastal observations |
| `/api/wildfires/{id}/progression` | Daily burn snapshots |
| `/api/tornadoes/{id}` | Tornado detail with track |

---

## Unified Popup System

All disaster types use a consistent popup structure with three action buttons for progressive disclosure.

### Popup Layout

```
+------------------------------------------+
|  [Icon] EVENT TITLE                      |
|  Subtitle (location, source)             |
+------------------------------------------+
|                                          |
|  QUICK STATS (always visible)            |
|  +--------+  +--------+  +--------+      |
|  | Power  |  | Time   |  | Impact |      |
|  | M 7.2  |  | 3h 42m |  | 450 km |      |
|  +--------+  +--------+  +--------+      |
|                                          |
+------------------------------------------+
|                                          |
|  [View Details]  [Sequence]  [Related]   |
|                                          |
+------------------------------------------+
```

### Quick Stats Section

Three metric cards showing the most important info at a glance:

| Disaster | Card 1 (Power) | Card 2 (Time) | Card 3 (Impact) |
|----------|----------------|---------------|-----------------|
| **Earthquake** | Magnitude (M 7.2) | Duration (est. shaking) | Felt radius (450 km) |
| **Tsunami** | Wave height (12.5m) | Duration (hrs to coast) | Runups (47 locations) |
| **Hurricane** | Category (Cat 4) | Duration (7 days) | Max wind (140 kt) |
| **Tornado** | EF Scale (EF3) | Duration (12 min) | Path (15 mi x 400 yd) |
| **Volcano** | VEI (5) | Duration (35 days) | Ash radius (200 km) |
| **Wildfire** | Size (12,500 km2) | Duration (45 days) | Spread (5 km/day) |
| **Flood** | Severity (Large) | Duration (21 days) | Area (890 km2) |

### Three Action Buttons

#### Button 1: View Details

Zooms to the event and loads full information into an expanded popup.

**What it shows:**
- Complete event metadata
- Damage/casualty statistics
- Source attribution
- Technical measurements
- Related images/reports (if available)

**Behavior:**
1. Map zooms to event location (fit to extent)
2. Popup expands with tabbed sections
3. Time slider locks to event time range
4. Animation circle/polygon displays on map

```
+------------------------------------------+
|  [<] EARTHQUAKE DETAIL         [Close X] |
+------------------------------------------+
| [Overview] [Impact] [Technical] [Source] |
+------------------------------------------+
|                                          |
|  Overview Tab:                           |
|  - Full description                      |
|  - Location context                      |
|  - When it happened                      |
|                                          |
|  Impact Tab:                             |
|  - Deaths: 2,942                         |
|  - Injuries: 12,450                      |
|  - Displaced: 250,000                    |
|  - Damage: $14.5B USD                    |
|                                          |
|  Technical Tab:                          |
|  - Magnitude: 7.2 Mw                     |
|  - Depth: 15.4 km                        |
|  - Fault mechanism: Thrust              |
|  - Felt radius: 450 km                   |
|  - Damage radius: 35 km                  |
|                                          |
|  Source Tab:                             |
|  - USGS Event ID: us7000abc1             |
|  - Last updated: 2024-01-15 14:30 UTC    |
|  - Data source: USGS                     |
|                                          |
+------------------------------------------+
|         [View Sequence]  [View Related]  |
+------------------------------------------+
```

#### Button 2: View Sequence (Same-Type Linkages)

Shows related events of the **same disaster type** - the internal structure of the disaster.

| Disaster | Sequence Shows |
|----------|----------------|
| **Earthquake** | Mainshock + Aftershocks (Gardner-Knopoff sequence) |
| **Tsunami** | Source event + All runup observations |
| **Hurricane** | Full track with all positions |
| **Tornado** | Supercell sequence (multiple tornadoes from same storm) |
| **Volcano** | All eruption episodes for this volcano |
| **Wildfire** | Daily progression perimeters |
| **Flood** | Duration bands (flood extent over time) |

**Behavior:**
1. Query sequence API endpoint
2. Display all related points/tracks/polygons
3. Time slider shows sequence time range
4. Play button animates through sequence
5. List view shows sequence members with click-to-highlight

```
+------------------------------------------+
|  [<] AFTERSHOCK SEQUENCE       [Close X] |
+------------------------------------------+
|  Mainshock: M 7.2 - Jan 15, 2024         |
|  Aftershocks: 847 events over 90 days    |
+------------------------------------------+
|                                          |
|  [==============|----] Day 45 of 90      |
|  [|>]  1x  [>>]                          |
|                                          |
+------------------------------------------+
|  Sequence Events:                        |
|  +--------------------------------------+|
|  | * M 7.2 - Mainshock (Day 0)         ||
|  | o M 6.1 - +2 hours, 15km NE         ||
|  | o M 5.8 - +4 hours, 8km SW          ||
|  | o M 5.4 - +1 day, 22km E            ||
|  | o M 5.2 - +3 days, 45km N           ||
|  | ... (847 events)                     ||
|  +--------------------------------------+|
|                                          |
+------------------------------------------+
|               [View Related Disasters]   |
+------------------------------------------+
```

#### Button 3: View Related (Cross-Type Linkages)

Shows linked events of **different disaster types** - cascading effects.

| Primary Event | Related Events |
|---------------|----------------|
| **Earthquake** | Triggered tsunamis, triggered landslides |
| **Tsunami** | Triggering earthquake, affected coasts |
| **Hurricane** | Storm surge flooding, wind damage events |
| **Volcano** | Triggered earthquakes, triggered tsunamis |
| **Flood** | Triggering hurricane, upstream rainfall |

**Behavior:**
1. Query linked events from parent_event_id and cross-references
2. Display all linked events as pins with type icons
3. Lines connect related events
4. Click any linked event to view its popup
5. Time slider spans full cascade timeline

```
+------------------------------------------+
|  [<] RELATED DISASTERS         [Close X] |
+------------------------------------------+
|  Primary: M 9.1 Earthquake               |
|  Jan 15, 2024 - Pacific Ocean            |
+------------------------------------------+
|                                          |
|  Disaster Chain:                         |
|                                          |
|  [EQ] Earthquake M 9.1                   |
|    |                                     |
|    +---> [TS] Tsunami (12.5m max height) |
|    |       |                             |
|    |       +---> [FL] Coastal flooding   |
|    |             (47 runup locations)    |
|    |                                     |
|    +---> [LS] Landslide (triggered)      |
|                                          |
|  Timeline:                               |
|  [EQ]--10min--[TS]--3hr--[FL]            |
|                                          |
+------------------------------------------+
|  Click any event to view details         |
+------------------------------------------+
```

### Popup State Machine

```
                    +---------------+
                    |    CLOSED     |
                    +---------------+
                           |
                      (click event)
                           v
                    +---------------+
                    |    BASIC      |<---------+
                    | (quick stats) |          |
                    +---------------+          |
                     |     |     |             |
            [Details] [Sequence] [Related]     |
                     v     v     v             |
              +-------+ +-------+ +-------+    |
              |DETAIL | |SEQUENCE| |RELATED|   |
              | VIEW  | |  VIEW  | | VIEW  |   |
              +-------+ +-------+ +-------+    |
                     |     |     |             |
                     +-----+-----+             |
                           |                   |
                       [< Back]                |
                           |                   |
                           +-------------------+
```

### Data Requirements

For the popup system to work, events need these fields:

**Required (all events):**
```
event_id        -- Unique identifier
event_type      -- Disaster type
timestamp       -- Start time
latitude        -- Location
longitude       -- Location
```

**For Power Card:**
```
magnitude       -- Earthquakes (M scale)
max_water_height_m -- Tsunamis
wind_kt         -- Hurricanes
tornado_scale   -- Tornadoes (EF0-EF5)
VEI             -- Volcanoes
area_km2        -- Wildfires, Floods
```

**For Time Card:**
```
end_timestamp   -- End time (or estimated)
duration_days   -- Duration in days
duration_minutes -- Duration in minutes (short events)
```

**For Impact Card:**
```
felt_radius_km  -- Earthquakes
runup_count      -- Tsunamis
max_wind_kt     -- Hurricanes
path_length_mi  -- Tornadoes
damage_radius_km -- Volcanoes
spread_speed    -- Wildfires
```

**For Sequence Button:**
```
sequence_id     -- Links same-type events
mainshock_id    -- Aftershock parent
aftershock_count -- Number of aftershocks
has_track       -- Has track data
has_progression -- Has progression data
runup_count      -- Number of runup observations
```

**For Related Button:**
```
parent_event_id -- Cross-type trigger link
eq_event_id     -- Specific earthquake link
volcano_id      -- Specific volcano link
hurricane_id    -- Specific hurricane link
link_type       -- Relationship type
```

### Implementation Notes

1. **Progressive Loading**: Basic popup loads instantly from cached GeoJSON. Detail/Sequence/Related buttons trigger API calls.

2. **Caching**: Sequence and related data is cached after first load. Subsequent clicks are instant.

3. **Animation Integration**: All three views integrate with TimeSlider:
   - Detail view: Locks to event time, shows impact animation
   - Sequence view: Shows full sequence timeline with playback
   - Related view: Shows cascade timeline across disaster types

4. **Mobile Considerations**: On mobile, buttons become full-width. Detail view uses bottom sheet instead of popup.

5. **Accessibility**: All buttons have aria labels. Tab order: Details -> Sequence -> Related -> Close.

### API Endpoints for Popups

| Endpoint | Returns | Used By |
|----------|---------|---------|
| `/api/{type}/{id}/detail` | Full event metadata | Detail button |
| `/api/{type}/{id}/sequence` | Same-type linked events | Sequence button |
| `/api/{type}/{id}/related` | Cross-type linked events | Related button |

### Unified API Response Format

ALL sequence/animation endpoints return a standard FeatureCollection with metadata:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [lon, lat] },
      "properties": { "event_id": "...", "magnitude": 6.1, ... }
    }
  ],
  "metadata": {
    "event_id": "us7000abc1",
    "event_type": "earthquake",
    "total_count": 42
  }
}
```

**Required metadata fields:**
- `event_id` - The seed/primary event ID
- `event_type` - earthquake, tornado, tsunami, hurricane, wildfire, volcano
- `total_count` - Number of features returned

**Optional metadata fields (type-specific):**
- `aftershock_count` - Earthquakes: count excluding mainshock
- `runup_count` - Tsunamis: coastal observation count
- `sequence_id` - Tornadoes: storm system sequence ID

Example responses:

```json
// GET /api/earthquakes/aftershocks/us7000abc1
{
  "type": "FeatureCollection",
  "features": [ ... ],
  "metadata": {
    "event_id": "us7000abc1",
    "event_type": "earthquake",
    "total_count": 848,
    "aftershock_count": 847
  }
}

// GET /api/tornadoes/1272931/sequence
{
  "type": "FeatureCollection",
  "features": [ ... ],
  "metadata": {
    "event_id": "1272931",
    "event_type": "tornado",
    "total_count": 5,
    "sequence_id": "SEQ-2011-04-27-001"
  }
}

// GET /api/tsunamis/5678/runups
{
  "type": "FeatureCollection",
  "features": [ ... ],
  "source": { ... },
  "metadata": {
    "event_id": "5678",
    "event_type": "tsunami",
    "total_count": 42,
    "runup_count": 42
  }
}

// GET /api/storms/2005236N23285/track
{
  "type": "FeatureCollection",
  "features": [ ... ],
  "metadata": {
    "event_id": "2005236N23285",
    "event_type": "hurricane",
    "total_count": 31
  }
}
```

---

## Implementation Status

### Complete

- [x] Earthquake display (Point+Radius, aftershock sequences)
- [x] Volcano display (Point+Radius, cross-linking)
- [x] Hurricane display (Track/Trail, drill-down animation)
- [x] Tsunami display (Radial propagation)
- [x] Wildfire display (Polygon)
- [x] Tornado display (Point + Track drill-down)
- [x] Flood display (Point+Radius for overview, Polygon on-demand)
- [x] Time slider (variable granularity, speed control)
- [x] Overlay selector UI
- [x] EventAnimator (unified controller)
- [x] Unified DisasterPopup module (see Implementation Notes below)
- [x] Type-specific polygon layer IDs (multiple overlay types render simultaneously)
- [x] Unified hover styling (buildHoverHtml with color-coded borders)
- [x] Date range formatting (formatDate, formatDateRange)
- [x] Impact tab with deaths/injuries/damage display
- [x] Rolling time animation (lifecycle filtering, speed-adaptive windows)

### In Progress

- [ ] Fire progression animation (converter ready)
- [ ] Drought choropleth animation
- [ ] Polygon _opacity support (model-polygon.js still uses static opacity)

### Future

- [ ] Live data pipeline
- [ ] deck.gl animation effects (see [native_refactor.md](future/native_refactor.md#deckgl-animation-integration-architecture))

---

## Implementation Notes

### DisasterPopup Module

**File:** `static/modules/disaster-popup.js`

Unified popup system providing consistent styling across all disaster types.

#### Color and Icon Configuration

```javascript
const colors = {
  earthquake: '#e74c3c',    // Red
  tsunami: '#3498db',       // Blue
  volcano: '#e67e22',       // Orange
  hurricane: '#9b59b6',     // Purple
  tornado: '#27ae60',       // Green
  wildfire: '#f39c12',      // Amber
  flood: '#2980b9',         // Dark blue
  generic: '#7f8c8d'        // Gray
};

const icons = {
  earthquake: 'E', tsunami: 'W', volcano: 'V',
  hurricane: 'H', tornado: 'T', wildfire: 'F', flood: 'FL'
};
```

#### Key Formatting Methods

| Method | Purpose | Example Output |
|--------|---------|----------------|
| `formatPower(props, type)` | Intensity metric | `{ label: 'Magnitude', value: 'M 7.2', detail: 'Mw' }` |
| `formatTime(props, type)` | Duration/timing | `{ label: 'Duration', value: '45 days', detail: '' }` |
| `formatImpact(props, type)` | Impact metric | `{ label: 'Deaths', value: '2.9K', detail: '' }` |
| `formatDate(timestamp)` | Single date | `"Jan 15, 2024"` |
| `formatDateRange(start, end)` | Date range | `"Jul 28 - Aug 5, 2024"` |
| `formatCurrency(value)` | USD formatting | `"$14.5B"` |
| `formatLargeNumber(num)` | Number abbreviation | `"2.9K"` |

#### Popup Tabs

Four tabs in detailed view, built by separate methods:

| Tab | Method | Content |
|-----|--------|---------|
| Overview | `buildOverviewTab()` | Location, coordinates, date/duration, type-specific context |
| Impact | `buildImpactTab()` | Deaths, injuries, displaced, property/crop damage |
| Technical | `buildTechnicalTab()` | Magnitude, depth, VEI, wind speed, path dimensions |
| Source | `buildSourceTab()` | Data source links, event IDs |

#### Hover Popup

`buildHoverHtml(props, eventType)` creates compact hover tooltip:
- Color-coded left border matching disaster type
- Icon badge with type color
- Event title
- Date (range if available)
- Primary intensity value
- "Click for details" hint

### Polygon Model Type-Specific Layers

**File:** `static/modules/models/model-polygon.js`

Supports multiple polygon overlay types (floods + wildfires) rendering simultaneously without layer ID conflicts.

#### Layer ID Pattern

```javascript
_layerId(baseId, eventType) {
  return `${eventType}-polygon-${baseId}`;
}
// Examples: 'flood-polygon-fill', 'wildfire-polygon-stroke'
```

#### State Tracking

```javascript
activeTypes: new Set(),           // Set of active event types
clickHandlers: new Map(),         // eventType -> click handler function
hoverHandlers: new Map(),         // eventType -> {mouseenter, mouseleave, mousemove, mouseleavePopup}
```

#### Handler Cleanup

Named functions stored for proper `map.off()` cleanup:

```javascript
// On render - store named handlers
this.hoverHandlers.set(eventType, {
  mouseenter: mouseenterHandler,
  mouseleave: mouseleaveHandler,
  mousemove: mousemoveHandler,
  mouseleavePopup: mouseleavePopupHandler
});

// On clear - remove by reference
const hoverH = this.hoverHandlers.get(eventType);
map.off('mouseenter', fillId, hoverH.mouseenter);
map.off('mouseleave', fillId, hoverH.mouseleave);
// ...
```

### Rolling Time Animation

**Files:**
- `static/modules/overlay-controller.js` - EVENT_LIFECYCLE config, filterByLifecycle()
- `static/modules/time-slider.js` - getWindowDuration(), speed-adaptive windows
- `static/modules/event-animator.js` - Rolling mode support

#### Event Lifecycle Configuration

Events appear based on timestamp, stay visible during active period, then fade out:

```
Timeline:
    start_ms              end_ms                  fade_ms
        |                    |                       |
        v                    v                       v
--------|====================|~~~~~~~~~~~~~~~~~~~~~~~|--------
        |     ACTIVE         |       FADING          |
        |   (full opacity)   |   (opacity 1.0->0)    |
```

Per-type lifecycle in EVENT_LIFECYCLE (overlay-controller.js:123-275):

| Type | Start Field | End Calculation | Fade Duration |
|------|-------------|-----------------|---------------|
| Earthquake | `timestamp` | Magnitude-based (4-30 days) | Magnitude-scaled |
| Hurricane | `start_date` | `end_date` | 30 days |
| Tsunami | `timestamp` | Wave speed + max distance | 7 days |
| Volcano | `timestamp` | end_timestamp or duration_days | 30 days |
| Tornado | `timestamp` | Path length estimate | 1 day |
| Wildfire | `timestamp` | duration_days or 30 days | 14 days |
| Flood | `timestamp` | end_timestamp or duration_days | 30 days |

#### filterByLifecycle Function

Returns features annotated with animation properties:

```javascript
// overlay-controller.js:287-397
function filterByLifecycle(features, currentMs, eventType) {
  // Returns features with:
  // - _opacity: 0-1 for fade effect
  // - _phase: "active" or "fading"
  // - _radiusProgress: 0-1 for expanding circles
  // - _waveRadiusKm: Current wave radius in km
}
```

#### _opacity Support in Models

| Model | _opacity Support | Notes |
|-------|-----------------|-------|
| model-point-radius.js | Yes (13 instances) | circle-opacity, circle-stroke-opacity |
| model-track.js | Yes | line-opacity for track and glow layers |
| model-polygon.js | No | Still uses static fillOpacity values |

Point radius example (model-point-radius.js:815-828):

```javascript
const lifecycleOpacity = ['coalesce', ['get', '_opacity'], 1.0];
const opacityExpr = (baseOpacity) => [
  'min', 1.0,
  ['*', baseOpacity, ['*', recencyExpr, lifecycleOpacity]]
];
```

#### Speed-Adaptive Windows

Window duration scales with playback speed (time-slider.js:104-107):

```javascript
getWindowDuration(stepsPerFrame) {
  const WINDOW_MULTIPLIER = 4;
  return this.BASE_STEP_MS * Math.max(1, stepsPerFrame) * WINDOW_MULTIPLIER;
}
```

| Speed | Window Duration | Effect |
|-------|-----------------|--------|
| Slow | Shorter window | Only recent events |
| Fast | Longer window | More events accumulate |

Adaptive fade (time-slider.js:872-881):

```javascript
getEventOpacity(eventTime, currentTime) {
  const windowDuration = this.getVisibilityWindow();
  const age = currentTime - eventTime;
  // Linear fade from 1.0 (new) to 0.2 (about to disappear)
  return 1.0 - (age / windowDuration) * 0.8;
}
```

#### Hurricane Rolling Mode

Hurricanes use TrackAnimator.startRolling() for progressive track drawing during rolling playback (overlay-controller.js:2950-3023).

---

## Live Data Sources (Future)

See `docs/future/native_refactor.md` for planned live architecture.

**Key APIs:**
- USGS Earthquakes: Real-time, minutes latency
- NASA FIRMS: 12-hour latency, global fires
- NOAA DART Buoys: 15-second samples during tsunami events
- IOC Sea Level: 1-minute values globally

---

## Known Issues

**Volcano prehistoric data:** Smithsonian GVP includes eruptions back to ~1280 CE which overflow pandas datetime. Only 36% have valid timestamps.

**Map projection:** Globe projection disabled due to animation interference. Uses Mercator only.

---

*Last Updated: 2026-01-12*
