import unittest
from pathlib import Path

from mapmover.paths import DATA_ROOT
from mapmover.runtime.reference_geometry_bank import (
    _safe_bank_root,
    _safe_partition_path,
    load_reference_graph_geometry,
)


LAKE_SUPERIOR = "CGNDB-666A39DABA2A11D892E2080020A0F4C9"
CANVEC_BANK = DATA_ROOT / "geometry" / "countries" / "CAN" / "relationships" / "canada_canvec_water_bodies_1m"
CANADA_ADMIN_BANK = DATA_ROOT / "geometry" / "countries" / "CAN" / "geometry.parquet"
CANADA_DB_BANK = DATA_ROOT / "geometry" / "countries" / "CAN" / "dissemination_block" / "CAN-BC.parquet"


class ReferenceGeometryBankRuntimeTests(unittest.TestCase):
    def test_bank_paths_cannot_escape_data_root(self):
        self.assertIsNone(_safe_bank_root("../outside"))
        bank = _safe_bank_root("geometry/countries/CAN/relationships/example")
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

    @unittest.skipUnless(CANADA_ADMIN_BANK.is_file(), "Canada admin bank is not installed")
    def test_single_file_admin_bank_does_not_require_identity_versions_sidecar(self):
        frame = load_reference_graph_geometry(["CAN-AB"])
        self.assertEqual(len(frame), 1)
        row = frame.iloc[0]
        self.assertEqual(row["loc_id"], "CAN-AB")
        self.assertEqual(row["name"], "Alberta")
        self.assertIn(row["geometry"]["type"], {"Polygon", "MultiPolygon"})

    @unittest.skipUnless(CANADA_DB_BANK.is_file(), "Canada dissemination-block bank is not installed")
    def test_province_partitioned_admin_bank_does_not_require_identity_versions_sidecar(self):
        loc_id = "CAN-BC-5931-021-0221-067"
        frame = load_reference_graph_geometry([loc_id])
        self.assertEqual(len(frame), 1)
        row = frame.iloc[0]
        self.assertEqual(row["loc_id"], loc_id)
        self.assertEqual(row["admin_level"], 5)
        self.assertIn(row["geometry"]["type"], {"Polygon", "MultiPolygon"})


if __name__ == "__main__":
    unittest.main()
