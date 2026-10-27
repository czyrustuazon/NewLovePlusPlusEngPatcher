"""Save-data dates print MM/DD/YYYY."""

from __future__ import annotations

import struct

import pytest

from conftest import SRC, load_module

date = load_module("patch_save_slot_date", SRC / "patch_save_slot_date.py")


def _image() -> bytearray:
    data = bytearray(date.ADDR_FORMAT + date.FORMAT_SLOT)
    for at, old, _new in date._all_words():
        data[at : at + 4] = old
    return data


def test_vanilla_becomes_month_day_year():
    data = _image()
    assert date.apply_patch(data) is True
    assert date.is_patched(data)
    assert date.apply_patch(data) is False


def test_dsel_sites_load_the_pad_format():
    data = _image()
    date.apply_patch(data)
    for name in ("date_0x46a500", "date_0x46ea1c"):
        old_fmt = date.SITES[name][4][0]
        ptr = struct.unpack_from("<I", data, old_fmt)[0]
        at = ptr - date.VA_BASE
        assert bytes(data[at : at + len(date.FORMAT)]) == date.FORMAT, name


def test_month_day_year_order():
    fmt = date.FORMAT.rstrip(b"\x00").decode()
    assert fmt % (10, 19, 2026) == "10/19/2026"
    assert fmt % (9, 5, 2026) == "09/05/2026"
    assert date.LIST_PATCHED_FORMAT.rstrip(b"\x00").decode() == fmt


def test_vanilla_words_match_rom():
    # Captured from vanilla code.bin.
    assert [old.hex() for _at, old, _new in date.SITES["date_0x46ea1c"][:4]] == [
        "0030a0e1",  # mov r3, r0
        "1e2e8fe2",  # add r2, pc, #0x1e0
        "04408de5",  # str r4, [sp, #4]
        "00508de5",  # str r5, [sp]
    ]
    assert [old.hex() for _at, old, _new in date.SITES["date_0x31c0f4"][:3]] == [
        "6c5c10eb",
        "d35c10eb",
        "ba5c10eb",
    ]


def test_refuses_unexpected_bytes():
    data = _image()
    data[date.ADDR_LIST_FORMAT : date.ADDR_LIST_FORMAT + 4] = b"%d.%"
    with pytest.raises(ValueError):
        date.apply_patch(data)
    assert not date.is_patched(data)


def test_refuses_busy_format_pad():
    data = _image()
    data[date.ADDR_FORMAT] = 0x41
    with pytest.raises(ValueError):
        date.apply_patch(data)


def test_last_saved_keeps_separator_format():
    # r3, [sp], [sp+4], [sp+8], [sp+12] = month, "/", day, "/", year.
    words = [new.hex() for _at, _old, new in date.SITES["dsel_last_saved"]]
    assert words == ["0c008de5", "40018de8", "08608de5", "0930a0e1"]
    assert "%d%s%d%s%d" % (7, "/", 23, "/", 2026) == "7/23/2026"


def test_rot_imm_rejects_a_non_immediate():
    assert date._rot_imm(0xFF000000) == 0x4FF
    with pytest.raises(ValueError):
        date._rot_imm(0x101)


def test_format_room_refuses_a_format_past_the_pad(monkeypatch):
    monkeypatch.setattr(date, "FORMAT", b"x" * (date.FORMAT_SLOT + 1))
    with pytest.raises(ValueError):
        date._format_room()
