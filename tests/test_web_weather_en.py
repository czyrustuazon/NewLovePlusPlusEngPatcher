"""Web weather title and weekly day panes."""

from __future__ import annotations

import struct

from conftest import TOOLS, load_module

weather = load_module("deploy_web_weather_en", TOOLS / "deploy_web_weather_en.py")


def _clyt_with_day(width: float, ty: float) -> bytes:
    sec = bytearray(128)
    sec[0:4] = b"pic1"
    struct.pack_into("<I", sec, 4, 128)
    sec[12:22] = b"Txt_Day_00"
    struct.pack_into("<f", sec, 8 + 32, ty)
    struct.pack_into("<f", sec, 8 + 60, width)
    struct.pack_into("<f", sec, 8 + 64, 14.0)
    header = struct.pack("<4sHHIII", b"CLYT", 0xFEFF, 20, 0, 0, 1)
    header += b"\x00" * (20 - len(header))
    blob = header + bytes(sec)
    return blob[:0x0C] + struct.pack("<I", len(blob)) + blob[0x10:]


def test_day_pane_widens_once():
    raw = _clyt_with_day(14.0, -36.0)
    patched, n = weather.patch_weather_layout(raw)
    assert n == 1
    assert len(patched) == len(raw)
    assert struct.unpack_from("<f", patched, 20 + 8 + 60)[0] == weather.DAY_W
    assert struct.unpack_from("<f", patched, 20 + 8 + 32)[0] == -36.0 + weather.DAY_DY
    again, n2 = weather.patch_weather_layout(patched)
    assert n2 == 0
    assert again == patched


def test_weekly_title_stops_before_the_date():
    from PIL import Image

    src = weather.ROOT / weather.PNG_REL
    im = weather.paint_weekly_title(src)
    assert isinstance(im, Image.Image)
    # Date DrawText starts about 115px into the 248px panel.
    pix = im.load()
    whites = [
        x
        for y in range(76, 89)
        for x in range(100, 144)
        if pix[x, y][0] > 250 and pix[x, y][1] > 250 and pix[x, y][2] > 250
    ]
    assert not whites
