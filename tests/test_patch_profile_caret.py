"""Profile form caret follows centered text measured in 7 px cells."""

from __future__ import annotations

import struct

import pytest
from capstone import CS_ARCH_ARM, CS_MODE_ARM, Cs

from conftest import SRC, load_module

caret = load_module("patch_profile_caret", SRC / "patch_profile_caret.py")


def _image() -> bytearray:
    end = max(a + len(o) // 2 for a, o, _ in caret.sites())
    data = bytearray(end + 0x10)
    for addr, old, _ in caret.sites():
        data[addr : addr + len(old) // 2] = bytes.fromhex(old)
    return data


def _disasm(data: bytes, lo: int, hi: int) -> list[str]:
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    return [f"{i.mnemonic} {i.op_str}" for i in md.disasm(bytes(data[lo:hi]), lo)]


def test_sites_keep_their_length():
    for addr, old, new in caret.sites():
        assert len(old) == len(new), hex(addr)


def test_setter_measures_cells_into_the_count_slot():
    data = _image()
    caret.apply_patch(data)
    ins = _disasm(data, 0x2484D0, 0x2484E4)
    assert ins == [
        "ldr r0, [sp, #0xc]",
        "add r1, r4, #0x4c",
        f"bl #{caret.ADDR_MEASURE_TEXT:#x}",
        "mov r1, r5",
        "mov r0, sb",
    ]


def test_caret_reads_cells_and_steps_half_a_cell():
    data = _image()
    caret.apply_patch(data)
    ins = _disasm(data, 0x247E24, 0x247E54)
    assert "ldr r1, [r1, #0x4c]" in ins
    assert "add r1, r1, #2" in ins
    assert "vmla.f32 s0, s6, s3" in ins
    assert not any(i.startswith("vsub") for i in ins)
    assert struct.unpack_from("<f", data, 0x247E80)[0] == 3.5


def test_refresh_uses_the_same_formula():
    data = _image()
    caret.apply_patch(data)
    assert _disasm(data, 0x2482C0, 0x2482C8) == ["add r0, r0, #2", "nop "]
    ins = _disasm(data, 0x24833C, 0x24834C)
    assert ins == [
        "vmov s4, r0",
        "vcvt.f32.s32 s4, s4",
        "vmla.f32 s0, s4, s17",
        "add r0, sp, #0x38",
    ]
    assert struct.unpack_from("<f", data, 0x248388)[0] == 3.5


@pytest.mark.parametrize(
    ("cells", "text_right"),
    [(3, 10.5), (8, 28.0), (16, 56.0)],  # "AAA", 8 ASCII, 8 kana
)
def test_caret_sits_half_a_caret_past_the_text(cells, text_right):
    # Centered text ends at center + 3.5 * cells; caret center is 7 px later.
    assert 3.5 * (cells + 2) == text_right + 7


def test_kana_matches_vanilla_below_the_clamp():
    for n in (1, 2, 3):  # vanilla: 14 + (n-1)*7 with n fullwidth glyphs
        assert 3.5 * (2 * n + 2) == 14 + (n - 1) * 7


def test_apply_is_idempotent():
    data = _image()
    assert not caret.is_patched(data)
    assert caret.apply_patch(data) is True
    assert caret.is_patched(data)
    assert caret.apply_patch(data) is False


def test_apply_refuses_unexpected_bytes():
    data = _image()
    addr = caret.sites()[1][0]
    data[addr] ^= 0xFF
    with pytest.raises(ValueError, match="unexpected bytes"):
        caret.apply_patch(data)
