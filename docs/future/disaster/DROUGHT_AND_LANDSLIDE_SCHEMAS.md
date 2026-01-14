# Drought and Landslide Schemas
*Created: 2026-01-13*

## Purpose

Define schemas for Drought and Landslide disaster types to integrate them into the disaster display system.

---

## Drought

### Display Model: Choropleth (Animated)

Drought uses a choropleth (shaded region) display model with temporal animation showing how drought expands/contracts over time.

### Two Data Products

**1. Temporal Snapshots** (for animation)
- Monthly or weekly drought area polygons
- Colored by severity level (D0-D4)
- Enables animated choropleth showing drought evolution

**2. Yearly Aggregates** (for analysis)
- County/province-level statistics per year
- Weeks in each severity level
- Percentage of year in drought

### Schema: Drought Snapshots (Canada)

**File:** `countries/CAN/drought/snapshots.parquet`

Choropleth-style temporal drought data for animation.

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `snapshot_id` | string | Yes | Unique identifier: `CAN-{YYYYMM}-{severity}` (e.g., `CAN-202107-D2`) |
| `timestamp` | datetime | Yes | First day of month (e.g., 2021-07-01) |
| `year` | int32 | Yes | Year (for filtering) |
| `month` | int32 | Yes | Month number (1-12) |
| `severity` | string | Yes | Drought severity level: `D0`, `D1`, `D2`, `D3`, `D4` |
| `severity_code` | int32 | Yes | Numeric code: 0-4 |
| `severity_name` | string | Yes | Full name: `Abnormally Dry`, `Moderate`, `Severe`, `Extreme`, `Exceptional` |
| `geometry` | string | Yes | GeoJSON polygon(s) of drought-affected area |
| `area_km2` | float32 | No | Total affected area in km2 |
| `iso3` | string | Yes | Country code: `CAN` |
| `provinces_affected` | string | No | Comma-separated province codes (e.g., `AB,SK,MB`) |

**Severity Scale (D0-D4):**

| Code | Level | Color | Description |
|------|-------|-------|-------------|
| D0 | Abnormally Dry | Yellow (#FFFFE0) | Going into/coming out of drought |
| D1 | Moderate Drought | Tan (#FCD37F) | Some crop/pasture damage |
| D2 | Severe Drought | Orange (#FFAA00) | Crop/pasture losses, water shortages |
| D3 | Extreme Drought | Red (#E60000) | Major crop/pasture losses |
| D4 | Exceptional Drought | Dark Red (#730000) | Exceptional/widespread losses |

**Example records:**
```
snapshot_id        timestamp     year  month  severity  geometry                area_km2
CAN-202107-D0      2021-07-01    2021  7      D0        {"type":"MultiPolygon"} 1250000
CAN-202107-D1      2021-07-01    2021  7      D1        {"type":"MultiPolygon"} 890000
CAN-202107-D2      2021-07-01    2021  7      D2        {"type":"MultiPolygon"} 340000
```

**Choropleth Animation:**
1. Load all snapshots for selected year
2. Group by month
3. Display severity polygons as colored overlay
4. Animate month-by-month showing drought expansion/contraction

### Schema: Drought Aggregates (USA - Existing)

**File:** `countries/USA/usdm_drought/USA.parquet`

County-level yearly statistics (already exists).

| Column | Type | Description |
|--------|------|-------------|
| `loc_id` | string | County/state loc_id (e.g., `USA-CA-037`) |
| `year` | int32 | Year |
| `max_drought_severity` | float32 | Maximum severity reached (weighted) |
| `avg_drought_severity` | float32 | Average severity (weighted) |
| `weeks_in_drought` | int32 | Total weeks with any drought (D0+) |
| `weeks_d0` | int32 | Weeks at D0 level |
| `weeks_d1` | int32 | Weeks at D1 level |
| `weeks_d2` | int32 | Weeks at D2 level |
| `weeks_d3` | int32 | Weeks at D3 level |
| `weeks_d4` | int32 | Weeks at D4 level |
| `pct_year_in_drought` | float32 | Percentage of year in drought |
| `pct_year_severe` | float32 | Percentage of year in severe+ (D2+) |
| `total_weeks` | int32 | Total weeks in year (52-53) |

### Future Enhancement: USA Drought Snapshots

To enable animated choropleth for USA (matching Canada), create:

**File:** `countries/USA/usdm_drought/snapshots.parquet`

Weekly drought snapshots from USDM weekly shapefiles. Same schema as Canada snapshots but with weekly instead of monthly timestamps.

**Implementation:**
- Download USDM weekly shapefiles from https://droughtmonitor.unl.edu/Data/Shapefiles.aspx
- Extract D0-D4 polygons per week
- Convert to parquet with snapshot schema above
- Enables side-by-side animated choropleth for USA + Canada

---

## Landslides

### Display Model: Point + Radius

Landslides use point+radius display like earthquakes and volcanoes.

**Unified Landslide Catalog:**
- Merged from DesInventar, NASA GLC, and NOAA Debris Flows
- 45,483 events from 160 countries, 1760-2025
- See [disaster data.md](disaster data.md#unified-landslide-catalog) for source breakdown

### Schema: Landslide Events

**File:** `global/landslides/events.parquet` (45,483 events)

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| **Core Event Columns** | | | |
| `event_id` | string | Yes | Unique identifier (e.g., `GLC-2017-0142`, `DI-COL-1987-032`) |
| `timestamp` | datetime64 | Yes | Event time (UTC, ISO 8601) |
| `year` | int32 | Yes | Event year (for filtering) |
| `latitude` | float64 | Yes | Event latitude (WGS84) |
| `longitude` | float64 | Yes | Event longitude (WGS84) |
| `event_type` | string | Yes | Always `landslide` |
| `loc_id` | string | Yes | Location code (country-province-district) |
| `parent_loc_id` | string | No | Parent admin unit |
| `iso3` | string | Yes | Country code (e.g., `USA`, `COL`, `NPL`) |
| **Landslide Characteristics** | | | |
| `landslide_type` | string | No | Type: `landslide`, `mudslide`, `debris_flow`, `rockfall`, `avalanche` |
| `landslide_size` | string | No | Size category: `small`, `medium`, `large`, `catastrophic` |
| `trigger` | string | No | Triggering event: `rainfall`, `earthquake`, `volcanic`, `snowmelt`, `unknown` |
| `area_km2` | float32 | No | Affected area in km2 |
| `volume_m3` | float32 | No | Volume of displaced material (cubic meters) |
| `runout_distance_m` | float32 | No | Distance traveled (meters) |
| `felt_radius_km` | float32 | No | Approximate felt radius (impact zone) |
| `damage_radius_km` | float32 | No | Approximate damage radius |
| **Impact Data** | | | |
| `deaths` | int32 | No | Total fatalities |
| `injuries` | int32 | No | Total injuries |
| `missing` | int32 | No | Missing persons |
| `displaced` | int32 | No | People displaced |
| `houses_destroyed` | int32 | No | Houses destroyed |
| `houses_damaged` | int32 | No | Houses damaged |
| `damage_usd` | float64 | No | Damage in USD |
| **Source Tracking** | | | |
| `source` | string | Yes | Data source: `desinventar`, `nasa_glc`, `noaa` |
| `source_event_id` | string | No | Original event ID in source database |
| `confidence` | string | No | Location confidence: `high`, `medium`, `low` |
| `verified` | bool | No | Multi-source verification flag |
| **Cross-Event Linking** | | | |
| `parent_event_id` | string | No | Triggering earthquake/volcanic event ID |
| `link_type` | string | No | Relationship: `triggered_by`, `associated_with` |

### Impact Radius Formulas

Landslides don't have a standard magnitude scale like earthquakes. Radius can be estimated from:

**Option 1: Based on Impact Data (if available)**
```python
def calculate_felt_radius(deaths, injuries, houses_destroyed):
    """Estimate impact radius from casualty/damage data."""
    total_impact = (deaths or 0) + (injuries or 0) * 0.5 + (houses_destroyed or 0) * 10
    if total_impact == 0:
        return 0.5  # Default 500m
    # Logarithmic scale: more impact = larger radius
    return min(50, 0.5 * (1 + np.log10(1 + total_impact)))
```

**Option 2: Based on Area (if available)**
```python
def calculate_radii_from_area(area_km2):
    """Estimate radii from affected area."""
    if not area_km2 or area_km2 == 0:
        return (0.5, 0.1)  # Default radii
    # Felt radius = radius of circle with same area
    felt_radius = np.sqrt(area_km2 / np.pi)
    # Damage radius = 20% of felt radius (core impact zone)
    damage_radius = felt_radius * 0.2
    return (felt_radius, damage_radius)
```

**Option 3: Size Category (if no data)**
```python
SIZE_RADII = {
    'small': (0.5, 0.1),           # 500m felt, 100m damage
    'medium': (2.0, 0.5),          # 2km felt, 500m damage
    'large': (5.0, 1.5),           # 5km felt, 1.5km damage
    'catastrophic': (20.0, 8.0)    # 20km felt, 8km damage
}
```

### Landslide Popup Quick Stats

Following the unified popup pattern (see DISASTER_DISPLAY.md#unified-popup-system):

| Card 1 (Power) | Card 2 (Time) | Card 3 (Impact) |
|----------------|---------------|-----------------|
| Type (Debris Flow) | Date (Jan 15, 2024) | Deaths (42) OR Area (2.5 km2) |
| Size (Large) | -- | Houses destroyed (120) |

**Power Card:**
- Primary: Landslide type (Landslide, Mudslide, Debris Flow, Rockfall)
- Secondary: Size category (Small, Medium, Large, Catastrophic) OR Volume if available

**Time Card:**
- Primary: Event date
- No duration (landslides are instantaneous)

**Impact Card:**
- If deaths > 0: Deaths as primary metric
- Else if houses_destroyed > 0: Houses destroyed
- Else if area_km2 > 0: Area affected
- Else: "Impact unknown"

### Source-Specific Notes

**DesInventar (32,039 events):**
- Rich impact data (deaths, injuries, houses)
- Structured fields (no text parsing)
- Latin America + South Asia focus
- Some events have detailed coordinates, others have only city-level

**NASA GLC (11,033 events):**
- News-based catalog, global coverage
- Often has detailed location info
- May include landslide_type, trigger, size_category
- Limited impact data (deaths often from news reports)

**NOAA Debris Flows (2,502 events):**
- US-only, high-quality coordinates
- Includes debris flow characteristics
- Often linked to weather events (rainfall triggers)
- Good metadata on magnitude/impacts

### Linking to Triggering Events

Landslides can be triggered by:

**Earthquakes:**
- Link window: 0-48 hours after earthquake
- Distance: Within 200 km of epicenter
- Magnitude threshold: M5.0+

**Volcanic Eruptions:**
- Link window: 0-30 days during eruption
- Distance: Within 50 km of volcano
- Lahars (volcanic mudflows) are a specific type

**Rainfall Events:**
- Link to tropical storms/hurricanes
- Link window: 0-7 days after peak rainfall
- Distance: Within storm path

---

## Integration with DISASTER_DISPLAY.md

### Add to Disaster Types Table

```markdown
| **Drought** | US/Canada Monitors | Yes (weekly/monthly) | Choropleth animation | 2000-present (USA), 2019-present (CAN) | Choropleth |
| **Landslides** | Unified Global Catalog | No | Point display | 1760-present | Point + Radius |
```

### Add to Complete Parquet Schemas Section

After Flood Schema, add:

**### Drought Schema (Snapshots)**

(Include full drought snapshot schema from above)

**### Landslide Schema**

(Include full landslide event schema from above)

### Add to Frontend Architecture Section

**Display Models table:**
```
| Model | File | Disasters |
|-------|------|-----------|
| Choropleth | choropleth.js | Drought, Aggregates |
| Point+Radius | model-point-radius.js | Earthquakes, Volcanoes, Tornadoes, **Landslides** |
```

### Add to API Endpoints Section

**GeoJSON Endpoints:**
```markdown
| `/api/drought/geojson` | year, month, severity, country |
| `/api/landslides/geojson` | year, min_deaths, country |
```

**Drill-Down Endpoints:**
```markdown
| `/api/drought/{country}/{year}` | Monthly snapshots for animation |
| `/api/landslides/{id}` | Landslide detail with triggering events |
```

---

## Converter Implementation

### Canada Drought Converter

**Script:** `data_converters/converters/convert_canada_drought.py`

```python
"""
Convert Canada Drought Monitor monthly GeoJSON files to parquet snapshots.

Input: Raw data/imported/canada/drought/{YYYY}/{YYYYMM}_D{0-4}_LR.geojson
Output: countries/CAN/drought/snapshots.parquet

Schema: snapshot_id, timestamp, year, month, severity, severity_code,
        severity_name, geometry, area_km2, iso3, provinces_affected
"""
```

**Processing steps:**
1. Iterate through each year folder (2019-2025)
2. For each month, load D0-D4 GeoJSON files
3. Extract polygon geometry and metadata
4. Calculate area_km2 from geometry
5. Determine affected provinces from geometry intersection
6. Create snapshot records with standardized fields
7. Write to parquet with proper dtypes

### Landslide Schema Updates

**Script:** (Already exists) `data_converters/converters/merge_landslide_sources.py`

The unified landslide catalog already exists (45,483 events). Update it to match the schema above:

**Add missing columns:**
- `felt_radius_km` - Calculate from area_km2 or impact data
- `damage_radius_km` - Calculate as 20% of felt_radius_km
- `event_type` - Set to `landslide` for all records
- `landslide_type` - Map from source-specific fields
- `trigger` - Map from source-specific fields (if available)

**Ensure core columns:**
- `event_id`, `timestamp`, `year`, `latitude`, `longitude` - Already exist
- `loc_id`, `parent_loc_id`, `iso3` - Need to be added via enrichment

**Source mapping:**

| Field | DesInventar | NASA GLC | NOAA |
|-------|-------------|----------|------|
| `landslide_type` | event_type field | landslide_category | "debris_flow" |
| `trigger` | cause field | landslide_trigger | "rainfall" (usually) |
| `landslide_size` | -- | landslide_size | magnitude category |

---

## Display Behavior Specifications

### Drought Choropleth Animation

**Behavior:**
1. User enables "Drought" overlay
2. Time slider shows month-by-month range
3. Map displays severity polygons colored by D0-D4 scale
4. As time advances, polygons fade in/out showing drought evolution
5. Clicking a drought area shows popup with:
   - Severity level
   - Date range
   - Area affected
   - Provinces/states affected

**Color Scale:**
- D0: Yellow (#FFFFE0) - Lightest
- D1: Tan (#FCD37F)
- D2: Orange (#FFAA00)
- D3: Red (#E60000)
- D4: Dark Red (#730000) - Darkest

**Opacity:**
- Active month: 0.6 opacity
- Fading out: Linear fade over 1 month
- Multiple severity levels: Overlay with higher severity on top

### Landslide Point Display

**Behavior:**
1. User enables "Landslides" overlay
2. Points appear colored by impact severity or landslide type
3. Point size scales with deaths or area_km2
4. Two concentric circles:
   - Outer (felt): Pale red, approximate impact zone
   - Inner (damage): Red, core damage zone
5. Clicking shows popup with landslide details

**Color by Impact:**
- 0 deaths: Blue (minor/unknown)
- 1-10 deaths: Yellow (moderate)
- 11-100 deaths: Orange (serious)
- 101-1000 deaths: Red (severe)
- 1000+ deaths: Dark Red (catastrophic)

**Sequence/Related Buttons:**
- **Sequence:** Shows landslide clusters (same region, same timeframe)
- **Related:** Shows triggering earthquake/volcano/storm if linked

---

## Data Completeness

### Drought

**USA:**
- Coverage: 2000-2026 (26 years)
- Granularity: Weekly observations → Yearly aggregates
- Geographic: County-level (3,143 counties x 26 years = ~81K records)
- Completeness: 100% for 2000+

**Canada:**
- Coverage: 2019-2025 (7 years, through Nov 2025)
- Granularity: Monthly snapshots
- Geographic: Province/territory-level polygons
- Completeness: ~94% (some months missing D3/D4 severity files)

**Global Gap:** No drought data for rest of world

### Landslides

**Geographic Coverage:**
- 160 countries
- Strong coverage: Latin America, South Asia, USA
- Moderate coverage: Europe, East Asia
- Weak coverage: Africa, Middle East, Central Asia

**Temporal Coverage:**
- Historical: 1760-2025 (344 years)
- Peak coverage: 1988+ (NASA GLC started)
- DesInventar: Varies by country (1900s-2024)
- NOAA: 1996-2025 (US only)

**Impact Data Completeness:**
- Deaths: 16.7% of events (7,586 events)
- Injuries: 8.2% of events (3,729 events)
- Damage USD: 5.4% of events (2,467 events, mostly US)

**Multi-source Verification:**
- Only 96 events (0.2%) found in multiple sources
- Suggests sources are largely complementary, not overlapping

---

## Next Steps

### Immediate (Canada Drought)

1. Create `convert_canada_drought.py` converter
2. Process monthly GeoJSON files to snapshots.parquet
3. Add metadata.json to countries/CAN/drought/
4. Test choropleth display with Canada data

### Short-term (Landslides)

1. Update landslide converter to add missing schema columns
2. Run loc_id enrichment on landslide events
3. Calculate felt_radius_km and damage_radius_km
4. Add to DISASTER_DISPLAY.md schemas section

### Medium-term (USA Drought Snapshots)

1. Download USDM weekly shapefiles (2000-2026)
2. Create `convert_usa_drought_snapshots.py`
3. Generate weekly snapshots for animated choropleth
4. Keep existing USA.parquet aggregates for analysis

### Long-term (Global Drought)

1. Research European Drought Observatory (EDO) data availability
2. Research Mexico drought monitoring systems
3. Research UN/WMO global drought products
4. Integrate if bulk download available

---

*This document defines the schema and integration plan for Drought and Landslide disaster types.*
