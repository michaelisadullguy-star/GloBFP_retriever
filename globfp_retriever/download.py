"""Download 3D-GloBFP grid tiles and read them as GeoDataFrames.

Tiles are zipped shapefiles. Downloads are streamed to disk (atomically) with
exponential-backoff retries, optionally cached by ``gridID`` so re-runs over the
same area do not re-download.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

log = logging.getLogger(__name__)

WGS84 = "EPSG:4326"
USER_AGENT = "globfp-retriever (https://github.com/)"


def download_file(
    url,
    dest,
    session=None,
    timeout=120,
    retries=4,
    backoff=2.0,
    chunk_size=1 << 20,
) -> Path:
    """Stream ``url`` to ``dest`` atomically, retrying transient network errors."""
    sess = session or requests
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    last_error = None
    for attempt in range(retries + 1):
        try:
            with sess.get(
                url, stream=True, timeout=timeout, headers={"User-Agent": USER_AGENT}
            ) as resp:
                resp.raise_for_status()
                with open(tmp, "wb") as handle:
                    for block in resp.iter_content(chunk_size=chunk_size):
                        if block:
                            handle.write(block)
            os.replace(tmp, dest)
            return dest
        except requests.RequestException as err:
            last_error = err
            tmp.unlink(missing_ok=True)
            if attempt < retries:
                wait = backoff ** (attempt + 1)
                log.warning("Download of %s failed (%s); retrying in %.0fs", url, err, wait)
                time.sleep(wait)
    raise RuntimeError(f"Failed to download {url}: {last_error}")


def extract_shapefiles(zip_path, extract_dir):
    """Extract a tile zip and return the ``.shp`` files it contains."""
    extract_dir = Path(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    if not zipfile.is_zipfile(zip_path):
        raise ValueError(f"Not a valid zip file: {zip_path}")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)
    return sorted(extract_dir.rglob("*.shp"))


def read_tile(zip_path, extract_dir=None):
    """Read a downloaded tile zip into a single WGS84 GeoDataFrame (or ``None``)."""
    cleanup = extract_dir is None
    if extract_dir is None:
        extract_dir = Path(tempfile.mkdtemp(prefix="globfp_tile_"))
    try:
        shp_files = extract_shapefiles(zip_path, extract_dir)
        if not shp_files:
            log.warning("No .shp found inside %s", zip_path)
            return None
        frames = []
        for shp in shp_files:
            try:
                frames.append(gpd.read_file(shp))
            except Exception as err:  # noqa: BLE001 - skip unreadable parts, keep going
                log.warning("Failed to read %s: %s", shp, err)
        if not frames:
            return None
        if len(frames) == 1:
            gdf = frames[0]
        else:
            gdf = gpd.GeoDataFrame(
                pd.concat(frames, ignore_index=True), geometry="geometry", crs=frames[0].crs
            )
        if gdf.crs is None:
            gdf = gdf.set_crs(WGS84, allow_override=True)
        elif gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(WGS84)
        return gdf
    finally:
        if cleanup:
            shutil.rmtree(extract_dir, ignore_errors=True)


def tile_cache_path(cache_dir, grid_id) -> Path:
    return Path(cache_dir) / "tiles" / f"{int(grid_id)}.zip"


def download_and_read_tile(
    row,
    cache_dir=None,
    use_cache=True,
    session=None,
    timeout=120,
    retries=4,
):
    """Download (or reuse a cached) tile described by ``row`` and read it."""
    url = row["download_url"]
    grid_id = row.get("gridID") if hasattr(row, "get") else row["gridID"]

    if cache_dir is not None and grid_id is not None:
        zip_path = tile_cache_path(cache_dir, grid_id)
        if use_cache and zip_path.exists() and zipfile.is_zipfile(zip_path):
            log.info("Using cached tile %s", zip_path)
        else:
            download_file(url, zip_path, session=session, timeout=timeout, retries=retries)
        return read_tile(zip_path)

    tmp_dir = Path(tempfile.mkdtemp(prefix="globfp_dl_"))
    try:
        zip_path = tmp_dir / f"{grid_id if grid_id is not None else 'tile'}.zip"
        download_file(url, zip_path, session=session, timeout=timeout, retries=retries)
        return read_tile(zip_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
