from __future__ import annotations

import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import app, _classify_route_surface


class PublicDiscoveryCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_four_public_catalog_routes_are_json_discovery(self) -> None:
        with mock.patch(
            "mapmover.routes.system._build_public_pack_list",
            return_value=[{"pack_id": "demo", "title": "Demo"}],
        ), mock.patch(
            "mapmover.routes.system._build_geometry_catalog_payload",
            return_value={"catalog_family": "geometry", "bank_count": 1},
        ), mock.patch(
            "mapmover.routes.system._build_live_feed_catalog_payload",
            return_value={"catalog_family": "live_feeds", "feed_count": 1},
        ), mock.patch(
            "mapmover.data_loading.load_api_catalog",
            return_value={"catalog_version": "1.0", "packs": [{"pack_id": "demo"}]},
        ), mock.patch(
            "pack_registry_shared.tool_family_ids",
            return_value=(),
        ):
            historical = self.client.get("/api/v1/historical/catalog")
            geometry = self.client.get("/api/v1/geometry/catalog")
            feeds = self.client.get("/api/v1/feeds/catalog")
            agent = self.client.get("/api/v1/agent/catalog")
            legacy_agent = self.client.get("/api/v1/catalog")

        self.assertEqual(historical.status_code, 200)
        self.assertEqual(historical.json()["catalog_family"], "historical_packs")
        self.assertEqual(historical.json()["pack_count"], 1)

        self.assertEqual(geometry.status_code, 200)
        self.assertEqual(geometry.json()["catalog_family"], "geometry")

        self.assertEqual(feeds.status_code, 200)
        self.assertEqual(feeds.json()["catalog_family"], "live_feeds")

        self.assertEqual(agent.status_code, 200)
        self.assertEqual(agent.json()["packs"][0]["pack_id"], "demo")
        self.assertEqual(legacy_agent.json(), agent.json())

    def test_catalog_routes_share_discovery_rate_limit_surface(self) -> None:
        for path in (
            "/api/v1/catalog",
            "/api/v1/agent/catalog",
            "/api/v1/historical/catalog",
            "/api/v1/geometry/catalog",
            "/api/v1/feeds/catalog",
        ):
            self.assertEqual(_classify_route_surface(path), "agent_api_discovery")


if __name__ == "__main__":
    unittest.main()
