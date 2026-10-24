"""Camera buttons / filter names (5322-5326) and the Quest master packing."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from conftest import ROOT, TOOLS, load_module

import fake_img as fi
from bclimutil import decode_etc1a4_pixels, encode_etc1a4_pixels, parse_bclim
from darcutil import DarcArchive

camera = load_module("deploy_camera_filters_en", TOOLS / "deploy_camera_filters_en.py")
todo = load_module("deploy_todo_en", TOOLS / "deploy_todo_en.py")
rebuild = load_module("rebuild_bake_img", TOOLS / "rebuild_bake_img.py")


def _plate(w: int = 128, h: int = 16) -> Image.Image:
    im = Image.new("RGBA", (w, h), (0, 0, 0, 153))
    ImageDraw.Draw(im).text((8, 2), "JP", fill=(255, 255, 255, 255))
    return im


def _etc1a4(im: Image.Image) -> bytes:
    return fi.bclim(im.width, im.height, 0xB, encode_etc1a4_pixels(im, im.width, im.height))


def test_text_blocks_keep_untouched_blocks_and_share_one_header():
    raw = _etc1a4(_plate())
    van = camera.decode(raw)
    master = van.copy()
    ImageDraw.Draw(master).text((60, 2), "Yellow", fill=(255, 255, 255, 255))

    out = camera.encode_text_blocks(raw, master, van, 24)

    old, new = parse_bclim(raw)[0], parse_bclim(out)[0]
    assert len(out) == len(raw)
    blocks = [(old[i : i + 16], new[i : i + 16]) for i in range(0, len(old), 16)]
    rewritten = [b for a, b in blocks if a != b]
    assert rewritten and len(rewritten) < len(blocks)
    headers = {int.from_bytes(b[8:16], "little") >> 32 for b in rewritten}
    assert len(headers) == 1
    got = np.asarray(decode_etc1a4_pixels(new, 128, 16), dtype=int)
    want = np.asarray(master, dtype=int)
    assert np.abs(got - want).max() <= 48


def test_text_blocks_alpha_levels_quantize_nibbles():
    im = Image.new("RGBA", (16, 16), (255, 255, 255, 0))
    raw = _etc1a4(im)
    master = im.copy()
    master.putpixel((5, 5), (255, 255, 255, 120))
    out = camera.encode_text_blocks(raw, master, camera.decode(raw), 24, a_levels=4)
    pix = parse_bclim(out)[0]
    alpha = b"".join(pix[i : i + 8] for i in range(0, len(pix), 16))
    nibs = {b >> s & 0xF for b in alpha for s in (0, 4)}
    assert nibs <= {0, 5, 10, 15}


def test_camera_deploy_runs_in_the_bake():
    scripts = rebuild.DEPLOY_SCRIPTS
    assert "deploy_camera_filters_en.py" in scripts
    assert scripts.index("deploy_camera_filters_en.py") < scripts.index("deploy_cesa_en.py")
    assert camera.PKGS == (5322, 5323, 5324, 5325, 5326)


def test_todo_packs_every_quest_master(tmp_path):
    """5253 is rebuilt from vanilla; a master it skips ships Japanese."""
    assert todo.QUEST_MASTERS == ROOT / "assets" / "images" / "Quest.check" / "timg"
    files = {}
    for png in todo.QUEST_MASTERS.glob("*.png"):
        with Image.open(png) as im:
            files[f"timg/{png.stem}.bclim"] = fi.bclim(*im.size, 8)
    darc = DarcArchive(bytearray(fi.darc(files)))
    packed = todo.pack_quest_masters(darc, tmp_path)
    assert packed == {p.stem for p in todo.QUEST_MASTERS.glob("*.png")}
    assert {Path(p).stem for p, _en in todo.QUEST_LABELS} <= packed


def test_dilate_is_scipys_default_cross():
    # scipy.ndimage.binary_dilation's default structure is 4-connected; the
    # NumPy port first used 8 and grew the re-encoded text.
    m = np.zeros((5, 5), dtype=bool)
    m[2, 2] = True
    want = np.zeros((5, 5), dtype=bool)
    want[1:4, 2] = want[2, 1:4] = True
    assert (camera._dilate(m) == want).all()
    edge = np.zeros((3, 3), dtype=bool)
    edge[0, 0] = True
    assert camera._dilate(edge).sum() == 3
