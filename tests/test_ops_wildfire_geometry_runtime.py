import json
import unittest

from mapmover.ops_orchestrator_runtime import (
    WILDFIRE_LIVE_FEED,
    _build_point_event_display_payload,
    _try_wildfire_snapshot_filter_result,
)


class OpsWildfireGeometryRuntimeTests(unittest.TestCase):
    def test_country_command_filters_the_display_payload(self):
        usa = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-120, 40]}, "properties": {"iso3": "USA", "area_km2": 1}}
        canada = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-78, 50]}, "properties": {"iso3": "CAN", "area_km2": 1}}
        payload = {"source_id": "wildfires_live_ops", "geojson": {"type": "FeatureCollection", "features": [usa, canada]}}
        report = {"display_payloads": [payload]}

        result = _try_wildfire_snapshot_filter_result(
            query="hide all fires in canada",
            report=report,
            effective_feeds=[WILDFIRE_LIVE_FEED],
            chat_history=[],
            cache=None,
        )

        filtered = result["display_payloads"][0]
        self.assertEqual("USA", filtered["ops_country_iso3"])
        self.assertTrue(filtered["ops_show_all"])
        self.assertEqual([usa], filtered["geojson"]["features"])

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
