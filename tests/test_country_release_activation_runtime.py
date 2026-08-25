from pathlib import Path
from unittest.mock import patch

import pandas as pd

from mapmover.runtime import geometry_catalog, reference_graph


def test_cloud_geometry_catalog_follows_selected_active_lane() -> None:
    with patch.object(geometry_catalog, "read_artifact_json", return_value={"schema_version": "1.1.1"}) as reader:
        assert geometry_catalog._fetch_geometry_catalog_from_s3() == {"schema_version": "1.1.1"}
    reader.assert_called_once_with("geometry/geometry_catalog.json", lane="active")


def test_cloud_reference_graph_discovery_is_catalog_owned(tmp_path: Path) -> None:
    catalog = {"country_profiles": [{
        "country_code": "GBR",
        "release_status": "published",
        "reference_graph_manifest": (
            "geometry/countries/GBR/releases/geometry/gbr_geometry_1_0_0/"
            "runtime/reference_graph/manifest.json"
        ),
    }]}
    with (
        patch.object(reference_graph, "load_geometry_catalog", return_value=catalog),
        patch.object(reference_graph, "_missing_graph_files", return_value=()),
    ):
        roots = reference_graph._discover_roots(str(tmp_path), "", True)
    assert roots == ((
        "GBR",
        str((tmp_path / catalog["country_profiles"][0]["reference_graph_manifest"]).parent.resolve()),
    ),)


def test_cloud_reference_graph_does_not_scan_legacy_roots(tmp_path: Path) -> None:
    legacy = tmp_path / "geometry/countries/GBR/reference_graph"
    legacy.mkdir(parents=True)
    with patch.object(reference_graph, "load_geometry_catalog", return_value={"country_profiles": []}):
        assert reference_graph._discover_roots(str(tmp_path), "", True) == ()


def test_explicit_operator_graph_override_wins_in_cloud_mode(tmp_path: Path) -> None:
    override = tmp_path / "isolated/GBR/reference_graph"
    override.mkdir(parents=True)
    with patch.object(reference_graph, "_country_for_root", return_value="GBR"):
        assert reference_graph._discover_roots(str(tmp_path), str(override), True) == (
            ("GBR", str(override.resolve())),
        )


def test_cloud_partition_index_is_read_through_shared_artifact_seam(tmp_path: Path) -> None:
    root = tmp_path / "geometry/countries/GBR/releases/geometry/r/runtime/reference_graph"
    partition = tmp_path / "geometry/countries/GBR/relationships/f/identities.parquet"
    frame = pd.DataFrame({"path": [str(partition.relative_to(tmp_path)).replace("\\", "/")]})
    with (
        patch.object(reference_graph, "DATA_ROOT", tmp_path),
        patch.object(reference_graph, "is_cloud_mode", return_value=True),
        patch.object(reference_graph, "select_rows", return_value=frame) as reader,
    ):
        paths = reference_graph._partition_paths(root, "identities")
    assert paths == [partition]
    reader.assert_called_once_with(root / "identity_partitions.parquet", columns=["path"])


def test_identities_fail_closed_before_duckdb_when_graph_has_no_partitions() -> None:
    with (
        patch.object(reference_graph, "reference_graph_available", return_value=True),
        patch.object(reference_graph, "_table_source", return_value=""),
        patch.object(reference_graph, "_connection") as connection,
    ):
        assert reference_graph.identities(["AUS-NSW-117-03"]) == []
    connection.assert_not_called()
