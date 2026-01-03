"""
Run comprehensive sanity checks on the World Factbook v9 parquet data.
"""

import pandas as pd
import numpy as np

df = pd.read_parquet(r'C:\Users\Bryan\Desktop\county-map-data\data\world_factbook\all_countries_v9.parquet')

# Get latest year for each country for most checks
latest = df.sort_values('year').groupby('loc_id').last().reset_index()

results = []

def check(name, condition, expected, actual):
    status = 'PASS' if condition else 'FAIL'
    results.append({'check': name, 'status': status, 'expected': expected, 'actual': actual})

def get_val(loc, metric, data=None):
    if data is None:
        data = latest
    row = data[data['loc_id'] == loc]
    if len(row) == 0:
        return None
    val = row[metric].values[0]
    return val if pd.notna(val) else None

# =============================================================================
# POPULATION CHECKS (1-20)
# =============================================================================
pop_checks = [
    ('CHN', 1300, 1500, 'China population 1.3-1.5B'),
    ('IND', 1300, 1500, 'India population 1.3-1.5B'),
    ('USA', 320, 345, 'USA population 320-345M'),
    ('IDN', 260, 290, 'Indonesia population 260-290M'),
    ('PAK', 200, 260, 'Pakistan population 200-260M'),
    ('BRA', 200, 220, 'Brazil population 200-220M'),
    ('NGA', 200, 250, 'Nigeria population 200-250M'),
    ('BGD', 160, 180, 'Bangladesh population 160-180M'),
    ('RUS', 140, 150, 'Russia population 140-150M'),
    ('JPN', 120, 130, 'Japan population 120-130M'),
    ('MEX', 120, 140, 'Mexico population 120-140M'),
    ('DEU', 80, 90, 'Germany population 80-90M'),
    ('GBR', 65, 70, 'UK population 65-70M'),
    ('FRA', 65, 70, 'France population 65-70M'),
    ('ITA', 58, 62, 'Italy population 58-62M'),
    ('ZAF', 55, 65, 'South Africa population 55-65M'),
    ('KOR', 50, 55, 'South Korea population 50-55M'),
    ('ESP', 45, 50, 'Spain population 45-50M'),
    ('CAN', 35, 42, 'Canada population 35-42M'),
    ('AUS', 24, 28, 'Australia population 24-28M'),
]

for loc, min_m, max_m, desc in pop_checks:
    val = get_val(loc, 'population')
    if val:
        val_m = val / 1e6
        check(desc, min_m <= val_m <= max_m, f'{min_m}-{max_m}M', f'{val_m:.1f}M')
    else:
        check(desc, False, f'{min_m}-{max_m}M', 'NO DATA')

# =============================================================================
# AREA CHECKS (21-35)
# =============================================================================
area_checks = [
    ('RUS', 16000000, 18000000, 'Russia area ~17M sq km'),
    ('CAN', 9000000, 10500000, 'Canada area ~10M sq km'),
    ('USA', 9000000, 10000000, 'USA area ~9.8M sq km'),
    ('CHN', 9000000, 10000000, 'China area ~9.6M sq km'),
    ('BRA', 8000000, 9000000, 'Brazil area ~8.5M sq km'),
    ('AUS', 7500000, 8000000, 'Australia area ~7.7M sq km'),
    ('IND', 3000000, 3500000, 'India area ~3.3M sq km'),
    ('ARG', 2700000, 2900000, 'Argentina area ~2.8M sq km'),
    ('KAZ', 2700000, 2800000, 'Kazakhstan area ~2.7M sq km'),
    ('DZA', 2300000, 2500000, 'Algeria area ~2.4M sq km'),
    ('COD', 2300000, 2400000, 'DRC area ~2.3M sq km'),
    ('SAU', 2100000, 2200000, 'Saudi Arabia area ~2.1M sq km'),
    ('MEX', 1900000, 2100000, 'Mexico area ~2M sq km'),
    ('IDN', 1800000, 2000000, 'Indonesia area ~1.9M sq km'),
    ('VAT', 0.3, 1, 'Vatican area <1 sq km'),
]

for loc, min_a, max_a, desc in area_checks:
    val = get_val(loc, 'area_sq_km')
    if val:
        check(desc, min_a <= val <= max_a, f'{min_a:,}-{max_a:,}', f'{val:,.0f}')
    else:
        check(desc, False, f'{min_a:,}-{max_a:,}', 'NO DATA')

# =============================================================================
# GDP PPP CHECKS (36-50)
# =============================================================================
gdp_checks = [
    ('USA', 20, 30, 'USA GDP 20-30T'),
    ('CHN', 20, 35, 'China GDP 20-35T'),
    ('IND', 8, 15, 'India GDP 8-15T'),
    ('JPN', 5, 7, 'Japan GDP 5-7T'),
    ('DEU', 4, 6, 'Germany GDP 4-6T'),
    ('GBR', 3, 4.5, 'UK GDP 3-4.5T'),
    ('FRA', 3, 4.5, 'France GDP 3-4.5T'),
    ('BRA', 2.5, 4, 'Brazil GDP 2.5-4T'),
    ('RUS', 3, 5, 'Russia GDP 3-5T'),
    ('KOR', 2, 3, 'South Korea GDP 2-3T'),
    ('CAN', 1.8, 2.5, 'Canada GDP 1.8-2.5T'),
    ('AUS', 1.3, 2, 'Australia GDP 1.3-2T'),
    ('MEX', 2, 3, 'Mexico GDP 2-3T'),
    ('IDN', 2.5, 4.5, 'Indonesia GDP 2.5-4.5T'),
    ('SAU', 1.5, 2.5, 'Saudi Arabia GDP 1.5-2.5T'),
]

for loc, min_t, max_t, desc in gdp_checks:
    val = get_val(loc, 'gdp_ppp')
    if val:
        val_t = val / 1e12
        check(desc, min_t <= val_t <= max_t, f'{min_t}-{max_t}T', f'{val_t:.2f}T')
    else:
        check(desc, False, f'{min_t}-{max_t}T', 'NO DATA')

# =============================================================================
# GDP PER CAPITA CHECKS (51-65)
# =============================================================================
gdppc_checks = [
    ('LUX', 100000, 150000, 'Luxembourg GDPPC >100k'),
    ('SGP', 80000, 140000, 'Singapore GDPPC 80-140k'),
    ('NOR', 60000, 100000, 'Norway GDPPC 60-100k'),
    ('CHE', 60000, 90000, 'Switzerland GDPPC 60-90k'),
    ('USA', 55000, 85000, 'USA GDPPC 55-85k'),
    ('ARE', 50000, 80000, 'UAE GDPPC 50-80k'),
    ('DEU', 45000, 70000, 'Germany GDPPC 45-70k'),
    ('JPN', 35000, 55000, 'Japan GDPPC 35-55k'),
    ('KOR', 35000, 55000, 'South Korea GDPPC 35-55k'),
    ('CHN', 15000, 30000, 'China GDPPC 15-30k'),
    ('BRA', 12000, 20000, 'Brazil GDPPC 12-20k'),
    ('IND', 5000, 12000, 'India GDPPC 5-12k'),
    ('NGA', 4000, 8000, 'Nigeria GDPPC 4-8k'),
    ('ETH', 2000, 4000, 'Ethiopia GDPPC 2-4k'),
    ('BDI', 500, 1500, 'Burundi GDPPC <1500 (poorest)'),
]

for loc, min_v, max_v, desc in gdppc_checks:
    val = get_val(loc, 'gdp_per_capita_ppp')
    if val:
        check(desc, min_v <= val <= max_v, f'{min_v:,}-{max_v:,}', f'{val:,.0f}')
    else:
        check(desc, False, f'{min_v:,}-{max_v:,}', 'NO DATA')

# =============================================================================
# LIFE EXPECTANCY CHECKS (66-75)
# =============================================================================
life_checks = [
    ('JPN', 82, 88, 'Japan life exp 82-88 (highest)'),
    ('CHE', 80, 86, 'Switzerland life exp 80-86'),
    ('AUS', 80, 86, 'Australia life exp 80-86'),
    ('ESP', 80, 86, 'Spain life exp 80-86'),
    ('USA', 75, 82, 'USA life exp 75-82'),
    ('CHN', 74, 82, 'China life exp 74-82'),
    ('BRA', 72, 78, 'Brazil life exp 72-78'),
    ('IND', 68, 76, 'India life exp 68-76'),
    ('NGA', 52, 62, 'Nigeria life exp 52-62'),
    ('CAF', 48, 58, 'Central African Republic life exp 48-58 (lowest)'),
]

for loc, min_v, max_v, desc in life_checks:
    val = get_val(loc, 'life_expectancy')
    if val:
        check(desc, min_v <= val <= max_v, f'{min_v}-{max_v}', f'{val:.1f}')
    else:
        check(desc, False, f'{min_v}-{max_v}', 'NO DATA')

# =============================================================================
# FERTILITY RATE CHECKS (76-85)
# =============================================================================
fert_checks = [
    ('NER', 6, 8, 'Niger fertility 6-8 (highest)'),
    ('MLI', 5, 7.5, 'Mali fertility 5-7.5'),
    ('TCD', 5, 7, 'Chad fertility 5-7'),
    ('NGA', 4.5, 6.5, 'Nigeria fertility 4.5-6.5'),
    ('IND', 1.8, 2.8, 'India fertility 1.8-2.8'),
    ('USA', 1.5, 2.2, 'USA fertility 1.5-2.2'),
    ('CHN', 1.0, 1.8, 'China fertility 1.0-1.8'),
    ('JPN', 1.0, 1.6, 'Japan fertility 1.0-1.6 (low)'),
    ('KOR', 0.7, 1.3, 'South Korea fertility 0.7-1.3 (lowest)'),
    ('DEU', 1.3, 1.7, 'Germany fertility 1.3-1.7'),
]

for loc, min_v, max_v, desc in fert_checks:
    val = get_val(loc, 'fertility_rate')
    if val:
        check(desc, min_v <= val <= max_v, f'{min_v}-{max_v}', f'{val:.2f}')
    else:
        check(desc, False, f'{min_v}-{max_v}', 'NO DATA')

# =============================================================================
# AIRPORTS CHECKS (86-95)
# =============================================================================
airport_checks = [
    ('USA', 5000, 20000, 'USA airports 5000-20000'),
    ('BRA', 2000, 5000, 'Brazil airports 2000-5000'),
    ('MEX', 1000, 2500, 'Mexico airports 1000-2500'),
    ('CAN', 1000, 2000, 'Canada airports 1000-2000'),
    ('RUS', 800, 2000, 'Russia airports 800-2000'),
    ('ARG', 800, 1500, 'Argentina airports 800-1500'),
    ('DEU', 300, 600, 'Germany airports 300-600'),
    ('AUS', 400, 700, 'Australia airports 400-700'),
    ('JPN', 150, 250, 'Japan airports 150-250'),
    ('GBR', 200, 500, 'UK airports 200-500'),
]

for loc, min_v, max_v, desc in airport_checks:
    val = get_val(loc, 'airports')
    if val:
        check(desc, min_v <= val <= max_v, f'{min_v:,}-{max_v:,}', f'{val:,.0f}')
    else:
        check(desc, False, f'{min_v:,}-{max_v:,}', 'NO DATA')

# =============================================================================
# MERCHANT MARINE CHECKS (96-100)
# =============================================================================
marine_checks = [
    ('PAN', 5000, 10000, 'Panama merchant ships 5000-10000'),
    ('LBR', 3000, 6000, 'Liberia merchant ships 3000-6000'),
    ('MHL', 2000, 5000, 'Marshall Islands ships 2000-5000'),
    ('HKG', 2000, 4000, 'Hong Kong ships 2000-4000'),
    ('SGP', 2000, 5000, 'Singapore ships 2000-5000'),
]

for loc, min_v, max_v, desc in marine_checks:
    val = get_val(loc, 'merchant_marine')
    if val:
        check(desc, min_v <= val <= max_v, f'{min_v:,}-{max_v:,}', f'{val:,.0f}')
    else:
        check(desc, False, f'{min_v:,}-{max_v:,}', 'NO DATA')

# =============================================================================
# INFANT MORTALITY CHECKS (101-107)
# =============================================================================
infant_checks = [
    ('JPN', 1, 4, 'Japan infant mort 1-4 (lowest)'),
    ('FIN', 1, 4, 'Finland infant mort 1-4'),
    ('USA', 4, 8, 'USA infant mort 4-8'),
    ('CHN', 5, 15, 'China infant mort 5-15'),
    ('IND', 25, 45, 'India infant mort 25-45'),
    ('NGA', 50, 90, 'Nigeria infant mort 50-90'),
    ('CAF', 70, 120, 'Central African Republic infant mort 70-120 (highest)'),
]

for loc, min_v, max_v, desc in infant_checks:
    val = get_val(loc, 'infant_mortality')
    if val:
        check(desc, min_v <= val <= max_v, f'{min_v}-{max_v}', f'{val:.1f}')
    else:
        check(desc, False, f'{min_v}-{max_v}', 'NO DATA')

# =============================================================================
# CO2 EMISSIONS CHECKS (108-112)
# =============================================================================
co2_checks = [
    ('CHN', 8000, 15000, 'China CO2 8000-15000 Mt (top emitter)'),
    ('USA', 4000, 6000, 'USA CO2 4000-6000 Mt'),
    ('IND', 2000, 4000, 'India CO2 2000-4000 Mt'),
    ('RUS', 1500, 2500, 'Russia CO2 1500-2500 Mt'),
    ('JPN', 1000, 1500, 'Japan CO2 1000-1500 Mt'),
]

for loc, min_v, max_v, desc in co2_checks:
    val = get_val(loc, 'co2_emissions')
    if val:
        val_mt = val / 1e6  # Convert to Mt
        check(desc, min_v <= val_mt <= max_v, f'{min_v}-{max_v}Mt', f'{val_mt:.0f}Mt')
    else:
        check(desc, False, f'{min_v}-{max_v}Mt', 'NO DATA')

# =============================================================================
# UNEMPLOYMENT RATE CHECKS (113-118)
# =============================================================================
unemp_checks = [
    ('JPN', 1, 5, 'Japan unemployment 1-5%'),
    ('DEU', 2, 7, 'Germany unemployment 2-7%'),
    ('USA', 3, 10, 'USA unemployment 3-10%'),
    ('FRA', 5, 12, 'France unemployment 5-12%'),
    ('ESP', 8, 25, 'Spain unemployment 8-25%'),
    ('ZAF', 20, 40, 'South Africa unemployment 20-40%'),
]

for loc, min_v, max_v, desc in unemp_checks:
    val = get_val(loc, 'unemployment_rate')
    if val:
        check(desc, min_v <= val <= max_v, f'{min_v}-{max_v}%', f'{val:.1f}%')
    else:
        check(desc, False, f'{min_v}-{max_v}%', 'NO DATA')

# =============================================================================
# CROSS-METRIC CONSISTENCY CHECKS (119-128)
# =============================================================================

# GDP per capita should roughly equal GDP / population
for loc in ['USA', 'CHN', 'IND', 'DEU', 'JPN']:
    gdp = get_val(loc, 'gdp_ppp')
    pop = get_val(loc, 'population')
    gdppc = get_val(loc, 'gdp_per_capita_ppp')
    if gdp and pop and gdppc:
        calc_gdppc = gdp / pop
        ratio = gdppc / calc_gdppc if calc_gdppc > 0 else 0
        check(f'{loc} GDPPC consistent with GDP/pop', 0.5 <= ratio <= 2.0, '0.5-2.0x', f'{ratio:.2f}x')
    else:
        check(f'{loc} GDPPC consistent with GDP/pop', False, '0.5-2.0x', 'NO DATA')

# Birth rate > death rate for growing populations
growing = ['NGA', 'IND', 'ETH', 'COD', 'TZA']
for loc in growing:
    br = get_val(loc, 'birth_rate')
    dr = get_val(loc, 'death_rate')
    if br and dr:
        check(f'{loc} birth rate > death rate (growing)', br > dr, 'BR>DR', f'BR={br:.1f}, DR={dr:.1f}')
    else:
        check(f'{loc} birth rate > death rate (growing)', False, 'BR>DR', 'NO DATA')

# =============================================================================
# HISTORICAL TREND CHECKS (129-138)
# =============================================================================

# Check that USA population increases over time (2002 vs 2020)
usa_2002 = df[(df['loc_id'] == 'USA') & (df['year'] == 2002)]['population'].values
usa_2020 = df[(df['loc_id'] == 'USA') & (df['year'] == 2020)]['population'].values
if len(usa_2002) > 0 and len(usa_2020) > 0:
    usa_2002_pop = usa_2002[0]
    usa_2020_pop = usa_2020[0]
    if pd.notna(usa_2002_pop) and pd.notna(usa_2020_pop):
        check('USA population grew 2002-2020', usa_2020_pop > usa_2002_pop,
              'growth', f'{usa_2002_pop/1e6:.0f}M -> {usa_2020_pop/1e6:.0f}M')
    else:
        check('USA population grew 2002-2020', False, 'growth', 'NO DATA')
else:
    check('USA population grew 2002-2020', False, 'growth', 'NO DATA')

# Check China GDP growth
chn_2005 = df[(df['loc_id'] == 'CHN') & (df['year'] == 2005)]['gdp_ppp'].values
chn_2020 = df[(df['loc_id'] == 'CHN') & (df['year'] == 2020)]['gdp_ppp'].values
if len(chn_2005) > 0 and len(chn_2020) > 0:
    chn_2005_gdp = chn_2005[0]
    chn_2020_gdp = chn_2020[0]
    if pd.notna(chn_2005_gdp) and pd.notna(chn_2020_gdp):
        check('China GDP grew 2005-2020', chn_2020_gdp > chn_2005_gdp * 2,
              '>2x growth', f'{chn_2005_gdp/1e12:.1f}T -> {chn_2020_gdp/1e12:.1f}T')
    else:
        check('China GDP grew 2005-2020', False, '>2x growth', 'NO DATA')
else:
    check('China GDP grew 2005-2020', False, '>2x growth', 'NO DATA')

# India life expectancy improvement
ind_2005 = df[(df['loc_id'] == 'IND') & (df['year'] == 2005)]['life_expectancy'].values
ind_2020 = df[(df['loc_id'] == 'IND') & (df['year'] == 2020)]['life_expectancy'].values
if len(ind_2005) > 0 and len(ind_2020) > 0:
    ind_2005_le = ind_2005[0]
    ind_2020_le = ind_2020[0]
    if pd.notna(ind_2005_le) and pd.notna(ind_2020_le):
        check('India life expectancy improved 2005-2020', ind_2020_le > ind_2005_le,
              'improvement', f'{ind_2005_le:.1f} -> {ind_2020_le:.1f}')
    else:
        check('India life expectancy improved 2005-2020', False, 'improvement', 'NO DATA')
else:
    check('India life expectancy improved 2005-2020', False, 'improvement', 'NO DATA')

# Global infant mortality decrease
world_2005_im = df[df['year'] == 2005]['infant_mortality'].dropna().mean()
world_2020_im = df[df['year'] == 2020]['infant_mortality'].dropna().mean()
if pd.notna(world_2005_im) and pd.notna(world_2020_im):
    check('Global avg infant mortality decreased 2005-2020', world_2020_im < world_2005_im,
          'decrease', f'{world_2005_im:.1f} -> {world_2020_im:.1f}')
else:
    check('Global avg infant mortality decreased 2005-2020', False, 'decrease', 'NO DATA')

# Global internet access increase
world_2010_bb = df[df['year'] == 2010]['broadband_subscriptions'].dropna().mean()
world_2020_bb = df[df['year'] == 2020]['broadband_subscriptions'].dropna().mean()
if pd.notna(world_2010_bb) and pd.notna(world_2020_bb):
    check('Global avg broadband increased 2010-2020', world_2020_bb > world_2010_bb,
          'increase', f'{world_2010_bb/1e6:.1f}M -> {world_2020_bb/1e6:.1f}M')
else:
    check('Global avg broadband increased 2010-2020', False, 'increase', 'NO DATA')

# =============================================================================
# RELATIONSHIP CHECKS (139-148)
# =============================================================================

# High GDP per capita countries should have low infant mortality
rich_countries = ['LUX', 'SGP', 'NOR', 'CHE', 'USA']
for loc in rich_countries:
    im = get_val(loc, 'infant_mortality')
    if im:
        check(f'{loc} rich country low infant mortality', im < 10, '<10', f'{im:.1f}')
    else:
        check(f'{loc} rich country low infant mortality', False, '<10', 'NO DATA')

# High GDP per capita should correlate with high life expectancy
for loc in rich_countries:
    le = get_val(loc, 'life_expectancy')
    if le:
        check(f'{loc} rich country high life expectancy', le > 75, '>75', f'{le:.1f}')
    else:
        check(f'{loc} rich country high life expectancy', False, '>75', 'NO DATA')

# =============================================================================
# DATA COMPLETENESS CHECKS (149-160)
# =============================================================================

# Check key metrics have data for major countries
major_countries = ['USA', 'CHN', 'IND', 'DEU', 'JPN', 'GBR', 'FRA', 'BRA', 'RUS']
key_metrics = ['population', 'gdp_ppp', 'life_expectancy', 'area_sq_km']

for metric in key_metrics:
    has_data = sum(1 for loc in major_countries if get_val(loc, metric) is not None)
    check(f'Major countries have {metric} data', has_data >= 7, '>=7/9', f'{has_data}/9')

# Check each metric has reasonable coverage
for metric in ['population', 'area_sq_km', 'life_expectancy', 'gdp_ppp', 'birth_rate', 'death_rate']:
    count = latest[metric].notna().sum()
    check(f'{metric} coverage > 100 countries', count > 100, '>100', str(count))

# =============================================================================
# PRINT RESULTS BEFORE METRIC STATS
# =============================================================================
print('=' * 80)
print('SANITY CHECK RESULTS')
print('=' * 80)
print()

pass_count = sum(1 for r in results if r['status'] == 'PASS')
fail_count = sum(1 for r in results if r['status'] == 'FAIL')

print(f'Total checks: {len(results)}')
print(f'PASS: {pass_count}')
print(f'FAIL: {fail_count}')
print(f'Pass rate: {100*pass_count/len(results):.1f}%')
print()

if fail_count > 0:
    print('FAILED CHECKS:')
    print('-' * 80)
    for r in results:
        if r['status'] == 'FAIL':
            print(f"  {r['check']}")
            print(f"    Expected: {r['expected']}, Got: {r['actual']}")
    print()

print('ALL CHECKS:')
print('-' * 80)
for i, r in enumerate(results, 1):
    status_mark = '[OK]' if r['status'] == 'PASS' else '[XX]'
    print(f"{i:3d}. {status_mark} {r['check']}: {r['actual']}")

# =============================================================================
# MIN/MAX/MEAN FOR ALL METRICS
# =============================================================================
print()
print('=' * 80)
print('METRIC STATISTICS (MIN / MAX / MEAN / COUNT)')
print('=' * 80)
print()

# Get all numeric columns (excluding loc_id, year, factbook_edition)
exclude_cols = ['loc_id', 'year', 'factbook_edition']
metric_cols = [c for c in df.columns if c not in exclude_cols and df[c].dtype in ['float64', 'int64', 'float32', 'int32']]

# Sort metrics alphabetically
metric_cols = sorted(metric_cols)

print(f"{'Metric':<35} {'Min':>18} {'Max':>18} {'Mean':>18} {'Count':>8}")
print('-' * 100)

metric_stats = []
for metric in metric_cols:
    vals = latest[metric].dropna()
    if len(vals) > 0:
        min_val = vals.min()
        max_val = vals.max()
        mean_val = vals.mean()
        count = len(vals)

        # Format based on magnitude
        def fmt(v):
            if abs(v) >= 1e12:
                return f'{v/1e12:.2f}T'
            elif abs(v) >= 1e9:
                return f'{v/1e9:.2f}B'
            elif abs(v) >= 1e6:
                return f'{v/1e6:.2f}M'
            elif abs(v) >= 1e3:
                return f'{v/1e3:.2f}K'
            elif abs(v) >= 1:
                return f'{v:.2f}'
            else:
                return f'{v:.4f}'

        print(f"{metric:<35} {fmt(min_val):>18} {fmt(max_val):>18} {fmt(mean_val):>18} {count:>8}")

        # Store for later analysis
        metric_stats.append({
            'metric': metric,
            'min': min_val,
            'max': max_val,
            'mean': mean_val,
            'count': count,
            'min_loc': latest.loc[latest[metric] == min_val, 'loc_id'].values[0] if len(latest.loc[latest[metric] == min_val]) > 0 else 'N/A',
            'max_loc': latest.loc[latest[metric] == max_val, 'loc_id'].values[0] if len(latest.loc[latest[metric] == max_val]) > 0 else 'N/A',
        })
    else:
        print(f"{metric:<35} {'NO DATA':>18} {'NO DATA':>18} {'NO DATA':>18} {'0':>8}")

print()
print('=' * 80)
print('MIN/MAX COUNTRIES FOR EACH METRIC')
print('=' * 80)
print()

print(f"{'Metric':<35} {'Min Country (Value)':<25} {'Max Country (Value)':<25}")
print('-' * 85)

for ms in metric_stats:
    metric = ms['metric']
    min_loc = ms['min_loc']
    max_loc = ms['max_loc']
    min_val = ms['min']
    max_val = ms['max']

    def fmt_short(v):
        if abs(v) >= 1e12:
            return f'{v/1e12:.1f}T'
        elif abs(v) >= 1e9:
            return f'{v/1e9:.1f}B'
        elif abs(v) >= 1e6:
            return f'{v/1e6:.1f}M'
        elif abs(v) >= 1e3:
            return f'{v/1e3:.1f}K'
        elif abs(v) >= 1:
            return f'{v:.1f}'
        else:
            return f'{v:.3f}'

    min_str = f'{min_loc} ({fmt_short(min_val)})'
    max_str = f'{max_loc} ({fmt_short(max_val)})'
    print(f"{metric:<35} {min_str:<25} {max_str:<25}")

print()
print('=' * 80)
print('POTENTIAL OUTLIERS / SUSPICIOUS VALUES')
print('=' * 80)
print()

# Check for potential issues
issues = []

# Check for extremely small populations (might be uninhabited or errors)
tiny_pops = latest[latest['population'] < 1000]['loc_id'].tolist()
if tiny_pops:
    issues.append(f"Countries with population < 1000: {', '.join(tiny_pops)}")

# Check for very high unemployment (> 50%)
high_unemp = latest[latest['unemployment_rate'] > 50]
if len(high_unemp) > 0:
    for _, row in high_unemp.iterrows():
        issues.append(f"Very high unemployment: {row['loc_id']} = {row['unemployment_rate']:.1f}%")

# Check for negative values where they shouldn't exist
neg_metrics = ['population', 'area_sq_km', 'life_expectancy', 'airports', 'labor_force']
for metric in neg_metrics:
    if metric in latest.columns:
        neg_vals = latest[latest[metric] < 0]
        if len(neg_vals) > 0:
            for _, row in neg_vals.iterrows():
                issues.append(f"Negative {metric}: {row['loc_id']} = {row[metric]}")

# Check for life expectancy outside normal bounds
low_life = latest[(latest['life_expectancy'] < 40) & (latest['life_expectancy'].notna())]
high_life = latest[(latest['life_expectancy'] > 90) & (latest['life_expectancy'].notna())]
for _, row in low_life.iterrows():
    issues.append(f"Very low life expectancy: {row['loc_id']} = {row['life_expectancy']:.1f}")
for _, row in high_life.iterrows():
    issues.append(f"Very high life expectancy: {row['loc_id']} = {row['life_expectancy']:.1f}")

# Check for fertility rate outside normal bounds
low_fert = latest[(latest['fertility_rate'] < 0.5) & (latest['fertility_rate'].notna())]
high_fert = latest[(latest['fertility_rate'] > 9) & (latest['fertility_rate'].notna())]
for _, row in low_fert.iterrows():
    issues.append(f"Very low fertility: {row['loc_id']} = {row['fertility_rate']:.2f}")
for _, row in high_fert.iterrows():
    issues.append(f"Very high fertility: {row['loc_id']} = {row['fertility_rate']:.2f}")

# Check for infant mortality outside bounds
high_im = latest[(latest['infant_mortality'] > 100) & (latest['infant_mortality'].notna())]
for _, row in high_im.iterrows():
    issues.append(f"Very high infant mortality: {row['loc_id']} = {row['infant_mortality']:.1f}")

if issues:
    for issue in issues:
        print(f"  - {issue}")
else:
    print("  No suspicious values detected.")

print()
print('=' * 80)
print('END OF SANITY CHECK REPORT')
print('=' * 80)
