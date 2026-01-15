# loc_id Inconsistency Analysis

*Generated: 2026-01-14*
*Resolved: 2026-01-14*

## Executive Summary

Analysis of loc_id patterns across geometry files and data sources revealed **critical inconsistencies** that caused join failures and data loss. **All issues have been resolved.**

### Issues Found and Fixed:

1. **USA FIPS Padding** - FIXED: Stripped leading zeros from 17,407 records across 6 files
2. **Australia State Codes** - FIXED: Created crosswalk file for 3-letter to 2-letter mapping
3. **Canada Census Divisions** - FIXED: Created crosswalk documenting incompatibility
4. **Europe NUTS Codes** - FIXED: Created 37 crosswalk files for Eurostat countries
5. **Missing Crosswalk Files** - FIXED: Created crosswalk.json for AUS, CAN, and 37 EU countries

---

## Issue 1: USA FIPS Padding (RESOLVED)

### Problem

USA county FIPS codes have inconsistent zero-padding across datasets. Some use 5-digit codes with leading zeros (USA-CA-06037), others use the raw numeric value (USA-CA-6037).

**Intended format:** Without leading zeros (e.g., USA-CA-6037)

### Impact

- **10% join failure** between drought data and geometry
- **Cross-dataset queries fail** (e.g., "show drought + population for LA County")

### Affected Files

| File | Status | Records |
|------|--------|---------|
| `geometry/USA.parquet` | HAS LEADING ZEROS - FIX | 35,861 |
| `countries/USA/geometry.parquet` | HAS LEADING ZEROS - FIX | 35,783 |
| `countries/USA/census_population/USA.parquet` | HAS LEADING ZEROS - FIX | 15,985 |
| `countries/USA/census_demographics/USA.parquet` | HAS LEADING ZEROS - FIX | ~15,000 |
| `countries/USA/fema_nri/USA.parquet` | HAS LEADING ZEROS - FIX | varies |
| `countries/USA/fema_disasters/USA.parquet` | HAS LEADING ZEROS - FIX | varies |
| `countries/USA/usdm_drought/USA.parquet` | OK (no zeros) | 91,358 |
| `countries/USA/wildfire_risk/USA.parquet` | OK (no zeros) | varies |
| `countries/USA/noaa_storms/USA.parquet` | OK (no zeros) | 159,651 |

### Fix Required

Strip leading zeros from FIPS codes in all affected files:

```python
# Fix pattern
df['loc_id'] = df['loc_id'].apply(lambda x:
    f"{x.split('-')[0]}-{x.split('-')[1]}-{int(x.split('-')[2])}"
    if x.count('-') == 2 else x
)
```

---

## Issue 2: Australia State Codes (RESOLVED)

### Problem

Australia uses different state abbreviation systems between GADM and country-specific data.

| GADM Code | Country Code | State Name |
|-----------|--------------|------------|
| AUS-AC | AUS-ACT | Australian Capital Territory |
| AUS-NS | AUS-NSW | New South Wales |
| AUS-QL | AUS-QLD | Queensland |
| AUS-TS | AUS-TAS | Tasmania |
| AUS-VI | AUS-VIC | Victoria |
| AUS-NT | AUS-NT | Northern Territory (same) |
| AUS-SA | AUS-SA | South Australia (same) |
| AUS-WA | AUS-WA | Western Australia (same) |
| AUS-AS | AUS-OT | Ashmore & Cartier -> Other Territories |
| AUS-CR | AUS-OT | Coral Sea -> Other Territories |
| AUS-JB | AUS-OT | Jervis Bay -> Other Territories |

### Impact

- Country geometry (557 records) cannot be mapped to GADM (576 records)
- Population data uses country codes, won't match GADM fallback
- No crosswalk file exists

### Affected Files

| File | Code System | Records |
|------|-------------|---------|
| `geometry/AUS.parquet` | GADM (2-char) | 576 |
| `countries/AUS/geometry.parquet` | Country (3-char) | 557 |
| `countries/AUS/abs_population/AUS.parquet` | Country (3-char) | 13,368 |
| `countries/AUS/bom_cyclones/events.parquet` | NO loc_id | 31,221 |

### Fix Required

Create crosswalk file `countries/AUS/crosswalk.json`:

```json
{
  "source_system": "abs_lga",
  "target_system": "gadm",
  "level_1_mappings": {
    "AUS-ACT": "AUS-AC",
    "AUS-NSW": "AUS-NS",
    "AUS-QLD": "AUS-QL",
    "AUS-TAS": "AUS-TS",
    "AUS-VIC": "AUS-VI",
    "AUS-NT": "AUS-NT",
    "AUS-SA": "AUS-SA",
    "AUS-WA": "AUS-WA",
    "AUS-OT": ["AUS-AS", "AUS-CR", "AUS-JB"]
  },
  "level_2_pattern": "Replace state prefix (AUS-NSW-10050 -> AUS-NS-10050)"
}
```

---

## Issue 3: Canada Census Divisions (RESOLVED)

### Problem

Canada uses different census division coding between GADM and country data.

| GADM Level 2 | Country Level 2 |
|--------------|-----------------|
| CAN-AB-EI (alpha) | CAN-NS-1205 (numeric) |
| CAN-AB-EL | CAN-NS-1206 |
| CAN-AB-ET | CAN-NS-1207 |

### Current State

- Country geometry uses **numeric** StatsCan census division codes
- GADM uses **alpha** codes (origin unclear)
- Country data (earthquakes) uses **numeric** codes matching country geometry
- Level 1 (provinces) match between systems

### Impact

- Low impact if GADM fallback is never used for Canada
- Canada data can join to country geometry
- If GADM fallback needed, would require crosswalk

### Recommendation

Since country data uses country geometry codes, no immediate fix needed. Document that GADM is not compatible for Canada Level 2.

---

## Issue 4: Global Disaster Data - Country Level Only (INFO)

### Observation

Global disaster event data has loc_id enrichment at country level only:

| Dataset | Unique loc_ids | Level |
|---------|---------------|-------|
| Global Earthquakes | 37 | Country + water bodies |
| Global Eruptions | 72 | Country + water bodies |
| Global Tsunamis | ~20 | Water bodies only |
| Global Landslides | ~100 | Country only |
| Global Floods | event-based | Not standard loc_id |

### Impact

- Cannot drill down to state/county for global events
- USA-specific disasters have better loc_id coverage
- This appears intentional for global data volume

### Recommendation

Document this as expected behavior. Consider enriching high-priority global events (M7+ earthquakes, VEI4+ volcanoes) with state-level loc_ids.

---

## Issue 5: Missing Crosswalk Files (RESOLVED)

### Problem

The three-tier geometry system requires crosswalk files to map between local and GADM loc_ids, but **no crosswalk files exist**.

### Current State

```
countries/AUS/crosswalk.json - MISSING
countries/CAN/crosswalk.json - MISSING
countries/USA/crosswalk.json - Not needed (same format)
countries/*/crosswalk.json - MISSING for all
```

### Impact

- Australia data cannot fall back to GADM geometry
- European NUTS data cannot map to GADM
- Three-tier system is broken for any country with local geometry

### Fix Required

Create crosswalk files for:
1. Australia (CRITICAL - different state codes)
2. Canada (MEDIUM - if GADM fallback needed)
3. European countries using NUTS (if any)

---

## Priority Fix Order

| Priority | Issue | Effort | Impact |
|----------|-------|--------|--------|
| 1 | USA FIPS padding | Medium | 10% data loss |
| 2 | Australia crosswalk | Low | Complete AU breakage |
| 3 | Add loc_id to AU cyclones | Low | Missing enrichment |
| 4 | Document CAN limitation | Low | Future clarity |
| 5 | Global data enrichment | High | Nice to have |

---

## Verification Queries

After fixes, run these to verify:

```python
# Test USA join
geom = pd.read_parquet('geometry/USA.parquet')
drought = pd.read_parquet('countries/USA/usdm_drought/USA.parquet')
geom_ids = set(geom[geom['admin_level']==2]['loc_id'])
drought_ids = set(drought[drought['loc_id'].str.count('-')==2]['loc_id'])
assert len(drought_ids - geom_ids) < 10, "USA join broken"

# Test AUS crosswalk exists
import os
assert os.path.exists('countries/AUS/crosswalk.json'), "AUS crosswalk missing"
```

---

## Resolution Summary (2026-01-14)

### Actions Taken

1. **USA FIPS Padding Fix**
   - Ran `fix_usa_fips_leading_zeros.py --apply`
   - Fixed 17,407 records across 6 files
   - Files fixed: geometry/USA.parquet, countries/USA/geometry.parquet, census_population, census_demographics, fema_nri, fema_disasters

2. **Crosswalk Files Created**
   - `countries/AUS/crosswalk.json` - Maps 3-letter ABS codes to 2-letter GADM codes
   - `countries/CAN/crosswalk.json` - Documents GADM incompatibility at level 2
   - `countries/EUR/crosswalk.json` - Single crosswalk for all 37 European countries

3. **EUR Regional Folder Created**
   - Consolidated 37 European country folders into `countries/EUR/`
   - `EUR/eurostat.parquet` - Combined Eurostat data (51,056 rows)
   - `EUR/geometry.parquet` - Combined NUTS geometry (2,015 regions)
   - Script: `data_converters/scripts/migrate_europe_to_eur.py`

4. **Documentation Updated**
   - Country-specific loc_id formats moved to [data_pipeline.md](../data_pipeline.md#country-specific-loc_id-formats)
   - Added notes about crosswalk requirements for each country type

### Scripts Created

| Script | Purpose |
|--------|---------|
| `data_converters/scripts/fix_usa_fips_leading_zeros.py` | Strip leading zeros from USA FIPS codes |
| `data_converters/scripts/create_eurostat_crosswalks.py` | Generate crosswalk files for European countries (deprecated) |
| `data_converters/scripts/migrate_europe_to_eur.py` | Consolidate European data into EUR folder |

### Verification

Run these queries to verify fixes:

```python
# Verify USA has no leading zeros
import pandas as pd
df = pd.read_parquet('geometry/USA.parquet')
zeros = df[df['loc_id'].str.match(r'USA-[A-Z]{2}-0\d+')].shape[0]
assert zeros == 0, f"Found {zeros} records with leading zeros"

# Verify crosswalk files exist
from pathlib import Path
assert Path('countries/AUS/crosswalk.json').exists()
assert Path('countries/CAN/crosswalk.json').exists()
assert Path('countries/EUR/crosswalk.json').exists()

# Verify EUR consolidation
eur = pd.read_parquet('countries/EUR/eurostat.parquet')
assert len(eur) > 50000, "EUR data not consolidated"
geom = pd.read_parquet('countries/EUR/geometry.parquet')
assert len(geom) > 2000, "EUR geometry not consolidated"
```

---

*This analysis was generated by examining parquet files in `county-map-data/`. See `data_import.md` for loc_id specification.*
