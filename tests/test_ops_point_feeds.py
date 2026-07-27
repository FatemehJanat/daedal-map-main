import unittest

from mapmover.ops_point_feeds import POINT_FEEDS, _assemble_points_geojson, _visible_air_quality_stations


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

    def test_air_quality_clusters_stay_source_separated_then_expand(self):
        def feature(source, lon, lat):
            return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": {"source_label": source, "station_name": source, "observed_at": "2026-07-27T00:00:00+00:00"}}
        base = {"type": "FeatureCollection", "count": 3, "features": [
            feature("OpenAQ", -118.2, 34.0), feature("OpenAQ", -118.1, 34.1), feature("AirNow", -118.2, 34.0),
        ]}
        clustered = _visible_air_quality_stations(base, bbox=(-120, 33, -117, 35), zoom=3)
        self.assertEqual(2, clustered["count"])
        self.assertTrue(clustered["merged"])
        self.assertEqual({"OpenAQ", "AirNow"}, {item["properties"]["source_label"] for item in clustered["features"]})
        expanded = _visible_air_quality_stations(base, bbox=(-120, 33, -117, 35), zoom=9)
        self.assertEqual(3, expanded["count"])
        self.assertFalse(expanded["merged"])


if __name__ == "__main__":
    unittest.main()
