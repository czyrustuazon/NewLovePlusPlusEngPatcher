"""Skip boot “No SpotPass data found.” when GetNsDataNewFlag is 0."""

from __future__ import annotations

from conftest import SRC, load_module

sp = load_module("patch_spotpass_skip", SRC / "patch_spotpass_skip.py")


def _blob(moveq: bytes) -> bytearray:
    data = bytearray(sp.ADDR_MOVEQ + 16)
    data[sp.ADDR_CMP : sp.ADDR_CMP + 4] = sp.VANILLA_CMP
    data[sp.ADDR_MOVEQ : sp.ADDR_MOVEQ + 4] = moveq
    data[sp.ADDR_MOVEQ + 4 : sp.ADDR_MOVEQ + 8] = sp.VANILLA_STRB
    return data


def test_spotpass_skip_rewrites_error_imm():
    data = _blob(sp.VANILLA_MOVEQ)
    assert sp.is_vanilla(data)
    assert not sp.is_patched(data)
    assert sp.apply_patch(data) is True
    assert data[sp.ADDR_MOVEQ : sp.ADDR_MOVEQ + 4] == sp.PATCHED_MOVEQ
    assert sp.is_patched(data)
    assert sp.apply_patch(data) is False


def test_spotpass_skip_revert_restores_vanilla():
    data = _blob(sp.PATCHED_MOVEQ)
    assert sp.revert_patch(data) is True
    assert sp.is_vanilla(data)
    assert sp.revert_patch(data) is False


def test_spotpass_skip_rejects_unknown_bytes():
    data = _blob(sp.VANILLA_MOVEQ)
    data[sp.ADDR_MOVEQ] = 0x99
    try:
        sp.apply_patch(data)
    except ValueError as exc:
        assert "unexpected SpotPass no-data store" in str(exc)
    else:
        raise AssertionError("expected ValueError")
