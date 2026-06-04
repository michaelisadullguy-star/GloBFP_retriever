import pytest

from globfp_retriever import metadata as M


def test_parse_tile_name_valid():
    assert M._parse_tile_name("123_-84.5_45.6_-84.0_46.0.zip") == {
        "gridID": 123,
        "xmin": -84.5,
        "ymin": 45.6,
        "xmax": -84.0,
        "ymax": 46.0,
    }


@pytest.mark.parametrize("name", ["readme.txt", "world_grid.shp", "", "12_3.zip", None])
def test_parse_tile_name_invalid(name):
    assert M._parse_tile_name(name) is None


def test_build_metadata_dedups_and_boxes(monkeypatch):
    fake = {
        100: [
            {"id": 1, "name": "100_0_0_1_1.zip", "download_url": "u1"},
            {"id": 2, "name": "100_0_0_1_1.zip", "download_url": "u1b"},  # dup gridID
            {"id": 3, "name": "readme.txt", "download_url": "ur"},  # ignored
        ],
        200: [{"id": 4, "name": "200_1_1_2_2.zip", "download_url": "u4"}],
    }
    monkeypatch.setattr(M, "fetch_article_files", lambda a, **k: fake[a])

    gdf = M.build_metadata(articles=[100, 200])

    assert len(gdf) == 2
    assert set(gdf["gridID"]) == {100, 200}
    assert gdf.crs.to_epsg() == 4326
    row = gdf[gdf["gridID"] == 100].iloc[0]
    assert row.geometry.bounds == (0, 0, 1, 1)
    assert row["download_url"] == "u1"


def test_load_or_build_metadata_caches(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_fetch(article_id, **_kw):
        calls["n"] += 1
        return [{"id": 1, "name": "100_0_0_1_1.zip", "download_url": "u1"}]

    monkeypatch.setattr(M, "fetch_article_files", fake_fetch)
    monkeypatch.setattr(M, "FIGSHARE_ARTICLES", [100])

    gdf = M.load_or_build_metadata(cache_dir=tmp_path)
    assert (tmp_path / M.CACHE_FILENAME).exists()
    assert len(gdf) == 1
    built_calls = calls["n"]

    # Second call must read the cache, not re-query figshare.
    gdf2 = M.load_or_build_metadata(cache_dir=tmp_path)
    assert len(gdf2) == 1
    assert calls["n"] == built_calls
    assert gdf2["gridID"].dtype.kind == "i"
