"""Fetch OSM public-use amenities for temporary WEP candidate shelters."""

from __future__ import annotations

import json
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_PATH = BASE_DIR / "static" / "data" / "wep_lake_county_candidate_buildings.geojson"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
QUERY = '[out:json][timeout:20];nwr["amenity"~"school|college|hospital|clinic|community_centre|townhall|fire_station|place_of_worship"](38.75,-123.1,39.5,-122.45);out center tags;'


def main() -> None:
    response = requests.post(
        OVERPASS_URL,
        data={"data": QUERY},
        headers={"User-Agent": "DaedalMap-WEP/1.0"},
        timeout=60,
    )
    response.raise_for_status()
    elements = response.json().get("elements", [])
    features = []
    for element in elements:
        tags = element.get("tags") or {}
        center = element.get("center") or {}
        longitude = element.get("lon", center.get("lon"))
        latitude = element.get("lat", center.get("lat"))
        if longitude is None or latitude is None:
            continue
        osm_id = f"{element.get('type', 'feature')}/{element.get('id')}"
        amenity = tags.get("amenity", "public building")
        name = tags.get("name") or f"OSM {amenity.replace('_', ' ')}"
        features.append(
            {
                "type": "Feature",
                "id": osm_id,
                "geometry": {"type": "Point", "coordinates": [float(longitude), float(latitude)]},
                "properties": {
                    "building_id": osm_id,
                    "building_name": name,
                    "amenity": amenity,
                    "candidate_type": "OSM public-use amenity",
                    "source": "OpenStreetMap via Overpass API",
                    "source_license": "ODbL",
                },
            }
        )
    output = {"type": "FeatureCollection", "features": features}
    OUTPUT_PATH.write_text(json.dumps(output, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} with {len(features)} candidate buildings")


if __name__ == "__main__":
    main()
