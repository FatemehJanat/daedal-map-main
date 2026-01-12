# Disaster Data Inventory

Data download status and research notes.

**Technical schemas**: See [DISASTER_DISPLAY.md](DISASTER_DISPLAY.md)
**Import guide**: See [data_import.md](data_import.md)
**Source attribution**: See [public reference.md](public%20reference.md)

---

## Processed Data (Ready for Map)

Location: `county-map-data/`

| Source | File | Records | Coverage |
|--------|------|---------|----------|
| FEMA NRI | USA.parquet | 12,747 | 2021-2025, 18 hazards |
| FEMA Disasters | USA.parquet | 46,901 | 1953-2025 |
| NOAA Storms | events.parquet | 1.2M | 1950-2025 |
| USGS Earthquakes | events.parquet | 1M+ | Global 1900+ |
| IBTrACS Hurricanes | storms.parquet + positions.parquet | 14K storms | Global 1842+ |
| NOAA Tsunamis | events.parquet + runups.parquet | 2,600 events | Global, historical |
| Smithsonian Volcanoes | events.parquet | 11,000 eruptions | Holocene |
| Global Fire Atlas | fires.parquet | 2GB+ | Global 2003-2016 |
| MTBS Wildfires | events.parquet | 25,000 | USA 1984-2023 |
| US Drought Monitor | USA.parquet | 90,188 | 2000-2026 |
| Wildfire Risk | USA.parquet | 3,144 | 2022 snapshot |
| Global Floods | events.parquet | 4,825 | 1985-2019 |

---

## Raw Data (Downloaded, Needs Processing)

Location: `county-map-data/Raw data/`

| Source | Size | Status |
|--------|------|--------|
| Canada Fire (CNFDB) | 789 MB | Downloaded |
| Canada Drought | 1.0 GB | Downloaded |
| Canada Earthquakes | 12 MB | Downloaded |
| Australia Cyclones | 7.6 MB | Downloaded |
| HDX/EM-DAT Global | 390 KB | Downloaded |
| ReliefWeb | 6.9 MB | Downloaded |
| EPA Air Quality | 2.8 MB | Downloaded |
| EIA Energy | 1.4 GB | Downloaded |
| Eurostat NUTS 3 | 5.9 MB | Downloaded |

---

## Download Scripts

Location: `data_converters/`

| Script | Status |
|--------|--------|
| download_fema_all.py | Working |
| download_and_extract_noaa.py | Working |
| download_usdm_drought.py | Working |
| download_canada_fires.py | Working |
| download_canada_earthquakes.py | Working |
| download_australia_cyclones.py | Working |
| download_hdx_disasters.py | Working |
| download_reliefweb.py | Working |

---

## Data Gaps

### Remaining Gaps

| Hazard | Current | Gap |
|--------|---------|-----|
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
