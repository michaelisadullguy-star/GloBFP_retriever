"""Keyed multi-resolution geometric obfuscation ("grid cipher") for coordinates.

This applies a secret-key-dependent, spatially smooth, sub-metre displacement
field to coordinates. It is a reversible *watermark / obfuscation* (not content
encryption): nearby points move almost identically, so the data stays usable,
local geometry/topology is preserved, and only the holder of the secret key can
reproduce or undo the offsets. Without the key the per-point offsets are
unpredictable, so leaked copies can be fingerprinted.

How it works
------------
Five layers act on the data: the original coordinates (base) plus four grid
resolutions::

    spacing  7 km    3 km    1 km    300 m
    range   ±0.4 m  ±0.2 m  ±0.1 m  ±0.05 m

On each grid layer every grid *vertex* (cell corner) is given a pseudo-random
offset vector drawn from that layer's range. The offset is a keyed PRF of the
vertex's integer grid index, so adjacent cells agree on the corners they share
(the field is continuous, with no tears at cell edges). A point inside a cell is
warped by **bilinear interpolation** of its four corner offsets: the warp grows
toward the periphery (a point at a corner gets that corner's full offset; the
cell centre gets the average of the four). Each node's offset is the **sum** of
the four layers' interpolated offsets; that accumulated ``(dx, dy)`` is then
added to the node.

Key handling
------------
The secret key/seed is read from the ``GLOBFP_GEOCRYPT_KEY`` environment
variable (hex or passphrase) or a locked-down key file (default ``.geocrypt.key``,
git-ignored, ``chmod 600``). It is generated on first use if absent. The key
value is **never printed, logged, written into any output, committed, or
transmitted** - only the holder of the key can reverse the transform.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import struct
from pathlib import Path

import numpy as np
import shapely

log = logging.getLogger(__name__)

WGS84 = "EPSG:4326"

# (cell spacing in metres, max corner offset in metres) per grid layer.
DEFAULT_LAYERS = (
    (7000.0, 0.4),
    (3000.0, 0.2),
    (1000.0, 0.1),
    (300.0, 0.05),
)

KEY_ENV = "GLOBFP_GEOCRYPT_KEY"
DEFAULT_KEY_FILE = Path(os.environ.get("GLOBFP_GEOCRYPT_KEYFILE", ".geocrypt.key"))


# --------------------------------------------------------------------------- #
# Secret key management (never log or emit the key value)
# --------------------------------------------------------------------------- #
def _decode_key(text: str) -> bytes:
    text = text.strip()
    try:
        return bytes.fromhex(text)
    except ValueError:
        return text.encode("utf-8")  # allow a raw passphrase


def load_key(*, allow_generate: bool = True, key_file=None) -> bytes:
    """Return the secret key from the env var or key file (generating if absent).

    The returned bytes are sensitive: do not print, log, or serialise them.
    """
    raw = os.environ.get(KEY_ENV)
    if raw:
        return _decode_key(raw)
    kf = Path(key_file) if key_file is not None else DEFAULT_KEY_FILE
    if kf.exists():
        return _decode_key(kf.read_text())
    if not allow_generate:
        raise RuntimeError(
            f"No geocrypt key found in ${KEY_ENV} or {kf}; refusing to proceed."
        )
    key = secrets.token_bytes(32)
    kf.write_text(key.hex())
    try:
        os.chmod(kf, 0o600)
    except OSError:  # pragma: no cover - platform dependent
        pass
    # Log only the location, never the key material.
    log.warning(
        "geocrypt: generated a new 256-bit key at %s (git-ignored, chmod 600; "
        "its value is never logged or transmitted). Set $%s to manage it yourself.",
        kf,
        KEY_ENV,
    )
    return key


# --------------------------------------------------------------------------- #
# Keyed pseudo-random corner offsets + bilinear displacement field
# --------------------------------------------------------------------------- #
_TWO64 = float(1 << 64)


def _corner_offsets(key: bytes, layer: int, ii: np.ndarray, jj: np.ndarray, rng: float):
    """Vectorised keyed PRF: offset (dx, dy) in [-rng, rng] per grid vertex (i, j)."""
    pairs = np.stack([ii.ravel(), jj.ravel()], axis=1)
    uniq, inv = np.unique(pairs, axis=0, return_inverse=True)
    ox = np.empty(len(uniq))
    oy = np.empty(len(uniq))
    for k, (a, b) in enumerate(uniq):
        msg = struct.pack(">iqq", layer, int(a), int(b))
        digest = hmac.new(key, msg, hashlib.sha256).digest()
        ux = int.from_bytes(digest[0:8], "big") / _TWO64
        uy = int.from_bytes(digest[8:16], "big") / _TWO64
        ox[k] = (2.0 * ux - 1.0) * rng
        oy[k] = (2.0 * uy - 1.0) * rng
    return ox[inv].reshape(ii.shape), oy[inv].reshape(jj.shape)


def displacement(key: bytes, x, y, layers=DEFAULT_LAYERS):
    """Accumulated ``(dx, dy)`` offset (metres) for each node, summed over layers.

    ``x``/``y`` are planar coordinates in metres (e.g. UTM). This is the
    "node-specific value" assigned to every node before the final stretch.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    dx = np.zeros_like(x)
    dy = np.zeros_like(y)
    for layer_idx, (spacing, rng) in enumerate(layers):
        xs = x / spacing
        ys = y / spacing
        i0 = np.floor(xs).astype(np.int64)
        j0 = np.floor(ys).astype(np.int64)
        fx = xs - i0
        fy = ys - j0
        o00x, o00y = _corner_offsets(key, layer_idx, i0, j0, rng)
        o10x, o10y = _corner_offsets(key, layer_idx, i0 + 1, j0, rng)
        o01x, o01y = _corner_offsets(key, layer_idx, i0, j0 + 1, rng)
        o11x, o11y = _corner_offsets(key, layer_idx, i0 + 1, j0 + 1, rng)
        w00 = (1 - fx) * (1 - fy)
        w10 = fx * (1 - fy)
        w01 = (1 - fx) * fy
        w11 = fx * fy
        dx += o00x * w00 + o10x * w10 + o01x * w01 + o11x * w11
        dy += o00y * w00 + o10y * w10 + o01y * w01 + o11y * w11
    return dx, dy


def _make_fn(key, layers, inverse, iterations=5):
    def forward(coords):
        x = coords[:, 0]
        y = coords[:, 1]
        dx, dy = displacement(key, x, y, layers)
        return np.column_stack([x + dx, y + dy])

    def backward(coords):
        # Solve p + offset(p) = q for p by fixed-point iteration. The field is a
        # strong contraction (range/spacing << 1), so a few iterations reach
        # sub-micrometre accuracy.
        qx = coords[:, 0]
        qy = coords[:, 1]
        px, py = qx.copy(), qy.copy()
        for _ in range(iterations):
            dx, dy = displacement(key, px, py, layers)
            px = qx - dx
            py = qy - dy
        return np.column_stack([px, py])

    return backward if inverse else forward


# --------------------------------------------------------------------------- #
# GeoDataFrame transform
# --------------------------------------------------------------------------- #
def transform_gdf(gdf, key=None, *, inverse=False, layers=DEFAULT_LAYERS, metric_crs=None):
    """Apply (or, with ``inverse=True``, undo) the grid cipher to a GeoDataFrame.

    Geometries are projected to a metric CRS (UTM by default) for the
    metre-scale warp and returned in their original CRS. To undo a transform you
    must supply the same ``key``, ``layers`` and ``metric_crs``.
    """
    if key is None:
        key = load_key()
    src_crs = gdf.crs
    mcrs = metric_crs if metric_crs is not None else gdf.estimate_utm_crs()
    g = gdf.to_crs(mcrs)
    fn = _make_fn(key, layers, inverse)
    out = g.copy()
    out["geometry"] = shapely.transform(g.geometry.values, fn)
    return out.to_crs(src_crs)


def encrypt_gdf(gdf, key=None, **kw):
    """Apply the grid cipher (forward)."""
    return transform_gdf(gdf, key, inverse=False, **kw)


def decrypt_gdf(gdf, key=None, **kw):
    """Undo the grid cipher (requires the same secret key)."""
    return transform_gdf(gdf, key, inverse=True, **kw)
