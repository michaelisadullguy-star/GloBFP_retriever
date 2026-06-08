"""Write building footprints as an extruded 3D Wavefront ``.obj`` mesh.

Each footprint polygon is extruded from its base to its ``height`` to form a
closed building solid (walls + triangulated roof + floor). Coordinates are
projected to a local metric CRS (UTM) and shifted to a local origin so the model
sits near ``(0, 0)``. Axes are ``X=east, Y=north, Z=up``, all in metres.

OBJ has no concept of a CRS, so the projection/units are recorded only in the
file header comments.
"""

from __future__ import annotations

import logging
from pathlib import Path

from shapely.geometry.polygon import orient
from shapely.ops import triangulate

log = logging.getLogger(__name__)

WGS84 = "EPSG:4326"


def _iter_polygons(geom):
    """Yield the Polygon parts of a geometry (skipping non-polygonal ones)."""
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == "Polygon":
        yield geom
    elif geom.geom_type == "MultiPolygon":
        for part in geom.geoms:
            if not part.is_empty:
                yield part


def _feature_height(value, default_height):
    try:
        h = float(value)
    except (TypeError, ValueError):
        return default_height
    if h != h or h <= 0:  # NaN or non-positive -> fall back
        return default_height
    return h


def _extrude_polygon(poly, height, base_z, ox, oy, voffset):
    """Build OBJ lines for one extruded polygon.

    Returns ``(vlines, flines, n_vertices)`` with face indices offset by
    ``voffset`` (the number of vertices already emitted), or ``None`` if the
    polygon could not be triangulated.
    """
    try:
        poly = orient(poly, sign=1.0)  # exterior CCW, holes CW -> outward normals
    except Exception:  # pragma: no cover - defensive
        return None

    top_z = base_z + height
    vlines: list[str] = []
    flines: list[str] = []
    coord_idx: dict[tuple, tuple] = {}
    added = 0

    def vid(x, y):
        nonlocal added
        lx, ly = x - ox, y - oy
        key = (round(lx, 3), round(ly, 3))  # share vertices at output precision
        hit = coord_idx.get(key)
        if hit is not None:
            return hit
        base_i = voffset + added + 1
        vlines.append(f"v {lx:.3f} {ly:.3f} {base_z:.3f}")
        added += 1
        top_i = voffset + added + 1
        vlines.append(f"v {lx:.3f} {ly:.3f} {top_z:.3f}")
        added += 1
        coord_idx[key] = (base_i, top_i)
        return base_i, top_i

    try:
        # Walls: two triangles per ring edge (base ring -> top ring).
        for ring in [poly.exterior, *poly.interiors]:
            coords = list(ring.coords)
            for (x0, y0), (x1, y1) in zip(coords[:-1], coords[1:]):
                b0, t0 = vid(x0, y0)
                b1, t1 = vid(x1, y1)
                flines.append(f"f {b0} {b1} {t1}")
                flines.append(f"f {b0} {t1} {t0}")

        # Roof + floor: Delaunay triangles kept only where they fall inside the
        # polygon (this drops triangles spanning holes or concave notches).
        for tri in triangulate(poly):
            if not poly.contains(tri.representative_point()):
                continue
            (ax, ay), (bx, by), (cx, cy) = tri.exterior.coords[:3]
            base_a, top_a = vid(ax, ay)
            base_b, top_b = vid(bx, by)
            base_c, top_c = vid(cx, cy)
            # Force CCW in XY so the roof normal points up (+Z), floor down (-Z).
            if (bx - ax) * (cy - ay) - (cx - ax) * (by - ay) < 0:
                base_b, top_b, base_c, top_c = base_c, top_c, base_b, top_b
            flines.append(f"f {top_a} {top_b} {top_c}")
            flines.append(f"f {base_a} {base_c} {base_b}")
    except Exception:  # pragma: no cover - defensive
        return None

    return vlines, flines, added


def write_obj(gdf, output, *, height_field="height", default_height=3.0, base_z=0.0):
    """Extrude ``gdf`` footprints to building solids and write a ``.obj`` file.

    Parameters
    ----------
    gdf
        GeoDataFrame of (Multi)Polygon footprints. Reprojected to a local UTM
        CRS so heights (metres) and plan coordinates share units.
    height_field
        Column holding each building's height in metres. Missing, non-numeric or
        non-positive values fall back to ``default_height``.
    default_height
        Height used when a feature has no usable ``height_field`` value.
    base_z
        Z of the building base (default ``0`` -> flat ground plane).
    """
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    vlines: list[str] = []
    flines: list[str] = []
    nverts = 0
    nsolids = 0

    if len(gdf) > 0:
        src = gdf if gdf.crs is not None else gdf.set_crs(WGS84)
        metric = src.to_crs(src.estimate_utm_crs())
        minx, miny, _, _ = metric.total_bounds
        ox = float(minx) if minx == minx else 0.0  # guard against NaN bounds
        oy = float(miny) if miny == miny else 0.0

        heights = (
            list(metric[height_field])
            if height_field in metric.columns
            else [None] * len(metric)
        )
        for idx, (geom, hval) in enumerate(zip(metric.geometry.values, heights)):
            polys = list(_iter_polygons(geom))
            if not polys:
                continue
            height = _feature_height(hval, default_height)
            feat_v: list[str] = []
            feat_f: list[str] = []
            for poly in polys:
                built = _extrude_polygon(poly, height, base_z, ox, oy, nverts)
                if built is None:
                    continue
                part_v, part_f, added = built
                feat_v.extend(part_v)
                feat_f.extend(part_f)
                nverts += added
            if feat_f:
                vlines.extend(feat_v)
                flines.append(f"g building_{idx}")
                flines.extend(feat_f)
                nsolids += 1

    header = [
        "# GloBFP-retriever building extrusion (Wavefront OBJ)",
        f"# solids: {nsolids}  vertices: {nverts}",
        "# axes: X=east, Y=north, Z=up; units: metres (local UTM origin)",
    ]
    output.write_text("\n".join(header + vlines + flines) + "\n")
    log.info("Wrote %d building solid(s) to %s", nsolids, output)
    return output
