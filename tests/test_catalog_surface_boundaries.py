from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mapmover.catalog_surface import request_can_use_wip_catalog


class CatalogSurfaceBoundaryTests(unittest.TestCase):
    def test_wip_catalog_allows_private_admin_context(self) -> None:
        request = SimpleNamespace(client=SimpleNamespace(host="10.0.0.5"))
        auth_user = {"id": "user-1"}
        with patch(
            "mapmover.catalog_surface.load_account_context",
            return_value={"plan_id": "master", "is_admin": False},
        ):
            self.assertTrue(request_can_use_wip_catalog(request, auth_user))

    def test_wip_catalog_falls_back_to_local_loopback_only(self) -> None:
        request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
        auth_user = {"id": "user-1"}
        with patch("mapmover.catalog_surface.load_account_context", return_value=None):
            with patch("os.getenv", side_effect=lambda key, default="": "local" if key == "DEPLOYMENT" else default):
                self.assertTrue(request_can_use_wip_catalog(request, auth_user))


if __name__ == "__main__":
    unittest.main()
