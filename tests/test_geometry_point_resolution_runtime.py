import pytest
import unittest
from unittest.mock import patch

from mapmover.geometry_handlers import (
    get_selection_geometries,
    get_selection_geometry_metadata,
    get_location_info,
    resolve_point_to_location,
    resolve_points_to_locations,
)
from mapmover.runtime.geometry_spine import geometry_spine_index_for_frame
from mapmover.runtime.loc_id_resolution import resolve_point_to_loc_id_stack


class GeometryPointResolutionRuntimeTests(unittest.TestCase):
    def test_runtime_geometry_spine_prefers_smallest_covering_polygon(self):
        import pandas as pd

        frame = pd.DataFrame(
            [
                {
                    "loc_id": "USA",
                    "name": "United States",
                    "admin_level": 0,
                    "geometry": '{"type":"Polygon","coordinates":[[[-125,24],[-125,50],[-66,50],[-66,24],[-125,24]]]}',
                },
                {
                    "loc_id": "USA-CA",
                    "name": "California",
                    "admin_level": 1,
                    "geometry": '{"type":"Polygon","coordinates":[[[-125,32],[-125,42],[-113,42],[-113,32],[-125,32]]]}',
                },
                {
                    "loc_id": "USA-CA-037",
                    "name": "Los Angeles",
                    "admin_level": 2,
                    "geometry": '{"type":"Polygon","coordinates":[[[-119,33],[-119,35],[-117,35],[-117,33],[-119,33]]]}',
                },
            ]
        )

        match = geometry_spine_index_for_frame(frame).match_point(-118.25, 34.05)

        self.assertIsNotNone(match)
        self.assertEqual(match.row["loc_id"], "USA-CA-037")
        self.assertEqual(match.candidate_count, 3)

    def test_runtime_geometry_spine_matches_points_in_one_batch(self):
        import pandas as pd

        frame = pd.DataFrame(
            [
                {
                    "loc_id": "A",
                    "name": "A",
                    "admin_level": 1,
                    "geometry": '{"type":"Polygon","coordinates":[[[0,0],[0,10],[10,10],[10,0],[0,0]]]}',
                },
                {
                    "loc_id": "B",
                    "name": "B",
                    "admin_level": 1,
                    "geometry": '{"type":"Polygon","coordinates":[[[20,20],[20,30],[30,30],[30,20],[20,20]]]}',
                },
            ]
        )

        matches = geometry_spine_index_for_frame(frame).match_points(
            [{"lon": 1, "lat": 1}, {"lon": 21, "lat": 21}, {"lon": 99, "lat": 99}]
        )

        self.assertEqual(matches[0].row["loc_id"], "A")
        self.assertEqual(matches[1].row["loc_id"], "B")
        self.assertIsNone(matches[2])

    def test_runtime_geometry_spine_accepts_wkb_geometry(self):
        import pandas as pd
        from shapely.geometry import Polygon

        frame = pd.DataFrame([{
            "loc_id": "USA-VA-600", "name": "Fairfax city", "admin_level": 2,
            "geometry": Polygon([(-78, 38), (-78, 39), (-77, 39), (-77, 38), (-78, 38)]).wkb,
        }])

        match = geometry_spine_index_for_frame(frame).match_point(-77.3, 38.84)

        self.assertIsNotNone(match)
        self.assertEqual(match.row["loc_id"], "USA-VA-600")

    def test_california_block_point_resolves_through_admin5_spine(self):
        """Regression: audited CA Admin 5 must not stop at legacy geometry admin2."""
        result = resolve_point_to_loc_id_stack(-116.710700, 34.320563, include_geometry=False)

        self.assertEqual(result["deepest_resolved_admin_level"], "admin_5")
        self.assertEqual(result["deepest_resolved_loc_id"], "USA-CA-071-010424-3-009")
        self.assertEqual(result["matches"]["admin_2"]["loc_id"], "USA-CA-071")
        self.assertEqual(result["matches"]["admin_3"]["loc_id"], "USA-CA-071-010424")
        self.assertEqual(result["matches"]["admin_4"]["loc_id"], "USA-CA-071-010424-3")

    def test_australia_point_resolves_to_declared_admin6_spine(self):
        result = resolve_point_to_loc_id_stack(139.827059, -27.604202, include_geometry=False)

        self.assertEqual(result["deepest_resolved_admin_level"], "admin_6")
        self.assertEqual(
            result["deepest_resolved_loc_id"],
            "AUS-SA-406-02-1141-07-0215189900",
        )
        self.assertEqual(result["matches"]["admin_2"]["loc_id"], "AUS-SA-406")
        self.assertEqual(result["matches"]["admin_6"]["name"], "40215189900")

    def test_canada_point_resolves_to_declared_admin5_spine(self):
        result = resolve_point_to_loc_id_stack(-122.849, 49.191, include_geometry=False)

        self.assertEqual(result["deepest_resolved_admin_level"], "admin_5")
        self.assertEqual(
            result["deepest_resolved_loc_id"],
            "CAN-BC-5915-004-2203-020",
        )
        self.assertEqual(result["matches"]["admin_2"]["loc_id"], "CAN-BC-5915")

    def test_canada_complete_point_chain_can_fetch_every_level_shape(self):
        result = resolve_points_to_locations(
            [{"lon": -122.849, "lat": 49.191}],
            country_scope="CAN",
        )[0]
        loc_ids = [row["loc_id"] for row in result["stack"]]

        metadata = get_selection_geometry_metadata(loc_ids)
        features = get_selection_geometries(loc_ids)["features"]

        self.assertEqual([row["admin_level"] for row in result["stack"]], [0, 1, 2, 3, 4, 5])
        self.assertEqual({row["loc_id"] for row in metadata}, set(loc_ids))
        self.assertEqual({feature["properties"]["loc_id"] for feature in features}, set(loc_ids))

        strict_chain = []
        current = loc_ids[-1]
        while current:
            info = get_location_info(current)
            strict_chain.append(info["loc_id"])
            self.assertTrue(info["has_polygon"])
            current = info.get("parent_id")
        self.assertEqual(strict_chain, list(reversed(loc_ids)))

    def test_brazil_bairro_point_resolves_to_declared_admin5_spine(self):
        result = resolve_point_to_loc_id_stack(-48.12994234942419, -22.793495497153657, include_geometry=False)

        self.assertEqual(result["deepest_resolved_admin_level"], "admin_5")
        self.assertEqual(
            result["deepest_resolved_loc_id"],
            "BRA-SP-3502309-05-00-003",
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

    def test_bulk_resolution_reuses_complete_prewarmed_admin_frames(self):
        import pandas as pd

        country_df = pd.DataFrame([{
            "loc_id": "USA", "name": "United States", "admin_level": 0,
            "geometry": '{"type":"Polygon","coordinates":[[[-125,24],[-125,50],[-66,50],[-66,24],[-125,24]]]}',
        }])
        admin1_df = pd.DataFrame([{
            "loc_id": "USA-CA", "parent_id": "USA", "name": "California", "admin_level": 1,
            "geometry": '{"type":"Polygon","coordinates":[[[-125,32],[-125,42],[-113,42],[-113,32],[-125,32]]]}',
        }])
        admin2_df = pd.DataFrame([{
            "loc_id": "USA-CA-037", "parent_id": "USA-CA", "name": "Los Angeles", "admin_level": 2,
            "geometry": '{"type":"Polygon","coordinates":[[[-119,33],[-119,35],[-117,35],[-117,33],[-119,33]]]}',
        }])

        with (
            patch("mapmover.geometry_handlers.load_global_countries_frame", return_value=country_df),
            patch("mapmover.geometry_handlers._cached_country_admin_frame", side_effect=lambda _iso3, level: admin1_df if level == 1 else admin2_df),
            patch("mapmover.geometry_handlers.load_country_parquet_viewport") as viewport_mock,
            patch("mapmover.geometry_handlers.get_country_supported_deep_admin_levels", return_value=[]),
        ):
            results = resolve_points_to_locations(
                [{"lon": -118.25, "lat": 34.05}],
                country_scope="USA",
                target_admin_level=2,
            )

        viewport_mock.assert_not_called()
        self.assertEqual(results[0]["matched"]["loc_id"], "USA-CA-037")

    def test_resolve_points_to_locations_skips_county_load_for_state_target(self):
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

        with (
            patch("mapmover.geometry_handlers.load_global_countries_frame", return_value=country_df),
            patch("mapmover.geometry_handlers.load_country_parquet_viewport", return_value=admin1_df) as viewport_mock,
            patch("mapmover.geometry_handlers.get_country_supported_deep_admin_levels", return_value=[]),
        ):
            results = resolve_points_to_locations(
                [{"lon": -118.25, "lat": 34.05}],
                include_geometry=False,
                target_admin_level=1,
            )

        viewport_mock.assert_called_once()
        self.assertEqual(viewport_mock.call_args.args[1], 1)
        self.assertEqual(results[0]["matched"]["loc_id"], "USA-CA")
        self.assertEqual(results[0]["target_admin_level"], "admin_1")

    def test_resolve_points_country_scope_skips_global_country_overlay(self):
        import pandas as pd

        country_df = pd.DataFrame(
            [
                {
                    "loc_id": "USA",
                    "name": "United States",
                    "admin_level": 0,
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
                    "geometry": '{"type":"Polygon","coordinates":[[[-119,33],[-119,35],[-117,35],[-117,33],[-119,33]]]}',
                }
            ]
        )

        with (
            patch("mapmover.geometry_handlers.load_global_countries_frame", return_value=country_df),
            patch("mapmover.geometry_handlers.load_country_parquet_viewport", side_effect=[admin1_df, admin2_df]),
            patch("mapmover.geometry_handlers.get_country_supported_deep_admin_levels", return_value=[]),
            patch("mapmover.geometry_handlers._find_containing_country_with_fallback") as country_fallback,
        ):
            results = resolve_points_to_locations(
                [{"lon": -118.25, "lat": 34.05}],
                include_geometry=False,
                country_scope="USA",
            )

        country_fallback.assert_not_called()
        self.assertEqual(results[0]["country"]["loc_id"], "USA")
        self.assertEqual(results[0]["matched"]["loc_id"], "USA-CA-037")

    def test_resolve_points_errors_when_requested_depth_is_unavailable(self):
        import pandas as pd

        country_df = pd.DataFrame(
            [
                {
                    "loc_id": "USA",
                    "name": "United States",
                    "admin_level": 0,
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
                    "geometry": '{"type":"Polygon","coordinates":[[[-119,33],[-119,35],[-117,35],[-117,33],[-119,33]]]}',
                }
            ]
        )

        with (
            patch("mapmover.geometry_handlers.load_global_countries_frame", return_value=country_df),
            patch("mapmover.geometry_handlers.load_country_parquet_viewport", side_effect=[admin1_df, admin2_df]),
            patch("mapmover.geometry_handlers.get_country_supported_deep_admin_levels", return_value=[]),
        ):
            results = resolve_points_to_locations(
                [{"lon": -118.25, "lat": 34.05}],
                include_geometry=False,
                target_admin_level=3,
                country_scope="USA",
            )

        self.assertEqual(results[0]["error"]["code"], "target_admin_level_unavailable")
        self.assertEqual(results[0]["error"]["message"], "USA currently serves through admin_2, not admin_3")
        self.assertEqual(results[0]["target_admin_level"], "admin_3")
        self.assertEqual(results[0]["max_available_admin_level"], "admin_2")
        self.assertEqual(results[0]["available_admin_levels"], ["admin_0", "admin_1", "admin_2"])
        self.assertEqual(results[0]["matched"]["loc_id"], "USA-CA-037")

    def test_resolve_points_defaults_to_complete_deep_chain(self):
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
        deep_frames = []
        parent_id = "USA-CA-037"
        for level, loc_id, name in (
            (3, "USA-CA-037-000100", "Tract 100"),
            (4, "USA-CA-037-000100-1", "Block Group 1"),
            (5, "USA-CA-037-000100-1-1001", "Block 1001"),
        ):
            stored_parent_id = "USA-CA-037-OLD" if level == 4 else parent_id
            deep_frames.append(
                pd.DataFrame(
                    [
                        {
                            "loc_id": loc_id,
                            "parent_id": stored_parent_id,
                            "name": name,
                            "admin_level": level,
                            "source_vintage": "2025" if level == 3 else "2021",
                            "geometry": '{"type":"Polygon","coordinates":[[[-119,33],[-119,35],[-117,35],[-117,33],[-119,33]]]}',
                        }
                    ]
                )
            )
            parent_id = loc_id

        with (
            patch("mapmover.geometry_handlers.load_global_countries_frame", return_value=country_df),
            patch("mapmover.geometry_handlers.load_country_parquet_viewport", side_effect=[admin1_df, admin2_df]),
            patch("mapmover.geometry_handlers.get_country_supported_deep_admin_levels", return_value=[3, 4, 5]),
            patch("mapmover.geometry_handlers.load_subcounty_geometry", side_effect=deep_frames) as deep_mock,
        ):
            results = resolve_points_to_locations([{"lon": -118.25, "lat": 34.05}])

        self.assertEqual(results[0]["matched"]["loc_id"], "USA-CA-037-000100-1-1001")
        self.assertEqual(results[0]["target_admin_level"], "deepest")
        self.assertFalse(results[0]["deeper_available"])
        self.assertEqual([row["admin_level"] for row in results[0]["stack"]], [0, 1, 2, 3, 4, 5])
        self.assertEqual([row.get("vintage") for row in results[0]["stack"][3:]], ["2025", "2021", "2021"])
        self.assertEqual(results[0]["resolution_mode"], "latest_available_per_depth")
        self.assertEqual(deep_mock.call_count, 3)


if __name__ == "__main__":
    unittest.main()
