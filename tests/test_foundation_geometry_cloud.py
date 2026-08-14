from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from mapmover import foundation_helpers


class FoundationGeometryCloudTests(unittest.TestCase):
    def setUp(self) -> None:
        foundation_helpers._GLOBAL_COUNTRIES_CACHE = None

    def tearDown(self) -> None:
        foundation_helpers._GLOBAL_COUNTRIES_CACHE = None

    def test_cloud_global_frame_merges_published_supplemental_admin0(self) -> None:
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

        def artifact_bytes(path: str, **_kwargs):
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
            frame = foundation_helpers.load_global_countries_frame()

        self.assertEqual({"USA", "MNP"}, set(frame["loc_id"]))
        self.assertEqual(2, int((frame["loc_id"] == "MNP").sum()))
        mnp = frame.loc[(frame["loc_id"] == "MNP") & frame["bbox_min_lon"].notna()].iloc[0]
        self.assertEqual(145.0, mnp["bbox_min_lon"])
        self.assertEqual(146.0, mnp["bbox_max_lon"])


if __name__ == "__main__":
    unittest.main()
