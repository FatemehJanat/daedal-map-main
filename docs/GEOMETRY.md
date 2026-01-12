# Geometry System

The geometry layer is the **source of truth** for all locations. Every indicator dataset joins to geometry via `loc_id`.

**Related docs:**
- [DISASTER_DISPLAY.md](DISASTER_DISPLAY.md) - Disaster event schemas, display models
- [MAPPING.md](MAPPING.md) - Frontend visualization, time slider
- [data_import.md](data_import.md) - Quick reference for creating converters

**Builder**: `mapmover/process_gadm.py`
**Output**: `county-map-data/geometry/`
**Source**: GADM 4.1 (gadm_410.gpkg)

---

## Quick Reference: Geometry Standards

| Standard | Specification | Example |
|----------|---------------|---------|
| **loc_id format** | `{ISO3}[-{admin1}[-{admin2}]]` | `USA-CA-6037` |
| **Country codes** | ISO 3166-1 alpha-3 (uppercase) | `USA`, `GBR`, `DEU` |
| **Water body codes** | X-prefix: XO_ (ocean), XS_ (sea), XL_ (lake) | `XOA`, `XSC`, `XLE` |
| **US state codes** | 2-letter postal abbreviation | `CA`, `TX`, `NY` |
| **US FIPS** | Integer (no leading zeros) | `6037` not `06037` |
| **Join key** | `loc_id` column in both geometry and data | Must match exactly |
| **Parquet schema** | See [Parquet Schema](#parquet-schema) section | `loc_id`, `admin_level`, `geometry`, ... |
| **Simplification** | Level-appropriate tolerances | Countries: 0.01, Counties: 0.001 |

### Key Files

| File | Purpose |
|------|---------|
| `geometry/USA.parquet` | All US geometry (states + counties) |
| `geometry/global.csv` | 257 country outlines |
| `geometry/index.json` | Discovery metadata |
| `countries/USA/geometry.parquet` | Symlink or copy for data folder structure |

### Cross-Reference

- **Data Pipeline**: See [data_pipeline.md](data_pipeline.md) for converter standards
- **Adding Data**: loc_id in data MUST match geometry exactly - see [How Data Links to Geometry](#how-data-links-to-geometry)
- **Reference Data**: See [Reference Data Files](#reference-data-files) for ISO codes, admin levels, conversions

---

## Location ID (loc_id) Specification

Every geographic location has a unique `loc_id` that:
- Identifies it across all datasets (geometry, indicators, metadata)
- Encodes the administrative hierarchy
- Enables parent-child relationships and data cascading

### Format

```
{country}[-{admin1}[-{admin2}[-{admin3}...]]]
```

### Examples

| Level | Example | Description |
|-------|---------|-------------|
| Country (admin_0) | `USA` | ISO 3166-1 alpha-3 |
| State (admin_1) | `USA-CA` | Country + state code |
| County (admin_2) | `USA-CA-6037` | Country + state + FIPS |
| Place (admin_3+) | `USA-CA-6037-12345` | Deeper levels as needed |

---

## Country Level (admin_0)

**Format**: ISO 3166-1 alpha-3 code (3 uppercase letters)

**Source**: `conversions.json` -> `iso_country_codes`

**Examples**:
- `USA` - United States
- `GBR` - United Kingdom
- `FRA` - France
- `DEU` - Germany
- `CHN` - China

**Conversion from alpha-2**:
- `US` -> `USA`
- `GB` -> `GBR`
- `FR` -> `FRA`

---

## Water Bodies (Oceans, Seas, Lakes)

Events and features that occur outside sovereign territory (international waters, shared lakes) need loc_ids that work alongside country codes. Since no existing standard provides 3-letter codes for water bodies, we use ISO 3166-1's **user-assigned range (XAA-XZZ)** with a semantic prefix structure.

### Existing Standards (Reference Only)

| Standard | Format | Notes |
|----------|--------|-------|
| IHO S-130 | Numeric IDs | New digital standard, replaces S-23 |
| Marine Regions MRGID | Numeric IDs | e.g., MRGID 1904 = Atlantic Ocean |
| ISO 3166-1 | 3-letter codes | Countries only, no water bodies |

Since these use numeric IDs (not compatible with our loc_id pattern), we define our own 3-letter codes using ISO's reserved X-prefix range.

### Water Body Code Structure

```
X{type}{identifier}

Where:
  X  = Required prefix (ISO user-assigned range)
  {type} = O (Ocean), S (Sea), L (Lake)
  {identifier} = 1-letter unique identifier
```

### Oceans (XO_)

| Code | Name | Notes |
|------|------|-------|
| `XOA` | Atlantic Ocean | Can subdivide: XOA-N (North), XOA-S (South) |
| `XOP` | Pacific Ocean | Can subdivide: XOP-N (North), XOP-S (South) |
| `XOI` | Indian Ocean | |
| `XOR` | Arctic Ocean | |
| `XOS` | Southern Ocean | Antarctic waters |

### Seas (XS_)

| Code | Name | Notes |
|------|------|-------|
| `XSM` | Mediterranean Sea | |
| `XSC` | Caribbean Sea | |
| `XSB` | Baltic Sea | |
| `XSR` | Red Sea | |
| `XSA` | Arabian Sea | |
| `XSG` | Gulf of Mexico | |
| `XSP` | Persian Gulf | |
| `XSJ` | Sea of Japan | |
| `XSE` | East China Sea | |
| `XSS` | South China Sea | |

### International Lakes (XL_)

Lakes shared between countries or otherwise needing standalone codes:

| Code | Name | Bordering Countries |
|------|------|---------------------|
| `XLE` | Lake Erie | USA, CAN |
| `XLH` | Lake Huron | USA, CAN |
| `XLM` | Lake Michigan | USA (entirely, but part of Great Lakes system) |
| `XLO` | Lake Ontario | USA, CAN |
| `XLS` | Lake Superior | USA, CAN |
| `XLC` | Caspian Sea | RUS, KAZ, TKM, IRN, AZE (technically a lake) |
| `XLV` | Lake Victoria | UGA, TZA, KEN |
| `XLT` | Lake Tanganyika | TZA, COD, BDI, ZMB |

### loc_id Format for Water Bodies

Water bodies are admin_level 0 entities (peers to countries):

```
{water_code}[-{subdivision}][-{sub-subdivision}]

Examples:
  XOA           - Atlantic Ocean (entire)
  XOA-N         - North Atlantic
  XOA-S         - South Atlantic
  XOA-N-0       - North Atlantic (single region ID)
  XSC-0         - Caribbean Sea (single region)
  XLE-0         - Lake Erie (single region)
```

### Usage Example: Hurricane Tracks

A hurricane track crosses from ocean to land:

```
Position 1: loc_id = XOA-0      (Atlantic Ocean, over water)
Position 2: loc_id = XOA-0      (still over Atlantic)
Position 3: loc_id = XSC-0      (entered Caribbean Sea)
Position 4: loc_id = XSG-0      (Gulf of Mexico)
Position 5: loc_id = USA-FL-12086  (landfall in Miami-Dade County)
Position 6: loc_id = USA-FL-12011  (continued inland to Broward County)
```

### Geometry for Water Bodies

Water bodies can optionally have geometry in `global_entities.parquet`:

```
loc_id  | admin_level | type  | name           | geometry
XOA     | 0           | ocean | Atlantic Ocean | POLYGON(...)
XOA-N   | 1           | ocean | North Atlantic | POLYGON(...)
XSC     | 0           | sea   | Caribbean Sea  | POLYGON(...)
XLE     | 0           | lake  | Lake Erie      | POLYGON(...)
```

For events over water, geometry is optional - the lat/lon coordinates are sufficient for visualization. The loc_id provides categorization and enables queries like "all hurricane positions in the Caribbean."

### Code Capacity

ISO 3166-1 reserves XAA-XZZ (676 codes) for user assignment:

| Category | Codes Available | Estimated Need |
|----------|-----------------|----------------|
| Oceans (XO_) | 26 | 5 (+ subdivisions) |
| Seas (XS_) | 26 | ~20 major seas |
| Lakes (XL_) | 26 | ~15 international lakes |
| **Total** | 78 single-letter | ~40 primary codes |

With subdivision support (XOA-N, XOA-S, etc.), this provides ample capacity for global coverage.

---

## United States Subdivisions

### States (admin_1)

**Format**: `USA-{2-letter postal abbrev}`

**Examples**:
- `USA-CA` - California
- `USA-TX` - Texas
- `USA-NY` - New York

### Counties (admin_2)

**Format**: `USA-{state}-{FIPS as integer}`

The FIPS code is stored as an integer (no leading zeros).

**Examples**:
- `USA-CA-6037` - Los Angeles County (FIPS 06037)
- `USA-OH-39071` - Highland County (FIPS 39071)
- `USA-AL-1001` - Autauga County (FIPS 01001)

**Converting from raw FIPS**:
```python
# From 5-digit FIPS string "06037"
fips_int = int("06037")  # -> 6037
loc_id = f"USA-CA-{fips_int}"  # -> "USA-CA-6037"
```

---

## Canada Subdivisions

**Format**: `CAN-{prov}-{cduid}` (e.g., `CAN-BC-5915` for Greater Vancouver)

- **admin_1**: 13 provinces/territories (NL, PE, NS, NB, QC, ON, MB, SK, AB, BC, YT, NT, NU)
- **admin_2**: Census Divisions (CD) - ~300 units
- **Code mappings**: `data_converters/base/constants.py` - `CAN_PROVINCE_ABBR`
- **loc_id converter**: `can_cduid_to_loc_id()` in `data_converters/base/geo_utils.py`

---

## Australia Subdivisions

**Format**: `AUS-{state}-{lga_code}` (e.g., `AUS-NSW-17200` for Sydney)

- **admin_1**: 9 states/territories (NSW, VIC, QLD, SA, WA, TAS, NT, ACT, OT)
- **admin_2**: Local Government Areas (LGA) - 547 units
- **Code mappings**: `data_converters/base/constants.py` - `AUS_STATE_ABBR`
- **loc_id converter**: `aus_lga_to_loc_id()` in `data_converters/base/geo_utils.py`

---

## International Subdivisions

**Format**: `{ISO3}-{region_code}` (human-readable where possible)

Region codes use ISO 3166-2 or national standard codes:
- `FRA-IDF` - Ile-de-France
- `DEU-BY` - Bavaria
- `GBR-ENG` - England
- `JPN-13` - Tokyo (prefecture number)

**Source**: GADM gpkg with mapping to standard codes via HASC_1/HASC_2 columns.

---

## How Data Links to Geometry

The `loc_id` column is the **join key** between geometry and all indicator datasets. This single-column join enables:

```
GEOMETRY (source of truth)              DATA (indicator values)
========================               ======================
geometry/USA.parquet                   countries/USA/fema_nri/USA.parquet
------------------------               ----------------------------------
loc_id          | geometry             loc_id          | risk_score | ...
USA-CA-6037     | {...}       <--->    USA-CA-6037     | 99.8       | ...
USA-TX-48201    | {...}       <--->    USA-TX-48201    | 87.2       | ...
```

### The Join Pattern

All data queries follow this pattern:

```python
# 1. Load geometry for the region
geometry = pd.read_parquet("geometry/USA.parquet")
geometry = geometry[geometry['admin_level'] == 2]  # Counties

# 2. Load indicator data
data = pd.read_parquet("countries/USA/fema_nri/USA.parquet")

# 3. Join on loc_id
merged = geometry.merge(data, on='loc_id', how='left')

# Result: GeoJSON features with properties from data
```

### loc_id Consistency Rules

For data to display correctly on the map:

| Rule | Geometry | Data | Result |
|------|----------|------|--------|
| Match | `USA-CA-6037` | `USA-CA-6037` | Data displays |
| Format mismatch | `USA-CA-6037` | `USA-CA-06037` | NO MATCH - leading zero |
| Format mismatch | `USA-CA-6037` | `6037` | NO MATCH - missing prefix |
| Missing geometry | (none) | `USA-CA-99999` | Data orphaned |
| Missing data | `USA-CA-6037` | (none) | Empty on map |

### Converters Must Match Geometry

When creating data converters, the loc_id format MUST match geometry exactly. See [data_pipeline.md](data_pipeline.md) for the FIPS to loc_id conversion pattern:

```python
# CORRECT: Matches geometry format
loc_id = f"USA-{state_abbr}-{int(fips)}"  # "USA-CA-6037"

# WRONG: Leading zeros don't match
loc_id = f"USA-{state_abbr}-{fips:05d}"   # "USA-CA-06037" - won't join!
```

### Validation

Before finalizing a data source, verify loc_ids match geometry:

```python
geometry = pd.read_parquet("geometry/USA.parquet")
data = pd.read_parquet("countries/USA/my_source/USA.parquet")

# Check for orphaned data (loc_ids in data but not geometry)
geo_ids = set(geometry['loc_id'])
data_ids = set(data['loc_id'])
orphaned = data_ids - geo_ids

if orphaned:
    print(f"WARNING: {len(orphaned)} loc_ids in data have no geometry!")
    print(list(orphaned)[:10])  # Show first 10
```

---

## Parent-Child Relationships

Every loc_id (except countries) has a `parent_id`:

| loc_id | parent_id |
|--------|-----------|
| `USA` | (none) |
| `USA-CA` | `USA` |
| `USA-CA-6037` | `USA-CA` |

This enables:
- **Cascade down**: If no data for `USA-CA-6037`, use `USA-CA` data
- **Aggregate up**: Sum children to compute parent values

### Data Cascade

When querying data for a location:

1. Look for exact match on `loc_id`
2. If not found, try `parent_id`
3. Continue up the hierarchy until found or reach root

Example: Query population for `USA-CA-6037` (LA County)
- Check for `loc_id = 'USA-CA-6037'`
- If missing, check for `loc_id = 'USA-CA'` (California)
- If missing, check for `loc_id = 'USA'` (national)

---

## Per-Country File Isolation

Each country's parquet file is self-contained, holding all admin levels for that country. This design allows:
- Country-specific naming conventions
- Different depth/structure per country
- Easy expansion without restructuring

**The "just append" principle**: Adding new subdivisions means appending rows to the relevant country file, not restructuring the system.

```
geometry/
  global.csv               <- 257 countries (admin_0, default display)
  global_entities.parquet  <- Supra-national entities (rivers, climate zones)
  index.json               <- Universal index for discovery
  USA.parquet              <- All USA subdivisions (states, counties, + special)
  DEU.parquet              <- All Germany subdivisions
  FRA.parquet              <- All France subdivisions
  ...
```

### Adding New Levels

To add NYC community districts to the system:

1. **Get geometry** - Download boundaries from NYC Open Data
2. **Assign loc_ids** - Use pattern `USA-NY-{county_fips}-CD{num}`
3. **Append to USA.parquet** - Add rows with level=3, type="admin"
4. **Regenerate index.json** - Run geometry index script
5. **Create data converter** - Output data with matching loc_ids

Result: System "just works" - loc_id matches, empty box model fills data.

---

## Cross-Boundary Entities

Some geographic features (watersheds, river basins, climate zones) cross administrative boundaries. These are handled using the **sibling layer approach**.

### The Sibling Rule

If a feature crosses boundaries at admin level N, make it a sibling at level N.

| Feature crosses... | Becomes sibling at... | Example |
|--------------------|----------------------|---------|
| Counties within a state | Level 2 (county sibling) | Hudson River in NY |
| States within a country | Level 1 (state sibling) | Mississippi Basin |
| Countries | Global entity | Amazon Basin |

### Within-Country Entities

Rivers, watersheds, and other features that stay within one country live in that country's parquet file as siblings at their interference level.

**USA.parquet with special entities:**
```
loc_id              | level | type    | name
USA-NY              | 1     | admin   | New York
USA-CA              | 1     | admin   | California
USA-MISS            | 1     | river   | Mississippi River Basin
USA-HUC01           | 1     | hydro   | New England Watershed Region
USA-NY-36061        | 2     | admin   | New York County
USA-NY-HUDSON       | 2     | river   | Hudson River
USA-MISS-UPPER      | 2     | segment | Upper Mississippi Segment
```

The Mississippi River basin crosses state lines, so it's a level-1 sibling to states. The Hudson River crosses county lines within NY, so it's a level-2 sibling to counties.

### Global Entities (Supra-National)

Features that cross country borders live in `global_entities.parquet`, separate from the clean `global.csv`:

**global.csv** - 257 recognized countries (clean, default map display)

**global_entities.parquet** - Everything else:
```
loc_id              | level | type      | name
XOA                 | 0     | ocean     | Atlantic Ocean
XOP                 | 0     | ocean     | Pacific Ocean
XSM                 | 0     | sea       | Mediterranean Sea
XSC                 | 0     | sea       | Caribbean Sea
XLE                 | 0     | lake      | Lake Erie
XLS                 | 0     | lake      | Lake Superior
AMAZON-BASIN        | 0     | river     | Amazon River Basin
NILE-WATERSHED      | 0     | river     | Nile Watershed
EU                  | 0     | political | European Union
SAHEL               | 0     | climate   | Sahel Region
```

**Why separate files:**
- Default map loads global.csv - fast, clean
- Global entities only loaded when requested
- Keeps the 257 countries pristine
- No accidental pollution of country list

### Type Column Specification

The `type` column distinguishes entity categories. This is the **canonical list** of allowed types.

**Governance/Administrative:**

| Type | Description | Examples |
|------|-------------|----------|
| admin | Official administrative divisions with governance | Countries, states, counties, community districts, wards |
| district | Single-purpose governance districts | School districts, water districts, fire districts |

**Statistical/Data Collection:**

| Type | Description | Examples |
|------|-------------|----------|
| census | Statistical collection boundaries | Census tracts, block groups |
| postal | Mail delivery zones | ZIP codes, postal codes |

**Natural Features:**

| Type | Description | Examples |
|------|-------------|----------|
| river | River basins, watersheds | Mississippi Basin, Amazon Basin |
| hydro | Hydrological units (HUC) | USGS watershed codes |
| watershed | Major watershed boundaries | Columbia River Watershed, Great Lakes |
| ocean | Major oceans | Atlantic (XOA), Pacific (XOP), Indian (XOI) |
| sea | Seas, gulfs, maritime zones | Mediterranean (XSM), Caribbean (XSC), Gulf of Mexico (XSG) |
| lake | International/shared lakes | Great Lakes (XLE, XLH, XLM, XLO, XLS), Caspian (XLC) |
| climate | Climate zones, biomes | Arctic Circle, Sahel, Tropics |

**Political/Economic/Cultural:**

| Type | Description | Examples |
|------|-------------|----------|
| political | Political entities with geometry | EU, NATO (if mapped) |
| economic | Economic zones | Trade corridors, special economic zones |
| tribal | Indigenous/tribal nation boundaries | Navajo Nation, Cherokee Nation |

**Disaster/Hazard Events:**

| Type | Description | Examples |
|------|-------------|----------|
| hurricane | Tropical storm tracks and wind swaths | Hurricane Ian, Katrina, Maria |
| wildfire | Fire perimeter boundaries | Creek Fire, Camp Fire, Dixie Fire |
| earthquake | Seismic events (epicenter + shake zones) | Northridge 1994, Loma Prieta 1989 |
| tsunami | Tsunami source events and runup zones | 1946 Aleutian, 1964 Alaska |
| eruption | Volcanic eruption events | Mt. St. Helens 1980, Kilauea 2018 |
| tornado | Tornado track paths | Joplin 2011, Moore 2013 |
| flood | Major flood events/zones | Great Flood of 1993, Harvey 2017 |

**Cross-Boundary Entity loc_id Examples:**
```
loc_id                  | level | type      | name                    | geometry
USA-FL                  | 1     | admin     | Florida                 | POLYGON(...)
USA-HRCN-IAN2022        | 1     | hurricane | Hurricane Ian (2022)    | POLYGON(...wind swath)
USA-HRCN-KATRINA2005    | 1     | hurricane | Hurricane Katrina       | POLYGON(...)
USA-CA-FIRE-CREEK2020   | 2     | wildfire  | Creek Fire (2020)       | POLYGON(...perimeter)
USA-AK-TSUN-1964ALASKA  | 1     | tsunami   | 1964 Alaska Tsunami     | POINT(...source)
PACIFIC-TSUN-2011TOHOKU | 0     | tsunami   | 2011 Tohoku Tsunami     | POINT(...global event)
USA-WSHED-MISSISSIPPI   | 1     | watershed | Mississippi River Basin | POLYGON(...)
USA-TRIBAL-NAVAJO       | 1     | tribal    | Navajo Nation           | POLYGON(...)
```

**Disaster Sibling Rules:**
- Disaster affecting multiple counties within a state -> level 2 sibling (e.g., `USA-CA-FIRE-CREEK2020`)
- Disaster affecting multiple states -> level 1 sibling (e.g., `USA-HRCN-IAN2022`)
- Disaster affecting multiple countries -> level 0 global entity (e.g., `PACIFIC-TSUN-2011TOHOKU`)

**Other:**

| Type | Description | Examples |
|------|-------------|----------|
| informal | Cultural/unofficial boundaries | Neighborhoods like "SoHo", "Tribeca" |

**Spec vs Reality:**
- **GEOMETRY.md** defines allowed types (this list)
- **index.json** reports actual types in use per country
- Most data will be `type=admin` until special entities are added

**Usage example:**
```python
df = pd.read_parquet("geometry/USA.parquet")
rivers = df[df["type"] == "river"]
admin_only = df[df["type"] == "admin"]
```

### loc_id Determines File Loading

The loc_id prefix tells you which file to load:

```python
def get_geometry_file(loc_id):
    # Water body codes (X-prefix) -> global entities
    if loc_id.startswith("X") and len(loc_id) >= 3:
        return "geometry/global_entities.parquet"

    if "-" in loc_id:
        # Has country prefix -> country file
        country = loc_id.split("-")[0]
        if len(country) == 3 and country.isupper():
            return f"geometry/{country}.parquet"

    # Check if it's a known country code
    if len(loc_id) == 3 and loc_id.isupper():
        return "geometry/global.csv"

    # Otherwise it's a global entity
    return "geometry/global_entities.parquet"

# Examples:
get_geometry_file("DEU")           # -> global.csv (country outline)
get_geometry_file("DEU-BY")        # -> DEU.parquet
get_geometry_file("USA-MISS")      # -> USA.parquet (river basin)
get_geometry_file("AMAZON-BASIN")  # -> global_entities.parquet
get_geometry_file("EU")            # -> global_entities.parquet
get_geometry_file("XOA")           # -> global_entities.parquet (Atlantic Ocean)
get_geometry_file("XSC-0")         # -> global_entities.parquet (Caribbean Sea)
get_geometry_file("XLE")           # -> global_entities.parquet (Lake Erie)
```

---

## Special Geometries

Disasters and natural phenomena often have complex geometries that go beyond simple administrative polygons. This section defines **standardized geometry patterns** that work globally across all countries, ensuring consistent handling of cross-border events, impact zones, and natural boundaries.

### Design Principles

1. **Events stored with point + attributes** - Raw event data lives in `events.parquet` with lat/lon and attributes
2. **Radii precomputed and stored** - Impact radii calculated at conversion time using standard formulas, stored as columns (cheap: 4-8 bytes per event). Frontend just reads the value.
3. **Tracks stored as LineStrings** - Paths stored with timestamps, rendered as animated tracks
4. **Impact zones optional** - Large disasters can have pre-computed polygon footprints as siblings
5. **Same pattern everywhere** - Canada earthquakes work like USA earthquakes work like Japan earthquakes
6. **Formulas documented for transparency** - Standard formulas in this doc ensure consistency across converters

### Geometry Categories

#### 1. Point + Radius Features

Events with an epicenter/source and calculable impact radius.

| Event Type | Point | Radius Fields | Formula |
|------------|-------|---------------|---------|
| **Earthquake** | epicenter (lat/lon) | `felt_radius_km`, `damage_radius_km` | R = 10^(0.5*M - 1.0) for felt |
| **Volcano** | vent location | `ash_radius_km`, `lahar_radius_km`, `pyroclastic_km` | VEI-based lookup |
| **Explosion** | blast center | `blast_radius_km`, `thermal_radius_km` | Energy-based |
| **Nuclear** | detonation point | `fireball_km`, `blast_km`, `radiation_km` | Yield-based (NUKEMAP formulas) |

**events.parquet schema for point+radius:**
```
event_id     | string    | Unique identifier
time         | timestamp | Event time (UTC)
latitude     | float32   | Epicenter latitude
longitude    | float32   | Epicenter longitude
loc_id       | string    | Admin unit containing epicenter
magnitude    | float32   | Event magnitude (Richter, VEI, etc.)
depth_km     | float32   | Depth below surface (earthquakes)
felt_radius_km    | float32 | Radius where shaking/effects felt
damage_radius_km  | float32 | Radius of potential damage
place        | string    | Human-readable location description
```

**Frontend rendering:**
- Draw circle at (lat, lon) with radius from field
- Color by severity (magnitude/VEI)
- Clicking circle shows affected admin units (spatial query)

#### 2. Track/Path Features

Events that move through space over time.

| Event Type | Geometry | Key Fields |
|------------|----------|------------|
| **Hurricane/Cyclone** | LineString (track) + polygons (wind swaths) | `max_wind_kt`, `pressure_mb`, `category` |
| **Tornado** | LineString (damage path) | `ef_scale`, `path_length_km`, `path_width_m` |
| **Storm system** | LineString (movement) | `storm_type`, `hail_size_in` |
| **Wildfire** | Polygon sequence (daily perimeters) | `acres_burned`, `containment_pct` |

**Track data schema (hurricanes/cyclones):**
```
storm_id     | string    | e.g., "AL092022" (Atlantic #9, 2022)
name         | string    | e.g., "IAN"
point_time   | timestamp | Time of this track point
latitude     | float32   | Position latitude
longitude    | float32   | Position longitude
max_wind_kt  | int16     | Maximum sustained wind (knots)
pressure_mb  | int16     | Central pressure (millibars)
category     | int8      | Saffir-Simpson (0-5) or Australian (1-5)
wind_radii_34kt_ne | float32 | 34-knot wind radius NE quadrant (nm)
wind_radii_34kt_se | float32 | 34-knot wind radius SE quadrant (nm)
wind_radii_34kt_sw | float32 | 34-knot wind radius SW quadrant (nm)
wind_radii_34kt_nw | float32 | 34-knot wind radius NW quadrant (nm)
```

**Frontend rendering:**
- Render track as animated LineString (time slider scrubs position)
- At each point, draw wind radii as asymmetric polygon (4-quadrant)
- Color track by intensity (category/wind speed)

#### 3. Impact Zone Features

Events with complex footprint polygons (not circular).

| Event Type | Zone Type | Data Source |
|------------|-----------|-------------|
| **Tsunami** | Runup zones, inundation areas | NOAA NGDC, national surveys |
| **Hurricane** | Storm surge zones, wind swaths | NOAA NHC, SLOSH models |
| **Flood** | Inundation extent | Satellite imagery, FEMA NFHL |
| **Wildfire** | Burn perimeter (final) | MTBS, NIFC |
| **Ash fall** | Deposit thickness contours | USGS, national volcanic surveys |

**Impact zone schema:**
```
event_id     | string    | Links to parent event
zone_type    | string    | "runup", "surge", "inundation", "perimeter", "ashfall"
zone_level   | string    | Severity level (e.g., "6ft_surge", "1cm_ash")
geometry     | geometry  | Polygon/MultiPolygon (GeoJSON)
area_km2     | float32   | Zone area
```

**Sibling creation rule:**
When an impact zone crosses admin boundaries, create a sibling entity:
- Single state: `USA-CA-FIRE-CREEK2020` (level 2 sibling)
- Multi-state: `USA-HRCN-IAN2022` (level 1 sibling)
- Multi-country: `PACIFIC-TSUN-2011TOHOKU` (level 0 global entity)

### Dual-File Pattern: Events + Aggregates

Most hazard datasets produce TWO output files that serve different purposes:

| File | Purpose | Size | When Loaded |
|------|---------|------|-------------|
| `events.parquet` | Individual events with point/geometry | Large (MB-GB) | On demand (detail view) |
| `{COUNTRY}.parquet` | Admin-year aggregates (counts, totals) | Small (KB-MB) | Always (choropleth maps) |

**Example: Wildfires**
```
wildfires/
  fires.parquet     # 50K fires: event_id, fire_name, timestamp, centroid, burned_acres, perimeter, loc_id
  USA.parquet       # 150K rows: loc_id, year, fire_count, total_acres, max_fire_acres
```

**Query patterns:**
- "Show fire risk by county (2020)" -> Load `USA.parquet`, filter year=2020, choropleth by fire_count
- "Show me the Creek Fire" -> Load `fires.parquet`, filter by name, show point/polygon
- "Which counties were affected by Creek Fire?" -> Use loc_id from event or `event_impacts.parquet`

### Tiered Polygon Loading

Polygon geometries (fire perimeters, flood extents) can be huge. Use tiered files:

```
wildfires/
  fires.parquet              # Metadata + centroid only (small, fast)
  fires_perimeters.parquet   # Full perimeter polygons (large, on-demand)
  USA.parquet                # County aggregates
```

**fires.parquet (always loaded):**
```
event_id | fire_name    | year | centroid_lat | centroid_lon | burned_acres | loc_id
CREEK20  | Creek Fire   | 2020 | 37.21        | -119.32      | 379895       | USA-CA-6019
```

**fires_perimeters.parquet (loaded on demand):**
```
event_id | geometry                    | simplified_geometry
CREEK20  | POLYGON((...full detail...))| POLYGON((...10% vertices...))
```

**Frontend flow:**
1. Load `fires.parquet` - show points on map (fast)
2. User clicks fire -> fetch `fires_perimeters.parquet` for that event_id
3. Render actual burn perimeter polygon

### Time-Series Perimeters (Active Events)

For "watch it grow" visualizations, need daily snapshots:

**Data sources:**
| Source | Coverage | Update Frequency | Perimeter Type |
|--------|----------|------------------|----------------|
| **MTBS** | USA 1984-present | Post-fire (final only) | Final perimeter |
| **NIFC/InciWeb** | USA active fires | Daily during event | Daily snapshots |
| **FIRMS (NASA)** | Global | Every 12 hours | Hotspot points |
| **Sentinel-2** | Global | 5 days | Derived polygons |

**Time-series perimeter schema:**
```
event_id     | string    | Fire identifier
snapshot_date| date      | Date of this perimeter
acres_burned | float32   | Cumulative acres as of this date
containment  | int8      | Percent contained (0-100)
geometry     | geometry  | Perimeter polygon at this date
```

**Example query:** "Show 2020 Creek Fire growth"
```python
perimeters = df[df['event_id'] == 'CREEK20'].sort_values('snapshot_date')
# Animate through perimeters as time slider moves
```

See [data_pipeline.md](data_pipeline.md) for converter implementation details.

#### 4. Natural Flow Features

Boundaries defined by physical flow patterns, not political lines.

| Feature Type | Description | loc_id Pattern |
|--------------|-------------|----------------|
| **Watershed/Basin** | Water drainage areas | `USA-WSHED-MISSISSIPPI`, `AMAZON-BASIN` |
| **Aquifer** | Underground water systems | `USA-AQUIFER-OGALLALA` |
| **Airshed** | Air quality management basins | `USA-AIR-SOCAL`, `USA-AIR-SANJOAQUIN` |
| **Ocean current** | Major current systems | `CURRENT-GULFSTREAM`, `CURRENT-KUROSHIO` |
| **Climate zone** | Koppen classification areas | `CLIMATE-BWH`, `CLIMATE-CFB` |

**Watershed hierarchy (USA HUC system):**
```
loc_id              | level | name                  | huc_code
USA-HUC01           | 1     | New England Region    | 01
USA-HUC0108         | 2     | Connecticut           | 0108
USA-HUC010802       | 3     | Lower Connecticut     | 010802
```

### Cross-Border Event Handling

When events cross international boundaries:

**Option A: Multiple country-specific records**
Store the event in each affected country's events.parquet with their local loc_id:
```
# USA events.parquet
EQ-2024-001 | USA-WA-53073 | 7.2 | ...

# CAN events.parquet
EQ-2024-001 | CAN-BC-5915 | 7.2 | ...
```
Same `event_id`, different `loc_id`. Frontend can aggregate by event_id.

**Option B: Global event entity**
For truly global events (Pacific tsunamis, major volcanic eruptions), create global entity:
```
# global_entities.parquet
PACIFIC-TSUN-2011TOHOKU | 0 | tsunami | 2011 Tohoku Tsunami | POINT(142.37, 38.32)
```
Then link affected countries via `event_impacts.parquet`.

**Recommended approach:** Option A for most events, Option B for catastrophic multi-country disasters.

### Event Impact Linkage

The `event_impacts.parquet` file links events to affected administrative units:

```
event_id           | loc_id         | impact_type | value
HRCN-IAN-2022     | USA-FL-12015   | damage_usd  | 1500000000
HRCN-IAN-2022     | USA-FL-12015   | deaths      | 12
HRCN-IAN-2022     | USA-FL-12021   | damage_usd  | 890000000
HRCN-IAN-2022     | USA-SC-45019   | damage_usd  | 45000000
EQ-TOHOKU-2011    | JPN-04         | deaths      | 15899
EQ-TOHOKU-2011    | JPN-04         | damage_usd  | 235000000000
```

This allows:
- Query: "Which counties were affected by Hurricane Ian?"
- Query: "What disasters affected Los Angeles County in 2024?"
- Aggregation: Total damage by state/country from an event

### Standardized Formulas

To ensure consistency globally, use these formulas:

**Earthquake felt radius (Modified Mercalli Intensity):**
```python
def felt_radius_km(magnitude):
    """Where shaking is perceptible (MMI II-III)"""
    return 10 ** (0.5 * magnitude - 1.0)

def damage_radius_km(magnitude):
    """Where structural damage possible (MMI VI+)"""
    return 10 ** (0.5 * magnitude - 1.5)
```

**Volcanic ash dispersal (simplified):**
```python
def ash_radius_km(vei):
    """Approximate ash fall radius by VEI"""
    radii = {0: 1, 1: 5, 2: 25, 3: 100, 4: 500, 5: 1000, 6: 2000, 7: 5000, 8: 10000}
    return radii.get(vei, 0)
```

**Saffir-Simpson wind radii estimation:**
```python
def estimate_wind_radius_nm(max_wind_kt):
    """Rough estimate of 34-knot wind radius"""
    if max_wind_kt >= 137:  # Cat 5
        return 150
    elif max_wind_kt >= 113:  # Cat 4
        return 120
    elif max_wind_kt >= 96:  # Cat 3
        return 100
    elif max_wind_kt >= 83:  # Cat 2
        return 80
    elif max_wind_kt >= 64:  # Cat 1
        return 60
    else:
        return 40
```

### File Organization

```
county-map-data/
  geometry/
    global.csv                    # 257 countries (clean)
    global_entities.parquet       # Oceans, seas, global events
    USA.parquet                   # USA admin + siblings (watersheds, etc.)
    CAN.parquet                   # Canada admin + siblings
    ...

  countries/
    USA/
      usgs_earthquakes/
        events.parquet            # Individual quakes with radius fields
        USA.parquet               # County-year aggregates
      noaa_storms/
        events.parquet            # Individual storms
        USA.parquet               # County-year aggregates
      wildfires/
        fires.parquet             # Individual fires with perimeters
        USA.parquet               # County-year aggregates
      event_impacts.parquet       # Links events to affected loc_ids (optional)

    CAN/
      nrcan_earthquakes/
        events.parquet            # Same schema as USA
        CAN.parquet               # Province/CSD-year aggregates
```

### Implementation Checklist for New Event Types

When adding a new event type (e.g., adding earthquakes to a new country):

1. [ ] Use same events.parquet schema as existing implementations
2. [ ] Include lat/lon for point location
3. [ ] Include calculated radius fields (using standard formulas)
4. [ ] Assign loc_id to containing admin unit
5. [ ] Create country-year aggregates in {COUNTRY}.parquet
6. [ ] Add to source_registry.py with `has_events: True`
7. [ ] Document any country-specific variations

This ensures Canada earthquakes, Japan earthquakes, and Chile earthquakes all work identically in the frontend.

---

## Universal Geometry Index

The `index.json` file provides discovery metadata for the LLM and admin tools.

**Location**: `geometry/index.json` (~25-50 KB)

```json
{
  "countries": {
    "USA": {
      "levels": {
        "0": {"count": 1, "type": "admin", "name": "Country"},
        "1": {"count": 50, "type": "admin", "name": "State"},
        "2": {"count": 3144, "type": "admin", "name": "County"},
        "3": {"count": 59, "type": "admin", "name": "Community District",
              "partial": ["USA-NY-36061", "USA-NY-36047"]}
      },
      "special_entities": {
        "river": {"count": 12, "levels": [1, 2]},
        "hydro": {"count": 18, "levels": [1, 2, 3]}
      },
      "total_locations": 3254
    },
    "DEU": {
      "levels": {
        "0": {"count": 1, "type": "admin", "name": "Country"},
        "1": {"count": 16, "type": "admin", "name": "Bundesland"},
        "2": {"count": 401, "type": "admin", "name": "Kreis"}
      },
      "total_locations": 418
    }
  },
  "global_entities": {
    "types": {
      "river": 8,
      "sea": 5,
      "climate": 12,
      "political": 3
    },
    "total": 28
  },
  "total_locations": 416066,
  "last_updated": "2025-12-22"
}
```

### Regenerating the Index

Run after any geometry changes:

```bash
python scripts/regenerate_geometry_index.py
```

The script scans all parquet files and rebuilds the index.

---

## Parent-Child from loc_id

Parent-child relationships are derived from loc_id structure, not stored:

```python
def get_parent(loc_id):
    """Derive parent from loc_id by removing last segment."""
    if "-" not in loc_id:
        return None  # Countries and global entities have no parent
    parts = loc_id.rsplit("-", 1)
    return parts[0]

def get_children(loc_id, all_loc_ids):
    """Find all direct children of a loc_id."""
    prefix = loc_id + "-"
    children = []
    for lid in all_loc_ids:
        if lid.startswith(prefix):
            # Only direct children (one more segment)
            remainder = lid[len(prefix):]
            if "-" not in remainder:
                children.append(lid)
    return children

# Examples:
get_parent("USA-NY-36061-CD01")  # -> "USA-NY-36061"
get_parent("USA-NY-36061")       # -> "USA-NY"
get_parent("USA-NY")             # -> "USA"
get_parent("USA")                # -> None
get_parent("AMAZON-BASIN")       # -> None (global entity)
```

---

## Geometry Files

Location: `county-map-data/geometry/`

### File Structure

| File | Content | Count |
|------|---------|-------|
| `global.csv` | All countries (admin_0 only) | 257 |
| `global_entities.parquet` | Supra-national entities (rivers, seas, climate zones) | varies |
| `index.json` | Universal discovery index | 1 |
| `{ISO3}.parquet` | All admin levels + special entities per country | 257 files |

**Total**: 257 countries, 416,066+ locations across all admin levels.

### Parquet Schema

| Column | Type | Description |
|--------|------|-------------|
| `loc_id` | string | Canonical location ID |
| `parent_id` | string | Parent location ID (derived, optional) |
| `level` | int | 0=country, 1=state, 2=county, etc. |
| `type` | string | Entity type: admin, hurricane, wildfire, watershed, tribal, river, etc. |
| `name` | string | Display name |
| `lon` | float | Centroid longitude |
| `lat` | float | Centroid latitude |
| `geometry` | string | GeoJSON geometry |

### Top Countries by Subdivisions

| Country | Total Locations | Max Depth |
|---------|-----------------|-----------|
| IDN (Indonesia) | 84,696 | 4 |
| PHL (Philippines) | 43,308 | 4 |
| FRA (France) | 40,800 | 5 |
| USA (United States) | 35,783 | 3 |
| DEU (Germany) | 16,380 | 4 |
| BRA (Brazil) | 15,727 | 3 |

### Flat File Structure and Scalability

All geometry for a country lives in a single parquet file (e.g., `USA.parquet`). This includes:
- Administrative boundaries (counties, states)
- Disaster events (hurricanes, wildfires, earthquakes)
- Natural features (watersheds, rivers)
- Cultural boundaries (tribal nations)

The `type` column distinguishes entity types. This flat structure:
- Provides single geometry source per country
- Uses consistent loc_id linking to data
- Enables efficient queries with column filtering

**Scalability tested:**

| Rows | File Size | Load Time | Memory |
|------|-----------|-----------|--------|
| 35k (USA current) | 35 MB | 300ms | 88 MB |
| 85k (Indonesia) | 122 MB | 610ms | 314 MB |
| 200k (projected) | 288 MB | 1,500ms | 754 MB |

Files up to 200k+ rows are acceptable. The geometry is loaded once per session and cached client-side.

**Example: USA with disasters**
```
Current:  35,783 admin rows
+ Add:    ~30,000 disaster events (hurricanes, wildfires, etc.)
+ Add:    ~5,000 watersheds, tribal lands
= Total:  ~70,000 rows (similar to Indonesia)
```

---

## Building Geometry

### Prerequisites

- GADM gpkg file in `county-map-data/Raw data/gadm_410.gpkg` (~2GB)
- Python with geopandas, pyarrow, shapely

### Running the Builder

```bash
python mapmover/process_gadm.py
```

This will:
1. Read all layers from GADM gpkg
2. Generate loc_ids using HASC codes where available
3. Build parent-child relationships
4. Simplify geometries for web display (level-appropriate tolerances)
5. Output one parquet per country to `geometry/`
6. Generate `global.csv` with country-level geometries
7. Generate `country_coverage.json` with drill-down metadata

### Post-Processing (Required After Import)

After importing geometry, run post-processing to complete the data:

```bash
python mapmover/post_process_geometry.py              # All countries
python mapmover/post_process_geometry.py USA          # Single country
python mapmover/post_process_geometry.py --dry-run    # Preview only
```

Post-processing performs 4 steps:

1. **Aggregate Geometry** - GADM only stores geometry at the deepest level. Parent boundaries are created by dissolving child polygons.
2. **Compute Bounding Boxes** - Add bbox columns for fast viewport filtering.
3. **Backfill Centroids** - Ensure all rows have centroid coordinates.
4. **Compute Children Counts** - Add `children_count`, `children_by_level`, `descendants_count`, `descendants_by_level` for popup info.

**Example output:**
```
[USA] Updated: 52 aggregated, 52 children, 52 descendants
[BRA] Updated: 28 aggregated, 28 children, 28 descendants
```

### Parquet Columns After Post-Processing

| Column | Type | Description |
|--------|------|-------------|
| `loc_id` | string | Canonical location ID |
| `parent_id` | string | Parent location ID |
| `admin_level` | int | 0=country, 1=state, 2=county, etc. |
| `name` | string | Display name |
| `geometry` | string | GeoJSON geometry |
| `centroid_lon` | float | Centroid longitude |
| `centroid_lat` | float | Centroid latitude |
| `bbox_min_lon` | float | Bounding box west |
| `bbox_min_lat` | float | Bounding box south |
| `bbox_max_lon` | float | Bounding box east |
| `bbox_max_lat` | float | Bounding box north |
| `children_count` | int | Number of direct children |
| `children_by_level` | string | JSON: `{"1": 27}` |
| `descendants_count` | int | Total descendants at all levels |
| `descendants_by_level` | string | JSON: `{"1": 27, "2": 5572}` |

### When to Rebuild

- New GADM version released
- loc_id format changes
- Need to add cross-boundary entities

---

## Geometry Simplification

Geometries are simplified for web display to reduce file sizes and improve rendering performance.

### Recommended Tolerances

| Level | Admin | Tolerance | Precision | Use Case |
|-------|-------|-----------|-----------|----------|
| Countries | 0 | 0.01 | ~1 km | World map view |
| States/Regions | 1 | 0.001 | ~100 m | Country zoom |
| Counties | 2 | 0.001 | ~100 m | State zoom |
| ZCTAs | 3 | 0.0001 | ~10 m | County zoom |
| Census Tracts | 4 | 0.0001 | ~10 m | City zoom |
| Block Groups | 5 | 0.00005 | ~5 m | Neighborhood zoom |
| Blocks | 6 | 0.00001 | ~1 m | Street zoom |

**Note:** Simplified geometry improves both file size AND loading speed. The `df_to_geojson()` function parses each geometry from JSON - fewer vertices = faster parsing.

### Size Impact

**global.csv (256 countries):**

| Tolerance | File Size | Reduction |
|-----------|-----------|-----------|
| Original | 31 MB | - |
| 0.01 | 7.8 MB | 75% |

**USA.parquet (35,731 counties):**

| Tolerance | File Size | Reduction |
|-----------|-----------|-----------|
| Original | 63 MB | - |
| 0.001 | 30 MB | 53% |

### Sample Country Geometry Sizes (after 0.01 simplification)

| Country | Size | Polygons | Notes |
|---------|------|----------|-------|
| Canada | ~350 KB | 412 | Many islands |
| USA | ~170 KB | 344 | Alaska/Hawaii |
| Russia | ~200 KB | 214 | Large landmass |
| France | ~50 KB | 21 | Metropolitan |
| Germany | ~40 KB | 22 | Compact |

### Simplification Code

```python
from shapely.geometry import shape, mapping
import json

def simplify_geometry(geom_json, tolerance=0.01):
    """Simplify GeoJSON geometry string."""
    geom = shape(json.loads(geom_json))
    simplified = geom.simplify(tolerance, preserve_topology=True)
    return json.dumps(mapping(simplified))
```

### When to Simplify

- After importing new geometry from GADM
- When adding new country/region files
- If file sizes exceed recommended limits:
  - global.csv: < 15 MB
  - Country parquets: < 50 MB each

---

## Name Standardization

Data sources use various name variants. Use `name_standardizer.py` for conversion.

### Common Aliases

| Variant | Canonical |
|---------|-----------|
| United States of America | United States |
| UK, Britain, Great Britain | United Kingdom |
| Korea, Republic of Korea | South Korea |
| Cote d'Ivoire | Ivory Coast |

### Programmatic Conversion

```python
from mapmover.name_standardizer import NameStandardizer

std = NameStandardizer()

# From country name
std.get_loc_id_from_name('United States')  # -> 'USA'

# From ISO code
std.get_loc_id_from_iso('US')   # -> 'USA'
std.get_loc_id_from_iso('USA')  # -> 'USA'

# From FIPS (US data)
std.get_loc_id_from_fips('06', '037')  # -> 'USA-CA-6037'
```

---

## Validation

A valid loc_id must:
1. Start with a 3-letter ISO country code OR be a global cross-boundary entity
2. Use hyphens as separators
3. Match an entry in geometry files
4. Have consistent parent_id chain (null parent for countries and global entities)

---

## Files That Use Geometry

| File | Purpose |
|------|---------|
| `mapmover/conversions.json` | ISO codes, regional groupings |
| `mapmover/name_standardizer.py` | Name-to-loc_id conversion |
| `mapmover/data_cascade.py` | Parent/child lookups |
| `mapmover/geometry_handlers.py` | Geometry API endpoints |
| `mapmover/geometry_enrichment.py` | Adding geometry to responses |

---

## Import Workflows

### Adding New Hierarchical Data (e.g., NYC Boroughs)

For data that fits the parent-child hierarchy (sub-city districts, neighborhoods):

```
1. Geometry Import
   - Add rows to country parquet (e.g., USA.parquet)
   - Assign loc_ids: USA-NY-36061-CD01, USA-NY-36061-CD02, ...
   - Set parent_id = USA-NY-36061 (Manhattan)
   - Set admin_level = 3

2. Post-Processing
   python mapmover/post_process_geometry.py USA
   - Aggregates geometry if needed
   - Computes bboxes
   - Updates children_count for parent (Manhattan gets +12)
   - Updates descendants_count up the tree (NY state, USA)

3. Data Import
   - Run data converter with loc_id = USA-NY-36061-CD01
   - Creates parquet in data/{source_id}/
   - Updates catalog.json

4. Dataset Counts (Automatic)
   - Popup reads catalog.json for dataset availability
   - Always current, no refresh needed
```

### Adding Cross-Cutting Data (e.g., Watersheds)

For data that crosses administrative boundaries:

```
1. Geometry Import
   - Create new file: relationships/watersheds.parquet
   - Or add to global_entities.parquet
   - loc_id = WATERSHED-MISSISSIPPI, WATERSHED-COLORADO
   - No parent_id (standalone entities)

2. Relationships Update
   - Add to relationships.json:
   {
     "watersheds": {
       "WATERSHED-MISSISSIPPI": ["USA-MN", "USA-WI", "USA-IA", "USA-MO", ...],
       "WATERSHED-COLORADO": ["USA-CO", "USA-UT", "USA-AZ", ...]
     }
   }

3. Data Import
   - Run converter with loc_id = WATERSHED-MISSISSIPPI
   - Same process as hierarchical data

4. Membership Lookups (Automatic)
   - Popup scans relationships.json
   - Shows "Part of: Mississippi Basin, Great Lakes Region, ..."
```

### Key Principle: Post-Processing is Idempotent

You can run post-processing multiple times safely:
- Already-aggregated geometry is skipped
- Already-computed bboxes are skipped
- Children counts are recalculated (cheap, fast)

```bash
# Safe to run after any change
python mapmover/post_process_geometry.py
```

### Adding Disaster Events

Disasters are cross-boundary entities with their own geometry and loc_id. They link to affected admin units via an impact table.

```
1. Geometry Import
   - Add disaster to appropriate parquet file based on scope
   - Single-state disaster -> country parquet (e.g., USA.parquet)
   - Multi-country disaster -> global_entities.parquet
   - Assign loc_id: USA-HRCN-IAN2022, USA-CA-FIRE-CREEK2020
   - Set type = hurricane, wildfire, earthquake, tsunami, eruption, tornado, flood
   - Set level based on sibling rule (see Disaster Sibling Rules above)

2. Impact Linkage (disaster_impacts.parquet)
   - Create rows linking disaster loc_id to affected admin loc_ids
   - Include impact metrics (damage, casualties, burned acres, etc.)

   Example:
   disaster_loc_id         | affected_loc_id  | impact_type  | value
   USA-HRCN-IAN2022        | USA-FL-12021     | landfall     | category_4
   USA-HRCN-IAN2022        | USA-FL-12015     | wind_damage  | 120_kt
   USA-CA-FIRE-CREEK2020   | USA-CA-06019     | burned_acres | 379895
   USA-CA-FIRE-CREEK2020   | USA-CA-06039     | burned_acres | 1200

3. Queries Enabled
   - "Show Hurricane Ian" -> load geometry, list affected counties
   - "What disasters affected Lee County FL?" -> scan impact table
   - "Total hurricane damage in Florida 2022" -> aggregate impacts

4. Visualization Options by Type
   | Type | Geometry | Display |
   |------|----------|---------|
   | hurricane | Track polyline + wind swath polygon | Path with buffered corridor |
   | wildfire | Burn perimeter polygon | Fill with severity coloring |
   | earthquake | Epicenter point | Concentric shake intensity rings |
   | tsunami | Source point + runup points | Source marker + coastal impacts |
   | eruption | Volcano point | Location + VEI-scaled radius |
   | tornado | Track line (begin to end) | Path with width by EF scale |
   | flood | Affected area polygon | Fill showing inundation |
```

---

## Geometry Sources

Primary and alternative sources for geographic boundaries.

### GADM (Primary Source)

- **URL**: gadm.org
- **File**: `gadm_410.gpkg` (~2GB)
- **Coverage**: Admin boundaries for every country, levels 0-5
- **License**: Free for non-commercial, attribution required
- **Used by**: `process_gadm.py`
- **Current Version**: 4.1 (400,276 administrative areas)
- **Next Version**: 5.0 expected January 2026

**GADM v5 Note (January 2026)**: Version 5 is expected to be released in January 2026. When available, evaluate for:
- Updated boundary definitions
- New administrative divisions
- Improved accuracy for regions that have changed since 4.1
- Consider running geometry comparison script against new version

---

## Geometry Overlay Strategy

GADM provides a **unified global baseline** for administrative boundaries, but local statistical agencies often have more accurate, current geometry that matches their data exactly. This section documents when to use GADM vs local sources.

### Strategy: GADM Base + Local Overlays

```
GADM 4.1 (Global Baseline)
    |
    +-- Use directly for: 200+ countries without local data
    |
    +-- Replace with local source for:
        |
        +-- Australia: ABS LGA boundaries (2024, 547 LGAs)
        +-- Canada: StatsCan CSD boundaries (2021, 5,161 CSDs)
        +-- Europe: Eurostat GISCO NUTS boundaries (1,612 NUTS 3)
        +-- USA: Continue using GADM (matches Census TIGER well)
```

### Comparison Results (January 2026)

Comparison script: `data_converters/utilities/compare_geometry_sources.py`

| Region | Local Source | Local Units | GADM Units | Name Match | Recommendation |
|--------|--------------|-------------|------------|------------|----------------|
| **Australia** | ABS LGA 2024 | 547 | 564 | 87.7% | **Use ABS** - more current, includes geometry |
| **Canada** | StatsCan CSD 2021 | 5,161 | ~5,000 | TBD | **Use StatsCan** - exact data match, need boundary download |
| **Europe** | Eurostat GISCO | 1,612 NUTS3 | varies | TBD | **Use GISCO** - standardized EU system |
| **USA** | Census TIGER | 3,144 | 3,144 | 99%+ | **Keep GADM** - good match, already working |

### When to Replace GADM

Replace GADM geometry with local source when:

1. **Data-Geometry Mismatch**: Local data uses codes that don't map cleanly to GADM regions
2. **Boundary Changes**: Local source has more recent boundary definitions (e.g., LGA mergers)
3. **Name Discrepancies**: Significant name differences cause join failures
4. **Geometry Included**: Local source provides geometry bundled with data (like ABS GeoPackage)
5. **Official Boundaries Available**: Local source provides pre-defined parent boundaries

**Important: Aggregation Artifacts**

GADM only stores geometry at the deepest admin level. Parent boundaries (states, provinces) are created by **aggregating child polygons** using `unary_union()`. This can introduce:
- Visual line artifacts from imperfect merges
- Sliver gaps between children that show through
- Inconsistencies at coastlines and complex borders

Local statistical agencies (ABS, StatsCan, Eurostat) provide **official parent boundaries** that don't have these aggregation issues. Their state/province/region geometry is authoritative, not derived.

```
GADM Approach:           Local Source Approach:

Counties -> merge ->     Counties (official)
  State boundary            +
  (artifacts possible)   State boundary (official, separate)
                         (clean, no artifacts)
```

### When to Keep GADM

Keep GADM geometry when:

1. **No Local Alternative**: Country doesn't have accessible open boundary data
2. **Good Match**: GADM boundaries align well with local data (like USA counties)
3. **Unified Hierarchy**: Need consistent admin levels across neighboring countries
4. **Simpler Maintenance**: Single source easier to update than multiple local sources

### Australia: ABS vs GADM Details

**Comparison Results:**
```
ABS LGAs (2024):    547 regions
GADM admin_2 (2021): 564 regions
Exact name matches:  480 (87.7%)
ABS-only names:      67 (merged LGAs, renamed)
GADM-only names:     78 (split LGAs, outdated names)
```

**Key Differences:**
- LGA mergers since 2021 (GADM outdated)
- Name variations: "Augusta-Margaret River" vs "Augusta Margaret River"
- ABS disambiguates duplicates: "Bayside (NSW)" vs "Bayside (Vic.)"
- GADM includes tiny external territories separately

**Decision**: Use ABS geometry - it's bundled in the GeoPackage, matches our population data exactly, and is more current.

**Implementation**:
```python
# Extract geometry from ABS GeoPackage
gdf = gpd.read_file("Raw data/abs/ERP_2024_LGA/32180_ERP_2024_LGA_GDA2020.gpkg")

# Convert to loc_id format
AUS_STATE_TO_ABBR = {1: "NSW", 2: "VIC", 3: "QLD", 4: "SA", 5: "WA", 6: "TAS", 7: "NT", 8: "ACT", 9: "OT"}
gdf["loc_id"] = gdf.apply(lambda r: f"AUS-{AUS_STATE_TO_ABBR[r['state_code_2021']]}-{r['lga_code_2024']}", axis=1)
```

### Canada: StatsCan vs GADM Details

**Comparison Results:**
```
StatsCan CSDs (2021): 5,161 municipalities
GADM admin_2:         ~5,000 regions
Name match:           TBD (need boundary file download)
```

**Key Challenge**: Census data doesn't include geometry. Need separate download from:
https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/index2021-eng.cfm

**Decision**: Download StatsCan boundary files - they match the census data DGUIDs exactly.

**Implementation** (when boundaries downloaded):
```python
# StatsCan uses DGUID for unique identification
dguid = "2021A00051001105"  # Example: Portugal Cove South, NL
province_code = dguid[9:11]  # "10" -> NL
csd_code = dguid[11:]        # "01105"

CANADA_PROV_TO_ABBR = {"10": "NL", "11": "PE", "12": "NS", "13": "NB", "24": "QC",
                        "35": "ON", "46": "MB", "47": "SK", "48": "AB", "59": "BC",
                        "60": "YT", "61": "NT", "62": "NU"}
loc_id = f"CAN-{CANADA_PROV_TO_ABBR[province_code]}-{csd_code}"
```

### Europe: Eurostat GISCO vs GADM Details

**Comparison Results:**
```
Eurostat NUTS 3: 1,612 regions across 37 countries
GADM admin_2:    Varies by country (different hierarchies)
```

**Key Challenge**:
- NUTS system is EU-specific, doesn't map 1:1 to national admin divisions
- GADM uses national admin structures (Kreise in Germany, Departements in France)
- NUTS 3 may combine or split national admin units

**Decision**: Use GISCO boundaries for NUTS data. Download from:
- **GISCO Distribution Service**: https://gisco-services.ec.europa.eu/distribution/v2/nuts/download/
- **Eurostat GISCO Main Page**: https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/territorial-units-statistics
- **Nuts2json (GitHub)**: https://github.com/eurostat/Nuts2json - GeoJSON/TopoJSON formats

**Available Formats**:
- Shapefiles (SHP)
- GeoJSON
- TopoJSON (smaller, web-optimized)
- Multiple scale options: 1M, 3M, 10M, 20M, 60M

**NUTS Hierarchy**:
- NUTS 0: Countries (37 EU/EFTA countries)
- NUTS 1: Major socio-economic regions (~100)
- NUTS 2: Basic regions for regional policy (~300)
- NUTS 3: Small regions for diagnosis (~1,500)

**Implementation**:
```python
# NUTS codes are self-describing: first 2 chars = country
nuts_code = "DE300"  # Berlin
NUTS_COUNTRY_TO_ISO3 = {"DE": "DEU", "FR": "FRA", "IT": "ITA", ...}
iso3 = NUTS_COUNTRY_TO_ISO3[nuts_code[:2]]
loc_id = f"{iso3}-{nuts_code}"  # "DEU-DE300"
```

**Recommended Approach for Eurostat Data**:
1. Download NUTS boundaries from GISCO (1M scale for detail, 10M for smaller files)
2. Convert to parquet with loc_ids matching Eurostat data format
3. Store in `countries/{ISO3}/geometry.parquet` for each European country
4. Eurostat data joins directly without crosswalk needed

### Geometry File Precedence

Three-tier system with crosswalk support:

```
1. countries/{ISO3}/geometry.parquet  <- Local source (preferred, uses local loc_ids like NUTS)
2. countries/{ISO3}/crosswalk.json    <- Maps local loc_ids to GADM loc_ids (if no local geometry)
3. geometry/{ISO3}.parquet            <- GADM fallback (global baseline)
```

**Resolution Order:**
1. **Direct match in country geometry**: Data loc_id matches country geometry loc_id -> use it
2. **Crosswalk fallback**: Data loc_id doesn't match, check crosswalk to translate -> use GADM geometry
3. **Direct GADM fallback**: Data loc_id is already GADM-style -> use GADM geometry directly

When a country gets its own data folder (with converters, better data), we include local geometry there. The `geometry/` folder stays pure GADM as the global fallback.

### Crosswalk Files

When data uses a different loc_id system (like NUTS codes for Eurostat) but we don't have matching geometry yet, a crosswalk file maps between systems.

**Location**: `countries/{ISO3}/crosswalk.json`

**Format**:
```json
{
  "source_system": "nuts",
  "target_system": "gadm",
  "mappings": {
    "FRA-FR1": "FRA-IF",
    "FRA-FRB": "FRA-CE",
    "FRA-FRC": "FRA-BF",
    "DEU-DE1": "DEU-BW",
    "DEU-DE2": "DEU-BY"
  },
  "notes": "NUTS to GADM mapping. Some NUTS regions span multiple GADM regions."
}
```

**When to use crosswalk vs. new geometry**:
- **Use crosswalk**: When NUTS/local regions roughly align with GADM regions (quick fix)
- **Download new geometry**: When local regions are fundamentally different or more accurate is needed

**Crosswalk limitations**:
- NUTS regions may not align 1:1 with GADM regions (aggregation/splitting)
- Boundaries may differ slightly at borders
- For best results, download official geometry from the source agency

```python
def get_geometry_for_loc_id(loc_id, iso3=None):
    """
    Get geometry for a loc_id using 3-tier fallback.

    1. Try country geometry (local loc_ids like NUTS)
    2. Try crosswalk to translate loc_id, then use GADM
    3. Try GADM directly (loc_id is already GADM-style)
    """
    if iso3 is None:
        iso3 = loc_id.split('-')[0]

    # Tier 1: Country-specific geometry (preferred)
    country_geom_path = f"countries/{iso3}/geometry.parquet"
    if Path(country_geom_path).exists():
        gdf = pd.read_parquet(country_geom_path)
        match = gdf[gdf['loc_id'] == loc_id]
        if len(match) > 0:
            return match.iloc[0]

    # Tier 2: Crosswalk translation -> GADM
    crosswalk_path = f"countries/{iso3}/crosswalk.json"
    if Path(crosswalk_path).exists():
        with open(crosswalk_path) as f:
            crosswalk = json.load(f)
        gadm_loc_id = crosswalk.get('mappings', {}).get(loc_id)
        if gadm_loc_id:
            gadm_path = f"geometry/{iso3}.parquet"
            if Path(gadm_path).exists():
                gdf = pd.read_parquet(gadm_path)
                match = gdf[gdf['loc_id'] == gadm_loc_id]
                if len(match) > 0:
                    return match.iloc[0]

    # Tier 3: Direct GADM fallback
    gadm_path = f"geometry/{iso3}.parquet"
    if Path(gadm_path).exists():
        gdf = pd.read_parquet(gadm_path)
        match = gdf[gdf['loc_id'] == loc_id]
        if len(match) > 0:
            return match.iloc[0]

    return None
```

### loc_id Systems and Migration

**The Two loc_id Systems**

GADM and local sources use different identification codes:

```
GADM loc_ids (global baseline):     Local loc_ids (country-specific):
  AUS-NS-11730                        AUS-NSW-10050
  CAN-QC-2466023                      CAN-QC-66023
  CHN-BJ-12345                        CHN-Beijing-110000
```

GADM uses its internal GID/HASC codes. Local sources use codes that citizens recognize (LGA codes, FIPS, postal regions). **Local loc_ids are preferred** because they're intuitive to locals and match the data source exactly.

**Migration When Local Geometry Arrives**

When a country transitions from GADM to local geometry:

```
Phase 1: Initial import (no local geometry)
  -> Data uses GADM loc_ids
  -> Links to geometry/{ISO3}.parquet

Phase 2: Local geometry obtained
  -> Create countries/{ISO3}/geometry.parquet with local loc_ids
  -> **Re-run all converters** to migrate data to local loc_ids
  -> All data now uses local loc_ids

Phase 3: Unified system
  -> All data uses local loc_ids
  -> GADM fallback catches any stragglers
```

**The goal is one loc_id system per country** - local when available. When adopting local geometry, re-run converters to migrate existing data.

**Dual loc_id Lookup (Safety Net)**

The geometry lookup checks both systems as a safety net:

```python
def get_geometry_for_loc_id(loc_id):
    """Find geometry for loc_id - tries local first, then GADM fallback."""
    iso3 = loc_id.split('-')[0]

    # Try local geometry (preferred)
    local_geom = load_country_geometry(iso3)
    if local_geom is not None:
        match = local_geom[local_geom['loc_id'] == loc_id]
        if len(match) > 0:
            return match.iloc[0]

    # Fallback to GADM
    gadm_geom = load_gadm_geometry(iso3)
    if gadm_geom is not None:
        match = gadm_geom[gadm_geom['loc_id'] == loc_id]
        if len(match) > 0:
            return match.iloc[0]

    return None
```

This handles:
- Data that wasn't migrated yet
- Edge cases during transition periods
- Niche datasets that are hard to update

**But the fallback is a safety net, not the design.** Strive to have all data use the same loc_id system.

**Current Status:**
| Country | Local Geometry | Source | Features |
|---------|---------------|--------|----------|
| AUS | `countries/AUS/geometry.parquet` | ABS LGA 2024 | 547 |
| CAN | (pending) | StatsCan CSD 2021 | 5,161 |
| USA | Uses GADM | GADM matches TIGER well | 3,144 |

### TODO: Geometry Downloads Needed

| Source | URL | Priority | Notes |
|--------|-----|----------|-------|
| **Eurostat GISCO NUTS** | https://gisco-services.ec.europa.eu/distribution/v2/nuts/download/ | **High** | Required for Eurostat data to display. Download NUTS 2024 at 10M scale. |
| **StatsCan CSD Boundaries** | https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/index2021-eng.cfm | High | Needed for Canadian census data |
| **GADM v5** | https://gadm.org (when released) | Medium | Update global fallback when available |

**NUTS Geometry Downloader TODO**:
1. Create `data_converters/downloaders/download_nuts_geometry.py`
2. Download NUTS 2024 boundaries from GISCO (GeoJSON format, 10M scale)
3. Split by country and convert to parquet
4. Store in `countries/{ISO3}/geometry.parquet` with NUTS-style loc_ids
5. Eurostat data will then join directly without crosswalk

### Natural Earth (Alternative)

- **URL**: naturalearthdata.com
- **Coverage**: Admin boundaries, populated places, physical features
- **Scales**: 1:10m (detailed), 1:50m (medium), 1:110m (small)
- **License**: Public domain
- **Best for**: Simplified country borders, physical features

### geoBoundaries (Alternative)

- **URL**: geoboundaries.org
- **Coverage**: Open admin boundaries, simplified versions
- **License**: Fully open (better than GADM for commercial)
- **Notes**: Good alternative with pre-simplified versions

### US Census TIGER/Line (US Detail)

- **URL**: census.gov/geographies/mapping-files.html
- **Coverage**: States, counties, ZCTAs, census tracts, blocks
- **License**: Public domain
- **Notes**: Most detailed US boundaries, updated annually

---

## Reference Data Files

The `mapmover/reference/` folder contains modular JSON files for geographic metadata. This keeps `conversions.json` lean while allowing rich country-specific data.

### File Status

| File | Purpose | Status | Used By |
|------|---------|--------|---------|
| `conversions.json` | Regional groupings (56 groups), region aliases, fallback coordinates | Complete | geography.py |
| `reference/iso_codes.json` | ISO 3166-1 alpha-2/alpha-3 mappings (207 countries) | Complete | geography.py, name_standardizer.py, order_executor.py |
| `reference/admin_levels.json` | Country-specific admin level names + synonyms (40+ countries) | Complete | geometry_handlers.py |
| `reference/country_metadata.json` | Capitals (207), currencies, timezones | Capitals complete | Not yet wired (TODO) |
| `reference/geographic_features.json` | Rivers, mountains, lakes, deserts, islands | Structure only | Not yet wired (TODO) |
| `reference/languages.json` | ISO 639-1 codes, country-language mappings | Codes complete | Not yet wired (TODO) |
| `reference/query_synonyms.json` | Metric/time/comparison synonyms for NLP | Partial | Not yet wired (TODO) |
| `reference/usa_admin.json` | US-specific admin data | Complete | order_taker.py, order_executor.py |

### What's in conversions.json

Core lookups that need fast access:
- `regional_groupings` - 56 groups (WHO regions, income levels, trade blocs)
- `region_aliases` - "Europe" -> "WHO_European_Region"
- `limited_geometry_countries` - Fallback coordinates for microstates

### Adding Reference Data

To add currencies to country_metadata.json:
```json
{
  "currencies": {
    "USA": ["USD", "$", "US Dollar"],
    "GBR": ["GBP", "L", "British Pound"],
    "EUR_ZONE": ["EUR", "E", "Euro"]
  }
}
```

To add country-language mappings to languages.json:
```json
{
  "country_languages": {
    "USA": ["en", "es"],
    "CAN": ["en", "fr"],
    "CHE": ["de", "fr", "it", "rm"]
  }
}
```

---

## Alternative Geographic Frameworks

Beyond the standard admin hierarchy (country > state > county), other frameworks exist for specialized data.

### Statistical and Functional Regions

- **Metropolitan Statistical Areas (MSAs)**: Cross city/county boundaries, defined by economic ties
- **OECD Functional Urban Areas**: Globally standardized metropolitan definitions
- **Eurostat NUTS Regions**: Hierarchical system for Europe (NUTS1 > NUTS2 > NUTS3)

### Grid-Based Systems

- **H3 Hexagonal Grids**: Uber's hierarchical geospatial indexing
- **Lat/Long Grid Cells**: Climate data (1x1 or 0.5x0.5 degree cells)
- **MGRS/UTM Zones**: Military Grid Reference System

### Natural Boundaries

- **Watershed/River Basins**: Water resource and environmental data (use sibling layer approach)
- **Ecoregions/Biomes**: Biodiversity and conservation
- **Climate Zones**: Koppen climate classification

### Implementation Notes

Grid-based and natural boundary data would use the **sibling layer approach** documented above:
- Watersheds crossing state lines -> level-1 siblings in country parquet
- Climate zones crossing countries -> global_entities.parquet

---

## Edge Cases and Special Geographies

Data that doesn't fit standard hierarchies:

### Transboundary Phenomena

- Air quality/pollution (doesn't respect borders)
- Ocean data and maritime boundaries
- Cross-border river systems (Mekong, Danube)

### Special Jurisdictions

- Indigenous/tribal lands (may overlap multiple admin units)
- Special economic zones
- Exclusive Economic Zones (EEZ) in oceans
- Disputed territories
- Extraterritorial areas (embassies, military bases)

### Point-Based Data

- Weather stations
- Seismic monitoring stations
- Shipping routes

For these cases, consider:
1. Store in global_entities.parquet with appropriate `type` column
2. Use relationships.json to map membership (which countries contain which features)
3. For point data, use centroid-only entries (no polygon geometry)

---

## TODO: Reference Data Gaps

### Data to Add

1. **country_metadata.json**
   - Add currencies (ISO 4217 codes)
   - Add primary timezones (IANA database)

2. **geographic_features.json**
   - Add major rivers (from Natural Earth or GeoNames)
   - Add mountain ranges with spanning countries
   - Add major lakes with bordering countries

3. **languages.json**
   - Add country-language mappings (official + major spoken)
   - Source: Ethnologue or Wikipedia

4. **query_synonyms.json**
   - Expand based on actual user query logs
   - Add country name aliases ("USA", "America", "United States")

### Code to Wire

Files with data but not yet used by the application:

1. **country_metadata.json** - Capitals exist but not displayed in popups
2. **query_synonyms.json** - Could enhance LLM query interpretation in order_taker.py
3. **geographic_features.json** - Needs data first, then wire to geometry/relationships system
4. **languages.json** - Needs country mappings, could display in popups

---

## Known Issues: Geometry Artifacts

### Visual Line Artifacts (2026-01-01)

Some countries show faint internal lines when viewing aggregated geometry (level 0 country view showing lines from level 1 boundaries). This has been investigated but not fully resolved.

**What We Tested:**

1. **Sliver Cleanup Script** (`build/geometry/cleanup_slivers.py`)
   - Removed 2,072,372 sliver interior holes and 173,427 sliver polygons globally
   - Uses 2x tolerance threshold based on admin level (per GEOMETRY.md tolerances)
   - Improved performance ("map is distinctly snappier")
   - Did NOT fully fix the visual line artifacts

2. **Aggressive buffer(0) Cleanup** (`build/geometry/aggregate_geometry.py --cleanup`)
   - Applied buffer(0) -> buffer(0.0005) -> buffer(-0.0005) -> buffer(0) sequence
   - Attempted to snap vertices and remove self-intersections
   - Mixed results, some artifacts remain

3. **Stroke Opacity for Siblings** (`static/modules/map-adapter.js`)
   - Added `getFocalStrokeOpacityExpression()` to hide strokes between sibling features
   - Works when viewing multiple features (e.g., provinces at level 1)
   - Does NOT fix artifacts within a single merged polygon geometry

**Root Cause Hypothesis:**

The artifacts appear to be internal geometry issues from the `unary_union()` operation when merging child polygons to create parent boundaries. The merged polygon retains vestigial edge data that renders as faint lines.

**Affected Countries:**

- Canada (Manitoba, Nunatsiavut, BC/Yukon border)
- Algeria (internal province boundaries showing through)
- Likely others with complex coastlines or many child regions

**Potential Future Fixes:**

- Try different simplification tolerances after merge
- Use Shapely's `make_valid()` more aggressively
- Consider buffering during merge, not just cleanup
- Investigate if MapLibre has anti-aliasing issues with complex polygons

---

## Related Files

### Documentation

| File | Purpose |
|------|---------|
| [data_pipeline.md](data_pipeline.md) | Data source catalog, metadata schema, folder structure |
| [data_import.md](data_import.md) | Quick reference for creating data converters |
| [MAPPING.md](MAPPING.md) | Frontend map rendering and display |

### Code Files

| File | Purpose |
|------|---------|
| `mapmover/process_gadm.py` | Build geometry from GADM source |
| `mapmover/post_process_geometry.py` | Aggregate parents, compute bboxes, children counts |
| `mapmover/name_standardizer.py` | Name-to-loc_id conversion |
| `mapmover/conversions.json` | Regional groupings (56 groups: WHO, income, trade blocs) |
| `mapmover/reference/` | Modular reference data (admin levels, ISO codes, metadata) |

### Data Workflow Integration

When adding new data sources, the geometry link is critical:

```
1. Geometry exists first (loc_id is source of truth)
       |
       v
2. Converter creates parquet with matching loc_id format
       |
       v
3. finalize_source() generates metadata.json
       |
       v
4. Data joins to geometry via loc_id at query time
```

See [data_pipeline.md - Adding New Data Sources](data_pipeline.md#adding-new-data-sources) for the complete converter workflow.

---

*Last Updated: 2026-01-07*
