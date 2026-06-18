import unittest

from mapmover.api_query_runtime import ApiSourceSpec
from mapmover.api_query_scope import format_year_end, format_year_start, parse_time_filter
from mapmover.execution.event_execution import _build_single_event_message
from mapmover.runtime.postprocess_pipeline import (
    apply_default_time_windows,
    apply_event_qualifier_defaults,
)


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


if __name__ == "__main__":
    unittest.main()
