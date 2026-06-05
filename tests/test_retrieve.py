import geopandas as gpd
import pytest
from shapely.geometry import box

from globfp_retriever import retrieve as R


def test_select_tiles_picks_only_overlapping(metadata_two_tiles):
    sel = R.select_tiles(metadata_two_tiles, box(0.5, 0.5, 0.6, 0.6))
    assert list(sel["gridID"]) == [1]


def test_keep_whole_building_uncut(monkeypatch, tmp_path, metadata_two_tiles, fake_tile_loader):
    monkeypatch.setattr(R, "_load_tile", fake_tile_loader)
    out = tmp_path / "out.geojson"
    # AOI clips the corner of the middle building (0.45-0.55) of tile 1.
    res = R.retrieve_globfp(
        box(0.40, 0.40, 0.50, 0.50),
        output=str(out),
        metadata=metadata_two_tiles,
        cache_dir=tmp_path,
    )
    assert len(res) == 1
    # keep-whole => geometry not cut, still extends past the AOI to 0.55.
    assert res.geometry.iloc[0].bounds[2] == pytest.approx(0.55)
    assert res.crs.to_epsg() == 4326
    assert out.exists()
    reread = gpd.read_file(out)
    assert len(reread) == 1
    # Every feature is tagged building=yes alongside lowercase height, in the file too.
    assert "height" in reread.columns
    assert "building" in reread.columns
    assert (reread["building"] == "yes").all()


def test_building_tag_on_every_feature(monkeypatch, tmp_path, metadata_two_tiles, fake_tile_loader):
    monkeypatch.setattr(R, "_load_tile", fake_tile_loader)
    res = R.retrieve_globfp(
        box(0.0, 0.0, 1.0, 1.0),  # whole tile 1: all three buildings
        metadata=metadata_two_tiles,
        cache_dir=tmp_path,
    )
    assert len(res) == 3
    assert "building" in res.columns
    assert (res["building"] == "yes").all()
    # building should sit alongside height (lowercase), with geometry last.
    assert list(res.columns) == ["height", "building", "geometry"]


def test_building_tag_can_be_disabled(monkeypatch, tmp_path, metadata_two_tiles, fake_tile_loader):
    monkeypatch.setattr(R, "_load_tile", fake_tile_loader)
    res = R.retrieve_globfp(
        box(0.0, 0.0, 1.0, 1.0),
        metadata=metadata_two_tiles,
        cache_dir=tmp_path,
        building_tag=None,
    )
    assert "building" not in res.columns


def test_clip_cuts_geometry(monkeypatch, tmp_path, metadata_two_tiles, fake_tile_loader):
    monkeypatch.setattr(R, "_load_tile", fake_tile_loader)
    res = R.retrieve_globfp(
        box(0.40, 0.40, 0.50, 0.50),
        metadata=metadata_two_tiles,
        cache_dir=tmp_path,
        clip=True,
    )
    assert len(res) == 1
    assert res.geometry.iloc[0].bounds[2] == pytest.approx(0.50)


def test_spans_two_tiles(monkeypatch, tmp_path, metadata_two_tiles, fake_tile_loader):
    monkeypatch.setattr(R, "_load_tile", fake_tile_loader)
    # Straddles the tile boundary at x=1: grabs the 0.8-0.9 building of tile 1
    # and the 1.1-1.2 building of tile 2.
    res = R.retrieve_globfp(
        box(0.80, 0.05, 1.20, 0.95),
        metadata=metadata_two_tiles,
        cache_dir=tmp_path,
    )
    assert len(res) == 2


def test_no_intersection_returns_empty(monkeypatch, tmp_path, metadata_two_tiles, fake_tile_loader):
    monkeypatch.setattr(R, "_load_tile", fake_tile_loader)
    out = tmp_path / "empty.geojson"
    res = R.retrieve_globfp(
        box(10, 10, 11, 11),
        output=str(out),
        metadata=metadata_two_tiles,
        cache_dir=tmp_path,
    )
    assert len(res) == 0
    assert out.exists()
    assert gpd.read_file(out).empty


def test_output_gpkg_format(monkeypatch, tmp_path, metadata_two_tiles, fake_tile_loader):
    monkeypatch.setattr(R, "_load_tile", fake_tile_loader)
    out = tmp_path / "out.gpkg"
    R.retrieve_globfp(
        box(0.40, 0.40, 0.60, 0.60),
        output=str(out),
        metadata=metadata_two_tiles,
        cache_dir=tmp_path,
    )
    assert out.exists()
    assert len(gpd.read_file(out)) >= 1


def test_unknown_format_raises():
    with pytest.raises(ValueError):
        R._resolve_driver(__import__("pathlib").Path("x.weird"), None)
