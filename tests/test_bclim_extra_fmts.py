"""Same-size encode for BCLIM formats that used to fall through to png2bclim."""
from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image

from bclimutil import (
    decode_bclim_to_image,
    decode_etc1a4_pixels,
    encode_etc1a4_pixels,
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


def test_etc1a4_1x1_passes_pack_validator_again(tmp_path: Path):
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


def test_rgb8_stored_as_bgr(tmp_path: Path):
    w, h = 8, 8
    orig = _write_bclim(tmp_path, w, h, 6, bytes(w * h * 3))
    png = tmp_path / "t.png"
    Image.new("RGBA", (w, h), (255, 0, 0, 255)).save(png)
    out = png_to_bclim_same_size(png, orig)
    pix, ow, oh, fmt, _ = parse_bclim(out)
    assert (ow, oh, fmt) == (w, h, 6)
    assert pix[:3] == bytes((0, 0, 255))
    assert decode_bclim_to_image(out).getpixel((0, 0)) == (255, 0, 0, 255)


def test_rgba8_stored_as_abgr(tmp_path: Path):
    w, h = 8, 8
    orig = _write_bclim(tmp_path, w, h, 9, bytes(w * h * 4))
    png = tmp_path / "t.png"
    Image.new("RGBA", (w, h), (10, 20, 30, 200)).save(png)
    out = png_to_bclim_same_size(png, orig)
    pix, ow, oh, fmt, _ = parse_bclim(out)
    assert (ow, oh, fmt) == (w, h, 9)
    assert pix[:4] == bytes((200, 30, 20, 10))
    assert decode_bclim_to_image(out).getpixel((0, 0)) == (10, 20, 30, 200)


def test_etc1a4_keeps_untouched_tiles(tmp_path: Path):
    w, h = 16, 8
    img = Image.new("RGBA", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = ((x * 17) & 255, (y * 40) & 255, 90, 255)
    raw = encode_etc1a4_pixels(img, w, h)
    decoded = decode_etc1a4_pixels(raw, w, h)
    assert encode_etc1a4_pixels(decoded, w, h, keep=raw) == raw

    edited = decoded.copy()
    ep = edited.load()
    for y in range(8):
        for x in range(8, 16):
            ep[x, y] = (0, 255, 0, 255)
    mixed = encode_etc1a4_pixels(edited, w, h, keep=raw)
    assert mixed[:64] == raw[:64]
    assert mixed[64:] != raw[64:]

    orig = _write_bclim(tmp_path, w, h, 0xB, raw)
    png = tmp_path / "t.png"
    decoded.save(png)
    out = png_to_bclim_etc1a4_same_size(png, orig)
    assert parse_bclim(out)[0] == raw


def test_etc1a4_can_grow_logical_height(tmp_path: Path):
    from bclimutil import png_to_bclim_etc1a4

    w, h = 8, 8
    pix = bytes(64)
    orig = _write_bclim(tmp_path, w, h, 0xB, pix)
    png = tmp_path / "t.png"
    Image.new("RGBA", (w, 16), (255, 255, 255, 255)).save(png)
    out = png_to_bclim_etc1a4(png, orig, size=(w, 16))
    assert len(out) > orig.stat().st_size
    _p, ow, oh, fmt, _ = parse_bclim(out)
    assert (ow, oh, fmt) == (w, 16, 0xB)
