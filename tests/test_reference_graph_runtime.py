from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from mapmover.geometry_handlers import get_location_info
from mapmover.runtime.reference_exchange import loc_id_references, resolve_reference
from mapmover.runtime.reference_graph import (
    aliases_for_loc_id,
    identity,
    relationships_for_loc_id,
    where_is_geography_data,
)


class ReferenceGraphRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        pd.DataFrame([{
            "loc_id": "TST-A-001", "family": "test_sidechain", "native_id": "001",
            "name": "Test Area", "parent_loc_id": "", "admin_level": None,
            "namespace_release": "test_2026", "valid_from": "2026-01-01", "valid_to": "",
            "has_shape": True, "geometry_bank": "test/shapes.parquet",
            "geometry_status": "approved", "source_system": "Test Authority",
            "source_vintage": "2026",
        }, {
            "loc_id": "TST-B-002", "family": "test_sidechain", "native_id": "002",
            "name": "Related Area", "parent_loc_id": "", "admin_level": None,
            "namespace_release": "test_2026", "valid_from": "2026-01-01", "valid_to": "",
            "has_shape": False, "geometry_bank": "", "geometry_status": "identity_only",
            "source_system": "Test Authority", "source_vintage": "2026",
        }]).to_parquet(self.root / "identities.parquet", index=False)
        pd.read_parquet(self.root / "identities.parquet").to_parquet(
            self.root / "identity_versions.parquet", index=False
        )
        pd.DataFrame([{
            "reference_system": "test.code", "external_id": "001",
            "loc_id": "TST-A-001", "alias_type": "official_code",
            "source_system": "Test Authority", "source_vintage": "2026",
        }]).to_parquet(self.root / "aliases.parquet", index=False)
        pd.DataFrame([{
            "relationship_id": "TST-REL-1", "source_family": "test_sidechain",
            "source_id": "001", "source_loc_id": "TST-A-001", "source_name": "Test Area",
            "target_family": "test_sidechain", "target_id": "002",
            "target_loc_id": "TST-B-002", "target_name": "Related Area",
            "relationship_type": "spatial_overlap", "relationship_subtype": "test_overlap",
            "method": "measured_polygon_intersection", "authority": "Test Authority",
            "relationship_vintage": "2026", "valid_from": None, "valid_to": None,
            "intersection_area": 1.0, "source_area": 2.0, "target_area": 4.0,
            "source_area_share": 0.5, "target_area_share": 0.25,
            "rank_by_source_area": 1, "rank_by_target_area": 1, "is_primary": True,
            "primary_policy": "largest_overlap", "source_centroid_target_loc_id": "TST-B-002",
            "evidence_member_count": None, "area_crs": "EPSG:6933",
            "source_artifact": "test.parquet", "source_release": "test_2026",
            "target_release": "test_2026", "has_source_shape": True,
            "has_target_shape": False, "review_status": "generated_verified",
        }]).to_parquet(self.root / "relationships.parquet", index=False)
        (self.root / "metadata.json").write_text(json.dumps({
            "release_id": "test_candidate", "scope": "TST", "status": "complete",
        }), encoding="utf-8")
        (self.root / "completion_report.json").write_text(json.dumps({
            "status": "PASS", "totals": {"identities": 2, "relationships": 1},
        }), encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {
            "GEOGRAPHY_REFERENCE_GRAPH_ROOT": str(self.root),
            "DEPLOYMENT": "local", "STORAGE_MODE": "local",
        })
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    def test_reports_explicit_local_candidate(self) -> None:
        report = where_is_geography_data()
        self.assertTrue(report["ok"])
        self.assertEqual(report["mode"], "explicit_runtime_selection")
        self.assertEqual(report["release_id"], "test_candidate")
        self.assertFalse(report["local_data_uploaded"])

    def test_identity_alias_and_relationship_queries(self) -> None:
        self.assertEqual(identity("TST-A-001")["family"], "test_sidechain")
        self.assertEqual(aliases_for_loc_id("TST-A-001")[0]["external_id"], "001")
        self.assertEqual(relationships_for_loc_id("TST-A-001")[0]["target_loc_id"], "TST-B-002")

    def test_existing_reference_tools_use_graph_without_new_contract(self) -> None:
        resolved = resolve_reference(from_system="test.code", value="001", iso3="TST")
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["resolved_loc_id"], "TST-A-001")
        self.assertEqual(resolved["resolved_family"], "test_sidechain")
        references = loc_id_references("TST-A-001", limit_per_system=5)
        self.assertEqual(references["family"], "test_sidechain")
        self.assertTrue(any(item.get("relationship_id") == "TST-REL-1" for item in references["references"]))

    def test_loc_id_info_falls_back_to_graph_identity(self) -> None:
        info = get_location_info("TST-A-001")
        self.assertEqual(info["name"], "Test Area")
        self.assertEqual(info["family"], "test_sidechain")
        self.assertEqual(info["release_id"], "test_candidate")


if __name__ == "__main__":
    unittest.main()
