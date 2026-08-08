import unittest
from unittest.mock import patch

from mapmover.geometry_handlers import resolve_point_to_location, resolve_points_to_locations
from mapmover.runtime.loc_id_resolution import resolve_point_to_loc_id_stack


class GeometryPointResolutionRuntimeTests(unittest.TestCase):
    def test_california_block_point_resolves_through_admin5_spine(self):
        """Regression: audited CA Admin 5 must not stop at legacy geometry admin2."""
        result = resolve_point_to_loc_id_stack(-116.710700, 34.320563, include_geometry=False)

        self.assertEqual(result["deepest_resolved_admin_level"], "admin_5")
        self.assertEqual(result["deepest_resolved_loc_id"], "USA-CA-071-010424-3-3009")
        self.assertEqual(result["matches"]["admin_2"]["loc_id"], "USA-CA-071")
        self.assertEqual(result["matches"]["admin_3"]["loc_id"], "USA-CA-071-010424")
        self.assertEqual(result["matches"]["admin_4"]["loc_id"], "USA-CA-071-010424-3")

    def test_australia_point_resolves_to_declared_admin6_spine(self):
        result = resolve_point_to_loc_id_stack(139.827059, -27.604202, include_geometry=False)

        self.assertEqual(result["deepest_resolved_admin_level"], "admin_6")
        self.assertEqual(
            result["deepest_resolved_loc_id"],
            "AUS-SA-406-40602-406021141-40602114107-40215189900",
        )
        self.assertEqual(result["matches"]["admin_2"]["loc_id"], "AUS-SA-406")
        self.assertEqual(result["matches"]["admin_6"]["name"], "40215189900")

    def test_canada_point_resolves_to_declared_admin5_spine(self):
        result = resolve_point_to_loc_id_stack(-122.849, 49.191, include_geometry=False)

        self.assertEqual(result["deepest_resolved_admin_level"], "admin_5")
        self.assertEqual(
            result["deepest_resolved_loc_id"],
            "CAN-BC-5915004-59152203-59152203020",
        )
        self.assertEqual(result["matches"]["admin_2"]["loc_id"], "CAN-BC-5915")

    def test_brazil_bairro_point_resolves_to_declared_admin5_spine(self):
        result = resolve_point_to_loc_id_stack(-48.12994234942419, -22.793495497153657, include_geometry=False)

        self.assertEqual(result["deepest_resolved_admin_level"], "admin_5")
        self.assertEqual(
            result["deepest_resolved_loc_id"],
            "BRA-G114911670B46470234103867-G256859067B93211874574950-350230905-35023090500-3502309003",
        )
        self.assertEqual(result["matches"]["admin_5"]["name"], "Jardim Nova Anhembi")

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

    def test_resolve_points_to_locations_batches_country_admin_reads(self):
        import pandas as pd

        country_df = pd.DataFrame(
            [
                {
                    "loc_id": "USA",
                    "name": "United States",
                    "admin_level": 0,
                    "bbox_min_lon": -125,
                    "bbox_min_lat": 24,
                    "bbox_max_lon": -66,
                    "bbox_max_lat": 50,
                    "geometry": '{"type":"Polygon","coordinates":[[[-125,24],[-125,50],[-66,50],[-66,24],[-125,24]]]}',
                }
            ]
        )
        admin1_df = pd.DataFrame(
            [
                {
                    "loc_id": "USA-CA",
                    "parent_id": "USA",
                    "name": "California",
                    "admin_level": 1,
                    "bbox_min_lon": -125,
                    "bbox_min_lat": 32,
                    "bbox_max_lon": -113,
                    "bbox_max_lat": 42,
                    "geometry": '{"type":"Polygon","coordinates":[[[-125,32],[-125,42],[-113,42],[-113,32],[-125,32]]]}',
                }
            ]
        )
        admin2_df = pd.DataFrame(
            [
                {
                    "loc_id": "USA-CA-037",
                    "parent_id": "USA-CA",
                    "name": "Los Angeles",
                    "admin_level": 2,
                    "bbox_min_lon": -119,
                    "bbox_min_lat": 33,
                    "bbox_max_lon": -117,
                    "bbox_max_lat": 35,
                    "geometry": '{"type":"Polygon","coordinates":[[[-119,33],[-119,35],[-117,35],[-117,33],[-119,33]]]}',
                }
            ]
        )

        with (
            patch("mapmover.geometry_handlers.load_global_countries_frame", return_value=country_df),
            patch("mapmover.geometry_handlers.load_country_parquet_viewport", side_effect=[admin1_df, admin2_df]) as viewport_mock,
            patch("mapmover.geometry_handlers.get_country_supported_deep_admin_levels", return_value=[]),
        ):
            results = resolve_points_to_locations(
                [
                    {"row_index": 1, "lon": -118.25, "lat": 34.05},
                    {"row_index": 2, "lon": -118.2, "lat": 34.0},
                ],
                include_geometry=False,
            )

        self.assertEqual(viewport_mock.call_count, 2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["matched"]["loc_id"], "USA-CA-037")
        self.assertEqual(results[1]["matched"]["loc_id"], "USA-CA-037")


if __name__ == "__main__":
    unittest.main()
