from __future__ import annotations

import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mapmover.routes.geometry import router as geometry_router
from mapmover.runtime import reference_exchange
from mapmover.runtime.reference_exchange import (
    LOC_ID_SYSTEM,
    convert_reference,
    list_reference_systems,
    loc_id_references,
    resolve_reference,
)


class ReferenceExchangeRuntimeTests(unittest.TestCase):
    def test_list_reference_systems_is_catalog_backed(self) -> None:
        payload = list_reference_systems()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["reserve_system"], LOC_ID_SYSTEM)
        systems = {item["system"] for item in payload["systems"]}
        self.assertIn(LOC_ID_SYSTEM, systems)
        self.assertIn("overlay_zcta", systems)
        self.assertIn("overlay_nws_fire_weather_zone", systems)
        self.assertGreaterEqual(len(payload["bridges"]), 1)

    def test_resolve_zip_alias_to_loc_id_uses_bridge_overlap(self) -> None:
        payload = resolve_reference(
            from_system="zip",
            value="00601",
            target_admin_level="admin_2",
            limit=2,
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["normalized_input"], "USA-Z-00601")
        self.assertEqual(payload["resolved_loc_id"], "USA-PR-001")
        self.assertEqual(payload["match_type"], "bridge_overlap")
        self.assertGreaterEqual(payload["match_count"], 1)
        self.assertEqual(payload["matches"][0]["target"]["loc_id"], "USA-PR-001")

    def test_resolve_noaa_fire_zone_alias_to_loc_id_uses_bridge_overlap(self) -> None:
        payload = resolve_reference(
            from_system="nws_fire",
            value="AKZ317",
            target_admin_level="admin_2",
            limit=1,
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["normalized_input"], "USA-NWSFZ-AKZ317")
        self.assertEqual(payload["resolved_loc_id"], "USA-AK-282")
        self.assertEqual(payload["matches"][0]["source"]["family"], "overlay_nws_fire_weather_zone")

    def test_loc_id_references_returns_reverse_sidechain_overlaps(self) -> None:
        payload = loc_id_references(
            "USA-PR-001",
            systems=["zcta"],
            target_admin_level="admin_2",
            limit_per_system=2,
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["loc_id"], "USA-PR-001")
        values = {item["value"] for item in payload["references"]}
        self.assertIn("USA-PR-001", values)
        self.assertIn("USA-Z-00601", values)

    def test_loc_id_references_exposes_accepted_legacy_geometry_aliases(self) -> None:
        payload = loc_id_references("USA-VA-059", target_admin_level="admin_2", limit_per_system=1)

        self.assertTrue(payload["ok"])
        aliases = {
            item["value"]
            for item in payload["references"]
            if item["system"] == "legacy_admin_geometry"
        }
        self.assertIn("USA-G125186-G282830", aliases)

    def test_convert_reference_composes_through_loc_id(self) -> None:
        payload = convert_reference(
            from_system="zip",
            value="00601",
            to_system="nws_fire",
            target_admin_level="admin_2",
            limit=2,
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["loc_id"], "USA-PR-001")
        self.assertTrue(payload["results"])
        self.assertEqual(payload["results"][0]["system"], "overlay_nws_fire_weather_zone")

    def test_convert_reference_without_target_results_is_not_success(self) -> None:
        payload = convert_reference(
            from_system="zip",
            value="10001",
            to_system="huc",
            target_admin_level="admin_2",
            limit=2,
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["to_system"], "huc")
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["error"]["code"], "unsupported_target_system")

    def test_unknown_bridge_system_returns_clean_error(self) -> None:
        payload = resolve_reference(
            from_system="huc",
            value="01080201",
            target_admin_level="admin_2",
        )

        self.assertFalse(payload["ok"])
        self.assertIn("no bridge artifact", payload["error"])

    def test_historical_country_resolution_is_time_scoped(self) -> None:
        in_2000 = resolve_reference(from_system="iso3166_3", value="YUG", as_of="2000")
        in_2025 = resolve_reference(from_system="historical_country", value="Yugoslavia", as_of="2025")

        self.assertEqual(in_2000["resolved_loc_id"], "HIST-YUG-FRY")
        self.assertTrue(in_2000["valid_at_requested_time"])
        self.assertFalse(in_2025["valid_at_requested_time"])
        self.assertEqual(
            {item["loc_id"] for item in in_2025["lifecycle"]["present_day_descendants"]},
            {"SRB", "MNE"},
        )

    def test_cloud_mode_keeps_catalog_bridge_artifacts_without_local_file(self) -> None:
        artifact = {
            "status": "complete",
            "source_family": "overlay_zcta",
            "target_admin_level": "admin_2",
            "artifact_path": "published/geometry/bridges/overlay_zcta_to_admin_2_USA.parquet",
            "row_count": 10,
            "bridge_vintage": "usa_geometry_current",
        }
        with (
            mock.patch("mapmover.runtime.reference_exchange.load_geometry_catalog", return_value={"bridge_artifacts": [artifact]}),
            mock.patch("mapmover.runtime.reference_exchange.is_cloud_mode", return_value=True),
        ):
            artifacts = reference_exchange._bridge_artifacts(
                source_family="zip",
                target_admin_level="admin_2",
                iso3="USA",
            )

        self.assertEqual(artifacts, [artifact])


class ReferenceExchangeRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(geometry_router)
        self.hosted_client = TestClient(app)
        self.local_client = TestClient(app, client=("127.0.0.1", 50000))

    def test_internal_reference_routes_deny_hosted_anonymous_as_json(self) -> None:
        response = self.hosted_client.get("/api/internal/reference/systems")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"ok": False, "error": "Unauthorized"})

    def test_internal_reference_resolve_route_accepts_local_loopback(self) -> None:
        response = self.local_client.post(
            "/api/internal/reference/resolve",
            json={
                "from_system": "zip",
                "value": "00601",
                "target_admin_level": "admin_2",
                "limit": 1,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["resolved_loc_id"], "USA-PR-001")

    def test_internal_reference_convert_route_accepts_local_loopback(self) -> None:
        response = self.local_client.post(
            "/api/internal/reference/convert",
            json={
                "from_system": "nws_fire",
                "value": "AKZ317",
                "to_system": "zcta",
                "target_admin_level": "admin_2",
                "limit": 2,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["loc_id"], "USA-AK-282")

    def test_internal_compare_route_accepts_local_loopback(self) -> None:
        expected = {"ok": True, "spatial_relation": "overlaps", "left_area_share": 0.2, "right_area_share": 0.1}
        with mock.patch("mapmover.routes.geometry.compare_geographies", return_value=expected) as compare_mock:
            response = self.local_client.post(
                "/api/internal/reference/compare",
                json={"left_loc_id": "USA-Z-90001", "right_loc_id": "USA-TRIBAL-1823", "as_of": "2025"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        compare_mock.assert_called_once_with(
            "USA-Z-90001",
            "USA-TRIBAL-1823",
            as_of="2025",
            left_as_of=None,
            right_as_of=None,
            include_successors=True,
        )


if __name__ == "__main__":
    unittest.main()
