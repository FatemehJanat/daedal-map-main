"""Generate v6 discrepancy report - includes 2025 CIA scrape data."""
import pandas as pd
from datetime import datetime

# Load parquet files
unique = pd.read_parquet('c:/Users/Bryan/Desktop/county-map-data/data/world_factbook/all_countries.parquet')
overlap = pd.read_parquet('c:/Users/Bryan/Desktop/county-map-data/data/world_factbook_overlap/all_countries.parquet')

unique_metrics = [c for c in unique.columns if c not in ['loc_id', 'year', 'factbook_edition']]
overlap_metrics = [c for c in overlap.columns if c not in ['loc_id', 'year', 'factbook_edition']]

# All editions now including 2025 from CIA scrape
all_editions = sorted(unique['factbook_edition'].unique(), reverse=True)
good_editions = [2025, 2020, 2019, 2018, 2017, 2016, 2015, 2012, 2010, 2008, 2007, 2006, 2005, 2004, 2003, 2002]
bad_editions = [2014, 2013, 2011, 2009]  # Low fill rates

output = []
output.append('=' * 120)
output.append('WORLD FACTBOOK DATA COVERAGE REPORT - V6 (WITH 2025 CIA SCRAPE)')
output.append('=' * 120)
output.append('')
output.append(f'Report Date: {datetime.now().strftime("%Y-%m-%d")}')
output.append('New in V6: Added 2025 edition from CIA World Factbook online archive scrape')
output.append('')

# Show all editions available
output.append('=' * 80)
output.append('ALL EDITIONS IN DATASET')
output.append('=' * 80)
output.append('')
output.append(f'Editions available: {sorted(all_editions, reverse=True)}')
output.append(f'Total editions: {len(all_editions)}')
output.append('')

# Edition quality ranking
output.append('=' * 80)
output.append('EDITION QUALITY RANKING')
output.append('=' * 80)
output.append('')
output.append('GOOD editions (use these):')
for ed in good_editions:
    ed_u = unique[unique['factbook_edition'] == ed]
    ed_o = overlap[overlap['factbook_edition'] == ed]
    u_vals = ed_u[unique_metrics].notna().sum().sum() if len(ed_u) > 0 else 0
    o_vals = ed_o[overlap_metrics].notna().sum().sum() if len(ed_o) > 0 else 0
    u_rows = len(ed_u)
    o_rows = len(ed_o)
    u_fill = u_vals / (u_rows * len(unique_metrics)) * 100 if u_rows > 0 else 0
    o_fill = o_vals / (o_rows * len(overlap_metrics)) * 100 if o_rows > 0 else 0
    new_tag = " <-- NEW" if ed == 2025 else ""
    output.append(f'  {ed}: unique={u_vals:5d} vals ({u_fill:4.1f}%), overlap={o_vals:5d} vals ({o_fill:4.1f}%){new_tag}')

output.append('')
output.append('BAD editions (skip these):')
for ed in bad_editions:
    ed_u = unique[unique['factbook_edition'] == ed]
    ed_o = overlap[overlap['factbook_edition'] == ed]
    u_vals = ed_u[unique_metrics].notna().sum().sum() if len(ed_u) > 0 else 0
    o_vals = ed_o[overlap_metrics].notna().sum().sum() if len(ed_o) > 0 else 0
    u_rows = len(ed_u)
    o_rows = len(ed_o)
    u_fill = u_vals / (u_rows * len(unique_metrics)) * 100 if u_rows > 0 else 0
    o_fill = o_vals / (o_rows * len(overlap_metrics)) * 100 if o_rows > 0 else 0
    output.append(f'  {ed}: unique={u_vals:5d} vals ({u_fill:4.1f}%), overlap={o_vals:5d} vals ({o_fill:4.1f}%) <-- LOW')

# Filter to good editions only
unique_good = unique[unique['factbook_edition'].isin(good_editions)]
overlap_good = overlap[overlap['factbook_edition'].isin(good_editions)]

output.append('')
output.append('=' * 80)
output.append('COVERAGE WITH GOOD EDITIONS (INCLUDING 2025)')
output.append('=' * 80)
output.append('')

# Dedupe by (loc_id, year) keeping newest edition first
unique_good = unique_good.sort_values('factbook_edition', ascending=False)
agg_dict_u = {col: 'first' for col in unique_metrics}
unique_dedup = unique_good.groupby(['loc_id', 'year'], as_index=False).agg(agg_dict_u)

overlap_good = overlap_good.sort_values('factbook_edition', ascending=False)
agg_dict_o = {col: 'first' for col in overlap_metrics}
overlap_dedup = overlap_good.groupby(['loc_id', 'year'], as_index=False).agg(agg_dict_o)

output.append(f'Unique dataset: {len(unique_dedup)} unique (country, year) pairs')
output.append(f'Overlap dataset: {len(overlap_dedup)} unique (country, year) pairs')

# Get actual year range and country count
countries_u = unique_dedup['loc_id'].nunique()
years_u = sorted(unique_dedup['year'].unique())
countries_o = overlap_dedup['loc_id'].nunique()
years_o = sorted(overlap_dedup['year'].unique())

output.append(f'')
output.append(f'Unique: {countries_u} countries, years {min(years_u)}-{max(years_u)} ({len(years_u)} years)')
output.append(f'Overlap: {countries_o} countries, years {min(years_o)}-{max(years_o)} ({len(years_o)} years)')

# Calculate realistic max per metric
output.append('')
output.append('=' * 80)
output.append('METRIC COVERAGE (GOOD EDITIONS)')
output.append('=' * 80)
output.append('')
output.append('UNIQUE METRICS:')
output.append(f'{"Metric":<35} {"Actual":>8} {"Max":>8} {"Coverage":>10}')
output.append('-' * 65)

u_total_actual = 0
u_total_max = len(unique_dedup)

coverage_data_u = []
for m in unique_metrics:
    actual = unique_dedup[m].notna().sum()
    max_val = len(unique_dedup)
    pct = actual / max_val * 100 if max_val > 0 else 0
    coverage_data_u.append((m, actual, max_val, pct))
    u_total_actual += actual

coverage_data_u.sort(key=lambda x: -x[3])
for m, actual, max_val, pct in coverage_data_u:
    output.append(f'{m:<35} {actual:>8,} {max_val:>8,} {pct:>9.1f}%')

output.append('')
output.append(f'UNIQUE SUBTOTAL: {u_total_actual:,} / {u_total_max * len(unique_metrics):,} = {u_total_actual / (u_total_max * len(unique_metrics)) * 100:.1f}%')

output.append('')
output.append('OVERLAP METRICS:')
output.append(f'{"Metric":<35} {"Actual":>8} {"Max":>8} {"Coverage":>10}')
output.append('-' * 65)

o_total_actual = 0
o_total_max = len(overlap_dedup)

coverage_data_o = []
for m in overlap_metrics:
    actual = overlap_dedup[m].notna().sum()
    max_val = len(overlap_dedup)
    pct = actual / max_val * 100 if max_val > 0 else 0
    coverage_data_o.append((m, actual, max_val, pct))
    o_total_actual += actual

coverage_data_o.sort(key=lambda x: -x[3])
for m, actual, max_val, pct in coverage_data_o:
    output.append(f'{m:<35} {actual:>8,} {max_val:>8,} {pct:>9.1f}%')

output.append('')
output.append(f'OVERLAP SUBTOTAL: {o_total_actual:,} / {o_total_max * len(overlap_metrics):,} = {o_total_actual / (o_total_max * len(overlap_metrics)) * 100:.1f}%')

# Grand total
grand_actual = u_total_actual + o_total_actual
grand_max = (u_total_max * len(unique_metrics)) + (o_total_max * len(overlap_metrics))
output.append('')
output.append('=' * 80)
output.append('GRAND TOTAL')
output.append('=' * 80)
output.append(f'Total data points: {grand_actual:,}')
output.append(f'Theoretical max: {grand_max:,}')
output.append(f'Overall coverage: {grand_actual / grand_max * 100:.1f}%')

# Compare V5 vs V6 (before and after 2025 merge)
output.append('')
output.append('=' * 80)
output.append('IMPROVEMENT FROM 2025 SCRAPE')
output.append('=' * 80)
output.append('')

# Count 2025 contribution
ed_2025_u = unique[unique['factbook_edition'] == 2025]
ed_2025_o = overlap[overlap['factbook_edition'] == 2025]
new_u_vals = ed_2025_u[unique_metrics].notna().sum().sum() if len(ed_2025_u) > 0 else 0
new_o_vals = ed_2025_o[overlap_metrics].notna().sum().sum() if len(ed_2025_o) > 0 else 0

output.append(f'2025 edition contribution:')
output.append(f'  Unique metrics: {new_u_vals:,} new data points from {len(ed_2025_u)} rows')
output.append(f'  Overlap metrics: {new_o_vals:,} new data points from {len(ed_2025_o)} rows')
output.append(f'  Total new: {new_u_vals + new_o_vals:,} data points')

# Year coverage from 2025
if len(ed_2025_u) > 0:
    years_2025 = sorted(ed_2025_u['year'].unique())
    output.append(f'')
    output.append(f'Years covered by 2025 edition: {years_2025}')
    output.append(f'Countries in 2025 edition: {ed_2025_u["loc_id"].nunique()}')

# Metrics scraped from 2025
output.append('')
output.append('Metrics scraped from 2025 CIA archive:')
scraped_unique = []
scraped_overlap = []
for m in unique_metrics:
    if ed_2025_u[m].notna().sum() > 0:
        scraped_unique.append(m)
for m in overlap_metrics:
    if ed_2025_o[m].notna().sum() > 0:
        scraped_overlap.append(m)

output.append(f'  Unique ({len(scraped_unique)}): {", ".join(scraped_unique)}')
output.append(f'  Overlap ({len(scraped_overlap)}): {", ".join(scraped_overlap)}')

output.append('')
output.append('=' * 80)
output.append('SUMMARY')
output.append('=' * 80)
output.append('')
output.append(f'Total editions: {len(all_editions)} (2000-2025)')
output.append(f'Good editions used: {len(good_editions)}')
output.append(f'Bad editions skipped: {len(bad_editions)} (2009, 2011, 2013, 2014)')
output.append(f'')
output.append(f'Final coverage: {grand_actual / grand_max * 100:.1f}%')
output.append(f'Total data points: {grand_actual:,}')
output.append('')

# Print and save
report = '\n'.join(output)
print(report)

with open('world_factbook_discrepancy_report_v6.txt', 'w', encoding='utf-8') as f:
    f.write(report)

print('\nSaved to world_factbook_discrepancy_report_v6.txt')
