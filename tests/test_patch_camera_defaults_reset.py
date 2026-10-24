"""Restore Default on the My Camera list asks Yes/No, then unequips all but the Memory Card."""

from __future__ import annotations

import struct

import pytest

from conftest import SRC, load_module

rst = load_module("patch_camera_defaults_reset", SRC / "patch_camera_defaults_reset.py")


def _words(blob: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(blob) // 4}I", blob))


def _branch_target(at: int, word: int) -> int:
    imm = word & 0xFFFFFF
    if imm & 0x800000:
        imm -= 0x1000000
    return at + 8 + imm * 4


def _targets(blob: bytes) -> list[int]:
    out = []
    for i, w in enumerate(_words(blob)):
        if (w >> 28) != 0xF and (w & 0x0E000000) == 0x0A000000:
            out.append(_branch_target(rst.CAVE_START + 4 * i, w))
    return out


def test_cave_fits_the_dead_body():
    region, press, poll = rst.build_region()
    assert len(region) == rst.CAVE_END - rst.CAVE_START
    assert rst.CAVE_START <= press < poll < rst.CAVE_END


def test_press_opens_a_yes_no_dialog_with_the_new_slot():
    blob, press, _poll = rst.build_cave()
    words = _words(blob)
    assert words[0] == 0xE5D6010F  # ldrb r0, [r6, #0x10f]  (slot 3 pressed)
    assert words[2] == 0x05D600DB  # otherwise Back's byte, as before
    assert 0xE3A01000 | rst.DIALOG_LAYOUT in words
    assert 0xE3A02000 | rst.DIALOG_MODE in words
    assert 0xE3A03002 in words  # Yes/No buttons
    assert rst.DIALOG_MGR_PTR in words  # literal
    assert rst.MSG_SLOT == rst.DIALOG_LAYOUT_BASE + rst.DIALOG_MODE == rst.MSG_VANILLA_SLOTS
    targets = _targets(blob)
    assert rst.ADDR_OPEN_DIALOG in targets
    assert rst.LIST_HIDE_SOFTKEYS in targets


def test_poll_waits_and_resets_only_on_yes():
    blob, _press, poll = rst.build_cave()
    words = _words(blob)
    i = (poll - rst.CAVE_START) // 4
    assert words[i] == 0xE5D4005D  # ldrb r0, [r4, #0x5d]
    assert words[i + 2] == 0x05D40052  # idle: the replaced ldrb [r4, #0x52]
    targets = _targets(blob)
    assert rst.ADDR_DIALOG_RESULT in targets
    assert rst.LIST_RETURN_0 in targets
    assert rst.ADDR_SET_CAMERA_EQUIP in targets and rst.ADDR_CALC_CAMERA_STATS in targets
    assert 0xE3550003 in words  # cmp r5, #3: skip the Memory Card
    assert any(w >> 24 == 0x5A for w in words)  # bpl: cat 0 (Parts) is cleared too
    assert 0xE584004C in words  # handle / picker sub-state back to -1


def test_apply_refuses_without_spotpass_stub():
    data = bytearray(rst.CAVE_END + 0x10)
    with pytest.raises(ValueError, match="spotpass"):
        rst.apply_patch(data)


def _fake_trb(sub_counts: list[int]) -> bytes:
    """STRI with two entries; INDX with cat 0x19 subs and a later cat."""
    strb = b"a\x00b\x00"
    stri = struct.pack("<IHH", 0, 1, 1) + struct.pack("<IHH", 2, 1, 1)
    cats = bytearray(0x400)
    body = bytearray()
    cat19 = 0x400
    subs = bytearray()
    rels = []
    head = 4 + 4 * len(sub_counts)
    for c in sub_counts:
        rels.append(head + len(subs))
        subs += struct.pack("<I", c) + struct.pack(f"<{c}H", *([0] * c))
    body += struct.pack("<I", len(sub_counts)) + b"".join(struct.pack("<I", r) for r in rels) + subs
    later = cat19 + len(body)
    body += struct.pack("<II", 1, 8) + struct.pack("<IH", 1, 1)
    struct.pack_into("<I", cats, 0x19 * 4, cat19)
    struct.pack_into("<I", cats, 0x20 * 4, later)
    indx = bytes(cats) + bytes(body)
    out = b""
    for name, chunk in (("STRI", stri), ("STRB", strb), ("INDX", indx)):
        out += name.encode() + struct.pack("<I", len(chunk)) + chunk
    return out


def test_append_confirm_message_adds_slot_501_and_shifts_later_offsets():
    from patch_password_serials import _sub_u16_off
    from patch_textresource import parse_chunks

    src = _fake_trb([3, rst.MSG_VANILLA_SLOTS, 2])
    old = parse_chunks(src)["INDX"]
    out, logs = rst.append_confirm_message(src)
    ch = parse_chunks(out)
    indx = ch["INDX"]
    u16, count = _sub_u16_off(indx, rst.MSG_CAT, rst.MSG_SUB)
    assert count == rst.MSG_VANILLA_SLOTS + 1
    new_idx = struct.unpack_from("<H", indx, u16 + 2 * rst.MSG_SLOT)[0]
    assert new_idx == 2 and "stri=2" in logs[0]
    start, length, flag = struct.unpack_from("<IHH", ch["STRI"], new_idx * 8)
    assert flag == 1
    assert ch["STRB"][start : start + length].decode() == rst.CONFIRM_TEXT
    # sub 2 and the later category still resolve, 4 bytes on.
    assert _sub_u16_off(indx, rst.MSG_CAT, 2)[1] == 2
    assert struct.unpack_from("<I", indx, 0x20 * 4)[0] == struct.unpack_from("<I", old, 0x20 * 4)[0] + 4
    assert len(indx) == len(old) + 4
    again, logs = rst.append_confirm_message(out)
    assert again == out and "already" in logs[0]


def test_append_confirm_message_refuses_unexpected_slot_count():
    with pytest.raises(ValueError, match="expected"):
        rst.append_confirm_message(_fake_trb([3, 400, 2]))
