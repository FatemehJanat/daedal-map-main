import unittest
from unittest.mock import patch

import pandas as pd

from mapmover.geometry_handlers import (
    _load_deep_geometry_index_rows,
    _load_subcounty_rows_by_loc_ids,
    _direct_family_bank_path,
    df_to_geojson,
    get_selection_geometries,
    load_geometry_rows_by_loc_ids,
)


class GeometrySelectionRuntimeTests(unittest.TestCase):
    def test_usa_admin5_selection_carries_census_geometry_provenance(self):
        frame = pd.DataFrame(
            [{
                "loc_id": "USA-NE-021-963200-1-1062",
                "iso_a3": "USA",
                "admin_level": 5,
                "geometry": '{"type":"Polygon","coordinates":[]}',
            }]
        )

        payload = df_to_geojson(frame)

        self.assertEqual(
            payload["features"][0]["properties"]["geometry_source"],
            "U.S. Census Bureau TIGER/Line 2024 TABBLOCK20",
        )

    def test_deep_selection_passes_exact_ids_to_partition_reader(self):
        requested = ["USA-DE-001-000101-1-1000", "USA-DE-001-000101-1-1001"]
        returned = pd.DataFrame(
            [{"loc_id": loc_id, "geometry": "{}"} for loc_id in requested]
        )

        with patch(
            "mapmover.geometry_handlers.load_subcounty_geometry",
            return_value=returned,
        ) as load_subcounty:
            result = _load_subcounty_rows_by_loc_ids("USA", requested)

        self.assertEqual(set(result["loc_id"]), set(requested))
        self.assertEqual(load_subcounty.call_count, 1)
        self.assertEqual(load_subcounty.call_args.kwargs["loc_ids"], requested)
        self.assertEqual(load_subcounty.call_args.kwargs["state_abbrev"], "DE")

    def test_deep_index_requests_bbox_projection_not_polygon_payload(self):
        index_df = pd.DataFrame(
            [{"loc_id": "USA-DE-001-000101-1-1000", "admin_level": 5}]
        )

        with patch(
            "mapmover.geometry_handlers.get_regions_in_bbox",
            return_value=["DE"],
        ), patch(
            "mapmover.geometry_handlers.load_subcounty_geometry",
            return_value=index_df,
        ) as load_subcounty:
            result = _load_deep_geometry_index_rows(
                "USA", admin_level=5, bbox=(-75.7, 38.4, -75.5, 38.6)
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(load_subcounty.call_args.kwargs["bbox"], (-75.7, 38.4, -75.5, 38.6))
        self.assertNotIn("geometry", load_subcounty.call_args.kwargs["columns"])

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
        self.assertEqual(
            _direct_family_bank_path("overlay_nws_public_zone", "USA").name,
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
        load_marine.assert_called_once_with(["EEZ-USA"], columns=None)

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

    def test_state_scoped_tribal_id_uses_direct_family_bank_not_admin3_loader(self):
        tribal_df = pd.DataFrame(
            [{
                "loc_id": "USA-CA-TRIBAL-4760",
                "name": "Yurok",
                "geometry": '{"type":"Polygon","coordinates":[]}',
            }]
        )

        with patch(
            "mapmover.geometry_handlers.load_geometry_rows_by_loc_ids",
            return_value=tribal_df,
        ) as direct_loader, patch(
            "mapmover.geometry_handlers._load_subcounty_rows_by_loc_ids",
            return_value=pd.DataFrame(),
        ) as deep_loader:
            payload = get_selection_geometries(["USA-CA-TRIBAL-4760"])

        self.assertEqual(len(payload["features"]), 1)
        direct_loader.assert_called_once_with("USA", ["USA-CA-TRIBAL-4760"])
        deep_loader.assert_not_called()

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
            "mapmover.geometry_handlers.is_cloud_mode",
            return_value=True,
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
