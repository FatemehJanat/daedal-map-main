import unittest

from mapmover.ops_point_feeds import POINT_FEEDS, _assemble_points_geojson


class OpsPointFeedTests(unittest.TestCase):
    def test_airnow_compact_rows_become_reporting_area_points(self):
        payload = {
            "reporting_areas": [[
                "Los Angeles", "CA", "PM2.5", 101, "Unhealthy for Sensitive Groups",
                34.0522, -118.2437, "2026-07-26T20:00:00+00:00", "South Coast AQMD", True,
            ]]
        }

        result = _assemble_points_geojson(POINT_FEEDS["airnow"], payload)

        self.assertEqual(1, result["count"])
        self.assertEqual([-118.2437, 34.0522], result["features"][0]["geometry"]["coordinates"])
        self.assertEqual(101, result["features"][0]["properties"]["aqi"])
        self.assertEqual("South Coast AQMD", result["features"][0]["properties"]["agency"])


if __name__ == "__main__":
    unittest.main()
