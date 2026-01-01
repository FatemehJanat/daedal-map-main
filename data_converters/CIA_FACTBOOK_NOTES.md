# CIA Factbook Data Import - Technical Notes

## Status: READY FOR IMPORT

- Converter script: `convert_cia_factbook.py`
- Field mappings: `cia_field_mappings.json`
- Raw data: 21 editions available (2000-2020)
- Decision: Single combined dataset with `factbook_edition` column

---

## Edition Format Discovery

The CIA Factbook changed HTML structure significantly across editions:

| Years | Format | Location | File Pattern | Parser |
|-------|--------|----------|--------------|--------|
| 2000-2001 | Text-based | fields/ | population.html | extract_data_2000_text |
| 2002 | Field listing | fields/ | 2001.html (no 'rank') | extract_data_2002_field_listing |
| 2003-2017 | Ranked tables | rankorder/ | 2001rank.html | extract_data_2003_2017 |
| 2018-2020 | Modern HTML | fields/ | 335rank.html | extract_data_2020 |

### Key Differences

**2000-2001 (Text format)**
- Descriptive filenames: `population.html`, `airports.html`
- Pattern: `<b>CountryName:</b><br>Value (year est.)`
- No rank column, no geos links in data

**2002 (Transition format)**
- 2xxx field IDs: `2001.html`, `2003.html`
- No "rank" suffix, files in `fields/`
- Combined value+year in single cell
- Pattern: Country link + text value

**2003-2017 (Rank Order format)**
- 2xxx field IDs: `2001rank.html`
- Located in `rankorder/` folder
- Separate columns: Rank, Country, Value, Year
- Pattern: `<a href="../geos/us.html" class="CountryLink">United States</a>`

**2018-2020 (Modern format)**
- 1xx-3xx field IDs: `335rank.html`
- Located in `fields/` folder
- Pattern: `<tr id="US">` with country code in row ID

### Field ID Mapping

Field IDs changed between formats:

| Metric | 2018-2020 | 2002-2017 | 2000-2001 |
|--------|-----------|-----------|-----------|
| population | 335 | 2119 | population.html |
| gdp_per_capita_ppp | 211 | 2004 | gdp_-_per_capita.html |
| airports | 379 | 2053 | airports.html |
| military_expenditure | 330 | 2034 | military_expenditures_-_percent_of_gdp.html |

Full mappings in `cia_field_mappings.json`.

---

## Output Structure

```
data/cia_factbook/
    all_countries.parquet  # All editions combined
    metadata.json          # Source info, metric definitions
```

The parquet file includes:
- `loc_id`: ISO3 country code
- `year`: Data year (from source)
- `factbook_edition`: Which edition data came from
- Metric columns (population, gdp_per_capita_ppp, etc.)

---

## Metrics Available (26 mapped)

### Demographics
- population, median_age, pop_growth_rate
- birth_rate, death_rate, life_expectancy, fertility_rate

### Economy
- gdp_growth_rate, gdp_per_capita_ppp
- unemployment_rate, inflation_rate
- exports, imports, external_debt

### Energy
- electricity_production, electricity_consumption
- crude_oil_production, natural_gas_production

### Infrastructure
- airports, railways_km, roadways_km
- telephones_fixed, telephones_mobile, internet_users

### Military
- military_expenditure_pct

### Geography
- area_sq_km

---

## Usage

```bash
# List mapped metrics
python data_converters/convert_cia_factbook.py --list-metrics

# Dry run on single edition
python data_converters/convert_cia_factbook.py --editions 2020 --dry-run

# Dry run on all editions
python data_converters/convert_cia_factbook.py --editions 2000,2001,2002,2003,2004,2005,2006,2007,2008,2009,2010,2011,2012,2013,2014,2015,2016,2017,2018,2019,2020 --dry-run

# Full import
python data_converters/convert_cia_factbook.py --editions 2000,2005,2010,2015,2020 --save
```

---

## Data Source Priority

When CIA Factbook overlaps with existing sources:

| Metric | Use CIA? | Reason |
|--------|----------|--------|
| military_expenditure_pct | PRIMARY | Unique to CIA |
| airports, railways, roads | PRIMARY | Unique to CIA |
| electricity_production | PRIMARY | More detail than OWID |
| population | SECONDARY | OWID more current |
| GDP | SECONDARY | IMF is primary source |
| life_expectancy | SECONDARY | WHO is primary source |

---

## Technical Notes

### Country Code Mapping
- All editions use 2-letter CIA codes (us, ch, in, etc.)
- Mapped to ISO3 via `appendix/appendix-d.html` (contains FIPS to ISO crosswalk)
- 248 countries typically mapped successfully

### Value Parsing
- Handles: `$55,761`, `1.5 trillion`, `45.6 million`, `-2.5%`
- Removes currency symbols, commas
- Applies multipliers (trillion, billion, million)

### Year Parsing
- Extracts year from strings like "2019 est." or "(2020)"
- Falls back to `factbook_edition - 1` if not specified

### Deduplication
- When same (loc_id, year) appears in multiple editions
- More recent factbook edition takes precedence

---

*Last Updated: 2025-12-31*
