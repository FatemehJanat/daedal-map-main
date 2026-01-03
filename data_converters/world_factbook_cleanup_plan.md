# World Factbook Data Cleanup Plan

## 1. Split v9 parquet into unique/overlap
- [ ] Load v9 parquet (78 metrics, 6832 rows)
- [ ] Split into UNIQUE metrics (52) -> world_factbook/all_countries.parquet
- [ ] Split into OVERLAP metrics (26) -> world_factbook_overlap/all_countries.parquet
- [ ] Keep loc_id, year, factbook_edition in both

## 2. Clean up old parquet versions
- [ ] Delete old versions: v5, v6, v7, v7_fixed, v8, v9 parquets
- [ ] Delete old 2025_only parquets
- [ ] Keep only all_countries.parquet in each folder

## 3. Regenerate world_factbook/metadata.json
- [ ] Update source description with editions 2002-2025
- [ ] Update row_count, temporal_coverage (now includes 2021-2025 web scrapes)
- [ ] List all 52 unique metrics with proper units
- [ ] Update llm_summary

## 4. Regenerate world_factbook_overlap/metadata.json
- [ ] Update editions 2002-2025
- [ ] List all 26 overlap metrics
- [ ] Add "excluded": true or equivalent to hide from catalogue
- [ ] Note which sources have primary data (OWID, WHO, IMF, UN SDG)

## 5. Update data catalogue
- [ ] Find catalogue file location
- [ ] Ensure world_factbook (unique) is included
- [ ] Ensure world_factbook_overlap is excluded or deprioritized
- [ ] Update any references to old parquet versions

## Metric Lists

### UNIQUE (52 metrics) - stays in world_factbook:
- Infrastructure: airports, railways_km, roadways_km, waterways_km, merchant_marine
- Military: military_expenditure_pct
- Telecom: telephones_fixed, telephones_mobile, internet_users, internet_hosts, broadband_subscriptions
- Oil/Gas: crude_oil_production, crude_oil_exports, crude_oil_imports, crude_oil_reserves,
           natural_gas_production, natural_gas_consumption, natural_gas_exports, natural_gas_imports, natural_gas_reserves,
           refined_petroleum_production, refined_petroleum_consumption, refined_petroleum_exports, refined_petroleum_imports
- Electricity: electricity_capacity, electricity_exports, electricity_imports,
               electricity_fossil_pct, electricity_nuclear_pct, electricity_hydro_pct, electricity_renewable_pct
- Financial: unemployment_rate, youth_unemployment, labor_force, industrial_production_growth,
             gini_index, foreign_reserves, central_bank_discount_rate, commercial_bank_prime_rate,
             budget_surplus_deficit, taxes_revenue_pct_gdp, gross_national_saving
- Stock/Markets: market_value_traded_shares, stock_fdi_abroad, stock_fdi_at_home,
                 stock_domestic_credit, stock_broad_money, stock_narrow_money
- Other: area_sq_km, median_age, net_migration_rate, pop_growth_rate

### OVERLAP (26 metrics) - moves to world_factbook_overlap:
- OWID: population, co2_emissions
- WHO: birth_rate, death_rate, fertility_rate, infant_mortality, life_expectancy,
       maternal_mortality, obesity_rate, child_underweight, hiv_deaths, hiv_living,
       hiv_prevalence, health_expenditures
- IMF: gdp_ppp, gdp_per_capita_ppp, gdp_growth_rate, exports, imports, external_debt,
       current_account_balance, public_debt_pct_gdp, inflation_rate
- UN SDG: education_expenditure
- Energy: electricity_production, electricity_consumption
