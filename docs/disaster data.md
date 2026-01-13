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
| USGS Earthquakes | usgs_earthquakes/ | 1,053,285 | 2,804 (M5.5+, 2020+) | 1900-2026 |
| IBTrACS Hurricanes | tropical_storms/ | 13,541 storms | 273 (Cat1+, 2020+) | 1842-2026 |
| NOAA Tsunamis | tsunamis/ | 2,619 events | 105 (2020+) | -2000-2025 |
| Smithsonian Volcanoes | smithsonian_volcanoes/ | 11,079 eruptions | 194 (2020+) | Holocene |
| Global Wildfires | wildfires/by_year/ | ~940K/year | ~3,200/year (100km2+) | 2002-2024 |
| Global Floods | floods/ | 4,825 events | 1,239 (2010+) | 1985-2019 |

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

## Raw Data (Downloaded, Needs Processing)

Location: `county-map-data/Raw data/`

### Canada
| Source | Size | Status |
|--------|------|--------|
| Canada Fire (CNFDB) | 789 MB | Downloaded |
| Canada Drought | 1.0 GB | Downloaded |
| Canada Earthquakes | 12 MB | Downloaded |

### Australia
| Source | Size | Status |
|--------|------|--------|
| Australia Cyclones | 7.6 MB | Downloaded |

### Europe
| Source | Size | Status |
|--------|------|--------|
| Eurostat NUTS 3 | 5.9 MB | Downloaded |

### Other/Global
| Source | Size | Status |
|--------|------|--------|
| HDX/EM-DAT Global | 390 KB | Downloaded |
| ReliefWeb | 6.9 MB | Downloaded |
| EPA Air Quality | 2.8 MB | Downloaded |
| EIA Energy | 1.4 GB | Downloaded |
| Flood Events (GFM) | 732 KB | Downloaded |
| Flood Events (GFD) | 1.2 MB | Downloaded |

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
| DesInventar (82 countries) | Server defunct |
| Canadian Disaster Database | Interactive only, no bulk API |

---

## Future Work

**In Progress:**
- Fill flood gap 2020-present (event-driven LANCE approach)
- Create converters for international data (Canada, Australia, Europe)
- Import international geometry (LGA, CSD, NUTS boundaries)

**Blocked:**
- FEMA NFHL flood zones (infrastructure down)

**Low Priority:**
- NRI Census Tracts (85K+ records, finer granularity)
- CDC PLACES county health data
- NOAA Sea Level Rise projections

---

*Last Updated: January 2026*
