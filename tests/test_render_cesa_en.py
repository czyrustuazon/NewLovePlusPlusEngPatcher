"""English CESA renderer — NLPPPATCH Heisei Gothic, vanilla-like layout."""

from __future__ import annotations

import pytest
from PIL import Image

from conftest import TOOLS, load_module

render = load_module("render_cesa_en", TOOLS / "render_cesa_en.py")


@pytest.mark.skipif(
    not render.TITLE_TTC.is_file() or not render.BODY_TTC.is_file(),
    reason="NLPPPATCH reference fonts not present",
)
def test_render_cesa_en_matches_tex_canvas():
    im = render.render_cesa_en()
    assert im.size == (240, 400)
    assert im.mode == "RGB"
    px = im.getpixel((0, 0))
    assert px == (255, 255, 255)
    colors = set(im.getdata())
    assert (255, 0, 0) in colors
    assert (0, 0, 0) in colors
    # Title is pure-red gothic; body includes black ink.
    reds = blacks = 0
    for pixel in im.getdata():
        r, g, b = pixel
        if r > 200 and g < 40 and b < 40:
            reds += 1
        elif r < 40 and g < 40 and b < 40:
            blacks += 1
    assert reds > 500
    assert blacks > 500
    # Antialiased ramps (not 3-color snap — that looked grainy / drop-shadowed).
    assert len(colors) > 8
    import sys
    from pathlib import Path
    import zlib

    src = Path(__file__).resolve().parents[1] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from patch_cesa import encode_cesa_tex

    compressed = len(zlib.compress(encode_cesa_tex(im), 9))
    assert compressed <= 13667, compressed


@pytest.mark.skipif(
    not render.TITLE_TTC.is_file() or not render.BODY_TTC.is_file(),
    reason="NLPPPATCH reference fonts not present",
)
def test_render_cesa_companion_en():
    im = render.render_cesa_companion_en()
    assert im.size == (240, 320)
    assert im.mode == "RGB"
    assert im.getpixel((0, 0)) == (255, 255, 255)
    colors = set(im.getdata())
    assert (255, 0, 0) not in colors
    teals = blacks = 0
    for r, g, b in im.getdata():
        if r < 40 and g < 40 and b < 40:
            blacks += 1
        elif b > g >= r and b > 40:
            teals += 1
    assert blacks > 200
    assert teals > 200
    # 3-step ramp: white / black / teal plus two AA midtones (fits pkg 90).
    assert len(colors) >= 5

    import sys
    import zlib
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from patch_cesa import encode_cesa_companion_tex

    # Compressed extra TEX must fit the 29232 PACK. Idx-table dec_len must
    # grow with the PACK header or boot heap-smashes (test_patch_cesa_idx).
    compressed = len(zlib.compress(encode_cesa_companion_tex(im), 9))
    assert compressed <= 5500, compressed
