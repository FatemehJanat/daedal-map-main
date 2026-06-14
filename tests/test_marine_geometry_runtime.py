import unittest

from mapmover.runtime.marine_geometry import (
    EEZ_PATH,
    WATER_BODIES_PATH,
    has_marine_geometry,
    is_marine_loc_id,
    load_marine_geometry,
    marine_bank_for_loc_id,
    resolve_marine_geometry_source,
)


class MarineGeometryRuntimeTests(unittest.TestCase):
    def test_classification(self):
        self.assertTrue(is_marine_loc_id("EEZ-USA"))
        self.assertTrue(is_marine_loc_id("EEZ-MRGID-21801"))
        self.assertTrue(is_marine_loc_id("XSG"))
        self.assertFalse(is_marine_loc_id("USA"))
        self.assertFalse(is_marine_loc_id("USA-CA-037"))
        self.assertFalse(is_marine_loc_id(""))

    def test_bank_routing(self):
        self.assertEqual(marine_bank_for_loc_id("EEZ-USA"), EEZ_PATH)
        self.assertEqual(marine_bank_for_loc_id("EEZ-ASM"), EEZ_PATH)
        self.assertEqual(marine_bank_for_loc_id("XOP"), WATER_BODIES_PATH)
        self.assertIsNone(marine_bank_for_loc_id("USA"))

    def test_resolve_source(self):
        self.assertEqual(resolve_marine_geometry_source("EEZ-USA")["marine_kind"], "marine_eez")
        self.assertEqual(resolve_marine_geometry_source("XSG")["marine_kind"], "water_body")
        self.assertIsNone(resolve_marine_geometry_source("USA")["parquet_file"])

    @unittest.skipUnless(has_marine_geometry(), "marine geometry banks not present locally")
    def test_load_geometry_for_loc_ids(self):
        df = load_marine_geometry(["EEZ-USA", "XSG"])
        ids = set(df["loc_id"])
        self.assertIn("EEZ-USA", ids)
        self.assertIn("XSG", ids)
        self.assertTrue((df["geometry"].astype(str).str.len() > 0).all())

    @unittest.skipUnless(has_marine_geometry(), "marine geometry banks not present locally")
    def test_eez_only_query_skips_water_body_bank(self):
        df = load_marine_geometry(["EEZ-USA"])
        self.assertEqual(set(df["loc_id"]), {"EEZ-USA"})


if __name__ == "__main__":
    unittest.main()
