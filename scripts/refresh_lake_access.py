import json
import time
import urllib.request
from pathlib import Path

repo = Path(r"C:/Users/fjanatab/Downloads/daedal-map-main/daedal-map-main")
tracts_path = repo / "static" / "data" / "tiger2020_lake_county_tracts_nri.geojson"
shelters_path = repo / "static" / "data" / "nss_lake_county_facilities.geojson"
out_path = repo / "static" / "data" / "tiger2020_lake_county_tracts_nri_access.geojson"

with tracts_path.open(encoding="utf-8") as fh:
    tracts = json.load(fh)
with shelters_path.open(encoding="utf-8") as fh:
    shelters = json.load(fh)


def centroid_coords(geometry):
    if not geometry:
        return (0.0, 0.0)
    if geometry.get("type") == "Point":
        return tuple(geometry["coordinates"])
    if geometry.get("type") == "MultiPolygon":
        coords = []
        for polygon in geometry["coordinates"]:
            for ring in polygon:
                coords.extend(ring)
    elif geometry.get("type") == "Polygon":
        coords = []
        for ring in geometry["coordinates"]:
            coords.extend(ring)
    else:
        return (0.0, 0.0)
    if not coords:
        return (0.0, 0.0)
    lon = sum(c[0] for c in coords) / len(coords)
    lat = sum(c[1] for c in coords) / len(coords)
    return (lon, lat)


def route_duration_min(lon1, lat1, lon2, lat2):
    url = f"https://router.project-osrm.org/route/v1/car/{lon1},{lat1};{lon2},{lat2}?overview=false&alternatives=false"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    routes = payload.get("routes") or []
    if not routes:
        return None
    duration = routes[0].get("duration")
    if duration is None:
        return None
    return duration / 60.0

shelter_points = []
for feature in shelters.get("features", []):
    coords = feature.get("geometry", {}).get("coordinates")
    if not coords:
        continue
    shelter_points.append((coords[0], coords[1]))

thresholds = [30, 45, 60]
for feature in tracts.get("features", []):
    props = feature.setdefault("properties", {})
    lon, lat = centroid_coords(feature.get("geometry"))
    counts = {thr: 0 for thr in thresholds}
    for slon, slat in shelter_points:
        dur = route_duration_min(lon, lat, slon, slat)
        if dur is None:
            continue
        for thr in thresholds:
            if dur <= thr:
                counts[thr] += 1
        time.sleep(0.02)
    props["shelters_within_30min_car"] = counts[30]
    props["shelters_within_45min_car"] = counts[45]
    props["shelters_within_60min_car"] = counts[60]
    props["access_method"] = "osrm_car"
    props["access_cutoff_min"] = 30

with out_path.open("w", encoding="utf-8") as fh:
    json.dump(tracts, fh, ensure_ascii=False, indent=2)

print(f"wrote {out_path}")
print(f"features {len(tracts.get('features', []))}")
print(f"sample {tracts['features'][0]['properties'].get('shelters_within_30min_car')} / {tracts['features'][0]['properties'].get('shelters_within_45min_car')} / {tracts['features'][0]['properties'].get('shelters_within_60min_car')}")
