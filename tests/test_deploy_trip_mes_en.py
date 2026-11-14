"""Trip date-picker message box: raw ETC1A4 TEX in pkg 5792."""

from __future__ import annotations

import zlib

import numpy as np
import pytest
from PIL import Image

from conftest import TOOLS, load_module

from bclimutil import decode_etc1a4_pixels

trip = load_module("deploy_trip_mes_en", TOOLS / "deploy_trip_mes_en.py")
rebuild = load_module("rebuild_bake_img", TOOLS / "rebuild_bake_img.py")


def test_master_matches_vanilla_texture_size():
    assert Image.open(trip.MASTER).size == trip.SIZE == (256, 128)


def test_master_keeps_the_box_outside_the_text():
    """Only the box interior is redrawn; the transparent margin stays empty."""
    px = np.array(Image.open(trip.MASTER).convert("RGBA"))
    assert (px[:, 170:, 3] == 0).all()
    assert (px[124:, :, 3] == 0).all()
    assert (px[20:110, 20:150, 3] == 255).all()


def test_bake_runs_trip_before_cesa():
    scripts = rebuild.DEPLOY_SCRIPTS
    assert "deploy_trip_mes_en.py" in scripts
    assert scripts.index("deploy_trip_mes_en.py") < scripts.index("deploy_cesa_en.py")


@pytest.mark.local_data
def test_vanilla_package_takes_master_at_same_size():
    from img import Image as ImgBin
    from nlpp_paths import find_vanilla_img

    vanilla = find_vanilla_img()
    if vanilla is None:
        pytest.skip("no vanilla img.bin")
    raw = vanilla.read_bytes()
    img = ImgBin(str(vanilla))
    img.parse(False)
    res = img.entries[trip.PKG]
    pkg_raw = raw[res.fw.base_offset : res.fw.base_offset + res.fw.len()]
    new = trip.patch_package(pkg_raw)
    assert len(new) == len(pkg_raw)
    off, ent = trip._tex_entry(new)
    assert trip._tex_entry(pkg_raw) == (off, ent)
    cmp_len, cmp_off = ent[5], ent[6]
    assert new[:cmp_off] == pkg_raw[:cmp_off]
    assert new[cmp_off + cmp_len :] == pkg_raw[cmp_off + cmp_len :]
    got = np.array(decode_etc1a4_pixels(zlib.decompress(new[cmp_off : cmp_off + cmp_len]), 256, 128))
    want = np.array(Image.open(trip.MASTER).convert("RGBA"))
    assert np.abs(got[..., 3].astype(int) - want[..., 3]).max() <= 17
