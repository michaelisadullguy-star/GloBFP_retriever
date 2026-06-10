import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import MultiPolygon, Polygon, box

from globfp_retriever import load_aoi
from globfp_retriever.aoi import bbox_to_geom, merge_shared_boundaries


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


# --- AOI preprocessing: merge polygons that share a common boundary ---


def test_polygons_sharing_an_edge_are_merged():
    geom = merge_shared_boundaries([box(0, 0, 1, 1), box(1, 0, 2, 1)])
    assert geom.geom_type == "Polygon"
    assert geom.area == pytest.approx(2.0)


def test_overlapping_polygons_are_merged():
    geom = merge_shared_boundaries([box(0, 0, 1, 1), box(0.5, 0, 1.5, 1)])
    assert geom.geom_type == "Polygon"
    assert geom.area == pytest.approx(1.5)


def test_disjoint_polygons_stay_separate():
    geom = merge_shared_boundaries([box(0, 0, 1, 1), box(2, 0, 3, 1)])
    assert geom.geom_type == "MultiPolygon"
    assert len(geom.geoms) == 2
    assert geom.area == pytest.approx(2.0)


def test_corner_touching_polygons_are_not_merged():
    geom = merge_shared_boundaries([box(0, 0, 1, 1), box(1, 1, 2, 2)])
    assert geom.geom_type == "MultiPolygon"
    assert len(geom.geoms) == 2


def test_mixed_groups_merge_only_adjacent_polygons():
    geom = merge_shared_boundaries(
        [box(0, 0, 1, 1), box(1, 0, 2, 1), box(5, 5, 6, 6)]
    )
    assert geom.geom_type == "MultiPolygon"
    areas = sorted(part.area for part in geom.geoms)
    assert areas == pytest.approx([1.0, 2.0])


def test_feature_collection_polygons_are_dissolved():
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
            },
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]]],
                },
            },
        ],
    }
    geom = load_aoi(fc)
    assert geom.geom_type == "Polygon"
    assert geom.area == pytest.approx(2.0)


def test_multi_feature_file_is_dissolved(tmp_path):
    path = tmp_path / "aoi.geojson"
    gpd.GeoDataFrame(
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)], crs="EPSG:4326"
    ).to_file(path, driver="GeoJSON")
    geom = load_aoi(str(path))
    assert geom.geom_type == "Polygon"
    assert geom.area == pytest.approx(2.0)


def test_shapely_multipolygon_input_is_dissolved():
    geom = load_aoi(MultiPolygon([box(0, 0, 1, 1), box(1, 0, 2, 1)]))
    assert geom.geom_type == "Polygon"
    assert geom.area == pytest.approx(2.0)


def test_wkt_multipolygon_is_dissolved():
    wkt = (
        "MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)), "
        "((1 0, 2 0, 2 1, 1 1, 1 0)))"
    )
    geom = load_aoi(wkt)
    assert geom.geom_type == "Polygon"
    assert geom.area == pytest.approx(2.0)
