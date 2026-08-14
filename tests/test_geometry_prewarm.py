from __future__ import annotations

import unittest
from unittest import mock

from mapmover import geometry_handlers


class GeometryPrewarmTests(unittest.TestCase):
    def test_cloud_prewarm_exercises_primary_usa_point_path(self) -> None:
        resolved = [{"deepest_resolved_loc_id": "USA-CA-037-207400-1-1024"}]
        county_cache_key = ("exact_county", "USA")

        with geometry_handlers._country_parquet_cache_lock:
            previous = geometry_handlers._country_parquet_cache.get(county_cache_key)
            geometry_handlers._country_parquet_cache[county_cache_key] = mock.sentinel.counties
        try:
            with mock.patch.object(geometry_handlers, "is_cloud_mode", return_value=True), mock.patch.object(
                geometry_handlers, "load_global_countries_frame", return_value=mock.Mock(empty=False, __len__=lambda _self: 250)
            ), mock.patch.object(
                geometry_handlers, "resolve_points_to_locations", return_value=resolved
            ) as resolve_mock:
                geometry_handlers.prewarm_geometry()
        finally:
            with geometry_handlers._country_parquet_cache_lock:
                if previous is None:
                    geometry_handlers._country_parquet_cache.pop(county_cache_key, None)
                else:
                    geometry_handlers._country_parquet_cache[county_cache_key] = previous

        resolve_mock.assert_called_once_with(
            [{"id": "prewarm-usa", "lat": 34.0522, "lon": -118.2437}],
            include_geometry=False,
            country_scope="USA",
        )

    def test_local_prewarm_does_no_work(self) -> None:
        with mock.patch.object(geometry_handlers, "is_cloud_mode", return_value=False), mock.patch.object(
            geometry_handlers, "load_global_countries_frame"
        ) as global_mock, mock.patch.object(
            geometry_handlers, "resolve_points_to_locations"
        ) as resolve_mock:
            geometry_handlers.prewarm_geometry()

        global_mock.assert_not_called()
        resolve_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
