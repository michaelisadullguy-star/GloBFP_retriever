import numpy as np
import geopandas as gpd
import pytest
import shapely
from shapely.geometry import box

from globfp_retriever import geocrypt as gc

KEY = b"unit-test-key-not-secret-000000000"
KEY2 = b"a-different-key-1111111111111111111"
UTM = "EPSG:32650"  # an arbitrary metric CRS (UTM zone 50N)
MAXSHIFT = sum(r for _, r in gc.DEFAULT_LAYERS)  # 0.75 m per axis


def _utm_gdf():
    # Three buildings in metric coords spread over a few km.
    polys = [
        box(500000, 3540000, 500030, 3540020),
        box(503000, 3542000, 503025, 3542040),
        box(507500, 3545500, 507560, 3545540),
    ]
    return gpd.GeoDataFrame({"height": [9.0, 20.0, 30.0]}, geometry=polys, crs=UTM)


def test_displacement_is_deterministic_and_key_dependent():
    x = np.array([500000.0, 503123.4, 507500.9])
    y = np.array([3540000.0, 3542222.2, 3545540.5])
    d1 = gc.displacement(KEY, x, y)
    d1b = gc.displacement(KEY, x, y)
    d2 = gc.displacement(KEY2, x, y)
    assert np.array_equal(d1[0], d1b[0]) and np.array_equal(d1[1], d1b[1])
    assert not np.allclose(d1[0], d2[0])  # different key => different field


def test_displacement_within_accumulated_bounds_and_nonzero():
    rng = np.random.default_rng(0)
    x = rng.uniform(490000, 510000, 5000)
    y = rng.uniform(3530000, 3550000, 5000)
    dx, dy = gc.displacement(KEY, x, y)
    assert np.abs(dx).max() <= MAXSHIFT + 1e-9
    assert np.abs(dy).max() <= MAXSHIFT + 1e-9
    assert np.abs(dx).max() > 0  # it actually moves points


def test_field_is_continuous():
    # Two points 1 mm apart must move almost identically (no tears across cells).
    x0, y0 = np.array([501234.5]), np.array([3543210.9])
    dx0, dy0 = gc.displacement(KEY, x0, y0)
    dx1, dy1 = gc.displacement(KEY, x0 + 1e-3, y0 + 1e-3)
    assert abs(dx0[0] - dx1[0]) < 1e-5
    assert abs(dy0[0] - dy1[0]) < 1e-5


def test_cell_centre_is_average_of_four_corners():
    # Single layer: bilinear weight at the centre is 1/4 each corner.
    layer = ((1000.0, 0.1),)
    i, j = 501, 3543
    cx = np.array([(i + 0.5) * 1000.0])
    cy = np.array([(j + 0.5) * 1000.0])
    dx, dy = gc.displacement(KEY, cx, cy, layers=layer)
    ii = np.array([i, i + 1, i, i + 1])
    jj = np.array([j, j, j + 1, j + 1])
    ox, oy = gc._corner_offsets(KEY, 0, ii, jj, 0.1)
    assert dx[0] == pytest.approx(ox.mean(), abs=1e-12)
    assert dy[0] == pytest.approx(oy.mean(), abs=1e-12)


def test_corner_point_gets_that_corner_offset():
    layer = ((1000.0, 0.1),)
    i, j = 7, 11
    px = np.array([i * 1000.0])
    py = np.array([j * 1000.0])
    dx, dy = gc.displacement(KEY, px, py, layers=layer)
    ox, oy = gc._corner_offsets(KEY, 0, np.array([i]), np.array([j]), 0.1)
    assert dx[0] == pytest.approx(ox[0], abs=1e-9)
    assert dy[0] == pytest.approx(oy[0], abs=1e-9)


def test_encrypt_then_decrypt_round_trips():
    g = _utm_gdf()
    enc = gc.encrypt_gdf(g, KEY, metric_crs=UTM)
    dec = gc.decrypt_gdf(enc, KEY, metric_crs=UTM)
    a = shapely.get_coordinates(g.geometry.values)
    b = shapely.get_coordinates(dec.geometry.values)
    assert np.abs(a - b).max() < 1e-6  # recovered to sub-micrometre


def test_encrypt_moves_points_sub_metre():
    g = _utm_gdf()
    enc = gc.encrypt_gdf(g, KEY, metric_crs=UTM)
    a = shapely.get_coordinates(g.geometry.values)
    b = shapely.get_coordinates(enc.geometry.values)
    shift = np.abs(a - b)
    assert shift.max() <= MAXSHIFT + 1e-9
    assert shift.max() > 0


def test_wrong_key_does_not_decrypt():
    g = _utm_gdf()
    enc = gc.encrypt_gdf(g, KEY, metric_crs=UTM)
    bad = gc.decrypt_gdf(enc, KEY2, metric_crs=UTM)
    a = shapely.get_coordinates(g.geometry.values)
    c = shapely.get_coordinates(bad.geometry.values)
    assert np.abs(a - c).max() > 1e-3  # cannot recover without the right key


def test_load_key_from_file_and_missing(tmp_path):
    kf = tmp_path / "k.key"
    k1 = gc.load_key(key_file=kf)        # generates
    assert kf.exists() and len(k1) == 32
    k2 = gc.load_key(key_file=kf)        # reads back the same
    assert k1 == k2
    with pytest.raises(RuntimeError):
        gc.load_key(allow_generate=False, key_file=tmp_path / "nope.key")
