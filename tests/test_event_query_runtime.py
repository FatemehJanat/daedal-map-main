import unittest

from mapmover.api_query_runtime import ApiSourceSpec
from mapmover.api_query_scope import format_year_end, format_year_start, parse_time_filter
from mapmover.execution.event_execution import _build_single_event_message
from mapmover.runtime.filter_primitives import partition_region_filter_codes
from mapmover.runtime.postprocess_pipeline import (
    apply_default_time_windows,
    apply_event_qualifier_defaults,
    apply_query_derived_order_hints,
)
from mapmover.runtime.query_constraint_primitives import extract_query_constraints


class EventQueryRuntimeTests(unittest.TestCase):
    def test_event_qualifier_defaults_are_config_driven_for_single_event_query(self):
        items = [
            {
                "source_id": "earthquakes_events",
                "pack_id": "earthquakes",
                "mode": "events",
                "_hints": {"original_query": "show me the biggest earthquake of all time"},
            }
        ]

        apply_event_qualifier_defaults(
            items,
            load_source_metadata=lambda _source_id: {
                "data_type": "events",
                "pack_id": "earthquakes",
            },
            load_reference_json=lambda _path: {
                "event_qualifier_defaults": {
                    "earthquakes": {"biggest": "magnitude"},
                    "wildfires": {"biggest": "area_km2"},
                }
            },
        )

        self.assertEqual(items[0]["sort"], {"by": "magnitude", "order": "desc"})
        self.assertEqual(items[0]["limit"], 1)

    def test_event_qualifier_defaults_do_not_force_single_limit_for_plural_query(self):
        items = [
            {
                "source_id": "earthquakes_events",
                "pack_id": "earthquakes",
                "mode": "events",
                "_hints": {"original_query": "show me the largest earthquakes in 2004"},
            }
        ]

        apply_event_qualifier_defaults(
            items,
            load_source_metadata=lambda _source_id: {
                "data_type": "events",
                "pack_id": "earthquakes",
            },
            load_reference_json=lambda _path: {
                "event_qualifier_defaults": {
                    "earthquakes": {"largest": "magnitude"},
                }
            },
        )

        self.assertEqual(items[0]["sort"], {"by": "magnitude", "order": "desc"})
        self.assertNotIn("limit", items[0])

    def test_event_qualifier_defaults_support_ascending_rank_queries(self):
        items = [
            {
                "source_id": "earthquakes_events",
                "pack_id": "earthquakes",
                "mode": "events",
                "_hints": {"original_query": "show me the smallest earthquake in 2004"},
            }
        ]

        apply_event_qualifier_defaults(
            items,
            load_source_metadata=lambda _source_id: {
                "data_type": "events",
                "pack_id": "earthquakes",
            },
            load_reference_json=lambda _path: {
                "event_qualifier_defaults": {
                    "earthquakes": {
                        "smallest": {"metric": "magnitude", "order": "asc"},
                    },
                }
            },
        )

        self.assertEqual(items[0]["sort"], {"by": "magnitude", "order": "asc"})
        self.assertEqual(items[0]["limit"], 1)

    def test_default_time_windows_skip_open_ended_all_time_queries(self):
        items = [
            {
                "source_id": "earthquakes_events",
                "_hints": {"original_query": "show me the biggest earthquake of all time"},
            }
        ]

        apply_default_time_windows(
            items,
            load_source_metadata=lambda _source_id: {
                "temporal_coverage": {"start": 1900, "end": 2025}
            },
        )

        self.assertNotIn("year_start", items[0])
        self.assertNotIn("year_end", items[0])
        self.assertTrue(items[0].get("_time_hint_applied"))

    def test_parse_time_filter_uses_utc_year_boundaries_for_temporal_sources(self):
        spec = ApiSourceSpec(
            source_id="earthquakes_events",
            pack_id="earthquakes",
            parquet_name="events.parquet",
            query_mode="single_source",
            location_field="loc_id",
            time_field="timestamp",
            time_granularity="timestamp",
            metrics={},
            filterable_fields={"timestamp"},
            sortable_fields={"timestamp"},
        )

        normalized_time, exact_filters, compare_filters = parse_time_filter(spec, {"year": 2004})

        self.assertEqual(normalized_time["start"], format_year_start(2004))
        self.assertEqual(normalized_time["end"], format_year_end(2004))
        self.assertEqual(exact_filters, {})
        self.assertEqual(
            compare_filters,
            [
                ("timestamp", ">=", format_year_start(2004)),
                ("timestamp", "<=", format_year_end(2004)),
            ],
        )

    def test_single_event_message_formats_timestamp_in_utc(self):
        message = _build_single_event_message(
            "earthquake",
            {
                "magnitude": 9.1,
                "place": "Off the west coast of northern Sumatra",
                "timestamp": "2004-12-26T00:58:53Z",
            },
            query_text="show me the biggest earthquake in 2004",
        )

        self.assertEqual(
            message,
            "The earthquake in 2004 was M 9.1 - Off the west coast of northern Sumatra - Dec 26, 2004 UTC.",
        )

    def test_single_event_message_preserves_smallest_qualifier(self):
        message = _build_single_event_message(
            "earthquake",
            {
                "magnitude": 1.2,
                "place": "Nevada",
                "timestamp": "2004-01-02T00:00:00Z",
            },
            query_text="show me the smallest earthquake in 2004",
        )

        self.assertEqual(
            message,
            "The smallest earthquake in 2004 was M 1.2 - Nevada - Jan 02, 2004 UTC.",
        )

    def test_query_derived_order_hints_convert_acres_to_area_km2(self):
        items = [
            {
                "source_id": "can_wildfires",
                "pack_id": "wildfires",
                "mode": "events",
                "_hints": {
                    "original_query": "show me fires in BC, canada, from 2017 to present, bigger than 1000 acres"
                },
            }
        ]

        apply_query_derived_order_hints(
            items,
            load_source_metadata=lambda _source_id: {
                "data_type": "events",
                "metrics": {
                    "area_km2": {"name": "Burned area"},
                    "burned_acres": {"name": "Burned acres"},
                },
            },
            hints={
                "query_constraints": {
                    "region_loc_id": "CAN-BC",
                    "area_constraint": {"normalized_value": 4.04686},
                }
            },
        )

        self.assertAlmostEqual(items[0]["filters"]["area_km2_min"], 4.04686, places=5)
        self.assertEqual(items[0]["region"], "CAN-BC")

    def test_query_derived_order_hints_preserve_existing_narrower_area_filter(self):
        items = [
            {
                "source_id": "can_wildfires",
                "pack_id": "wildfires",
                "mode": "events",
                "filters": {"area_km2_min": 10.0},
                "_hints": {
                    "original_query": "show me fires in BC, canada, bigger than 1000 acres"
                },
            }
        ]

        apply_query_derived_order_hints(
            items,
            load_source_metadata=lambda _source_id: {
                "data_type": "events",
                "metrics": {"area_km2": {"name": "Burned area"}},
            },
            hints={
                "query_constraints": {
                    "region_loc_id": "CAN-BC",
                    "area_constraint": {"normalized_value": 4.04686},
                }
            },
        )

        self.assertEqual(items[0]["filters"]["area_km2_min"], 10.0)
        self.assertEqual(items[0]["region"], "CAN-BC")

    def test_query_derived_order_hints_replace_free_text_region_with_canonical_loc_id(self):
        items = [
            {
                "source_id": "worldpop",
                "region": "Paris, France",
                "_hints": {
                    "original_query": "give me a data point for paris, france"
                },
            }
        ]

        apply_query_derived_order_hints(
            items,
            load_source_metadata=lambda _source_id: {
                "data_type": "metrics",
                "metrics": {"population": {"name": "Population"}},
            },
            hints={
                "query_constraints": {
                    "region_loc_id": "FRA-G147427",
                }
            },
        )

        self.assertEqual(items[0]["region"], "FRA-G147427")

    def test_query_derived_order_hints_preserve_existing_canonical_region(self):
        items = [
            {
                "source_id": "worldpop",
                "region": "FRA-G147427",
                "_hints": {
                    "original_query": "give me a data point for paris, france"
                },
            }
        ]

        apply_query_derived_order_hints(
            items,
            load_source_metadata=lambda _source_id: {
                "data_type": "metrics",
                "metrics": {"population": {"name": "Population"}},
            },
            hints={
                "query_constraints": {
                    "region_loc_id": "FRA-G147427",
                }
            },
        )

        self.assertEqual(items[0]["region"], "FRA-G147427")

    def test_extract_query_constraints_resolve_subregion_and_area_units(self):
        constraints = extract_query_constraints(
            "show me fires in BC, canada, from 2017 to present, bigger than 1000 acres",
            resolve_admin_text_to_loc_id_func=lambda value, country_hint=None, admin_level_hint=None: (
                {"deepest_resolved_loc_id": "CAN"} if str(value).strip().lower() == "canada"
                else {"deepest_resolved_loc_id": "CAN-BC"}
            ),
            load_reference_file_func=lambda _path: {"iso3_to_name": {"CAN": "Canada"}},
            reference_dir=".",
        )

        self.assertEqual(constraints["region_loc_id"], "CAN-BC")
        self.assertEqual(constraints["location"]["iso3"], "CAN")
        self.assertAlmostEqual(constraints["filters"]["area_km2_min"], 4.04686, places=5)

    def test_extract_query_constraints_resolve_space_separated_subregion_and_country(self):
        def _resolve(value, country_hint=None, admin_level_hint=None):
            normalized = str(value).strip().lower()
            if normalized == "canada":
                return {"deepest_resolved_loc_id": "CAN"}
            if normalized == "ontario":
                return {"deepest_resolved_loc_id": "CAN-ON"}
            return {}

        constraints = extract_query_constraints(
            "show me the fires in ontario canada bigger than 200km2",
            resolve_admin_text_to_loc_id_func=_resolve,
            load_reference_file_func=lambda _path: {"iso3_to_name": {"CAN": "Canada"}},
            reference_dir=".",
        )

        self.assertEqual(constraints["region_loc_id"], "CAN-ON")
        self.assertEqual(constraints["location"]["matched_term"], "ontario")
        self.assertAlmostEqual(constraints["filters"]["area_km2_min"], 200.0, places=5)

    def test_extract_query_constraints_does_not_force_admin_level_one_for_subregions(self):
        calls = []

        def _resolve(value, country_hint=None, admin_level_hint=None):
            calls.append(
                {
                    "value": str(value).strip().lower(),
                    "country_hint": country_hint,
                    "admin_level_hint": admin_level_hint,
                }
            )
            normalized = str(value).strip().lower()
            if normalized == "canada":
                return {"deepest_resolved_loc_id": "CAN"}
            if normalized == "toronto":
                return {"deepest_resolved_loc_id": "CAN-ON-TOR"}
            return {}

        constraints = extract_query_constraints(
            "show me fires in toronto canada bigger than 1 km2",
            resolve_admin_text_to_loc_id_func=_resolve,
            load_reference_file_func=lambda _path: {"iso3_to_name": {"CAN": "Canada"}},
            reference_dir=".",
        )

        self.assertEqual(constraints["region_loc_id"], "CAN-ON-TOR")
        self.assertEqual(calls[0]["admin_level_hint"], 0)
        self.assertIsNone(calls[-1]["admin_level_hint"])

    def test_partition_region_filter_codes_keeps_subnational_loc_ids_as_prefixes(self):
        prefixes, countries = partition_region_filter_codes(
            ["CAN-BC", "USA-CA-037", "CAN", "USA", "EEZ-CAN", "XNA"]
        )

        self.assertEqual(prefixes, ["CAN-BC", "USA-CA-037", "EEZ-CAN", "XNA"])
        self.assertEqual(countries, ["CAN", "USA"])


if __name__ == "__main__":
    unittest.main()
