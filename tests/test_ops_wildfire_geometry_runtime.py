import json
import unittest

from mapmover.ops_orchestrator_runtime import _build_point_event_display_payload


class OpsWildfireGeometryRuntimeTests(unittest.TestCase):
    def test_multipart_perimeter_is_preserved_as_one_multipolygon_feature(self):
        perimeter = {
            "type": "MultiPolygon",
            "coordinates": [
                [[[-79.0, 50.0], [-78.9, 50.0], [-78.9, 50.1], [-79.0, 50.0]]],
                [[[-78.7, 50.2], [-78.6, 50.2], [-78.6, 50.3], [-78.7, 50.2]]],
            ],
        }
        snapshot = {
            "payload_hash": "test",
            "payload_summary": {
                "events": [{
                    "event_id": "CAN-M3-test",
                    "latitude": 50.15,
                    "longitude": -78.8,
                    "area_km2": 20.0,
                    "perimeter": json.dumps(perimeter),
                }],
            },
        }

        payload = _build_point_event_display_payload(
            snapshot,
            collector="wildfires",
            event_type="wildfire",
            label="Ops Wildfire Snapshot",
        )

        features = payload["geojson"]["features"]
        self.assertEqual(1, len(features))
        self.assertEqual("MultiPolygon", features[0]["geometry"]["type"])
        self.assertEqual(2, len(features[0]["geometry"]["coordinates"]))
        self.assertEqual("CAN-M3-test", features[0]["properties"]["event_id"])


if __name__ == "__main__":
    unittest.main()
