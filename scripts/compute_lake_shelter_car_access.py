"""Build tract-level cumulative FEMA NSS facility access by automobile for WEP.

Uses each Lake County tract's geometric centroid and OSRM's OSM car profile.
OSRM applies OSM road restrictions and speed information where mapped, with
profile defaults for road classes where a maximum speed is not tagged.
It models normal routing conditions, not live traffic, closures, or evacuation
controls. FEMA NSS records are registry facilities; their status must not be
interpreted as currently open shelters.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests
from shapely.geometry import shape

BASE_DIR = Path(__file__).resolve().parents[1]
TRACTS_PATH = BASE_DIR / "static" / "data" / "fema_nri_v1_20_lake_county_tracts.geojson"
FACILITIES_PATH = BASE_DIR / "static" / "data" / "fema_nss_lake_county_facilities.geojson"
OUTPUT_PATH = BASE_DIR / "static" / "data" / "wep_lake_county_nss_car_access.geojson"
OSRM_TABLE_URL = "https://router.project-osrm.org/table/v1/car/"
THRESHOLDS_MINUTES = (30, 60, 90)
DESTINATION_BATCH_SIZE = 60


def load_feature_collection(path: Path) -> dict:
    with path.open(encoding="utf-8-sig") as source_file:
        return json.load(source_file)


def point_coordinates(feature: dict) -> tuple[float, float]:
    geometry = feature.get("geometry") or {}
    if geometry.get("type") != "Point":
        raise ValueError("Facility geometry must be a Point")
    coordinates = geometry.get("coordinates") or []
    if len(coordinates) < 2:
        raise ValueError("Facility point has no coordinates")
    return float(coordinates[0]), float(coordinates[1])


def tract_centroid(feature: dict) -> tuple[float, float]:
    geometry = feature.get("geometry")
    if not geometry:
        raise ValueError("Tract geometry is missing")
    centroid = shape(geometry).centroid
    return float(centroid.x), float(centroid.y)


def osrm_duration_matrix(origins: list[tuple[float, float]], destinations: list[tuple[float, float]]) -> list[list[float | None]]:
    coordinates = origins + destinations
    coordinate_text = ";".join(f"{longitude:.7f},{latitude:.7f}" for longitude, latitude in coordinates)
    origin_indices = ";".join(str(index) for index in range(len(origins)))
    destination_indices = ";".join(str(index) for index in range(len(origins), len(coordinates)))
    response = requests.get(
        f"{OSRM_TABLE_URL}{coordinate_text}",
        params={"sources": origin_indices, "destinations": destination_indices, "annotations": "duration"},
        headers={"User-Agent": "DaedalMap-WEP-accessibility/1.0"},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != "Ok":
        raise RuntimeError(f"OSRM table request failed: {payload.get('code')}")
    durations = payload.get("durations")
    if not isinstance(durations, list) or len(durations) != len(origins):
        raise RuntimeError("OSRM returned an incomplete duration matrix")
    return durations


def main() -> None:
    tracts = load_feature_collection(TRACTS_PATH)
    facilities = load_feature_collection(FACILITIES_PATH)
    tract_features = tracts.get("features") or []
    facility_features = facilities.get("features") or []
    if not tract_features or not facility_features:
        raise RuntimeError("Both tract and FEMA NSS facility layers must contain features")

    origins = [tract_centroid(feature) for feature in tract_features]
    destinations = [point_coordinates(feature) for feature in facility_features]
    counts = [{threshold: 0 for threshold in THRESHOLDS_MINUTES} for _ in origins]
    nearest_minutes: list[float | None] = [None] * len(origins)
    routed_destinations = 0

    for batch_start in range(0, len(destinations), DESTINATION_BATCH_SIZE):
        destination_batch = destinations[batch_start : batch_start + DESTINATION_BATCH_SIZE]
        for attempt in range(1, 4):
            try:
                durations = osrm_duration_matrix(origins, destination_batch)
                break
            except requests.RequestException as error:
                if attempt == 3:
                    raise RuntimeError("OSRM routing service did not return a usable matrix") from error
                time.sleep(attempt)
        for origin_index, duration_row in enumerate(durations):
            if len(duration_row) != len(destination_batch):
                raise RuntimeError("OSRM returned a matrix row with an unexpected length")
            for duration_seconds in duration_row:
                if duration_seconds is None:
                    continue
                duration_minutes = float(duration_seconds) / 60.0
                previous_nearest = nearest_minutes[origin_index]
                if previous_nearest is None or duration_minutes < previous_nearest:
                    nearest_minutes[origin_index] = duration_minutes
                for threshold in THRESHOLDS_MINUTES:
                    if duration_minutes <= threshold:
                        counts[origin_index][threshold] += 1
        routed_destinations += len(destination_batch)
        print(f"Routed {routed_destinations} of {len(destinations)} FEMA NSS facilities")
        time.sleep(0.25)

    for index, feature in enumerate(tract_features):
        properties = feature.setdefault("properties", {})
        tract_geoid = str(properties.get("TRACTFIPS") or properties.get("NRI_ID") or "")
        longitude, latitude = origins[index]
        properties.update(
            {
                "GEOID": tract_geoid,
                "tract_centroid_lon": round(longitude, 7),
                "tract_centroid_lat": round(latitude, 7),
                "centroid_method": "geometric_centroid_wgs84",
                "nss_facilities_within_30min_car": counts[index][30],
                "nss_facilities_within_60min_car": counts[index][60],
                "nss_facilities_within_90min_car": counts[index][90],
                "nearest_nss_facility_minutes_car": round(nearest_minutes[index], 1) if nearest_minutes[index] is not None else None,
                "access_method": "osrm_osm_car_profile",
                "access_network_source": "OpenStreetMap via OSRM public demo service",
                "access_speed_model": "OSRM car profile using OSM maxspeed tags and road-class defaults",
                "access_conditions": "normal routing; excludes traffic, closures, and evacuation controls",
                "access_destination_status": "FEMA NSS registry facilities; status is not an open-shelter assertion",
                "access_thresholds_minutes": "30,60,90",
                "access_generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )

    tracts["wep_accessibility"] = {
        "destination_count": len(destinations),
        "origin_count": len(origins),
        "thresholds_minutes": list(THRESHOLDS_MINUTES),
        "method": "osrm_osm_car_profile",
        "network_source": "OpenStreetMap via OSRM public demo service",
    }
    with OUTPUT_PATH.open("w", encoding="utf-8") as output_file:
        json.dump(tracts, output_file, separators=(",", ":"))
    print(f"Wrote {OUTPUT_PATH}")
    print(f"Tracts: {len(origins)}; FEMA NSS facilities: {len(destinations)}")
    for threshold in THRESHOLDS_MINUTES:
        values = [count[threshold] for count in counts]
        print(f"Within {threshold} minutes: min={min(values)}, max={max(values)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
