from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mapmover.routes.geometry import router as geometry_router
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

    def test_unknown_bridge_system_returns_clean_error(self) -> None:
        payload = resolve_reference(
            from_system="huc",
            value="01080201",
            target_admin_level="admin_2",
        )

        self.assertFalse(payload["ok"])
        self.assertIn("no bridge artifact", payload["error"])


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


if __name__ == "__main__":
    unittest.main()
