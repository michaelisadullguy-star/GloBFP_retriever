"""Retrieve cropped, small-block 3D-GloBFP building footprints for an area of interest.

The 3D-GloBFP dataset (Che et al., 2024/2025) is published on figshare as a large
number of *grid tiles*, each a zipped shapefile named
``gridID_xmin_ymin_xmax_ymax.zip`` carrying a per-building ``Height`` attribute.

This package lets you pass a small area of interest -- a lon/lat bounding box, a
boundary polygon, or a local vector file (``.shp`` / ``.geojson`` / ``.json``) --
and it downloads *only* the tiles that intersect that area, then returns/saves the
building footprints intersecting it. You never download a whole-country dataset.

The input is treated as one complete AOI: polygons that share a common boundary
(or overlap) are merged into single regions before retrieval, while disjoint
polygons stay separate parts of the AOI.

Example
-------
>>> from globfp_retriever import retrieve_globfp
>>> gdf = retrieve_globfp((-84.4855, 45.6361, -84.4628, 45.6506),
...                       output="buildings.geojson")
"""

from .aoi import load_aoi, bbox_to_geom, aoi_to_gdf
from .metadata import (
    FIGSHARE_ARTICLES,
    build_metadata,
    get_metadata,
    load_or_build_metadata,
    default_cache_dir,
)
from .retrieve import retrieve_globfp, select_tiles

__version__ = "0.1.0"

__all__ = [
    "retrieve_globfp",
    "select_tiles",
    "load_aoi",
    "bbox_to_geom",
    "aoi_to_gdf",
    "build_metadata",
    "get_metadata",
    "load_or_build_metadata",
    "default_cache_dir",
    "FIGSHARE_ARTICLES",
    "__version__",
]
