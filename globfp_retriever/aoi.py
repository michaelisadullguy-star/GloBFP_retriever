"""Parse heterogeneous area-of-interest (AOI) inputs into a WGS84 geometry.

Accepted inputs:
  * a bounding box ``(min_lon, min_lat, max_lon, max_lat)``,
  * a polygon ring as a sequence of ``(lon, lat)`` pairs,
  * a GeoJSON-like ``dict`` (geometry, Feature or FeatureCollection),
  * a shapely geometry, ``GeoDataFrame`` or ``GeoSeries``,
  * a path to a local vector file (``.shp``, ``.geojson``, ``.json``, ...),
  * a WKT string.

Everything is returned as a single shapely geometry in EPSG:4326.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely import wkt as _wkt
from shapely.geometry import Polygon, box, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

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


def _union(geo) -> BaseGeometry:
    # geopandas >= 0.14 prefers union_all(); fall back to unary_union otherwise.
    if hasattr(geo, "union_all"):
        return geo.union_all()
    return geo.unary_union


def _from_geodata(geo) -> BaseGeometry:
    if geo.crs is None:
        # No CRS recorded; assume the coordinates are already lon/lat (WGS84).
        geo = geo.set_crs(WGS84, allow_override=True)
    elif geo.crs.to_epsg() != 4326:
        geo = geo.to_crs(WGS84)
    geometry = geo.geometry if isinstance(geo, gpd.GeoDataFrame) else geo
    if len(geometry) == 0:
        raise ValueError("AOI contains no geometry")
    return _union(geometry)


def _geom_from_geojson(obj: dict) -> BaseGeometry:
    kind = obj.get("type")
    if kind == "FeatureCollection":
        geoms = [
            shape(f["geometry"])
            for f in obj.get("features", [])
            if f.get("geometry") is not None
        ]
        if not geoms:
            raise ValueError("GeoJSON FeatureCollection has no geometries")
        return unary_union(geoms)
    if kind == "Feature":
        if obj.get("geometry") is None:
            raise ValueError("GeoJSON Feature has no geometry")
        return shape(obj["geometry"])
    return shape(obj)


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
    """Resolve an AOI of any supported type to a single shapely geometry in WGS84."""
    if isinstance(aoi, np.ndarray):
        aoi = aoi.tolist()

    if isinstance(aoi, (gpd.GeoDataFrame, gpd.GeoSeries)):
        return _from_geodata(aoi)

    if isinstance(aoi, BaseGeometry):
        return aoi

    if isinstance(aoi, dict):
        return _geom_from_geojson(aoi)

    if isinstance(aoi, (str, os.PathLike)):
        path = Path(aoi)
        if path.exists():
            read_kwargs = {"layer": layer} if layer else {}
            gdf = gpd.read_file(path, **read_kwargs)
            return _from_geodata(gdf)
        if isinstance(aoi, str):
            try:
                return _wkt.loads(aoi)
            except Exception:  # noqa: BLE001 - fall through to a clear error
                pass
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
