import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import CRS, Transformer
from shapely.geometry import box
from shapely.ops import transform as transform_geometry

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

    def test_geometry_loc_id_fetches_retired_shape_for_canonical_identity(self):
        canonical_id = "CAN-ON-PLACE-NEW"
        retired_id = "CAN-PLACE-OLD"
        identity_rows = [{
            "loc_id": canonical_id,
            "geometry_loc_id": retired_id,
            "geometry_bank": "geometry/countries/CAN/relationships/example",
            "has_shape": True,
            "family": "can_designated_place",
            "name": "Example",
        }]
        version_rows = pd.DataFrame([{
            "loc_id": retired_id,
            "geometry_partition": "shapes/places.parquet",
            "shape_storage": "shape_partition",
        }])
        shape_rows = pd.DataFrame([{
            "loc_id": retired_id,
            "geometry": box(-80, 43, -79, 44).wkb,
        }])
        selected_filters = []

        def fake_select_rows(path, *, columns, in_filters):
            selected_filters.append(in_filters)
            return version_rows

        with (
            patch("mapmover.runtime.reference_geometry_bank.identities", return_value=identity_rows),
            patch("mapmover.runtime.reference_geometry_bank._safe_bank_root", return_value=Path("example-bank")),
            patch("mapmover.runtime.reference_geometry_bank._safe_partition_path", return_value=Path("places.parquet")),
            patch("mapmover.runtime.reference_geometry_bank.select_rows", side_effect=fake_select_rows),
            patch("mapmover.runtime.reference_geometry_bank._read_shape_partition", return_value=shape_rows),
        ):
            frame = load_reference_graph_geometry([canonical_id])

        self.assertEqual(selected_filters, [{"loc_id": [retired_id]}])
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["loc_id"], canonical_id)
        self.assertEqual(frame.iloc[0]["name"], "Example")
        self.assertEqual(frame.iloc[0]["geometry"]["type"], "Polygon")

    def test_projected_geoparquet_shape_is_normalized_to_wgs84(self):
        loc_id = "CAN-HEALTH-PROJECTED"
        wgs84_geometry = box(-80, 43, -79, 44)
        to_projected = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
        projected_geometry = transform_geometry(to_projected.transform, wgs84_geometry)

        with tempfile.TemporaryDirectory() as temporary:
            bank_path = Path(temporary) / "projected.parquet"
            table = pa.Table.from_pandas(pd.DataFrame([{
                "loc_id": loc_id,
                "name": "Projected health region",
                "geometry": projected_geometry.wkb,
            }]), preserve_index=False)
            geo_metadata = {
                "version": "1.1.0",
                "primary_column": "geometry",
                "columns": {
                    "geometry": {
                        "encoding": "WKB",
                        "geometry_types": ["Polygon"],
                        "crs": CRS.from_epsg(3857).to_json_dict(),
                    },
                },
            }
            metadata = dict(table.schema.metadata or {})
            metadata[b"geo"] = json.dumps(geo_metadata).encode("utf-8")
            pq.write_table(table.replace_schema_metadata(metadata), bank_path)
            identity_rows = [{
                "loc_id": loc_id,
                "geometry_bank": "ignored/projected.parquet",
                "has_shape": True,
                "family": "can_health_region",
                "name": "Projected health region",
            }]

            with (
                patch("mapmover.runtime.reference_geometry_bank.identities", return_value=identity_rows),
                patch("mapmover.runtime.reference_geometry_bank._safe_bank_root", return_value=bank_path),
            ):
                frame = load_reference_graph_geometry([loc_id])

        self.assertEqual(len(frame), 1)
        row = frame.iloc[0]
        self.assertAlmostEqual(row["bbox_min_lon"], -80.0, places=5)
        self.assertAlmostEqual(row["bbox_min_lat"], 43.0, places=5)
        self.assertAlmostEqual(row["bbox_max_lon"], -79.0, places=5)
        self.assertAlmostEqual(row["bbox_max_lat"], 44.0, places=5)
        self.assertAlmostEqual(row["centroid_lon"], -79.5, places=4)

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
