"""
Quick analysis of fire sizes in Global Fire Atlas to help choose filter threshold.
Uses pre-calculated 'size' field (appears to be in km2 based on values).
"""
import geopandas as gpd
from pathlib import Path
import pandas as pd

raw_path = Path('C:/Users/Bryan/Desktop/county-map-data/Raw data/global_fire_atlas')

# Sample a few years to get distribution
years_to_sample = [2024, 2020, 2015, 2010, 2005]

all_stats = []

for year in years_to_sample:
    shp = raw_path / f'SHP_perimeters/GFA_v20240409_perimeters_{year}.shp'
    if not shp.exists():
        print(f"Year {year}: File not found")
        continue

    print(f"\n=== Year {year} ===")
    gdf = gpd.read_file(shp)

    total = len(gdf)
    multi_day = len(gdf[gdf['duration'] >= 2])

    print(f"Total fires: {total:,}")
    print(f"Multi-day fires (duration >= 2): {multi_day:,}")
    print(f"Size range: {gdf['size'].min():.2f} - {gdf['size'].max():.2f} (unit TBD)")
    print(f"Size median: {gdf['size'].median():.2f}")

    # Size thresholds - using 'size' field
    thresholds = [0.1, 0.5, 1, 5, 10, 25, 50, 100, 250, 500]

    print(f"\nFires by minimum size:")
    print(f"{'Threshold':<12} {'Count':<12} {'% of Total':<12} {'Multi-day':<12}")
    print("-" * 48)

    for thresh in thresholds:
        count = len(gdf[gdf['size'] >= thresh])
        multi = len(gdf[(gdf['size'] >= thresh) & (gdf['duration'] >= 2)])
        pct = count / total * 100 if total > 0 else 0
        print(f">= {thresh:<8} {count:<12,} {pct:<11.1f}% {multi:,}")

        all_stats.append({
            'year': year,
            'threshold': thresh,
            'count': count,
            'multi_day': multi,
            'pct': pct
        })

# Summary across all sampled years
print("\n\n=== SUMMARY ACROSS ALL SAMPLED YEARS ===")
df = pd.DataFrame(all_stats)
summary = df.groupby('threshold').agg({
    'count': 'mean',
    'multi_day': 'mean',
    'pct': 'mean'
}).round(0)

print(f"\nAverage per year:")
print(f"{'Threshold':<12} {'Avg Count':<15} {'Avg Multi-day':<15} {'Avg %':<10}")
print("-" * 55)
for thresh in [0.1, 0.5, 1, 5, 10, 25, 50, 100, 250, 500]:
    row = summary.loc[thresh]
    print(f">= {thresh:<8} {int(row['count']):>12,} {int(row['multi_day']):>12,} {row['pct']:>8.1f}%")

# Estimate total processing time
print("\n\n=== ESTIMATED PROCESSING TIME (23 years) ===")
fires_per_min = 1800
for thresh in [1, 5, 10, 25, 50, 100]:
    avg_multi = summary.loc[thresh, 'multi_day']
    total_fires = avg_multi * 23  # 23 years
    minutes = total_fires / fires_per_min
    hours = minutes / 60
    print(f">= {thresh}: ~{int(total_fires):,} fires total, ~{hours:.1f} hours")
