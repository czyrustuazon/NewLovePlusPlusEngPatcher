"""Mail template rows lay out at 180 px instead of 128."""

from __future__ import annotations

import struct

import pytest

from conftest import SRC, load_module

patch = load_module("patch_mail_reply_width", SRC / "patch_mail_reply_width.py")


def test_widens_the_vanilla_immediate():
    data = bytearray(patch.ADDR + 4)
    struct.pack_into("<I", data, patch.ADDR, patch.VANILLA)
    assert patch.apply_patch(data) is True
    assert patch.is_patched(data)
    assert patch.apply_patch(data) is False
    assert struct.unpack_from("<I", data, patch.ADDR)[0] == patch.PATCHED


def test_refuses_an_unexpected_instruction():
    data = bytearray(patch.ADDR + 4)
    with pytest.raises(ValueError, match="mail reply width"):
        patch.apply_patch(data)
