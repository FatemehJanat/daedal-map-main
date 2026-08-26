from pathlib import Path
from unittest.mock import patch

import pandas as pd

from mapmover.runtime import admin_spine_query


def test_cloud_manifest_check_follows_the_selected_active_lane() -> None:
    payload = {
        "status": "PASS", "country": "GBR",
        "layout_policy": "national_admin_0_3_plus_admin_1_owned_deep",
    }
    with patch.object(admin_spine_query, "read_artifact_json", return_value=payload) as reader:
        admin_spine_query._published_layout_manifest_available.cache_clear()
        assert admin_spine_query._published_layout_manifest_available(
            "GBR", "geometry/countries/GBR/releases/geometry/r/runtime/admin_spine/manifest.json"
        ) is True
    reader.assert_called_once_with(
        "geometry/countries/GBR/releases/geometry/r/runtime/admin_spine/manifest.json",
        lane="active",
    )


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


def test_exact_id_load_opens_only_shallow_and_requested_admin1_shards() -> None:
    opened_paths = []

    class Result:
        def __init__(self, frame):
            self.frame = frame

        def fetchdf(self):
            return self.frame

    class Connection:
        def execute(self, _sql, parameters=None):
            if parameters is None:
                return self
            path = parameters[0]
            opened_paths.append(path)
            loc_ids = parameters[1:]
            return Result(pd.DataFrame({"loc_id": loc_ids, "name": loc_ids}))

        def close(self):
            pass

    with (
        patch.object(admin_spine_query, "layout_available", return_value=True),
        patch.object(admin_spine_query, "layout_root", return_value=Path("layout")),
        patch.object(admin_spine_query, "is_cloud_mode", return_value=True),
        patch.object(admin_spine_query, "path_to_uri", side_effect=lambda path: path.as_posix()),
        patch.object(admin_spine_query, "_connection", return_value=Connection()),
    ):
        result = admin_spine_query.load_rows_by_loc_ids(
            "USA",
            ["USA-SD-019", "USA-SD-019-967600-1-023", "USA-CA-037-001-1-001"],
            columns=["name"],
        )

    assert opened_paths == [
        "layout/admin_0_3.parquet",
        "layout/deep/USA-SD.parquet",
        "layout/deep/USA-CA.parquet",
    ]
    assert result["loc_id"].tolist() == [
        "USA-SD-019",
        "USA-SD-019-967600-1-023",
        "USA-CA-037-001-1-001",
    ]
