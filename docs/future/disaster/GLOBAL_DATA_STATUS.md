# Global Disaster Data Status
*Updated: 2026-01-13*

## Completed Cleanups

### 1. Floods - Finalized
- **Action:** Replaced `events.parquet` with enriched version
- **Status:** COMPLETE
- **Records:** 4,825 flood events (1985-2019)
- **Columns:** 24 (added loc_confidence, parent_loc_id, sibling_level, iso3, perimeter)
- **Impact Data:** 3,400 with deaths, 3,395 with displaced
- **Deleted:** events_with_geometry.parquet (redundant)

### 2. Earthquakes - Duplicate Removed
- **Action:** Deleted obsolete `usgs_earthquakes/` folder
- **Status:** COMPLETE
- **Freed:** 45MB disk space
- **Current:** `earthquakes/` folder with NOAA impact data merged
- **Records:** 1,055,868 events (2150 BC - 2026)
- **Impact Data:** 1,992 with deaths

### 3. Scripts - Moved to Proper Location
- **Action:** Moved misplaced scripts from county-map-data to county-map
- **Files Moved:**
  - `data_converters/converters/convert_fire_progression.py`
  - `scripts/simplify_geometry.py`
- **Folders Cleaned:** Removed empty data_converters/ and scripts/ from county-map-data

### 4. Volcanoes - NOAA Impact Data Merged
- **Action:** Merged NOAA significant volcanic eruptions impact data
- **Status:** COMPLETE
- **Script Created:** `merge_noaa_volcano_impact.py`
- **Records:** 11,079 volcanic eruptions
- **Matches:** 170 events matched with NOAA data (1.5%)
- **Impact Data Added:**
  - 101 events with deaths (70,894 total deaths recorded)
  - 28 events with injuries
  - 1 event with damage data
  - 16 events with houses destroyed
- **New Columns:** deaths, injuries, missing, damage_usd, houses_destroyed, eruption_agent, noaa_id
- **Deadliest:** Mount Etna 1169 (16,000 deaths)

### 5. Temp Files - Cleaned
- **Action:** Deleted obsolete temp folder with volcano page downloads
- **Freed:** 437KB disk space

### 6. Floods Geometries - Consolidated
- **Action:** Deleted redundant geometries folder
- **Status:** COMPLETE
- **Reason:** Geometry data was duplicated - identical polygons stored in both `geometries/` folder and `perimeter` column
- **Verification:** Sampled multiple events - all geometries identical between folder and parquet
- **Freed:** 13MB disk space (4,825 redundant GeoJSON files)
- **Result:** All flood extent polygons remain available in the `perimeter` column

### 7. Country-Specific Redundant Data - Cleaned
- **Action:** Deleted country folders with data already in global datasets
- **Status:** COMPLETE
- **Deleted:**
  - `countries/CAN/tornadoes/` (128KB) - All 2,673 events already in global tornadoes
- **Kept (unique regional data):**
  - `countries/CAN/nrcan_earthquakes/` - 101,366 events vs 339 in global (valuable regional detail)
  - `countries/AUS/bom_cyclones/` - 31,221 positions (Australian regional data)
  - `countries/USA/wildfires/` - 30,733 MTBS fires (different source/schema than global FIRMS)
  - `countries/USA/noaa_storms/` - Severe weather events (distinct from tropical storms)
  - All demographic data (eurostat, census, population folders)

---

## Current Global Dataset Status

| Dataset | Records | Has Impact Data | Has loc_id | Status |
|---------|---------|-----------------|------------|--------|
| **earthquakes** | 1,055,868 | YES (deaths, injuries, damage_millions, houses_destroyed) | YES | COMPLETE |
| **smithsonian_volcanoes** | 11,079 | YES (deaths, injuries, damage_usd, houses_destroyed) | YES | COMPLETE |
| **tsunamis** | 2,619 | YES (deaths, damage_millions) | YES | COMPLETE |
| **floods** | 4,825 | YES (deaths, displaced, damage_usd) | YES | COMPLETE |
| **tropical_storms** | 13,541 | NO (track data only) | YES (basin) | COMPLETE |
| **landslides** | 45,483 | YES (deaths, injuries, damage_usd) | YES | COMPLETE |
| **tornadoes** | 81,711 | YES (deaths_direct/indirect, damage_property) | YES | COMPLETE |
| **wildfires** | ~815K/year | NO | YES (2018-2024 enriched) | IN PROGRESS |

### Impact Data Sources

| Dataset | Records | Coverage | Status |
|---------|---------|----------|--------|
| **reliefweb_disasters** | 18,371 | Global, 1981+ | COMPLETE |
| **desinventar** | 86 countries | Multi-hazard | COMPLETE |
| **pager_cat** | 7,500+ | Earthquakes 1900-2007 | COMPLETE |

---

## Wildfires Status

### Enriched Years (has loc_id)
- 2018: 175,000 fires enriched
- 2019: 883,922 fires enriched
- 2020: 941,872 fires enriched
- 2021: 811,489 fires enriched
- 2022: 799,297 fires enriched
- 2023: 815,152 fires enriched
- 2024: 106,615 fires enriched

### Fire Progression Status
- 2018-2019: Progression files NEED loc_id finalization (pending)
- 2020-2024: Progression files HAVE loc_id (complete)

**Note:** Fire enrichment is ongoing - finalization deferred

---

## Analysis Completed

### 8. US Risk Assessment Data - Comparison with Global Plans
- **Action:** Analyzed existing US risk data and compared with proposed global unified aggregate schema
- **Status:** COMPLETE
- **Documents Created:** US_RISK_DATA_COMPARISON.md
- **Datasets Analyzed:**
  - FEMA NRI (National Risk Index) - 12,747 counties, 18 hazard types, 0-100 risk scale
  - Wildfire Risk - 3,144 counties, percentile-based scoring (state vs national)
  - FEMA Disasters - 48,875 county-years (1953-2025) with disaster counts
- **Key Findings:**
  - FEMA NRI pattern: `{HAZARD}_EVNTS`, `{HAZARD}_RISKS`, `{HAZARD}_AFREQ` validates our approach
  - Percentile-based risk scoring (Wildfire Risk) easier to interpret than raw scores
  - Multi-hazard composite risk (18 hazards) confirms value of our unified schema
  - US data lacks impact metrics (deaths, damage) - our global schema will improve this
- **Recommendation:** Keep US-specific products separate, create parallel global aggregates with standardized schema

### 9. HazardAware.org Sources - Evaluation for Future Use
- **Action:** Analyzed HazardAware.org data sources for potential downloads or pattern adoption
- **Status:** COMPLETE
- **Sources Evaluated:**
  - SHELDUS (Spatial Hazard Events and Losses Database) - county-level US, 1960-present
  - FEMA NRI - already have this
  - SoVI (Social Vulnerability Index) - out of scope (social vulnerability)
  - BRIC (Baseline Resilience Indicators) - out of scope (resilience)
  - EVI (Environmental Vulnerability Index) - out of scope (ecosystem vulnerability)
- **Key Decisions:**
  - DO NOT download SHELDUS - redundant with our NOAA Storm Events, MTBS fires, etc.
  - SHELDUS validates our approach (county-level, impact data, temporal coverage)
  - FEMA NRI already in countries/USA/fema_nri/
- **Patterns to Adopt:**
  - Population normalization: deaths_per_100k, damage_per_capita
  - Inflation adjustment: damage_usd_adjusted with base year (2024)
  - Crop damage separate tracking (if agricultural data added later)
- **Alignment Confirmed:** Our disaster_upgrades.md unified aggregate schema aligns with industry standards

### 10. Unified Landslide Catalog - COMPLETE
- **Action:** Merged 3 complementary landslide datasets into unified global catalog
- **Status:** COMPLETE
- **Output:** `global/landslides/events.parquet` and `metadata.json`
- **Sources Merged:**
  - DesInventar: 32,044 landslides from 33 countries (1700-2104)
  - NASA Global Landslide Catalog: 11,033 landslides from 140 countries (1988-2017)
  - NOAA Debris Flows: 2,502 events from 39 US states (1996-2025)
- **Final Statistics:**
  - Total Unique Events: 45,483
  - Countries Covered: 160
  - Time Span: 1760-2025 (344 years)
  - Events with Deaths: 7,586 (16.7%)
  - Total Deaths: 60,485
  - Total Injuries: 17,499
  - Total Damage: $1.6 billion USD
  - Duplicates Removed: 96 (0.2% dedup rate)
- **Key Achievement:** Multi-source verification for critical events, structured impact data, geographic precision with coordinates

---

## Pending Work

### 1. Fire Progression Finalization (2018-2019)
- Run `finalize_fires.py --year 2018 --year 2019`
- Adds loc_id columns from enriched fires to progression files
- Deferred until fire enrichment completes

### 2. Country-Specific Data Review
**Regional datasets to evaluate:**
- `countries/CAN/nrcan_earthquakes/` - 101,366 events (only 339 in global)
- `countries/AUS/bom_cyclones/` - 31,221 positions (2,764 in global)
- `countries/USA/wildfires/` - 30,733 MTBS fires (different source than global FIRMS)

**Decision:** Keep as regional supplements for country-specific analysis

---

## Data Quality Improvements Completed

1. **Floods loc_id:** Fixed from NULL to proper location IDs (e.g. "FLOOD-DFO-1")
2. **Floods enrichment:** Added parent_loc_id, sibling_level, iso3, loc_confidence
3. **Earthquakes consolidation:** Single authoritative source with impact data
4. **Script organization:** All converter scripts in proper county-map location

---

## Unified Column Naming (Active)

### Standard Impact Columns
| Column | Type | Used By |
|--------|------|---------|
| deaths | int32 | earthquakes, volcanoes, floods, tsunamis, (tornadoes as deaths_direct) |
| injuries | int32 | earthquakes, volcanoes, (tornadoes as injuries_direct) |
| missing | int32 | volcanoes |
| displaced | int32 | floods |
| damage_usd | float64 | volcanoes, floods, (earthquakes as damage_millions) |
| houses_destroyed | int32 | earthquakes, volcanoes |
| houses_damaged | int32 | (none yet) |

**Note:** Frontend handles column variations via fallback chains

---

## Files Modified This Session

### Deleted
- `global/usgs_earthquakes/` (45MB, obsolete)
- `global/floods/events_with_geometry.parquet` (redundant)
- `global/floods/events.parquet` (replaced by enriched)
- `global/floods/geometries/` (13MB, 4,825 redundant GeoJSON files)
- `global/temp/` (437KB, volcano page downloads)
- `countries/CAN/tornadoes/` (128KB, all 2,673 events in global)
- `county-map-data/data_converters/` (empty folder)
- `county-map-data/scripts/` (empty folder)

### Created/Renamed
- `global/floods/events.parquet` (from events_enriched.parquet)
- `global/landslides/events.parquet` (unified catalog from 3 sources)
- `global/landslides/metadata.json` (country-level source tracking)
- `global/desinventar/events.parquet` and `GLOBAL.parquet` (multi-hazard database)
- `global/nasa_landslides/events.parquet` (global landslide catalog)
- `global/noaa_debris_flows/events.parquet` (US debris flows)
- `global/pager_cat/events.parquet` (earthquake impacts 1900-2007)
- `global/reliefweb_disasters/events.parquet` (humanitarian disasters)
- `county-map/data_converters/converters/merge_noaa_volcano_impact.py` (new script)
- `county-map/data_converters/converters/merge_landslide_sources.py` (new script)

### Modified
- `global/smithsonian_volcanoes/events.parquet` (added impact columns from NOAA)
- `global/smithsonian_volcanoes/metadata.json` (updated with merge stats)
- `global/earthquakes/events.parquet` (added impact columns from NOAA and PAGER-CAT)
- `global/floods/metadata.json` (updated with enriched columns, removed geometries folder reference)

### Moved
- `convert_fire_progression.py` -> county-map/data_converters/converters/
- `simplify_geometry.py` -> county-map/scripts/

---

## Next Steps (Priority Order)

1. Complete fire enrichment for remaining years (2002-2017) - run overnight
2. Run finalize_fires for 2018-2019 progression after enrichment completes
3. Implement unified aggregate schema (see disaster_upgrades.md) for risk scoring and multi-hazard analysis
4. Add population normalization and inflation adjustment metrics to aggregate schema

---

*This document tracks the consolidation and unification of global disaster data for the county-map project.*
