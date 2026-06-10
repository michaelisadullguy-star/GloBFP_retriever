"""Optional footprint-cleaning filters (area, exact duplicates, triangles).

All filters are opt-in: by default nothing is removed. They are exposed through
``retrieve_globfp`` parameters and the CLI so a user can enable them manually.
"""

from __future__ import annotations

import logging
from collections import Counter

import numpy as np
import shapely

log = logging.getLogger(__name__)


def _areas_m2(gdf, metric_crs=None):
    mcrs = metric_crs if metric_crs is not None else gdf.estimate_utm_crs()
    return gdf.to_crs(mcrs).geometry.area.values


def filter_min_area(gdf, min_area, metric_crs=None):
    """Drop footprints smaller than ``min_area`` m². Returns ``(gdf, n_removed)``."""
    if not min_area or min_area <= 0 or len(gdf) == 0:
        return gdf, 0
    keep = _areas_m2(gdf, metric_crs) >= float(min_area)
    return gdf.loc[keep].reset_index(drop=True), int((~keep).sum())


def remove_exact_duplicates(gdf):
    """Drop *every* member of each group of footprints with identical geometry."""
    if len(gdf) == 0:
        return gdf, 0
    keys = [shapely.normalize(g).wkb for g in gdf.geometry]
    counts = Counter(keys)
    keep = np.array([counts[k] == 1 for k in keys])
    return gdf.loc[keep].reset_index(drop=True), int((~keep).sum())


def _is_triangle(geom) -> bool:
    """True for a single Polygon with exactly three distinct exterior vertices."""
    if geom is None or geom.is_empty or geom.geom_type != "Polygon":
        return False
    if len(geom.interiors) > 0:
        return False
    coords = list(geom.exterior.coords)
    n = len(coords) - 1 if len(coords) > 1 and coords[0] == coords[-1] else len(coords)
    return n == 3


def remove_triangles(gdf):
    """Drop triangular footprints (3-vertex polygons). Returns ``(gdf, n_removed)``."""
    if len(gdf) == 0:
        return gdf, 0
    keep = np.array([not _is_triangle(g) for g in gdf.geometry])
    return gdf.loc[keep].reset_index(drop=True), int((~keep).sum())


def clean_buildings(
    gdf, *, min_area=None, drop_duplicates=False, drop_triangles=False, metric_crs=None
):
    """Apply the enabled cleaning filters and return ``(gdf, stats)``.

    ``stats`` records the input/output counts and how many each enabled rule
    removed (applied in order: triangles, area, duplicates).
    """
    stats = {"input": len(gdf)}
    if drop_triangles:
        gdf, stats["triangles"] = remove_triangles(gdf)
    if min_area:
        gdf, stats["min_area"] = filter_min_area(gdf, min_area, metric_crs)
    if drop_duplicates:
        gdf, stats["duplicates"] = remove_exact_duplicates(gdf)
    stats["output"] = len(gdf)
    return gdf, stats
