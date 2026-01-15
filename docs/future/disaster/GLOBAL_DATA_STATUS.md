# Global Data Status
*Updated: 2026-01-14*

Status tracking for non-disaster data categories. For disaster data status, see [disaster data.md](disaster%20data.md).

---

## Demographics Data

Location: `county-map-data/global/` and `county-map-data/countries/`

| Dataset | Location | Records | Coverage | Status |
|---------|----------|---------|----------|--------|
| **Eurostat** | global/eurostat/ | NUTS3 regions | EU 27 countries | COMPLETE |
| **UN Population** | global/un_population/ | Country-level | 195 countries | COMPLETE |
| **US Census** | countries/USA/census/ | County-level | USA | COMPLETE |
| **Australia ABS** | countries/AUS/abs_demographics/ | LGA-level | Australia | COMPLETE |

### Demographic Metrics Available

| Metric | USA | EU | Australia | Global |
|--------|-----|-----|-----------|--------|
| Population | Yes | Yes | Yes | Yes |
| Births | Yes | Yes | Yes | Limited |
| Deaths | Yes | Yes | Yes | Limited |
| Migration | Yes | Yes | Yes | No |
| Age Distribution | Yes | Yes | Yes | Yes |
| Density | Yes | Yes | Yes | Yes |

---

## Economic Data

| Dataset | Location | Coverage | Status |
|---------|----------|----------|--------|
| **GDP (World Bank)** | global/world_bank/ | 195 countries | COMPLETE |
| **Unemployment** | global/ilo/ | 185 countries | COMPLETE |

---

## Geographic Boundaries

Location: `county-map-data/geometry/`

| Level | Countries | Total Regions | Status |
|-------|-----------|---------------|--------|
| admin0 | 195 | 195 | COMPLETE |
| admin1 | 195 | ~4,500 | COMPLETE |
| admin2 | ~100 | ~45,000 | IN PROGRESS |

### Admin2 Coverage by Region

| Region | Countries | Admin2 Regions |
|--------|-----------|----------------|
| USA | 1 | 3,143 counties |
| EU | 27 | ~1,500 NUTS3 |
| Australia | 1 | 564 LGAs |
| Japan | 1 | 1,805 municipalities |
| Brazil | 1 | 5,572 municipalities |

---

## Data Quality Tracking

### loc_id Enrichment Status

| Dataset | Total Records | Enriched | Coverage |
|---------|---------------|----------|----------|
| Wildfires | ~815K/year | 2018-2024 | 86% |
| Floods | 4,825 | 4,825 | 100% |
| Landslides | 45,483 | 45,483 | 100% |
| Earthquakes | 1,055,868 | country only | ~30% |

---

## Pending Data Work

### High Priority
1. Complete wildfire loc_id enrichment (2002-2017)
2. Canada drought converter
3. Canada fire converter

### Medium Priority
1. Admin2 boundary coverage expansion
2. Earthquake subnational loc_id enrichment

### Low Priority
1. Historical economic data expansion
2. Climate projection data integration

---

*This document tracks non-disaster data status. For disaster-specific data, see disaster data.md and disaster_upgrades.md.*
