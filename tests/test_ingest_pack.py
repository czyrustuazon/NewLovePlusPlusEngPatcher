"""Volunteer Scripts packs splice changed lines onto XML and rebuild_dbin2."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import TOOLS, load_module

ingest = load_module("ingest_pack", TOOLS / "ingest_pack.py")
rebuild = load_module("rebuild_dbin2_from_xml", TOOLS / "rebuild_dbin2_from_xml.py")

XML = """<?xml version="1.0" encoding="utf-8"?>
<DBIN2 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" Key="1" Unknown="1">
  <Entries>
    <Entry Unknown0="1" Unknown1="2">
      <SDL2 Key="3">
        <Unknown>
          <Entry>
            <Values />
            <Value0>1</Value0>
            <Value1>2</Value1>
          </Entry>
        </Unknown>
        <Dialogs>
          <Dialog>○○○○○○○○</Dialog>
          <Dialog>こんにちは●▲苗字▲</Dialog>
          <Dialog>stay &amp; put</Dialog>
        </Dialogs>
      </SDL2>
    </Entry>
  </Entries>
</DBIN2>
""".replace("\n", "\r\n")


def _layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    scripts = tmp_path / "scripts"
    dbin_root = tmp_path / "rebuild_dbin2"
    scripts.mkdir()
    xml = scripts / "p001.xml"
    xml.write_bytes(XML.encode("utf-8"))
    key, unknown, entries = rebuild.xml_to_entries(xml)
    dest = dbin_root / "script" / "p001.dbin2"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(rebuild.build_dbin2(key, unknown, entries))
    return scripts, dbin_root, xml


def _pack(baseline: list[str], dialogs: list[str], *, dirty: bool = True) -> dict:
    return {
        "schema": 1,
        "kind": "nlpp-contrib",
        "author": "tester",
        "items": [
            {
                "kind": "script",
                "stem": "p001",
                "dirty": dirty,
                "baseline_dialogs": baseline,
                "dialogs": dialogs,
            }
        ],
    }


def _write_pack(tmp_path: Path, pack: dict) -> Path:
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
    return path


BASE = ["○○○○○○○○", "こんにちは●▲苗字▲", "stay & put"]


def test_dry_run_applies_only_a_baseline_match(tmp_path: Path, capsys):
    scripts, dbin_root, xml = _layout(tmp_path)
    before_xml = xml.read_bytes()
    before_dbin = (dbin_root / "script" / "p001.dbin2").read_bytes()
    dialogs = ["○○○○○○○○", "Hello ●▲苗字▲", "stay & put"]
    pack = _write_pack(tmp_path, _pack(BASE, dialogs))
    code = ingest.main(
        [str(pack), "--scripts", str(scripts), "--dbin-root", str(dbin_root)]
    )
    assert code == 0
    assert "apply 1" in capsys.readouterr().out
    assert xml.read_bytes() == before_xml
    assert (dbin_root / "script" / "p001.dbin2").read_bytes() == before_dbin


def test_apply_splices_xml_and_dbin_without_touching_other_lines(tmp_path: Path):
    scripts, dbin_root, xml = _layout(tmp_path)
    dialogs = ["○○○○○○○○", "Hello ●▲苗字▲\n\n", "stay & put"]
    pack = _write_pack(tmp_path, _pack(BASE, dialogs))
    code = ingest.main(
        [
            str(pack),
            "--apply",
            "--scripts",
            str(scripts),
            "--dbin-root",
            str(dbin_root),
        ]
    )
    assert code == 0
    raw = xml.read_bytes()
    assert b"stay &amp; put" in raw
    assert b"\r\n" in raw
    assert ingest._xml_dialogs(xml) == dialogs
    found = ingest._dbin_dialogs(dbin_root / "script" / "p001.dbin2")
    assert found[1] == "Hello ●▲苗字▲\n\n"
    assert found[0] == BASE[0]
    assert found[2] == "stay & put"


def test_existing_english_is_a_conflict_until_force(tmp_path: Path, capsys):
    scripts, dbin_root, xml = _layout(tmp_path)
    # Repo already moved off the Japanese baseline.
    ingest._write_xml_dialogs(xml, ["○○○○○○○○", "Hello there ●▲苗字▲", "stay & put"])
    key, unknown, entries = rebuild.xml_to_entries(xml)
    dbin = dbin_root / "script" / "p001.dbin2"
    dbin.write_bytes(rebuild.build_dbin2(key, unknown, entries))
    before = dbin.read_bytes()
    dialogs = ["○○○○○○○○", "Hi ●▲苗字▲", "stay & put"]
    pack = _write_pack(tmp_path, _pack(BASE, dialogs))
    code = ingest.main(
        [str(pack), "--apply", "--scripts", str(scripts), "--dbin-root", str(dbin_root)]
    )
    captured = capsys.readouterr().out
    assert code == 0
    assert "conflict 1" in captured
    assert "nothing to write" in captured
    assert dbin.read_bytes() == before

    code = ingest.main(
        [
            str(pack),
            "--apply",
            "--force",
            "--scripts",
            str(scripts),
            "--dbin-root",
            str(dbin_root),
        ]
    )
    assert code == 0
    assert ingest._dbin_dialogs(dbin)[1] == "Hi ●▲苗字▲"


def test_token_drop_and_locked_line_and_mark_drop_reject(tmp_path: Path, capsys):
    scripts, dbin_root, xml = _layout(tmp_path)
    before = xml.read_bytes()
    dropped = ["○○○○○○○○", "Hello ●", "stay & put"]
    pack = _write_pack(tmp_path, _pack(BASE, dropped))
    assert ingest.main(
        [str(pack), "--apply", "--scripts", str(scripts), "--dbin-root", str(dbin_root)]
    ) == 1
    assert xml.read_bytes() == before

    locked = ["???", "こんにちは●▲苗字▲", "stay & put"]
    pack = _write_pack(tmp_path, _pack(BASE, locked))
    assert ingest.main(
        [str(pack), "--apply", "--scripts", str(scripts), "--dbin-root", str(dbin_root)]
    ) == 1

    marked_base = ["○○○○○○○○", "注意※▲苗字▲", "stay & put"]
    marked = ["○○○○○○○○", "Careful ▲苗字▲", "stay & put"]
    # Current repo text must match this baseline for the check to be about marks,
    # but the mark check runs before the repo compare.
    ingest._write_xml_dialogs(xml, marked_base)
    pack = _write_pack(tmp_path, _pack(marked_base, marked))
    code = ingest.main(
        [str(pack), "--apply", "--scripts", str(scripts), "--dbin-root", str(dbin_root)]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "※ count dropped" in out
    assert "nothing written" in out


def test_pronoun_translated_away_applies_without_a_warning(tmp_path: Path, capsys):
    scripts, dbin_root, _xml = _layout(tmp_path)
    dialogs = ["○○○○○○○○", "Hello ▲苗字▲", "stay & put"]
    pack = _write_pack(tmp_path, _pack(BASE, dialogs))
    code = ingest.main(
        [str(pack), "--apply", "--scripts", str(scripts), "--dbin-root", str(dbin_root)]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "●" not in out
    assert ingest._dbin_dialogs(dbin_root / "script" / "p001.dbin2")[1] == "Hello ▲苗字▲"


def test_pronoun_left_in_a_translated_line_warns():
    errors, warnings = ingest._validate_pair(BASE, ["○○○○○○○○", "Hello ●▲苗字▲", "stay & put"])
    assert not errors
    assert warnings == ["● left in translated line(s) [1]: shows as 俺/僕; write I / me / my"]


def test_dbin_only_stem_gains_an_xml_source(tmp_path: Path):
    scripts, dbin_root, xml = _layout(tmp_path)
    xml.unlink()
    dialogs = ["○○○○○○○○", "Hello ●▲苗字▲", "stay & put"]
    pack = _write_pack(tmp_path, _pack(BASE, dialogs))
    code = ingest.main(
        [str(pack), "--apply", "--scripts", str(scripts), "--dbin-root", str(dbin_root)]
    )
    assert code == 0
    created = scripts / "p001.xml"
    assert created.is_file()
    assert ingest._xml_dialogs(created)[1] == "Hello ●▲苗字▲"
    assert ingest._dbin_dialogs(dbin_root / "script" / "p001.dbin2")[1] == "Hello ●▲苗字▲"


def test_wrong_kind_is_rejected(tmp_path: Path):
    pack = _write_pack(
        tmp_path,
        {"schema": 1, "kind": "nlpp-strings-contrib", "items": []},
    )
    assert ingest.main([str(pack)]) == 1


def test_clean_item_is_skipped(tmp_path: Path, capsys):
    scripts, dbin_root, _xml = _layout(tmp_path)
    pack = _write_pack(tmp_path, _pack(BASE, BASE, dirty=False))
    code = ingest.main(
        [str(pack), "--apply", "--scripts", str(scripts), "--dbin-root", str(dbin_root)]
    )
    assert code == 0
    assert "skipped" in capsys.readouterr().out


def test_gemini_stem_writes_a_separate_file(tmp_path: Path, capsys):
    gemini = tmp_path / "gemini"
    contrib = tmp_path / "script_contrib"
    scripts = tmp_path / "scripts"
    dbin_root = tmp_path / "rebuild_dbin2"
    scripts.mkdir()
    xml = tmp_path / "gemini_src.xml"
    xml.write_bytes(XML.encode("utf-8"))
    key, unknown, entries = rebuild.xml_to_entries(xml)
    blob = rebuild.build_dbin2(key, unknown, entries)
    for pack in ("script", "NLP_01"):
        dest = gemini / "dbin2" / pack / "a001.dbin2"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(blob)
    (gemini / "stems.json").write_text(
        json.dumps({"stems": ["a001"]}), encoding="utf-8"
    )
    before = {path: path.read_bytes() for path in gemini.rglob("*.dbin2")}

    dialogs = ["○○○○○○○○", "Hello ●▲苗字▲", "stay & put"]
    pack = {
        "schema": 1,
        "kind": "nlpp-contrib",
        "items": [
            {
                "kind": "script",
                "stem": "a001",
                "dirty": True,
                "baseline_dialogs": BASE,
                "dialogs": dialogs,
            }
        ],
    }
    pack_path = _write_pack(tmp_path, pack)
    code = ingest.main(
        [
            str(pack_path),
            "--apply",
            "--scripts",
            str(scripts),
            "--dbin-root",
            str(dbin_root),
            "--gemini-root",
            str(gemini),
            "--contrib-root",
            str(contrib),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Gemini translation" in out
    assert not (scripts / "a001.xml").exists()
    assert not any(dbin_root.rglob("*.dbin2"))
    for path, raw in before.items():
        assert path.read_bytes() == raw
    assert ingest._xml_dialogs(contrib / "xml" / "a001.xml") == dialogs
    assert ingest._dbin_dialogs(contrib / "dbin2" / "script" / "a001.dbin2") == dialogs
    assert ingest._dbin_dialogs(contrib / "dbin2" / "NLP_01" / "a001.dbin2") == dialogs


def test_gemini_proofread_applies_onto_the_machine_pass(tmp_path: Path, capsys):
    """Workbench baseline stays Japanese. Edits land on the Gemini text."""
    gemini = tmp_path / "gemini"
    contrib = tmp_path / "script_contrib"
    scripts = tmp_path / "scripts"
    dbin_root = tmp_path / "rebuild_dbin2"
    scripts.mkdir()
    machine = ["Good morning", "Hello ●▲苗字▲", "stay & put"]
    machine_xml = XML.replace("○○○○○○○○", machine[0]).replace(
        "こんにちは●▲苗字▲", machine[1]
    )
    xml = gemini / "xml" / "a001.xml"
    xml.parent.mkdir(parents=True)
    xml.write_bytes(machine_xml.encode("utf-8"))
    proposed = ["○○○○○○○○", "Hi ●▲苗字▲", "stay & put"]
    pack = {
        "schema": 1,
        "kind": "nlpp-contrib",
        "items": [
            {
                "kind": "script",
                "stem": "a001",
                "dirty": True,
                "baseline_dialogs": BASE,
                "dialogs": proposed,
            }
        ],
    }
    code = ingest.main(
        [
            str(_write_pack(tmp_path, pack)),
            "--apply",
            "--scripts",
            str(scripts),
            "--dbin-root",
            str(dbin_root),
            "--gemini-root",
            str(gemini),
            "--contrib-root",
            str(contrib),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "conflict 0" in out
    merged = ingest._xml_dialogs(contrib / "xml" / "a001.xml")
    assert merged[0] == "Good morning"
    assert merged[1] == "Hi ●▲苗字▲"
    assert merged[2] == "stay & put"
    assert xml.read_bytes() == machine_xml.encode("utf-8")
