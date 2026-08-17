from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from mapmover import foundation_helpers


class FoundationGeometryCloudTests(unittest.TestCase):
    def setUp(self) -> None:
        foundation_helpers._GLOBAL_COUNTRIES_CACHE = None
        foundation_helpers._GLOBAL_COUNTRY_DISPLAY_CACHE = None

    def tearDown(self) -> None:
        foundation_helpers._GLOBAL_COUNTRIES_CACHE = None
        foundation_helpers._GLOBAL_COUNTRY_DISPLAY_CACHE = None
        foundation_helpers._COUNTRY_CROSSWALK_CACHE.clear()

    def test_country_crosswalk_reads_canonical_country_geometry_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            path = root / "USA" / "crosswalk.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"sub_admin_levels": {"admin_3": {"folder": "tract"}}}),
                encoding="utf-8",
            )
            with mock.patch.object(
                foundation_helpers, "COUNTRY_GEOMETRY_DIR", root
            ), mock.patch.object(
                foundation_helpers, "prefer_local_geometry_reads", return_value=True
            ):
                payload = foundation_helpers.load_country_crosswalk("USA")

        self.assertEqual(payload["sub_admin_levels"]["admin_3"]["folder"], "tract")

    def test_cloud_display_frame_merges_published_supplemental_admin0(self) -> None:
        supplemental = pd.DataFrame([{
            "loc_id": "MNP",
            "name": "Northern Mariana Islands",
            "source_system": "test",
            "geometry": '{"type":"Polygon","coordinates":[[[145,19],[146,19],[146,20],[145,20],[145,19]]]}',
        }])
        parquet = io.BytesIO()
        supplemental.to_parquet(parquet, index=False)
        global_csv = (
            b"loc_id,name,geometry,bbox_min_lon,bbox_min_lat,bbox_max_lon,bbox_max_lat\n"
            b"USA,United States,,,,,\n"
            b"MNP,Northern Mariana Islands (shallow),,,,,\n"
        )
        display = pd.DataFrame([
            {
                "loc_id": "USA",
                "name": "United States",
                "geometry": "{}",
                "bbox_min_lon": -125.0,
                "bbox_min_lat": 24.0,
                "bbox_max_lon": -66.0,
                "bbox_max_lat": 49.0,
            },
            {
                "loc_id": "MNP",
                "name": "Northern Mariana Islands (display)",
                "geometry": "{}",
                "bbox_min_lon": 145.0,
                "bbox_min_lat": 14.0,
                "bbox_max_lon": 146.0,
                "bbox_max_lat": 21.0,
            },
        ])
        display_parquet = io.BytesIO()
        display.to_parquet(display_parquet, index=False)

        def artifact_bytes(path: str, **_kwargs):
            if path == "geometry/display/admin_0.parquet":
                return display_parquet.getvalue()
            if path == "geometry/global.csv":
                return global_csv
            if path == "geometry/supplemental/admin0_territories.parquet":
                return parquet.getvalue()
            raise AssertionError(path)

        with tempfile.TemporaryDirectory() as temp_name, mock.patch.object(
            foundation_helpers, "GEOMETRY_DIR", Path(temp_name) / "not-installed"
        ), mock.patch.object(
            foundation_helpers, "is_cloud_mode", return_value=True
        ), mock.patch.object(
            foundation_helpers, "read_artifact_bytes", side_effect=artifact_bytes
        ), mock.patch.object(
            foundation_helpers,
            "read_artifact_json",
            return_value={
                "license_review_status": "approved",
                "usable_for_derivation": True,
                "overlap_override_loc_ids": ["MNP"],
            },
        ), mock.patch.object(foundation_helpers, "_reference_country_codes", return_value={"USA", "MNP"}):
            frame = foundation_helpers.load_global_country_display_frame()

        self.assertEqual({"USA", "MNP"}, set(frame["loc_id"]))
        self.assertEqual(2, int((frame["loc_id"] == "MNP").sum()))
        mnp = frame.loc[(frame["loc_id"] == "MNP") & frame["bbox_min_lon"].notna()].iloc[0]
        self.assertEqual(145.0, mnp["bbox_min_lon"])
        self.assertEqual(146.0, mnp["bbox_max_lon"])

    def test_local_display_frame_prefers_display_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            (root / "display").mkdir()
            pd.DataFrame([{"loc_id": "DSP", "name": "Display"}]).to_parquet(
                root / "display" / "admin_0.parquet",
                index=False,
            )
            pd.DataFrame([{"loc_id": "EXACT", "name": "Exact"}]).to_csv(
                root / "global.csv",
                index=False,
            )
            with mock.patch.object(
                foundation_helpers, "GEOMETRY_DIR", root
            ), mock.patch.object(
                foundation_helpers, "_load_supplemental_admin0_frame",
                return_value=pd.DataFrame(),
            ):
                frame = foundation_helpers.load_global_country_display_frame()

        self.assertEqual(["DSP"], frame["loc_id"].tolist())

    def test_exact_global_frame_does_not_use_display_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            (root / "display").mkdir()
            pd.DataFrame([{"loc_id": "DSP", "name": "Display"}]).to_parquet(
                root / "display" / "admin_0.parquet",
                index=False,
            )
            pd.DataFrame([{"loc_id": "EXACT", "name": "Exact"}]).to_csv(
                root / "global.csv",
                index=False,
            )
            with mock.patch.object(
                foundation_helpers, "GEOMETRY_DIR", root
            ), mock.patch.object(
                foundation_helpers, "_load_supplemental_admin0_frame",
                return_value=pd.DataFrame(),
            ):
                frame = foundation_helpers.load_global_countries_frame()

        self.assertEqual(["EXACT"], frame["loc_id"].tolist())


if __name__ == "__main__":
    unittest.main()
