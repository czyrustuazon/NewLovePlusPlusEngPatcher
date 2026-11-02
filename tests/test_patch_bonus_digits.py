"""BONUS! popup Riches amounts use pack 0x0100's ASCII digit slots."""

from __future__ import annotations

import struct

import pytest

from conftest import SRC, load_module

digits = load_module("patch_bonus_digits", SRC / "patch_bonus_digits.py")


def _image(word: int) -> bytearray:
    data = bytearray(digits.ADDR_DIGIT_SLOT + 0x10)
    struct.pack_into("<I", data, digits.ADDR_DIGIT_SLOT, word)
    return data


def test_vanilla_slot_lookup_becomes_digit_plus_17():
    data = _image(digits.VANILLA)
    assert not digits.is_patched(data)
    assert digits.apply_patch(data) is True
    assert digits.is_patched(data)
    assert digits.apply_patch(data) is False
    # add r1, r0, #imm: the low byte is the slot offset of ASCII "0".
    assert digits.PATCHED & 0xFF == digits.ASCII_DIGIT_SLOT == 17


def test_unexpected_word_is_refused():
    data = _image(0xE1A00000)
    with pytest.raises(ValueError, match="bonus digit slot"):
        digits.apply_patch(data)
