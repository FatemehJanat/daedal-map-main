from mapmover.wep_fire_impact import historical_analog_probabilities, screen_fire_impact


def _feature(tract_id, coordinates):
    return {
        "type": "Feature",
        "properties": {"GEOID": tract_id},
        "geometry": {"type": "Polygon", "coordinates": [coordinates]},
    }


def test_screen_fire_impact_marks_direct_and_buffered_tracts():
    fire = _feature(
        "fire-1",
        [
            [-123.01, 39.0],
            [-122.99, 39.0],
            [-122.99, 39.02],
            [-123.01, 39.02],
            [-123.01, 39.0],
        ],
    )
    fire["properties"] = {"incident_id": "test-fire"}
    tracts = [
        _feature(
            "06033000100",
            [
                [-123.005, 39.005],
                [-122.995, 39.005],
                [-122.995, 39.015],
                [-123.005, 39.015],
                [-123.005, 39.005],
            ],
        ),
        _feature(
            "06033000200",
            [
                [-122.985, 39.005],
                [-122.98, 39.005],
                [-122.98, 39.015],
                [-122.985, 39.015],
                [-122.985, 39.005],
            ],
        ),
        _feature(
            "06033000300",
            [
                [-122.96, 39.005],
                [-122.955, 39.005],
                [-122.955, 39.015],
                [-122.96, 39.015],
                [-122.96, 39.005],
            ],
        ),
    ]
    candidate_sites = [
        _feature(
            "direct-site",
            [
                [-123.001, 39.009],
                [-123.001, 39.009],
                [-123.001, 39.009],
                [-123.001, 39.009],
            ],
        ),
        _feature(
            "buffer-site",
            [
                [-122.982, 39.01],
                [-122.982, 39.01],
                [-122.982, 39.01],
                [-122.982, 39.01],
            ],
        ),
        _feature(
            "outside-site",
            [
                [-122.95, 39.01],
                [-122.95, 39.01],
                [-122.95, 39.01],
                [-122.95, 39.01],
            ],
        ),
    ]
    for feature, site_id in zip(candidate_sites, ("direct", "buffer", "outside")):
        feature["geometry"] = {"type": "Point", "coordinates": feature["geometry"]["coordinates"][0][0]}
        feature["properties"] = {"building_id": site_id}

    result = screen_fire_impact([fire], tracts, warning_buffer_km=1.2, candidate_sites=candidate_sites)

    assert result["fire_count"] == 1
    assert result["warning_buffer_km"] == 1.2
    assert result["excluded_candidate_ids"] == ["direct", "buffer"]
    assert result["tracts"] == [
        {
            "tract_id": "06033000100",
            "tier": "potential_evacuation",
            "fire_ids": ["test-fire"],
        },
        {
            "tract_id": "06033000200",
            "tier": "potential_warning",
            "fire_ids": ["test-fire"],
        },
    ]


def test_historical_analog_returns_weighted_tract_frequency():
    fire = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-123.0, 39.0]},
        "properties": {"incident_id": "scenario-fire", "acres": 10},
    }
    training = {
        "status": "experimental",
        "distance_scale_km": 10,
        "log_acre_scale": 4,
        "tract_ids": ["06033000100", "06033000200"],
        "events": [
            {
                "center": [-123.0, 39.0],
                "fire_acres": 10,
                "tract_severity_labels": [3, 0],
            },
            {
                "center": [-123.0, 39.0],
                "fire_acres": 10,
                "tract_severity_labels": [0, 1],
            },
        ],
    }

    result = historical_analog_probabilities([fire], training)
    probabilities = {item["tract_id"]: item for item in result["tracts"]}

    assert result["available"] is True
    assert probabilities["06033000100"]["probability"] == 0.5
    assert probabilities["06033000100"]["mandatory_probability"] == 0.5
    assert probabilities["06033000200"]["warning_probability"] == 0.5
    assert probabilities["06033000100"]["effective_analog_count"] == 2