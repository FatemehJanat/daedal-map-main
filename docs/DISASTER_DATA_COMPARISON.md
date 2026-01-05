# Disaster Data Comparison Report

**Generated:** January 5, 2026

This report compares our various disaster/hazard datasets, identifies naming mappings between them, and documents gaps in our data coverage relative to what FEMA NRI claims to use.

---

## Executive Summary

We have **6 primary disaster/hazard datasets** covering different aspects of natural hazards:

| Dataset | Type | Time Range | Records | Primary Use |
|---------|------|------------|---------|-------------|
| FEMA Disaster Declarations | Historical events | 1953-2025 | 68,542 | Federal response history |
| NOAA Storm Events | Historical events | 1950-2025 | 1.2M+ | Weather event details |
| USGS Earthquakes | Historical events | 1970-2025 | 173,971 | Seismic events |
| USDM Drought | Time-series | 2000-2025 | 90,188 | Drought conditions |
| USFS Wildfire Risk | Snapshot | 2022 | 3,144 | Fire risk assessment |
| FEMA NRI | Risk scores | 2021-2025 | 12,747 | Composite risk index |

**Key Findings:**
1. NOAA Storm Events is our most comprehensive historical event dataset
2. We have significant gaps in historical data for cold wave, heat wave, and winter weather
3. FEMA NRI uses data sources we don't directly have (ice storm data back to 1946)
4. Hurricane historical data goes back to 1851 (per FEMA) but we only have 1950+
5. Some FEMA hazard types use probability models, not historical records

---

## Dataset Details

### 1. FEMA Disaster Declarations (68,542 records)

**Coverage:** 1953-2025 (72 years)
**Counties:** 3,238 unique

This is the official record of presidentially-declared disasters. NOT the same as actual events - represents federal response decisions.

**Top Incident Types:**
| Type | Count | Notes |
|------|-------|-------|
| Severe Storm | 19,299 | Includes thunderstorms, high winds, hail |
| Hurricane | 13,721 | Major tropical storms requiring federal aid |
| Flood | 11,227 | River and flash flooding |
| Biological | 7,857 | COVID-19 pandemic declarations |
| Fire | 3,844 | Wildfires requiring federal assistance |
| Snowstorm | 3,707 | Major winter storms |
| Severe Ice Storm | 2,956 | Freezing rain/ice events |
| Tornado | 1,623 | Only severe tornadoes get declarations |
| Drought | 1,292 | Agricultural disasters |
| Earthquake | 228 | Relatively rare federal declarations |

**Important:** Declarations != Events. A single hurricane may generate 50+ county declarations, while thousands of small tornadoes never get declared.

---

### 2. NOAA Storm Events (1,231,663 individual events)

**Coverage:** 1950-2025 (76 years, with data quality issues pre-1969)
**Counties:** 3,403 unique (in aggregate file)

This is our primary source for actual weather event records with locations, casualties, and damage.

**Top Event Types:**
| Type | Count | FEMA Equivalent |
|------|-------|-----------------|
| Thunderstorm Wind | 538,814 | Severe Storm |
| Hail | 398,488 | Severe Storm |
| Tornado | 79,038 | Tornado |
| Flash Flood | 78,992 | Flood |
| Flood | 50,279 | Flood |
| Marine Thunderstorm Wind | 39,000 | (marine zone) |
| Heavy Rain | 23,662 | Flood |
| Lightning | 9,074 | Severe Storm |
| Funnel Cloud | 6,270 | (pre-tornado) |
| Debris Flow | 1,746 | Landslide |

**Data Quality Note:** 33,308 events have future dates (2050s-2060s) - likely parsing errors from 1950s-1960s data. Should be corrected.

**Event Type Coverage in Aggregate (USA.parquet):**

The aggregate file has 32 event type columns with varying coverage:

| Event Type | Total Events | Notes |
|------------|--------------|-------|
| Thunderstorm Wind | 563,168 | GOOD coverage |
| Hail | 418,619 | GOOD coverage |
| Flash Flood | 109,930 | GOOD coverage |
| Tornado | 80,214 | GOOD coverage |
| Flood | 52,930 | GOOD coverage |
| Heavy Rain | 29,912 | GOOD coverage |
| Lightning | 18,138 | Moderate coverage |
| Funnel Cloud | 9,914 | GOOD coverage |
| Wildfire | 1,749 | LIMITED - need NIFC data |
| Winter Weather | 48 | VERY LIMITED |
| Heavy Snow | 38 | VERY LIMITED |
| Hurricane (Typhoon) | 6 | VERY LIMITED - need HURDAT |
| Heat | 11 | VERY LIMITED - need NCEI |
| Excessive Heat | 1 | VERY LIMITED |
| Cold Wind Chill | 3 | VERY LIMITED |
| Frost Freeze | 16 | VERY LIMITED |
| Drought | 4 | VERY LIMITED - have USDM |
| Volcanic Ash | 4 | Rare events |

**Key Gaps Identified:**
- Hurricanes (only 6 events! - need HURDAT2 database)
- Earthquakes (separate USGS source - we have this)
- Wildfires (only 1,749 events - need NIFC/MTBS)
- Heat/Cold extremes (minimal coverage - need NCEI)
- Winter storms (minimal in events file)

---

### 3. USGS Earthquakes (173,971 events)

**Coverage:** 1970-2025 (55 years)
**Counties:** 985 unique with earthquakes
**Magnitude Range:** 2.4 - 8.2

This covers seismic events that NOAA does not track.

**By Decade:**
| Decade | Events |
|--------|--------|
| 1970s | ~5,000 |
| 1980s | ~10,000 |
| 1990s | ~15,000 |
| 2000s | ~35,000 |
| 2010s | ~55,000 |
| 2020s | ~53,000 |

Note: Increasing counts reflect improved detection, not necessarily more earthquakes.

---

### 4. USDM Drought Monitor (90,188 county-year records)

**Coverage:** 2000-2025 (26 years)
**Counties:** 3,221 unique

Weekly drought conditions aggregated to annual statistics.

**Coverage Gap:** FEMA NRI uses drought data from 2000-2025, which we have. However, historical drought records (pre-2000) would require different sources like Palmer Drought Severity Index.

---

### 5. USFS Wildfire Risk (3,144 counties)

**Coverage:** Snapshot (2022 landscape conditions)
**Type:** Risk assessment, not historical events

This is a modeled risk assessment, not historical fire records. For actual fire events, we rely on NOAA's limited wildfire data.

**Gap:** We don't have comprehensive historical wildfire event data. Sources to consider:
- NIFC (National Interagency Fire Center) fire perimeters
- MTBS (Monitoring Trends in Burn Severity)
- InciWeb fire incidents

---

## FEMA NRI Data Sources vs Our Coverage

FEMA claims to use specific historical periods for each hazard. Here's how we compare:

### Hazards We HAVE Good Coverage For:

| Hazard | FEMA Period | Our Data | Status |
|--------|-------------|----------|--------|
| Tornado | 1986-2023 (38 yrs) | NOAA 1950-2025 | COVERED |
| Hail | 1986-2023 (38 yrs) | NOAA 1950-2025 | COVERED |
| Strong Wind | 1986-2023 (38 yrs) | NOAA 1950-2025 | COVERED |
| Drought | 2000-2025 (25 yrs) | USDM 2000-2025 | COVERED |
| Earthquake | Probability model | USGS 1970-2025 | COVERED |
| Inland Flooding | 1996-2023 (28 yrs) | NOAA 1950-2025 | COVERED |

### Hazards With PARTIAL Coverage:

| Hazard | FEMA Period | Our Data | Gap |
|--------|-------------|----------|-----|
| Hurricane | 1851-2024 (173 yrs!) | NOAA 1950-2025 | Missing 100 years! |
| Avalanche | 1994-2023 (30 yrs) | NOAA has some | Need to verify |
| Cold Wave | 2005-2024 (19 yrs) | Limited in NOAA | May need NCEI data |
| Heat Wave | 2005-2024 (19 yrs) | Limited in NOAA | May need NCEI data |
| Winter Weather | 2005-2024 (19 yrs) | NOAA 1950-2025 | COVERED |

### Hazards With NO Historical Events (Model-Based):

| Hazard | FEMA Approach | Our Coverage |
|--------|---------------|--------------|
| Coastal Flooding | Probability model | No event data |
| Landslide | Probability model | Debris Flow in NOAA |
| Lightning | Probability model | Limited in NOAA |
| Tsunami | Probability model | No event data |
| Volcanic Activity | Probability model | No event data |
| Wildfire | Probability model | USFS risk only |

### Hazards With SIGNIFICANT Gaps:

| Hazard | FEMA Period | Our Data | Gap |
|--------|-------------|----------|-----|
| Ice Storm | 1946-2014 (67 yrs!) | NOAA 1950-2025 | Need pre-1950 data |
| Hurricane (pre-1950) | 1851-1949 | NONE | 100 years missing |

---

## Event Type Mapping

### FEMA Declarations -> NOAA Event Types

| FEMA Type | Maps To NOAA Types |
|-----------|-------------------|
| Tornado | Tornado |
| Hurricane | (Not directly in NOAA - need HURDAT) |
| Tropical Storm | (Not directly in NOAA - need HURDAT) |
| Flood | Flood, Flash Flood, Coastal Flood |
| Severe Storm | Thunderstorm Wind, Hail, Lightning |
| Fire | Wildfire (limited) |
| Snowstorm | Heavy Snow, Blizzard, Winter Storm |
| Severe Ice Storm | Ice Storm, Freezing Fog |
| Drought | Drought (rare in NOAA) |
| Coastal Storm | Coastal Flood, Storm Surge/Tide |
| Earthquake | (USGS, not NOAA) |
| Volcanic | (Not in NOAA) |

### FEMA NRI Hazard -> Our Data Sources

| NRI Hazard | Primary Source | Secondary Source |
|------------|----------------|------------------|
| AVLN (Avalanche) | NOAA | None |
| CFLD (Coastal Flooding) | Model-based | None |
| CWAV (Cold Wave) | NOAA (limited) | NCEI needed |
| DRGT (Drought) | USDM | Palmer Drought Index |
| ERQK (Earthquake) | USGS | None |
| HAIL (Hail) | NOAA | None |
| HWAV (Heat Wave) | NOAA (limited) | NCEI needed |
| HRCN (Hurricane) | NOAA + HURDAT needed | NHC data |
| ISTM (Ice Storm) | NOAA | None |
| IFLD (Inland Flooding) | NOAA | None |
| LNDS (Landslide) | NOAA (Debris Flow) | USGS landslide |
| LTNG (Lightning) | NOAA | None |
| SWND (Strong Wind) | NOAA | None |
| TRND (Tornado) | NOAA | None |
| TSUN (Tsunami) | Model-based | NOAA tsunami db |
| VLCN (Volcanic) | Model-based | USGS volcano |
| WFIR (Wildfire) | USFS risk | NIFC/MTBS events |
| WNTW (Winter Weather) | NOAA | None |

---

## Data Gaps and Recommendations

### Priority 1: Hurricane Historical Data (1851-1949)

**Gap:** 100 years of hurricane data missing

**Source:** NOAA HURDAT2 (Hurricane Database)
- Atlantic: https://www.nhc.noaa.gov/data/hurdat/hurdat2-1851-2023-051124.txt
- Pacific: https://www.nhc.noaa.gov/data/hurdat/hurdat2-nepac-1949-2023-042624.txt

**Action:** Download and integrate HURDAT2 for complete hurricane history.

### Priority 2: Cold Wave / Heat Wave Events

**Gap:** Limited event coverage for temperature extremes

**Source:** NOAA NCEI Climate at a Glance
- Temperature anomalies by county
- Degree day data

**Action:** Add temperature extreme data from NCEI.

### Priority 3: Wildfire Event History

**Gap:** Only have risk scores, not historical fire events

**Sources:**
- NIFC fire perimeters (2000-present)
- MTBS burn severity (1984-present)
- InciWeb incidents

**Action:** Download historical wildfire perimeter data.

### Priority 4: Tsunami and Volcano Events

**Gap:** No event data for these hazards

**Sources:**
- NOAA NGDC Tsunami Database
- USGS Volcano Hazards Program

**Action:** These are rare events but worth cataloging for completeness.

### Priority 5: Pre-1950 Event Data

**Gap:** Limited data before 1950 for most hazards

**Sources:**
- Historical newspaper archives
- State climate records
- Monthly Weather Review archives

**Action:** Lower priority due to data quality concerns.

---

## Data Quality Issues

### NOAA Storm Events

1. **Future dates (2050s-2060s):** 33,308 events have incorrect dates - likely 1950s-1960s data with century parsing errors.

2. **Missing coordinates:** Many pre-1990 events lack lat/lon data.

3. **Inconsistent damage estimates:** Pre-1996 damage values may not be inflation-adjusted.

### FEMA Disaster Declarations

1. **Statewide declarations:** 1,552 records are statewide (FIPS 000), not county-specific.

2. **Biological category:** 7,857 COVID-related declarations skew recent data.

### USGS Earthquakes

1. **Detection bias:** More recent data has more small earthquakes due to improved sensors.

2. **Offshore events:** Many earthquakes are offshore and don't map to counties.

---

## Summary Table: What We Have vs What We Need

| Hazard | Historical Events | Risk Scores | Gap Priority |
|--------|-------------------|-------------|--------------|
| Tornado | NOAA (1950+) | NRI | LOW |
| Hurricane | NOAA (1950+) | NRI | HIGH (pre-1950) |
| Flood | NOAA (1950+) | NRI | LOW |
| Earthquake | USGS (1970+) | NRI | LOW |
| Drought | USDM (2000+) | NRI | MEDIUM (pre-2000) |
| Wildfire | Limited | USFS + NRI | HIGH (events) |
| Hail | NOAA (1950+) | NRI | LOW |
| Tornado | NOAA (1950+) | NRI | LOW |
| Heat Wave | Limited | NRI | MEDIUM |
| Cold Wave | Limited | NRI | MEDIUM |
| Winter Weather | NOAA (1950+) | NRI | LOW |
| Ice Storm | NOAA (1950+) | NRI | MEDIUM (pre-1950) |
| Tsunami | None | NRI (model) | LOW (rare) |
| Volcano | None | NRI (model) | LOW (rare) |
| Landslide | NOAA (Debris Flow) | NRI | LOW |
| Lightning | Limited | NRI | LOW |
| Avalanche | Limited | NRI | LOW |
| Coastal Flood | Limited | NRI | MEDIUM |

---

## Next Steps

1. **Fix NOAA date parsing** - Correct 33K events with 2050s dates
2. **Download HURDAT2** - Add 100+ years of hurricane history
3. **Add wildfire events** - NIFC/MTBS data for historical fires
4. **Evaluate NCEI temperature data** - For heat wave / cold wave coverage
5. **Consider NOAA tsunami database** - For completeness

---

*Report generated for county-map project data inventory.*
