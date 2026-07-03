import unittest
from unittest.mock import patch

from mapmover.geometry_handlers import resolve_point_to_location


class GeometryPointResolutionRuntimeTests(unittest.TestCase):
    def test_resolve_point_to_location_prefers_admin2_without_series_truthiness(self):
        class _Frame:
            empty = False

        country_row = {"loc_id": "USA", "name": "United States", "admin_level": 0}
        admin1_row = {"loc_id": "USA-G125186", "name": "Virginia", "admin_level": 1}
        admin2_row = {"loc_id": "USA-G125186-G215213", "name": "Fairfax", "admin_level": 2}

        with (
            patch("mapmover.geometry_handlers.load_global_countries_frame", return_value=_Frame()),
            patch("mapmover.geometry_handlers.load_country_parquet_viewport", return_value=_Frame()),
            patch("mapmover.geometry_handlers.load_country_parquet", return_value=_Frame()),
            patch(
                "mapmover.geometry_handlers._find_containing_row",
                side_effect=[country_row, admin1_row, admin2_row],
            ),
            patch("mapmover.geometry_handlers._resolve_deepest_point_match", return_value=None),
        ):
            result = resolve_point_to_location(-77.307, 38.845, include_geometry=False)

        self.assertEqual(result["matched"]["loc_id"], "USA-G125186-G215213")
        self.assertEqual(result["matched"]["admin_level"], 2)
        self.assertEqual(result["stack"][1]["loc_id"], "USA-G125186")
        self.assertEqual(result["stack"][2]["loc_id"], "USA-G125186-G215213")

    def test_resolve_point_to_location_falls_back_to_country_bank_when_global_outline_misses(self):
        class _Frame:
            empty = False

        country_df = __import__("pandas").DataFrame(
            [
                {
                    "loc_id": "AUS",
                    "name": "Australia",
                    "admin_level": 0,
                    "bbox_min_lon": 73.0,
                    "bbox_min_lat": -55.0,
                    "bbox_max_lon": 168.0,
                    "bbox_max_lat": -10.0,
                    "geometry": '{"type":"Polygon","coordinates":[[[0,0],[0,1],[1,1],[1,0],[0,0]]]}',
                }
            ]
        )
        aus_admin0_df = __import__("pandas").DataFrame(
            [
                {
                    "loc_id": "AUS",
                    "name": "Australia",
                    "admin_level": 0,
                    "geometry": '{"type":"Polygon","coordinates":[[[150.0,-34.5],[150.0,-33.0],[152.0,-33.0],[152.0,-34.5],[150.0,-34.5]]]}',
                }
            ]
        )
        admin1_df = __import__("pandas").DataFrame(
            [
                {
                    "loc_id": "AUS-G114531",
                    "name": "New South Wales",
                    "admin_level": 1,
                    "geometry": '{"type":"Polygon","coordinates":[[[150.0,-34.5],[150.0,-33.0],[152.0,-33.0],[152.0,-34.5],[150.0,-34.5]]]}',
                }
            ]
        )
        admin2_df = __import__("pandas").DataFrame(
            [
                {
                    "loc_id": "AUS-G114531-G295907",
                    "name": "Sydney",
                    "admin_level": 2,
                    "geometry": '{"type":"Polygon","coordinates":[[[151.0,-34.2],[151.0,-33.6],[151.4,-33.6],[151.4,-34.2],[151.0,-34.2]]]}',
                }
            ]
        )

        with (
            patch("mapmover.geometry_handlers.load_global_countries_frame", return_value=country_df),
            patch(
                "mapmover.geometry_handlers.load_country_parquet",
                side_effect=lambda iso3, admin_level=None: aus_admin0_df if admin_level == 0 else admin1_df if admin_level == 1 else admin2_df if admin_level == 2 else None,
            ),
            patch("mapmover.geometry_handlers.load_country_parquet_viewport", side_effect=[admin1_df, admin2_df]),
            patch("mapmover.geometry_handlers._resolve_deepest_point_match", return_value=None),
        ):
            result = resolve_point_to_location(151.2093, -33.8688, include_geometry=False)

        self.assertEqual(result["country"]["loc_id"], "AUS")
        self.assertEqual(result["matched"]["loc_id"], "AUS-G114531-G295907")
        self.assertEqual(result["matched"]["admin_level"], 2)


if __name__ == "__main__":
    unittest.main()
