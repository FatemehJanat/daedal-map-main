# CIA Factbook Data Import - Planning Notes

## Status
- Converter script created: `convert_cia_factbook.py`
- Tested with 2020 edition: 238 countries, 66 available metrics
- Data folders NOT created yet - pending decisions below

## Raw Data Available
- `factbook-2020/` - downloaded, tested
- Earlier editions (2000-2019) available as zip files online
- 2024 edition available online (live website)

## Decisions Needed

### 1. Folder Organization

**Option A: Single combined dataset**
```
data/cia_factbook/
    all_countries.parquet  (all editions merged, year column)
    metadata.json
```
- Pro: Simple, single source to query
- Con: Data from different editions may conflict

**Option B: Per-edition datasets**
```
data/cia_factbook_2020/
    all_countries.parquet
    metadata.json
data/cia_factbook_2024/
    all_countries.parquet
    metadata.json
```
- Pro: Clear provenance, can compare editions
- Con: More files, need to pick which to use

**Option C: Combined with edition tracking (RECOMMENDED)**
```
data/cia_factbook/
    all_countries.parquet  (has factbook_edition column)
    metadata.json
```
- Pro: Best of both - single file, but can filter by edition
- Con: Slightly larger file

### 2. Data Source Trust Hierarchy

When CIA Factbook overlaps with existing sources, which takes precedence?

| Metric | CIA Factbook | Existing Source | Recommended Primary |
|--------|--------------|-----------------|---------------------|
| Population | Yes | OWID, Census | OWID (more current) |
| GDP | Yes | OWID, IMF | IMF (primary source) |
| Life expectancy | Yes | WHO | WHO (primary source) |
| CO2 emissions | Yes | OWID | OWID (more granular) |
| Military spending | Yes | None | **CIA (unique)** |
| Infrastructure | Yes | None | **CIA (unique)** |
| Energy sources % | Yes | Limited in OWID | **CIA (more detail)** |

**Suggested approach**: Use CIA Factbook as PRIMARY for:
- Military expenditure
- Infrastructure (airports, railways, roads, waterways)
- Energy source percentages
- Telecom infrastructure

Use as SECONDARY/VALIDATION for:
- Demographics (population, life expectancy)
- Economy (GDP, unemployment)

### 3. Time Series Strategy

If we download all editions (2000-2024):
- ~25 editions x ~200 countries x ~60 metrics = potential for rich time series
- But: Same country/year may have different values in different editions
- Resolution strategy: Trust most recent edition for any given (country, year, metric)

### 4. Language/Religion Data

The factbook also has:
- Languages by country with percentages
- Religions by country with percentages
- Ethnic groups

These could be separate datasets:
```
data/cia_languages/
    all_countries.parquet
    metadata.json

data/cia_religions/
    all_countries.parquet
    metadata.json
```

Or combined into a reference dataset.

## Metrics Available (66 total)

### Priority Metrics (unique or best-in-class from CIA)
- military_expenditure_pct
- airports, railways_km, roadways_km, waterways_km
- merchant_marine
- electricity source percentages (fossil, nuclear, hydro, renewable)
- crude oil/natural gas production, consumption, reserves
- telephones_fixed, telephones_mobile, broadband_subscriptions

### Overlap Metrics (good for cross-validation)
- population, median_age, life_expectancy, infant_mortality
- gdp_per_capita_ppp, unemployment_rate, public_debt
- birth_rate, death_rate, fertility_rate

### Full list: Run `python convert_cia_factbook.py --list-metrics`

## Next Steps

1. [ ] Decide on folder organization (Option A/B/C)
2. [ ] Decide which metrics to extract by default
3. [ ] Download additional factbook editions if time series wanted
4. [ ] Create output folders and run conversion
5. [ ] Update catalog.json with new source
6. [ ] Add LLM summary for data discovery

## Usage

```bash
# List available metrics
python data_converters/convert_cia_factbook.py --list-metrics

# Dry run (test extraction, no output)
python data_converters/convert_cia_factbook.py --year 2020 --dry-run

# Extract priority metrics only
python data_converters/convert_cia_factbook.py --year 2020 --output ../county-map-data/data/cia_factbook

# Extract all 66 metrics
python data_converters/convert_cia_factbook.py --year 2020 --all-metrics --output ../county-map-data/data/cia_factbook
```
