"""B_Place hometown-list text pane width + glyph cap (prefecture picker)."""

from __future__ import annotations

import pytest

import patch_bplace_list_pane as bplace
from conftest import ROOT
from nlpp_paths import find_vanilla_code


def test_wide_block_matches_orig_length():
    assert len(bplace.ORIG_PANE) == len(bplace.WIDE_PANE) == 16
    assert bplace.ORIG_PANE != bplace.WIDE_PANE
    assert bplace.ORIG_PANE[0] == 0x40
    assert bplace.WIDE_PANE[0] == 0x80
    assert bplace.BAD_PANE[0] == 0x60
    assert len(bplace.ORIG_CAP) == len(bplace.WIDE_CAP) == 8
    assert len(bplace.ORIG_DRAW_SP0) == len(bplace.WIDE_DRAW_SP0) == 8
    assert bplace.WIDE_DRAW_SP0[0] == 0x10


def test_deploy_name_input_includes_bplace_pane():
    text = (ROOT / "tools" / "deploy_name_input_en.py").read_text(encoding="utf-8")
    assert "apply_bplace_list_pane" in text


def test_apply_bplace_pane_on_vanilla():
    src = find_vanilla_code()
    if src is None:
        pytest.skip("no vanilla code.bin")
    data = bytearray(src.read_bytes())
    if not bplace.is_vanilla(data):
        pytest.skip("code.bin BPlace pane setup is not vanilla")
    assert bplace.apply_patch(data) is True
    assert bplace.is_wide(data)
    assert bplace.apply_patch(data) is False


def test_upgrades_failed_96px_experiment():
    src = find_vanilla_code()
    if src is None:
        pytest.skip("no vanilla code.bin")
    data = bytearray(src.read_bytes())
    if data[bplace.ADDR_PANE : bplace.ADDR_PANE + 16] != bplace.ORIG_PANE:
        pytest.skip("BPlace pane bytes are not vanilla")
    data[bplace.ADDR_PANE : bplace.ADDR_PANE + 16] = bplace.BAD_PANE
    assert bplace.apply_patch(data) is True
    assert data[bplace.ADDR_PANE : bplace.ADDR_PANE + 16] == bplace.WIDE_PANE
    assert bplace.is_wide(data)
