# Geometry System

The geometry layer is the **source of truth** for all locations. Every indicator dataset joins to geometry via `loc_id`.

**Builder**: `mapmover/process_gadm.py`
**Output**: `county-map-data/geometry/`
**Source**: GADM 3.6 (gadm36.gpkg)

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

## Cross-Boundary Entities

Some geographic features (watersheds, river basins, lakes) cross administrative boundaries. These are handled as **flat siblings at the level of their highest parent**.

### The Rule

If a feature crosses boundaries at admin level N, make it a sibling at level N-1.
If it crosses country boundaries, it becomes a global entity (admin_level=0, no parent).

### Examples

| Feature | Crosses | Parent | loc_id | admin_level |
|---------|---------|--------|--------|-------------|
| Lake Tahoe watershed | CA/NV (states) | USA | `USA-TAHOE` | 1 |
| Colorado River basin | 7 states | USA | `USA-COLORADO-BASIN` | 1 |
| Great Lakes | USA/CAN (countries) | (none) | `GREATLAKES` | 0 |
| Amazon basin | 9 countries | (none) | `AMAZON` | 0 |

---

## Geometry Files

Location: `county-map-data/geometry/`

### File Structure

| File | Content | Count |
|------|---------|-------|
| `global.csv` | All countries (admin_0 only) | 257 |
| `country_coverage.json` | Drill-down metadata | - |
| `{ISO3}.parquet` | All admin levels per country | 257 files |

**Total**: 257 countries, 416,066 locations across all admin levels.

### Parquet Schema

| Column | Type | Description |
|--------|------|-------------|
| `loc_id` | string | Canonical location ID |
| `parent_id` | string | Parent location ID (null for countries) |
| `admin_level` | int | 0=country, 1=state, 2=county, etc. |
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

- GADM gpkg file in `county-map-data/Raw data/gadm36.gpkg` (1.9GB)
- Python with geopandas, pyarrow

### Running the Builder

```bash
python mapmover/process_gadm.py
```

This will:
1. Read all layers from GADM gpkg
2. Generate loc_ids using HASC codes where available
3. Build parent-child relationships
4. Simplify geometries for web display
5. Output one parquet per country to `geometry/`
6. Generate `global.csv` with country-level geometries
7. Generate `country_coverage.json` with drill-down metadata

### When to Rebuild

- New GADM version released
- loc_id format changes
- Need to add cross-boundary entities

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

*Last Updated: 2024-12-21*
