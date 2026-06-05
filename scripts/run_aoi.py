"""Run a 3D-GloBFP retrieval for an AOI file and write GeoJSON + GPKG outputs.

Used by the GitHub Actions workflow to produce a downloadable artifact, but it
works locally too:

    python scripts/run_aoi.py examples/dongshan_nanjing.geojson
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from globfp_retriever import retrieve_globfp


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("aoi", help="Path to the AOI file (.shp/.geojson/.json)")
    parser.add_argument("--cache-dir", default=".globfp-cache")
    parser.add_argument("--outdir", default="output")
    parser.add_argument("--stem", default="aoi_buildings", help="Output file base name")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    os.makedirs(args.outdir, exist_ok=True)

    gdf = retrieve_globfp(args.aoi, cache_dir=args.cache_dir)
    print(f"Buildings found: {len(gdf)}")
    print(f"Columns: {list(gdf.columns)}")
    print(f"CRS: {gdf.crs}")

    if len(gdf) == 0:
        print("No buildings intersect the AOI; nothing written.")
        return 0

    if "Height" in gdf.columns:
        heights = gdf["Height"].dropna()
        if len(heights):
            print(
                f"Height (m): min={heights.min():.1f} "
                f"mean={heights.mean():.1f} max={heights.max():.1f}"
            )

    geojson_path = os.path.join(args.outdir, f"{args.stem}.geojson")
    gpkg_path = os.path.join(args.outdir, f"{args.stem}.gpkg")
    gdf.to_file(geojson_path, driver="GeoJSON")
    gdf.to_file(gpkg_path, driver="GPKG")
    print(f"Wrote {geojson_path}")
    print(f"Wrote {gpkg_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
