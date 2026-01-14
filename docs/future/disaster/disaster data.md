# Disaster Data Inventory

Data download status and research notes.

**Technical schemas**: See [DISASTER_DISPLAY.md](DISASTER_DISPLAY.md)
**Import guide**: See [data_import.md](data_import.md)
**Source attribution**: See [public reference.md](public%20reference.md)

---

## Global Disaster Sources

Location: `county-map-data/global/`

| Source | Path | Total Records | Filtered (frontend) | Years |
|--------|------|---------------|---------------------|-------|
| USGS Earthquakes | earthquakes/ | 1,055,868 | 2,804 (M5.5+, 2020+) | 2150 BC-2026 |
| IBTrACS Hurricanes | tropical_storms/ | 13,541 storms | 273 (Cat1+, 2020+) | 1842-2026 |
| NOAA Tsunamis | tsunamis/ | 2,619 events | 105 (2020+) | -2000-2025 |
| Smithsonian Volcanoes | smithsonian_volcanoes/ | 11,079 eruptions | 194 (2020+) | Holocene |
| Global Wildfires | wildfires/by_year/ | ~940K/year | ~3,200/year (100km2+) | 2002-2024 |
| Global Floods | floods/ | 4,825 events | 1,239 (2010+) | 1985-2019 |
| Global Landslides | landslides/ | 45,483 events | TBD | 1760-2025 |

### Frontend Filter Summary

Default overlay filters (in overlay-controller.js) reduce data for initial load:

| Overlay | Filter | Rationale |
|---------|--------|-----------|
| Earthquakes | M5.5+, 2020+ | Significant events only |
| Hurricanes | Cat1+, 2020+ | Named hurricanes, excludes TD/TS |
| Tornadoes | EF2+, 2020+ | Significant damage threshold |
| Wildfires | 100km2+, 2020+ | Major fires only |
| Volcanoes | 2020+ | Small dataset, no severity filter |
| Tsunamis | 2020+ | Small dataset, no severity filter |
| Floods | 2010+ | Data ends 2019 |

---

## US-Specific Sources

Location: `county-map-data/countries/USA/`

| Source | Path | Total Records | Filtered | Years |
|--------|------|---------------|----------|-------|
| NOAA Storms (all) | noaa_storms/ | 1.2M events | - | 1950-2025 |
| - Tornadoes | (subset) | 79,038 | 1,154 (EF2+, 2020+) | 1950-2025 |
| FEMA Disasters | fema_disasters/ | 46,901 | - | 1953-2025 |
| FEMA NRI | fema_nri/ | 12,747 | - | 2021-2025 |
| US Wildfires | wildfires/ | 30,733 | - | 1984-2023 |
| US Drought Monitor | usdm_drought/ | 90,188 | - | 2000-2026 |
| Wildfire Risk | wildfire_risk/ | 3,144 | - | 2022 snapshot |

---

## Raw Data Status

Location: `county-map-data/Raw data/`

**Note:** See [RAW_DATA_CLEANUP_STATUS.md](RAW_DATA_CLEANUP_STATUS.md) for detailed cleanup guidance

### Converted (Raw Data Can Be Deleted)

| Source | Raw Size | Processed Location | Records |
|--------|----------|-------------------|---------|
| Eurostat NUTS 3 | 6 MB | global/eurostat/ | NUTS3 regions |
| ReliefWeb | Empty | global/reliefweb_disasters/ | 18,371 disasters |
| DesInventar | ~100 MB | global/desinventar/ | 86 countries |
| PAGER-CAT | 31 MB | global/pager_cat/ | 7,500+ earthquakes |
| NASA Landslides | 3.4 MB | global/nasa_landslides/ | 11,033 events |
| Flood Events (GFM/GFD) | 2 MB | global/floods/ | 4,825 events |
| Canada Earthquakes | 12 MB | countries/CAN/nrcan_earthquakes/ | 101,366 events |
| Australia Cyclones | 7.6 MB | countries/AUS/bom_cyclones/ | 31,221 positions |

**Action:** Raw data for above sources can be deleted (keep metadata JSONs for re-download info)

### Unprocessed (Needs Decision)

| Source | Size | Location | Recommendation |
|--------|------|----------|----------------|
| Canada Fire (CNFDB) | 789 MB | Raw data/imported/canada/cnfdb/ | **PROCESS - fills critical gap** |
| Canada Drought | 1.0 GB | Raw data/imported/canada/drought/ | **PROCESS - no global drought** |
| EPA Air Quality | 2.8 MB | Raw data/imported/epa_aqs/ | OUT OF SCOPE? |
| EIA Energy | 1.4 GB | Raw data/eia/ | OUT OF SCOPE? |
| HDX/EM-DAT | 390 KB | Raw data/imported/hdx/ | DELETE - DesInventar covers this |

**Note:** See [CANADA_DATA_ANALYSIS.md](CANADA_DATA_ANALYSIS.md) for detailed drought/fire gap analysis.

---

## Download Scripts

Location: `data_converters/downloaders/`

### Global
| Script | Status |
|--------|--------|
| download_global_earthquakes.py | Working |
| download_ibtracs.py | Working |
| download_global_volcanoes.py | Working |
| download_global_tsunamis.py | Working |
| download_flood_events.py | Working |
| download_lance_floods.py | Built (needs Earthdata account) |
| download_nasa_firms.py | Working |

### USA
| Script | Status |
|--------|--------|
| download_fema_all.py | Working |
| download_and_extract_noaa.py | Working |
| download_usdm_drought.py | Working |

### Canada
| Script | Status |
|--------|--------|
| download_canada_fires.py | Working |
| download_canada_earthquakes.py | Working |

### Other
| Script | Status |
|--------|--------|
| download_australia_cyclones.py | Working |
| download_hdx_disasters.py | Working |
| download_reliefweb.py | Working |

---

## Data Gaps

### Remaining Gaps

| Hazard | Current | Gap |
|--------|---------|-----|
| Floods | 1985-2019 | 2020-present (use LANCE + event triggers) |
| Heat/Cold Wave | Limited NOAA | NCEI temperature extremes |
| Pre-2000 Drought | USDM 2000+ | Palmer Drought Index |
| Coastal Flooding | Model only | Event database |

### Blocked Sources

| Source | Issue |
|--------|-------|
| FEMA NFHL Flood Zones | hazards.fema.gov infrastructure down |
| Canadian Disaster Database | Interactive only, no bulk API |

---

## Future Work

See [disaster_upgrades.md](future/disaster_upgrades.md) for comprehensive upgrade plans including:
- Fire aggregates product (multi-region fire impact tracking)
- Global fire risk product (inspired by US USFS wildfire risk)
- loc_id enrichment for fires and floods
- Fire progression data gaps (2008 incomplete)
- Live data pipeline integration

**In Progress:**
- Fill flood gap 2020-present (event-driven LANCE approach)
- Create converters for international data (Canada, Australia, Europe)
- Import international geometry (LGA, CSD, NUTS boundaries)
- Fire/flood loc_id enrichment (~20 hours processing)

**Blocked:**
- FEMA NFHL flood zones (infrastructure down)

**Low Priority:**
- NRI Census Tracts (85K+ records, finer granularity)
- CDC PLACES county health data
- NOAA Sea Level Rise projections

---

---

## Impact Data Sources

Location: `county-map-data/global/`

### Converted Multi-Hazard Databases

| Source | Events | Coverage | Impact Data | Status |
|--------|--------|----------|-------------|--------|
| **DesInventar** | 86 countries | Multi-hazard | Deaths, injuries, damage, houses destroyed | COMPLETE |
| **ReliefWeb** | 18,371 disasters | Global, 1981+ | Humanitarian impact (text-based) | COMPLETE |
| **PAGER-CAT** | 7,500+ earthquakes | Global, 1900-2007 | Deaths, injuries, damage (detailed) | COMPLETE |

### Unified Landslide Catalog

**Source:** Merged from DesInventar, NASA GLC, and NOAA Debris Flows
**Location:** `global/landslides/`

| Metric | Value |
|--------|-------|
| Total Events | 45,483 unique events |
| Countries | 160 |
| Time Span | 1760-2025 (344 years) |
| Deaths Documented | 60,485 |
| Injuries Documented | 17,499 |
| Damage (US only) | $1.6 billion |

**Source breakdown:**
- DesInventar: 32,039 landslides (33 countries, Latin America + South Asia)
- NASA GLC: 10,937 landslides (116 countries, global news-based)
- NOAA: 2,411 debris flows (39 US states)
- Multi-source verified: 96 events (0.2%)

**Key features:**
- Multi-source verification for critical events
- Structured impact data (no text parsing needed)
- Geographic precision with lat/lon coordinates
- Country-level source tracking in metadata

---

*Last Updated: January 2026*
