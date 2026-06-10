"""Parse heterogeneous area-of-interest (AOI) inputs into a WGS84 geometry.

Accepted inputs:
  * a bounding box ``(min_lon, min_lat, max_lon, max_lat)``,
  * a polygon ring as a sequence of ``(lon, lat)`` pairs,
  * a GeoJSON-like ``dict`` (geometry, Feature or FeatureCollection),
  * a shapely geometry, ``GeoDataFrame`` or ``GeoSeries``,
  * a path to a local vector file (``.shp``, ``.geojson``, ``.json``, ...),
  * a WKT string.

Everything is returned as a single shapely geometry in EPSG:4326. The input is
always treated as one complete AOI: as a preprocessing step, polygons that
share a common boundary (or overlap) are merged into a single region, while
polygons that are disjoint or touch only at isolated points stay separate
parts of the result.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely import wkt as _wkt
from shapely.geometry import Polygon, box, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

log = logging.getLogger(__name__)

WGS84 = "EPSG:4326"


def _is_number(value) -> bool:
    return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(
        value, bool
    )


def bbox_to_geom(bbox) -> Polygon:
    """Build a rectangular polygon from ``(min_lon, min_lat, max_lon, max_lat)``."""
    seq = list(bbox)
    if len(seq) != 4 or not all(_is_number(v) for v in seq):
        raise ValueError(
            "bbox must be 4 numbers: (min_lon, min_lat, max_lon, max_lat)"
        )
    minx, miny, maxx, maxy = (float(v) for v in seq)
    if minx > maxx or miny > maxy:
        raise ValueError(
            f"Invalid bbox ordering {tuple(seq)}; expected "
            "(min_lon, min_lat, max_lon, max_lat)"
        )
    return box(minx, miny, maxx, maxy)


def aoi_to_gdf(geom: BaseGeometry) -> gpd.GeoDataFrame:
    """Wrap a single geometry as a one-row WGS84 GeoDataFrame (handy for clipping)."""
    return gpd.GeoDataFrame(geometry=[geom], crs=WGS84)


def _primitive_parts(geoms) -> list[BaseGeometry]:
    """Flatten a geometry or iterable of geometries into non-empty single parts."""
    if isinstance(geoms, BaseGeometry):
        geoms = [geoms]
    parts: list[BaseGeometry] = []
    for geom in geoms:
        if geom is None or geom.is_empty:
            continue
        if hasattr(geom, "geoms"):
            parts.extend(_primitive_parts(list(geom.geoms)))
        else:
            parts.append(geom)
    return parts


def _share_boundary(a: BaseGeometry, b: BaseGeometry) -> bool:
    """True when two polygons share a boundary segment or overlap.

    An intersection that is only isolated points (a corner touch) does not
    count as a common boundary.
    """
    inter = a.intersection(b)
    if inter.is_empty:
        return False
    return inter.length > 0 or inter.area > 0


def merge_shared_boundaries(geoms) -> BaseGeometry:
    """Preprocess an AOI: merge polygons that share a common boundary.

    ``geoms`` (one geometry or an iterable of geometries) is treated as one
    complete AOI. Polygons whose pairwise intersection contains a shared
    boundary segment -- or that overlap -- are dissolved into a single region;
    polygons that are disjoint or touch only at isolated points remain
    separate parts. Returns a single shapely geometry covering all parts.
    """
    parts = _primitive_parts(geoms)
    if not parts:
        raise ValueError("AOI contains no geometry")
    if len(parts) == 1:
        return parts[0]

    polygons = [g for g in parts if isinstance(g, Polygon)]
    others = [g for g in parts if not isinstance(g, Polygon)]

    regions = polygons
    if len(polygons) > 1:
        # Union-find over polygons; an edge means "shares a boundary segment".
        parent = list(range(len(polygons)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        tree = STRtree(polygons)
        for i, poly in enumerate(polygons):
            for j in tree.query(poly, predicate="intersects"):
                j = int(j)
                if j > i and _share_boundary(poly, polygons[j]):
                    parent[find(j)] = find(i)

        groups: dict[int, list[Polygon]] = {}
        for i, poly in enumerate(polygons):
            groups.setdefault(find(i), []).append(poly)
        regions = [
            unary_union(group) if len(group) > 1 else group[0]
            for group in groups.values()
        ]
        if len(regions) < len(polygons):
            log.info(
                "AOI preprocessing: merged %d polygon(s) sharing common "
                "boundaries into %d region(s)",
                len(polygons),
                len(regions),
            )

    return unary_union(regions + others)


def _geoms_from_geodata(geo) -> list[BaseGeometry]:
    if geo.crs is None:
        # No CRS recorded; assume the coordinates are already lon/lat (WGS84).
        geo = geo.set_crs(WGS84, allow_override=True)
    elif geo.crs.to_epsg() != 4326:
        geo = geo.to_crs(WGS84)
    geometry = geo.geometry if isinstance(geo, gpd.GeoDataFrame) else geo
    geoms = [g for g in geometry.values if g is not None]
    if not geoms:
        raise ValueError("AOI contains no geometry")
    return geoms


def _geoms_from_geojson(obj: dict) -> list[BaseGeometry]:
    kind = obj.get("type")
    if kind == "FeatureCollection":
        geoms = [
            shape(f["geometry"])
            for f in obj.get("features", [])
            if f.get("geometry") is not None
        ]
        if not geoms:
            raise ValueError("GeoJSON FeatureCollection has no geometries")
        return geoms
    if kind == "Feature":
        if obj.get("geometry") is None:
            raise ValueError("GeoJSON Feature has no geometry")
        return [shape(obj["geometry"])]
    return [shape(obj)]


def _looks_like_ring(seq) -> bool:
    try:
        return all(
            hasattr(pt, "__len__")
            and len(pt) == 2
            and _is_number(pt[0])
            and _is_number(pt[1])
            for pt in seq
        )
    except TypeError:
        return False


def load_aoi(aoi, layer: str | None = None) -> BaseGeometry:
    """Resolve an AOI of any supported type to a single shapely geometry in WGS84.

    The input is taken as the complete area of interest. Multi-polygon inputs
    are preprocessed with :func:`merge_shared_boundaries`: polygons sharing a
    common boundary (or overlapping) are merged into one region, while
    disjoint polygons stay separate parts of the returned geometry.
    """
    if isinstance(aoi, np.ndarray):
        aoi = aoi.tolist()

    if isinstance(aoi, (gpd.GeoDataFrame, gpd.GeoSeries)):
        return merge_shared_boundaries(_geoms_from_geodata(aoi))

    if isinstance(aoi, BaseGeometry):
        return merge_shared_boundaries(aoi)

    if isinstance(aoi, dict):
        return merge_shared_boundaries(_geoms_from_geojson(aoi))

    if isinstance(aoi, (str, os.PathLike)):
        path = Path(aoi)
        if path.exists():
            read_kwargs = {"layer": layer} if layer else {}
            gdf = gpd.read_file(path, **read_kwargs)
            return merge_shared_boundaries(_geoms_from_geodata(gdf))
        if isinstance(aoi, str):
            try:
                geom = _wkt.loads(aoi)
            except Exception:  # noqa: BLE001 - fall through to a clear error
                geom = None
            if geom is not None:
                return merge_shared_boundaries(geom)
        raise FileNotFoundError(
            f"AOI {aoi!r} is not an existing file and is not valid WKT"
        )

    if isinstance(aoi, Sequence):
        seq = list(aoi)
        if len(seq) == 4 and all(_is_number(v) for v in seq):
            return bbox_to_geom(seq)
        if len(seq) >= 3 and _looks_like_ring(seq):
            return Polygon([(float(x), float(y)) for x, y in seq])
        raise ValueError(
            "Sequence AOI must be a 4-number bbox (min_lon, min_lat, max_lon, "
            "max_lat) or a ring of at least 3 (lon, lat) pairs"
        )

    raise TypeError(f"Unsupported AOI type: {type(aoi)!r}")
