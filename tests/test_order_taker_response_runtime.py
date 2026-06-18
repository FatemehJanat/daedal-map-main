import unittest
from unittest.mock import patch

from mapmover.runtime.order_taker_response import (
    _build_metadata_guided_pack_aggregate_order,
    _query_requests_over_time_analysis,
)


class OrderTakerResponseRuntimeTests(unittest.TestCase):
    def test_query_requests_over_time_analysis_for_year_range(self):
        self.assertTrue(
            _query_requests_over_time_analysis(
                {
                    "time": {
                        "year_start": 2000,
                        "year_end": 2010,
                    }
                }
            )
        )
        self.assertFalse(
            _query_requests_over_time_analysis(
                {
                    "time": {
                        "year_start": 2004,
                        "year_end": 2004,
                    }
                }
            )
        )

    @patch("mapmover.runtime.order_taker_response.infer_requested_geo_level_from_query", return_value="admin_0")
    @patch("mapmover.runtime.order_taker_response.get_routing_hints", return_value={"query_priority": 2.0})
    @patch("mapmover.runtime.order_taker_response.get_query_alias_matches", return_value=[("damage", "event_count")])
    @patch("mapmover.runtime.order_taker_response.select_query_guided_metric", return_value="event_count")
    @patch("mapmover.runtime.order_taker_response.source_supports_aggregate_mode_impl")
    @patch("mapmover.runtime.order_taker_response.load_source_metadata")
    @patch("mapmover.runtime.order_taker_response.load_catalog")
    def test_build_metadata_guided_pack_aggregate_order_prefers_aggregate_source(
        self,
        load_catalog_mock,
        load_source_metadata_mock,
        source_supports_aggregate_mode_mock,
        _select_metric_mock,
        _query_alias_mock,
        _routing_hints_mock,
        _geo_level_mock,
    ):
        load_catalog_mock.return_value = {
            "sources": [
                {
                    "source_id": "earthquakes_events",
                    "pack_id": "earthquakes",
                    "data_type": "events",
                },
                {
                    "source_id": "earthquakes_country_yearly",
                    "pack_id": "earthquakes",
                    "data_type": "metrics",
                    "metrics": {"event_count": {"name": "Earthquake count"}},
                },
            ]
        }

        def load_source_metadata_side_effect(source_id):
            if source_id == "earthquakes_country_yearly":
                return {
                    "source_id": source_id,
                    "pack_id": "earthquakes",
                    "source_name": "Earthquake aggregates",
                    "metrics": {"event_count": {"name": "Earthquake count"}},
                }
            if source_id == "earthquakes_events":
                return {
                    "source_id": source_id,
                    "pack_id": "earthquakes",
                    "source_name": "Earthquake events",
                    "data_type": "events",
                }
            return {}

        load_source_metadata_mock.side_effect = load_source_metadata_side_effect
        source_supports_aggregate_mode_mock.side_effect = lambda src: src.get("source_id") == "earthquakes_country_yearly"

        result = _build_metadata_guided_pack_aggregate_order(
            "how did earthquakes change over time in Japan",
            {
                "detected_source": {"pack_id": "earthquakes"},
                "location": {"iso3": "JPN"},
                "time": {"year_start": 2000, "year_end": 2010, "pattern_type": "trend"},
            },
        )

        self.assertIsNotNone(result)
        item = result["order"]["items"][0]
        self.assertEqual(item["source_id"], "earthquakes_country_yearly")
        self.assertEqual(item["metric"], "event_count")
        self.assertEqual(item["geo_level"], "admin_0")
        self.assertEqual(item["region"], "JPN")
        self.assertEqual(item["year_start"], 2000)
        self.assertEqual(item["year_end"], 2010)

    @patch("mapmover.runtime.order_taker_response.load_catalog", return_value={"sources": []})
    def test_build_metadata_guided_pack_aggregate_order_skips_non_time_series_queries(self, _load_catalog_mock):
        result = _build_metadata_guided_pack_aggregate_order(
            "show me the biggest earthquake in 2004",
            {
                "detected_source": {"pack_id": "earthquakes"},
                "time": {"year_start": 2004, "year_end": 2004},
            },
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
