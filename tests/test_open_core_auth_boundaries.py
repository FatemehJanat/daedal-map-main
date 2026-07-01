from __future__ import annotations

import unittest
from types import SimpleNamespace

from mapmover.auth_context import build_session_cache_key, get_authenticated_user
from mapmover.routes import system


class OpenCoreAuthBoundaryTests(unittest.TestCase):
    def test_public_runtime_does_not_authenticate_hosted_users(self) -> None:
        request = SimpleNamespace(state=SimpleNamespace())
        self.assertIsNone(get_authenticated_user(request))

    def test_auth_config_is_disabled_for_open_core_runtime(self) -> None:
        self.assertFalse(system._hosted_auth_enabled())

    def test_session_cache_key_stays_guest_without_user(self) -> None:
        self.assertEqual(build_session_cache_key("session-1", None), "session-1")


if __name__ == "__main__":
    unittest.main()
