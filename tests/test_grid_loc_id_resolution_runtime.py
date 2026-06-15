import unittest

from mapmover.runtime.grid_loc_id_resolution import (
    aggregate_grid_to_loc_ids,
    build_centered_grid_cell_rows,
    build_regular_grid_cell_rows,
    build_grid_target_overlaps,
    classify_grid_target_loc_id,
    is_eez_loc_id,
    is_water_body_loc_id,
    normalize_overlap_weights,
    project_loc_id_metrics_to_grid,
)


class GridLocIdResolutionRuntimeTests(unittest.TestCase):
    def test_build_regular_grid_cell_rows(self):
        rows = build_regular_grid_cell_rows(
            west=0.0,
            south=0.0,
            east=2.0,
            north=1.0,
            width=2,
            height=1,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["bbox"], [0.0, 0.0, 1.0, 1.0])
        self.assertEqual(rows[1]["bbox"], [1.0, 0.0, 2.0, 1.0])

    def test_build_centered_grid_cell_rows(self):
        rows = build_centered_grid_cell_rows(
            [{"cell_id": "a", "lon": 10.0, "lat": 20.0}],
            cell_width_deg=2.0,
            cell_height_deg=4.0,
        )
        self.assertEqual(rows[0]["bbox"], [9.0, 18.0, 11.0, 22.0])

    def test_classifies_admin_and_water_body_targets(self):
        self.assertEqual(classify_grid_target_loc_id("USA-VA-059"), "admin_2")
        self.assertEqual(classify_grid_target_loc_id("XOP"), "water_body")
        self.assertTrue(is_water_body_loc_id("XOP"))
        self.assertFalse(is_water_body_loc_id("USA"))

    def test_classifies_eez_marine_targets(self):
        # EEZ is a marine overlay namespace: a valid grid target, distinct from
        # both the admin spine and the X* water bodies.
        self.assertEqual(classify_grid_target_loc_id("EEZ-USA"), "marine_eez")
        self.assertEqual(classify_grid_target_loc_id("EEZ-ASM"), "marine_eez")
        self.assertEqual(classify_grid_target_loc_id("EEZ-MRGID-21801"), "marine_eez")
        self.assertTrue(is_eez_loc_id("EEZ-USA"))
        self.assertFalse(is_eez_loc_id("USA"))
        self.assertFalse(is_eez_loc_id("XOP"))

    def test_build_grid_target_overlaps_accepts_eez_target(self):
        cell_rows = [{"cell_id": "c1", "bbox": [0.0, 0.0, 1.0, 1.0]}]
        target_rows = [{"loc_id": "EEZ-USA", "bbox": [0.0, 0.0, 1.0, 1.0]}]
        overlaps = build_grid_target_overlaps(cell_rows, target_rows)
        self.assertEqual(len(overlaps), 1)
        self.assertEqual(str(overlaps.iloc[0]["target_kind"]), "marine_eez")

    def test_build_grid_target_overlaps_from_bboxes(self):
        cell_rows = [
            {"cell_id": "c1", "bbox": [0.0, 0.0, 1.0, 1.0]},
            {"cell_id": "c2", "bbox": [1.0, 0.0, 2.0, 1.0]},
        ]
        target_rows = [
            {"loc_id": "USA-VA-059", "bbox": [0.0, 0.0, 1.5, 1.0]},
            {"loc_id": "XOP", "bbox": [1.5, 0.0, 2.0, 1.0]},
        ]
        overlaps = build_grid_target_overlaps(cell_rows, target_rows)
        self.assertEqual(len(overlaps), 3)

        fairfax_c1 = overlaps[(overlaps["cell_id"] == "c1") & (overlaps["loc_id"] == "USA-VA-059")].iloc[0]
        self.assertAlmostEqual(float(fairfax_c1["cell_fraction"]), 1.0, places=6)

        fairfax_c2 = overlaps[(overlaps["cell_id"] == "c2") & (overlaps["loc_id"] == "USA-VA-059")].iloc[0]
        pacific_c2 = overlaps[(overlaps["cell_id"] == "c2") & (overlaps["loc_id"] == "XOP")].iloc[0]
        self.assertAlmostEqual(float(fairfax_c2["cell_fraction"]), 0.5, places=6)
        self.assertAlmostEqual(float(pacific_c2["cell_fraction"]), 0.5, places=6)
        self.assertEqual(str(pacific_c2["target_kind"]), "water_body")

    def test_aggregate_grid_to_loc_ids_weighted(self):
        cell_rows = [
            {"cell_id": "c1", "timestamp": "2026-06-01", "sst_c": 10.0},
            {"cell_id": "c2", "timestamp": "2026-06-01", "sst_c": 20.0},
        ]
        overlap_rows = [
            {"cell_id": "c1", "loc_id": "USA-VA-059", "cell_fraction": 1.0},
            {"cell_id": "c2", "loc_id": "USA-VA-059", "cell_fraction": 0.5},
            {"cell_id": "c2", "loc_id": "XOP", "cell_fraction": 0.5},
        ]
        out = aggregate_grid_to_loc_ids(
            cell_rows,
            overlap_rows,
            metric_columns=["sst_c"],
            time_columns=["timestamp"],
        )
        fairfax = out[out["loc_id"] == "USA-VA-059"].iloc[0]
        pacific = out[out["loc_id"] == "XOP"].iloc[0]
        self.assertAlmostEqual(float(fairfax["sst_c"]), (10.0 * 1.0 + 20.0 * 0.5) / 1.5, places=6)
        self.assertAlmostEqual(float(pacific["sst_c"]), 20.0, places=6)

    def test_aggregate_grid_to_loc_ids_supports_weighted_stats(self):
        cell_rows = [
            {"cell_id": "c1", "timestamp": "2026-06-01", "sst_c": 10.0},
            {"cell_id": "c2", "timestamp": "2026-06-01", "sst_c": 20.0},
            {"cell_id": "c3", "timestamp": "2026-06-01", "sst_c": 30.0},
        ]
        overlap_rows = [
            {"cell_id": "c1", "loc_id": "XOP", "cell_fraction": 1.0},
            {"cell_id": "c2", "loc_id": "XOP", "cell_fraction": 2.0},
            {"cell_id": "c3", "loc_id": "XOP", "cell_fraction": 1.0},
        ]
        out = aggregate_grid_to_loc_ids(
            cell_rows,
            overlap_rows,
            metric_columns=["sst_c"],
            time_columns=["timestamp"],
            metric_stats={"sst_c": ["min", "max", "p05", "p50", "p95"]},
        )
        pacific = out[out["loc_id"] == "XOP"].iloc[0]
        self.assertAlmostEqual(float(pacific["sst_c"]), 20.0, places=6)
        self.assertAlmostEqual(float(pacific["sst_c__min"]), 10.0, places=6)
        self.assertAlmostEqual(float(pacific["sst_c__max"]), 30.0, places=6)
        self.assertAlmostEqual(float(pacific["sst_c__p05"]), 10.0, places=6)
        self.assertAlmostEqual(float(pacific["sst_c__p50"]), 20.0, places=6)
        self.assertAlmostEqual(float(pacific["sst_c__p95"]), 30.0, places=6)

    def test_aggregate_grid_to_loc_ids_supports_weighted_sum(self):
        cell_rows = [
            {"cell_id": "c1", "timestamp": "2026-06-01", "people": 100.0},
            {"cell_id": "c2", "timestamp": "2026-06-01", "people": 80.0},
        ]
        overlap_rows = [
            {"cell_id": "c1", "loc_id": "USA-VA-059", "cell_fraction": 0.25},
            {"cell_id": "c2", "loc_id": "USA-VA-059", "cell_fraction": 0.50},
        ]
        out = aggregate_grid_to_loc_ids(
            cell_rows,
            overlap_rows,
            metric_columns=["people"],
            time_columns=["timestamp"],
            metric_aggregations={"people": "weighted_sum"},
        )
        fairfax = out[out["loc_id"] == "USA-VA-059"].iloc[0]
        self.assertAlmostEqual(float(fairfax["people"]), 65.0, places=6)

    def test_normalize_overlap_weights_by_cell(self):
        normalized = normalize_overlap_weights(
            [
                {"cell_id": "c1", "loc_id": "A", "cell_fraction": 0.25},
                {"cell_id": "c1", "loc_id": "B", "cell_fraction": 0.75},
            ],
            group_by="cell",
        )
        self.assertAlmostEqual(float(normalized.iloc[0]["normalized_weight"]), 0.25, places=6)
        self.assertAlmostEqual(float(normalized.iloc[1]["normalized_weight"]), 0.75, places=6)

    def test_project_loc_id_metrics_to_grid_weighted(self):
        cell_rows = [
            {"cell_id": "c1", "timestamp": "2026-06-01"},
            {"cell_id": "c2", "timestamp": "2026-06-01"},
        ]
        overlap_rows = [
            {"cell_id": "c1", "loc_id": "USA-VA-059", "cell_fraction": 1.0},
            {"cell_id": "c2", "loc_id": "USA-VA-059", "cell_fraction": 0.5},
            {"cell_id": "c2", "loc_id": "XOP", "cell_fraction": 0.5},
        ]
        loc_rows = [
            {"loc_id": "USA-VA-059", "timestamp": "2026-06-01", "risk": 4.0},
            {"loc_id": "XOP", "timestamp": "2026-06-01", "risk": 8.0},
        ]
        projected = project_loc_id_metrics_to_grid(
            cell_rows,
            overlap_rows,
            loc_rows,
            metric_columns=["risk"],
            time_columns=["timestamp"],
        )
        c1 = projected[projected["cell_id"] == "c1"].iloc[0]
        c2 = projected[projected["cell_id"] == "c2"].iloc[0]
        self.assertAlmostEqual(float(c1["risk"]), 4.0, places=6)
        self.assertAlmostEqual(float(c2["risk"]), 6.0, places=6)

    def test_project_loc_id_metrics_to_grid_supports_sum(self):
        cell_rows = [
            {"cell_id": "c2", "timestamp": "2026-06-01"},
        ]
        overlap_rows = [
            {"cell_id": "c2", "loc_id": "USA-VA-059", "cell_fraction": 0.5},
            {"cell_id": "c2", "loc_id": "XOP", "cell_fraction": 0.5},
        ]
        loc_rows = [
            {"loc_id": "USA-VA-059", "timestamp": "2026-06-01", "people": 100.0},
            {"loc_id": "XOP", "timestamp": "2026-06-01", "people": 80.0},
        ]
        projected = project_loc_id_metrics_to_grid(
            cell_rows,
            overlap_rows,
            loc_rows,
            metric_columns=["people"],
            time_columns=["timestamp"],
            metric_aggregations={"people": "sum"},
        )
        self.assertAlmostEqual(float(projected.iloc[0]["people"]), 90.0, places=6)


if __name__ == "__main__":
    unittest.main()
