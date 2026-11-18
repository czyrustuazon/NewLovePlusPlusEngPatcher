"""Community a*/k* English mapped onto the NLP_01 / NLP_02 script packs."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import TOOLS, load_module

import patch_names as names
import script_inject

cp = load_module("build_community_packs", TOOLS / "build_community_packs.py")


def script(entries: list[list[str]], key: int = 1, skey: int = 2) -> bytes:
    """DBN2 with one entry per dialog list; ``key`` / ``skey`` stand for the per-pack keys."""
    return names.build_dbin2(
        key, 0, [names.DbinEntry(i, i, names.SDL2Data(skey, [], d)) for i, d in enumerate(entries)]
    )


JP = [["こんにちは。\n元気？", "うん"], ["またね"]]
EN = [["Hello.\nHow are you?", "Yeah"], ["See you"]]


def test_map_pack_keeps_pack_keys_and_takes_english():
    pack = script([["こんにちは。　元気？", "うん"], ["またね"]], key=7, skey=9)
    out, why = cp.map_pack(script(EN), script(JP), pack)
    assert why == ""
    key, _unknown, entries = names.parse_dbin2(out)
    assert key == 7
    assert [e.sdl2.key for e in entries] == [9, 9]
    assert [e.sdl2.dialogs for e in entries] == EN


def test_map_pack_takes_a_shorter_pack():
    out, _ = cp.map_pack(script(EN), script(JP), script(JP[:1]))
    assert [e.sdl2.dialogs for e in names.parse_dbin2(out)[2]] == EN[:1]


def test_map_pack_accepts_typo_level_variants():
    pack = script([["こんにちわ。元気？", "うん"], ["またね"]])
    assert cp.map_pack(script(EN), script(JP), pack)[1] == ""


@pytest.mark.parametrize(
    ("english", "pack", "why"),
    [
        (EN[:1], JP, "shape"),
        (EN, JP + [["余分"]], "3 entries, script has 2"),
        (EN, [["こんにちは。", "うん", "え"], ["またね"]], "entry 0: 3 dialogs"),
        (EN, [["こんにちは。元気？", "まったく別の台詞です"], ["またね"]], "entry 0 dialog 1"),
    ],
)
def test_map_pack_refuses_lines_that_do_not_line_up(english, pack, why):
    out, reason = cp.map_pack(script(english), script(JP), script(pack))
    assert out is None
    assert why in reason


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    dbin, vanilla = tmp_path / "rebuild_dbin2", tmp_path / "vanilla"
    for pack in ("script", "NLP_01", "NLP_02"):
        (dbin / pack).mkdir(parents=True)
        (vanilla / pack).mkdir(parents=True)
    for stem in ("k002", "a027", "t001", "k999"):
        (dbin / "script" / f"{stem}.dbin2").write_bytes(script(EN))
        (vanilla / "script" / f"{stem}.dbin2").write_bytes(script(JP))
    (vanilla / "NLP_01" / "k002.dbin2").write_bytes(script(JP, key=5))
    (vanilla / "NLP_02" / "k002.dbin2").write_bytes(script(JP, key=6))
    (vanilla / "NLP_01" / "a027.dbin2").write_bytes(script([["別の文です", "うん"], ["またね"]]))
    (vanilla / "NLP_01" / "t001.dbin2").write_bytes(script(JP))
    (vanilla / "NLP_01" / "k999.dbin2").write_bytes(script(JP))
    return dbin, vanilla


def test_main_writes_aligned_community_stems(tmp_path, monkeypatch, capsys):
    dbin, vanilla = _tree(tmp_path)
    monkeypatch.setattr(script_inject, "community_stems", lambda: {"k002", "a027"})
    assert cp.main(["--dbin", str(dbin), "--vanilla-bin", str(vanilla), "--check"]) == 0
    assert not (dbin / "NLP_01" / "k002.dbin2").exists()
    assert cp.main(["--dbin", str(dbin), "--vanilla-bin", str(vanilla)]) == 0
    out = capsys.readouterr().out
    assert "can write 2 pack file(s)" in out and "wrote 2 pack file(s)" in out
    assert "skipped NLP_01/a027: entry 0 dialog 0" in out
    for pack, key in (("NLP_01", 5), ("NLP_02", 6)):
        k, _u, entries = names.parse_dbin2((dbin / pack / "k002.dbin2").read_bytes())
        assert k == key and [e.sdl2.dialogs for e in entries] == EN
    assert not (dbin / "NLP_01" / "a027.dbin2").exists()
    assert not (dbin / "NLP_01" / "t001.dbin2").exists()  # Manaka is not community
    assert not (dbin / "NLP_01" / "k999.dbin2").exists()  # not in the manifest


def test_without_a_manifest_every_a_k_stem_is_community(tmp_path, monkeypatch):
    dbin, _vanilla = _tree(tmp_path)
    monkeypatch.setattr(script_inject, "community_stems", lambda: set())
    assert cp.community_english(dbin) == ["a027", "k002", "k999"]


def test_main_needs_the_vanilla_tree(tmp_path):
    with pytest.raises(SystemExit, match="missing vanilla script tree"):
        cp.main(["--vanilla-bin", str(tmp_path / "none")])


@pytest.mark.local_data
def test_shipped_pack_files_match_a_fresh_build(tmp_path):
    """rebuild_dbin2/NLP_0x community files are current with rebuild_dbin2/script."""
    if not (cp.VANILLA_BIN / "script").is_dir():
        pytest.skip("no vanilla script tree")
    dbin = tmp_path / "dbin"
    (dbin / "script").mkdir(parents=True)
    for stem in cp.community_english(cp.DBIN):
        (dbin / "script" / f"{stem}.dbin2").write_bytes((cp.DBIN / "script" / f"{stem}.dbin2").read_bytes())
    done, _skipped = cp.build(dbin, cp.VANILLA_BIN, write=True)
    assert done > 0
    for path in sorted((dbin / "NLP_01").glob("*.dbin2")) + sorted((dbin / "NLP_02").glob("*.dbin2")):
        assert (cp.DBIN / path.parent.name / path.name).read_bytes() == path.read_bytes(), path
