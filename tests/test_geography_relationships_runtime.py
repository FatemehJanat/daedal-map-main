from __future__ import annotations

import unittest
from unittest import mock

from shapely.geometry import Polygon, mapping

from mapmover.runtime.geography_relationships import (
    compare_geographies,
    historical_entity_info,
    resolve_historical_country_reference,
)


def _feature(loc_id: str, polygon: Polygon) -> dict:
    return {
        "ok": True,
        "has_shape": True,
        "loc_id": loc_id,
        "name": loc_id,
        "family": "test",
        "admin_level": None,
        "geometry": mapping(polygon),
    }


class GeographyRelationshipRuntimeTests(unittest.TestCase):
    def test_yugoslavia_2000_selects_valid_federal_republic(self) -> None:
        result = resolve_historical_country_reference("YUG", as_of="2000")

        self.assertTrue(result["ok"])
        self.assertEqual(result["resolved_loc_id"], "HIST-YUG-FRY")
        self.assertTrue(result["valid_at_requested_time"])
        self.assertEqual(result["lifecycle"]["direct_successors"][0]["loc_id"], "HIST-SCG")

    def test_yugoslavia_2025_is_expired_and_has_many_terminal_descendants(self) -> None:
        result = resolve_historical_country_reference("Yugoslavia", as_of="2025-01-01")

        self.assertTrue(result["ok"])
        self.assertFalse(result["valid_at_requested_time"])
        self.assertEqual(result["lifecycle"]["successor_cardinality"], "one")
        self.assertEqual(result["lifecycle"]["direct_successors"][0]["loc_id"], "HIST-SCG")
        self.assertEqual(
            {row["loc_id"] for row in result["lifecycle"]["present_day_descendants"]},
            {"SRB", "MNE"},
        )
        sfr_history = next(row for row in result["name_history"] if row["loc_id"] == "HIST-YUG-SFRY")
        self.assertEqual(
            {row["loc_id"] for row in sfr_history["present_day_descendants"]},
            {"BIH", "HRV", "SVN", "MKD", "SRB", "MNE"},
        )
        self.assertTrue(all(row["geometry_request"]["tool"] == "get_geometry" for row in sfr_history["present_day_descendants"]))

    def test_sfr_yugoslavia_has_five_equal_successors_and_six_current_descendants(self) -> None:
        result = historical_entity_info("HIST-YUG-SFRY", as_of="1990")

        self.assertTrue(result["valid_at_requested_time"])
        self.assertEqual(result["successor_cardinality"], "many")
        self.assertEqual(len(result["direct_successors"]), 5)
        self.assertEqual(
            {row["loc_id"] for row in result["present_day_descendants"]},
            {"BIH", "HRV", "SVN", "MKD", "SRB", "MNE"},
        )

    def test_compare_geographies_returns_directional_overlap_shares(self) -> None:
        geometries = {
            "LEFT": _feature("LEFT", Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])),
            "RIGHT": _feature("RIGHT", Polygon([(1, 0), (4, 0), (4, 2), (1, 2)])),
        }

        result = compare_geographies(
            "LEFT",
            "RIGHT",
            geometry_fetcher=lambda loc_id, **_kwargs: geometries[loc_id],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["spatial_relation"], "overlaps")
        self.assertAlmostEqual(result["left_area_share"], 0.5, places=3)
        self.assertAlmostEqual(result["right_area_share"], 1 / 3, places=3)
        self.assertGreater(result["intersection_area_km2"], 0)

    def test_invalid_historical_identity_does_not_reuse_current_geometry(self) -> None:
        result = compare_geographies(
            "HIST-YUG-FRY",
            "SRB",
            as_of="2025",
            geometry_fetcher=lambda loc_id, **_kwargs: {"ok": False, "loc_id": loc_id, "has_shape": False},
        )

        self.assertEqual(result["temporal_relation"], "one_or_more_not_valid")
        self.assertEqual(result["spatial_relation"], "not_evaluated")
        self.assertEqual(
            {row["loc_id"] for row in result["left"]["present_day_descendants"]},
            {"SRB", "MNE"},
        )

    def test_bank_validity_windows_control_temporal_comparison(self) -> None:
        polygons = {
            "LEFT": {**_feature("LEFT", Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])), "valid_from": "2020", "valid_to": "2024"},
            "RIGHT": {**_feature("RIGHT", Polygon([(1, 0), (3, 0), (3, 2), (1, 2)])), "valid_from": "2020", "valid_to": None},
        }

        result = compare_geographies(
            "LEFT",
            "RIGHT",
            as_of="2025",
            geometry_fetcher=lambda loc_id, **_kwargs: polygons[loc_id],
        )

        self.assertEqual(result["temporal_relation"], "one_or_more_not_valid")
        self.assertFalse(result["left"]["valid_at_requested_time"])
        self.assertTrue(result["right"]["valid_at_requested_time"])
        self.assertEqual(result["spatial_relation"], "not_evaluated")

    def test_reference_graph_validity_controls_temporal_comparison(self) -> None:
        graph_rows = {
            "OLD": {"loc_id": "OLD", "family": "test", "valid_from": "1996-01-01", "valid_to": "2004-01-01"},
            "NEW": {"loc_id": "NEW", "family": "test", "valid_from": "2023-01-01", "valid_to": ""},
        }
        with mock.patch(
            "mapmover.runtime.reference_graph.identity_at",
            side_effect=lambda loc_id, _when: graph_rows.get(loc_id),
        ):
            result = compare_geographies(
                "OLD",
                "NEW",
                as_of="2025",
                geometry_fetcher=lambda loc_id, **_kwargs: {"ok": False, "loc_id": loc_id, "has_shape": False},
            )

        self.assertEqual(result["temporal_relation"], "one_or_more_not_valid")
        self.assertFalse(result["left"]["valid_at_requested_time"])
        self.assertTrue(result["right"]["valid_at_requested_time"])
        self.assertEqual(result["spatial_relation"], "not_evaluated")


if __name__ == "__main__":
    unittest.main()
