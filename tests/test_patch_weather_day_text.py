"""Weekly weather day names use the same 64×28 capture as today's Mon."""

from __future__ import annotations

import struct

from conftest import SRC, load_module

day = load_module("patch_weather_day_text", SRC / "patch_weather_day_text.py")


def _image() -> bytearray:
    data = bytearray(0x00200000)
    for off, old, _new in day._SITES:
        struct.pack_into("<I", data, off, old)
    return data


def test_day_capture_matches_today_mon():
    data = _image()
    assert day.apply_patch(data) is True
    assert day.is_patched(data)
    words = {off: struct.unpack_from("<I", data, off)[0] for off, _o, _n in day._SITES}
    assert words[0x001FFDD0] == 0xE3A03040  # mov r3, #0x40
    assert words[0x001FFDD4] == 0xE3A01020  # mov r1, #0x20
    assert words[0x001FFDDC] == 0xE3A0001C  # mov r0, #0x1c
    assert words[0x001FFDE0] == 0xE1CD3CB0  # strh r3, [sp, #0xc0]
    assert day.apply_patch(data) is False


def test_day_capture_refuses_unexpected_bytes():
    data = _image()
    data[0x001FFDD0] ^= 0xA5
    try:
        day.apply_patch(data)
    except ValueError:
        return
    raise AssertionError("apply wrote over an unexpected instruction")
