import unittest

from mapmover.runtime.geography_reference import (
    build_crosswalk_maps,
    canonicalize_loc_id,
    translate_geometry_id_to_local_id,
    translate_loc_id_to_geometry_id,
)


class LocIdRuntimeTests(unittest.TestCase):
    def test_admin1_bridge_maps_to_geometry_id(self):
        self.assertEqual(
            translate_loc_id_to_geometry_id("USA-VA"),
            "USA-G125186",
        )

    def test_admin2_bridge_maps_to_geometry_id(self):
        self.assertEqual(
            translate_loc_id_to_geometry_id("USA-VA-059"),
            "USA-G125186-G215213",
        )

    def test_reverse_bridge_maps_geometry_id_to_canonical_local_id(self):
        self.assertEqual(
            translate_geometry_id_to_local_id("USA-G125186-G215213"),
            "USA-VA-059",
        )

    def test_deprecated_legacy_t_formats_are_not_normalized(self):
        legacy = "USA-VA-T51059452400"
        self.assertEqual(canonicalize_loc_id(legacy), legacy)
        self.assertEqual(translate_loc_id_to_geometry_id(legacy), legacy)

    def test_crosswalk_maps_include_admin1_and_admin2_entries(self):
        local_to_geo, geo_to_local = build_crosswalk_maps(
            {
                "mappings": {"USA-VA": "USA-G125186"},
                "admin_2_fips": {"USA-VA-059": "USA-G125186-G215213"},
            }
        )
        self.assertEqual(local_to_geo["USA-VA"], "USA-G125186")
        self.assertEqual(local_to_geo["USA-VA-059"], "USA-G125186-G215213")
        self.assertEqual(geo_to_local["USA-G125186"], "USA-VA")
        self.assertEqual(geo_to_local["USA-G125186-G215213"], "USA-VA-059")


if __name__ == "__main__":
    unittest.main()
