import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Polygon, box

from globfp_retriever import load_aoi
from globfp_retriever.aoi import bbox_to_geom


def test_bbox_tuple():
    geom = load_aoi((-84.49, 45.63, -84.46, 45.65))
    assert geom.equals(box(-84.49, 45.63, -84.46, 45.65))


def test_bbox_bad_ordering_raises():
    with pytest.raises(ValueError):
        bbox_to_geom((10, 10, 0, 0))


def test_polygon_ring():
    ring = [(-84.49, 45.63), (-84.46, 45.63), (-84.46, 45.65), (-84.49, 45.65)]
    geom = load_aoi(ring)
    assert geom.geom_type == "Polygon"
    assert geom.area > 0


def test_numpy_ring():
    arr = np.array([[0, 0], [1, 0], [1, 1], [0, 1]])
    geom = load_aoi(arr)
    assert isinstance(geom, Polygon)
    assert geom.area == pytest.approx(1.0)


def test_geojson_dict_geometry():
    d = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    assert load_aoi(d).area == pytest.approx(1.0)


def test_geojson_feature_collection():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                },
            }
        ],
    }
    assert load_aoi(fc).area == pytest.approx(1.0)


def test_geojson_file(tmp_path):
    path = tmp_path / "aoi.geojson"
    gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1)], crs="EPSG:4326").to_file(
        path, driver="GeoJSON"
    )
    assert load_aoi(str(path)).area == pytest.approx(1.0)


def test_shapefile_is_reprojected_to_wgs84(tmp_path):
    path = tmp_path / "aoi.shp"
    gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1)], crs="EPSG:4326").to_crs(3857).to_file(path)
    geom = load_aoi(str(path))
    minx, miny, maxx, maxy = geom.bounds
    assert (minx, miny) == pytest.approx((0.0, 0.0), abs=1e-6)
    assert (maxx, maxy) == pytest.approx((1.0, 1.0), abs=1e-6)


def test_wkt_string():
    assert load_aoi("POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))").area == pytest.approx(1.0)


def test_missing_path_raises():
    with pytest.raises((FileNotFoundError, ValueError)):
        load_aoi("/no/such/file.shp")


def test_bad_sequence_raises():
    with pytest.raises(ValueError):
        load_aoi([1, 2, 3])
