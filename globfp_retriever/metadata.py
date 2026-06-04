"""Build and cache the 3D-GloBFP grid index from the figshare API.

The dataset is split across ten figshare articles. Each *file* in an article is a
zipped shapefile for one grid tile, named ``gridID_xmin_ymin_xmax_ymax.zip``. We
query the figshare files API, parse those names into tile bounding boxes, and keep
each tile's ``download_url``. The result is an ``sf``-like GeoDataFrame grid that
maps geographic extent -> download URL, which is cached on disk for reuse.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import geopandas as gpd
import requests
from shapely.geometry import box

log = logging.getLogger(__name__)

WGS84 = "EPSG:4326"
CACHE_FILENAME = "grid_index.geojson"
USER_AGENT = "globfp-retriever (https://github.com/)"

# figshare article IDs holding the 3D-GloBFP grid tiles (mirrors the gloBFPr R pkg).
FIGSHARE_ARTICLES = [
    28879733,
    28881749,
    28882700,
    28889813,
    28890593,
    28891631,
    28903454,
    28903853,
    28904453,
    28906499,
]

FIGSHARE_FILES_API = "https://api.figshare.com/v2/articles/{article_id}/files?limit=1000"


def default_cache_dir() -> Path:
    """Directory used to cache the grid index and downloaded tiles."""
    env = os.environ.get("GLOBFP_CACHE_DIR")
    if env:
        return Path(env)
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(Path.home(), ".cache")
    return Path(base) / "globfp-retriever"


def metadata_cache_path(cache_dir=None) -> Path:
    cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    return cache_dir / CACHE_FILENAME


def _parse_tile_name(name: str):
    """Parse ``gridID_xmin_ymin_xmax_ymax(.zip)`` -> dict, or ``None`` if it doesn't fit."""
    if not name:
        return None
    stem = name[:-4] if name.lower().endswith(".zip") else name
    parts = stem.split("_")
    if len(parts) < 5:
        return None
    try:
        grid_id = int(float(parts[0]))
        xmin, ymin, xmax, ymax = (float(parts[i]) for i in range(1, 5))
    except (ValueError, IndexError):
        return None
    if xmin > xmax or ymin > ymax:
        return None
    return {"gridID": grid_id, "xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax}


def _request_json(url, session=None, timeout=60, retries=4, backoff=2.0):
    sess = session or requests
    last_error = None
    for attempt in range(retries + 1):
        try:
            resp = sess.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {resp.status_code} from {url}")
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as err:
            last_error = err
            if attempt < retries:
                wait = backoff ** (attempt + 1)
                log.warning("Request to %s failed (%s); retrying in %.0fs", url, err, wait)
                time.sleep(wait)
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def fetch_article_files(article_id, session=None, timeout=60, retries=4):
    """Return the list of file records for a figshare article."""
    url = FIGSHARE_FILES_API.format(article_id=article_id)
    return _request_json(url, session=session, timeout=timeout, retries=retries)


def build_metadata(articles=None, session=None, timeout=60, retries=4) -> gpd.GeoDataFrame:
    """Build the full grid index by querying figshare (requires network)."""
    articles = articles if articles is not None else FIGSHARE_ARTICLES
    rows = []
    seen_grid_ids = set()
    for article_id in articles:
        files = fetch_article_files(
            article_id, session=session, timeout=timeout, retries=retries
        )
        for record in files:
            info = _parse_tile_name(record.get("name", ""))
            if info is None:
                continue
            grid_id = info["gridID"]
            if grid_id in seen_grid_ids:
                continue
            seen_grid_ids.add(grid_id)
            rows.append(
                {
                    **info,
                    "article_id": article_id,
                    "file_id": record.get("id"),
                    "download_url": record.get("download_url"),
                    "geometry": box(
                        info["xmin"], info["ymin"], info["xmax"], info["ymax"]
                    ),
                }
            )
    if not rows:
        raise RuntimeError("No tiles parsed from figshare metadata")
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=WGS84)
    gdf["gridID"] = gdf["gridID"].astype("int64")
    return gdf.sort_values("gridID").reset_index(drop=True)


def load_or_build_metadata(
    cache_dir=None,
    refresh=False,
    session=None,
    timeout=60,
    retries=4,
    save=True,
) -> gpd.GeoDataFrame:
    """Load the cached grid index, building (and caching) it from figshare if needed."""
    cache_path = metadata_cache_path(cache_dir)
    if cache_path.exists() and not refresh:
        log.info("Loading cached grid index from %s", cache_path)
        gdf = gpd.read_file(cache_path)
        if "gridID" in gdf.columns:
            gdf["gridID"] = gdf["gridID"].astype("int64")
        return gdf

    log.info("Building grid index from the figshare API ...")
    gdf = build_metadata(session=session, timeout=timeout, retries=retries)
    if save:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(cache_path, driver="GeoJSON")
        log.info("Cached grid index (%d tiles) to %s", len(gdf), cache_path)
    return gdf


def get_metadata(*args, **kwargs) -> gpd.GeoDataFrame:
    """Alias of :func:`load_or_build_metadata` (mirrors gloBFPr's ``get_metadata``)."""
    return load_or_build_metadata(*args, **kwargs)
