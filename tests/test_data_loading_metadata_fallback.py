import unittest
from unittest.mock import patch

from mapmover import data_loading


class SourceMetadataFallbackTests(unittest.TestCase):
    def test_cloud_metadata_failure_uses_embedded_catalog_contract(self):
        source_contract = {
            "source_id": "example_monthly_source",
            "path": "global/climate/example_monthly_source",
            "metrics": {"temperature_c": {"name": "Temperature"}},
            "routing_hints": {"query_aliases": ["example temperature"]},
        }
        data_loading._metadata_cache.pop("example_monthly_source", None)

        with patch("mapmover.data_loading.get_runtime_config", return_value={"runtime_mode": "cloud"}), patch(
            "mapmover.data_loading.load_full_catalog", return_value={"sources": [source_contract]}
        ), patch(
            "mapmover.data_loading._fetch_json_from_s3", side_effect=OSError("temporary R2 failure")
        ), patch("mapmover.data_loading.get_source_path"), patch(
            "mapmover.data_loading._allow_local_source_fallback", return_value=False
        ):
            result = data_loading.load_source_metadata("example_monthly_source")

        self.assertEqual(result["source_id"], "example_monthly_source")
        self.assertEqual(result["metrics"]["temperature_c"]["name"], "Temperature")
        self.assertEqual(result["routing_hints"]["query_aliases"], ["example temperature"])
        data_loading._metadata_cache.pop("example_monthly_source", None)


if __name__ == "__main__":
    unittest.main()
