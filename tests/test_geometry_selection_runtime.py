import unittest
from unittest.mock import patch

import pandas as pd

from mapmover.geometry_handlers import (
    _direct_family_bank_path,
    get_selection_geometries,
    load_geometry_rows_by_loc_ids,
)


class GeometrySelectionRuntimeTests(unittest.TestCase):
    def test_direct_family_bank_registry_maps_known_overlay_families(self):
        regional_path = _direct_family_bank_path("regional_base", "DEU")
        self.assertIsNotNone(regional_path)
        self.assertTrue(str(regional_path).replace("\\", "/").endswith("/countries/EUR/geometry.parquet"))
        self.assertEqual(
            _direct_family_bank_path("overlay_zcta", "USA").name,
            "USA.parquet",
        )
        self.assertEqual(
            _direct_family_bank_path("overlay_tribal", "USA").name,
            "USA.parquet",
        )
        self.assertIsNone(_direct_family_bank_path("admin_local", "USA"))

    def test_load_geometry_rows_by_loc_ids_partitions_mixed_families(self):
        zcta_df = pd.DataFrame(
            [
                {
                    "loc_id": "USA-Z-22031",
                    "geometry": '{"type":"Polygon","coordinates":[]}',
                    "name": "22031",
                }
            ]
        )
        marine_df = pd.DataFrame(
            [
                {
                    "loc_id": "EEZ-USA",
                    "geometry": '{"type":"Polygon","coordinates":[]}',
                    "name": "United States EEZ",
                }
            ]
        )

        with patch(
            "mapmover.geometry_handlers.load_marine_geometry",
            return_value=marine_df,
        ) as load_marine, patch(
            "mapmover.geometry_handlers._prefer_local_geometry_reads",
            return_value=True,
        ), patch(
            "mapmover.geometry_handlers._parquet_accessible",
            return_value=True,
        ), patch(
            "mapmover.geometry_handlers.pd.read_parquet",
            return_value=zcta_df,
        ):
            result = load_geometry_rows_by_loc_ids("USA", ["USA-Z-22031", "EEZ-USA"])

        self.assertEqual(set(result["loc_id"]), {"USA-Z-22031", "EEZ-USA"})
        load_marine.assert_called_once_with(["EEZ-USA"])

    def test_get_selection_geometries_handles_marine_and_admin_together(self):
        marine_df = pd.DataFrame(
            [
                {
                    "loc_id": "EEZ-USA",
                    "geometry": '{"type":"Polygon","coordinates":[]}',
                    "name": "United States EEZ",
                }
            ]
        )
        admin_df = pd.DataFrame(
            [
                {
                    "loc_id": "USA-Z-22031",
                    "geometry": '{"type":"Polygon","coordinates":[]}',
                    "name": "22031",
                }
            ]
        )

        with patch(
            "mapmover.geometry_handlers.load_marine_geometry",
            return_value=marine_df,
        ) as load_marine, patch(
            "mapmover.geometry_handlers.load_geometry_rows_by_loc_ids",
            return_value=admin_df,
        ):
            payload = get_selection_geometries(["EEZ-USA", "USA-Z-22031"])

        feature_ids = {
            feature.get("properties", {}).get("loc_id")
            for feature in payload.get("features", [])
        }
        self.assertEqual(feature_ids, {"EEZ-USA", "USA-Z-22031"})
        load_marine.assert_called_once_with(["EEZ-USA"])

    def test_load_geometry_rows_by_loc_ids_falls_back_to_level_loader_for_usa_admin1(self):
        level_df = pd.DataFrame(
            [
                {
                    "loc_id": "USA-G123456",
                    "local_loc_id": "USA-CA",
                    "name": "California",
                    "admin_level": 1,
                    "geometry": '{"type":"Polygon","coordinates":[]}',
                }
            ]
        )

        with patch(
            "mapmover.geometry_handlers._prefer_local_geometry_reads",
            return_value=False,
        ), patch(
            "mapmover.geometry_handlers._resolve_geometry_source",
            return_value=("dummy.parquet", {"mappings": {"USA-CA": "USA-G123456"}}),
        ), patch(
            "mapmover.geometry_handlers.select_rows",
            return_value=pd.DataFrame(),
        ), patch(
            "mapmover.geometry_handlers.load_country_parquet",
            return_value=level_df,
        ):
            result = load_geometry_rows_by_loc_ids("USA", ["USA-CA"])

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["loc_id"], "USA-CA")
        self.assertEqual(result.iloc[0]["local_loc_id"], "USA-CA")


if __name__ == "__main__":
    unittest.main()
