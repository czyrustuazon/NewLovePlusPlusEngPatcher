"""Coverage for bclimutil's encoder guards and decode paths on tiny BCLIMs.

The "size mismatch" / "BCLIM size changed" guards hold for every real input,
so they are reached by monkeypatching an encoder or parse_bclim's footer.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

import bclimutil as bu
import fake_img as fi


def _file(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _png(tmp_path: Path, size=(8, 8), color=(200, 100, 50, 255)) -> Path:
    path = tmp_path / f"in_{size[0]}x{size[1]}.png"
    Image.new("RGBA", size, color).save(path)
    return path


def _a4(w: int = 8, h: int = 8) -> bytes:
    return fi.bclim(w, h, 0xD, pixels=bytes(w * h // 2))


def _etc(w: int = 8, h: int = 8, blocks: int | None = None) -> bytes:
    n = (w // 4) * (h // 4) if blocks is None else blocks
    return fi.bclim(w, h, 0xB, pixels=bytes(16 * n))


def _long_footer(monkeypatch):
    real = bu.parse_bclim

    def parse(data):
        pix, w, h, fmt, footer = real(data)
        return pix, w, h, fmt, footer + b"!"

    monkeypatch.setattr(bu, "parse_bclim", parse)


def test_small_helpers():
    assert bu.nlpo2(0) == 1
    with pytest.raises(ValueError, match="not a BCLIM"):
        bu.parse_bclim(b"nothing here")
    assert bu.canvas_for_pixel_bytes(32, 3, 3, 1) == (8, 4)  # from the fallback list
    with pytest.raises(ValueError, match="missing imag"):
        bu.parse_bclim(b"imag" + bytes(20) + b"CLIM" + bytes(20))
    with pytest.raises(ValueError, match="not divisible"):
        bu.canvas_for_pixel_bytes(3, 1, 1, 2)
    assert bu.canvas_for_pixel_bytes(256 * 128, 240, 104, 1) == (256, 128)
    with pytest.raises(ValueError, match="cannot map"):
        bu.canvas_for_pixel_bytes(3, 1, 1, 1)
    with pytest.raises(ValueError, match="footer missing imag"):
        bu._rewrite_footer(b"CLIM" + bytes(16), 1, 1, 1, 1)


def test_tiny_canvases_pad_out_of_range_texels():
    im = Image.new("RGBA", (4, 4), (255, 255, 255, 255))
    assert len(bu.encode_a8_pixels(im, 4, 4)) == 16  # narrower than one 8-px tile
    # 8×2: Morton order walks rows 2..3 of the first tile, past the canvas.
    assert bu.encode_a8_pixels(im, 8, 2)[8:] == bytes(8)
    assert len(bu.encode_a4_pixels(im, 8, 2)) == 32  # whole 8×8 tiles
    assert bu.encode_a8_pixels(im, 0, 8) == b""
    clear = Image.new("RGBA", (8, 8), (90, 90, 90, 0))
    assert set(bu.encode_rgb8_pixels(clear, 8, 8)) == {0}


def test_etc1a4_codec_guards(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="not a multiple of 4"):
        bu.decode_etc1a4_pixels(b"", 6, 4)
    with pytest.raises(ValueError, match="buffer 0 < 16"):
        bu.decode_etc1a4_pixels(b"", 4, 4)
    out = bu.encode_etc1a4_pixels(Image.new("RGBA", (4, 4), (1, 2, 3, 255)), 8, 8)
    assert len(out) == 4 * 16
    monkeypatch.setattr(bu.etcpak, "compress_to_etc1", lambda data, w, h: b"")
    with pytest.raises(ValueError, match="ETC1 compress size"):
        bu.encode_etc1a4_pixels(Image.new("RGBA", (8, 8)), 8, 8)


def test_a4_same_size_guards(tmp_path, monkeypatch):
    png = _png(tmp_path)
    with pytest.raises(ValueError, match="expected A4"):
        bu.png_to_bclim_a4_same_size(png, _file(tmp_path, "rgba.bclim", fi.bclim(8, 8, 8)))
    a4 = _file(tmp_path, "a4.bclim", _a4())
    assert len(bu.png_to_bclim_a4_same_size(png, a4)) == len(a4.read_bytes())
    with monkeypatch.context() as m:
        m.setattr(bu, "encode_a4_pixels", lambda im, w, h: b"x")
        with pytest.raises(ValueError, match="A4 size mismatch"):
            bu.png_to_bclim_a4_same_size(png, a4)
    with monkeypatch.context() as m:
        m.setattr(bu, "canvas_for_pixel_bytes", lambda n, w, h, bpp: (8, 16))
        with pytest.raises(ValueError, match="A4 payload mismatch"):
            bu.png_to_bclim_a4_same_size(png, a4)
    _long_footer(monkeypatch)
    with pytest.raises(ValueError, match="BCLIM size changed"):
        bu.png_to_bclim_a4_same_size(png, a4)


@pytest.mark.parametrize(
    "fn, fmt, encoder",
    [
        (bu.png_to_bclim_a8_same_size, 1, "encode_a8_pixels"),
        (bu.png_to_bclim_rgba4444_same_size, 8, "encode_rgba4444_pixels"),
        (bu.png_to_bclim_rgb565_same_size, 5, "encode_rgb565_pixels"),
    ],
)
def test_same_size_encoders_guard_lengths(tmp_path, monkeypatch, fn, fmt, encoder):
    png = _png(tmp_path)
    orig = _file(tmp_path, f"f{fmt}.bclim", fi.bclim(8, 8, fmt))
    assert len(fn(png, orig)) == len(orig.read_bytes())
    with monkeypatch.context() as m:
        m.setattr(bu, encoder, lambda im, w, h: b"x")
        with pytest.raises(ValueError, match="size mismatch"):
            fn(png, orig)
    _long_footer(monkeypatch)
    with pytest.raises(ValueError, match="BCLIM size changed"):
        fn(png, orig)


def test_tiled_same_size_rejects_other_format(tmp_path):
    with pytest.raises(ValueError, match="expected fmt"):
        bu.png_to_bclim_rgb565_same_size(_png(tmp_path), _file(tmp_path, "a8.bclim", fi.bclim(8, 8, 1)))


def test_etc1a4_same_size_paths(tmp_path, monkeypatch):
    png = _png(tmp_path, (16, 16))
    with pytest.raises(ValueError, match="expected ETC1A4"):
        bu.png_to_bclim_etc1a4(png, _file(tmp_path, "a8.bclim", fi.bclim(8, 8, 1)), size=(8, 8))
    with pytest.raises(ValueError, match="expected ETC1A4"):
        bu.png_to_bclim_etc1a4_same_size(png, _file(tmp_path, "a8b.bclim", fi.bclim(8, 8, 1)))

    # 6 blocks for an 8×8 header: the canvas lookup says 2×3 texels, so the
    # width-major unpack (2 blocks wide) gives an 8×12 canvas.
    six = _file(tmp_path, "six.bclim", _etc(8, 8, blocks=6))
    monkeypatch.setattr(bu, "canvas_for_pixel_bytes", lambda n, w, h, bpp: (2, 3))
    assert len(bu.png_to_bclim_etc1a4_same_size(png, six)) == len(six.read_bytes())
    wide = _file(tmp_path, "wide.bclim", _etc(16, 8, blocks=6))
    with pytest.raises(ValueError, match="cannot derive ETC1A4 pot"):
        bu.png_to_bclim_etc1a4_same_size(png, wide)
    # The canvas lookup itself can name a matching block grid.
    monkeypatch.setattr(bu, "canvas_for_pixel_bytes", lambda n, w, h, bpp: (8, 12))
    assert len(bu.png_to_bclim_etc1a4_same_size(png, six)) == len(six.read_bytes())
    monkeypatch.undo()

    plain = _file(tmp_path, "plain.bclim", _etc())
    with monkeypatch.context() as m:
        m.setattr(bu, "encode_etc1a4_pixels", lambda im, w, h, keep=None: b"x")
        with pytest.raises(ValueError, match="ETC1A4 size mismatch"):
            bu.png_to_bclim_etc1a4_same_size(png, plain)
    _long_footer(monkeypatch)
    with pytest.raises(ValueError, match="BCLIM size changed"):
        bu.png_to_bclim_etc1a4_same_size(png, plain)


def test_decode_bclim_to_image_formats():
    a8 = bu.decode_bclim_to_image(fi.bclim(8, 8, 1, pixels=bytes([200]) * 64))
    assert a8.getpixel((0, 0)) == (255, 255, 255, 200)
    l8 = bu.decode_bclim_to_image(fi.bclim(8, 8, 0, pixels=bytes([0, 9]) * 32))
    assert {l8.getpixel((0, 0))[3], l8.getpixel((1, 0))[3]} == {0, 255}
    rgb565 = bu.decode_bclim_to_image(fi.bclim(8, 8, 5, pixels=b"\xff\xff" * 64))
    assert rgb565.getpixel((0, 0)) == (255, 255, 255, 255)
    la4 = bu.decode_bclim_to_image(fi.bclim(8, 8, 2, pixels=bytes([0xF3]) * 64))
    assert la4.getpixel((0, 0)) == (255, 255, 255, 51)
    rgba8 = bu.decode_bclim_to_image(fi.bclim(8, 8, 9, pixels=bytes([4, 3, 2, 1]) * 64))
    assert rgba8.getpixel((0, 0)) == (1, 2, 3, 4)
    assert bu.decode_bclim_to_image(_a4()) is None
    assert bu.decode_bclim_to_image(fi.bclim(8, 8, 7, pixels=bytes(16))) is None
    assert bu.decode_bclim_to_image(_etc()).size == (8, 8)
    # ETC1A4 6×8 stored on an 8×8 canvas is cropped back.
    etc = bu.decode_bclim_to_image(fi.bclim(6, 8, 0xB, pixels=bytes(64)))
    assert etc.size == (6, 8)
    # A payload that maps to no canvas gives None.
    assert bu.decode_bclim_to_image(fi.bclim(8, 8, 0xB, pixels=bytes(3))) is None


def test_png_to_bclim_same_size_dispatch(tmp_path):
    png = _png(tmp_path)
    for fmt in (1, 8, 0):
        orig = _file(tmp_path, f"f{fmt}.bclim", fi.bclim(8, 8, fmt))
        assert len(bu.png_to_bclim_same_size(png, orig)) == len(orig.read_bytes())
    a4 = _file(tmp_path, "a4.bclim", _a4())
    assert len(bu.png_to_bclim_same_size(png, a4)) == len(a4.read_bytes())
    with pytest.raises(ValueError, match="expected RGBA4444"):
        bu.png_to_bclim_rgba4444_same_size(png, _file(tmp_path, "x.bclim", fi.bclim(8, 8, 1)))
    odd = _file(tmp_path, "f7.bclim", fi.bclim(8, 8, 7, pixels=bytes(16)))
    with pytest.raises(ValueError, match="unsupported BCLIM format 0x7"):
        bu.png_to_bclim_same_size(png, odd)
