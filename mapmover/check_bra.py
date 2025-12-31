import pandas as pd
df = pd.read_parquet(r'C:\Users\Bryan\Desktop\county-map-data\geometry\BRA.parquet')
print('Level breakdown:')
for lvl in sorted(df['admin_level'].unique()):
    lvl_df = df[df['admin_level']==lvl]
    print(f'  Level {lvl}: {len(lvl_df)} rows, {lvl_df["geometry"].notna().sum()} with geometry')
