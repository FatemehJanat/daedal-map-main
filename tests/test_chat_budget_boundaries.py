from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

from mapmover.chat_budget import check_anonymous_chat_budget


class ChatBudgetBoundaryTests(unittest.TestCase):
    def test_anonymous_budget_reads_private_bridge_and_blocks_when_cap_reached(self) -> None:
        caller_ctx = {
            "caller_kind": "anonymous",
            "ip_hash": "anon-hash-1",
        }
        with patch("mapmover.chat_budget.load_anonymous_usage_cost", return_value=0.5) as usage_mock:
            with patch("mapmover.chat_budget.get_anonymous_cap_usd") as cap_mock:
                cap_mock.return_value = Decimal("0.25")
                decision = check_anonymous_chat_budget(caller_ctx)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.error_code, "chat_budget_exceeded_anonymous")
        usage_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
