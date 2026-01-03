# World Factbook Converter - Technical Reference

This document provides technical reference for maintaining the World Factbook data converter.

For usage instructions, see [DATA_PIPELINE.md](../DATA_PIPELINE.md#world-factbook).

---

## Files in This Folder

| File | Purpose |
|------|---------|
| `convert_world_factbook.py` | Main converter - extracts data from 21 editions (2000-2020) |
| `world_factbook_field_mappings.json` | Maps metric names to field IDs across editions |
| `world_factbook_metrics.csv` | Tracking spreadsheet: country counts per metric per edition |
| `WORLD_FACTBOOK_CONVERTER_REFERENCE.md` | This file - technical reference for parser maintenance |

### Output Locations

| Source ID | Output Path | Description |
|-----------|-------------|-------------|
| `world_factbook` | `county-map-data/data/world_factbook/` | 51 unique metrics (in catalog) |
| `world_factbook_overlap` | `county-map-data/data/world_factbook_overlap/` | 27 overlap metrics (excluded from catalog) |

---

## Metric Summary (78 Total Across All Editions)

Based on scanning all 21 editions (2000-2020), there are 78 distinct metrics tracked. These are categorized by uniqueness to World Factbook vs overlap with other data sources.

---

### UNIQUE TO WORLD FACTBOOK (40 metrics)

These metrics are NOT available in our other data sources (OWID, WHO, IMF, UN SDG).

**Infrastructure (5)**
- airports
- railways_km
- roadways_km
- waterways_km
- merchant_marine

**Military (1)**
- military_expenditure_pct

**Economy - Budgetary (4)**
- budget_surplus_deficit
- gini_index
- gross_national_saving
- taxes_revenue_pct_gdp

**Economy - Banking (3)**
- central_bank_discount_rate
- commercial_bank_prime_rate
- foreign_reserves

**Economy - Financial Markets (6)**
- market_value_traded_shares
- stock_broad_money
- stock_domestic_credit
- stock_fdi_abroad
- stock_fdi_at_home
- stock_narrow_money

**Economy - Industrial (1)**
- industrial_production_growth

**Energy - Oil (8)**
- crude_oil_production
- crude_oil_exports
- crude_oil_imports
- crude_oil_reserves
- refined_petroleum_production
- refined_petroleum_consumption
- refined_petroleum_exports
- refined_petroleum_imports

**Energy - Natural Gas (5)**
- natural_gas_production
- natural_gas_consumption
- natural_gas_exports
- natural_gas_imports
- natural_gas_reserves

**Energy - Electricity (7)**
- electricity_capacity
- electricity_exports
- electricity_imports
- electricity_fossil_pct
- electricity_nuclear_pct
- electricity_hydro_pct
- electricity_renewable_pct

---

### OVERLAP WITH OTHER SOURCES (27 metrics)

These metrics are also available in other data sources we have imported.

**Demographics - OWID/WHO (4)**
- birth_rate
- death_rate
- fertility_rate
- life_expectancy

**Demographics - OWID only (2)**
- population
- pop_growth_rate

**Health - WHO only (8)**
- child_underweight
- health_expenditures
- hiv_deaths
- hiv_living
- hiv_prevalence
- infant_mortality
- maternal_mortality
- obesity_rate

**Economy - IMF only (7)**
- current_account_balance
- exports
- imports
- external_debt
- gdp_ppp
- inflation_rate
- public_debt_pct_gdp

**Economy - IMF/OWID (2)**
- gdp_growth_rate
- gdp_per_capita_ppp

**Energy - OWID (3)**
- co2_emissions
- electricity_production
- electricity_consumption

**Education - UN SDG (1)**
- education_expenditure

---

### ALSO UNIQUE (11 metrics - verified against catalog)

After checking DATA_PIPELINE.md and SDG metadata, these 11 metrics are also effectively UNIQUE:

| Metric | Why Unique |
|--------|------------|
| area_sq_km | Basic geography, not in any source |
| broadband_subscriptions | SDG 9 has mobile coverage %, not broadband counts |
| internet_users | No source has user counts |
| internet_hosts | Deprecated metric, no source has this |
| labor_force | SDG 8 has employment %, not total workforce count |
| median_age | census_agesex is US counties only - unique at country level |
| net_migration_rate | Demographic, not in OWID population data |
| telephones_fixed | No source has landline counts |
| telephones_mobile | SDG 9 has coverage %, not subscriber counts |
| unemployment_rate | SDG 8 has manufacturing employment %, not overall rate |
| youth_unemployment | SDG 8 has strategy indicator (binary), not rate |

**Total UNIQUE metrics: 51** (40 marked + 11 verified)

---

## Import Priority

**High Priority (51 UNIQUE metrics)**: Import all - these provide data not available elsewhere.

**Low Priority (27 overlap metrics)**: Import for time series continuity, but primary source may be better for current values

---

## Overlap Comparison Results (2025-12-31)

Comparison of Factbook overlap metrics with primary sources (OWID, WHO, IMF):

### Use PRIMARY Source (Factbook adds little value)

| Metric | Factbook Coverage | Primary Source | Primary Coverage | Recommendation |
|--------|--------------|----------------|------------------|----------------|
| population | 587 obs (1999-2020) | OWID | 38,332 obs (1750-2024) | Use OWID |
| co2_emissions | 557 obs (2010-2017) | OWID | 23,370 obs (1750-2024) | Use OWID |
| current_account | 605 obs (1998-2019) | IMF | 3,291 obs (2005-2022) | Use IMF (more current) |
| goods exports | 1,113 obs (1991-2019) | IMF | 3,291 obs (2005-2022) | Use IMF (more current) |
| goods imports | 1,113 obs (1991-2020) | IMF | 3,291 obs (2005-2022) | Use IMF (more current) |

### Factbook Adds Historical Value

| Metric | Factbook Coverage | Notes |
|--------|--------------|-------|
| gdp_growth_rate | 968 obs (1995-2019) | IMF doesn't have this exact metric |
| gdp_per_capita_ppp | 1,024 obs (1993-2019) | Extends OWID GDP data |
| gdp_ppp | 777 obs (1993-2018) | Historical GDP data |
| inflation_rate | 1,029 obs (1990-2020) | Longest time series |
| external_debt | 1,010 obs (1993-2019) | No primary source equivalent |
| public_debt_pct_gdp | 513 obs (2003-2019) | Unique government debt metric |

### Factbook Adds Health Historical Value

| Metric | Factbook Coverage | WHO Coverage | Notes |
|--------|--------------|--------------|-------|
| life_expectancy | 437 obs (2003-2019) | 185 obs (2021 only) | Factbook has historical data |
| infant_mortality | 490 obs (1999-2019) | Different metric | WHO uses neonatal rate |
| hiv_prevalence | 804 obs (1999-2019) | Different metric | WHO uses incidence |
| hiv_deaths | 659 obs (1999-2019) | Not in WHO | Unique to Factbook |
| hiv_living | 799 obs (1999-2019) | Not in WHO | Unique to Factbook |
| maternal_mortality | 441 obs (2008-2017) | Not in current WHO | Historical data |
| obesity_rate | 381 obs (2007-2016) | Not in current WHO | Historical data |
| child_underweight | 278 obs (2000-2019) | Not in current WHO | Historical data |

### Factbook Unique Among Overlap

| Metric | Factbook Coverage | Notes |
|--------|--------------|-------|
| pop_growth_rate | 418 obs (2000-2020) | Not in OWID CO2 dataset |
| education_expenditure | 611 obs (1991-2019) | Different from UN SDG indicators |
| electricity_production | 836 obs (1994-2016) | Supplements OWID energy data |
| electricity_consumption | 746 obs (1994-2016) | Supplements OWID energy data |

### Data Quality Notes

- Some population values appear to be rank numbers (e.g., 202, 195) - parser bug in 2003-2007 editions
- CO2 units differ: Factbook in tonnes, OWID in million tonnes
- GDP values correlate well after filtering parsing errors
- Historical data (pre-2005) may have more parsing issues

### Year Coverage Summary

| Source | Year Range | Years | Notes |
|--------|------------|-------|-------|
| Factbook Overlap | 1990-2020 | 31 | Best recent decade coverage |
| OWID CO2 | 1750-2024 | 275 | Long history but narrow metrics |
| WHO Health | 2015-2024 | 10 | Very limited history |
| IMF BOP | 2005-2022 | 18 | No pre-2005 data |

**Key Insight**: For GDP, trade, inflation, and health metrics, World Factbook is often the ONLY source with 1990s data.

### Recommendation

1. **Keep world_factbook_overlap excluded from catalog** - prevents duplicate/conflicting data in search
2. **Use for historical fill** - pre-2005 data that IMF/WHO don't have
3. **Use for time series** - 30 years of consistent methodology across editions
4. **Use for HIV metrics** - Factbook has better historical HIV data (1999-2019) than current WHO
5. **Consider re-including specific metrics** - gdp_growth_rate, inflation_rate, hiv_* could be added to catalog as they fill real gaps

---

## Edition Format Differences (Technical Notes)

The World Factbook changed HTML structure significantly across editions. This section documents how to extract data from each era.

### Format Overview

| Era | Years | Format Type | File Location | Field IDs |
|-----|-------|-------------|---------------|-----------|
| Modern | 2018-2020 | TR rows | `fields/XXXrank.html` | 1xx-3xx (e.g., 335, 379) |
| Rankorder TR | 2015-2017 | TR rows | `rankorder/XXXXrank.html` | 2xxx (e.g., 2119, 2053) |
| Rankorder TABLE | 2010-2014 | Table-per-country | `rankorder/XXXXrank.html` | 2xxx (e.g., 2119, 2053) |
| Rankorder Simple | 2003-2009 | Simple table | `rankorder/XXXXrank.html` | 2xxx |
| Field Listing | 2002 | Field listing | `fields/XXXX.html` | 2xxx (no 'rank' suffix) |
| Text | 2000-2001 | Text paragraphs | `fields/{name}.html` | Descriptive names |

### 2018-2020 (Modern Format)

**Location**: `fields/{field_id}rank.html` (e.g., `fields/335rank.html`)

**HTML Structure**:
```html
<tr id="US" class='rankorder north-america'>
  <td>23</td>
  <td class='region'><a href='../geos/us.html'>United States</a></td>
  <td>$55,761</td>
  <td>2019 est.</td>
</tr>
```

**Extraction Method**:
- Country code: `<tr id="XX">` attribute (UPPERCASE 2-letter code)
- Rank: First `<td>` cell
- Country name: Link text in second cell
- Value: Third `<td>` cell
- Year: Fourth `<td>` cell (parse from "2019 est.")

**Regex Patterns**:
```python
# Extract all data rows
pattern = (
    r"<tr id=\"([A-Z]+)\"[^>]*>.*?"
    r"<td[^>]*>(\d+)</td>.*?"  # rank
    r"<td[^>]*>.*?<a[^>]*>([^<]+)</a>.*?</td>.*?"  # country name
    r"<td>([^<]*)</td>.*?"  # value
    r"<td>([^<]*)</td>"  # year
)
matches = re.findall(pattern, content, re.DOTALL)
# Returns: [(factbook_code, rank, country_name, value_str, year_str), ...]
```

**Metric discovery**: Scan `fields/` for files matching `*rank.html`, extract title for metric name.

### 2015-2017 (Rankorder Format - TR-based)

**Location**: `rankorder/{field_id}rank.html` (e.g., `rankorder/2119rank.html`)

**HTML Structure** (TR rows with lowercase id attribute):
```html
<tr id="ch"><td>1</td><td class="region"><a href=../geos/ch.html>China</a></td><td>1,379,302,771</td><td>July 2017 est.</td></tr>
```

**Extraction Method**:
- Country code: `<tr id="xx">` attribute (LOWERCASE 2-letter code - convert to upper)
- Rank: First `<td>` cell
- Country name: Link text in second cell
- Value: Third `<td>` cell
- Year: Fourth `<td>` cell

**Regex Patterns**:
```python
# Extract all data rows (note: lowercase country codes)
pattern = (
    r'<tr[^>]*id="([a-z]{2})"[^>]*>.*?'
    r'<td[^>]*>(\d+)</td>.*?'  # rank
    r'<td[^>]*>.*?<a[^>]*>([^<]+)</a>.*?</td>.*?'  # country name
    r'<td[^>]*>([^<]*)</td>.*?'  # value
    r'<td[^>]*>([^<]*)</td>'  # year
)
matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)
# Convert country code to uppercase: factbook_code.upper()
```

**Key differences from 2018+**:
- Files in `rankorder/` folder (not `fields/`)
- Uses 2xxx field IDs (e.g., 2119) instead of 1xx-3xx (e.g., 335)
- Country codes are LOWERCASE in HTML (ch instead of CH)

### 2010-2014 (Rankorder Format - Table Per Country)

**Location**: `rankorder/{field_id}rank.html` (e.g., `rankorder/2119rank.html`)

**HTML Structure** (each country in SEPARATE table element):
```html
<table id="ch">
  <tr>
    <td class="currentRow">1</td>
    <td><a href="../geos/ch.html"><strong>China</strong></a></td>
    <td class="category_data">1,394,015,977</td>
    <td>2014 est.</td>
  </tr>
</table>
```

**Extraction Method**:
- Country code: `<table id="xx">` attribute (lowercase 2-letter code)
- Rank: Cell with `class="currentRow"` or first numeric cell
- Country name: Link text (may be wrapped in `<strong>`)
- Value: Cell with `class="category_data"` or look for large numbers
- Year: Cell containing "YYYY est."

**Regex Patterns**:
```python
# Step 1: Find all table blocks with country codes
table_pattern = r'<table[^>]*id="([a-z]{2})"[^>]*>(.*?)</table>'
tables = re.findall(table_pattern, content, re.DOTALL | re.IGNORECASE)

# Step 2: For each table, extract data
for cia_code_lower, table_html in tables:
    cia_code = cia_code_lower.upper()

    # Extract rank (look for currentRow class)
    rank_match = re.search(r'class="currentRow"[^>]*>\s*(\d+)\s*<', table_html)

    # Extract country name (may have <strong> wrapper)
    name_match = re.search(r'geos/' + cia_code_lower + r'\.html[^>]*>(?:<strong>)?([^<]+)', table_html, re.IGNORECASE)

    # Extract value (look for category_data class)
    value_match = re.search(r'category_data[^>]*>.*?([\d,]+(?:\.\d+)?)\s*<', table_html, re.DOTALL)

    # Extract year
    year_match = re.search(r'(\d{4})\s*est\.', table_html, re.IGNORECASE)
```

**Key difference from 2015+**: Each country wrapped in its own `<table id="xx">` element instead of `<tr id="xx">`.

### 2003-2009 (Rankorder Format - Simple Table)

**Location**: `rankorder/{field_id}rank.html`

**HTML Structure** (all countries in one table, NO id attribute on rows):
```html
<tr>
  <td>1</td>
  <td><a href="../geos/ch.html">China</a></td>
  <td>1,330,141,295</td>
  <td>2008 est.</td>
</tr>
```

**Extraction Method**:
- Country code: Parse from `geos/XX.html` link href (NOT from tr/table id)
- All data in sequential `<td>` cells within `<tr>` rows
- Simpler structure than 2010-2017

**Regex Patterns**:
```python
# Count countries in a file (for scanning)
pattern = r'<a[^>]*href=["\']?\.{0,2}/?geos/([a-z]{2})\.html'
matches = re.findall(pattern, content, re.IGNORECASE)
country_count = len(set(matches))

# Extract full data row
pattern = (
    r'<tr[^>]*>.*?'
    r'<td[^>]*>.*?(\d+).*?</td>.*?'  # rank
    r'<td[^>]*>.*?<a[^>]*geos/([a-z]+)\.html[^>]*>([^<]+)</a>.*?</td>.*?'  # country
    r'<td[^>]*>([^<]*)</td>.*?'  # value
    r'<td[^>]*>([^<]*)</td>'  # year
)
```

**Key difference from 2010+**: No `id` attribute on `<tr>` or `<table>` elements. Must parse country code from the geos link href.

### 2002 (Field Listing Format)

**Location**: `fields/{field_id}.html` (NO 'rank' suffix, e.g., `fields/2001.html`)

**HTML Structure**:
```html
<tr>
  <td valign=top><a href="../geos/us.html" class="CountryLink">United States</a></td>
  <td class="Normal">purchasing power parity - $10.082 trillion (2001 est.)</td>
</tr>
```

**Extraction Method**:
- Country code: Parse from `geos/XX.html` link href
- Value and year combined in single cell - must parse text
- No separate rank column (assign ranks sequentially)

**Regex Patterns**:
```python
# Extract country and combined value/year text
pattern = (
    r"<tr[^>]*>.*?"
    r"<td[^>]*>.*?<a[^>]*href=['\"]\.{0,2}/?geos/([a-z]+)\.html['\"][^>]*>([^<]+)</a>.*?</td>.*?"
    r"<td[^>]*>([^<]+)</td>"
)
matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)
# Returns: [(cia_code, country_name, value_year_text), ...]

# Parse value from combined text like "purchasing power parity - $10.082 trillion (2001 est.)"
value_pattern = r'[\$]?([\d,\.]+)\s*(trillion|billion|million)?'
year_pattern = r'\((\d{4})\s*est\.\)'
```

**Key differences from 2003+**:
- Files in `fields/` folder (not `rankorder/`)
- NO 'rank' suffix on filenames
- Value and year combined in single cell (not separate columns)
- No rank column - countries listed alphabetically

### 2000-2001 (Text Format)

**Location**: `fields/{descriptive_name}.html` (e.g., `fields/population.html`, `fields/airports.html`)

**HTML Structure**:
```html
<p><b>China:</b><br>1,261,832,482 (July 2000 est.)</p>
```

**Extraction Method**:
- Country name: Text between `<b>` and `:</b>`
- Value and year: Text after `<br>` tag
- Must build country name -> ISO3 mapping from `geos/` folder
- No country codes in data files

**Regex Patterns**:
```python
# Extract country name and value from text format
pattern = r"<b>([^<:]+):</b>\s*<br>\s*([^<]+)"
matches = re.findall(pattern, content, re.IGNORECASE)
# Returns: [(country_name, value_text), ...]

# Build name-to-code mapping from geos folder
for filename in os.listdir(geos_path):
    if filename.endswith('.html'):
        cia_code = filename[:-5].upper()
        # Read title from geo file to get country name
        title_match = re.search(r'<title>([^<]+)</title>', content)
```

**Key differences from 2002+**:
- Uses DESCRIPTIVE filenames (population.html, airports.html) not numeric IDs
- NO country codes in data - must match by country NAME
- Text paragraphs instead of table rows
- Requires building name-to-code mapping from geos/ folder first

### Field ID Mapping

Field IDs changed completely between editions. Examples:

| Metric | 2020 | 2019 | 2018 | 2017 | 2010 | 2005 | 2000-2001 |
|--------|------|------|------|------|------|------|-----------|
| population | 335 | 335 | 335 | 2119 | 2119 | 2119 | population.html |
| gdp_per_capita | 211 | 211 | 211 | 2004 | 2004 | 2004 | gdp_-_per_capita.html |
| airports | 379 | 379 | 379 | 2053 | 2053 | 2053 | airports.html |
| military_exp | 330 | 330 | 330 | 2034 | 2034 | 2034 | military_expenditures_-_percent_of_gdp.html |
| birth_rate | 345 | 345 | 345 | 2054 | 2054 | 2054 | birth_rate.html |
| death_rate | 346 | 346 | 346 | 2066 | 2066 | 2066 | death_rate.html |
| life_expectancy | 355 | 355 | 355 | 2102 | 2102 | 2102 | life_expectancy_at_birth.html |
| infant_mortality | 354 | 354 | 354 | 2091 | 2091 | 2091 | infant_mortality_rate.html |
| fertility_rate | 356 | 356 | 356 | 2127 | 2127 | 2127 | total_fertility_rate.html |
| exports | 239 | 239 | 239 | 2078 | 2078 | 2078 | exports.html |
| imports | 242 | 242 | 242 | 2087 | 2087 | 2087 | imports.html |

Full mappings stored in `world_factbook_field_mappings.json`.

### 2000-2001 Filename Conventions

The 2000-2001 editions use descriptive filenames with underscores and dashes:

| Metric | Filename in 2000-2001 |
|--------|----------------------|
| population | population.html |
| area | area.html |
| airports | airports.html |
| birth_rate | birth_rate.html |
| death_rate | death_rate.html |
| gdp | gdp.html |
| gdp_per_capita_ppp | gdp_-_per_capita.html |
| gdp_growth_rate | gdp_-_real_growth_rate.html |
| life_expectancy | life_expectancy_at_birth.html |
| infant_mortality | infant_mortality_rate.html |
| fertility_rate | total_fertility_rate.html |
| pop_growth_rate | population_growth_rate.html |
| net_migration_rate | net_migration_rate.html |
| exports | exports.html |
| imports | imports.html |
| external_debt | debt_-_external.html |
| unemployment_rate | unemployment_rate.html |
| inflation_rate | inflation_rate_(consumer_prices).html |
| labor_force | labor_force.html |
| military_expenditure_pct | military_expenditures_-_percent_of_gdp.html |
| telephones_fixed | telephones_-_main_lines_in_use.html |
| telephones_mobile | telephones_-_mobile_cellular.html |
| internet_users | internet_users.html |
| railways_km | railways.html |
| roadways_km | highways.html |
| waterways_km | waterways.html |
| merchant_marine | merchant_marine.html |
| electricity_production | electricity_-_production.html |
| electricity_consumption | electricity_-_consumption.html |
| hiv_prevalence | hiv_aids_-_adult_prevalence_rate.html |
| hiv_living | hiv_aids_-_people_living_with_hiv_aids.html |
| hiv_deaths | hiv_aids_-_deaths.html |

### Country Code Mapping (appendix-d.html)

All editions include `appendix/appendix-d.html` with FIPS/ISO code crosswalk.
Format varies by edition:

**2010+**: `<a href="../geos/XX.html">Country</a>` followed by FIPS, ISO2, ISO3 in `<td>` cells
**2005-2009**: Country name in `<b>`, codes in subsequent `<td>` cells
**2002-2004**: Values wrapped in `<p>` tags inside `<td>` cells

### Metrics by Edition

Based on scanning all editions 2010-2020. Detailed counts per metric in `world_factbook_metrics.csv`.

| Edition | Mapped Metrics | Max Countries | Format | Notes |
|---------|----------------|---------------|--------|-------|
| 2020 | 66 | 241 | modern (TR) | 10 metrics dropped, no internet_hosts |
| 2019 | 76 | 258 | modern (TR) | - |
| 2018 | 77 | 258 | modern (TR) | +health_expenditures |
| 2017 | 77 | 254 | rankorder (TR) | Uses 2xxx field IDs, +internet_hosts |
| 2016 | 77 | 257 | rankorder (TR) | Same TR format as 2017 |
| 2015 | 74 | 257 | rankorder (TR) | Missing: median_age, central_bank_discount_rate, electricity_consumption |
| 2014 | 77 | 252 | rankorder (TABLE) | Table-per-country format begins |
| 2013 | 77 | 252 | rankorder (TABLE) | - |
| 2012 | 46 | 252 | rankorder (TABLE) | Many metrics missing |
| 2011 | 46 | 250 | rankorder (TABLE) | Many metrics missing |
| 2010 | 46 | 250 | rankorder (TABLE) | - |
| 2009 | 58 | 249 | rankorder (SIMPLE) | Simple tr/td format, 165 total rank files |
| 2008 | 57 | 258 | rankorder (SIMPLE) | 58 rank files, no median_age/gini |
| 2007 | 48 | 264 | rankorder (SIMPLE) | 50 rank files, missing pop_growth, net_migration |
| 2006 | 45 | 273 | rankorder (SIMPLE) | 47 rank files, no stock/FDI metrics |
| 2005 | 46 | 270 | rankorder (SIMPLE) | 47 rank files, lower oil import/export coverage |
| 2004 | 40 | 270 | rankorder (SIMPLE) | 44 rank files, NO airports/merchant_marine/waterways |
| 2003 | 28 | 267 | rankorder (SIMPLE) | 35 rank files, NO natural gas consumption/exports/imports |
| 2002 | 29 | 268 | field listing | 127 field files, NO crude_oil/current_account, HAS airports |
| 2001 | ~25 | 267 | text | 124 field files, descriptive names, country NAME matching |
| 2000 | ~22 | 262 | text | 119 field files, earliest edition scanned |

**Format transition points**:
- 2018: Field IDs changed from 2xxx to 1xx-3xx, files moved from rankorder/ to fields/
- 2015: Last year using TR format in rankorder/ folder
- 2014: TABLE format begins (each country in separate `<table id="xx">` element)

**Metrics dropped in 2020** (present in 2019):
- central_bank_discount_rate
- commercial_bank_prime_rate
- gini_index
- market_value_traded_shares
- stock_broad_money
- stock_domestic_credit
- stock_fdi_abroad
- stock_fdi_at_home
- stock_narrow_money
- gdp_ppp

**Metrics unique to specific editions**:
- `internet_hosts` (2017 and earlier) - dropped in 2018+
- `health_expenditures` (2018+) - may have different field ID in earlier editions
- `broadband_subscriptions` - no data in 2017

---

## Metric Availability Timeline

This section documents when specific metrics became available or were removed. Critical for the converter to know what to expect.

### Metrics Added Over Time

| Metric | First Available | Notes |
|--------|-----------------|-------|
| airports | 2002 | Present in field listing, dropped 2003-2004, returned 2005+ |
| merchant_marine | 2005 | Not available 2002-2004 |
| waterways_km | 2005 | Not available 2002-2004 |
| natural_gas_consumption | 2004 | Only reserves (2179) available in 2003 |
| natural_gas_exports | 2004 | Only reserves (2179) available in 2003 |
| natural_gas_imports | 2004 | Only reserves (2179) available in 2003 |
| natural_gas_production | 2004 | Only reserves (2179) available in 2003 |
| current_account_balance | 2004 | Not in 2002-2003 |
| foreign_reserves | 2004 | Not in 2002-2003 |
| gross_national_saving | 2004 | Called "Investment (gross fixed)" in earlier years |
| internet_hosts | 2004 | Not in 2002-2003, dropped in 2018+ |
| median_age | 2009 | Not available before 2009 |
| pop_growth_rate | 2009 | Available as field 2002 starting 2009 |
| net_migration_rate | 2009 | Available as field 2112 starting 2009 |
| gini_index | 2009 | Not available before 2009 |
| central_bank_discount_rate | 2009 | Not available before 2009 |
| commercial_bank_prime_rate | 2009 | Not available before 2009 |
| stock_fdi_abroad | 2007 | Not available before 2007 |
| stock_fdi_at_home | 2007 | Not available before 2007 |
| market_value_traded_shares | 2007 | Not available before 2007 |
| stock_domestic_credit | 2008 | Not available before 2008 |
| stock_narrow_money | 2008 | Not available before 2008 |
| education_expenditure | 2008 | Not available before 2008 |
| public_debt_pct_gdp | 2003 | Field 2186, available from 2003 |
| broadband_subscriptions | 2018 | Modern format only |
| health_expenditures | 2018 | Modern format only |

### Metrics Removed Over Time

| Metric | Last Available | Notes |
|--------|----------------|-------|
| internet_hosts | 2017 | Dropped in 2018 format change |
| central_bank_discount_rate | 2019 | Dropped in 2020 |
| commercial_bank_prime_rate | 2019 | Dropped in 2020 |
| gini_index | 2019 | Dropped in 2020 |
| market_value_traded_shares | 2019 | Dropped in 2020 |
| stock_broad_money | 2019 | Dropped in 2020 |
| stock_domestic_credit | 2019 | Dropped in 2020 |
| stock_fdi_abroad | 2019 | Dropped in 2020 |
| stock_fdi_at_home | 2019 | Dropped in 2020 |
| stock_narrow_money | 2019 | Dropped in 2020 |
| gdp_ppp | 2019 | Dropped in 2020 (only per capita remains) |

### Oil/Petroleum Field Evolution

The oil metrics changed structure over time:

| Years | Fields Available | Notes |
|-------|------------------|-------|
| 2002 | None | No oil rank data |
| 2003 | 2173 (production), 2178 (reserves), 2174 (consumption), 2175/2176 (imports/exports) | Low import/export coverage (28 countries) |
| 2004-2005 | Same as 2003 | Import/export coverage 31-58 countries |
| 2006+ | Same fields | Import/export coverage expands to 60-80 countries |
| 2008+ | Same fields | Coverage stabilizes at 200+ for production/consumption |

### Core Metrics (Available All Years 2002-2020)

These metrics are available in ALL scanned editions:
- population (2119/335)
- area_sq_km (2147/279)
- birth_rate (2054/345)
- death_rate (2066/346)
- fertility_rate (2127/356)
- life_expectancy (2102/355)
- infant_mortality (2091/354)
- gdp_ppp (2001/varies) - dropped 2020
- gdp_per_capita_ppp (2004/211)
- gdp_growth_rate (2003/210)
- exports (2078/239)
- imports (2087/242)
- external_debt (2079/246)
- inflation_rate (2092/229)
- unemployment_rate (2129/220)
- labor_force (2095/218)
- telephones_fixed (2150/196)
- telephones_mobile (2151/197)
- military_expenditure_pct (2034/330)
- railways_km (2121/384)
- roadways_km (2085/385)
- electricity_production (2038/252)
- electricity_consumption (2042/253)

---

## Scanning Process

### How to Scan an Edition

1. **Identify format** from `EDITION_FORMATS` dict in converter
2. **Locate rank files**:
   - Modern (2018+): `fields/XXXrank.html`
   - Rankorder (2003-2017): `rankorder/XXXXrank.html`
   - Field listing (2002): `fields/XXXX.html`
   - Text (2000-2001): `fields/{metric_name}.html`

3. **Count countries per metric**:
   ```python
   # For 2017+ (TR-based)
   re.findall(r'<tr[^>]*id=\"([a-z][a-z])\"[^>]*><td>(\d+)</td>', content)

   # For 2010-2016 (TABLE-based)
   re.findall(r'<table[^>]*id=\"([a-z]{2})\"[^>]*>', content)
   ```

4. **Extract metric titles** from HTML:
   ```python
   re.search(r'COUNTRY COMPARISON :: <strong>([^<]+)</strong>', content)
   ```

### Key Discoveries

**2017 vs 2018 Format Change**:
- 2017 uses `<tr id="ch">` (lowercase) in `rankorder/` folder
- 2018 uses `<tr id="CH">` (uppercase) in `fields/` folder
- Same extraction pattern works for both, just need case handling

**Field ID Schemes**:
- 2018-2020: 1xx-3xx range (e.g., 335=population, 379=airports)
- 2003-2017: 2xxx range (e.g., 2119=population, 2053=airports)
- 2000-2001: Descriptive names (e.g., population.html, airports.html)

**Edge Cases**:
- Some rank files exist but have no data (e.g., 2017 broadband)
- HTML structure varies within same era (striped rows, style attributes)
- Country codes always 2 lowercase letters in id attribute

---

## Parser Bug Fixes and Lessons Learned

This section documents parsing issues discovered during implementation and how they were resolved.

### 2009 Nested Div Issue

**Problem**: The 2009 edition wraps values in nested `<div>` elements:
```html
<td class="category_data"><div align="right">15,095</div></td>
```

The original regex `<td[^>]*>([^<]*)</td>` fails because `[^<]*` doesn't match content containing `<`.

**Solution**: Use row-by-row parsing instead of complex regex:
```python
# Split content into rows
rows = re.split(r'<tr[^>]*>', content, flags=re.IGNORECASE)

for row in rows:
    # Find elements individually within each row
    value_match = re.search(r'category_data[^>]*>(?:<div[^>]*>)?\s*([\d,.\s]+)', row)
```

**Key insight**: Avoid `re.DOTALL` with `.*?` on large files - causes catastrophic backtracking.

### 2009 Uppercase Geos Links

**Problem**: The appendix-d.html in 2009 uses UPPERCASE country codes in geos links:
```html
<a href="../geos/AF.html">Afghanistan</a>
```

But the original regex only matched lowercase: `geos/([a-z]+)\.html`

**Solution**: Use case-insensitive matching:
```python
pattern = r"geos/([a-zA-Z]+)\.html"
matches = re.findall(pattern, content, re.IGNORECASE)
cia_code = match.group(1).upper()  # Normalize to uppercase
```

### 2002 Value+Year Concatenation

**Problem**: The 2002 format combines value and year in one cell:
```html
<td class="Normal">46 (2001)</td>
```

The original `parse_value()` was stripping parentheses and concatenating digits: "46 (2001)" -> "462001" -> 462001

**Solution**: Strip year parentheses BEFORE removing other parentheses:
```python
# Remove year in parentheses like "(2001 est.)" BEFORE removing other parentheses
s = re.sub(r'\s*\(\d{4}[^)]*\)', '', s)
```

### Edition Format Detection

**Lessons learned about format detection**:

| Edition | Key Indicators | Common Pitfalls |
|---------|----------------|-----------------|
| 2018-2020 | `<tr id="XX">` uppercase, files in `fields/` | None |
| 2015-2017 | `<tr id="xx">` lowercase, files in `rankorder/` | Forget to uppercase code |
| 2010-2014 | `<table id="xx">` per country | Different from TR format |
| 2009 | `class="currentRow"`, nested divs | Regex backtracking on large files |
| 2002 | Value+year in same cell | Year included in value |
| 2000-2001 | Text format with country names | No country codes |

### Working Editions Summary

After fixing parser bugs:
- **Fully working**: 2003-2008, 2010-2020 (17 editions)
- **Partially working**: 2002 (value parsing needs more work)
- **Not implemented**: 2000-2001 (text format requires name matching)
- **Fixed but untested thoroughly**: 2009

---

## CSV Tracking File

A detailed CSV (`world_factbook_metrics.csv`) tracks metric availability across all editions:
- Row 1: Header (edition, num_countries, 80 metric columns)
- Row 2: Overlap annotations (UNIQUE, IMF, OWID, WHO, UN SDG)
- Row 3+: One row per edition with country counts per metric

Current columns: 80 total (edition + num_countries + 78 metrics)

---

*Generated: 2025-12-31 - All editions 2000-2020 scanned (21 years)*
