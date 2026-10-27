"""Friends-list sort label and Delete Save Data buttons ship Zhoumaru LA8.

These slots are fmt 3 (LA8). Read as RGB565, the transparent background
looks yellow/green and grey ink looks cyan, which led to 1-bit "cyan on a
chroma key" renders that showed up in game as jagged, over-dark text.
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from bclimutil import _decode_tiled, nlpo2, parse_bclim, png_to_bclim_same_size

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

# (deploy script, master, slot size)
LABELS = [
    (
        "deploy_card_flist_en.py",
        ROOT / "assets/images/Card.check/timg/Flist_Txt03.png",
        (96, 16),
    ),
    (
        "deploy_datadelete_en.py",
        ROOT / "assets/images/DataDelete.check/DataDelete/timg/DD_Data_Txt_Big01.png",
        (112, 16),
    ),
    (
        "deploy_datadelete_en.py",
        ROOT / "assets/images/DataDelete.check/DataDelete/timg/DD_Data_Txt_Big02.png",
        (152, 16),
    ),
]


def _fmt3_bclim(tmp: Path, w: int, h: int) -> Path:
    pix_len = nlpo2(w) * nlpo2(h) * 2
    footer = bytearray(
        bytes.fromhex(
            "434c494dfffe1400000002022808000001000000696d616710000000300010000500000000080000"
        )
    )
    imag = footer.find(b"imag")
    struct.pack_into("<HHI", footer, imag + 8, w, h, 3)
    struct.pack_into("<I", footer, imag + 16, pix_len)
    struct.pack_into("<I", footer, 0x0C, pix_len + len(footer))
    dest = tmp / f"fmt3_{w}x{h}.bclim"
    dest.write_bytes(bytes(pix_len) + bytes(footer))
    return dest


@pytest.mark.parametrize("script,master,size", LABELS, ids=lambda v: getattr(v, "stem", v))
def test_master_is_antialiased(script: str, master: Path, size: tuple[int, int]):
    im = Image.open(master).convert("RGBA")
    assert im.size == size
    alpha = np.array(im)[..., 3]
    # A 1-bit render has two levels; the Zhoumaru masters have a soft halo.
    assert len(np.unique(alpha)) > 4


@pytest.mark.parametrize("script,master,size", LABELS, ids=lambda v: getattr(v, "stem", v))
def test_master_round_trips_as_la8(
    tmp_path: Path, script: str, master: Path, size: tuple[int, int]
):
    w, h = size
    out = png_to_bclim_same_size(master, _fmt3_bclim(tmp_path, w, h))
    pix, ow, oh, fmt, _ = parse_bclim(out)
    assert (ow, oh, fmt) == (w, h, 3)
    got = np.array(
        _decode_tiled(pix, w, h, 2, lambda p, i: (p[2 * i + 1],) * 3 + (p[2 * i],))
    ).astype(int)
    want = np.array(Image.open(master).convert("RGBA")).astype(int)
    assert np.array_equal(got[..., 3], want[..., 3])
    vis = want[..., 3] > 0
    assert np.array_equal(got[..., 0][vis], want[..., 0][vis])


@pytest.mark.parametrize("script", sorted({s for s, _m, _z in LABELS}))
def test_script_writes_la8_not_rgb565(script: str):
    text = (TOOLS / script).read_text(encoding="utf-8")
    assert "png_to_bclim_la8_same_size" in text
    assert "png_to_bclim_rgb565_same_size" not in text
    for old in ("render_flist_label", "render_button_label", "_hard_cyan"):
        assert old not in text


def test_datadelete_uses_zhoumaru_button_masters():
    text = (TOOLS / "deploy_datadelete_en.py").read_text(encoding="utf-8")
    assert '"DD_Data_Txt_Big01", "DD_Data_Txt_Big02"' in text


def test_flist_uses_zhoumaru_master():
    text = (TOOLS / "deploy_card_flist_en.py").read_text(encoding="utf-8")
    assert '"Card.check"' in text
    assert '"Flist_Txt03.png"' in text
