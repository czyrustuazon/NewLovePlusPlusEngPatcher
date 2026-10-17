"""Called-list no-voice legend under the Profile name boxes (pkg 5252)."""

from __future__ import annotations

import struct
import sys

import pytest

from conftest import ROOT, SRC, TOOLS, load_module

sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "nlpp-tools"))

legend = load_module("patch_call_legend", SRC / "patch_call_legend.py")
from bclimutil import d2xy, parse_bclim  # noqa: E402

FONT = ROOT / "assets" / "fonts" / "MPLUS1p-Regular.ttf"


def _footer(w: int, h: int, fmt: int, pix_len: int) -> bytes:
    # Same real CLIM/imag footer as tests/test_bclim_extra_fmts.py.
    buf = bytearray(
        bytes.fromhex(
            "434c494dfffe1400000002022808000001000000696d616710000000300010000500000000080000"
        )
    )
    imag = buf.find(b"imag")
    struct.pack_into("<HHI", buf, imag + 8, w, h, fmt)
    struct.pack_into("<I", buf, imag + 16, pix_len)
    struct.pack_into("<I", buf, 0x0C, pix_len + len(buf))
    return bytes(buf)


def _texel(pix: bytes, x: int, y: int, tiles_x: int) -> bytes:
    xy = {d2xy(i): i for i in range(64)}
    i = ((y // 8) * tiles_x + x // 8) * 64 + xy[(x % 8, y % 8)]
    return pix[2 * i : 2 * i + 2]


def _pic1(name: str, ty: float, h: float, origin: int = 0x4) -> bytes:
    sec = bytearray(128)
    sec[0:4] = b"pic1"
    struct.pack_into("<I", sec, 4, 128)
    sec[8], sec[9] = 1, origin
    sec[12 : 12 + len(name)] = name.encode()
    struct.pack_into("<2f", sec, 8 + 28, 0.0, ty)
    struct.pack_into("<2f", sec, 8 + 60, 240.0, h)
    struct.pack_into("<8f", sec, 0x60, 0, 0, 1, 0, 0, 1, 1, 1)
    return bytes(sec)


def _clyt(*sections: bytes) -> bytes:
    body = b"".join(sections)
    head = struct.pack("<4sHHIII", b"CLYT", 0xFEFF, 0x14, 0x02020000, 0x14 + len(body), len(sections))
    return head + body


def test_legend_renders_inside_its_strip():
    im = legend.render_legend(FONT, 240)
    assert im.size == (240, legend.LEGEND_H)
    alpha = im.getchannel("A")
    assert alpha.getbbox() is not None
    lum = [p[0] for p in im.getdata() if p[3] == 255]
    assert min(lum) <= legend.INK + 8  # dark ink (antialiased into the halo)
    assert max(lum) == legend.HALO


def test_paint_la8_rows_writes_only_below_the_visible_image():
    w, h, pot_w, pot_h = 240, 152, 256, 256
    pix = bytes.fromhex("80c8") * (pot_w * pot_h)  # opaque grey everywhere
    raw = pix + _footer(w, h, legend.LA8_FMT, len(pix))
    im = legend.render_legend(FONT, w)
    out = legend.paint_la8_rows(raw, h, im)
    assert len(out) == len(raw) and out[len(pix) :] == raw[len(pix) :]
    new_pix = parse_bclim(out)[0]
    for y in (0, 100, h - 1, h + legend.LEGEND_H, pot_h - 1):
        for x in (0, 120, 239):
            assert _texel(new_pix, x, y, pot_w // 8) == bytes.fromhex("80c8"), (x, y)
    painted = {_texel(new_pix, x, y, pot_w // 8) for y in range(h, h + legend.LEGEND_H) for x in range(w)}
    assert b"\x00\x00" in painted  # transparent around the text
    assert any(a == 255 and lum <= legend.INK + 8 for a, lum in painted)  # opaque ink


def test_paint_la8_rows_rejects_overflow_and_other_formats():
    pix = bytes(256 * 128 * 2)
    with pytest.raises(ValueError, match="does not fit"):
        legend.paint_la8_rows(pix + _footer(240, 120, legend.LA8_FMT, len(pix)), 120, legend.render_legend(FONT, 240))
    with pytest.raises(ValueError, match="LA8"):
        legend.paint_la8_rows(pix + _footer(240, 104, 5, len(pix)), 104, legend.render_legend(FONT, 240))


def test_extend_pic_pane_keeps_the_top_edge():
    lyt = _clyt(_pic1("Pic_Other", 7.0, 50.0), _pic1("Pic_Call01", -4.0, 152.0))
    out = legend.extend_pic_pane(lyt, "Pic_Call01", 152)
    assert len(out) == len(lyt)
    sec = out[0x14 + 128 :]
    ty, h = struct.unpack_from("<f", sec, 8 + 32)[0], struct.unpack_from("<f", sec, 8 + 64)[0]
    assert h == 152 + legend.LEGEND_H
    assert ty + h / 2 == -4.0 + 152 / 2  # top edge unchanged
    uv = struct.unpack_from("<8f", sec, 0x60)
    assert uv[:4] == (0, 0, 1, 0)
    assert uv[5] == uv[7] == pytest.approx((152 + legend.LEGEND_H) / 152)
    assert out[0x14 : 0x14 + 128] == lyt[0x14 : 0x14 + 128]  # other pane untouched


def test_extend_pic_pane_refuses_non_vanilla_panes():
    with pytest.raises(ValueError, match="not found"):
        legend.extend_pic_pane(_clyt(_pic1("Pic_Other", 0.0, 152.0)), "Pic_Call01", 152)
    with pytest.raises(ValueError, match="origin"):
        legend.extend_pic_pane(_clyt(_pic1("Pic_Call01", 0.0, 152.0, origin=0)), "Pic_Call01", 152)
    with pytest.raises(ValueError, match="expected vanilla"):
        legend.extend_pic_pane(_clyt(_pic1("Pic_Call01", 0.0, 168.0)), "Pic_Call01", 152)


def test_profile_deploy_adds_the_legend():
    text = (TOOLS / "deploy_profile_en.py").read_text(encoding="utf-8")
    assert "add_call_legend(darc, UI_FONT)" in text


def _profile_arc(img_path):
    from darcutil import DarcArchive
    from img import ARC, FileWindow, Image as ImgBin, Package

    img = ImgBin(str(img_path))
    img.parse(False)
    res = img.entries[5252]
    pkg = Package(FileWindow(str(img_path), res.fw.base_offset, res.fw.len()), 0)
    pkg.parse(False)
    arc = next(e for e in pkg.entries if isinstance(e, ARC) and e.fn == "Profile.arc")
    return DarcArchive(bytearray(arc.parsed()))


@pytest.mark.local_data
def test_legend_on_vanilla_profile_arc_keeps_its_size():
    from nlpp_paths import find_vanilla_img

    vanilla = find_vanilla_img()
    if vanilla is None:
        pytest.skip("no vanilla img.bin")
    darc = _profile_arc(vanilla)
    size = len(darc.data)
    assert len(legend.add_call_legend(darc, FONT)) == 3
    assert len(darc.data) == size


@pytest.mark.local_data
def test_release_bake_has_the_legend():
    """Stale-bake guard, like test_input_panes_hidden: deploy-a ships release/."""
    from nlpp_paths import BAKE_IMG

    if not BAKE_IMG.is_file():
        pytest.skip("no release/bake_img.bin")
    darc = _profile_arc(BAKE_IMG)
    for _tex, (visible_h, panes) in legend.TARGETS.items():
        for lyt, pane in panes:
            with pytest.raises(ValueError, match="expected vanilla"):
                legend.extend_pic_pane(darc.extract_file(darc.find(lyt)), pane, visible_h)
