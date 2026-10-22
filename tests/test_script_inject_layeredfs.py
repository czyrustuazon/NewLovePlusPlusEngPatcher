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
    monkeypatch.delenv("NLPP_INCLUDE_GEMINI_NENE", raising=False)

    romfs = tmp_path / "romfs"
    count = script_inject.inject_scripts(romfs, eng, create_dirs=True)

    assert count == 4
    assert (romfs / "script/bin/NLP_01/t001.dbin2").read_bytes() == b"manaka"
    assert (romfs / "script/bin/NLP_02/p010.dbin2").read_bytes() == b"common"
    assert (romfs / "script/bin/script/t002.dbin2").read_bytes() == b"manaka-script"
    assert (romfs / "script/bin/script/a900.dbin2").read_bytes() == b"community"
    assert not (romfs / "script/bin/NLP_01/a001.dbin2").exists()
    assert not (romfs / "script/bin/script/a901.dbin2").exists()


def test_gemini_nene_opt_in_overrides_community_a_and_fills_packs(
    tmp_path: Path, monkeypatch
):
    eng = tmp_path / "rebuild_dbin2"
    _write(eng, "NLP_01/t001.dbin2", b"manaka")
    _write(eng, "NLP_02/p010.dbin2", b"common")
    _write(eng, "script/t002.dbin2", b"manaka-script")
    _write(eng, "script/a900.dbin2", b"community-a900")
    _write(eng, "script/k001.dbin2", b"community-k")

    gem = tmp_path / "gemini_dbin2"
    _write(gem, "NLP_01/a900.dbin2", b"gemini-a900-nlp01")
    _write(gem, "NLP_02/a900.dbin2", b"gemini-a900-nlp02")
    _write(gem, "script/a900.dbin2", b"gemini-a900-script")
    _write(gem, "script/a901.dbin2", b"gemini-a901")
    _write(gem, "NLP_01/a901.dbin2", b"gemini-a901-nlp01")

    monkeypatch.setattr(script_inject, "community_stems", lambda: {"a900", "k001"})
    monkeypatch.setattr(script_inject, "gemini_nene_stems", lambda: {"a900", "a901"})
    monkeypatch.setattr(script_inject, "GEMINI_NENE_DBIN", gem)
    monkeypatch.setenv("NLPP_INCLUDE_GEMINI_NENE", "1")

    romfs = tmp_path / "romfs"
    count = script_inject.inject_scripts(romfs, eng, create_dirs=True)

    # manaka×2 + p*×1 + gemini a* across packs (5) + community k* (1)
    assert count == 9
    assert (romfs / "script/bin/script/a900.dbin2").read_bytes() == b"gemini-a900-script"
    assert (romfs / "script/bin/script/a901.dbin2").read_bytes() == b"gemini-a901"
    assert (romfs / "script/bin/NLP_01/a900.dbin2").read_bytes() == b"gemini-a900-nlp01"
    assert (romfs / "script/bin/NLP_01/a901.dbin2").read_bytes() == b"gemini-a901-nlp01"
    assert (romfs / "script/bin/NLP_02/a900.dbin2").read_bytes() == b"gemini-a900-nlp02"
    assert (romfs / "script/bin/script/k001.dbin2").read_bytes() == b"community-k"


def test_contrib_file_ships_without_gemini_and_wins_over_it(
    tmp_path: Path, monkeypatch
):
    eng = tmp_path / "rebuild_dbin2"
    _write(eng, "NLP_01/t001.dbin2", b"manaka")
    _write(eng, "NLP_02/p010.dbin2", b"common")
    _write(eng, "script/t002.dbin2", b"manaka-script")
    _write(eng, "script/a900.dbin2", b"community-a900")

    gem = tmp_path / "gemini_dbin2"
    _write(gem, "script/a900.dbin2", b"gemini-a900")
    _write(gem, "script/a901.dbin2", b"gemini-a901")
    _write(gem, "NLP_01/a901.dbin2", b"gemini-a901-nlp")

    contrib = tmp_path / "script_contrib"
    _write(contrib, "script/a900.dbin2", b"human-a900")
    _write(contrib, "script/a901.dbin2", b"human-a901")
    _write(contrib, "NLP_01/a901.dbin2", b"human-a901-nlp")

    monkeypatch.setattr(script_inject, "community_stems", lambda: {"a900"})
    monkeypatch.setattr(script_inject, "gemini_nene_stems", lambda: {"a900", "a901"})
    monkeypatch.setattr(script_inject, "GEMINI_NENE_DBIN", gem)
    monkeypatch.setattr(script_inject, "CONTRIB_DBIN", contrib)
    monkeypatch.delenv("NLPP_INCLUDE_GEMINI_NENE", raising=False)

    romfs = tmp_path / "romfs"
    script_inject.inject_scripts(romfs, eng, create_dirs=True)
    assert (romfs / "script/bin/script/a900.dbin2").read_bytes() == b"human-a900"
    assert (romfs / "script/bin/script/a901.dbin2").read_bytes() == b"human-a901"
    assert (romfs / "script/bin/NLP_01/a901.dbin2").read_bytes() == b"human-a901-nlp"

    monkeypatch.setenv("NLPP_INCLUDE_GEMINI_NENE", "1")
    romfs_on = tmp_path / "romfs-on"
    script_inject.inject_scripts(romfs_on, eng, create_dirs=True)
    assert (romfs_on / "script/bin/script/a900.dbin2").read_bytes() == b"human-a900"
    assert (romfs_on / "script/bin/script/a901.dbin2").read_bytes() == b"human-a901"


def test_nene_speaker_becomes_anegasaki_on_every_stem(tmp_path: Path, monkeypatch):
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
    assert common[0].sdl2.dialogs == ["Anegasaki", "See ▲Anegasaki＊▲"]
    _, _, rinko = names.parse_dbin2(
        (romfs / "script/bin/script/p011.dbin2").read_bytes()
    )
    assert rinko[0].sdl2.dialogs == [
        "Kobayakawa",
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
    assert patched[0].sdl2.dialogs == ["Anegasaki", "See ▲Anegasaki＊▲"]
    _, _, copied = names.parse_dbin2(
        (romfs / "script" / "bin" / "script" / "a050.dbin2").read_bytes()
    )
    assert copied[0].sdl2.dialogs == ["Anegasaki", "まだ▲Anegasaki＊▲"]
    _, _, pack = names.parse_dbin2(
        (romfs / "script" / "bin" / "NLP_01" / "a050.dbin2").read_bytes()
    )
    assert pack[0].sdl2.dialogs == ["▲Anegasaki＊▲"]
    _, _, rinko = names.parse_dbin2((eng / "p010.dbin2").read_bytes())
    assert rinko[0].sdl2.dialogs == ["Kobayakawa", "See ▲Kobayaka＊▲", "▲Takane＊＊▲"]
    _, _, manaka = names.parse_dbin2(
        (romfs / "script" / "bin" / "script" / "t010.dbin2").read_bytes()
    )
    assert manaka[0].sdl2.dialogs == ["Takane", "▲Takane＊＊▲", "今日は高嶺だ"]
    _, _, copied_r = names.parse_dbin2(
        (romfs / "script" / "bin" / "script" / "k010.dbin2").read_bytes()
    )
    assert copied_r[0].sdl2.dialogs == ["Kobayakawa", "▲Kobayaka＊▲"]
    assert not (romfs / "script" / "bin" / "script" / "a099.dbin2").exists()
    assert not (romfs / "script" / "bin" / "script" / "k099.dbin2").exists()


def test_cia_inject_still_requires_existing_pack_dirs(tmp_path: Path):
    eng = tmp_path / "rebuild_dbin2"
    for pack in ("NLP_01", "NLP_02", "script"):
        _write(eng, f"{pack}/t001.dbin2")
    with pytest.raises(script_inject.ScriptInjectError, match="missing script pack folder"):
        script_inject.inject_scripts(tmp_path / "romfs", eng, create_dirs=False)
