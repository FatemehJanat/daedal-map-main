import unittest
from pathlib import Path
from unittest.mock import patch

from mapmover.runtime.geometry_loader import resolve_country_geometry_source


class GeometryLoaderRuntimeTests(unittest.TestCase):
    def test_prefers_country_county_geometry_for_admin2(self):
        with patch(
            "mapmover.runtime.geometry_loader.parquet_accessible",
            side_effect=lambda path: str(path).endswith("countries\\USA\\geometry\\county.parquet"),
        ), patch(
            "mapmover.runtime.geometry_loader.load_country_crosswalk",
            return_value={"mappings": {"USA-VA": "USA-G125186"}},
        ):
            resolved = resolve_country_geometry_source("USA", admin_level=2)

        self.assertEqual(resolved["source_kind"], "country_county")
        self.assertTrue(str(resolved["parquet_file"]).endswith("countries\\USA\\geometry\\county.parquet"))
        self.assertFalse(resolved["uses_crosswalk"])

    def test_prefers_country_geometry_base_before_crosswalk_fallback(self):
        def accessible(path: Path | None) -> bool:
            text = str(path)
            return text.endswith("countries\\EUR\\geometry.parquet")

        with patch("mapmover.runtime.geometry_loader.parquet_accessible", side_effect=accessible), patch(
            "mapmover.runtime.geometry_loader.load_country_crosswalk",
            return_value={"mappings": {"FRA-IDF": "FRA-GEO"}},
        ):
            resolved = resolve_country_geometry_source("EUR")

        self.assertEqual(resolved["source_kind"], "country_base")
        self.assertTrue(str(resolved["parquet_file"]).endswith("countries\\EUR\\geometry.parquet"))
        self.assertFalse(resolved["uses_crosswalk"])

    def test_uses_crosswalk_base_when_local_geometry_missing(self):
        def accessible(path: Path | None) -> bool:
            text = str(path)
            return text.endswith("geometry\\USA.parquet")

        crosswalk = {"mappings": {"USA-VA": "USA-G125186"}}
        with patch("mapmover.runtime.geometry_loader.parquet_accessible", side_effect=accessible), patch(
            "mapmover.runtime.geometry_loader.load_country_crosswalk",
            return_value=crosswalk,
        ):
            resolved = resolve_country_geometry_source("USA")

        self.assertEqual(resolved["source_kind"], "crosswalk_base")
        self.assertTrue(str(resolved["parquet_file"]).endswith("geometry\\USA.parquet"))
        self.assertTrue(resolved["uses_crosswalk"])
        self.assertEqual(resolved["crosswalk"], crosswalk)

    def test_uses_global_base_when_crosswalk_missing(self):
        def accessible(path: Path | None) -> bool:
            text = str(path)
            return text.endswith("geometry\\BRA.parquet")

        with patch("mapmover.runtime.geometry_loader.parquet_accessible", side_effect=accessible), patch(
            "mapmover.runtime.geometry_loader.load_country_crosswalk",
            return_value=None,
        ):
            resolved = resolve_country_geometry_source("BRA")

        self.assertEqual(resolved["source_kind"], "global_base")
        self.assertTrue(str(resolved["parquet_file"]).endswith("geometry\\BRA.parquet"))
        self.assertFalse(resolved["uses_crosswalk"])


if __name__ == "__main__":
    unittest.main()
