"""Shared fixtures for offline tests (no network access required)."""

import geopandas as gpd
import pytest
from shapely.geometry import box


@pytest.fixture
def metadata_two_tiles():
    """Grid index with two adjacent 1x1 degree tiles: x in [0,1] and [1,2], y in [0,1]."""
    rows = [
        {
            "gridID": 1,
            "xmin": 0,
            "ymin": 0,
            "xmax": 1,
            "ymax": 1,
            "download_url": "https://example.invalid/tile1.zip",
            "geometry": box(0, 0, 1, 1),
        },
        {
            "gridID": 2,
            "xmin": 1,
            "ymin": 0,
            "xmax": 2,
            "ymax": 1,
            "download_url": "https://example.invalid/tile2.zip",
            "geometry": box(1, 0, 2, 1),
        },
    ]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


@pytest.fixture
def fake_tile_loader():
    """Return three buildings per tile, offset so tile 2 sits one degree east."""

    def _loader(row, **_kwargs):
        grid_id = row["gridID"]
        base = 0.0 if grid_id == 1 else 1.0
        polys = [
            box(base + 0.10, 0.10, base + 0.20, 0.20),
            box(base + 0.45, 0.45, base + 0.55, 0.55),
            box(base + 0.80, 0.80, base + 0.90, 0.90),
        ]
        return gpd.GeoDataFrame(
            {"Height": [10.0, 20.0, 30.0]}, geometry=polys, crs="EPSG:4326"
        )

    return _loader
