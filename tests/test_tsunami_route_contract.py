from __future__ import annotations

import unittest

from mapmover.routes.disasters.tsunamis import get_tsunami_property_builders


class TsunamiRouteContractTests(unittest.TestCase):
    def test_preserves_prepared_marine_relationship_without_replacing_event_id(self) -> None:
        props = {
            name: builder({
                "event_id": "TS000001",
                "loc_id": "XOO-TSUN-TS000001",
                "marine_loc_id": "IHO1953-240001003",
                "physical_surface": "water",
            })
            for name, builder in get_tsunami_property_builders().items()
        }

        self.assertEqual(props["event_id"], "TS000001")
        self.assertEqual(props["loc_id"], "XOO-TSUN-TS000001")
        self.assertEqual(props["marine_loc_id"], "IHO1953-240001003")
        self.assertEqual(props["physical_surface"], "water")


if __name__ == "__main__":
    unittest.main()
