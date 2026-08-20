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
from mapmover.runtime import reference_graph


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
        pd.DataFrame([{
            "partition_id": "test_sidechain", "family": "test_sidechain",
            "kind": "sidechain_identity", "path": str(self.root / "identities.parquet"),
            "sha256": "test", "row_count": 2, "selector": "",
            "strict_parent_source": False,
        }]).to_parquet(self.root / "identity_partitions.parquet", index=False)
        pd.DataFrame([{
            "partition_id": "test_sidechain", "family": "test_sidechain",
            "path": str(self.root / "aliases.parquet"), "sha256": "test", "row_count": 1,
        }]).to_parquet(self.root / "alias_partitions.parquet", index=False)
        pd.DataFrame([{
            "partition_id": "test_relationships", "semantic_type": "measured_spatial_overlap",
            "evidence_class": "test", "source_family": "test_sidechain",
            "target_family": "test_sidechain", "path": str(self.root / "relationships.parquet"),
            "sha256": "test", "index_path": "", "index_sha256": "", "row_count": 1,
            "payload_mode": "materialized_partition", "strict_parent": False, "succession": False,
        }]).to_parquet(self.root / "relationship_partitions.parquet", index=False)
        pd.DataFrame(columns=["partition_id", "family", "path", "sha256", "row_count"]).to_parquet(
            self.root / "shape_partitions.parquet", index=False
        )
        pd.DataFrame([{
            "family": "test_sidechain", "status": "identity_admitted", "identity_admitted": True,
        }]).to_parquet(self.root / "endpoint_families.parquet", index=False)
        pd.DataFrame([{
            "role": "test", "package_id": "test", "path": "test",
            "sha256": "test", "bytes": 0,
        }]).to_parquet(self.root / "source_manifests.parquet", index=False)
        (self.root / "manifest.json").write_text(json.dumps({
            "schema_version": "0.2.0", "graph_scope": "country", "country": "TST",
            "release_id": "test_candidate", "status": "PASS",
            "publication_status": "test", "completeness_status": "complete_declared_scope",
            "metrics": {"identities": 2, "relationships": 1},
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

    def test_relationship_query_avoids_global_order_by(self) -> None:
        statements: list[str] = []
        real_connection = reference_graph._connection

        class RecordingConnection:
            def __init__(self):
                self.connection = real_connection()

            def execute(self, statement, parameters=None):
                statements.append(statement)
                return self.connection.execute(statement, parameters or [])

            def close(self):
                self.connection.close()

        with mock.patch.object(reference_graph, "_connection", side_effect=RecordingConnection):
            rows = relationships_for_loc_id("TST-A-001")

        self.assertEqual(len(rows), 1)
        self.assertEqual(len(statements), 2)
        self.assertTrue(all("ORDER BY" not in statement.upper() for statement in statements))
        self.assertTrue(all("LIMIT ?" in statement.upper() for statement in statements))

    def test_existing_reference_tools_use_graph_without_new_contract(self) -> None:
        resolved = resolve_reference(from_system="test.code", value="001", iso3="TST")
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["resolved_loc_id"], "TST-A-001")
        self.assertEqual(resolved["resolved_family"], "test_sidechain")
        references = loc_id_references("TST-A-001", limit_per_system=5)
        self.assertEqual(references["family"], "test_sidechain")
        self.assertTrue(any(item.get("relationship_id") == "TST-REL-1" for item in references["references"]))

    def test_loc_id_info_falls_back_to_graph_identity(self) -> None:
        with mock.patch(
            "mapmover.geometry_handlers._get_selection_metadata_for_loc_id",
            side_effect=AssertionError("identity metadata must not hydrate geometry"),
        ):
            info = get_location_info("TST-A-001")
        self.assertEqual(info["name"], "Test Area")
        self.assertEqual(info["family"], "test_sidechain")
        self.assertEqual(info["release_id"], "test_candidate")

    def test_graph_sql_path_uses_cloud_path_translation(self) -> None:
        with mock.patch.object(reference_graph, "path_to_uri", return_value="s3://bucket/published/graph.parquet"):
            self.assertEqual(
                reference_graph._sql_path(self.root / "identities.parquet"),
                "s3://bucket/published/graph.parquet",
            )

    def test_country_graph_precedes_global_fallback(self) -> None:
        country = self.root / "country"
        global_root = self.root / "global"
        with mock.patch.object(reference_graph, "reference_graph_roots", return_value={"TST": country}), \
             mock.patch.object(reference_graph, "global_reference_graph_root", return_value=global_root):
            self.assertEqual(
                reference_graph.graph_roots_for_loc_id("TST-A-001"),
                [country, global_root],
            )
            self.assertEqual(
                reference_graph.graph_roots_for_loc_id("ZZZ-G1"),
                [global_root],
            )


if __name__ == "__main__":
    unittest.main()
