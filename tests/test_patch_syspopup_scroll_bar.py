"""SysPopup scroll range is textH - winH and the bar spans it exactly."""

from __future__ import annotations

import struct

import pytest

from conftest import SRC, load_module

bar = load_module("patch_syspopup_scroll_bar", SRC / "patch_syspopup_scroll_bar.py")


def _image(pick) -> bytearray:
    data = bytearray(0x001D93BC)
    for addr, old, new in bar._WORDS:
        struct.pack_into("<I", data, addr, pick(old, new))
    return data


def test_apply_once():
    data = _image(lambda old, _new: old)
    assert bar.apply_patch(data) is True and bar.is_patched(data)
    assert bar.apply_patch(data) is False


def test_refuses_unexpected_code():
    data = _image(lambda old, _new: old)
    struct.pack_into("<I", data, bar._WORDS[0][0], 0)
    with pytest.raises(ValueError, match="SysPopup"):
        bar.apply_patch(data)


def test_decodes_as_intended():
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    got = {
        a: " ".join(next(md.disasm(struct.pack("<I", new), a)).op_str.split())
        for a, _old, new in bar._WORDS
    }
    assert got[0x001D93A0] == "s2, s0, s2"  # textH - winH
    assert got[0x001D93B4] == "s2, s2, s17"  # + (-67)
    assert got[0x001D8FDC] == "s5, [r4, #0x14c]"  # textH
    assert got[0x001D8FF4] == "s1, s6, s5"  # (pos + 67) / textH


@pytest.mark.parametrize("lines", [9, 16, 59])
def test_bar_bottom_meets_track_end(lines):
    text_h, win_h, track = 14.0 * lines, 112.0, 101.0
    length = track * win_h / text_h
    t_end = (text_h - win_h) / text_h  # pos at the clamp, + 67, / textH
    assert track * t_end + length == pytest.approx(track)
