# Disaster Data Reference

**Last Updated:** January 5, 2026

Comprehensive reference for all disaster/hazard datasets including processed data, raw downloads, visualization options, and data gaps.

**Related Docs:**
- [GEOMETRY.md](GEOMETRY.md) - Disaster entity types and loc_id format
- [DATA_SOURCES_EXPLORATION.md](DATA_SOURCES_EXPLORATION.md) - Data source URLs and download instructions
- [data_pipeline.md](data_pipeline.md) - Converter standards and finalize_source() workflow

---

## Quick Reference

### Data by Source Agency

| Agency | Datasets | Scope | Status |
|--------|----------|-------|--------|
| **FEMA** | Disaster Declarations, NRI Risk Scores | US Only | Processed |
| **NOAA NHC** | HURDAT2 Hurricane Tracks | Atlantic/Pacific | Downloaded |
| **NOAA NCEI** | Storm Events, Tsunami Database | US / Global | Processed + Downloaded |
| **USGS** | Earthquakes | US / Global | Processed |
| **USFS/MTBS** | Wildfire Perimeters | US Only | Downloaded |
| **Smithsonian** | Volcanoes, Eruptions | Global | Downloaded |
| **USDM** | Drought Monitor | US Only | Processed |

### Record Counts Summary

| Dataset | Total Records | US Records | Coverage |
|---------|---------------|------------|----------|
| FEMA Disasters | 68,542 | 68,542 | 1953-2025 |
| NOAA Storm Events | 1.2M+ | 1.2M+ | 1950-2025 |
| HURDAT2 Hurricanes | 1,991 storms | ~600 | 1851-2024 |
| MTBS Wildfires | ~25,000 fires | ~25,000 | 1984-2023 |
| NOAA Tsunamis | 3,025 events | 321 | 2100 BC-present |
| Tsunami Runups | 34,281 locations | 4,329 | - |
| Volcanoes | 1,222 | 165 | Holocene |
| Eruptions | 11,079 | 1,281 | - |
| USGS Earthquakes | 173,971 | ~100,000 | 1970-2025 |

---

## Processed Data (Ready for Mapping)

Location: `county-map-data/countries/USA/`

### FEMA Disaster Declarations
- **Files:** `fema_disasters/USA.parquet`, `USA_declarations.parquet`
- **Records:** 68,542 declarations (46,901 county-year aggregates)
- **Coverage:** 1953-2025 (72 years), 3,238 counties
- **Key Fields:** loc_id, year, total_declarations, disaster_types, incident counts by category

**Top Incident Types:**
| Type | Count |
|------|-------|
| Severe Storm | 19,299 |
| Hurricane | 13,721 |
| Flood | 11,227 |
| Biological | 7,857 |
| Fire | 3,844 |

### NOAA Storm Events
- **Files:** `noaa_storms/USA.parquet`, `events.parquet`
- **Records:** 1.2M+ individual events, 159,651 county-year aggregates
- **Coverage:** 1950-2025 (76 years), 3,403 counties
- **Key Fields:** 32 event type columns (tornado, hail, flood, etc.)

### FEMA NRI Risk Scores
- **Files:** `fema_nri/USA.parquet`, `USA_full.parquet`
- **Records:** 12,747 (time-series), 3,232 (latest full)
- **Coverage:** 4 versions (2021-2025)
- **Key Fields:** Risk scores for 18 hazards, Expected Annual Loss, Social Vulnerability

### USGS Earthquakes
- **Files:** `usgs_earthquakes/USA.parquet`, `events.parquet`
- **Records:** 173,971 events
- **Coverage:** 1970-2025, magnitude 2.4-8.2
- **Key Fields:** loc_id, year, magnitude, depth, coordinates

### USDM Drought
- **Files:** `usdm_drought/USA.parquet`
- **Records:** 90,188 county-year records
- **Coverage:** 2000-2025 (26 years)
- **Key Fields:** Drought severity (D0-D4), weeks in drought, max severity

### USFS Wildfire Risk
- **Files:** `wildfire_risk/USA.parquet`
- **Records:** 3,144 counties
- **Coverage:** 2022 snapshot (modeled risk, not events)
- **Key Fields:** Fire risk scores, exposure metrics

---

## Raw Downloaded Data (Needs Processing)

Location: `county-map-data/Raw data/`
Total Size: 410 MB

### HURDAT2 Hurricane Database (NOAA NHC)
**Path:** `noaa/hurdat2/`
**Source:** https://www.nhc.noaa.gov/data/

| File | Size | Records | Coverage |
|------|------|---------|----------|
| hurdat2_atlantic.txt | 6.7 MB | 1,991 storms, 57,221 positions | 1851-2024 |
| hurdat2_pacific.txt | 3.8 MB | 32,781 positions | 1949-2024 |

**Data Format:** 6-hourly positions with coordinates
```
AL011851, UNNAMED, 14,
18510625, 0000, , HU, 28.0N, 94.8W, 80, -999, ...
```

**Key Fields:**
- Storm ID, Name
- Date, Time, Status (TD/TS/HU)
- Latitude, Longitude (e.g., `28.0N, 94.8W`)
- Max wind (kt), Min pressure (mb)
- Wind radii at 34/50/64 kt (NE/SE/SW/NW quadrants)

### MTBS Wildfire Perimeters (USGS/USFS)
**Path:** `mtbs/`
**Source:** https://www.mtbs.gov/direct-download

| File | Size | Description |
|------|------|-------------|
| mtbs_perimeter_data.zip | 357 MB | CONUS fire perimeters 1984-2023 |
| mtbs_fod_pts_data.zip | 3.3 MB | Fire occurrence points |

**Shapefile Attributes:**
- Event_ID, Incid_Name, Incid_Type
- BurnBndAc (burned acres)
- BurnBndLat, BurnBndLon (centroid)
- Ig_Date (ignition date)
- Geometry: Polygon (burn perimeter)

### NOAA Tsunami Database
**Path:** `noaa/tsunami/`
**Source:** https://www.ngdc.noaa.gov/hazel/

| File | Records | US Records | Description |
|------|---------|------------|-------------|
| tsunami_events.json | 3,025 | 321 | Source events |
| tsunami_runups.json | 34,281 | 4,329 | Coastal impact points |

**Event Fields:** id, year, country, locationName, latitude, longitude, causeCode, tsIntensity
**Runup Fields:** id, tsunamiEventId, country, area (state), locationName, latitude, longitude

**US Runup Distribution:**
| State | Count |
|-------|-------|
| Hawaii | 2,133 |
| California | 860 |
| Alaska | 759 |
| Washington | 250 |
| Oregon | 142 |

### Smithsonian Volcano Database
**Path:** `smithsonian/volcano/`
**Source:** https://volcano.si.edu/

| File | Features | Format | Description |
|------|----------|--------|-------------|
| gvp_volcanoes.json | 1,222 | GeoJSON | Volcano locations |
| gvp_eruptions.json | 11,079 | GeoJSON | Eruption history |

**US Volcanoes:** 165 total
- Aleutian Ridge (AK): 46
- Alaska Peninsula: 27
- High Cascades: 19
- Hawaiian Islands: 6
- Mariana Islands: 25
- Yellowstone: 4

**US Eruptions:** 1,281 total (459 since 1900)

**Volcano Fields:** Volcano_Number, Volcano_Name, Country, Latitude, Longitude, Last_Eruption_Year, Primary_Volcano_Type
**Eruption Fields:** Volcano_Number, Eruption_Number, StartDateYear, ExplosivityIndexMax (VEI)

---

## Visualization by Disaster Type

Each disaster type has appropriate geometry and display options.

| Type | Raw Data | Geometry | Display Method |
|------|----------|----------|----------------|
| **Hurricane** | Track positions | Polyline + buffered corridor | Path with wind swath polygon |
| **Wildfire** | Burn perimeters | Polygon | Fill with severity coloring |
| **Tsunami** | Source + runup points | Points | Markers with connection lines |
| **Volcano** | Location points | Point + radius | Location marker with VEI-scaled buffer |
| **Earthquake** | Epicenter points | Point + radius | Concentric shake intensity rings |
| **Tornado** | Begin/end coords | Line segment | Track path with EF-scale width |
| **Flood** | Affected areas | Polygon | Fill showing extent |

### Hurricane Visualization Detail

HURDAT2 provides wind radii in quadrants (NE, SE, SW, NW):
- 34 kt: Tropical storm winds
- 50 kt: Strong tropical storm
- 64 kt: Hurricane-force winds

**Visualization Options:**
1. **Track Line:** Connect 6-hourly positions
2. **Wind Swath:** Buffer track by wind radius (asymmetric per quadrant)
3. **Landfall Points:** Highlight where track crosses coastline
4. **Category Gradient:** Color track by intensity at each point

### Wildfire Visualization Detail

MTBS provides actual burn perimeters at 30m resolution.

**Visualization Options:**
1. **Perimeter Fill:** Show exact burned area
2. **Centroid + Size:** Point marker scaled by BurnBndAc
3. **Heatmap:** Density of fire occurrence
4. **Severity Overlay:** Color by dNBR burn severity thresholds

**MTBS Temporal Limitation:** MTBS data only includes YEAR, not exact ignition dates. For daily/hourly wildfire animation, additional data sources would be needed:

| Source | Granularity | Data Type | URL |
|--------|-------------|-----------|-----|
| **VIIRS/MODIS** | Daily hotspots | Active fire detections | https://firms.modaps.eosdis.nasa.gov/ |
| **NIFC InciWeb** | Daily updates | Incident situation reports | https://inciweb.wildfire.gov/ |
| **GeoMAC/IRWIN** | Daily perimeters | Fire boundary updates | https://data-nifc.opendata.arcgis.com/ |
| **WFIGS** | Near real-time | Integrated fire info | https://data-nifc.opendata.arcgis.com/ |

These sources would enable:
- Day-by-day fire ignition sequences
- Fire spread/growth animation
- Real-time active fire tracking

---

## Aggregation Hierarchy

Data can be aggregated at multiple levels for different queries.

### Level 1: Individual Events
```json
{
  "event_id": "USA-HRCN-IAN2022",
  "type": "hurricane",
  "name": "Hurricane Ian",
  "date": "2022-09-28",
  "max_wind_kt": 150,
  "track": "LINESTRING(...)",
  "affected_counties": ["USA-FL-12021", "USA-FL-12015", ...]
}
```

### Level 2: County-Year Aggregates (Primary for mapping)
```json
{
  "loc_id": "USA-FL-12021",
  "year": 2022,
  "hurricane_count": 1,
  "wildfire_count": 0,
  "tornado_count": 3,
  "total_events": 9,
  "total_damage_usd": 15000000
}
```

### Level 3: State/Region/Country Rollups (Derived on query)
```python
# "How many hurricanes has Florida had?"
fl_counties = df[df['loc_id'].str.startswith('USA-FL-')]
total = fl_counties['hurricane_count'].sum()

# "Wildfires in Pacific Northwest?"
pnw = ['USA-WA-', 'USA-OR-', 'USA-ID-']
pnw_df = df[df['loc_id'].str.match('|'.join(pnw))]
total = pnw_df['wildfire_count'].sum()

# "Total US disasters since 2000?"
us_df = df[(df['loc_id'].str.startswith('USA-')) & (df['year'] >= 2000)]
total = us_df['total_events'].sum()
```

---

## Disasters as Geometry Entities

See [GEOMETRY.md](GEOMETRY.md#disaster-hazard-events) for full specification.

Disasters are treated as cross-boundary entities with their own `loc_id` values, following the sibling rule:

| Disaster scope | Level | Example loc_id |
|----------------|-------|----------------|
| Multiple counties in one state | 2 | `USA-CA-FIRE-CREEK2020` |
| Multiple states | 1 | `USA-HRCN-IAN2022` |
| Multiple countries | 0 | `PACIFIC-TSUN-2011TOHOKU` |

### Impact Linkage

Disasters link to affected admin units via impact table:

```
disaster_loc_id         | affected_loc_id  | impact_type  | value
USA-HRCN-IAN2022        | USA-FL-12021     | landfall     | category_4
USA-HRCN-IAN2022        | USA-FL-12015     | wind_damage  | 120_kt
USA-CA-FIRE-CREEK2020   | USA-CA-06019     | burned_acres | 379895
```

This enables bidirectional queries:
- "Show Hurricane Ian" -> load geometry + list affected counties
- "What disasters affected Lee County?" -> scan impact table for `USA-FL-12021`

---

## Data Gaps Analysis

### Gaps Filled by Downloads

| Gap | Solution | Status |
|-----|----------|--------|
| Pre-1950 hurricanes | HURDAT2 (1851-2024) | Downloaded |
| Historical wildfires | MTBS (1984-2023) | Downloaded |
| Tsunami events | NOAA NCEI (2100 BC-present) | Downloaded |
| Volcano eruptions | Smithsonian (Holocene) | Downloaded |

### Remaining Gaps

| Hazard | Current Coverage | Gap | Priority |
|--------|------------------|-----|----------|
| Heat Wave | Limited NOAA data | NCEI temperature extremes | MEDIUM |
| Cold Wave | Limited NOAA data | NCEI temperature extremes | MEDIUM |
| Ice Storm (pre-1950) | NOAA 1950+ | Historical archives | LOW |
| Pre-2000 Drought | USDM 2000+ | Palmer Drought Index | LOW |
| Coastal Flooding | Model only | Event database | MEDIUM |

### FEMA NRI Source Comparison

| NRI Hazard | FEMA Source Period | Our Coverage | Match |
|------------|-------------------|--------------|-------|
| Hurricane | 1851-2024 (173 yrs) | HURDAT2 1851-2024 | FULL |
| Tornado | 1986-2023 (38 yrs) | NOAA 1950-2025 | FULL |
| Wildfire | Model-based | MTBS 1984-2023 | FULL |
| Earthquake | Model-based | USGS 1970-2025 | FULL |
| Tsunami | Model-based | NCEI 2100 BC-present | FULL |
| Volcano | Model-based | Smithsonian Holocene | FULL |
| Drought | 2000-2025 | USDM 2000-2025 | FULL |

---

## Converters Needed

| Script | Input | Output | Spatial Processing |
|--------|-------|--------|---------------------|
| convert_hurdat2.py | Track text | Tracks + county aggregates | Buffer by wind radii |
| convert_mtbs.py | Shapefiles | Perimeters + county aggregates | Polygon intersection |
| convert_tsunami.py | JSON | Points + county aggregates | Point-in-polygon |
| convert_volcano.py | GeoJSON | Points + county aggregates | Buffer by VEI |

---

## File Organization

### Current Structure
```
county-map-data/
  countries/USA/
    fema_disasters/          # Processed
    fema_nri/                # Processed
    noaa_storms/             # Processed
    usgs_earthquakes/        # Processed
    usdm_drought/            # Processed
    wildfire_risk/           # Processed

  Raw data/
    noaa/hurdat2/            # Downloaded - needs processing
    noaa/tsunami/            # Downloaded - needs processing
    mtbs/                    # Downloaded - needs processing
    smithsonian/volcano/     # Downloaded - needs processing
```

### Proposed Structure (after converters)
```
county-map-data/
  countries/USA/
    hurricanes/              # HURDAT2 + FEMA hurricane declarations
    wildfires/               # MTBS + FEMA fire declarations
    tsunamis/                # NOAA NCEI
    volcanoes/               # Smithsonian GVP
    earthquakes/             # USGS
    floods/                  # NOAA + FEMA
    tornadoes/               # NOAA + FEMA
    severe_storms/           # NOAA + FEMA
    drought/                 # USDM
    composite/               # FEMA NRI risk scores
```

---

*This document consolidates DISASTER_DATA_COMPARISON.md, DISASTER_DATA_INVENTORY.md, and DOWNLOADED_DATA_REPORT.md.*
