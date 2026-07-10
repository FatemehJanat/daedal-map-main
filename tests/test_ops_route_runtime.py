import unittest

from mapmover.ops_route_runtime import load_or_create_ops_watch
from mapmover.ops_route_runtime import _public_default_ops_feeds


class DummyCache:
    def __init__(self):
        self.map_state = {}


class OpsRouteRuntimeTest(unittest.TestCase):
    def test_requested_sources_replace_cached_watch_feeds(self):
        cache = DummyCache()
        cache.map_state["ops_watch"] = {
            "watch_id": "watch_ops",
            "label": "Old watch",
            "geography": {"viewport": {}},
            "active_feeds": ["earthquakes", "wildfires_us_nifc"],
        }

        watch = load_or_create_ops_watch(
            cache=cache,
            session_id="ops",
            body={
                "watch_id": "watch_ops",
                "watch_context": {
                    "label": "Updated watch",
                    "sources": ["earthquakes", "hurricanes"],
                },
            },
            allowed_feeds=["earthquakes", "hurricanes_live", "wildfires_us_nifc"],
        )

        self.assertEqual(["earthquakes", "hurricanes_live"], watch["active_feeds"])
        self.assertEqual("Updated watch", watch["label"])
        self.assertEqual(watch, cache.map_state["ops_watch"])

    def test_account_default_load_resets_cached_narrow_watch(self):
        cache = DummyCache()
        cache.map_state["ops_watch"] = {
            "watch_id": "watch_ops",
            "label": "Ops deep link",
            "geography": {"viewport": {}},
            "active_feeds": ["earthquakes"],
        }

        watch = load_or_create_ops_watch(
            cache=cache,
            session_id="ops",
            body={
                "watch_id": "watch_ops",
                "watch_context": {
                    "label": "Ops watch",
                    "reset_to_allowed": True,
                },
            },
            allowed_feeds=["earthquakes", "hurricanes_live", "wildfires_us_nifc"],
        )

        self.assertEqual(["earthquakes", "hurricanes_live", "wildfires_us_nifc"], watch["active_feeds"])
        self.assertEqual("Ops watch", watch["label"])

    def test_report_without_reset_preserves_cached_narrow_watch(self):
        cache = DummyCache()
        cache.map_state["ops_watch"] = {
            "watch_id": "watch_ops",
            "label": "Ops deep link",
            "geography": {"viewport": {}},
            "active_feeds": ["earthquakes"],
        }

        watch = load_or_create_ops_watch(
            cache=cache,
            session_id="ops",
            body={
                "watch_id": "watch_ops",
                "watch_context": {
                    "label": "Ops watch",
                },
            },
            allowed_feeds=["earthquakes", "hurricanes_live", "wildfires_us_nifc"],
        )

        self.assertEqual(["earthquakes"], watch["active_feeds"])
        self.assertEqual("Ops deep link", watch["label"])

    def test_public_default_ops_feeds_exclude_currency(self):
        feeds = _public_default_ops_feeds()
        self.assertNotIn("currency", feeds)
        self.assertIn("earthquakes", feeds)
        self.assertIn("hurricanes_live", feeds)
        self.assertIn("noaa_ndbc", feeds)
        self.assertIn("ocean_sst", feeds)
        self.assertIn("usa_nws_alerts", feeds)


if __name__ == "__main__":
    unittest.main()
