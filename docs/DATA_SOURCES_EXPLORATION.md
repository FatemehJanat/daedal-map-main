# County Map - Data Sources Exploration

Quick reference for potential data sources to expand risk scoring capabilities.

Last Updated: January 5, 2026

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

- [x] Download FEMA NRI county-level data via ArcGIS
- [x] Build converter following existing pattern
- [x] Generate metadata.json
- [x] Add to index.json
- [x] Download ALL 4 historical NRI versions (v1.17, v1.18.1, v1.19.0, v1.20.0) for trend analysis
- [x] Create NRI time-series converter (merge 4 versions into single parquet)
- [x] Download all 467 fields (not just 188) from latest NRI version
- [x] Download FEMA disaster declarations (68K records, 1953-2025)
- [x] Create disaster declarations converter with county-year aggregates
- [ ] Wait for FEMA infrastructure recovery for NFHL flood zones
- [ ] Add NOAA Climate at a Glance data
- [ ] Consider NRI Census Tracts download (85K+ records, finer granularity)

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
All raw downloaded files are preserved in `county-map-data/Raw data/fema/`:
- `nri_counties/nri_v1_17_raw.json` (27.5 MB)
- `nri_counties/nri_v1_18_1_raw.json` (30.5 MB)
- `nri_counties/nri_v1_19_0_raw.json` (41.3 MB)
- `nri_counties/nri_v1_20_0_raw.json` (41.6 MB)
- `disasters/disaster_declarations_raw.json` (60.1 MB)
- `nri_hazard_info.json` (8.7 KB)

