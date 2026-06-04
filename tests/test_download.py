"""Exercise the real zip/extract/read path (no network) via the tile cache."""

import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import box

from globfp_retriever import download as D


def _make_tile_zip(zip_path, tmp_path):
    """Write a small shapefile and bundle its sidecar files into ``zip_path``."""
    shp_dir = tmp_path / "shp"
    shp_dir.mkdir()
    gdf = gpd.GeoDataFrame(
        {"Height": [12.0, 7.5]},
        geometry=[box(0.1, 0.1, 0.2, 0.2), box(0.6, 0.6, 0.7, 0.7)],
        crs="EPSG:4326",
    )
    shp = shp_dir / "tile.shp"
    gdf.to_file(shp)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as zf:
        for part in shp_dir.iterdir():
            zf.write(part, arcname=part.name)


def test_read_tile_real_zip(tmp_path):
    zip_path = tmp_path / "tile.zip"
    _make_tile_zip(zip_path, tmp_path)
    gdf = D.read_tile(zip_path)
    assert len(gdf) == 2
    assert "Height" in gdf.columns
    assert gdf.crs.to_epsg() == 4326


def test_download_and_read_tile_cache_hit(tmp_path):
    cache_dir = tmp_path / "cache"
    grid_id = 42
    zip_path = D.tile_cache_path(cache_dir, grid_id)
    _make_tile_zip(zip_path, tmp_path)

    row = {"gridID": grid_id, "download_url": "https://example.invalid/should-not-fetch.zip"}
    # Cache hit => no network call is attempted.
    gdf = D.download_and_read_tile(row, cache_dir=cache_dir, use_cache=True)
    assert len(gdf) == 2
    assert set(gdf["Height"]) == {12.0, 7.5}


def test_read_tile_rejects_non_zip(tmp_path):
    bad = tmp_path / "not.zip"
    bad.write_text("not a zip")
    with pytest.raises(ValueError):
        D.read_tile(bad)
