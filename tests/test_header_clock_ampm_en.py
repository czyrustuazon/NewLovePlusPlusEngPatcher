"""Home header clock reads HH:MM AM/PM (ClockInfo pkg 5402)."""

from __future__ import annotations

import re
import struct

import pytest

from conftest import TOOLS, load_module

hdr = load_module("deploy_header_clock_ampm_en", TOOLS / "deploy_header_clock_ampm_en.py")
clock = load_module("deploy_clock_date_order_en", TOOLS / "deploy_clock_date_order_en.py")

WEEKDAY_Y = 12.0  # (Su) anchor, 28px glyph with ink 2..26
DIGIT_HALF_INK = 7 * 0.8  # 16px digit, ink ±7, anchor scale 0.8
AMPM_INK = (2, 23)  # in the 26px AM/PM glyph


def _pane(name: str, y: float) -> bytes:
    sec = bytearray(0x4C)
    sec[0:4] = b"pan1"
    struct.pack_into("<I", sec, 4, len(sec))
    sec[8] = 1
    sec[12 : 12 + len(name)] = name.encode("ascii")
    struct.pack_into("<f", sec, hdr.Y_OFF, y)
    return bytes(sec)


def _clyt(sections: list[bytes]) -> bytes:
    header = struct.pack("<4sHHIII", b"CLYT", 0xFEFF, 20, 0, 0, len(sections))
    blob = header + b"".join(sections)
    return blob[:0x0C] + struct.pack("<I", len(blob)) + blob[0x10:]


def _vanilla() -> bytes:
    return _clyt([_pane(n, v) for n, (v, _t) in hdr.ANCHOR_Y.items()])


def _sx(layout: bytes, name: str) -> float:
    """Screen x: the layout is drawn rotated, higher y is further left."""
    for tag, off, _size in clock._sections(layout):
        if tag in clock.PANE_TAGS and clock._pane_name(layout, off) == name:
            return -struct.unpack_from("<f", layout, off + hdr.Y_OFF)[0]
    raise KeyError(name)


def _ampm_ink(center: float) -> tuple[float, float]:
    left = center - 13
    return left + AMPM_INK[0], left + AMPM_INK[1]


def test_row_reads_hour_colon_minute_then_ampm():
    patched, changed = hdr.patch_layout(_vanilla())
    assert changed == len(hdr.ANCHOR_Y)
    hour = [_sx(patched, f"manl_pos_btn0{i}_0") for i in (6, 7)]
    colon = _sx(patched, "manl_pos_btn10_0")
    minute = [_sx(patched, f"manl_pos_btn0{i}_0") for i in (8, 9)]
    ampm = _sx(patched, "manl_pos_btn05_0")
    assert hour == sorted(hour) and minute == sorted(minute)
    assert max(hour) < colon < min(minute) < max(minute) < ampm
    # Hour ink starts where vanilla AM/PM ink started (center 13), 2px
    # after the weekday ")" ink.
    weekday_ink_end = -WEEKDAY_Y - 14 + 26
    assert min(hour) - DIGIT_HALF_INK == pytest.approx(_ampm_ink(13)[0])
    assert min(hour) - DIGIT_HALF_INK - weekday_ink_end == pytest.approx(2)
    # A small space before AM/PM, and the row ends inside vanilla's span
    # (minute ink ended at 77 + 5.6).
    gap = _ampm_ink(ampm)[0] - (max(minute) + DIGIT_HALF_INK)
    assert 2 <= gap <= 4
    assert _ampm_ink(ampm)[1] <= 77 + DIGIT_HALF_INK


def test_time_keeps_vanilla_spacing():
    patched, _ = hdr.patch_layout(_vanilla())
    names = [f"manl_pos_btn{n}_0" for n in ("06", "07", "10", "08", "09")]
    xs = [_sx(patched, n) for n in names]
    assert [b - a for a, b in zip(xs, xs[1:])] == pytest.approx([13, 10, 10, 12])


def test_patch_is_idempotent():
    patched, _ = hdr.patch_layout(_vanilla())
    assert hdr.patch_layout(patched) == (patched, 0)


def test_unexpected_layout_fails():
    raw = _clyt([_pane(n, 999.0) for n in hdr.ANCHOR_Y])
    with pytest.raises(ValueError, match="expected vanilla"):
        hdr.patch_layout(raw)


def test_bake_runs_header_clock_deploy():
    rebuild = load_module("rebuild_bake_img", TOOLS / "rebuild_bake_img.py")
    assert "deploy_header_clock_ampm_en.py" in rebuild.DEPLOY_SCRIPTS
    # Unique package: no other bake script may splice 5402 after it.
    for name in rebuild.DEPLOY_SCRIPTS:
        if name == "deploy_header_clock_ampm_en.py":
            continue
        text = (TOOLS / name).read_text(encoding="utf-8")
        assert not re.search(r"^\s*PKG\s*=\s*5402\b", text, re.MULTILINE), name


def _clockinfo_layout(img_path) -> bytes:
    from darcutil import DarcArchive
    from img import ARC, FileWindow, Image as ImgBin, Package

    img = ImgBin(str(img_path))
    img.parse(False)
    res = img.entries[hdr.PKG]
    pkg = Package(FileWindow(str(img_path), res.fw.base_offset, res.fw.len()), 0)
    pkg.parse(False)
    arc = next(e for e in pkg.entries if isinstance(e, ARC))
    darc = DarcArchive(bytearray(arc.parsed()))
    return darc.extract_file(darc.find(hdr.LAYOUT))


@pytest.mark.local_data
def test_vanilla_layout_patches():
    from nlpp_paths import find_vanilla_img

    vanilla = find_vanilla_img()
    if vanilla is None:
        pytest.skip("no vanilla img.bin")
    layout = _clockinfo_layout(vanilla)
    patched, changed = hdr.patch_layout(layout)
    assert changed == len(hdr.ANCHOR_Y)
    assert len(patched) == len(layout)


@pytest.mark.local_data
def test_release_bake_has_us_header_clock():
    """Stale-bake guard: deploy-a ships release/bake_img.bin."""
    from nlpp_paths import BAKE_IMG

    if not BAKE_IMG.is_file():
        pytest.skip("no release/bake_img.bin")
    layout = _clockinfo_layout(BAKE_IMG)
    assert hdr.patch_layout(layout) == (layout, 0)
