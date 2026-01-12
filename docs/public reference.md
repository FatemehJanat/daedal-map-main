# Data Sources Reference

Attribution and links for all data sources used in the mapping system.

**Technical schemas**: See [DISASTER_DISPLAY.md](DISASTER_DISPLAY.md) | **Import guide**: See [data_import.md](data_import.md)

---

## Disaster Event Data

| Source | Organization | Coverage | Status |
|--------|--------------|----------|--------|
| **Volcanoes** | Smithsonian GVP | Global, Holocene-present | COMPLETE |
| **Tsunamis** | NOAA NCEI | Global, 2100 BC-present | COMPLETE |
| **Hurricanes** | NOAA IBTrACS | Global, 1842-present | COMPLETE |
| **Earthquakes** | USGS | Global, 1900-present | Needs historical |
| Tornadoes | NOAA Storm Events | USA/Canada only | Regional |
| Wildfires | NASA/USFS | Fragmented sources | Gaps |
| Floods | Cloud to Street/DFO | Global, 1985-2019 | Ends 2019 |

**COMPLETE** = Full global coverage, maximum historical depth, live update source available

### Historical Earthquake Sources (To Add)

| Source | Coverage | Events |
|--------|----------|--------|
| [NOAA Significant Earthquakes](https://www.ngdc.noaa.gov/hazel/view/hazards/earthquake/search) | 2150 BC-present | ~5,700 |
| [GHEC Catalogue](https://storage.globalquakemodel.org/what/seismic-hazard/historical-catalogue/) | 1000-1903 AD | ~800 (M7+) |

---

## Risk & Climate Data

| Source | Organization | Coverage |
|--------|--------------|----------|
| FEMA NRI | FEMA | US counties, 18 hazards |
| Drought Monitor | NDMC/USDA/NOAA | USA 2000+, Canada 2019+ |
| Wildfire Risk | US Forest Service | US counties |
| FEMA Disasters | FEMA | US 1953-present |

---

## Demographics & Boundaries

| Source | Organization | Coverage |
|--------|--------------|----------|
| US Census | Census Bureau | US counties/tracts |
| Canada Census | Statistics Canada | CSDs/DAs |
| Australia ABS | ABS | LGAs/SA2s |
| Eurostat | European Commission | NUTS 3 regions |
| Boundaries | Natural Earth | Global countries |

---

## Licensing

| Source | License |
|--------|---------|
| US Government (NOAA/USGS/FEMA/Census) | Public Domain |
| Statistics Canada | Open Government License - Canada |
| Smithsonian GVP | Creative Commons |
| Natural Earth | Public Domain |

---

## Live Data APIs

| Source | Endpoint | Update Frequency |
|--------|----------|------------------|
| USGS Earthquakes | earthquake.usgs.gov/fdsnws/event/1/ | Real-time |
| Smithsonian Volcanoes | volcano.si.edu | Weekly reports |
| IBTrACS Storms | ncei.noaa.gov | Near real-time |
| NOAA Tsunamis | ngdc.noaa.gov | As events occur |

---

*Last Updated: January 2026*
