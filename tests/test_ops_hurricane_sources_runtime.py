import unittest
from unittest.mock import patch

from mapmover import ops_orchestrator_runtime as ops


class OpsHurricaneSourcesRuntimeTest(unittest.TestCase):
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

    def test_logical_hurricanes_feed_unifies_agency_ids_and_gdacs_context(self):
        snapshots = {
            "tc_nhc/snapshot.json": {
                "collector": "tc_nhc",
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
        self.assertEqual(2, len(storms))
        bavi = next(storm for storm in storms if storm["name"] == "BAVI")
        self.assertEqual("JTWC", bavi["source"])
        self.assertEqual(["GDACS", "JTWC", "JMA"], bavi["contributing_sources"])
        self.assertEqual("Red", bavi["gdacs_alert"]["alert_level"])
        self.assertEqual("09W", bavi["source_identities"]["JTWC"]["aliases"]["jtwc_warning_id"])
        self.assertEqual("2609", bavi["source_identities"]["JMA"]["aliases"]["jma_number"])


if __name__ == "__main__":
    unittest.main()
