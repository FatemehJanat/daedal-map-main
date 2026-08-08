from __future__ import annotations

import unittest
import io
import json
import os
from unittest import mock

from fastapi.testclient import TestClient

from app import app, _classify_route_surface, _rate_limit_config_for_surface
from mapmover.runtime import geometry_catalog


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

    def test_point_lookup_routes_have_dedicated_rate_limit_surface(self) -> None:
        self.assertEqual(_classify_route_surface("/geometry/resolve-point"), "point_lookup")
        self.assertEqual(_classify_route_surface("/api/v1/resolve/point"), "point_lookup")
        self.assertEqual(_classify_route_surface("/api/v1/resolve/points"), "point_lookup")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_rate_limit_config_for_surface("point_lookup"), (25, 60))

    def test_point_lookup_batch_endpoint_returns_one_bulk_payload(self) -> None:
        def fake_resolve(points, include_geometry=False, **_kwargs):
            return [
                {
                    "deepest_resolved_loc_id": f"TEST-{point['lat']}-{point['lon']}",
                    "matched": {"loc_id": f"TEST-{point['lat']}-{point['lon']}"},
                }
                for point in points
            ]

        with mock.patch(
            "mapmover.routes.geometry.resolve_points_to_locations",
            side_effect=fake_resolve,
        ) as bulk_mock, mock.patch(
            "mapmover.routes.geometry.log_api_query_event",
        ):
            response = self.client.post(
                "/api/v1/resolve/points",
                json={
                    "source": "try_dataset",
                    "batch_id": "test-bulk-2",
                    "points": [
                        {"row_index": 10, "lon": -123.1, "lat": 49.2},
                        {"row_index": 11, "lon": -122.9, "lat": 49.1},
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["batch_id"], "test-bulk-2")
        self.assertEqual(payload["point_count"], 2)
        self.assertEqual(payload["resolved_count"], 2)
        self.assertEqual(payload["results"][0]["row_index"], 10)
        bulk_mock.assert_called_once()

    def test_point_lookup_batch_endpoint_challenges_over_free_limit(self) -> None:
        with mock.patch("mapmover.routes.geometry.log_api_query_event") as analytics_mock:
            response = self.client.post(
                "/api/v1/resolve/points",
                json={"source": "try_dataset", "batch_id": "too-many", "parent_loc_id": "USA", "target_admin_level": "admin_2", "points": [{"lon": 0, "lat": 0} for _ in range(26)]},
            )

        self.assertEqual(response.status_code, 402)
        body = response.json()
        self.assertTrue(body["payment_required"])
        self.assertEqual(body["limits"]["free_batch_limit"], 25)
        self.assertEqual(body["quote"]["payment_rails"], ["account_credit", "x402"])
        analytics = analytics_mock.call_args.kwargs
        self.assertEqual(analytics["decision"], "challenge")
        self.assertEqual(analytics["source_id"], "resolve_points")
        self.assertEqual(analytics["capability_id"], "point_lookup_batch")
        self.assertEqual(analytics["error_code"], "payment_required")
        self.assertEqual(analytics["row_count"], 26)
        self.assertEqual(analytics["metadata"]["surface"], "test_data")

    def test_point_lookup_batch_endpoint_trusted_token_executes_over_free_limit(self) -> None:
        def fake_resolve(points, include_geometry=False, **_kwargs):
            return [
                {
                    "matched": {"loc_id": f"TEST-{point['row_index']}", "admin_level": 2},
                    "target_admin_level": "admin_2",
                    "deeper_available": False,
                    "available_deeper_admin_levels": [],
                }
                for point in points
            ]

        with mock.patch.dict("os.environ", {"ARTIFACT_ACCESS_TOKENS": "tok_test_bypass"}):
            with mock.patch("mapmover.routes.geometry.resolve_points_to_locations", side_effect=fake_resolve) as bulk_mock:
                with mock.patch("mapmover.routes.geometry.log_api_query_event") as analytics_mock:
                    response = self.client.post(
                        "/api/v1/resolve/points",
                        headers={"Authorization": "Bearer tok_test_bypass"},
                        json={"source": "try_dataset", "batch_id": "trusted-50", "parent_loc_id": "USA", "target_admin_level": "admin_2", "points": [{"lon": 0, "lat": 0, "row_index": index} for index in range(50)]},
                    )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["point_count"], 50)
        self.assertEqual(body["country_scope"], "USA")
        self.assertEqual(body["resolved_count"], 50)
        bulk_mock.assert_called_once()
        self.assertEqual(bulk_mock.call_args.kwargs["country_scope"], "USA")
        analytics = analytics_mock.call_args.kwargs
        self.assertEqual(analytics["decision"], "allow")
        self.assertEqual(analytics["payment_rail"], "trusted_artifact")
        self.assertIsNotNone(analytics["artifact_token_id"])

    def test_geometry_catalog_loads_from_object_store_in_cloud_mode(self) -> None:
        class FakeObjectStore:
            def get_object(self, **kwargs):
                self.kwargs = kwargs
                return {
                    "Body": io.BytesIO(json.dumps({
                        "schema_version": 1,
                        "geometry_banks": [{"bank_id": "cloud_bank"}],
                    }).encode("utf-8"))
                }

        store = FakeObjectStore()
        geometry_catalog.clear_geometry_catalog_cache()
        with mock.patch.dict(os.environ, {"S3_BUCKET": "test-bucket", "S3_PREFIX": "published"}, clear=False):
            with mock.patch(
                "mapmover.runtime.geometry_catalog.get_runtime_config",
                return_value={"runtime_mode": "cloud", "cloud": {"bucket": "test-bucket", "prefix": "published"}},
            ), mock.patch(
                "boto3.client",
                return_value=store,
            ):
                payload = geometry_catalog.load_geometry_catalog()

        self.assertEqual(payload["geometry_banks"][0]["bank_id"], "cloud_bank")
        self.assertEqual(store.kwargs["Bucket"], "test-bucket")
        self.assertEqual(store.kwargs["Key"], "published/geometry/geometry_catalog.json")
        geometry_catalog.clear_geometry_catalog_cache()

    def test_geometry_catalog_exposes_country_admin_spine_depth(self) -> None:
        response = self.client.get("/api/v1/geometry/catalog")

        self.assertEqual(response.status_code, 200)
        coverage = {
            item["country_code"]: item
            for item in response.json().get("admin_spine_coverage") or []
        }
        self.assertEqual(coverage["AUS"]["max_admin_level"], "admin_6")
        self.assertEqual(coverage["CAN"]["max_admin_level"], "admin_5")
        self.assertEqual(coverage["BRA"]["max_admin_level"], "admin_5")
        self.assertIn("admin_6", coverage["AUS"]["strict_nested_levels"])


if __name__ == "__main__":
    unittest.main()
