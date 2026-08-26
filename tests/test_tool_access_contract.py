from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path
from unittest import mock

from tool_access_shared import (
    paid_bulk_tool_ids,
    tool_effective_item_limit,
    tool_meter,
    tool_payment_required_payload,
    tool_pricing_version,
    tool_quote,
)


ROOT = Path(__file__).resolve().parents[1]


class ToolAccessContractTests(unittest.TestCase):
    def test_registry_source_has_no_duplicate_literal_keys(self) -> None:
        tree = ast.parse((ROOT / "tool_access_shared.py").read_text(encoding="utf-8"))
        duplicates: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            seen: set[object] = set()
            for key in node.keys:
                if not isinstance(key, ast.Constant):
                    continue
                if key.value in seen:
                    duplicates.append(f"line {key.lineno}: {key.value!r}")
                seen.add(key.value)
        self.assertEqual(duplicates, [])

    def test_every_paid_tool_has_a_versioned_meter_and_integer_quote(self) -> None:
        for tool_name in paid_bulk_tool_ids():
            with self.subTest(tool_name=tool_name):
                self.assertNotEqual(tool_pricing_version(tool_name), "unpriced-v0")
                self.assertTrue(tool_meter(tool_name).get("unit"))
                quote = tool_quote(tool_name, 1, free_limit=0)
                self.assertIsInstance(quote["amount_usdc_base_units"], int)
                self.assertGreaterEqual(quote["amount_usdc_base_units"], 0)

    def test_price_and_limit_levers_share_one_env_convention(self) -> None:
        env = {
            "MCP_TOOL_PRICE_BASE_MICRO_USD_CREATE_CONVERSION_JOB": "12345",
            "MCP_TOOL_PRICE_PER_UNIT_MICRO_USD_CREATE_CONVERSION_JOB": "321",
            "MCP_TOOL_BATCH_LIMIT_CREATE_CONVERSION_JOB": "4321",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            quote = tool_quote("create_conversion_job", 2, free_limit=0)
            self.assertEqual(quote["amount_usdc_base_units"], 12987)
            self.assertEqual(tool_effective_item_limit("create_conversion_job"), 4321)

    def test_shared_challenge_preserves_the_canonical_quote(self) -> None:
        payload = tool_payment_required_payload(
            "resolve_point", 101, free_limit=100, paid_limit=10_000, request_id="req-1"
        )
        self.assertEqual(payload["quote"]["capability_id"], "point_lookup")
        self.assertEqual(payload["quote"]["amount_usdc_base_units"], 10_200)
        self.assertEqual(payload["limits"], {"free_batch_limit": 100, "paid_batch_limit": 10_000})


if __name__ == "__main__":
    unittest.main()
