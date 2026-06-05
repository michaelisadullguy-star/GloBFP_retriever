"""High-level retrieval: AOI -> intersecting tiles -> cropped building footprints."""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

from . import aoi as _aoi
from . import download as _download
from . import metadata as _metadata

log = logging.getLogger(__name__)

WGS84 = "EPSG:4326"

# Map output extensions / format names to pyogrio drivers.
_EXT_DRIVERS = {
    ".geojson": "GeoJSON",
    ".json": "GeoJSON",
    ".gpkg": "GPKG",
    ".shp": "ESRI Shapefile",
    ".fgb": "FlatGeobuf",
}
_NAME_DRIVERS = {
    "geojson": "GeoJSON",
    "json": "GeoJSON",
    "gpkg": "GPKG",
    "shp": "ESRI Shapefile",
    "shapefile": "ESRI Shapefile",
    "fgb": "FlatGeobuf",
    "flatgeobuf": "FlatGeobuf",
    "parquet": "Parquet",
}


def select_tiles(metadata: gpd.GeoDataFrame, aoi_geom) -> gpd.GeoDataFrame:
    """Return the subset of grid tiles whose extent intersects ``aoi_geom``."""
    positions = metadata.sindex.query(aoi_geom, predicate="intersects")
    return metadata.iloc[sorted(set(positions))]


def _load_tile(
    row, cache_dir=None, use_cache=True, session=None, timeout=120, retries=4, bbox=None
):
    """Indirection point so tests can stub tile downloading/reading."""
    return _download.download_and_read_tile(
        row,
        cache_dir=cache_dir,
        use_cache=use_cache,
        session=session,
        timeout=timeout,
        retries=retries,
        bbox=bbox,
    )


def _empty_result(height_field, building_tag="yes"):
    data = {height_field: []}
    if building_tag is not None:
        data["building"] = []
    return gpd.GeoDataFrame(data, geometry=[], crs=WGS84)


def retrieve_globfp(
    aoi,
    output=None,
    out_format=None,
    *,
    layer=None,
    metadata=None,
    cache_dir=None,
    refresh_metadata=False,
    use_tile_cache=True,
    clip=False,
    height_field="Height",
    building_tag="yes",
    session=None,
    timeout=120,
    retries=4,
):
    """Download and crop 3D-GloBFP building footprints for an area of interest.

    Parameters
    ----------
    aoi
        Area of interest: a ``(min_lon, min_lat, max_lon, max_lat)`` bbox, a ring of
        ``(lon, lat)`` pairs, a GeoJSON dict, a shapely geometry, a GeoDataFrame, or a
        path to a local vector file (``.shp`` / ``.geojson`` / ``.json`` / ...).
    output
        Optional output path. Format is inferred from its extension unless
        ``out_format`` is given.
    out_format
        Explicit output format: ``geojson`` (default), ``gpkg``, ``shp``, ``fgb`` or
        ``parquet``.
    metadata
        Pre-built grid index. If omitted it is loaded/cached via the figshare API.
    clip
        If ``True``, clip building geometries to the AOI boundary. Default ``False``
        keeps whole buildings that intersect the AOI.
    building_tag
        Value for an OSM-style ``building`` tag added to every feature. Defaults to
        ``"yes"``; pass ``None`` to omit the tag.

    Returns
    -------
    geopandas.GeoDataFrame
        Building footprints intersecting the AOI, in WGS84, with a ``Height`` column
        and (by default) a ``building=yes`` column.
    """
    aoi_geom = _aoi.load_aoi(aoi, layer=layer)
    cache_dir = Path(cache_dir) if cache_dir is not None else _metadata.default_cache_dir()

    if metadata is None:
        metadata = _metadata.load_or_build_metadata(
            cache_dir=cache_dir,
            refresh=refresh_metadata,
            session=session,
            timeout=timeout,
            retries=retries,
        )

    tiles = select_tiles(metadata, aoi_geom)
    log.info("%d grid tile(s) intersect the AOI", len(tiles))
    if len(tiles) == 0:
        log.warning("No tiles intersect the AOI; returning an empty result")
        result = _empty_result(height_field, building_tag)
        if output:
            _write_output(result, output, out_format)
        return result

    # Restrict tile reading to the AOI's bounding window (huge tiles are never
    # loaded into memory in full); precise polygon filtering happens afterwards.
    aoi_bbox = aoi_geom.bounds

    frames = []
    for ordinal, (_, row) in enumerate(tiles.iterrows(), start=1):
        log.info(
            "Tile %d/%d (gridID=%s): downloading/reading",
            ordinal,
            len(tiles),
            row.get("gridID"),
        )
        gdf = _load_tile(
            row,
            cache_dir=cache_dir,
            use_cache=use_tile_cache,
            session=session,
            timeout=timeout,
            retries=retries,
            bbox=aoi_bbox,
        )
        if gdf is None or len(gdf) == 0:
            continue
        gdf = _normalise_height(gdf, height_field)
        keep = [height_field] if height_field in gdf.columns else []
        frames.append(gdf[keep + ["geometry"]])

    if not frames:
        log.warning("No building features read from tiles; returning an empty result")
        result = _empty_result(height_field, building_tag)
        if output:
            _write_output(result, output, out_format)
        return result

    combined = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), geometry="geometry", crs=WGS84
    )

    # Keep every building whose footprint intersects the AOI (uncut).
    positions = combined.sindex.query(aoi_geom, predicate="intersects")
    result = combined.iloc[sorted(set(positions))].reset_index(drop=True)
    log.info("%d building footprint(s) intersect the AOI", len(result))

    if clip:
        result = gpd.clip(result, _aoi.aoi_to_gdf(aoi_geom)).reset_index(drop=True)
        log.info("Clipped to AOI boundary: %d feature(s) remain", len(result))

    # Tag every feature with an OSM-style building=yes alongside Height.
    if building_tag is not None:
        result["building"] = building_tag
        geom_name = result.geometry.name
        front = [c for c in (height_field, "building") if c in result.columns]
        rest = [c for c in result.columns if c not in front and c != geom_name]
        result = result[front + rest + [geom_name]]

    if output:
        _write_output(result, output, out_format)
    return result


def _normalise_height(gdf, height_field):
    """Rename a differently-cased height column to ``height_field`` if needed."""
    if height_field in gdf.columns:
        return gdf
    matches = [c for c in gdf.columns if c.lower() == height_field.lower()]
    if matches:
        return gdf.rename(columns={matches[0]: height_field})
    return gdf


def _resolve_driver(output: Path, out_format):
    if out_format:
        driver = _NAME_DRIVERS.get(out_format.lower())
        if driver is None:
            raise ValueError(f"Unknown output format: {out_format!r}")
        return driver
    ext = output.suffix.lower()
    if ext == ".parquet":
        return "Parquet"
    driver = _EXT_DRIVERS.get(ext)
    if driver is None:
        raise ValueError(
            f"Cannot infer output format from extension {ext!r}; pass out_format"
        )
    return driver


def _write_output(gdf: gpd.GeoDataFrame, output, out_format=None):
    output = Path(output)
    driver = _resolve_driver(output, out_format)
    output.parent.mkdir(parents=True, exist_ok=True)

    if len(gdf) == 0 and driver == "GeoJSON":
        # pyogrio cannot infer a geometry type for an empty layer; write a valid
        # empty FeatureCollection ourselves.
        output.write_text('{"type": "FeatureCollection", "features": []}')
    elif driver == "Parquet":
        gdf.to_parquet(output)
    else:
        gdf.to_file(output, driver=driver)
    log.info("Wrote %d feature(s) to %s", len(gdf), output)
    return output
