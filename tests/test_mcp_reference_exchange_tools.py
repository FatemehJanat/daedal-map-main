from __future__ import annotations

import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mapmover.runtime.reference_exchange import get_geometry_availability, get_geometry_references
from mapmover.routes.mcp import _tool_rate_limit_for_tier, _tool_result, router as mcp_router


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
        self.assertIn("compare_geographies", tool_names)
        self.assertIn("check_geometry", tool_names)
        self.assertIn("get_geometry", tool_names)
        self.assertIn("compare_geographies", tool_names)
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

    def test_large_structured_tool_result_summarizes_text_copy(self) -> None:
        payload = {
            "request_id": "large-shape-test",
            "ok": True,
            "results": [{"loc_id": "USA-AK-063", "geometry": "x" * 200}],
        }

        with mock.patch.dict("os.environ", {"MCP_TOOL_TEXT_INLINE_MAX_BYTES": "100"}):
            result = _tool_result(payload)

        self.assertEqual(result["structuredContent"]["request_id"], "large-shape-test")
        text = result["content"][0]["text"]
        self.assertIn("Large structured MCP result", text)
        self.assertIn("structuredContent", text)
        self.assertNotIn("x" * 200, text)

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
        self.assertEqual(payload["results"][0]["resolution_mode"], "latest_available_per_depth")
        self.assertTrue(payload["results"][0]["deeper_available"])
        self.assertEqual(payload["results"][0]["available_deeper_admin_levels"], ["admin_3"])
        self.assertIsNone(bulk_mock.call_args.kwargs["target_admin_level"])
        analytics = analytics_mock.call_args.kwargs
        self.assertEqual(analytics["capability_id"], "point_lookup")
        self.assertEqual(analytics["pack_id"], "geography_tools")
        self.assertEqual(analytics["source_id"], "resolve_point")
        self.assertEqual(analytics["decision"], "allow")
        self.assertEqual(analytics["payment_rail"], "free")
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
        """Over the free allowance the verifier decides, and its price is passed through."""
        challenge = (
            "challenge",
            {
                "status": "challenge",
                "message": "Commercial access is required for this capability.",
                "context": {"pricing": {"price_display": "$0.011306", "amount_usdc_base_units": 11306}},
                "challenge": {"opaque": True, "headers": {}},
            },
        )
        with (
            mock.patch("mapmover.routes.mcp._commercial_access_decision", return_value=challenge),
            mock.patch("mapmover.routes.mcp.log_api_query_event") as analytics_mock,
        ):
            payload = _tool_call(
                self.client,
                "resolve_point",
                {"points": [{"lon": 0, "lat": 0} for _ in range(26)]},
            )

        self.assertTrue(payload["payment_required"])
        self.assertEqual(payload["limits"]["free_batch_limit"], 25)
        self.assertEqual(payload["error"]["code"], "payment_required")
        # The caller must receive the verifier's real price, not a guess.
        self.assertEqual(payload["daedalmap_pricing"]["amount_usdc_base_units"], 11306)
        self.assertTrue(payload["challenge"]["opaque"])
        analytics = analytics_mock.call_args.kwargs
        self.assertEqual(analytics["decision"], "challenge")
        self.assertEqual(analytics["payment_rail"], "commercial_access")

    def test_resolve_point_refuses_when_the_verifier_is_unreachable(self) -> None:
        """Fail closed: a paid request must never execute for free."""
        with (
            mock.patch(
                "mapmover.routes.mcp._commercial_access_decision",
                return_value=("unavailable", {"error": {"code": "commercial_access_unavailable"}}),
            ),
            mock.patch("mapmover.routes.mcp.log_api_query_event") as analytics_mock,
        ):
            payload = _tool_call(
                self.client,
                "resolve_point",
                {"points": [{"lon": 0, "lat": 0} for _ in range(26)]},
            )

        self.assertEqual(payload["error"]["code"], "commercial_access_unavailable")
        self.assertEqual(analytics_mock.call_args.kwargs["decision"], "deny")

    def test_resolve_point_executes_and_records_settlement_when_allowed(self) -> None:
        """A settled call runs, and lands in analytics as paid rather than free."""

        def fake_resolve(points, include_geometry=False, **_kwargs):
            return [
                {
                    "point": {"lon": point["lon"], "lat": point["lat"]},
                    "matched": {"loc_id": "TEST-1", "admin_level": 2, "iso3": "USA"},
                    "stack": [{"loc_id": "USA"}, {"loc_id": "TEST-1"}],
                    "target_admin_level": "admin_2",
                    "deeper_available": False,
                    "available_deeper_admin_levels": [],
                }
                for point in points
            ]

        allow = ("allow", {"status": "allow", "settlement": {"settlement_id": "settle-abc"}})
        with (
            mock.patch("mapmover.routes.mcp._commercial_access_decision", return_value=allow),
            mock.patch("mapmover.geometry_handlers.resolve_points_to_locations", side_effect=fake_resolve),
            mock.patch("mapmover.routes.mcp.log_api_query_event") as analytics_mock,
        ):
            payload = _tool_call(
                self.client,
                "resolve_point",
                {"points": [{"lon": 0, "lat": 0} for _ in range(26)]},
            )

        self.assertEqual(payload["point_count"], 26)
        analytics = analytics_mock.call_args.kwargs
        self.assertEqual(analytics["decision"], "allow")
        self.assertEqual(analytics["payment_rail"], "paid")
        self.assertEqual(analytics["metadata"]["settlement_id"], "settle-abc")

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
        challenge = ("challenge", {"status": "challenge", "context": {}, "challenge": {}})
        with mock.patch.dict("os.environ", {"MCP_TOOL_BATCH_LIMIT_RESOLVE_POINT": "2"}):
            with (
                mock.patch("mapmover.routes.mcp._commercial_access_decision", return_value=challenge),
                mock.patch("mapmover.routes.mcp.log_api_query_event"),
            ):
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
        self.assertEqual(analytics["payment_rail"], "free")
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

    def test_get_geometry_metadata_uses_metadata_only_fetch(self) -> None:
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
            mock.patch("mapmover.runtime.reference_exchange.get_location_info", return_value={"loc_id": "USA-CA-037"}),
        ):
            payload = get_geometry_references(["USA-CA-037", "USA-NOPE"], include_polygon=False)

        metadata_mock.assert_called_once_with(["USA-CA-037", "USA-NOPE"])
        geometry_mock.assert_not_called()
        self.assertEqual(payload["available"], 1)
        self.assertEqual(payload["results"][0]["name"], "Los Angeles County")
        self.assertNotIn("geometry", payload["results"][0])

    def test_get_geometry_single_normalizes_legacy_string_error(self) -> None:
        with (
            mock.patch(
                "mapmover.runtime.reference_exchange.get_geometry_reference",
                return_value={"ok": False, "loc_id": "USA-NOPE", "has_shape": False, "error": "no geometry found"},
            ),
            mock.patch("mapmover.routes.mcp.log_api_query_event") as analytics_mock,
        ):
            payload = _tool_call(self.client, "get_geometry", {"loc_id": "USA-NOPE"})

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "not_found")
        self.assertEqual(payload["error"]["message"], "no geometry found")
        self.assertEqual(analytics_mock.call_args.kwargs["error_code"], "not_found")

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

        geometry_mock.assert_called_once_with(["USA-CA-037", "USA-NOPE"], include_polygon=False, include_info=False)
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

    def test_point_and_geometry_schemas_keep_details_in_loc_id_info(self) -> None:
        envelope = _mcp_call(self.client, "tools/list")
        tools = {tool["name"]: tool for tool in envelope["result"]["tools"]}

        self.assertNotIn("include_geometry", tools["resolve_point"]["inputSchema"]["properties"])
        self.assertNotIn("include_info", tools["get_geometry"]["inputSchema"]["properties"])
        self.assertIn("Pass the returned stack loc_ids to loc_id_info", tools["resolve_point"]["description"])
        self.assertIn("drill-down tool", tools["loc_id_info"]["description"])
        self.assertIn("does not explain hierarchy", tools["get_geometry"]["description"])

    def test_get_geometry_tool_trusted_token_bypasses_batch_limit(self) -> None:
        with mock.patch.dict("os.environ", {"ARTIFACT_ACCESS_TOKENS": "tok_test_bypass", "MCP_TOOL_BATCH_LIMIT_GET_GEOMETRY": "2"}):
            with (
                mock.patch(
                    "mapmover.runtime.reference_exchange.get_geometry_references",
                    return_value={
                        "ok": True,
                        "requested": 3,
                        "available": 3,
                        "missing": 0,
                        "results": [
                            {"ok": True, "loc_id": "USA-CA-037", "has_shape": True},
                            {"ok": True, "loc_id": "USA-NY-061", "has_shape": True},
                            {"ok": True, "loc_id": "USA-IL-031", "has_shape": True},
                        ],
                    },
                ) as geometry_mock,
                mock.patch("mapmover.routes.mcp.log_api_query_event") as analytics_mock,
            ):
                payload = _tool_call(
                    self.client,
                    "get_geometry",
                    {"loc_ids": ["USA-CA-037", "USA-NY-061", "USA-IL-031"]},
                    headers={"Authorization": "Bearer tok_test_bypass"},
                )

        geometry_mock.assert_called_once()
        self.assertEqual(payload["requested"], 3)
        analytics = analytics_mock.call_args.kwargs
        self.assertEqual(analytics["payment_rail"], "trusted_artifact")
        self.assertIsNotNone(analytics["artifact_token_id"])

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
                    "has_polygon": True,
                    "source_vintage": "2021",
                    "source_system": "test_authority",
                    "release_id": "test-release-2021",
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
        self.assertEqual(payload["source_vintage"], "2021")
        self.assertEqual(payload["release_id"], "test-release-2021")
        self.assertEqual(payload["reference_count"], 1)
        self.assertEqual(payload["references"]["references"][0]["system"], "overlay_nws_fire_weather_zone")

    def test_loc_id_info_hierarchy_follows_stored_country_parentage(self) -> None:
        rows = {
            "CAN-BC-5915004": {
                "loc_id": "CAN-BC-5915004",
                "name": "Surrey",
                "admin_level": 3,
                "parent_id": "CAN-BC-5915",
                "family": "admin_boundary",
                "iso3": "CAN",
            },
            "CAN-BC-5915": {
                "loc_id": "CAN-BC-5915",
                "name": "Greater Vancouver",
                "admin_level": 2,
                "parent_id": "CAN-BC",
                "family": "admin_boundary",
                "iso3": "CAN",
            },
            "CAN-BC": {
                "loc_id": "CAN-BC",
                "name": "British Columbia",
                "admin_level": 1,
                "parent_id": "CAN",
                "family": "admin_boundary",
                "iso3": "CAN",
            },
            "CAN": {
                "loc_id": "CAN",
                "name": "Canada",
                "admin_level": 0,
                "parent_id": None,
                "family": "admin_boundary",
                "iso3": "CAN",
            },
        }
        with mock.patch("mapmover.geometry_handlers.get_location_info", side_effect=lambda loc_id: rows[loc_id]):
            payload = _tool_call(
                self.client,
                "loc_id_info",
                {"loc_id": "CAN-BC-5915004", "include_hierarchy": True},
            )

        self.assertEqual(payload["hierarchy"]["relationship_mode"], "strict_stored_parent")
        self.assertEqual(payload["hierarchy"]["parent"], "CAN-BC-5915")
        self.assertEqual(payload["hierarchy"]["ancestors"], ["CAN-BC-5915", "CAN-BC", "CAN"])

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
                "schema_version": "1.1.0",
                "generated_at": "2026-08-03T18:25:18Z",
                "geometry_families": [{"family": "admin_boundary", "label": "Admin", "feature_count": 10}],
                "geometry_products": [
                    {
                        "product_id": "global_admin_spine",
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
                "geometry_collections": [],
                "release_packages": [],
                "resolver_groups": [],
                "named_reference_objects": [],
            },
        ):
            payload = _tool_call(self.client, "read_geometry_catalog", {"view": "summary"})

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["view"], "summary")
        self.assertEqual(payload["schema_version"], "1.1.0")
        self.assertEqual(payload["counts"]["geometry_products"], 1)
        self.assertEqual(payload["admin_coverage"][0]["product_id"], "global_admin_spine")
        self.assertIn("download_url", payload)

    def test_read_geometry_catalog_logs_runtime_analytics(self) -> None:
        with (
            mock.patch(
                "mapmover.runtime.reference_exchange.read_geometry_catalog",
                return_value={
                    "ok": True,
                    "view": "products",
                    "counts": {"geometry_products": 3, "geometry_banks": 2},
                    "products": [],
                },
            ),
            mock.patch("mapmover.routes.mcp.log_api_query_event") as analytics_mock,
        ):
            payload = _tool_call(self.client, "read_geometry_catalog", {"view": "products"})

        self.assertTrue(payload["ok"])
        analytics = analytics_mock.call_args.kwargs
        self.assertEqual(analytics["source_id"], "read_geometry_catalog")
        self.assertEqual(analytics["capability_id"], "geometry_catalog_discovery")
        self.assertEqual(analytics["row_count"], 3)
        self.assertEqual(analytics["metadata"]["event"], "geometry_catalog_discovery")
        self.assertEqual(analytics["metadata"]["view"], "products")
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

    def test_resolve_reference_tool_selects_historical_identity_as_of_date(self) -> None:
        payload = _tool_call(
            self.client,
            "resolve_reference",
            {"from_system": "iso3166_3", "value": "YUG", "as_of": "2025"},
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["resolved_loc_id"], "HIST-YUG-FRY")
        self.assertFalse(payload["valid_at_requested_time"])
        self.assertEqual(
            {row["loc_id"] for row in payload["lifecycle"]["present_day_descendants"]},
            {"SRB", "MNE"},
        )

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

    def test_compare_geographies_tool_returns_spatial_and_temporal_relationship(self) -> None:
        expected = {
            "ok": True,
            "temporal_relation": "coexistent",
            "spatial_relation": "overlaps",
            "left_area_share": 0.18,
            "right_area_share": 0.03,
        }
        with (
            mock.patch("mapmover.runtime.geography_relationships.compare_geographies", return_value=expected) as compare_mock,
            mock.patch("mapmover.routes.mcp.log_api_query_event") as analytics_mock,
        ):
            payload = _tool_call(
                self.client,
                "compare_geographies",
                {"left_loc_id": "USA-Z-90001", "right_loc_id": "USA-TRIBAL-1823", "as_of": "2025"},
            )

        self.assertEqual(payload["spatial_relation"], "overlaps")
        self.assertEqual(payload["left_area_share"], 0.18)
        compare_mock.assert_called_once_with(
            "USA-Z-90001",
            "USA-TRIBAL-1823",
            as_of="2025",
            left_as_of=None,
            right_as_of=None,
            include_successors=True,
        )
        self.assertEqual(analytics_mock.call_args.kwargs["capability_id"], "geography_comparison")

    def test_compare_geographies_tool_accepts_pair_batch(self) -> None:
        with mock.patch(
            "mapmover.runtime.geography_relationships.compare_geographies",
            return_value={"ok": True, "spatial_relation": "disjoint"},
        ):
            payload = _tool_call(
                self.client,
                "compare_geographies",
                {
                    "batch_id": "relations-1",
                    "items": [
                        {"id": "one", "left_loc_id": "USA-Z-90001", "right_loc_id": "USA-TRIBAL-1823"},
                        {"id": "two", "left_loc_id": "USA-Z-10001", "right_loc_id": "USA-TRIBAL-1823"},
                    ],
                },
            )

        self.assertEqual(payload["batch_id"], "relations-1")
        self.assertEqual(payload["item_count"], 2)
        self.assertEqual(payload["compared_count"], 2)
        self.assertEqual([row["row_index"] for row in payload["results"]], ["one", "two"])

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
        base_mock.assert_called_once()
        self.assertEqual(base_mock.call_args.kwargs["admin_level"], 2)
        self.assertIn("loc_id", base_mock.call_args.kwargs["columns"])
        self.assertNotIn("geometry", base_mock.call_args.kwargs["columns"])
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
        self.assertEqual(created["next_call"]["tool"], "get_job_status")
        self.assertEqual(created["next_call"]["arguments"]["job_id"], created["job_id"])
        self.assertEqual(status["job_id"], created["job_id"])
        self.assertEqual(status["status"], "completed")

    def test_geometry_export_retry_is_idempotent_by_request_id(self) -> None:
        with (
            mock.patch(
                "mapmover.runtime.geometry_tool_jobs.get_geometry_references",
                return_value={"ok": True, "requested": 1, "available": 1, "missing": 0, "results": []},
            ),
            mock.patch("mapmover.routes.mcp.log_api_query_event"),
        ):
            arguments = {
                "request_id": "geometry-export-idempotency-test",
                "loc_ids": ["USA-CA-037"],
                "include_polygon": False,
            }
            first = _tool_call(self.client, "create_geometry_export", arguments)
            retry = _tool_call(self.client, "create_geometry_export", arguments)
            conflict = _tool_call(
                self.client,
                "create_geometry_export",
                {**arguments, "loc_ids": ["USA-NY-061"]},
            )

        self.assertEqual(retry["job_id"], first["job_id"])
        self.assertEqual(retry["created_at"], first["created_at"])
        self.assertEqual(retry["next_call"], first["next_call"])
        self.assertFalse(conflict["ok"])
        self.assertEqual(conflict["error"]["code"], "idempotency_conflict")

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
        self.assertEqual(created["next_call"]["arguments"]["job_id"], created["job_id"])
        self.assertEqual(created["result"]["row_count"], 1)
        self.assertEqual(created["result"]["converted_count"], 1)


if __name__ == "__main__":
    unittest.main()
