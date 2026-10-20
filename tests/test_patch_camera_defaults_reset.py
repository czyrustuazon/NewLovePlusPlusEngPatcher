"""Restore Default on the My Camera list unequips all but the Memory Card (cat 3)."""

from __future__ import annotations

import struct

from conftest import SRC, load_module

rst = load_module("patch_camera_defaults_reset", SRC / "patch_camera_defaults_reset.py")


def _words(blob: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(blob) // 4}I", blob))


def test_region_fits_and_skips_the_cave():
    region, reset_at = rst.build_region()
    assert len(region) == rst.REGION_END - rst.REGION_START
    skip = reset_at - 4
    assert region[skip - rst.REGION_START : reset_at - rst.REGION_START] == rst.b(skip, rst.REGION_END)


def test_rows_point_at_the_same_names_and_empty_string():
    rows = rst.build_rows()
    words = _words(rows)
    # every "add r1, pc, #imm" lands on the empty string.
    for i, w in enumerate(words):
        if w & 0xFFFFF000 == 0xE28F1000:
            imm = w & 0xFF
            rot = (w >> 8) & 0xF
            val = ((imm >> (2 * rot)) | (imm << (32 - 2 * rot))) & 0xFFFFFFFF
            assert rst.REGION_START + 4 * i + 8 + val == rst.EMPTY_STRING
    for field, name_off, fn in rst.ROWS:
        assert 0xE5940000 | field in words
        assert sum(rst._split_imm(name_off)) == name_off


def test_reset_keeps_memory_card_and_returns_back_flag():
    _region, reset_at = rst.build_region()
    cave = rst.build_reset(reset_at)
    words = _words(cave)
    assert words[0] == 0xE5D6010F  # ldrb r0, [r6, #0x10f]  (slot 3 pressed)
    assert words[2] == 0x05D600DB and words[-2] == 0xE5D600DB  # Back's byte both ways
    assert 0xE3A05004 in words  # mov r5, #4: cat 4..0
    assert 0xE3550003 in words  # cmp r5, #3: skip the Memory Card (cat 3, row 0)
    assert 0xE2555001 in words
    assert any(w >> 24 == 0x5A for w in words)  # bpl: cat 0 (Parts) is cleared too


def test_apply_is_idempotent_on_vanilla_shaped_bytes():
    import hashlib

    data = bytearray(rst.REGION_END + 0x100)
    # fake "vanilla" region: patch the expected hash check by building from real bytes is
    # not possible without the ROM, so only check refusal on non-vanilla bytes here.
    data[rst.HOOK : rst.HOOK + 4] = rst.HOOK_VANILLA
    try:
        rst.apply_patch(data)
    except ValueError as exc:
        assert "not vanilla" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("patched a non-vanilla region")
    assert hashlib.sha256(bytes(data[rst.REGION_START : rst.REGION_END])).hexdigest() != rst.REGION_VANILLA_SHA256
