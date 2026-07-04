import unittest

from mapmover.ops_route_runtime import load_or_create_ops_watch


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
            allowed_feeds=["earthquakes", "hurricanes", "wildfires_us_nifc"],
        )

        self.assertEqual(["earthquakes", "hurricanes"], watch["active_feeds"])
        self.assertEqual("Updated watch", watch["label"])
        self.assertEqual(watch, cache.map_state["ops_watch"])


if __name__ == "__main__":
    unittest.main()
