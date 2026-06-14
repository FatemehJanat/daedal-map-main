import unittest
from unittest.mock import patch

from mapmover.runtime.source_hints import (
    get_country_geo_level_aliases,
    resolve_geo_contract,
)


class SourceHintsRuntimeTests(unittest.TestCase):
    def test_country_geo_level_aliases_include_overlap_levels(self):
        metadata = {"geographic_coverage": {"country": "BEL"}}
        with (
            patch(
                "mapmover.runtime.source_hints.get_country_overlap_levels",
                return_value={
                    "admin_2": {
                        "display_name": "province",
                        "canonical_dataset_label": "nuts_2",
                        "aliases": ["province", "provinces", "provincie"],
                    },
                    "admin_3": {
                        "display_name": "arrondissement",
                        "canonical_dataset_label": "nuts_3",
                        "aliases": ["arrondissement", "district"],
                    },
                },
            ),
            patch("mapmover.runtime.source_hints.get_country_sub_admin_levels", return_value={}),
        ):
            aliases = get_country_geo_level_aliases(metadata)

        self.assertEqual(aliases["province"], "admin_2")
        self.assertEqual(aliases["provinces"], "admin_2")
        self.assertEqual(aliases["arrondissement"], "admin_3")
        self.assertEqual(aliases["district"], "admin_3")

    def test_resolve_geo_contract_maps_overlap_only_terms_to_runtime_levels(self):
        metadata = {
            "geographic_coverage": {"country": "FRA"},
            "geographic_level": ["admin_0", "admin_1", "admin_2", "admin_3"],
        }
        with (
            patch(
                "mapmover.runtime.source_hints.get_country_overlap_levels",
                return_value={
                    "admin_3": {
                        "display_name": "department",
                        "canonical_dataset_label": "nuts_3",
                        "aliases": ["department", "departments", "departement"],
                    }
                },
            ),
            patch("mapmover.runtime.source_hints.get_country_sub_admin_levels", return_value={}),
        ):
            contract = resolve_geo_contract("department", metadata)

        self.assertEqual(contract.runtime_level, "admin_3")
        self.assertEqual(contract.country_level_name, "department")
        self.assertEqual(contract.source_level_value, "department")
        self.assertEqual(contract.source_filter_field, "geo_level")

    def test_real_crosswalk_terms_resolve_on_shared_runtime_contract(self):
        cases = [
            (
                {"geographic_coverage": {"country": "FRA"}, "geographic_level": ["admin_0", "admin_1", "admin_2", "admin_3"]},
                "department",
                "admin_3",
                "department",
            ),
            (
                {"geographic_coverage": {"country": "BEL"}, "geographic_level": ["admin_0", "admin_1", "admin_2", "admin_3"]},
                "province",
                "admin_2",
                None,
            ),
            (
                {"geographic_coverage": {"country": "SVK"}, "geographic_level": ["admin_0", "admin_1", "admin_2", "admin_3"]},
                "district",
                "admin_4",
                "district",
            ),
            (
                {"geographic_coverage": {"country": "SVK"}, "geographic_level": ["admin_0", "admin_1", "admin_2", "admin_3", "admin_4", "admin_5"]},
                "obec",
                "admin_5",
                "municipality",
            ),
            (
                {"geographic_coverage": {"country": "AUT"}, "geographic_level": ["admin_0", "admin_1", "admin_2", "admin_3", "admin_4", "admin_5"]},
                "Gemeinde",
                "admin_5",
                "municipality",
            ),
        ]

        for metadata, token, expected_level, expected_source_value in cases:
            with self.subTest(token=token, country=metadata["geographic_coverage"]["country"]):
                contract = resolve_geo_contract(token, metadata)
                self.assertEqual(contract.runtime_level, expected_level)
                self.assertEqual(contract.source_level_value, expected_source_value)

    def test_country_local_level_terms_do_not_bleed_across_other_countries(self):
        cases = [
            (
                {"geographic_coverage": {"country": "FRA"}, "geographic_level": ["admin_0", "admin_1", "admin_2", "admin_3"]},
                "obec",
            ),
            (
                {"geographic_coverage": {"country": "BEL"}, "geographic_level": ["admin_0", "admin_1", "admin_2", "admin_3"]},
                "Gemeinde",
            ),
            (
                {"geographic_coverage": {"country": "AUT"}, "geographic_level": ["admin_0", "admin_1", "admin_2", "admin_3", "admin_4", "admin_5"]},
                "department",
            ),
            (
                {"geographic_coverage": {"country": "SVK"}, "geographic_level": ["admin_0", "admin_1", "admin_2", "admin_3", "admin_4", "admin_5"]},
                "province",
            ),
        ]

        for metadata, token in cases:
            with self.subTest(token=token, country=metadata["geographic_coverage"]["country"]):
                contract = resolve_geo_contract(token, metadata)
                self.assertIsNone(contract.runtime_level)
                self.assertIsNone(contract.source_level_value)


if __name__ == "__main__":
    unittest.main()
