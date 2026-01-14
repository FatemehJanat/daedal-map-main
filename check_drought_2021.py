import pandas as pd

df = pd.read_parquet('C:/Users/Bryan/Desktop/county-map-data/countries/CAN/drought/snapshots.parquet')

summer_2021 = df[(df['year'] == 2021) & (df['month'].isin([6,7,8]))]

print('Summer 2021 snapshots:')
for idx, row in summer_2021.iterrows():
    print(f"{row['snapshot_id']}: {row['severity']} - Area: {row['area_km2']:.2f} km2 - Geom length: {len(row['geometry'])} chars")

print(f'\nTotal summer 2021 snapshots: {len(summer_2021)}')
