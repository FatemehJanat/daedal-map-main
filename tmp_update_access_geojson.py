import json
from pathlib import Path

repo = Path(r'C:\Users\fjanatab\Downloads\daedal-map-main\daedal-map-main')
path = repo / 'static' / 'data' / 'tiger2020_lake_county_tracts_nri_access.geojson'

with path.open(encoding='utf-8') as f:
    data = json.load(f)

for feat in data['features']:
    props = feat['properties']
    props['shelters_within_45min_car'] = props.get('shelters_within_45min_car', props.get('shelters_within_30min_car', 0))
    props['shelters_within_60min_car'] = props.get('shelters_within_60min_car', props.get('shelters_within_30min_car', 0))
    props['access_cutoff_min'] = 30

with path.open('w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print('updated', len(data['features']))
