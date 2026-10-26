"""Mini-game ``.l2mgtex`` textures (img.bin pkgs 94–155).

Each file is a 0x80-byte header followed by raw PICA texture data:

  +0x00  u32 width
  +0x04  u32 height
  +0x08  u32 format (13 = ETC1A4, same block order as BCLIM fmt 0xB;
                    10 = RGBA8, 8×8 Morton tiles stored A, B, G, R;
                    9 = RGBA4444, same tiles, u16 LE R:G:B:A nibbles)
  +0x0C  u32 data length
  +0x10  zero pad to 0x80

The package entry stores each file as its own zlib stream, so a same-size
splice only has to keep that element's ``cmp_len``.
"""
from __future__ import annotations

import struct

import numpy as np
from PIL import Image

from bclimutil import d2xy, decode_etc1a4_pixels, encode_etc1a4_pixels

HEADER_LEN = 0x80
FMT_RGBA4444 = 9
FMT_RGBA8 = 10
FMT_ETC1A4 = 13


def _texel_index(w: int, h: int) -> np.ndarray:
    """Texel index of each (y, x) in 8×8 Morton tiles."""
    idx = np.zeros((h, w), np.int64)
    tiles_x = w // 8
    for i in range(w * h):
        mx, my = d2xy(i % 64)
        t = i // 64
        idx[my + (t // tiles_x) * 8, mx + (t % tiles_x) * 8] = i
    return idx


def parse_header(data: bytes) -> tuple[int, int, int, int]:
    """Return ``(width, height, fmt, data_len)``."""
    if len(data) < HEADER_LEN:
        raise ValueError(f"l2mgtex too short ({len(data)} bytes)")
    w, h, fmt, n = struct.unpack_from("<4I", data, 0)
    if len(data) != HEADER_LEN + n:
        raise ValueError(f"l2mgtex length {len(data)} != header {HEADER_LEN} + {n}")
    return w, h, fmt, n


def decode(data: bytes) -> Image.Image:
    w, h, fmt, n = parse_header(data)
    body = data[HEADER_LEN : HEADER_LEN + n]
    if fmt == FMT_ETC1A4:
        return decode_etc1a4_pixels(body, w, h)
    if fmt == FMT_RGBA8:
        b = np.frombuffer(body, np.uint8)
        o = _texel_index(w, h) * 4
        return Image.fromarray(np.dstack([b[o + 3], b[o + 2], b[o + 1], b[o]]), "RGBA")
    if fmt == FMT_RGBA4444:
        v = np.frombuffer(body, "<u2")[_texel_index(w, h)].astype(np.uint16)
        px = np.dstack([(v >> 12) & 15, (v >> 8) & 15, (v >> 4) & 15, v & 15]) * 17
        return Image.fromarray(px.astype(np.uint8), "RGBA")
    raise ValueError(f"l2mgtex fmt {fmt} not supported")


def encode_like(orig: bytes, im: Image.Image) -> bytes:
    """Encode ``im`` with ``orig``'s header (same size and format)."""
    w, h, fmt, n = parse_header(orig)
    if im.size != (w, h):
        raise ValueError(f"image {im.size} != texture {w}x{h}")
    if fmt == FMT_ETC1A4:
        body = encode_etc1a4_pixels(im.convert("RGBA"), w, h)
    elif fmt == FMT_RGBA8:
        # Texels clear in both keep their vanilla bytes (vanilla stores white
        # under alpha 0), so untouched areas compress exactly as before.
        o = _texel_index(w, h) * 4
        px = np.array(im.convert("RGBA"))
        out = np.frombuffer(orig[HEADER_LEN:], np.uint8).copy()
        write = ~((px[..., 3] == 0) & (out[o] == 0))
        o, px = o[write], px[write]
        out[o], out[o + 1], out[o + 2], out[o + 3] = px[:, 3], px[:, 2], px[:, 1], px[:, 0]
        body = out.tobytes()
    elif fmt == FMT_RGBA4444:
        # Same rule as RGBA8: clear-in-both texels keep their vanilla bits.
        idx = _texel_index(w, h)
        px = (np.array(im.convert("RGBA")).astype(np.uint32) * 15 + 127) // 255
        v = ((px[..., 0] << 12) | (px[..., 1] << 8) | (px[..., 2] << 4) | px[..., 3]).astype(np.uint16)
        out = np.frombuffer(orig[HEADER_LEN:], "<u2").copy()
        write = ~((px[..., 3] == 0) & ((out[idx] & 15) == 0))
        out[idx[write]] = v[write]
        body = out.astype("<u2").tobytes()
    else:
        raise ValueError(f"l2mgtex fmt {fmt} not supported")
    if len(body) != n:
        raise ValueError(f"encoded {len(body)} bytes != {n}")
    return orig[:HEADER_LEN] + body
