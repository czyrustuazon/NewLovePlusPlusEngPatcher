"""Tests for heroine name patches (patch_names.py)."""

from __future__ import annotations

from pathlib import Path

import patch_names as names


def test_replace_dialog_tokens_strips_markers():
    text = "Hello ▲高嶺＊＊▲, meet ▲小早川＊▲!"
    new, n = names.replace_dialog_tokens(text)
    assert new == "Hello Takane, meet Rinko!"
    assert n == 2


def test_replace_dialog_tokens_trailing_pad():
    text = "See Takane       !"
    new, n = names.replace_dialog_tokens(text)
    assert new == "See Takane!"
    assert n == 1


def test_replace_all_same_length_padding():
    old = "高嶺".encode("utf-8")
    data = bytearray(b"prefix" + old + b"suffix")
    count = names.replace_all(data, "高嶺", "Takane")
    assert count == 1
    assert b"Takane" in data


def test_replace_all_rejects_overflow():
    data = bytearray(b"ab")
    try:
        names.replace_all(data, "ab", "toolong")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "slot" in str(exc)


def test_patch_name_table_bytes():
    raw = "高嶺 愛花］".encode("utf-8") + b"\x00" * 4
    data = bytearray(raw)
    n = names.patch_name_table_bytes(data)
    assert n >= 1
    assert b"Takane Manaka" in bytes(data)


def test_sdl2_roundtrip():
    original = names.SDL2Data(
        key=0x12345678,
        unknown=[],
        dialogs=["Line with ▲姉ヶ崎＊▲ token"],
    )
    blob = names.build_sdl2(original)
    parsed = names.parse_sdl2(blob)
    assert parsed.key == original.key
    assert parsed.dialogs == original.dialogs


def test_dbin2_roundtrip_and_patch(tmp_path: Path):
    sdl2 = names.SDL2Data(key=0xAABBCCDD, unknown=[], dialogs=["▲高嶺＊＊▲ speaks"])
    entry = names.DbinEntry(1, 2, sdl2)
    blob = names.build_dbin2(0xDEADBEEF, 0, [entry])

    path = tmp_path / "test.dbin2"
    path.write_bytes(blob)
    repl = names.patch_dbin2_file(path, strip_tokens=True)
    assert repl == 1

    key, unknown, entries = names.parse_dbin2(path.read_bytes())
    assert key == 0xDEADBEEF
    assert entries[0].sdl2.dialogs == ["Takane speaks"]


def test_patch_dbin2_preserves_tokens_by_default(tmp_path: Path):
    dialog = "▲高嶺＊＊▲ speaks"
    sdl2 = names.SDL2Data(key=0xAABBCCDD, unknown=[], dialogs=[dialog])
    path = tmp_path / "test.dbin2"
    path.write_bytes(names.build_dbin2(0xDEADBEEF, 0, [names.DbinEntry(1, 2, sdl2)]))

    assert names.patch_dbin2_file(path) == 0
    _, _, entries = names.parse_dbin2(path.read_bytes())
    assert entries[0].sdl2.dialogs == [dialog]
