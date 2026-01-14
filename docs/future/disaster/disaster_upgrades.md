# Disaster Data Upgrades

Future improvements, data quality issues, and planned features for disaster data.

---

## Data Quality Issues

### Fire Progression Incomplete Years

**Status:** 2008 only 2.6% complete, needs rerun

| Year | Progression Rows | Unique Fires | Total Fires | Coverage |
|------|------------------|--------------|-------------|----------|
| 2017 | 3.4M | 511K | 867K | 59% |
| 2016 | 2.2M | 527K | 911K | 58% |
| 2015-2009 | ~2.3M each | ~550K each | ~940K each | ~58% |
| **2008** | **104K** | **26K** | **996K** | **2.6%** |

**Action:** Rerun fire progression extraction for 2008.

### Fire loc_id Enrichment - Sibling Level Issues

**Problem:** Cross-border fires get bubbled up to country level using sibling rule.

| sibling_level | Count (2024) | Issue |
|---------------|--------------|-------|
| 0 | 719 (0.7%) | No geography - crossed countries |
| 1 | 2,483 (2.3%) | Country-level only |
| 2 | 4,251 (4.0%) | State/province level |
| 3 | 99,162 (93%) | County/district level (good) |

**Example:** A fire crossing USA-Canada border gets `parent_loc_id=""` which means queries like "fires in USA" or "fires in Canada" would miss it, but "all fires globally" would incorrectly weight it as affecting both entire countries.

**Solution:** Create fire_aggregates table (see below).

### Floods loc_id - All NULL

**File:** `global/floods/events.parquet`
**Status:** loc_id column exists but all 4,825 values are NULL

**Action:** Run point-in-polygon enrichment (in progress, ~20 hours).

---

## Planned Data Products

### Fire Aggregates Table

**Inspiration:** US Wildfire Risk product from USFS

Instead of one loc_id per fire (which forces sibling-rule bubbling), create a many-to-many relationship showing which admin regions each fire actually touched.

**Current structure (problematic):**
```
fires_2024_enriched.parquet
  event_id: 62400
  parent_loc_id: ""           # Problem: fire crossed borders
  area_km2: 1024.7
```

**New structure (fire_aggregates):**
```
fire_aggregates_2024.parquet
  event_id  | loc_id    | area_km2_in_region | pct_of_fire
  62400     | SSD-UE    | 412.3              | 40.2%
  62400     | SSD-EQ    | 287.1              | 28.0%
  62400     | SSD-CE    | 325.3              | 31.8%
```

**Benefits:**
- "Fires in South Sudan Upper Nile" -> returns fire 62400
- "Total fire area in SSD-UE" -> 412.3 km2 (not full 1024 km2)
- Cross-border fires properly split by actual area affected

**Generator approach:**
1. Load fire perimeter geometry
2. Intersect with admin2/3 polygons
3. Calculate area in each region
4. Output one row per (fire, region) pair

### Global Fire Risk Product

**Inspiration:** US Wildfire Risk (`countries/USA/wildfire_risk/USA.parquet`)

US product structure:
```
loc_id: USA-AL-1001
burn_probability_national_percentile: 50.5
risk_national_percentile: 48.1
pct_buildings_direct_exposure: 68.5%
```

**Proposed global structure:**
```
fire_risk_by_region.parquet
  loc_id: "BRA-AM"                    # Amazon state
  fires_per_year_avg: 12,450          # Historical average
  total_area_burned_km2: 45,230       # Cumulative 2002-2024
  burn_probability: 0.89              # Years with fires / total years
  area_burned_percentile: 95.2        # vs other admin1 regions
  fire_frequency_percentile: 98.1     # vs other admin1 regions
  population_at_risk: 4,200,000       # From demographics
  years_analyzed: 22                  # 2002-2024
```

**Enables queries:**
- "Which regions have highest fire risk?"
- "Compare fire frequency across Brazilian states"
- "Population exposed to high fire areas"

**Dependencies:**
- Fire loc_id enrichment complete
- Fire aggregates table (for accurate per-region stats)

### International Risk Frameworks (Research)

Survey of global disaster risk aggregation methodologies to inform our schema design.

#### INFORM Risk Index (UN/EU)

**Source:** [DRMKC INFORM](https://drmkc.jrc.ec.europa.eu/inform-index)

The INFORM Global Risk Index (GRI) is the primary international standard, used by UN agencies, EU, and NGOs.

**Three Dimensions:**
1. **Hazard & Exposure** - Natural + human hazards, population exposed
2. **Vulnerability** - Socioeconomic factors, health, development
3. **Lack of Coping Capacity** - Institutional strength, infrastructure

**Formula:** `Risk = (H&E)^(1/3) x (V)^(1/3) x (LCC)^(1/3)`
- Geometric mean ensures risk = 0 if any dimension = 0
- Score range: 0-10 (higher = more risk)
- 80 indicators across 54 components
- Categories: Very Low / Low / Medium / High / Very High

**Subnational Models:** [INFORM Subnational](https://drmkc.jrc.ec.europa.eu/inform-index/INFORM-Subnational-risk) applies same methodology at state/province level.

#### WorldRiskIndex (Bundnis Entwicklung Hilft)

**Source:** [HDX WorldRiskIndex](https://data.humdata.org/dataset/worldriskindex)

Alternative composite index covering 193 countries.

**Two Components:**
1. **Exposure** - Population affected by earthquakes, tsunamis, cyclones, floods, droughts, sea level rise (3 intensity levels per hazard)
2. **Vulnerability** - Three sub-components:
   - Susceptibility
   - Lack of coping capacities
   - Lack of adaptive capacities

**Methodology:**
- 100+ indicators (revised 2022, up from 27 in 2011)
- Retrospective updates maintain 10-year trend validity
- Annual releases with longitudinal dataset

#### EU DRMKC Risk Data Hub

**Source:** [DRMKC Risk Data Hub](https://drmkc.jrc.ec.europa.eu/risk-data-hub)

Pan-European multi-hazard risk assessment at NUTS3 level.

**Approach:**
- Meta-analysis aggregating single-hazard hotspots
- Stouffer's method for combining statistical significance
- Z-scores and p-values for cluster identification
- Spearman correlation validation against empirical data

**Key innovation:** Identifies multi-hazard exposed regions by combining statistically significant single-hazard hotspots.

#### Japan Prefecture-Level System

**Source:** [Japan Disaster Management](https://www.bousai.go.jp/en/)

Decentralized model with national coordination.

**Structure:**
- Basic Disaster Management Plan (national)
- Local Disaster Management Plans (prefecture/municipal)
- Hazard maps at municipality level showing extent + magnitude
- Prefecture-aggregated hazard zone data

**Notable:** Extensive open data on predicted exposure for various hazard types.

#### Australia QERMF

**Source:** [Queensland Emergency Risk Management Framework](https://www.disaster.qld.gov.au)

Based on ISO 31000 and Sendai Framework.

**Approach:**
- Multidisciplinary risk assessment
- Operational geospatial intelligence for exposure/vulnerability
- National Emergency Risk Assessment Guidelines (NERAG)
- Prioritization of risks with greatest potential effects

#### Key Takeaways for Our Schema

| Framework | Key Innovation | Adopt? |
|-----------|---------------|--------|
| INFORM | Geometric mean (risk=0 if any dimension=0) | Consider for composite scores |
| INFORM | 0-10 scale, 5 risk categories | YES - adopt scale |
| WorldRiskIndex | Multi-intensity exposure (3 levels per hazard) | YES - severity bands |
| DRMKC | Multi-hazard hotspot identification | Future - combined risk |
| Japan | Hazard maps with extent + magnitude | Already doing this |
| QERMF | ISO 31000 alignment | Consider for documentation |

**Recommendation:** Adopt INFORM-style 0-10 scale with 5 categories. Use geometric mean for composite scores. Add exposure intensity levels like WorldRiskIndex.

---

### Unified Aggregate Risk Schema

**Goal:** Create a consistent schema that works for ALL disaster types globally, inspired by existing US products and international frameworks (INFORM, WorldRiskIndex).

#### Existing US Aggregate Patterns

| Product | Key Fields | Pattern |
|---------|-----------|---------|
| **FEMA NRI** | `{HAZARD}_EVNTS`, `{HAZARD}_AFREQ`, `{HAZARD}_EALT`, `{HAZARD}_RISKS`, `{HAZARD}_RISKR` | Event count, annual frequency, expected loss, risk score+rating |
| **Wildfire Risk** | `burn_probability_*_percentile`, `risk_*_percentile`, `pct_buildings_*_exposure` | Percentiles (state/national), exposure categories |
| **FEMA Disasters** | `total_declarations`, `{type}_count`, `decade` | Event counts by type, decade for trends |
| **NOAA Storms** | `events_{type}`, `deaths_direct`, `damage_property_usd` | Event counts, casualties, damage |
| **Drought Monitor** | `max/avg_drought_severity`, `weeks_d0-d4`, `pct_year_in_drought` | Severity levels, time-in-state |

#### Proposed Universal Schema

Every disaster aggregate file uses this common structure:

```
hazard_aggregate_{year}.parquet

  # Identity
  loc_id: string              # Any admin level (country, state, county)
  year: int32                 # Aggregate year
  hazard_type: string         # earthquake, wildfire, flood, tornado, etc.

  # Event Counts
  event_count: int32          # Total events in region+year
  annual_frequency: float     # Events/year (for multi-year averages)

  # Severity Metrics (hazard-specific scale normalized to 0-1)
  max_severity: float         # Highest severity event
  avg_severity: float         # Mean severity of all events
  severity_percentile: float  # Rank vs other regions (0-100)

  # Area Metrics (for spatial hazards: fire, flood, drought)
  total_area_km2: float       # Total affected area
  max_area_km2: float         # Largest single event
  pct_region_affected: float  # Affected area / region area

  # Impact Metrics
  deaths: int32               # Total fatalities
  injuries: int32             # Total injuries
  damage_usd: float           # Property + infrastructure damage
  damage_percentile: float    # Rank vs other regions (0-100)

  # Time Metrics (for duration hazards: drought, flood, fire)
  total_days: int32           # Days of active events
  max_duration_days: int32    # Longest single event

  # Risk Composite (INFORM-style, 0-10 scale)
  risk_score: float           # Composite risk (0-10, higher = more risk)
  risk_rating: string         # Very Low (<2) / Low (2-3.5) / Medium (3.5-5) / High (5-6.5) / Very High (>6.5)

  # Exposure Intensity (WorldRiskIndex-style)
  exposure_low: int32         # Population in low-intensity zone
  exposure_medium: int32      # Population in medium-intensity zone
  exposure_high: int32        # Population in high-intensity zone
```

#### Severity Mapping by Hazard Type

| Hazard | Raw Scale | Normalized (0-1) |
|--------|-----------|------------------|
| Earthquake | Magnitude 0-10 | mag/10 |
| Tornado | EF0-EF5 | scale/5 |
| Hurricane | Cat 1-5 | (cat-1)/4 |
| Wildfire | Area-based | log(area_km2)/log(max_area) |
| Flood | Severity 1-3 | (severity-1)/2 |
| Drought | D0-D4 | level/4 |
| Volcano | VEI 0-8 | vei/8 |
| Tsunami | Wave height | log(height_m)/log(max_height) |

#### Risk Score Calculation (INFORM-inspired)

Composite risk score combines three factors using geometric mean:

```
risk_score = 10 * (frequency_norm * severity_norm * impact_norm)^(1/3)

Where:
  frequency_norm = min(1, event_count / historical_max_events)
  severity_norm  = max_severity (already 0-1 from table above)
  impact_norm    = min(1, (deaths + injuries/10 + damage_usd/1M) / historical_max_impact)
```

**Risk Rating Thresholds (INFORM-style):**

| Score Range | Rating | Color |
|-------------|--------|-------|
| 0.0 - 2.0 | Very Low | Green |
| 2.0 - 3.5 | Low | Yellow-Green |
| 3.5 - 5.0 | Medium | Yellow |
| 5.0 - 6.5 | High | Orange |
| 6.5 - 10.0 | Very High | Red |

**Note:** For hazards without impact data (deaths/damage), use frequency x severity only: `risk_score = 10 * (frequency_norm * severity_norm)^(1/2)`

#### Admin Level Strategy

Generate aggregates at multiple admin levels, with admin2 as the primary level.

| Level | Description | Use Case | Example loc_ids |
|-------|-------------|----------|-----------------|
| admin2 | County/district/municipality | Primary - local risk assessment | USA-TX-48201, JPN-AI-01100 |
| admin1 | State/province/prefecture | Regional comparison | USA-TX, JPN-AI, BRA-AM |
| admin0 | Country | Global rankings | USA, JPN, BRA |

**Rationale:**
- admin2 aligns with EU DRMKC (NUTS3 level) and Japan municipal planning
- Matches existing US data (FEMA NRI, NOAA storms at county level)
- We have reliable admin2 geometry globally
- admin1/admin0 are simple rollups (sum events, max severity, recalculate percentiles)

**Coverage check (from geometry files):**
- USA: 35,808 admin2 counties
- Germany: 381 admin2 (NUTS3)
- Japan: 1,805 admin2 municipalities
- Brazil: 5,572 admin2 municipalities
- Australia: 564 admin2 LGAs

#### Time Window Strategy

Generate aggregates for multiple time windows to balance recency with statistical validity.

| Window | Years | Primary Use | Rationale |
|--------|-------|-------------|-----------|
| **10-year** | 2015-2024 | Primary risk score | Reflects current climate trends (WorldRiskIndex standard) |
| **20-year** | 2005-2024 | Rare event statistics | Statistical significance for earthquakes, volcanoes |
| **Annual** | Single year | Trend analysis | Year-over-year comparison |
| **Full historical** | All available | Research/baselines | Maximum sample size |

**Risk score calculation uses 10-year window by default:**
- Recent enough to capture accelerating climate trends
- Long enough for statistical validity
- Matches WorldRiskIndex methodology

**For rare events (earthquakes, volcanoes), use 20-year window:**
- Major earthquakes may not occur in every 10-year period
- Volcanic eruptions are inherently rare
- Longer window prevents false "zero risk" scores

#### File Organization

```
global/aggregates/
  earthquakes/
    earthquake_aggregate_2024_admin2.parquet    # Single year, admin2
    earthquake_aggregate_2024_admin1.parquet    # Single year, admin1
    earthquake_aggregate_10yr_admin2.parquet    # 10-year rolling (2015-2024)
    earthquake_aggregate_20yr_admin2.parquet    # 20-year rolling (2005-2024)
  wildfires/
    wildfire_aggregate_2024_admin2.parquet
    wildfire_aggregate_10yr_admin2.parquet
    ...
  combined/
    all_hazards_10yr_admin2.parquet             # Multi-hazard risk by region

countries/USA/aggregates/
  tornado_aggregate_2024_admin2.parquet         # US-specific (county level)
  tornado_aggregate_10yr_admin2.parquet
  ...
```

#### Query Examples

With this unified schema:

```sql
-- "Which counties have highest earthquake risk?"
SELECT loc_id, risk_score, event_count, max_severity
FROM earthquake_aggregate_2024
WHERE loc_id LIKE 'USA-%'
ORDER BY risk_score DESC
LIMIT 10

-- "Compare wildfire impact across Brazilian states"
SELECT loc_id, total_area_km2, damage_usd, risk_rating
FROM wildfire_aggregate_2024
WHERE loc_id LIKE 'BRA-%'

-- "All hazards affecting Texas in 2024"
SELECT hazard_type, event_count, damage_usd, risk_score
FROM all_hazards_aggregate_2024
WHERE loc_id LIKE 'USA-TX%'
```

#### Generator Script Pattern

Each hazard converter outputs to this schema:

```python
def generate_aggregate(events_df, year, hazard_type):
    """Convert event-level data to aggregate schema."""
    agg = events_df.groupby('loc_id').agg({
        'event_id': 'count',
        'severity': ['max', 'mean'],
        'area_km2': ['sum', 'max'],
        'deaths': 'sum',
        'injuries': 'sum',
        'damage_usd': 'sum',
        'duration_days': ['sum', 'max']
    })

    agg['year'] = year
    agg['hazard_type'] = hazard_type
    agg['risk_score'] = calculate_risk_composite(agg)
    agg['risk_rating'] = risk_score_to_rating(agg['risk_score'])

    return agg
```

**Dependencies:**
- loc_id enrichment for all hazards
- Event-level data with severity/area/impact fields

#### Field Availability by Hazard

Current event-level data coverage for aggregate generation:

| Hazard | loc_id | Severity | Area | Deaths | Damage | Duration |
|--------|--------|----------|------|--------|--------|----------|
| Earthquakes | country only | magnitude | felt_radius | - | - | - |
| Floods | NULL (in progress) | severity 1-3 | area_km2 | deaths | - | duration_days |
| Volcanoes | country only | VEI | - | - | - | duration_days |
| Tsunamis | ocean codes | max_water_height | - | deaths | damage_millions | - |
| Tropical Storms | - | max_category | - | - | - | start/end dates |
| US Tornadoes | county | EF scale | - | deaths | damage_property | - |
| US Storms (all) | county | magnitude | - | deaths/injuries | damage | - |
| Global Fires | in progress | - | area_km2 | - | - | progression |

**Gaps to fill before aggregates:**
1. Deaths/damage for earthquakes (available from NOAA significant EQ dataset)
2. Deaths/damage for volcanoes (available from Smithsonian impact data)
3. Impact data for tropical storms (landfall damage from NOAA)
4. Fire severity metric (calculated from area, intensity, progression)

---

## Data Sources to Fill Gaps

Research from EM-DAT sources and related databases that can fill our impact data gaps.

### Earthquake Deaths/Damage

**Source:** [NOAA NCEI Significant Earthquake Database](https://www.ngdc.noaa.gov/hazel/view/hazards/earthquake/search)

| Field | Description |
|-------|-------------|
| Coverage | 2150 BC to present, 5,700+ earthquakes |
| Criteria | M7.5+, 10+ deaths, $1M+ damage, or MMI X+ |
| Impact fields | deaths, injuries, houses_destroyed, houses_damaged, damage_millions |
| Download | CSV/TSV via search interface or API |

**Action:** Download and join to our USGS earthquake events on (lat, lon, date, magnitude).

### Volcano Deaths/Damage

**Source:** [NOAA NCEI Significant Volcanic Eruptions Database](https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ngdc.mgg.hazards:G10147)

| Field | Description |
|-------|-------------|
| Coverage | 4360 BC to present, 600+ significant eruptions |
| Criteria | VEI 6+, fatalities, $1M+ damage, or tsunami-generating |
| Impact fields | deaths, injuries, houses_destroyed, damage_millions |
| Links | Linked to tsunami and earthquake events |

**Action:** Download and join to our Smithsonian GVP events on volcano_id + year.

### Flood Events 2020+

**Source:** [Dartmouth Flood Observatory Active Archive](https://floodobservatory.colorado.edu/Archives/)

| Field | Description |
|-------|-------------|
| Coverage | 1985-present (active, updated continuously) |
| Our gap | We have 1985-2019 from Cloud to Street/DFO, missing 2020+ |
| Impact fields | deaths, displaced, damage (varies by event) |
| Format | Shapefiles + event database |

**Note:** Global Flood Database (Google Earth Engine) only covers 2000-2018. For 2020+, need to scrape DFO active archive or use [GloFAS](https://www.globalfloods.eu/) event triggers.

### Multi-Hazard Impact Data

**Source:** [EM-DAT - International Disaster Database](https://www.emdat.be/)

| Field | Description |
|-------|-------------|
| Coverage | 1900-present, 27,000+ disasters globally |
| Hazards | Earthquakes, floods, storms, droughts, volcanoes, wildfires, epidemics |
| Impact fields | total_deaths, injured, affected, homeless, total_damage_usd |
| Access | Free registration required, CSV download |
| Limitation | Country-level only (no subnational), threshold bias (10+ deaths or 100+ affected) |

**Best use:** Fill gaps where hazard-specific databases lack impact data. Cross-validate our counts.

### Tropical Storm Impact

**Sources for landfall damage:**

| Source | Coverage | Fields |
|--------|----------|--------|
| [NOAA Storm Events](https://www.ncdc.noaa.gov/stormevents/) | USA 1950+ | deaths, injuries, damage_property, damage_crops |
| [NOAA Billion-Dollar Disasters](https://www.ncei.noaa.gov/access/billions/) | USA 1980+ | Event totals, inflation-adjusted |
| EM-DAT | Global | deaths, damage_usd (country-level) |

**Action:** For US hurricanes, join IBTrACS storms to NOAA Storm Events on date + affected counties.

### Download Priority

| Source | Fills Gap | Effort | Priority |
|--------|-----------|--------|----------|
| NCEI Significant Earthquakes | EQ deaths/damage | Low (CSV download) | HIGH - DOWNLOADED |
| NCEI Significant Volcanoes | Volcano deaths/damage | Low (CSV download) | HIGH - DOWNLOADED |
| EM-DAT Full Export | Cross-validation, fill remaining | Medium (registration) | MEDIUM |
| DFO Active Archive 2020+ | Flood gap | Medium (scraping) | MEDIUM |
| NOAA Storm Events | Hurricane US impact | Medium (large dataset) | LOW |

---

## NOAA Impact Data Merge Strategy

Downloaded data ready for merging with our existing event databases.

### Impact Data Status by Disaster Type

**Review of existing schemas (see DISASTER_DISPLAY.md):**

| Type | Has Deaths | Has Damage | Has Cross-Links | Action Needed |
|------|-----------|------------|-----------------|---------------|
| **Tsunamis** | YES | YES | parent_event_id | None - already complete |
| **Tornadoes** | YES | YES | sequence_id | None - already complete |
| **Earthquakes** | NO | NO | aftershock only | MERGE NOAA data |
| **Volcanoes** | NO | NO | eq/tsunami IDs | MERGE NOAA data |
| **Floods** | YES | YES | - | None - already has deaths/displaced/damage_usd |
| **Hurricanes** | NO | NO | - | Future - use NOAA Storm Events for landfall impact |
| **Wildfires** | NO | NO | - | Future - no global impact database exists |

**Tsunamis already have (DISASTER_DISPLAY.md lines 192-195):**
- `deaths`, `deaths_order`, `damage_millions`, `damage_order`
- Plus runups.parquet has per-location deaths

**Tornadoes already have (DISASTER_DISPLAY.md lines 260-265):**
- `deaths_direct`, `deaths_indirect`, `injuries_direct`, `injuries_indirect`
- `damage_property`, `damage_crops`

### NOAA Significant Earthquakes (Downloaded) - MERGE REQUIRED

**Location:** `Raw data/noaa/significant_earthquakes/`
**Records:** 6,627 events (2150 BC - 2026)
**Impact coverage:** 2,373 with deaths, 657 with damage, 235 from 2020+

**NOAA columns to add to our schema:**

| Category | NOAA Columns | Target Schema Column |
|----------|--------------|---------------------|
| Deaths | `deaths`, `deathsTotal` | `deaths` (use deathsTotal for cascade totals) |
| Injuries | `injuries`, `injuriesTotal` | `injuries` |
| Missing | `missing`, `missingTotal` | `missing` |
| Damage | `damageMillionsDollars` | `damage_usd` (multiply by 1M) |
| Housing | `housesDamaged`, `housesDestroyed` | `houses_damaged`, `houses_destroyed` |
| Links | `tsunamiEventId` | Validate existing cross-links |
| Links | `volcanoEventId` | Validate existing cross-links |

**Our USGS Earthquakes current columns:**
```
event_id, event_type, timestamp, year, latitude, longitude, loc_id,
magnitude, depth_km, felt_radius_km, damage_radius_km, place,
mainshock_id, sequence_id, is_mainshock, aftershock_count
```

**New columns to add:**
```
deaths, injuries, missing, damage_usd, houses_damaged, houses_destroyed,
noaa_id, noaa_tsunami_id, noaa_volcano_id
```

**Merge strategy:**
1. Match on: `year` + `latitude` (within 0.5 deg) + `longitude` (within 0.5 deg) + `magnitude` (within 0.3)
2. Add impact fields (NULL if no match)
3. Add NOAA cross-reference IDs for link validation

**Notes:**
- NOAA uses AmountOrder codes (1-4) for rough estimates when exact numbers unknown
- `deathsTotal` includes deaths from associated tsunamis/landslides
- Match rate expected: ~90% of NOAA significant events should match USGS M5.5+
- Cross-links can validate our existing earthquake->tsunami parent_event_id system

### NOAA Significant Volcanoes (Downloaded) - MERGE REQUIRED

**Location:** `Raw data/noaa/significant_volcanoes/`
**Records:** 200 events (141 BC - 1996)
**Impact coverage:** 128 with deaths, 1 with damage

**NOAA columns to add to our schema:**

| Category | NOAA Columns | Target Schema Column |
|----------|--------------|---------------------|
| Deaths | `deaths`, `deathsTotal` | `deaths` |
| Injuries | `injuries`, `injuriesTotal` | `injuries` |
| Missing | `missing`, `missingTotal` | `missing` |
| Damage | `damageMillionsDollars` | `damage_usd` (multiply by 1M) |
| Housing | `housesDestroyed` | `houses_destroyed` |
| Agent | `agent` | `eruption_agent` (T=Tephra, L=Lava, P=Pyroclastic, etc.) |
| Links | `earthquakeEventId` | Validate earthquake_event_ids |
| Links | `tsunamiEventId` | Validate tsunami_event_ids |

**Our Smithsonian Volcanoes current columns:**
```
event_id, eruption_id, event_type, year, timestamp, end_year, end_timestamp,
duration_days, is_ongoing, latitude, longitude, loc_id, felt_radius_km,
damage_radius_km, volcano_number, volcano_name, activity_type, activity_area,
VEI, country, region, earthquake_event_ids, tsunami_event_ids
```

**New columns to add:**
```
deaths, injuries, missing, damage_usd, houses_destroyed, eruption_agent,
noaa_id, noaa_earthquake_id, noaa_tsunami_id
```

**Merge strategy:**
1. Match on: `volcanoLocationNewNum` = `volcano_number` + `year`
2. Add impact fields (NULL if no match)
3. Validate/enhance existing earthquake_event_ids, tsunami_event_ids

**Limitations:**
- Only 200 events (vs 11,079 in Smithsonian)
- Data ends 1996 (no recent events with impact data)
- Better for historical impact research than current risk

### Cross-Link Validation

NOAA provides explicit event IDs that can validate our computed cross-links:

**Current cross-linking (DISASTER_DISPLAY.md lines 363-377):**
- Tsunami `parent_event_id` links to triggering earthquake
- Volcano `earthquake_event_ids`, `tsunami_event_ids` link related events
- Computed using time/distance windows

**NOAA provides:**
- Earthquake `tsunamiEventId` - explicit link to triggered tsunami
- Earthquake `volcanoEventId` - explicit link to triggering volcano
- Volcano `earthquakeEventId` - explicit link to triggered earthquakes
- Volcano `tsunamiEventId` - explicit link to triggered tsunamis

**Validation approach:**
1. Compare NOAA explicit IDs vs our computed links
2. Add missing links found in NOAA
3. Flag conflicts for manual review

### Output Files

After merge, single global parquet files with enriched schemas:

```
global/usgs_earthquakes/events.parquet        # Enriched with impact columns
global/smithsonian_volcanoes/events.parquet   # Enriched with impact columns
```

### Next Steps

1. Create `merge_noaa_earthquake_impact.py` converter
2. Create `merge_noaa_volcano_impact.py` converter
3. Run merges to create enriched parquet files
4. Validate cross-links using NOAA IDs
5. Update aggregate generators to use impact data

### Downloader Scripts Needed

```
data_converters/downloaders/
  download_ncei_earthquakes.py      # NEW - significant EQ with impact
  download_ncei_volcanoes.py        # NEW - significant eruptions with impact
  download_emdat.py                 # NEW - multi-hazard (needs API key)
  download_dfo_floods_2020.py       # NEW - recent flood events
```

---

## Unified Impact Column Naming

Standard column names for impact data across all disaster types. The frontend popup system (disaster-popup.js) uses fallback chains to handle variations.

### Standard Column Names

| Category | Standard Column | Type | Description |
|----------|----------------|------|-------------|
| **Human Impact** | | | |
| Deaths | `deaths` | int32 | Total fatalities |
| Injuries | `injuries` | int32 | Total injuries |
| Missing | `missing` | int32 | Missing persons |
| Displaced | `displaced` | int32 | People displaced |
| **Property Impact** | | | |
| Damage | `damage_usd` | float64 | Total damage in USD |
| Houses Destroyed | `houses_destroyed` | int32 | Houses completely destroyed |
| Houses Damaged | `houses_damaged` | int32 | Houses damaged but not destroyed |
| **Spatial Impact** | | | |
| Felt Radius | `felt_radius_km` | float32 | Area where effects noticed |
| Damage Radius | `damage_radius_km` | float32 | Area with structural damage |
| Area Affected | `area_km2` | float32 | Total affected area |

### Current Column Variations by Type

| Type | Deaths | Injuries | Damage | Special |
|------|--------|----------|--------|---------|
| **Tsunamis** | `deaths` | - | `damage_millions` | `deaths_order`, `damage_order` |
| **Floods** | `deaths` | - | `damage_usd` | `displaced` |
| **Tornadoes** | `deaths_direct`, `deaths_indirect` | `injuries_direct`, `injuries_indirect` | `damage_property`, `damage_crops` | - |
| **Earthquakes** | `deaths` (new) | `injuries` (new) | `damage_usd` (new) | `houses_damaged`, `houses_destroyed` |
| **Volcanoes** | `deaths` (new) | `injuries` (new) | `damage_usd` (new) | `houses_destroyed`, `eruption_agent` |
| **Hurricanes** | - | - | - | (future: link to NOAA Storm Events) |
| **Wildfires** | - | - | - | (no global impact database) |

### Frontend Fallback Chains (disaster-popup.js)

The popup buildImpactTab() handles variations with fallback chains:

```javascript
// Deaths - handles both unified and tornado-style
const deaths = data.deaths || data.deaths_direct;

// Injuries - handles both unified and tornado-style
const injuries = data.injuries || data.injuries_direct;

// Damage - handles multiple formats
const damage = data.damage_usd || data.damage_property;
// Also checks: data.damage_millions (for tsunamis)

// Displaced - handles variations
const displaced = data.displaced || data.displaced_count;
```

### Migration Notes

**No migration needed for existing data:**
- Tornadoes: Keep `deaths_direct/indirect`, `injuries_direct/indirect`, `damage_property/crops` - popup handles these
- Tsunamis: Keep `damage_millions` - popup has special handling
- Floods: Already uses standard names

**New data uses standard names:**
- Earthquakes: Add `deaths`, `injuries`, `damage_usd` (standard)
- Volcanoes: Add `deaths`, `injuries`, `damage_usd` (standard)

**Optional future enhancement:**
- Add computed `deaths_total = deaths_direct + deaths_indirect` to tornadoes
- Convert `damage_millions` to `damage_usd` for tsunamis (multiply by 1M)

---

## US vs Global Fire Data

### Coverage Comparison

| Aspect | US MTBS | Global FIRMS |
|--------|---------|--------------|
| Years | **1984-2024** | 2002-2024 |
| Pre-2002 | **9,386 fires (exclusive)** | None |
| 2020 count | 815 | 941,872 |
| Focus | Large/significant fires | All satellite detections |
| Has loc_id | YES | Being added |
| Has names | YES ("WOOD DRAW") | NO |
| Has type | YES (Wildfire, Prescribed) | NO |

### Recommendation

**Keep both datasets:**
- US provides historical 1984-2001 (exclusive coverage)
- US has fire names for lookup ("find the Creek Fire")
- US has fire type distinction (Wildfire vs Prescribed Fire: 17K vs 9K)
- Global has comprehensive satellite coverage

### Fire Types (US only)
```
Wildfire             16,963
Prescribed Fire       8,870
Unknown               4,689
Wildland Fire Use       211
```

---

## Frontend Implementation Gaps

### From DISASTER_DISPLAY.md

**In Progress:**
- [ ] Fire progression animation (converter ready, data incomplete for 2008)
- [ ] Drought choropleth animation
- [ ] Polygon _opacity support (model-polygon.js still uses static opacity)

**Future:**
- [ ] Live data pipeline (USGS, NASA FIRMS, NOAA)
- [ ] deck.gl animation effects

### Flood Display

Currently marked as "(future)" in disaster types table:
```
| **Floods** | (future) | - | - | - | Polygon |
```

**Data status:** 4,825 events (1985-2019), needs loc_id enrichment

---

## API Endpoint Gaps

### Missing loc_id Filter Parameters

All disaster endpoints need location filtering (see chat_refactor.md Phase 5):

| Endpoint | Current Params | Missing |
|----------|---------------|---------|
| `/api/earthquakes/geojson` | year, min_magnitude | loc_id, loc_prefix |
| `/api/tornadoes/geojson` | year, min_scale | loc_id, loc_prefix |
| `/api/wildfires/geojson` | year, min_area_km2 | loc_id, loc_prefix |
| `/api/hurricanes/storms` | year, us_landfall | loc_id |
| `/api/floods/geojson` | year | loc_id |
| `/api/eruptions/geojson` | year, min_vei | loc_id |
| `/api/tsunamis/geojson` | year, cause | loc_id |

---

## Known Issues

### Volcano Prehistoric Data

Smithsonian GVP includes eruptions back to ~1280 CE which overflow pandas datetime. Only 36% have valid timestamps.

### Map Projection

Globe projection disabled due to animation interference. Uses Mercator only.

---

## Live Data Sources (Future)

| Source | API | Latency | Coverage |
|--------|-----|---------|----------|
| USGS Earthquakes | earthquake.usgs.gov | Minutes | Global M2.5+ |
| NASA FIRMS | firms.modaps.eosdis.nasa.gov | 12 hours | Global fires |
| NOAA DART Buoys | - | 15 seconds | Tsunami events |
| IOC Sea Level | - | 1 minute | Global |

---

## Data Gaps (from disaster data.md)

### Remaining Gaps

| Hazard | Current | Gap |
|--------|---------|-----|
| Floods | 1985-2019 | 2020-present (use LANCE + event triggers) |
| Heat/Cold Wave | Limited NOAA | NCEI temperature extremes |
| Pre-2000 Drought | USDM 2000+ | Palmer Drought Index |
| Coastal Flooding | Model only | Event database |

### Canada Coverage Gaps - PRIORITY

**See [CANADA_DATA_ANALYSIS.md](CANADA_DATA_ANALYSIS.md) for detailed analysis.**

| Hazard | Current Global | Canada Raw Data | Gap Impact | Action |
|--------|---------------|-----------------|------------|--------|
| **Drought** | USA only (2000-2026) | 2019-2025 monthly (1 GB) | ZERO global drought | **PROCESS** |
| **Fires** | 38 Canada fires in 2024 | CNFDB thousands (789 MB) | 99.9% missing | **PROCESS** |

**Key findings:**
- **Drought:** No global drought product exists. Canada + USA = North America coverage only.
- **Fires:** Global FIRMS has only 38 Canada fires in 2024. CNFDB (Canadian National Fire Database) has thousands of official ground-truth fires.

**Next steps:**
1. Create `convert_canada_drought.py` converter (GeoJSON → parquet)
2. Create `convert_canada_fires.py` converter (shapefile → parquet)
3. Output to `countries/CAN/drought/` and `countries/CAN/wildfires/`

### Blocked Sources

| Source | Issue |
|--------|-------|
| FEMA NFHL Flood Zones | hazards.fema.gov infrastructure down |
| DesInventar (82 countries) | Server defunct |
| Canadian Disaster Database | Interactive only, no bulk API |

---

*Last Updated: 2026-01-13*
*Added: International risk frameworks (INFORM, WorldRiskIndex, DRMKC, Japan, Australia)*
