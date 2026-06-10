# GloBFP-retriever

Download **cropped, small-block** building footprints from the
[3D-GloBFP](https://essd.copernicus.org/articles/16/5357/2024/) dataset for just
the area you care about — no whole-country downloads.

You give it an **area of interest** (a lon/lat bounding box, a boundary polygon,
or a local `.shp` / `.geojson` / `.json` file) and it:

1. treats your input as one complete AOI, first merging any polygons that
   share a common boundary (or overlap) into single regions,
2. figures out which 3D-GloBFP **grid tiles** intersect that area,
3. downloads **only those tiles** (zipped shapefiles on figshare),
4. keeps the building footprints intersecting your AOI (with their `height`),
5. writes them to a single small file (GeoJSON by default).

This is a Python re-implementation and extension of the ideas in the
[`gloBFPr`](https://github.com/billbillbilly/gloBFPr) R package, adding **polygon
and local-file AOI inputs** and **direct file output**.

## How it works

3D-GloBFP is published on figshare across ten articles. Every grid tile is a
separate zipped shapefile whose name encodes its extent:

```
gridID_xmin_ymin_xmax_ymax.zip
```

`get_metadata()` reads the figshare files API for those articles, parses the file
names into a grid of tile polygons + download URLs, and caches the result locally
(`grid_index.geojson`). Retrieval then intersects your AOI with that grid and pulls
only the matching tiles, caching each downloaded tile by `gridID` so repeated runs
over the same area are fast.

**AOI preprocessing.** Whatever form the AOI takes, it is treated as one
complete area of interest. If the input contains multiple polygons, polygons
that share a common boundary (or overlap) are first dissolved into a single
region; polygons that are disjoint, or touch only at isolated points, are kept
as separate parts of the AOI. Retrieval then runs against the resulting
geometry.

## Install

```bash
pip install -e .
# or just the runtime dependencies:
pip install -r requirements.txt
```

Requires Python ≥ 3.9 and `geopandas`, `shapely`, `pyproj`, `requests`, `pyogrio`.

## Command-line usage

```bash
# By bounding box (min_lon min_lat max_lon max_lat), WGS84:
globfp-retriever --bbox -84.4855 45.6361 -84.4628 45.6506 -o buildings.geojson

# By polygon ring:
globfp-retriever --polygon "-84.49,45.63 -84.46,45.63 -84.46,45.65 -84.49,45.65" -o area.geojson

# From a local boundary file (.shp / .geojson / .json), reprojected automatically:
globfp-retriever my_boundary.geojson -o out.gpkg -f gpkg

# Just see which tiles would be downloaded (no download):
globfp-retriever --bbox -84.49 45.63 -84.46 45.65 --list-tiles

# Clip buildings exactly to the AOI boundary instead of keeping whole footprints:
globfp-retriever my_boundary.shp --clip -o clipped.geojson

# Optional cleaning filters (all off by default; drop tiny / duplicate / triangular footprints):
globfp-retriever my_boundary.geojson --min-area 10 --drop-duplicates --drop-triangles -o clean.geojson

# Extrude footprints to 3D building solids (Wavefront OBJ):
globfp-retriever --bbox -84.49 45.63 -84.46 45.65 -o buildings.obj
```

Output format is inferred from the `-o` extension (or set with `-f`):
`geojson` (default), `gpkg`, `shp`, `fgb`, `parquet`, `obj`, `osm`.

`obj` is a 3D export: each footprint is extruded from the ground to its `height`
into a closed solid (walls + roof + floor). Coordinates are projected to local
UTM metres and shifted near the origin, with axes `X=east, Y=north, Z=up`.
Footprints without a usable height fall back to a 3&nbsp;m default. (Roofs of
strongly non-convex footprints use an approximate triangulation; walls are exact.)

`osm` writes OpenStreetMap XML: each footprint becomes a closed way (or a
`type=multipolygon` relation when it has holes) carrying its attributes as tags
(`building=yes`, `height=...`), with new objects using negative ids.

## Python usage

```python
from globfp_retriever import retrieve_globfp

# Bounding box
gdf = retrieve_globfp((-84.4855, 45.6361, -84.4628, 45.6506),
                      output="buildings.geojson")

# Polygon ring of (lon, lat) pairs
gdf = retrieve_globfp([(-84.49, 45.63), (-84.46, 45.63),
                       (-84.46, 45.65), (-84.49, 45.65)])

# Local file (any format geopandas can read); reprojected to WGS84 internally
gdf = retrieve_globfp("my_boundary.shp", output="out.gpkg", out_format="gpkg")

print(gdf.head())          # columns: height, building (="yes"), geometry  (EPSG:4326)
```

Useful options: `clip=True` (cut at the AOI boundary), `refresh_metadata=True`
(rebuild the grid index), `cache_dir=...`, `use_tile_cache=False`.

The grid index and tiles are cached under `~/.cache/globfp-retriever` by default
(override with `--cache-dir` or the `GLOBFP_CACHE_DIR` environment variable).

## Reproducible AOI runs (GitHub Actions)

Because some environments block outbound access to figshare, the repo includes a
workflow (`.github/workflows/retrieve-aoi.yml`) that runs the retrieval on a
GitHub-hosted runner (which has internet). Trigger it via *Actions → Retrieve
GloBFP for AOI → Run workflow* and provide either `aoi` (a repo path to a
boundary file, or a WKT polygon) or `bbox` (`min_lon min_lat max_lon max_lat`),
plus an optional output `format` and `clip` toggle. The cropped result is
uploaded as a build artifact; nothing is committed to the repository.

## Coordinate obfuscation (grid cipher)

`globfp_retriever.geocrypt` applies a **keyed, multi-resolution, sub-metre
displacement field** to coordinates — a reversible watermark/obfuscation (not
content encryption). Five layers act on the data: the original coordinates plus
four grids (7 km, 3 km, 1 km, 300 m). On each grid every cell **corner** gets a
pseudo-random offset (a keyed PRF of its integer grid index, so neighbouring
cells agree on shared corners), within `±0.4 / ±0.2 / ±0.1 / ±0.05` m
respectively. Points inside a cell are warped by **bilinear interpolation** of
the four corner offsets (continuous across cells, growing toward the periphery),
and the per-node offsets are **summed across layers** and added. The result
stays usable (nearby points move almost identically) yet carries a hidden,
owner-only-reversible fingerprint.

Watermarking is applied **automatically** to every written output by the backend
— there is no CLI/front-end switch. Set a persistent secret key so you keep
control and can reverse it later (otherwise a fresh key is generated per run):

```bash
export GLOBFP_GEOCRYPT_KEY=$(python -c "import secrets;print(secrets.token_hex(32))")
```

```python
from globfp_retriever import geocrypt
enc = geocrypt.encrypt_gdf(gdf)          # key from $GLOBFP_GEOCRYPT_KEY / key file
orig = geocrypt.decrypt_gdf(enc)         # round-trips to sub-micrometre
```

**Key confidentiality:** the secret key/seed is read from `$GLOBFP_GEOCRYPT_KEY`
or a git-ignored key file (`.geocrypt.key`, `chmod 600`), generated on first use.
Its value is never printed, logged, written into any output, committed, or
transmitted — without it the offsets cannot be predicted or removed. Keep it
backed up: lose the key and you lose the ability to recover the true coordinates.

## Notes & limitations

- **Network access is required** to reach `api.figshare.com` and
  `ndownloader.figshare.com`. In restricted/sandboxed environments these hosts may
  be blocked; run on a machine with outbound HTTPS to those domains.
- AOIs crossing the antimeridian (±180° longitude) are not specially handled.
- Building heights are in a lowercase `height` attribute (OSM-style; the source
  dataset names it `Height`). Every feature is also tagged `building=yes` (OSM
  convention); pass `building_tag=None` to `retrieve_globfp` to omit it.

## Data source & citation

Data: **3D-GloBFP** building footprints with height
([figshare](https://doi.org/10.6084/m9.figshare.c.7566563), grid index on
[Zenodo](https://zenodo.org/records/15487037)).

> Che, Y., Li, X., Liu, X., Wang, Y., Liao, W., Zheng, X., Zhang, X., Xu, X.,
> Shi, Q., Zhu, J., Zhang, H., Yuan, H., & Dai, Y. (2024). 3D-GloBFP: the first
> global three-dimensional building footprint dataset. *Earth System Science
> Data*, 16, 5357–5374. https://doi.org/10.5194/essd-16-5357-2024

Please cite the dataset authors when you use the data.

## License

Apache-2.0 (see [LICENSE](LICENSE)). The 3D-GloBFP data carries its own license
from its authors.
