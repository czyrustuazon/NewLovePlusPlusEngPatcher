"""Coverage for tools/rebuild_dbin2_from_xml.py on tiny generated XML."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import TOOLS, load_module

rb = load_module("rebuild_dbin2_from_xml", TOOLS / "rebuild_dbin2_from_xml.py")
TOKEN = rb.HERO_TOKEN


def _entries(dialogs: list[str]) -> list:
    unknown = [
        rb.UnknownEntry([rb.SectionAEntry(1, 2)], 3, 4),
        rb.UnknownEntry([], 5, 6),
    ]
    return [rb.DbinEntry(7, 8, rb.SDL2Data(9, unknown, dialogs))]


def _xml(path: Path, dialogs: list[str], extra: str = "") -> Path:
    text = rb.entries_to_xml(10, 11, _entries(dialogs))
    if extra:
        text = text.replace("  <Entries>", f"  <!-- {extra} -->\n  <Entries>", 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_round_trip_and_token_count(tmp_path):
    xml = _xml(tmp_path / "t001.xml", [f"Hi {TOKEN}", "a < b & c"])
    key, unknown, entries = rb.xml_to_entries(xml)
    assert (key, unknown) == (10, 11)
    assert entries[0].sdl2.dialogs[1] == "a < b & c"
    dbin = tmp_path / "t001.dbin2"
    dbin.write_bytes(rb.build_dbin2(key, unknown, entries))
    assert rb.count_tokens_in_dbin(dbin) == 1 == rb.count_tokens_in_xml(xml)


@pytest.mark.parametrize("body, msg", [
    ("<Other/>", "root tag must be DBIN2"),
    ("<DBIN2 Key='1' Unknown='2'/>", "missing <Entries>"),
    ("<DBIN2 Key='1' Unknown='2'><Entries><Entry Unknown0='1' Unknown1='2'/></Entries></DBIN2>", "missing <SDL2>"),
    (
        "<DBIN2 Key='1' Unknown='2'><Entries><Entry Unknown0='1' Unknown1='2'>"
        "<SDL2 Key='3'/></Entry></Entries></DBIN2>",
        "SDL2 missing <Dialogs>",
    ),
])
def test_xml_errors(tmp_path, body, msg):
    path = tmp_path / "bad.xml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match=msg):
        rb.xml_to_entries(path)


def test_sdl2_without_unknown_block(tmp_path):
    path = tmp_path / "plain.xml"
    path.write_text(
        "<DBIN2 Key='1' Unknown='2'><Entries><Entry Unknown0='1' Unknown1='2'>"
        "<SDL2 Key='3'><Dialogs><Dialog>x</Dialog><Dialog/></Dialogs></SDL2>"
        "</Entry></Entries></DBIN2>",
        encoding="utf-8",
    )
    _k, _u, entries = rb.xml_to_entries(path)
    assert entries[0].sdl2.unknown == [] and entries[0].sdl2.dialogs == ["x", ""]


def test_packs_for_stem(tmp_path):
    assert rb.packs_for_stem("t001", None) == list(rb.PACKS)
    assert rb.packs_for_stem("t001", tmp_path / "missing") == list(rb.PACKS)
    (tmp_path / "NLP_01").mkdir()
    (tmp_path / "NLP_01" / "t001.dbin2").write_bytes(b"x")
    assert rb.packs_for_stem("t001", tmp_path) == ["NLP_01"]
    assert rb.packs_for_stem("t999", tmp_path) == list(rb.PACKS)


def test_build_one_paths(tmp_path):
    out = tmp_path / "out"
    vanilla = tmp_path / "van"
    (vanilla / "script").mkdir(parents=True)
    (vanilla / "script" / "t001.dbin2").write_bytes(b"x")
    # A token in an XML comment is counted in the XML but not in the dbin2.
    xml = _xml(tmp_path / "s" / "t001.xml", ["plain"], extra=TOKEN)
    built = rb.build_one(xml, out, vanilla, verify=False)
    assert [r.pack for r in built] == ["script"] and built[0].warnings
    # Verify mode compares with what is already on disk and writes nothing.
    checked = rb.build_one(xml, out, vanilla, verify=True)
    assert checked[0].warnings == ["was dbin_tokens=0"]
    fresh = rb.build_one(xml, tmp_path / "out2", vanilla, verify=True)
    assert fresh[0].warnings == [] and not (tmp_path / "out2" / "script" / "t001.dbin2").exists()

    broken = tmp_path / "s" / "t002.xml"
    broken.write_text("<DBIN2", encoding="utf-8")
    failed = rb.build_one(broken, out, None, verify=False)
    assert len(failed) == len(rb.PACKS) and not any(r.ok for r in failed)


def test_build_one_matching_tokens(tmp_path):
    xml = _xml(tmp_path / "t003.xml", [f"{TOKEN}!"])
    res = rb.build_one(xml, tmp_path / "out", None, verify=False)
    assert all(r.ok and not r.warnings for r in res)
    again = rb.build_one(xml, tmp_path / "out", None, verify=True)
    assert all(not r.warnings for r in again)


def test_main(tmp_path, capsys):
    with pytest.raises(SystemExit, match="scripts dir missing"):
        rb.main(["--scripts", str(tmp_path / "none")])
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    with pytest.raises(SystemExit, match="no files match"):
        rb.main(["--scripts", str(scripts)])

    _xml(scripts / "t001.xml", [f"{TOKEN} hi", "Takane says hi"], extra=TOKEN)
    for i in range(12):
        (scripts / f"z{i:02d}.xml").write_text("<DBIN2", encoding="utf-8")
    out = tmp_path / "out"
    args = ["--scripts", str(scripts), "--out", str(out), "--vanilla-bin", str(tmp_path / "van")]
    assert rb.main(args) == 1
    text = capsys.readouterr().out
    assert "FAILED" in text and "warnings" in text and "plain Takane" in text
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["t_with_hero_token"] == 1 and report["t_with_plain_takane"] == 1

    assert rb.main(args + ["--verify-only", "--glob", "t*.xml"]) == 0
    assert "verify 1 xml" in capsys.readouterr().out
    assert rb.main(["--scripts", str(scripts), "--out", str(out), "--vanilla-bin", "", "--glob", "t*.xml"]) == 0


def test_unknown_entry_without_values_and_clean_main(tmp_path, capsys):
    scripts = tmp_path / "clean"
    scripts.mkdir()
    (scripts / "a001.xml").write_text(
        "<DBIN2 Key='1' Unknown='2'><Entries><Entry Unknown0='1' Unknown1='2'>"
        "<SDL2 Key='3'><Unknown><Entry><Value0>4</Value0><Value1>5</Value1></Entry></Unknown>"
        "<Dialogs><Dialog>hello</Dialog></Dialogs></SDL2></Entry></Entries></DBIN2>",
        encoding="utf-8",
    )
    _k, _u, entries = rb.xml_to_entries(scripts / "a001.xml")
    assert entries[0].sdl2.unknown[0].values == []
    assert rb.main(["--scripts", str(scripts), "--out", str(tmp_path / "o"), "--vanilla-bin", ""]) == 0
    assert "warnings" not in capsys.readouterr().out
