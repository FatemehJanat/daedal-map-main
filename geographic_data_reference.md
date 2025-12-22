# Organizing Global Geographic Data - Reference Guide

## 1. Overview and Problem Statement

When working with global data sets across multiple countries, administrative levels, and temporal dimensions, data organization becomes challenging quickly. Common data types include:
- Census data
- SDG reports from the UN
- Climate data
- Central bank economic data

The traditional American-centric hierarchy (country → state → county → city → zip code) works for some contexts but fails to capture the complexity and variety of administrative structures worldwide. Additionally, many important geographic phenomena don't respect administrative boundaries at all.

## 2. Alternative Geographic Frameworks

### 2.1 Statistical and Functional Regions
- **Metropolitan Statistical Areas (MSAs)**: Cross city/county boundaries, defined by economic ties and commuting patterns
- **OECD Functional Urban Areas**: Globally standardized metropolitan area definitions
- **Eurostat NUTS Regions**: Hierarchical system used across Europe that doesn't always align with administrative boundaries

### 2.2 Grid-Based Systems
- **H3 Hexagonal Grids**: Uber's hierarchical geospatial indexing system
- **Lat/Long Grid Cells**: Used by climate scientists (1°x1° or 0.5°x0.5° cells)
- **MGRS/UTM Zones**: Military Grid Reference System or Universal Transverse Mercator

### 2.3 Natural and Physical Boundaries
- **Watershed/River Basins**: Critical for water resource and environmental data
- **Ecoregions or Biomes**: Used in biodiversity and conservation data
- **Climate Zones**: Köppen climate classification
- **Seismic Zones**: For earthquake and geological hazard data

### 2.4 Supranational and Multi-Country Regions
- **UN Geoscheme Regions**: "Western Africa", "Southern Asia", etc.
- **World Bank Income Groups**: Regional classifications
- **Trade Blocs**: USMCA, MERCOSUR, ASEAN, European Union
- **Continental Divisions**

## 3. Data That Doesn't Fit Traditional Hierarchies

### 3.1 Transboundary Phenomena
- Air quality/pollution (doesn't respect borders)
- Ocean currents and maritime data
- Migratory species tracking
- Cross-border river systems (Mekong, Danube)

### 3.2 Special Jurisdictions
- Indigenous/tribal lands (may overlap multiple administrative units)
- Special economic zones
- Exclusive economic zones (EEZ) in oceans
- Disputed territories
- Extraterritorial areas (embassies, military bases)

### 3.3 Time-Variable and Point-Based Data
- Conflict zones
- Disaster-affected areas
- Epidemiological zones during outbreaks
- Individual weather stations
- Seismic monitoring stations
- Shipping routes and telecommunications networks

## 4. Recommended Global Administrative System

Rather than forcing all countries into a rigid 5-layer structure, use a **flexible depth approach** that accommodates varying administrative structures worldwide.

### 4.1 Base Administrative Layers

| Layer | Level | Examples |
|-------|-------|----------|
| Layer 0 | Country | ISO 3166-1 alpha-2/3 codes. Universal and well-standardized. |
| Layer 1 | Admin Level 1 | States (US), Provinces (Canada, China), Regions (France, Italy), Oblasts (Russia). First subdivision below country. ISO 3166-2 codes where available. |
| Layer 2 | Admin Level 2 | Counties (US), Districts (many countries), Departments (France), Prefectures (Japan). Second subdivision. Not all countries have this meaningfully. |
| Layer 3 | Admin Level 3 | Municipalities, Cities, Towns, Communes. Most populated places, but definitions vary widely. |
| Layer 4 | Localities | Postal codes where granular (UK postcodes, US ZIP codes). Neighborhoods, districts, wards. Census blocks or enumeration areas. |

### 4.2 Important Considerations

- **Depth varies by country**:
  - Singapore: Just country level
  - Luxembourg: Country + 2 levels
  - France: Country + 4-5 levels
  - China: Country + 4-5 levels

- **Skip "metro zone" as a fixed layer**: Doesn't exist consistently globally. Treat metro/functional urban areas as a separate optional overlay dataset.

- **Use admin_level terminology**: OpenStreetMap and GADM use this convention (admin_0 through admin_5)

- **Design with flexible depth**: 
  - Include fields: `admin_level` (0-4+), `admin_type` (province, state, etc.), `parent_id`, `has_children`
  - This way France can have 5 levels, Singapore has 1, and you're not forcing artificial structure

## 5. Folder Structure Strategies

**Key Principle**: Separate geometries from data. Download geometries once, then reference them by ID when storing indicator data.

### 5.1 Geography-First Structure (Recommended)

```
data/
  geometries/
    admin_0/
      world.geojson
    admin_1/
      usa_states.geojson
      canada_provinces.geojson
      france_regions.geojson
    admin_2/
      usa_counties.geojson
      france_departments.geojson
    postal/
      usa_zipcodes.geojson
      uk_postcodes.geojson
    
  indicators/
    country/
      gdp/
        2020.json
        2021.json
      population/
        2020.json
    admin_1/
      usa/
        unemployment/
          2020.json
          2021.json
```

### 5.2 File Naming Conventions

Use consistent, descriptive naming that includes source, level, and year:

```
geometries/admin_1_gadm_simplified.geojson
geometries/admin_2_usa_census_2020.geojson
geometries/cities_naturalearth_10m.geojson

indicators/population/admin_0_worldbank_2020.json
indicators/temperature/grid_1deg_era5_2020.json
```

## 6. Best Downloadable GeoJSON/Shapefile Sources

### 6.1 GADM - Best for Comprehensive Admin Boundaries
- **Website**: gadm.org
- **What**: Administrative boundaries for every country at multiple levels
- **Format**: Shapefiles, GeoPackage, or R format (convert to GeoJSON)
- **Download**: Individual countries or global datasets
- **Levels**: 0-5 depending on country
- **License**: Free for non-commercial, attribution required
- **Size**: Can be large (global admin_2 is several GB)
- **URL**: gadm.org/download_country.html

### 6.2 Natural Earth - Best for Clean, Multi-Scale Data
- **Website**: naturalearthdata.com
- **What**: Admin boundaries, populated places, physical features
- **Format**: Shapefiles (easily convert to GeoJSON)
- **Scales**: 1:10m (detailed), 1:50m (medium), 1:110m (small scale)
- **License**: Public domain
- **Great for**: Country borders, states/provinces, major cities, physical features

### 6.3 geoBoundaries - Excellent Alternative to GADM
- **Website**: geoboundaries.org
- **What**: Open admin boundaries, simplified versions available
- **Format**: GeoJSON, Shapefiles, direct from API or bulk download
- **Levels**: Multiple admin levels per country
- **License**: Fully open (better than GADM for commercial use)
- **Special**: Has simplified geometries for faster rendering

### 6.4 OpenStreetMap Extracts
- **Geofabrik** (download.geofabrik.de): Country/region extracts updated daily, shapefiles or OSM format
- **BBBike**: City-level extracts, custom bounding boxes

### 6.5 US-Specific Sources
- **US Census TIGER/Line** (census.gov/geographies/mapping-files.html): States, counties, ZCTAs, census tracts, blocks. Very detailed, updated annually.
- **Census Cartographic Boundary Files**: Simplified versions, smaller file sizes, better for web mapping

### 6.6 Postal Code Boundaries
- **GeoNames Postal Codes** (download.geonames.org/export/zip/): Point locations (not polygons) for postal codes globally
- **US ZCTA from Census**: Polygon boundaries for US ZIP codes
- **OpenAddresses**: Some postal boundary data for various countries

### 6.7 Other Country-Specific Sources
- **UK**: ONS Geography Portal (geoportal.statistics.gov.uk)
- **Canada**: Statistics Canada Boundary Files
- **Australia**: ABS (Australian Bureau of Statistics)
- **EU**: Eurostat GISCO (ec.europa.eu/eurostat/web/gisco)

### 6.8 Humanitarian and Development Data
- **HDX** - Humanitarian Data Exchange (data.humdata.org): Admin boundaries for many countries, often more up-to-date for developing nations

### 6.9 Climate and Natural Boundaries
- **HydroSHEDS** (hydrosheds.org): Watershed boundaries globally
- **WWF Ecoregions**: Downloadable ecological boundaries
- **FAO GeoNetwork**: Agricultural, soil, climate zones

## 7. Practical Workflow

### 7.1 Download and Conversion

1. **Download base geometries once**:
   - GADM or geoBoundaries for admin levels 0-2 globally
   - Natural Earth for simplified versions
   - Country-specific sources for detailed sub-national data

2. **Convert to GeoJSON if needed**:
   ```bash
   # Using ogr2ogr (part of GDAL)
   ogr2ogr -f GeoJSON output.geojson input.shp
   ```

3. **Simplify geometries for web use**:
   ```bash
   # Using mapshaper
   mapshaper input.geojson -simplify 10% -o output_simplified.geojson
   ```

### 7.2 ID Standardization

Each geometry should have standardized IDs:
- ISO 3166-1 for countries
- ISO 3166-2 for admin_1 where available
- GADM IDs or FIPS codes for other levels
- GeoNames IDs for cities

Store indicator data separately, referencing geometry IDs rather than embedding full geometries.

## 8. Key Recommendations

- Use multiple parallel classification systems rather than forcing everything into one hierarchy
- Separate geometry storage from indicator data storage
- Design with flexible depth to accommodate varying administrative structures
- Start with the base 5-layer system (admin_0 through admin_4) and build exception cases for watersheds, natural boundaries, and special geographies
- Download comprehensive geometry datasets once from GADM, geoBoundaries, and Natural Earth
- Use standardized IDs (ISO codes, GADM IDs, GeoNames IDs) for linking
- Implement consistent file naming conventions

## 9. Data Sources to Avoid (Paid/Restricted)

### Always Free/Open (Primary Sources)

**Government Statistical Agencies:**
- US Census Bureau - completely free, public domain
- BLS (Bureau of Labor Statistics) - free
- NOAA/NASA - free, public domain
- USGS - free, public domain
- Most national statistical offices worldwide (Eurostat, Statistics Canada, etc.) - free
- Central banks (Federal Reserve, ECB, etc.) - free

**International Organizations:**
- UN agencies (UNDP, WHO, FAO, etc.) - free, open licenses
- World Bank Open Data - free
- IMF Data - free
- OECD Data - free (some premium services exist but core data is free)

**Climate/Environmental:**
- NOAA Climate Data - free
- NASA Earth Data - free
- Copernicus (EU Earth observation) - free
- ERA5 reanalysis data - free

### Watch Out For / Potentially Paid

**High-Resolution/Real-Time Commercial Data:**
- Bloomberg Terminal - very expensive ($20k+/year)
- Refinitiv (formerly Thomson Reuters) - expensive
- S&P Capital IQ - expensive
- FactSet - expensive

**Commercial Climate/Weather:**
- Weather Underground API (now IBM) - has free tier but limits quickly
- Tomorrow.io (formerly ClimaCell) - some free, paid for detailed
- Planet Labs satellite imagery - paid (though some academic access)

**Demographic/Marketing Data:**
- Nielsen data - very expensive
- Experian/Equifax consumer data - expensive
- Esri demographic layers - paid (though they use census data underneath)
- CoreLogic real estate data - paid

**Some Remote Sensing:**
- Maxar/DigitalGlobe high-res imagery - paid
- Planet Labs - paid for most access
- Note: Landsat (USGS) and Sentinel (ESA) are FREE and very good

**Proprietary Economic Indices:**
- Some industry-specific indices
- Proprietary inflation measures
- Some trade data aggregators

**Power/Energy Sector:**
- EIA (Energy Information Administration) - FREE
- FERC data - FREE
- ISO/RTO data (CAISO, ERCOT, PJM, etc.) - FREE but can be messy
- S&P Global Platts - PAID
- Wood Mackenzie - PAID
- IHS Markit - PAID

**Financial/Economic:**
- Most central bank data - FREE
- Haver Analytics - PAID (aggregates free data but charges for access)
- CRSP stock data - PAID (though Yahoo Finance is free alternative)

**Real Estate:**
- Zillow/Redfin - free but with terms of service limits
- CoreLogic - PAID
- County assessor data - FREE but need to scrape each county

### Licensing Gotchas Even With Free Data

**Terms of Service Issues:**
- Some free APIs limit redistribution
- Google Maps API - free tier exists but strict terms
- Twitter API - free but limits on what you can do with data
- Some government data requires attribution

**GADM Specifically:**
- Free for non-commercial
- For commercial use, technically need license
- Most people use it anyway for internal work
- For 90% personal use: you're fine

**OpenStreetMap:**
- ODbL license - requires attribution and share-alike
- If you distribute derived datasets, they must also be ODbL
- Fine for personal use

### Bottom Line for Personal Use

Stick to government sources (Census, BLS, EIA, NOAA, USGS, etc.) - all free. Use UN/World Bank/IMF for international - all free. Use GADM/Natural Earth for boundaries - free for non-commercial. Avoid anything with "Bloomberg", "S&P", "Nielsen", "IHS Markit" in the name. If a dataset requires a "sales inquiry" or "demo", it's paid.

## 10. Esri and Alternatives

### Why Avoid Esri for Your Use Case

**Esri (ArcGIS Online) issues:**
- Expensive for full access
- Clunky, confusing interface
- Datasets are often just repackaged government data
- Proprietary formats
- Not ideal for custom applications

**Better alternatives:**
- **QGIS** - free, open source, can do everything ArcGIS does
- **GeoPandas (Python)** - programmatic GIS analysis
- **PostGIS** - spatial database, free
- **Leaflet/MapLibre** - for web mapping
- For data: go straight to the source (Census, Natural Earth, etc.)

Most of Esri's "Living Atlas" layers are just Census data with a pretty wrapper. Skip the middleman and build your own interface.

## 11. Bulk Downloading Strategies

### SDG-Specific Sources

**UN Stats (unstats.un.org/sdgs):**
- Has bulk download option but poorly documented
- Better: Use their API with bulk requests
- Best: Download from World Bank or OECD who mirror the data

**World Bank for SDGs:**
- API: `https://api.worldbank.org/v2/sdg/Goal/1/Target/1.1/Indicator/1.1.1?format=json&per_page=1000`
- Better: Use bulk download files at data.worldbank.org
- Clean CSV/Excel formats available

**OECD.Stat:**
- Good bulk download in CSV/Excel
- Better interface than UN
- stats.oecd.org

**UNSD Data Commons:**
- Sometimes has bulk data files
- data.un.org

### General Bulk Download Strategies

**Look for these on any data portal:**
1. "Bulk download" or "Data dump" links (often buried in footer/about pages)
2. FTP servers (many old government sites still use these)
3. "API" pages often link to bulk files
4. Check robots.txt file - sometimes lists bulk data locations
5. Wayback Machine - older versions of sites sometimes had better download options

**Tools for automated downloading:**

```bash
# wget for recursive downloads
wget -r -np -nH --cut-dirs=3 -R index.html http://example.com/data/

# Check for FTP servers
ftp://ftp.example.gov/pub/data/
```

```python
# Python for API bulk downloads
import requests
import pandas as pd

# Many sites have hidden bulk endpoints
url = "https://api.example.com/bulk/all_data.csv"
response = requests.get(url)
df = pd.read_csv(url)
```

### Finding Hidden Bulk Downloads

1. Look at page source for download links
2. Check network tab in browser dev tools when clicking "download"
3. Search for "ftp://" on the website
4. Look for "developers" or "technical documentation" pages
5. Check if there's a GitHub repo with data

## 12. Database Design for Multi-Dimensional Data

This is the core challenge: organizing 200 indicators × 200 countries × 20-30 years × multiple admin levels.

### The Core Trade-off

**One Giant Database:**
- ✅ Simple queries across multiple dimensions
- ✅ No stitching needed
- ❌ Slow to load
- ❌ Hard to update partially
- ❌ Memory intensive

**Many Small Databases:**
- ✅ Fast to load specific subsets
- ✅ Easy to update one piece
- ✅ Can parallelize queries
- ❌ Complex stitching logic
- ❌ Harder to do cross-cutting queries

### Recommended Hybrid Approach

**Partition by indicator, then by geography level:**

```
data/
  indicators/
    gdp/                          # One indicator
      admin_0/                    # Country level
        all_countries_all_years.parquet   # ~200 countries x 30 years = 6,000 rows
      admin_1/                    # State/province level  
        usa_all_years.parquet     # ~50 states x 30 years = 1,500 rows
        can_all_years.parquet
        fra_all_years.parquet
      admin_2/                    # County level
        usa_all_years.parquet     # ~3,000 counties x 30 years = 90,000 rows
    
    population/
      admin_0/
        all_countries_all_years.parquet
      admin_1/
        usa_all_years.parquet
    
    poverty_rate/
      admin_0/
        all_countries_all_years.parquet
```

### Why This Structure?

**Country level (admin_0):**
- Small enough to have one file for all countries, all years
- 200 countries × 30 years × 200 indicators = manageable
- Each indicator file: ~6,000 rows

**Sub-national (admin_1, admin_2):**
- Split by country because it gets big fast
- USA states: 50 × 30 years = 1,500 rows (fine)
- USA counties: 3,000 × 30 years = 90,000 rows (still fine)
- USA cities: 20,000 × 30 years = 600,000 rows (getting chunky, might need further splitting)

**If you get to city level with many indicators:**
- Consider splitting by decade: `usa_2000_2010.parquet`, `usa_2010_2020.parquet`
- Or by state: `california_cities_all_years.parquet`

**Don't split by year** - time is usually a dimension you want to query across, so keep it together. This is especially important for the time slider feature.

### File Format Recommendations

**Don't use CSV for large datasets. Use:**

**1. Parquet (BEST for your use case):**
```python
import pandas as pd

# Write
df.to_parquet('data.parquet', compression='snappy')

# Read (super fast)
df = pd.read_parquet('data.parquet')

# Read specific columns only (even faster)
df = pd.read_parquet('data.parquet', columns=['year', 'value'])
```

Benefits:
- Columnar format (only read columns you need)
- Built-in compression (10x smaller than CSV)
- Much faster to read than CSV
- Preserves data types

**2. HDF5 (good for scientific data):**
```python
# Can store multiple datasets in one file
df.to_hdf('data.h5', key='gdp', mode='w')
```

**3. SQLite (good for relational queries):**
- Still file-based (single .db file)
- Can do SQL queries
- Easy to manage

**4. DuckDB (newest, might be perfect for you):**
```python
import duckdb

# Query parquet files directly without loading into memory
duckdb.query("SELECT * FROM 'data.parquet' WHERE year > 2010")
```

Benefits:
- Can query parquet files like a database
- Extremely fast
- No separate database server needed
- Perfect for the time slider use case

### Size Guidelines

Based on "fast searches" requirement:

**File size sweet spots:**
- **< 100 MB**: Load entire file into memory, filter in pandas/R
- **100 MB - 1 GB**: Use parquet + selective column reading
- **1 GB - 10 GB**: Use DuckDB to query without loading all into memory
- **> 10 GB**: Consider PostgreSQL or split further

**For 200 indicators × 200 countries × 30 years at country level:**
- Estimate: 200 × 200 × 30 = 1.2 million data points
- As parquet: probably ~50-100 MB per indicator
- Total: ~10-20 GB for all indicators at country level
- **Recommendation**: Keep one file per indicator at country level

**For USA cities (20,000 cities):**
- 20,000 cities × 30 years × 1 indicator = 600,000 rows
- As parquet: ~10-30 MB per indicator
- **Recommendation**: One file per indicator for all USA cities

### Querying Strategy

**Common query patterns and optimal structure:**

**Pattern 1: "Show me GDP for all countries in 2020"**
- Read: `indicators/gdp/admin_0/all_countries_all_years.parquet`
- Filter: `year == 2020`
- Fast because it's one file, one read

**Pattern 2: "Show me all indicators for USA in 2020"**
- Read: Multiple files (one per indicator) from `indicators/*/admin_0/`
- Filter: `country == 'USA' AND year == 2020`
- Reasonable because you're only reading country-level files (small)

**Pattern 3: "Show me GDP for California cities over time"**
- Read: `indicators/gdp/admin_3/usa_all_years.parquet`
- Filter: `state == 'CA'`
- Fast because it's one file

**Pattern 4: "Compare GDP and population for California cities in 2020"**
- Read: `indicators/gdp/admin_3/usa_all_years.parquet` + `indicators/population/admin_3/usa_all_years.parquet`
- Filter and join: Both on `city AND year == 2020`
- Reasonable - two files, but optimized with parquet

### Recommended Tech Stack

```python
import pandas as pd
import geopandas as gpd
import duckdb

# For simple queries
df = pd.read_parquet('indicators/gdp/admin_0/all_countries_all_years.parquet')
result = df[df['year'] == 2020]

# For complex multi-file queries
query = """
SELECT 
  gdp.country, 
  gdp.year, 
  gdp.value as gdp_value,
  pop.value as population
FROM 'indicators/gdp/admin_0/*.parquet' gdp
JOIN 'indicators/population/admin_0/*.parquet' pop
  ON gdp.country = pop.country AND gdp.year = pop.year
WHERE gdp.year > 2015
"""
result = duckdb.query(query).to_df()

# For spatial queries
gdf = gpd.read_file('geometries/admin_0/world.geojson')
result_with_geo = gdf.merge(result, left_on='iso_code', right_on='country')
```

### The Balance Answer

**For SDG-style data (200 indicators × 200 countries × 30 years × multiple admin levels):**

1. **Split by indicator** (200 separate folders)
2. **Within each indicator, split by admin level** (admin_0, admin_1, admin_2, admin_3)
3. **At country level (admin_0)**: one file for all countries, all years
4. **At sub-national levels**: one file per country, all years
5. **Use parquet format**
6. **Use DuckDB for queries that span multiple files**

This gives you:
- Fast access to single indicator + single geography
- Reasonable performance for multi-indicator queries (DuckDB handles this)
- Easy to update (replace one file at a time)
- Manageable file sizes (most files under 100 MB)
- Perfect structure for time slider (all years in one file per indicator/geography)

**Don't split by year** - time is usually a dimension you want to query across, so keep it together.

## 13. Time Slider Implementation Ideas

### The Vision
A slider bar on the map that allows dragging back and forth across time, dynamically updating the visualization as years change.

### Technical Approaches

**Option 1: Web-based with Leaflet/MapLibre + D3.js**
```javascript
// Pseudocode structure
let currentYear = 2020;
let data = {}; // Pre-loaded data for all years

// Slider event
slider.on('input', function() {
  currentYear = this.value;
  updateMap(currentYear);
});

function updateMap(year) {
  // Filter data to current year
  const yearData = data.filter(d => d.year === year);
  
  // Update choropleth colors
  geoJsonLayer.eachLayer(function(layer) {
    const value = yearData.find(d => d.location === layer.feature.properties.id);
    layer.setStyle({ fillColor: getColor(value) });
  });
}
```

**Option 2: Pre-render frames (for smoother performance)**
- Generate a GeoJSON file for each year
- Load year's file on slider change
- Faster but more storage

**Option 3: Client-side with Parquet**
```javascript
// Use arrow-js to read parquet in browser
import { tableFromIPC } from 'apache-arrow';

// Load all years at once, filter on client
const table = await tableFromIPC(fetch('data.parquet'));
const filtered = table.filter(row => row.year === currentYear);
```

### Data Structure for Time Slider

**For smooth performance, structure data like:**
```
web_app/
  data/
    indicators/
      gdp/
        admin_0_all_years.parquet  # All countries, all years, one file
                                    # Pre-loaded in browser memory
```

**File size considerations:**
- 200 countries × 30 years × 1 indicator = 6,000 rows
- As parquet: ~2-5 MB
- Easily pre-loaded in browser
- Filter by year happens in-memory (instant)

### Performance Optimization

**Pre-processing:**
1. Simplify geometries for web (use mapshaper at 1-5% tolerance)
2. Pre-join indicator data with geography IDs
3. Generate one file per indicator with all years
4. Consider GeoJSON with embedded time-series vs separate files

**Runtime:**
1. Load full time series on page load
2. Use requestAnimationFrame for smooth slider updates
3. Debounce slider events (only update every 50ms)
4. Use canvas rendering instead of SVG for 1000+ features

### Example Implementation Options

**Libraries that handle this well:**
- **Kepler.gl** - Uber's geospatial toolkit, has built-in time slider
- **Deck.gl** - Also from Uber, high-performance WebGL
- **Plotly Dash** - Python-based, has slider components
- **Observable Plot** - D3-based, modern syntax
- **Vega-Lite** - Declarative visualization, supports time filtering

**Custom build:**
- Leaflet + noUiSlider (for the slider component)
- MapLibre GL JS + custom slider
- D3.js for full control

### Next Steps for Time Slider

1. Choose a single indicator and geography level to prototype
2. Export to parquet with structure: `location_id, year, value`
3. Create simple HTML page with slider
4. Test performance with full time series loaded
5. Expand to multiple indicators once prototype works

## 14. Metadata and Data Catalog System

### The Challenge

With hundreds of datasets spread across multiple folders, admin levels, and years, you need a way for:
1. **The chat function** to quickly know what's available without scanning all files
2. **Users to ask natural language questions** like "how has poverty changed in Africa?" and have the system find relevant datasets
3. **You to maintain** an organized catalog of what exists

### Solution: Central Catalog with Embeddings

Create a **master catalog** that acts as the "table of contents" for your entire data collection, with semantic search capabilities.

### Central Catalog Structure

```
data/
  catalog.json                    # Master catalog - the chat reads this
  catalog_embeddings.npy          # Vector embeddings for semantic search
  geometries/
    admin_0/
      world.geojson
      metadata.json               # Optional: per-file metadata
    admin_1/
      ...
  indicators/
    gdp/
      admin_0/
        all_countries_all_years.parquet
        metadata.json             # Optional: per-indicator metadata
```

### Catalog Schema

Your `catalog.json` should contain comprehensive metadata for quick lookup:

```json
{
  "metadata": {
    "catalog_version": "1.0",
    "last_updated": "2024-12-21",
    "total_datasets": 450,
    "total_indicators": 200,
    "total_geometries": 25
  },
  
  "geometries": [
    {
      "id": "geom_admin0_world",
      "name": "World Countries",
      "type": "geometry",
      "admin_level": 0,
      "format": "geojson",
      "file_path": "geometries/admin_0/world.geojson",
      "source": "Natural Earth",
      "source_url": "naturalearthdata.com",
      "license": "public domain",
      "feature_count": 195,
      "geographic_coverage": "global",
      "properties": ["iso_a2", "iso_a3", "name", "continent", "region_un"],
      "simplified": false,
      "file_size_mb": 24.5,
      "last_updated": "2024-01-15",
      "tags": ["boundaries", "countries", "global", "admin0"]
    },
    {
      "id": "geom_admin1_usa",
      "name": "USA States",
      "type": "geometry",
      "admin_level": 1,
      "format": "geojson",
      "file_path": "geometries/admin_1/usa_states.geojson",
      "source": "US Census TIGER/Line",
      "license": "public domain",
      "feature_count": 52,
      "geographic_coverage": "USA",
      "properties": ["statefp", "stusps", "name", "aland", "awater"],
      "simplified": true,
      "file_size_mb": 2.1,
      "tags": ["boundaries", "states", "usa", "admin1"]
    }
  ],
  
  "indicators": [
    {
      "id": "ind_poverty_headcount_admin0",
      "name": "Poverty Headcount Ratio at $2.15/day",
      "type": "indicator",
      "category": "economic",
      "subcategory": "poverty",
      "admin_level": 0,
      "format": "parquet",
      "file_path": "indicators/poverty/admin_0/all_countries_all_years.parquet",
      "source": "World Bank",
      "source_url": "data.worldbank.org",
      "source_dataset": "Poverty and Inequality Platform",
      "license": "CC BY 4.0",
      "geographic_coverage": {
        "type": "global",
        "countries": 164,
        "regions": ["Africa", "Asia", "Latin America", "Europe"],
        "continents": ["Africa", "Asia", "Europe", "North America", "South America", "Oceania"]
      },
      "temporal_coverage": {
        "start_year": 1990,
        "end_year": 2023,
        "frequency": "annual",
        "total_years": 34
      },
      "units": "percentage of population",
      "data_points": 5576,
      "file_size_mb": 2.8,
      "last_updated": "2024-10-15",
      "related_indicators": [
        "ind_poverty_headcount_365_admin0",
        "ind_poverty_gap_admin0",
        "ind_gini_admin0"
      ],
      "sdg_alignment": ["1.1.1"],
      "tags": [
        "poverty", "extreme poverty", "inequality", "economic", 
        "sdg1", "development", "living standards", "income"
      ],
      "keywords": [
        "poor", "poverty rate", "destitution", "impoverished",
        "low income", "underprivileged", "economic hardship"
      ],
      "description": "Proportion of population living below international poverty line of $2.15 per day (2017 PPP)",
      "notes": "Data availability varies by country. Some estimates based on household surveys.",
      "quality_score": 0.88,
      "completeness": 0.82,
      "search_text": "poverty headcount ratio extreme poverty $2.15 per day percentage population living below international poverty line economic hardship low income poor destitution SDG 1.1.1"
    },
    {
      "id": "ind_gdp_admin0",
      "name": "GDP (Gross Domestic Product)",
      "type": "indicator",
      "category": "economic",
      "subcategory": "national accounts",
      "admin_level": 0,
      "format": "parquet",
      "file_path": "indicators/gdp/admin_0/all_countries_all_years.parquet",
      "source": "World Bank",
      "license": "CC BY 4.0",
      "geographic_coverage": {
        "type": "global",
        "countries": 217,
        "regions": ["Africa", "Asia", "Latin America", "Europe", "North America"],
        "continents": ["Africa", "Asia", "Europe", "North America", "South America", "Oceania"]
      },
      "temporal_coverage": {
        "start_year": 1990,
        "end_year": 2023,
        "frequency": "annual",
        "total_years": 34
      },
      "units": "current USD",
      "data_points": 7378,
      "file_size_mb": 3.2,
      "related_indicators": ["ind_gdp_per_capita_admin0", "ind_gdp_growth_admin0"],
      "sdg_alignment": ["8.1.1"],
      "tags": ["economic", "gdp", "economy", "national accounts", "sdg8", "growth"],
      "keywords": ["economic output", "production", "wealth", "economy size"],
      "description": "Gross domestic product at current market prices in US dollars",
      "search_text": "GDP gross domestic product economic output economy national accounts production wealth economy size"
    },
    {
      "id": "ind_population_admin1_usa",
      "name": "Population - USA States",
      "type": "indicator",
      "category": "demographic",
      "subcategory": "population",
      "admin_level": 1,
      "format": "parquet",
      "file_path": "indicators/population/admin_1/usa_all_years.parquet",
      "source": "US Census Bureau",
      "license": "public domain",
      "geographic_coverage": {
        "type": "country",
        "countries": ["USA"],
        "regions": 52
      },
      "temporal_coverage": {
        "start_year": 2000,
        "end_year": 2023,
        "frequency": "annual",
        "total_years": 24
      },
      "units": "persons",
      "data_points": 1248,
      "file_size_mb": 0.8,
      "related_indicators": ["ind_population_admin2_usa", "ind_population_density_admin1_usa"],
      "tags": ["demographic", "population", "usa", "states", "census"],
      "keywords": ["people", "residents", "inhabitants", "population size"],
      "description": "Total resident population by state",
      "search_text": "population people residents inhabitants demographic census population size"
    }
  ],
  
  "categories": {
    "economic": {
      "subcategories": ["gdp", "trade", "employment", "inflation", "poverty"],
      "indicator_count": 45
    },
    "demographic": {
      "subcategories": ["population", "migration", "age_structure", "urbanization"],
      "indicator_count": 28
    },
    "environmental": {
      "subcategories": ["emissions", "deforestation", "water_quality", "biodiversity"],
      "indicator_count": 35
    },
    "health": {
      "subcategories": ["mortality", "disease_prevalence", "healthcare_access"],
      "indicator_count": 42
    },
    "education": {
      "subcategories": ["literacy", "enrollment", "attainment"],
      "indicator_count": 22
    }
  },
  
  "coverage_summary": {
    "countries_available": ["USA", "CAN", "FRA", "DEU", "CHN", "..."],
    "regions_available": ["Africa", "Asia", "Europe", "Latin America", "North America"],
    "admin_levels": [0, 1, 2, 3],
    "years_range": {
      "min": 1990,
      "max": 2023
    },
    "total_data_points": 5420000,
    "total_size_gb": 12.4
  }
}
```

### Essential Metadata Fields

**For Every Dataset:**
- `id` - unique identifier
- `name` - human-readable name
- `file_path` - relative path to file
- `format` - parquet, geojson, etc.
- `tags` - searchable keywords (CRITICAL for chat)
- `keywords` - synonyms and related terms (CRITICAL for chat)
- `search_text` - combined searchable text for embeddings
- `description` - detailed explanation

**For Indicators:**
- `category` / `subcategory` - hierarchical organization
- `admin_level` - 0, 1, 2, 3, 4
- `geographic_coverage` - countries, regions, continents
- `temporal_coverage` - start_year, end_year, frequency
- `units` - measurement units
- `data_points` - total number of records
- `sdg_alignment` - which SDG indicators this maps to
- `related_indicators` - IDs of similar/complementary datasets
- `completeness` - percentage of expected data points that exist
- `quality_score` - 0-1 rating

**For Geometries:**
- `admin_level` - 0, 1, 2, 3, 4
- `geographic_coverage` - global, country name, region
- `feature_count` - number of features
- `properties` - available attribute fields
- `simplified` - whether geometry has been simplified

### Semantic Search with Embeddings

For natural language queries like "how has poverty changed in Africa?", use embeddings:

```python
from sentence_transformers import SentenceTransformer
import numpy as np
import json

class SemanticDataCatalog:
    def __init__(self, catalog_path="data/catalog.json"):
        with open(catalog_path) as f:
            self.catalog = json.load(f)
        
        # Load embedding model (small, fast, works offline)
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        
        # Generate or load embeddings
        self.load_or_generate_embeddings()
        
        # Build quick lookup indexes
        self.build_indexes()
    
    def generate_embeddings(self):
        """Create vector embeddings for all datasets"""
        self.embeddings = []
        self.embedding_metadata = []
        
        for indicator in self.catalog['indicators']:
            # Combine all searchable text
            search_text = indicator.get('search_text', '')
            if not search_text:
                # Fallback: combine key fields
                search_text = f"{indicator['name']} {indicator.get('description', '')} "
                search_text += f"{' '.join(indicator.get('tags', []))} "
                search_text += f"{' '.join(indicator.get('keywords', []))}"
            
            # Generate embedding
            embedding = self.model.encode(search_text)
            self.embeddings.append(embedding)
            self.embedding_metadata.append({
                'id': indicator['id'],
                'name': indicator['name'],
                'type': 'indicator'
            })
        
        self.embeddings = np.array(self.embeddings)
        
        # Save embeddings for faster loading next time
        np.save('data/catalog_embeddings.npy', self.embeddings)
        with open('data/catalog_embedding_metadata.json', 'w') as f:
            json.dump(self.embedding_metadata, f)
    
    def load_or_generate_embeddings(self):
        """Load existing embeddings or generate new ones"""
        try:
            self.embeddings = np.load('data/catalog_embeddings.npy')
            with open('data/catalog_embedding_metadata.json') as f:
                self.embedding_metadata = json.load(f)
            print("Loaded existing embeddings")
        except FileNotFoundError:
            print("Generating new embeddings...")
            self.generate_embeddings()
    
    def build_indexes(self):
        """Create quick lookup structures for filtering"""
        self.by_category = {}
        self.by_country = {}
        self.by_region = {}
        self.by_sdg = {}
        self.by_admin_level = {}
        
        for indicator in self.catalog['indicators']:
            # Index by category
            cat = indicator['category']
            if cat not in self.by_category:
                self.by_category[cat] = []
            self.by_category[cat].append(indicator)
            
            # Index by region
            for region in indicator['geographic_coverage'].get('regions', []):
                if region not in self.by_region:
                    self.by_region[region] = []
                self.by_region[region].append(indicator)
            
            # Index by SDG
            for sdg in indicator.get('sdg_alignment', []):
                if sdg not in self.by_sdg:
                    self.by_sdg[sdg] = []
                self.by_sdg[sdg].append(indicator)
            
            # Index by admin level
            level = indicator['admin_level']
            if level not in self.by_admin_level:
                self.by_admin_level[level] = []
            self.by_admin_level[level].append(indicator)
    
    def semantic_search(self, query, top_k=10, filters=None):
        """
        Search using semantic similarity
        
        Args:
            query: Natural language query
            top_k: Number of results to return
            filters: Dict with optional filters like:
                - region: "Africa"
                - country: "USA"
                - admin_level: 0
                - year: 2020
                - category: "economic"
        """
        # Encode the query
        query_embedding = self.model.encode(query)
        
        # Compute cosine similarity
        similarities = np.dot(self.embeddings, query_embedding)
        
        # Get top matches
        top_indices = np.argsort(similarities)[-top_k*3:][::-1]  # Get extra for filtering
        
        # Get corresponding indicators
        results = []
        for idx in top_indices:
            indicator_id = self.embedding_metadata[idx]['id']
            indicator = next(ind for ind in self.catalog['indicators'] if ind['id'] == indicator_id)
            
            # Apply filters
            if filters:
                if not self._matches_filters(indicator, filters):
                    continue
            
            results.append({
                'indicator': indicator,
                'relevance_score': float(similarities[idx]),
                'match_reason': self._explain_match(query, indicator)
            })
            
            if len(results) >= top_k:
                break
        
        return results
    
    def _matches_filters(self, indicator, filters):
        """Check if indicator matches filter criteria"""
        if 'region' in filters:
            if filters['region'] not in indicator['geographic_coverage'].get('regions', []):
                return False
        
        if 'country' in filters:
            if filters['country'] not in indicator['geographic_coverage'].get('countries', []):
                return False
        
        if 'admin_level' in filters:
            if indicator['admin_level'] != filters['admin_level']:
                return False
        
        if 'year' in filters:
            temp = indicator['temporal_coverage']
            if not (temp['start_year'] <= filters['year'] <= temp['end_year']):
                return False
        
        if 'category' in filters:
            if indicator['category'] != filters['category']:
                return False
        
        return True
    
    def _explain_match(self, query, indicator):
        """Generate explanation for why this matched"""
        reasons = []
        query_lower = query.lower()
        
        # Check direct matches
        if any(tag in query_lower for tag in indicator.get('tags', [])):
            reasons.append("matched tags")
        
        if any(kw in query_lower for kw in indicator.get('keywords', [])):
            reasons.append("matched keywords")
        
        if indicator['name'].lower() in query_lower or query_lower in indicator['name'].lower():
            reasons.append("matched name")
        
        return ", ".join(reasons) if reasons else "semantic similarity"

# Usage examples
catalog = SemanticDataCatalog()

# User asks: "How has poverty changed in Africa?"
results = catalog.semantic_search(
    query="poverty change Africa",
    filters={'region': 'Africa'},
    top_k=5
)

# Returns:
# 1. Poverty Headcount Ratio (relevance: 0.89)
# 2. Poverty Gap Index (relevance: 0.85)
# 3. Gini Index (relevance: 0.72)
# 4. Income Share Bottom 10% (relevance: 0.68)
# ...
```

### Chat Integration Examples

**Query: "How has poverty changed in Africa?"**

```python
# Parse query to extract:
# - topic: "poverty"
# - action: "changed" (implies time series)
# - region: "Africa"

results = catalog.semantic_search(
    query="poverty trends Africa",
    filters={'region': 'Africa'},
    top_k=5
)

# Chat response:
"""
I found 5 poverty-related indicators for Africa:

1. **Poverty Headcount Ratio at $2.15/day** (SDG 1.1.1)
   - Coverage: 48 African countries, 1990-2023
   - Shows % of population in extreme poverty
   
2. **Poverty Headcount Ratio at $3.65/day**
   - Coverage: 48 African countries, 1990-2023
   - Higher poverty threshold
   
3. **Poverty Gap Index**
   - Coverage: 45 African countries, 1992-2023
   - Measures depth of poverty

Would you like me to show the trend over time for any of these?
"""
```

**Query: "unemployment in Europe 2020"**

```python
results = catalog.semantic_search(
    query="unemployment jobless rate",
    filters={
        'region': 'Europe',
        'year': 2020
    },
    top_k=3
)

# Chat finds and visualizes unemployment data for European countries in 2020
```

**Query: "What health data do you have for California cities?"**

```python
results = catalog.semantic_search(
    query="health healthcare medical",
    filters={
        'country': 'USA',
        'admin_level': 3  # city level
    }
)

# Filter results that have California coverage
california_results = [
    r for r in results 
    if 'file_path' in r['indicator'] 
    and 'california' in r['indicator']['file_path'].lower()
]
```

### Tagging Strategy for SDG Indicators

For SDG indicators, use comprehensive tagging:

```json
{
  "id": "ind_poverty_headcount_admin0",
  "name": "Poverty Headcount Ratio at $2.15/day",
  "sdg_alignment": ["1.1.1"],
  "sdg_goal": 1,
  "sdg_target": "1.1",
  
  "tags": [
    "poverty",
    "extreme poverty",
    "inequality",
    "economic",
    "sdg1",
    "no poverty",
    "development",
    "living standards",
    "income"
  ],
  
  "keywords": [
    "poor",
    "poverty rate",
    "destitution",
    "impoverished",
    "low income",
    "underprivileged",
    "economic hardship",
    "poverty line",
    "subsistence",
    "deprivation"
  ],
  
  "related_concepts": [
    "inequality",
    "income distribution",
    "social protection",
    "economic development",
    "standard of living"
  ]
}
```

### Auto-Generating the Catalog

Create a script to build and maintain the catalog:

```python
import os
import json
import pandas as pd
from pathlib import Path
from datetime import datetime

def generate_catalog():
    """Generate catalog from existing files"""
    catalog = {
        "metadata": {
            "catalog_version": "1.0",
            "last_updated": datetime.now().isoformat(),
            "total_datasets": 0,
            "total_indicators": 0
        },
        "geometries": [],
        "indicators": [],
        "categories": {},
        "coverage_summary": {}
    }
    
    # Scan geometries
    for geom_file in Path("geometries").rglob("*.geojson"):
        metadata = extract_geometry_metadata(geom_file)
        catalog["geometries"].append(metadata)
    
    # Scan indicators
    for parquet_file in Path("indicators").rglob("*.parquet"):
        metadata = extract_indicator_metadata(parquet_file)
        catalog["indicators"].append(metadata)
    
    # Build category summary
    catalog["categories"] = build_category_summary(catalog["indicators"])
    
    # Build coverage summary
    catalog["coverage_summary"] = build_coverage_summary(catalog)
    
    # Update counts
    catalog["metadata"]["total_indicators"] = len(catalog["indicators"])
    catalog["metadata"]["total_geometries"] = len(catalog["geometries"])
    
    # Save
    with open("data/catalog.json", "w") as f:
        json.dump(catalog, f, indent=2)
    
    print(f"Catalog generated with {len(catalog['indicators'])} indicators")
    return catalog

def extract_indicator_metadata(file_path):
    """Extract metadata from parquet file"""
    df = pd.read_parquet(file_path)
    
    # Check if metadata.json exists alongside
    metadata_file = file_path.parent / "metadata.json"
    manual_metadata = {}
    if metadata_file.exists():
        with open(metadata_file) as f:
            manual_metadata = json.load(f)
    
    # Auto-extract from data
    auto_metadata = {
        "id": generate_id_from_path(file_path),
        "file_path": str(file_path.relative_to("data")),
        "format": "parquet",
        "data_points": len(df),
        "file_size_mb": round(file_path.stat().st_size / 1024 / 1024, 2),
        "last_updated": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
    }
    
    # Extract temporal coverage
    if 'year' in df.columns:
        auto_metadata["temporal_coverage"] = {
            "start_year": int(df['year'].min()),
            "end_year": int(df['year'].max()),
            "total_years": int(df['year'].nunique()),
            "frequency": "annual"
        }
    
    # Extract geographic coverage
    if 'country' in df.columns:
        auto_metadata["geographic_coverage"] = {
            "type": "global" if df['country'].nunique() > 50 else "country",
            "countries": int(df['country'].nunique()),
            "countries_list": df['country'].unique().tolist()
        }
    
    # Merge with manual metadata (manual takes precedence)
    return {**auto_metadata, **manual_metadata}

def update_catalog_with_new_file(file_path, catalog_path="data/catalog.json"):
    """Add new dataset to existing catalog"""
    with open(catalog_path) as f:
        catalog = json.load(f)
    
    # Extract metadata
    metadata = extract_indicator_metadata(file_path)
    
    # Check if already exists
    existing_ids = [ind['id'] for ind in catalog['indicators']]
    if metadata['id'] in existing_ids:
        # Update existing
        for i, ind in enumerate(catalog['indicators']):
            if ind['id'] == metadata['id']:
                catalog['indicators'][i] = metadata
                break
    else:
        # Add new
        catalog['indicators'].append(metadata)
    
    # Update timestamp
    catalog['metadata']['last_updated'] = datetime.now().isoformat()
    
    # Save
    with open(catalog_path, "w") as f:
        json.dump(catalog, f, indent=2)
    
    print(f"Updated catalog with {metadata['name']}")
```

### Catalog Maintenance Workflow

**When adding new data:**
1. Download and process the data file
2. Create optional `metadata.json` with manual fields (tags, description, SDG alignment)
3. Run `update_catalog_with_new_file()`
4. Regenerate embeddings: `catalog.generate_embeddings()`

**Weekly/monthly maintenance:**
1. Run full catalog rebuild to catch any changes
2. Review and update tags for better search
3. Add newly discovered related indicators

### Performance Considerations

**Catalog loading:**
- JSON catalog: ~1-5 MB, loads instantly
- Embeddings: ~200 indicators × 384 dimensions × 4 bytes = ~300 KB, loads very fast
- Total: Sub-second load time

**Search performance:**
- Semantic search: ~10-50ms for 200 datasets
- Filter-based search: <1ms
- Combined: ~10-50ms total

**Storage:**
- Catalog JSON: 1-5 MB
- Embeddings: <1 MB
- Negligible compared to actual data

## 15. RAG Implementation for Chat Interface

### Two-Layer LLM Architecture

**Layer 1: Query Understanding**
Extracts structured intent from natural language questions.

**Layer 2: Query Construction & Execution**
Generates database queries and retrieves actual data.

### Integration with Catalog and Embeddings

```python
class GeographicDataRAG:
    def __init__(self):
        # Load catalog with embeddings (from Section 14)
        self.catalog = SemanticDataCatalog()
        
        # Initialize LLM client
        self.llm = anthropic.Anthropic(api_key="your-key")
    
    def process_query(self, user_question):
        """Full RAG pipeline"""
        
        # Step 1: Find relevant datasets using semantic search
        relevant_datasets = self.catalog.semantic_search(
            query=user_question,
            top_k=5
        )
        
        # Step 2: LLM Layer 1 - Extract structured intent
        intent = self.extract_intent(user_question, relevant_datasets)
        
        # Step 3: LLM Layer 2 - Generate and execute query
        data = self.execute_data_query(intent)
        
        # Step 4: Return for visualization
        return {
            'data': data,
            'metadata': intent,
            'datasets_used': relevant_datasets
        }
    
    def extract_intent(self, question, relevant_datasets):
        """LLM Layer 1: Parse user question into structured format"""
        
        dataset_context = "\n".join([
            f"- {ds['indicator']['name']}: {ds['indicator']['description']}"
            for ds in relevant_datasets
        ])
        
        prompt = f"""Extract structured information from this question:
"{question}"

Available datasets:
{dataset_context}

Return JSON with:
- topic: main indicator (e.g., "poverty", "gdp", "population")
- location: geographic area (e.g., "Africa", "USA", "Kenya")
- admin_level: 0 (country), 1 (state), 2 (county), 3 (city)
- time_range: [start_year, end_year]
- visualization_type: "time_series", "choropleth", "comparison"
- primary_dataset_id: which dataset to use
"""
        
        response = self.llm.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return json.loads(response.content[0].text)
    
    def execute_data_query(self, intent):
        """LLM Layer 2: Generate and run database query"""
        
        prompt = f"""Generate Python code to query this data:

Intent: {json.dumps(intent, indent=2)}

Available file structure:
- File: indicators/{intent['topic']}/admin_{intent['admin_level']}/[country]_all_years.parquet
- Columns: location_id, location_name, year, value

Generate pandas code to:
1. Load the parquet file
2. Filter by location and years
3. Return as DataFrame

Return only the code, no explanation.
"""
        
        response = self.llm.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        
        # Execute generated code
        query_code = response.content[0].text
        local_vars = {}
        exec(query_code, {"pd": pd, "Path": Path}, local_vars)
        
        return local_vars.get('result') or local_vars.get('df')

# Usage
rag = GeographicDataRAG()

# User asks question
result = rag.process_query("How has poverty changed in Africa since 2000?")

# Result contains:
# - data: DataFrame with actual poverty values
# - metadata: {topic: "poverty", location: "Africa", time_range: [2000, 2023], ...}
# - datasets_used: List of relevant datasets from catalog
```

### Example Query Flows

**Query 1: "How has poverty changed in Africa since 2000?"**

```python
# Step 1: Semantic search finds relevant datasets
catalog.semantic_search("poverty changed Africa")
# Returns: Poverty Headcount, Poverty Gap, Gini Index

# Step 2: LLM Layer 1 extracts intent
{
  "topic": "poverty",
  "location": "Africa",
  "admin_level": 0,
  "time_range": [2000, 2023],
  "visualization_type": "time_series",
  "primary_dataset_id": "ind_poverty_headcount_admin0"
}

# Step 3: LLM Layer 2 generates query
df = pd.read_parquet('indicators/poverty/admin_0/all_countries_all_years.parquet')
african_countries = ['Kenya', 'Nigeria', 'Ethiopia', 'Ghana', ...]
result = df[
    (df['country'].isin(african_countries)) &
    (df['year'] >= 2000) &
    (df['year'] <= 2023)
]

# Step 4: Return data for map visualization with time slider
```

**Query 2: "Compare GDP and population for California cities in 2020"**

```python
# Step 1: Search finds GDP and population datasets at admin_level 3

# Step 2: Extract intent
{
  "topics": ["gdp", "population"],
  "location": "California",
  "admin_level": 3,
  "time_range": [2020, 2020],
  "visualization_type": "comparison"
}

# Step 3: Generate multi-dataset query
gdp_df = pd.read_parquet('indicators/gdp/admin_3/usa_all_years.parquet')
pop_df = pd.read_parquet('indicators/population/admin_3/usa_all_years.parquet')

gdp_ca = gdp_df[(gdp_df['state'] == 'CA') & (gdp_df['year'] == 2020)]
pop_ca = pop_df[(pop_df['state'] == 'CA') & (pop_df['year'] == 2020)]

result = gdp_ca.merge(pop_ca, on=['city_id', 'year'])
```

**Query 3: "What health data do you have for African cities?"**

```python
# Step 1: Search catalog for health + Africa + admin_level 3
catalog.semantic_search(
    "health cities Africa",
    filters={'admin_level': 3}
)

# Returns list of available datasets (may be empty)

# Step 2: LLM responds with available options
{
  "available_datasets": [
    "Infant Mortality Rate - 15 African countries, city-level",
    "Healthcare Access Index - 8 African countries, city-level"
  ],
  "coverage_gaps": "Limited city-level health data for Africa",
  "suggestion": "Country-level data available for 48 African countries"
}
```

### Handling Updates Without Retraining

**Scenario: World Bank publishes new 2024 poverty data**

```bash
# 1. Download new data
wget https://api.worldbank.org/poverty/2024/data.csv

# 2. Convert and update parquet file
python scripts/update_dataset.py --input data.csv --indicator poverty

# 3. Update catalog metadata
python scripts/update_catalog.py

# 4. Regenerate embeddings (only if description changed)
python scripts/regenerate_embeddings.py

# Done! Chat immediately works with 2024 data
```

The LLMs don't need retraining - they query the updated files dynamically.

### Prompt Templates for Query Construction

**For time series queries:**
```python
prompt_template = """
Generate pandas code to load and filter data:

Dataset: {file_path}
Location filter: {locations}
Time filter: {start_year} to {end_year}
Columns: location_id, location_name, year, value

Return DataFrame sorted by year.
"""
```

**For multi-indicator comparisons:**
```python
prompt_template = """
Generate pandas code to merge multiple datasets:

Datasets:
- {dataset_1_path} (primary indicator)
- {dataset_2_path} (secondary indicator)

Merge on: location_id, year
Filter: {locations}, {years}
"""
```

**For spatial queries:**
```python
prompt_template = """
Generate geopandas code to:

1. Load geometry: {geometry_path}
2. Load indicator data: {data_path}
3. Join on: {join_field}
4. Filter: {filters}

Return GeoDataFrame ready for choropleth map.
"""
```

### Error Handling

```python
def safe_query_execution(self, query_code):
    """Execute generated code with safety checks"""
    
    try:
        # Execute code
        result = exec(query_code, {"pd": pd, "gpd": gpd})
        
        # Validate result
        if result is None or len(result) == 0:
            return {
                "error": "No data found",
                "suggestion": "Try broader time range or different location"
            }
        
        return {"data": result}
        
    except FileNotFoundError as e:
        # Dataset doesn't exist
        return {
            "error": "Dataset not available",
            "missing_file": str(e),
            "suggestion": "Check catalog for similar datasets"
        }
    
    except Exception as e:
        # Query error
        return {
            "error": "Query failed",
            "details": str(e),
            "suggestion": "Rephrase question or contact support"
        }
```

### Integration with Time Slider

```python
def prepare_for_time_slider(self, data, metadata):
    """Format data for time slider visualization"""
    
    return {
        "indicator": metadata['topic'],
        "location": metadata['location'],
        "years": sorted(data['year'].unique().tolist()),
        "data_by_year": {
            year: data[data['year'] == year].to_dict('records')
            for year in data['year'].unique()
        },
        "visualization_config": {
            "type": metadata['visualization_type'],
            "color_scale": self.get_color_scale(metadata['topic']),
            "initial_year": metadata['time_range'][1]  # Start at most recent
        }
    }
```

### Best Practices

**1. Cache Catalog Embeddings**
- Generate once, reload on startup
- Only regenerate when catalog changes

**2. Validate LLM-Generated Queries**
- Check file paths exist before executing
- Limit query complexity
- Sanitize user input in generated code

**3. Provide Context to Layer 2**
- Include available columns in prompt
- Show example queries
- Specify expected output format

**4. Handle Ambiguity**
- If multiple interpretations possible, ask user to clarify
- Show what was understood: "Showing poverty data for East Africa (Kenya, Uganda, Tanzania). Did you mean all of Africa?"

**5. Log and Learn**
- Track which queries work/fail
- Use failures to improve prompts
- Build library of common query patterns

## 16. Summary of Key Recommendations

**Data Sources:**
- Use government and international organization data (all free)
- Avoid Esri, Bloomberg, Nielsen, and other commercial aggregators
- For SDGs: Use World Bank or OECD bulk downloads over UN's interface

**Folder Structure:**
- Separate geometries from indicators
- Partition by indicator → admin level → country (for sub-national)
- Don't split by year (keep time together for slider)

**File Format:**
- Use Parquet for indicator data
- Use GeoJSON for geometries (simplified for web)
- Consider DuckDB for cross-file queries

**Database Design Balance:**
- Files sized < 100 MB for fast loading
- One file per indicator at country level (all countries, all years)
- One file per country at sub-national levels (all years)
- This optimizes for both single-indicator queries and time-based queries

**Metadata and Catalog:**
- Create central `catalog.json` with comprehensive metadata
- Include tags, keywords, and search_text for every dataset
- Generate embeddings for semantic search (handles queries like "poverty in Africa")
- Auto-generate catalog from files, supplement with manual metadata
- Use indexes for fast filtering by region, category, SDG, etc.

**RAG Implementation:**
- Use two-layer LLM architecture: Layer 1 (intent extraction) + Layer 2 (query generation)
- Semantic search finds relevant datasets from catalog
- LLMs generate database queries dynamically based on user questions
- Data updates don't require model retraining - just replace parquet files
- Cache catalog embeddings, regenerate only when catalog changes

**Time Slider:**
- Keep all years in one file per indicator/geography
- Pre-load data in browser for smooth performance
- Use modern web mapping libraries (Leaflet, MapLibre, Deck.gl)

**Chat Function:**
- Load catalog on startup (sub-second)
- Use semantic search with embeddings for natural language queries
- Apply filters (region, year, admin_level) after semantic ranking
- Explain matches to users (why each dataset is relevant)

## 17. Next Steps and Brainstorming Notes

## 16. Next Steps and Brainstorming Notes

## 17. Next Steps and Brainstorming Notes

**Immediate priorities:**
1. Download base geometries from GADM/Natural Earth
2. Set up folder structure (geometries/ and indicators/ with admin level subdirectories)
3. Test bulk download from World Bank for SDG indicators
4. Convert first dataset to parquet and test loading performance
5. **Create initial catalog.json structure**
6. **Build catalog generation script**
7. **Generate embeddings for semantic search**
8. Build simple time slider prototype with one indicator
9. **Implement two-layer LLM architecture for chat**
10. Test full RAG pipeline with sample queries

**Metadata and Catalog Tasks:**
1. Create catalog schema template
2. Define comprehensive tag taxonomy for all categories (economic, demographic, health, etc.)
3. Map SDG indicators to related keywords and concepts
4. Build auto-extraction script for basic metadata (from file paths and data)
5. Create manual metadata template for supplementary information
6. Generate initial embeddings with sentence-transformers
7. Test semantic search with sample queries
8. Build catalog update workflow for adding new datasets

**RAG Implementation Tasks:**
1. Set up LLM API access (Anthropic/OpenAI)
2. Create prompt templates for Layer 1 (intent extraction)
3. Create prompt templates for Layer 2 (query generation)
4. Build query validation and safety checks
5. Implement error handling for missing data
6. Test with various query patterns (time series, comparisons, spatial)
7. Build query result caching for repeated queries
8. Create feedback loop for failed queries

**Questions to explore:**
- Best way to handle missing data across time series
- How to display multiple indicators simultaneously on map
- Annotation/note system for data points
- Export functionality for sharing small datasets
- Should embeddings be regenerated periodically or only when catalog changes?
- How to handle version control for datasets (when World Bank updates historical data)
- User feedback mechanism for improving search relevance
- How to explain to users what data was found vs what they asked for
- Balance between auto-executing queries vs asking for confirmation
