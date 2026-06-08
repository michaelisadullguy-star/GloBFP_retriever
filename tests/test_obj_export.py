import geopandas as gpd
import pytest
from shapely.geometry import Polygon, box

from globfp_retriever.obj_export import write_obj


def _vf(text):
    lines = text.splitlines()
    verts = [ln for ln in lines if ln.startswith("v ")]
    faces = [ln for ln in lines if ln.startswith("f ")]
    return verts, faces


def test_extrude_unit_square_counts(tmp_path):
    poly = box(0.0, 0.0, 0.001, 0.001)
    gdf = gpd.GeoDataFrame({"height": [10.0]}, geometry=[poly], crs="EPSG:4326")
    out = write_obj(gdf, tmp_path / "b.obj", height_field="height")
    verts, faces = _vf(out.read_text())
    # 4 corners -> base+top = 8 vertices
    assert len(verts) == 8
    # walls 4 edges x2 + roof 2 + floor 2 = 12 triangles
    assert len(faces) == 12
    zs = sorted({round(float(ln.split()[3]), 3) for ln in verts})
    assert zs[0] == 0.0
    assert zs[-1] == pytest.approx(10.0, abs=1e-3)


def test_missing_height_uses_default(tmp_path):
    poly = box(0.0, 0.0, 0.001, 0.001)
    gdf = gpd.GeoDataFrame({"height": [None]}, geometry=[poly], crs="EPSG:4326")
    out = write_obj(gdf, tmp_path / "b.obj", height_field="height", default_height=7.0)
    verts, _ = _vf(out.read_text())
    assert max(float(ln.split()[3]) for ln in verts) == pytest.approx(7.0, abs=1e-3)


def test_empty_gdf_writes_header_only(tmp_path):
    gdf = gpd.GeoDataFrame({"height": []}, geometry=[], crs="EPSG:4326")
    out = write_obj(gdf, tmp_path / "empty.obj", height_field="height")
    text = out.read_text()
    verts, faces = _vf(text)
    assert verts == [] and faces == []
    assert "# solids: 0" in text


def test_nonconvex_polygon_faces_reference_valid_vertices(tmp_path):
    # L-shaped (non-convex) footprint: walls are exact (6 corners -> 12 verts),
    # roof/floor come from the filtered triangulation. Assert the mesh is sound:
    # every face index points at a real vertex.
    l_shape = Polygon(
        [(0, 0), (0.002, 0), (0.002, 0.001), (0.001, 0.001), (0.001, 0.002), (0, 0.002)]
    )
    gdf = gpd.GeoDataFrame({"height": [5.0]}, geometry=[l_shape], crs="EPSG:4326")
    out = write_obj(gdf, tmp_path / "l.obj", height_field="height")
    verts, faces = _vf(out.read_text())
    assert len(verts) == 12
    assert len(faces) > 12  # walls plus some roof/floor triangles
    n = len(verts)
    for face in faces:
        for tok in face.split()[1:]:
            assert 1 <= int(tok) <= n
