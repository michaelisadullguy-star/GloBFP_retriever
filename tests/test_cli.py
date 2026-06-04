import geopandas as gpd
import pytest

from globfp_retriever import cli
from globfp_retriever import metadata as M
from globfp_retriever import retrieve as R
from globfp_retriever.cli import _parse_polygon


def test_parse_polygon_comma_and_space():
    assert _parse_polygon("0,0 1,0 1,1") == [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    assert _parse_polygon("0 0 1 0 1 1") == [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]


def test_parse_polygon_too_few_pairs():
    with pytest.raises(Exception):
        _parse_polygon("0,0 1,1")


def test_cli_bbox_writes_output(monkeypatch, tmp_path, metadata_two_tiles, fake_tile_loader):
    monkeypatch.setattr(M, "load_or_build_metadata", lambda **_kw: metadata_two_tiles)
    monkeypatch.setattr(R, "_load_tile", fake_tile_loader)
    out = tmp_path / "cli.geojson"
    rc = cli.main(
        [
            "--bbox", "0.40", "0.40", "0.60", "0.60",
            "-o", str(out),
            "--cache-dir", str(tmp_path),
        ]
    )
    assert rc == 0
    assert out.exists()
    assert len(gpd.read_file(out)) >= 1


def test_cli_list_tiles(monkeypatch, capsys, metadata_two_tiles):
    monkeypatch.setattr(M, "load_or_build_metadata", lambda **_kw: metadata_two_tiles)
    rc = cli.main(["--bbox", "0.5", "0.5", "0.6", "0.6", "--list-tiles"])
    captured = capsys.readouterr().out
    assert rc == 0
    assert "1 tile(s)" in captured
    assert "gridID=1" in captured


def test_cli_requires_exactly_one_aoi():
    with pytest.raises(SystemExit):
        cli.main([])


def test_cli_rejects_two_aois():
    with pytest.raises(SystemExit):
        cli.main(["some.shp", "--bbox", "0", "0", "1", "1"])
