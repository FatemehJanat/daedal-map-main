# Canada Data Analysis
*Created: 2026-01-13*

## Purpose

Evaluate whether Canada fire and drought data should be processed to supplement our global disaster coverage.

---

## Summary

**DROUGHT: YES - Process it. We have NO global drought coverage.**

**FIRES: YES - Process it. Canada fires severely underrepresented in global data.**

---

## 1. Canada Drought Monitor

### What We Have (Raw Data)

**Location:** `Raw data/imported/canada/drought/`
**Source:** Agriculture and Agri-Food Canada
**URL:** https://agriculture.canada.ca/atlas/data_donnees/canadianDroughtMonitor/
**License:** Open Government License - Canada

**Coverage:**
- **Years:** 2019-2025 (through November 2025)
- **Frequency:** Monthly
- **Format:** GeoJSON polygons by severity level
- **Files:** 325 total (7 years x 12 months x 5 severity levels)
- **Size:** ~1 GB uncompressed

**Severity Levels (Same as USA):**
- D0: Abnormally Dry
- D1: Moderate Drought
- D2: Severe Drought
- D3: Extreme Drought
- D4: Exceptional Drought

### What We Currently Have (Global)

**US Drought Monitor:**
- Location: `countries/USA/usdm_drought/`
- Coverage: 2000-2026
- Format: Converted to parquet

**Global Drought Data:** NONE

### Gap Analysis

**Current drought coverage:**
- USA: 2000-2026 (fully covered)
- Canada: NONE
- Rest of World: NONE

**If we process Canada Drought Monitor:**
- USA: 2000-2026
- Canada: 2019-2025
- Rest of World: Still NONE

**Conclusion:** Process Canada drought data to get North America coverage.

### Recommendation: PROCESS

**Why:**
1. We have NO global drought product
2. Canada Drought Monitor uses same D0-D4 scale as USA
3. Creates North America drought coverage (2019-2025)
4. Only 1 GB of data, manageable size
5. Monthly resolution matches US data

**Where to put it:**
- `countries/CAN/drought/` (similar to USA structure)
- Monthly parquet files OR single CAN.parquet with month column

**Converter needed:**
- Similar to US drought monitor converter
- Load GeoJSON polygons by month/severity
- Convert to parquet with columns: timestamp, severity, geometry, area_km2

---

## 2. Canada National Fire Database (CNFDB)

### What We Have (Raw Data)

**Location:** `Raw data/imported/canada/cnfdb/`
**Source:** Natural Resources Canada - Canadian Forest Service
**URL:** https://cwfis.cfs.nrcan.gc.ca/datamart
**License:** Open Government License - Canada

**Downloaded Files:**
1. **Fire Points** (30 MB) - All fire point data (lat/lon, date, cause, size)
2. **Fire Polygons** (743 MB) - Fire perimeter polygons (large fires >= 200 hectares)
3. **Large Fires** (2.4 MB) - Large fires >= 200 hectares subset
4. **Statistics** (797 KB) - Summary statistics (Excel)
5. **Text Version** (14 MB) - All fire point data in text format

**Total Size:** 789 MB

**Coverage:**
- **Spatial:** Canada (all provinces and territories)
- **Temporal:** Historical fire records (varies by province)
- **Data completeness:** Varies by province and year

### What We Currently Have (Global)

**Global Wildfires:**
- Location: `global/wildfires/by_year/`
- Source: NASA FIRMS (satellite fire detections)
- Coverage: 2002-2024, ~815K fires/year worldwide
- Format: Parquet files by year

**Canada fires in global data (2024):**
- Total 2024 global fires: 106,615
- Canada fires 2024: 38 fires
- **ONLY 38 FIRES FOR ALL OF CANADA IN 2024!**

### Gap Analysis

**Problem:** Canada is severely underrepresented in global fires.

**Why the gap?**
- NASA FIRMS detects active fires from satellites
- May miss smaller fires, fires under cloud cover, or fires in remote areas
- CNFDB is ground-truth data from Canadian forest management agencies
- CNFDB includes historical records going back decades (varies by province)

**Sample comparison (2023-2024):**
- Real-world: Canada had massive wildfire seasons in 2023-2024
- Global data: Only 38 fires detected in Canada for 2024
- CNFDB: Likely has thousands of fires for same period

### Recommendation: PROCESS

**Why:**
1. Canada severely underrepresented in global fires (only 38 in 2024!)
2. CNFDB has ground-truth data from Canadian fire management
3. Historical depth varies by province (some go back to early 1900s)
4. Includes fire polygons for large fires (743 MB polygon file)
5. Complements satellite data with official records

**Where to put it:**
- `countries/CAN/wildfires/` (similar to USA MTBS fires structure)
- Point data: `events.parquet` (all fires with lat/lon, date, size, cause)
- Polygons: Either in `perimeter` column or separate `geometry/` folder

**Data quality notes:**
- "Data completeness varies by province and year" (per metadata)
- "Not all fires have been mapped - see metadata for gaps" (per metadata)
- Should document coverage gaps in metadata.json

**Converter needed:**
- Read NFDB_point.zip shapefile → extract fire events
- Columns: event_id, timestamp, latitude, longitude, area_km2, cause, province
- Optionally: Read NFDB_poly.zip → add perimeter geometries for large fires
- Create metadata documenting coverage by province/year

---

## 3. Implementation Strategy

### Priority 1: Canada Drought (Higher Value)

**Rationale:** We have ZERO global drought coverage. Adding Canada creates North America drought map.

**Steps:**
1. Create converter: `convert_canada_drought.py`
2. Read GeoJSON files from `Raw data/imported/canada/drought/`
3. Convert to parquet with schema:
   - timestamp (monthly)
   - severity (D0-D4)
   - geometry (polygon)
   - area_km2
   - province (if available)
4. Output to: `countries/CAN/drought/CAN.parquet`
5. Create metadata.json documenting source, years, severity scale

**Expected result:** North America drought coverage (USA 2000-2026, CAN 2019-2025)

### Priority 2: Canada Fires (Fill Critical Gap)

**Rationale:** Canada has only 38 fires in 2024 global data - clearly missing thousands.

**Steps:**
1. Create converter: `convert_canada_fires.py`
2. Extract NFDB_point.zip shapefile
3. Read fire points with columns: lat, lon, date, size, cause, province
4. Convert to parquet with schema:
   - event_id
   - timestamp
   - latitude, longitude
   - area_km2 (convert from hectares)
   - fire_cause
   - province
   - has_polygon (boolean)
5. Optionally: Extract NFDB_poly.zip and add perimeter geometries
6. Output to: `countries/CAN/wildfires/events.parquet`
7. Create metadata.json documenting coverage by province, temporal range, data gaps

**Expected result:** Thousands of Canada fires added to supplement global satellite data

---

## 4. Comparison with Existing Data

### Drought Coverage After Processing

| Region | Current | After CAN Processing | Status |
|--------|---------|---------------------|--------|
| USA | 2000-2026 | 2000-2026 | Excellent |
| Canada | NONE | 2019-2025 | Good |
| Mexico | NONE | NONE | Gap |
| Rest of World | NONE | NONE | Major Gap |

**Takeaway:** No global drought product exists. Canada + USA creates North America coverage only.

### Fire Coverage After Processing

| Region | Global FIRMS | After CAN Processing | Improvement |
|--------|--------------|---------------------|-------------|
| USA | Good (~800K) | + USA MTBS (30K) | Excellent |
| Canada | VERY POOR (38 in 2024) | + CNFDB (thousands) | Excellent |
| Mexico | Good | - | - |
| Rest of World | Good (~940K/year) | - | - |

**Takeaway:** Canada fires will go from severely underrepresented to excellent coverage.

---

## 5. Disk Space Considerations

**Canada Drought:**
- Raw: ~1 GB (325 GeoJSON files)
- Converted: ~200-400 MB (parquet compression)
- After cleanup: Delete raw GeoJSON files
- Net impact: +200-400 MB

**Canada Fires:**
- Raw: 789 MB (mostly polygons 743 MB)
- Converted points: ~50-100 MB
- Converted polygons: ~300-400 MB (if included)
- After cleanup: Delete raw shapefiles
- Net impact: +350-500 MB (if including polygons)

**Total after processing both:**
- Net disk usage: +550-900 MB
- Can delete ~1.8 GB of raw data
- Recovery: ~900 MB disk space saved

---

## 6. Global Drought Gap

**Current state:** Only USA and (soon) Canada have drought coverage.

**Future enhancement ideas:**
1. **Mexico Drought Monitor:** Does it exist? Research needed.
2. **European Drought Observatory:** EU has drought monitoring - check if downloadable
3. **Global Drought Monitor:** Research UN/WMO global drought products

**For now:** Focus on Canada to complete North America coverage.

---

## Recommendations Summary

### Process Both Canada Datasets

**Canada Drought:**
- MUST PROCESS: We have zero global drought coverage
- Creates North America drought map (USA + CAN)
- Same D0-D4 scale as USA for easy integration
- Relatively small (~400 MB after conversion)

**Canada Fires:**
- MUST PROCESS: Canada severely underrepresented in global data
- Global data has only 38 Canada fires in 2024 (missing thousands)
- CNFDB provides ground-truth official records
- Complements satellite data with agency-reported fires

### Converter Scripts Needed

1. `data_converters/converters/convert_canada_drought.py`
2. `data_converters/converters/convert_canada_fires.py`

### Output Locations

- `countries/CAN/drought/CAN.parquet`
- `countries/CAN/drought/metadata.json`
- `countries/CAN/wildfires/events.parquet`
- `countries/CAN/wildfires/metadata.json`

---

*Analysis complete. Both Canada datasets add significant value and should be processed.*
