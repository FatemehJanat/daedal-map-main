from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mapmover.routes.mcp import router as mcp_router


def _mcp_call(client: TestClient, method: str, params: dict | None = None, *, path: str = "/mcp/geography") -> dict:
    response = client.post(
        path,
        json={"jsonrpc": "2.0", "id": "test-1", "method": method, "params": params or {}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _tool_call(client: TestClient, name: str, arguments: dict | None = None, *, path: str = "/mcp/geography") -> dict:
    envelope = _mcp_call(
        client,
        "tools/call",
        {"name": name, "arguments": arguments or {}},
        path=path,
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
        self.assertIn("resolve_reference", tool_names)
        self.assertIn("loc_id_references", tool_names)
        self.assertIn("convert_reference", tool_names)
        self.assertIn("get_geometry", tool_names)
        self.assertIn("sidechain_to_admin", tool_names)
        self.assertIn("admin_to_sidechain", tool_names)

    def test_get_pack_geography_prefers_reference_exchange(self) -> None:
        payload = _tool_call(self.client, "get_pack", {"pack_id": "geography"})

        self.assertEqual(payload["routing"]["preferred_tool"], "list_reference_systems")
        self.assertEqual(payload["quick_start"]["first_query_template"]["tool"], "list_reference_systems")
        starter_tools = set(payload["quick_start"]["starter_tools"])
        self.assertIn("resolve_reference", starter_tools)
        self.assertIn("convert_reference", starter_tools)

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


if __name__ == "__main__":
    unittest.main()
