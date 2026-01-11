# Non-Disaster Data Sources & Pipeline

Reference for census, economic, energy, and international data sources.

**Disaster sources**: See [DATA_SOURCES_EXPLORATION.md](DATA_SOURCES_EXPLORATION.md)

Last Updated: January 10, 2026

---

## Current Pipeline Status

| Country | Sources | Geometry | Status |
|---------|---------|----------|--------|
| **USA** | 15 datasets | County-level | Production-ready |
| **Australia** | 2 datasets | LGA-level | Production-ready |
| **Canada** | 2 datasets | CSD-level | Needs more data |
| **Global** | 23 datasets | Country-level | Production-ready |
| **Europe** | 1 dataset (Eurostat) | NUTS3-level | Production-ready |

### Census/Population Converters Status

| Source | Converter | Status | Output |
|--------|-----------|--------|--------|
| US Census | `convert_census_population.py` | Complete | Long format (loc_id, year, total_pop) |
| Australia ABS | `convert_abs_population.py` | Complete | Long format (loc_id, year, total_pop) |
| Canada StatsCan | `convert_statcan_census.py` | Planned | Phase 5 pipeline validation |

---

## Currency Market Data (Planned)

Exchange rate data for currency conversions and economic analysis. Since currencies are country-level (no geographic subdivisions needed), we can afford higher temporal resolution.

### Architecture: USD as Base Currency

Store all exchange rates as **X/USD** (units of foreign currency per 1 USD):

```
EUR/USD = 0.92  (1 USD = 0.92 EUR)
CAD/USD = 1.36  (1 USD = 1.36 CAD)
GBP/USD = 0.79  (1 USD = 0.79 GBP)
```

**Cross-rate derivation** - Any pair can be calculated mathematically:
```
EUR/CAD = (EUR/USD) / (CAD/USD) = 0.92 / 1.36 = 0.676
GBP/JPY = (GBP/USD) / (JPY/USD)
```

This enables queries like "show EUR/CAD over time" without storing every possible currency pair.

### Integration with Derived Data System

The `postprocessor.py` derived field system needs enhancement to support:

1. **Currency conversion**: GDP_EUR * (USD/EUR) = GDP_USD
2. **Chained derivations**: GDP_EUR -> GDP_USD -> GDP_USD_per_capita
3. **Transform operations**: multiply, divide (not just divide by denominator)

Reference files:
- `mapmover/reference/currencies_scraped.json` - ISO3 to currency code mapping (215 countries)
- `mapmover/reference/country_metadata.json` - placeholder for additional currency metadata

### Potential Data Sources

| Source | Coverage | Frequency | Format | Cost | Notes |
|--------|----------|-----------|--------|------|-------|
| **Federal Reserve (FRED)** | 20+ major currencies | Daily/Weekly | CSV/JSON | Free | Already USD-based |
| **ECB Statistical Data Warehouse** | 40+ currencies | Daily | CSV/JSON | Free | EUR-based |
| **IMF Exchange Rates** | 180+ currencies | Monthly | CSV | Free | SDR-based, comprehensive |

### Priority Currencies

Start with major traded currencies (~20):

| Code | Currency | Priority |
|------|----------|----------|
| EUR | Euro | HIGH |
| GBP | British Pound | HIGH |
| JPY | Japanese Yen | HIGH |
| CAD | Canadian Dollar | HIGH |
| AUD | Australian Dollar | HIGH |
| CHF | Swiss Franc | HIGH |
| CNY | Chinese Yuan | HIGH |

---

## US Census Sub-County Geography

Deep dive into Census geographic levels below county.

### Geographic Hierarchy

```
USA (admin_0)
  +-- States (admin_1): 51 units
        +-- Counties (admin_2): 3,144 units        <-- CURRENT LEVEL
              +-- ZCTAs (postal): ~33,000 units
              +-- Census Tracts: 84,414 units
                    +-- Block Groups: 239,781 units
                          +-- Blocks: 8,180,866 units
```

### Data Availability by Level

| Level | Polygons | ACS Data? | Variables | Update |
|-------|----------|-----------|-----------|--------|
| **County** | 3,144 | 1-yr + 5-yr | 64,000+ | Annual |
| **ZCTA** | ~33,000 | 5-yr only | Data Profiles | Annual |
| **Tract** | 84,414 | 5-yr only | 64,000+ | Annual |
| **Block Group** | 239,781 | 5-yr only | Detailed only | Annual |
| **Block** | 8,180,866 | **NO** | ~400 fields | Decennial |

### Key Insight: Block Level Has Limited Value

Since blocks only have decennial data (population, race, housing units):
- 6+ years old (2020 Census)
- No economic/social data
- Won't update until 2030

**Recommendation**: Stop at Block Group level for most use cases.

### Downloaded Geometry Files

Location: `county-map-data/Raw data/census/geometry/`

| File | Size | Content |
|------|------|---------|
| cb_2024_us_tract_500k.zip | 56 MB | National tracts |
| cb_2024_us_bg_500k.zip | 93 MB | National block groups |
| tl_2024_us_zcta520.zip | 505 MB | National ZCTAs |

---

## EPA Air Quality System (AQS)

Historical air quality data with annual county-level AQI summaries.

- **Pre-Generated Files**: https://aqs.epa.gov/aqsweb/airdata/download_files.html
- **Coverage**: All US counties with monitors, 1980-2025
- **Format**: CSV (zipped)
- **Cost**: Free

**Pollutants Covered:** O3, PM2.5, PM10, CO, SO2, NO2, Lead

**Download URL Pattern:**
```
https://aqs.epa.gov/aqsweb/airdata/annual_aqi_by_county_[YEAR].zip
```

**Downloaded**: 2.8 MB in `county-map-data/Raw data/epa_aqs/`

---

## EIA Energy Data

US energy statistics from the Energy Information Administration.

- **Bulk Download**: https://www.eia.gov/opendata/v1/bulkfiles.php
- **Coverage**: National + State level, 1960s-present
- **Format**: JSON (bulk downloads)
- **Cost**: Free

**Bulk Files:**

| File | Description | Series Count |
|------|-------------|--------------|
| SEDS.zip | State Energy Data System | 30,000+ |
| ELEC.zip | Electricity | 408,000+ |
| NG.zip | Natural Gas | 11,989+ |
| PET.zip | Petroleum | 115,052+ |
| COAL.zip | Coal | varies |
| EMISS.zip | CO2 Emissions | varies |

**Downloaded**: 1.4 GB in `county-map-data/Raw data/eia/`

---

## Eurostat Regional Statistics (NUTS 3)

European regional statistics at NUTS 3 level (~1,165 regions).

- **Regional Database**: https://ec.europa.eu/eurostat/web/regions/database
- **GISCO Geodata**: https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/territorial-units-statistics
- **Coverage**: EU 27 + candidate countries
- **Format**: TSV, JSON-stat

**NUTS Levels:**
- NUTS 0: Countries (27 EU members)
- NUTS 1: Major regions (92 units)
- NUTS 2: Basic regions (244 units)
- NUTS 3: Small regions (1,165 units)

**Key Datasets:**
| Dataset Code | Description |
|--------------|-------------|
| demo_r_gind3 | Population change at NUTS 3 |
| nama_10r_3gdp | GDP at NUTS 3 level |
| lfst_r_lfu3rt | Unemployment rate NUTS 3 |

**Downloaded**: 5.9 MB in `county-map-data/Raw data/eurostat/`

---

## Statistics Canada Census

Canadian census population data at census subdivision (municipality) level.

- **Census Portal**: https://www12.statcan.gc.ca/census-recensement/index-eng.cfm
- **Coverage**: All census subdivisions, 1981-2021
- **Format**: CSV, PRN

**Geographic Levels:**
- Census Divisions (CD): ~293 units
- Census Subdivisions (CSD): ~5,000+ municipalities
- Dissemination Areas (DA): 57,936 units

**Downloaded Files:**
- 6 regional CSV files (Atlantic, BC, Ontario, Prairies, Quebec, Territories)
- 25 GB total extracted
- 5,161 Census Subdivisions + 57,936 Dissemination Areas

**Province Code Mapping:**
| Code | Province | Abbr |
|------|----------|------|
| 10 | Newfoundland and Labrador | NL |
| 24 | Quebec | QC |
| 35 | Ontario | ON |
| 48 | Alberta | AB |
| 59 | British Columbia | BC |

---

## Australian Bureau of Statistics (ABS)

Australian population estimates by Local Government Area.

- **Portal**: https://www.abs.gov.au/statistics/people/population/regional-population/latest-release
- **Coverage**: All LGAs, 2001-2024 (annual estimates)
- **Format**: GeoPackage (includes geometry), Excel

**Geographic Levels:**
- States and Territories (8)
- Local Government Areas (LGA): ~544 units
- Statistical Area Level 2 (SA2): ~2,472 units

**Downloaded Files:**
- `ERP_2024_LGA/` - GeoPackage with 547 LGAs, population 2001-2024 + geometry (54 MB)
- `ERP_2024_SA2/` - GeoPackage with SA2 regions (71 MB)

**State Code Mapping:**
| Code | State/Territory | Abbr |
|------|-----------------|------|
| 1 | New South Wales | NSW |
| 2 | Victoria | VIC |
| 3 | Queensland | QLD |
| 6 | Tasmania | TAS |

**Comparison: Australia vs Canada Data Quality**
| Aspect | Australia | Canada |
|--------|-----------|--------|
| Format | GeoPackage (geometry included) | CSV (geometry separate) |
| Size | 54 MB | 25 GB |
| Structure | Wide (1 row per LGA) | Long (1 row per characteristic) |
| Converter effort | Low | High |

---

## loc_id Mapping for International Sources

All data must map to the loc_id system. Format: `{ISO3}[-{admin1}[-{admin2}...]]`

### Source Compatibility

| Source | Geographic Level | Source ID | loc_id Format |
|--------|-----------------|-----------|---------------|
| **EPA AQS** | US Counties | FIPS 5-digit | `USA-{state}-{FIPS}` |
| **EIA Energy** | US States | State postal | `USA-{state}` |
| **Eurostat** | NUTS 3 regions | NUTS code | `{ISO3}-{NUTS}` |
| **Statistics Canada** | Census Subdivisions | DGUID | `CAN-{prov}-{CSD}` |
| **ABS Australia** | LGAs | State+LGA code | `AUS-{state}-{LGA}` |

### European Data (Eurostat NUTS)

```python
# Eurostat NUTS to loc_id
nuts_code = "DE300"  # Berlin
iso3 = NUTS_COUNTRY_TO_ISO3[nuts_code[:2]]  # "DEU"
loc_id = f"{iso3}-{nuts_code}"  # "DEU-DE300"
```

### Canadian Data (Statistics Canada)

```python
# Canada DGUID to loc_id
dguid = "2021A00051001105"  # Portugal Cove South, NL
province_code = dguid[9:11]  # "10" -> NL
csd_code = dguid[11:]  # "01105"
loc_id = f"CAN-{prov_abbr}-{csd_code}"  # "CAN-NL-1001105"
```

### Australian Data (ABS)

```python
# Australia ABS to loc_id
state_code = 1  # New South Wales
lga_code = 10050  # Albury
loc_id = f"AUS-{state_abbr}-{lga_code}"  # "AUS-NSW-10050"
```

---

## Geometry Considerations

For international data, two options:

1. **Use existing GADM geometry** - Build crosswalk from source IDs to GADM codes
2. **Import source geometry** - Cleaner since geometry matches data exactly

The second option is preferred:
- Import AUS LGA geometry from GeoPackage -> `AUS.parquet`
- Import NUTS 3 geometry from GISCO -> country parquets
- Import Canada CSD geometry from StatsCan -> `CAN.parquet`

---

## Download Priority Order

1. **ReliefWeb API** - Global disasters (already in disaster sources doc)
2. **EPA AQS Annual AQI** - 45 years of air quality (downloaded)
3. **EIA Bulk Data** - Energy infrastructure (downloaded)
4. **Eurostat NUTS 3** - European regional data (downloaded)
5. **Statistics Canada Census** - Canadian population (downloaded)
6. **ABS Regional Population** - Australian LGA population (downloaded)

---

*Last Updated: January 10, 2026*
