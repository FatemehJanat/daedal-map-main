# Data Import Reference

Quick reference for importing new data sources using the unified converter system.

For detailed documentation see:
- [data_pipeline.md](data_pipeline.md) - Full pipeline documentation
- [geometry.md](geometry.md) - Geometry system details

---

## Data Architecture Philosophy

All data in this system is designed to be **interoperable**. Conceptually, everything fits into one unified table:

```
| loc_id        | year | pop    | gdp    | earthquakes | drought_weeks | ... |
|---------------|------|--------|--------|-------------|---------------|-----|
| USA-CA-6037   | 2020 | 10.0M  | 500B   | 12          | 8             | ... |
| USA-CA-6037   | 2021 | 9.8M   | 520B   | 8           | 15            | ... |
| CAN-ON-35001  | 2020 | 50000  | 2B     | 0           | NULL          | ... |
| AUS-NSW-10050 | 2020 | 25000  | 1B     | 1           | NULL          | ... |
```

**Key principle**: `(loc_id, year)` is the universal join key. All metrics are columns.

**Note on loc_id sources**: Some countries have dual loc_id systems:
- **Country-specific**: Official boundaries (ABS LGAs, StatsCan CSDs) stored in `countries/{ISO}/geometry.parquet`
- **GADM fallback**: Global boundaries in `geometry/{ISO}.parquet`

The system uses graceful fallback - country-specific geometry takes priority when present. This means loc_ids may differ between sources, but within each country's data ecosystem, they're consistent.

This enables:
- **Column portability**: Move population from census to geometry file
- **Dataset merging**: Combine drought aggregates with rainfall aggregates
- **Custom exports**: Future admin dashboard lets users pick locations + years + metrics
- **No overlaps**: loc_id ensures uniqueness across all 400K+ GADM locations

---

## New Source Checklist

When importing a new data source, verify these requirements:

| Check | Requirement | Why |
|-------|-------------|-----|
| 1. loc_id match | All location codes use `{ISO3}[-{admin1}[-{admin2}]]` format | Universal join key |
| 2. Long format | Time-series uses rows (loc_id, year, metric), NOT columns (loc_id, metric_2020, metric_2021) | Enables time slider, joins |
| 3. Column analysis | Decide which metrics to keep, rename, or combine | Clean schema |
| 4. No duplicates | One row per (loc_id, year) in aggregates | Clean joins |
| 5. Null handling | Missing data as NULL, not 0 or special values | Accurate analysis |
| 6. No redundant cols | Remove state, county, name, FIPS columns | Derivable from loc_id |
| 7. Source registry | Add to `build/catalog/source_registry.py` with URL, license, description | Clickable source links in UI |

**IMPORTANT: Source Registry Entry**

Every new source MUST be registered in `build/catalog/source_registry.py` before running the metadata generator. The registry provides:
- `source_name` - Human-readable name shown in UI
- `source_url` - Clickable link to original data source
- `license` - Data license information
- `description` - Brief description of the dataset
- `category` - Data category (hazard, demographic, environment, etc.)
- `topic_tags` / `keywords` - For search and discovery

Without a registry entry, metadata will have empty/default values and source links won't work in the UI.

**Important: Column Rules**

Output parquet should ONLY contain:
- `loc_id` - Location identifier
- `year` - Time dimension
- `[numeric metrics]` - Data columns

Do NOT include:
- `state`, `county`, `name` - Derivable from loc_id (e.g., `USA-NC-001` -> state is `NC`)
- `STCOFIPS`, `GEOID`, `fips` - Redundant with loc_id
- `STATE`, `COUNTY`, `region` - Stored in geometry, not data

**Exception**: Event data (earthquakes, hurricanes) uses different schema with `event_id`, `timestamp`, etc.

---

## Adding a New Source

**Step 1: Find a similar existing converter to copy**

Before creating anything new, identify which existing converter best matches your data:

| If your data has... | Copy this converter |
|---------------------|---------------------|
| Point events with lat/lon (earthquakes, incidents) | `convert_usgs_earthquakes.py` or `convert_canada_earthquakes.py` |
| Track/trajectory data (storms, paths) | `convert_hurdat2.py` |
| Multiple related tables (locations + events) | `convert_volcano.py` or `convert_tsunami.py` |
| Polygon/perimeter data (fire boundaries, zones) | `convert_mtbs.py` |
| Pre-aggregated statistics (no events file) | Create minimal converter (see below) |

**Step 2: Modify the copy for your source**

1. Copy the chosen converter to `data_converters/converters/convert_{source}.py`
2. Update configuration paths (`RAW_DATA_DIR`, `OUTPUT_DIR`, `SOURCE_ID`)
3. Modify `load_raw_data()` for your input format
4. Adjust column mappings in `create_events_dataframe()` and `create_aggregates()`
5. Update statistics/metadata sections

**Step 3: Register and finalize**

1. Register in `build/catalog/source_registry.py` for auto-finalization
2. Run converter to generate parquet files
3. Verify output with `finalize_source`

---

## Base Utilities

All converters import from `data_converters/base/`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_converters.base import (
    # Constants
    USA_STATE_FIPS,          # {'01': 'AL', '02': 'AK', ...}
    CAN_PROVINCE_ABBR,       # {'10': 'NL', '11': 'PE', ...}
    TERRITORIAL_WATERS_DEG,  # 0.2 (~12 nautical miles)

    # Geo utilities
    load_geometry_parquet,   # Load county/division boundaries
    spatial_join_3pass,      # Full 3-pass geocoding
    create_point_gdf,        # Create GeoDataFrame from lat/lon
    get_water_body_loc_id,   # Assign ocean/sea codes

    # Parquet utilities
    save_parquet,            # Standardized parquet saving
)
from build.catalog.finalize_source import finalize_source
```

---

## Admin Levels

All data uses standardized admin levels that work across all countries:

| Level | Description | Examples |
|-------|-------------|----------|
| admin_0 | Country | USA, CAN, AUS, DEU |
| admin_1 | State/Province/Region | USA-CA, CAN-BC, AUS-NSW, DEU-BY |
| admin_2 | County/District/LGA | USA-CA-6037, CAN-BC-5915, AUS-NSW-10050 |

This standardization means:
- **No country-specific terminology** in code (not "county", "LGA", "CSD", "NUTS3")
- **Consistent API** - `admin_level=2` works everywhere
- **Scalable** - Works for any country without code changes

---

## loc_id Format

All locations use standardized loc_id format based on admin levels:

| Admin Level | Format | Example |
|-------------|--------|---------|
| admin_0 | `{ISO3}` | `USA`, `CAN`, `AUS` |
| admin_1 | `{ISO3}-{code}` | `USA-CA`, `CAN-BC`, `AUS-NSW` |
| admin_2 | `{ISO3}-{code}-{code}` | `USA-CA-6037`, `CAN-BC-5915` |
| Water | `X{code}` | `XOP` (Pacific), `XOA` (Atlantic) |

**Water Body Codes:**
- `XOP` - Pacific Ocean
- `XOA` - Atlantic Ocean
- `XON` - Arctic Ocean
- `XOI` - Indian Ocean
- `XSG` - Gulf of Mexico / Gulf of St. Lawrence
- `XSC` - Caribbean Sea
- `XSH` - Hudson Bay
- `XSB` - Bering Sea

---

## Geometry File Standards

When creating country-specific geometry files in `countries/{ISO}/geometry.parquet`, use the **same column names** as the GADM files in `geometry/{ISO}.parquet`:

**Required columns (must match exactly):**

| Column | Type | Description |
|--------|------|-------------|
| `loc_id` | string | Location identifier (e.g., `AUS-NSW-10050`) |
| `name` | string | Human-readable name |
| `admin_level` | int | Admin level (0=country, 1=state, 2=county) |
| `parent_id` | string | Parent location's loc_id |
| `geometry` | string | GeoJSON string (e.g., `{"type": "Polygon", ...}`) |

**IMPORTANT**:
- Use `parent_id`, NOT `parent_loc_id`. This ensures consistent column naming across all geometry sources and prevents join failures.
- Use **GeoJSON strings**, NOT WKB bytes. WKB bytes cause JSON serialization errors at runtime.

**Optional columns (included in GADM files):**
- `centroid_lon`, `centroid_lat` - Centroid coordinates
- `bbox_min_lon`, `bbox_min_lat`, `bbox_max_lon`, `bbox_max_lat` - Bounding box
- `children_count`, `descendants_count` - Hierarchy counts
- `has_polygon` - Boolean for geometry presence

**Geometry Priority:**
The system loads geometry in this order:
1. `countries/{ISO}/geometry.parquet` - Country-specific (preferred, matches data loc_ids)
2. `geometry/{ISO}.parquet` - GADM fallback (global coverage)

This allows country-specific sources (ABS, StatsCan) to use their official boundaries while falling back to GADM for countries without custom geometry.

---

## Standard Converter Structure

Every converter follows this pattern:

```python
"""
Convert {SOURCE} data to parquet format.

Creates output files:
1. events.parquet - Individual events
2. {COUNTRY}.parquet - Region-year aggregated statistics

Uses unified base utilities for spatial join and water body assignment.

Usage:
    python convert_{source}.py
"""

# Configuration
RAW_DATA_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/Raw data/{source}")
GEOMETRY_PATH = Path("C:/Users/Bryan/Desktop/county-map-data/geometry/{COUNTRY}.parquet")
OUTPUT_DIR = Path("C:/Users/Bryan/Desktop/county-map-data/countries/{COUNTRY}/{source_id}")
SOURCE_ID = "{source_id}"


def load_geometry():
    """Load boundaries using base utility."""
    return load_geometry_parquet(GEOMETRY_PATH, admin_level=2, geometry_format='geojson')


def load_raw_data():
    """Load source-specific raw data."""
    # Custom parsing logic here
    pass


def process_events(df, geometry_gdf):
    """Process events with spatial join."""
    # Create point geometries
    gdf = create_point_gdf(df, lat_col='latitude', lon_col='longitude')

    # 3-pass spatial join
    gdf = spatial_join_3pass(
        gdf,
        geometry_gdf,
        loc_id_col='loc_id',
        water_body_region='usa'  # or 'canada', 'global'
    )
    return gdf


def create_events_dataframe(gdf):
    """Create standardized events DataFrame."""
    # Select and rename columns
    pass


def create_aggregates(events):
    """Create region-year aggregates."""
    # Group by loc_id, year and aggregate
    pass


def main():
    print("=" * 60)
    print("{Source} Converter")
    print("=" * 60)

    # Load geometry
    geometry_gdf = load_geometry()

    # Load and process data
    df = load_raw_data()
    gdf = process_events(df, geometry_gdf)

    # Create outputs
    events = create_events_dataframe(gdf)
    aggregates = create_aggregates(events)

    # Save outputs
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    events_path = OUTPUT_DIR / "events.parquet"
    save_parquet(events, events_path, description="events")

    agg_path = OUTPUT_DIR / f"{COUNTRY}.parquet"
    save_parquet(aggregates, agg_path, description="aggregates")

    # Finalize
    print("\n" + "=" * 60)
    print("Finalizing source...")
    print("=" * 60)

    try:
        finalize_source(
            parquet_path=str(agg_path),
            source_id=SOURCE_ID,
            events_parquet_path=str(events_path)
        )
    except ValueError as e:
        print(f"  Note: {e}")
        print(f"  Add '{SOURCE_ID}' to source_registry.py to enable auto-finalization")

    print("\n" + "=" * 60)
    print("COMPLETE!")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

## 3-Pass Spatial Join

The `spatial_join_3pass()` function handles all geocoding:

1. **Pass 1: Point-in-polygon** - Strict match for points inside boundaries
2. **Pass 2: Nearest neighbor** - Match coastal points within territorial waters (0.2 deg / ~12nm)
3. **Pass 3: Water body codes** - Assign ocean/sea codes for offshore points

```python
gdf = spatial_join_3pass(
    points_gdf,              # GeoDataFrame with point geometries
    polygons_gdf,            # GeoDataFrame with boundaries (must have loc_id)
    loc_id_col='loc_id',     # Column name for location ID
    territorial_waters_deg=0.2,  # Distance threshold for pass 2
    water_body_region='usa', # 'usa', 'canada', 'australia', 'global'
    verbose=True             # Print progress
)
```

---

## Output File Structure

```
countries/{COUNTRY}/{source_id}/
    events.parquet       # Individual events (optional)
    {COUNTRY}.parquet    # Region-year aggregates (required)
    metadata.json        # Auto-generated by finalize_source
```

**events.parquet** - Individual records (optional for pre-aggregated data):
- `event_id` - Unique identifier
- `loc_id` - Location code
- `year` - Event/record year
- `lat`, `lon` - Coordinates (if applicable)
- Source-specific columns (varies by data type)

**{COUNTRY}.parquet** - Region-year aggregates (required):
- `loc_id` - Location code
- `year` - Year
- Aggregated statistics (counts, sums, means, etc.)

**IMPORTANT: Use Long Format for Time-Series Data**

All time-series data MUST use long format (one row per location-year), NOT wide format (year as columns):

```
CORRECT (Long Format):
loc_id          year    total_pop
USA-CA-6037     2020    10014009
USA-CA-6037     2021    9829544
USA-CA-6037     2022    9721138

WRONG (Wide Format):
loc_id          pop_2020    pop_2021    pop_2022
USA-CA-6037     10014009    9829544     9721138
```

Long format enables:
- Consistent time slider functionality across all datasets
- Easy filtering by year range
- Uniform data loading in frontend
- Simpler aggregation queries

---

## Hierarchical Aggregation

When source data is only available at a detailed level (e.g., admin_2 LGAs), **auto-aggregate up to parent levels** for better visualization at country/state scale.

> **See also**: [data_pipeline.md - Hierarchical Aggregation Scripts](data_pipeline.md#hierarchical-aggregation-scripts) for NUTS hierarchy details and the `aggregate_eurostat_to_country.py` script.

### Why Aggregate?

Without aggregation:
- User asks for "Australia population" -> gets 547 tiny LGAs
- Choropleth dominated by one outlier (Brisbane ~1.4M), everything else dull blue
- Hard to see state-level patterns

With aggregation:
- Same query -> shows 8 states with meaningful variation
- User can drill down to LGAs if needed
- Better UX at every zoom level

### Aggregation Pattern

When your source data has only one admin level, create parent levels:

```python
def aggregate_to_parent_levels(df, geometry_df):
    """
    Aggregate admin_2 data up to admin_1 and admin_0 levels.

    Args:
        df: DataFrame with loc_id, year, and metric columns
        geometry_df: DataFrame with loc_id, parent_id, admin_level

    Returns:
        Combined DataFrame with all admin levels
    """
    all_levels = [df.copy()]  # Start with original data

    # Build parent lookup from geometry
    parent_lookup = geometry_df.set_index('loc_id')['parent_id'].to_dict()

    # Identify numeric columns to aggregate (exclude loc_id, year)
    metric_cols = [c for c in df.columns if c not in ['loc_id', 'year']]

    # Aggregate to admin_1 (states)
    df_with_parent = df.copy()
    df_with_parent['parent_id'] = df_with_parent['loc_id'].map(parent_lookup)

    admin1 = df_with_parent.groupby(['parent_id', 'year'])[metric_cols].sum().reset_index()
    admin1 = admin1.rename(columns={'parent_id': 'loc_id'})
    all_levels.append(admin1)

    # Aggregate to admin_0 (country)
    # Extract country code from loc_id (e.g., "AUS-NSW" -> "AUS")
    admin1['country'] = admin1['loc_id'].str.split('-').str[0]
    admin0 = admin1.groupby(['country', 'year'])[metric_cols].sum().reset_index()
    admin0 = admin0.rename(columns={'country': 'loc_id'})
    all_levels.append(admin0)

    return pd.concat(all_levels, ignore_index=True)
```

### Geometry Aggregation

Parent-level geometry is created by dissolving child polygons:

```python
def create_parent_geometry(geometry_gdf):
    """
    Dissolve admin_2 polygons into admin_1 and admin_0.

    Args:
        geometry_gdf: GeoDataFrame with geometry, loc_id, parent_id

    Returns:
        Combined GeoDataFrame with all admin levels
    """
    from shapely.ops import unary_union

    all_levels = [geometry_gdf.copy()]

    # Dissolve to admin_1 (group by parent_id)
    admin1_groups = geometry_gdf.groupby('parent_id')
    admin1_records = []
    for parent_id, group in admin1_groups:
        dissolved = unary_union(group.geometry.tolist())
        admin1_records.append({
            'loc_id': parent_id,
            'name': get_state_name(parent_id),  # Lookup state name
            'admin_level': 1,
            'parent_id': parent_id.split('-')[0],  # Country code
            'geometry': dissolved
        })
    admin1_gdf = gpd.GeoDataFrame(admin1_records, crs=geometry_gdf.crs)
    all_levels.append(admin1_gdf)

    # Dissolve to admin_0 (whole country)
    country_code = geometry_gdf['loc_id'].str.split('-').str[0].iloc[0]
    country_geom = unary_union(geometry_gdf.geometry.tolist())
    admin0_gdf = gpd.GeoDataFrame([{
        'loc_id': country_code,
        'name': get_country_name(country_code),
        'admin_level': 0,
        'parent_id': None,
        'geometry': country_geom
    }], crs=geometry_gdf.crs)
    all_levels.append(admin0_gdf)

    return pd.concat(all_levels, ignore_index=True)
```

### Aggregation Rules by Metric Type

> **See**: [data_pipeline.md - Aggregation Rules](data_pipeline.md#aggregate_eurostat_to_countrypy) for the complete 9-row table covering counts, rates, per-capita, density, averages, indices, categorical, min/max, and medians - plus common mistakes and when NOT to aggregate.

### Complete Example

```python
# In converter main():
def main():
    # Load source data (admin_2 only)
    gdf = load_geopackage()

    # Process to long format
    df = process_data(gdf)  # Creates admin_2 rows

    # Extract geometry
    geom_gdf = extract_geometry(gdf)  # admin_2 polygons

    # === NEW: Aggregate to parent levels ===
    df = aggregate_to_parent_levels(df, geom_gdf)
    geom_gdf = create_parent_geometry(geom_gdf)

    # Save outputs (now includes all admin levels)
    save_parquet(df, OUTPUT_DIR / "AUS.parquet", "population data")
    save_parquet(geom_gdf, COUNTRY_DIR / "geometry.parquet", "geometry")
```

### Output Verification

After aggregation, verify all levels exist:

```python
# Check data levels
print(df.groupby(df['loc_id'].str.count('-'))['loc_id'].nunique())
# 0 dashes (AUS): 1 location
# 1 dash (AUS-NSW): 8 states
# 2 dashes (AUS-NSW-10050): 547 LGAs

# Check geometry levels
print(geom_df.groupby('admin_level').size())
# admin_level 0: 1
# admin_level 1: 8
# admin_level 2: 547
```

---

## Existing Converters

### Event-Based Data (has events.parquet)

| Source | File | Input Format | Geocoding | Best For |
|--------|------|--------------|-----------|----------|
| USGS Earthquakes | `convert_usgs_earthquakes.py` | CSV | 3-pass spatial join | Simple point events |
| Canada Earthquakes | `convert_canada_earthquakes.py` | CSV | 3-pass spatial join | Canadian data |
| HURDAT2 Hurricanes | `convert_hurdat2.py` | Custom text | Point-in-polygon + water | Track/trajectory data |
| NOAA Tsunamis | `convert_tsunami.py` | JSON | 3-pass spatial join | Multiple related tables |
| Smithsonian Volcanoes | `convert_volcano.py` | GeoJSON | Point + water bodies | Location + events |
| MTBS Wildfires | `convert_mtbs.py` | Shapefile (zip) | Centroid + nearest | Polygon geometries |

### Pre-Aggregated Data (aggregates only)

For data that comes pre-aggregated by region (census data, economic stats, etc.):

```python
"""Minimal converter for pre-aggregated data."""

def load_raw_data():
    """Load and map to loc_id format."""
    df = pd.read_csv(INPUT_FILE)
    # Map existing region codes to loc_id format
    df['loc_id'] = df['fips'].apply(lambda x: f"USA-{state}-{x}")
    return df

def main():
    df = load_raw_data()

    # Select/rename columns for output
    output = df[['loc_id', 'year', 'value_col1', 'value_col2']].copy()

    # Save aggregate only (no events file)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    save_parquet(output, OUTPUT_DIR / "USA.parquet", description="aggregates")

    finalize_source(
        parquet_path=str(OUTPUT_DIR / "USA.parquet"),
        source_id=SOURCE_ID
        # Note: no events_parquet_path for pre-aggregated data
    )
```

---

## Quick Reference

**Load geometry:**
```python
gdf = load_geometry_parquet(path, admin_level=2, geometry_format='geojson')
```

**Create points:**
```python
gdf = create_point_gdf(df, lat_col='latitude', lon_col='longitude')
```

**Get water body code:**
```python
code = get_water_body_loc_id(lat, lon, region='usa')
```

**Save parquet:**
```python
save_parquet(df, path, description="county-year aggregates")
```

**Finalize:**
```python
finalize_source(parquet_path, source_id, events_parquet_path)
```

---

## Related Documentation

| File | Purpose |
|------|---------|
| [data_pipeline.md](data_pipeline.md) | Full pipeline documentation, metadata schema, all datasets |
| [GEOMETRY.md](GEOMETRY.md) | loc_id specification, geometry structure, water body codes |
| [MAPPING.md](MAPPING.md) | Frontend map rendering and display |

---

*Last Updated: 2026-01-06*
