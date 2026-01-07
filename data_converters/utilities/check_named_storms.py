"""
Quick script to check for named storms in NOAA data.
"""
import pandas as pd
from pathlib import Path

RAW_FILE = Path("C:/Users/bryan/Desktop/county_map_data/Raw data/noaa_storms/StormEvents_details-ftp_v1.0_d2025_c20251216.csv")

df = pd.read_csv(RAW_FILE)

print("Checking for named storms in 2025...")
print("\nEVENT_TYPEs that might be named:")
tropical = df[df['EVENT_TYPE'].str.contains('Hurricane|Tropical', case=False, na=False)]
print(tropical['EVENT_TYPE'].value_counts())
print(f'\nTotal tropical events: {len(tropical)}')
print(f'Unique EPISODE_IDs: {tropical["EPISODE_ID"].nunique()}')

print('\nSample EPISODE_IDs and narratives:')
for ep_id in tropical['EPISODE_ID'].unique()[:3]:
    ep_data = tropical[tropical['EPISODE_ID'] == ep_id]
    print(f'\nEPISODE_ID: {ep_id}')
    print(f'  Counties: {ep_data["CZ_NAME"].nunique()}')
    print(f'  States: {", ".join(ep_data["STATE"].unique())}')
    narrative = ep_data["EPISODE_NARRATIVE"].iloc[0]
    print(f'  Narrative: {narrative[:300] if pd.notna(narrative) else "N/A"}...')
