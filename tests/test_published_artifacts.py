from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mapmover import duckdb_helpers
from mapmover.runtime import published_artifacts


class PublishedArtifactTests(unittest.TestCase):
    def _config(self) -> dict:
        return {
            "cloud": {
                "bucket": "config-bucket",
                "prefix": "config-prefix",
                "endpoint_url": "https://config.example",
            }
        }

    def test_published_ref_owns_prefix_and_storage_configuration(self) -> None:
        env = {
            "S3_BUCKET": "runtime-bucket",
            "S3_PREFIX": "active-candidate",
            "S3_PUBLISHED_PREFIX": "published-v7",
            "S3_ENDPOINT_URL": "https://objects.example",
            "AWS_DEFAULT_REGION": "auto",
        }
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
            published_artifacts, "get_runtime_config", return_value=self._config()
        ):
            ref = published_artifacts.artifact_ref("geometry/catalog.json")

        self.assertEqual(ref.bucket, "runtime-bucket")
        self.assertEqual(ref.key, "published-v7/geometry/catalog.json")
        self.assertEqual(ref.uri, "s3://runtime-bucket/published-v7/geometry/catalog.json")
        self.assertEqual(ref.endpoint_url, "https://objects.example")

    def test_active_lane_preserves_active_prefix(self) -> None:
        with mock.patch.dict(os.environ, {
            "S3_BUCKET": "bucket", "S3_PREFIX": "candidate", "S3_PUBLISHED_PREFIX": "published"
        }, clear=True), mock.patch.object(
            published_artifacts, "get_runtime_config", return_value=self._config()
        ):
            ref = published_artifacts.artifact_ref("catalog.json", lane="active")

        self.assertEqual(ref.key, "candidate/catalog.json")

    def test_unsafe_relative_paths_are_rejected(self) -> None:
        with mock.patch.dict(os.environ, {"S3_BUCKET": "bucket"}, clear=True), mock.patch.object(
            published_artifacts, "get_runtime_config", return_value=self._config()
        ):
            for value in ("", ".", "../secret.json", "geometry/../../secret.json", "/secret.json", "C:/secret.json"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    published_artifacts.artifact_ref(value)

    def test_data_artifact_ref_requires_path_below_data_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ, {"S3_BUCKET": "bucket"}, clear=True
        ), mock.patch.object(published_artifacts, "get_runtime_config", return_value=self._config()):
            root = Path(temp_dir) / "data"
            inside = root / "countries" / "CAN" / "geometry.parquet"
            ref = published_artifacts.data_artifact_ref(inside, data_root=root)
            self.assertEqual(ref.relative_path, "countries/CAN/geometry.parquet")
            with self.assertRaises(ValueError):
                published_artifacts.data_artifact_ref(Path(temp_dir) / "outside.parquet", data_root=root)

    def test_json_read_uses_canonical_ref(self) -> None:
        response = {"Body": io.BytesIO(b'{"status":"ok"}')}
        client = mock.Mock()
        client.get_object.return_value = response
        with mock.patch.dict(os.environ, {
            "S3_BUCKET": "bucket", "S3_PUBLISHED_PREFIX": "published"
        }, clear=True), mock.patch.object(
            published_artifacts, "get_runtime_config", return_value=self._config()
        ), mock.patch.object(published_artifacts, "_object_store_client", return_value=client):
            payload = published_artifacts.read_artifact_json("graph/metadata.json")

        self.assertEqual(payload, {"status": "ok"})
        client.get_object.assert_called_once_with(
            Bucket="bucket", Key="published/graph/metadata.json"
        )

    def test_duckdb_path_translation_uses_shared_artifact_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(os.environ, {
            "S3_BUCKET": "bucket", "S3_PREFIX": "active"
        }, clear=True), mock.patch.object(
            published_artifacts, "get_runtime_config", return_value=self._config()
        ), mock.patch.object(duckdb_helpers, "is_cloud_mode", return_value=True), mock.patch.object(
            duckdb_helpers, "_allow_local_source_fallback", return_value=False
        ), mock.patch.object(duckdb_helpers, "_get_data_root", return_value=Path(temp_dir)):
            uri = duckdb_helpers.path_to_uri(Path(temp_dir) / "global" / "pack" / "data.parquet")

        self.assertEqual(uri, "s3://bucket/active/global/pack/data.parquet")


if __name__ == "__main__":
    unittest.main()
