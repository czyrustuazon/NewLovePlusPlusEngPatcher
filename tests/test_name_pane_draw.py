"""Single-pane name draw + 128x16 glyph panes (profile name-input)."""

from __future__ import annotations

import pytest

import patch_code
from conftest import ROOT
from nlpp_paths import find_vanilla_code


def test_pane_size_blocks_are_same_length():
    assert len(patch_code.ORIG_PANE_SIZE) == patch_code.PANE_SIZE_LEN
    assert len(patch_code.WIDE_PANE_SIZE) == patch_code.PANE_SIZE_LEN
    assert patch_code.ORIG_PANE_SIZE != patch_code.WIDE_PANE_SIZE


def test_set_name_fits_and_draws_full_string():
    blob = patch_code.assemble_set_name()
    assert len(blob) == patch_code.SIZE_SET
    # mov r10, #0 = unlimited DrawText glyphs for the joined name.
    assert bytes.fromhex("00a0a0e3") in blob


def test_clear_and_backspace_sizes():
    assert len(patch_code.assemble_clear()) == patch_code.SIZE_CLEAR
    assert len(patch_code.assemble_backspace()) == patch_code.SIZE_BACKSPACE


def test_deploy_name_input_includes_name_panes():
    text = (ROOT / "tools" / "deploy_name_input_en.py").read_text(encoding="utf-8")
    assert "apply_name_pane_patches" in text
    assert "apply_ascii_dakuten" in text
    assert "apply_strcat_raw" in text
    assert "apply_message_speed" in text
    assert "message_speed_already" in text


def test_apply_name_pane_patches_on_vanilla():
    src = find_vanilla_code()
    if src is None:
        pytest.skip("no vanilla code.bin")
    data = bytearray(src.read_bytes())
    if not patch_code.is_vanilla_code(data):
        pytest.skip("code.bin is not vanilla name-pane functions")
    assert patch_code.is_vanilla_name_pane_size(data)
    assert patch_code.apply_name_pane_patches(data) is True
    assert patch_code.is_patched_code(data)
    assert patch_code.is_wide_name_panes(data)
    assert patch_code.apply_name_pane_patches(data) is False
