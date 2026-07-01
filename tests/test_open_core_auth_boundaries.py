from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mapmover.auth_context import build_session_cache_key, get_authenticated_user
from mapmover.routes import system


class OpenCoreAuthBoundaryTests(unittest.TestCase):
    def test_public_runtime_stays_guest_without_bearer_token(self) -> None:
        request = SimpleNamespace(headers={}, state=SimpleNamespace())
        self.assertIsNone(get_authenticated_user(request))

    def test_public_runtime_only_uses_private_bridge_for_bearer_auth(self) -> None:
        request = SimpleNamespace(
            headers={"authorization": "Bearer access-token-1"},
            state=SimpleNamespace(),
        )
        with patch(
            "mapmover.auth_context.load_authenticated_user",
            return_value={"id": "user-1", "email": "user@example.com"},
        ) as load_user:
            result = get_authenticated_user(request)

        self.assertEqual(result["id"], "user-1")
        load_user.assert_called_once_with("access-token-1")

    def test_auth_config_is_disabled_for_open_core_runtime(self) -> None:
        self.assertFalse(system._hosted_auth_enabled())

    def test_session_cache_key_stays_guest_without_user(self) -> None:
        self.assertEqual(build_session_cache_key("session-1", None), "session-1")


if __name__ == "__main__":
    unittest.main()
