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


if __name__ == "__main__":
    unittest.main()
