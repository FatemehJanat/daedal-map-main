# Raw Data Cleanup Status
*Created: 2026-01-13*

## Purpose

This document tracks which raw data files have been processed into the global/countries directories and can be safely deleted to save disk space.

---

## Processed Raw Data (Can be Deleted)

These raw data sources have been converted to parquet format and are in production use. The raw files can be deleted, but source URLs are documented for re-download if needed.

### Global Disaster Data

| Raw Data Location | Processed Location | Size | Can Delete? |
|-------------------|-------------------|------|-------------|
| `Raw data/desinventar/` | `global/desinventar/` | Multiple ZIPs | YES - Keep metadata.json |
| `Raw data/pager_cat/` | `global/pager_cat/` | 31 MB | YES |
| `Raw data/nasa_landslides/` | `global/nasa_landslides/` | 3.4 MB | YES |
| `Raw data/reliefweb/` | `global/reliefweb_disasters/` | Empty folder | YES |
| `Raw data/flood_events/` + `Raw data/gfd/` | `global/floods/` | ~2 MB | YES |
| `Raw data/imported/eurostat/` | `global/eurostat/` | ~6 MB | YES |

### Country-Specific Data

| Raw Data Location | Processed Location | Size | Can Delete? |
|-------------------|-------------------|------|-------------|
| `Raw data/imported/canada/eqarchive-en.csv` | `countries/CAN/nrcan_earthquakes/` | 12 MB | YES |
| `Raw data/imported/australia/IDCKMSTM0S.csv` | `countries/AUS/bom_cyclones/` | 7.6 MB | YES |

### Source Documentation (Keep These)

**Do NOT delete these JSON files** - they document sources for re-download:
- `Raw data/desinventar/desinventar_metadata.json`
- `Raw data/imported/canada/canada_earthquakes_metadata.json`
- `Raw data/imported/australia/australia_cyclones_metadata.json`

---

## Unprocessed Raw Data (Needs Decision)

These raw data sources exist but have NOT been converted yet. Decide whether to process or delete.

### Canada

| Source | Location | Size | Status | Recommendation |
|--------|----------|------|--------|----------------|
| Canada Fire (CNFDB) | `Raw data/imported/canada/cnfdb/` | 789 MB | Not processed | **PROCESS - CRITICAL GAP** |
| Canada Drought | `Raw data/imported/canada/drought/` | 1.0 GB | Not processed | **PROCESS - NO GLOBAL DROUGHT** |

**See [CANADA_DATA_ANALYSIS.md](CANADA_DATA_ANALYSIS.md) for detailed analysis.**

**Key findings:**
- **Drought:** We have ZERO global drought data. Only USA (2000-2026). Canada adds 2019-2025 to create North America coverage.
- **Fires:** Canada severely underrepresented in global data (only 38 fires in 2024!). CNFDB has thousands of fires from official sources.

**Notes:**
- Canada Fire: Canadian National Fire Database, likely has 1900s-2024 fire data
- Canada Drought: May complement or overlap with existing drought data

### Other Sources

| Source | Location | Size | Status | Recommendation |
|--------|----------|------|--------|----------------|
| EPA Air Quality | `Raw data/imported/epa_aqs/` | 2.8 MB | Not processed | DECIDE - out of disaster scope? |
| EIA Energy | `Raw data/eia/` | 1.4 GB | Not processed | DECIDE - out of disaster scope? |
| HDX/EM-DAT | `Raw data/imported/hdx/` | 390 KB | Not processed | CHECK - may overlap with DesInventar |
| Canadian Disaster DB | `Raw data/imported/canada/cdd_disasters.csv` | Small | Not processed | REVIEW - manual download limitation noted |

---

## Disk Space Summary

### Can Recover (if delete processed raw data):
- Desinventar ZIPs: ~50-100 MB (multiple country exports)
- PAGER-CAT: 31 MB
- NASA Landslides: 3.4 MB
- Eurostat: 6 MB
- Flood events: 2 MB
- Canada/Australia CSVs: 20 MB
- **Total: ~115-150 MB** (not including reliefweb which is already empty)

### Unprocessed (decision needed):
- Canada Fire: 789 MB
- Canada Drought: 1.0 GB
- EIA Energy: 1.4 GB
- EPA Air Quality: 2.8 MB
- HDX/EM-DAT: 390 KB
- **Total: ~3.2 GB**

---

## Recommendations

### Immediate Actions

1. **Delete processed raw data** (~150 MB savings)
   - Keep metadata JSON files
   - Delete all ZIPs and CSVs that have been converted

2. **Review Canada Fire** (789 MB)
   - Check if this overlaps with global wildfires data
   - If unique, create converter for countries/CAN/wildfires/
   - If redundant, delete

3. **Review EIA/EPA** (1.4 GB)
   - These may be out of scope for disaster data
   - Move to separate "economic" or "environmental" raw data folder
   - Or delete if not needed for the project

4. **Delete HDX/EM-DAT raw** (390 KB)
   - DesInventar already provides multi-hazard data
   - EM-DAT has licensing issues noted in docs
   - Already have better sources

### Source Re-Download Instructions

If you need to re-download any deleted raw data:

**DesInventar:**
- Manual download from: https://www.desinventar.net/DesInventar/download.jsp
- Click country name, download ZIP
- Already documented in GLOBAL_DATA_STATUS.md

**PAGER-CAT:**
- Download from: https://www.sciencebase.gov/catalog/item/5bc730dde4b0fc368ebcad8a
- File: pagercat_2008_06.mat

**NASA Landslides:**
- Download from: https://data.humdata.org/dataset/global-landslide-catalogue-nasa
- File: global_landslide_catalog_NASA.zip (shapefile)

**Flood Data:**
- Global Flood Database: https://global-flood-database.cloudtostreet.ai/
- Dartmouth Flood Observatory: https://floodobservatory.colorado.edu/Archives/

**Eurostat:**
- Download from: https://ec.europa.eu/eurostat/
- Multiple indicators downloaded

**Canada Earthquakes:**
- Download from: https://earthquakescanada.nrcan.gc.ca/
- CSV export of historical earthquakes

**Australia Cyclones:**
- Download from: http://www.bom.gov.au/cyclone/history/
- CSV export: IDCKMSTM0S.csv

---

## Next Steps

1. Update [disaster data.md](disaster data.md) to move processed raw data to "Converted" status
2. Delete processed raw data files (keep metadata JSONs)
3. Process or delete unprocessed raw data based on project scope
4. Update download scripts documentation with re-download instructions

---

*This document helps manage disk space and track data processing status.*
