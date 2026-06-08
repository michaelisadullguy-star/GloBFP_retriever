import xml.etree.ElementTree as ET

import geopandas as gpd
from shapely.geometry import Polygon, box

from globfp_retriever.osm_export import write_osm


def _tags(elem):
    return {t.get("k"): t.get("v") for t in elem.findall("tag")}


def test_single_building_is_closed_way(tmp_path):
    poly = box(0.0, 0.0, 0.001, 0.001)
    gdf = gpd.GeoDataFrame(
        {"height": [9.0], "building": ["yes"]}, geometry=[poly], crs="EPSG:4326"
    )
    out = write_osm(gdf, tmp_path / "b.osm")
    root = ET.fromstring(out.read_text())
    assert root.tag == "osm"
    nodes = root.findall("node")
    ways = root.findall("way")
    assert len(nodes) == 4  # 4 distinct corners
    assert len(ways) == 1
    nds = ways[0].findall("nd")
    assert len(nds) == 5  # closed: first node repeated at the end
    assert nds[0].get("ref") == nds[-1].get("ref")
    tags = _tags(ways[0])
    assert tags["building"] == "yes"
    assert tags["height"] == "9"  # 9.0 formatted without trailing zeros


def test_polygon_with_hole_becomes_multipolygon_relation(tmp_path):
    exterior = [(0, 0), (0, 0.01), (0.01, 0.01), (0.01, 0), (0, 0)]
    hole = [(0.003, 0.003), (0.003, 0.006), (0.006, 0.006), (0.006, 0.003), (0.003, 0.003)]
    gdf = gpd.GeoDataFrame(
        {"height": [12.0], "building": ["yes"]},
        geometry=[Polygon(exterior, [hole])],
        crs="EPSG:4326",
    )
    out = write_osm(gdf, tmp_path / "h.osm")
    root = ET.fromstring(out.read_text())
    rels = root.findall("relation")
    assert len(rels) == 1
    assert len(root.findall("way")) == 2  # one outer, one inner
    roles = sorted(m.get("role") for m in rels[0].findall("member"))
    assert roles == ["inner", "outer"]
    rtags = _tags(rels[0])
    assert rtags["type"] == "multipolygon"
    assert rtags["building"] == "yes"
    assert rtags["height"] == "12"


def test_empty_writes_valid_osm(tmp_path):
    gdf = gpd.GeoDataFrame({"height": []}, geometry=[], crs="EPSG:4326")
    out = write_osm(gdf, tmp_path / "empty.osm")
    root = ET.fromstring(out.read_text())  # parses -> well-formed
    assert root.tag == "osm"
    assert root.findall("node") == []
    assert root.findall("way") == []


def test_reprojects_to_wgs84(tmp_path):
    # Web Mercator input must come out as plausible lat/lon.
    poly = box(0.0, 0.0, 100.0, 100.0)
    gdf = gpd.GeoDataFrame({"height": [3.0]}, geometry=[poly], crs="EPSG:3857")
    out = write_osm(gdf, tmp_path / "m.osm")
    root = ET.fromstring(out.read_text())
    for node in root.findall("node"):
        assert -180 <= float(node.get("lon")) <= 180
        assert -90 <= float(node.get("lat")) <= 90
