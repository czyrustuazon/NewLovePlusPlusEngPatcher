"""Short talk-window speaker names keep normal letter spacing."""

from __future__ import annotations

from conftest import SRC, load_module

spacing = load_module("patch_speaker_spacing", SRC / "patch_speaker_spacing.py")


def _image(table) -> bytearray:
    data = bytearray(spacing.ADDR_SPEAKER_SPACING + 0x40)
    raw = spacing._pack(table)
    data[spacing.ADDR_SPEAKER_SPACING : spacing.ADDR_SPEAKER_SPACING + len(raw)] = raw
    return data


def test_vanilla_spacing_is_zeroed():
    data = _image(spacing.VANILLA)
    assert spacing.apply_patch(data) is True
    assert spacing.is_patched(data)
    assert spacing.apply_patch(data) is False


def test_three_glyph_name_loses_its_gap():
    # PPP is three glyphs; vanilla adds 8px after each one.
    assert spacing.VANILLA[3] == (-1, 8)
    assert spacing.PATCHED[3] == (0, 0)


def test_unexpected_table_is_refused():
    data = _image(((1, 1),) * 9)
    try:
        spacing.apply_patch(data)
    except ValueError:
        return
    raise AssertionError("apply wrote over an unexpected spacing table")
