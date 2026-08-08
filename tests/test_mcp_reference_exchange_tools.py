from __future__ import annotations

import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mapmover.runtime.reference_exchange import get_geometry_availability
from mapmover.routes.mcp import _tool_rate_limit_for_tier, router as mcp_router


def _mcp_call(client: TestClient, method: str, params: dict | None = None, *, path: str = "/mcp/geography", headers: dict | None = None) -> dict:
    response = client.post(
        path,
        headers=headers or {},
        json={"jsonrpc": "2.0", "id": "test-1", "method": method, "params": params or {}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _tool_call(client: TestClient, name: str, arguments: dict | None = None, *, path: str = "/mcp/geography", headers: dict | None = None) -> dict:
    envelope = _mcp_call(
        client,
        "tools/call",
        {"name": name, "arguments": arguments or {}},
        path=path,
        headers=headers,
    )
    return envelope["result"]["structuredContent"]


class McpReferenceExchangeToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(mcp_router)
        self.client = TestClient(app)

    def test_geography_facade_lists_reference_exchange_tools_first_class(self) -> None:
        envelope = _mcp_call(self.client, "tools/list")
        tool_names = {tool["name"] for tool in envelope["result"]["tools"]}

        self.assertIn("list_reference_systems", tool_names)
        self.assertIn("read_geometry_catalog", tool_names)
        self.assertIn("resolve_reference", tool_names)
        self.assertIn("convert_reference", tool_names)
        self.assertIn("check_geometry", tool_names)
        self.assertIn("get_geometry", tool_names)
        self.assertIn("resolve_point", tool_names)
        self.assertIn("loc_id_info", tool_names)
        self.assertIn("resolve_loc_id_scope", tool_names)
        self.assertIn("estimate_geometry_package", tool_names)
        self.assertIn("create_geometry_export", tool_names)
        self.assertIn("estimate_conversion_job", tool_names)
        self.assertIn("create_conversion_job", tool_names)
        self.assertIn("get_job_status", tool_names)
        self.assertNotIn("check_geometries", tool_names)
        self.assertNotIn("resolve_points", tool_names)
        self.assertNotIn("loc_id_references", tool_names)
        self.assertNotIn("get_boundary", tool_names)
        self.assertNotIn("loc_id_hierarchy", tool_names)
        self.assertNotIn("sidechain_to_admin", tool_names)
        self.assertNotIn("admin_to_sidechain", tool_names)

    def test_reverse_geocoding_facade_lists_multipurpose_point_tool(self) -> None:
        envelope = _mcp_call(self.client, "tools/list", path="/mcp/reverse-geocoding")
        tool_names = {tool["name"] for tool in envelope["result"]["tools"]}

        self.assertIn("resolve_point", tool_names)
        self.assertNotIn("resolve_points", tool_names)
        self.assertNotIn("get_boundary", tool_names)

    def test_boundaries_facade_lists_geometry_preflight_tools(self) -> None:
        envelope = _mcp_call(self.client, "tools/list", path="/mcp/boundaries")
        tool_names = {tool["name"] for tool in envelope["result"]["tools"]}

        self.assertIn("check_geometry", tool_names)
        self.assertNotIn("check_geometries", tool_names)
        self.assertIn("get_geometry", tool_names)
        self.assertNotIn("get_boundary", tool_names)
        self.assertNotIn("resolve_points", tool_names)
        self.assertIn("resolve_loc_id_scope", tool_names)
        self.assertIn("estimate_geometry_package", tool_names)
        self.assertIn("create_geometry_export", tool_names)
        self.assertIn("get_job_status", tool_names)

    def test_resolve_point_tool_accepts_point_batch(self) -> None:
        def fake_resolve(points, include_geometry=False, **_kwargs):
            return [
                {
                    "point": {"lon": point["lon"], "lat": point["lat"]},
                    "matched": {"loc_id": f"TEST-{point['lat']}-{point['lon']}", "iso3": "USA"},
                    "deepest_resolved_loc_id": f"TEST-{point['lat']}-{point['lon']}",
                    "deepest_resolved_admin_level": "admin_2",
                    "stack": [{"loc_id": "USA"}, {"loc_id": f"TEST-{point['lat']}-{point['lon']}"}],
                    "target_admin_level": "admin_2",
                    "deeper_available": True,
                    "available_deeper_admin_levels": ["admin_3"],
                }
                for point in points
            ]

        with (
            mock.patch("mapmover.geometry_handlers.resolve_points_to_locations", side_effect=fake_resolve) as bulk_mock,
            mock.patch("mapmover.routes.mcp.log_api_query_event") as analytics_mock,
        ):
            payload = _tool_call(
                self.client,
                "resolve_point",
                {
                    "request_id": "mcp-bulk-test",
                    "batch_id": "batch-1",
                    "points": [
                        {"row_index": 10, "lon": -123.1, "lat": 49.2},
                        {"row_index": 11, "lon": -122.9, "lat": 49.1},
                    ],
                },
            )

        self.assertEqual(payload["batch_id"], "batch-1")
        bulk_mock.assert_called_once()
        self.assertEqual(payload["point_count"], 2)
        self.assertEqual(payload["resolved_count"], 2)
        self.assertEqual(payload["results"][0]["row_index"], 10)
        self.assertEqual(payload["results"][0]["deepest_resolved_loc_id"], "TEST-49.2--123.1")
        self.assertTrue(payload["results"][0]["deeper_available"])
        self.assertEqual(payload["results"][0]["available_deeper_admin_levels"], ["admin_3"])
        analytics = analytics_mock.call_args.kwargs
        self.assertEqual(analytics["capability_id"], "point_lookup")
        self.assertEqual(analytics["pack_id"], "geography_tools")
        self.assertEqual(analytics["source_id"], "resolve_point")
        self.assertEqual(analytics["decision"], "allow")
        self.assertEqual(analytics["payment_rail"], "free_preview")
        self.assertEqual(analytics["row_count"], 2)
        self.assertEqual(analytics["query_granularity"], "bulk_2")
        self.assertEqual(analytics["metadata"]["surface"], "agent_api_mcp")
        self.assertEqual(analytics["metadata"]["event"], "point_lookup")
        self.assertEqual(analytics["metadata"]["tool_mode"], "bulk")
        self.assertEqual(analytics["metadata"]["quantity"], 2)
        self.assertEqual(analytics["metadata"]["batch_id"], "batch-1")
        self.assertEqual(analytics["metadata"]["compute"]["input_count"], 2)
        self.assertEqual(analytics["metadata"]["compute"]["output_count"], 2)
        self.assertIn("point_resolver_ms", analytics["metadata"]["compute"]["stage_ms"])

    def test_resolve_point_tool_challenges_point_batch_over_free_limit(self) -> None:
        with mock.patch("mapmover.routes.mcp.log_api_query_event") as analytics_mock:
            payload = _tool_call(
                self.client,
                "resolve_point",
                {"points": [{"lon": 0, "lat": 0} for _ in range(26)]},
            )

        self.assertTrue(payload["payment_required"])
        self.assertEqual(payload["limits"]["free_batch_limit"], 25)
        self.assertEqual(payload["error"]["code"], "payment_required")
        self.assertEqual(payload["quote"]["payment_rails"], ["account_credit", "x402"])
        analytics = analytics_mock.call_args.kwargs
        self.assertEqual(analytics["decision"], "challenge")
        self.assertEqual(analytics["payment_rail"], "commercial_access")

    def test_resolve_point_tool_trusted_token_executes_over_free_limit(self) -> None:
        def fake_resolve(points, include_geometry=False, **_kwargs):
            return [
                {
                    "point": {"lon": point["lon"], "lat": point["lat"]},
                    "matched": {"loc_id": f"TEST-{point['row_index']}", "admin_level": 2, "iso3": "USA"},
                    "stack": [{"loc_id": "USA"}, {"loc_id": f"TEST-{point['row_index']}"}],
                    "target_admin_level": "admin_2",
                    "deeper_available": False,
                    "available_deeper_admin_levels": [],
                }
                for point in points
            ]

        with mock.patch.dict("os.environ", {"ARTIFACT_ACCESS_TOKENS": "tok_test_bypass"}):
            with (
                mock.patch("mapmover.geometry_handlers.resolve_points_to_locations", side_effect=fake_resolve) as bulk_mock,
                mock.patch("mapmover.routes.mcp.log_api_query_event") as analytics_mock,
            ):
                payload = _tool_call(
                    self.client,
                    "resolve_point",
                    {"points": [{"lon": 0, "lat": 0, "row_index": index} for index in range(50)]},
                    headers={"Authorization": "Bearer tok_test_bypass"},
                )

        self.assertEqual(payload["point_count"], 50)
        self.assertEqual(payload["resolved_count"], 50)
        bulk_mock.assert_called_once()
        analytics = analytics_mock.call_args.kwargs
        self.assertEqual(analytics["decision"], "allow")
        self.assertEqual(analytics["payment_rail"], "trusted_artifact")
        self.assertIsNotNone(analytics["artifact_token_id"])

    def test_resolve_point_tool_uses_per_tool_batch_limit_override(self) -> None:
        with mock.patch.dict("os.environ", {"MCP_TOOL_BATCH_LIMIT_RESOLVE_POINT": "2"}):
            with mock.patch("mapmover.routes.mcp.log_api_query_event"):
                payload = _tool_call(
                    self.client,
                    "resolve_point",
                    {"points": [{"lon": 0, "lat": 0} for _ in range(3)]},
                )

        self.assertEqual(payload["limits"]["free_batch_limit"], 2)
        self.assertEqual(payload["error"]["code"], "payment_required")

    def test_check_geometry_tool_accepts_loc_id_batch(self) -> None:
        with (
            mock.patch(
                "mapmover.runtime.reference_exchange.get_geometry_availability",
                return_value={
                    "ok": True,
                    "requested": 3,
                    "available": 2,
                    "missing": 1,
                    "items": [
                        {"loc_id": "USA-CA-037", "has_shape": True},
                        {"loc_id": "USA-CA-075", "has_shape": True},
                        {"loc_id": "USA-NOPE", "has_shape": False, "error": "no geometry found"},
                    ],
                    "results": [
                        {"loc_id": "USA-CA-037", "has_shape": True},
                        {"loc_id": "USA-CA-075", "has_shape": True},
                        {"loc_id": "USA-NOPE", "has_shape": False, "error": "no geometry found"},
                    ],
                },
            ),
            mock.patch("mapmover.routes.mcp.log_api_query_event") as analytics_mock,
        ):
            payload = _tool_call(
                self.client,
                "check_geometry",
                {"batch_id": "shapes-1", "loc_ids": ["USA-CA-037", "USA-CA-075", "USA-NOPE"]},
            )

        self.assertEqual(payload["batch_id"], "shapes-1")
        self.assertEqual(payload["requested"], 3)
        self.assertEqual(payload["available"], 2)
        self.assertEqual(payload["missing"], 1)
        self.assertEqual(payload["items"][2]["has_shape"], False)
        analytics = analytics_mock.call_args.kwargs
        self.assertEqual(analytics["capability_id"], "geometry_availability")
        self.assertEqual(analytics["pack_id"], "geography_tools")
        self.assertEqual(analytics["source_id"], "check_geometry")
        self.assertEqual(analytics["decision"], "allow")
        self.assertEqual(analytics["payment_rail"], "free_preview")
        self.assertEqual(analytics["row_count"], 3)
        self.assertEqual(analytics["query_granularity"], "bulk_3")
        self.assertEqual(analytics["metadata"]["event"], "geometry_availability")
        self.assertEqual(analytics["metadata"]["tool_mode"], "bulk")
        self.assertEqual(analytics["metadata"]["quantity"], 3)
        self.assertEqual(analytics["metadata"]["available_count"], 2)
        self.assertEqual(analytics["metadata"]["missing_count"], 1)
        self.assertEqual(analytics["metadata"]["compute"]["input_count"], 3)
        self.assertEqual(analytics["metadata"]["compute"]["output_count"], 2)
        self.assertIn("geometry_availability_ms", analytics["metadata"]["compute"]["stage_ms"])

    def test_geometry_availability_uses_metadata_only_fetch(self) -> None:
        metadata_rows = [
                {
                    "loc_id": "USA-CA-037",
                    "name": "Los Angeles County",
                    "admin_level": 2,
                    "centroid_lon": -118.25,
                    "centroid_lat": 34.05,
                    "bbox_min_lon": -119.0,
                    "bbox_min_lat": 33.0,
                    "bbox_max_lon": -117.0,
                    "bbox_max_lat": 35.0,
                }
        ]
        with (
            mock.patch("mapmover.runtime.reference_exchange.get_selection_geometry_metadata", return_value=metadata_rows) as metadata_mock,
            mock.patch("mapmover.runtime.reference_exchange.get_selection_geometries") as geometry_mock,
        ):
            payload = get_geometry_availability(["USA-CA-037", "USA-NOPE"])

        metadata_mock.assert_called_once_with(["USA-CA-037", "USA-NOPE"])
        geometry_mock.assert_not_called()
        self.assertEqual(payload["requested"], 2)
        self.assertEqual(payload["available"], 1)
        self.assertEqual(payload["missing"], 1)
        self.assertEqual(payload["items"][0]["has_shape"], True)
        self.assertEqual(payload["items"][1]["has_shape"], False)

    def test_check_geometry_tool_uses_per_tool_batch_limit_override(self) -> None:
        with mock.patch.dict("os.environ", {"MCP_TOOL_BATCH_LIMIT_CHECK_GEOMETRY": "2"}):
            with mock.patch("mapmover.routes.mcp.log_api_query_event"):
                payload = _tool_call(
                    self.client,
                    "check_geometry",
                    {"loc_ids": ["USA", "CAN", "MEX"]},
                )

        self.assertEqual(payload["limit"], 2)
        self.assertEqual(payload["error"]["code"], "too_many_loc_ids")

    def test_get_geometry_tool_accepts_loc_id_batch(self) -> None:
        with (
            mock.patch(
                "mapmover.runtime.reference_exchange.get_geometry_references",
                return_value={
                    "ok": True,
                    "requested": 2,
                    "items": [
                        {"ok": True, "loc_id": "USA-CA-037", "bbox": [-119, 33, -117, 35]},
                        {"ok": False, "loc_id": "USA-NOPE", "error": {"code": "not_found"}},
                    ],
                },
            ) as geometry_mock,
            mock.patch("mapmover.routes.mcp.log_api_query_event") as analytics_mock,
        ):
            payload = _tool_call(
                self.client,
                "get_geometry",
                {"batch_id": "geo-1", "loc_ids": ["USA-CA-037", "USA-NOPE"]},
            )

        geometry_mock.assert_called_once_with(["USA-CA-037", "USA-NOPE"], include_polygon=False, include_info=True)
        self.assertEqual(payload["batch_id"], "geo-1")
        self.assertEqual(payload["requested"], 2)
        self.assertEqual(payload["items"][0]["loc_id"], "USA-CA-037")
        analytics = analytics_mock.call_args.kwargs
        self.assertEqual(analytics["source_id"], "get_geometry")
        self.assertEqual(analytics["capability_id"], "geometry_lookup")
        self.assertEqual(analytics["row_count"], 2)
        self.assertEqual(analytics["query_granularity"], "bulk_2")
        self.assertEqual(analytics["metadata"]["tool_mode"], "bulk")
        self.assertEqual(analytics["metadata"]["quantity"], 2)
        self.assertEqual(analytics["metadata"]["compute"]["input_count"], 2)
        self.assertEqual(analytics["metadata"]["compute"]["output_count"], 1)
        self.assertEqual(analytics["metadata"]["compute"]["include_polygon"], False)
        self.assertIn("geometry_fetch_ms", analytics["metadata"]["compute"]["stage_ms"])

    def test_loc_id_info_can_include_references(self) -> None:
        with (
            mock.patch(
                "mapmover.geometry_handlers.get_location_info",
                return_value={
                    "loc_id": "USA-AK-282",
                    "name": "Yakutat",
                    "admin_level": 2,
                    "parent_id": "USA-AK",
                    "family": "admin",
                    "iso3": "USA",
                    "centroid": {"lon": -140, "lat": 59},
                    "bbox": [-142, 58, -138, 60],
                    "children_count": 0,
                    "children_by_level": "{}",
                    "descendants_count": 0,
                },
            ),
            mock.patch(
                "mapmover.runtime.reference_exchange.loc_id_references",
                return_value={"ok": True, "references": [{"system": "overlay_nws_fire_weather_zone", "value": "USA-NWSFZ-AKZ317"}]},
            ) as references_mock,
        ):
            payload = _tool_call(
                self.client,
                "loc_id_info",
                {"loc_id": "USA-AK-282", "include_references": True, "systems": ["nws_fire"]},
            )

        references_mock.assert_called_once()
        self.assertEqual(payload["loc_id"], "USA-AK-282")
        self.assertEqual(payload["reference_count"], 1)
        self.assertEqual(payload["references"]["references"][0]["system"], "overlay_nws_fire_weather_zone")

    def test_loc_id_info_references_batch_uses_smaller_guard(self) -> None:
        with (
            mock.patch.dict("os.environ", {"MCP_TOOL_REFERENCES_BATCH_LIMIT_LOC_ID_INFO": "2"}),
            mock.patch("mapmover.routes.mcp.log_api_query_event") as analytics_mock,
        ):
            payload = _tool_call(
                self.client,
                "loc_id_info",
                {
                    "loc_ids": ["USA-CA-037", "USA-NY-061", "USA-AK-282"],
                    "include_references": True,
                },
            )

        self.assertEqual(payload["limit"], 2)
        self.assertEqual(payload["error"]["code"], "too_many_loc_ids_for_references")
        analytics = analytics_mock.call_args.kwargs
        self.assertEqual(analytics["decision"], "deny")
        self.assertEqual(analytics["error_code"], "too_many_loc_ids_for_references")
        self.assertEqual(analytics["metadata"]["batch_limit"], 2)

    def test_tool_rate_limit_uses_per_tool_override(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {
                "MCP_LIVE_TOOL_RATE_LIMIT": "10",
                "MCP_TOOL_RATE_LIMIT_RESOLVE_POINT": "4",
                "MCP_TOOL_RATE_WINDOW_SECONDS_RESOLVE_POINT": "30",
                "MCP_TOOL_RATE_LIMIT_RESOLVE_POINT_PLUS": "40",
            },
        ):
            self.assertEqual(_tool_rate_limit_for_tier("resolve_point", "free"), (4, 30))
            self.assertEqual(_tool_rate_limit_for_tier("resolve_point", "plus"), (40, 30))

    def test_get_pack_geography_prefers_reference_exchange(self) -> None:
        payload = _tool_call(self.client, "get_pack", {"pack_id": "geography"})

        self.assertEqual(payload["routing"]["preferred_tool"], "read_geometry_catalog")
        self.assertEqual(payload["quick_start"]["first_query_template"]["tool"], "read_geometry_catalog")
        starter_tools = set(payload["quick_start"]["starter_tools"])
        self.assertIn("read_geometry_catalog", starter_tools)
        self.assertIn("list_reference_systems", starter_tools)
        self.assertIn("resolve_reference", starter_tools)
        self.assertIn("convert_reference", starter_tools)

    def test_read_geometry_catalog_returns_agent_summary(self) -> None:
        with mock.patch(
            "mapmover.runtime.reference_exchange.load_geometry_catalog",
            return_value={
                "schema_version": "1.0.0",
                "generated_at": "2026-08-03T18:25:18Z",
                "geometry_families": [{"family": "admin_boundary", "label": "Admin", "feature_count": 10}],
                "geometry_assets": [
                    {
                        "asset_id": "global_admin_spine",
                        "label": "Global Admin Spine",
                        "scope": "Global",
                        "family": "admin_base",
                        "feature_count": 10,
                        "has_shapes": True,
                        "admin_coverage": {
                            "min_admin_level": 0,
                            "max_admin_level": 2,
                            "levels": [{"admin_level": "admin_2", "label": "county", "row_count": 10}],
                        },
                    }
                ],
                "bridge_artifacts": [{"source_family": "overlay_zcta", "status": "complete"}],
                "geometry_packages": [],
                "named_geometry_groups": [],
                "named_geometries": [],
            },
        ):
            payload = _tool_call(self.client, "read_geometry_catalog", {"view": "summary"})

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["view"], "summary")
        self.assertEqual(payload["schema_version"], "1.0.0")
        self.assertEqual(payload["counts"]["geometry_assets"], 1)
        self.assertEqual(payload["admin_coverage"][0]["asset_id"], "global_admin_spine")
        self.assertIn("download_url", payload)

    def test_read_geometry_catalog_logs_runtime_analytics(self) -> None:
        with (
            mock.patch(
                "mapmover.runtime.reference_exchange.read_geometry_catalog",
                return_value={
                    "ok": True,
                    "view": "packages",
                    "counts": {"geometry_assets": 3, "geometry_packages": 3, "geometry_banks": 2},
                    "packages": [],
                },
            ),
            mock.patch("mapmover.routes.mcp.log_api_query_event") as analytics_mock,
        ):
            payload = _tool_call(self.client, "read_geometry_catalog", {"view": "packages"})

        self.assertTrue(payload["ok"])
        analytics = analytics_mock.call_args.kwargs
        self.assertEqual(analytics["source_id"], "read_geometry_catalog")
        self.assertEqual(analytics["capability_id"], "geometry_catalog_discovery")
        self.assertEqual(analytics["row_count"], 3)
        self.assertEqual(analytics["metadata"]["event"], "geometry_catalog_discovery")
        self.assertEqual(analytics["metadata"]["view"], "packages")
        self.assertEqual(analytics["metadata"]["compute"]["input_count"], 1)
        self.assertEqual(analytics["metadata"]["compute"]["output_count"], 3)

    def test_list_reference_systems_logs_runtime_analytics(self) -> None:
        with (
            mock.patch(
                "mapmover.runtime.reference_exchange.list_reference_systems",
                return_value={
                    "ok": True,
                    "systems": [{"system": "daedalmap.loc_id"}, {"system": "overlay_zcta"}],
                    "bridges": [],
                },
            ),
            mock.patch("mapmover.routes.mcp.log_api_query_event") as analytics_mock,
        ):
            payload = _tool_call(self.client, "list_reference_systems")

        self.assertTrue(payload["ok"])
        analytics = analytics_mock.call_args.kwargs
        self.assertEqual(analytics["source_id"], "list_reference_systems")
        self.assertEqual(analytics["capability_id"], "reference_system_discovery")
        self.assertEqual(analytics["row_count"], 2)
        self.assertEqual(analytics["metadata"]["event"], "reference_system_discovery")
        self.assertEqual(analytics["metadata"]["system_count"], 2)
        self.assertEqual(analytics["metadata"]["compute"]["input_count"], 1)
        self.assertEqual(analytics["metadata"]["compute"]["output_count"], 2)
        self.assertIn("catalog_lookup_ms", analytics["metadata"]["compute"]["stage_ms"])

    def test_resolve_reference_tool_resolves_zip_to_loc_id(self) -> None:
        payload = _tool_call(
            self.client,
            "resolve_reference",
            {
                "from_system": "zip",
                "value": "00601",
                "target_admin_level": "admin_2",
                "limit": 2,
            },
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["normalized_input"], "USA-Z-00601")
        self.assertEqual(payload["resolved_loc_id"], "USA-PR-001")
        self.assertEqual(payload["match_type"], "bridge_overlap")

    def test_resolve_reference_tool_accepts_item_batch(self) -> None:
        payload = _tool_call(
            self.client,
            "resolve_reference",
            {
                "batch_id": "refs-1",
                "from_system": "zip",
                "target_admin_level": "admin_2",
                "items": [
                    {"row_index": 1, "value": "00601"},
                    {"row_index": 2, "value": "not-a-real-zcta"},
                ],
            },
        )

        self.assertEqual(payload["batch_id"], "refs-1")
        self.assertEqual(payload["item_count"], 2)
        self.assertEqual(payload["results"][0]["row_index"], 1)
        self.assertTrue(payload["results"][0]["ok"])
        self.assertEqual(payload["results"][0]["resolved_loc_id"], "USA-PR-001")
        self.assertEqual(payload["resolved_count"], 1)
        self.assertEqual(payload["unresolved_count"], 1)
        # The real analytics rows carry compute.input_count/output_count and
        # bridge_lookup_ms; other tests assert the shared shape with mocks.

    def test_resolve_reference_tool_uses_per_tool_batch_limit_override(self) -> None:
        with mock.patch.dict("os.environ", {"MCP_TOOL_BATCH_LIMIT_RESOLVE_REFERENCE": "1"}):
            payload = _tool_call(
                self.client,
                "resolve_reference",
                {"from_system": "zip", "items": [{"value": "00601"}, {"value": "00602"}]},
            )

        self.assertEqual(payload["limit"], 1)
        self.assertEqual(payload["error"]["code"], "too_many_items")

    def test_resolve_reference_tool_normalizes_string_error(self) -> None:
        with (
            mock.patch(
                "mapmover.runtime.reference_exchange.resolve_reference",
                return_value={"ok": False, "from_system": "zip", "input": "not-real", "error": "no bridge artifact found"},
            ),
            mock.patch("mapmover.routes.mcp.log_api_query_event") as analytics_mock,
        ):
            payload = _tool_call(
                self.client,
                "resolve_reference",
                {"from_system": "zip", "value": "not-real", "target_admin_level": "admin_2"},
            )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "not_found")
        self.assertEqual(payload["error"]["message"], "no bridge artifact found")
        self.assertEqual(analytics_mock.call_args.kwargs["error_code"], "not_found")

    def test_convert_reference_tool_composes_through_loc_id(self) -> None:
        payload = _tool_call(
            self.client,
            "convert_reference",
            {
                "from_system": "zip",
                "value": "00601",
                "to_system": "nws_fire",
                "target_admin_level": "admin_2",
                "limit": 2,
            },
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["loc_id"], "USA-PR-001")
        self.assertTrue(payload["results"])
        self.assertEqual(payload["results"][0]["system"], "overlay_nws_fire_weather_zone")

    def test_convert_reference_tool_accepts_item_batch(self) -> None:
        payload = _tool_call(
            self.client,
            "convert_reference",
            {
                "batch_id": "conversions-1",
                "from_system": "zip",
                "to_system": "nws_fire",
                "target_admin_level": "admin_2",
                "items": [
                    {"row_index": "a", "value": "00601"},
                    {"row_index": "b", "value": ""},
                ],
            },
        )

        self.assertEqual(payload["batch_id"], "conversions-1")
        self.assertEqual(payload["item_count"], 2)
        self.assertEqual(payload["results"][0]["row_index"], "a")
        self.assertTrue(payload["results"][0]["ok"])
        self.assertEqual(payload["results"][0]["loc_id"], "USA-PR-001")
        self.assertEqual(payload["converted_count"], 1)
        self.assertEqual(payload["unconverted_count"], 1)

    def test_convert_reference_tool_normalizes_string_error(self) -> None:
        with (
            mock.patch(
                "mapmover.runtime.reference_exchange.convert_reference",
                return_value={"ok": False, "from_system": "zip", "input": "not-real", "to_system": "nws_fire", "error": "no bridge artifact found"},
            ),
            mock.patch("mapmover.routes.mcp.log_api_query_event") as analytics_mock,
        ):
            payload = _tool_call(
                self.client,
                "convert_reference",
                {"from_system": "zip", "value": "not-real", "to_system": "nws_fire", "target_admin_level": "admin_2"},
            )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "not_found")
        self.assertEqual(payload["error"]["message"], "no bridge artifact found")
        self.assertEqual(analytics_mock.call_args.kwargs["error_code"], "not_found")

    def test_convert_reference_tool_rejects_empty_target_results(self) -> None:
        with mock.patch("mapmover.routes.mcp.log_api_query_event") as analytics_mock:
            payload = _tool_call(
                self.client,
                "convert_reference",
                {
                    "from_system": "zip",
                    "value": "10001",
                    "to_system": "huc",
                    "target_admin_level": "admin_2",
                    "limit": 2,
                },
            )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "unsupported_target_system")
        self.assertEqual(analytics_mock.call_args.kwargs["decision"], "deny")
        self.assertEqual(analytics_mock.call_args.kwargs["error_code"], "unsupported_target_system")

    def test_resolve_loc_id_scope_uses_geometry_index(self) -> None:
        with (
            mock.patch(
                "mapmover.runtime.geometry_tool_jobs.get_geometry_index",
                return_value={
                    "rows": [
                        {
                            "loc_id": "USA-CA-037",
                            "parent_id": "USA-CA",
                            "admin_level": 2,
                            "name": "Los Angeles County",
                            "bbox_min_lon": -119,
                            "bbox_min_lat": 33,
                            "bbox_max_lon": -117,
                            "bbox_max_lat": 35,
                            "centroid_lon": -118.25,
                            "centroid_lat": 34.05,
                        },
                        {"loc_id": "USA-CA-075", "parent_id": "USA-CA", "admin_level": 2, "name": "San Francisco County"},
                    ],
                    "count": 2,
                },
            ) as index_mock,
            mock.patch("mapmover.routes.mcp.log_api_query_event"),
        ):
            payload = _tool_call(
                self.client,
                "resolve_loc_id_scope",
                {"parent_loc_id": "USA-CA", "admin_level": "admin_2", "limit": 1},
            )

        index_mock.assert_called_once()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["total_count"], 2)
        self.assertEqual(payload["returned_count"], 1)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["loc_ids"], ["USA-CA-037"])

    def test_resolve_loc_id_scope_expands_country_to_counties(self) -> None:
        pd = __import__("pandas")
        base_rows = pd.DataFrame(
            [
                {"loc_id": "USA-MN-001", "parent_id": "USA-MN", "admin_level": 2, "name": "Aitkin County"},
                {"loc_id": "USA-MN-003", "parent_id": "USA-MN", "admin_level": 2, "name": "Anoka County"},
                {"loc_id": "USA-WY-001", "parent_id": "USA-WY", "admin_level": 2, "name": "Albany County"},
            ]
        )

        with (
            mock.patch("mapmover.runtime.geometry_tool_jobs.get_geometry_index", return_value={"rows": [], "count": 0}) as index_mock,
            mock.patch("mapmover.runtime.geometry_tool_jobs.load_country_parquet", return_value=base_rows) as base_mock,
            mock.patch("mapmover.routes.mcp.log_api_query_event"),
        ):
            payload = _tool_call(
                self.client,
                "resolve_loc_id_scope",
                {"parent_loc_id": "USA", "admin_level": "admin_2", "limit": 2},
            )

        index_mock.assert_called_once()
        base_mock.assert_called_once_with("USA", admin_level=2)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["total_count"], 3)
        self.assertEqual(payload["returned_count"], 2)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["loc_ids"], ["USA-MN-001", "USA-MN-003"])

    def test_resolve_loc_id_scope_rejects_unsupported_deep_country_level(self) -> None:
        with (
            mock.patch("mapmover.runtime.geometry_tool_jobs.get_country_supported_deep_admin_levels", return_value=[]),
            mock.patch("mapmover.runtime.geometry_tool_jobs.get_geometry_index") as index_mock,
            mock.patch("mapmover.routes.mcp.log_api_query_event"),
        ):
            payload = _tool_call(
                self.client,
                "resolve_loc_id_scope",
                {"parent_loc_id": "NGA", "admin_level": "admin_4", "limit": 5},
            )

        index_mock.assert_not_called()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "unsupported_admin_level")

    def test_resolve_loc_id_scope_rejects_too_broad_deep_country_level(self) -> None:
        with (
            mock.patch("mapmover.runtime.geometry_tool_jobs.get_country_supported_deep_admin_levels", return_value=[3, 4]),
            mock.patch("mapmover.runtime.geometry_tool_jobs.get_geometry_index") as index_mock,
            mock.patch("mapmover.routes.mcp.log_api_query_event"),
        ):
            payload = _tool_call(
                self.client,
                "resolve_loc_id_scope",
                {"parent_loc_id": "USA", "admin_level": "admin_4", "limit": 5},
            )

        index_mock.assert_not_called()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "scope_too_broad")

    def test_estimate_geometry_package_uses_availability_preflight(self) -> None:
        with (
            mock.patch(
                "mapmover.runtime.geometry_tool_jobs.get_geometry_availability",
                return_value={"ok": True, "requested": 2, "available": 1, "missing": 1, "items": []},
            ) as availability_mock,
            mock.patch("mapmover.routes.mcp.log_api_query_event") as analytics_mock,
        ):
            payload = _tool_call(
                self.client,
                "estimate_geometry_package",
                {"loc_ids": ["USA-CA-037", "USA-NOPE"], "format": "geojson_gzip", "include_polygon": True},
            )

        availability_mock.assert_called_once_with(["USA-CA-037", "USA-NOPE"])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["loc_id_count"], 2)
        self.assertEqual(payload["available_shape_count"], 1)
        self.assertEqual(payload["missing_shape_count"], 1)
        self.assertEqual(payload["create_call"]["tool"], "create_geometry_export")
        self.assertEqual(analytics_mock.call_args.kwargs["capability_id"], "geometry_package_estimate")
        self.assertEqual(analytics_mock.call_args.kwargs["metadata"]["compute"]["input_count"], 2)
        self.assertEqual(analytics_mock.call_args.kwargs["metadata"]["compute"]["estimated_transfer_bytes"], payload["estimated_transfer_bytes"])
        self.assertIn("runtime_ms", analytics_mock.call_args.kwargs["metadata"]["compute"]["stage_ms"])

    def test_create_geometry_export_inline_then_status(self) -> None:
        with (
            mock.patch(
                "mapmover.runtime.geometry_tool_jobs.get_geometry_references",
                return_value={"ok": True, "requested": 1, "available": 1, "missing": 0, "results": [{"loc_id": "USA-CA-037", "has_shape": True}]},
            ),
            mock.patch("mapmover.routes.mcp.log_api_query_event"),
        ):
            created = _tool_call(
                self.client,
                "create_geometry_export",
                {"loc_ids": ["USA-CA-037"], "include_polygon": False},
            )
            status = _tool_call(self.client, "get_job_status", {"job_id": created["job_id"]})

        self.assertTrue(created["ok"])
        self.assertEqual(created["status"], "completed")
        self.assertEqual(created["result"]["delivery_mode"], "inline")
        self.assertEqual(status["job_id"], created["job_id"])
        self.assertEqual(status["status"], "completed")

    def test_conversion_estimate_and_inline_create(self) -> None:
        with mock.patch("mapmover.routes.mcp.log_api_query_event"):
            estimate = _tool_call(
                self.client,
                "estimate_conversion_job",
                {"from_system": "zip", "target_admin_level": "admin_2", "items": [{"value": "00601"}, {"value": "not-real"}]},
            )
            created = _tool_call(
                self.client,
                "create_conversion_job",
                {"from_system": "zip", "target_admin_level": "admin_2", "items": [{"row_index": 1, "value": "00601"}]},
            )

        self.assertTrue(estimate["ok"])
        self.assertEqual(estimate["row_count"], 2)
        self.assertEqual(estimate["create_call"]["tool"], "create_conversion_job")
        self.assertTrue(created["ok"])
        self.assertEqual(created["status"], "completed")
        self.assertEqual(created["result"]["row_count"], 1)
        self.assertEqual(created["result"]["converted_count"], 1)


if __name__ == "__main__":
    unittest.main()
