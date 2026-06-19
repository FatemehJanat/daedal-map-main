import unittest
from unittest.mock import patch

from mapmover.runtime.source_hints import (
    build_query_specific_disaster_relationship_guidance,
    build_shared_disaster_relationship_guidance,
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

    @patch(
        "mapmover.runtime.source_hints.load_reference_json",
        return_value={
            "published_contract": {
                "supported_pack_ids": ["wildfires", "earthquakes"],
            },
            "relationship_language_hints": {
                "metaquestion_examples": [
                    "What type of links do you have?",
                    "How many wildfire to flood links are published?",
                ],
                "relationships": [
                    {
                        "relationship_id": "wildfire_to_flood",
                        "side_a": {
                            "event_type": "wildfire",
                            "pack_ids": ["wildfires"],
                        },
                        "side_b": {
                            "event_type": "flood",
                            "pack_ids": ["floods"],
                        },
                        "canonical_direction": "a_to_b",
                        "a_to_b_phrases": ["floods after fires", "post-fire floods"],
                        "b_to_a_phrases": ["floods that caused fires"],
                        "neutral_phrases": ["wildfire flood links"],
                        "clarify_when_reversed": True,
                        "reverse_edge_supported": False,
                        "reverse_query_behavior": "correct_and_continue_with_canonical_family",
                        "example_queries": ["Show me post-fire floods in California."],
                    }
                ],
                "not_paired_relationships": [
                    {
                        "relationship_id": "tornado_wildfire_not_paired",
                        "side_a": {
                            "event_type": "tornado",
                            "pack_ids": ["tornadoes"],
                        },
                        "side_b": {
                            "event_type": "wildfire",
                            "pack_ids": ["wildfires"],
                        },
                        "query_behavior": "state_not_published",
                        "note": "No published cross-disaster link family exists in either direction today.",
                        "example_queries": ["Do you have tornado wildfire links?"],
                    }
                ],
            },
        },
    )
    def test_build_shared_disaster_relationship_guidance_uses_neutral_relationship_hints(self, _load_reference_json_mock):
        guidance = build_shared_disaster_relationship_guidance("wildfires")

        self.assertIn("wildfire -> flood", guidance)
        self.assertIn("floods after fires", guidance)
        self.assertIn("wildfire flood links", guidance)
        self.assertIn("reversed wording should clarify", guidance)
        self.assertIn("correct to the canonical direction and continue with linked events", guidance)
        self.assertIn("tornado x wildfire", guidance)
        self.assertIn("no published link family exists yet", guidance)
        self.assertIn("What type of links do you have?", guidance)

    @patch(
        "mapmover.runtime.source_hints.load_reference_json",
        return_value={
            "published_contract": {
                "supported_pack_ids": ["wildfires", "earthquakes"],
            },
            "relationship_language_hints": {
                "relationships": [
                    {
                        "relationship_id": "hurricane_to_tornado",
                        "side_a": {
                            "event_type": "hurricane",
                            "pack_ids": ["hurricanes"],
                        },
                        "side_b": {
                            "event_type": "tornado",
                            "pack_ids": ["tornadoes"],
                        },
                        "canonical_direction": "a_to_b",
                        "a_to_b_phrases": ["tornadoes caused by hurricanes"],
                        "b_to_a_phrases": ["tornadoes that caused hurricanes"],
                        "neutral_phrases": ["hurricane tornado links"],
                        "clarify_when_reversed": True,
                        "reverse_edge_supported": False,
                        "reverse_query_behavior": "correct_and_continue_with_canonical_family",
                    }
                ],
                "not_paired_relationships": [],
            },
        },
    )
    def test_build_shared_disaster_relationship_guidance_is_not_limited_to_api_supported_pack_ids(self, _load_reference_json_mock):
        guidance = build_shared_disaster_relationship_guidance("tornadoes")

        self.assertIn("hurricane -> tornado", guidance)
        self.assertIn("correct to the canonical direction and continue with linked events", guidance)

    @patch(
        "mapmover.runtime.source_hints.load_reference_json",
        return_value={
            "relationship_language_hints": {
                "relationships": [
                    {
                        "relationship_id": "wildfire_to_flood",
                        "side_a": {
                            "event_type": "wildfire",
                            "pack_ids": ["wildfires"],
                            "aliases": ["wildfire", "wildfires", "fire", "fires"],
                        },
                        "side_b": {
                            "event_type": "flood",
                            "pack_ids": ["floods"],
                            "aliases": ["flood", "floods", "post-fire flood", "post-fire floods"],
                        },
                        "canonical_direction": "a_to_b",
                        "a_to_b_phrases": ["post-fire floods", "floods after fires"],
                        "b_to_a_phrases": ["floods that led to fires", "floods that caused fires"],
                        "neutral_phrases": ["wildfire flood links", "floods linked to fires"],
                        "clarify_when_reversed": True,
                        "reverse_edge_supported": False,
                        "reverse_query_behavior": "correct_and_continue_with_canonical_family",
                    }
                ],
                "not_paired_relationships": [
                    {
                        "relationship_id": "volcano_wildfire_not_paired",
                        "side_a": {
                            "event_type": "volcano",
                            "pack_ids": ["volcanoes"],
                            "aliases": ["volcano", "volcanoes"],
                        },
                        "side_b": {
                            "event_type": "wildfire",
                            "pack_ids": ["wildfires"],
                            "aliases": ["wildfire", "wildfires", "fire", "fires"],
                        },
                        "query_behavior": "state_not_published",
                        "example_queries": ["Do you have volcano wildfire links?"],
                    }
                ],
            },
        },
    )
    def test_query_specific_relationship_guidance_corrects_reverse_queries_without_hiding_existing_family(self, _load_reference_json_mock):
        guidance = build_query_specific_disaster_relationship_guidance(
            "Show me the floods that led to fires.",
            "wildfires",
        )

        self.assertIn("published wildfire -> flood family", guidance)
        self.assertIn("reverse direction", guidance)
        self.assertIn("Do not say this relationship family is absent", guidance)

    @patch(
        "mapmover.runtime.source_hints.load_reference_json",
        return_value={
            "relationship_language_hints": {
                "relationships": [],
                "not_paired_relationships": [
                    {
                        "relationship_id": "volcano_wildfire_not_paired",
                        "side_a": {
                            "event_type": "volcano",
                            "pack_ids": ["volcanoes"],
                            "aliases": ["volcano", "volcanoes"],
                        },
                        "side_b": {
                            "event_type": "wildfire",
                            "pack_ids": ["wildfires"],
                            "aliases": ["wildfire", "wildfires", "fire", "fires"],
                        },
                        "query_behavior": "state_not_published",
                        "example_queries": ["Do you have volcano wildfire links?"],
                    }
                ],
            },
        },
    )
    def test_query_specific_relationship_guidance_resolves_not_paired_queries(self, _load_reference_json_mock):
        guidance = build_query_specific_disaster_relationship_guidance(
            "Do you have volcano wildfire links?",
            "wildfires",
        )

        self.assertIn("not-paired volcano x wildfire family", guidance)
        self.assertIn("no published cross-disaster link family exists", guidance)


if __name__ == "__main__":
    unittest.main()
