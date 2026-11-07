"""Talk lines that pass the width break at the previous space."""

from __future__ import annotations

import struct

import pytest
from capstone import CS_ARCH_ARM, CS_MODE_ARM, Cs

from conftest import SRC, load_module

patch = load_module("patch_dialog_break", SRC / "patch_dialog_break.py")


def _buf() -> bytearray:
    data = bytearray(patch.CAVE + 64)
    struct.pack_into("<I", data, patch.SITE, patch.VANILLA)
    return data


def test_hook_branches_to_a_space_scan_and_is_idempotent():
    data = _buf()
    assert patch.apply_patch(data) is True
    assert patch.is_patched(data)
    assert patch.apply_patch(data) is False
    cave = patch.build_cave()
    assert data[patch.CAVE : patch.CAVE + len(cave)] == cave
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    insns = list(md.disasm(cave, patch.CAVE))
    text = [(i.mnemonic, i.op_str) for i in insns]
    assert ("ldr", "r0, [r4, r6, lsl #2]") in text
    assert ("cmp", "r0, #0x20") in text
    assert ("b", f"#{patch.INSERT:#x}") in text
    assert ("b", f"#{patch.RESUME:#x}") in text
    assert insns[-2].mnemonic == "ldr" and insns[-2].op_str == "r0, [sp, #0x48]"


def test_refuses_a_moved_site_or_a_dirty_cave():
    data = _buf()
    data[patch.SITE] = 0xFF
    with pytest.raises(ValueError, match="dialog break"):
        patch.apply_patch(data)
    data = _buf()
    data[patch.CAVE] = 1
    with pytest.raises(ValueError, match="not empty"):
        patch.apply_patch(data)


def break_at_space(text: str, width: int) -> str:
    """The patched breaker: overflow walks back to the previous ASCII space."""
    out: list[str] = []
    col = 0
    line: list[str] = []
    for ch in text:
        if ch == "\n":
            out.append("".join(line))
            line, col = [], 0
            continue
        col += 1 if ord(ch) < 0x80 else 2
        if col > width and line:
            space = "".join(line).rfind(" ")
            if space > 0:
                out.append("".join(line[:space]))
                rest = "".join(line[space + 1 :]) + ch
                line, col = [], 0
                for nxt in rest:
                    col += 1 if ord(nxt) < 0x80 else 2
                    line.append(nxt)
                continue
        line.append(ch)
    out.append("".join(line))
    return "\n".join(part for part in out if part != "")


def test_a_longer_nickname_breaks_at_the_space_not_the_letter_before_punctuation():
    # "Kobayakawa" (10) sits on the 30-column line. "-chan" pushes it over,
    # which is where vanilla kinsoku cuts "absen / t," and "agai / n...".
    absent = break_at_space(
        "(Kobayakawa-chan's absent, huh... I hope nothing happened to her.)", 30
    )
    again = break_at_space(
        "（Don't tell me that's about Kobayakawa-chan again...）", 30
    )
    assert absent == (
        "(Kobayakawa-chan's absent,\n"
        "huh... I hope nothing\n"
        "happened to her.)"
    )
    assert again == (
        "（Don't tell me that's about\n"
        "Kobayakawa-chan again...）"
    )
    assert "absen\n" not in absent
    assert "agai\n" not in again
