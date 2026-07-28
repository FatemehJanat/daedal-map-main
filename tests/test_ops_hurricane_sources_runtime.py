import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from mapmover import ops_orchestrator_runtime as ops


class OpsHurricaneSourcesRuntimeTest(unittest.TestCase):
    def test_gdacs_alert_timestamp_cannot_replace_advisory_track(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        composed = ops._compose_hurricane_candidates({
            "storm_id": "EP062026",
            "basin": "EP",
            "source_candidates": {
                "NHC": {
                    "storm_id": "EP062026",
                    "source": "NHC",
                    "current_position": {
                        "timestamp": (now - timedelta(hours=2)).isoformat(),
                        "latitude": 16.6,
                        "longitude": -120.3,
                    },
                    "observed_track": [{"timestamp": (now - timedelta(hours=3)).isoformat(), "latitude": 16.3, "longitude": -119.0}],
                    "forecast_track": {"type": "LineString", "coordinates": [[-120.3, 16.6], [-121.4, 16.9]]},
                },
                "GDACS": {
                    "storm_id": "GDACS-TC1001289",
                    "source": "GDACS",
                    "current_position": {
                        "timestamp": now.isoformat(),
                        "latitude": 16.6,
                        "longitude": -120.3,
                    },
                },
            },
        })

        self.assertEqual("NHC", composed["selected_observed_source"])
        self.assertEqual("EP062026", composed["storm_id"])
        self.assertTrue(composed["forecast_track"])

    def test_basin_authority_wins_while_it_is_fresh(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        composed = ops._compose_hurricane_candidates({
            "storm_id": "WP092026",
            "basin": "WP",
            "source_candidates": {
                "JMA": {"source": "JMA", "current_position": {"timestamp": (now - timedelta(hours=4)).isoformat(), "latitude": 20, "longitude": 130}},
                "JTWC": {"source": "JTWC", "current_position": {"timestamp": (now - timedelta(hours=1)).isoformat(), "latitude": 20, "longitude": 130}},
            },
        })

        self.assertEqual("JMA", composed["selected_observed_source"])

    def test_overlapping_source_fills_in_when_basin_authority_is_stale(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        composed = ops._compose_hurricane_candidates({
            "storm_id": "WP092026",
            "basin": "WP",
            "source_candidates": {
                "JMA": {"source": "JMA", "current_position": {"timestamp": (now - timedelta(hours=7)).isoformat(), "latitude": 20, "longitude": 130}},
                "JTWC": {"source": "JTWC", "current_position": {"timestamp": (now - timedelta(hours=1)).isoformat(), "latitude": 20, "longitude": 130}},
            },
        })

        self.assertEqual("JTWC", composed["selected_observed_source"])

    def test_track_slots_keep_authority_and_fill_only_its_missing_gap(self):
        now = datetime.now(timezone.utc).replace(microsecond=0, minute=0, second=0)
        snapshot = {
            "payload_summary": {
                "storms": [{
                    "storm_id": "WP092026",
                    "identity": {"canonical_id": "WP092026"},
                    "name": "BAVI",
                    "year": now.year,
                    "basin": "WP",
                    "source": "JMA",
                    "selected_observed_source": "JMA",
                    "observed_track": [
                        {"timestamp": (now - timedelta(hours=6)).isoformat(), "latitude": 18.0, "longitude": 132.0},
                        {"timestamp": now.isoformat(), "latitude": 20.0, "longitude": 130.0},
                    ],
                    "current_position": {"timestamp": now.isoformat(), "latitude": 20.0, "longitude": 130.0},
                }],
            },
        }
        history = [{
            "payload_summary": {
                "storms": [{
                    "storm_id": "WP092026",
                    "identity": {"canonical_id": "WP092026"},
                    "name": "BAVI",
                    "year": now.year,
                    "basin": "WP",
                    "source": "JTWC",
                    "current_position": {"timestamp": (now - timedelta(hours=3)).isoformat(), "latitude": 19.0, "longitude": 131.0},
                }],
            },
        }]

        augmented = ops._with_hurricane_history_tracks(snapshot, history)
        points = augmented["payload_summary"]["storms"][0]["observed_track"]

        self.assertEqual([[132.0, 18.0], [131.0, 19.0], [130.0, 20.0]], [[point["longitude"], point["latitude"]] for point in points])

    def test_retired_ibtracs_display_payload_is_not_a_live_hurricane_feed(self):
        payloads = ops._report_display_payload_by_feed({
            "display_payloads": [
                {"source_id": "hurricanes_ops", "geojson": {"features": []}},
            ],
        })

        self.assertEqual({}, payloads)

        payloads = ops._report_display_payload_by_feed({
            "display_payloads": [
                {"source_id": "hurricanes_live_ops", "geojson": {"features": []}},
            ],
        })

        self.assertEqual({"hurricanes_live"}, set(payloads))
        self.assertEqual("hurricanes_live_ops", payloads["hurricanes_live"]["source_id"])

    def test_retained_advisories_build_solid_observed_track(self):
        snapshot = {
            "payload_summary": {
                "storms": [{
                    "storm_id": "WP092026",
                    "identity": {"canonical_id": "WP092026"},
                    "name": "BAVI",
                    "year": 2026,
                }],
            },
        }
        history = [
            {
                "payload_summary": {
                    "storms": [{
                        "storm_id": "WP092026",
                        "identity": {"canonical_id": "WP092026"},
                        "name": "BAVI",
                        "year": 2026,
                        "source": "JMA",
                        "current_position": {
                            "timestamp": "2026-07-04T00:00:00+00:00",
                            "latitude": 12.4,
                            "longitude": 151.5,
                        },
                    }],
                },
            },
            {
                "payload_summary": {
                    "storms": [{
                        "storm_id": "WP092026",
                        "identity": {"canonical_id": "WP092026"},
                        "name": "BAVI",
                        "year": 2026,
                        "source": "JTWC",
                        "current_position": {
                            "timestamp": "2026-07-04T06:00:00+00:00",
                            "latitude": 12.5,
                            "longitude": 150.8,
                        },
                    }],
                },
            },
        ]
        augmented = ops._with_hurricane_history_tracks(snapshot, history)
        track = augmented["payload_summary"]["storms"][0]["observed_track"]
        self.assertEqual(2, len(track))
        self.assertEqual(150.8, track[-1]["longitude"])

    def test_retained_history_does_not_turn_gdacs_alert_repolls_into_track_points(self):
        snapshot = {"payload_summary": {"storms": []}}
        history = [
            {
                "payload_summary": {
                    "storms": [{
                        "storm_id": "GDACS-TC1001279",
                        "name": "BAVI-26",
                        "year": 2026,
                        "source": "GDACS",
                        "current_position": {
                            "timestamp": "2026-07-15T17:55:16+00:00",
                            "latitude": 28.7,
                            "longitude": 120.4,
                        },
                    }],
                },
            },
            {
                "payload_summary": {
                    "storms": [{
                        "storm_id": "WP092026",
                        "identity": {"canonical_id": "WP092026"},
                        "name": "BAVI",
                        "year": 2026,
                        "source": "JMA",
                        "current_position": {
                            "timestamp": "2026-07-15T00:00:00+00:00",
                            "latitude": 40.0,
                            "longitude": 130.0,
                        },
                    }],
                },
            },
        ]

        augmented = ops._with_hurricane_history_tracks(snapshot, history)
        storms = augmented["payload_summary"]["storms"]

        self.assertEqual(1, len(storms))
        self.assertEqual("WP092026", storms[0]["storm_id"])
        self.assertEqual([[130.0, 40.0]], [[point["longitude"], point["latitude"]] for point in storms[0]["observed_track"]])
        self.assertEqual(130.0, storms[0]["current_position"]["longitude"])

    def test_logical_hurricanes_feed_unifies_agency_ids_and_gdacs_context(self):
        snapshots = {
            "tc_nhc/snapshot.json": {
                "collector": "tc_nhc",
                "ops_history_retention_hours": 336,
                "ops_history_display_hours": 336,
                "last_checked_at": "2026-07-04T07:30:00+00:00",
                "last_changed_at": "2026-07-04T07:30:00+00:00",
                "payload_hash": "nhc-hash",
                "payload_summary": {
                    "storms": [{
                        "storm_id": "EP052026",
                        "identity": {
                            "canonical_id": "EP052026",
                            "aliases": {"atcf_id": "EP052026"},
                        },
                        "name": "DOUGLAS",
                        "year": 2026,
                        "source": "NHC",
                        "current_position": {
                            "latitude": 12.5,
                            "longitude": 151.5,
                        },
                    }],
                },
            },
            "tc_gdacs/snapshot.json": {
                "collector": "tc_gdacs",
                "ops_history_retention_hours": 336,
                "ops_history_display_hours": 336,
                "last_checked_at": "2026-07-04T07:32:00+00:00",
                "last_changed_at": "2026-07-04T07:32:00+00:00",
                "payload_hash": "gdacs-hash",
                "payload_summary": {
                    "storms": [{
                        "storm_id": "GDACS-TC1001279",
                        "name": "BAVI-26",
                        "year": 2026,
                        "source": "GDACS",
                        "alert_level": "Red",
                        "population_affected": 170533,
                    }],
                },
            },
            "tc_jtwc/snapshot.json": {
                "collector": "tc_jtwc",
                "ops_history_retention_hours": 336,
                "ops_history_display_hours": 336,
                "last_checked_at": "2026-07-04T07:33:00+00:00",
                "last_changed_at": "2026-07-04T07:33:00+00:00",
                "payload_hash": "jtwc-hash",
                "payload_summary": {
                    "storms": [{
                        "storm_id": "WP092026",
                        "identity": {
                            "canonical_id": "WP092026",
                            "aliases": {"jtwc_warning_id": "09W"},
                        },
                        "name": "BAVI",
                        "year": 2026,
                        "source": "JTWC",
                    }],
                },
            },
            "tc_jma/snapshot.json": {
                "collector": "tc_jma",
                "ops_history_retention_hours": 336,
                "ops_history_display_hours": 336,
                "last_checked_at": "2026-07-04T07:34:00+00:00",
                "last_changed_at": "2026-07-04T07:34:00+00:00",
                "payload_hash": "jma-hash",
                "payload_summary": {
                    "storms": [{
                        "storm_id": "WP092026",
                        "identity": {
                            "canonical_id": "WP092026",
                            "aliases": {"jma_number": "2609"},
                        },
                        "name": "BAVI",
                        "year": 2026,
                        "source": "JMA",
                    }],
                },
            },
        }

        with (
            patch.object(ops, "_get_live_state_cache", return_value=None),
            patch.object(ops, "_read_json_object", side_effect=lambda key: snapshots.get(key)),
            patch.object(ops, "_fetch_live_state_via_site", return_value=None),
        ):
            snapshot = ops.load_current_state_snapshot("hurricanes")

        storms = snapshot["payload_summary"]["storms"]
        self.assertEqual(336, snapshot["ops_history_retention_hours"])
        self.assertEqual(336, snapshot["ops_history_display_hours"])
        self.assertEqual(2, len(storms))
        bavi = next(storm for storm in storms if storm["name"] == "BAVI")
        self.assertEqual("JTWC", bavi["source"])
        self.assertEqual(["GDACS", "JTWC", "JMA"], bavi["contributing_sources"])
        self.assertEqual("Red", bavi["gdacs_alert"]["alert_level"])
        self.assertEqual("09W", bavi["source_identities"]["JTWC"]["aliases"]["jtwc_warning_id"])
        self.assertEqual("2609", bavi["source_identities"]["JMA"]["aliases"]["jma_number"])

    def test_hurricane_history_payload_keeps_retained_only_storms_and_source_tracks(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        snapshot = {
            "collector": "hurricanes_live",
            "payload_hash": "current-hash",
            "ops_history_retention_hours": 336,
            "ops_history_display_hours": 336,
            "payload_summary": {
                "storms": [{
                    "storm_id": "WP092026",
                    "identity": {"canonical_id": "WP092026"},
                    "name": "BAVI",
                    "year": 2026,
                    "source": "JTWC",
                    "source_url": "https://www.metoc.navy.mil/jtwc/products/wp0926web.txt",
                    "current_position": {
                        "timestamp": (now - timedelta(hours=6)).isoformat(),
                        "latitude": 12.5,
                        "longitude": 150.8,
                        "wind_kt": 135,
                    },
                    "observed_track": [{
                        "timestamp": (now - timedelta(hours=12)).isoformat(),
                        "latitude": 12.4,
                        "longitude": 151.5,
                        "wind_kt": 120,
                    }],
                    "forecast_points": [
                        {
                            "valid_at": (now + timedelta(hours=12)).isoformat(),
                            "latitude": 13.2,
                            "longitude": 149.8,
                            "wind_kt": 130,
                        },
                        {
                            "valid_at": (now + timedelta(hours=24)).isoformat(),
                            "latitude": 14.0,
                            "longitude": 148.5,
                            "wind_kt": 125,
                        },
                    ],
                    "forecast_horizon_hours": 120,
                }],
            },
        }
        history = [
            {
                "published_at": (now - timedelta(hours=30)).isoformat(),
                "payload_summary": {
                    "storms": [{
                        "storm_id": "WP082026",
                        "identity": {"canonical_id": "WP082026"},
                        "name": "AILING",
                        "year": 2026,
                        "source": "JMA",
                        "current_position": {
                            "timestamp": (now - timedelta(hours=30)).isoformat(),
                            "latitude": 10.0,
                            "longitude": 140.0,
                        },
                    }],
                },
            },
            {
                "published_at": (now - timedelta(hours=9)).isoformat(),
                "payload_summary": {
                    "storms": [{
                        "storm_id": "WP092026",
                        "identity": {"canonical_id": "WP092026"},
                        "name": "BAVI",
                        "year": 2026,
                        "source": "JMA",
                        "current_position": {
                            "timestamp": (now - timedelta(hours=9)).isoformat(),
                            "latitude": 12.45,
                            "longitude": 151.0,
                        },
                    }],
                },
            },
        ]

        augmented = ops._with_hurricane_history_tracks(snapshot, history)
        storms = augmented["payload_summary"]["storms"]
        self.assertEqual({"WP092026", "WP082026"}, {storm["storm_id"] for storm in storms})
        bavi = next(storm for storm in storms if storm["storm_id"] == "WP092026")
        self.assertEqual(3, len(bavi["observed_track"]))
        retained = next(storm for storm in storms if storm["storm_id"] == "WP082026")
        self.assertTrue(retained["retained_history_only"])

        payload = ops._build_live_hurricane_display_payload(augmented)
        self.assertEqual("hurricanes_live_ops", payload["source_id"])
        features = payload["geojson"]["features"]
        kinds = [feature["properties"]["track_kind"] for feature in features]
        self.assertIn("observed", kinds)
        self.assertIn("forecast", kinds)
        observed = next(feature for feature in features if feature["properties"]["track_kind"] == "observed")
        current = next(feature for feature in features if feature["properties"]["track_kind"] == "current")
        self.assertEqual("Cat4", observed["properties"]["category"])
        self.assertEqual(135.0, observed["properties"]["max_wind_kt"])
        self.assertEqual("Joint Typhoon Warning Center", observed["properties"]["source_name"])
        self.assertEqual("https://www.metoc.navy.mil/jtwc/jtwc.html", observed["properties"]["source_url"])
        self.assertEqual("https://www.metoc.navy.mil/jtwc/jtwc.html", observed["properties"]["source_page_url"])
        self.assertEqual(
            "https://www.metoc.navy.mil/jtwc/products/wp0926web.txt",
            observed["properties"]["source_product_url"],
        )
        self.assertEqual("Cat4", current["properties"]["category"])
        self.assertEqual(135, current["properties"]["wind_kt"])
        self.assertEqual(2, payload["count"])

    def test_retained_hurricane_current_uses_latest_track_point(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        snapshot = {
            "collector": "hurricanes_live",
            "payload_hash": "current-hash",
            "ops_history_retention_hours": 336,
            "ops_history_display_hours": 336,
            "payload_summary": {"storms": []},
        }
        history = [
            {
                "published_at": (now - timedelta(hours=72)).isoformat(),
                "payload_summary": {
                    "storms": [{
                        "storm_id": "GDACS-TC1001281",
                        "name": "MAYSAK-26",
                        "year": 2026,
                        "source": "GDACS",
                        "current_position": {
                            "timestamp": (now - timedelta(hours=72)).isoformat(),
                            "latitude": 20.2,
                            "longitude": 108.4,
                        },
                    }],
                },
            },
            {
                "published_at": (now - timedelta(hours=48)).isoformat(),
                "payload_summary": {
                    "storms": [{
                        "storm_id": "WP102026",
                        "identity": {"canonical_id": "WP102026"},
                        "name": "MAYSAK",
                        "year": 2026,
                        "source": "JTWC",
                        "current_position": {
                            "timestamp": (now - timedelta(hours=48)).isoformat(),
                            "latitude": 21.6,
                            "longitude": 107.9,
                        },
                    }],
                },
            },
            {
                "published_at": (now - timedelta(hours=24)).isoformat(),
                "payload_summary": {
                    "storms": [{
                        "storm_id": "WP102026",
                        "identity": {"canonical_id": "WP102026"},
                        "name": "MAYSAK",
                        "year": 2026,
                        "source": "JMA",
                        "current_position": {
                            "timestamp": (now - timedelta(hours=24)).isoformat(),
                            "latitude": 25.0,
                            "longitude": 109.0,
                        },
                    }],
                },
            },
        ]

        augmented = ops._with_hurricane_history_tracks(snapshot, history)
        storm = augmented["payload_summary"]["storms"][0]
        self.assertTrue(storm["retained_history_only"])
        self.assertEqual(25.0, storm["current_position"]["latitude"])
        self.assertEqual(109.0, storm["current_position"]["longitude"])

        payload = ops._build_live_hurricane_display_payload(augmented)
        observed = next(
            feature for feature in payload["geojson"]["features"]
            if feature["properties"]["track_kind"] == "observed"
        )
        self.assertEqual([109.0, 25.0], observed["geometry"]["coordinates"][-1])
        self.assertNotEqual(
            observed["geometry"]["coordinates"][0],
            observed["geometry"]["coordinates"][-1],
        )

    def test_default_hurricane_history_uses_display_window_not_saved_retention(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        snapshot = {
            "collector": "hurricanes_live",
            "payload_hash": "current-hash",
            "ops_history_retention_hours": 336,
            "ops_history_display_hours": 72,
            "payload_summary": {"storms": []},
        }
        history = [
            {
                "published_at": (now - timedelta(hours=96)).isoformat(),
                "payload_summary": {
                    "storms": [{
                        "storm_id": "WP072026",
                        "identity": {"canonical_id": "WP072026"},
                        "name": "OLD",
                        "year": 2026,
                        "source": "JMA",
                        "current_position": {
                            "timestamp": (now - timedelta(hours=96)).isoformat(),
                            "latitude": 8.0,
                            "longitude": 130.0,
                        },
                    }],
                },
            },
            {
                "published_at": (now - timedelta(hours=48)).isoformat(),
                "payload_summary": {
                    "storms": [{
                        "storm_id": "WP082026",
                        "identity": {"canonical_id": "WP082026"},
                        "name": "RECENT",
                        "year": 2026,
                        "source": "JMA",
                        "current_position": {
                            "timestamp": (now - timedelta(hours=48)).isoformat(),
                            "latitude": 10.0,
                            "longitude": 140.0,
                        },
                    }],
                },
            },
        ]

        in_window, window_label = ops._default_history_window_entries(
            snapshot=snapshot,
            history_entries=history,
        )
        self.assertEqual("the default Ops display window (72h)", window_label)
        self.assertEqual(1, len(in_window))
        storms = in_window[0]["payload_summary"]["storms"]
        self.assertEqual("WP082026", storms[0]["storm_id"])

    def test_hurricane_display_drops_stale_source_slots(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        snapshot = {
            "collector": "hurricanes_live",
            "payload_hash": "current-hash",
            "ops_history_retention_hours": 336,
            "ops_history_display_hours": 336,
            "payload_summary": {
                "storms": [
                    {
                        "storm_id": "WP192025",
                        "identity": {"canonical_id": "WP192025"},
                        "name": "NEOGURI",
                        "year": 2025,
                        "source": "JMA",
                        "current_position": {
                            "timestamp": "2025-09-29T00:00:00+00:00",
                            "latitude": 42.0,
                            "longitude": 173.0,
                        },
                    },
                    {
                        "storm_id": "WP102026",
                        "identity": {"canonical_id": "WP102026"},
                        "name": "MAYSAK",
                        "year": 2026,
                        "source": "JMA",
                        "current_position": {
                            "timestamp": (now - timedelta(hours=96)).isoformat(),
                            "latitude": 25.0,
                            "longitude": 109.0,
                        },
                    },
                ],
            },
        }

        payload = ops._build_live_hurricane_display_payload(snapshot)
        names = {feature["properties"]["name"] for feature in payload["geojson"]["features"]}
        self.assertNotIn("NEOGURI", names)
        self.assertIn("MAYSAK", names)
        self.assertEqual(1, payload["count"])

    def test_terminal_advisory_never_renders_a_forecast(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        snapshot = {
            "collector": "hurricanes_live",
            "payload_hash": "current-hash",
            "ops_history_display_hours": 336,
            "payload_summary": {
                "storms": [{
                    "storm_id": "WP092026",
                    "name": "BAVI",
                    "source": "JTWC",
                    "issued_at": now.isoformat(),
                    "valid_through": (now - timedelta(hours=1)).isoformat(),
                    "current_position": {
                        "timestamp": now.isoformat(),
                        "latitude": 28.7,
                        "longitude": 120.4,
                        "wind_kt": 60,
                    },
                    "forecast_points": [{
                        "valid_at": (now + timedelta(hours=12)).isoformat(),
                        "latitude": 30.7,
                        "longitude": 118.5,
                        "wind_kt": 40,
                    }],
                }],
            },
        }

        payload = ops._build_live_hurricane_display_payload(snapshot)
        kinds = [feature["properties"]["track_kind"] for feature in payload["geojson"]["features"]]

        self.assertIn("current", kinds)
        self.assertNotIn("forecast", kinds)
        self.assertEqual("ended_recent", payload["geojson"]["features"][0]["properties"]["track_state"])

    def test_logical_wildfire_history_carries_forward_other_child_state(self):
        def child_entry(collector, at, event_id, iso3):
            return {
                "collector": collector,
                "published_at": at,
                "last_checked_at": at,
                "last_changed_at": at,
                "payload_hash": f"{collector}:{event_id}:{at}",
                "payload_summary": {
                    "events": [{
                        "event_id": event_id,
                        "latitude": 45.0,
                        "longitude": -120.0,
                        "area_km2": 10.0,
                        "iso3": iso3,
                    }],
                },
            }

        histories = [
            [
                child_entry("wildfires_us_nifc", "2026-07-27T00:00:00+00:00", "usa-1", "USA"),
                child_entry("wildfires_us_nifc", "2026-07-27T02:00:00+00:00", "usa-2", "USA"),
            ],
            [
                child_entry("wildfires_can_cwfis", "2026-07-27T01:00:00+00:00", "can-1", "CAN"),
            ],
        ]

        frames = ops._compose_logical_history(
            ops.WILDFIRE_LIVE_FEED,
            ops.WILDFIRE_OPS_COLLECTORS,
            histories,
        )

        self.assertEqual(3, len(frames))
        self.assertEqual(["USA"], [event["iso3"] for event in frames[0]["payload_summary"]["events"]])
        self.assertEqual({"USA", "CAN"}, {event["iso3"] for event in frames[1]["payload_summary"]["events"]})
        self.assertEqual({"usa-2", "can-1"}, {event["event_id"] for event in frames[-1]["payload_summary"]["events"]})


if __name__ == "__main__":
    unittest.main()
