from pathlib import Path
from unittest.mock import patch

from mapmover.runtime import admin_spine_query


def test_cloud_layout_availability_comes_from_published_catalog() -> None:
    catalog = {
        "country_profiles": [{
            "country_code": "NZL", "release_status": "published",
            "query_layout_manifest": "geometry/countries/NZL/releases/geometry/nzl_geometry_1/runtime/admin_spine/manifest.json",
        }],
    }
    with (
        patch.object(admin_spine_query, "is_cloud_mode", return_value=True),
        patch.object(admin_spine_query, "load_geometry_catalog", return_value=catalog),
        patch.object(admin_spine_query, "_published_layout_manifest_available", return_value=True),
    ):
        admin_spine_query.clear_admin_spine_query_cache()
        assert admin_spine_query.layout_available("NZL") is True
        assert admin_spine_query.layout_available("FRA") is False


def test_cloud_layout_availability_fails_closed_without_catalog_activation() -> None:
    with (
        patch.object(admin_spine_query, "is_cloud_mode", return_value=True),
        patch.object(admin_spine_query, "load_geometry_catalog", return_value={"country_profiles": []}),
        patch.object(admin_spine_query, "_published_layout_manifest_available", return_value=True) as fallback,
    ):
        admin_spine_query.clear_admin_spine_query_cache()
        assert admin_spine_query.layout_available("NZL") is False
    fallback.assert_not_called()


def test_cloud_metadata_uses_object_store_uri() -> None:
    class Connection:
        def execute(self, _sql, parameters):
            self.parameters = parameters
            return self

        def fetchall(self):
            return []

    connection = Connection()
    with patch.object(admin_spine_query, "path_to_uri", return_value="s3://bucket/published/layout.parquet"):
        admin_spine_query._metadata(connection, Path("layout.parquet"), 1.0, 2.0)
    assert connection.parameters[0] == "s3://bucket/published/layout.parquet"
