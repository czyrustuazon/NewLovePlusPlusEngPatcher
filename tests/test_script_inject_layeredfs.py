"""LayeredFS dialog inject matches the CIA .dbin2 picker."""

from __future__ import annotations

from pathlib import Path

import pytest

import script_inject


def _write(root: Path, rel: str, payload: bytes = b"EN") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_layeredfs_inject_creates_dirs_and_skips_japanese(tmp_path: Path, monkeypatch):
    eng = tmp_path / "rebuild_dbin2"
    _write(eng, "NLP_01/t001.dbin2", b"manaka")
    _write(eng, "NLP_01/a001.dbin2", b"skip-pack")
    _write(eng, "NLP_02/p010.dbin2", b"common")
    _write(eng, "script/t002.dbin2", b"manaka-script")
    _write(eng, "script/a900.dbin2", b"community")
    _write(eng, "script/a901.dbin2", b"still-jp")
    monkeypatch.setattr(script_inject, "community_stems", lambda: {"a900"})

    romfs = tmp_path / "romfs"
    count = script_inject.inject_scripts(romfs, eng, create_dirs=True)

    assert count == 4
    assert (romfs / "script/bin/NLP_01/t001.dbin2").read_bytes() == b"manaka"
    assert (romfs / "script/bin/NLP_02/p010.dbin2").read_bytes() == b"common"
    assert (romfs / "script/bin/script/t002.dbin2").read_bytes() == b"manaka-script"
    assert (romfs / "script/bin/script/a900.dbin2").read_bytes() == b"community"
    assert not (romfs / "script/bin/NLP_01/a001.dbin2").exists()
    assert not (romfs / "script/bin/script/a901.dbin2").exists()


def test_a_stem_speaker_becomes_anegasaki(tmp_path: Path, monkeypatch):
    import patch_names as names

    def _script(dialogs: list[str]) -> bytes:
        sdl2 = names.SDL2Data(key=2, unknown=[], dialogs=dialogs)
        return names.build_dbin2(1, 0, [names.DbinEntry(0, 0, sdl2)])

    eng = tmp_path / "rebuild_dbin2"
    _write(eng, "NLP_01/t001.dbin2", b"manaka")
    _write(eng, "NLP_02/p010.dbin2", b"common")
    _write(eng, "script/t002.dbin2", b"manaka-script")
    (eng / "script" / "a900.dbin2").write_bytes(
        _script(["姉ヶ崎", "Hello ▲姉ヶ崎＊▲"])
    )
    (eng / "script" / "p004.dbin2").write_bytes(
        _script(["姉ヶ崎", "See ▲姉ヶ崎＊▲"])
    )
    (eng / "script" / "p011.dbin2").write_bytes(
        _script(["小早川", "Hi ▲小早川＊▲", "▲高嶺＊＊▲", "高嶺"])
    )
    monkeypatch.setattr(script_inject, "community_stems", lambda: {"a900"})

    romfs = tmp_path / "romfs"
    script_inject.inject_scripts(romfs, eng, create_dirs=True)

    _, _, entries = names.parse_dbin2(
        (romfs / "script/bin/script/a900.dbin2").read_bytes()
    )
    assert entries[0].sdl2.dialogs == ["Anegasaki", "Hello ▲Anegasaki＊▲"]
    _, _, common = names.parse_dbin2(
        (romfs / "script/bin/script/p004.dbin2").read_bytes()
    )
    assert common[0].sdl2.dialogs == ["姉ヶ崎", "See ▲Anegasaki＊▲"]
    _, _, rinko = names.parse_dbin2(
        (romfs / "script/bin/script/p011.dbin2").read_bytes()
    )
    assert rinko[0].sdl2.dialogs == [
        "Kobayaka",
        "Hi ▲Kobayaka＊▲",
        "▲Takane＊＊▲",
        "Takane",
    ]


def test_vanilla_scripts_overlay_nene_marker_only(tmp_path: Path):
    import patch_names as names

    def _script(dialogs: list[str]) -> bytes:
        sdl2 = names.SDL2Data(key=2, unknown=[], dialogs=dialogs)
        return names.build_dbin2(1, 0, [names.DbinEntry(0, 0, sdl2)])

    vanilla = tmp_path / "vanilla"
    (vanilla / "script").mkdir(parents=True)
    (vanilla / "NLP_01").mkdir()
    (vanilla / "script" / "a050.dbin2").write_bytes(
        _script(["姉ヶ崎", "まだ▲姉ヶ崎＊▲"])
    )
    (vanilla / "script" / "a099.dbin2").write_bytes(_script(["no marker"]))
    (vanilla / "NLP_01" / "a050.dbin2").write_bytes(_script(["▲姉ヶ崎＊▲"]))

    romfs = tmp_path / "romfs"
    eng = romfs / "script" / "bin" / "script"
    eng.mkdir(parents=True)
    (eng / "a001.dbin2").write_bytes(
        _script(["Anegasaki", "Hello ▲Anegasaki＊▲"])
    )
    (eng / "k050.dbin2").write_bytes(_script(["姉ヶ崎", "See ▲姉ヶ崎＊▲"]))
    (eng / "p010.dbin2").write_bytes(
        _script(["小早川", "See ▲小早川＊▲", "▲高嶺＊＊▲"])
    )
    (vanilla / "script" / "t010.dbin2").write_bytes(
        _script(["高嶺", "▲高嶺＊＊▲", "今日は高嶺だ"])
    )
    (vanilla / "script" / "k010.dbin2").write_bytes(
        _script(["小早川", "▲小早川＊▲"])
    )
    (vanilla / "script" / "k099.dbin2").write_bytes(_script(["今日は小早川だ"]))

    changed = script_inject.apply_nene_marker_to_romfs(romfs, vanilla)
    assert changed == 6

    _, _, kept = names.parse_dbin2((eng / "a001.dbin2").read_bytes())
    assert kept[0].sdl2.dialogs == ["Anegasaki", "Hello ▲Anegasaki＊▲"]
    _, _, patched = names.parse_dbin2((eng / "k050.dbin2").read_bytes())
    assert patched[0].sdl2.dialogs == ["姉ヶ崎", "See ▲Anegasaki＊▲"]
    _, _, copied = names.parse_dbin2(
        (romfs / "script" / "bin" / "script" / "a050.dbin2").read_bytes()
    )
    assert copied[0].sdl2.dialogs == ["Anegasaki", "まだ▲Anegasaki＊▲"]
    _, _, pack = names.parse_dbin2(
        (romfs / "script" / "bin" / "NLP_01" / "a050.dbin2").read_bytes()
    )
    assert pack[0].sdl2.dialogs == ["▲Anegasaki＊▲"]
    _, _, rinko = names.parse_dbin2((eng / "p010.dbin2").read_bytes())
    assert rinko[0].sdl2.dialogs == ["Kobayaka", "See ▲Kobayaka＊▲", "▲Takane＊＊▲"]
    _, _, manaka = names.parse_dbin2(
        (romfs / "script" / "bin" / "script" / "t010.dbin2").read_bytes()
    )
    assert manaka[0].sdl2.dialogs == ["Takane", "▲Takane＊＊▲", "今日は高嶺だ"]
    _, _, copied_r = names.parse_dbin2(
        (romfs / "script" / "bin" / "script" / "k010.dbin2").read_bytes()
    )
    assert copied_r[0].sdl2.dialogs == ["Kobayaka", "▲Kobayaka＊▲"]
    assert not (romfs / "script" / "bin" / "script" / "a099.dbin2").exists()
    assert not (romfs / "script" / "bin" / "script" / "k099.dbin2").exists()


def test_cia_inject_still_requires_existing_pack_dirs(tmp_path: Path):
    eng = tmp_path / "rebuild_dbin2"
    for pack in ("NLP_01", "NLP_02", "script"):
        _write(eng, f"{pack}/t001.dbin2")
    with pytest.raises(script_inject.ScriptInjectError, match="missing script pack folder"):
        script_inject.inject_scripts(tmp_path / "romfs", eng, create_dirs=False)
