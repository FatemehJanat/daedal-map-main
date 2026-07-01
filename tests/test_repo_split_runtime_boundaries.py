from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from mapmover import data_loading
from mapmover.private_mcp_loader import DEFAULT_PRIVATE_MCP_BUNDLE_ROOTS
from mapmover.runtime_env_files import runtime_env_file_candidates


class RepoSplitRuntimeBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_extra_env_files = os.environ.get("COUNTY_MAP_EXTRA_ENV_FILES")
        self._original_catalog_root = os.environ.get("COUNTY_MAP_API_CATALOG_OUTPUT_ROOT")

    def tearDown(self) -> None:
        if self._original_extra_env_files is None:
            os.environ.pop("COUNTY_MAP_EXTRA_ENV_FILES", None)
        else:
            os.environ["COUNTY_MAP_EXTRA_ENV_FILES"] = self._original_extra_env_files

        if self._original_catalog_root is None:
            os.environ.pop("COUNTY_MAP_API_CATALOG_OUTPUT_ROOT", None)
        else:
            os.environ["COUNTY_MAP_API_CATALOG_OUTPUT_ROOT"] = self._original_catalog_root

    def test_runtime_env_candidates_do_not_include_private_repo_by_default(self) -> None:
        os.environ.pop("COUNTY_MAP_EXTRA_ENV_FILES", None)
        workspace_root = Path(r"C:\workspace\global map")

        candidates = runtime_env_file_candidates(workspace_root)
        candidate_texts = [str(path) for path in candidates]

        self.assertIn(str(workspace_root / "county-map" / ".env"), candidate_texts)
        self.assertIn(str(workspace_root / ".env"), candidate_texts)
        self.assertNotIn(str(workspace_root / "county-map-private" / ".env"), candidate_texts)

    def test_runtime_env_candidates_allow_explicit_extra_files(self) -> None:
        workspace_root = Path(r"C:\workspace\global map")
        private_env = workspace_root / "county-map-private" / ".env"
        os.environ["COUNTY_MAP_EXTRA_ENV_FILES"] = str(private_env)

        candidates = runtime_env_file_candidates(workspace_root)

        self.assertIn(private_env, candidates)

    def test_private_mcp_loader_defaults_allow_hosted_private_bundle_roots_only(self) -> None:
        root_texts = {str(path) for path in DEFAULT_PRIVATE_MCP_BUNDLE_ROOTS}

        self.assertIn(str(Path("/app/private_mcp_tools")), root_texts)
        self.assertIn(str(Path("/app/county-map-private/tools")), root_texts)
        self.assertFalse(any(r"C:\workspace\global map\county-map-private" in text for text in root_texts))

    def test_api_catalog_output_root_uses_env_override(self) -> None:
        override = r"C:\tmp\api-catalog-output"
        os.environ["COUNTY_MAP_API_CATALOG_OUTPUT_ROOT"] = override

        self.assertEqual(data_loading._api_catalog_output_root(), Path(override))

    def test_api_pack_detail_hydration_strips_private_browser_artifact_paths(self) -> None:
        payload = {
            "pack_id": "demo_pack",
            "sources": [
                {
                    "source_id": "demo_source",
                    "browser_artifact": {"storage_key": "stale/value.json.gz"},
                }
            ],
        }
        metadata = {
            "browser_artifact": {
                "storage_key": "published/browser_artifacts/sources/demo_source/runtime_snapshot_v1.json.gz",
                "sha256": "abc123",
                "transfer_bytes": 10,
                "stored_bytes": 10,
                "expanded_bytes": 20,
                "generated_at": "2026-06-30T00:00:00Z",
                "local_artifact_path": "/opt/global-map/repo/county-map-private/build/browser_artifacts/output/published/browser_artifacts/sources/demo_source/runtime_snapshot_v1.json.gz",
            }
        }

        with mock.patch("mapmover.data_loading.load_source_metadata", return_value=metadata):
            hydrated = data_loading._hydrate_api_pack_detail_from_source_metadata(payload)

        source = hydrated["sources"][0]
        artifact = source["browser_artifact"]
        self.assertEqual(
            artifact["storage_key"],
            "published/browser_artifacts/sources/demo_source/runtime_snapshot_v1.json.gz",
        )
        self.assertNotIn("local_artifact_path", artifact)


if __name__ == "__main__":
    unittest.main()
