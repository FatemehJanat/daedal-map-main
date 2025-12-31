# Geometry System

The geometry layer is the **source of truth** for all locations. Every indicator dataset joins to geometry via `loc_id`.

**Builder**: `mapmover/process_gadm.py`
**Output**: `county-map-data/geometry/`
**Source**: GADM 4.1 (gadm_410.gpkg)

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
AMAZON-BASIN        | 0     | river     | Amazon River Basin
NILE-WATERSHED      | 0     | river     | Nile Watershed
MEDITERRANEAN       | 0     | sea       | Mediterranean Sea
EU                  | 0     | political | European Union
SAHEL               | 0     | climate   | Sahel Region
ARCTIC              | 0     | climate   | Arctic Circle
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
| sea | Seas, oceans, maritime zones | Mediterranean, Baltic Sea |
| climate | Climate zones, biomes | Arctic Circle, Sahel, Tropics |

**Political/Economic:**

| Type | Description | Examples |
|------|-------------|----------|
| political | Political entities with geometry | EU, NATO (if mapped) |
| economic | Economic zones | Trade corridors, special economic zones |

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
| `type` | string | Entity type: admin, river, hydro, sea, climate, political, economic |
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

---

*Last Updated: 2025-12-30*
