# Demographics & Economic Data

Non-disaster data sources: census, energy, economic indicators.

**Technical pipeline**: See [data_pipeline.md](data_pipeline.md)
**Import guide**: See [data_import.md](data_import.md)

---

## Pipeline Status

| Country | Sources | Geometry Level | Status |
|---------|---------|----------------|--------|
| USA | 15 datasets | County | Production |
| Australia | 2 datasets | LGA | Production |
| Canada | 2 datasets | CSD | Needs converters |
| Europe | 1 dataset | NUTS 3 | Production |
| Global | 23 datasets | Country | Production |

---

## Processed Data

| Source | Converter | Output Format |
|--------|-----------|---------------|
| US Census | convert_census_population.py | loc_id, year, total_pop |
| Australia ABS | convert_abs_population.py | loc_id, year, total_pop |
| Canada StatsCan | Planned | - |

---

## Raw Data (Downloaded)

| Source | Location | Size |
|--------|----------|------|
| EPA Air Quality | Raw data/epa_aqs/ | 2.8 MB |
| EIA Energy | Raw data/eia/ | 1.4 GB |
| Eurostat NUTS 3 | Raw data/eurostat/ | 5.9 MB |
| Canada Census | Raw data/statcan/ | 25 GB |
| Australia ABS | Raw data/abs/ | 127 MB |

---

## Data Format

All demographics data uses simple long format:

```
loc_id          | year | metric      | value
USA-AL-01001    | 2020 | total_pop   | 55869
AUS-NSW-10050   | 2023 | total_pop   | 56093
DEU-DE300       | 2022 | gdp_eur     | 155000
```

This flows directly to the frontend via simple API queries - no GeoJSON transforms needed.

---

## loc_id Mapping

| Source | Geographic Level | loc_id Format |
|--------|-----------------|---------------|
| US Census | Counties | USA-{state}-{FIPS} |
| Eurostat | NUTS 3 | {ISO3}-{NUTS} |
| Canada | Census Subdivisions | CAN-{prov}-{CSD} |
| Australia | LGAs | AUS-{state}-{LGA} |

---

## Future Work

- Create Canada StatsCan converter
- Import NUTS 3 geometry for Europe
- Add currency exchange rate data (FRED, ECB)

---

*Last Updated: January 2026*
