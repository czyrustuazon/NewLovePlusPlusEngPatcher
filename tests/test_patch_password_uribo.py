"""ウリボー傘 grant: remap password slots 33–35 off 内部 sentinels."""

from __future__ import annotations

import struct

from conftest import SRC, TOOLS, load_module

uribo = load_module("patch_password_uribo", SRC / "patch_password_uribo.py")


def _blob() -> bytearray:
    data = bytearray(uribo.ADDR_TABLE + uribo.N_SLOTS * 4)
    data[uribo.ADDR_SLOT_THRESH : uribo.ADDR_SLOT_THRESH + 4] = uribo.VANILLA_CMP
    data[uribo.ADDR_SLOT_THRESH + 4 : uribo.ADDR_SLOT_THRESH + 8] = uribo.VANILLA_BGE
    struct.pack_into("<i", data, uribo.ADDR_TABLE, uribo.GLOVE_MANAKA)
    struct.pack_into("<i", data, uribo.ADDR_TABLE + 24 * 4, uribo.SENTINEL_VISA)
    for slot in range(33, 41):
        struct.pack_into("<i", data, uribo.ADDR_TABLE + slot * 4, uribo.SENTINEL_INTERNAL)
    return data


def _item(data: bytearray, slot: int) -> int:
    return struct.unpack_from("<i", data, uribo.ADDR_TABLE + slot * 4)[0]


def test_uribo_patch_rewrites_table_and_threshold():
    data = _blob()
    assert uribo.is_vanilla(data)
    assert not uribo.is_patched(data)
    assert uribo.apply_patch(data) is True
    assert [_item(data, s) for s in uribo.URIBO_SLOTS] == list(uribo.URIBO_ITEMS)
    assert _item(data, 36) == uribo.SENTINEL_INTERNAL
    assert data[uribo.ADDR_SLOT_THRESH : uribo.ADDR_SLOT_THRESH + 4] == uribo.PATCHED_CMP
    assert uribo.is_patched(data)
    assert uribo.apply_patch(data) is False


def test_uribo_revert_restores_vanilla():
    data = _blob()
    uribo.apply_patch(data)
    assert uribo.revert_patch(data) is True
    assert uribo.is_vanilla(data)
    assert [_item(data, s) for s in uribo.URIBO_SLOTS] == [uribo.SENTINEL_INTERNAL] * 3
    assert uribo.revert_patch(data) is False


def test_uribo_rejects_unknown_bytes():
    data = _blob()
    struct.pack_into("<i", data, uribo.ADDR_TABLE + 33 * 4, 123)
    try:
        uribo.apply_patch(data)
    except ValueError as exc:
        assert "unexpected password grant table" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_deploy_name_input_hooks_password_uribo():
    text = (TOOLS / "deploy_name_input_en.py").read_text(encoding="utf-8")
    assert "apply_password_uribo" in text
    assert "password_uribo_already" in text
    assert (SRC / "patch_password_uribo.py").is_file()
