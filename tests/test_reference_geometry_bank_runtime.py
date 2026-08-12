import unittest
from pathlib import Path

from mapmover.paths import DATA_ROOT
from mapmover.runtime.reference_geometry_bank import (
    _safe_bank_root,
    _safe_partition_path,
    load_reference_graph_geometry,
)


LAKE_SUPERIOR = "CGNDB-666A39DABA2A11D892E2080020A0F4C9"
CANVEC_BANK = DATA_ROOT / "countries" / "CAN" / "geometry" / "relationships" / "canada_canvec_water_bodies_1m"


class ReferenceGeometryBankRuntimeTests(unittest.TestCase):
    def test_bank_paths_cannot_escape_data_root(self):
        self.assertIsNone(_safe_bank_root("../outside"))
        bank = _safe_bank_root("countries/CAN/geometry/relationships/example")
        self.assertIsNotNone(bank)
        self.assertIsNone(_safe_partition_path(bank, "../../outside.parquet"))

    @unittest.skipUnless(
        (CANVEC_BANK / "shapes" / "water_bodies.parquet").is_file(),
        "Canada CanVec reference bank is not installed",
    )
    def test_lake_superior_loads_from_graph_owned_partition(self):
        frame = load_reference_graph_geometry([LAKE_SUPERIOR])
        self.assertEqual(len(frame), 1)
        row = frame.iloc[0]
        self.assertEqual(row["loc_id"], LAKE_SUPERIOR)
        self.assertEqual(row["name"], "Lake Superior")
        self.assertEqual(row["family"], "water_body")
        self.assertEqual(row["geometry"]["type"], "Polygon")
        self.assertLess(row["bbox_min_lon"], row["bbox_max_lon"])


if __name__ == "__main__":
    unittest.main()
