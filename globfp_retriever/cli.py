"""Command-line interface for retrieving cropped 3D-GloBFP building footprints."""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__
from . import aoi as _aoi
from . import metadata as _metadata
from . import retrieve as _retrieve

log = logging.getLogger("globfp_retriever")

_DEFAULT_EXT = {
    "geojson": "geojson",
    "gpkg": "gpkg",
    "shp": "shp",
    "fgb": "fgb",
    "parquet": "parquet",
    "obj": "obj",
    "osm": "osm",
}


def _parse_polygon(text: str):
    """Parse ``"lon,lat lon,lat ..."`` (or space-separated numbers) into a ring."""
    numbers = [tok for tok in text.replace(",", " ").split() if tok]
    try:
        values = [float(tok) for tok in numbers]
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"invalid number in --polygon: {err}")
    if len(values) < 6 or len(values) % 2 != 0:
        raise argparse.ArgumentTypeError(
            "--polygon needs an even count of at least 3 lon,lat pairs"
        )
    return list(zip(values[0::2], values[1::2]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="globfp-retriever",
        description=(
            "Download and crop 3D-GloBFP building footprints for a small area of "
            "interest. Only the grid tiles intersecting the AOI are downloaded."
        ),
    )
    parser.add_argument(
        "aoi",
        nargs="?",
        help="Path to an AOI file (.shp/.geojson/.json) or a WKT polygon string",
    )
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
        help="Area of interest as a lon/lat bounding box (WGS84)",
    )
    parser.add_argument(
        "--polygon",
        type=_parse_polygon,
        help='Area of interest as a ring: "lon,lat lon,lat ..." (WGS84)',
    )
    parser.add_argument(
        "-o", "--output", help="Output path (default: globfp_buildings.<format>)"
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["geojson", "gpkg", "shp", "fgb", "parquet", "obj", "osm"],
        help="Output format (default: inferred from --output, else geojson). "
        "'obj' extrudes footprints to 3D solids; 'osm' writes OpenStreetMap XML.",
    )
    parser.add_argument("--layer", help="Layer name when the AOI file has multiple layers")
    parser.add_argument("--cache-dir", help="Directory for the grid index + tile cache")
    parser.add_argument(
        "--refresh-metadata",
        action="store_true",
        help="Rebuild the figshare grid index instead of using the cache",
    )
    parser.add_argument(
        "--no-tile-cache",
        action="store_true",
        help="Do not cache downloaded tiles to disk",
    )
    parser.add_argument(
        "--clip",
        action="store_true",
        help="Clip buildings to the AOI boundary (default: keep whole buildings)",
    )
    parser.add_argument(
        "--list-tiles",
        action="store_true",
        help="List the grid tiles intersecting the AOI and exit (no download)",
    )
    parser.add_argument("--timeout", type=float, default=120, help="HTTP timeout (s)")
    parser.add_argument("--retries", type=int, default=4, help="HTTP retry attempts")
    parser.add_argument("-q", "--quiet", action="store_true", help="Only warnings/errors")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose (debug) logs")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _resolve_aoi(args):
    provided = [x for x in (args.aoi, args.bbox, args.polygon) if x is not None]
    if len(provided) != 1:
        raise SystemExit(
            "error: provide exactly one area of interest "
            "(an AOI path/WKT argument, --bbox, or --polygon)"
        )
    if args.bbox is not None:
        return tuple(args.bbox)
    if args.polygon is not None:
        return args.polygon
    return args.aoi


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.quiet:
        level = logging.WARNING
    elif args.verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(message)s")

    aoi = _resolve_aoi(args)

    if args.list_tiles:
        meta = _metadata.load_or_build_metadata(
            cache_dir=args.cache_dir,
            refresh=args.refresh_metadata,
            timeout=args.timeout,
            retries=args.retries,
        )
        geom = _aoi.load_aoi(aoi, layer=args.layer)
        tiles = _retrieve.select_tiles(meta, geom)
        print(f"{len(tiles)} tile(s) intersect the AOI:")
        for _, row in tiles.iterrows():
            print(
                f"  gridID={row.get('gridID')}  "
                f"bbox=({row.get('xmin')}, {row.get('ymin')}, "
                f"{row.get('xmax')}, {row.get('ymax')})  {row.get('download_url')}"
            )
        return 0

    output = args.output
    if output is None:
        ext = _DEFAULT_EXT.get(args.format or "geojson", "geojson")
        output = f"globfp_buildings.{ext}"

    result = _retrieve.retrieve_globfp(
        aoi,
        output=output,
        out_format=args.format,
        layer=args.layer,
        cache_dir=args.cache_dir,
        refresh_metadata=args.refresh_metadata,
        use_tile_cache=not args.no_tile_cache,
        clip=args.clip,
        timeout=args.timeout,
        retries=args.retries,
    )
    print(f"Retrieved {len(result)} building footprint(s) -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
