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


def test_restore_control_tokens_to_japanese_keys():
    text = "Hi ▲Protagonist＊▲, meet ▲Anesaki＊▲ and ▲Rinko's▲."
    got = names.restore_control_tokens(text)
    assert got == "Hi ▲主人公＊▲, meet ▲Anegasaki＊▲ and ▲凛▲'s."
    assert names.restore_control_tokens("▲the\nprotagonist＊▲") == "▲主人公＊▲"
    assert names.restore_control_tokens("▲彼女＊＊▲ stays") == "▲彼女＊＊▲ stays"
    assert names.restore_control_tokens("▲Last name▲ ▲First Name▲") == "▲苗字▲ ▲名前▲"
    assert names.restore_control_tokens("▲Anegasaki＊▲") == "▲Anegasaki＊▲"
    assert names.restore_control_tokens("call ▲姉ヶ崎＊▲") == "call ▲Anegasaki＊▲"
    assert names.restore_control_tokens("▲小早川＊▲") == "▲Kobayaka＊▲"
    assert names.restore_control_tokens("▲Kobayakawa＊▲") == "▲Kobayaka＊▲"
    assert names.restore_control_tokens("▲高嶺＊＊▲") == "▲Takane＊＊▲"
    assert names.restore_control_tokens("▲Takane＊＊▲") == "▲Takane＊＊▲"
    assert names.restore_control_tokens("▲Takamine ＊＊▲") == "▲Takane＊＊▲"


def test_manaka_marker_slot_becomes_takane_and_a_sentence_stays():
    token = "▲高嶺＊＊▲"
    live = "▲Takane＊＊▲"
    sentence = "今日は高嶺だ"
    blob = bytearray(b"\x00" + token.encode("utf-8") + b"\x00" + sentence.encode("utf-8") + b"\x00")
    names.patch_name_table_bytes(blob)
    chunks = [c.decode("utf-8") for c in bytes(blob).split(b"\x00") if c]
    assert chunks == [live, sentence]


def test_manaka_surname_slots_fit_and_keep_other_heroines():
    for old, new in names.MANAKA_SURNAME_SLOTS:
        assert len(new.encode("utf-8")) <= len(old.encode("utf-8"))
    parts = [
        "高嶺",
        "高嶺さん",
        "▲高嶺＊＊▲",
        "▲Kobayaka＊▲",
        "▲Anegasaki＊▲",
        "今日は高嶺だ",
    ]
    blob = bytearray()
    for part in parts:
        blob += b"\x00" + part.encode("utf-8")
    blob += b"\x00"
    assert names.patch_manaka_surname_bytes(blob) == 3
    chunks = [c.decode("utf-8") for c in bytes(blob).split(b"\x00") if c]
    assert chunks == [
        "Takane",
        "Takane-san",
        "▲Takane＊＊▲",
        "▲Kobayaka＊▲",
        "▲Anegasaki＊▲",
        "今日は高嶺だ",
    ]


def test_rewrite_manaka_surname_speakers_updates_token():
    original = ["高嶺", "Hello ▲高嶺＊＊▲", "▲Kobayaka＊▲", "今日は高嶺だ"]
    blob = names.build_dbin2(
        1,
        0,
        [names.DbinEntry(0, 0, names.SDL2Data(key=2, unknown=[], dialogs=list(original)))],
    )
    patched = names.rewrite_manaka_surname_speakers(blob)
    _, _, entries = names.parse_dbin2(patched)
    assert entries[0].sdl2.dialogs == [
        "Takane",
        "Hello ▲Takane＊＊▲",
        "▲Kobayaka＊▲",
        "今日は高嶺だ",
    ]
    assert names.rewrite_manaka_surname_speakers(b"not-a-script") == b"not-a-script"
    assert names.rewrite_manaka_surname_speakers(patched) == patched


def test_nene_surname_slots_rewrite_nickname_key():
    token = "▲姉ヶ崎＊▲"
    live = "▲Anegasaki＊▲"
    parts = [
        "姉ヶ崎",
        "姉ヶ崎さん",
        "姉ヶ崎寧々",
        "［姉ヶ崎 寧々］",
        "姉ヶ崎先輩",
        token,
        "寧々",
    ]
    blob = bytearray()
    for part in parts:
        blob += b"\x00" + part.encode("utf-8")
    blob += b"\x00"
    assert names.patch_name_table_bytes(blob) >= 5
    chunks = [c.decode("utf-8") for c in bytes(blob).split(b"\x00") if c]
    assert chunks == [
        "Anegasaki",
        "Anegasaki-san",
        "Anegasaki Nene",
        "［Anegasaki Nene］",
        "Nene-senpai",
        live,
        "Nene",
    ]


def test_exact_cstring_rejects_senpai_overflow():
    data = bytearray(b"\x00" + "姉ヶ崎先輩".encode("utf-8") + b"\x00")
    try:
        names.replace_exact_cstring(data, "姉ヶ崎先輩", "Anegasaki-senpai")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "slot" in str(exc)
    assert "姉ヶ崎先輩".encode("utf-8") in data


def test_rinko_surname_slots_use_kobayaka_and_keep_takane():
    for old, new in names.RINKO_SURNAME_SLOTS:
        assert len(new.encode("utf-8")) <= len(old.encode("utf-8"))
    parts = [
        "小早川",
        "小早川さん",
        "▲小早川＊▲",
        "▲高嶺＊＊▲",
        "小早川凛子",
        "今日は小早川だ",
    ]
    blob = bytearray()
    for part in parts:
        blob += b"\x00" + part.encode("utf-8")
    blob += b"\x00"
    assert names.patch_rinko_surname_bytes(blob) == 4
    chunks = [c.decode("utf-8") for c in bytes(blob).split(b"\x00") if c]
    assert chunks == [
        "Kobayaka",
        "Kobayaka-san",
        "▲Kobayaka＊▲",
        "▲高嶺＊＊▲",
        "Kobayaka Rinko",
        "今日は小早川だ",
    ]


def test_rewrite_rinko_surname_speakers_updates_token():
    original = ["小早川", "Hello ▲小早川＊▲", "▲高嶺＊＊▲", "今日は小早川だ"]
    blob = names.build_dbin2(
        1,
        0,
        [names.DbinEntry(0, 0, names.SDL2Data(key=2, unknown=[], dialogs=list(original)))],
    )
    patched = names.rewrite_rinko_surname_speakers(blob)
    _, _, entries = names.parse_dbin2(patched)
    assert entries[0].sdl2.dialogs == [
        "Kobayakawa",
        "Hello ▲Kobayaka＊▲",
        "▲高嶺＊＊▲",
        "今日は小早川だ",
    ]
    assert names.rewrite_rinko_surname_speakers(b"not-a-script") == b"not-a-script"
    assert names.rewrite_rinko_surname_speakers(patched) == patched


def test_rewrite_rinko_surname_speakers_widens_committed_plate():
    blob = names.build_dbin2(
        1,
        0,
        [names.DbinEntry(0, 0, names.SDL2Data(key=2, unknown=[], dialogs=["Kobayaka", "▲Kobayaka＊▲"]))],
    )
    _, _, entries = names.parse_dbin2(names.rewrite_rinko_surname_speakers(blob))
    assert entries[0].sdl2.dialogs == ["Kobayakawa", "▲Kobayaka＊▲"]
    assert names.rewrite_rinko_nickname_tokens(blob) == blob


def test_rewrite_nene_surname_speakers_updates_token():
    original = ["姉ヶ崎", "Hello ▲姉ヶ崎＊▲"]
    blob = names.build_dbin2(
        1,
        0,
        [names.DbinEntry(0, 0, names.SDL2Data(key=2, unknown=[], dialogs=list(original)))],
    )
    patched = names.rewrite_nene_surname_speakers(blob)
    _, _, entries = names.parse_dbin2(patched)
    assert entries[0].sdl2.dialogs == ["Anegasaki", "Hello ▲Anegasaki＊▲"]
    assert names.rewrite_nene_surname_speakers(b"not-a-script") == b"not-a-script"
    assert names.rewrite_nene_surname_speakers(patched) == patched


def test_nickname_token_rewrite_skips_other_route_speakers():
    original = ["姉ヶ崎", "Hello ▲姉ヶ崎＊▲", "▲高嶺＊＊▲"]
    blob = names.build_dbin2(
        1,
        0,
        [names.DbinEntry(0, 0, names.SDL2Data(key=2, unknown=[], dialogs=list(original)))],
    )
    patched = names.rewrite_nene_nickname_tokens(blob)
    _, _, entries = names.parse_dbin2(patched)
    assert entries[0].sdl2.dialogs == ["姉ヶ崎", "Hello ▲Anegasaki＊▲", "▲高嶺＊＊▲"]


def test_patch_dbin2_preserves_tokens_by_default(tmp_path: Path):
    dialog = "▲高嶺＊＊▲ speaks"
    sdl2 = names.SDL2Data(key=0xAABBCCDD, unknown=[], dialogs=[dialog])
    path = tmp_path / "test.dbin2"
    path.write_bytes(names.build_dbin2(0xDEADBEEF, 0, [names.DbinEntry(1, 2, sdl2)]))

    assert names.patch_dbin2_file(path) == 0
    _, _, entries = names.parse_dbin2(path.read_bytes())
    assert entries[0].sdl2.dialogs == [dialog]
