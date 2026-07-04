import unittest
from unittest.mock import patch

from mapmover import ops_orchestrator_runtime as ops


class OpsHurricaneSourcesRuntimeTest(unittest.TestCase):
    def test_logical_hurricanes_feed_merges_gdacs_context_into_nhc_storm(self):
        snapshots = {
            "tc_nhc/snapshot.json": {
                "collector": "tc_nhc",
                "last_checked_at": "2026-07-04T07:30:00+00:00",
                "last_changed_at": "2026-07-04T07:30:00+00:00",
                "payload_hash": "nhc-hash",
                "payload_summary": {
                    "storms": [{
                        "storm_id": "WP012026",
                        "name": "BAVI",
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
        }

        with (
            patch.object(ops, "_get_live_state_cache", return_value=None),
            patch.object(ops, "_read_json_object", side_effect=lambda key: snapshots.get(key)),
            patch.object(ops, "_fetch_live_state_via_site", return_value=None),
        ):
            snapshot = ops.load_current_state_snapshot("hurricanes")

        storms = snapshot["payload_summary"]["storms"]
        self.assertEqual(1, len(storms))
        self.assertEqual("NHC", storms[0]["source"])
        self.assertEqual(["NHC", "GDACS"], storms[0]["contributing_sources"])
        self.assertEqual("Red", storms[0]["gdacs_alert"]["alert_level"])


if __name__ == "__main__":
    unittest.main()
