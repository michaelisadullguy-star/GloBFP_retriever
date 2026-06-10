import geopandas as gpd
from shapely.geometry import Polygon, box

from globfp_retriever import clean

UTM = "EPSG:32650"  # metric, so .area is in m²


def _gdf(polys):
    return gpd.GeoDataFrame({"height": [1.0] * len(polys)}, geometry=polys, crs=UTM)


def test_filter_min_area_drops_small_only():
    g = _gdf([box(0, 0, 2, 2), box(10, 10, 30, 30)])  # 4 m² and 400 m²
    out, n = clean.filter_min_area(g, 10, metric_crs=UTM)
    assert n == 1 and len(out) == 1
    assert out.geometry.iloc[0].area == 400


def test_filter_min_area_disabled_when_none_or_zero():
    g = _gdf([box(0, 0, 1, 1)])
    assert clean.filter_min_area(g, None, metric_crs=UTM)[1] == 0
    assert clean.filter_min_area(g, 0, metric_crs=UTM)[1] == 0


def test_remove_exact_duplicates_drops_all_members():
    c = box(50, 50, 60, 60)
    g = _gdf([box(0, 0, 10, 10), box(0, 0, 10, 10), c])  # first two identical
    out, n = clean.remove_exact_duplicates(g)
    assert n == 2 and len(out) == 1  # both copies removed, unique kept
    assert out.geometry.iloc[0].equals(c)


def test_remove_triangles_only():
    quad = box(0, 0, 10, 10)
    g = _gdf([Polygon([(0, 0), (10, 0), (5, 8)]), quad])
    out, n = clean.remove_triangles(g)
    assert n == 1 and len(out) == 1
    assert out.geometry.iloc[0].equals(quad)


def test_clean_buildings_off_by_default():
    g = _gdf([Polygon([(0, 0), (1, 0), (0.5, 1)]), box(0, 0, 2, 2)])
    out, stats = clean.clean_buildings(g, metric_crs=UTM)
    assert len(out) == 2  # nothing removed unless explicitly enabled
    assert stats["input"] == stats["output"] == 2


def test_clean_buildings_all_filters():
    tri = Polygon([(0, 0), (10, 0), (5, 8)])  # triangle (area 40)
    small = box(0, 0, 2, 2)                   # 4 m²
    dup_a = box(100, 100, 120, 120)           # 400 m², duplicated
    dup_b = box(100, 100, 120, 120)
    big = box(200, 200, 260, 260)             # 3600 m², unique
    out, stats = clean.clean_buildings(
        _gdf([tri, small, dup_a, dup_b, big]),
        min_area=10,
        drop_duplicates=True,
        drop_triangles=True,
        metric_crs=UTM,
    )
    assert stats["triangles"] == 1
    assert stats["min_area"] == 1
    assert stats["duplicates"] == 2
    assert len(out) == 1 and out.geometry.iloc[0].equals(big)
