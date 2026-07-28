from __future__ import annotations

import unittest

from mapmover.runtime.source_response_semantics import append_source_caveats, collect_metric_caveats
from mapmover.runtime.postprocess_validation import _should_enforce_event_count_intent


class SourceResponseSemanticsRuntimeTests(unittest.TestCase):
    def test_selected_metric_adds_its_required_source_caveat(self) -> None:
        items = [{"_valid": True, "source_id": "tsunamis_events", "metric": "max_water_height_m"}]
        metadata = {
            "metrics": {
                "max_water_height_m": {
                    "response_semantics": {
                        "required_framing": "Reported local water-height observations are not necessarily open-ocean wave heights."
                    }
                }
            }
        }

        caveats = collect_metric_caveats(items, load_source_metadata_func=lambda _source_id: metadata)

        self.assertEqual(caveats, ["Reported local water-height observations are not necessarily open-ocean wave heights."])
        self.assertEqual(items[0]["source_caveats"], caveats)
        self.assertEqual(
            append_source_caveats("Showing tsunami events.", caveats),
            "Showing tsunami events. Reported local water-height observations are not necessarily open-ocean wave heights.",
        )

    def test_unselected_metric_does_not_add_a_caveat(self) -> None:
        items = [{"_valid": True, "source_id": "tsunamis_events", "metric": "event_count"}]
        metadata = {
            "metrics": {
                "max_water_height_m": {
                    "response_semantics": {"required_framing": "A caveat."}
                }
            }
        }

        self.assertEqual(collect_metric_caveats(items, load_source_metadata_func=lambda _source_id: metadata), [])

    def test_plain_event_listing_overrides_an_unrelated_model_metric(self) -> None:
        metadata = {"routing_hints": {"metric_aliases": {"events": "event_count", "deaths": "deaths"}}}
        self.assertTrue(_should_enforce_event_count_intent("Show tsunami events since 2000", metadata, "event_count"))
        self.assertFalse(_should_enforce_event_count_intent("Show tsunami events and deaths since 2000", metadata, "event_count"))


if __name__ == "__main__":
    unittest.main()
