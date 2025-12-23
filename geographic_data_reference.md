# Geographic Data Reference

Reference guide for data sources, geographic frameworks, and edge cases.

---

## Alternative Geographic Frameworks

Beyond the standard admin hierarchy (country > state > county), other frameworks exist:

### Statistical and Functional Regions
- **Metropolitan Statistical Areas (MSAs)**: Cross city/county boundaries, defined by economic ties
- **OECD Functional Urban Areas**: Globally standardized metropolitan definitions
- **Eurostat NUTS Regions**: Hierarchical system for Europe

### Grid-Based Systems
- **H3 Hexagonal Grids**: Uber's hierarchical geospatial indexing
- **Lat/Long Grid Cells**: Climate data (1x1 or 0.5x0.5 degree cells)
- **MGRS/UTM Zones**: Military Grid Reference System

### Natural Boundaries
- **Watershed/River Basins**: Water resource and environmental data
- **Ecoregions/Biomes**: Biodiversity and conservation
- **Climate Zones**: Koppen climate classification

### Supranational Regions
- **UN Geoscheme**: "Western Africa", "Southern Asia"
- **Trade Blocs**: USMCA, MERCOSUR, ASEAN, EU
- Already implemented in conversions.json

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

---

## Geometry Sources

### GADM (Current Source)
- **URL**: gadm.org
- **Coverage**: Admin boundaries for every country, levels 0-5
- **Format**: GeoPackage, Shapefiles
- **License**: Free for non-commercial, attribution required
- **Notes**: Used for process_gadm.py

### Natural Earth
- **URL**: naturalearthdata.com
- **Coverage**: Admin boundaries, populated places, physical features
- **Scales**: 1:10m (detailed), 1:50m (medium), 1:110m (small)
- **License**: Public domain
- **Best for**: Simplified country borders, physical features

### geoBoundaries
- **URL**: geoboundaries.org
- **Coverage**: Open admin boundaries, simplified versions
- **Format**: GeoJSON, Shapefiles, API
- **License**: Fully open (better than GADM for commercial)
- **Notes**: Good alternative, has pre-simplified versions

### US Census TIGER/Line
- **URL**: census.gov/geographies/mapping-files.html
- **Coverage**: States, counties, ZCTAs, census tracts, blocks
- **License**: Public domain
- **Notes**: Most detailed US boundaries, updated annually

### Country-Specific Sources
- **UK**: ONS Geography Portal (geoportal.statistics.gov.uk)
- **Canada**: Statistics Canada Boundary Files
- **Australia**: ABS (Australian Bureau of Statistics)
- **EU**: Eurostat GISCO (ec.europa.eu/eurostat/web/gisco)

### Humanitarian Data
- **HDX**: data.humdata.org - Often more current for developing nations

---

## Data Sources - Free vs Paid

### Always Free (Use These)

**Government Statistical Agencies:**
- US Census Bureau - public domain
- BLS (Bureau of Labor Statistics)
- NOAA/NASA - public domain
- USGS - public domain
- EIA (Energy Information Administration)
- Most national statistical offices (Eurostat, Statistics Canada, etc.)
- Central banks (Federal Reserve, ECB, etc.)

**International Organizations:**
- World Bank Open Data
- IMF Data
- UN agencies (UNDP, WHO, FAO)
- OECD Data (core data free)

**Climate/Environmental:**
- NOAA Climate Data
- NASA Earth Data
- Copernicus (EU Earth observation)
- Landsat (USGS) and Sentinel (ESA)

### Avoid (Paid/Restricted)

**Financial Data:**
- Bloomberg Terminal ($20k+/year)
- Refinitiv (Thomson Reuters)
- S&P Capital IQ
- FactSet

**Commercial Data:**
- Nielsen data
- Experian/Equifax consumer data
- CoreLogic real estate
- Esri demographic layers (repackaged census data)

**Energy (Paid):**
- S&P Global Platts
- Wood Mackenzie
- IHS Markit

**Rule of thumb**: If it requires a "sales inquiry" or "demo", it's paid.

### Licensing Notes

**GADM**: Free for non-commercial. For commercial, technically need license.

**OpenStreetMap**: ODbL license - requires attribution and share-alike.

---

## Bulk Download Tips

**Look for these on data portals:**
1. "Bulk download" or "Data dump" links (often in footer)
2. FTP servers (many government sites still use these)
3. "API" pages often link to bulk files
4. Check robots.txt for bulk data locations

**For SDG data:**
- Use World Bank or OECD bulk downloads over UN's interface
- API: `https://api.worldbank.org/v2/sdg/Goal/1/Target/1.1/Indicator/1.1.1?format=json`
- Better: Use bulk CSV/Excel files at data.worldbank.org

---

*Last Updated: 2025-12-21*
