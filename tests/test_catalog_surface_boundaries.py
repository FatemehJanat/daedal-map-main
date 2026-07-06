from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mapmover.catalog_surface import (
    catalog_product_surface,
    filter_catalog_for_product_surface,
    has_catalog_product_surface,
    normalize_catalog_surface,
    request_can_use_wip_catalog,
)


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

    def test_published_alias_maps_to_explore_product_surface(self) -> None:
        self.assertEqual(normalize_catalog_surface("published"), "published")
        self.assertEqual(catalog_product_surface("published"), "explore")
        self.assertEqual(catalog_product_surface("research"), "research")

    def test_missing_catalog_surfaces_keep_legacy_explore_and_research(self) -> None:
        self.assertTrue(has_catalog_product_surface({}, "explore"))
        self.assertTrue(has_catalog_product_surface({}, "research"))
        self.assertFalse(has_catalog_product_surface({}, "api"))

    def test_filter_catalog_for_product_surface_keeps_research_only_out_of_explore(self) -> None:
        catalog = {
            "sources": [
                {"source_id": "normal_source", "pack_id": "normal_pack", "catalog_surfaces": ["explore", "research"]},
                {"source_id": "research_source", "pack_id": "research_pack", "catalog_surfaces": ["research"]},
            ],
            "packs": [
                {"pack_id": "normal_pack", "source_ids": ["normal_source"], "catalog_surfaces": ["explore", "research"]},
                {"pack_id": "research_pack", "source_ids": ["research_source"], "catalog_surfaces": ["research"]},
            ],
        }
        explore = filter_catalog_for_product_surface(catalog, "explore")
        research = filter_catalog_for_product_surface(catalog, "research")

        self.assertEqual([source["source_id"] for source in explore["sources"]], ["normal_source"])
        self.assertEqual([pack["pack_id"] for pack in explore["packs"]], ["normal_pack"])
        self.assertEqual(
            {source["source_id"] for source in research["sources"]},
            {"normal_source", "research_source"},
        )


if __name__ == "__main__":
    unittest.main()
