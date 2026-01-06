# County Map - Data Sources Exploration

Quick reference for potential data sources to expand risk scoring capabilities.

Last Updated: January 6, 2026

---

## QUICK REFERENCE: Current Data Inventory

### Processed Data (Ready for Map)
Location: `county-map-data/countries/USA/`

| Source | File | Size | Records | Time Range | Key Metrics |
|--------|------|------|---------|------------|-------------|
| FEMA NRI | USA.parquet | 5.7 MB | 12,747 | 2021-2025 | 18 hazard risk scores |
| FEMA NRI Full | USA_full.parquet | 8.5 MB | 3,232 | Latest | 467 fields |
| FEMA Disasters | USA.parquet | 0.24 MB | 46,901 | 1953-2025 | Declaration counts by type |
| NOAA Storms | USA.parquet | 1 MB | 159,651 | 1950-2025 | 41 event type columns |
| NOAA Storms Events | events.parquet | 28 MB | 1,231,663 | 1950-2025 | Individual storm records |
| USGS Earthquakes | USA.parquet | 61 KB | 7,680 | 1970-2025 | County-year aggregates |
| USGS Earthquakes Events | events.parquet | 5.7 MB | 173,971 | 1970-2025 | Individual quakes 3.0+ |
| US Drought Monitor | USA.parquet | 0.67 MB | 90,188 | 2000-2026 | D0-D4 severity weeks |
| Wildfire Risk | USA.parquet | 112 KB | 3,144 | 2022 snapshot | Burn probability, exposure |

### Raw Data (Downloaded, Needs Processing)
Location: `county-map-data/Raw data/`

| Source | Location | Size | Content |
|--------|----------|------|---------|
| **FEMA** | `fema/nri_counties/` | 141 MB | 4 NRI versions JSON |
| **FEMA** | `fema/disasters/` | 60 MB | Disaster declarations JSON |
| **Canada Fire** | `canada/cnfdb/` | 789 MB | Fire points + polygons (shapefiles) |
| **Canada Drought** | `canada/drought/` | 1.0 GB | 325 monthly GeoJSON (2019-2025) |
| **Canada Earthquakes** | `canada/` | 12 MB | CSV + GDB earthquake catalog |
| **Canada Census** | `statcan/census_2021/` | 25 GB | 2021 Census Profile (all geo levels) |
| **Australia Cyclones** | `australia/` | 7.6 MB | 31,225 cyclone tracks (1909-present) |
| **Australia Population** | `abs/` | 127 MB | LGA + SA2 population 2001-2024 (GeoPackage) |
| **NOAA Climate** | `noaa/climate_at_a_glance/` | 65 MB | Temperature/precip 1895-2025 |
| **HDX/EM-DAT** | `hdx/` | 390 KB | Global disaster profiles (27K+ events) |
| **ReliefWeb** | `reliefweb/` | 6.9 MB | Global disasters 1981-present (18K+ events) |
| **EPA AQS** | `epa_aqs/` | 2.8 MB | Annual AQI by county 1980-2025 |
| **EIA Energy** | `eia/` | 1.4 GB | US energy data (7 bulk datasets) |
| **Eurostat** | `eurostat/` | 5.9 MB | NUTS 3 population + GDP |

### Download Scripts Available
Location: `county-map/data_converters/`

| Script | Source | Status |
|--------|--------|--------|
| download_fema_all.py | FEMA NRI + Disasters | Working |
| download_and_extract_noaa.py | NOAA Storm Events | Working |
| download_usdm_drought.py | US Drought Monitor | Working |
| download_canada_fires.py | Canadian CNFDB | Working |
| download_canada_drought.py | Canadian Drought Monitor | Working |
| download_canada_earthquakes.py | Earthquakes Canada | Working |
| download_canada_disasters.py | Canadian CDD | Needs interactive |
| download_australia_cyclones.py | Australia BOM | Working |
| download_noaa_climate.py | Climate at a Glance | Working |
| download_hdx_disasters.py | HDX/EM-DAT | Working |
| download_desinventar.py | 82+ countries | Server dead |
| download_fema_nfhl.py | Flood zones | FEMA servers down |
| download_reliefweb.py | ReliefWeb/HDX | Working (uses HDX mirror) |
| download_epa_aqs.py | EPA Air Quality | Working |
| download_eia_bulk.py | EIA Energy Data | Working |
| download_eurostat.py | Eurostat NUTS 3 | Working (partial) |
| download_statcan.py | Statistics Canada | Manual download required |
| download_abs.py | Australian ABS | Manual download required |

### Blocked Sources (Infrastructure Issues)
| Source | Issue | Workaround |
|--------|-------|------------|
| FEMA NFHL Flood Zones | hazards.fema.gov DOWN | State GIS portals (MassGIS has data) |
| DesInventar (82 countries) | Server dead (times out) | None - service appears defunct |
| Canadian Disaster Database | Interactive search only | Manual export |
| Statistics Canada | API URLs return 404 | Manual download from portal (done) |
| ABS Australia | API URLs return 404 | Manual download from portal (done) |

### Total Raw Data Size: ~29 GB

**Breakdown:**
- US Sources: ~1.5 GB (FEMA, EPA, EIA, NOAA)
- Canada: ~26 GB (Census 25GB, Fire 789MB, Drought 1GB, Earthquakes 12MB)
- Australia: ~135 MB (Population 127MB, Cyclones 7.6MB)
- Europe: ~6 MB (Eurostat NUTS 3)
- Global: ~7 MB (ReliefWeb, HDX/EM-DAT)

---

## Priority 1: FEMA Data Sources

### FEMA National Risk Index (NRI) - COMPLETE (Time-Series)

**This is the goldmine.** County-level risk data for 18 natural hazards, pre-calculated. Now with 4 historical versions merged into time-series format.

**Status**: All 4 versions downloaded and converted (2026-01-05). Main FEMA sites down but ArcGIS REST API accessible.

- **ArcGIS REST API** (WORKING): `https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/`
- **Main Download Page**: https://hazards.fema.gov/nri/data-resources (DOWN)
- **OpenFEMA Data**: https://www.fema.gov/about/openfema/data-sets/national-risk-index-data (DOWN)
- **Coverage**: All 50 states + territories, 3,232 counties
- **Format**: Parquet (converted from ArcGIS JSON)
- **Cost**: Free
- **Downloader Script**: `data_converters/download_fema_all.py` (comprehensive FEMA downloader)
- **Converter Script**: `data_converters/convert_fema_nri_timeseries.py`

**Output Files:**
| File | Size | Records | Columns | Description |
|------|------|---------|---------|-------------|
| `USA.parquet` | 5.71 MB | 12,747 | 117 | Time-series (all 4 versions for trend analysis) |
| `USA_full.parquet` | 8.47 MB | 3,232 | 469 | Latest version with ALL 467+ fields |

**Historical Versions Downloaded:**
| Version | Service | Counties | Fields | Release |
|---------|---------|----------|--------|---------|
| v1.17 | NRI_Counties_v117 | 3,142 | 350 | 2021 |
| v1.18.1 | NRI_Counties_Prod_v1181_view | 3,142 | 365 | Nov 2021 |
| v1.19.0 | National_Risk_Index_Counties_(March_2023) | 3,231 | 465 | Mar 2023 |
| v1.20.0 | National_Risk_Index_Counties | 3,232 | 465 | Dec 2025 |

**Key Discovery - Methodology Change:**
Risk score methodology changed significantly between v1.18.1 and v1.19.0:
- Average RISK_SCORE v1.17/v1.18.1: ~11 (3,142 counties)
- Average RISK_SCORE v1.19.0/v1.20.0: ~50 (3,231-3,232 counties)
- New counties added in 2023+ versions (Connecticut planning regions replaced legacy counties)

**18 Hazards Covered:**
1. Avalanche
2. Coastal Flooding
3. Cold Wave
4. Drought
5. Earthquake
6. Hail
7. Heat Wave
8. Hurricane
9. Ice Storm
10. Inland Flooding
11. Landslide
12. Lightning
13. Strong Wind
14. Tornado
15. Tsunami
16. Volcanic Activity
17. Wildfire
18. Winter Weather

**Key Metrics Per County:**
- Risk Index (composite score)
- Expected Annual Loss ($)
- Social Vulnerability
- Community Resilience
- Per-hazard risk scores

**Why This Is Perfect:**
- Pre-calculated risk scores we can use directly
- Matches our county-level loc_id system
- Free, official government data
- Already combines multiple hazard types
- FIPS codes for easy joining

### FEMA National Flood Hazard Layer (NFHL)

**Detailed flood zone mapping** for property-level flood risk assessment.

- **Main Page**: https://www.fema.gov/flood-maps/national-flood-hazard-layer (UP - info only)
- **Map Service Center**: https://msc.fema.gov (DOWN)
- **NFHL Database Search**: https://hazards.fema.gov/femaportal/NFHL/searchResult/ (DOWN)
- **Web Services**: https://hazards.fema.gov/femaportal/wps/portal/NFHLWMS (DOWN)
- **Coverage**: 90%+ of US population
- **Format**: Shapefiles, KMZ, GeoJSON (by county or state)
- **Cost**: Free

**What It Provides:**
- Flood zone boundaries (A, AE, V, VE, X zones)
- 100-year and 500-year floodplains
- Special Flood Hazard Areas (SFHA)
- Base Flood Elevations (BFE)
- Floodway status
- NFIP community information

**Use Case**: Detailed flood risk beyond the NRI composite score, property-specific assessments

### FEMA Disaster Declarations - COMPLETE (Time-Series)

**Historical federal disaster declarations since 1953.** Every presidential disaster declaration with county-level granularity.

**Status**: Downloaded 68,542 records (1953-2025) via OpenFEMA API (2026-01-05).

- **OpenFEMA API**: `https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries`
- **Data Page**: https://www.fema.gov/openfema-data-page/disaster-declarations-summaries-v2
- **Coverage**: All US counties, 1953-present
- **Format**: Parquet (converted from OpenFEMA JSON)
- **Cost**: Free
- **Update Frequency**: Continuous (new declarations added as issued)
- **Downloader Script**: `data_converters/download_fema_all.py`
- **Converter Script**: `data_converters/convert_fema_disasters.py`

**Output Files:**
| File | Size | Records | Columns | Description |
|------|------|---------|---------|-------------|
| `USA.parquet` | 0.24 MB | 46,901 | 19 | County-year aggregates (for mapping) |
| `USA_declarations.parquet` | 0.76 MB | 68,542 | 25 | Full declaration records |

**Key Statistics:**
- **72 years** of disaster data (1953-2025)
- **3,238 unique counties** with declarations
- **5,134 unique disasters** declared
- **66,990 county-specific** declarations + **1,552 statewide**

**Declarations by Decade:**
| Decade | Unique Disasters |
|--------|------------------|
| 1950s | 94 |
| 1960s | 184 |
| 1970s | 443 |
| 1980s | 286 |
| 1990s | 737 |
| 2000s | 1,265 |
| 2010s | 1,185 |
| 2020s | 940 |

**Top Incident Types (All Time):**
- Severe Storm: 19,299 declarations
- Hurricane: 13,721 declarations
- Flood: 11,227 declarations
- Biological: 7,857 declarations (COVID-19, etc.)
- Fire: 3,844 declarations
- Snowstorm: 3,707 declarations

**Most Disaster-Prone Counties (All Time):**
1. Los Angeles County, CA (USA-CA-06037): 88 declarations
2. Riverside County, CA (USA-CA-06065): 65 declarations
3. San Bernardino County, CA (USA-CA-06071): 61 declarations
4. Ascension Parish, LA (USA-LA-22005): 57 declarations
5. Collier County, FL (USA-FL-12021): 54 declarations

**Use Case**: Time-series visualization of disaster frequency by county, historical trend analysis, correlation with NRI risk scores.

---

## Priority 2: NOAA Data Sources

### NOAA Storm Events Database (COMPLETE ✓)

Historical storm event data with bulk CSV downloads.

**Status**: Downloaded all 76 years (1950-2025), converted to parquet, reference files built.

- **Bulk Download Page**: https://www.ncei.noaa.gov/stormevents/ftp.jsp
- **Direct CSV Directory**: https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/
- **Format Documentation**: https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/Storm-Data-Bulk-csv-Format.pdf
- **Coverage**: 1950-2025, all US counties
- **Format**: CSV (gzip compressed)
- **Cost**: Free
- **Downloader Script**: `data_converters/download_and_extract_noaa.py` ✓
- **Converter Script**: `data_converters/convert_noaa_storms.py` ✓
- **Reference Builder**: `data_converters/build_storm_reference.py` ✓

**Three File Types:**
1. `StormEvents_details` - Comprehensive storm event info
2. `StormEvents_fatalities` - Fatality data
3. `StormEvents_locations` - Geographic coordinates

**File Naming:** `StormEvents_[type]-ftp_v1.0_d[YYYY]_c[YYYYMMDD].csv.gz`
- `d[YYYY]` = data year
- `c[YYYYMMDD]` = compilation date

**Current Dataset:**
- **159,651 county-year records** across 3,403 unique counties
- **683 named storms** cataloged (hurricanes, tropical storms)
- **392,874 total episodes** tracked
- **41 event type columns** including tornadoes, hail, floods, wildfires
- Files: USA.parquet (1 MB), reference.json (132 MB), named_storms.json (556 KB)

**Note:** Data arrives ~75 days after month end (e.g., January data available mid-April)

### U.S. Drought Monitor (COMPLETE)

County-level drought statistics aggregated from weekly data.

**Status**: Downloaded 26 years (2000-2026), aggregated weekly to annual statistics, parquet and metadata complete.

- **API Endpoint**: https://usdmdataservices.unl.edu/api/CountyStatistics
- **Data Download**: https://droughtmonitor.unl.edu/DmData/DataDownload.aspx
- **Drought.gov Portal**: https://www.drought.gov/data-download
- **Coverage**: All U.S. counties, 2000-present (weekly updates)
- **Format**: CSV via API
- **Cost**: Free
- **Update Frequency**: Weekly (published every Thursday)
- **Downloader Script**: `data_converters/download_usdm_drought.py`
- **Converter Script**: `data_converters/convert_usdm_drought.py`

**Current Dataset:**
- **90,188 county-year records** across 3,221 unique counties
- **26 years** of historical data (2000-2026)
- **Annual aggregation** from weekly measurements (52x compression)
- Files: USA.parquet (0.67 MB), metadata.json (complete)

**Drought Categories:**
- D0: Abnormally Dry (going into or coming out of drought)
- D1: Moderate Drought
- D2: Severe Drought
- D3: Extreme Drought
- D4: Exceptional Drought

**Metrics per county-year:**
- Max/average drought severity (0-5 scale)
- Weeks in each drought category (D0-D4)
- Percent of year in drought / severe drought
- Most drought-prone: Arizona and Utah counties (90%+ of time in drought)
- Worst year: 2012 (avg severity 1.41 across all counties)

**Note:** Raw weekly CSVs preserved for future detailed analysis. Annual parquet optimized for map time slider.

### Climate at a Glance (VERIFIED)

County-level climate data from 1895 to present.

- **Main Page**: https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/county/time-series
- **Coverage**: All U.S. counties, 1895-present
- **Format**: CSV, JSON (web interface download)
- **Cost**: Free
- **Update Frequency**: Monthly
- **Contact**: ncei.info@noaa.gov / (828) 271-4800

**Available Parameters:**
- Average Temperature
- Maximum Temperature
- Minimum Temperature
- Precipitation
- Cooling Degree Days
- Heating Degree Days
- Palmer Drought Severity Index (PDSI)
- Palmer Hydrological Drought Index (PHDI)
- Palmer Modified Drought Index (PMDI)
- Palmer Z-Index

**Data Source**: Based on nClimGrid dataset (GHCN daily weather stations)

**Use Case**: Long-term climate trends, temperature extremes, precipitation patterns, drought indices

**Note**: Web interface allows custom date ranges and base period selection. For bulk downloads, may need to contact NCEI or build automated scraper.

### nClimGrid Daily (VERIFIED - Grid Data)

Daily gridded climate data that can be aggregated to county level.

- **FTP Directory**: https://www.ncei.noaa.gov/pub/data/daily-grids/v1-0-0/
- **Documentation**: https://www.ncei.noaa.gov/products/land-based-station/nclimgrid-daily
- **Coverage**: Contiguous US, 1951-present
- **Format**: NetCDF gridded files (5km resolution)
- **Cost**: Free
- **Update Frequency**: Daily

**Available Parameters:**
- Daily Maximum Temperature (tmax)
- Daily Minimum Temperature (tmin)
- Daily Precipitation (prcp)

**Grid Resolution**: ~5km x 5km cells

**Use Case**: Can aggregate grid cells to county boundaries to get county-level daily climate data. More granular than Climate at a Glance, allows custom aggregation methods.

**Note**: Requires GIS processing to aggregate grid cells to county polygons. Raw gridded data, not pre-aggregated by county.

---

## Priority 2: Wildfire Risk to Communities (COMPLETE)

US Forest Service wildfire risk data with county-level risk assessments.

**Status**: Downloaded Version 2 (May 2025), converted to parquet, metadata complete.

- **Main Site**: https://wildfirerisk.org/
- **Download Page**: https://wildfirerisk.org/download/
- **Direct Download**: https://wildfirerisk.org/wp-content/uploads/2025/05/wrc_download_202505.xlsx
- **Coverage**: All US counties (3,144 counties)
- **Format**: Excel spreadsheet (XLSX)
- **Cost**: Free (Public Domain)
- **Update Frequency**: Periodic (Version 2 released May 2025)
- **Converter Script**: `data_converters/convert_wildfire_risk.py`

**Current Dataset:**
- **3,144 counties** with wildfire risk assessments
- **332 million population** analyzed
- **146 million buildings** assessed for exposure
- Files: USA.parquet (112 KB), metadata.json (complete)

**Key Metrics:**
- **Building Exposure Zones**: Minimal (20.4%), Indirect (19.8%), Direct (59.8%)
- **Burn Probability Rankings**: State and national percentile ranks
- **Risk to Potential Structures**: Composite risk measure combining burn probability and building density

**Highest Risk Areas:**
- Burn Probability: Washington, California, Nevada, Texas, Idaho, Oregon counties
- Direct Exposure: Kentucky, Virginia, North Carolina counties (97-99% of buildings in direct wildfire zone)
- 156 counties at very high risk (>95th percentile nationally)

**Version History:**
- **Version 1 (2020)**: Based on LANDFIRE 2014 data, represents landscape conditions as of end of 2014. Published in 2020. Tabular spreadsheet no longer publicly available (only GIS raster files in Research Data Archive).
- **Version 2 (2024/2025)**: Based on LANDFIRE 2020 data updated through 2022, represents landscape conditions as of end of 2022. Published May 2025. **This is what we downloaded.**

**Historical Data Availability:**
- Version 1 tabular county summaries are not archived for download
- Only Version 2 (current) spreadsheet is available at wildfirerisk.org
- Version 1 GIS spatial files available at: https://doi.org/10.2737/RDS-2020-0016
- 8-year gap between versions (2014 → 2022 landscape conditions)
- Future versions expected but update schedule unclear

**Note:** This is periodic snapshot data (not annual time-series). Risk assessments change over time as forests change, development expands into wildland areas, and climate patterns shift. If future versions are released, could build time-series with sparse updates (e.g., 2014, 2022, 2030). Good candidate for cross-border "sibling layer" in loc_id system (wildfire zones span multiple counties/states).

---

## Priority 3: USGS Earthquake API (VERIFIED)

Real-time and historical earthquake data via REST API.

- **API Documentation**: https://earthquake.usgs.gov/fdsnws/event/1/
- **Web Services**: https://earthquake.usgs.gov/ws/
- **Data & Tools**: https://www.usgs.gov/programs/earthquake-hazards/data
- **GeoJSON Feeds**: https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php
- **Format**: GeoJSON, XML, QuakeML
- **Cost**: Free

**Example API Calls:**
```
# Earthquakes in date range
https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=2024-01-01&endtime=2024-12-31

# Magnitude 5+ only
https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=2024-01-01&endtime=2024-12-31&minmagnitude=5
```

**Note:** API returns events, not pre-calculated county risk. May need to aggregate by location.

---

## Priority 4: Additional USFS Data (VERIFIED)

- **FSGeodata Clearinghouse**: https://data.fs.usda.gov/geodata/edw/datasets.php?xmlKeyword=wildfire
- **Wildfire Hazard Potential**: https://research.fs.usda.gov/firelab/products/dataandtools/wildfire-hazard-potential
- **Format**: Shapefile, ESRI File Geodatabase

---

## Canadian Data Sources

### Canadian National Fire Database (CNFDB) - COMPLETE

**Status**: Downloaded 2026-01-05. 788 MB of fire data.

- **Main Portal**: https://cwfis.cfs.nrcan.gc.ca/ha/nfdb
- **Datamart**: https://cwfis.cfs.nrcan.gc.ca/datamart
- **Coverage**: All Canadian provinces and territories, historical fire records
- **Format**: Shapefile (points and polygons), text files
- **Cost**: Free (Open Government License - Canada)
- **Downloader Script**: `data_converters/download_canada_fires.py`

**Downloaded Files:**
| File | Size | Description |
|------|------|-------------|
| NFDB_point.zip | 29 MB | All fire point locations |
| NFDB_poly.zip | 742 MB | Fire perimeter polygons (>= 200 ha) |
| NFDB_point_large_fires.zip | 2 MB | Large fires only |
| NFDB_point_txt.zip | 13 MB | Text format data |
| NFDB_point_stats.zip | 1 MB | Summary statistics |

**Key Fields**: Fire location (lat/lon), date, cause, size (hectares), agency

### Canadian Drought Monitor - COMPLETE

**Status**: Downloaded 2026-01-05.

- **Main Portal**: https://agriculture.canada.ca/en/agricultural-production/weather/canadian-drought-monitor
- **Data URL**: https://agriculture.canada.ca/atlas/data_donnees/canadianDroughtMonitor/
- **Coverage**: Canada-wide, 2019-present (monthly)
- **Format**: GeoJSON polygons by severity level
- **Cost**: Free (Open Government License - Canada)
- **Downloader Script**: `data_converters/download_canada_drought.py`

**Drought Severity Levels** (same as US Drought Monitor):
- D0: Abnormally Dry
- D1: Moderate Drought
- D2: Severe Drought
- D3: Extreme Drought
- D4: Exceptional Drought

**File Pattern**: `CDM_{YYMM}_D{0-4}_LR.geojson` per month/severity

### Canadian Disaster Database (CDD) - PENDING

**Status**: Requires interactive search, no bulk download API.

- **Main Portal**: https://cdd.publicsafety.gc.ca/
- **Open Data Portal**: https://open.canada.ca/data/en/dataset/1c3d15f9-9cfa-4010-8462-0d67e493d9b9
- **Coverage**: 1000+ disasters since 1900
- **Format**: CSV (via search), KML, GeoRSS
- **Disaster Types**: Floods, storms, wildfires, earthquakes, industrial accidents

**Note**: The geospatial view is temporarily out of service. Standard search still works but requires manual export.

### Earthquakes Canada - COMPLETE

**Status**: Downloaded 2026-01-05. 8 MB earthquake catalog.

- **Database Search**: https://www.earthquakescanada.nrcan.gc.ca/stndon/NEDB-BNDS/bulletin-en.php
- **Open Data Portal**: https://open.canada.ca/data/en/dataset/4cedd37e-0023-41fe-8eff-bea45385e469
- **Direct CSV**: https://ftp.maps.canada.ca/pub/nrcan_rncan/Earthquakes_Tremblement-de-terre/canadian-earthquakes_tremblements-de-terre-canadien/eqarchive-en.csv
- **Coverage**: Canadian earthquakes since 1985 (some records back to 1600s)
- **Format**: CSV, GDB (geodatabase)
- **Cost**: Free (Open Government License - Canada)
- **Downloader Script**: `data_converters/download_canada_earthquakes.py`

**Downloaded Files:**
| File | Size | Description |
|------|------|-------------|
| eqarchive-en.csv | 8 MB | Full earthquake catalog |
| earthquakes_en.gdb.zip | 3.7 MB | Geodatabase format |

**Key Fields**: Date/Time, Latitude, Longitude, Depth, Magnitude, Location

### Canadian Flood Extent Polygons - NOT YET EXPLORED

- **Portal**: https://geo.ca/emergency/
- **Coverage**: Historical flood extents from satellite imagery
- **Source**: Natural Resources Canada

---

## Australian Data Sources

### Australian Tropical Cyclone Database - COMPLETE

**Status**: Downloaded 2026-01-05. 7.6 MB, 31,225 records (1909-present).

- **Portal**: https://www.bom.gov.au/cyclone/tropical-cyclone-knowledge-centre/databases/
- **Direct CSV**: http://www.bom.gov.au/clim_data/IDCKMSTM0S.csv
- **Coverage**: Australian region (90E-160E, 0-40S), 1909-present
- **Format**: CSV
- **Cost**: Free (Creative Commons BY 4.0)
- **Downloader Script**: `data_converters/download_australia_cyclones.py`

**Downloaded Files:**
| File | Size | Records | Description |
|------|------|---------|-------------|
| IDCKMSTM0S.csv | 7.6 MB | 31,225 | Best track database |

**Key Fields**: Cyclone ID, Name, Date/Time, Lat/Lon, Central Pressure, Max Wind Speed, Category

**Note**: OTCR reanalysis database (1981-2016) with improved intensity estimates not publicly available in CSV form.

---

## Global Disaster Databases

### NOAA Climate at a Glance - COMPLETE

**Status**: Downloaded 2026-01-05. 65 MB total.

- **Portal**: https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/
- **Coverage**: US National + 43 states, 1895-2025
- **Format**: CSV time series
- **Cost**: Free (Public Domain)
- **Downloader Script**: `data_converters/download_noaa_climate.py`

**Downloaded Files:**
- National level: 9/9 parameters (all successful)
- State level: 193/255 files

**Parameters Downloaded:**
- tavg: Average Temperature
- tmax: Maximum Temperature
- tmin: Minimum Temperature
- pcp: Precipitation
- pdsi: Palmer Drought Severity Index
- phdi: Palmer Hydrological Drought Index
- zndx: Palmer Z-Index
- cdd: Cooling Degree Days
- hdd: Heating Degree Days

### HDX/EM-DAT Global Disaster Profiles - COMPLETE

**Status**: Downloaded 2026-01-05. 390 KB.

- **Portal**: https://data.humdata.org/
- **Dataset**: https://data.humdata.org/dataset/emdat-country-profiles
- **Coverage**: Global (all countries), 1900-present
- **Format**: XLSX
- **Cost**: Free
- **Downloader Script**: `data_converters/download_hdx_disasters.py`

**Downloaded Files:**
| File | Size | Description |
|------|------|-------------|
| EMDAT-country-profiles_2026_01_06.xlsx | 390 KB | Aggregated disaster stats by country/year/type |

**Content**: 27,000+ disasters since 1900, aggregated by year, country, disaster subtype. Includes deaths, affected population, economic losses.

### DesInventar Global Disaster Database - IN PROGRESS

**Status**: Downloading 2026-01-05. 82+ countries available.

- **Portal**: https://www.desinventar.net/
- **Download**: https://www.desinventar.net/DesInventar/download.jsp
- **Coverage**: 82+ countries (Latin America, Africa, Asia, Europe, Pacific)
- **Format**: XML per country
- **Cost**: Free (Apache 2.0-like license)
- **Downloader Script**: `data_converters/download_desinventar.py`

**Countries Available Include:**
- **Latin America**: Argentina, Bolivia, Chile, Colombia, Ecuador, Guatemala, Mexico, Peru, Venezuela
- **Africa**: Algeria, Angola, Ethiopia, Ghana, Kenya, Madagascar, Morocco, Nigeria, Tanzania
- **Asia**: Afghanistan, India, Indonesia, Iran, Nepal, Pakistan, Philippines, Sri Lanka, Vietnam
- **Europe**: Albania, Serbia, Spain, Turkey

**Key Fields**: Event ID, Date, Location (admin levels), Event Type, Deaths, Injured, Affected, Houses Destroyed, Economic Losses

### ReliefWeb API - AVAILABLE

- **API Docs**: https://reliefweb.int/help/api
- **Disasters Endpoint**: https://api.reliefweb.int/v1/disasters
- **Coverage**: Global disasters since 1981
- **Format**: JSON API
- **Note**: API requires appname parameter, returns disaster metadata with GLIDE numbers

---

## Other Data Sources

### HazardAware (Regional)

- **URL**: https://www.hazardaware.org/
- **Coverage**: Gulf Coast region primarily
- **Focus**: 30 years historical weather, drought, fire, flood
- **Limitation**: Regional focus (Gulf states), but interesting methodology

### Historical Weather/Disasters

| Source | URL | Coverage |
|--------|-----|----------|
| SHELDUS Database | (academic access) | US counties, hazard losses |
| NOAA NCEI | https://www.ncei.noaa.gov/ | Global climate data |

### Sea Level Rise / Coastal

| Source | URL | Coverage |
|--------|-----|----------|
| NOAA Sea Level Rise Viewer | https://coast.noaa.gov/slr/ | US coasts |
| NOAA Digital Coast | https://coast.noaa.gov/digitalcoast/data/ | Coastal data |

### Air Quality / Health

| Source | URL | Coverage |
|--------|-----|----------|
| EPA AirNow | https://www.airnow.gov/ | US real-time |
| CDC PLACES | https://www.cdc.gov/places/ | US counties |

### Infrastructure / Utilities

| Source | URL | Coverage |
|--------|-----|----------|
| EIA | https://www.eia.gov/opendata/ | US energy data |
| SAIDI/SAIFI (already have) | - | US states |

---

## Cross-Border Entities (Sibling Layer Candidates)

Some hazard zones span multiple counties/states - good candidates for the loc_id sibling layer system.

| Zone Type | Description | Data Source |
|-----------|-------------|-------------|
| **Tornado Alley** | Central US tornado corridor | NOAA Storm Events |
| **Dixie Alley** | Southeast tornado zone | NOAA Storm Events |
| **Wildfire Zones** | Western fire-prone regions | USFS Wildfire Risk |
| **Hurricane Corridors** | Gulf/Atlantic coast paths | FEMA NRI, NOAA |
| **Earthquake Fault Zones** | San Andreas, New Madrid, etc. | USGS |
| **Flood Basins** | Mississippi, Missouri river systems | FEMA NFHL |
| **Drought Regions** | Southwest, Great Plains | NOAA |

**Implementation Idea:**
- Create sibling layers for these cross-border zones
- Counties within a zone share the zone's loc_id as a parent/sibling
- Allows queries like "show all Tornado Alley counties" or "wildfire zone risk trends"

---

## Data Integration Priority

For Sheltrium risk scores, priority order:

1. **FEMA NRI** - Immediate. Download and convert. Pre-calculated composite scores.
2. **SAIDI/SAIFI** - Already have. Power reliability.
3. **NOAA Climate** - Next. Adds depth to weather risks.
4. **NFHL Flood Zones** - Property-specific flood risk.
5. **USGS Earthquake** - Regional seismic risk.
6. **Wildfire Risk** - Western states especially.

---

## Converter Needed

For FEMA NRI data, need to build:

```
data_converters/convert_fema_nri.py
```

Output format matching existing pattern:
- loc_id (county FIPS -> USA-{state}-{fips})
- Year (or "latest")
- risk_index, expected_annual_loss, social_vulnerability, community_resilience
- Per-hazard scores (earthquake_risk, flood_risk, wildfire_risk, etc.)

---

## Questions Answered

1. How often is FEMA NRI updated? **Major releases every 1-2 years (v1.17 to v1.20 from 2021-2025)**
2. Can we get historical NRI data for trend analysis? **YES! 4 versions available via ArcGIS: v1.17, v1.18.1, v1.19.0, v1.20.0**
3. How granular is NFHL data? (Parcel-level?) **TBD - FEMA infrastructure still down**
4. Are there APIs or just file downloads? **ArcGIS REST API works as workaround!**
5. License restrictions on redistribution? **Public Domain (U.S. Government)**

---

## Next Steps

### Completed
- [x] Download FEMA NRI county-level data via ArcGIS
- [x] Build converter following existing pattern
- [x] Generate metadata.json
- [x] Add to index.json
- [x] Download ALL 4 historical NRI versions (v1.17, v1.18.1, v1.19.0, v1.20.0) for trend analysis
- [x] Create NRI time-series converter (merge 4 versions into single parquet)
- [x] Download all 467 fields (not just 188) from latest NRI version
- [x] Download FEMA disaster declarations (68K records, 1953-2025)
- [x] Create disaster declarations converter with county-year aggregates
- [x] Add NOAA Climate at a Glance data (65 MB, 9 national + 193 state files)
- [x] Download Canadian fire, earthquake, drought data (1.8 GB total)
- [x] Download Australia tropical cyclones (31K records, 1909-present)
- [x] Download HDX/EM-DAT global profiles (27K+ disasters)
- [x] Download ReliefWeb disasters via HDX mirror (18K+ events)
- [x] Download EPA AQS annual AQI data (1980-2025, 46 years)
- [x] Download EIA bulk energy data (7 datasets, 1.4 GB)
- [x] Download Eurostat NUTS 3 data (population, GDP)
- [x] Download Statistics Canada Census 2021 (5,161 CSDs, 25 GB)
- [x] Download Australia ABS population (547 LGAs, 127 MB)

### In Progress
- [ ] Create converters for new international data (Canada, Australia, Europe)
- [ ] Import international geometry (LGA, CSD, NUTS boundaries)

### Blocked
- [ ] Wait for FEMA infrastructure recovery for NFHL flood zones
- [ ] DesInventar - server appears defunct (times out on downloads)

### Future
- [ ] Consider NRI Census Tracts download (85K+ records, finer granularity)
- [ ] CDC PLACES county health data
- [ ] NOAA Sea Level Rise projections

---

## NEW SOURCES TO EXPLORE (January 2026)

### ReliefWeb API - Global Disasters (1981-present) - TO DOWNLOAD

Global disaster data from OCHA/UN covering humanitarian emergencies since 1981.

- **API Documentation**: https://apidoc.reliefweb.int/
- **Disasters Endpoint**: `https://api.reliefweb.int/v1/disasters?appname=YOUR_APP&preset=analysis&limit=1000`
- **HDX Mirror**: https://data.humdata.org/dataset/reliefweb-disasters-list
- **Coverage**: Global, 1981-present
- **Format**: JSON API (paginated, max 1000 per request)
- **Cost**: Free (requires appname parameter, registration recommended from Nov 2025)
- **GLIDE Numbers**: Includes standardized disaster identifiers

**Key Features:**
- All major disasters with humanitarian impact since 1981
- Includes GLIDE numbers for cross-referencing with EM-DAT
- Situation reports, assessments, maps linked per disaster
- `preset=analysis` includes archived disasters for historical analysis
- Countries, disaster types, dates, affected areas

**API Notes:**
- Valid limit: 0-1000 per request
- Must use `appname` parameter (can be any identifier)
- Returns JSON with `count` property for total records

---

### EPA Air Quality System (AQS) - County AQI (1980-present) - TO DOWNLOAD

Historical air quality data with annual county-level AQI summaries.

- **Pre-Generated Files**: https://aqs.epa.gov/aqsweb/airdata/download_files.html
- **AQS API**: https://aqs.epa.gov/aqsweb/documents/data_api.html
- **Main Portal**: https://www.epa.gov/outdoor-air-quality-data
- **Coverage**: All US counties with monitors, 1980-2025
- **Format**: CSV (zipped)
- **Cost**: Free
- **Update Frequency**: Twice annually (June for full year, December for summer ozone)

**Pre-Generated Files Available:**

| File Type | Years | Description |
|-----------|-------|-------------|
| `annual_aqi_by_county_[YEAR].zip` | 1980-2025 | Annual AQI summary by county |
| `annual_aqi_by_cbsa_[YEAR].zip` | 1980-2025 | Annual AQI by metro area |
| `daily_aqi_by_county_[YEAR].zip` | 1980-2025 | Daily AQI values |
| `annual_conc_by_monitor_[YEAR].zip` | 1980-2025 | Pollutant concentrations |

**Pollutants Covered:**
- Ozone (O3)
- Particulate Matter (PM2.5, PM10)
- Carbon Monoxide (CO)
- Sulfur Dioxide (SO2)
- Nitrogen Dioxide (NO2)
- Lead (Pb)

**Download URL Pattern:**
```
https://aqs.epa.gov/aqsweb/airdata/annual_aqi_by_county_[YEAR].zip
```

**API Rate Limits:**
- Max 1,000,000 rows per query
- Max 10 requests per minute
- 5 second pause between requests

**Use Case**: New visualization layer - air quality trends, pollution hotspots, health correlations

---

### EIA Energy Data - State Level (1960s-present) - TO DOWNLOAD

Comprehensive US energy statistics from the Energy Information Administration.

- **Open Data Portal**: https://www.eia.gov/opendata/
- **Bulk Download**: https://www.eia.gov/opendata/v1/bulkfiles.php
- **API Documentation**: https://www.eia.gov/opendata/documentation.php
- **Coverage**: National + State level, 1960s-present (varies by dataset)
- **Format**: JSON (API), ZIP (bulk downloads contain JSON text files)
- **Cost**: Free (API key recommended but bulk download is key-free)
- **Update Frequency**: Twice daily (5am and 3pm ET)

**Bulk Download Files:**

| File | Description | Series Count |
|------|-------------|--------------|
| SEDS.zip | State Energy Data System | 30,000+ |
| ELEC.zip | Electricity | 408,000+ |
| NG.zip | Natural Gas | 11,989+ |
| PET.zip | Petroleum | 115,052+ |
| COAL.zip | Coal (includes county-level mine data) | varies |
| TOTAL.zip | Total Energy | varies |
| EMISS.zip | CO2 Emissions | varies |
| EBA.zip | Electric System Operating Data (hourly) | varies |
| STEO.zip | Short-Term Energy Outlook | varies |
| INTL.zip | International Energy Data | varies |

**Geographic Levels:**
- **National**: All datasets
- **State**: SEDS, Electricity, Natural Gas, Petroleum
- **County**: Coal mine-level data only
- **Plant-level**: Electricity generation

**Key Metrics:**
- Electricity generation by source (coal, gas, nuclear, renewables)
- Natural gas production, prices, storage
- Petroleum production, refining, imports/exports
- Energy consumption by sector (residential, commercial, industrial, transport)
- CO2 emissions by state and sector

**Time Coverage by Dataset:**
- SEDS: 1960-present (annual)
- Electricity: 2001-present (monthly, some hourly)
- Natural Gas: 1973-present (monthly)
- Petroleum: 1981-present (weekly/monthly)

**Use Case**: Energy infrastructure resilience, grid reliability correlation, emissions mapping

---

### Eurostat Regional Statistics - NUTS 3 (1990-present) - TO DOWNLOAD

European regional statistics at NUTS 3 level (small regions, ~1,165 units in EU).

- **Regional Database**: https://ec.europa.eu/eurostat/web/regions/database
- **Statistics API**: https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/
- **GISCO Geodata**: https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/territorial-units-statistics
- **Bulk Download**: https://ec.europa.eu/eurostat/estat-navtree-portlet-prod/BulkDownloadListing
- **Coverage**: EU 27 + candidate countries, NUTS 0-3 levels
- **Format**: TSV (tab-separated), SDMX-ML (XML), JSON-stat
- **Cost**: Free (Open Data)

**NUTS Levels:**
- NUTS 0: Countries (27 EU members)
- NUTS 1: Major socio-economic regions (92 units)
- NUTS 2: Basic regions for regional policy (244 units)
- NUTS 3: Small regions for specific diagnoses (1,165 units)

**Key Datasets:**

| Dataset Code | Description | Time Range |
|--------------|-------------|------------|
| demo_r_gind3 | Population change at NUTS 3 | 1990-present |
| demo_r_d3avg | Average population by NUTS 3 | 1990-present |
| nama_10r_3gdp | GDP at NUTS 3 level | 2000-present |
| nama_10r_3popgdp | GDP per capita at NUTS 3 | 2000-present |
| lfst_r_lfu3rt | Unemployment rate NUTS 3 | 1999-present |

**Population Data (NUTS 3):**
- Total population by sex and broad age groups (0-14, 15-64, 65+)
- Time series from 1990 (voluntary reporting pre-2013)
- Birth rates, death rates, migration

**Economic Data (NUTS 3):**
- GDP and GDP per capita
- Employment by sector
- Compensation of employees

**API Filtering:**
```
geoLevel=nuts3  # Filter to NUTS 3 regions only
```

**Use Case**: European expansion - population, economic, demographic layers

---

### Statistics Canada Census - Subdivision Level (1981-2021) - TO DOWNLOAD

Canadian census population data at census subdivision (municipality) level.

- **Census Portal**: https://www12.statcan.gc.ca/census-recensement/index-eng.cfm
- **Multi-Census Datasets**: https://www12.statcan.gc.ca/datasets/index-eng.cfm
- **Census Profile Downloads**: https://www150.statcan.gc.ca/n1/en/catalogue/98-401-X
- **Web Data Service API**: https://www.statcan.gc.ca/en/developers
- **Coverage**: All census subdivisions, 1981-2021 (census years)
- **Format**: CSV, PRN (tab-separated), IVT (Beyond 20/20)
- **Cost**: Free (Open Government License - Canada)

**Census Years Available:**
- 2021 Census (latest)
- 2016 Census
- 2011 Census + National Household Survey
- 2006 Census
- 2001 Census
- 1996 Census
- 1991 Census (time series profiles back to 1981)

**Geographic Levels:**
- Census Divisions (CD) - ~293 units
- Census Subdivisions (CSD) - ~5,000+ municipalities
- Census Metropolitan Areas (CMA)
- Census Tracts (CT) - urban areas only

**Key Variables:**
- Population and dwelling counts
- Age and sex distribution
- Marital status
- Language (mother tongue, home language, official language)
- Immigration and citizenship
- Education attainment
- Labour force participation
- Income
- Housing characteristics

**Download Options:**
1. Census Profile Downloads (Catalogue 98-401-X) - comprehensive profiles by geography
2. Population and Dwelling Count tables - CSV downloads by census year
3. Web Data Service API - SDMX and JSON formats

**Time Series Profiles:**
- The 1991 Census Time Series Community profiles include comparable data from 1981, 1986, and 1991 censuses

**Use Case**: Canadian expansion - population trends, demographics at municipality level

---

### Australian Bureau of Statistics - LGA Population (2001-2024) - TO DOWNLOAD

Australian population estimates by Local Government Area.

- **Regional Population Portal**: https://www.abs.gov.au/statistics/people/population/regional-population/latest-release
- **Data API**: https://www.abs.gov.au/about/data-services/application-programming-interfaces-apis/data-api-user-guide
- **Population Statistics**: https://www.abs.gov.au/statistics/people/population
- **Coverage**: All LGAs, 2001-2024 (annual estimates)
- **Format**: Excel data cubes, CSV, JSON (API), XML (SDMX)
- **Cost**: Free (Creative Commons BY 4.0)
- **Update Frequency**: Annual (regional population) + Quarterly (national)

**Geographic Levels:**
- National
- States and Territories (8)
- Statistical Area Level 4 (SA4) - ~89 units
- Statistical Area Level 3 (SA3) - ~340 units
- Statistical Area Level 2 (SA2) - ~2,472 units
- Local Government Areas (LGA) - ~544 units

**Available Datasets:**

| Dataset ID | Description | Time Range |
|------------|-------------|------------|
| ABS_ANNUAL_ERP_LGA2024 | Annual population by LGA | 2001-2024 |
| ERP_QUARTERLY | Quarterly population estimates | varies |
| Regional components of change | Births, deaths, migration by region | varies |

**Key Metrics:**
- Estimated Resident Population (ERP)
- Population change (number and percent)
- Natural increase (births minus deaths)
- Net internal migration
- Net overseas migration
- Population density

**Census Data (1991):**
- Census-based LGA data from 1991 available through AURIN (data.aurin.org.au)
- Time Series Community Profiles cover 1981, 1986, 1991

**API Notes:**
- SDMX 2.1 compliant
- Authentication optional but recommended for production
- Large datasets recommended via Excel data cubes rather than API

**Use Case**: Australian expansion - population trends by LGA, demographic analysis

---

## loc_id Mapping for New Sources

All data must map to the loc_id system defined in GEOMETRY.md. The loc_id format is:

```
{ISO3}[-{admin1}[-{admin2}[-{admin3}...]]]
```

**Key Design Principle**: Each country can use their **own naming scheme** within this structure. The loc_id system is intentionally flexible - admin codes can use ISO 3166-2, national standard codes, or any consistent identifier. The only requirement is the ISO3 country prefix.

### Source Compatibility Summary

| Source | Geographic Level | Source ID | loc_id Format | Status |
|--------|-----------------|-----------|---------------|--------|
| **ReliefWeb** | Country | ISO alpha-3 | `{ISO3}` | Direct match |
| **EPA AQS** | US Counties | FIPS 5-digit | `USA-{state}-{FIPS}` | Direct match |
| **EIA Energy** | US States | State postal | `USA-{state}` | Direct match |
| **Eurostat** | NUTS 3 regions | NUTS code | `{ISO3}-{NUTS}` | Compatible |
| **Statistics Canada** | Census Subdivisions | DGUID | `CAN-{prov}-{CSD}` | Compatible |
| **ABS Australia** | LGAs | State+LGA code | `AUS-{state}-{LGA}` | Compatible |

### US Data (Direct Match)

US sources use FIPS codes which map directly to our existing loc_id format:

```python
# County level (FIPS to loc_id)
state_fips = "06"
county_fips = "037"
state_abbr = STATE_FIPS_TO_ABBR[state_fips]  # "CA"
loc_id = f"USA-{state_abbr}-{int(state_fips + county_fips)}"  # "USA-CA-6037"

# State level
loc_id = f"USA-{state_abbr}"  # "USA-CA"
```

### European Data (Eurostat NUTS)

NUTS (Nomenclature of Territorial Units for Statistics) is the EU's hierarchical system:

| NUTS Level | Description | Units | Example Code | loc_id |
|------------|-------------|-------|--------------|--------|
| NUTS 0 | Country | 27 | `DE` | `DEU` |
| NUTS 1 | Major regions | 92 | `DE3` | `DEU-DE3` |
| NUTS 2 | Basic regions | 244 | `DE30` | `DEU-DE30` |
| NUTS 3 | Small regions | 1,165 | `DE300` | `DEU-DE300` |

The NUTS code becomes the admin identifier directly. This is consistent with the loc_id spec which allows "ISO 3166-2 or national standard codes."

```python
# Eurostat NUTS to loc_id
nuts_code = "DE300"  # Berlin
iso3 = NUTS_COUNTRY_TO_ISO3[nuts_code[:2]]  # "DEU"
loc_id = f"{iso3}-{nuts_code}"  # "DEU-DE300"
```

**Downloaded Eurostat Files:**
- `demo_r_gind3.tsv` - Population change at NUTS 3 (3.5 MB, ~23,165 regions)
- `nama_10r_3gdp.tsv` - GDP at NUTS 3 level (2.4 MB, ~12,498 regions)

### Canadian Data (Statistics Canada)

Canada uses a hierarchical census geography system:

| Level | Description | Units | DGUID Pattern | loc_id |
|-------|-------------|-------|---------------|--------|
| Province | Provinces/Territories | 13 | `2021A000210` | `CAN-NL` |
| Census Division (CD) | Counties, districts | 293 | `2021A00031001` | `CAN-NL-1001` |
| Census Subdivision (CSD) | Municipalities | 5,161 | `2021A00051001105` | `CAN-NL-1001105` |
| Dissemination Area (DA) | Small areas | 57,936 | `2021S051210010732` | (optional) |

```python
# Canada DGUID to loc_id
dguid = "2021A00051001105"  # Portugal Cove South, NL
province_code = dguid[9:11]  # "10" -> NL
csd_code = dguid[11:]  # "01105"
prov_abbr = CANADA_PROV_TO_ABBR[province_code]  # "NL"
loc_id = f"CAN-{prov_abbr}-{csd_code}"  # "CAN-NL-1001105"
```

**Downloaded StatsCan Files:**
- 6 regional CSV files (Atlantic, BC, Ontario, Prairies, Quebec, Territories)
- 25 GB total extracted
- 5,161 Census Subdivisions + 57,936 Dissemination Areas

**Census Profile Download URLs (for future reference):**

Canada conducts a census every 5 years. Download pages for comprehensive CSV files:

| Census | Catalogue | Download Page | Notes |
|--------|-----------|---------------|-------|
| **2021** | 98-401-X2021006 | [Census Profile Downloads](https://www150.statcan.gc.ca/n1/en/catalogue/98-401-X) | What we downloaded (25 GB) |
| **2016** | 98-401-X2016044 | [2016 Download Page](https://www12.statcan.gc.ca/census-recensement/2016/dp-pd/prof/details/download-telecharger/comp/page_dl-tc.cfm?Lang=E) | ~1.6 GB for all geo levels |
| **2011** | 98-316-XWE | [2011 Download Page](https://www12.statcan.gc.ca/census-recensement/2011/dp-pd/prof/details/download-telecharger/comprehensive/comp-csv-tab-dwnld-tlchrgr.cfm?Lang=E) | ~194 MB for DAs |
| **Multi-year** | - | [Census Datasets Portal](https://www12.statcan.gc.ca/datasets/index-eng.cfm) | 1981-2021 selected datasets |

**2016 Direct Download URLs:**
```
# All levels (Canada through CSDs) - 147 MB compressed
https://www12.statcan.gc.ca/census-recensement/2016/dp-pd/prof/details/download-telecharger/comp/GetFile.cfm?Lang=E&FILETYPE=CSV&GEONO=055

# All levels including DAs - 1.6 GB compressed
https://www12.statcan.gc.ca/census-recensement/2016/dp-pd/prof/details/download-telecharger/comp/GetFile.cfm?Lang=E&FILETYPE=CSV&GEONO=044
```

**Data Structure (why 25 GB for one census year):**
- 166.8 million rows total (63,409 locations x 2,631 characteristics)
- Each row = one characteristic for one location
- Characteristics span: population, age, income, languages, indigenous identity, immigration, ethnicity, religion, mobility, education, labour, commuting

**Characteristic Categories (2,631 total):**
| ID Range | Category | Variables |
|----------|----------|-----------|
| 1-40 | Population & Age | Population 2021/2016, age groups, density |
| 41-110 | Dwellings & Families | Structure type, household size, family composition |
| 111-382 | Income | Median/mean income, sources, deciles, inequality (2019 & 2020) |
| 383-1401 | Languages | ~1000 languages - mother tongue, home, work |
| 1402-1521 | Indigenous Identity | First Nations, Metis, Inuit, Treaty status |
| 1522-1682 | Immigration | Citizenship, place of birth, admission category |
| 1683-1948 | Ethnicity | Visible minority, 250+ ethnic origins |
| 1949-1973 | Religion | 25+ religions |
| 1974-2222 | Education & Mobility | Degrees, field of study, moved in past 1/5 years |
| 2223-2631 | Labour & Commuting | Employment, occupation, industry, mode of transport |

**Future Processing Notes:**
- Will need to extract subset of key characteristics (~50-100) for practical use
- Consider splitting into multiple parquets by theme (demographics, income, housing, labour, etc.)
- For future census years, download only the trimmed characteristic set
- CSD level (5,161 municipalities) is primary target; DA level (57,936) optional for finer analysis

**Province Code Mapping:**
| Code | Province | Abbr |
|------|----------|------|
| 10 | Newfoundland and Labrador | NL |
| 11 | Prince Edward Island | PE |
| 12 | Nova Scotia | NS |
| 13 | New Brunswick | NB |
| 24 | Quebec | QC |
| 35 | Ontario | ON |
| 46 | Manitoba | MB |
| 47 | Saskatchewan | SK |
| 48 | Alberta | AB |
| 59 | British Columbia | BC |
| 60 | Yukon | YT |
| 61 | Northwest Territories | NT |
| 62 | Nunavut | NU |

### Australian Data (ABS)

Australia uses State/Territory codes with LGA (Local Government Area) codes:

| Level | Description | Units | Source ID | loc_id |
|-------|-------------|-------|-----------|--------|
| State | States/Territories | 9 | `state_code_2021` | `AUS-NSW` |
| LGA | Local Government Areas | 547 | `lga_code_2024` | `AUS-NSW-10050` |
| SA2 | Statistical Area Level 2 | 2,472 | `sa2_code` | (optional) |

```python
# Australia ABS to loc_id
state_code = 1  # New South Wales
lga_code = 10050  # Albury
state_abbr = AUS_STATE_TO_ABBR[state_code]  # "NSW"
loc_id = f"AUS-{state_abbr}-{lga_code}"  # "AUS-NSW-10050"
```

**Downloaded ABS Files:**
- `ERP_2024_LGA/` - GeoPackage with 547 LGAs, population 2001-2024 + geometry (54 MB)
- `ERP_2024_SA2/` - GeoPackage with SA2 regions (71 MB)
- `Data-cubes/` - 6 Excel files with time series data (2.2 MB)

**Data Structure (much cleaner than Canada!):**
- Wide table format: 1 row per LGA, columns for each year/metric
- 547 LGAs x 61 columns = ~33,000 cells (vs Canada's 166 million rows)
- Geometry included in GeoPackage
- Ready to convert with minimal processing

**Column Categories (61 total):**
| Category | Columns | Notes |
|----------|---------|-------|
| Identifiers | state_code, state_name, lga_code, lga_name | 4 columns |
| Population (ERP) | erp_2001 through erp_2024 | 24 years time series |
| Area/Density | area_km2, pop_density_2024 | 2 columns |
| Change | erp_change_number, erp_change_per_cent | 2023-24 |
| Births/Deaths | births, deaths, natural_increase | 3 fiscal years (2021-24) |
| Internal Migration | arrivals, departures, net | 3 fiscal years |
| Overseas Migration | arrivals, departures, net | 3 fiscal years |
| Geometry | geom (polygon) | Built-in |

**ABS Regional Population Download URLs (for future reference):**

Australia releases annual population estimates. Download page:

| Release | Download Page | Notes |
|---------|---------------|-------|
| **Latest (2023-24)** | [Regional Population](https://www.abs.gov.au/statistics/people/population/regional-population/latest-release) | What we downloaded |
| **Previous releases** | Same URL, select "Previous releases" | Annual updates |

**Direct Download URLs (from latest release page):**
```
# LGA GeoPackage (population 2001-2024 + geometry) - 38 MB
https://www.abs.gov.au/statistics/people/population/regional-population/latest-release
-> Download: "LGA population estimates (2001-2024), GDA 2020 GeoPackage"

# SA2 GeoPackage (finer granularity) - 48 MB
-> Download: "SA2 population estimates (2001-2024), GDA 2020 GeoPackage"

# Excel data cubes (no geometry)
-> Download: "Population estimates by LGA, 2001-2024" (265 KB)
```

**Comparison: Australia vs Canada Data Quality**
| Aspect | Australia | Canada |
|--------|-----------|--------|
| Format | GeoPackage (geometry included) | CSV (geometry separate) |
| Size | 54 MB | 25 GB |
| Structure | Wide (1 row per LGA) | Long (1 row per characteristic) |
| Time series | 24 years built-in | Single year + comparison |
| Variables | 61 columns | 2,631 characteristics |
| Converter effort | Low (direct extract) | High (pivot + filter) |

**State Code Mapping:**
| Code | State/Territory | Abbr |
|------|-----------------|------|
| 1 | New South Wales | NSW |
| 2 | Victoria | VIC |
| 3 | Queensland | QLD |
| 4 | South Australia | SA |
| 5 | Western Australia | WA |
| 6 | Tasmania | TAS |
| 7 | Northern Territory | NT |
| 8 | Australian Capital Territory | ACT |
| 9 | Other Territories | OT |

### Global/Country-Level Data

Sources that provide country-level data use ISO 3166-1 alpha-3 directly:

```python
# ReliefWeb uses ISO alpha-3
country_iso3 = "USA"  # Already in our format
loc_id = country_iso3  # "USA"
```

### Water Body Codes (for ocean/sea disasters)

ReliefWeb disasters may reference ocean areas. Use existing water body codes from GEOMETRY.md:
- `XOA` - Atlantic Ocean
- `XOP` - Pacific Ocean
- `XOI` - Indian Ocean
- `XSC` - Caribbean Sea
- `XSG` - Gulf of Mexico

### Geometry Considerations

For international data, we have two options:

1. **Use existing GADM geometry** - GADM has admin boundaries for all countries. Need to build crosswalk from source IDs (NUTS, CSD, LGA) to GADM region codes.

2. **Import source geometry** - The downloaded files include geometry:
   - ABS GeoPackage files have LGA boundaries
   - Eurostat GISCO provides NUTS boundaries
   - StatsCan provides boundary files separately

The second option is cleaner since the geometry matches the data exactly. We would:
- Import AUS LGA geometry from GeoPackage -> `AUS.parquet`
- Import NUTS 3 geometry from GISCO -> country parquets (DEU.parquet, FRA.parquet, etc.)
- Import Canada CSD geometry from StatsCan -> `CAN.parquet`

---

## Download Priority Order (New Sources)

1. **ReliefWeb API** - Global disasters, complements HDX/EM-DAT, easy JSON API
2. **EPA AQS Annual AQI** - 45 years of air quality, new visualization layer
3. **EIA Bulk Data** - Energy infrastructure, state-level metrics (state level = easy)
4. **Statistics Canada Census** - Canadian population for municipality mapping (needs crosswalk)
5. **ABS Regional Population** - Australian LGA population for expansion (needs crosswalk)
6. **Eurostat NUTS 3** - European regional data for future expansion (needs crosswalk)

---

*Quick reference doc for laptop session.*

ession Complete Summary
Successfully completed USGS Earthquakes and NOAA Storm Events with dual-file structure:
USGS Earthquakes (NEW)
events.parquet (5.7 MB): 173,971 earthquakes with felt_radius_km & damage_radius_km
USA.parquet (61 KB): 7,680 county-year aggregates (min/max/avg magnitude)
Geocoded using Census TIGER/Line 2024 shapefile
Magnitude 3.0+ from 1970-2025
Largest: Mag 8.2 (damage radius 398 km)
NOAA Storm Events (UPDATED)
events.parquet (28 MB): 1,231,663 individual storms with event_radius_km
USA.parquet (1 MB): County-year aggregates (existing)
Event types: Tornadoes, hail, floods, hurricanes, wildfires, etc.
Casualties & damage data included
61.5% of events have location data (1950-2025)
### Current Data Inventory (as of 2026-01-05)

**FEMA Sources:**
| Source | Files | Records | Time Range |
|--------|-------|---------|------------|
| NRI (Risk Index) | USA.parquet + USA_full.parquet | 12,747 + 3,232 | 2021-2025 (4 versions) |
| Disaster Declarations | USA.parquet + USA_declarations.parquet | 46,901 + 68,542 | 1953-2025 |

**NOAA Sources:**
| Source | Files | Records | Time Range |
|--------|-------|---------|------------|
| Storm Events | USA.parquet + events.parquet + reference.json | 159,651 + 1,231,663 | 1950-2025 |
| Drought Monitor | USA.parquet | 90,188 | 2000-2026 |

**Other Sources:**
| Source | Files | Records | Time Range |
|--------|-------|---------|------------|
| Wildfire Risk | USA.parquet | 3,144 | Snapshot (2022 conditions) |
| Earthquakes | USA.parquet + events.parquet | 7,680 + 173,971 | 1970-2025 |

**Raw Data Preserved:**
All raw downloaded files are preserved in `county-map-data/Raw data/`:

FEMA (`Raw data/fema/`):
- `nri_counties/nri_v1_17_raw.json` (27.5 MB)
- `nri_counties/nri_v1_18_1_raw.json` (30.5 MB)
- `nri_counties/nri_v1_19_0_raw.json` (41.3 MB)
- `nri_counties/nri_v1_20_0_raw.json` (41.6 MB)
- `disasters/disaster_declarations_raw.json` (60.1 MB)
- `nri_hazard_info.json` (8.7 KB)

Canada (`Raw data/canada/` - 1.8 GB total):
- `cnfdb/NFDB_point.zip` (29 MB) - Fire point locations
- `cnfdb/NFDB_poly.zip` (742 MB) - Fire perimeter polygons
- `drought/` (1 GB) - 325 monthly GeoJSON files (2019-2025)
- `eqarchive-en.csv` (8 MB) - Earthquake catalog
- `earthquakes_en.gdb.zip` (3.7 MB) - Earthquake geodatabase

Australia (`Raw data/australia/` - 7.6 MB):
- `IDCKMSTM0S.csv` (7.6 MB) - 31,225 cyclone track records (1909-present)

NOAA (`Raw data/noaa/` - 65 MB):
- `climate_at_a_glance/national/` - 9 parameter files (1895-2025)
- `climate_at_a_glance/state/` - 193 state parameter files

HDX (`Raw data/hdx/` - 390 KB):
- `EMDAT-country-profiles_2026_01_06.xlsx` - Global disaster statistics

DesInventar (`Raw data/desinventar/` - downloading):
- Up to 82 country XML files with detailed disaster records

