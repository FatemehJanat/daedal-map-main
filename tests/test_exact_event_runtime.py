from __future__ import annotations

import unittest
from unittest.mock import patch

from mapmover.catalog_surface import get_catalog_surface_override
from mapmover.routes.disasters.related import (
    _classify_exact_event_identifier,
    _get_exact_event_candidates,
)


class ExactEventRuntimeTests(unittest.TestCase):
    def test_canonical_disaster_ids_route_to_their_pack(self) -> None:
        tsunami_packs, tsunami_strict = _classify_exact_event_identifier(
            "IHO1953-240001003-TSUN-TS000001"
        )
        wildfire_packs, wildfire_strict = _classify_exact_event_identifier(
            "USA-CA-FIRE-US-FIRE-EXAMPLE"
        )

        self.assertEqual(tsunami_packs, ["tsunamis"])
        self.assertTrue(tsunami_strict)
        self.assertEqual(wildfire_packs, ["wildfires"])
        self.assertTrue(wildfire_strict)

    def test_exact_event_candidates_use_api_catalog_surface(self) -> None:
        def load_catalog_for_current_surface():
            if get_catalog_surface_override() != "api":
                return {"sources": []}
            return {
                "sources": [
                    {
                        "source_id": "tsunamis_events",
                        "pack_id": "tsunamis",
                        "data_type": "events",
                        "path": "global/disasters/tsunamis/sources/tsunamis_events",
                    }
                ]
            }

        with patch(
            "mapmover.routes.disasters.related.load_catalog",
            side_effect=load_catalog_for_current_surface,
        ):
            candidates = _get_exact_event_candidates(
                "tsunamis",
                identifier_value="IHO1953-240001003-TSUN-TS000001",
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source_id"], "tsunamis_events")
        self.assertIsNone(get_catalog_surface_override())


if __name__ == "__main__":
    unittest.main()
