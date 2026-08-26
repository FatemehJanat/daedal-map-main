import unittest
from pathlib import Path
from unittest.mock import patch

from mapmover import duckdb_helpers as helpers


class DuckdbProjectionRuntimeTests(unittest.TestCase):
    def test_filtered_event_rows_projects_requested_and_filter_columns(self):
        with patch.object(helpers, "duckdb", object()), \
             patch.object(helpers, "parquet_available", return_value=True), \
             patch.object(helpers, "path_to_uri", return_value="s3://bucket/events.parquet"), \
             patch.object(helpers, "parquet_columns", return_value={"event_id", "timestamp", "latitude", "longitude"}), \
             patch.object(helpers, "run_df", return_value=None) as run_df:
            helpers.select_filtered_event_rows(
                Path("events.parquet"),
                columns=["event_id", "latitude"],
                exact_filters={"event_id": "e1"},
                start="2026-01-01",
                limit=1,
            )

        sql = run_df.call_args.args[0]
        self.assertIn('SELECT "event_id", "latitude", "timestamp"', sql)
        self.assertNotIn("SELECT *", sql)
        self.assertIn('"event_id" = ?', sql)

    def test_exact_value_projection_can_bound_rows(self):
        with patch.object(helpers, "duckdb", object()), \
             patch.object(helpers, "parquet_available", return_value=True), \
             patch.object(helpers, "path_to_uri", return_value="s3://bucket/events.parquet"), \
             patch.object(helpers, "parquet_columns", return_value={"event_id", "name", "timestamp"}), \
             patch.object(helpers, "run_df", return_value=None) as run_df:
            helpers.select_rows_by_exact_value(
                Path("events.parquet"), "event_id", "e1",
                columns=["name"], order_by="timestamp", limit=1,
            )

        sql = run_df.call_args.args[0]
        self.assertIn('SELECT "name", "event_id", "timestamp"', sql)
        self.assertIn("LIMIT ?", sql)


if __name__ == "__main__":
    unittest.main()
