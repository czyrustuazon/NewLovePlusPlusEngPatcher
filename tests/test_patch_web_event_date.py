"""Event-card digits stay in the vanilla MM/DD slots."""

from __future__ import annotations

import struct

from conftest import SRC, load_module

digits = load_module("patch_web_event_date", SRC / "patch_web_event_date.py")


def _image(values: tuple[float, ...]) -> bytearray:
    data = bytearray(digits.ADDR_DIGIT_X + 16)
    struct.pack_into("<4f", data, digits.ADDR_DIGIT_X, *values)
    return data


def test_shifted_digits_return_to_vanilla():
    data = _image(digits.SHIFTED_X)
    assert digits.apply_patch(data) is True
    assert digits.is_patched(data)
    assert struct.unpack_from("<4f", data, digits.ADDR_DIGIT_X) == digits.VANILLA_X
    assert digits.apply_patch(data) is False


def test_vanilla_digits_stay_put():
    data = _image(digits.VANILLA_X)
    assert digits.apply_patch(data) is False


def test_digit_positions_refuse_unexpected_bytes():
    data = _image((1.0, 2.0, 3.0, 4.0))
    try:
        digits.apply_patch(data)
    except ValueError:
        return
    raise AssertionError("apply wrote over unexpected digit positions")
