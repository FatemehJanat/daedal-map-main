import unittest

from mapmover.runtime.geography_resolver import resolve_geography


class GeographyResolverRuntimeTests(unittest.TestCase):
    def test_bare_country_names_outrank_same_name_seas(self):
        cases = {
            "Iceland": "ISL",
            "Japan": "JPN",
            "Greenland": "GRL",
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                resolved = resolve_geography(query=query)
                self.assertEqual(resolved.get("outcome"), "ok")
                self.assertEqual(resolved.get("loc_ids"), [expected])
                self.assertEqual(resolved.get("locations", [{}])[0].get("family"), "admin_0")

    def test_explicit_named_seas_still_resolve_to_water_geometry(self):
        for query in ["Sea of Japan", "Japan Sea", "Mediterranean Sea"]:
            with self.subTest(query=query):
                resolved = resolve_geography(query=query)
                self.assertEqual(resolved.get("outcome"), "ok")
                self.assertEqual(resolved.get("locations", [{}])[0].get("family"), "water_body")


if __name__ == "__main__":
    unittest.main()
