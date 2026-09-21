"""Embed SpotPass NsData and spoof BOSS NewFlag/ReadNsData."""

from __future__ import annotations

from conftest import SRC, load_module

sp = load_module("patch_spotpass_embed", SRC / "patch_spotpass_embed.py")


def _vanilla_blob() -> bytearray:
    data = bytearray(sp.ADDR_SPOTPASS_PAYLOAD + 0x920)
    data[sp.ADDR_NEWFLAG : sp.ADDR_NEWFLAG + sp.NEWFLAG_LEN] = sp.VANILLA_FUN
    data[sp.ADDR_CONFIRM : sp.ADDR_CONFIRM + 4] = sp.VANILLA_CONFIRM
    data[sp.ADDR_READ_BL1 : sp.ADDR_READ_BL1 + 4] = sp.VANILLA_READ_BL1
    data[sp.ADDR_READ_BL2 : sp.ADDR_READ_BL2 + 4] = sp.VANILLA_READ_BL2
    return data


def test_caves_fit_in_replaced_function():
    stub = sp.build_function_blob()
    assert len(stub) == sp.NEWFLAG_LEN
    newflag = sp.build_newflag_cave()
    memcpy = sp.build_memcpy_cave(sp.memcpy_addr())
    assert len(newflag) == 0x44
    assert len(memcpy) == 0x2C
    assert sp.memcpy_addr() == sp.ADDR_NEWFLAG + 0x44


def test_newflag_calls_save_ready_and_applied_header():
    data = _vanilla_blob()
    cave = sp.build_newflag_cave()
    data[sp.ADDR_NEWFLAG : sp.ADDR_NEWFLAG + len(cave)] = cave
    assert sp._bl_target(data, sp.ADDR_NEWFLAG + 0x08) == sp.FUN_SAVE_READY
    assert sp._bl_target(data, sp.ADDR_NEWFLAG + 0x1C) == sp.FUN_APPLIED_HDR


def test_memcpy_literals_are_payload_va_and_size():
    addr = sp.memcpy_addr()
    cave = sp.build_memcpy_cave(addr)
    assert cave[-8:-4] == sp._u32(sp.PAYLOAD_VA)
    assert cave[-4:] == sp._u32(0x914)


def test_embed_applies_idempotent_and_reverts():
    data = _vanilla_blob()
    assert sp.is_vanilla(data)
    assert not sp.is_patched(data)
    assert sp.apply_patch(data) is True
    assert sp.is_patched(data)
    assert data[sp.ADDR_CONFIRM : sp.ADDR_CONFIRM + 4] == sp.PATCHED_CONFIRM
    memcpy = sp.memcpy_addr()
    assert sp._bl_target(data, sp.ADDR_READ_BL1) == memcpy
    assert sp._bl_target(data, sp.ADDR_READ_BL2) == memcpy
    payload = sp.load_payload()
    assert data[sp.ADDR_SPOTPASS_PAYLOAD : sp.ADDR_SPOTPASS_PAYLOAD + 0x914] == payload
    assert sp.apply_patch(data) is False
    assert sp.revert_patch(data) is True
    assert sp.is_vanilla(data)
    assert sp.revert_patch(data) is False


def test_embed_rejects_unknown_function():
    data = _vanilla_blob()
    data[sp.ADDR_NEWFLAG] = 0x99
    try:
        sp.apply_patch(data)
    except ValueError as exc:
        assert "unexpected GetNsDataNewFlag" in str(exc)
    else:
        raise AssertionError("expected ValueError")
