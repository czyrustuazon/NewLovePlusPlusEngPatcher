"""Same-size encode for BCLIM formats that used to fall through to png2bclim."""
from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image

from bclimutil import (
    parse_bclim,
    png_to_bclim_etc1a4_same_size,
    png_to_bclim_same_size,
)


def _footer(w: int, h: int, fmt: int, pix_len: int) -> bytes:
    # Real 40-byte CLIM/imag footer (fmt 5 48x16 sample).
    raw = bytes.fromhex(
        "434c494dfffe1400000002022808000001000000696d616710000000300010000500000000080000"
    )
    buf = bytearray(raw)
    imag = buf.find(b"imag")
    struct.pack_into("<HHI", buf, imag + 8, w, h, fmt)
    struct.pack_into("<I", buf, imag + 16, pix_len)
    struct.pack_into("<I", buf, 0x0C, pix_len + len(buf))
    return bytes(buf)


def _write_bclim(tmp: Path, w: int, h: int, fmt: int, pix: bytes) -> Path:
    dest = tmp / f"{fmt}_{w}x{h}.bclim"
    dest.write_bytes(pix + _footer(w, h, fmt, len(pix)))
    return dest


def test_fmt5_rgb565_same_size(tmp_path: Path):
    w, h = 48, 16
    pix = bytes(2048)
    orig = _write_bclim(tmp_path, w, h, 5, pix)
    png = tmp_path / "t.png"
    Image.new("RGBA", (w, h), (40, 80, 160, 255)).save(png)
    out = png_to_bclim_same_size(png, orig)
    assert len(out) == orig.stat().st_size
    _p, ow, oh, fmt, _ = parse_bclim(out)
    assert (ow, oh, fmt) == (w, h, 5)


def test_fmt9_rgba8_same_size(tmp_path: Path):
    w, h = 56, 16
    pix = bytes(4096)
    orig = _write_bclim(tmp_path, w, h, 9, pix)
    png = tmp_path / "t.png"
    Image.new("RGBA", (w, h), (10, 20, 30, 200)).save(png)
    out = png_to_bclim_same_size(png, orig)
    assert len(out) == orig.stat().st_size
    _p, ow, oh, fmt, _ = parse_bclim(out)
    assert (ow, oh, fmt) == (w, h, 9)


def test_fmt2_la4_same_size(tmp_path: Path):
    w, h = 64, 16
    pix = bytes(1024)
    orig = _write_bclim(tmp_path, w, h, 2, pix)
    png = tmp_path / "t.png"
    Image.new("RGBA", (w, h), (200, 200, 200, 180)).save(png)
    out = png_to_bclim_same_size(png, orig)
    assert len(out) == orig.stat().st_size


def test_fmt0_l8_same_size(tmp_path: Path):
    w, h = 98, 14
    pix = bytes(2048)
    orig = _write_bclim(tmp_path, w, h, 0, pix)
    png = tmp_path / "t.png"
    Image.new("RGBA", (w, h), (90, 90, 90, 255)).save(png)
    out = png_to_bclim_same_size(png, orig)
    assert len(out) == orig.stat().st_size


def test_etc1a4_1x1_passes_pack_validator(tmp_path: Path):
    from pack_images import _bclim_looks_valid, convert_png_to_bclim

    w, h = 1, 1
    pix = bytes(64)
    orig = _write_bclim(tmp_path, w, h, 0xB, pix)
    png = tmp_path / "t.png"
    Image.new("RGBA", (w, h), (0, 0, 0, 255)).save(png)
    produced = convert_png_to_bclim(png, orig, tmp_path / "work")
    ok, reason = _bclim_looks_valid(produced, orig.stat().st_size)
    assert ok, reason
    assert produced.stat().st_size == 104
    w, h = 1, 1
    pix = bytes(64)  # 8x8 ETC1A4
    orig = _write_bclim(tmp_path, w, h, 0xB, pix)
    png = tmp_path / "t.png"
    Image.new("RGBA", (w, h), (0, 0, 0, 255)).save(png)
    out = png_to_bclim_etc1a4_same_size(png, orig)
    assert len(out) == orig.stat().st_size
    _p, ow, oh, fmt, _ = parse_bclim(out)
    assert (ow, oh, fmt) == (1, 1, 0xB)


def test_etc1a4_1x1_passes_pack_validator(tmp_path: Path):
    from pack_images import _bclim_looks_valid, convert_png_to_bclim

    w, h = 1, 1
    pix = bytes(64)
    orig = _write_bclim(tmp_path, w, h, 0xB, pix)
    png = tmp_path / "t.png"
    Image.new("RGBA", (w, h), (0, 0, 0, 255)).save(png)
    produced = convert_png_to_bclim(png, orig, tmp_path / "work")
    ok, reason = _bclim_looks_valid(produced, orig.stat().st_size)
    assert ok, reason
    assert produced.stat().st_size == 104
