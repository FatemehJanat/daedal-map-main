import pandas as pd
import geopandas as gpd
from shapely import wkt

df = pd.read_parquet('C:/Users/Bryan/Desktop/county-map-data/countries/CAN/drought/snapshots.parquet')

# Check a few 2021 summer snapshots
summer_2021 = df[(df['year'] == 2021) & (df['month'].isin([6,7,8]))]

print('Summer 2021 area values:')
for idx, row in summer_2021.head(5).iterrows():
    geom = wkt.loads(row['geometry'])
    # Calculate actual area in the data
    print(f"{row['snapshot_id']}:")
    print(f"  Stored area_km2: {row['area_km2']}")
    print(f"  Geometry type: {geom.geom_type}")
    print(f"  Geometry is valid: {geom.is_valid}")
    print(f"  Geometry is empty: {geom.is_empty}")
    if not geom.is_empty:
        # Calculate area in WGS84 (approximate, for comparison)
        print(f"  WGS84 area (deg^2): {geom.area}")
    print()

# Compare with earlier months
print('\n2019 samples for comparison:')
samples_2019 = df[(df['year'] == 2019) & (df['month'] == 6)]
for idx, row in samples_2019.head(3).iterrows():
    geom = wkt.loads(row['geometry'])
    print(f"{row['snapshot_id']}: stored={row['area_km2']:.6f}, WGS84={geom.area:.6f}")
