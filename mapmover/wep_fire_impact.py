"""Advisory tract screening for temporary WEP fire footprints."""

import math

from shapely.geometry import shape
from shapely.ops import transform


_METERS_PER_LATITUDE_DEGREE = 111_320.0
_LAKE_COUNTY_LATITUDE = 39.16
_METERS_PER_LONGITUDE_DEGREE = _METERS_PER_LATITUDE_DEGREE * math.cos(
    math.radians(_LAKE_COUNTY_LATITUDE)
)


def _project_geometry(geometry):
    return transform(
        lambda longitude, latitude, z=None: (
            longitude * _METERS_PER_LONGITUDE_DEGREE,
            latitude * _METERS_PER_LATITUDE_DEGREE,
        ),
        geometry,
    )


def _tract_id(properties):
    for key in ("GEOID", "GEOID20", "TRACTFIPS", "tract_geoid", "geoid"):
        value = str(properties.get(key) or "")
        normalized = "".join(character for character in value if character.isdigit())
        if normalized:
            return normalized
    return ""


def historical_analog_probabilities(fires, training_data):
    """Estimate tract-level historical evacuation frequency for nearby, size-similar fires."""
    events = training_data.get("events") if isinstance(training_data, dict) else None
    tract_ids = training_data.get("tract_ids") if isinstance(training_data, dict) else None
    if not isinstance(events, list) or not isinstance(tract_ids, list) or not events or not tract_ids:
        return {"available": False, "tracts": []}

    try:
        distance_scale = float(training_data.get("distance_scale_km", 10))
        log_acre_scale = float(training_data.get("log_acre_scale", 4))
    except (TypeError, ValueError):
        return {"available": False, "tracts": []}
    if distance_scale <= 0 or log_acre_scale <= 0:
        return {"available": False, "tracts": []}

    tract_ids = [str(tract_id) for tract_id in tract_ids]
    probabilities = {
        tract_id: {
            "tract_id": tract_id,
            "probability": 0.0,
            "warning_probability": 0.0,
            "mandatory_probability": 0.0,
            "effective_analog_count": 0.0,
            "nearest_analog_distance_km": None,
            "fire_ids": [],
        }
        for tract_id in tract_ids
    }

    for fire_index, fire in enumerate(fires if isinstance(fires, list) else []):
        if not isinstance(fire, dict) or not isinstance(fire.get("geometry"), dict):
            continue
        try:
            fire_geometry = shape(fire["geometry"])
            acres = float((fire.get("properties") or {}).get("acres"))
        except (TypeError, ValueError, Exception):
            continue
        if fire_geometry.is_empty or acres <= 0 or not math.isfinite(acres):
            continue
        center = fire_geometry.centroid
        weighted_events = []
        for event in events:
            try:
                event_center = event.get("center")
                event_acres = float(event.get("fire_acres"))
                event_labels = event.get("tract_severity_labels")
                if not isinstance(event_center, list) or len(event_center) < 2 or len(event_labels) != len(tract_ids):
                    continue
                event_longitude, event_latitude = float(event_center[0]), float(event_center[1])
                mean_latitude = math.radians((center.y + event_latitude) / 2)
                dx_km = (center.x - event_longitude) * 111.32 * math.cos(mean_latitude)
                dy_km = (center.y - event_latitude) * 111.32
                distance_km = math.hypot(dx_km, dy_km)
                size_distance = abs(math.log(max(acres, 1) / max(event_acres, 1)))
                weight = math.exp(-distance_km / distance_scale - size_distance / log_acre_scale)
                weighted_events.append((weight, distance_km, event_labels))
            except (TypeError, ValueError, OverflowError):
                continue
        weight_total = sum(item[0] for item in weighted_events)
        weight_squared_total = sum(item[0] ** 2 for item in weighted_events)
        if weight_total <= 0:
            continue
        effective_count = weight_total**2 / weight_squared_total if weight_squared_total else 0.0
        fire_id = str((fire.get("properties") or {}).get("incident_id") or f"fire-{fire_index + 1}")
        for tract_index, tract_id in enumerate(tract_ids):
            probability = sum(weight for weight, _distance, labels in weighted_events if int(labels[tract_index]) > 0) / weight_total
            warning_probability = sum(weight for weight, _distance, labels in weighted_events if int(labels[tract_index]) == 1) / weight_total
            mandatory_probability = sum(weight for weight, _distance, labels in weighted_events if int(labels[tract_index]) == 3) / weight_total
            current = probabilities[tract_id]
            if probability > current["probability"]:
                current.update(
                    {
                        "probability": probability,
                        "effective_analog_count": effective_count,
                        "nearest_analog_distance_km": min(distance for _weight, distance, _labels in weighted_events),
                        "fire_ids": [fire_id],
                    }
                )
            elif math.isclose(probability, current["probability"]) and probability > 0:
                current["fire_ids"].append(fire_id)
                current["effective_analog_count"] = max(current["effective_analog_count"], effective_count)
            current["warning_probability"] = max(current["warning_probability"], warning_probability)
            current["mandatory_probability"] = max(current["mandatory_probability"], mandatory_probability)

    return {
        "available": True,
        "status": str(training_data.get("status") or "experimental"),
        "event_count": len(events),
        "validation": training_data.get("validation") or {},
        "tracts": list(probabilities.values()),
    }


def screen_fire_impact(fires, tracts, warning_buffer_km=1.2, candidate_sites=None):
    """Classify tracts by overlap with fire footprints or an advisory buffer."""
    try:
        buffer_km = float(warning_buffer_km)
    except (TypeError, ValueError) as exc:
        raise ValueError("warning_buffer_km must be numeric") from exc
    if not math.isfinite(buffer_km) or not 0 <= buffer_km <= 25:
        raise ValueError("warning_buffer_km must be between 0 and 25")
    if not isinstance(fires, list) or len(fires) > 10:
        raise ValueError("fires must be an array with at most 10 features")
    if not isinstance(tracts, list) or len(tracts) > 500:
        raise ValueError("tracts must be an array with at most 500 features")
    if candidate_sites is None:
        candidate_sites = []
    if not isinstance(candidate_sites, list) or len(candidate_sites) > 500:
        raise ValueError("candidate_sites must be an array with at most 500 features")

    projected_fires = []
    for index, feature in enumerate(fires):
        if not isinstance(feature, dict) or not isinstance(feature.get("geometry"), dict):
            continue
        try:
            geometry = _project_geometry(shape(feature["geometry"]))
        except Exception as exc:
            raise ValueError(f"Fire feature {index} has invalid geometry") from exc
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError(f"Fire feature {index} has invalid geometry")
        properties = feature.get("properties") or {}
        projected_fires.append(
            {
                "id": str(properties.get("incident_id") or f"fire-{index + 1}"),
                "geometry": geometry,
                "warning_geometry": geometry.buffer(buffer_km * 1000),
            }
        )

    results = []
    affected_tract_geometries = []
    for index, feature in enumerate(tracts):
        if not isinstance(feature, dict) or not isinstance(feature.get("geometry"), dict):
            continue
        properties = feature.get("properties") or {}
        tract_id = _tract_id(properties)
        if not tract_id:
            continue
        try:
            geometry = _project_geometry(shape(feature["geometry"]))
        except Exception as exc:
            raise ValueError(f"Tract feature {index} has invalid geometry") from exc
        if geometry.is_empty or not geometry.is_valid:
            continue

        direct_fires = [
            fire["id"]
            for fire in projected_fires
            if geometry.intersects(fire["geometry"])
        ]
        if direct_fires:
            affected_tract_geometries.append(geometry)
            results.append(
                {"tract_id": tract_id, "tier": "potential_evacuation", "fire_ids": direct_fires}
            )
            continue

        warning_fires = [
            fire["id"]
            for fire in projected_fires
            if geometry.intersects(fire["warning_geometry"])
        ]
        if warning_fires:
            affected_tract_geometries.append(geometry)
            results.append(
                {"tract_id": tract_id, "tier": "potential_warning", "fire_ids": warning_fires}
            )

    excluded_candidate_ids = []
    for index, feature in enumerate(candidate_sites):
        if not isinstance(feature, dict) or not isinstance(feature.get("geometry"), dict):
            continue
        try:
            point = _project_geometry(shape(feature["geometry"]))
        except Exception as exc:
            raise ValueError(f"Candidate site {index} has invalid geometry") from exc
        if point.is_empty or not point.is_valid or point.geom_type != "Point":
            raise ValueError(f"Candidate site {index} must have valid Point geometry")
        properties = feature.get("properties") or {}
        candidate_id = str(
            properties.get("building_id")
            or properties.get("source_building_id")
            or properties.get("shelter_id")
            or f"candidate-{index + 1}"
        )
        if any(
            point.intersects(fire["warning_geometry"])
            for fire in projected_fires
        ) or any(tract.covers(point) for tract in affected_tract_geometries):
            excluded_candidate_ids.append(candidate_id)

    return {
        "tracts": results,
        "excluded_candidate_ids": excluded_candidate_ids,
        "warning_buffer_km": buffer_km,
        "fire_count": len(projected_fires),
    }