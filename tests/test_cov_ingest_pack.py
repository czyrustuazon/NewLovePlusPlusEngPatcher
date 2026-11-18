"""Branch coverage for tools/ingest_pack.py: pack and tree errors, Gemini
branches, apply_plan layouts, and main()'s reporting.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from conftest import ROOT, TOOLS, load_module
from test_ingest_pack import BASE, _layout, _pack, _write_pack, ingest, rebuild

SRC = ROOT / "src"


def _plan(item, tmp_path: Path, *, scripts=None, dbin=None, contrib=None, gemini=None, force=False):
    return ingest.plan_item(
        item,
        scripts_dir=scripts or tmp_path / "scripts",
        dbin_root=dbin or tmp_path / "rebuild_dbin2",
        force=force,
        contrib_root=contrib or tmp_path / "contrib",
        gemini_root=gemini or tmp_path / "gemini",
    )


def _item(dialogs=None, baseline=None, stem="p001", **extra):
    return {"kind": "script", "stem": stem, "baseline_dialogs": baseline or list(BASE),
            "dialogs": dialogs or ["○○○○○○○○", "Hi ●▲苗字▲", "stay & put"], **extra}


def _dbin(path: Path, dialogs: list[str]) -> Path:
    xml = path.with_suffix(".xml")
    xml.parent.mkdir(parents=True, exist_ok=True)
    xml.write_bytes(ingest.entries_to_xml(*_entries(dialogs)).encode("utf-8"))
    key, unknown, entries = rebuild.xml_to_entries(xml)
    xml.unlink()
    path.write_bytes(rebuild.build_dbin2(key, unknown, entries))
    return path


def _entries(dialogs: list[str]):
    from patch_names import DbinEntry, SDL2Data

    return 1, 1, [DbinEntry(1, 2, SDL2Data(3, [], dialogs))]


# ---------------------------------------------------------------------------
# module + pack loading
# ---------------------------------------------------------------------------


def test_module_adds_src_and_tools_to_path(monkeypatch):
    keep = {str(SRC), str(TOOLS)}
    monkeypatch.setattr(sys, "path", [p for p in sys.path if str(Path(p).resolve()) not in keep])
    load_module("ingest_pack_fresh", TOOLS / "ingest_pack.py")
    assert str(SRC) in sys.path and str(TOOLS) in sys.path
    # tools/ already there, src/ not.
    monkeypatch.setattr(sys, "path", [p for p in sys.path if str(Path(p).resolve()) != str(SRC)])
    load_module("ingest_pack_fresh2", TOOLS / "ingest_pack.py")
    assert sys.path.count(str(TOOLS)) == 1


@pytest.mark.parametrize("text, msg", [
    ("{nope", "cannot read"),
    ("[]", "pack root must be an object"),
    ('{"schema": 2}', "schema must be 1"),
    ('{"schema": 1, "kind": "nlpp-contrib", "items": {}}', "items must be a list"),
])
def test_load_pack_errors(tmp_path, text, msg):
    path = tmp_path / "p.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ingest.IngestError, match=msg):
        ingest.load_pack(path)


def test_reader_errors(tmp_path):
    with pytest.raises(ingest.IngestError, match="must be a list of strings"):
        ingest._as_dialogs(["a", 1], "x")
    bad_xml = tmp_path / "b.xml"
    bad_xml.write_text("<DBIN2", encoding="utf-8")
    with pytest.raises(ingest.IngestError, match="XML parse error"):
        ingest._xml_dialogs(bad_xml)
    bad_dbin = tmp_path / "b.dbin2"
    bad_dbin.write_bytes(b"nope")
    with pytest.raises(ingest.IngestError, match="b.dbin2"):
        ingest._dbin_dialogs(bad_dbin)


def test_dbin_paths_finds_extra_pack_folders(tmp_path):
    root = tmp_path / "d"
    _dbin(root / "script" / "p001.dbin2", BASE)
    _dbin(root / "zz_extra" / "p001.dbin2", BASE)
    assert [p.parent.name for p in ingest._dbin_paths(root, "p001")] == ["script", "zz_extra"]


def test_validate_pair_count_and_mark_rise():
    errors, _w = ingest._validate_pair(["a"], ["a", "b"])
    assert errors and "dialog count" in errors[0]
    _e, warnings = ingest._validate_pair(["x"], ["x ▼"])
    assert any("▼ count rose 0 -> 1" in w for w in warnings)


def test_gemini_translated_ignores_a_bad_manifest(tmp_path):
    (tmp_path / "stems.json").write_text("{bad", encoding="utf-8")
    assert ingest.gemini_translated("a001", tmp_path) is False


# ---------------------------------------------------------------------------
# plan_item
# ---------------------------------------------------------------------------


def test_plan_rejects_bad_items(tmp_path):
    assert _plan("x", tmp_path).errors == ["item is not an object"]
    assert "kind must be" in _plan(_item(kind="sms"), tmp_path).errors[0]
    assert "is not an a/k/t/p" in _plan(_item(stem="z1"), tmp_path).errors[0]
    assert "must be a list" in _plan({"stem": "p001", "baseline_dialogs": "x"}, tmp_path).errors[0]
    assert "no p001.xml and no p001.dbin2" in _plan(_item(), tmp_path).errors[0]


def test_plan_reports_repo_errors(tmp_path):
    scripts, dbin_root, xml = _layout(tmp_path)
    # XML exists but is broken.
    xml.write_text("<DBIN2", encoding="utf-8")
    assert "XML parse error" in _plan(_item(), tmp_path, scripts=scripts, dbin=dbin_root).errors[0]
    # No XML; the only dbin2 is broken.
    xml.unlink()
    (dbin_root / "script" / "p001.dbin2").write_bytes(b"bad")
    assert _plan(_item(), tmp_path, scripts=scripts, dbin=dbin_root).errors
    # No XML; a good dbin2 plus a broken one in another pack.
    _dbin(dbin_root / "script" / "p001.dbin2", BASE)
    (dbin_root / "NLP_01").mkdir()
    (dbin_root / "NLP_01" / "p001.dbin2").write_bytes(b"bad")
    assert _plan(_item(), tmp_path, scripts=scripts, dbin=dbin_root).errors
    # Two dbin2 that disagree.
    _dbin(dbin_root / "NLP_01" / "p001.dbin2", ["x", "y", "z"])
    errors = _plan(_item(), tmp_path, scripts=scripts, dbin=dbin_root).errors
    assert any("does not match" in e for e in errors)
    # Repo has a different dialog count than the pack baseline.
    _dbin(dbin_root / "NLP_01" / "p001.dbin2", BASE)
    _dbin(dbin_root / "script" / "p001.dbin2", BASE)
    short = _item(baseline=["○○○○○○○○", "x"], dialogs=["○○○○○○○○", "y"])
    assert "repo dialog count" in _plan(short, tmp_path, scripts=scripts, dbin=dbin_root).errors[0]


def test_plan_already_applied_line(tmp_path):
    scripts, dbin_root, xml = _layout(tmp_path)
    proposed = ["○○○○○○○○", "Hi ●▲苗字▲", "stay & put"]
    ingest._write_xml_dialogs(xml, proposed)
    key, unknown, entries = rebuild.xml_to_entries(xml)
    (dbin_root / "script" / "p001.dbin2").write_bytes(rebuild.build_dbin2(key, unknown, entries))
    plan = _plan(_item(dialogs=proposed), tmp_path, scripts=scripts, dbin=dbin_root)
    assert [d.action for d in plan.decisions] == ["already"]


def _gemini(tmp_path: Path, *, xml: bool = True, dbin: bool = False, stem="a001") -> Path:
    gem = tmp_path / "gemini"
    (gem / "xml").mkdir(parents=True, exist_ok=True)
    if xml:
        (gem / "xml" / f"{stem}.xml").write_bytes(ingest.entries_to_xml(*_entries(list(BASE))).encode("utf-8"))
    if dbin:
        _dbin(gem / "dbin2" / "script" / f"{stem}.dbin2", BASE)
    return gem


def test_plan_gemini_branches(tmp_path):
    item = _item(stem="a001")
    gem = _gemini(tmp_path, xml=False, dbin=True)
    contrib = tmp_path / "contrib"
    # Contributor tree already exists but its dbin2 disagrees with the XML.
    (contrib / "xml").mkdir(parents=True)
    (contrib / "xml" / "a001.xml").write_bytes(ingest.entries_to_xml(*_entries(list(BASE))).encode("utf-8"))
    _dbin(contrib / "dbin2" / "script" / "a001.dbin2", ["q", "r", "s"])
    assert any("does not match" in e for e in _plan(item, tmp_path, gemini=gem, contrib=contrib).errors)
    # Contributor XML that does not parse.
    (contrib / "xml" / "a001.xml").write_text("<DBIN2", encoding="utf-8")
    assert "XML parse error" in _plan(item, tmp_path, gemini=gem, contrib=contrib).errors[0]

    # No contributor tree: branch from the Gemini dbin2 (the shell).
    fresh = tmp_path / "contrib2"
    plan = _plan(item, tmp_path, gemini=gem, contrib=fresh)
    assert not plan.errors and plan.shells and plan.source_xml is None
    # A broken extra Gemini dbin2 is an error.
    (gem / "dbin2" / "zz").mkdir()
    (gem / "dbin2" / "zz" / "a001.dbin2").write_bytes(b"bad")
    gem_xml = _gemini(tmp_path, xml=True)
    scripts = tmp_path / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "a001.xml").write_bytes(ingest.entries_to_xml(*_entries(list(BASE))).encode("utf-8"))
    assert _plan(item, tmp_path, gemini=gem_xml, contrib=fresh, scripts=scripts).errors

    # Branched tree whose dbin2 disagree.
    gem2 = tmp_path / "gem2"
    (gem2 / "xml").mkdir(parents=True)
    (gem2 / "xml" / "a001.xml").write_bytes(ingest.entries_to_xml(*_entries(list(BASE))).encode("utf-8"))
    _dbin(gem2 / "dbin2" / "script" / "a001.dbin2", ["q", "r", "s"])
    no_scripts = tmp_path / "noscripts"
    errors = _plan(item, tmp_path, gemini=gem2, contrib=tmp_path / "c3", scripts=no_scripts).errors
    assert any("does not match" in e for e in errors)

    # An existing contributor tree that agrees is the one written.
    good = tmp_path / "c5"
    (good / "xml").mkdir(parents=True)
    (good / "xml" / "a001.xml").write_bytes(ingest.entries_to_xml(*_entries(list(BASE))).encode("utf-8"))
    _dbin(good / "dbin2" / "script" / "a001.dbin2", BASE)
    plan = _plan(item, tmp_path, gemini=gem2, contrib=good)
    assert not plan.errors and plan.xml_path == good / "xml" / "a001.xml"

    # Gemini-translated per the manifest, but no script anywhere.
    gem3 = tmp_path / "gem3"
    gem3.mkdir()
    (gem3 / "stems.json").write_text(json.dumps({"stems": ["a001"]}), encoding="utf-8")
    errors = _plan(item, tmp_path, gemini=gem3, contrib=tmp_path / "c4", scripts=no_scripts).errors
    assert "no a001 script" in errors[0]


# ---------------------------------------------------------------------------
# writers + apply_plan
# ---------------------------------------------------------------------------


def test_writer_guards(tmp_path):
    with pytest.raises(ingest.IngestError, match="Dialog tag"):
        ingest._escape_dialog("a</Dialog>")
    scripts, dbin_root, xml = _layout(tmp_path)
    with pytest.raises(ingest.IngestError, match="found 3 <Dialog> tags"):
        ingest._write_xml_dialogs(xml, ["a"])
    with pytest.raises(ingest.IngestError, match="dialog count changed"):
        ingest._write_dbin_dialogs(dbin_root / "script" / "p001.dbin2", ["a"])


def test_apply_plan_layouts(tmp_path):
    assert ingest.apply_plan(ingest.ItemPlan(stem="p001")) == []
    scripts, dbin_root, xml = _layout(tmp_path)
    decision = ingest.LineDecision(1, "apply", BASE[1], BASE[1], "Hi ●▲苗字▲")

    # Copy a source XML into a destination that already has one; no dbin root.
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "p001.xml").write_bytes(xml.read_bytes())
    plan = ingest.ItemPlan(stem="p001", decisions=[decision], source_xml=xml, dest_scripts=dest,
                           current=list(BASE))
    assert ingest.apply_plan(plan) == [dest / "p001.xml"]

    # XML in the repo, no dbin2 yet: one is built under script/.
    plan = ingest.ItemPlan(stem="p001", decisions=[decision], xml_path=xml,
                           dest_dbin_root=tmp_path / "newdbin", current=list(BASE))
    written = ingest.apply_plan(plan)
    assert tmp_path / "newdbin" / "script" / "p001.dbin2" in written

    # Shells with a repo XML: no second XML is generated.
    shell = dbin_root / "script" / "p001.dbin2"
    plan = ingest.ItemPlan(stem="p001", decisions=[decision], xml_path=xml, shells=[shell],
                           dest_dbin_root=tmp_path / "shelled", dest_scripts=dest, current=list(BASE))
    assert tmp_path / "shelled" / "script" / "p001.dbin2" in ingest.apply_plan(plan)

    # dbin2 only, and the destination XML already exists: left as is.
    plan = ingest.ItemPlan(stem="p001", decisions=[decision], dbin_paths=[shell], dest_scripts=dest,
                           current=list(BASE))
    assert dest / "p001.xml" not in ingest.apply_plan(plan)


# ---------------------------------------------------------------------------
# main / printing
# ---------------------------------------------------------------------------


def test_short_and_stdio():
    assert ingest._short("x" * 100, 10) == "xxxxxxx..."

    class _NoReconf:
        pass

    class _Bad:
        def reconfigure(self, **k):
            raise ValueError("closed")

    real = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = _NoReconf(), _Bad()
        ingest._configure_stdio()
    finally:
        sys.stdout, sys.stderr = real


def test_main_reporting(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ingest, "_configure_stdio", lambda: None)
    scripts, dbin_root, xml = _layout(tmp_path)
    args = ["--scripts", str(scripts), "--dbin-root", str(dbin_root),
            "--contrib-root", str(tmp_path / "c"), "--gemini-root", str(tmp_path / "g")]

    empty = _write_pack(tmp_path, {"schema": 1, "kind": "nlpp-contrib", "note": "n" * 200, "items": []})
    assert ingest.main([str(empty)] + args) == 0
    out = capsys.readouterr().out
    assert "note:" in out and "no items" in out

    # 45 changed lines: the report stops after 40.
    base = [f"行{i}" for i in range(45)]
    many = [f"line {i}" for i in range(45)]
    _dbin(dbin_root / "script" / "t050.dbin2", base)
    pack = {"schema": 1, "kind": "nlpp-contrib", "items": [_item(dialogs=many, baseline=base, stem="t050")]}
    assert ingest.main([str(_write_pack(tmp_path, pack))] + args) == 0
    assert "... 5 more" in capsys.readouterr().out

    pack = _write_pack(tmp_path, _pack(BASE, ["○○○○○○○○", "Hi ●▲苗字▲", "stay & put"]))
    monkeypatch.setattr(ingest, "apply_plan", lambda plan: (_ for _ in ()).throw(OSError("disk full")))
    assert ingest.main([str(pack), "--apply"] + args) == 1
    assert "write failed: disk full" in capsys.readouterr().out
