from pathlib import Path
from unittest.mock import patch

from mapmover.runtime import admin_spine_query


def test_cloud_layout_availability_comes_from_published_catalog() -> None:
    catalog = {
        "geometry_banks": [{
            "query_layout_manifest": "geometry/countries/NZL/admin_spine/manifest.json",
        }],
    }
    with (
        patch.object(admin_spine_query, "is_cloud_mode", return_value=True),
        patch.object(admin_spine_query, "load_geometry_catalog", return_value=catalog),
        patch.object(admin_spine_query, "_published_layout_manifest_available", return_value=False),
    ):
        assert admin_spine_query.layout_available("NZL") is True
        assert admin_spine_query.layout_available("FRA") is False


def test_cloud_layout_availability_falls_back_to_published_manifest() -> None:
    with (
        patch.object(admin_spine_query, "is_cloud_mode", return_value=True),
        patch.object(admin_spine_query, "load_geometry_catalog", return_value={"geometry_banks": []}),
        patch.object(admin_spine_query, "_published_layout_manifest_available", return_value=True) as fallback,
    ):
        assert admin_spine_query.layout_available("NZL") is True
    fallback.assert_called_once_with(
        "NZL", "geometry/countries/NZL/admin_spine/manifest.json"
    )


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
