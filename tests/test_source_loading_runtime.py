import unittest
from pathlib import Path

import pandas as pd

from mapmover.execution.source_loading import load_source_data


class SourceLoadingRuntimeTests(unittest.TestCase):
    def test_load_source_data_tries_geometry_prefix_before_local_prefix(self):
        calls = []

        def select_rows(parquet_path, **kwargs):
            prefix = ((kwargs.get("starts_with_filters") or {}).get("loc_id"))
            calls.append(prefix)
            if prefix == "USA-G123331":
                return pd.DataFrame([{"loc_id": "USA-G123331-G200759", "population": 1}])
            return pd.DataFrame(columns=["loc_id", "population"])

        df, metadata = load_source_data(
            "worldpop",
            loc_id_prefix="USA-CA",
            columns=["population"],
            get_source_path_func=lambda _source_id: Path("fake/worldpop"),
            load_source_metadata_func=lambda _source_id: {"files": {"data": {"name": "population.parquet"}}},
            candidate_parquet_paths_func=lambda _source_dir, _metadata: [Path("fake/worldpop/population.parquet")],
            is_cloud_mode_func=lambda: True,
            path_to_uri_func=lambda path: f"s3://bucket/{path.as_posix()}",
            select_rows_func=select_rows,
            logger=type("Logger", (), {"info": lambda *args, **kwargs: None})(),
        )

        self.assertEqual(calls, ["USA-G123331"])
        self.assertEqual(len(df), 1)
        self.assertEqual(metadata["files"]["data"]["name"], "population.parquet")

    def test_load_source_data_falls_back_to_original_local_prefix(self):
        calls = []

        def select_rows(parquet_path, **kwargs):
            prefix = ((kwargs.get("starts_with_filters") or {}).get("loc_id"))
            calls.append(prefix)
            if prefix == "USA-VA":
                return pd.DataFrame([{"loc_id": "USA-VA-059", "metric": 1}])
            return pd.DataFrame(columns=["loc_id", "metric"])

        df, _metadata = load_source_data(
            "fema_nri",
            loc_id_prefix="USA-VA",
            columns=["metric"],
            get_source_path_func=lambda _source_id: Path("fake/fema"),
            load_source_metadata_func=lambda _source_id: {"files": {"data": {"name": "nri.parquet"}}},
            candidate_parquet_paths_func=lambda _source_dir, _metadata: [Path("fake/fema/nri.parquet")],
            is_cloud_mode_func=lambda: True,
            path_to_uri_func=lambda path: f"s3://bucket/{path.as_posix()}",
            select_rows_func=select_rows,
            logger=type("Logger", (), {"info": lambda *args, **kwargs: None})(),
        )

        self.assertEqual(calls, ["USA-G125186", "USA-VA"])
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["loc_id"], "USA-VA-059")


if __name__ == "__main__":
    unittest.main()
