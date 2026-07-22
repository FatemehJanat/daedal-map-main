from __future__ import annotations

import unittest
from unittest.mock import patch

from mapmover.pack_state import build_overlay_tree_for_sources


class OverlayDisplayContractRuntimeTests(unittest.TestCase):
    def test_runtime_overlay_tree_preserves_authored_display_contract(self) -> None:
        source = {
            "source_id": "historical_storms",
            "pack_id": "storms",
            "scope": "global",
            "data_type": "events",
            "overlay": "disasters/storms",
            "geojson_shape": "event_point",
            "geometry_family": "event_point",
            "display_contract": {
                "family": "event_overlay",
                "rendering_model": "track_event",
                "popup_family": "disaster_popup",
            },
        }
        with (
            patch("mapmover.data_loading.load_source_metadata", return_value=None),
            patch("mapmover.data_loading.source_data_version", return_value=None),
        ):
            tree = build_overlay_tree_for_sources([source])

        entry = tree["disasters"]["children"]["storms"]["sources"][0]
        self.assertEqual(entry["geojson_shape"], "event_point")
        self.assertEqual(entry["geometry_family"], "event_point")
        self.assertEqual(entry["display_contract"], source["display_contract"])


if __name__ == "__main__":
    unittest.main()
