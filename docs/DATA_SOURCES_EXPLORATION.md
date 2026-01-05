# County Map - Data Sources Exploration

Quick reference for potential data sources to expand risk scoring capabilities.

Last Updated: January 2025

---

## Priority 1: FEMA National Risk Index (VERIFIED)

**This is the goldmine.** County-level risk data for 18 natural hazards, pre-calculated.

- **Main Download Page**: https://hazards.fema.gov/nri/data-resources
- **OpenFEMA Data**: https://www.fema.gov/about/openfema/data-sets/national-risk-index-data
- **Data Archive** (older versions): https://hazards.fema.gov/nri/data-archive
- **Coverage**: All 50 states + territories, county AND census tract level
- **Format**: CSV, Shapefile, Geodatabase (39MB - 411MB compressed)
- **Cost**: Free
- **Latest Version**: December 2025 v1.20
- **Contact**: FEMA-NRI@fema.dhs.gov

**Download Instructions:**
1. Go to https://hazards.fema.gov/nri/data-resources
2. Scroll to Downloads section
3. Click "Table format (CSV)"
4. Download nationwide or by state
5. Files named like `NRI_Table_Counties_California.csv`

**18 Hazards Covered:**
1. Avalanche
2. Coastal Flooding
3. Cold Wave
4. Drought
5. Earthquake
6. Hail
7. Heat Wave
8. Hurricane
9. Ice Storm
10. Inland Flooding
11. Landslide
12. Lightning
13. Strong Wind
14. Tornado
15. Tsunami
16. Volcanic Activity
17. Wildfire
18. Winter Weather

**Key Metrics Per County:**
- Risk Index (composite score)
- Expected Annual Loss ($)
- Social Vulnerability
- Community Resilience
- Per-hazard risk scores

**Why This Is Perfect:**
- Pre-calculated risk scores we can use directly
- Matches our county-level loc_id system
- Free, official government data
- Already combines multiple hazard types
- FIPS codes for easy joining

---

## Priority 2: NOAA Storm Events Database (VERIFIED)

Historical storm event data with bulk CSV downloads.

- **Bulk Download Page**: https://www.ncei.noaa.gov/stormevents/ftp.jsp
- **Direct CSV Directory**: https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/
- **Format Documentation**: https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/Storm-Data-Bulk-csv-Format.pdf
- **Coverage**: 1950-2025, all US counties
- **Format**: CSV (gzip compressed)
- **Cost**: Free

**Three File Types:**
1. `StormEvents_details` - Comprehensive storm event info
2. `StormEvents_fatalities` - Fatality data
3. `StormEvents_locations` - Geographic coordinates

**File Naming:** `StormEvents_[type]-ftp_v1.0_d[YYYY]_c[YYYYMMDD].csv.gz`
- `d[YYYY]` = data year
- `c[YYYYMMDD]` = compilation date

**Note:** Data arrives ~75 days after month end (e.g., January data available mid-April)

---

## Priority 3: Wildfire Risk to Communities (VERIFIED)

US Forest Service wildfire risk data with direct downloads.

- **Main Site**: https://wildfirerisk.org/
- **Download Page**: https://wildfirerisk.org/download/
- **GIS Data (All Lands)**: https://doi.org/10.2737/RDS-2020-0016-2
- **GIS Data (Populated Areas)**: https://doi.org/10.2737/RDS-2020-0060-2
- **Coverage**: All US states including Alaska and Hawaii
- **Format**: Excel spreadsheet (XLSX) + GIS by state

**Available Data:**
- Risk to Homes
- Wildfire Likelihood (Burn Probability)
- Community Wildfire Risk Reduction Zones
- Wildfire Hazard Potential
- Housing exposure and risk layers

**Tabular Download:** Spreadsheet with all wildfirerisk.org data for communities, tribal areas, counties, and states.

**Note:** Good candidate for cross-border "sibling layer" in loc_id system (wildfire zones span multiple counties/states).

---

## Priority 4: USGS Earthquake API (VERIFIED)

Real-time and historical earthquake data via REST API.

- **API Documentation**: https://earthquake.usgs.gov/fdsnws/event/1/
- **Web Services**: https://earthquake.usgs.gov/ws/
- **Data & Tools**: https://www.usgs.gov/programs/earthquake-hazards/data
- **GeoJSON Feeds**: https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php
- **Format**: GeoJSON, XML, QuakeML
- **Cost**: Free

**Example API Calls:**
```
# Earthquakes in date range
https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=2024-01-01&endtime=2024-12-31

# Magnitude 5+ only
https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=2024-01-01&endtime=2024-12-31&minmagnitude=5
```

**Note:** API returns events, not pre-calculated county risk. May need to aggregate by location.

---

## Priority 5: FEMA National Flood Hazard Layer (NFHL)

Detailed flood zone data.

- **URL**: https://www.fema.gov/flood-maps/national-flood-hazard-layer
- **Coverage**: 90%+ of US population
- **Format**: GIS files (by county or state)

**What It Provides:**
- Flood zone boundaries
- 100-year flood plains
- Special flood hazard areas
- Base flood elevations

**Use Case**: Detailed flood risk beyond the NRI composite score.

---

## Priority 6: Additional USFS Data (VERIFIED)

- **FSGeodata Clearinghouse**: https://data.fs.usda.gov/geodata/edw/datasets.php?xmlKeyword=wildfire
- **Wildfire Hazard Potential**: https://research.fs.usda.gov/firelab/products/dataandtools/wildfire-hazard-potential
- **Format**: Shapefile, ESRI File Geodatabase

---

## Other Data Sources

### HazardAware (Regional)

- **URL**: https://www.hazardaware.org/
- **Coverage**: Gulf Coast region primarily
- **Focus**: 30 years historical weather, drought, fire, flood
- **Limitation**: Regional focus (Gulf states), but interesting methodology

### Historical Weather/Disasters

| Source | URL | Coverage |
|--------|-----|----------|
| SHELDUS Database | (academic access) | US counties, hazard losses |
| NOAA NCEI | https://www.ncei.noaa.gov/ | Global climate data |

### Sea Level Rise / Coastal

| Source | URL | Coverage |
|--------|-----|----------|
| NOAA Sea Level Rise Viewer | https://coast.noaa.gov/slr/ | US coasts |
| NOAA Digital Coast | https://coast.noaa.gov/digitalcoast/data/ | Coastal data |

### Air Quality / Health

| Source | URL | Coverage |
|--------|-----|----------|
| EPA AirNow | https://www.airnow.gov/ | US real-time |
| CDC PLACES | https://www.cdc.gov/places/ | US counties |

### Infrastructure / Utilities

| Source | URL | Coverage |
|--------|-----|----------|
| EIA | https://www.eia.gov/opendata/ | US energy data |
| SAIDI/SAIFI (already have) | - | US states |

---

## Cross-Border Entities (Sibling Layer Candidates)

Some hazard zones span multiple counties/states - good candidates for the loc_id sibling layer system.

| Zone Type | Description | Data Source |
|-----------|-------------|-------------|
| **Tornado Alley** | Central US tornado corridor | NOAA Storm Events |
| **Dixie Alley** | Southeast tornado zone | NOAA Storm Events |
| **Wildfire Zones** | Western fire-prone regions | USFS Wildfire Risk |
| **Hurricane Corridors** | Gulf/Atlantic coast paths | FEMA NRI, NOAA |
| **Earthquake Fault Zones** | San Andreas, New Madrid, etc. | USGS |
| **Flood Basins** | Mississippi, Missouri river systems | FEMA NFHL |
| **Drought Regions** | Southwest, Great Plains | NOAA |

**Implementation Idea:**
- Create sibling layers for these cross-border zones
- Counties within a zone share the zone's loc_id as a parent/sibling
- Allows queries like "show all Tornado Alley counties" or "wildfire zone risk trends"

---

## Data Integration Priority

For Sheltrium risk scores, priority order:

1. **FEMA NRI** - Immediate. Download and convert. Pre-calculated composite scores.
2. **SAIDI/SAIFI** - Already have. Power reliability.
3. **NOAA Climate** - Next. Adds depth to weather risks.
4. **NFHL Flood Zones** - Property-specific flood risk.
5. **USGS Earthquake** - Regional seismic risk.
6. **Wildfire Risk** - Western states especially.

---

## Converter Needed

For FEMA NRI data, need to build:

```
data_converters/convert_fema_nri.py
```

Output format matching existing pattern:
- loc_id (county FIPS -> USA-{state}-{fips})
- Year (or "latest")
- risk_index, expected_annual_loss, social_vulnerability, community_resilience
- Per-hazard scores (earthquake_risk, flood_risk, wildfire_risk, etc.)

---

## Questions to Research

1. How often is FEMA NRI updated? (Appears annual)
2. Can we get historical NRI data for trend analysis?
3. How granular is NFHL data? (Parcel-level?)
4. Are there APIs or just file downloads?
5. License restrictions on redistribution?

---

## Next Steps

- [ ] Download FEMA NRI county-level CSV
- [ ] Examine schema and field names
- [ ] Build converter following existing pattern
- [ ] Test with a few states
- [ ] Add to catalog.json

---

*Quick reference doc for laptop session.*
