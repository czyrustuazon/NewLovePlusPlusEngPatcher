"""DrawTextToPane packs glyph count + width per line so 64 lines fit."""

from __future__ import annotations

import struct

import pytest

from conftest import SRC, load_module

dt = load_module("patch_drawtext_64_lines", SRC / "patch_drawtext_64_lines.py")
info = load_module("patch_title_engpatch_info", SRC / "patch_title_engpatch_info.py")


def _image(words) -> bytearray:
    data = bytearray(0x0054BD80)
    for addr, word in words:
        struct.pack_into("<I", data, addr, word)
    return data


def test_apply_rewrites_every_word_once():
    data = _image((a, old) for a, old, _new in dt._WORDS)
    assert not dt.is_patched(data)
    assert dt.apply_patch(data) is True
    assert dt.is_patched(data)
    assert dt.apply_patch(data) is False


def test_apply_refuses_unexpected_code():
    data = _image((a, old) for a, old, _new in dt._WORDS)
    struct.pack_into("<I", data, dt._WORDS[0][0], 0)
    with pytest.raises(ValueError, match="DrawTextToPane"):
        dt.apply_patch(data)


def test_width_low_half_count_high_half():
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    asm = {
        a: " ".join(next(md.disasm(struct.pack("<I", new), a)).op_str.split())
        for a, _old, new in dt._WORDS
    }
    assert asm[0x0054B984] == "r5, [r0, #2]"  # count -> high half
    assert asm[0x0054BA98] == "r3, [r0]" and asm[0x0054BAA0] == "r1, [r0]"  # width -> low half
    assert asm[0x0054BB4C] == "r5, [sp, #0x36]" and asm[0x0054BB58] == "r7, [sp, #0x34]"
    assert asm[0x0054BD78] == "ip, [r3, #2]" and asm[0x0054BD7C] == "r3, [r3]"


def test_credits_box_fits_the_table():
    assert all(len(page.split("\n")) <= dt.MAX_LINES for page in info.CREDIT_PAGES)
