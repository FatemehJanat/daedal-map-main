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
        self.assertEqual(
            historical.json()["download_url"],
            "https://downloads.daedalmap.com/downloadable/catalog.json",
        )

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

    def test_artifact_token_bypasses_shared_mcp_surface_rate_limit(self) -> None:
        token = "qa-surface-rate-token"
        with (
            mock.patch.dict(os.environ, {"ARTIFACT_ACCESS_TOKENS": f"qa={token}"}, clear=False),
            mock.patch("app.rate_limiter.check", return_value=(False, 60)) as limiter_mock,
        ):
            response = self.client.post(
                "/mcp/geography",
                headers={"Authorization": f"Bearer {token}"},
                json={"jsonrpc": "2.0", "id": "qa-rate", "method": "tools/list", "params": {}},
            )
        self.assertEqual(response.status_code, 200)
        limiter_mock.assert_not_called()

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
        self.assertFalse(bulk_mock.call_args.kwargs["include_geometry"])
        self.assertIsNone(bulk_mock.call_args.kwargs["target_admin_level"])

    def test_point_lookup_batch_endpoint_records_onboarding_context(self) -> None:
        def fake_resolve(points, include_geometry=False, **_kwargs):
            return [{"matched": {"loc_id": f"TEST-{point['row_index']}"}} for point in points]

        with mock.patch(
            "mapmover.routes.geometry.resolve_points_to_locations",
            side_effect=fake_resolve,
        ), mock.patch(
            "mapmover.routes.geometry.log_api_query_event",
        ) as analytics_mock:
            response = self.client.post(
                "/api/v1/resolve/points",
                json={
                    "source": "try_dataset",
                    "batch_id": "test-onboarding-1",
                    "identity_role": "location",
                    "session_id": "tds-abc",
                    "dataset_id": "tdd-def",
                    "input_method": "upload",
                    "points": [{"row_index": 0, "lon": -123.1, "lat": 49.2}],
                },
            )

        self.assertEqual(response.status_code, 200)
        metadata = analytics_mock.call_args.kwargs["metadata"]
        self.assertEqual(metadata["identity_role"], "location")
        self.assertEqual(metadata["session_id"], "tds-abc")
        self.assertEqual(metadata["dataset_id"], "tdd-def")
        self.assertEqual(metadata["input_method"], "upload")

    def test_point_lookup_batch_endpoint_omits_absent_onboarding_context(self) -> None:
        def fake_resolve(points, include_geometry=False, **_kwargs):
            return [{"matched": {"loc_id": "TEST-0"}} for _ in points]

        with mock.patch(
            "mapmover.routes.geometry.resolve_points_to_locations",
            side_effect=fake_resolve,
        ), mock.patch(
            "mapmover.routes.geometry.log_api_query_event",
        ) as analytics_mock:
            response = self.client.post(
                "/api/v1/resolve/points",
                json={"source": "agent", "points": [{"row_index": 0, "lon": 0, "lat": 0}]},
            )

        self.assertEqual(response.status_code, 200)
        metadata = analytics_mock.call_args.kwargs["metadata"]
        self.assertIsNone(metadata["identity_role"])
        self.assertIsNone(metadata["session_id"])

    def test_point_lookup_batch_endpoint_challenges_over_free_limit(self) -> None:
        with mock.patch("mapmover.routes.geometry.log_api_query_event") as analytics_mock:
            response = self.client.post(
                "/api/v1/resolve/points",
                json={"source": "try_dataset", "batch_id": "too-many", "country_scope": "USA", "target_admin_level": "admin_2", "points": [{"lon": 0, "lat": 0} for _ in range(26)]},
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

    def test_point_lookup_verified_account_gets_included_bulk(self) -> None:
        def fake_resolve(points, include_geometry=False, **_kwargs):
            return [{"matched": {"loc_id": "USA-CA-037", "admin_level": 2}} for _ in points]

        with (
            mock.patch("app.get_authenticated_user_async", return_value={"id": "user-1"}),
            mock.patch("mapmover.routes.geometry.resolve_points_to_locations", side_effect=fake_resolve),
            mock.patch("mapmover.routes.geometry.log_api_query_event") as analytics_mock,
        ):
            response = self.client.post(
                "/api/v1/resolve/points",
                headers={"Authorization": "Bearer account-session-test"},
                json={"source": "try_dataset", "country_scope": "USA", "target_admin_level": "admin_2", "points": [{"lon": -118.2, "lat": 34.0} for _ in range(26)]},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(analytics_mock.call_args.kwargs["metadata"]["included_account_bulk"])
        self.assertEqual(analytics_mock.call_args.kwargs["auth_user_id"], "user-1")

    def test_mcp_verified_account_gets_same_included_bulk(self) -> None:
        def fake_resolve(points, include_geometry=False, **_kwargs):
            return [{"matched": {"loc_id": "USA-CA-037", "admin_level": 2, "iso3": "USA"}, "stack": [{"loc_id": "USA"}, {"loc_id": "USA-CA-037"}]} for _ in points]

        with (
            mock.patch("app.get_authenticated_user_async", return_value={"id": "user-mcp"}),
            mock.patch("mapmover.routes.mcp.rate_limiter.check", return_value=(True, 0)),
            mock.patch("mapmover.routes.mcp._commercial_access_decision") as verifier_mock,
            mock.patch("mapmover.geometry_handlers.resolve_points_to_locations", side_effect=fake_resolve),
            mock.patch("mapmover.routes.mcp.log_api_query_event"),
        ):
            response = self.client.post(
                "/mcp/geography",
                headers={"Authorization": "Bearer account-mcp-test"},
                json={"jsonrpc": "2.0", "id": "account-bulk", "method": "tools/call", "params": {"name": "resolve_point", "arguments": {"country_scope": "USA", "target_admin_level": "admin_2", "points": [{"lon": -118.2, "lat": 34.0} for _ in range(26)]}}},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()["result"]["structuredContent"]
        self.assertEqual(payload["resolved_count"], 26)
        verifier_mock.assert_not_called()

    def test_rest_global_admin_0_preset_sets_bounded_resolver_plan(self) -> None:
        def fake_resolve(points, include_geometry=False, **_kwargs):
            return [{"matched": {"loc_id": "USA", "admin_level": 0}} for _ in points]

        with (
            mock.patch("app.get_authenticated_user_async", return_value={"id": "user-global"}),
            mock.patch("mapmover.routes.geometry.resolve_points_to_locations", side_effect=fake_resolve) as resolver_mock,
            mock.patch("mapmover.routes.geometry.log_api_query_event"),
        ):
            response = self.client.post(
                "/api/v1/resolve/points",
                headers={"Authorization": "Bearer account-global-test"},
                json={"source": "try_dataset", "bulk_preset": "global_admin_0", "points": [{"lon": -118.2, "lat": 34.0} for _ in range(26)]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["bulk_preset"], "global_admin_0")
        self.assertEqual(resolver_mock.call_args.kwargs["target_admin_level"], 0)
        self.assertIsNone(resolver_mock.call_args.kwargs["country_scope"])

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
                        json={"source": "try_dataset", "batch_id": "trusted-50", "country_scope": "USA", "target_admin_level": "admin_2", "points": [{"lon": 0, "lat": 0, "row_index": index} for index in range(50)]},
                    )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["point_count"], 50)
        self.assertEqual(body["resolved_count"], 50)
        bulk_mock.assert_called_once()
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
