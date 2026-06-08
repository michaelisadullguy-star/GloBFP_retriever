"""Write building footprints as an OpenStreetMap XML (``.osm``) file.

Each footprint becomes a closed way tagged with the feature's attributes (e.g.
``building=yes``, ``height=...``); polygons with holes or multipolygons become a
``type=multipolygon`` relation with outer/inner ways. New objects use negative
ids (the JOSM convention for not-yet-uploaded data). Coordinates are WGS84
lat/lon, as OSM requires.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from xml.sax.saxutils import quoteattr

log = logging.getLogger(__name__)

WGS84 = "EPSG:4326"


def _iter_polygons(geom):
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == "Polygon":
        yield geom
    elif geom.geom_type == "MultiPolygon":
        for part in geom.geoms:
            if not part.is_empty:
                yield part


def _fmt_tag(value):
    """Format a property value as an OSM tag string, or ``None`` to drop it."""
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value):
            return None
        text = f"{value:.3f}".rstrip("0").rstrip(".")
        return text or "0"
    text = str(value)
    return text if text != "" else None


def write_osm(gdf, output, *, height_field="height"):
    """Write ``gdf`` building footprints to an OSM XML file.

    All non-geometry columns are emitted as OSM tags (so a ``height`` column
    becomes ``height=...`` and a ``building`` column becomes ``building=...``).
    ``height_field`` is accepted for signature parity with the other writers.
    """
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    g = gdf
    if len(g):
        if g.crs is None:
            g = g.set_crs(WGS84)
        elif g.crs.to_epsg() != 4326:
            g = g.to_crs(WGS84)

    geom_name = g.geometry.name
    tag_cols = [c for c in g.columns if c != geom_name]
    col_data = {c: list(g[c]) for c in tag_cols}
    geoms = list(g.geometry.values)

    nodes: list[str] = []
    ways: list[str] = []
    relations: list[str] = []
    node_id = [0]
    way_id = [0]
    rel_id = [0]

    def make_nodes(ring):
        coords = list(ring.coords)
        if len(coords) > 1 and coords[0] == coords[-1]:
            coords = coords[:-1]
        refs = []
        for x, y in coords:
            node_id[0] -= 1
            nodes.append(f"  <node id='{node_id[0]}' lat='{y:.7f}' lon='{x:.7f}' visible='true'/>")
            refs.append(node_id[0])
        return refs

    def emit_way(refs, tags):
        way_id[0] -= 1
        wid = way_id[0]
        lines = [f"  <way id='{wid}' visible='true'>"]
        lines += [f"    <nd ref='{r}'/>" for r in (*refs, refs[0])]
        lines += [f"    <tag k={quoteattr(k)} v={quoteattr(v)}/>" for k, v in tags]
        lines.append("  </way>")
        ways.append("\n".join(lines))
        return wid

    nfeat = 0
    for idx, geom in enumerate(geoms):
        polys = list(_iter_polygons(geom))
        if not polys:
            continue
        tags = []
        for col in tag_cols:
            val = _fmt_tag(col_data[col][idx])
            if val is not None:
                tags.append((col, val))

        if len(polys) == 1 and not polys[0].interiors:
            refs = make_nodes(polys[0].exterior)
            if len(refs) < 3:
                continue
            emit_way(refs, tags)
        else:
            members = []
            for poly in polys:
                outer = make_nodes(poly.exterior)
                if len(outer) >= 3:
                    members.append(("outer", emit_way(outer, [])))
                for hole in poly.interiors:
                    inner = make_nodes(hole)
                    if len(inner) >= 3:
                        members.append(("inner", emit_way(inner, [])))
            if not members:
                continue
            rel_id[0] -= 1
            lines = [f"  <relation id='{rel_id[0]}' visible='true'>"]
            lines += [
                f"    <member type='way' ref='{ref}' role='{role}'/>"
                for role, ref in members
            ]
            lines += [
                f"    <tag k={quoteattr(k)} v={quoteattr(v)}/>"
                for k, v in (("type", "multipolygon"), *tags)
            ]
            lines.append("  </relation>")
            relations.append("\n".join(lines))
        nfeat += 1

    head = ["<?xml version='1.0' encoding='UTF-8'?>", "<osm version='0.6' generator='globfp-retriever'>"]
    if len(g):
        minx, miny, maxx, maxy = g.total_bounds
        if minx == minx:  # not NaN
            head.append(
                f"  <bounds minlat='{miny:.7f}' minlon='{minx:.7f}' "
                f"maxlat='{maxy:.7f}' maxlon='{maxx:.7f}'/>"
            )
    body = head + nodes + ways + relations + ["</osm>"]
    output.write_text("\n".join(body) + "\n", encoding="utf-8")
    log.info("Wrote %d building(s) to %s", nfeat, output)
    return output
