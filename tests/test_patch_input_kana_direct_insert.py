"""Kana-direct insert NOPs the FillCandidates gate and nothing else."""

from __future__ import annotations

import pytest

from conftest import SRC, load_module

kana = load_module(
    "patch_input_kana_direct_insert", SRC / "patch_input_kana_direct_insert.py"
)


def _buf(site_bytes: bytes) -> bytearray:
    data = bytearray(kana.SITE + 0x100)
    data[kana.SITE : kana.SITE + 4] = site_bytes
    return data


def test_apply_nops_gate_only():
    data = _buf(kana.VANILLA)
    before = bytes(data)
    kana.apply_patch(data)
    assert kana.is_patched(data)
    assert data[kana.SITE : kana.SITE + 4] == bytes.fromhex("00f020e3")
    assert data[: kana.SITE] == before[: kana.SITE]
    assert data[kana.SITE + 4 :] == before[kana.SITE + 4 :]


def test_apply_is_idempotent_and_revertible():
    data = _buf(kana.VANILLA)
    kana.apply_patch(data)
    once = bytes(data)
    kana.apply_patch(data)
    assert bytes(data) == once
    kana.revert_patch(data)
    assert data[kana.SITE : kana.SITE + 4] == kana.VANILLA


def test_apply_refuses_unknown_site():
    data = _buf(bytes.fromhex("deadbeef"))
    with pytest.raises(ValueError):
        kana.apply_patch(data)
    assert data[kana.SITE : kana.SITE + 4] == bytes.fromhex("deadbeef")


def test_restore_bind_sites_puts_back_vanilla_bl():
    data = bytearray(kana.SITE_BIND_CAND + 0x10)
    kana.restore_bind_sites(data)
    assert data[kana.SITE_BIND_KBD : kana.SITE_BIND_KBD + 4] == kana.VANILLA_BL_KBD
    assert data[kana.SITE_BIND_CAND : kana.SITE_BIND_CAND + 4] == kana.VANILLA_BL_CAND
