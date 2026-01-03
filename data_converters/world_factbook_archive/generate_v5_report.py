"""Generate v5 discrepancy report with top-down strategy."""
import pandas as pd

# Load parquet files
unique = pd.read_parquet('c:/Users/Bryan/Desktop/county-map-data/data/world_factbook/all_countries.parquet')
overlap = pd.read_parquet('c:/Users/Bryan/Desktop/county-map-data/data/world_factbook_overlap/all_countries.parquet')

unique_metrics = [c for c in unique.columns if c not in ['loc_id', 'year', 'factbook_edition']]
overlap_metrics = [c for c in overlap.columns if c not in ['loc_id', 'year', 'factbook_edition']]

# Recommended editions (skip problematic ones)
good_editions = [2020, 2019, 2018, 2017, 2016, 2015, 2012, 2010, 2008, 2007, 2006, 2005, 2004, 2003, 2002]
bad_editions = [2014, 2013, 2011, 2009]  # Low fill rates

output = []
output.append('=' * 120)
output.append('WORLD FACTBOOK DATA COVERAGE REPORT - V5 (TOP-DOWN STRATEGY)')
output.append('=' * 120)
output.append('')
output.append('Strategy: Use newest editions first, skip problematic years (2009, 2011, 2013, 2014)')
output.append('')

# Calculate coverage using ONLY good editions
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
    u_fill = u_vals / (len(ed_u) * len(unique_metrics)) * 100 if len(ed_u) > 0 else 0
    o_fill = o_vals / (len(ed_o) * len(overlap_metrics)) * 100 if len(ed_o) > 0 else 0
    output.append(f'  {ed}: unique={u_vals:5d} vals ({u_fill:4.1f}%), overlap={o_vals:5d} vals ({o_fill:4.1f}%)')

output.append('')
output.append('BAD editions (skip these):')
for ed in bad_editions:
    ed_u = unique[unique['factbook_edition'] == ed]
    ed_o = overlap[overlap['factbook_edition'] == ed]
    u_vals = ed_u[unique_metrics].notna().sum().sum() if len(ed_u) > 0 else 0
    o_vals = ed_o[overlap_metrics].notna().sum().sum() if len(ed_o) > 0 else 0
    u_fill = u_vals / (len(ed_u) * len(unique_metrics)) * 100 if len(ed_u) > 0 else 0
    o_fill = o_vals / (len(ed_o) * len(overlap_metrics)) * 100 if len(ed_o) > 0 else 0
    output.append(f'  {ed}: unique={u_vals:5d} vals ({u_fill:4.1f}%), overlap={o_vals:5d} vals ({o_fill:4.1f}%) <-- LOW')

# Filter to good editions only
unique_good = unique[unique['factbook_edition'].isin(good_editions)]
overlap_good = overlap[overlap['factbook_edition'].isin(good_editions)]

output.append('')
output.append('=' * 80)
output.append('COVERAGE WITH GOOD EDITIONS ONLY')
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
output.append('METRIC COVERAGE (GOOD EDITIONS ONLY)')
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

# Compare with ALL editions
output.append('')
output.append('=' * 80)
output.append('COMPARISON: Good editions vs All editions')
output.append('=' * 80)

# All editions
unique_all = unique.sort_values('factbook_edition', ascending=False)
unique_all_dedup = unique_all.groupby(['loc_id', 'year'], as_index=False).agg(agg_dict_u)
overlap_all = overlap.sort_values('factbook_edition', ascending=False)
overlap_all_dedup = overlap_all.groupby(['loc_id', 'year'], as_index=False).agg(agg_dict_o)

all_u_vals = unique_all_dedup[unique_metrics].notna().sum().sum()
all_o_vals = overlap_all_dedup[overlap_metrics].notna().sum().sum()
good_u_vals = unique_dedup[unique_metrics].notna().sum().sum()
good_o_vals = overlap_dedup[overlap_metrics].notna().sum().sum()

output.append('')
output.append(f'Unique metrics:')
output.append(f'  Good editions (15): {good_u_vals:,} values')
output.append(f'  All editions (19): {all_u_vals:,} values')
output.append(f'  Lost by skipping bad: {all_u_vals - good_u_vals:,} ({(all_u_vals - good_u_vals) / all_u_vals * 100:.1f}%)')

output.append('')
output.append(f'Overlap metrics:')
output.append(f'  Good editions (15): {good_o_vals:,} values')
output.append(f'  All editions (19): {all_o_vals:,} values')
output.append(f'  Lost by skipping bad: {all_o_vals - good_o_vals:,} ({(all_o_vals - good_o_vals) / all_o_vals * 100:.1f}%)')

output.append('')
output.append('=' * 80)
output.append('RECOMMENDATION')
output.append('=' * 80)
output.append('')
output.append('Skip editions 2009, 2011, 2013, 2014 - they have low fill rates and')
output.append('their data is mostly covered by adjacent better editions.')
output.append('')
output.append('The ~3-6% data loss from skipping bad editions is acceptable')
output.append('because those editions have extraction issues that cause bad data.')
output.append('')

# Print and save
report = '\n'.join(output)
print(report)

with open('world_factbook_discrepancy_report_v5.txt', 'w', encoding='utf-8') as f:
    f.write(report)

print('\nSaved to world_factbook_discrepancy_report_v5.txt')
