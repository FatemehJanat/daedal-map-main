from __future__ import annotations

import unittest
from unittest.mock import patch

from mapmover.llm_usage import classify_caller


class LLMUsageBoundaryTests(unittest.TestCase):
    def test_authenticated_caller_uses_private_account_context_for_plan(self) -> None:
        with patch(
            "mapmover.llm_usage._get_cached_account_context",
            return_value={"plan_id": "member", "email": "user@example.com"},
        ):
            result = classify_caller(
                auth_user={"id": "user-1", "email": "user@example.com"},
                ip_hash="ip-1",
            )

        self.assertEqual(result["caller_kind"], "authenticated")
        self.assertEqual(result["plan_id"], "member")


if __name__ == "__main__":
    unittest.main()
