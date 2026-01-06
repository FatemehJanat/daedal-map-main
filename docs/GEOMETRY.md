# Geometry System

The geometry layer is the **source of truth** for all locations. Every indicator dataset joins to geometry via `loc_id`.

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

| Level | Tolerance | Precision | Use Case |
|-------|-----------|-----------|----------|
| Countries | 0.01 | ~1 km | World map view |
| States/Regions | 0.001 | ~100 m | Country zoom |
| Counties | 0.001 | ~100 m | State zoom |
| Cities/Districts | 0.0001 | ~10 m | County zoom |

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
| [data_pipeline.md](data_pipeline.md) | Data source catalog, converter standards, finalize_source() workflow |
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

*Last Updated: 2026-01-05*
